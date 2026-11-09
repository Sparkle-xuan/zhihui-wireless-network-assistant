"""Read-only presentation model for saved suspension aggregates."""
import json
from core import CITIES
import suspension_reasons

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
    reasons=suspension_reasons.validate(group.get('reason_analysis'),total,CITIES)
    if reasons is not None:result['reason_analysis']=reasons
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
    if current['cities'] is not None and previous['cities'] is not None and (not current['city_note'] or current['kind']=='manual'):
        before={row['name']:row['value'] for row in previous['cities']}
        if not previous['city_note'] or previous['kind']=='manual':
            result['cities']=[{'name':row['name'],'delta':row['value']-before[row['name']]} for row in current['cities'] if row['name'] in before]
            if previous['city_note'] or current['city_note']:result['note']='部分地市数据未提供，仅展示已知地市的对比。'
        else:result['note']='上月地市分布不完整，无法比较各地市变化。'
    else:result['note']='上月或本月未保存完整地市分布，无法比较各地市变化。'
    return result


def diagnostic_facts(current, previous, month):
    """Build bounded, verifiable aggregates for the diagnostic, not work-order detail."""
    comparison=compare(current,previous,previous_month(month))
    facts=[f'{month}全省挂起 {current["total"]} 处。']
    if comparison['available']:
        delta=comparison['delta']
        change='持平' if delta==0 else ('增加' if delta>0 else '减少')+str(abs(delta))+' 处'
        baseline=('上月统计日：'+comparison['previous_period']) if comparison['previous_period'] else '上月为人工补录，日期未提供'
        facts.append(f'上月全省挂起 {comparison["previous_total"]} 处，较上月{change}（{baseline}）。')
    else:facts.append('缺少可比较的上月全省数据。')
    top=top_cities(current)
    if top is None:facts.append('地市分布不完整，暂不能判断全省地市排名。')
    elif top:facts.append('挂起数量最多的地市：'+'、'.join(f'{x["name"]} {x["value"]} 处' for x in top)+'。')
    else:facts.append('本月没有挂起记录。')
    if current.get('category_estimated'):facts.append('挂起分类为关键词初筛，需结合原表核实。')
    elif current.get('category_note'):facts.append('分类数据不完整，需结合原表核实。')
    elif current.get('categories'):facts.append('挂起分类以已保存的归属类别统计为准。')
    else:facts.append('该月未保存挂起分类。')
    allowed={'无项目','纠纷协调类工单','低价值','已有室分+宏站覆盖但有覆盖盲区且暂无解决方案','特殊场景和烂尾楼','未记录分类','待核实'}
    categories=[{'name':row['name'],'value':row['value']} for row in current.get('categories') or [] if row['name'] in allowed]
    known=[row for row in categories if row['name'] not in ('未记录分类','待核实')]
    if known:
        highest=max(row['value'] for row in known)
        facts.append(('初筛结果中' if current.get('category_estimated') else '已记录分类中')+'数量最多：'+'、'.join(f'{row["name"]} {row["value"]} 处' for row in known if row['value']==highest)+'。')
    reason_data=current.get('reason_analysis')
    reason_evidence=None
    if isinstance(reason_data,dict) and reason_data.get('total')==current['total']:
        counts=sorted(reason_data.get('counts',[]),key=lambda row:-row['value'])
        if counts:
            greatest=counts[0]['value']
            facts.append('原因关键词初筛中出现最多：'+'、'.join(f'{row["name"]} {row["value"]} 处' for row in counts if row['value']==greatest)+'。')
        facts.append(f'原因关键词初筛：未匹配 {reason_data["unmatched"]} 处，空白 {reason_data["blank"]} 处，多关键词 {reason_data["multi"]} 处；一处可涉及多个关键词，不能相加。')
        city_rows=[]
        if top is not None:
            for city in top[:3]:
                rows=sorted((r for r in reason_data.get('cities',[]) if r['city']==city['name']),key=lambda row:-row['value'])
                selected=rows[:3]
                selected+= [r for r in rows[3:] if r['reason'] in ('涉及7+9','涉及室分建设或改造')]
                city_rows.extend(selected)
                if selected:facts.append(city['name']+'关键词初筛：'+'、'.join(f'{row["reason"]} {row["value"]} 处' for row in selected)+'。')
        cross=sorted(reason_data.get('categories',[]),key=lambda row:-row['value'])[:8]
        joints=sorted((r for r in reason_data.get('issue_suspension_cities',[]) if top is not None and r['city'] in {x['name'] for x in top[:3]}),key=lambda row:-row['value'])
        for row in joints:facts.append(f'{row["city"]}同一记录跨字段关键词初筛：形成原因{row["issue"]}，不纳入原因{row["suspension"]}，共 {row["value"]} 处。')
        reason_evidence={'counts':counts,'cities':city_rows,'categories':cross,'city_categories':sorted((r for r in reason_data.get('city_categories',[]) if top is not None and r['city'] in {x['name'] for x in top[:3]}),key=lambda row:-row['value'])[:6], 'issue_suspension_cities':joints,'unmatched':reason_data['unmatched'],'blank':reason_data['blank'],'multi':reason_data['multi'],'method':'关键词初筛，可多重命中，不能证明实际原因；跨字段同记录仅以明确交叉统计为准'}
        issue=reason_data.get('issue')
        if isinstance(issue,dict) and issue.get('available'):
            issue_counts=sorted(issue['counts'],key=lambda row:-row['value'])
            if issue_counts:
                highest=issue_counts[0]['value']
                facts.append('问题形成原因关键词初筛中出现最多：'+'、'.join(f'{row["name"]} {row["value"]} 处' for row in issue_counts if row['value']==highest)+'。')
            facts.append(f'问题形成原因初筛：未匹配 {issue["unmatched"]} 处，空白 {issue["blank"]} 处，多关键词 {issue["multi"]} 处；不可与挂起原因混为一谈。')
            issue_cities=[]
            if top is not None:
                for city in top[:3]:
                    all_rows=sorted((r for r in issue['cities'] if r['city']==city['name']),key=lambda row:-row['value'])
                    rows=all_rows[:3]+[r for r in all_rows[3:] if r['reason'] in ('涉及玻璃','涉及7+9')]
                    issue_cities.extend(rows)
                    if rows:facts.append(city['name']+'形成原因关键词初筛：'+'、'.join(f'{row["reason"]} {row["value"]} 处' for row in rows)+'。')
            reason_evidence['issue']={'counts':issue_counts,'cities':issue_cities,'categories':sorted(issue['categories'],key=lambda row:-row['value'])[:8], 'city_categories':sorted((r for r in issue['city_categories'] if top is not None and r['city'] in {x['name'] for x in top[:3]}),key=lambda row:-row['value'])[:6], 'unmatched':issue['unmatched'],'blank':issue['blank'],'multi':issue['multi']}
        else:facts.append('本月没有可用的问题形成原因汇总。')
    else:facts.append('本月未保存不纳入原因汇总，暂不能分析具体挂起障碍。')
    return {'month':month,'period':current.get('period'),'source':current.get('kind'),
            'facts':facts,'cities_complete':top is not None,
            'categories_estimated':bool(current.get('category_estimated')),
            'comparison_available':comparison['available'],'categories':categories,'reasons':reason_evidence}


def local_diagnostic_advice(evidence):
    """Offer a clearly labelled local fallback using only existing aggregate labels."""
    reason=evidence.get('reasons')
    if not isinstance(reason,dict) or not evidence.get('cities_complete'):
        return '该版本的地市分布或原因汇总不完整，暂无法形成针对具体地市和问题的推进建议。'
    rows=reason.get('cities') or []
    issue=(reason.get('issue') or {}).get('cities') or []
    joint=reason.get('issue_suspension_cities') or []
    ordered=[]
    for row in rows:
        city=row.get('city')
        if city in CITIES and city not in ordered:ordered.append(city)
    paragraphs=[]
    for city in ordered[:3]:
        tags={r.get('reason') for r in rows if r.get('city')==city}
        issues={r.get('reason') for r in issue if r.get('city')==city}
        pairs={(r.get('issue'),r.get('suspension')) for r in joint if r.get('city')==city}
        actions=[]
        if ('涉及玻璃','涉及7+9') in pairs:
            actions.append('对涉及玻璃和7+9的场景，结合现场条件评估设备替换或室分增补方案')
        elif '涉及玻璃' in issues:
            actions.append('对玻璃相关覆盖问题评估室分增补或优化方案')
        elif '涉及7+9' in tags:
            actions.append('对涉及7+9的场景评估设备替换或室分优化方案')
        elif '涉及覆盖问题' in tags or '涉及覆盖' in issues:
            actions.append('结合场景评估覆盖优化或室分增补方案')
        if '涉及无项目' in tags or '涉及室分建设或改造' in tags:
            actions.append('对具备建设条件的需求推动纳入项目储备')
        if '涉及协调或阻挠' in tags:actions.append('对协调障碍推动相关方协商处理')
        if '涉及低价值' in tags:actions.append('结合需求和投入评估低成本优化方式')
        if actions:paragraphs.append(city+'：建议'+'；'.join(actions)+'。')
    if not paragraphs:return '当前汇总缺少可用于地市分析的原因线索，暂无法形成具体推进建议。'
    return '以下为依据关键词初筛生成的本地参考建议，具体方案需结合实际判断。\n'+'\n'.join(paragraphs)


def workbook_summary(source, provisional=False):
    """Extract only suspension aggregates; do not retain work orders or the workbook."""
    from collections import Counter
    import re
    from openpyxl import load_workbook
    try:book=load_workbook(source,read_only=True,data_only=True)
    except Exception as exc:raise ValueError('无法读取 Excel 文件。') from exc
    try:
        if '挂起' not in book:raise ValueError('文件缺少挂起工作表。')
        rows=book['挂起'].iter_rows(values_only=True);headers=next(rows,())
        def index(name):
            hits=[i for i,value in enumerate(headers) if value==name]
            if len(hits)!=1:raise ValueError('挂起表缺少或重复字段：'+name)
            return hits[0]
        city_index=index('地市');id_index=index('工单Id')
        matches=[i for i,value in enumerate(headers) if value=='waitingClassifyName']
        if len(matches)>1 and 105 in matches:matches=[105]
        if len(matches)>1:raise ValueError('挂起分类字段重复，请核对表格。')
        category_index=matches[0] if matches else None
        reason_index=index('不纳入原因') if provisional and category_index is None else None
        cities=Counter();categories=Counter();estimates=Counter();count=0
        for row in rows:
            if len(row)<=id_index or row[id_index] is None or not str(row[id_index]).strip():continue
            count+=1
            city=str(row[city_index]).strip() if len(row)>city_index and row[city_index] is not None else ''
            if city and city not in CITIES:raise ValueError('挂起表存在无法识别的地市，请核对。')
            if city:cities[city]+=1
            if category_index is not None and len(row)>category_index and row[category_index] is not None:
                category=str(row[category_index]).strip()
                if category:categories[category]+=1
            if reason_index is not None:
                reason=str(row[reason_index] or '') if len(row)>reason_index else ''
                coordination=bool(re.search('协调|纠纷',reason))
                choices=[name for name,pattern in [('低价值','低价值|价值低|价值较低'),('无项目','无项目|暂无项目|没有项目'),('特殊场景和烂尾楼','烂尾|特殊场景')] if re.search(pattern,reason)]
                label='纠纷协调类工单' if coordination else choices[0] if len(choices)==1 else '待核实'
                estimates[label]+=1
        if not count:raise ValueError('挂起表没有可识别的工单记录。')
        group={'count':count,'cities':list(cities.items())}
        if category_index is not None:group['categories']=dict(categories)
        reasons=suspension_reasons.extract(book['挂起'],CITIES)
        if reasons and reasons['total']==count:group['reason_analysis']=reasons
        result={'suspended':group}
        if reason_index is not None:result['estimated_categories']=dict(estimates)
        return result
    finally:book.close()
