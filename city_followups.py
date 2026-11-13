"""User-maintained follow-up records and read-only next-month comparisons."""
import re
from datetime import date,datetime
from fractions import Fraction
from uuid import uuid4

from core import CITIES
from smart_query import _last_friday,query
from suspension import previous_month

STATUSES=('待联系','推进中','已反馈','已完成')

def ensure(c):
    c.execute('CREATE TABLE IF NOT EXISTS city_followups (id TEXT PRIMARY KEY, month TEXT NOT NULL, city TEXT NOT NULL, issue TEXT NOT NULL, status TEXT NOT NULL, action TEXT NOT NULL, next_date TEXT NOT NULL, updated_at TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS city_followup_events (id TEXT PRIMARY KEY, record_id TEXT NOT NULL, captured_at TEXT NOT NULL, status TEXT NOT NULL, action TEXT NOT NULL, next_date TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS city_followup_event_context (event_id TEXT PRIMARY KEY, month TEXT NOT NULL, city TEXT NOT NULL, issue TEXT NOT NULL)')

def save(connect,payload):
    if not isinstance(payload,dict):raise ValueError('推进记录格式无效。')
    month=payload.get('month');city=payload.get('city');issue=payload.get('issue');status=payload.get('status');action=payload.get('action','');next_date=payload.get('next_date','');record_id=payload.get('id','')
    if not isinstance(month,str):raise ValueError('请选择统计月份。')
    _last_friday(month)
    if city not in CITIES:raise ValueError('请选择有效地市。')
    if not isinstance(issue,str) or not issue.strip() or len(issue)>300:raise ValueError('请填写不超过 300 字的关注事项。')
    if status not in STATUSES:raise ValueError('推进状态无效。')
    if not isinstance(action,str) or len(action)>2000:raise ValueError('推进措施不能超过 2000 字。')
    if not isinstance(next_date,str):raise ValueError('跟进日期无效。')
    if next_date:
        try:
            if date.fromisoformat(next_date).isoformat()!=next_date:raise ValueError()
        except ValueError:raise ValueError('跟进日期无效。')
    stamp=datetime.now().isoformat(timespec='microseconds')
    with connect() as c:
        ensure(c)
        if record_id:
            if not isinstance(record_id,str) or not re.fullmatch(r'[0-9a-f]{32}',record_id):raise ValueError('推进记录无效。')
            changed=c.execute('UPDATE city_followups SET month=?,city=?,issue=?,status=?,action=?,next_date=?,updated_at=? WHERE id=?',(month,city,issue.strip(),status,action.strip(),next_date,stamp,record_id))
            if changed.rowcount!=1:raise ValueError('该推进记录不存在，请刷新。')
        else:
            record_id=uuid4().hex
            c.execute('INSERT INTO city_followups (id,month,city,issue,status,action,next_date,updated_at) VALUES (?,?,?,?,?,?,?,?)',(record_id,month,city,issue.strip(),status,action.strip(),next_date,stamp))
        event_id=uuid4().hex
        c.execute('INSERT INTO city_followup_events (id,record_id,captured_at,status,action,next_date) VALUES (?,?,?,?,?,?)',(event_id,record_id,stamp,status,action.strip(),next_date))
        c.execute('INSERT INTO city_followup_event_context (event_id,month,city,issue) VALUES (?,?,?,?)',(event_id,month,city,issue.strip()))
    return record_id

def list_records(connect,*,source_reader=None,suspension_reader=None,month=None,city=None,include_comparison=True):
    conditions=[];parameters=[]
    if month is not None:
        _last_friday(month);conditions.append('month=?');parameters.append(month)
    if city is not None:
        if city not in CITIES:raise ValueError('请选择有效地市。')
        conditions.append('city=?');parameters.append(city)
    where=' WHERE '+' AND '.join(conditions) if conditions else ''
    with connect() as c:
        ensure(c)
        rows=c.execute('SELECT id,month,city,issue,status,action,next_date,updated_at FROM city_followups'+where+' ORDER BY updated_at DESC,id DESC LIMIT 100',tuple(parameters)).fetchall()
        events=[]
        if include_comparison and rows:
            markers=','.join('?' for _ in rows)
            events=c.execute('SELECT record_id,captured_at,status,action,next_date,month,city,issue FROM ('
                'SELECT e.record_id,e.captured_at,e.status,e.action,e.next_date,x.month,x.city,x.issue, '
                'ROW_NUMBER() OVER (PARTITION BY e.record_id ORDER BY e.captured_at DESC,e.id DESC) AS rn '
                'FROM city_followup_events e LEFT JOIN city_followup_event_context x ON e.id=x.event_id '
                'WHERE e.record_id IN ('+markers+')) ranked WHERE rn<=30 ORDER BY captured_at DESC',tuple(row[0] for row in rows)).fetchall()
    cache={};suspension_cache={}
    def values(month):
        if month not in cache:
            try:
                result=query(connect,'query_city_metrics',{'month':month,'city':'全部地市','metric':'解决率'},structured=True,source_reader=source_reader)
                table=(result.get('table') or {}).get('rows')
                if not result.get('available') or not table:cache[month]=('missing',None)
                else:
                    values={}
                    for city,included,qualified,_ in table:
                        inc,done=Fraction(included),Fraction(qualified)
                        if city not in CITIES or city in values or inc.denominator!=1 or done.denominator!=1 or inc<0 or done<0 or done>inc:raise ValueError('数据异常')
                        values[city]=done/inc if inc else None
                    if set(values)!=set(CITIES):raise ValueError('地市数据不完整')
                    cache[month]=('ok',(values,result.get('source_info') or {}))
            except RuntimeError:cache[month]=('error','统计查询服务暂不可用，请检查数据连接后重试。')
            except (ValueError,TypeError,ZeroDivisionError):cache[month]=('error','统计数据异常，请核对来源后重试。')
        return cache[month]
    def suspended(month):
        if month not in suspension_cache:
            try:suspension_cache[month]=suspension_reader(month) if suspension_reader else None
            except (ValueError,RuntimeError,TypeError):suspension_cache[month]={'error':True}
        return suspension_cache[month]
    result=[]
    for row in rows:
        record=dict(zip(('id','month','city','issue','status','action','next_date','updated_at'),row))
        record['events']=[{'at':event[1],'status':event[2],'action':event[3],'next_date':event[4],'month':event[5],'city':event[6],'issue':event[7]} for event in events if event[0]==record['id']]
        # Historical entries may refer to a different city or issue after an edit.
        # Only summarize events belonging to the current tracked matter.
        current_events=[event for event in record['events'] if event['month']==record['month'] and event['city']==record['city'] and event['issue']==record['issue'] and event['action']]
        record['progress_summary']=[{'at':event['at'],'action':event['action']} for event in current_events[:3]]
        if not include_comparison:
            result.append(record);continue
        year,num=map(int,record['month'].split('-'));following=f'{year+(num==12):04d}-{num%12+1:02d}'
        base_state,base=values(record['month']);after_state,after=values(following)
        record['comparison']={'available':False,'month':following,'message':'下月数据或可比较的分母尚不可用。'}
        if base_state=='error' or after_state=='error':
            record['comparison']['message']=base if base_state=='error' else after
        elif base_state=='missing':record['comparison']['message']='本期统计数据不可用，无法计算变化。'
        elif after_state=='missing':record['comparison']['message']='下月统计数据不可用，无法计算变化。'
        elif base_state=='ok' and after_state=='ok' and base[0][record['city']] is not None and after[0][record['city']] is not None:
            change=(after[0][record['city']]-base[0][record['city']])*100
            record['comparison']={'available':True,'month':following,'change':float(change),'base_period':base[1].get('period'),'period':after[1].get('period')}
        else:record['comparison']['message']='本期或下月确认纳入数为零，无法比较解决率。'
        year2,num2=map(int,following.split('-'));later=f'{year2+(num2==12):04d}-{num2%12+1:02d}'
        later_state,later_data=values(later)
        earlier=previous_month(record['month']);earlier_state,earlier_data=values(earlier)
        record['trend']=[]
        for m,state,item in ((earlier,earlier_state,earlier_data),(record['month'],base_state,base),(following,after_state,after),(later,later_state,later_data)):
            if state=='ok':
                rate=item[0][record['city']]
                record['trend'].append({'month':m,'rate':float(rate*100) if rate is not None else None,'period':item[1].get('period'),'source':item[1].get('kind'),'note':'无分母' if rate is None else ''})
            else:record['trend'].append({'month':m,'rate':None,'period':None,'source':None,'note':item if state=='error' else '暂无数据'})
        record['suspension_trend']=[]
        for m in (earlier,record['month'],following,later):
            item=suspended(m);matches=[]
            if item and not item.get('error') and (not item.get('city_note') or item.get('kind')=='manual'):
                matches=[r for r in item.get('cities') or [] if r.get('name')==record['city'] and type(r.get('value')) is int and r['value']>=0]
            record['suspension_trend'].append({'month':m,'count':matches[0]['value'] if len(matches)==1 else None,'period':item.get('period') if item else None,'source':item.get('kind') if item else None,'note':'读取失败' if item and item.get('error') else '暂无数据' if len(matches)!=1 else ''})
        result.append(record)
    return result
