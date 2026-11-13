"""Short-lived, server-side copies of reports explicitly prepared for review."""
from collections import OrderedDict
from threading import RLock
from time import monotonic
from uuid import uuid4
from html import escape

_lock=RLock()
_reports=OrderedDict()
_ttl=3600
_capacity=32


def save(month,html):
    with _lock:
        now=monotonic()
        for key in list(_reports):
            if now-_reports[key]['created']>_ttl:del _reports[key]
        while len(_reports)>=_capacity:_reports.popitem(last=False)
        key=uuid4().hex
        _reports[key]={'month':month,'html':html,'created':now,'state':'ready'}
        return key


def begin(key):
    with _lock:
        item=_reports.get(key)
        if not item or monotonic()-item['created']>_ttl:raise ValueError('报告预览已过期，请重新生成并核对。')
        if item['state']!='ready':raise ValueError('该报告正在发送或已发送，请检查发件箱；如需再次发送请重新生成。')
        item['state']='sending'
        return item['month'],item['html']


def finish(key,state):
    with _lock:
        if key in _reports:_reports[key]['state']=state


def email_html(html,body):
    intro='<div style="font-family:Arial,sans-serif;white-space:pre-wrap;margin:20px;">'+escape(body)+'</div>'
    marker='<body>'
    if marker not in html:raise ValueError('报告格式无效，请重新生成。')
    return html.replace(marker,marker+intro,1)
