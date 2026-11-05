"""Structured, editable daily reports and safe email rendering."""
import html
import json
import re
from datetime import datetime, timezone
from historical_report_tables import parse as parse_tables

MAX_BLOCKS=500
ALLOWED_FONTS={'Microsoft YaHei','SimSun','SimHei','Arial'}
ALLOWED_SIZES={12,14,16,18,20,24,28}
COLOR_RE=re.compile(r'^#[0-9a-fA-F]{6}$')

def validate_runs(value,runs):
    if not isinstance(runs,list) or len(runs)>5000: raise ValueError('文字样式格式无效。')
    clean=[]
    for r in runs:
        if not isinstance(r,dict) or not isinstance(r.get('text'),str): raise ValueError('文字样式格式无效。')
        item={'text':r['text']}
        if 'font' in r:
            if r['font'] not in ALLOWED_FONTS: raise ValueError('字体不受支持。')
            item['font']=r['font']
        if 'size' in r:
            if type(r['size']) is not int or r['size'] not in ALLOWED_SIZES: raise ValueError('字号不受支持。')
            item['size']=r['size']
        if 'color' in r:
            if not isinstance(r['color'],str) or not COLOR_RE.fullmatch(r['color']): raise ValueError('文字颜色无效。')
            item['color']=r['color'].lower()
        for key in ('bold','italic','underline'):
            if key in r:
                if type(r[key]) is not bool: raise ValueError('文字样式格式无效。')
                if r[key]: item[key]=True
        clean.append(item)
    if ''.join(r['text'] for r in clean)!=value: raise ValueError('文字与样式内容不一致，请重新编辑。')
    return clean

def runs_html(runs):
    parts=[]
    for run in runs:
        css=[]
        if run.get('font'): css.append('font-family:'+run['font'])
        if run.get('size'): css.append('font-size:'+str(run['size'])+'px')
        if run.get('color'): css.append('color:'+run['color'])
        if run.get('bold'): css.append('font-weight:bold')
        if run.get('italic'): css.append('font-style:italic')
        if run.get('underline'): css.append('text-decoration:underline')
        text=html.escape(run['text']).replace('\n','<br>')
        parts.append('<span style="'+';'.join(css)+'">'+text+'</span>' if css else text)
    return ''.join(parts)

def schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS network_daily_documents (report_date TEXT PRIMARY KEY, document_json TEXT NOT NULL, updated_at TEXT NOT NULL)')

def validate(blocks):
    if not isinstance(blocks,list) or not blocks or len(blocks)>MAX_BLOCKS: raise ValueError('日报内容无效或过长。')
    result=[];chars=0;cells=0
    for b in blocks:
        if not isinstance(b,dict): raise ValueError('日报内容格式无效。')
        if b.get('type')=='text':
            value=b.get('text')
            if not isinstance(value,str) or len(value)>20000: raise ValueError('日报文字格式无效。')
            item={'type':'text','text':value}
            if 'runs' in b: item['runs']=validate_runs(value,b['runs'])
            chars+=len(value);result.append(item)
        elif b.get('type')=='table':
            title=b.get('title','');headers=b.get('headers');rows=b.get('rows')
            if not isinstance(title,str) or len(title)>200 or not isinstance(headers,list) or not 1<=len(headers)<=30 or not isinstance(rows,list) or len(rows)>300: raise ValueError('日报表格格式无效。')
            if any(not isinstance(x,str) or len(x)>1000 for x in headers): raise ValueError('日报表头格式无效。')
            if any(not isinstance(row,list) or len(row)!=len(headers) or any(not isinstance(x,str) or len(x)>5000 for x in row) for row in rows): raise ValueError('日报表格内容格式无效。')
            chars+=len(title)+sum(map(len,headers))+sum(len(x) for row in rows for x in row);cells+=len(headers)*len(rows)
            result.append({'type':'table','title':title,'headers':headers,'rows':rows})
        else: raise ValueError('日报内容类型无效。')
    if chars>100000 or cells>10000: raise ValueError('日报内容过长。')
    return result

def from_text(text):
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    tables=parse_tables(text,include_spans=True);by_start={t['_pos']:t for t in tables};result=[];i=0
    while i<len(lines):
        if i in by_start:
            t=by_start[i]; result.append({'type':'table','title':t['title'],'headers':t['headers'],'rows':t['rows']});i=t['_end']
        else:
            result.append({'type':'text','text':lines[i]});i+=1
    if result and not any(b['type']=='text' and re.search(r'投诉预警',b['text']) for b in result):
        result.extend([{'type':'text','text':'投诉预警情况'},{'type':'text','text':''}])
    elif result and result[-1]['type']=='text' and '投诉预警' in result[-1]['text']:
        result.append({'type':'text','text':''})
    return result or [{'type':'text','text':''}]

def load(c,day):
    schema(c);row=c.execute('SELECT document_json,updated_at FROM network_daily_documents WHERE report_date=?',(day,)).fetchone()
    return (validate(json.loads(row[0])),row[1]) if row else (None,None)

def save(c,day,blocks):
    schema(c);clean=validate(blocks);now=datetime.now(timezone.utc).isoformat()
    c.execute('INSERT INTO network_daily_documents VALUES (?,?,?) ON CONFLICT(report_date) DO UPDATE SET document_json=excluded.document_json,updated_at=excluded.updated_at',(day,json.dumps(clean,ensure_ascii=False),now))
    return now

def email_parts(blocks):
    blocks=validate(blocks);plain=[];parts=[]
    for index,b in enumerate(blocks):
        if b['type']=='text':
            plain.append(b['text']); content=runs_html(b['runs']) if 'runs' in b else html.escape(b['text']).replace('\n','<br>')
            if index==0:
                parts.append('<p style="margin:12px 0;text-align:center;font-size:18px;font-weight:bold;white-space:pre-wrap;line-height:1.65"><strong>'+content+'</strong></p>')
            else:
                parts.append('<p style="margin:12px 0;white-space:pre-wrap;line-height:1.65">'+content+'</p>')
        else:
            plain.append(b['title']);plain.append('\t'.join(b['headers']))
            plain.extend('\t'.join(row) for row in b['rows'])
            parts.append('<h3 style="font-size:15px;margin:20px 0 8px">'+html.escape(b['title'])+'</h3>')
            parts.append('<table style="border-collapse:collapse;font-size:12px;width:100%;margin:8px 0 20px"><thead><tr>'+''.join('<th style="border:1px solid #777;padding:5px;background:#f3f2f8">'+html.escape(v)+'</th>' for v in b['headers'])+'</tr></thead><tbody>')
            for row in b['rows']:
                parts.append('<tr>'+''.join('<td style="border:1px solid #777;padding:5px;vertical-align:top">'+html.escape(v).replace('\n','<br>')+'</td>' for v in row)+'</tr>')
            parts.append('</tbody></table>')
    return '\n\n'.join(plain), '<!doctype html><html><body style="font-family:Microsoft YaHei,Arial,sans-serif;color:#222">'+''.join(parts)+'</body></html>'

USER_FIELDS=[('lte_online_users','LTE 在线用户数（万户）',False),('volte_online_users','VoLTE 在网用户数（万户）',False),('nr_terminal_users','5G 终端用户数（万户）',False),('nr_terminal_login_users_day','5G 当日终端登网用户数（万户）',False),('nr_login_users_mon','5G 当月累计登网用户数（万户）',False)]
TRAFFIC_FIELDS=[('lte_upoct','4G 流量（TB）',False),('nr_upoct','5G 流量（TB）',False),('split_flow_rate','5G 分流比',True),('upoct_700','700M 流量（TB）',False),('lowdatauser_rate','5G 低速率用户占比',True),('upoctul_user_rate','4G 上行速率（Mbps）',False),('upoctdl_user_rate','4G 下行速率（Mbps）',False),('upoctul_user_rate_5g','5G 上行速率（Mbps）',False),('upoctdl_user_rate_5g','5G 下行速率（Mbps）',False),('vonr_voice_traffic','VoNR 话务量（万 Erl）',False),('volte_voice_traffic','VoLTE 话务量（万 Erl）',False)]
QUALITY_FIELDS=[('wirelessconn_rate_5g','SA 接通率',True),('enb_suc_rate_5g','SA 切换成功率',True),('wirelessdrop_rate_5g','SA 掉线率',True),('epsfb_fallback_succ_rate','EPSFB 回落成功率',True),('wirelessconn_rate','LTE 无线接通率',True),('enb_suc_rate','LTE 切换成功率',True),('wirelessdrop_rate','LTE 无线掉线率',True),('low2high2_rate','VoLTE 两高两低小区占比',True)]
PROVINCE_FIELDS=[('用户数','vonr_active_users','VoNR 活跃用户数（万户）',False),('用户数','nr_terminal_users','5G 终端用户数（万户）',False),('用户数','nr_terminal_login_users_day','5G 当日终端登网用户数（万户）',False),('用户数','lte_online_users','LTE 在线用户数（万户）',False),('用户数','volte_online_users','VoLTE 在网用户数（万户）',False),('业务量','nr_upoct','5G 数据流量（TB）',False),('业务量','split_flow_rate','5G 分流比',True),('业务量','upoct_700','700M 数据流量（TB）',False),('业务量','lte_upoct','4G 数据流量（TB）',False),('业务量','vonr_voice_traffic','VoNR 话务量（万 Erl）',False),('业务量','volte_voice_traffic','VoLTE 话务量（万 Erl）',False),('业务量','tch_traffic_sum','2G 话务量（万 Erl）',False),('业务量','gsm_traffic_rate','2G 话务量占比',True)]

def stat_document(data, text):
    table_data=data['report_tables']; province=table_data['province'];cities=table_data['cities']
    def fmt(value,pct): return '—' if value is None or value=='' else str(value)+('%' if pct else '')
    def city_table(title,fields):
        return {'type':'table','title':title,'headers':['地市']+[label for _,label,_ in fields], 'rows':[[row['city']]+[fmt(row['values'].get(key),pct) for key,_,pct in fields] for row in cities]}
    prov={'type':'table','title':'全省用户与业务量','headers':['类型','指标',data['date'],'较上月对比'],'rows':[[group,label,fmt(province.get(key),pct),'—'] for group,key,label,pct in PROVINCE_FIELDS]}
    blocks=from_text(text);out=[];inserted=False
    for b in blocks:
        if b['type']=='text' and '无线网络运行质量' in b['text']:
            out.extend([prov,city_table('各地市用户数',USER_FIELDS),city_table('各地市业务量及感知速率',TRAFFIC_FIELDS)]);inserted=True
        out.append(b)
        if b['type']=='text' and '无线网络运行质量' in b['text']:
            out.append(city_table('各地市网络质量',QUALITY_FIELDS))
    if not inserted: out.extend([prov,city_table('各地市用户数',USER_FIELDS),city_table('各地市业务量及感知速率',TRAFFIC_FIELDS),city_table('各地市网络质量',QUALITY_FIELDS)])
    return out
