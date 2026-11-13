"""LangGraph workflow for a locally verifiable blackspot monthly report."""
import json
import re
from fractions import Fraction
from typing import TypedDict, Any

from langgraph.graph import StateGraph, START, END
from langsmith import tracing_context
from core import CITIES
from smart_query import query, _last_friday
from suspension import previous_month
from assistant_service import complete

_CHINESE_NUMBER = re.compile(r'(?:百分之|千分之)[零〇一二两三四五六七八九十百千万亿点多]+|[零〇一二两三四五六七八九十百千万亿几数多半]+(?:分之[零〇一二两三四五六七八九十百千万亿]+|余?\s*(?:处|件|个|户|站|项目|区域|地市|城市|工单|次|批|项|条|人|家|点|倍|成|年|月|日|季度))|半数|多数地市')


class ReportState(TypedDict, total=False):
    month: str
    current: dict
    prior: dict
    older: dict
    facts: dict
    advice: str
    advice_notice: str


def create_report(month, connect, *, source_reader=None, key=None, model=None, complete_fn=complete):
    _last_friday(month)
    def read(m):
        result=query(connect,'query_city_metrics',{'month':m,'city':'全部地市','metric':'解决率'},structured=True,source_reader=source_reader)
        if not result.get('available') or not result.get('table'):
            return {'month':m,'available':False,'notice':result.get('reply','该月统计不可用。')}
        rows=[]
        for city,included,qualified,_ in result['table']['rows']:
            inc,qual=Fraction(included),Fraction(qualified)
            if inc.denominator!=1 or qual.denominator!=1 or inc<0 or qual<0 or qual>inc:raise ValueError('地市统计数据异常，请核对确认纳入和质检合格数量。')
            rows.append({'city':city,'included':int(inc),'qualified':int(qual),'rate':qual/inc if inc else None})
        if len(rows)!=len(CITIES) or {r['city'] for r in rows}!=set(CITIES):raise ValueError('地市统计不完整，无法生成报告。')
        source=result.get('source_info') or {'period':_last_friday(m),'kind':'已保存报告'}
        return {'month':m,'period':source['period'],'source':source['kind'],'rows':rows,'available':True}

    def gather(state):
        current=read(state['month'])
        if not current['available']:raise ValueError(current['notice'])
        prev=previous_month(state['month'])
        return {'current':current,'prior':read(prev),'older':read(previous_month(prev))}

    def analyze(state):
        current=state['current'];rows=current['rows'];prior=state['prior']
        previous={r['city']:r for r in prior.get('rows',[])}
        eligible=sorted((r for r in rows if r['rate'] is not None),key=lambda r:r['rate'])
        selected=[]
        if eligible:
            cutoff=eligible[min(3,len(eligible))-1]['rate']
            selected=[r['city'] for r in eligible if r['rate']<=cutoff]
        result=[]
        for r in rows:
            old=previous.get(r['city'],{}).get('rate')
            result.append({'city':r['city'],'included':r['included'],'qualified':r['qualified'],
                           'rate':float(r['rate']*100) if r['rate'] is not None else None,
                           'change':float((r['rate']-old)*100) if r['rate'] is not None and old is not None else None,
                           'highlight':r['city'] in selected})
        total=sum(r['included'] for r in rows);done=sum(r['qualified'] for r in rows)
        comparable=[r for r in result if r['change'] is not None]
        declines=sorted((r for r in comparable if r['change']<0),key=lambda r:r['change'])
        improvements=sorted((r for r in comparable if r['change']>0),key=lambda r:-r['change'])
        trend=[]
        for item in (state['older'],prior,current):
            counts=item.get('rows',[]);all_inc=sum(r['included'] for r in counts);all_done=sum(r['qualified'] for r in counts)
            trend.append({'month':item['month'],'period':item.get('period'),'available':item['available'],
                          'source':item.get('source'),'rate':float(Fraction(all_done,all_inc)*100) if item['available'] and all_inc else None})
        return {'facts':{'month':current['month'],'period':current['period'],'source':current['source'],
                'included':total,'qualified':done,'rate':float(Fraction(done,total)*100) if total else None,
                'cities':result,'lowest':selected,'trend':trend,'previous_available':prior['available'],
                'declines':declines[:3],'improvements':improvements[:3],'comparable_count':len(comparable)}}

    def interpret(state):
        facts=state['facts']
        fallback='请重点关注解决率靠后的地市，结合现有整治计划推进；具体障碍和解决方案需结合实际情况判断。'
        if not key:return {'advice':fallback,'advice_notice':'未配置 DeepSeek，已展示本地建议。'}
        payload=json.dumps(facts,ensure_ascii=False)
        prompt='根据以下黑点月度汇总，为工作人员写一段简短的推进建议。只讨论数据支持的情况，不要编造具体原因、项目、目标、日期或数字。不要输出数字、百分数或具体地市名称。只输出建议正文。\n'+payload
        try:
            answer=complete_fn(key,[{'role':'user','content':prompt}],model=model,system='你是无线网络运行分析助手。数据由程序提供；不得杜撰事实。')
            if not isinstance(answer,str) or not answer.strip() or len(answer)>600 or re.search(r'\d|[%％]|'+'|'.join(CITIES),answer) or _CHINESE_NUMBER.search(answer):raise ValueError('建议未通过核验')
            return {'advice':answer,'advice_notice':'AI 根据本次汇总生成建议，请结合实际核对。'}
        except ValueError:
            return {'advice':fallback,'advice_notice':'AI 建议暂不可用，已展示本地建议。'}

    graph=StateGraph(ReportState)
    graph.add_node('read_statistics',gather);graph.add_node('calculate',analyze);graph.add_node('interpret',interpret)
    graph.add_edge(START,'read_statistics');graph.add_edge('read_statistics','calculate');graph.add_edge('calculate','interpret');graph.add_edge('interpret',END)
    # This workflow handles local business aggregates; never enable remote tracing.
    with tracing_context(enabled=False):
        state=graph.compile().invoke({'month':month})
    return {'facts':state['facts'],'advice':state['advice'],'advice_notice':state['advice_notice']}
