import json
import hashlib
import os
import re
import sqlite3
import smtplib
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file
sys.path.insert(0,str(Path(__file__).parent / '.deps'))
from core import analyze, reports, export_monthly, CITIES
from mailing import send_report
from assistant_service import complete as complete_chat
from assistant_service import plan_query, summarize_query, validate_model, diagnose_suspension, DEFAULT_MODEL
from smart_query import query as query_statistics, identify_explicit_metric, local_query_plan, highest_resolution_plan, highest_resolution
import credential_store
from network_daily_store import import_history
import network_daily
import network_query
import query_context
import analysis_planner
import ranking_planner
import wren_daily_bridge
import network_document
import suspension
import suspension_reasons

app=Flask(__name__,instance_relative_config=True)
from complaint_routes import complaints
app.register_blueprint(complaints)
app.config['MAX_CONTENT_LENGTH']=30*1024*1024
Path(app.instance_path).mkdir(parents=True,exist_ok=True)
DB=Path(app.instance_path)/'zhihui.sqlite3'

@contextmanager
def connect():
    backend=os.environ.get('ZHIHUI_DATABASE','sqlite')
    if backend=='postgres':
        import psycopg
        raw=psycopg.connect(host=os.environ.get('PGHOST','127.0.0.1'),port=os.environ.get('PGPORT','5432'),dbname=os.environ.get('PGDATABASE','zhihui'),user=os.environ.get('PGUSER','postgres'),password=os.environ.get('PGPASSWORD'),connect_timeout=5)
        class PostgresConnection:
            def execute(self, query, params=()): return raw.execute(query.replace('?', '%s'),params)
        c=PostgresConnection()
        try:
            with raw: yield c
        finally: raw.close()
        return
    if backend!='sqlite': raise RuntimeError('未知的数据库类型')
    c=sqlite3.connect(DB)
    try:
        c.execute('CREATE TABLE IF NOT EXISTS reports (period TEXT PRIMARY KEY, data TEXT NOT NULL, notes TEXT NOT NULL, weekly TEXT NOT NULL, monthly TEXT NOT NULL)')
        columns={row[1] for row in c.execute('PRAGMA table_info(reports)')}
        if 'monthly_data' not in columns:
            c.execute('ALTER TABLE reports ADD COLUMN monthly_data TEXT')
            c.execute("UPDATE reports SET monthly_data = data WHERE monthly != ''")
        for name in ('weekly_generated_at','monthly_generated_at','weekly_updated_at','monthly_updated_at'):
            if name not in columns: c.execute(f'ALTER TABLE reports ADD COLUMN {name} TEXT')
        with c: yield c
    finally: c.close()

@app.get('/')
def index(): return render_template('index.html')

@app.get('/network')
def network_page(): return render_template('network.html')

@app.get('/suspension')
def suspension_page(): return render_template('suspension.html')

def suspension_last_friday(month):
    import calendar
    suspension.previous_month(month)  # Validate the input format and month.
    year,number=map(int,month.split('-'))
    end=date(year,number,calendar.monthrange(year,number)[1])
    return (end-timedelta(days=(end.weekday()-4)%7)).isoformat()

def ensure_suspension_manual(c):
    c.execute('CREATE TABLE IF NOT EXISTS suspension_manual (month TEXT PRIMARY KEY, snapshot TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS suspension_imports (month TEXT PRIMARY KEY, source_date TEXT NOT NULL, snapshot TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS suspension_estimates (month TEXT PRIMARY KEY, source_date TEXT NOT NULL, categories TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS suspension_preferences (month TEXT PRIMARY KEY, source TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS suspension_reason_summaries (fingerprint TEXT PRIMARY KEY, month TEXT NOT NULL, source_date TEXT NOT NULL, summary TEXT NOT NULL)')

@app.get('/api/suspension/periods')
def suspension_periods():
    with connect() as c:
        ensure_suspension_manual(c)
        rows=c.execute("SELECT period,weekly,monthly FROM reports WHERE weekly <> '' OR monthly <> '' ORDER BY period DESC").fetchall()
        manual=c.execute('SELECT month FROM suspension_manual ORDER BY month DESC').fetchall()
        imported=c.execute('SELECT month FROM suspension_imports ORDER BY month DESC').fetchall()
    months={}
    for period,weekly,monthly in rows:
        try:
            if date.fromisoformat(period).isoformat()!=period:continue
            month=period[:7];expected=suspension_last_friday(month)
        except (ValueError,TypeError):continue
        entry=months.setdefault(month,{'month':month,'available':False,'expected_period':expected})
        if period==expected and (weekly or monthly):entry['available']=True
    for (month,) in manual+imported:
        try:expected=suspension_last_friday(month)
        except (ValueError,TypeError):continue
        entry=months.setdefault(month,{'month':month,'available':False,'expected_period':expected})
        entry['available']=True
    return jsonify(sorted(months.values(),key=lambda x:x['month'],reverse=True))

def suspension_month_snapshot_base(c,month,source=None):
    period=suspension_last_friday(month)
    ensure_suspension_manual(c)
    if source is None:
        preference=c.execute('SELECT source FROM suspension_preferences WHERE month=?',(month,)).fetchone()
        if preference:source=preference[0]
    if source=='manual':
        manual=c.execute('SELECT snapshot FROM suspension_manual WHERE month=?',(month,)).fetchone()
        return suspension.summary(manual[0],None,'manual') if manual else None
    imported=c.execute('SELECT source_date,snapshot FROM suspension_imports WHERE month=?',(month,)).fetchone()
    if imported:
        result=suspension.summary(imported[1],imported[0],'imported')
        if result['categories'] is None:
            estimate=c.execute('SELECT source_date,categories FROM suspension_estimates WHERE month=?',(month,)).fetchone()
            if estimate and estimate[0]==imported[0]:
                provisional=json.loads(estimate[1]);snapshot=json.loads(imported[1]);snapshot['suspended']['categories']=provisional
                result=suspension.summary(json.dumps(snapshot,ensure_ascii=False),imported[0],'imported')
                result['category_estimated']=True
                result['category_note']='基于不纳入原因的关键词初筛，并非原表归属类别；提及协调或纠纷优先归协调，无法唯一判断的列为待核实。'
            else:result['category_note']='原表未提供挂起归属类别，暂无法统计分类。'
        return result
    if source=='imported':return None
    row=c.execute('SELECT data,monthly_data,weekly,monthly FROM reports WHERE period=?',(period,)).fetchone()
    if row:
        data,monthly_data,weekly,monthly=row
        if weekly:return suspension.summary(data,period,'weekly')
        if monthly:return suspension.summary(monthly_data or data,period,'monthly')
    ensure_suspension_manual(c)
    manual=c.execute('SELECT snapshot FROM suspension_manual WHERE month=?',(month,)).fetchone()
    return suspension.summary(manual[0],None,'manual') if manual else None


def suspension_reason_fingerprint(month,current):
    base={key:value for key,value in current.items() if key!='reason_analysis'}
    return hashlib.sha256(json.dumps({'version':1,'month':month,'snapshot':base},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def suspension_month_snapshot(c,month,source=None):
    result=suspension_month_snapshot_base(c,month,source)
    if result:
        row=c.execute('SELECT summary FROM suspension_reason_summaries WHERE fingerprint=?',(suspension_reason_fingerprint(month,result),)).fetchone()
        if row:
            try:
                reasons=suspension_reasons.validate(json.loads(row[0]),result['total'],CITIES)
                if reasons is not None:result['reason_analysis']=reasons
            except (ValueError,TypeError):pass
    return result


@app.post('/api/suspension/reasons/import')
def suspension_reasons_import():
    try:
        month=request.form.get('month');suspension.previous_month(month)
        source=request.form.get('source') or None
        if source not in (None,'manual','imported'):raise ValueError('版本选择无效。')
        upload=request.files.get('file')
        if not upload or not upload.filename or not upload.filename.lower().endswith('.xlsx'):raise ValueError('请选择当期 .xlsx 工单表。')
        with connect() as c:current=suspension_month_snapshot_base(c,month,source)
        if not current or not current.get('period'):raise ValueError('当前版本缺少原表统计日期，不能关联原因；请选择对应工单表版本。')
        dates=set()
        for m in re.finditer(r'(?<!\d)(20\d{2})[-_.年]?(\d{2})[-_.月]?(\d{2})(?:日)?(?!\d)',upload.filename):
            try:dates.add(date(*map(int,m.groups())).isoformat())
            except ValueError:pass
        if dates!={current['period']}:raise ValueError('文件名中的日期与当前版本统计日期不一致。')
        extracted=suspension.workbook_summary(upload.stream)
        fresh=suspension.summary(json.dumps(extracted,ensure_ascii=False),current['period'],current['kind'])
        reasons=fresh.get('reason_analysis')
        if not reasons:raise ValueError('表中缺少可用的不纳入原因列，或有效工单数与统计不一致。')
        if current['city_note'] or fresh['city_note'] or current['total']!=fresh['total'] or current['cities']!=fresh['cities']:
            raise ValueError('文件的挂起总数或地市分布与当前版本不一致，请核对原表。')
        if current.get('categories') is not None and not current.get('category_estimated') and current['categories']!=fresh['categories']:
            def category_map(items):return {item['name']:item['value'] for item in items or []}
            if category_map(current['categories'])!=category_map(fresh['categories']):raise ValueError('文件的挂起分类与当前版本不一致，请核对原表。')
        fingerprint=suspension_reason_fingerprint(month,current)
        with connect() as c:
            latest=suspension_month_snapshot_base(c,month,source)
            if not latest or suspension_reason_fingerprint(month,latest)!=fingerprint:raise ValueError('该月数据已变化，请刷新后重试。')
            c.execute('INSERT INTO suspension_reason_summaries (fingerprint,month,source_date,summary) VALUES (?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET summary=excluded.summary',
                      (fingerprint,month,current['period'],json.dumps(reasons,ensure_ascii=False)))
        return jsonify({'ok':True,'message':'已补充原因关键词汇总，请重新诊断。'})
    except (ValueError,TypeError) as exc:return jsonify({'error':str(exc) or '文件或日期无效。'}),400

@app.post('/api/suspension/import')
def suspension_import():
    try:
        source_date=request.form.get('source_date','')
        parsed=date.fromisoformat(source_date)
        if parsed.isoformat()!=source_date:raise ValueError('请选择有效的统计日期。')
        upload=request.files.get('file')
        if not upload or not upload.filename or not upload.filename.lower().endswith('.xlsx'):raise ValueError('请选择 .xlsx 格式的当年工单表。')
        dates=set()
        for m in re.finditer(r'(?<!\d)(20\d{2})[-_.年]?(\d{2})[-_.月]?(\d{2})(?:日)?(?!\d)',upload.filename):
            try:dates.add(date(*map(int,m.groups())).isoformat())
            except ValueError:pass
        if len(dates)!=1 or source_date not in dates:raise ValueError('文件名中的日期与所选统计日期不一致，请核对。')
        provisional=request.form.get('provisional','')=='1'
        extracted=suspension.workbook_summary(upload.stream,provisional=provisional)
        estimated=extracted.pop('estimated_categories',None)
        if provisional and estimated is None:raise ValueError('该表已有原始归属分类，不需要关键词初筛。')
        snapshot=json.dumps(extracted,ensure_ascii=False,sort_keys=True)
        month=source_date[:7]
        with connect() as c:
            ensure_suspension_manual(c)
            existing=c.execute('SELECT source_date,snapshot FROM suspension_imports WHERE month=?',(month,)).fetchone()
            if existing:
                saved=json.loads(existing[1]);fresh=json.loads(snapshot)
                saved.get('suspended',{}).pop('reason_analysis',None);fresh.get('suspended',{}).pop('reason_analysis',None)
                if existing[0]!=source_date or saved!=fresh:return jsonify({'error':'该月已有不同的导入记录，为避免覆盖，请先核对已有数据。'}),409
            else:c.execute('INSERT INTO suspension_imports (month,source_date,snapshot) VALUES (?,?,?)',(month,source_date,snapshot))
            if estimated is not None:
                encoded=json.dumps(estimated,ensure_ascii=False,sort_keys=True)
                previous=c.execute('SELECT source_date,categories FROM suspension_estimates WHERE month=?',(month,)).fetchone()
                if previous and (previous[0]!=source_date or json.loads(previous[1])!=estimated):return jsonify({'error':'该月已有不同的初筛结果，请先核对。'}),409
                if not previous:c.execute('INSERT INTO suspension_estimates (month,source_date,categories) VALUES (?,?,?)',(month,source_date,encoded))
            reasons=extracted['suspended'].get('reason_analysis')
            if existing and reasons:
                current=suspension_month_snapshot_base(c,month,'imported')
                fingerprint=suspension_reason_fingerprint(month,current)
                c.execute('INSERT INTO suspension_reason_summaries (fingerprint,month,source_date,summary) VALUES (?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET summary=excluded.summary',
                          (fingerprint,month,source_date,json.dumps(reasons,ensure_ascii=False)))
        return jsonify({'ok':True,'message':'已保存该月挂起汇总。'})
    except (ValueError,TypeError) as exc:return jsonify({'error':str(exc) or '文件或日期无效。'}),400

@app.post('/api/suspension/manual')
def suspension_manual_save():
    try:
        payload=request.get_json() or {}
        if not isinstance(payload,dict):raise ValueError('数据格式无效。')
        month=payload.get('month');suspension_last_friday(month)
        total=payload.get('total');cities=payload.get('cities');categories=payload.get('categories')
        if not suspension._count(total) or not isinstance(cities,dict) or not isinstance(categories,dict):raise ValueError('请填写有效月份、总数和汇总数据。')
        if any(name not in CITIES or not suspension._count(value) for name,value in cities.items()):raise ValueError('地市名称或数量无效。')
        if any(not isinstance(name,str) or not name.strip() or len(name)>100 or not suspension._count(value) for name,value in categories.items()):raise ValueError('分类名称或数量无效。')
        if sum(cities.values())>total or sum(categories.values())>total:raise ValueError('地市或分类数量之和不能超过总数。')
        preferred=payload.get('preferred',False)
        if type(preferred) is not bool:raise ValueError('版本选择无效。')
        group={'count':total,'cities':list(cities.items()),'partial_cities':len(cities)!=len(CITIES) or sum(cities.values())!=total}
        if categories:group['categories']=categories
        encoded=json.dumps({'suspended':group},ensure_ascii=False)
        with connect() as c:
            ensure_suspension_manual(c)
            if c.execute('SELECT month FROM suspension_manual WHERE month=?',(month,)).fetchone():return jsonify({'error':'该月份已有补录汇总，为避免覆盖请先核对。'}),409
            c.execute('INSERT INTO suspension_manual (month,snapshot) VALUES (?,?)',(month,encoded))
            if preferred:c.execute('INSERT INTO suspension_preferences (month,source) VALUES (?,?) ON CONFLICT(month) DO UPDATE SET source=excluded.source',(month,'manual'))
        return jsonify({'ok':True})
    except (ValueError,TypeError) as exc:return jsonify({'error':str(exc) or '数据格式无效。'}),400

def selected_suspension(month):
    with connect() as c:return suspension_month_snapshot(c,month)


def suspension_diagnosis_fingerprint(month,current,previous):
    identity={'version':2 if current.get('reason_analysis') else 1,'month':month,'current':current,'previous':previous}
    encoded=json.dumps(identity,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def suspension_diagnosis_table(c):
    c.execute('CREATE TABLE IF NOT EXISTS suspension_diagnoses (fingerprint TEXT PRIMARY KEY, month TEXT NOT NULL, source TEXT NOT NULL, model TEXT NOT NULL, evidence TEXT NOT NULL, reply TEXT NOT NULL, created_at TEXT NOT NULL)')


def suspension_diagnosis_load(c,fingerprint):
    suspension_diagnosis_table(c)
    row=c.execute('SELECT evidence,reply,model,created_at FROM suspension_diagnoses WHERE fingerprint=?',(fingerprint,)).fetchone()
    if not row:return None
    try:evidence=json.loads(row[0])
    except (ValueError,TypeError):return None
    if not isinstance(evidence,dict) or not isinstance(row[1],str) or not row[1].strip():return None
    return {'evidence':evidence,'reply':row[1],'model':row[2],'created_at':row[3],'cached':True}


@app.get('/api/suspension/month/<month>')
def suspension_month_data(month):
    try:
        previous=suspension.previous_month(month)
        source=request.args.get('source') or None
        if source not in (None,'manual','imported'):return jsonify({'error':'版本选择无效。'}),400
        with connect() as c:
            current=suspension_month_snapshot(c,month,source)
            available_sources=[]
            if c.execute('SELECT month FROM suspension_manual WHERE month=?',(month,)).fetchone():available_sources.append({'value':'manual','label':'人工提供的汇总'})
            if c.execute('SELECT month FROM suspension_imports WHERE month=?',(month,)).fetchone():available_sources.append({'value':'imported','label':'工单表统计'})
            if not current:return jsonify({'error':f"该月缺少最后一个周五（{suspension_last_friday(month)}）的周报或同日月报数据，请先生成并保存。"}),404
            try:before=suspension_month_snapshot(c,previous);previous_error=''
            except ValueError:before=None;previous_error='上月月末统计数据缺失或异常，无法比较。'
            saved_diagnosis=suspension_diagnosis_load(c,suspension_diagnosis_fingerprint(month,current,before))
        current['month']=month
        current['sources']=available_sources
        current['warning_cities']=suspension.top_cities(current)
        current['comparison']=suspension.compare(current,before,previous)
        current['diagnosis']=saved_diagnosis
        if previous_error:current['comparison']['note']=previous_error
        return jsonify(current)
    except ValueError as exc:return jsonify({'error':str(exc)}),422

@app.post('/api/suspension/diagnose')
def suspension_diagnose():
    try:
        data=request.get_json(silent=True)
        if not request.is_json or not isinstance(data,dict):raise ValueError('请求格式无效。')
        month=data.get('month');previous=suspension.previous_month(month)
        source=data.get('source') or None
        if source not in (None,'manual','imported'):raise ValueError('版本选择无效。')
        model=validate_model(data.get('model',DEFAULT_MODEL))
        force=data.get('force',False)
        if type(force) is not bool:raise ValueError('请求格式无效。')
        with connect() as c:
            current=suspension_month_snapshot(c,month,source)
            if current is None:raise ValueError('该月或所选版本没有挂起汇总数据。')
            try:before=suspension_month_snapshot(c,previous)
            except ValueError:before=None
            fingerprint=suspension_diagnosis_fingerprint(month,current,before)
            saved=suspension_diagnosis_load(c,fingerprint)
        if saved and not force:return jsonify(saved)
        key=credential_store.get_assistant_key()
        if not key:raise ValueError('请先在小助手设置中保存 DeepSeek API 密钥。')
        evidence=suspension.diagnostic_facts(current,before,month)
        selected_model=model
        try:reply=diagnose_suspension(key,evidence,model=model)
        except ValueError as exc:
            if saved:return jsonify({'evidence':evidence,'reply':None,'notice':str(exc),'cached':False})
            reply=suspension.local_diagnostic_advice(evidence)
            selected_model='local'
        created_at=datetime.now().astimezone().isoformat(timespec='seconds')
        with connect() as c:
            suspension_diagnosis_table(c)
            c.execute('INSERT INTO suspension_diagnoses (fingerprint,month,source,model,evidence,reply,created_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET model=excluded.model,evidence=excluded.evidence,reply=excluded.reply,created_at=excluded.created_at',
                      (fingerprint,month,current['kind'],selected_model,json.dumps(evidence,ensure_ascii=False),reply,created_at))
        return jsonify({'evidence':evidence,'reply':reply,'model':selected_model,'created_at':created_at,'cached':False})
    except (ValueError,RuntimeError) as exc:return jsonify({'error':str(exc)}),400


@app.get('/api/network/dates')
def network_dates():
    with connect() as c: result=network_daily.dates(c)
    return jsonify({'dates':result})

@app.get('/api/network/day/<day>')
def network_day(day):
    try:
        with connect() as c: result=network_daily.detail(c,day)
        return jsonify(result)
    except ValueError as exc: return jsonify({'error':str(exc)}),400

@app.get('/api/network/day/<day>/original/<version>')
def network_original(day,version):
    try:
        with connect() as c: text=network_daily.original(c,day,version)
        return jsonify({'content':text,'historical_tables':network_daily.parse_historical_tables(text),'blocks':network_document.from_text(text)})
    except ValueError as exc: return jsonify({'error':str(exc)}),400

@app.get('/api/network/day/<day>/document')
def network_document_get(day):
    try:
        network_daily.validate_date(day)
        with connect() as c:
            data=network_daily.detail(c,day)
            blocks,updated=network_document.load(c,day)
        source='structured'
        if blocks is None:
            source='legacy' if data['draft'] is not None else 'original'
            text=data['draft'] if data['draft'] is not None else data['original']
            blocks=network_document.from_text(text) if text else []
        return jsonify({'blocks':blocks,'source':source,'updated_at':updated})
    except ValueError as exc: return jsonify({'error':str(exc)}),400

@app.post('/api/network/day/<day>/document')
def network_document_save(day):
    try:
        network_daily.validate_date(day);payload=request.get_json(silent=True)
        if not isinstance(payload,dict): raise ValueError('日报格式无效。')
        with connect() as c: updated=network_document.save(c,day,payload.get('blocks'))
        return jsonify({'ok':True,'updated_at':updated})
    except (ValueError,TypeError) as exc: return jsonify({'error':str(exc)}),400

@app.post('/api/network/day/<day>/document-word')
def network_document_word(day):
    try:
        network_daily.validate_date(day);payload=request.get_json(silent=True)
        if not isinstance(payload,dict): raise ValueError('日报格式无效。')
        from network_word import export_word
        data=export_word(payload.get('blocks'))
        return send_file(data,as_attachment=True,download_name=f'全省无线网络运行日报-{day}.docx',mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    except ModuleNotFoundError:
        return jsonify({'error':'缺少 Word 导出组件，请按项目说明安装 python-docx。'}),500
    except (ValueError,TypeError) as exc: return jsonify({'error':str(exc)}),400

@app.post('/api/network/day/<day>/document-email')
def network_document_email(day):
    try:
        network_daily.validate_date(day);payload=request.get_json(silent=True)
        if not isinstance(payload,dict): raise ValueError('邮件请求格式无效。')
        fields=[payload.get(k,'') for k in ('sender','recipient','auth_code','subject')]
        if not all(isinstance(field,str) for field in fields): raise ValueError('邮件字段格式无效。')
        if not fields[2]: fields[2]=credential_store.get_for_sender(fields[0]) or ''
        if not fields[2]: raise ValueError('没有该发件邮箱已保存的授权码，请先填写或保存。')
        plain,formatted=network_document.email_parts(payload.get('blocks'))
        send_report(*fields,plain,html_body=formatted)
        return jsonify({'ok':True,'message':'QQ 邮箱服务器已接受图文表格邮件，请在发件箱核对。'})
    except (ValueError,TypeError,RuntimeError) as exc: return jsonify({'error':str(exc) or '邮件信息无效。'}),400

@app.post('/api/network/day/<day>/generate')
def network_generate(day):
    try:
        with connect() as c: data=network_daily.detail(c,day)
        content=network_daily.build_draft(data)
        return jsonify({'content':content,'blocks':network_document.stat_document(data,content)})
    except ValueError as exc: return jsonify({'error':str(exc)}),400

@app.post('/api/network/day/<day>/save')
def network_save(day):
    try:
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict): raise ValueError('请求格式无效。')
        with connect() as c: updated=network_daily.save(c,day,payload.get('content'))
        return jsonify({'ok':True,'updated_at':updated})
    except ValueError as exc: return jsonify({'error':str(exc)}),400

@app.post('/api/network/day/<day>/email')
def network_email(day):
    try:
        network_daily.validate_date(day)
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict): raise ValueError('邮件请求格式无效。')
        fields=[payload.get(k,'') for k in ('sender','recipient','auth_code','subject','body')]
        if not all(isinstance(field,str) for field in fields): raise ValueError('邮件字段格式无效。')
        if not fields[2]: fields[2]=credential_store.get_for_sender(fields[0]) or ''
        if not fields[2]: raise ValueError('没有该发件邮箱已保存的授权码，请先填写或保存。')
        send_report(*fields)
        return jsonify({'ok':True,'message':'QQ 邮箱服务器已接受邮件，请在发件箱核对。'})
    except (smtplib.SMTPException,OSError): return jsonify({'error':'邮件发送失败，请检查网络、邮箱地址和授权码后重试。'}),502
    except (ValueError,TypeError,RuntimeError) as exc: return jsonify({'error':str(exc) or '邮件信息无效。'}),400

@app.get('/api/status')
def status():
    with connect() as c: c.execute('SELECT 1').fetchone()
    return jsonify({'database':os.environ.get('ZHIHUI_DATABASE','sqlite'),'connected':True})

def compact_snapshot(data):
    """Save aggregate statistics only; never save the imported workbook rows."""
    totals=('platform','platform_complaints','included','complaints','five','suspended',
            'investment','cost','qualified','rate','after','solved','reduction','stages')
    cities=('city',)+totals
    group_fields={
        'qualified_complaints':('before','after','reduction'),
        'archive':('count','before','after','reduction'),
        'global':('count','qualified','rate','opening'),
        'suspended':('count','cities','categories'),
        'legacy':('count','done','remaining','coordination','other','rate'),
    }
    result={'snapshot_version':2,
            'total':{key:data['total'][key] for key in totals},
            'cities':[{key:row[key] for key in cities} for row in data['cities']]}
    for group,fields in group_fields.items():
        source=data[group]
        result[group]={key:source[key] for key in fields} if source is not None else None
    if data.get('suspended',{}).get('reason_analysis') is not None:
        result['suspended']['reason_analysis']=data['suspended']['reason_analysis']
    return result

def supplement_snapshot(old, fresh):
    """Backfill aggregates only after matching all available comparable counts."""
    if not isinstance(old,dict) or not isinstance(fresh,dict): raise ValueError('历史快照格式异常，无法安全补充。')
    old_total=old.get('total');old_cities=old.get('cities');old_suspended=old.get('suspended')
    if not isinstance(old_total,dict) or not all(k in old_total for k in ('included','qualified')) or not isinstance(old_cities,list) or not isinstance(old_suspended,dict) or 'count' not in old_suspended:
        raise ValueError('历史快照缺少校验所需的汇总，无法安全补充。')
    if any(not isinstance(row,dict) or 'city' not in row or 'included' not in row or 'qualified' not in row for row in old_cities):
        raise ValueError('历史快照缺少地市校验数据，无法安全补充。')
    by_old={row['city']:row for row in old_cities};by_new={row['city']:row for row in fresh['cities']}
    if len(old_cities)!=len(CITIES) or set(by_old)!=set(CITIES) or len(by_old)!=len(old_cities):
        raise ValueError('历史快照的地市数据不完整，无法安全补充。')
    def check(existing,current):
        for key,value in existing.items():
            if key not in current or key=='snapshot_version': continue
            candidate=current[key]
            if isinstance(value,dict) and isinstance(candidate,dict): check(value,candidate)
            elif value!=candidate: raise ValueError('所选表格与历史报告已保存的统计不一致，已停止补充；请确认使用原版本。')
    fresh=json.loads(json.dumps(fresh,ensure_ascii=False))
    by_new={row['city']:row for row in fresh['cities']}
    check(old_total,fresh['total']);check(old_suspended,fresh['suspended'])
    for city in CITIES: check(by_old[city],by_new[city])
    def fill(existing,current):
        merged=dict(existing)
        for key,value in current.items():
            if key not in merged: merged[key]=value
            elif isinstance(merged[key],dict) and isinstance(value,dict): merged[key]=fill(merged[key],value)
        return merged
    result=fill(old,{key:value for key,value in fresh.items() if key not in ('cities','snapshot_version')})
    result['cities']=[fill(row,by_new[row['city']]) for row in old_cities]
    result['snapshot_version']=2
    return result

@app.get('/api/history')
def history():
    with connect() as c: rows=c.execute('SELECT period,data,weekly,monthly FROM reports ORDER BY period DESC').fetchall()
    return jsonify([{'period':p,'included':json.loads(d)['total']['included'],'qualified':json.loads(d)['total']['qualified'],'has_weekly':bool(w),'has_monthly':bool(m)} for p,d,w,m in rows])

@app.get('/api/history/cities')
def city_history():
    month=request.args.get('month','')
    if not re.fullmatch(r'\d{4}-\d{2}',month): return jsonify({'error':'请选择有效月份。'}),400
    try: date.fromisoformat(month+'-01')
    except ValueError: return jsonify({'error':'请选择有效月份。'}),400
    with connect() as c:
        rows=c.execute("SELECT period, CASE WHEN weekly <> '' THEN data ELSE COALESCE(monthly_data,data) END FROM reports WHERE substr(period,1,7)=? ORDER BY period",(month,)).fetchall()
    points=[]
    for period,encoded in rows:
        try:
            data=json.loads(encoded); cities=data.get('cities',[])
            if not isinstance(cities,list): continue
            clean=[]
            for item in cities:
                if not isinstance(item,dict) or item.get('city') not in CITIES: continue
                included=item.get('included');qualified=item.get('qualified')
                if isinstance(included,bool) or isinstance(qualified,bool) or not isinstance(included,(int,float)) or not isinstance(qualified,(int,float)): continue
                if not (0<=included<10**12 and 0<=qualified<10**12): continue
                clean.append({'city':item['city'],'included':included,'qualified':qualified})
            if clean: points.append({'period':period,'cities':clean})
        except (ValueError,TypeError,AttributeError): continue
    return jsonify({'month':month,'cities':CITIES,'points':points})

@app.before_request
def protect_mail_endpoints():
    if request.path.startswith('/api/'):
        allowed={'127.0.0.1:5088','localhost:5088'}
        if app.testing: allowed.update({'localhost','127.0.0.1'})
        origin=request.headers.get('Origin')
        if request.host not in allowed or (origin and origin != f'http://{request.host}'):
            return jsonify({'error':'仅允许本机智徽页面访问此设置。'}),403

@app.after_request
def prevent_credential_response_caching(response):
    if request.path.startswith('/api/'): response.headers['Cache-Control']='no-store'
    return response

@app.post('/api/network/history/import')
def import_network_history():
    try:
        files=request.files.getlist('reports')
        if len(files)>100: raise ValueError('一次最多导入 100 份日报。')
        reports=[f.read() for f in files]
        csv_file=request.files.get('csv')
        csv_data=csv_file.read() if csv_file else None
        with connect() as c:
            result=import_history(c,reports,csv_data)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({'error':str(exc)}),400

@app.route('/api/mail/credential',methods=['GET','POST','DELETE'])
def mail_credential():
    try:
        if request.method=='GET': return jsonify(credential_store.status())
        if not request.is_json: return jsonify({'error':'请求格式无效。'}),400
        if request.method=='POST':
            payload=request.get_json(silent=True) or {}
            if not isinstance(payload,dict): raise ValueError('请求格式无效。')
            credential_store.save(payload.get('sender'),payload.get('auth_code'))
            return jsonify({'ok':True,'message':'授权码已保存至 Windows 凭据管理器。'})
        credential_store.delete()
        return jsonify({'ok':True,'message':'已删除保存的授权码。'})
    except (ValueError,RuntimeError) as exc: return jsonify({'error':str(exc)}),400

@app.route('/api/database/credential',methods=['GET','POST'])
def database_credential():
    try:
        if request.method=='GET':
            saved=credential_store.get_database()
            return jsonify({'configured':bool(saved),'user':saved['user'] if saved else os.environ.get('PGUSER',''),
                            'dbname':saved['dbname'] if saved else os.environ.get('PGDATABASE','')})
        if not request.is_json: return jsonify({'error':'请求格式无效。'}),400
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict): raise ValueError('请求格式无效。')
        user=payload.get('user'); dbname=payload.get('dbname'); password=payload.get('password','')
        if any(not isinstance(x,str) or not x.strip() or '\x00' in x for x in (user,dbname)): raise ValueError('请填写数据库用户名和名称。')
        if not isinstance(password,str): raise ValueError('密码格式无效。')
        if not password:
            saved=credential_store.get_database()
            if not saved or saved['user']!=user.strip(): raise ValueError('请为该数据库用户名输入密码。')
            password=saved['password']
        if not password.strip() or '\x00' in password: raise ValueError('请填写有效的数据库密码。')
        if len(user)>63 or len(dbname)>63 or len(password)>512: raise ValueError('数据库用户名、名称或密码过长。')
        import psycopg
        try:
            with psycopg.connect(host='127.0.0.1',port=5432,dbname=dbname.strip(),user=user.strip(),password=password,connect_timeout=5) as c:
                c.execute('SELECT 1')
        except psycopg.Error as exc:
            raise ValueError('连接验证失败，请核对数据库用户名、密码和名称。') from exc
        credential_store.save_database(user,dbname,password)
        return jsonify({'ok':True,'message':'数据库连接信息已保存，下次启动生效。'})
    except (ValueError,RuntimeError) as exc: return jsonify({'error':str(exc)}),400

@app.route('/api/assistant/key',methods=['GET','POST','DELETE'])
def assistant_key():
    try:
        if request.method=='GET': return jsonify({'configured':bool(credential_store.get_assistant_key())})
        if not request.is_json: return jsonify({'error':'请求格式无效。'}),400
        if request.method=='POST':
            data=request.get_json(silent=True)
            if not isinstance(data,dict): raise ValueError('请求格式无效。')
            credential_store.save_assistant_key(data.get('key'))
            return jsonify({'ok':True,'message':'密钥已保存，可以开始聊天。'})
        credential_store.delete_assistant_key()
        return jsonify({'ok':True,'message':'密钥已删除。'})
    except (ValueError,RuntimeError) as exc: return jsonify({'error':str(exc)}),400

@app.post('/api/assistant/chat')
def assistant_chat():
    try:
        data=request.get_json(silent=True)
        if not request.is_json or not isinstance(data,dict): raise ValueError('请求格式无效。')
        key=credential_store.get_assistant_key()
        if not key: return jsonify({'error':'请先在机器人设置中保存 DeepSeek API 密钥。'}),400
        model=validate_model(data.get('model',DEFAULT_MODEL))
        reply=complete_chat(key,data.get('messages'),data.get('report_context',''),model=model)
        return jsonify({'reply':reply})
    except (ValueError,RuntimeError) as exc: return jsonify({'error':str(exc)}),400

@app.post('/api/assistant/query-chat')
def assistant_query_chat():
    try:
        data=request.get_json(silent=True)
        if not request.is_json or not isinstance(data,dict): raise ValueError('请求格式无效。')
        key=credential_store.get_assistant_key()
        if not key: raise ValueError('请先在机器人设置中保存 DeepSeek API 密钥。')
        model=validate_model(data.get('model',DEFAULT_MODEL))
        messages=data.get('messages')
        if not isinstance(messages,list) or not 1<=len(messages)<=12 or any(not isinstance(m,dict) or m.get('role') not in ('user','assistant') or not isinstance(m.get('content'),str) or not 1<=len(m['content'].strip())<=5000 for m in messages) or messages[-1].get('role')!='user' or sum(len(m['content']) for m in messages)>24000:
            raise ValueError('对话内容无效或过长，请重新输入。')
        if analysis_planner.should_plan(messages):
            plan=analysis_planner.create_plan(key,messages,model)
            if not plan:
                return jsonify({'reply':'暂时无法可靠确定比较条件，请说明黑点解决率、地市和两个统计月份。','local_query':True})
            try:result=analysis_planner.execute(plan,connect,source_reader=wren_daily_bridge.read_snapshot if os.environ.get('ZHIHUI_DATABASE')=='postgres' else None)
            except ValueError as exc:result={'reply':str(exc),'available':False}
            result.pop('available',None)
            return jsonify({**result,'local_query':True})
        if ranking_planner.should_plan(messages):
            plan=ranking_planner.create_plan(key,messages,model)
            if not plan:return jsonify({'reply':'请说明排名方向、数量和统计月份，例如“2026年10月黑点解决率倒数前三”。','local_query':True})
            try:result=ranking_planner.execute(plan,connect,source_reader=wren_daily_bridge.read_snapshot if os.environ.get('ZHIHUI_DATABASE')=='postgres' else None)
            except ValueError as exc:result={'reply':str(exc),'available':False}
            result.pop('available',None)
            return jsonify({**result,'local_query':True})
        ranking=highest_resolution_plan(messages[-1]['content'])
        if ranking:
            if 'error' in ranking:return jsonify({'reply':ranking['error'],'local_query':True})
            result=highest_resolution(connect,ranking['month'],source_reader=wren_daily_bridge.read_snapshot if os.environ.get('ZHIHUI_DATABASE')=='postgres' else None)
            result.pop('available',None)
            return jsonify({**result,'local_query':True})
        comparison=network_query.comparison_plan(messages[-1]['content'])
        if comparison:
            if 'error' in comparison:return jsonify({'reply':comparison['error'],'local_query':True})
            result=network_query.compare(connect,comparison,source_reader=wren_daily_bridge.read_rows if os.environ.get('ZHIHUI_DATABASE')=='postgres' else None)
            result.pop('available',None)
            return jsonify({**result,'local_query':True})
        overview_plan=network_query.overview_plan(messages)
        if overview_plan:
            if 'error' in overview_plan: return jsonify({'reply':overview_plan['error'],'local_query':True})
            result=network_query.overview(connect,overview_plan['day'],source_reader=wren_daily_bridge.read_rows if os.environ.get('ZHIHUI_DATABASE')=='postgres' else None)
            if result.pop('available',False):
                try:
                    result['reply']=summarize_query(key,messages[-1]['content'],result,model=model)
                    date_match=re.search(r'\b\d{4}-\d{2}-\d{2}\b',result.get('evidence',''))
                    if date_match:result['reply']+=f'\n统计日期：{date_match.group(0)}。'
                    result['summary_kind']='ai'
                except ValueError:
                    result['summary_notice']='AI 总结暂不可用，已显示本地汇总结果。'
                result['reply']+='\n'+result.pop('coverage')
            return jsonify({**result,'local_query':True})
        network_plan=network_query.local_plan(messages[-1]['content']) or query_context.resolve_network_followup(messages)
        if network_plan:
            if 'error' in network_plan: return jsonify({'reply':network_plan['error'],'local_query':True})
            if not query_context.validate_network_plan(network_plan): return jsonify({'reply':'查询条件不完整，请确认日期、地市和指标。','local_query':True})
            try: result=network_query.query(connect,network_plan['arguments'],source_reader=wren_daily_bridge.read_rows if os.environ.get('ZHIHUI_DATABASE')=='postgres' else None)
            except ValueError as exc: result={'reply':str(exc),'available':False}
            if result.pop('available',False):
                original=result['reply']
                try:
                    summary=summarize_query(key,messages[-1]['content'],result,model=model)
                    date_match=re.search(r'\b\d{4}-\d{2}-\d{2}\b',original)
                    result['reply']=summary+(f'\n统计日期：{date_match.group(0)}。' if date_match else '')
                    result['evidence']=original
                    result['summary_kind']='ai'
                except ValueError: result['summary_notice']='AI 总结暂不可用，已显示本地统计结果。'
            return jsonify({**result,'local_query':True})
        network_question=messages[-1]['content']
        if re.search(r'日报|网络运行|RedCap|3CC|5G[-－]?A|4G|5G|VoNR|VoLTE|EPSFB',network_question,re.I) and re.search(r'多少|几个|几处|数量|数值|统计|数据|指标|情况如何|怎么样|用户数|话务量|成功率|接通率|掉线率|分流比|占比',network_question) and not re.search(r'黑点|挂起|确认纳入|质检|怎么算|怎么计算|口径|什么意思|区别|定义|是什么|原理',network_question):
            return jsonify({'reply':'该日报指标暂未接入，或指标名称不明确。请说明单日日期、全省或地市及具体指标，例如“2026年10月21日合肥5G数据流量”。','local_query':True})
        explicit_metric=None
        if isinstance(messages,list) and messages and isinstance(messages[-1],dict):
            question=messages[-1].get('content')
            if isinstance(question,str) and re.search(r'黑点量|黑点数量|黑点数(?:有)?多少',question) and not re.search(r'汇聚|平台|纳入|入库|挂起|解决|合格|投诉',question):
                return jsonify({'reply':'你想查询平台汇聚黑点量，还是已确认纳入的黑点数量？两者统计范围不同。','local_query':True})
            explicit_metric=identify_explicit_metric(question)
            if explicit_metric=='多个指标':
                return jsonify({'reply':'这句话包含多个统计指标，请先指定其中一个查询，以便准确核对口径。','local_query':True})
            if isinstance(question,str) and (explicit_metric or re.search(r'黑点|解决率|质检合格|确认纳入|挂起',question)) and re.search(r'对比|比较|相比|环比|同比|上月|上个月|排名|第几|最多|最少|最高|最低|原因|类别',question) and not re.search(r'怎么算|怎么计算|口径|什么意思|区别|定义',question):
                return jsonify({'reply':'目前仅支持单月的地市指标和挂起库数量查询；跨月对比、排名、原因或类别查询暂未实现。','local_query':True})
            if isinstance(question,str) and re.search(r'全球通|投资|成本|投诉压降|投诉压降率|实时未解决|4G投诉|5G投诉|已归档',question) and not re.search(r'怎么算|怎么计算|口径|什么意思|区别|定义',question):
                return jsonify({'reply':'该指标的查询工具暂未接入，我不会用其他指标替代。','local_query':True})
        local_fallback=False;fallback_reason=''
        try:
            if re.search(r'申请挂起|黑点解决情况|挂起库情况',messages[-1]['content']):
                plan=local_query_plan(messages) or {'reply':'请说明要查询的月份和范围，例如“2026年10月全省黑点解决情况”。'}
            else: plan=plan_query(key,data.get('messages'),model=model)
        except ValueError as exc:
            reason=str(exc)
            if not any(marker in reason for marker in ('无法连接 DeepSeek','DeepSeek 响应超时','DeepSeek 服务暂时无法处理请求','请求过于频繁','DeepSeek 返回服务错误')): raise
            plan=local_query_plan(messages)
            if plan is None: raise
            local_fallback=True;fallback_reason=reason
        if explicit_metric and isinstance(question,str) and not re.search(r'怎么算|怎么计算|口径|什么意思|区别|定义',question):
            if 'tool' not in plan or not isinstance(plan.get('arguments'),dict):
                return jsonify({'reply':'已识别查询指标，但还不能确定统计月份和范围。请说明年份、月份及地市或全省。','local_query':True})
            args=plan['arguments']
            named=[city for city in CITIES if city in question]
            if len(named)==1: args['city']=named[0]
            elif re.search(r'各地市|全部地市|各市',question): args['city']='全部地市'
            elif '全省' in question: args['city']='全省'
            dates=re.findall(r'(?<!\d)(20\d{2})\s*(?:年|[-/])\s*(1[0-2]|0?[1-9])\s*月?',question)
            if len(dates)==1: args['month']=f'{dates[0][0]}-{int(dates[0][1]):02d}'
            else:
                months=re.findall(r'(?<!\d)(1[0-2]|0?[1-9])\s*月',question)
                if len(months)==1 and isinstance(args.get('month'),str) and re.fullmatch(r'\d{4}-\d{2}',args['month']):
                    args['month']=f'{args["month"][:4]}-{int(months[0]):02d}'
            plan={'tool':'query_city_metrics','arguments':{'month':args.get('month'),'city':args.get('city'),'metric':explicit_metric}}
        if plan.get('tool')=='query_network_daily':
            return jsonify({'reply':'暂时无法确定日报查询指标或范围。请说明单日日期、地市和具体指标，例如“2026年10月21日合肥5G数据流量”。','local_query':True})
        if 'tool' in plan:
            try: result=query_statistics(connect,plan['tool'],plan['arguments'],structured=True,source_reader=wren_daily_bridge.read_snapshot if os.environ.get('ZHIHUI_DATABASE')=='postgres' else None,suspension_reader=selected_suspension)
            except ValueError as exc: result={'reply':str(exc)}
            if local_fallback:
                result['summary_notice']=fallback_reason+' 本次已使用本地规则查询和生成回答。'
                result.pop('available',None)
            elif result.pop('available',False):
                original=result['reply']
                try:
                    summary=summarize_query(key,messages[-1]['content'],result,model=model)
                    date_match=re.search(r'\b\d{4}-\d{2}-\d{2}\b',original)
                    result['reply']=summary+(f'\n统计日期：{date_match.group(0)}。' if date_match else '')
                    result['evidence']=original
                    result['summary_kind']='ai'
                except ValueError:
                    result['summary_notice']='AI 总结暂不可用，已显示本地统计结果。'
            return jsonify({**result,'local_query':True})
        return jsonify({'reply':plan['reply'],'local_query':False})
    except (ValueError,RuntimeError) as exc: return jsonify({'error':str(exc)}),400

@app.post('/api/generate')
def generate():
    try:
        period=request.form.get('period',''); date.fromisoformat(period)
        kind=request.form.get('kind')
        if kind not in ('weekly','monthly'): raise ValueError('请选择生成周报或月报。')
        current=request.files.get('current'); legacy=request.files.get('legacy')
        if not current or not current.filename: raise ValueError('请先选择 2026 年黑点工单进展表。')
        if kind=='monthly' and (not legacy or not legacy.filename): raise ValueError('生成月报需要上传历史黑点工单进展表。')
        if not current.filename.lower().endswith('.xlsx') or (kind=='monthly' and not legacy.filename.lower().endswith('.xlsx')): raise ValueError('请上传 .xlsx 文件。')
        data=analyze(current.stream,legacy.stream if kind=='monthly' else None)
        with connect() as c: row=c.execute('SELECT period,data FROM reports WHERE period < ? ORDER BY period DESC LIMIT 1',(period,)).fetchone()
        previous=None; previous_period=None
        if request.form.get('previous_included','').strip() or request.form.get('previous_qualified','').strip():
            if not request.form.get('previous_included','').isdigit() or not request.form.get('previous_qualified','').isdigit(): raise ValueError('请完整填写两个非负的上周基准数值。')
            previous={'included':int(request.form['previous_included']),'qualified':int(request.form['previous_qualified'])}; previous_period='手动填写'
        elif row and (date.fromisoformat(period)-date.fromisoformat(row[0])).days==7:
            previous_period=row[0]; d=json.loads(row[1]); previous={'included':d['total']['included'],'qualified':d['total']['qualified']}
        notes={k:request.form.get(k,'').strip() for k in ['global','suspended','monthly','legacy']}
        weekly,monthly=reports(data,period,previous,notes)
        encoded=json.dumps(compact_snapshot(data),ensure_ascii=False); encoded_notes='{}'
        with connect() as c:
            existing=c.execute('SELECT data,weekly,monthly,monthly_data,notes FROM reports WHERE period=?',(period,)).fetchone()
            if existing:
                old_data,old_weekly,old_monthly,old_monthly_data,old_notes=existing
                old_text=old_weekly if kind=='weekly' else old_monthly
                if old_text:
                    revision=hashlib.sha256(old_text.encode('utf-8')).hexdigest()
                    requested=request.form.get('overwrite_revision','')
                    if requested!=revision:
                        code='report_changed' if requested else 'report_exists'
                        return jsonify({'error':'该日期已有保存的报告，请确认后再重新生成。' if not requested else '报告在确认后发生变化，请重新核对。','code':code,'revision':revision}),409
                if kind=='weekly': values=(encoded,old_notes,weekly,old_monthly,old_monthly_data,period)
                else: values=(old_data if old_weekly else encoded,old_notes,old_weekly,monthly,encoded,period)
                updated=c.execute("UPDATE reports SET data=?,notes=?,weekly=?,monthly=?,monthly_data=? WHERE period=? AND data=? AND weekly=? AND monthly=? AND COALESCE(monthly_data,'')=? AND notes=?",values+(old_data,old_weekly,old_monthly,old_monthly_data or '',old_notes))
                if updated.rowcount!=1:return jsonify({'error':'报告在操作期间发生变化，请刷新后重新核对。','code':'report_changed'}),409
            else:
                c.execute('INSERT INTO reports (period,data,notes,weekly,monthly,monthly_data) VALUES (?,?,?,?,?,?)',(period,encoded,encoded_notes,weekly if kind=='weekly' else '',monthly if kind=='monthly' else '',encoded if kind=='monthly' else None))
            generated_at=datetime.now().astimezone().isoformat(timespec='seconds')
            c.execute(f'UPDATE reports SET {kind}_generated_at=?, {kind}_updated_at=? WHERE period=?',(generated_at,generated_at,period))
        day=date.fromisoformat(period); last=date(day.year+int(day.month==12), day.month%12+1, 1)-timedelta(days=1); last_friday=last-timedelta(days=(last.weekday()-4)%7)
        warnings=[]
        if kind=='weekly' and previous is None: warnings.append('没有上周基准，本周新增和本周解决尚未计算；可补录后重新生成。')
        if kind=='monthly' and day != last_friday: warnings.append(f'{day:%Y年%m月}最后一个周五是 {last_friday}；当前版本用于月报时请核对。')
        warnings.append('报告中的文字说明需人工补充并审核。')
        return jsonify({'data':data,'weekly':weekly if kind=='weekly' else '', 'monthly':monthly if kind=='monthly' else '', 'kind':kind,'previous_period':previous_period,'warnings':warnings})
    except (ValueError,TypeError) as exc: return jsonify({'error':str(exc) or '日期格式不正确，请选择有效日期。'}),400

@app.post('/api/report/<period>/supplement-statistics')
def supplement_statistics(period):
    try:
        date.fromisoformat(period)
        upload=request.files.get('current')
        if not upload or not upload.filename or not upload.filename.lower().endswith('.xlsx'):
            raise ValueError('请选择当期原始 .xlsx 工单表。')
        with connect() as c:
            row=c.execute('SELECT data,weekly FROM reports WHERE period=?',(period,)).fetchone()
        if not row or not row[1]: raise ValueError('该日期没有已保存的周报，请先生成周报。')
        try: old=json.loads(row[0])
        except (ValueError,TypeError) as exc: raise ValueError('历史快照格式异常，无法安全补充。') from exc
        calculated=compact_snapshot(analyze(upload.stream))
        merged=supplement_snapshot(old,calculated)
        encoded=json.dumps(merged,ensure_ascii=False)
        with connect() as c:
            updated=c.execute('UPDATE reports SET data=? WHERE period=? AND data=?',(encoded,period,row[0]))
            if updated.rowcount!=1: raise ValueError('历史统计在操作期间发生变化，请刷新后重试。')
        return jsonify({'ok':True,'message':'已补充该期周报缺失的统计，报告文字未改变。'})
    except (ValueError,TypeError) as exc: return jsonify({'error':str(exc) or '日期格式无效。'}),400

@app.get('/api/report/<period>')
def get_report(period):
    kind=request.args.get('kind','weekly')
    if kind not in ('weekly','monthly'): return jsonify({'error':'报告类型无效。'}),400
    with connect() as c: row=c.execute(f'SELECT data,weekly,monthly,monthly_data,{kind}_generated_at,{kind}_updated_at FROM reports WHERE period=?',(period,)).fetchone()
    if not row: return jsonify({'error':'找不到该期报告。'}),404
    data,weekly,monthly,monthly_data,generated_at,updated_at=row
    if not (weekly if kind=='weekly' else monthly): return jsonify({'error':'该期没有此类型报告。'}),404
    return jsonify({'data':json.loads(data if kind=='weekly' else monthly_data or data),'weekly':weekly if kind=='weekly' else '', 'monthly':monthly if kind=='monthly' else '', 'kind':kind,'generated_at':generated_at,'updated_at':updated_at,'warnings':['历史报告按保存时的数据展示。']})

@app.post('/api/report/<period>/save')
def save_report(period):
    payload=request.get_json(silent=True) or {}
    kind=payload.get('kind'); text=payload.get('text')
    if kind not in ('weekly','monthly'): return jsonify({'error':'报告类型无效。'}),400
    if not isinstance(text,str) or not text.strip(): return jsonify({'error':'报告文字不能为空。'}),400
    if len(text)>100000: return jsonify({'error':'报告文字过长。'}),400
    saved_at=datetime.now().astimezone().isoformat(timespec='seconds')
    with connect() as c:
        cur=c.execute(f'UPDATE reports SET {kind}=?,{kind}_updated_at=? WHERE period=? AND {kind} != ?', (text,saved_at,period,''))
        if cur.rowcount==0: return jsonify({'error':'该期报告不存在，请先生成。'}),404
    return jsonify({'ok':True,'updated_at':saved_at})

@app.post('/api/export/<period>')
def export(period):
    with connect() as c: row=c.execute('SELECT COALESCE(monthly_data,data),monthly FROM reports WHERE period=?',(period,)).fetchone()
    if not row or not row[1]: return jsonify({'error':'该期月报尚未生成。'}),404
    report=request.form.get('monthly',row[1]); return send_file(export_monthly(json.loads(row[0]),report,period),as_attachment=True,download_name=f'重点投诉区域月报-{period}.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.post('/api/report/<period>/email')
def email_report(period):
    try:
        date.fromisoformat(period)
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict): raise ValueError('邮件请求格式无效。')
        kind=payload.get('kind'); body=payload.get('body'); attach=payload.get('attach',False)
        if kind not in ('weekly','monthly') or not isinstance(body,str) or not isinstance(attach,bool): raise ValueError('报告类型或邮件内容无效。')
        if attach and kind!='monthly': raise ValueError('只有月报可以附带月报 Excel。')
        with connect() as c: row=c.execute('SELECT COALESCE(monthly_data,data),weekly,monthly FROM reports WHERE period=?',(period,)).fetchone()
        if not row or not row[1 if kind=='weekly' else 2]: return jsonify({'error':'该期报告尚未生成。'}),404
        attachment=(export_monthly(json.loads(row[0]),body,period).getvalue(),f'重点投诉区域月报-{period}.xlsx') if attach else None
        fields=[payload.get(k,'') for k in ('sender','recipient','auth_code','subject')]
        if not all(isinstance(field,str) for field in fields): raise ValueError('邮件字段格式无效。')
        if not fields[2]:
            fields[2]=credential_store.get_for_sender(fields[0]) or ''
            if not fields[2]: raise ValueError('没有该发件邮箱已保存的授权码，请输入或先保存授权码。')
        send_report(*fields,body,attachment)
        return jsonify({'ok':True,'message':'QQ 邮箱服务器已接受邮件，请在发件箱核对。'})
    except (ValueError,TypeError,RuntimeError) as exc:
        return jsonify({'error':str(exc) or '邮件信息无效。'}),400

if __name__=='__main__': app.run(host='127.0.0.1',port=5088,debug=False)
