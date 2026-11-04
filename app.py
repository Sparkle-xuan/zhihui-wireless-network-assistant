import json
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file
sys.path.insert(0,str(Path(__file__).parent / '.deps'))
from core import analyze, reports, export_monthly, CITIES
from mailing import send_report
from assistant_service import complete as complete_chat
from assistant_service import plan_query, summarize_query, validate_model, DEFAULT_MODEL
from smart_query import query as query_statistics, identify_explicit_metric, local_query_plan
import credential_store

app=Flask(__name__,instance_relative_config=True)
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
    if request.path in ('/api/mail/credential','/api/database/credential') or request.path.startswith('/api/assistant/') or request.path.endswith(('/email','/supplement-statistics')):
        allowed={'127.0.0.1:5088','localhost:5088'}
        if app.testing: allowed.update({'localhost','127.0.0.1'})
        origin=request.headers.get('Origin')
        if request.host not in allowed or (origin and origin != f'http://{request.host}'):
            return jsonify({'error':'仅允许本机智徽页面访问此设置。'}),403

@app.after_request
def prevent_credential_response_caching(response):
    if request.path in ('/api/mail/credential','/api/database/credential') or request.path.startswith('/api/assistant/'): response.headers['Cache-Control']='no-store'
    return response

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
            if isinstance(question,str) and re.search(r'申请挂起|全球通|投资|成本|投诉压降|投诉压降率|实时未解决|4G投诉|5G投诉|已归档',question) and not re.search(r'怎么算|怎么计算|口径|什么意思|区别|定义',question):
                return jsonify({'reply':'该指标的查询工具暂未接入，我不会用其他指标替代。','local_query':True})
        local_fallback=False;fallback_reason=''
        try: plan=plan_query(key,data.get('messages'),model=model)
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
        if 'tool' in plan:
            try: result=query_statistics(connect,plan['tool'],plan['arguments'],structured=True)
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
                if kind=='weekly': values=(encoded,old_notes,weekly,old_monthly,old_monthly_data,period)
                else: values=(old_data if old_weekly else encoded,old_notes,old_weekly,monthly,encoded,period)
                c.execute('UPDATE reports SET data=?,notes=?,weekly=?,monthly=?,monthly_data=? WHERE period=?',values)
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
