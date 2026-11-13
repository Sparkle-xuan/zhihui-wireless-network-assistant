"""Controlled follow-up resolution for explicit, supported statistical queries."""
import re
import network_query
from core import CITIES

# Resolve only contiguous, unambiguous scope follow-ups; never infer from assistant prose.
def _network_scope_followup(text):
    compact=re.sub(r'\s+','',text)
    names='|'.join(CITIES)
    match=re.fullmatch(r'(?P<scope>全省|安徽省|全部地市|各地市|各市|'+names+r')(?:市)?(?:的)?(?:呢|怎么样|如何|多少|是多少|有多少)?[？?。！!]*',compact)
    if not match:return None
    scope=match.group('scope')
    if scope in ('安徽省','全省'):return '全省'
    if scope in ('全部地市','各地市','各市'):return '全部地市'
    return scope


def resolve_network_followup(messages):
    questions=[m['content'].strip() for m in messages if m.get('role')=='user']
    if len(questions)<2:return None
    current=_network_scope_followup(questions[-1])
    if not current:return None
    state=None
    for question in questions[:-1]:
        plan=network_query.local_plan(question)
        if plan and 'arguments' in plan:
            state=plan['arguments'].copy();continue
        scope=_network_scope_followup(question)
        if state and scope:
            state['city']=scope;continue
        state=None
    if not state:return None
    state['city']=current
    return {'tool':'query_network_daily','arguments':state}

# Semantic aliases are explicit; formulas and data remain in their existing tool.
METRIC_CATALOG={
    'blackspot.suspended':{'name':'挂起库数量','aliases':['挂起库','申请挂起'],'tool':'query_suspended','unit':'处','period':'月末周五快照'},
    'blackspot.resolution_rate':{'name':'解决率','aliases':['解决率','质检合格率'],'formula':'质检合格数 / 确认纳入数','unit':'%'},
    'network.5g_traffic':{'name':'5G数据流量','aliases':['5G数据流量','5G流量'],'unit':'TB','period':'日'},
}

# Daily metric names and units are derived from the approved query definitions.
for _name, _definition in network_query.METRICS.items():
    METRIC_CATALOG['network.'+_name]={'name':_name,'unit':_definition[5],'period':'日','tool':'query_network_daily'}

def validate_network_plan(plan):
    """Reject unregistered metrics and unsupported dimensions before executing a query."""
    if not isinstance(plan,dict) or plan.get('tool')!='query_network_daily':return False
    args=plan.get('arguments')
    return (isinstance(args,dict) and set(args)=={'day','city','metric'}
            and 'network.'+str(args['metric']) in METRIC_CATALOG
            and args['city'] in (*CITIES,'全省','全部地市')
            and isinstance(args['day'],str)
            and (args['day']=='latest' or bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}',args['day']))))
