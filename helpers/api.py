# -*- coding: utf-8 -*-

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import re
import urllib
import hashlib
import time
from functools import wraps

from helpers.error import error

import config
from singletons import rds
from log import debug_log

def param(key, is_required=False, process_func=lambda x: x):
    def decorator(f):
        @wraps(f)
        def wrapper(args, me, meta):
            value = args.get(key)
            if value == 'undefined':
                value = None
            if not value and is_required:
                error(10009, key)
            if value:
                args[key] = process_func(value)
            else:
                args[key] = None
            return f(args, me, meta)
        return wrapper
    return decorator

def login(f):
    @wraps(f)
    def wrapper(args, me, meta):
        me or error(20010)
        return f(args, me, meta)
    return wrapper

def route(routes, args, me, meta):
    uri = args['URIARGS']
    api_line = routes.get(args['REQUEST_METHOD']) or []
    for api_line_items in api_line:
        if len(api_line_items) == 2:
            r, func = api_line_items
            extra = {}
        else:
            r, func, extra = api_line_items
        match_obj = re.match(r, uri)
        if match_obj:
            print r, 'matched'
            groups = match_obj.groupdict()
            del args['REQUEST_METHOD'], args['URIARGS']
            args.update(groups)
            for x in extra:
                if x not in args:
                    args[x] = extra[x]
                else:
                    error()
            return func(args, me, meta)
    else:
        error(10036, {'uri': uri, 'request_method': args['REQUEST_METHOD']})
