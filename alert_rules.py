"""Optional, user-configured alert rules over saved city aggregates."""
import json
from fractions import Fraction

from core import CITIES
from smart_query import query
from suspension import previous_month

DEFAULT={'bottom_three':True,'minimum_rate':None,'unfinished_at_least':None,'two_month_decline':False,'suspension_increase_at_least':None}

def ensure(c):
    c.execute('CREATE TABLE IF NOT EXISTS city_alert_rules (id TEXT PRIMARY KEY, rules TEXT NOT NULL)')

def get(connect):
    with connect() as c:
        ensure(c)
        row=c.execute("SELECT rules FROM city_alert_rules WHERE id='default'").fetchone()
    return validate(json.loads(row[0])) if row else dict(DEFAULT)

def validate(data):
    if not isinstance(data,dict) or set(data)!=set(DEFAULT):raise ValueError('预警规则格式无效。')
    for key in ('bottom_three','two_month_decline'):
        if type(data[key]) is not bool:raise ValueError('预警开关无效。')
    rate=data['minimum_rate']
    if rate is not None and (type(rate) not in (int,float) or not 0<=rate<=100):raise ValueError('解决率阈值应为 0 至 100。')
    for key in ('unfinished_at_least','suspension_increase_at_least'):
        value=data[key]
        if value is not None and (type(value) is not int or not 1<=value<=10000000):raise ValueError('数量阈值应为大于零的整数。')
    if not any((data['bottom_three'],rate is not None,data['unfinished_at_least'] is not None,data['two_month_decline'],data['suspension_increase_at_least'] is not None)):
        raise ValueError('请至少启用一项预警规则。')
    return dict(data)

def save(connect,data):
    data=validate(data)
    with connect() as c:
        ensure(c)
        c.execute("INSERT INTO city_alert_rules (id,rules) VALUES ('default',?) ON CONFLICT(id) DO UPDATE SET rules=excluded.rules",(json.dumps(data,ensure_ascii=False),))

def _cities(connect,month,source_reader):
    result=query(connect,'query_city_metrics',{'month':month,'city':'全部地市','metric':'解决率'},structured=True,source_reader=source_reader)
    rows=(result.get('table') or {}).get('rows')
    if not result.get('available') or not rows:raise ValueError(month+'地市统计不可用，无法执行已启用的预警规则。')
    values={}
    for city,included,qualified,_ in rows:
        inc,done=Fraction(included),Fraction(qualified)
        if city in values or city not in CITIES or inc.denominator!=1 or done.denominator!=1 or inc<0 or done<0 or done>inc:raise ValueError(month+'地市统计异常，请核对。')
        values[city]={'included':int(inc),'qualified':int(done),'rate':done/inc if inc else None}
    if set(values)!=set(CITIES):raise ValueError(month+'地市统计不完整，无法执行预警。')
    return values,result.get('source_info')

def evaluate(connect,month,rules,*,source_reader=None,suspension_reader=None):
    current,source=_cities(connect,month,source_reader)
    reasons={city:[] for city in CITIES};extra_sources=[]
    if rules['bottom_three']:
        eligible=sorted(item['rate'] for item in current.values() if item['rate'] is not None)
        if eligible:
            cutoff=eligible[min(3,len(eligible))-1]
            for city,item in current.items():
                if item['rate'] is not None and item['rate']<=cutoff:reasons[city].append('解决率倒数靠前')
    for city,item in current.items():
        if rules['minimum_rate'] is not None and item['rate'] is not None and item['rate']*100<Fraction(str(rules['minimum_rate'])):
            reasons[city].append(f"解决率低于 {rules['minimum_rate']}%")
        if rules['unfinished_at_least'] is not None and item['included']-item['qualified']>=rules['unfinished_at_least']:
            reasons[city].append(f"尚未质检合格不少于 {rules['unfinished_at_least']} 处")
    if rules['two_month_decline']:
        m1=previous_month(month);m2=previous_month(m1)
        before,s1=_cities(connect,m1,source_reader);older,s2=_cities(connect,m2,source_reader);extra_sources.extend([s1,s2])
        for city,item in current.items():
            rates=(older[city]['rate'],before[city]['rate'],item['rate'])
            if all(x is not None for x in rates) and rates[0]>rates[1]>rates[2]:reasons[city].append('解决率连续两个月下降')
    if rules['suspension_increase_at_least'] is not None:
        if suspension_reader is None:raise ValueError('挂起数据来源不可用，无法执行预警。')
        m1=previous_month(month);a,b=suspension_reader(month),suspension_reader(m1)
        def city_values(data):
            if not data or data.get('city_note') or not isinstance(data.get('cities'),list):raise ValueError('本月或上月挂起地市数据不完整，无法执行预警。')
            result={row['name']:row['value'] for row in data['cities']}
            if set(result)!=set(CITIES) or any(type(x) is not int or x<0 for x in result.values()):raise ValueError('挂起地市数据不完整，无法执行预警。')
            return result
        current_s,prior_s=city_values(a),city_values(b)
        extra_sources.extend([{'period':a.get('period'),'kind':a.get('kind'),'cities':current_s},{'period':b.get('period'),'kind':b.get('kind'),'cities':prior_s}])
        for city in CITIES:
            delta=current_s[city]-prior_s[city]
            if delta>=rules['suspension_increase_at_least']:reasons[city].append(f'挂起较上月增加 {delta} 处')
    ordered=sorted((city for city in CITIES if reasons[city]),key=lambda city:(current[city]['rate'] is None,current[city]['rate'] or 0,CITIES.index(city)))
    rows=[]
    for city in ordered:
        item=current[city];rate=item['rate']
        rows.append([city, f'{float(rate)*100:.2f}%' if rate is not None else '无分母',str(item['qualified']),str(item['included']),reasons[city]])
    return rows,{'rules':rules,'source':source,'extra_sources':extra_sources,'rows':rows}
