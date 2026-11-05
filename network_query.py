"""Read-only, allowlisted network daily report statistics; never export raw rows."""
import json
import re
from datetime import date,timedelta
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from core import CITIES
from historical_report_tables import parse as parse_tables

# Each mapping names an actual source column. Uncertain equivalents are kept separate.
METRICS={
 '5G数据流量':('nr_upoct','province','5G数据流量','traffic','5G流量','TB',r'5G(?:数据)?流量'),
 '4G数据流量':('lte_upoct','province','4G数据流量','traffic','4G流量','TB',r'(?:4G|LTE)(?:数据)?流量'),
 '5G分流比':('split_flow_rate','province','5G分流比','traffic','分流比','%',r'(?:5G)?分流(?:比|率)'),
 '700M数据流量':('upoct_700','province','700M数据流量','traffic','700M数据流量','TB',r'700M(?:数据)?流量'),
 '5G终端用户数':('nr_terminal_users','province','5G终端用户数','users','5G终端用户数','万户',r'5G终端用户(?:数|量)?'),
 '5G活跃用户数':(None,'province','5G活跃用户数','users','5G活跃用户数','万户',r'5G活跃用户(?:数|量)?'),
 '5G当日终端登网用户数':('nr_terminal_login_users_day',None,None,None,None,'万户',r'5G(?:当日)?(?:终端)?登网用户(?:数|量)?'),
 'VoNR活跃用户数':('vonr_active_users','province','VoNR活跃用户数','users','VONR活跃用户数','万户',r'VoNR活跃用户(?:数|量)?'),
 'VoLTE在网用户数':('volte_online_users','province','VoLTE在网用户数','users','Volte在网用户数','万户',r'VoLTE在网用户(?:数|量)?'),
 '4G MME附着用户数':(None,'province','4G MME附着用户','users','4G MME附着用户','万户',r'(?:4G)?\s*MME附着用户(?:数|量)?'),
 'VoNR语音话务量':('vonr_voice_traffic','province','VoNR语音话务量','traffic','VoNR语音话务量','万Erl',r'VoNR(?:语音)?(?:话务量|业务量)'),
 'VoLTE语音话务量':('volte_voice_traffic','province','VoLTE语音业务量','traffic','VoLTE语音业务量','万Erl',r'VoLTE(?:语音)?(?:话务量|业务量)'),
 '5G低速率用户占比':('lowdatauser_rate',None,None,'traffic','5G低速率用户占比','%',r'5G低速率用户(?:占比|比例)'),
 '4G上行用户感知速率':('upoctul_user_rate',None,None,'traffic','4G上行用户感知速率','Mbps',r'4G上行(?:用户)?感知速率'),
 '4G下行用户感知速率':('upoctdl_user_rate',None,None,'traffic','4G下行用户感知速率','Mbps',r'4G下行(?:用户)?感知速率'),
 '5G上行用户感知速率':('upoctul_user_rate_5g',None,None,'traffic','5G上行用户感知速率','Mbps',r'5G上行(?:用户)?感知速率'),
 '5G下行用户感知速率':('upoctdl_user_rate_5g',None,None,'traffic','5G下行用户感知速率','Mbps',r'5G下行(?:用户)?感知速率'),
 'SA接通率':('wirelessconn_rate_5g',None,None,'quality','SA接通率','%',r'SA(?:无线)?接通率'),
 'SA切换成功率':('enb_suc_rate_5g',None,None,'quality','SA切换成功率','%',r'SA切换成功率'),
 'SA掉线率':('wirelessdrop_rate_5g',None,None,'quality','SA掉线率','%',r'SA(?:无线)?掉线率'),
 'EPSFB回落成功率':('epsfb_fallback_succ_rate',None,None,'quality','EPSFB回落成功率','%',r'EPSFB回落成功率'),
 'LTE无线接通率':('wirelessconn_rate',None,None,'quality','LTE无线接通率','%',r'LTE(?:无线)?接通率'),
 'LTE切换成功率':('enb_suc_rate',None,None,'quality','LTE切换成功率','%',r'LTE切换成功率'),
 'LTE无线掉线率':('wirelessdrop_rate',None,None,'quality','LTE无线掉线率','%',r'LTE(?:无线)?掉线率'),
 'VoLTE两高两低小区占比':('low2high2_rate',None,None,'quality','VOLTE两高两低小区占比','%',r'VoLTE两高两低(?:小区)?(?:占比|比例)'),
 '3CC开通站点数':(None,None,None,'3cc','3CC开通站点数','个',r'3CC(?:开通)?站点(?:数|量)?'),
 '3CC开通小区数':(None,None,None,'3cc','3CC开通小区数','个',r'3CC(?:开通)?小区(?:数|量)?'),
 '5G-A套餐用户数':(None,None,None,'3cc','5G-A套餐用户数','户',r'5G[-－]?A套餐用户(?:数|量)?'),
 '通感基站数':(None,None,None,'sensing','通感基站数','站',r'通感(?:基站|站点)(?:数|量)?'),
 '通感扇区数':(None,None,None,'sensing','扇区数','个',r'通感扇区(?:数|量)?'),
 'RedCap RRC建立成功率':(None,None,None,'redcap','RedCap 用户的 RRC建立成功率','%',r'RedCap(?:用户)?(?:的)?RRC建立成功率'),
 'RedCap QoS Flow建立成功率':(None,None,None,'redcap','RedCap 用户的 QoS Flow 建立成功率','%',r'RedCap(?:用户)?(?:的)?QoS\s*Flow建立成功率'),
 'RedCap QoS Flow掉线率':(None,None,None,'redcap','RedCap 用户的 QoS Flow 掉线率','%',r'RedCap(?:用户)?(?:的)?QoS\s*Flow掉线率'),
 'RedCap NR到LTE切换成功率':(None,None,None,'redcap','RedCap终端NR到LTE切换出成功率','%',r'RedCap(?:终端)?NR到LTE切换(?:出)?成功率'),
 'RedCap日均业务量':(None,None,None,'redcap','日均业务量','GB',r'RedCap(?:的)?日均(?:业务量|流量)'),
}
NETWORK_TOOL={'type':'function','function':{'name':'query_network_daily','description':'按明确的单日查询无线网络运行日报、5G-A 或 CSV 中全省或各地市的受控汇总指标；无日期必须追问，原始小区明细不可查询。','parameters':{'type':'object','properties':{'day':{'type':'string','description':'日期 YYYY-MM-DD，或用户明确要求最新时填 latest'},'city':{'type':'string','description':'全省、全部地市或安徽地市'},'metric':{'type':'string','enum':list(METRICS)}},'required':['day','city','metric']}}}

def recognize(question):
    if not isinstance(question,str): return None
    if re.search(r'(?:5G\s*(?:和|与|及|、|/|和|或)\s*4G|4G\s*(?:和|与|及|、|/|和|或)\s*5G)\s*(?:的数据|数据)?流量',question,re.I):return '多个指标'
    compact=re.sub(r'\s+','',question)
    found=[name for name,rule in METRICS.items() if re.search(rule[-1],compact,re.I)]
    if not found: return None
    # A long specific label wins over a contained generic label only where equivalent.
    return found[0] if len(found)==1 else '多个指标'

def date_in_question(question,today=None):
    today=today or date.today();text=re.sub(r'\s+','',question)
    m=re.search(r'(?<!\d)(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?',text)
    if m: parts=map(int,m.groups())
    else:
        m=re.search(r'(?<!\d)(\d{1,2})月(\d{1,2})[日号]',text)
        if m:
            if re.search(r'20\d{2}年',text):return None
            parts=(today.year,int(m.group(1)),int(m.group(2)))
        else:
            if re.search(r'20\d{2}年',text):return None
            if '前天' in text:return (today-timedelta(days=2)).isoformat()
            if '昨天' in text or '昨日' in text:return (today-timedelta(days=1)).isoformat()
            if '今天' in text or '今日' in text:return today.isoformat()
            if any(w in text for w in ('最新','最近一期','最近一日')):return 'latest'
            return None
    try:return date(*parts).isoformat()
    except ValueError:return None

def local_plan(question):
    metric=recognize(question)
    if not metric:return None
    if re.search(r'同比|环比|对比|比较|相比|较上|较去年|趋势|排名|最高|最低|最多|最少|平均|增长|下降|变化|本周|本月|上周|上月',question) or re.search(r'\d\s*(?:日|号)\s*(?:至|到|[-~～])\s*\d',question):
        return {'error':'目前日报问数支持指定单日的单项指标，跨日期对比、趋势和排名暂不支持，请指定一天查询。'}
    if re.search(r'黑点|挂起库|确认纳入|质检合格',question):
        return {'error':'问题中同时涉及黑点和网络运行指标，请分别提问以免混淆口径。'}
    if re.search(r'CGI|单个小区|某(?:个)?小区|小区名称|小区名|小区明细|站点明细|基站明细|用户明细|用户号码|(?:用户|小区|站点|基站).{0,8}(?:清单|名单|明细|详情)',question,re.I):
        return {'error':'目前日报问数只支持全省和地市汇总，不查询小区、站点或用户明细。'}
    relative_dates=sum(bool(re.search(pattern,question)) for pattern in (r'前天',r'昨天|昨日',r'今天|今日'))
    explicit_date=bool(re.search(r'(?<!\d)\d{1,2}月\d{1,2}[日号]|20\d{2}[-/]\d{1,2}[-/]\d{1,2}',question))
    if relative_dates>1 or (relative_dates and explicit_date):return {'error':'请先指定一个统计日期，跨日对比暂不支持。'}
    if len(re.findall(r'(?<!\d)\d{1,2}月\d{1,2}[日号]',question))>1 or len(re.findall(r'20\d{2}[-/]\d{1,2}[-/]\d{1,2}',question))>1:
        return {'error':'请先指定一个统计日期，跨日对比暂不支持。'}
    if metric=='多个指标':return {'error':'请先指定一个指标，以便准确查询。'}
    day=date_in_question(question)
    if not day:return {'error':'请说明统计日期，例如“2026年10月21日”，或明确说“最新”。'}
    cities=[x for x in CITIES if x in question]
    if len(cities)>1:return {'error':'请指定一个地市，或查询全部地市。'}
    city=cities[0] if cities else '全部地市' if re.search(r'各地市|全部地市|各市|各个地市',question) else '全省' if re.search(r'全省|安徽省|安徽',question) else None
    if not city:return {'error':'请说明查询范围：全省、全部地市或具体地市。'}
    return {'tool':'query_network_daily','arguments':{'day':day,'city':city,'metric':metric}}

def norm(value):return re.sub(r'[\s()（）\[\]【】]','',str(value)).lower()
def number(value):
    if value is None:return None
    text=str(value).strip().replace(',','').replace('％','%')
    if text.endswith('%'):text=text[:-1]
    if not re.fullmatch(r'-?\d+(?:\.\d+)?',text):return None
    try:
        result=Decimal(text)
        return result if result.is_finite() else None
    except InvalidOperation:return None

def report_values(tables,metric,city):
    _,province_id,province_col,city_id,city_col,_,_=METRICS[metric];found=[]
    if city=='全省':
        if province_id:
            for table in tables:
                if table['id']!=province_id:continue
                for row in table['rows']:
                    if len(row)>=3 and norm(row[1]).startswith(norm(province_col)):found.append(row[2])
        # Some reports include a province total row in the same city table.
        if city_id:
            for table in tables:
                if table['id']!=city_id:continue
                indices=[i for i,h in enumerate(table['headers']) if norm(h).startswith(norm(city_col))]
                for row in table['rows']:
                    if row and row[0] in ('安徽省','安徽','全省','汇总','合计','总计') and len(indices)==1 and indices[0]<len(row): found.append(row[indices[0]])
    elif city_id:
        for table in tables:
            if table['id']!=city_id:continue
            indices=[i for i,h in enumerate(table['headers']) if norm(h).startswith(norm(city_col))]
            for row in table['rows']:
                if row and row[0]==city and len(indices)==1 and indices[0]<len(row): found.append(row[indices[0]])
    return found

def query(connect,arguments, *, source_reader=None):
    if not isinstance(arguments,dict) or set(arguments)!={'day','city','metric'}:raise ValueError('请说明日期、地市和日报指标。')
    day=arguments['day'];city=arguments['city'];metric=arguments['metric']
    if metric not in METRICS:raise ValueError('该日报指标暂未接入查询。')
    if not isinstance(city,str):raise ValueError('请说明查询范围。')
    city=city.strip()
    if city not in ('全省','全部地市'):city=city.removesuffix('市')
    if city not in (*CITIES,'全省','全部地市'):raise ValueError('请选择全省、全部地市或安徽省地市。')
    try:
        with connect() as c:
            if day=='latest':
                rows=c.execute('SELECT MAX(report_date) FROM network_daily_reports UNION ALL SELECT MAX(report_date) FROM network_daily_indicators').fetchall()
                candidates=[r[0] for r in rows if r[0]]
                if not candidates:return {'reply':'数据库中尚无网络运行日报数据。','available':False}
                day=max(candidates)
            try:
                if not isinstance(day,str) or len(day)!=10 or date.fromisoformat(day).isoformat()!=day:raise ValueError()
            except ValueError:raise ValueError('请提供有效的单日日期，例如 2026-10-21。')
            source_reports=c.execute('SELECT content FROM network_daily_reports WHERE report_date=?',(day,)).fetchall()
            source_rows=source_reader(day) if source_reader else c.execute('SELECT region,metrics_json FROM network_daily_indicators WHERE report_date=?',(day,)).fetchall()
    except Exception as exc:
        message=str(exc).lower()
        if getattr(exc,'sqlstate',None)=='42P01' or ('no such table' in message and ('network_daily_reports' in message or 'network_daily_indicators' in message)):
            return {'reply':'尚未初始化网络运行日报数据，请先打开网络运行页面并导入数据。','available':False}
        raise
    if not source_reports and not source_rows:return {'reply':f'{day}没有已保存的网络运行日报或指标数据。','available':False}
    tables=[parse_tables(row[0]) for row in source_reports]
    csv=defaultdict(list);corrupt=set()
    for name,encoded in source_rows:
        try:
            obj=json.loads(encoded)
            if isinstance(obj,dict):csv[name].append(obj)
            else:corrupt.add(name)
        except (ValueError,TypeError):corrupt.add(name)
    field=METRICS[metric][0];unit=METRICS[metric][5]
    names=list(CITIES) if city=='全部地市' else [city];output=[];conflicts=[];missing=[]
    for name in names:
        if ('安徽省' if name=='全省' else name) in corrupt:
            conflicts.append(name);output.append([name,'—','数据格式待核对']);continue
        report=[v for group in tables for v in report_values(group,metric,name)]
        csv_raw=[item.get(field) for item in csv.get('安徽省' if name=='全省' else name,[]) if field and item.get(field) is not None]
        raw=[(v,'历史日报') for v in report]+[(v,'指标CSV') for v in csv_raw]
        vals=[(number(v),str(v),source) for v,source in raw]
        # Compound vendor cells (e.g. 2/7) must not be added or guessed.
        if any(v is None for v,_,_ in vals):
            if len(vals)==1 and '/' in vals[0][1] and metric in ('通感基站数','通感扇区数'):
                output.append([name,vals[0][1]+'（按厂商列示）','历史日报']);continue
            conflicts.append(name);output.append([name,'—','数据格式待核对']);continue
        if not vals:missing.append(name);output.append([name,'—','暂无数据']);continue
        first=vals[0][0]
        if any(abs(v-first)>Decimal('0.005') for v,_,_ in vals[1:]):
            conflicts.append(name);output.append([name,'—','来源存在差异']);continue
        shown=vals[0][1].strip().replace('％','%')
        if unit=='%' and not shown.endswith('%'):shown+='%'
        elif unit!='%':shown+=' '+unit
        origins=' / '.join(dict.fromkeys(source for _,_,source in vals));output.append([name,shown,origins])
    if city!='全部地市':
        name,value,origin=output[0];label='全省' if name=='全省' else name+'市'
        if name in conflicts:return {'reply':f'{day}{label}{metric}的数据来源存在差异或格式不明确，请核对历史日报与 CSV。','available':False}
        if name in missing:return {'reply':f'{day}{label}未保存可用的{metric}数据。','available':False}
        scalar=number(value.removesuffix(' '+unit))
        result={'reply':f'{day}，{label}{metric}为 {value}。数据来源：{origin}。','available':True}
        if scalar is not None:result['stat']={'value':str(scalar),'unit':unit,'day':day,'city':city,'metric':metric}
        return result
    result={'reply':f'{day}各地市{metric}如下。'+(f'部分地市数据缺失或存在差异，已标注。' if missing or conflicts else ''),'available':not (missing or conflicts),'table':{'headers':['地市',metric,'数据来源'],'rows':output,'footnote':'按所选日期原始日报和指标 CSV 查询；“—”表示缺失或来源差异，未按零处理。'}}
    return result

# A daily overview uses only approved province-wide aggregate indicators.
OVERVIEW_METRICS=('5G数据流量','4G数据流量','5G分流比','5G终端用户数','5G活跃用户数','VoNR活跃用户数','SA接通率','SA切换成功率','SA掉线率','LTE无线接通率','LTE切换成功率','LTE无线掉线率','3CC开通站点数','通感基站数')

def overview_plan(messages):
    question=messages[-1]['content']
    if re.search(r'^(?:你)?(?:都|全部|一起)(?:讲|说|介绍|总结|概括)(?:一下|一遍|下)?[？?。！!]*$',question.strip()):
        previous=next((m['content'] for m in reversed(messages[:-1]) if m.get('role')=='user'), '')
        if re.search(r'日报|网络运行',previous): question=previous
    # Only inherit from the immediately preceding user turn, never an older topic.
    if not re.search(r'日报|网络运行',question) and re.search(r'简述|概述|概览|总结|汇总|介绍|讲一下|说一下|核心指标',question) and re.search(r'全省|安徽省|核心指标',question):
        previous=next((m['content'] for m in reversed(messages[:-1]) if m.get('role')=='user'), '')
        if re.search(r'日报|网络运行',previous):
            previous_plan=overview_plan([{'role':'user','content':previous+' 简述'}])
            if previous_plan and 'day' in previous_plan:
                own_day=date_in_question(question)
                day=own_day or previous_plan['day']
                question=question+' 日报'+((' '+(day if day!='latest' else '最新')) if not own_day else '')
    if not (re.search(r'日报|网络运行',question) or re.search(r'全省网络情况|安徽(?:省)?网络情况',question)) or not re.search(r'简述|概述|概览|总结|汇总|介绍|都讲|全部|内容|整体|网络情况',question): return None
    if re.search(r'小区|站点明细|基站明细|用户明细|原因分析|投诉|明细|对比|同比|环比|趋势|排名|昨天和今天',question):
        return {'error':'日报概览目前只支持单日全省汇总指标；明细、原因和跨日比较请分别核对原日报。'}
    if sum(bool(re.search(p,question)) for p in (r'前天',r'昨天|昨日',r'今天|今日'))>1 or len(re.findall(r'(?<!\d)\d{1,2}月\d{1,2}[日号]|20\d{2}[-/]\d{1,2}[-/]\d{1,2}',question))>1:
        return {'error':'请指定一个日期，日报概览暂不支持跨日比较。'}
    if any(city in question for city in CITIES) or re.search(r'各地市|各市',question):
        return {'error':'日报概览暂支持全省；如需地市数据，请指定日期、地市及具体指标。'}
    day=date_in_question(question)
    if not day:return {'error':'请说明日报日期，例如“简述2026年11月2日日报”，或指定最新日报。'}
    return {'day':day}

def overview(connect,day, *, source_reader=None):
    parts=[]; missing=[]
    cache={}
    def cached_reader(selected_day):
        if selected_day not in cache:cache[selected_day]=source_reader(selected_day)
        return cache[selected_day]
    reader=cached_reader if source_reader else None
    for metric in OVERVIEW_METRICS:
        result=query(connect,{'day':day,'city':'全省','metric':metric},source_reader=reader)
        if result.get('available'):
            parts.append(result['reply'])
        else: missing.append(metric)
    if not parts:return {'reply':f'{day}没有可用的全省日报汇总指标，请检查该日期是否已导入及数据是否存在冲突。','available':False}
    actual_day=re.search(r'\d{4}-\d{2}-\d{2}',parts[0]).group(0)
    values=[re.sub(r'^\d{4}-\d{2}-\d{2}，全省','',x).split('数据来源：')[0].rstrip('。') for x in parts]
    return {'reply':f'截至{actual_day}，全省'+ '；'.join(values)+'。','evidence':'\n'.join(parts),'coverage':'仅涵盖已接入且可核对的全省汇总指标；投诉预警、具体原因和未收录指标请查看日报原文。'+('部分指标缺失或存在差异，未列入概览。' if missing else ''),'available':True}


def comparison_plan(question,today=None):
    """Controlled comparison: two explicitly requested relative days and one scope."""
    text=re.sub(r'\s+','',question)
    if not re.search(r'昨天|昨日',text) or '前天' not in text or not re.search(r'比|比较|对比',text):return None
    if re.search(r'同比|上月|排名|原因|小区|明细|黑点|挂起|20\d{2}|\d{1,2}月|今天|今日',text):return {'error':'请仅指定两个明确的日期和同一个汇总指标。'}
    metric=recognize(text)
    if not metric or metric=='多个指标':return {'error':'请指定需要比较的一项日报指标。'}
    cities=[c for c in CITIES if c in text]
    all_cities=bool(re.search(r'各地市|全部地市|各市',text))
    province=bool(re.search(r'全省|安徽省',text))
    if len(cities)>1 or sum((bool(cities),all_cities,province))!=1 or all_cities:return {'error':'跨日比较请指定全省或一个地市。'}
    now=today or date.today()
    return {'metric':metric,'city':cities[0] if cities else '全省','day':(now-timedelta(days=1)).isoformat(),'base_day':(now-timedelta(days=2)).isoformat()}

def compare(connect,plan,*,source_reader=None):
    current=query(connect,{'day':plan['day'],'city':plan['city'],'metric':plan['metric']},source_reader=source_reader)
    previous=query(connect,{'day':plan['base_day'],'city':plan['city'],'metric':plan['metric']},source_reader=source_reader)
    if not current.get('available') or not previous.get('available'):
        return {'reply':'无法完成跨日比较：'+ '；'.join(r['reply'] for r in (previous,current) if not r.get('available')),'available':False}
    if not current.get('stat') or not previous.get('stat'):
        return {'reply':'该指标含分厂商数据，暂不支持直接比较，请核对原始统计。','available':False}
    a=Decimal(current['stat']['value']);b=Decimal(previous['stat']['value']);unit=current['stat']['unit'];delta=a-b
    label='全省' if plan['city']=='全省' else plan['city']+'市'
    direction='增长' if delta>0 else '下降' if delta<0 else '持平'
    change=f'{abs(delta):.2f}'
    if unit=='%':detail='持平' if delta==0 else f'{direction}{change}个百分点'
    else:
        detail='持平' if delta==0 else f'{direction}{change}{unit}'
        if b!=0:detail+=f'，变化率{delta/b*100:+.2f}%'
        else:detail+='；前日为零，无法计算变化率'
    reply=f"{label}{plan['metric']}：{plan['base_day']}为{b} {unit}，{plan['day']}为{a} {unit}，{detail}。"
    return {'reply':reply,'evidence':previous['reply']+'\n'+current['reply'],'available':True}
