"""Blackspot statistics. Only aggregates are retained; original workbooks stay local."""
from collections import Counter
from datetime import date
from io import BytesIO
import re
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

CITIES = '安庆 蚌埠 亳州 池州 滁州 阜阳 合肥 淮北 淮南 黄山 六安 马鞍山 宿州 铜陵 芜湖 宣城'.split()
STAGES = '项目申请 勘察设计 站点选址 站点协调 配套建设 设备安装 站点开通'.split()
HEADERS = {'city':'地市','included':'是否已生成黑点编号','status':'当前节点名称-2','before':'未解决投诉数','after':'实时数量','five':'5G投诉数','priority':'专业处理优先级','cost':'整治费用类别','stage':'项目进展','first':'一次质检结果','second':'二次质检结果','category':'waitingClassifyName','kind':'备注-2','coord':'是否存在协调问题'}

def number(v):
    if isinstance(v, bool): return 0
    if isinstance(v,(float,int)): return v
    return 0

def read_rows(sheet, fields):
    iterator = sheet.iter_rows(values_only=True)
    header = next(iterator, ())
    indexes = {}
    for key in fields:
        title=HEADERS[key]
        positions=[i for i,x in enumerate(header) if x == title]
        # The suspension sheet also contains a summary header with the same name;
        # the supplied rule explicitly specifies the detail category in column DB.
        if key=='category' and 105 in positions: positions=[105]
        if len(positions)!=1: raise ValueError(f'工作表「{sheet.title}」缺少或重复字段「{title}」')
        indexes[key]=positions[0]
    for row in iterator:
        item={k: row[i] if i < len(row) else None for k,i in indexes.items()}
        if any(v is not None and str(v).strip() for v in item.values()): yield item

def percentage(n,d): return n/d if d else 0
def fmt(n): return f'{n*100:.2f}%'

def analyze(current, legacy=None):
    w = old = None
    try:
        w=load_workbook(current,read_only=True,data_only=True)
        if legacy is not None: old=load_workbook(legacy,read_only=True,data_only=True)
    except Exception as exc:
        if w: w.close()
        raise ValueError('无法读取 Excel，请确认文件为未损坏的 .xlsx 格式。') from exc
    try:
        if '汇聚黑点-汇总' not in w or '挂起' not in w or (old is not None and '汇聚黑点-汇总' not in old):
            raise ValueError('缺少必要工作表：2026 文件需要「汇聚黑点-汇总」「挂起」，历史文件需要「汇聚黑点-汇总」。')
        rows=list(read_rows(w['汇聚黑点-汇总'],['city','included','status','before','after','five','priority','cost','stage','first','second']))
        suspended=list(read_rows(w['挂起'],['city','category']))
        legacy_rows=list(read_rows(old['汇聚黑点-汇总'],['kind','status','coord'])) if old is not None else None
    finally:
        w.close()
        if old is not None: old.close()
    unknown=sorted({str(r['city']) for r in rows if r['city'] and r['city'] not in CITIES})
    if unknown: raise ValueError('存在无法识别的地市：'+ '、'.join(unknown[:20]))
    city_rows=[]
    for city in CITIES:
        allrows=[r for r in rows if r['city']==city]; inc=[r for r in allrows if r['included']=='是']
        num=len(inc); before=sum(number(r['before']) for r in inc); after=sum(number(r['after']) for r in inc)
        qualified=sum(r['first']=='合格' and (r['second'] in (None,'','合格')) for r in inc)
        stages={s:sum(r['stage']==s and r['status']=='地市处理' for r in inc) for s in STAGES}
        city_rows.append({'city':city,'platform':len(allrows),'platform_complaints':sum(number(r['before']) for r in allrows),'included':num,'complaints':before,'five':sum(number(r['five']) for r in inc),'suspended':sum(r['status']=='挂起' for r in allrows),'investment':sum(r['cost']=='投资' for r in inc),'cost':sum(r['cost']=='成本' for r in inc),'stages':stages,'qualified':qualified,'rate':percentage(qualified,num),'after':after,'solved':before-after,'reduction':1-after/before if before else 0})
    keys=['platform','platform_complaints','included','complaints','five','suspended','investment','cost','qualified','after','solved']
    total={k:sum(r[k] for r in city_rows) for k in keys}
    total['rate']=percentage(total['qualified'],total['included']); total['reduction']=1-total['after']/total['complaints'] if total['complaints'] else 0
    total['stages']={s:sum(r['stages'][s] for r in city_rows) for s in STAGES}
    qualified_rows=[r for r in rows if r['included']=='是' and r['status'] in ('评估环节','归档','人工审核')]
    archived=[r for r in rows if r['status']=='归档']
    global_rows=[r for r in rows if r['included']=='是' and r['priority']=='全球通']
    gb=sum(r['status'] in ('评估环节','归档') for r in global_rows)
    suspended_city=Counter(str(r['city']) for r in suspended if r['city']); categories=Counter(str(r['category']) for r in suspended if r['category'])
    legacy_result=None
    if legacy_rows is not None:
        prior=[r for r in legacy_rows if r['kind']=='遗留94处']; done=sum(r['status'] in ('评估环节','归档') for r in prior); coordination=sum(r['status']=='地市处理' and r['coord']=='是' for r in prior)
        legacy_result={'count':94,'done':done,'remaining':94-done,'coordination':coordination,'other':94-done-coordination,'rate':percentage(done,94)}
    def aggregate(rr):
        b=sum(number(r['before']) for r in rr); a=sum(number(r['after']) for r in rr)
        return {'before':b,'after':a,'reduction':abs(a/b-1) if b else 0}
    return {'cities':city_rows,'total':total,'qualified_complaints':aggregate(qualified_rows),'archive':{'count':len(archived),**aggregate(archived)},'global':{'count':len(global_rows),'qualified':gb,'rate':percentage(gb,len(global_rows)),'opening':sum(r['status'] in ('地市处理','结果质检') and r['stage'] in ('站点开通','设备安装') for r in global_rows)},'suspended':{'count':len(suspended),'cities':suspended_city.most_common(),'categories':dict(categories)},'legacy':legacy_result}

def reports(data, period, previous, notes):
    t=data['total']; q=data['qualified_complaints']; a=data['archive']; g=data['global']; h=data['suspended']; l=data['legacy']
    week_new=str(t['included']-previous['included']) if previous is not None else '待补上周数据'
    week_solved=str(t['qualified']-previous['qualified']) if previous is not None else '待补上周数据'
    stages='，'.join(f'{name}{t["stages"][name]}处' for name in STAGES)
    ranked='、'.join(f'{name}{count}处' for name,count in h['cities'][:3]) or '暂无地市数据'
    cats='，'.join(f'{name}{count}处' for name,count in h['categories'].items()) or '暂无分类数据'
    weekly=f'四、2026年重点投诉区域情况\n1、总体情况：本周新增{week_new}处重点投诉区域入库，总体重点投诉区域入库{t["included"]}处，目前全量重点投诉区域已质检合格{t["qualified"]}处（本周解决{week_solved}处），质检合格率{fmt(t["rate"])}。已质检合格重点投诉区域整治前累计关联未解决投诉{q["before"]}件，整治后未解决投诉{q["after"]}件，投诉压降{fmt(q["reduction"])}。其中经过三个月观察期已归档{a["count"]}处，关联的未解决投诉从{a["before"]}减少到{a["after"]}个，压降{fmt(a["reduction"])}。遗留重点投诉区域中按照整治进展来看，目前{stages}；\n2、全球通白金卡、钻石卡用户投诉入库管理：累计入库{g["count"]}处，目前已质检合格{g["qualified"]}处，解决率{fmt(g["rate"])}，站点开通及设备安装{g["opening"]}处。{notes.get("global", "")}\n3、重点投诉区域挂起库：目前挂起库中存在{h["count"]}处，地市分布靠前的为{ranked}。挂起重点投诉区域中按照归属类别来看，{cats}。{notes.get("suspended", "")}'
    remaining=t['included']-t['qualified']
    monthly=None
    if l is not None:
        monthly=f'四、重点投诉区域处理情况\n截至{period[:7]}，全省汇聚重点投诉区域{t["included"]}个，其中已整治完成{t["qualified"]}处，解决率{fmt(t["rate"])}，剩余{remaining}处。{notes.get("monthly") or "工程及成本优化项目解决情况待补充。"}\n\n全球通白金卡、钻石卡用户投诉入库管理：累计入库{g["count"]}处，目前已质检合格{g["qualified"]}处，解决率{fmt(g["rate"])}，站点开通及设备安装{g["opening"]}处。{notes.get("global", "")}\n\n按照巡视反馈情况，2024年未如期解决投诉黑点94处，截至目前已解决{l["done"]}处，整体解决率{fmt(l["rate"])}；遗留未解决{l["remaining"]}处，其中{l["other"]}处整治效果待完善，{l["coordination"]}处存在协调问题。{notes.get("legacy") or "具体进展及附件清单待补充。"}'
    return weekly,monthly

def export_monthly(data, report, period):
    wb=Workbook(); ws=wb.active; ws.title='月报'
    ws.merge_cells('A1:G1'); ws['A1']='重点投诉区域处理月报'; ws['A1'].font=Font(size=16,bold=True,color='153E52'); ws['A2']='数据日期'; ws['B2']=period
    ws.merge_cells('A4:G4'); ws['A4']=report; ws['A4'].alignment=Alignment(wrap_text=True,vertical='top'); ws.row_dimensions[4].height=max(130, len(report)//42*16)
    headers=['地市','黑点确认纳入数量','质检合格','合格率','实时未解决投诉','已解决数','投诉压降数']; ws.append([]); ws.append(headers)
    for cell in ws[6]: cell.fill=PatternFill('solid',fgColor='FFF200'); cell.font=Font(bold=True); cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
    for r in data['cities']+[dict(data['total'],city='总计')]: ws.append([r['city'],r['included'],r['qualified'],r['rate'],r['after'],r['solved'],r['reduction']])
    for row in ws.iter_rows(min_row=7,max_row=ws.max_row):
        for c in row: c.alignment=Alignment(horizontal='center'); c.border=Border(*(Side(style='thin',color='B5C4CA'),)*4)
        for idx in (3,6): row[idx].number_format='0.00%'
    for col,width in zip('ABCDEFG',[14,22,15,15,20,15,18]): ws.column_dimensions[col].width=width
    ws.freeze_panes='B7'; ws.row_dimensions[6].height=32
    for c in ws[ws.max_row]: c.fill=PatternFill('solid',fgColor='DDEBF7'); c.font=Font(bold=True)
    output=BytesIO(); wb.save(output); output.seek(0); return output
