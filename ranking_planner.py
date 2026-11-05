"""Structured intent and safe execution for blackspot city-rate rankings."""
import json,re
from datetime import date
from fractions import Fraction
import requests
from assistant_service import ENDPOINT,validate_model
from analysis_planner import _possible_months,_grounding_messages
from smart_query import query as query_statistics,_last_friday
from core import CITIES

TOOL={'type':'function','function':{'name':'plan_city_ranking','description':'规划安徽地市黑点解决率的单月排名，信息不足时澄清。','parameters':{'type':'object','properties':{'operation':{'type':'string','enum':['rank','clarify']},'month':{'type':'string'},'direction':{'type':'string','enum':['asc','desc','']},'limit':{'type':'integer'},'metric':{'type':'string','enum':['blackspot_resolution_rate','']}},'required':['operation','month','direction','limit','metric']}}}

def should_plan(messages):
    q=messages[-1]['content']
    if re.search(r'比|对比|同比|环比|原因|挂起|投诉量|流量|网络质量|项目进展',q):return False
    if not re.search(r'倒数|排名|排行|第[一二三四五六七八九十0-9]|(?:前|后)[一二三四五六七八九十0-9]+',q):return False
    context=' '.join(m['content'] for m in _grounding_messages(messages))
    return bool(re.search(r'黑点|重点投诉区域',context) and re.search(r'解决率|合格率',context))

def explicit_limit(q):
    m=re.search(r'(?:倒数)?前([一二三四五六七八九十0-9]+)|(?:倒数|最低|最高|后)([一二三四五六七八九十0-9]+)',q)
    if not m:
        if re.search(r'第(?:一|1)(?:名)?',q):return 1
        return 16 if re.search(r'排名|排行',q) else None
    value=m.group(1) or m.group(2);mapping={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
    try:n=mapping.get(value) if value in mapping else int(value)
    except ValueError:return None
    return n if n is not None and 1<=n<=16 else None

def direction(q):
    if re.search(r'倒数|最低|从低到高|后[一二三四五六七八九十0-9]',q):return 'asc'
    if re.search(r'最高|从高到低|第(?:一|1)(?:名)?|前[一二三四五六七八九十0-9]',q):return 'desc'
    return None

def rank_months(messages):
    # An explicit month in the current turn replaces previous comparison months.
    q=messages[-1]['content']
    if re.search(r'(?<!\d)(?:1[0-2]|0?[1-9])月|20\d{2}[-/](?:1[0-2]|0?[1-9])',q):
        if not re.search(r'20\d{2}',q):
            context=_grounding_messages(messages)
            if len(context)>1:
                years=set(re.findall(r'(?<!\d)(20\d{2})(?:年|[-/])',context[0]['content']))
                if len(years)==1:q=next(iter(years))+'年'+q
        return _possible_months([{'role':'user','content':q}])
    return _possible_months(messages)

def validate(plan,messages):
    if not isinstance(plan,dict) or set(plan)!={'operation','month','direction','limit','metric'}:return None
    if plan.get('operation')=='clarify':return {'operation':'clarify'}
    if plan.get('operation')!='rank' or plan.get('metric')!='blackspot_resolution_rate':return None
    q=messages[-1]['content'];d=direction(q);n=explicit_limit(q)
    if d is None or n is None or plan.get('direction')!=d or type(plan.get('limit')) is not int or plan['limit']!=n:return None
    if not isinstance(plan.get('month'),str) or plan['month'] not in rank_months(messages):return None
    if re.search(r'最高.*最低|最低.*最高|上月|本月.*上月',q):return None
    if any(city in q for city in CITIES):return None
    try:_last_friday(plan['month'])
    except ValueError:return None
    return plan

def fallback(messages):
    q=messages[-1]['content'];months=rank_months(messages);d=direction(q);n=explicit_limit(q)
    if len(months)!=1 or not d or not n:return None
    return validate({'operation':'rank','month':next(iter(months)),'direction':d,'limit':n,'metric':'blackspot_resolution_rate'},messages)

def create_plan(key,messages,model):
    model=validate_model(model);questions=[m['content'] for m in _grounding_messages(messages)]
    system=('你是问数规划器，解析单月安徽地市黑点解决率排名，不产生数据或SQL。'
            '最低或倒数取asc，最高或正向排名取desc；limit为用户指定的地市数。'
            '本轮省略指标时仅可继承紧邻的上一轮用户问题；不确定则clarify。当前日期：'+date.today().isoformat())
    try:
        r=requests.post(ENDPOINT,headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'},json={'model':model,'thinking':{'type':'disabled'},'messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(questions,ensure_ascii=False)}],'tools':[TOOL],'tool_choice':{'type':'function','function':{'name':'plan_city_ranking'}},'max_tokens':400},timeout=(6,25),allow_redirects=False)
        if r.status_code!=200:return fallback(messages)
        calls=r.json()['choices'][0]['message']['tool_calls']
        if not isinstance(calls,list) or len(calls)!=1:return fallback(messages)
        fn=calls[0]['function'];raw=fn['arguments']
        if fn['name']!='plan_city_ranking' or not isinstance(raw,str) or len(raw)>2000:return fallback(messages)
        plan=validate(json.loads(raw),messages)
        return plan if plan and plan['operation']!='clarify' else fallback(messages)
    except (requests.RequestException,ValueError,KeyError,TypeError,IndexError):return fallback(messages)

def execute(plan,connect,*,source_reader=None):
    result=query_statistics(connect,'query_city_metrics',{'month':plan['month'],'city':'全部地市','metric':'解决率'},structured=True,source_reader=source_reader)
    if not result.get('available') or not result.get('table'):return result
    eligible=[];excluded=[]
    for city,included,qualified,_ in result['table']['rows']:
        denominator=Fraction(included);numerator=Fraction(qualified)
        if numerator>denominator:raise ValueError('存在质检合格数大于纳入数的地市，请核对统计数据。')
        if not denominator:excluded.append(city);continue
        eligible.append((numerator/denominator,city,included,qualified))
    eligible.sort(key=lambda x:x[0],reverse=plan['direction']=='desc')
    if not eligible:return {'reply':'该月各地市均无确认纳入黑点，无法排名。','available':False}
    count=min(plan['limit'],len(eligible));cut=eligible[count-1][0]
    selected=[r for r in eligible if r[0]<=cut] if plan['direction']=='asc' else [r for r in eligible if r[0]>=cut]
    rows=[];previous=None;rank=0
    for index,(value,city,included,qualified) in enumerate(selected,1):
        if value!=previous:rank=index;previous=value
        rows.append([str(rank),city,f'{float(value)*100:.2f}%',qualified,included])
    label='最低' if plan['direction']=='asc' else '最高'
    listing='、'.join(f'{r[1]}{r[2]}' for r in rows)
    extra='；末位并列，一并列出' if len(selected)>count else ''
    note='按未四舍五入的解决率计算；解决率＝质检合格数÷确认纳入数。'
    if excluded:note+='无纳入黑点不参与排名：'+'、'.join(excluded)+'。'
    period=_last_friday(plan['month'])
    return {'reply':f"截至{period}，{plan['month']}黑点解决率{label}的{count}个地市：{listing}{extra}。",'available':True,'table':{'headers':['名次','地市','解决率','质检合格（处）','确认纳入（处）'],'rows':rows,'footnote':note},'evidence':f'统计日期：{period}。'+note}
