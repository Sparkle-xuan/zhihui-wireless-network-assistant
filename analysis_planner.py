"""Bounded LLM planning and deterministic multi-step blackspot analysis."""
import json,re
from datetime import date
from fractions import Fraction
import requests
from core import CITIES
from smart_query import query as query_statistics, _last_friday
from assistant_service import ENDPOINT, validate_model

TOOL={'type':'function','function':{'name':'plan_blackspot_analysis','description':'将黑点解决率复杂问题转换为受控查询计划，无法确定时选择 clarify。','parameters':{'type':'object','properties':{'operation':{'type':'string','enum':['highest_compare','compare','clarify']},'month':{'type':'string','description':'基准月 YYYY-MM，不确定时为空字符串'},'other_month':{'type':'string','description':'比较月 YYYY-MM，不确定时为空字符串'},'city':{'type':'string','description':'安徽具体地市、全省或全部地市；最高地市比较填全部地市'},'clarification':{'type':'string','description':'需要补充条件时的简短问题，否则为空字符串'}},'required':['operation','month','other_month','city','clarification']}}}

def should_plan(messages):
    # Only select the analysis capability; the model decides the actual plan.
    current=messages[-1]['content']
    context=' '.join(m['content'] for m in messages[-5:] if m['role']=='user')
    return bool(re.search(r'黑点|重点投诉区域|解决率|合格率',context) and re.search(r'比|对照|变化|上月|上个月|前一个月|环比',current) and not re.search(r'怎么算|公式|定义|什么意思|口径|挂起|流量|用户数|投诉量|项目进展|最低|倒数',current))

def _grounding_messages(messages):
    # Reuse only the immediately preceding relevant user question for follow-ups.
    questions=[m for m in messages if m['role']=='user']
    current=questions[-1]
    if len(questions)>1 and re.search(r'解决率|合格率',questions[-2]['content']):
        return questions[-2:]
    return [current]

def _possible_months(messages,today=None):
    today=today or date.today(); text=' '.join(m['content'] for m in _grounding_messages(messages))
    years=re.findall(r'(?<!\d)(20\d{2})年',text)
    if len(set(years))>1:return set()
    year=int(years[0]) if years else today.year
    pairs=re.findall(r'(?<!\d)(20\d{2})[-/](1[0-2]|0?[1-9])(?:[-/]\d{1,2})?',text)
    months={f'{int(y):04d}-{int(m):02d}' for y,m in pairs}
    months.update(f'{year:04d}-{int(m):02d}' for m in re.findall(r'(?<!\d)(1[0-2]|0?[1-9])月',text))
    if '本月' in text or '这个月' in text:months.add(f'{today.year:04d}-{today.month:02d}')
    if re.search(r'上月|上个月|前一个月|上期',text):
        # Relative month is anchored on the most recent explicitly mentioned month.
        explicit=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])月',text)
        anchor=date(year,int(explicit[-1]),1) if explicit else date(today.year,today.month,1)
        prior=anchor.replace(day=1).toordinal()-1
        d=date.fromordinal(prior);months.add(f'{d.year:04d}-{d.month:02d}')
    return months

def validate_plan(plan,messages):
    if not isinstance(plan,dict) or set(plan)!={'operation','month','other_month','city','clarification'}:return None
    if any(not isinstance(v,str) or len(v)>100 for v in plan.values()):return None
    if plan['operation']=='clarify':return {'operation':'clarify'}
    if plan['operation'] not in ('highest_compare','compare'):return None
    allowed=_possible_months(messages)
    if plan['month']==plan['other_month'] or not {plan['month'],plan['other_month']}.issubset(allowed):return None
    try:_last_friday(plan['month']);_last_friday(plan['other_month'])
    except ValueError:return None
    city=plan['city'].removesuffix('市');text=' '.join(m['content'] for m in _grounding_messages(messages))
    if plan['operation']=='highest_compare':
        if plan['city']!='全部地市' or not re.search(r'最高|第一|第1|第一名',text):return None
        # Do not let the model swap which month supplies the winners.
        before_highest=re.split(r'最高|第一|第1|第一名',text,1)[0]
        mentioned=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])月',before_highest)
        if mentioned and int(plan['month'][5:])!=int(mentioned[-1]):return None
    elif city not in CITIES or city not in text:return None
    else:plan={**plan,'city':city}
    return plan

def create_plan(key,messages,model):
    model=validate_model(model)
    # Previous assistant messages can contain data; never send them to this planner.
    questions=[m['content'] for m in messages if m['role']=='user'][-4:]
    system=('你是统计查询规划器。只规划黑点解决率的两月比较。不要回答数值，不生成SQL。'
            '最高地市再比较另一月用highest_compare；指定某个地市两月比较用compare。'
            '无法确定两个年月或地市时用clarify；没有明确年份时按当前年份。'
            'month是先筛选或用户主要关注的月份，other_month是对照月份。'
            '仅使用用户问题给出的条件，当前日期为'+date.today().isoformat()+'。')
    try:
        r=requests.post(ENDPOINT,headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'},json={'model':model,'thinking':{'type':'disabled'},'messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(questions,ensure_ascii=False)}],'tools':[TOOL],'tool_choice':{'type':'function','function':{'name':'plan_blackspot_analysis'}},'max_tokens':500},timeout=(6,25),allow_redirects=False)
        if r.status_code!=200:return None
        calls=r.json()['choices'][0]['message']['tool_calls']
        if not isinstance(calls,list) or len(calls)!=1:return None
        fn=calls[0]['function'];raw=fn['arguments']
        if fn['name']!='plan_blackspot_analysis' or not isinstance(raw,str) or len(raw)>2000:return None
        return validate_plan(json.loads(raw),messages)
    except (requests.RequestException,ValueError,KeyError,TypeError,IndexError):return None

def _read_cities(connect,month,source_reader):
    result=query_statistics(connect,'query_city_metrics',{'month':month,'city':'全部地市','metric':'解决率'},structured=True,source_reader=source_reader)
    if not result.get('available') or not result.get('table'):return None,result.get('reply','数据缺失。')
    values={}
    for city,included,qualified,_ in result['table']['rows']:
        denominator=Fraction(included);numerator=Fraction(qualified)
        if numerator>denominator:raise ValueError('质检合格数大于纳入数，请核对该期数据。')
        values[city]=None if denominator==0 else numerator/denominator
    return values,None

def execute(plan,connect,*,source_reader=None):
    if plan['operation']=='clarify':return {'reply':'请说明要比较的两个月，以及地市或最高解决率范围。','available':False}
    now,error=_read_cities(connect,plan['month'],source_reader)
    if error:return {'reply':error,'available':False}
    if plan['operation']=='highest_compare':
        eligible={city:rate for city,rate in now.items() if rate is not None}
        if not eligible:return {'reply':'该月各地市均无纳入黑点，无法比较解决率。','available':False}
        best=max(eligible.values());cities=[c for c in CITIES if eligible.get(c)==best]
    else:cities=[plan['city']]
    before,error=_read_cities(connect,plan['other_month'],source_reader)
    if error:return {'reply':f"{plan['other_month']}对照数据不可用：{error}",'available':False}
    rows=[]
    for city in cities:
        a,b=now[city],before[city]
        if a is None or b is None:rows.append([city,'无分母' if a is None else f'{float(a)*100:.2f}%','无分母' if b is None else f'{float(b)*100:.2f}%','无法比较']);continue
        delta=float(a-b)*100
        rows.append([city,f'{float(a)*100:.2f}%',f'{float(b)*100:.2f}%',f'{delta:+.2f}个百分点'])
    scope='、'.join(cities)+'（并列最高）' if plan['operation']=='highest_compare' and len(cities)>1 else cities[0]+('（最高）' if plan['operation']=='highest_compare' else '')
    summary=f"{plan['month']}黑点解决率{scope}；与{plan['other_month']}相比，"+'；'.join(f'{r[0]}本期{r[1]}、对照期{r[2]}，变化{r[3]}' for r in rows)+'。'
    return {'reply':summary,'available':True,'table':{'headers':['地市',plan['month']+'解决率',plan['other_month']+'解决率','变化'],'rows':rows,'footnote':f"数据日期：{_last_friday(plan['month'])}、{_last_friday(plan['other_month'])}；解决率为质检合格数除以确认纳入数，按未四舍五入比率计算；无分母不参与排名。"}}
