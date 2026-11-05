"""Read-only, allowlisted queries and deterministic answers for saved snapshots."""
import json
import math
import re
from datetime import date, timedelta
from fractions import Fraction
from core import CITIES, STAGES
from network_query import NETWORK_TOOL

METRICS=('解决率','确认纳入数','质检合格数','汇聚黑点量','平台关联投诉量','已纳入关联投诉量','关联投诉量','项目进展')
SCALAR_FIELDS={'汇聚黑点量':('platform','处'),'平台关联投诉量':('platform_complaints','件'),'已纳入关联投诉量':('complaints','件')}

TOOLS = [
    {'type':'function','function':{'name':'query_city_metrics','description':'按月份查询全省或地市的黑点汇聚量、关联投诉量、项目进展、确认纳入数、质检合格数或解决率；项目进展应使用项目进展，不可用解决率替代。', 'parameters':{'type':'object','properties':{'month':{'type':'string','description':'用户明确表达或上下文可确定的月份，格式 YYYY-MM'},'city':{'type':'string','description':'全省、全部地市或具体地市名'},'metric':{'type':'string','enum':list(METRICS),'description':'用户请求的指标；关联投诉量口径不明时选关联投诉量，同时查询两种口径'}},'required':['month','city','metric']}}},
    {'type':'function','function':{'name':'query_suspended','description':'查询挂起库（申请挂起）数量或地市分布；不查询类别、原因或跨月对比。', 'parameters':{'type':'object','properties':{'month':{'type':'string','description':'用户明确表达或上下文可确定的月份，格式 YYYY-MM'},'city':{'type':'string','description':'全省、全部地市或具体地市名'}},'required':['month','city']}}},
]

TOOLS.append(NETWORK_TOOL)

def identify_explicit_metric(question):
    """Recognize explicit business terms; None leaves interpretation to the model."""
    if not isinstance(question,str): return None
    text=re.sub(r'\s+','',question)
    candidates=set()
    if re.search(r'项目进展|工程进展|整治进展|建设进展|各(?:个)?阶段|整治阶段',text): candidates.add('项目进展')
    if re.search(r'关联投诉|投诉关联|关联的投诉',text):
        if re.search(r'已纳入|确认纳入|纳入黑点',text): candidates.add('已纳入关联投诉量')
        elif re.search(r'平台|汇聚',text): candidates.add('平台关联投诉量')
        else: candidates.add('关联投诉量')
    elif re.search(r'汇聚黑点|黑点汇聚|平台黑点|平台汇聚',text): candidates.add('汇聚黑点量')
    if re.search(r'解决率|合格率|黑点解决情况|重点投诉区域解决情况',text): candidates.add('解决率')
    if re.search(r'质检合格(?:数|量|多少|几处)',text): candidates.add('质检合格数')
    if re.search(r'(?:确认|已)纳入(?:数|量|多少|几处)',text) and '关联投诉量' not in candidates and '已纳入关联投诉量' not in candidates: candidates.add('确认纳入数')
    return next(iter(candidates)) if len(candidates)==1 else '多个指标' if len(candidates)>1 else None

def local_query_plan(messages):
    """Use only explicit terms when the external intent service is unavailable."""
    if not isinstance(messages,list) or not 1<=len(messages)<=12: return None
    if any(not isinstance(m,dict) or m.get('role') not in ('user','assistant') or not isinstance(m.get('content'),str) or not 1<=len(m['content'].strip())<=5000 for m in messages): return None
    if sum(len(m['content']) for m in messages)>24000 or messages[-1]['role']!='user': return None
    question=messages[-1]['content'];metric=identify_explicit_metric(question)
    if metric=='多个指标' or re.search(r'怎么算|怎么计算|口径|什么意思|区别|定义|对比|比较|相比|环比|同比|上月|上个月|排名|第几|最多|最少|最高|最低|原因|类别',question): return None
    suspended=bool(re.search(r'挂起库|申请挂起|挂起(?:的)?数量|挂起多少|挂起数',question))
    if suspended and metric: return None
    if not metric and not suspended: return None
    matches=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])\s*月?',question)
    if len(matches)>1: return None
    if matches: month=f'{matches[0][0]}-{int(matches[0][1]):02d}'
    else:
        months=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月',question)
        if len(months)!=1: return None
        month=f'{date.today().year}-{int(months[0]):02d}'
    named=[c for c in CITIES if c in question]
    if len(named)>1: return None
    if named: city=named[0]
    elif re.search(r'各地市|全部地市|各市',question): city='全部地市'
    elif '全省' in question: city='全省'
    else: return None
    return {'tool':'query_suspended','arguments':{'month':month,'city':city}} if suspended else {'tool':'query_city_metrics','arguments':{'month':month,'city':city,'metric':metric}}

def _count(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
        raise ValueError('该期统计数据不完整或格式异常，请核对报告。')
    return value

def _last_friday(month):
    if not isinstance(month,str) or not re.fullmatch(r'\d{4}-\d{2}',month):
        raise ValueError('请提供明确的查询月份，例如 2026 年 10 月。')
    try:
        first=date.fromisoformat(month+'-01')
        last=date(first.year+int(first.month==12),first.month%12+1,1)-timedelta(days=1)
    except ValueError as exc:
        raise ValueError('查询月份无效，请提供有效的年份和月份。') from exc
    return (last-timedelta(days=(last.weekday()-4)%7)).isoformat()

def _city(value):
    if not isinstance(value,str): raise ValueError('请提供查询范围：全省、全部地市或具体地市。')
    value=value.strip()
    if value in ('全省','全部地市'): return value
    if value.endswith('市'): value=value[:-1]
    if value not in CITIES: raise ValueError('未识别地市，请选择安徽省 16 个地市之一。')
    return value

def query(connect, name, arguments, *, structured=False, source_reader=None):
    def output(reply,headers=None,rows=None,footnote=None,available=True):
        if not structured: return reply
        result={'reply':reply,'available':available}
        if headers is not None: result['table']={'headers':headers,'rows':rows,'footnote':footnote}
        return result
    if name not in ('query_city_metrics','query_suspended') or not isinstance(arguments,dict):
        raise ValueError('暂不支持该查询，请换一种方式提问。')
    expected={'month','city','metric'} if name=='query_city_metrics' else {'month','city'}
    if set(arguments)!=expected: raise ValueError('查询条件不完整，请说明月份和地市。')
    period=_last_friday(arguments['month']); city=_city(arguments['city'])
    metric=arguments.get('metric')
    if name=='query_city_metrics' and metric not in METRICS:
        raise ValueError('暂不支持该指标，请确认要查询的统计口径。')
    if source_reader:
        row=source_reader(period)
    else:
        with connect() as c:
            row=c.execute('SELECT data,monthly_data,weekly,monthly FROM reports WHERE period=?',(period,)).fetchone()
    if not row or not (row[2] or row[3]):
        return output(f'{arguments["month"]}缺少最后一个周五（{period}）的报告统计，请导入该期工单表生成报告。',available=False)
    try:
        snapshot=json.loads(row[1] if row[3] and row[1] else row[0])
        if not isinstance(snapshot,dict): raise ValueError()
    except (ValueError,TypeError): raise ValueError('该期统计数据格式异常，请核对报告。')
    kind='月报' if row[3] and row[1] else '周报' if row[2] else '月报'
    title=f'{arguments["month"]}统计（数据日期：{period}；采用{kind}快照）'
    if name=='query_city_metrics':
        if city=='全省': entries=[('全省',snapshot.get('total'))]
        else:
            rows=snapshot.get('cities')
            if not isinstance(rows,list): raise ValueError('该期缺少地市统计，请重新导入该期表格。')
            by_city={r['city']:r for r in rows if isinstance(r,dict) and r.get('city') in CITIES}
            selected=CITIES if city=='全部地市' else [city]
            if any(c not in by_city for c in selected): raise ValueError('该期缺少部分地市统计，请重新导入该期表格。')
            entries=[(c,by_city[c]) for c in selected]
        if metric=='项目进展':
            table_rows=[]; totals={stage:0 for stage in STAGES}
            for label,item in entries:
                stages=item.get('stages') if isinstance(item,dict) else None
                if not isinstance(stages,dict) or any(stage not in stages for stage in STAGES): raise ValueError('该期未保存项目进展明细，请使用当期原表重新生成对应报告。')
                values=[_count(stages[stage]) for stage in STAGES]
                for stage,value in zip(STAGES,values): totals[stage]+=value
                table_rows.append([label]+[f'{value:g}' for value in values])
            count=sum(totals.values());label='全省' if city in ('全省','全部地市') else city+'市'
            summary=f'截至{period}，{label}处于地市处理节点的七个项目进展阶段合计{count:g}处。'
            note='口径：仅统计已确认纳入且处于地市处理节点的黑点，按项目进展分类；不代表所有未解决黑点。数据来源：汇聚黑点-汇总。'
            if city=='全部地市': headers=['地市']+[stage+'（处）' for stage in STAGES];rows=table_rows
            else: headers=['项目阶段','数量（处）'];rows=[[stage,f'{totals[stage]:g}'] for stage in STAGES]
            if structured: return output(summary,headers,rows,note)
            return summary+'\n'+'、'.join(f'{stage}{totals[stage]:g}处' for stage in STAGES)+'\n'+note
        if metric in SCALAR_FIELDS or metric=='关联投诉量':
            fields=('platform_complaints','complaints') if metric=='关联投诉量' else (SCALAR_FIELDS[metric][0],)
            table_rows=[];sums=[0]*len(fields)
            for label,item in entries:
                if not isinstance(item,dict) or any(field not in item for field in fields): raise ValueError('该期未保存所需的汇聚或投诉汇总，请使用当期原表重新生成对应报告。')
                values=[_count(item[field]) for field in fields]
                sums=[a+b for a,b in zip(sums,values)];table_rows.append([label]+[f'{v:g}' for v in values])
            label='全省' if city in ('全省','全部地市') else city+'市'
            if metric=='关联投诉量':
                summary=f'截至{period}，{label}平台汇聚黑点关联投诉{sums[0]:g}件，其中已确认纳入黑点关联投诉{sums[1]:g}件。'
                note='口径：平台汇聚包含该范围所有汇聚黑点；已纳入口径仅统计确认纳入的黑点。数据来源：汇聚黑点-汇总。'
                headers=['地市','平台关联投诉（件）','已纳入关联投诉（件）']
            else:
                unit=SCALAR_FIELDS[metric][1];summary=f'截至{period}，{label}{metric}为{sums[0]:g}{unit}。'
                note=('口径：对该范围全部汇聚黑点计数。' if metric=='汇聚黑点量' else '口径：对该范围全部汇聚黑点的整治前关联未解决投诉求和。' if metric=='平台关联投诉量' else '口径：仅对该范围已确认纳入黑点的整治前关联未解决投诉求和。')+'数据来源：汇聚黑点-汇总。'
                headers=['地市',metric+'（'+unit+'）']
            if city=='全部地市' and structured: return output(summary+'各地市情况如下：',headers,table_rows,note)
            return output(summary+'\n'+note+f'（{kind}快照）')
        lines=[];table_rows=[];sum_included=0;sum_qualified=0
        for label,item in entries:
            if not isinstance(item,dict) or 'included' not in item or 'qualified' not in item: raise ValueError('该期缺少所需统计，请重新导入该期表格。')
            included=_count(item['included']);qualified=_count(item['qualified'])
            sum_included+=included;sum_qualified+=qualified
            if metric=='解决率': value=f'{qualified/included*100:.2f}%（质检合格 {qualified:g} 处 / 确认纳入 {included:g} 处）' if included else f'0.00%（确认纳入 0 处，无分母）'
            else: value=f'{(included if metric=="确认纳入数" else qualified):g} 处'
            lines.append(f'{label}：{value}')
            table_rows.append([label,f'{included:g}',f'{qualified:g}',f'{qualified/included*100:.2f}%' if included else '0.00%（无纳入）'] if metric=='解决率' else [label,f'{(included if metric=="确认纳入数" else qualified):g}'])
        if city=='全部地市' and structured:
            headers=['地市','确认纳入（处）','质检合格（处）','解决率'] if metric=='解决率' else ['地市',metric+'（处）']
            if metric=='解决率':
                summary=(f'截至{period}，全省确认纳入{sum_included:g}处，其中质检合格{sum_qualified:g}处，整体解决率为{sum_qualified/sum_included*100:.2f}%。' if sum_included else f'截至{period}，全省确认纳入0处，当前无分母，解决率显示为0.00%。')
            else:
                total=sum_included if metric=='确认纳入数' else sum_qualified
                summary=f'截至{period}，全省{metric}共{total:g}处。'
            return output(summary+'各地市情况如下：',headers,table_rows,'解决率 = 质检合格数 ÷ 确认纳入数；分母为 0 时显示 0%。数据来源：汇聚黑点-汇总。' if metric=='解决率' else '数据来源：汇聚黑点-汇总。')
        if city!='全部地市':
            label='全省' if city=='全省' else city+'市'
            if metric=='解决率':
                if included:
                    summary=f'截至{period}，{label}黑点解决率为{qualified/included*100:.2f}%，累计确认纳入{included:g}处，其中质检合格{qualified:g}处。'
                    if qualified<=included: summary+=f'还有{included-qualified:g}处尚未质检合格。'
                else: summary=f'截至{period}，{label}没有确认纳入的黑点，解决率按当前口径显示为0.00%（分母为0）。'
            else:
                value=included if metric=='确认纳入数' else qualified
                summary=f'截至{period}，{label}黑点{metric}为{value:g}处。'
            return output(summary+f'\n数据来源：汇聚黑点-汇总（{kind}快照）。'+('\n口径：解决率 = 质检合格数 ÷ 确认纳入数。' if metric=='解决率' else ''))
        return output(title+'\n'+metric+'\n'+'\n'.join(lines)+'\n口径：解决率 = 质检合格数 ÷ 确认纳入数；数据来源：汇聚黑点-汇总。')
    suspended=snapshot.get('suspended')
    if not isinstance(suspended,dict) or 'count' not in suspended: raise ValueError('该期缺少挂起库统计，请重新导入该期表格。')
    # Both labels describe the same metric; independently collected totals must agree.
    if city=='全省':
        count=_count(suspended['count'])
        total=snapshot.get('total')
        if isinstance(total,dict) and 'suspended' in total and _count(total['suspended'])!=count:
            return output(f'{period}挂起数据来源不一致：挂起工作表与汇聚表的申请挂起数量不同，请核对原表。',available=False)
        return output(f'截至{int(period[:4])}年{int(period[5:7])}月，全省挂起库累计{count:g}处。\n统计日期：{period}；数据来源：挂起工作表。')
    else:
        values=suspended.get('cities')
        if snapshot.get('snapshot_version')!=2 or not isinstance(values,list): raise ValueError('该期未保存挂起库地市分布，请重新导入该期表格生成报告。')
        try:
            distribution={name:_count(n) for name,n in values if name in CITIES}
        except (ValueError,TypeError): raise ValueError('该期挂起库地市数据格式异常，请核对报告。')
        raw_cities=snapshot.get('cities')
        if isinstance(raw_cities,list):
            other={r.get('city'):r['suspended'] for r in raw_cities if isinstance(r,dict) and r.get('city') in CITIES and 'suspended' in r}
            selected=CITIES if city=='全部地市' else [city]
            if any(name in other and _count(other[name])!=distribution.get(name,0) for name in selected):
                return output(f'{period}挂起数据来源不一致：部分地市在挂起工作表和汇聚表中的数量不同，请核对原表。',available=False)
        lines=[f'{name}：{distribution.get(name,0):g} 处' for name in (CITIES if city=='全部地市' else [city])]
        if city=='全部地市' and structured:
            return output(f'截至{period}，全省挂起库累计{_count(suspended["count"]):g}处。各地市情况如下：',['地市','挂起库数量（处）'],[[name,f'{distribution.get(name,0):g}'] for name in CITIES],'数据来源：挂起工作表。')
    return output(f'截至{period}，{city}市挂起库累计{distribution.get(city,0):g}处。\n数据来源：挂起工作表（{kind}快照）。')


def highest_resolution_plan(question):
    text=re.sub(r'\s+','',question)
    if not re.search(r'(?:黑点|重点投诉区域)',text) or not re.search(r'解决率|质检合格率',text) or not re.search(r'最高|第一|第1',text):return None
    if re.search(r'最低|倒数|前[二三四五六七八九十0-9]|后[二三四五六七八九十0-9]|同比|环比|上月|较上|对比|比较|相比|原因|哪些指标',text) or any(city in text for city in CITIES):
        return {'error':'请明确查询全省各地市某个月的最高黑点解决率；其他排名或对比请分别提问。'}
    matches=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])\s*月?',text)
    if len(matches)==1:month=f'{matches[0][0]}-{int(matches[0][1]):02d}'
    else:
        months=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])月',text)
        if len(matches)>1 or len(months)!=1:return {'error':'请指定一个统计月份，例如“2026年10月哪个地市黑点解决率最高”。'}
        month=f'{date.today().year}-{int(months[0]):02d}'
    return {'month':month}

def highest_resolution(connect,month,*,source_reader=None):
    result=query(connect,'query_city_metrics',{'month':month,'city':'全部地市','metric':'解决率'},structured=True,source_reader=source_reader)
    if not result.get('available') or not result.get('table'):return result
    ranking=[]; excluded=[]
    for city,included,qualified,_ in result['table']['rows']:
        base=Fraction(included);passed=Fraction(qualified)
        if passed>base:raise ValueError('存在质检合格数大于纳入数的地市，无法确定排名，请核对统计数据。')
        if not base:excluded.append(city);continue
        ranking.append((passed/base,city,included,qualified))
    if not ranking:return {'reply':f'{month}各地市均无确认纳入黑点，无法计算最高解决率。','available':False}
    best=max(r[0] for r in ranking);winners=[r for r in ranking if r[0]==best]
    names='、'.join(r[1]+'市' for r in winners)
    detail='；'.join(f'{city}质检合格{passed}处／确认纳入{base}处' for _,city,base,passed in winners)
    period=_last_friday(month)
    reply=f"截至{period}，{month}黑点解决率最高的是{names}，{'并列' if len(winners)>1 else ''}{float(best)*100:.2f}%。{detail}。"
    note='解决率＝质检合格数÷确认纳入数；按未四舍五入的比率判断并列。'
    if excluded:note+='确认纳入为零的地市不参与排名：'+'、'.join(excluded)+'。'
    return {'reply':reply,'evidence':note+' 数据日期：'+period+'。','table':result['table'],'available':True}
