"""Dashboard projections of verified aggregates; no raw workbook rows are exposed."""
from datetime import date
from decimal import Decimal
from core import CITIES
import network_query
from smart_query import query as query_statistics

NETWORK_METRICS=('5G数据流量','5G分流比','SA接通率')
CARDS=('5G数据流量','4G数据流量','5G分流比')


def network(connect, day, metric, *, source_reader=None):
    if metric not in NETWORK_METRICS:raise ValueError('请选择支持的网络指标。')
    if day=='latest':
        with connect() as c:
            rows=c.execute('SELECT MAX(report_date) FROM network_daily_reports UNION ALL SELECT MAX(report_date) FROM network_daily_indicators').fetchall()
        dates=[r[0] for r in rows if r[0]]
        if not dates:return {'day':None,'metric':metric,'cities':[],'cards':[],'notice':'尚无已导入的网络日报数据。'}
        day=max(dates)
    if not isinstance(day,str) or len(day)!=10 or date.fromisoformat(day).isoformat()!=day:raise ValueError('请选择有效的日报日期。')
    cache={}
    def reader(d):
        if d not in cache:cache[d]=source_reader(d)
        return cache[d]
    read=reader if source_reader else None
    cities_result=network_query.query(connect,{'day':day,'city':'全部地市','metric':metric},source_reader=read)
    rows=(cities_result.get('table') or {}).get('rows') or []
    unit=network_query.METRICS[metric][5]
    cities=[]
    for row in rows:
        if len(row)<3 or row[0] not in CITIES:continue
        label=str(row[1]);raw=label.removesuffix(' '+unit)
        val=network_query.number(raw)
        if val is not None and val<0:val=None
        cities.append({'name':row[0],'value':float(val) if val is not None else None,'source':row[2]})
    cards=[]
    for name in CARDS:
        result=network_query.query(connect,{'day':day,'city':'全省','metric':name},source_reader=read)
        stat=result.get('stat') if result.get('available') else None
        cards.append({'label':name,'value':stat['value'] if stat else None,'unit':network_query.METRICS[name][5],
                      'source':result.get('reply','').partition('数据来源：')[2].rstrip('。') if stat else result.get('reply','暂无数据')})
    # Traffic is additive across the 16 cities. Compare only a complete set
    # with a verified provincial total, allowing for two-decimal rounding.
    discrepancy=False
    provincial=next((card for card in cards if card['label']==metric),None)
    if metric=='5G数据流量' and len(cities)==len(CITIES) and len({row['name'] for row in cities})==len(CITIES) and all(row['value'] is not None for row in cities) and provincial and provincial['value'] is not None:
        total=sum((Decimal(str(row['value'])) for row in cities),Decimal(0))
        discrepancy=abs(total-Decimal(str(provincial['value'])))>Decimal('0.10')
        if discrepancy:
            for row in cities:row.update(value=None,source='地市合计与全省总量不一致，需核对口径')
    incomplete=len(cities)!=len(CITIES) or any(row['value'] is None for row in cities)
    return {'day':day,'metric':metric,'unit':unit,'cities':cities,'cards':cards,
            'notice':'地市流量合计与全省总量不一致，已暂停地市数值和排序，请核对日报、CSV 与统计口径。' if discrepancy else '部分地市缺失或来源冲突，显示为暂无数据，请核对日报和 CSV。' if incomplete else '按所选日期已保存的数据展示。'}


def monthly(connect, month, *, source_reader=None, suspension_reader=None):
    try:result=query_statistics(connect,'query_city_metrics',{'month':month,'city':'全部地市','metric':'解决率'},structured=True,source_reader=source_reader)
    except (ValueError,RuntimeError) as exc:result={'available':False,'reply':str(exc) or '黑点统计暂不可用。'}
    rows=(result.get('table') or {}).get('rows') or []
    cities=[]
    for row in rows:
        if len(row)<4 or row[0] not in CITIES:continue
        included=network_query.number(row[1]);qualified=network_query.number(row[2])
        if included is None or qualified is None or included<0 or qualified<0 or qualified>included or included!=included.to_integral_value() or qualified!=qualified.to_integral_value():raise ValueError('地市黑点统计存在异常，请核对数据。')
        cities.append({'name':row[0],'included':int(included),'qualified':int(qualified),'rate':float(qualified/included*100) if included else None})
    suspension_notice=None
    try:suspended=suspension_reader(month) if suspension_reader else None
    except (ValueError,RuntimeError) as exc:
        suspended=None;suspension_notice=str(exc) or '挂起统计暂不可用。'
    return {'month':month,'cities':cities,'source_info':result.get('source_info'),
            'notice':None if result.get('available') else result.get('reply','该月暂无黑点统计。'),'suspension_notice':suspension_notice,
            'suspension':{'total':suspended.get('total'),'cities':suspended.get('cities') or [],'period':suspended.get('period'),
                          'kind':suspended.get('kind'),'city_note':suspended.get('city_note')} if suspended else None}
