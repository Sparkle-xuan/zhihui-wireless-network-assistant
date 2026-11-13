"""Bounded local question evaluation; fixtures never use the business database."""
import json
import hashlib
import sqlite3
from fractions import Fraction
from contextlib import contextmanager
from datetime import date
from core import CITIES
import assistant_actions,intent_router,smart_query,ranking_planner

ROUTES=('suspension_growth','daily_comparison','suspension','ranked_comparison','city_comparison','suspension_reason','analysis','ranking','highest_resolution','network_comparison','network_overview','network_metric','general')
BUILTIN=[
 ('挂起库','2026年10月各地市挂起数量最多的前三名','suspension'),
 ('挂起库','2026年10月合肥挂起主要问题是什么','suspension_reason'),
 ('挂起库','2026年10月哪些地市挂起数量连续两个月增长','suspension_growth'),
 ('黑点','2026年10月哪个地市黑点解决率最低，和上个月比怎么样','ranked_comparison'),
 ('黑点','2026年10月各地市黑点解决率和上月相比','city_comparison'),
 ('网络日报','2026年11月2日简述日报内容','network_overview'),
 ('网络日报','2026年10月21日全省5G流量与10月20日相比怎么样','daily_comparison'),
 ('网络日报','2026年10月21日合肥5G流量是多少','network_metric'),
]
EXPECTED_FIELDS={
 '2026年10月各地市挂起数量最多的前三名':{'month':'2026-10','direction':'desc','limit':3},
 '2026年10月合肥挂起主要问题是什么':{'month':'2026-10','city':'合肥','source':'suspension'},
 '2026年10月各地市黑点解决率和上月相比':{'month':'2026-10','other_month':'2026-09'},
 '2026年11月2日简述日报内容':{'day':'2026-11-02'},
 '2026年10月21日合肥5G流量是多少':{'arguments':{'day':'2026-10-21','city':'合肥','metric':'5G数据流量'}},
}
def ensure(c):
    c.execute('CREATE TABLE IF NOT EXISTS assistant_evaluation_cases (id TEXT PRIMARY KEY, category TEXT NOT NULL, question TEXT NOT NULL, expected_route TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS assistant_evaluation_previous (id INTEGER PRIMARY KEY, snapshot TEXT NOT NULL)')

def add(connect,category,question,expected_route):
    from uuid import uuid4
    if category not in ('黑点','挂起库','网络日报','其他') or expected_route not in ROUTES:raise ValueError('请选择有效的分类和预期路由。')
    if not isinstance(question,str) or not question.strip() or len(question)>500:raise ValueError('问题应为 1 至 500 字。')
    ident=uuid4().hex
    with connect() as c:
        ensure(c)
        if c.execute('SELECT COUNT(*) FROM assistant_evaluation_cases').fetchone()[0]>=200:raise ValueError('自定义测试题已达到 200 条上限。')
        c.execute('INSERT INTO assistant_evaluation_cases (id,category,question,expected_route) VALUES (?,?,?,?)',(ident,category,question.strip(),expected_route))
    return ident

def run(connect):
    with connect() as c:
        ensure(c);custom=c.execute('SELECT category,question,expected_route FROM assistant_evaluation_cases ORDER BY id LIMIT 200').fetchall()
    results=[]
    for category,question,expected in BUILTIN+list(custom):
        try:
            actual,plan=intent_router.route([{'role':'user','content':question}]);fields=EXPECTED_FIELDS.get(question)
            fields_ok=not fields or isinstance(plan,dict) and all(plan.get(k)==v for k,v in fields.items())
            passed=actual==expected and fields_ok
            results.append({'category':category,'question':question,'expected':expected,'actual':actual,'passed':passed,'detail':('路由及条件匹配' if fields else '路由匹配') if passed else ('日期、地市或指标条件不匹配' if actual==expected else '识别路由与预期不同')})
        except Exception:results.append({'category':category,'question':question,'expected':expected,'actual':'异常','passed':False,'detail':'路由检查异常'})
    def append(name,ok,detail):results.append({'category':'计算与缺数','question':name,'expected':'通过','actual':'通过' if ok else '失败','passed':bool(ok),'detail':detail})
    db=sqlite3.connect(':memory:')
    @contextmanager
    def fixture():yield db
    try:
        db.execute('CREATE TABLE reports (period TEXT PRIMARY KEY,data TEXT NOT NULL,notes TEXT NOT NULL,weekly TEXT NOT NULL,monthly TEXT NOT NULL,monthly_data TEXT)')
        cities=[{'city':c,'included':10,'qualified':i%10} for i,c in enumerate(CITIES)]
        db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?)',('2026-10-30',json.dumps({'cities':cities,'total':{'included':160,'qualified':70}}),'{}','fixture','',None))
        result=smart_query.query(fixture,'query_city_metrics',{'month':'2026-10','city':'全部地市','metric':'解决率'},structured=True)
        rows=(result.get('table') or {}).get('rows',[])
        append('模拟地市解决率计算',len(rows)==16 and Fraction(rows[1][1])==10 and Fraction(rows[1][2])==1 and rows[1][3]=='10.00%','确认纳入10、质检合格1的地市应对应10%。')
        rank=ranking_planner.execute({'month':'2026-10','direction':'asc','limit':3},fixture)
        append('模拟倒数排名',rank.get('available') and bool((rank.get('table') or {}).get('rows')),'排名使用已保存的模拟地市汇总。')
        missing=smart_query.query(fixture,'query_city_metrics',{'month':'2098-01','city':'全部地市','metric':'解决率'},structured=True)
        append('缺失月份不补零',not missing.get('available'),'缺少快照时应返回不可用。')
        action=assistant_actions.plan('生成2026年10月黑点解决率分析报告并发送邮件',date(2026,11,10))
        append('报告与邮件确认',bool(action and action.get('action',{}).get('type')=='open_analysis_report'),'仅打开报告入口，不自动发送邮件。')
    except Exception:append('模拟数据执行',False,'测试夹具执行异常，请检查服务日志。')
    finally:db.close()
    return {'items':results,'total':len(results),'passed':sum(x['passed'] for x in results),'failed':sum(not x['passed'] for x in results),'custom_count':len(custom)}

def run_and_compare(connect):
    """Save only evaluation outcomes after an explicit user-initiated run."""
    report=run(connect)
    with connect() as c:
        ensure(c)
        old=c.execute('SELECT snapshot FROM assistant_evaluation_previous WHERE id=1').fetchone()
        try: previous=json.loads(old[0]) if old else {}
        except (TypeError,ValueError): previous={}
        if not isinstance(previous,dict):previous={}
        current={};counts={'newly_passed':0,'newly_failed':0,'unchanged':0,'new':0}
        for item in report['items']:
            key=hashlib.sha256(json.dumps([item['category'],item['question'],item['expected']],ensure_ascii=False).encode('utf-8')).hexdigest()
            old_pass=previous.get(key)
            change=('new' if type(old_pass) is not bool else 'unchanged' if old_pass==item['passed'] else 'newly_passed' if item['passed'] else 'newly_failed')
            item['change']=change;counts[change]+=1;current[key]=item['passed']
        c.execute('INSERT INTO assistant_evaluation_previous (id,snapshot) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET snapshot=excluded.snapshot',(1,json.dumps(current)))
    report['comparison']=counts
    report['has_previous']=bool(old)
    return report
