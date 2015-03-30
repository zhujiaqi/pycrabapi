# -*- coding: utf-8 -*-

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

#format your objects before sending responses

#sample
def format_account(account):
    return {
        'id': account['id'],
    }
