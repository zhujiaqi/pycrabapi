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
import json
from StringIO import StringIO
from exceptions import BaseException

import config

from helpers.error import *
from helpers.util import realize
from helpers import mail

from singletons import mysql_conn, rds
from log import *

exc = BaseException
loaded_controllers = {}

def _check_limit_exceed(ua_ip_hash):
    current_time = int(time.time() / 60) #per 60 seconds
    key = 'timelimit:%s%s' % (ua_ip_hash, current_time)
    current_limit = rds.get(key)
    if current_limit is not None and int(current_limit) > 1000:
        mail_key = 'timelimit_exceed:%s' % (ua_ip_hash)
        mail_limit = rds.get(mail_key)
        if mail_limit is None:
            email_body = '<p>Limit Exceeded:%s</p><br><p>Value:%s(%s)</p>' % (ua_ip_hash, current_limit, 1000)
            mail.send(['admin@mydomain.com'], email_body, 'API Limit Exceeded（%s）（%s）' % (str(datetime.datetime.now()), config.STAGE), True)
            p = rds.pipeline()
            p.set(mail_key, 1)
            p.expire(mail_key, 3600)
            p.execute()
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

def _format_error(me, api_error):
    return {
        'version': 1,
        'meta': {
            'status': api_error.code,
            'errdata': api_error.data,
            'errmsg': api_error.get_message(),
            'cost': 0.0,
            'server_time': datetime.datetime.now(),
            'account_id': me and me['id'] or 0,
        },
        'data': None
    }

def _log_error(path, args, me, exception):
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
    elif exc and isinstance(exception, exc):
        f = StringIO()
        traceback.print_exc(None, f)
        f.seek(0)
        msg = f.read().decode('utf8')
        panic_info = ['<%s>' % _log_me(args, me), msg, str(path), str(args)]
        panic_info = map(str, panic_info)
        panic_log.critical('\t'.join(panic_info))
        email_body = '<br>'.join(panic_info)
        mail.send(['admin@mydomain.com'], email_body, 'Server Error（%s）（%s）' % (str(datetime.datetime.now()), config.STAGE), True)

def _copy_dict_with_limited_value_length(o):
    res = {}
    for k, v in o.iteritems():
        if not isinstance(v, (str, unicode)) or len(v) < config.LOG_LENGTH:
            res[k] = v
    return res

def process_action(orig_path, args, me):
    path = orig_path
    path = path.strip('/')
    r = path.split('/')

    if len(r) < 1:
        api_error = CustomError(10035)
        return _format_error(me, api_error), api_error

    m = loaded_controllers.get(r[0])
    if m is None:
        try:
            m = imp.find_module(r[0], ['controllers'])
        except ImportError, e:
            api_error = CustomError(10035)
            return _format_error(me, api_error), api_error

        m = imp.load_module(r[0], *m)
        loaded_controllers[r[0]] = m
    try:
        action = getattr(m, 'index')
    except:
        action = None
    if not action:
        api_error = CustomError(10036)
        return _format_error(me, api_error), api_error
    else:
        args['URIARGS'] = '/'.join(r[1:])

    time1 = time.time()
    meta = {
        'version': 1,
        'update_db': False,
    }

    res = None
    api_error = None
    try:
        res = action(args, me, meta)
        mysql_conn.commit()
    except exc, e:
        _log_error(orig_path, args, me, e)
        if not isinstance(e, CustomError):
            api_error = CustomError(10034, str(e))
        else:
            api_error = e
        if meta['update_db']:
            mysql_conn.conn.rollback()
    finally:
        time2 = time.time()
        meta['cost'] = time2 - time1
        app_log.info('%s\t<%s>\t%.4f\t%s' % (
            orig_path,
            _log_me(args, me),
            meta['cost'],
            str(args['ip']))
        )
        debug_log.info('%s\t<%s>\t%.4f\t%s' % (
            orig_path,
            _log_me(args, me),
            meta['cost'],
            urllib.urlencode(_copy_dict_with_limited_value_length(args)))
        )
    res = {
        'meta': meta,
        'data': res
    }
    meta['account_id'] = me and me['id'] or 0
    meta['server_time'] = datetime.datetime.now()
    meta['status'] = api_error and api_error.code or 0
    meta['errdata'] = api_error and api_error.data or None
    meta['errmsg'] = api_error and api_error.get_message() or ''
    return res, api_error

def _build_args(environ):
    args = {}
    safe_env = {'QUERY_STRING':''} # Build a safe environment for cgi
    for key in ('REQUEST_METHOD', 'CONTENT_TYPE', 'CONTENT_LENGTH', 'HTTP_' + config.TOKEN_HEADER):
        val = environ.get(key)
        if val:
            safe_env[key] = val

    args['REQUEST_METHOD'] = safe_env['REQUEST_METHOD']
    post_data = cgi.FieldStorage(fp=environ['wsgi.input'], environ=safe_env, keep_blank_values=True)

    if safe_env.get('CONTENT_TYPE'):
        if safe_env['CONTENT_TYPE'].startswith('application/x-www-form-urlencoded') or safe_env['CONTENT_TYPE'].startswith('multipart/form-data'):
            for item in post_data.list:
                args[item.name] = unicode(item.value, 'utf-8')
        elif safe_env['CONTENT_TYPE'] == 'application/json':
            try:
                json_data = json.loads(post_data.file.read())
            except:
                return
            #print json_data
            for key, value in json_data.items():
                args[key] = value
        else:
            print safe_env['CONTENT_TYPE']
            return

    params = cgi.parse_qs(environ['QUERY_STRING'])
    for k, v in params.iteritems():
        args[k] = unicode(v[0], 'utf-8') 

    client_ip = environ.get('HTTP_X_REAL_IP') or environ['REMOTE_ADDR'] or ''
    if client_ip.startswith('127.') or client_ip.startswith('10.') or client_ip.startswith('192.'):
        forwarded_for = environ.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            client_ip = forwarded_for
    client_ip = client_ip.split(',')[0].strip()

    args['ip'] = client_ip
    args['ua_ip_hash'] = hashlib.md5(client_ip + '|' + environ.get('HTTP_USER_AGENT', '')).hexdigest()
    return args

def _check_auth(environ):
    token = environ.get('HTTP_' + config.TOKEN_HEADER)
    if token:
        acc = {'id': 0} #TODO: verify account
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
        api_error = None
        me = None
        args = _build_args(environ)
        if args is None:
            api_error = CustomError(10002)
            res = _format_error(me, api_error)
        else:
            if hasattr(config, 'IS_DOWN') and config.IS_DOWN == True:
                api_error = CustomError(10001)
                res = _format_error(me, api_error)
            else:
                if _check_limit_exceed(args['ua_ip_hash']):
                    api_error = CustomError(10030)
                    res = _format_error(me, api_error)
                else:
                    auth = _check_auth(environ)
                    if auth:
                        me = auth
                        if me.get('is_session_id'):
                            args['session_id'] = int(me['id'])
                    if 'force_auth' in args and not me:
                        api_error = CustomError(20010)
                        res = _format_error(me, api_error)

                if not api_error:
                    res, api_error = process_action(environ['PATH_INFO'], args, me)

        if api_error:
            if api_error.code >= 20010 and api_error.code <= 26999:
                response_header = '401 Unauthorized'
                headers.append(('WWW-Authenticate', 'Digest realm="wtf"'))
            elif api_error.code >= 90000 and api_error.code <= 99999:
                response_header = api_error.get_message()
            elif api_error.code == 10030:
                response_header = '429 Too Many Requests'
            else:
                response_header = '500 Internal Server Error'

        else:
            callback = args.get('callback')
            if callback:
                start_response('301 Redirect', [('Location', callback.encode('utf8')),])
                return []
            elif res['meta'].get('force_txt'):
                headers.append(('Content-Type', 'text/plain; charset=utf-8'))
                res = res['data']

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
