import config

from miscs import logger

def get_logger(lname, fname=None, size=512*1024*1024, count=50, fmt='[%(asctime)s] %(message)s', datefmt=""):
    if not fname:
        fname = lname + '.log'
    l = logger.getLogger(filename=config.LOG_PATH + fname, level=logger.DEBG, fmt=fmt, maxbytes=size, backups=count, when='midnight')
    return l

error_log = get_logger(
    'error',
    count=10,
    fmt='[%(asctime)s] [%(levelname)s] (#%(pid)d %(function)s %(filename)s:%(lineno)d) %(message)s\n',
    datefmt="%Y-%m-%d %H:%M:%S"
)
panic_log = get_logger(
    'panic',
    count=10,
    fmt='[%(asctime)s] [%(levelname)s] (#%(pid)d %(function)s %(filename)s:%(lineno)d) %(message)s\n',
    datefmt="%Y-%m-%d %H:%M:%S"
)
app_log = get_logger(
    'app',
    count=10000,
    fmt='[%(asctime)s] [%(levelname)s] (#%(pid)d %(function)s %(filename)s:%(lineno)d) %(message)s\n',
    datefmt="%Y-%m-%d %H:%M:%S"
)
debug_log = get_logger(
    'debug',
    count=90,
    fmt='[%(asctime)s] [%(levelname)s] (#%(pid)d %(function)s %(filename)s:%(lineno)d) %(message)s\n',
    datefmt="%Y-%m-%d %H:%M:%S"
)
maillog = logger.getLogger(
    filename='logs/mail.log',
    level=logger.DEBG,
    fmt='[%(asctime)s] %(message)s\n',
    maxbytes=1024*1024*1024,
    backups=1,
    when='midnight'
)

# you may define new loggers here
