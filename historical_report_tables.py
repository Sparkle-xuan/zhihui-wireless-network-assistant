"""Recover report tables from pasted text while keeping their original provenance."""
import re

REGIONS=set('安庆 蚌埠 亳州 池州 滁州 阜阳 合肥 淮北 淮南 黄山 六安 马鞍山 宿州 铜陵 芜湖 宣城 安徽省 安徽 全省 汇总 总计 合计'.split())
NUM=re.compile(r'^(?:[-—–]|-?\d[\d,.]*(?:%|％)?(?:\s*/\s*-?\d[\d,.]*(?:%|％)?)*)$')
HEADING=re.compile(r'^[一二三四五六七八九十]+、')

def kind(headers):
    joined='|'.join(headers)
    if '小区名' in headers and 'CGI' in headers: return 'cells'
    if '通感基站数' in joined: return 'sensing'
    if '3CC开通站点数' in joined: return '3cc'
    if '站型分布' in joined and '频段分布' in joined: return 'construction'
    if 'RedCap' in joined and '日均业务量' in joined: return 'redcap'
    if '5G终端用户数' in joined and '地市' in joined: return 'users'
    if '地市' in joined and '5G流量' in joined and '4G流量' in joined: return 'traffic'
    if 'SA接通率' in joined and 'LTE无线接通率' in joined: return 'quality'
    return None

def columns(t,headers):
    if t=='sensing': return headers[:4]
    if t=='3cc': return headers[:4]
    if t=='construction': return [headers[0],headers[1]]+headers[5:]
    if t=='redcap': return headers[:6]
    if t=='users': return [headers[0]]+headers[3:]
    if t in ('traffic','quality'): return [headers[0]]+headers[3:]
    return []

TITLES={'sensing':'通感基站分布','3cc':'3CC 与 5G-A 用户','construction':'RedCap 站点分布','redcap':'RedCap 网络指标','users':'各地市用户数','traffic':'各地市业务量及感知速率','quality':'各地市网络质量','cells':'劣化小区情况'}

def parse(text, include_spans=False):
    if not isinstance(text,str): return []
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    tables=[]
    # The pasted report places each populated Word table cell on its own line.
    for start,line in enumerate(lines):
        if line!='地市': continue
        if lines[start:start+6]==['地市','小区名','CGI','规则','原因分析','处理措施']:
            end=next((j for j in range(start+6,len(lines)) if HEADING.match(lines[j])),len(lines))
            entries=[]; network=''; i=start+6; ok=True
            while i<end:
                if lines[i] in ('4G','5G'): network=lines[i];i+=1;continue
                if not network or i+5>=end: ok=False;break
                row=lines[i:i+6]
                if not re.fullmatch(r'[A-Za-z-]{2,8}',row[0]) or not re.search(r'\d',row[2]): ok=False;break
                entries.append([network]+row);i+=6
            if ok and entries: tables.append({'_pos':start,'_end':end,'id':'cells','title':TITLES['cells'],'headers':['网络','地市','小区名','CGI','规则','原因分析','处理措施'],'rows':entries})
            continue
        first=next((j for j in range(start+1,min(start+25,len(lines))) if lines[j] in REGIONS),None)
        if first is None: continue
        headers=lines[start:first]; k=kind(headers)
        if not k or k=='cells': continue
        cols=columns(k,headers); n=len(cols)-1
        if n<1: continue
        end=next((j for j in range(first+1,len(lines)) if lines[j]=='地市' or HEADING.match(lines[j])),len(lines))
        markers=[j for j in range(first,end) if lines[j] in REGIONS]
        out=[];ok=bool(markers)
        for index,pos in enumerate(markers):
            limit=markers[index+1] if index+1<len(markers) else end
            vals=lines[pos+1:limit]
            if len(vals)<n or (index+1<len(markers) and len(vals)!=n): ok=False;break
            vals=vals[:n]
            numvals=vals[1:] if k in ('construction','sensing') else vals
            if any(not NUM.fullmatch(v) for v in numvals): ok=False;break
            out.append([lines[pos]]+vals)
        if ok and out: tables.append({'_pos':start,'_end':markers[-1]+1+n,'id':k,'title':TITLES[k],'headers':cols,'rows':out})
    # Provincial table is a three-column sequence following its four-cell header.
    for start,line in enumerate(lines):
        if line!='类型' or start+3>=len(lines) or lines[start+1]!='指标' or lines[start+3]!='较上月对比': continue
        end=next((j for j in range(start+4,len(lines)) if lines[j]=='地市'),len(lines))
        i=start+4; group='';out=[];ok=True
        while i<end:
            if lines[i] in ('5G','4G','2G','用户数','业务量'): group=lines[i];i+=1;continue
            if not group or i+2>=end or not NUM.fullmatch(lines[i+1]) or not NUM.fullmatch(lines[i+2]): ok=False;break
            out.append([group,lines[i],lines[i+1],lines[i+2]]);i+=3
        if ok and out: tables.append({'_pos':start,'_end':end,'id':'province','title':'全省用户与业务量','headers':['类型','指标',lines[start+2],'较上月对比'],'rows':out})
        break
    tables.sort(key=lambda item:item['_pos'])
    if not include_spans:
        for table in tables:
            table.pop('_pos'); table.pop('_end')
    return tables
