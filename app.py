import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file
from core import analyze, reports, export_monthly

app=Flask(__name__,instance_relative_config=True)
app.config['MAX_CONTENT_LENGTH']=30*1024*1024
Path(app.instance_path).mkdir(parents=True,exist_ok=True)
DB=Path(app.instance_path)/'zhihui.sqlite3'

@contextmanager
def connect():
    c=sqlite3.connect(DB)
    try:
        c.execute('CREATE TABLE IF NOT EXISTS reports (period TEXT PRIMARY KEY, data TEXT NOT NULL, notes TEXT NOT NULL, weekly TEXT NOT NULL, monthly TEXT NOT NULL)')
        with c: yield c
    finally: c.close()

@app.get('/')
def index(): return render_template('index.html')

@app.get('/api/history')
def history():
    with connect() as c: rows=c.execute('SELECT period,data FROM reports ORDER BY period DESC').fetchall()
    return jsonify([{'period':p,'included':json.loads(d)['total']['included'],'qualified':json.loads(d)['total']['qualified']} for p,d in rows])

@app.post('/api/generate')
def generate():
    try:
        period=request.form.get('period',''); date.fromisoformat(period)
        current=request.files.get('current'); legacy=request.files.get('legacy')
        if not current or not legacy: raise ValueError('请同时选择 2026 年明细表和历史遗留明细表。')
        if not current.filename.lower().endswith('.xlsx') or not legacy.filename.lower().endswith('.xlsx'): raise ValueError('请上传 .xlsx 文件。')
        data=analyze(current.stream,legacy.stream)
        with connect() as c: row=c.execute('SELECT period,data FROM reports WHERE period < ? ORDER BY period DESC LIMIT 1',(period,)).fetchone()
        previous=None; previous_period=None
        if request.form.get('previous_included','').strip() or request.form.get('previous_qualified','').strip():
            if not request.form.get('previous_included','').isdigit() or not request.form.get('previous_qualified','').isdigit(): raise ValueError('请完整填写两个非负的上周基准数值。')
            previous={'included':int(request.form['previous_included']),'qualified':int(request.form['previous_qualified'])}; previous_period='手动填写'
        elif row and (date.fromisoformat(period)-date.fromisoformat(row[0])).days==7:
            previous_period=row[0]; d=json.loads(row[1]); previous={'included':d['total']['included'],'qualified':d['total']['qualified']}
        notes={k:request.form.get(k,'').strip() for k in ['global','suspended','monthly','legacy']}
        weekly,monthly=reports(data,period,previous,notes)
        with connect() as c: c.execute('INSERT OR REPLACE INTO reports VALUES (?,?,?,?,?)',(period,json.dumps(data,ensure_ascii=False),json.dumps(notes,ensure_ascii=False),weekly,monthly))
        day=date.fromisoformat(period); last=date(day.year+int(day.month==12), day.month%12+1, 1)-timedelta(days=1); last_friday=last-timedelta(days=(last.weekday()-4)%7)
        warnings=[]
        if previous is None: warnings.append('没有上周基准，本周新增和本周解决尚未计算；可补录后重新生成。')
        if day != last_friday: warnings.append(f'{day:%Y年%m月}最后一个周五是 {last_friday}；当前版本用于月报时请核对。')
        warnings.append('月报中的工程及成本优化项目说明、挂起原因等需人工补充并审核。')
        return jsonify({'data':data,'weekly':weekly,'monthly':monthly,'previous_period':previous_period,'warnings':warnings})
    except (ValueError,TypeError) as exc: return jsonify({'error':str(exc) or '日期格式不正确，请选择有效日期。'}),400

@app.get('/api/report/<period>')
def get_report(period):
    with connect() as c: row=c.execute('SELECT data,weekly,monthly FROM reports WHERE period=?',(period,)).fetchone()
    if not row: return jsonify({'error':'找不到该期报告。'}),404
    return jsonify({'data':json.loads(row[0]),'weekly':row[1],'monthly':row[2],'warnings':['历史报告按生成时的数据保存。']})

@app.post('/api/export/<period>')
def export(period):
    with connect() as c: row=c.execute('SELECT data,monthly FROM reports WHERE period=?',(period,)).fetchone()
    if not row: return jsonify({'error':'找不到该期报告。'}),404
    report=request.form.get('monthly',row[1]); return send_file(export_monthly(json.loads(row[0]),report,period),as_attachment=True,download_name=f'重点投诉区域月报-{period}.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

if __name__=='__main__': app.run(host='127.0.0.1',port=5088,debug=False)
