#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
reload(sys)
sys.setdefaultencoding('utf8')

import imp
import traceback
import gzip
import cgi
import urllib
import datetime
import time
import hashlib
import urllib2
import json
from StringIO import StringIO
from exceptions import BaseException

import config

from helpers.error import *
from helpers.util import realize
#from helpers import account
from helpers import mail

from singletons import mysql_conn, rds
from log import *

exc = BaseException
loaded_controllers = {}

def _check_limit_exceed(ua_ip_hash):
    current_time = int(time.time() / 60) #per 60 seconds
    key = 'timelimit:%s%s' % (ua_ip_hash, current_time)
    current_limit = rds.get(key)
    print key, current_limit
    if current_limit is not None and int(current_limit) > 1000:
        return True
    else:
        p = rds.pipeline()
        p.incr(key, 1)
        p.expire(key, 64)
        p.execute()
        return False

def _log_me(args, me):
    if me:
        return me['id']
    elif args.get('ua_ip_hash'):
        return args['ua_ip_hash']
    else:
        return 0

def _format_error(me, status, data, message):
    return {
        'version': 1,
        'meta': {
            'status': int(status),
            'errdata': data,
            'errmsg': message,
            'cost': 0.0,
            'server_time': datetime.datetime.utcnow(),
            'account_id': me and me['id'] or 0,
        },
        'data': None
    }

def _get_error(path, args, me, exception):
    if isinstance(exception, CustomError):
        if exception.code != 10001:
            error_info = [
                '<%s>' % _log_me(args, me),
                exception.code,
                exception.data,
                str(path),
                str(_copy_dict_with_limited_value_length(args))
            ]
            error_info = map(str, error_info)
            error_log.error('\t'.join(error_info))
        return _format_error(me, exception.code, exception.data, exception.get_message())
    elif exc and isinstance(exception, exc):
        f = StringIO()
        traceback.print_exc(None, f)
        f.seek(0)
        msg = f.read().decode('utf8')
        panic_info = ['<%s>' % _log_me(args, me), msg, str(path), str(args)]
        panic_info = map(str, panic_info)
        panic_log.critical('\t'.join(panic_info))
        email_body = '<br>'.join(panic_info)
        #mail.send(['me@mydomain.com'], email_body, 'API Error（%s）' % str(datetime.datetime.now()), True)
        return _format_error(me, 10034, None, str(exception))
    else:
        raise

def _copy_dict_with_limited_value_length(o):
    res = {}
    for k, v in o.iteritems():
        if not isinstance(v, (str, unicode)) or len(v) < config.LOG_LENGTH:
            res[k] = v
    return res

def process_action(path, args, me):
    path = path.strip('/')
    r = path.split('/')

    if len(r) < 1:
        return None, 10035

    m = loaded_controllers.get(r[0])
    if m is None:
        try:
            m = imp.find_module(r[0], ['controllers'])
        except ImportError, e:
            return None, 10035

        m = imp.load_module(r[0], *m)
        loaded_controllers[r[0]] = m
    try:
        action = getattr(m, 'index')
    except:
        action = None
    if not action:
        return None, 10035
    else:
        args['URIARGS'] = '/'.join(r[1:])

    time1 = time.time()
    meta = {
        'version': 1,
    }
    res = action(args, me, meta)
    time2 = time.time()
    res = {
        'meta': {},
        'data': res
    }
    meta['account_id'] = me and me['id'] or 0
    meta['cost'] = time2 - time1
    meta['server_time'] = datetime.datetime.now()
    meta['status'] = 0
    meta['errdata'] = None
    meta['errmsg'] = ''
    res['meta'] = meta
    return res, 0

def _build_args(environ):
    args = {}
    safe_env = {'QUERY_STRING':''} # Build a safe environment for cgi
    for key in ('REQUEST_METHOD', 'CONTENT_TYPE', 'CONTENT_LENGTH', 'HTTP_' + config.TOKEN_HEADER):
        val = environ.get(key)
        if val:
            safe_env[key] = val

    args['REQUEST_METHOD'] = safe_env['REQUEST_METHOD']

    post_data_list = cgi.FieldStorage(fp=environ['wsgi.input'], environ=safe_env, keep_blank_values=True).list
    for item in post_data_list:
        args[item.name] = unicode(item.value, 'utf-8')

    params = cgi.parse_qs(environ['QUERY_STRING'])
    for k, v in params.iteritems():
        args[k] = unicode(v[0], 'utf-8')

    client_ip = environ.get('HTTP_X_REAL_IP') or environ['REMOTE_ADDR']

    if client_ip.startswith('127.') or client_ip.startswith('10.') or client_ip.startswith('192.'):
        forwarded_for = environ.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            forwarded_for = forwarded_for.split(',')
            client_ip = forwarded_for[-1].strip()
            if client_ip.startswith('127.'):
                client_ip = forwarded_for[-1].strip()

    args['ip'] = client_ip[:20]
    args['ua_ip_hash'] = hashlib.md5(client_ip + '|' + environ.get('HTTP_USER_AGENT', '')).hexdigest()
    return args

def _check_auth(environ):
    token = environ.get('HTTP_' + config.TOKEN_HEADER)
    if token:
        #TODO: verify token
        acc = {'id': 0}
        return acc

def application(environ, start_response):
    response_header = '200 OK'
    headers = [('Access-Control-Allow-Origin', '*')]
    use_gzip = 'gzip' in environ.get('HTTP_ACCEPT_ENCODING', '').lower()
    if environ['PATH_INFO'] == '/crossdomain.xml':
        res = '''<?xml version="1.0"?>
<cross-domain-policy>
    <allow-access-from domain="*" />
</cross-domain-policy>'''
        headers.append(('Content-Type', 'text/xml'))
    elif environ['PATH_INFO'] == '/favicon.ico':
        res = ''
        headers.append(('Content-Type', 'image/x-icon'))
    else:
        status = 0
        api_error = None
        me = None
        args = _build_args(environ)
        if hasattr(config, 'IS_DOWN') and config.IS_DOWN == True:
            status = 10001
        else:
            if _check_limit_exceed(args['ua_ip_hash']):
                status = 10030
            else:
                auth = _check_auth(environ)
                if auth:
                    me = auth
                if 'force_auth' in args and not me:
                    status = 20010

            start_time = datetime.datetime.now()
            res = None
            try:
                if not status:
                    res, status = process_action(environ['PATH_INFO'], args, me)
                    mysql_conn.conn.commit()
            except exc, e:
                api_error = e
                mysql_conn.conn.rollback()
            finally:
                api_cost = datetime.datetime.now() - start_time
                api_cost = api_cost.seconds + api_cost.microseconds / 1000000.0
                app_log.info('%s\t<%s>\t%.4f\t%s' % (
                    environ['PATH_INFO'],
                    _log_me(args, me),
                    api_cost,
                    str(args['ip']))
                )
                debug_log.info('%s\t<%s>\t%.4f\t%s' % (
                    environ['PATH_INFO'],
                    _log_me(args, me),
                    api_cost,
                    urllib.urlencode(_copy_dict_with_limited_value_length(args)))
                )

        if status:
            api_error = CustomError(status, None)

        if api_error:
            res = _get_error(environ['PATH_INFO'], args, me, api_error)
            if res['meta']['status'] in [20010, ]:
                response_header = '401 Unauthorized'
            elif res['meta']['status'] >= 90000 and res['meta']['status'] <= 99999:
                response_header = res['meta']['errmsg']
            elif res['meta']['status'] == 10030:
                response_header = '429 Too Many Requests'
            else:
                response_header = '500 Internal Server Error'

        callback = args.get('callback')
        if callback and not api_error:
            start_response('301 Redirect', [('Location', callback.encode('utf8')),])
            return []
        elif res['meta'].get('force_txt') and not api_error:
            headers.append(('Content-Type', 'text/plain; charset=utf-8'))
            res = res['data']
        else:
            res = json.dumps(realize(res))
            headers.append(('Content-Type', 'application/json; charset=utf-8'))

    etag = '"' + hashlib.md5(res).hexdigest()[:16] + '"'
    headers.append(('ETag', etag))
    if environ.get('HTTP_IF_NONE_MATCH') == etag:
        start_response('304 Not Modified', [])
        return {}

    if use_gzip:
        headers.append(('Content-Encoding', 'gzip'))
        resio = StringIO()
        g = gzip.GzipFile(mode='wb', fileobj=resio)
        g.write(res)
        g.close()
        resio.seek(0)
        res = resio.read()

    content_length = len(res)
    headers.append(('Content-Length', str(content_length)))
    start_response(response_header, headers)
    return [res]
