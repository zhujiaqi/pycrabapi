# -*- coding: utf-8 -*-

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import re
import datetime
import time
import random
from decimal import Decimal
import string
import calendar
import base64
from Crypto.Cipher import AES
from Crypto import Random
import requests
import urllib

from helpers.error import error

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
        return round(obj, 2)
    if isinstance(obj, time.struct_time):
        return time.strftime('%Y-%m-%d %H:%M:%S', obj)
    if isinstance(obj, set):
        return str(obj)
    return obj

def str_to_int(s):
    r = None
    try:
        r = int(s)
    except ValueError, e:
        pass
    return r

def str_to_datetime(s):
    r = None
    try:
        r = datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
    except ValueError, e:
        pass
    return r

def validate_email(email):
    r = r'^(?#Start of dot-atom)[-!#\$%&\'\*\+\/=\?\^_`{}\|~0-9A-Za-z]+(?:\.[-!#\$%&\'\*\+\/=\?\^_`{}\|~0-9A-Za-z]+)*(?#End of dot-atom)(?:@(?#Start of domain)[-0-9A-Za-z]+(?:\.[-0-9A-Za-z]+)+(?#End of domain))$'
    return re.match(r, email)

def validate_mobile(mobile):
    r = r'\d{11}'
    return re.match(r, mobile)

def htmlspecialchars(text, ent_quotes=False):
    if not text:
        return u''
    text = text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    if ent_quotes:
        text = text.replace("'", "&apos;");
    return text

def htmlspecialchars_decode(text, ent_quotes=False):
    if not text:
        return u''
    text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    if ent_quotes:
        text = text.replace("&apos;", "'");
    return text

def str_split(s, split_length=1):
    return filter(None, re.split('(.{1,%d})' % split_length, s))

def remove_spaces(s):
    pattern = '|'.join(string.whitespace)
    return re.sub(pattern, '', s)

def generate_long_id():
    time.sleep(0.000001) #magic
    return int(time.time() * 1000000) * 100 + random.randrange(100)

def get_today_timestamp():
    return calendar.timegm(datetime.date.today().timetuple())

def base64_url_decode(inp):
    return base64.urlsafe_b64decode(str(inp + '=' * (4 - len(inp) % 4)))

def base64_url_encode(inp):
    return base64.urlsafe_b64encode(str(inp)).rstrip('=')

class AESCipher:

    def __init__( self, key ):
        self.key = key
        self.BS = 16

    def pad(self, s):
        return s + (self.BS - len(s) % self.BS) * chr(self.BS - len(s) % self.BS)

    def unpad(self, s):
        return s[:-ord(s[len(s)-1:])]

    def encrypt(self, raw):
        raw = self.pad(raw)
        iv = Random.new().read(AES.block_size)
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return base64.b64encode(iv + cipher.encrypt(raw))

    def decrypt(self, enc):
        enc = base64.b64decode(enc)
        iv = enc[:16]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        return self.unpad(cipher.decrypt(enc[16:]))

def get_total_seconds(td):
    return (td.microseconds + (td.seconds + td.days * 24 * 3600) * 1e6) / 1e6

def next_weekdays(today, weekdays, num_days):
    if not weekdays:
        return []
    if num_days < 0 or num_days > 100:
        return None
    day = 1
    next_days = []
    while len(next_days) < num_days:
        next_day = today + datetime.timedelta(days=day)
        if datetime.date.isoweekday(next_day) in weekdays:
            next_days.append(next_day)
            print next_day, next_day.isocalendar()
        day += 1
    return next_days

def partition(alist, indices):
    return [alist[i:j] for i, j in zip([0]+indices, indices+[None])]

def download_file(url, filename):
    r = requests.get(url, stream=True)
    with open(filename, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk: # filter out keep-alive new chunks
                f.write(chunk)
                f.flush()
    return filename

class RangeCheck:

    def __init__(self, value, value_cast, allow_none=False):
        try:
            self.value = value_cast(value)
        except ValueError, e:
            error(10011, {'value': value})
        self.value_type = value
        self.allow_none = allow_none
        self.evaluation = []

    def check(self):
        if self.allow_none and self.value is None:
            return self.value, False
        result = all(ev(self.value) for ev in self.evaluation)
        print type(self.value), self.value
        return self.value, result

    def is_one_of(self, choices):
        try:
            choices_ = iter(choices)
        except TypeError, e:
            self.evaluation.append(lambda x: False)
            return self
        self.evaluation.append(lambda x: x in choices_)
        return self

    def min(self, value):
        if type(self.value) != type(value):
            self.evaluation.append(lambda x: False)
            return self
        self.evaluation.append(lambda x: x >= value)
        return self

    def max(self, value):
        if type(self.value) != type(value):
            self.evaluation.append(lambda x: False)
            return self
        self.evaluation.append(lambda x: x <= value)
        return self

    def equals(self, value):
        if type(self.value) != type(value):
            self.evaluation.append(lambda x: False)
            return self
        self.evaluation.append(lambda x: x == value)
        return self

    def not_equal(self, value):
        if type(self.value) != type(value):
            self.evaluation.append(lambda x: False)
            return self
        self.evaluation.append(lambda x: x != value)
        return self

    def less_than(self, value):
        return self.min(value).not_equal(value)

    def greater_than(self, value):
        return self.max(value).not_equal(value)

    def within(self, min, max):
        return self.min(min).max(max)

if __name__ == '__main__':
    assert RangeCheck(1, int).is_one_of(range(2)).check() == (1, True)
    assert RangeCheck(3, int).is_one_of(range(2)).check() == (3, False)
    assert RangeCheck(3, int).is_one_of(range(2)).check() == (3, False)
    assert RangeCheck(1, int).is_one_of([]).check() == (1, False)
    assert RangeCheck(1, int).is_one_of(None).check() == (1, False)
    assert RangeCheck(1, int).min(1).check() == (1, True)
    assert RangeCheck(1, int).max(1).check() == (1, True)
    assert RangeCheck(1, int).within(1, 2).check() == (1, True)
