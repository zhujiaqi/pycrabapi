"""
Logger implementation loosely modeled on PEP 282.  We don't use the
PEP 282 logger implementation in the stdlib ('logging') because it's
idiosyncratic and a bit slow for our purposes (we don't use threads).
"""

# This module must not depend on any non-stdlib modules to
# avoid circular import problems

import os
import re
import sys
import time
import errno
import traceback
import subprocess

from stat import ST_MTIME
from random import randint

try:
    import syslog
except ImportError:
    # only required when 'syslog' is specified as the log filename
    pass

from portalocker import lock, unlock, LOCK_EX, LOCK_NB, LockException

# A client can set this to true to automatically convert relative paths to
# absolute paths (which will also hide the absolute path warnings)
FORCE_ABSOLUTE_PATH = False

_MIDNIGHT = 24 * 60 * 60

if hasattr(sys, 'frozen'): #support for py2exe
    _srcfile = "logging%s__init__%s" % (os.sep, __file__[-4:])
elif __file__[-4:].lower() in ['.pyc', '.pyo']:
    _srcfile = __file__[:-4] + '.py'
else:
    _srcfile = __file__
_srcfile = os.path.normcase(_srcfile)

def currentFrame():
    """Return the frame object for the caller's stack frame."""
    try:
        raise Exception
    except:
        return sys.exc_info()[2].tb_frame.f_back

if hasattr(sys, '_getframe'): currentframe = lambda: sys._getframe(3)

class LevelsByName:
    CRIT = 50   # messages that probably require immediate user attention
    ERRO = 40   # messages that indicate a potentially ignorable error condition
    WARN = 30   # messages that indicate issues which aren't errors
    INFO = 20   # normal informational output
    DEBG = 10   # messages useful for users trying to debug configurations
    TRAC = 5    # messages useful to developers trying to debug plugins
    BLAT = 3    # messages useful for developers trying to debug supervisor

class LevelsByDescription:
    critical = LevelsByName.CRIT
    error = LevelsByName.ERRO
    warn = LevelsByName.WARN
    info = LevelsByName.INFO
    debug = LevelsByName.DEBG
    trace = LevelsByName.TRAC
    blather = LevelsByName.BLAT

def _levelNumbers():
    bynumber = {}
    for name, number in LevelsByName.__dict__.items():
        if not name.startswith('_'):
            bynumber[number] = name
    return bynumber

LOG_LEVELS_BY_NUM = _levelNumbers()

def getLevelNumByDescription(description):
    num = getattr(LevelsByDescription, description, None)
    return num

def FileIsOpen(fname):
    if not os.path.isabs(fname):
        fname = os.path.abspath(fname)

    processes = filter(str.isdigit, os.listdir('/proc'))
    for process in processes:
        try:
            fds = os.listdir('/proc/%s/fd' % process)
        except OSError as ex:
            if ex.errno in (2, 13):
                continue
            else:
                raise

        for fd in fds:
            fdpath = '/proc/%s/fd/%s' % (process, fd)
            try:
                if os.readlink(fdpath) == fname:
                    return True
            except OSError as ex:
                if ex.errno in (2, 13, 22):
                    continue
                else:
                    raise
    else:
        return False

class Handler:
    fmt = '%(message)s'
    level = LevelsByName.INFO
    def setFormat(self, fmt):
        self.fmt = fmt

    def setLevel(self, level):
        self.level = level

    def flush(self):
        try:
            self.stream.flush()
        except IOError, why:
            # if supervisor output is piped, EPIPE can be raised at exit
            if why[0] != errno.EPIPE:
                raise

    def close(self):
        if hasattr(self.stream, 'fileno'):
            fd = self.stream.fileno()
            if fd < 3: # don't ever close stdout or stderr
                return
        self.stream.close()

    def emit(self, record):
        try:
            msg = self.fmt % record.asdict()
            try:
                self.stream.write(msg)
            except UnicodeError:
                self.stream.write(msg.encode("UTF-8"))
            self.flush()
        except:
            self.handleError(record)

    def handleError(self, record):
        ei = sys.exc_info()
        traceback.print_exception(ei[0], ei[1], ei[2], None, sys.stderr)
        del ei

class FileHandler(Handler):
    """File handler which supports reopening of logs.
    """

    def __init__(self, filename, mode="a"):
        self.stream = open(filename, mode, 0)
        self.baseFilename = filename
        self.mode = mode

    def reopen(self):
        self.close()
        self.stream = open(self.baseFilename, self.mode, 0)

    def remove(self):
        try:
            os.remove(self.baseFilename)
        except OSError, why:
            if why[0] != errno.ENOENT:
                raise

class StreamHandler(Handler):
    def __init__(self, strm=None):
        self.stream = strm

    def remove(self):
        if hasattr(self.stream, 'clear'):
            self.stream.clear()

    def reopen(self):
        pass

class BoundIO:
    def __init__(self, maxbytes, buf=''):
        self.maxbytes = maxbytes
        self.buf = buf

    def flush(self):
        pass

    def close(self):
        self.clear()

    def write(self, s):
        slen = len(s)
        if len(self.buf) + slen > self.maxbytes:
            self.buf = self.buf[slen:]
        self.buf += s

    def getvalue(self):
        return self.buf

    def clear(self):
        self.buf = ''

class RotatingFileHandler(FileHandler):
    def __init__(self, filename, mode='a', maxBytes=512*1024*1024,
                 backupCount=10):
        """
        Open the specified file and use it as the stream for logging.

        By default, the file grows indefinitely. You can specify particular
        values of maxBytes and backupCount to allow the file to rollover at
        a predetermined size.

        Rollover occurs whenever the current log file is nearly maxBytes in
        length. If backupCount is >= 1, the system will successively create
        new files with the same pathname as the base file, but with extensions
        ".1", ".2" etc. appended to it. For example, with a backupCount of 5
        and a base file name of "app.log", you would get "app.log",
        "app.log.1", "app.log.2", ... through to "app.log.5". The file being
        written to is always "app.log" - when it gets filled up, it is closed
        and renamed to "app.log.1", and if files "app.log.1", "app.log.2" etc.
        exist, then they are renamed to "app.log.2", "app.log.3" etc.
        respectively.

        If maxBytes is zero, rollover never occurs.
        """
        if maxBytes > 0:
            mode = 'a' # doesn't make sense otherwise!
        FileHandler.__init__(self, filename, mode)
        self.maxBytes = maxBytes
        self.backupCount = backupCount
        self.counter = 0
        self.every = 10

    def emit(self, record):
        """
        Emit a record.

        Output the record to the file, catering for rollover as described
        in doRollover().
        """
        if self.shouldRollover(record):
            self.doRollover()
        FileHandler.emit(self, record)

    def shouldRollover(self, record):
        if self.maxBytes <= 0:
            return False

        if not (self.stream.tell() >= self.maxBytes):
            return False

        return True

    def doRollover(self):
        """
        Do a rollover, as described in __init__().
        """

        self.stream.close()
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = "%s.%d" % (self.baseFilename, i)
                dfn = "%s.%d" % (self.baseFilename, i + 1)
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        try:
                            os.remove(dfn)
                        except OSError, why:
                            # catch race condition (already deleted)
                            if why[0] != errno.ENOENT:
                                raise
                    os.rename(sfn, dfn)
            dfn = self.baseFilename + ".1"
            if os.path.exists(dfn):
                try:
                    os.remove(dfn)
                except OSError, why:
                    # catch race condition (already deleted)
                    if why[0] != errno.ENOENT:
                        raise
            os.rename(self.baseFilename, dfn)
        self.stream = open(self.baseFilename, 'w', 0)

class MyRotatingFileHandler(RotatingFileHandler):
    def __init__(self, filename, mode='a', maxBytes=0, when='h', interval=1,
                 backupCount=0, supress_abs_warn=False):
        if not os.path.isabs(filename):
            if FORCE_ABSOLUTE_PATH or \
               not os.path.split(filename)[0]:
                filename = os.path.abspath(filename)
            elif not supress_abs_warn:
                from warnings import warn
                warn("The given 'filename' should be an absolute path.  If your "
                     "application calls os.chdir(), your logs may get messed up. "
                     "Use 'supress_abs_warn=True' to hide this message.")

        rollFilename = "/.".join(os.path.split(filename))
        RotatingFileHandler.__init__(self, filename, mode)
        
        self.maxBytes = maxBytes
        self.backupCount = backupCount
        # Prevent multiple extensions on the lock file (Only handles the normal "*.log" case.)
        if filename.endswith(".log"):
            lock_file = filename[:-4]
            roll_file = rollFilename[:-4]
        else:
            lock_file = filename
            roll_file = rollFilename

        self.rollFile = roll_file + ".rollat"
        self.rollFileHandle = None
        self.stream_lock = open(lock_file + ".lock", "w")
        
        self.when = when.upper()

        if self.when == 'S':
            self.interval = 1 # one second
            self.suffix = "%Y-%m-%d_%H-%M-%S"
            self.extMatch = r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.\d+$"
        elif self.when == 'M':
            self.interval = 60 # one minute
            self.suffix = "%Y-%m-%d_%H-%M"
            self.extMatch = r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.\d+$"
        elif self.when == 'H':
            self.interval = 60 * 60 # one hour
            self.suffix = "%Y-%m-%d_%H"
            self.extMatch = r"^\d{4}-\d{2}-\d{2}_\d{2}\.\d+$"
        elif self.when == 'D' or self.when == 'MIDNIGHT':
            self.interval = 60 * 60 * 24 # one day
            self.suffix = "%Y-%m-%d"
            self.extMatch = r"^\d{4}-\d{2}-\d{2}\.\d+$"
        #elif self.when.startswith('W'):
        #    self.interval = 60 * 60 * 24 * 7 # one week
        #    if len(self.when) != 2:
        #        raise ValueError("You must specify a day for weekly rollover from 0 to 6 (0 is Monday): %s" % self.when)
        #    if self.when[1] < '0' or self.when[1] > '6':
        #        raise ValueError("Invalid day specified for weekly rollover: %s" % self.when)
        #    self.dayOfWeek = int(self.when[1])
        #    self.suffix = "%Y-%m-%d"
        #    self.extMatch = r"^\d{4}-\d{2}-\d{2}\.\d+$"
        else:
            raise ValueError("Invalid rollover interval specified: %s" % self.when)

        self.extMatch = re.compile(self.extMatch)
        self.interval = self.interval * interval # multiply by units requested
        self.dev = None
        self.inode = None

        self.rolloverAt = None

        if os.path.exists(filename):
            t = os.stat(filename)[ST_MTIME]
        else:
            t = int(time.time())

        self.acquire()

        if os.path.exists(self.rollFile) and self.rollFileIsOpen():
            self.rolloverAt = os.stat(self.rollFile)[ST_MTIME]

        self.rollFileHandle = open(self.rollFile, 'a')
        if self.rolloverAt is None:
            self.rolloverAt = self.computeRollover(t)
            self.updateRolloverAt(self.rolloverAt)

        self.release()

        self.toDoTimedRollover = False
        self.toDoSizedRollover = False

    def rollFileIsOpen(self):
        return FileIsOpen(self.rollFile)

    def updateRolloverAt(self, rolloverAt):
        #now = int(time.time())
        #if now > rolloverAt:
        #    print 'now > rolloverAt, %d > %d' %(now, rolloverAt)
        #    multiple = (now - rolloverAt) / self.interval
        #    if multiple > 0:
        #        rolloverAt += self.interval * multiple
        #        print '     adjust rolloverAt, %d += %d * %d' % (rolloverAt, self.interval, multiple)
        os.utime(self.rollFile, (rolloverAt, rolloverAt))
        #self.rolloverAt = rolloverAt

    def computeRollover(self, currentTime):
        result = currentTime + self.interval
        # If we are rolling over at midnight or weekly, then the interval is already known.
        # What we need to figure out is WHEN the next interval is.  In other words,
        # if you are rolling over at midnight, then your base interval is 1 day,
        # but you want to start that one day clock at midnight, not now.  So, we
        # have to fudge the rolloverAt value in order to trigger the first rollover
        # at the right time.  After that, the regular interval will take care of
        # the rest.  Note that this code doesn't care about leap seconds. :)
        if self.when == 'MIDNIGHT': # or self.when.startswith('W'):
            # This could be done with less code, but I wanted it to be clear
            t = time.localtime(currentTime)
            currentHour = t[3]
            currentMinute = t[4]
            currentSecond = t[5]
            # r is the number of seconds left between now and midnight
            r = _MIDNIGHT - ((currentHour * 60 + currentMinute) * 60 + currentSecond)
            result = currentTime + r
            # If we are rolling over on a certain day, add in the number of days until
            # the next rollover, but offset by 1 since we just calculated the time
            # until the next day starts.  There are three cases:
            # Case 1) The day to rollover is today; in this case, do nothing
            # Case 2) The day to rollover is further in the interval (i.e., today is
            #         day 2 (Wednesday) and rollover is on day 6 (Sunday).  Days to
            #         next rollover is simply 6 - 2 - 1, or 3.
            # Case 3) The day to rollover is behind us in the interval (i.e., today
            #         is day 5 (Saturday) and rollover is on day 3 (Thursday).
            #         Days to rollover is 6 - 5 + 3, or 4.  In this case, it's the
            #         number of days left in the current week (1) plus the number
            #         of days in the next week until the rollover day (3).
            # The calculations described in 2) and 3) above need to have a day added.
            # This is because the above time calculation takes us to midnight on this
            # day, i.e. the start of the next day.
            #if self.when.startswith('W'):
            #    day = t[6] # 0 is Monday
            #    if day != self.dayOfWeek:
            #        if day < self.dayOfWeek:
            #            daysToWait = self.dayOfWeek - day
            #        else:
            #            daysToWait = 6 - day + self.dayOfWeek + 1
            #        newRolloverAt = result + (daysToWait * (60 * 60 * 24))
            #        dstNow = t[-1]
            #        dstAtRollover = time.localtime(newRolloverAt)[-1]
            #        if dstNow != dstAtRollover:
            #            if not dstNow:  # DST kicks in before next rollover, so we need to deduct an hour
            #                newRolloverAt = newRolloverAt - 3600
            #            else:           # DST bows out before next rollover, so we need to add an hour
            #                newRolloverAt = newRolloverAt + 3600
            #        result = newRolloverAt
        return result

    def getFilesToRename(self, rolloverAt):
        dirName, baseName = os.path.split(self.baseFilename)
        fileNames = os.listdir(dirName)
        result = []
        prefix = baseName + "."
        plen = len(prefix)
        timeTuple = time.localtime(rolloverAt)
        match = time.strftime(self.suffix, timeTuple)

        for fileName in fileNames:
            if fileName[:plen] == prefix:
                suffix = fileName[plen:].split(".")[0]
                #if self.extMatch.match(suffix):
                if match == suffix:
                    result.append(os.path.join(dirName, fileName))

        def key_func(x):
            r = x.split('.')[-1]
            return r
        def cmp_func(x, y):
            return cmp(int(x), int(y))
        return sorted(result, cmp=cmp_func, key=key_func)

    def getFilesToDelete(self):
        """
        Determine the files to delete when rolling over.

        More specific than the earlier method, which just used glob.glob().
        """
        dirName, baseName = os.path.split(self.baseFilename)
        fileNames = os.listdir(dirName)
        result = []
        prefix = baseName + "."
        plen = len(prefix)
        for fileName in fileNames:
            if fileName[:plen] == prefix:
                suffix = fileName[plen:]
                if self.extMatch.match(suffix):
                    result.append(os.path.join(dirName, fileName))

        def key_func(x):
            date, number = x.split('.')[-2:]
            return date, number
        def cmp_func(x, y):
            xts = time.mktime(time.strptime(x[0], self.suffix))
            yts = time.mktime(time.strptime(y[0], self.suffix))
            xn = int(x[1])
            yn = int(y[1])
            if xts < yts:
                return 1
            elif xts > yts:
                return -1
            else:
                if xn < yn:
                    return -1
                elif xn > yn:
                    return 1
            return 0
        result = sorted(result, cmp=cmp_func, key=key_func, reverse=True)

        if len(result) < self.backupCount:
            result = []
        else:
            result = result[:len(result) - self.backupCount]
        return result

    def doTimedRollover(self):
        self.stream.flush()
        empty = os.path.getsize(self.baseFilename) == 0

        #if self.stream:
        #    self.stream.close()
        #    self.stream = None

        if not empty:
            if self.stream:
                self.stream.close()
                self.stream = None
            self.renameFiles(self.rolloverAt-self.interval)

        if self.stream is None:
            self._openFile(self.mode)

        currentTime = self.rolloverAt
        now = int(time.time())
        if now > currentTime:
            #print 'now > currentTime, %d > %d' %(now, currentTime)
            multiple = (now - currentTime) / self.interval
            if multiple > 0:
                currentTime = currentTime + self.interval * multiple
                #print '     adjust rolloverAt, %d += %d * %d' % (currentTime, self.interval, multiple)

        newRolloverAt = self.computeRollover(currentTime)
        while newRolloverAt <= currentTime:
            newRolloverAt = newRolloverAt + self.interval
        #If DST changes and midnight or weekly rollover, adjust for this.
        if self.when == 'MIDNIGHT': # or self.when.startswith('W'):
            dstNow = time.localtime(currentTime)[-1]
            dstAtRollover = time.localtime(newRolloverAt)[-1]
            if dstNow != dstAtRollover:
                if not dstNow:  # DST kicks in before next rollover, so we need to deduct an hour
                    newRolloverAt = newRolloverAt - 3600
                else:           # DST bows out before next rollover, so we need to add an hour
                    newRolloverAt = newRolloverAt + 3600

        self.rolloverAt = newRolloverAt
        self.updateRolloverAt(self.rolloverAt)

        files = self.getFilesToDelete()
        for f in files:
            os.remove(f)

    def doSizedRollover(self):
        if self.backupCount <= 0:
            # Don't keep any backups, just overwrite the existing backup file
            # Locking doesn't much matter here; since we are overwriting it anyway
            self.stream.close()
            self._openFile(self.mode)
            return
        self.stream.close()
        try:
            # Attempt to rename logfile to tempname:  There is a slight race-condition here, but it seems unavoidable
            self.renameFiles(self.rolloverAt-self.interval)    
        finally:
            self._openFile(self.mode)

        files = self.getFilesToDelete()
        for f in files:
            os.remove(f)

    def renameFiles(self, timeStamp):
        tmpname = None
        while not tmpname or os.path.exists(tmpname):
            tmpname = "%s.rotate.%08d" % (self.baseFilename, randint(0,99999999))

        os.rename(self.baseFilename, tmpname)
        
        # Q: Is there some way to protect this code from a KeboardInterupt?
        # This isn't necessarily a data loss issue, but it certainly would
        # break the rotation process during my stress testing.
        
        # There is currently no mechanism in place to handle the situation
        # where one of these log files cannot be renamed. (Example, user
        # opens "logfile.3" in notepad)
        filesToRename = self.getFilesToRename(self.rolloverAt - self.interval)
        timeTuple = time.localtime(self.rolloverAt - self.interval)
        if len(filesToRename) > 1:
            suffixNumber = len(filesToRename) + 1
            dfn = "".join([self.baseFilename, ".", time.strftime(self.suffix, timeTuple), ".",  str(suffixNumber)])
            os.rename(filesToRename[-1], dfn)

            filesToRename.reverse()
            for dfn, sfn in zip(filesToRename[:-1], filesToRename[1:]):
                os.rename(sfn, dfn)

        dfn = "".join([self.baseFilename, ".", time.strftime(self.suffix, timeTuple), ".1"])
        if os.path.exists(dfn):
            sfn = dfn
            dfn = "".join([self.baseFilename, ".", time.strftime(self.suffix, timeTuple), ".2"])
            os.rename(sfn, dfn)
            dfn = sfn
        os.rename(tmpname, dfn)

    def _openFile(self, mode):
        self.stream = open(self.baseFilename, mode)
        s = os.fstat(self.stream.fileno())
        self.dev = s.st_dev
        self.inode = s.st_ino
    
    def acquire(self):
        lock(self.stream_lock, LOCK_EX)
        if self.stream.closed:
            self._openFile(self.mode)
    
    def release(self):
        try:
            self.stream.flush()
        finally:
            unlock(self.stream_lock)
    
    def close(self):
        """
        Closes the stream.
        """
        if not self.stream.closed:
            self.stream.flush()
            self.stream.close()
    
    def flush(self):
        """ flush():  Do nothing.

        Since a flush is issued in release(), we don't do it here. To do a flush
        here, it would be necessary to re-lock everything, and it is just easier
        and cleaner to do it all in release(), rather than requiring two lock
        ops per handle() call.

        Doing a flush() here would also introduces a window of opportunity for
        another process to write to the log file in between calling
        stream.write() and stream.flush(), which seems like a bad thing. """
        pass

    def fileMoved(self):
        s = os.stat(self.baseFilename)
        return s.st_dev != self.dev or s.st_ino != self.inode

    def shouldTimedRollover(self, record):
        if self.fileMoved():
            self.stream.close()
            self._openFile(self.mode)

        #if not os.path.getsize(self.baseFilename) > 0:
        #    return False

        self.rolloverAt = os.stat(self.rollFile)[ST_MTIME]
        t = int(time.time())
        return t >= self.rolloverAt

    #def _shouldTimedRollover(self, record):
    #    return os.stat(self.baseFilename)[ST_MTIME] >= self.rolloverAt

    def shouldSizedRollover(self, record):
        del record  # avoid pychecker warnings
        if self._shouldSizedRollover():
            # if some other process already did the rollover we might
            # checked log.1, so we reopen the stream and check again on
            # the right log file
            self.stream.close()
            self._openFile(self.mode)
            return self._shouldSizedRollover()
        return False
    
    def _shouldSizedRollover(self):
        if self.maxBytes > 0:                   # are we rolling over?
            self.stream.seek(0, 2)  #due to non-posix-compliant Windows feature
            if self.stream.tell() >= self.maxBytes:
                return True
        return False

    def shouldRollover(self, record):
        self.toDoTimedRollover = self.shouldTimedRollover(record)
        self.toDoSizedRollover = self.shouldSizedRollover(record)
        return self.toDoTimedRollover or self.toDoSizedRollover

    def doRollover(self):
        if self.toDoTimedRollover:
            self.doTimedRollover()
            self.toDoTimedRollover = False
            self.toDoSizedRollover = False
            return

        if self.toDoSizedRollover:
            self.doSizedRollover()
            self.toDoSizedRollover = False

class LogRecord:
    def __init__(self, level, msg, **kw):
        self.level = level
        self.msg = msg
        self.kw = kw
        self.dictrepr = None

    def asdict(self):
        if self.dictrepr is None:
            now = time.time()
            msecs = (now - long(now)) * 1000
            part1 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
            asctime = '%s,%03d' % (part1, msecs)
            levelname = LOG_LEVELS_BY_NUM[self.level]
            if self.kw:
                msg = self.msg % self.kw
            else:
                msg = self.msg
            self.dictrepr = {'message':msg, 'levelname':levelname,
                             'asctime':asctime}
        return self.dictrepr

class MyLogRecord:
    def __init__(self, level, filename, lineno, function, msg, **kw):
        self.level = level
        self.filename = filename
        self.lineno = lineno
        self.function = function
        self.msg = msg
        self.kw = kw
        self.dictrepr = None

    def asdict(self):
        if self.dictrepr is None:
            now = time.time()
            msecs = (now - long(now)) * 1000
            part1 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
            asctime = '%s,%03d' % (part1, msecs)
            levelname = LOG_LEVELS_BY_NUM[self.level]
            if self.kw:
                msg = self.msg % self.kw
            else:
                msg = self.msg
            self.dictrepr = {'message':msg, 'levelname':levelname,
                    'asctime':asctime, 'filename': self.filename,
                    'lineno': self.lineno, 'pid': os.getpid(),
                    'function': self.function}
        return self.dictrepr

class Logger:
    def __init__(self, level=None, handlers=None):
        if level is None:
            level = LevelsByName.INFO
        self.level = level

        if handlers is None:
            handlers = []
        self.handlers = handlers

    def close(self):
        for handler in self.handlers:
            handler.close()

    def blather(self, msg, **kw):
        if LevelsByName.BLAT >= self.level:
            self.log(LevelsByName.BLAT, msg, **kw)

    def trace(self, msg, **kw):
        if LevelsByName.TRAC >= self.level:
            self.log(LevelsByName.TRAC, msg, **kw)

    def debug(self, msg, **kw):
        if LevelsByName.DEBG >= self.level:
            self.log(LevelsByName.DEBG, msg, **kw)

    def info(self, msg, **kw):
        if LevelsByName.INFO >= self.level:
            self.log(LevelsByName.INFO, msg, **kw)

    def warn(self, msg, **kw):
        if LevelsByName.WARN >= self.level:
            self.log(LevelsByName.WARN, msg, **kw)

    def error(self, msg, **kw):
        if LevelsByName.ERRO >= self.level:
            self.log(LevelsByName.ERRO, msg, **kw)

    def critical(self, msg, **kw):
        if LevelsByName.CRIT >= self.level:
            self.log(LevelsByName.CRIT, msg, **kw)

    def log(self, level, msg, **kw):
        record = LogRecord(level, msg, **kw)
        for handler in self.handlers:
            if level >= handler.level:
                handler.emit(record)

    def addHandler(self, hdlr):
        self.handlers.append(hdlr)

    def getvalue(self):
        raise NotImplementedError

class MyLogger(Logger):
    def __init__(self, level=None, boundLevel=None,
                 statisticHandlers=None, monitorHandlers=None):
        if level is None:
            level = LevelsByName.INFO
        self.level = level
        
        if boundLevel is None:
            boundLevel = LevelsByName.WARN
        self.boundLevel = boundLevel

        if statisticHandlers is None:
            statisticHandlers = []
        self.statisticHandlers = statisticHandlers

        if monitorHandlers is None:
            monitorHandlers = []
        self.monitorHandlers = monitorHandlers

        self.handlers = []

    def findCaller(self):
        f = currentFrame()
        if f is not None:
            f = f.f_back
        rv = "(unknown file)", 0, "(unknown function)"
        while hasattr(f, "f_code"):
            co = f.f_code
            filename = os.path.normcase(co.co_filename)
            if filename == _srcfile:
                f = f.f_back
                continue
            rv = (co.co_filename, f.f_lineno, co.co_name)
            break
        return rv

    def addStatisticHandler(self, handler):
        self.statisticHandlers.append(handler)

    def addMonitorHandler(self, handler):
        self.monitorHandlers.append(handler)

    def getvalue(self):
        raise NotImplementedError

    def close(self):
        for handler in self.statisticHandlers:
            handler.close()

        for handler in self.monitorHandlers:
            handler.close()

        for handler in self.handlers:
            handler.close()

    def log(self, level, msg, **kw):
        if _srcfile:
            try:
                fn, lno, func = self.findCaller()
            except ValueError:
                fn, lno, func = "(unknown file)", 0, "(unknown function)"
        else:
            fn, lno, func = "(unknown file)", 0, "(unknown function)"

        record = MyLogRecord(level, fn, lno, func, msg, **kw)

        for handler in self.statisticHandlers:
            if level >= handler.level and level < self.boundLevel:
                handler.acquire()
                handler.emit(record)
                handler.release()

        for handler in self.monitorHandlers:
            if level >= self.boundLevel:
                handler.acquire()
                handler.emit(record)
                handler.release()

        for handler in self.handlers:
            if level >= handler.level:
                handler.emit(record)

class SyslogHandler(Handler):
    def __init__(self):
        assert 'syslog' in globals(), "Syslog module not present"

    def close(self):
        pass

    def reopen(self):
        pass

    def emit(self, record):
        try:
            params = record.asdict()
            message = params['message']
            for line in message.rstrip('\n').split('\n'):
                params['message'] = line
                msg = self.fmt % params
                try:
                    syslog.syslog(msg)
                except UnicodeError:
                    syslog.syslog(msg.encode("UTF-8"))
        except:
            self.handleError(record)

def getBoundLevel(level):
    levels = sorted(LOG_LEVELS_BY_NUM.keys())
    assert(level in levels)

    if level == levels[-1]:
        return None

    if level < LevelsByName.WARN:
        return LevelsByName.WARN

    for l in levels:
        if l > level:
            return l

def getLogger(filename, level,
              fmt='[%(asctime)s] [%(levelname)s] (#%(pid)d %(function)s %(filename)s:%(lineno)d) %(message)s\n',
              when='d', interval=1, rotating=True, maxbytes=5*100**1024*1024, backups=50, stdout=False, seperate=True):

    handlers = []
    statisticHandlers = []
    monitorHandlers = []

    bound = getBoundLevel(level)
    if bound is None:
        seperate = False

    #if seperate is False:
    #    logger = Logger(level)
    #else:
    logger = MyLogger(level, bound)

    if filename is None:
        if not maxbytes:
            maxbytes = 1<<21 #2MB
        io = BoundIO(maxbytes)
        handlers.append(StreamHandler(io))
        logger.getvalue = io.getvalue

    elif filename == 'syslog':
        handlers.append(SyslogHandler())

    else:
        if rotating is False:
            if seperate is False:
                handlers.append(FileHandler(filename))
            else:
                statisticHandlers.append(FileHandler(filename))
                monitorHandlers.append(FileHandler(filename + '_mon'))   # mon for monitor
        else:
            if seperate is False:
                handlers.append(MyRotatingFileHandler(filename,'a', maxbytes, when, interval, backups))
            else:
                statisticHandlers.append(MyRotatingFileHandler(filename,'a', maxbytes, when, interval, backups))
                monitorHandlers.append(MyRotatingFileHandler(filename + '_mon','a', maxbytes, when, interval, backups))

    if stdout:
        handlers.append(StreamHandler(sys.stdout))

    for handler in handlers:
        handler.setFormat(fmt)
        handler.setLevel(level)
        logger.addHandler(handler)

    for handler in statisticHandlers:
        handler.setFormat(fmt)
        handler.setLevel(level)
        logger.addStatisticHandler(handler)

    for handler in monitorHandlers:
        handler.setFormat(fmt)
        handler.setLevel(bound)
        logger.addMonitorHandler(handler)

    return logger
