"""Read-only, locally calculated highlights with explicit evidence."""
from datetime import date,timedelta
from fractions import Fraction
from core import CITIES
from smart_query import query
from suspension import previous_month
import network_query

def build(connect,month,*,source_reader=None,suspension_reader=None,network_reader=None,today=None):
    today=today or date.today();observations=[];notices=[]
    cache={}
    def city_data(m):
        if m not in cache:
            try:
                data=query(connect,'query_city_metrics',{'month':m,'city':'全部地市','metric':'解决率'},structured=True,source_reader=source_reader)
                rows=(data.get('table') or {}).get('rows');values={}
                if not data.get('available') or not rows:raise ValueError(data.get('reply','数据不可用'))
                for city,included,qualified,_ in rows:
                    inc,done=Fraction(included),Fraction(qualified)
                    if city not in CITIES or city in values or inc.denominator!=1 or done.denominator!=1 or inc<0 or done<0 or done>inc:raise ValueError('地市统计异常')
                    values[city]=(done/inc if inc else None,int(inc-done))
                if set(values)!=set(CITIES):raise ValueError('地市统计不完整')
                cache[m]=(values,data.get('source_info') or {})
            except (ValueError,TypeError,RuntimeError,ZeroDivisionError):cache[m]=None
        return cache[m]
    current=city_data(month);prior_month=previous_month(month);prior=city_data(prior_month);older=city_data(previous_month(prior_month))
    if current:
        values,source=current;eligible=sorted((v[0],city,v[1]) for city,v in values.items() if v[0] is not None)
        if eligible:
            cutoff=eligible[min(3,len(eligible))-1][0]
            selected=[{'city':city,'rate':f'{float(rate)*100:.2f}%','unfinished':unfinished} for rate,city,unfinished in eligible if rate<=cutoff]
            observations.append({'kind':'resolution','title':'解决率靠后的地市','items':selected,'period':source.get('period'),'source':source.get('kind'),'month':month,'rule':'按未舍入解决率倒数前三，末位并列一并展示；分母为零不参与排名。'})
        if prior and older:
            falling=[]
            for city,(rate,unfinished) in values.items():
                before=prior[0][city][0];earlier=older[0][city][0]
                if rate is not None and before is not None and earlier is not None and earlier>before>rate:falling.append({'city':city,'rate':f'{float(rate)*100:.2f}%','unfinished':unfinished})
            if falling:observations.append({'kind':'decline','title':'解决率连续两个月下降','items':falling,'month':month,'period':source.get('period'),'source':source.get('kind'),'rule':'三期解决率依次下降；各期实际数据日期分别为 '+str(older[1].get('period') or '未提供')+'、'+str(prior[1].get('period') or '未提供')+'、'+str(source.get('period') or '未提供')+'。'})
        else:notices.append('缺少前两个月完整地市数据，未判断连续下降。')
    else:notices.append(month+'地市解决率数据不可用，未生成排名和趋势判断。')
    if suspension_reader:
        try:
            a,b=suspension_reader(month),suspension_reader(prior_month)
            if a and b and not a.get('city_note') and not b.get('city_note') and isinstance(a.get('cities'),list) and isinstance(b.get('cities'),list):
                x={r['name']:r['value'] for r in a['cities']};y={r['name']:r['value'] for r in b['cities']}
                if set(x)==set(CITIES) and set(y)==set(CITIES) and all(type(v) is int and v>=0 for v in [*x.values(),*y.values()]):
                    increases=sorted(({'city':city,'change':x[city]-y[city],'count':x[city]} for city in CITIES if x[city]>y[city]),key=lambda r:-r['change'])
                    if increases:observations.append({'kind':'suspension','title':'挂起数量较上月增加','items':increases[:3],'month':month,'period':a.get('period'),'source':a.get('kind'),'rule':'本期减上期；上期日期：'+str(b.get('period') or '未提供')+'。仅展示增量最大的三个地市。'})
                else:notices.append('挂起地市数据不完整，未判断增长。')
            else:notices.append('本月或上月挂起地市数据不完整，未判断增长。')
        except (ValueError,RuntimeError,TypeError,KeyError):notices.append('挂起数据读取失败，未判断增长。')
    try:
        latest=network_query.query(connect,{'day':'latest','city':'全省','metric':'5G数据流量'},source_reader=network_reader)
        if latest.get('available') and latest.get('stat'):
            stat=latest['stat'];day=stat['day'];previous_day=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
            before=network_query.query(connect,{'day':previous_day,'city':'全省','metric':'5G数据流量'},source_reader=network_reader)
            if before.get('available') and before.get('stat'):
                a,b=Fraction(stat['value']),Fraction(before['stat']['value'])
                origin=latest.get('reply','').partition('数据来源：')[2].strip('。') or '已保存日报汇总'
                baseline=before.get('reply','').partition('数据来源：')[2].strip('。') or '已保存日报汇总'
                observations.append({'kind':'network','title':'全省5G流量日变化','day':day,'previous_day':previous_day,'value':stat['value'],'previous':before['stat']['value'],'change':f'{float(a-b):+.2f}','unit':'TB','rule':f'对比最近可用日期与其前一自然日；{day}来源：{origin}；{previous_day}来源：{baseline}。来源冲突时不比较。'})
            else:notices.append('最新日报的前一自然日5G流量缺失或存在冲突，未比较。')
        else:notices.append('没有可用的全省5G流量日报，未比较。')
    except (ValueError,RuntimeError,TypeError,KeyError,ZeroDivisionError):notices.append('网络日报读取失败，未比较流量。')
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS city_followups (id TEXT PRIMARY KEY, month TEXT NOT NULL, city TEXT NOT NULL, issue TEXT NOT NULL, status TEXT NOT NULL, action TEXT NOT NULL, next_date TEXT NOT NULL, updated_at TEXT NOT NULL)')
        due=c.execute("SELECT month,city,issue,status,next_date FROM city_followups WHERE next_date<>'' AND next_date<=? AND status<>'已完成' ORDER BY next_date,city LIMIT 101",(today.isoformat(),)).fetchall()
    return {'month':month,'observations':observations,'notices':notices,'due_truncated':len(due)>100,'due':[{'month':r[0],'city':r[1],'issue':r[2],'status':r[3],'next_date':r[4]} for r in due[:100]]}
