"""Recognize a small allowlist of navigation and preparation requests."""
import re
from datetime import date
import network_query
from smart_query import _last_friday
from core import CITIES


def report_conversation(messages, today=None):
    """Continue a report request through one explicit clarification turn."""
    if not isinstance(messages,list) or not messages:return None
    latest=messages[-1].get('content','')
    if not isinstance(latest,str):return None
    is_report=lambda s: bool(re.search(r'分析报告|分析.*报告|报告.*分析',s))
    requests=lambda s: bool(re.search(r'生成|制作|准备|给我|来一份|来个|我要|我想要|想要|出一份|做一份',s))
    # Only inherit the immediately preceding user request across one assistant reply.
    if len(messages)>=3 and messages[-2].get('role')=='assistant' and messages[-3].get('role')=='user':
        prior=messages[-3].get('content','')
        if isinstance(prior,str) and is_report(prior) and requests(prior) and not re.search(r'不要|不用|取消|算了|删除|清空|覆盖',latest):
            if re.search(r'黑点|重点投诉区域|解决率|合格率',latest) and not re.search(r'网络日报|运行日报|话术',latest):
                if any(city in latest for city in CITIES):
                    return {'reply':'目前分析报告是全省及各地市解决情况对比，暂不支持生成单个地市专属报告。你可以先查看全省报告中的地市统计。','local_query':True}
                # A month supplied in the new answer takes precedence over the old question.
                has_date=bool(re.search(r'20\d{2}|\d+\s*月',latest))
                years=set(re.findall(r'(?<!\d)(20\d{2})(?!\d)',prior))
                if has_date and not re.search(r'20\d{2}',latest) and len(years)==1:
                    latest=re.sub(r'(?<!\d)(\d{1,2})\s*月',lambda m:next(iter(years))+'年'+m.group(0),latest)
                dates=re.findall(r'(?<!\d)(?:20\d{2}\s*年\s*)?\d{1,2}\s*月|(?<!\d)20\d{2}[-/]\d{1,2}(?!\d)',prior)
                inherited=(' '.join(dates)+' ') if not has_date else ''
                return plan('生成'+inherited+latest+' 黑点解决情况分析报告',today)
    if is_report(latest) and requests(latest) and not re.search(r'不要|不用|取消|算了|怎么|如何|是什么|黑点|重点投诉区域|解决率|合格率|网络|流量|投诉|挂起|话术',latest):
        return {'reply':'你想生成哪类分析报告？目前可以生成全省黑点解决情况分析报告（包含各地市对比）。请告诉我报告类型和月份。','local_query':True}
    return None


def plan(question, today=None):
    if not isinstance(question,str):return None
    q=question.strip();today=today or date.today()
    if re.search(r'不(?:用|要|需要)(?:再|帮我|给我)?(?:生成|制作|准备|打开|进入)|取消(?:生成|制作|准备|打开|进入)',q):return None
    navigation=bool(re.search(r'打开|进入|跳转|前往|带我去',q))
    prepare=bool(re.search(r'生成|制作|准备',q))
    report_request=bool(re.search(r'分析报告|分析.*报告|报告.*分析',q) and re.search(r'给我|来一份|来个|我要|我想要|想要|出一份|做一份',q))
    if not navigation and not prepare and not report_request:return None
    if re.search(r'删除|清空|覆盖',q):return None
    send_request=bool(re.search(r'发(?:送)?邮件|发到.*邮箱|收件',q))
    if send_request and not (prepare and re.search(r'分析报告|分析.*报告|地市告警|地市提醒|解决率告警|解决率提醒',q)):return None
    if re.search(r'地市告警|地市提醒|解决率告警|解决率提醒',q):
        pairs=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])(?!\d)\s*月?',q)
        bare=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月',q)
        if len(pairs)>1 or len(bare)>1:return {'reply':'请指定一个统计月份。','local_query':True}
        if not pairs and not bare and re.search(r'20\d{2}|\d+月',q):return {'reply':'月份无效，请输入例如“2026年10月”。','local_query':True}
        month=f'{pairs[0][0]}-{int(pairs[0][1]):02d}' if pairs else f'{today.year}-{int(bare[0]):02d}' if bare else None
        action={'type':'open_city_alerts'}
        if month:action['month']=month
        return {'reply':'请打开地市提醒页面，核对月份并生成草稿。','action':action,'local_query':True}
    if re.search(r'分析报告|分析.*报告|报告.*分析',q) and re.search(r'黑点|重点投诉区域|解决率|合格率',q):
        if any(city in q for city in CITIES):return {'reply':'目前分析报告是全省及各地市解决情况对比，暂不支持生成单个地市专属报告。你可以先查看全省报告中的地市统计。','local_query':True}
        pairs=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])(?!\d)\s*月?',q)
        bare=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月',q)
        if len(pairs)>1 or len(bare)>1:
            from suspension import previous_month
            tokens=re.findall(r'(?:(20\d{2})\s*年\s*)?(1[0-2]|0?[1-9])\s*月',q)
            if len(tokens)!=2 or not re.search(r'对比|比较|相比|环比',q):return {'reply':'请指定一个报告月份。','local_query':True}
            year=int(tokens[0][0] or today.year);month=f'{year:04d}-{int(tokens[0][1]):02d}'
            prior=previous_month(month);other_year=int(tokens[1][0] or (int(prior[:4]) if int(tokens[1][1])==int(prior[5:]) else year))
            if f'{other_year:04d}-{int(tokens[1][1]):02d}'!=prior:return {'reply':'目前报告支持与上一个自然月比较，请指定该月份。','local_query':True}
            return {'reply':'可以生成黑点月度分析报告，核对数据后将展示上月对比。','action':{'type':'open_analysis_report','month':month},'local_query':True}
        if not pairs and not bare and re.search(r'20\d{2}|\d+月',q):return {'reply':'月份无效，请输入例如“2026年10月”。','local_query':True}
        month=f'{pairs[0][0]}-{int(pairs[0][1]):02d}' if pairs else f'{today.year}-{int(bare[0]):02d}' if bare else None
        action={'type':'open_analysis_report'}
        if month:action['month']=month
        return {'reply':'可以生成全省黑点解决情况分析报告，包含各地市对比。请打开报告页面核对月份并生成；邮件需另行核对后手动发送。','action':action,'local_query':True}
    destinations=[]
    if re.search(r'挂起库|挂起页面',q):destinations.append('suspension')
    if re.search(r'网络日报|运行日报|无线网络运行|网络运行情况',q):destinations.append('network')
    if re.search(r'黑点周报|黑点月报|黑点报告|生成周报|生成月报',q) or (prepare and re.search(r'周报|月报',q)):destinations.append('reports')
    if re.search(r'话术模拟|模拟客服',q):destinations.append('complaint_simulation')
    if len(destinations)!=1:return {'reply':'请说明想打开的一个功能，例如“打开挂起库”或“打开网络运行日报”。','local_query':True} if destinations else None
    dest=destinations[0]
    if dest=='suspension':
        years=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])(?!\d)\s*月?',q)
        months=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月',q)
        if len(years)>1 or len(months)>1:return {'reply':'请指定一个统计月份。','local_query':True}
        if not years and not months and re.search(r'20\d{2}|\d+月',q):return {'reply':'统计月份无效，请输入例如“2026年10月”。','local_query':True}
        month=f'{years[0][0]}-{int(years[0][1]):02d}' if years else f'{today.year}-{int(months[0]):02d}' if months else None
        action={'type':'open_suspension'}
        if month:action['month']=month
        return {'reply':f"可以打开{month+' 的' if month else ''}挂起库页面；请点击下方入口。",'action':action,'local_query':True}
    if dest=='network':
        has_date=bool(re.search(r'20\d{2}|\d{1,2}月|今天|昨天|前天|最新',q))
        explicit_days=re.findall(r'(?:20\d{2}年)?\d{1,2}月\d{1,2}[日号]|20\d{2}[-/]\d{1,2}[-/]\d{1,2}',q)
        if len(explicit_days)>1:return {'reply':'请指定一个日报日期。','local_query':True}
        day=network_query.date_in_question(q,today=today) if has_date else None
        if has_date and not day:return {'reply':'日期不明确或无效，请写明具体日期，例如“2026年11月2日”。','local_query':True}
        action={'type':'open_network'}
        if day and day!='latest':action['day']=day
        return {'reply':f"可以打开{day+' 的' if day and day!='latest' else ''}网络运行日报；请点击下方入口。",'action':action,'local_query':True}
    if dest=='complaint_simulation':return {'reply':'可以打开话术模拟，请点击下方入口。','action':{'type':'open_complaint_simulation'},'local_query':True}
    if dest=='reports' and navigation and not prepare:
        if '周报' in q and '月报' in q:return {'reply':'请指定周报或月报中的一种。','local_query':True}
        kind='weekly' if '周报' in q else 'monthly' if '月报' in q else None
        if len(re.findall(r'(?:20\d{2}年)?\d{1,2}月\d{1,2}[日号]|20\d{2}[-/]\d{1,2}[-/]\d{1,2}',q))>1:return {'reply':'请指定一个报告日期。','local_query':True}
        has_date=bool(re.search(r'20\d{2}|\d+月|今天|昨天|前天',q))
        day=network_query.date_in_question(q,today=today) if has_date else None
        if not day and re.search(r'\d{1,2}月\d{1,2}[日号]|20\d{2}[-/]\d{1,2}[-/]\d{1,2}',q):return {'reply':'报告日期无效，请写明有效日期。','local_query':True}
        if has_date and not day and kind=='monthly':
            years=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])(?!\d)\s*月?',q)
            months=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月',q)
            if len(years)==1 and len(months)<=1:day=_last_friday(f'{years[0][0]}-{int(years[0][1]):02d}')
            elif not years and len(months)==1 and not re.search(r'20\d{2}',q):day=_last_friday(f'{today.year}-{int(months[0]):02d}')
        if has_date and (not kind or not day or day=='latest'):return {'reply':'请说明报告类型及有效日期；月报也可指定月份。','local_query':True}
        if day:
            return {'reply':f'可以打开{day}保存的黑点{"周报" if kind=="weekly" else "月报"}；请点击下方入口。','action':{'type':'open_reports','day':day,'kind':kind},'local_query':True}
    return {'reply':'可以打开黑点报告工作台。生成报告需要先选择工单表并核对日期。','action':{'type':'open_reports'},'local_query':True}
