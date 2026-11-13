"""Small local query for user-maintained city follow-up records."""
import re
from datetime import date
from core import CITIES
from suspension import previous_month

def plan(question,today=None):
    if not re.search(r'推进记录|跟进记录|推进台账|提醒过.{0,30}(?:推进|进展)|(?:推进|跟进).{0,8}(?:台账|记录)',question):return None
    today=today or date.today()
    pairs=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])(?!\d)\s*月?',question)
    bare=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月',question)
    if len(pairs)>1 or len(bare)>1:return {'error':'请指定一个需要查询的月份。'}
    if not pairs and not bare and re.search(r'20\d{2}|\d+\s*月',question):return {'error':'月份无效，请输入例如“2026年10月”。'}
    if pairs:month=f'{pairs[0][0]}-{int(pairs[0][1]):02d}'
    elif bare:month=f'{today.year}-{int(bare[0]):02d}'
    elif re.search(r'上个?月',question):month=previous_month(today.strftime('%Y-%m'))
    elif re.search(r'本月|这个月',question):month=today.strftime('%Y-%m')
    else:month=None
    cities=[city for city in CITIES if city in question]
    if len(cities)>1:return {'error':'请指定一个地市或查询全部地市。'}
    return {'month':month,'city':cities[0] if cities else None}

def answer(plan,records,alerts):
    month=plan.get('month');city=plan.get('city')
    chosen=[r for r in records if (not month or r['month']==month) and (not city or r['city']==city)]
    sent=[a for a in alerts if a['status']=='sent' and (not city or a['city']==city)]
    intro=(month or '最近')+'推进记录：'
    if not chosen:
        intro+='暂无符合条件的人工推进记录。'
    else:intro+=f'{"最近 " if len(chosen)==100 else "共 "}{len(chosen)} 条，详情如下。'
    if month:
        intro+='该月系统记录已提交提醒的地市：'+('、'.join(a['city'] for a in sent) if sent else '暂无')+'。'
    result={'reply':intro,'evidence':'提醒仅表示系统记录邮箱服务器已接受，不代表对方收到；推进状态来自人工维护的记录，最多展示符合条件的最近 100 条。','local_query':True}
    if chosen:result['table']={'headers':['月份','地市','关注事项','推进状态','下次跟进'],'rows':[[r['month'],r['city'],r['issue'],r['status'],r['next_date'] or '未设置'] for r in chosen]}
    return result
