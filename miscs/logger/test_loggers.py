import sys
import unittest
import tempfile
import shutil
import os
import syslog

import mock

#from supervisor.tests.base import DummyStream

class DummyStream:
    def __init__(self, error=None):
        self.error = error
        self.closed = False
        self.flushed = False
        self.written = ''
    def close(self):
        if self.error:
            raise self.error
        self.closed = True
    def flush(self):
        self.flushed = True
    def write(self, msg):
        if self.error:
            raise self.error
        self.written +=msg
    def seek(self, num, whence=0):
        pass
    def tell(self):
        return len(self.written)

class LevelTests(unittest.TestCase):
    def test_LOG_LEVELS_BY_NUM_doesnt_include_builtins(self):
        import logger
        for level_name in logger.LOG_LEVELS_BY_NUM.values():
            self.assertFalse(level_name.startswith('_'))

class HandlerTests:
    def setUp(self):
        self.basedir = tempfile.mkdtemp()
        self.filename = os.path.join(self.basedir, 'thelog')

    def tearDown(self):
        try:
            shutil.rmtree(self.basedir)
        except OSError:
            pass

    def _makeOne(self, *arg, **kw):
        klass = self._getTargetClass()
        return klass(*arg, **kw)

    def _makeLogRecord(self, msg):
        import logger
        record = logger.LogRecord(level=logger.LevelsByName.INFO,
                                   msg=msg,
                                   exc_info=None)
        return record

class MyRotatingFileHandlerTests(HandlerTests, unittest.TestCase):
    def _getTargetClass(self):
        from logger import MyRotatingFileHandler
        return MyRotatingFileHandler

    def _makeLogRecord(self, msg):
        import logger
        record = logger.MyLogRecord(level=logger.LevelsByName.INFO,
                                    filename='hehe.py',
                                    lineno=100,
                                    function='foo',
                                    msg = msg,
                                    exc_info=None)
        return record

    def test_ctor(self):
        handler = self._makeOne(self.filename)
        self.assertTrue(os.path.exists(self.filename), self.filename)
        self.assertTrue(os.path.exists(handler.rollFile))
        self.assertTrue(os.path.exists(self.filename + '.lock'))
        self.assertEqual(handler.mode, 'a')
        self.assertEqual(handler.baseFilename, self.filename)
        self.assertEqual(handler.maxBytes, 0)
        self.assertEqual(handler.backupCount, 0)
        self.assertFalse(handler.stream_lock.closed)
        self.assertEqual(handler.when, 'H')
        self.assertEqual(handler.suffix, '%Y-%m-%d_%H')
        self.assertEqual(handler.extMatch.pattern, r"^\d{4}-\d{2}-\d{2}_\d{2}\.\d+$")
        self.assertFalse(handler.toDoTimedRollover)
        self.assertFalse(handler.toDoSizedRollover)

    def test_close(self):
        handler = self._makeOne(self.filename)
        handler.close()
        self.assertEqual(handler.stream.closed, True)

    def test_emit(self):
        handler = self._makeOne(self.filename)
        record = self._makeLogRecord(u'fi\xed')
        handler.emit(record)
        handler.stream.flush()
        content = open(self.filename, 'r').read()
        self.assertEqual(content, 'fi\xc3\xad')

    def test_emit_does_rollover(self):
        handler = self._makeOne(self.filename, maxBytes=10, backupCount=2)
        record = self._makeLogRecord('a' * 5)

        handler.emit(record)
        self.assertFalse(os.path.exists(self.filename + '.1'))
        self.assertFalse(os.path.exists(self.filename + '.2'))

        handler.emit(record)
        self.assertFalse(os.path.exists(self.filename + '.1'))
        self.assertFalse(os.path.exists(self.filename + '.2'))

        def getFiles():
            files = []
            dirName, baseName = os.path.split(self.filename)
            prefix = baseName + "."
            plen = len(prefix)
            d = os.listdir(os.path.split(self.filename)[0])
            for i in d:
                if i[:plen] == prefix:
                    suffix = i[plen:]
                    if handler.extMatch.match(suffix):
                        files.append(os.path.join(dirName, i))
            return sorted(files)

        handler.emit(record)
        files = getFiles()
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith('.1'))

        handler.emit(record)
        handler.emit(record)
        files = getFiles()
        self.assertEqual(len(files), 2)
        self.assertTrue(files[0].endswith('.1'))
        self.assertTrue(files[1].endswith('.2'))

        handler.emit(record)
        handler.emit(record)
        handler.emit(record)
        handler.emit(record)
        handler.emit(record)
        handler.emit(record)
        handler.emit(record)
        handler.emit(record)
        handler.emit(record)
        files = getFiles()
        self.assertEqual(len(files), 2)
        self.assertTrue(files[0].endswith('.1'))
        self.assertTrue(files[1].endswith('.2'))

        current = open(self.filename,'r').read()
        self.assertEqual(current, 'a' * 5)
        one = open(files[0],'r').read()
        self.assertEqual(one, 'a'*10)
        two = open(files[1],'r').read()
        self.assertEqual(two, 'a'*10)

class FileHandlerTests(HandlerTests, unittest.TestCase):
    def _getTargetClass(self):
        from logger import FileHandler
        return FileHandler

    def test_ctor(self):
        handler = self._makeOne(self.filename)
        self.assertTrue(os.path.exists(self.filename), self.filename)
        self.assertEqual(handler.mode, 'a')
        self.assertEqual(handler.baseFilename, self.filename)
        self.assertEqual(handler.stream.name, self.filename)

    def test_close(self):
        handler = self._makeOne(self.filename)
        handler.stream = DummyStream()
        handler.close()
        self.assertEqual(handler.stream.closed, True)

    def test_close_raises(self):
        handler = self._makeOne(self.filename)
        handler.stream = DummyStream(OSError)
        self.assertRaises(OSError, handler.close)
        self.assertEqual(handler.stream.closed, False)

    def test_reopen(self):
        handler = self._makeOne(self.filename)
        stream = DummyStream()
        handler.stream = stream
        handler.reopen()
        self.assertEqual(stream.closed, True)
        self.assertEqual(handler.stream.name, self.filename)

    def test_reopen_raises(self):
        handler = self._makeOne(self.filename)
        stream = DummyStream()
        handler.stream = stream
        handler.baseFilename = os.path.join(self.basedir, 'notthere', 'a.log')
        self.assertRaises(IOError, handler.reopen)
        self.assertEqual(stream.closed, True)

    def test_remove_exists(self):
        handler = self._makeOne(self.filename)
        self.assertTrue(os.path.exists(self.filename), self.filename)
        handler.remove()
        self.assertFalse(os.path.exists(self.filename), self.filename)

    def test_remove_doesntexist(self):
        handler = self._makeOne(self.filename)
        os.remove(self.filename)
        self.assertFalse(os.path.exists(self.filename), self.filename)
        handler.remove() # should not raise
        self.assertFalse(os.path.exists(self.filename), self.filename)

    def test_remove_raises(self):
        handler = self._makeOne(self.filename)
        os.remove(self.filename)
        os.mkdir(self.filename)
        self.assertTrue(os.path.exists(self.filename), self.filename)
        self.assertRaises(OSError, handler.remove)

    def test_emit_ascii_noerror(self):
        handler = self._makeOne(self.filename)
        record = self._makeLogRecord('hello!')
        handler.emit(record)
        content = open(self.filename, 'r').read()
        self.assertEqual(content, 'hello!')

    def test_emit_unicode_noerror(self):
        handler = self._makeOne(self.filename)
        record = self._makeLogRecord(u'fi\xed')
        handler.emit(record)
        content = open(self.filename, 'r').read()
        self.assertEqual(content, 'fi\xc3\xad')

    def test_emit_error(self):
        handler = self._makeOne(self.filename)
        handler.stream = DummyStream(error=OSError)
        record = self._makeLogRecord('hello!')
        try:
            old_stderr = sys.stderr
            dummy_stderr = DummyStream()
            sys.stderr = dummy_stderr
            handler.emit(record)
        finally:
            sys.stderr = old_stderr

        self.assertTrue(dummy_stderr.written.endswith('OSError\n'),
                        dummy_stderr.written)

class RotatingFileHandlerTests(FileHandlerTests):

    def _getTargetClass(self):
        from logger import RotatingFileHandler
        return RotatingFileHandler

    def test_ctor(self):
        handler = self._makeOne(self.filename)
        self.assertEqual(handler.mode, 'a')
        self.assertEqual(handler.maxBytes, 512*1024*1024)
        self.assertEqual(handler.backupCount, 10)

    def test_emit_does_rollover(self):
        handler = self._makeOne(self.filename, maxBytes=10, backupCount=2)
        record = self._makeLogRecord('a' * 5)

        handler.emit(record)
        self.assertFalse(os.path.exists(self.filename + '.1'))
        self.assertFalse(os.path.exists(self.filename + '.2'))

        handler.emit(record)
        self.assertFalse(os.path.exists(self.filename + '.1'))
        self.assertFalse(os.path.exists(self.filename + '.2'))

        handler.emit(record)
        self.assertTrue(os.path.exists(self.filename + '.1'))
        self.assertFalse(os.path.exists(self.filename + '.2'))

        handler.emit(record)
        self.assertTrue(os.path.exists(self.filename + '.1'))
        self.assertFalse(os.path.exists(self.filename + '.2'))

        handler.emit(record)
        self.assertTrue(os.path.exists(self.filename + '.1'))
        self.assertTrue(os.path.exists(self.filename + '.2'))

        handler.emit(record)
        self.assertTrue(os.path.exists(self.filename + '.1'))
        self.assertTrue(os.path.exists(self.filename + '.2'))

        handler.emit(record)
        self.assertTrue(os.path.exists(self.filename + '.1'))
        self.assertTrue(os.path.exists(self.filename + '.2'))

        current = open(self.filename,'r').read()
        self.assertEqual(current, 'a' * 5)
        one = open(self.filename+ '.1','r').read()
        self.assertEqual(one, 'a'*10)
        two = open(self.filename+ '.2','r').read()
        self.assertEqual(two, 'a'*10)

class BoundIOTests(unittest.TestCase):
    def _getTargetClass(self):
        from logger import BoundIO
        return BoundIO

    def _makeOne(self, maxbytes, buf=''):
        klass = self._getTargetClass()
        return klass(maxbytes, buf)

    def test_write_overflow(self):
        io = self._makeOne(1, 'a')
        io.write('b')
        self.assertEqual(io.buf, 'b')

    def test_getvalue(self):
        io = self._makeOne(1, 'a')
        self.assertEqual(io.getvalue(), 'a')

    def test_clear(self):
        io = self._makeOne(1, 'a')
        io.clear()
        self.assertEqual(io.buf, '')

    def test_close(self):
        io = self._makeOne(1, 'a')
        io.close()
        self.assertEqual(io.buf, '')

class FileIsOpenTest(unittest.TestCase):
    def testFileIsOpen(self):
        from logger import FileIsOpen
        from tempfile import NamedTemporaryFile

        f = NamedTemporaryFile(delete=False)
        self.assertTrue(FileIsOpen(f.name))
        f.close()
        self.assertFalse(FileIsOpen(f.name))

class LoggerTests(unittest.TestCase):
    def _getTargetClass(self):
        from logger import Logger
        return Logger

    def _makeOne(self, level=None, handlers=None):
        klass = self._getTargetClass()
        return klass(level, handlers)

    def test_blather(self):
        from logger import LevelsByName
        handler = DummyHandler(LevelsByName.BLAT)
        logger = self._makeOne(LevelsByName.BLAT, (handler,))
        logger.blather('hello')
        self.assertEqual(len(handler.records), 1)
        logger.level = LevelsByName.TRAC
        logger.blather('hello')
        self.assertEqual(len(handler.records), 1)

    def test_trace(self):
        from logger import LevelsByName
        handler = DummyHandler(LevelsByName.TRAC)
        logger = self._makeOne(LevelsByName.TRAC, (handler,))
        logger.trace('hello')
        self.assertEqual(len(handler.records), 1)
        logger.level = LevelsByName.DEBG
        logger.trace('hello')
        self.assertEqual(len(handler.records), 1)

    def test_debug(self):
        from logger import LevelsByName
        handler = DummyHandler(LevelsByName.DEBG)
        logger = self._makeOne(LevelsByName.DEBG, (handler,))
        logger.debug('hello')
        self.assertEqual(len(handler.records), 1)
        logger.level = LevelsByName.INFO
        logger.debug('hello')
        self.assertEqual(len(handler.records), 1)

    def test_info(self):
        from logger import LevelsByName
        handler = DummyHandler(LevelsByName.INFO)
        logger = self._makeOne(LevelsByName.INFO, (handler,))
        logger.info('hello')
        self.assertEqual(len(handler.records), 1)
        logger.level = LevelsByName.WARN
        logger.info('hello')
        self.assertEqual(len(handler.records), 1)

    def test_warn(self):
        from logger import LevelsByName
        handler = DummyHandler(LevelsByName.WARN)
        logger = self._makeOne(LevelsByName.WARN, (handler,))
        logger.warn('hello')
        self.assertEqual(len(handler.records), 1)
        logger.level = LevelsByName.ERRO
        logger.warn('hello')
        self.assertEqual(len(handler.records), 1)

    def test_error(self):
        from logger import LevelsByName
        handler = DummyHandler(LevelsByName.ERRO)
        logger = self._makeOne(LevelsByName.ERRO, (handler,))
        logger.error('hello')
        self.assertEqual(len(handler.records), 1)
        logger.level = LevelsByName.CRIT
        logger.error('hello')
        self.assertEqual(len(handler.records), 1)

    def test_critical(self):
        from logger import LevelsByName
        handler = DummyHandler(LevelsByName.CRIT)
        logger = self._makeOne(LevelsByName.CRIT, (handler,))
        logger.critical('hello')
        self.assertEqual(len(handler.records), 1)

    def test_close(self):
        from logger import LevelsByName
        handler = DummyHandler(LevelsByName.CRIT)
        logger = self._makeOne(LevelsByName.CRIT, (handler,))
        logger.close()
        self.assertEqual(handler.closed, True)

class MockSysLog(mock.Mock):
    def __call__(self, *args, **kwargs):
        message = args[-1]
        if sys.version_info < (3, 0) and isinstance(message, unicode):
            # Python 2.x raises a UnicodeEncodeError when attempting to
            #  transmit unicode characters that don't encode in the
            #  default encoding.
            message.encode()
        super(MockSysLog, self).__call__(*args, **kwargs)

class SyslogHandlerTests(HandlerTests, unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def _getTargetClass(self):
        import logger
        return logger.SyslogHandler

    def _makeOne(self):
        return self._getTargetClass()()

    @mock.patch('syslog.syslog', MockSysLog())
    def test_emit_ascii_noerror(self):
        handler = self._makeOne()
        record = self._makeLogRecord('hello!')
        handler.emit(record)
        syslog.syslog.assert_called_with('hello!')

    @mock.patch('syslog.syslog', MockSysLog())
    def test_close(self):
        handler = self._makeOne()
        handler.close()  # no-op for syslog

    @mock.patch('syslog.syslog', MockSysLog())
    def test_reopen(self):
        handler = self._makeOne()
        handler.reopen()  # no-op for syslog

    @mock.patch('syslog.syslog', MockSysLog())
    def test_emit_unicode_noerror(self):
        handler = self._makeOne()
        record = self._makeLogRecord(u'fi\xed')
        handler.emit(record)
        if sys.version_info < (3, 0):
            syslog.syslog.assert_called_with('fi\xc3\xad')
        else:
            syslog.syslog.assert_called_with(u'fi\xed')

class DummyHandler:
    close = False
    def __init__(self, level):
        self.level = level
        self.records = []
    def emit(self, record):
        self.records.append(record)
    def close(self):
        self.closed = True

def test_suite():
    return unittest.findTestCases(sys.modules[__name__])

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
