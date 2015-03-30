# -*- coding: utf-8 -*-

import requests
from jinja2 import Template
import json
from simpleflake import simpleflake

from singletons import rds
import config

def get_mail_body(template_name, *args, **kwargs):
    body_html_template = Template(open('mail/' + template_name).read().decode('utf-8'))
    body_html = body_html_template.render(*args, **kwargs)
    return body_html

def mailgun_send(to, body, subject, attachments=None, campaign_id=None):
    if attachments is None:
        attachments = []
    if isinstance(to, (str, unicode)):
        to = [to]
    params = {
        'auth': ("api", config.MAILGUN_KEY),
        'data': {
            "from": config.MAIL_SENDER,
            "to": to,
            "subject": subject,
            "html": body,
            "text": 'Plain texts for clients without HTML supports',
            "h:Connection": 'close'
        }
    }
    if len(to) > 1:
        rv = {}
        for recipient in to:
            rv[recipient] = {'unique_id': simpleflake()}
        params['data']['recipient-variables'] = json.dumps(rv)
    if campaign_id:
        params['data']['o:campaign'] = campaign_id
    if config.STAGE == 'dev':
        params['data']['o:testmode'] = 'yes'
    attfs = []
    if attachments:
        params['files'] = []
        for att in attachments:
            attf = open(att)
            params['files'].append(('attachment', attf))
            attfs.append(attf)
    if config.STAGE == 'dev':
        print '========== mock send mail =========='
        print params
        print '===================================='
    rlt = requests.post(config.MAILGUN_PATH, **params)
    for attf in attfs:
        attf.close()
    return rlt

def send(to, body, subject):
    return mailgun_send(to, body, subject)
