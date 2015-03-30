# -*- coding: utf-8 -*-

import datetime
import time
from decimal import Decimal

def realize(obj):
    if isinstance(obj, dict):
        res = {}
        for k in obj:
            res[k] = realize(obj[k])
        return res
    if isinstance(obj, (list, tuple)):
        return map(realize, obj)
    if isinstance(obj, datetime.datetime):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(obj, (datetime.date, datetime.time)):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    return obj
