"""Explicitly imported historic aggregates, separate from report documents."""
import json
from datetime import date


def ensure(c):
    c.execute('CREATE TABLE IF NOT EXISTS blackspot_history_imports (month TEXT PRIMARY KEY, source_date TEXT NOT NULL, snapshot TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS blackspot_history_versions (month TEXT NOT NULL, source_date TEXT NOT NULL, snapshot TEXT NOT NULL, PRIMARY KEY (month,source_date))')
    c.execute('CREATE TABLE IF NOT EXISTS blackspot_history_preferences (month TEXT PRIMARY KEY, source_date TEXT NOT NULL)')
    c.execute('INSERT INTO blackspot_history_versions (month,source_date,snapshot) SELECT month,source_date,snapshot FROM blackspot_history_imports WHERE 1=1 ON CONFLICT(month,source_date) DO NOTHING')


def save(connect,source_date,snapshot):
    day=date.fromisoformat(source_date)
    if day.isoformat()!=source_date:raise ValueError('统计日期无效。')
    # Store only aggregate statistics, never workbook rows or free-text reasons.
    clean={'cities':snapshot['cities'],'total':snapshot['total']}
    encoded=json.dumps(clean,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    with connect() as c:
        ensure(c)
        month=source_date[:7]
        existing=c.execute('SELECT source_date,snapshot FROM blackspot_history_versions WHERE month=? AND source_date=?',(month,source_date)).fetchone()
        if existing:
            if json.loads(existing[1])!=clean:raise ValueError('该日期已有不同的历史统计，未覆盖，请先核对。')
            return False
        previous=c.execute('SELECT source_date FROM blackspot_history_versions WHERE month=? ORDER BY source_date DESC',(month,)).fetchone()
        if previous:c.execute('INSERT INTO blackspot_history_preferences (month,source_date) VALUES (?,?) ON CONFLICT(month) DO NOTHING',(month,previous[0]))
        c.execute('INSERT INTO blackspot_history_versions (month,source_date,snapshot) VALUES (?,?,?)',(month,source_date,encoded))
    return True


def versions(connect,month):
    date.fromisoformat(month+'-01')
    with connect() as c:
        ensure(c)
        rows=c.execute('SELECT source_date FROM blackspot_history_versions WHERE month=? ORDER BY source_date DESC',(month,)).fetchall()
        preference=c.execute('SELECT source_date FROM blackspot_history_preferences WHERE month=?',(month,)).fetchone()
    return {'month':month,'dates':[r[0] for r in rows],'selected':preference[0] if preference and any(r[0]==preference[0] for r in rows) else (rows[0][0] if rows else None)}


def select_version(connect,month,source_date):
    date.fromisoformat(month+'-01')
    if not isinstance(source_date,str) or date.fromisoformat(source_date).isoformat()!=source_date or not source_date.startswith(month+'-'):raise ValueError('历史版本日期无效。')
    with connect() as c:
        ensure(c)
        if not c.execute('SELECT source_date FROM blackspot_history_versions WHERE month=? AND source_date=?',(month,source_date)).fetchone():raise ValueError('未找到该历史版本。')
        c.execute('INSERT INTO blackspot_history_preferences (month,source_date) VALUES (?,?) ON CONFLICT(month) DO UPDATE SET source_date=excluded.source_date',(month,source_date))


def resolve(connect,month,expected_period,source_reader=None):
    if source_reader:row=source_reader(expected_period)
    else:
        with connect() as c:row=c.execute('SELECT data,monthly_data,weekly,monthly FROM reports WHERE period=?',(expected_period,)).fetchone()
    if row and (row[2] or row[3]):
        kind='月报' if row[3] and row[1] else '周报' if row[2] else '月报'
        return row,{'period':expected_period,'kind':kind}
    with connect() as c:
        ensure(c)
        saved=c.execute('SELECT v.source_date,v.snapshot FROM blackspot_history_versions v LEFT JOIN blackspot_history_preferences p ON v.month=p.month WHERE v.month=? ORDER BY CASE WHEN v.source_date=p.source_date THEN 0 ELSE 1 END,v.source_date DESC',(month,)).fetchone()
    if saved:return (saved[1],None,'历史汇总',''),{'period':saved[0],'kind':'历史工单表汇总'}
    return None,None
