"""Resolve a narrow multi-turn reference by recomputing a concrete ranking."""
import re
import os
import json
import hashlib
from fractions import Fraction
from itsdangerous import URLSafeTimedSerializer, BadSignature
import ranking_planner
import smart_query
from core import CITIES

_signer=URLSafeTimedSerializer(os.urandom(32),salt='zhihui-guided-ranking')

def _fingerprint(result):
    value={'source':result.get('source_info'),'rows':(result.get('table') or {}).get('rows')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def context_for(question,plan,result):
    rows=(result.get('table') or {}).get('rows') or []
    if not result.get('available') or not rows:return None
    return _signer.dumps({'question_hash':hashlib.sha256(question.encode()).hexdigest(),'month':plan['month'],'fingerprint':_fingerprint(result)})

def attention_plan(question):
    if not (re.search(r'黑点|重点投诉区域',question) and re.search(r'解决率|解决情况|合格率',question) and re.search(r'哪些地市|哪些市|各地市',question) and re.search(r'关注|需要注意',question)) or re.search(r'比较|相比|对比|上月|环比|原因|项目进展|挂起|投诉量|流量|网络质量',question) or any(city in question for city in CITIES):return None
    months=ranking_planner.rank_months([{'role':'user','content':question}])
    if len(months)!=1:return {'error':'请明确需要分析的一个月份。'}
    return {'month':next(iter(months)),'direction':'asc','limit':3}

def initial(question,connect,*,source_reader=None):
    plan=attention_plan(question)
    if not plan:return None
    if 'error' in plan:return {'reply':plan['error'],'local_query':True}
    result=ranking_planner.execute(plan,connect,source_reader=source_reader)
    if result.get('available'):result['reply']='按解决率倒数前三筛选：'+result['reply']
    context=context_for(question,plan,result)
    if context:result['query_context']=context
    result.pop('available',None);result['local_query']=True
    return result

def execute(messages,connect,*,source_reader=None,context=None):
    users=[m['content'] for m in messages if m.get('role')=='user']
    if len(users)<2:return None
    q=users[-1]
    reference=bool(re.search(r'第(?:一|1)个地市|第(?:一|1)名地市|第(?:一|1)个|它|该地市',q))
    stage=bool(re.search(r'环节|阶段|项目进展|工程进展|卡在|卡在哪',q))
    action=bool(re.search(r'加入.*(?:推进|跟踪)|准备.*(?:提醒|邮件)',q))
    if not reference or not (stage or action):return None
    previous=users[-2]
    # At most one intervening, referential stage question; never inherit through a topic change.
    if re.search(r'第(?:一|1)个|第(?:一|1)名地市|它|该地市',previous) and re.search(r'环节|阶段|项目进展|工程进展|卡在|卡在哪',previous):
        if len(users)<3:return {'reply':'请先指定地市和统计月份。','local_query':True}
        previous=users[-3]
    plan=attention_plan(previous)
    if not plan and ranking_planner.should_plan([{'role':'user','content':previous}]):plan=ranking_planner.fallback([{'role':'user','content':previous}])
    if plan and 'error' in plan:plan=None
    if not plan:return {'reply':'请先明确黑点解决率排名的月份、方向和数量。','local_query':True}
    try:
        if not isinstance(context,str) or len(context)>3000:raise BadSignature('missing')
        saved=_signer.loads(context,max_age=3600)
        if saved.get('question_hash')!=hashlib.sha256(previous.encode()).hexdigest() or saved.get('month')!=plan['month']:raise BadSignature('mismatch')
    except (BadSignature,TypeError,ValueError,AttributeError):
        return {'reply':'无法安全确认上一轮排名，请重新查询后再选择地市。','local_query':True}
    ranked=ranking_planner.execute(plan,connect,source_reader=source_reader)
    rows=(ranked.get('table') or {}).get('rows') or []
    if not ranked.get('available') or not rows:return {'reply':ranked.get('reply','排名数据不可用。'),'local_query':True}
    if _fingerprint(ranked)!=saved.get('fingerprint'):return {'reply':'排名数据已发生变化，请重新查询后再选择地市。','local_query':True}
    if len(rows)>1 and rows[0][0]==rows[1][0]:return {'reply':'排名第一有并列地市，请明确要查看哪个地市。','local_query':True}
    city=rows[0][1];month=plan['month'];period=(ranked.get('source_info') or {}).get('period')
    named=[name for name in CITIES if name in q]
    if len(named)>1 or named and named[0]!=city:return {'reply':'本轮指定的地市与上一轮排名不一致，请明确要处理的地市。','local_query':True}
    if re.search(r'20\d{2}|\d+\s*月|本月|上月|上个月',q):
        anchored=month[:4]+'年'+q if re.search(r'\d+\s*月',q) and not re.search(r'20\d{2}',q) else q
        months=ranking_planner.rank_months([{'role':'user','content':anchored}])
        if months!={month}:return {'reply':'本轮月份与上一轮排名不一致，请明确统计月份。','local_query':True}
    if action:
        return {'reply':f'按当前 {month} 排名重新核对，第一个地市是{city}。可打开提醒页面，将事项带入推进表单；请核对并手动保存或准备邮件。','action':{'type':'open_city_alerts','month':month,'city':city,'followup':True},'local_query':True}
    result=smart_query.query(connect,'query_city_metrics',{'month':month,'city':city,'metric':'项目进展'},structured=True,source_reader=source_reader)
    check=ranking_planner.execute(plan,connect,source_reader=source_reader)
    if not check.get('available') or _fingerprint(check)!=saved.get('fingerprint'):return {'reply':'查询期间排名数据发生变化，请重新查询后再选择地市。','local_query':True}
    result['reply']=f'按当前 {month} 排名重新核对，第一个地市是{city}。'+result.get('reply','')
    stages=(result.get('table') or {}).get('rows') or []
    if stages:
        top=max(Fraction(row[1]) for row in stages)
        if top>0:result['reply']+=' 当前数量较多的项目阶段：'+'、'.join(f'{row[0]} {row[1]}处' for row in stages if Fraction(row[1])==top)+'。'
        else:result['reply']+=' 七个阶段均无记录，无法根据阶段分布判断推进障碍。'
    result['evidence']=f'排名数据日期：{period or "未提供"}；项目阶段仅统计已纳入且处于地市处理节点的区域，不等于全部未解决区域。'
    result['query_context']=context
    result.pop('available',None);result['local_query']=True
    return result
