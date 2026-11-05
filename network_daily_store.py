"""Local, provenance-preserving import of network operations history."""
import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

METRICS = set('''tch_traffic_sum volte_voice_traffic vonr_voice_traffic gsm_traffic_rate wirelessconn_rate enb_suc_rate wirelessdrop_rate lte_upoct wirelessconn_rate_5g enb_suc_rate_5g wirelessdrop_rate_5g nr_upoct upoct_700 split_flow_rate upoctul_user_rate upoctdl_user_rate upoctul_user_rate_5g upoctdl_user_rate_5g epsfb_fallback_succ_rate vonr_active_users low2high2_rate lowdatauser_rate volte_online_users nr_terminal_users lte_online_users nr_login_users_mon nr_terminal_login_users_day tch_traffic_sum_mom volte_voice_traffic_mom vonr_voice_traffic_mom lte_upoct_mom nr_upoct_mom upoct_700_mom vonr_active_users_mom volte_online_users_mom nr_terminal_users_mom lte_online_users_mom nr_terminal_login_users_day_mom voice_45g_fallback_2g data_perception_rate camping_ratio inefficiency_5g'''.split())
REGIONS=set('安庆 蚌埠 亳州 池州 滁州 阜阳 合肥 淮北 淮南 黄山 六安 马鞍山 宿州 铜陵 芜湖 宣城 安徽省'.split())

def digest(data): return hashlib.sha256(data).hexdigest()

def parse_report(data):
    try: text=data.decode('utf-8-sig')
    except UnicodeDecodeError: raise ValueError('日报文本不是 UTF-8 格式。')
    match=re.search(r'全省无线网络运行日报\s*[（(]\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*[）)]',text[:300])
    if not match: raise ValueError('日报标题中没有可识别的统计日期。')
    try: day=date(*map(int,match.groups())).isoformat()
    except ValueError: raise ValueError('日报标题中的日期无效。')
    return {'date':day,'text':text,'hash':digest(data)}

def parse_csv(data):
    try: text=data.decode('utf-8-sig')
    except UnicodeDecodeError:
        try: text=data.decode('gb18030')
        except UnicodeDecodeError: raise ValueError('CSV 编码无法识别。')
    reader=csv.DictReader(io.StringIO(text, newline=''))
    if not reader.fieldnames: raise ValueError('CSV 缺少表头。')
    headers=[x.strip().lower() for x in reader.fieldnames]
    if len(set(headers))!=len(headers) or not {'scan_start_time','region_name'} <= set(headers): raise ValueError('CSV 日期或地市表头无效。')
    if not (set(headers)&METRICS): raise ValueError('CSV 中没有可识别的网络指标。')
    if set(headers)-METRICS-{'scan_start_time','region_name'}: raise ValueError('CSV 含有未识别的列，请先核对。')
    reader.fieldnames=headers
    groups=defaultdict(dict); rows=0
    for row in reader:
        rows+=1
        if None in row or any(v is None for v in row.values()): raise ValueError('CSV 数据列数与表头不一致。')
        try: day=date.fromisoformat(row['scan_start_time'].strip()).isoformat()
        except ValueError: raise ValueError('CSV 中有无效日期。')
        region=row['region_name'].strip()
        if region not in REGIONS: raise ValueError('CSV 中有未识别的地市名称。')
        metrics={}
        for key in sorted(set(headers)&METRICS):
            value=row[key].strip()
            if value.lower() in ('','null','-'): metrics[key]=None; continue
            try: num=Decimal(value)
            except InvalidOperation: raise ValueError('CSV 中有无效的指标数值。')
            if not num.is_finite(): raise ValueError('CSV 中有无效的指标数值。')
            metrics[key]=value
        encoded=json.dumps(metrics,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        groups[(day,region)][digest(encoded.encode('utf-8'))]=encoded
    if not rows: raise ValueError('CSV 没有数据。')
    distinct=sum(len(v) for v in groups.values())
    return {'hash':digest(data),'groups':groups,'rows':rows,'exact_duplicates':rows-distinct,'conflict_groups':sum(len(v)>1 for v in groups.values()),'dates':sorted({d for d,_ in groups})}

def import_history(connection, reports, csv_data):
    # Parsing precedes every database write so invalid input cannot create partial imports.
    parsed_reports=[parse_report(data) for data in reports]
    parsed_csv=parse_csv(csv_data) if csv_data else None
    if not parsed_reports and not parsed_csv: raise ValueError('请选择日报或 CSV。')
    connection.execute('CREATE TABLE IF NOT EXISTS network_import_sources (source_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, imported_at TEXT NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS network_daily_reports (report_date TEXT NOT NULL, content_sha256 TEXT NOT NULL, content TEXT NOT NULL, source_id TEXT NOT NULL, review_status TEXT NOT NULL, PRIMARY KEY(report_date,content_sha256))')
    connection.execute('CREATE TABLE IF NOT EXISTS network_daily_indicators (source_id TEXT NOT NULL, report_date TEXT NOT NULL, region TEXT NOT NULL, metrics_sha256 TEXT NOT NULL, metrics_json TEXT NOT NULL, quality_status TEXT NOT NULL, PRIMARY KEY(source_id,report_date,region,metrics_sha256))')
    now=datetime.now(timezone.utc).isoformat()
    added_reports=0
    for report in parsed_reports:
        source='report-'+report['hash']
        c=connection.execute('INSERT INTO network_import_sources VALUES (?,?,?) ON CONFLICT DO NOTHING',(source,'report',now))
        if c.rowcount:
            connection.execute('INSERT INTO network_daily_reports VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING',(report['date'],report['hash'],report['text'],source,'pending_review'))
            added_reports+=1
    csv_added=False
    if parsed_csv:
        source='csv-'+parsed_csv['hash']
        c=connection.execute('INSERT INTO network_import_sources VALUES (?,?,?) ON CONFLICT DO NOTHING',(source,'csv',now))
        if c.rowcount:
            csv_added=True
            for (day,region), variants in parsed_csv['groups'].items():
                quality='conflict' if len(variants)>1 else 'unreviewed'
                for item_hash,encoded in variants.items():
                    connection.execute('INSERT INTO network_daily_indicators VALUES (?,?,?,?,?,?)',(source,day,region,item_hash,encoded,quality))
    result={'report_dates':sorted({r['date'] for r in parsed_reports}),'new_reports':added_reports}
    if parsed_csv: result['csv']={'new_source':csv_added,'rows':parsed_csv['rows'],'exact_duplicates':parsed_csv['exact_duplicates'],'conflict_groups':parsed_csv['conflict_groups'],'first_date':parsed_csv['dates'][0],'last_date':parsed_csv['dates'][-1]}
    return result
