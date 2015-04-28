# -*- coding: utf-8 -*-

from exceptions import BaseException

#customize errors here

ERROR_MESSAGES = {
    #1xxxx API Level
    10001: 'API is down',
    10009: 'Required parameter',
    10010: 'Parameter out of range',
    10011: 'Invalid parameter type',
    10020: 'Record not found',
    10030: 'Too many requests',
    10032: 'Invalid method',
    10034: 'Internal error',
    10035: 'Controller not found',
    10036: 'API not found',

    #2xxxx Authetication Errors
    20010: 'Authentication required',

    #hack HTTP Errors 90000~99999
    90405: '405 Method not allowed',
}

class CustomError(BaseException):
    def __init__(self, code, data=''):
        self.code = code
        self.data = data
    def __str__(self):
        return self.get_message() or 'Error %d' % self.code
    def get_message(self):
        if ERROR_MESSAGES.has_key(self.code):
            return ERROR_MESSAGES[self.code]
        else:
            return ''

def error(code, data=''):
    raise CustomError(code, data)

class DBException(BaseException):
    pass
