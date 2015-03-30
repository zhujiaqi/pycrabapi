# -*- coding: utf-8 -*-

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from singletons import mysql_conn

#no ORM here, the idea is to wrap your db queries into functions before using them 

#sample
def get_account_by_id(user_id):
    account = mysql_conn.fetch_one('select * from users where id = %s limit 1', (user_id, ))
    return account
