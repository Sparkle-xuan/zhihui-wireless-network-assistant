"""Conservative multi-turn routing for saved suspension and daily aggregates."""
import re
from datetime import date, timedelta
import network_query
import smart_query
import suspension
import query_router
from core import CITIES

SUSPENSION_WORDS=r'挂起库|申请挂起|挂起(?:的)?数量|挂起多少|挂起数'
OTHER_DOMAIN=r'解决率|合格率|项目进展|投诉量|流量|网络质量|用户数|原因|类别|明细|小区'


def _city_values(snapshot):
    return {r['name']:r['value'] for r in (snapshot.get('cities') or [])}


def _source(snapshot):
    kind={'manual':'人工补录','imported':'指定历史工单表','weekly':'月末周报','monthly':'月报'}.get(snapshot.get('kind'),'已保存数据')
    return kind+'（统计日期：'+(snapshot.get('period') or '未提供')+'）'


def _previous(month):
    return suspension.previous_month(month)


def growth_plan(messages):
    """Recognize a bounded, three-snapshot consecutive-growth question."""
    q = messages[-1]['content'].strip()
    if not re.search(r'挂起', q) or not re.search(r'连续(?:两|2)个?月', q) or not re.search(r'增长|增加|上升', q):
        return None
    if re.search(r'原因|类别|分类|解决率|流量|投诉', q):
        return {'error': '请单独查询挂起数量连续增长，原因和其他指标请另行提问。'}
    dates = re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])\s*月?', q)
    months = re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月', q)
    if len(dates) == 1:
        month = f'{dates[0][0]}-{int(dates[0][1]):02d}'
    elif not dates and len(months) == 1:
        month = f'{date.today().year}-{int(months[0]):02d}'
    else:
        return {'error': '请说明截至哪个月，例如“2026年10月哪些地市挂起连续两个月增长”。'}
    cities = [c for c in CITIES if c in q]
    if cities or '全省' in q:
        return {'error': '这项分析用于比较各地市，请不要指定单个地市或全省。'}
    return {'month': month}


def execute_growth(plan, reader):
    current = plan['month']
    months = [_previous(_previous(current)), _previous(current), current]
    snapshots = [reader(month) for month in months]
    missing = [month for month, snap in zip(months, snapshots) if not snap]
    if missing:
        return {'reply': '缺少' + '、'.join(missing) + '挂起统计，无法判断连续增长。'}
    if any(not isinstance(s.get('cities'), list) or s.get('city_note') or set(_city_values(s)) != set(CITIES) for s in snapshots):
        return {'reply': '部分月份的地市挂起数据不完整，无法可靠判断哪些地市连续增长。'}
    values = [_city_values(s) for s in snapshots]
    matched = [c for c in CITIES if values[0][c] < values[1][c] < values[2][c]]
    note = '；'.join(month + '：' + _source(snap) for month, snap in zip(months, snapshots)) + '。连续增长指每次均高于上月；挂起数量是各期累计存量。'
    if not matched:
        return {'reply': f'截至{current}，没有地市在连续两个月的比较中均出现挂起数量增长。', 'evidence': note}
    rows = [[c] + [str(v[c]) for v in values] for c in matched]
    return {'reply': f'截至{current}，共有{len(matched)}个地市的挂起数量连续两个月增长：' + '、'.join(matched) + '。',
            'table': {'headers': ['地市'] + [m + '（处）' for m in months], 'rows': rows, 'footnote': note}, 'evidence': note}


def _short_city(q):
    compact=re.sub(r'\s+','',q)
    if not re.fullmatch(r'(?:全省|安徽省|'+ '|'.join(CITIES) +r')(?:市)?(?:呢|怎么样|如何|多少|有多少|的情况)?[？?。！!]*',compact):return None
    return next((city for city in CITIES if city in compact),'全省')


def suspension_context(messages):
    """Reconstruct only explicit queries and short scope follow-ups; reset on topic change."""
    questions=[m['content'].strip() for m in messages if m.get('role')=='user']
    if len(questions)<2:return None
    state=None
    for q in questions[:-1]:
        parsed=smart_query.local_query_plan([{'role':'user','content':q}])
        if parsed and parsed['tool']=='query_suspended':state=parsed['arguments'].copy();continue
        city=_short_city(q)
        if state and city:state['city']=city;continue
        state=None
    return state


def suspension_plan(messages):
    q=messages[-1]['content'].strip();history=suspension_context(messages)
    if re.search(OTHER_DOMAIN,q):return None
    ranking=bool(re.search(r'排名|排行|最多|最少|最高|最低|倒数|前[一二三四五六七八九十0-9]',q))
    comparison=bool(re.search(r'上(?:个)?月|环比|与.{0,12}比|和.{0,12}比|跟.{0,12}比|较.{0,12}比|相比',q))
    explicit=bool(re.search(SUSPENSION_WORDS,q) or (re.search(r'挂起',q) and (ranking or comparison)))
    if not explicit and not history:return None
    city_follow=_short_city(q)
    if not explicit and city_follow and history:return {'action':'lookup','month':history['month'],'city':city_follow}
    if not (ranking or comparison):return None
    if ranking and comparison:return {'error':'请分别查询挂起数量排名和月度变化，以便确认范围。'}
    comparison_marker=re.search(r'和|与|跟|较|相比',q) if comparison else None
    main_question=q[:comparison_marker.start()] if comparison_marker else q
    comparison_question=q[comparison_marker.end():] if comparison_marker else q
    date_tokens=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])\s*月?',main_question)
    bare=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月',main_question)
    if len(date_tokens)>1 or (not date_tokens and len(bare)>1):return {'error':'请说明一个统计月份，再说明比较月份。'}
    if date_tokens:month=f'{date_tokens[0][0]}-{int(date_tokens[0][1]):02d}'
    elif bare:month=f"{(history['month'][:4] if history else date.today().year)}-{int(bare[0]):02d}"
    elif history:month=history['month']
    else:return {'error':'请说明统计月份，例如“2026年10月”。'}
    cities=[c for c in CITIES if c in q]
    if len(cities)>1:return {'error':'请指定全省或一个地市。'}
    city=cities[0] if cities else '全省' if re.search(r'全省|安徽省',q) else (history['city'] if history else '全省')
    if ranking:
        if cities:return {'error':'地市排名请查询全部地市，不要同时指定单个地市。'}
        direction='asc' if re.search(r'最少|最低|倒数',q) else 'desc' if re.search(r'最多|最高|排名|排行|前',q) else None
        if not direction:return {'error':'请说明按挂起数量从高到低还是从低到高排名。'}
        match=re.search(r'前([一二三四五六七八九十]|\d{1,2})',q)
        nums={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
        count=(nums.get(match.group(1)) or int(match.group(1))) if match and match.group(1).isdigit() else nums.get(match.group(1)) if match else 3 if re.search(r'最多|最少|最高|最低',q) else 16
        if not count or not 1<=count<=16:return {'error':'排名数量需在1至16之间。'}
        return {'action':'rank','month':month,'direction':direction,'limit':count}
    if re.search(r'上(?:个)?月|环比',comparison_question):other=_previous(month)
    else:other=query_router._other_month(comparison_question,month)
    if not other or other==month:return {'error':'请明确另一个不同的比较月份，例如“和9月相比”。'}
    if city=='全部地市':return {'error':'月度比较请指定全省或一个地市。'}
    return {'action':'compare','month':month,'other_month':other,'city':city}


def execute_suspension(plan,reader):
    current=reader(plan['month'])
    if not current:return {'reply':f"{plan['month']}没有已保存的挂起库统计，请先导入对应数据。"}
    if plan['action']=='lookup':
        city=plan['city'];values=_city_values(current)
        if city!='全省' and city not in values:return {'reply':f"{plan['month']}{city}挂起数量未提供，无法查询。"}
        value=current['total'] if city=='全省' else values[city]
        return {'reply':f"截至{current.get('period') or plan['month']}，{city}挂起库累计{value}处。",'evidence':'数据来源：'+_source(current)+'。'}
    if plan['action']=='rank':
        if not isinstance(current.get('cities'),list) or current.get('city_note'):
            return {'reply':'该月地市挂起数据不完整，不能可靠排名，请补充完整数据。'}
        rows=sorted(current['cities'],key=lambda r:r['value'],reverse=plan['direction']=='desc')
        limit=min(plan['limit'],len(rows));cut=rows[limit-1]['value']
        rows=[r for r in rows if r['value']>=cut] if plan['direction']=='desc' else [r for r in rows if r['value']<=cut]
        note='数据来源：'+_source(current)+'；末位并列一并展示。'
        return {'reply':f"{plan['month']}挂起数量{'最多' if plan['direction']=='desc' else '最少'}的地市："+'、'.join(f"{r['name']}{r['value']}处" for r in rows)+'。',
                'table':{'headers':['地市','挂起数量（处）'],'rows':[[r['name'],str(r['value'])] for r in rows],'footnote':note},'evidence':note}
    before=reader(plan['other_month'])
    if not before:return {'reply':f"缺少{plan['other_month']}挂起统计，无法进行月度比较。"}
    city=plan['city'];now=_city_values(current);old=_city_values(before)
    if city!='全省' and (city not in now or city not in old):return {'reply':f'{city}的本月或上月地市统计未提供，无法比较。'}
    a=current['total'] if city=='全省' else now[city];b=before['total'] if city=='全省' else old[city];delta=a-b
    change='持平' if not delta else ('增加' if delta>0 else '减少')+str(abs(delta))+'处'
    note=f"本期：{_source(current)}；对照期：{_source(before)}。"
    return {'reply':f"{plan['month']}{city}挂起{a}处，较{plan['other_month']}的{b}处{change}。",'evidence':note}


def daily_comparison_plan(messages):
    q=messages[-1]['content'].strip()
    if not re.search(r'相比|比较|对比|(?:和|与|跟).{0,25}比|比.{0,25}(?:如何|怎么样|多少)',q):return None
    if re.search(r'黑点|挂起|排名|小区|明细|趋势|同比|环比',q):return None
    previous=next((m['content'] for m in reversed(messages[:-1]) if m.get('role')=='user'),None)
    previous_plan=network_query.local_plan(previous) if previous else None
    args=previous_plan.get('arguments') if previous_plan and 'arguments' in previous_plan else None
    metric=network_query.recognize(q)
    if metric=='多个指标':return {'error':'请先指定一个日报指标。'}
    if metric is None and args:metric=args['metric']
    if not metric:return None
    cities=[c for c in CITIES if c in q];province=bool(re.search(r'全省|安徽省',q));all_cities=bool(re.search(r'各地市|全部地市|各市',q))
    if len(cities)>1 or all_cities or (cities and province):return {'error':'跨日比较请指定全省或一个地市。'}
    city=cities[0] if cities else '全省' if province else args['city'] if args else None
    if city not in (*CITIES,'全省'):return {'error':'请说明比较范围：全省或一个地市。'}
    # Accept two explicit calendar dates, or one date against the prior explicit query date.
    tokens=list(re.finditer(r'(?<!\d)(?:(20\d{2})年)?(1[0-2]|0?[1-9])月(3[01]|[12]\d|0?[1-9])[日号]',q))
    iso=list(re.finditer(r'(?<!\d)(20\d{2})[-/](1[0-2]|0?[1-9])[-/](3[01]|[12]\d|0?[1-9])(?!\d)',q))
    if tokens and iso:return {'error':'请使用一致的日期格式，并明确两个日期。'}
    found=tokens or iso
    if len(found)>2:return {'error':'请仅指定两个比较日期。'}
    if len(found)==1 and args:
        base=args['day']
        if base=='latest':return {'error':'上次查询是最新日期，请明确两个具体日期。'}
        try:d=date(int(found[0].group(1) or base[:4]),int(found[0].group(2)),int(found[0].group(3))).isoformat()
        except ValueError:return {'error':'日期无效，请检查后重试。'}
        return {'metric':metric,'city':city,'day':base,'base_day':d}
    if len(found)!=2:return None
    years=[m.group(1) for m in found if m.group(1)]
    if len(set(years))>1 and any(not m.group(1) for m in found):return {'error':'跨年比较请明确两个日期的年份。'}
    year=int(years[0]) if years else date.today().year
    try:
        days=[date(int(m.group(1) or year),int(m.group(2)),int(m.group(3))).isoformat() for m in found]
    except ValueError:return {'error':'日期无效，请检查后重试。'}
    if days[0]==days[1]:return {'error':'请指定两个不同日期。'}
    return {'metric':metric,'city':city,'day':days[0],'base_day':days[1]}
