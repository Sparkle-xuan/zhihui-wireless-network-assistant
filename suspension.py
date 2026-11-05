"""Read-only presentation model for saved suspension aggregates."""
import json
from core import CITIES

def _count(value):
    return isinstance(value,int) and not isinstance(value,bool) and value>=0

def summary(encoded,period,kind):
    try:
        snapshot=json.loads(encoded)
        group=snapshot['suspended']
        total=group['count']
        if not isinstance(group,dict) or not _count(total):raise ValueError()
    except (KeyError,ValueError,TypeError):
        raise ValueError('该期挂起库汇总缺失或格式异常，请核对报告。')
    result={'period':period,'kind':kind,'total':total,'cities':None,'categories':None,'city_note':'','category_note':''}
    raw=group.get('cities')
    if isinstance(raw,list):
        values={}
        for entry in raw:
            if not isinstance(entry,(list,tuple)) or len(entry)!=2 or not isinstance(entry[0],str) or not entry[0] or not _count(entry[1]) or entry[0] in values:
                result['city_note']='地市汇总格式异常，请核对原始报告。';break
            values[entry[0]]=entry[1]
        else:
            amount=sum(values.values())
            if amount>total:result['city_note']='地市汇总大于总数，请核对原始报告。'
            else:
                result['cities']=[{'name':name,'value':values[name]} for name in CITIES if name in values] if group.get('partial_cities') else [{'name':name,'value':values.get(name,0)} for name in CITIES]
                other=amount-sum(values.get(name,0) for name in CITIES)
                missing=total-amount
                if group.get('partial_cities'):result['city_note']='仅记录了部分地市，未提供的地市不计为零。'
                elif other or missing:result['city_note']=f'另有 {other+missing} 处未能匹配到 16 个地市，请核对原始报告。'
    else:result['city_note']='该期未保存挂起地市分布，请使用原表补充统计。'
    raw=group.get('categories')
    if isinstance(raw,dict):
        if any(not isinstance(k,str) or not k.strip() or not _count(v) for k,v in raw.items()):result['category_note']='分类汇总格式异常，请核对原始报告。'
        elif sum(raw.values())>total:result['category_note']='分类汇总大于总数，请核对原始报告。'
        else:
            result['categories']=[{'name':k,'value':v} for k,v in raw.items() if v>0]
            missing=total-sum(raw.values())
            if missing:
                existing=next((x for x in result['categories'] if x['name']=='未记录分类'),None)
                if existing:existing['value']+=missing
                else:result['categories'].append({'name':'未记录分类','value':missing})
                result['category_note']=f'{missing} 处未记录分类，请核对原始报告。'
    else:result['category_note']='该期未保存挂起分类汇总，请使用原表补充统计。'
    return result


def top_cities(data,limit=3):
    cities=data.get('cities')
    if not isinstance(cities,list) or data.get('city_note'):return None
    ordered=sorted((row for row in cities if row['value']>0),key=lambda row:-row['value'])
    if not ordered:return []
    threshold=ordered[min(limit,len(ordered))-1]['value']
    return [row for row in ordered if row['value']>=threshold]

def previous_month(month):
    from datetime import date,timedelta
    if not isinstance(month,str) or len(month)!=7:raise ValueError('月份无效。')
    try:
        first=date.fromisoformat(month+'-01')
        if first.strftime('%Y-%m')!=month:raise ValueError()
        return (first-timedelta(days=1)).strftime('%Y-%m')
    except (ValueError,OverflowError):raise ValueError('月份无效。')

def compare(current,previous,month):
    result={'month':month,'available':False,'note':'暂无上月最后一个周五的报告数据，无法比较。','previous_total':None,'delta':None,'cities':None,'previous_period':None,'previous_kind':None}
    if not previous:return result
    result.update(available=True,note='',previous_total=previous['total'],delta=current['total']-previous['total'],previous_period=previous['period'],previous_kind=previous['kind'])
    if current['cities'] is not None and previous['cities'] is not None and not current['city_note']:
        before={row['name']:row['value'] for row in previous['cities']}
        if not previous['city_note'] or previous['kind']=='manual':
            result['cities']=[{'name':row['name'],'delta':row['value']-before[row['name']]} for row in current['cities'] if row['name'] in before]
            if previous['city_note']:result['note']='上月仅提供部分地市数据，其他地市暂无对比。'
        else:result['note']='上月地市分布不完整，无法比较各地市变化。'
    else:result['note']='上月或本月未保存完整地市分布，无法比较各地市变化。'
    return result
