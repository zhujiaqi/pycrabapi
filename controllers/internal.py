# -*- coding: utf-8 -*-

import time
import json

import japi
from helpers.error import error
from helpers.api import route, param, login
from helpers.format import format_account

from singletons import rds
from dao import account as dao_account

# sample router
def index(args, me, meta):
    routes = {
        'GET': [
            ('^sleep$', sleep),
            ('^noop$', noop),
            ('^echo\/(?P<foo>.+)$', echo, {'myvar': 'bar'}),
            ('^sample\/(?P<account_id>.+)$', get_account),
        ],
        'POST': [
            ('^multiapi$', multiapi),
        ]
    }
    return route(routes, args, me, meta)

#sample apis
@param('duration', False, lambda x: x in ['short', 'long'] and x or error(10010, {'duration': x}))
def sleep(args, me, meta):
    start = time.time()
    duration = args.get('duration') or 'short'
    if duration == 'short':
        time.sleep(1)
    else:
        time.sleep(10)
    end = time.time()
    return {
        'time_elapsed': end - start,
    }

@login
def noop(args, me, meta):
    return

@param('apis', True, str)
def multiapi(args, me, meta):
    apis = json.loads(args['apis'])
    ip = args['ip']
    callback = args.get('callback')
    if callback:
        error(10032, {'callback': callback})
    responses = []
    for method, api, args in apis:
        args['REQUEST_METHOD'] = method
        if not args.get('ip'):
            args['ip'] = ip
        apires, status = japi.process_action(api, args, me)
        if status:
            error(status)
        responses.append(apires)
    return responses

@param('foo', True, str)
def echo(args, me, meta):
    meta['force_txt'] = True
    return (args['foo'] + args['myvar'])

@param('account_id', True, str)
def get_account(args, me, meta):
    return format_account(dao_account.get_account_by_id(args['account_id']))
