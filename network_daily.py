"""Database-backed network daily reports. No data is sent to a model."""
import json
from historical_report_tables import parse as parse_historical_tables
import re
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from datetime import date, datetime, timezone

TABLE_FIELDS=('vonr_active_users','nr_terminal_users','nr_terminal_login_users_day','nr_login_users_mon','lte_online_users','volte_online_users','nr_upoct','lte_upoct','split_flow_rate','upoct_700','lowdatauser_rate','upoctul_user_rate','upoctdl_user_rate','upoctul_user_rate_5g','upoctdl_user_rate_5g','vonr_voice_traffic','volte_voice_traffic','tch_traffic_sum','gsm_traffic_rate','wirelessconn_rate_5g','enb_suc_rate_5g','wirelessdrop_rate_5g','epsfb_fallback_succ_rate','wirelessconn_rate','enb_suc_rate','wirelessdrop_rate','low2high2_rate')

METRICS=[('nr_upoct','5G 数据流量','TB'),('lte_upoct','4G 数据流量','TB'),('split_flow_rate','5G 分流比','%'),('nr_terminal_login_users_day','5G 当日登录用户','万户')]

def schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS network_import_sources (source_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, imported_at TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS network_daily_reports (report_date TEXT NOT NULL, content_sha256 TEXT NOT NULL, content TEXT NOT NULL, source_id TEXT NOT NULL, review_status TEXT NOT NULL, PRIMARY KEY(report_date,content_sha256))')
    c.execute('CREATE TABLE IF NOT EXISTS network_daily_indicators (source_id TEXT NOT NULL, report_date TEXT NOT NULL, region TEXT NOT NULL, metrics_sha256 TEXT NOT NULL, metrics_json TEXT NOT NULL, quality_status TEXT NOT NULL, PRIMARY KEY(source_id,report_date,region,metrics_sha256))')
    c.execute('CREATE TABLE IF NOT EXISTS network_daily_drafts (report_date TEXT PRIMARY KEY, content TEXT NOT NULL, updated_at TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS network_daily_documents (report_date TEXT PRIMARY KEY, document_json TEXT NOT NULL, updated_at TEXT NOT NULL)')

def validate_date(value):
    if not isinstance(value,str) or len(value)!=10: raise ValueError('请选择有效的统计日期。')
    try:
        if date.fromisoformat(value).isoformat()!=value: raise ValueError()
    except ValueError: raise ValueError('请选择有效的统计日期。')
    return value

def dates(c):
    schema(c)
    rows=c.execute('SELECT report_date FROM network_daily_reports UNION SELECT report_date FROM network_daily_indicators UNION SELECT report_date FROM network_daily_drafts UNION SELECT report_date FROM network_daily_documents ORDER BY report_date DESC').fetchall()
    return [r[0] for r in rows]

def detail(c, day):
    validate_date(day); schema(c)
    raw=c.execute('SELECT content_sha256, content FROM network_daily_reports WHERE report_date=? ORDER BY content_sha256',(day,)).fetchall()
    draft=c.execute('SELECT content,updated_at FROM network_daily_drafts WHERE report_date=?',(day,)).fetchone()
    rows=c.execute('SELECT region,metrics_json,quality_status FROM network_daily_indicators WHERE report_date=? ORDER BY region',(day,)).fetchall()
    grouped=defaultdict(list)
    for region,data,quality in rows:
        grouped[region].append((json.loads(data),quality))
    regions={}; conflicts=[]; conflicted_fields={}
    for region,variants in grouped.items():
        combined={}; bad=set()
        for item,_ in variants:
            for key,value in item.items():
                if value is None: continue
                if key in combined:
                    try: same=Decimal(combined[key])==Decimal(value)
                    except (InvalidOperation,TypeError): same=combined[key]==value
                    if not same: bad.add(key)
                else: combined[key]=value
        for key in bad: combined[key]=None
        if bad: conflicts.append(region); conflicted_fields[region]=bad
        regions[region]=combined
    province=regions.get('安徽省')
    patterns={'nr_upoct':r'全省5G当日数据流量\s*([0-9]+(?:\.[0-9]+)?)\s*TB',
              'lte_upoct':r'4G当日数据流量\s*([0-9]+(?:\.[0-9]+)?)\s*TB',
              'split_flow_rate':r'5G分流比\s*([0-9]+(?:\.[0-9]+)?)\s*%'}
    available=[];metric_conflicts=[]
    for key,label,unit in METRICS:
        csv_value=province.get(key) if province else None
        matches=re.findall(patterns[key],raw[0][1]) if len(raw)==1 and key in patterns else []
        found={Decimal(value) for value in matches}; report_value=matches[0] if len(found)==1 else None
        conflict=len(found)>1 or key in conflicted_fields.get('安徽省',set())
        if csv_value is not None and report_value is not None:
            try: conflict=conflict or Decimal(csv_value)!=Decimal(report_value)
            except InvalidOperation: conflict=True
        if conflict:
            metric_conflicts.append(label); value=None; source='来源冲突'
        elif csv_value is not None: value=csv_value; source='CSV / 日报' if report_value is not None else 'CSV'
        elif report_value is not None: value=report_value; source='历史日报正文'
        else: value=None; source='暂无数据'
        available.append({'key':key,'label':label,'unit':unit,'value':value,'source':source})
    cities=[{'city':name,'five':data.get('nr_upoct'),'four':data.get('lte_upoct'),'split':data.get('split_flow_rate')} for name,data in sorted(regions.items()) if name!='安徽省']
    province_table={key:(province or {}).get(key) for key in TABLE_FIELDS}
    for metric in available:
        province_table[metric['key']]=metric['value']
    table_cities=[{'city':name,'values':{key:data.get(key) for key in TABLE_FIELDS}} for name,data in sorted(regions.items()) if name!='安徽省']
    return {'historical_tables':parse_historical_tables(raw[0][1]) if len(raw)==1 else [],'report_tables':{'province':province_table,'cities':table_cities},'date':day,'versions':[{'id':v[0]} for v in raw], 'original':raw[0][1] if len(raw)==1 else None,
            'draft':draft[0] if draft else None,'updated_at':draft[1] if draft else None,
            'metrics':available,'metric_conflicts':metric_conflicts,'cities':cities,'conflicts':conflicts,'has_indicators':bool(rows)}

def original(c,day,version):
    validate_date(day); schema(c)
    row=c.execute('SELECT content FROM network_daily_reports WHERE report_date=? AND content_sha256=?',(day,version)).fetchone()
    if not row: raise ValueError('该历史日报版本不存在。')
    return row[0]

def build_draft(data):
    day=data['date']; values={m['key']:m['value'] for m in data['metrics']}
    if not data['has_indicators']: raise ValueError('该日期没有入库的指标数据，不能自动生成草稿。')
    def metric(key,unit):
        value=values[key]
        return f'{value}{unit}' if value is not None else '【缺少数据，待补充】'
    return (f'全省无线网络运行日报（{day}）\n\n一、全网业务量及用户情况\n'
            f'全省5G当日数据流量{metric("nr_upoct","TB")}，4G当日数据流量{metric("lte_upoct","TB")}，'
            f'5G分流比{metric("split_flow_rate","%")}，5G当日登录用户{metric("nr_terminal_login_users_day","万户")}。\n\n'
            '二、无线网络运行质量\n【数据未接入，请补充并核对】\n\n'
            '三、投诉预警情况\n')

def save(c,day,text):
    validate_date(day)
    if not isinstance(text,str) or not text.strip() or len(text)>100000: raise ValueError('日报内容不能为空或超过 10 万字。')
    schema(c); now=datetime.now(timezone.utc).isoformat()
    c.execute('INSERT INTO network_daily_drafts VALUES (?,?,?) ON CONFLICT(report_date) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at',(day,text,now))
    return now
