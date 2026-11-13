"""Bounded routing for evidence-based multi-step and suspension-reason queries."""
import re
from datetime import date, timedelta
from fractions import Fraction

import ranking_planner
from analysis_planner import _read_cities
from core import CITIES
from smart_query import _last_friday


def city_comparison_plan(messages):
    q=messages[-1]['content'].strip()
    if not re.search(r'黑点|重点投诉区域|解决率|合格率',q) or not re.search(r'各地市|各市|所有地市|全部地市',q):return None
    if not re.search(r'上(?:个)?月|环比|(?:和|与|跟).{0,12}(?:比|对比)',q):return None
    if re.search(r'挂起|原因|排名|倒数|最高|最低|投诉量|流量|项目进展',q):return None
    marker=re.search(r'和|与|跟|较|相比',q)
    primary=q[:marker.start()] if marker else q
    years=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])\s*月?',primary)
    bare=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月',primary)
    if len(years)==1:month=f'{years[0][0]}-{int(years[0][1]):02d}'
    elif not years and len(bare)==1:month=f'{date.today().year}-{int(bare[0]):02d}'
    else:return {'error':'请说明本期月份，例如“2026年10月各地市黑点解决率和上月相比”。'}
    other=_other_month(q[marker.end():] if marker else q,month)
    if not other or other==month:return {'error':'请说明不同的对照月份，例如“和上月相比”。'}
    return {'month':month,'other_month':other}


def execute_city_comparison(plan,connect,*,source_reader=None):
    now,error,now_source=_read_cities(connect,plan['month'],source_reader,with_source=True)
    if error:return {'reply':f"{plan['month']}数据不可用：{error}",'available':False}
    before,error,before_source=_read_cities(connect,plan['other_month'],source_reader,with_source=True)
    if error:return {'reply':f"{plan['other_month']}对照数据不可用：{error}",'available':False}
    if set(now)!=set(CITIES) or set(before)!=set(CITIES):return {'reply':'地市数据不完整，无法进行全省地市比较。','available':False}
    rows=[]
    for city in CITIES:
        a,b=now[city],before[city]
        rows.append([city,'无分母' if a is None else f'{float(a)*100:.2f}%','无分母' if b is None else f'{float(b)*100:.2f}%', '无法比较' if a is None or b is None else f'{float(a-b)*100:+.2f}个百分点'])
    compared=[now[c]-before[c] for c in CITIES if now[c] is not None and before[c] is not None]
    note=f"数据日期：{now_source['period']}（{now_source['kind']}）、{before_source['period']}（{before_source['kind']}）；解决率为质检合格数除以确认纳入数，变化以百分点计算，分母为零时不参与比较。"
    return {'reply':f"{plan['month']}各地市解决率与{plan['other_month']}相比：{sum(x>0 for x in compared)}个地市上升、{sum(x<0 for x in compared)}个下降、{sum(x==0 for x in compared)}个持平，{len(CITIES)-len(compared)}个因分母为零无法比较。",'table':{'headers':['地市',plan['month']+'解决率',plan['other_month']+'解决率','变化'],'rows':rows,'footnote':note},'evidence':note,'available':True}


def _other_month(text, base):
    if re.search(r'上(?:个)?月|前一个月', text):
        d = date.fromisoformat(base + '-01') - timedelta(days=1)
        return f'{d.year:04d}-{d.month:02d}'
    pairs = re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])\s*月?', text)
    if len(pairs) == 1:
        return f'{pairs[0][0]}-{int(pairs[0][1]):02d}'
    months = re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月', text)
    if len(months) == 1:
        return f'{base[:4]}-{int(months[0]):02d}'
    return None


def ranked_comparison_plan(messages):
    """Only inherit an immediately preceding rank, never model output or old unrelated topics."""
    questions = [m['content'].strip() for m in messages if m.get('role') == 'user']
    if not questions:
        return None
    current = questions[-1]
    if re.search(r'挂起|流量|投诉量|项目进展|网络质量|原因', current):
        return None
    comparison = re.search(r'(?:和|与|跟|较|相比)(?P<rest>.*(?:比|对照|变化|怎么样|如何).*)', current)
    if not comparison:
        return None
    prefix = current[:comparison.start()]
    history = questions[:-1]
    # A terse comparison may refer only to the immediately preceding rank question.
    if re.search(r'倒数|最高|最低|排名|排行', prefix):
        rank_question = prefix
    elif not prefix.strip(' ，,？?') and history:
        rank_question = history.pop()
    else:
        return None
    if re.search(r'挂起|流量|投诉量|项目进展|网络质量', rank_question):
        return None
    # Keep the existing highest-city comparison path and its established wording.
    if '最高' in rank_question and not re.search(r'前[一二三四五六七八九十0-9]|排名|排行',rank_question):
        return None
    # Normalize the unambiguous single lowest-city request for the existing rank validator.
    if '最低' in rank_question and not re.search(r'倒数|前[一二三四五六七八九十0-9]|排名|排行',rank_question):
        rank_question=rank_question.replace('最低','倒数前一')
    rank_questions = ([history[-1]] if history else []) + [rank_question]
    rank_messages = [{'role':'user','content':q} for q in rank_questions]
    if not ranking_planner.should_plan(rank_messages):
        return None
    rank = ranking_planner.fallback(rank_messages)
    if not rank:
        return {'error':'请明确排名月份、方向和数量，例如“2026年10月黑点解决率倒数前三，与上月相比”。'}
    other = _other_month(comparison.group('rest'),rank['month'])
    if not other or other == rank['month']:
        return {'error':'请明确另一个不同的比较月份，例如“和9月相比”。'}
    return {'rank':rank,'other_month':other}


def execute_ranked_comparison(plan, connect, *, source_reader=None):
    rank = plan['rank']
    ranked = ranking_planner.execute(rank,connect,source_reader=source_reader)
    if not ranked.get('available') or not ranked.get('table'):
        return ranked
    before,error,before_source = _read_cities(connect,plan['other_month'],source_reader,with_source=True)
    if error:
        return {'reply':f"{plan['other_month']}对照数据不可用：{error}",'available':False}
    rows=[]
    for position,city,current,qualified,included in ranked['table']['rows']:
        before_rate=before.get(city)
        current_rate=Fraction(qualified)/Fraction(included)
        if before_rate is None:
            rows.append([position,city,current,'无分母','无法比较'])
        else:
            rows.append([position,city,current,f'{float(before_rate)*100:.2f}%',f'{float(current_rate-before_rate)*100:+.2f}个百分点'])
    direction='最低' if rank['direction']=='asc' else '最高'
    detail='；'.join(f'{r[1]}：{r[2]}，较对照期{r[4]}' for r in rows)
    rank_source=ranked['source_info']
    note=(f"统计日期：{rank_source['period']}（{rank_source['kind']}）、{before_source['period']}（{before_source['kind']}）。"
          '按未四舍五入的质检合格数÷确认纳入数排名并计算百分点差；无纳入黑点的地市不参与排名，末位并列一并展示。')
    return {'reply':f"{rank['month']}黑点解决率{direction}的地市与{plan['other_month']}比较：{detail}。",
            'available':True,'table':{'headers':['名次','地市',rank['month']+'解决率',plan['other_month']+'解决率','变化'],'rows':rows,'footnote':note},'evidence':note}


def suspension_reason_plan(messages):
    q=messages[-1]['content'].strip()
    if not re.search(r'挂起',q) or not re.search(r'原因|为什么|归因|主要问题|主要集中在什么|哪些问题',q):
        return None
    if re.search(r'对比|相比|环比|同比|排名|各地市|各市',q):
        return {'error':'请先指定一个月份和全省或单个地市，查询挂起原因关键词汇总。'}
    months=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])\s*月?',q)
    bare=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月',q)
    if len(months)==1:month=f'{months[0][0]}-{int(months[0][1]):02d}'
    elif not months and len(bare)==1:month=f'{date.today().year}-{int(bare[0]):02d}'
    else:return {'error':'请说明统计月份，例如“2026年10月合肥挂起原因”。'}
    cities=[name for name in CITIES if name in q]
    if len(cities)>1:return {'error':'请先指定一个地市或全省。'}
    city=cities[0] if cities else '全省'
    source='issue' if re.search(r'形成原因|网络原因',q) else 'suspension'
    return {'month':month,'city':city,'source':source}


def execute_suspension_reasons(plan,reader):
    current=reader(plan['month'])
    if not current:return {'reply':'该月没有已保存的挂起库统计，请先导入对应数据。','available':False}
    reasons=current.get('reason_analysis')
    if not reasons:return {'reply':'该版本未保存原因关键词汇总，请在挂起库页面补充对应日期的原表。','available':False}
    if plan['source']=='issue':
        reasons=reasons.get('issue')
        if not reasons or not reasons.get('available'):return {'reply':'该版本没有可用的问题形成原因汇总。','available':False}
    city=plan['city']
    rows=([{'name':r['reason'],'value':r['value']} for r in reasons['cities'] if r['city']==city]
          if city!='全省' else reasons['counts'])
    rows=sorted(rows,key=lambda r:(-r['value'],r['name']))
    label='问题形成原因' if plan['source']=='issue' else '不纳入原因'
    when=current.get('period') or '未提供'
    source={'manual':'人工汇总','imported':'历史工单表','weekly':'月末周报','monthly':'月报'}.get(current.get('kind'),'已保存统计')
    note=f'数据来源：{source}；统计日期：{when}。基于{label}的关键词初筛，一条记录可能命中多个关键词，数量不能相加；不是已确认的实际原因。'
    if not rows:return {'reply':f"{plan['month']}{city}{label}没有匹配的关键词，不能推断没有相关问题。",'available':True,'evidence':note}
    text='、'.join(f"{r['name']} {r['value']}处" for r in rows[:3])
    return {'reply':f"{plan['month']}{city}{label}关键词初筛中，主要涉及{text}。",'available':True,
            'table':{'headers':['关键词初筛','数量（处）'],'rows':[[r['name'],str(r['value'])] for r in rows],'footnote':note},'evidence':note}
