"""Minimal, local-only blackspot area records for the dashboard."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from openpyxl import load_workbook
from core import CITIES

FIELDS={'included':'是否已生成黑点编号','city':'地市','name':'黑点名称','kind':'黑点类型','entered':'入库时间','status':'当前节点名称-2'}

def extract(stream):
    try:
        workbook=load_workbook(stream,read_only=True,data_only=True)
    except Exception as exc:raise ValueError('无法读取 Excel，请选择有效的 .xlsx 文件。') from exc
    try:
        if '汇聚黑点-汇总' not in workbook:raise ValueError('缺少「汇聚黑点-汇总」工作表。')
        rows=workbook['汇聚黑点-汇总'].iter_rows(values_only=True)
        header=next(rows,())
        indexes={}
        for key,label in FIELDS.items():
            found=[i for i,x in enumerate(header) if x==label]
            if len(found)!=1:raise ValueError(f'明细缺少或重复字段「{label}」。')
            indexes[key]=found[0]
        result=[]
        for row in rows:
            get=lambda key:row[indexes[key]] if indexes[key]<len(row) else None
            if get('included')!='是':continue
            city=str(get('city') or '').strip()
            if city not in CITIES:raise ValueError('明细中存在无法识别的地市，请核对原表。')
            def clean(key,limit):
                value=get(key)
                if value is None:return ''
                return str(value).strip()[:limit]
            raw=get('entered');entered=''
            if isinstance(raw,datetime):entered=raw.isoformat(sep=' ',timespec='minutes')
            elif isinstance(raw,date):entered=raw.isoformat()
            elif raw:
                try:entered=datetime.fromisoformat(str(raw).strip()).isoformat(sep=' ',timespec='minutes')
                except ValueError:entered=''
            result.append({'city':city,'name':clean('name',160),'kind':clean('kind',60),'entered':entered,'status':clean('status',60)})
            if len(result)>20000:raise ValueError('明细数量超过导入上限，请核对原表。')
        return result
    finally:workbook.close()

def filename_date(filename):
    dates=set()
    for match in re.finditer(r'(?<!\d)(20\d{2})[-_.年]?(\d{2})[-_.月]?(\d{2})(?:日)?(?!\d)',filename or ''):
        try:dates.add(date(*map(int,match.groups())).isoformat())
        except ValueError:pass
    if len(dates)!=1:raise ValueError('无法从文件名唯一识别统计日期，请使用带日期的原始工单表。')
    return dates.pop()

def ensure(c):
    c.execute('CREATE TABLE IF NOT EXISTS blackspot_detail_snapshots (period TEXT PRIMARY KEY, digest TEXT NOT NULL, records TEXT NOT NULL, stale INTEGER NOT NULL DEFAULT 0)')

class Conflict(ValueError):
    def __init__(self,revision):
        super().__init__('该日期已有不同明细，请核对后再决定是否替换。')
        self.revision=revision

def save(c,period,records,expected_revision=None):
    if date.fromisoformat(period).isoformat()!=period:raise ValueError('统计日期无效。')
    encoded=json.dumps(records,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    digest=hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    ensure(c)
    old=c.execute('SELECT digest,stale FROM blackspot_detail_snapshots WHERE period=?',(period,)).fetchone()
    if old and old[0]!=digest:
        if expected_revision!=old[0]:raise Conflict(old[0])
        updated=c.execute('UPDATE blackspot_detail_snapshots SET digest=?,records=?,stale=0 WHERE period=? AND digest=?',(digest,encoded,period,old[0]))
        if updated.rowcount!=1:raise ValueError('明细在操作期间发生变化，请刷新后重新核对。')
        return True
    if old:
        if old[1]:c.execute('UPDATE blackspot_detail_snapshots SET stale=0 WHERE period=? AND digest=?',(period,digest))
        return False
    c.execute('INSERT INTO blackspot_detail_snapshots (period,digest,records,stale) VALUES (?,?,?,0)',(period,digest,encoded))
    return True

def read(c,period,window='30',offset=0):
    day=date.fromisoformat(period)
    if day.isoformat()!=period or window not in ('30','all') or type(offset) is not int or not 0<=offset<=20000:raise ValueError('明细查询条件无效。')
    ensure(c)
    row=c.execute('SELECT records,stale FROM blackspot_detail_snapshots WHERE period=?',(period,)).fetchone()
    if not row:return {'period':period,'available':False,'items':[],'total':0,'notice':'该期尚未导入区域明细，请选择对应日期的工单表。'}
    if row[1]:return {'period':period,'available':False,'items':[],'total':0,'notice':'该期报告已更新，请重新核对并导入相同版本的明细。'}
    records=json.loads(row[0]);start=day-timedelta(days=29)
    def eligible(item):
        if window=='all':return True
        try: entered=date.fromisoformat(item.get('entered','')[:10]);return start<=entered<=day
        except (ValueError,TypeError):return False
    chosen=sorted((r for r in records if eligible(r)),key=lambda r:r.get('entered') or '',reverse=True)
    return {'period':period,'available':True,'items':chosen[offset:offset+5],'total':len(chosen),'offset':offset,'start':start.isoformat() if window=='30' else None,'window':window}
