# -*- coding: utf-8 -*-

import config
import pymysql
import redis
import time

rds = redis.Redis(**config.REDIS)

class MySQL():

    def __init__(self, config):
        self.config = config
        self.conn = pymysql.connect(**config)
        self.timestamp = time.time()

    def reconnect(self):
        new_ts = time.time()
        if new_ts - self.timestamp > 3600:
            try:
                self.conn.close()
            except pymysql.OperationalError, e:
                print e
                pass
            self.conn = pymysql.connect(**self.config)
        self.timestamp = new_ts

    def execute_once(self, query, params):
        self.reconnect()
        cur = self.conn.cursor()
        result = cur.execute(query, params)
        cur.nextset()
        cur.close()
        return result

    def insert_and_get_id(self, query, params):
        self.reconnect()
        cur = self.conn.cursor()
        result = cur.execute(query, params)
        last_id = None
        if result:
            last_id = self.conn.insert_id()
        cur.nextset()
        cur.close()
        return last_id

    def fetch_one(self, query, params):
        self.reconnect()
        cur = self.conn.cursor(pymysql.cursors.DictCursor)
        result = cur.execute(query, params)
        if not result:
            return
        rlt = cur.fetchone()
        cur.nextset()
        cur.close()
        return rlt

    def fetch_all(self, query, params):
        self.reconnect()
        cur = self.conn.cursor(pymysql.cursors.DictCursor)
        result = cur.execute(query, params)
        if not result:
            return []
        rlt = list(cur.fetchall())
        cur.nextset()
        cur.close()
        return rlt

mysql_conn = MySQL(config.MYSQL)
