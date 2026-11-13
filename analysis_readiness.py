"""Check the exact saved snapshots required for a monthly comparison."""
from fractions import Fraction

from core import CITIES
from smart_query import _last_friday, query
from suspension import previous_month


def check(month, connect, *, source_reader=None):
    _last_friday(month)
    months=[month,previous_month(month)]
    results=[];eligible=[]
    for value in months:
        try:
            data=query(connect,'query_city_metrics',{'month':value,'city':'全部地市','metric':'解决率'},structured=True,source_reader=source_reader)
            rows=(data.get('table') or {}).get('rows')
            if not data.get('available') or not rows:
                results.append({'month':value,'available':False,'message':data.get('reply','缺少该月统计。')})
                eligible.append(set())
                continue
            names=[];usable=set()
            for city,included,qualified,_ in rows:
                inc,done=Fraction(included),Fraction(qualified)
                if inc.denominator!=1 or done.denominator!=1 or inc<0 or done<0 or done>inc:raise ValueError('地市统计数值异常，请核对原表。')
                names.append(city)
                if inc:usable.add(city)
            if len(names)!=len(CITIES) or set(names)!=set(CITIES):raise ValueError('地市统计不完整，请核对原表。')
            source=data.get('source_info') or {}
            results.append({'month':value,'available':True,'period':source.get('period'),'source':source.get('kind'),'message':'数据可用'})
            eligible.append(usable)
        except (ValueError,TypeError,ZeroDivisionError) as exc:
            results.append({'month':value,'available':False,'message':str(exc) or '数据检查失败。'})
            eligible.append(set())
    comparable=len(eligible[0]&eligible[1])
    message=('本月和上月有可比较的地市。' if comparable else
             '没有两个月分母均不为零的地市，无法比较解决率。' if all(r['available'] for r in results) else
             '本月或上月数据不可用，无法比较。')
    return {'month':month,'current':results[0],'previous':results[1],
            'can_generate':results[0]['available'],'can_compare':bool(comparable),
            'comparison_count':comparable,'comparison_message':message}
