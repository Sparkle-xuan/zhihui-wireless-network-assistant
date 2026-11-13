"""Verified, source-aware comparisons for the dashboard."""
from datetime import date, timedelta
from math import isfinite
from core import CITIES
from suspension import previous_month


def _number(value):
    if value is None or isinstance(value, bool):return None
    try: n=float(value)
    except (TypeError,ValueError):return None
    return n if isfinite(n) and n >= 0 else None


def _total(data):
    rows=data.get('cities') or []
    if len(rows)!=len(CITIES) or {r.get('name') for r in rows}!=set(CITIES):return None
    included=sum(r['included'] for r in rows)
    qualified=sum(r['qualified'] for r in rows)
    return qualified/included*100 if included else None


def _card(data,name):
    item=next((r for r in data.get('cards',[]) if r.get('label')==name),{})
    return _number(item.get('value')),item.get('source')


def build(month, day, monthly_reader, network_reader):
    """Compare exact previous periods only, preserving provenance and missing values."""
    previous=previous_month(month)
    current=monthly_reader(month)
    try: before=monthly_reader(previous)
    except (ValueError,RuntimeError):before={}
    daily=network_reader(day)
    actual=daily.get('day')
    prior_day=(date.fromisoformat(actual)-timedelta(days=1)).isoformat() if actual else None
    try: prior=network_reader(prior_day) if prior_day else {}
    except (ValueError,RuntimeError):prior={}
    changes={}
    for name in ('5G数据流量','4G数据流量','5G分流比'):
        value,source=_card(daily,name);old,old_source=_card(prior,name)
        # Different source descriptions need review before comparing the values.
        comparable=value is not None and old is not None and source and old_source and source==old_source
        changes[name]={'value':value,'previous':old if comparable else None,'delta':value-old if comparable else None,
                       'period':actual,'previous_period':prior_day,'source':source,'previous_source':old_source}
    rate,old_rate=_total(current),_total(before)
    changes['黑点解决率']={'value':rate,'previous':old_rate,'delta':rate-old_rate if rate is not None and old_rate is not None else None,
                        'period':(current.get('source_info') or {}).get('period'),'previous_period':(before.get('source_info') or {}).get('period'),
                        'source':(current.get('source_info') or {}).get('kind'),'previous_source':(before.get('source_info') or {}).get('kind')}
    a,b=current.get('suspension') or {},before.get('suspension') or {}
    x,y=_number(a.get('total')),_number(b.get('total'))
    changes['挂起库数量']={'value':x,'previous':y,'delta':x-y if x is not None and y is not None else None,
                        'period':a.get('period'),'previous_period':b.get('period'),'source':a.get('kind'),'previous_source':b.get('kind')}
    notices=[];focus=[]
    rows=current.get('cities') or []
    if len(rows)==len(CITIES) and {r.get('name') for r in rows}==set(CITIES):
        eligible=sorted((r for r in rows if r.get('rate') is not None),key=lambda r:r['rate'])
        if eligible:
            cutoff=eligible[min(3,len(eligible))-1]['rate']
            focus.append({'kind':'resolution','title':'解决率靠后','items':[{'city':r['name'],'value':r['rate'],'unit':'%'} for r in eligible if r['rate']<=cutoff],
                          'period':(current.get('source_info') or {}).get('period'),'rule':'按解决率倒数前三，末位并列一并展示；分母为零不排名。'})
    else:notices.append('本月地市解决率数据不完整，未生成全省排名。')
    city_rows=a.get('cities') or []
    if len(city_rows)==len(CITIES) and {r.get('name') for r in city_rows}==set(CITIES) and not a.get('city_note') and all(_number(r.get('value')) is not None for r in city_rows):
        ranked=sorted(city_rows,key=lambda r:r['value'],reverse=True);cutoff=ranked[min(3,len(ranked))-1]['value']
        focus.append({'kind':'suspension','title':'挂起数量较多','items':[{'city':r['name'],'value':r['value'],'unit':'处'} for r in ranked if r['value']>=cutoff],
                      'period':a.get('period'),'rule':'按挂起数量从高到低，前三名末位并列一并展示。'})
    else:notices.append('本月挂起地市数据不完整，未生成全省排名。')
    old_rows=b.get('cities') or []
    if (len(city_rows)==len(CITIES) and len(old_rows)==len(CITIES) and not a.get('city_note') and not b.get('city_note')
        and {r.get('name') for r in city_rows}==set(CITIES) and {r.get('name') for r in old_rows}==set(CITIES)
        and all(_number(r.get('value')) is not None for r in city_rows+old_rows)):
        old_values={r['name']:r['value'] for r in old_rows}
        growth=sorted(({'city':r['name'],'value':r['value']-old_values[r['name']],'unit':'处'} for r in city_rows if r['value']>old_values[r['name']]),key=lambda r:-r['value'])
        if growth:
            cutoff=growth[min(3,len(growth))-1]['value']
            focus.append({'kind':'growth','title':'挂起增长较多','items':[r for r in growth if r['value']>=cutoff],
                          'period':a.get('period'),'rule':'本期减上期，展示增加数量最多的三个地市，末位并列一并展示；上期日期：'+str(b.get('period') or '未提供')+'。'})
    else:notices.append('本月或上月挂起地市数据不完整，未判断地市增长。')
    summary=[]
    if changes['5G数据流量']['value'] is not None:summary.append(f"{actual}全省 5G 数据流量 {changes['5G数据流量']['value']:.2f} TB")
    if rate is not None:summary.append(f"{month}黑点解决率 {rate:.2f}%")
    if x is not None:summary.append(f"{month}挂起库 {x:.0f} 处")
    if changes['5G数据流量']['delta'] is not None:summary.append(f"5G 流量较 {prior_day} 变化 {changes['5G数据流量']['delta']:+.2f} TB")
    if changes['黑点解决率']['delta'] is not None:summary.append(f"解决率较 {previous} 变化 {changes['黑点解决率']['delta']:+.2f} 个百分点")
    if changes['挂起库数量']['delta'] is not None:summary.append(f"挂起库较 {previous} 变化 {changes['挂起库数量']['delta']:+.0f} 处")
    if prior_day and changes['5G数据流量']['delta'] is None:notices.append('前一自然日数据缺失、冲突或来源不一致，未比较网络指标。')
    if old_rate is None:notices.append('上月完整黑点统计缺失或无分母，未比较解决率。')
    if y is None:notices.append('上月挂起总数缺失，未比较挂起数量。')
    return {'month':month,'previous_month':previous,'day':actual,'previous_day':prior_day,'changes':changes,'focus':focus,'notices':notices,
            'summary':'；'.join(summary)+'。' if summary else '', 'cities':rows,'previous_cities':before.get('cities') or [],
            'suspension':a,'previous_suspension':b}
