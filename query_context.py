"""Controlled follow-up resolution for explicit, supported statistical queries."""
import re
import network_query
from core import CITIES

# Only inherit from the immediately previous user question; never infer from model prose.
def resolve_network_followup(messages):
    current=messages[-1]['content'].strip()
    previous=next((m['content'] for m in reversed(messages[:-1]) if m.get('role')=='user'),None)
    if not previous or re.search(r'对比|相比|同比|环比|趋势|排名|原因|为什么|明细|小区|黑点|挂起',current): return None
    previous_plan=network_query.local_plan(previous)
    if not previous_plan or 'arguments' not in previous_plan: return None
    args=previous_plan['arguments'].copy()
    # Only recognized terse follow-ups carry previous metric and date.
    named=[c for c in CITIES if c in current]
    all_cities=bool(re.search(r'各地市|全部地市|各市',current))
    province=bool(re.search(r'全省|安徽省',current))
    if len(named)>1 or sum((bool(named),all_cities,province))>1:return None
    if not (named or all_cities or province):return None
    if not re.fullmatch(r'[\s\u4e00-\u9fff0-9年月日号？?，,的呢怎么样如何多少是]+',current):return None
    if network_query.recognize(current) not in (None,args['metric']):return None
    if re.search(r'20\d{2}|\d{1,2}月|今天|昨天|前天|最新|本月|上月|去年|今年',current):return None
    args['city']=named[0] if named else '全部地市' if all_cities else '全省'
    return {'tool':'query_network_daily','arguments':args}

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
