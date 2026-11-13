"""Monthly resolution alerts. Scheduling creates drafts; only user actions send."""
import hashlib
import json
import re
import logging
from datetime import datetime, timedelta
from fractions import Fraction
from threading import Event, Thread

from core import CITIES
from mailing import ADDRESS
from ranking_planner import execute as rank
from smart_query import _last_friday
from suspension import previous_month
import alert_rules


def ensure(c):
    c.execute('CREATE TABLE IF NOT EXISTS city_alert_contacts (city TEXT PRIMARY KEY, email TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS city_alert_batches (month TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, source_date TEXT NOT NULL, source_kind TEXT NOT NULL, created_at TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS city_alert_items (month TEXT NOT NULL, city TEXT NOT NULL, details TEXT NOT NULL, status TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (month,city))')
    c.execute('CREATE TABLE IF NOT EXISTS city_alert_schedule (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, hour INTEGER NOT NULL, minute INTEGER NOT NULL, checked_at TEXT NOT NULL, checked_month TEXT NOT NULL, result TEXT NOT NULL)')
    c.execute("INSERT INTO city_alert_schedule (id,enabled,hour,minute,checked_at,checked_month,result) VALUES ('default',0,18,0,'','','') ON CONFLICT(id) DO NOTHING")


def now_text():return datetime.now().isoformat(timespec='seconds')


def contacts(connect):
    with connect() as c:
        ensure(c);rows=c.execute('SELECT city,email FROM city_alert_contacts').fetchall()
    saved=dict(rows)
    return [{'city':city,'email':saved.get(city,'')} for city in CITIES]


def save_contacts(connect,items):
    if not isinstance(items,dict) or any(city not in CITIES for city in items):raise ValueError('地市联系人格式无效。')
    clean={}
    for city,value in items.items():
        if not isinstance(value,str):raise ValueError('邮箱格式无效。')
        value=value.strip()
        if value and (len(value)>254 or not ADDRESS.fullmatch(value)):raise ValueError(city+'的邮箱地址无效，请填写一个有效地址。')
        clean[city]=value
    with connect() as c:
        ensure(c)
        for city,email in clean.items():c.execute('INSERT INTO city_alert_contacts (city,email) VALUES (?,?) ON CONFLICT(city) DO UPDATE SET email=excluded.email',(city,email))


def calculate(connect,month,*,source_reader=None,suspension_reader=None,require_month_end=False):
    _last_friday(month)
    rules=alert_rules.get(connect)
    custom=rules!=alert_rules.DEFAULT
    if custom:
        entries,details=alert_rules.evaluate(connect,month,rules,source_reader=source_reader,suspension_reader=suspension_reader)
        source=details['source'];rows=entries
        if not source:raise ValueError('统计来源不可用，请核对数据。')
    else:
        result=rank({'month':month,'direction':'asc','limit':3},connect,source_reader=source_reader)
        if not result.get('available') or not result.get('table'):raise ValueError(result.get('reply','该月数据不可用。'))
        source=result['source_info'];rows=result['table']['rows']
    if require_month_end and source['period']!=_last_friday(month):raise ValueError('暂未保存当月最后一个周五的数据，请导入后重新检查。')
    # Hash only the public summary used for these drafts, never raw work orders.
    payload=details if custom else {'source':source,'rows':rows}
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return source,rows,fingerprint


def generate(connect,month,*,source_reader=None,suspension_reader=None,require_month_end=False,replace_drafts=False):
    source,rows,fingerprint=calculate(connect,month,source_reader=source_reader,suspension_reader=suspension_reader,require_month_end=require_month_end)
    stamp=now_text()
    with connect() as c:
        ensure(c)
        c.execute('INSERT INTO city_alert_batches (month,fingerprint,source_date,source_kind,created_at) VALUES (?,?,?,?,?) ON CONFLICT(month) DO NOTHING',(month,fingerprint,source['period'],source['kind'],stamp))
        # Lock the batch before checking drafts, also serializing against send.
        c.execute('UPDATE city_alert_batches SET fingerprint=fingerprint WHERE month=?',(month,))
        batch=c.execute('SELECT fingerprint FROM city_alert_batches WHERE month=?',(month,)).fetchone()
        if not batch:raise ValueError('无法读取该月告警批次。')
        if batch[0]!=fingerprint:
            if not replace_drafts:raise ValueError('该月已有不同版本的告警草稿或记录，未覆盖，请先核对。')
            pending=c.execute("SELECT COUNT(*) FROM city_alert_items WHERE month=? AND status IN ('sending','unknown')",(month,)).fetchone()[0]
            if pending:raise ValueError('请先核对发送中或状态不明的记录，再更新草稿。')
            c.execute("DELETE FROM city_alert_items WHERE month=? AND status='draft'",(month,))
            c.execute('UPDATE city_alert_batches SET fingerprint=?,source_date=?,source_kind=?,created_at=? WHERE month=?',(fingerprint,source['period'],source['kind'],stamp,month))
        count=0
        for entry in rows:
            if isinstance(entry[4],list):city,rate,qualified,included,reasons=entry;position=None
            else:position,city,rate,qualified,included=entry;reasons=['解决率倒数靠前']
            detail={'rank':position,'rate':rate,'qualified':qualified,'included':included,'period':source['period'],'source':source['kind']}
            detail['reasons']=reasons
            subject=f'{month}重点投诉区域解决情况提醒'
            rate_text='由于确认纳入数为零，解决率无法计算' if rate=='无分母' else f'解决率为{rate}'
            body=(f'{city}市同事：\n\n截至{source["period"]}，贵市重点投诉区域确认纳入{included}处，质检合格{qualified}处，'
                  f'{rate_text}。关注原因：{"、".join(reasons)}。请结合实际整治进展，关注尚未质检合格的区域，推动相关建设与优化工作。\n\n'
                  '解决率按质检合格数除以确认纳入数计算；具体推进措施请结合实际情况核实。')
            cur=c.execute("INSERT INTO city_alert_items (month,city,details,status,recipient,subject,body,updated_at) VALUES (?,?,?,'draft','',?,?,?) ON CONFLICT(month,city) DO NOTHING",(month,city,json.dumps(detail,ensure_ascii=False),subject,body,stamp))
            count+=cur.rowcount
    return {'month':month,'created':count,'cities':len(rows),'period':source['period'],'source':source['kind']}


def list_alerts(connect,month):
    _last_friday(month)
    with connect() as c:
        ensure(c)
        batch=c.execute('SELECT source_date,source_kind,created_at FROM city_alert_batches WHERE month=?',(month,)).fetchone()
        rows=c.execute('SELECT i.city,i.details,i.status,i.recipient,i.subject,i.body,i.updated_at,co.email FROM city_alert_items i LEFT JOIN city_alert_contacts co ON i.city=co.city WHERE i.month=? ORDER BY i.city',(month,)).fetchall()
    return {'month':month,'batch':{'period':batch[0],'source':batch[1],'created_at':batch[2]} if batch else None,'items':[{'city':r[0],'details':json.loads(r[1]),'status':r[2],'recipient':r[3] or r[7] or '', 'recipient_from_contact':not bool(r[3]), 'subject':r[4],'body':r[5],'updated_at':r[6]} for r in rows]}


def prepare_send(connect,month,city,recipient,subject,body,expected_fingerprint):
    _last_friday(month)
    if city not in CITIES:raise ValueError('地市无效。')
    if not isinstance(recipient,str) or len(recipient.strip())>254 or not ADDRESS.fullmatch(recipient.strip()):raise ValueError('请输入一个有效的收件邮箱。')
    if not isinstance(subject,str) or not subject.strip() or len(subject)>200 or '\n' in subject or '\r' in subject:raise ValueError('邮件主题无效。')
    if not isinstance(body,str) or not body.strip() or len(body)>10000:raise ValueError('请填写不超过 10000 字的邮件正文。')
    with connect() as c:
        ensure(c)
        c.execute('UPDATE city_alert_batches SET fingerprint=fingerprint WHERE month=?',(month,))
        batch=c.execute('SELECT fingerprint FROM city_alert_batches WHERE month=?',(month,)).fetchone()
        if not batch or batch[0]!=expected_fingerprint:raise ValueError('本期数据已变化，请更新草稿并重新核对。')
        result=c.execute("UPDATE city_alert_items SET status='sending',recipient=?,subject=?,body=?,updated_at=? WHERE month=? AND city=? AND status='draft'",(recipient.strip(),subject.strip(),body,now_text(),month,city))
        if result.rowcount!=1:raise ValueError('草稿不存在、正在发送或已有发送记录，请先核对。')


def finish_send(connect,month,city,status):
    if status not in ('sent','unknown','draft'):raise ValueError('状态无效。')
    with connect() as c:c.execute("UPDATE city_alert_items SET status=?,updated_at=? WHERE month=? AND city=? AND status='sending'",(status,now_text(),month,city))


def reset_uncertain(connect,month,city):
    _last_friday(month)
    if city not in CITIES:raise ValueError('地市无效。')
    cutoff=(datetime.now()-timedelta(minutes=5)).isoformat(timespec='seconds')
    with connect() as c:
        ensure(c)
        c.execute('UPDATE city_alert_batches SET fingerprint=fingerprint WHERE month=?',(month,))
        changed=c.execute("UPDATE city_alert_items SET status='draft',updated_at=? WHERE month=? AND city=? AND (status='unknown' OR (status='sending' AND updated_at<=?))",(now_text(),month,city,cutoff))
        if changed.rowcount!=1:raise ValueError('该记录无法恢复；发送中请稍候，已发送的记录不能恢复。')


def schedule(connect):
    with connect() as c:
        ensure(c);r=c.execute("SELECT enabled,hour,minute,checked_at,checked_month,result FROM city_alert_schedule WHERE id='default'").fetchone()
    return {'enabled':bool(r[0]),'hour':r[1],'minute':r[2],'checked_at':r[3],'checked_month':r[4],'result':r[5]}


def set_schedule(connect,enabled,hour,minute):
    if type(enabled)!=bool or type(hour)!=int or type(minute)!=int or not 0<=hour<=23 or not 0<=minute<=59:raise ValueError('定时设置无效。')
    with connect() as c:
        ensure(c);c.execute("UPDATE city_alert_schedule SET enabled=?,hour=?,minute=?,checked_at='' WHERE id='default'",(int(enabled),hour,minute))


def due_month(now,hour,minute):
    month=now.strftime('%Y-%m');last=datetime.fromisoformat(_last_friday(month)).replace(hour=hour,minute=minute)
    return month if now>=last else previous_month(month)


def check_due(connect,*,source_reader=None,suspension_reader=None,now=None):
    now=now or datetime.now();config=schedule(connect)
    if not config['enabled']:return None
    # On first start and after downtime check the latest due month, not every missed month.
    if config['checked_at']:
        try:
            if now-datetime.fromisoformat(config['checked_at'])<timedelta(minutes=15):return None
        except ValueError:pass
    month=due_month(now,config['hour'],config['minute'])
    try:
        result=generate(connect,month,source_reader=source_reader,suspension_reader=suspension_reader,require_month_end=True)
        message=f"已检查 {month}，新增 {result['created']} 条待核对草稿。"
    except ValueError as exc:message=f'{month} 检查未完成：{exc}'
    with connect() as c:
        ensure(c);c.execute("UPDATE city_alert_schedule SET checked_at=?,checked_month=?,result=? WHERE id='default'",(now.isoformat(timespec='seconds'),month,message))
    return message


def start_worker(connect,source_reader=None,suspension_reader=None):
    stop=Event()
    def loop():
        while not stop.is_set():
            try:check_due(connect,source_reader=source_reader,suspension_reader=suspension_reader)
            except Exception:logging.warning('告警定时检查暂不可用，请检查本机数据库连接。')
            stop.wait(60)
    Thread(target=loop,name='zhihui-alert-scheduler',daemon=True).start()
    return stop
