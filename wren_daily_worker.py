"""Local Wren reader: a fixed, validated daily query; no free-form SQL."""
import base64,json,os,sys
from datetime import date
from pathlib import Path

def main():
    from wren.engine import WrenEngine
    request=json.loads(sys.stdin.read(1024))
    day=request.get('day')
    if not isinstance(day,str) or len(day)!=10 or date.fromisoformat(day).isoformat()!=day:raise ValueError('invalid date')
    model=Path(os.environ.get('ZHIHUI_WREN_MODEL',r'E:\zhihui-wren\zhihui-model\target\mdl.json'))
    manifest=base64.b64encode(model.read_bytes()).decode('ascii')
    info={'host':os.environ.get('PGHOST','127.0.0.1'),'port':os.environ.get('PGPORT','5432'),'database':os.environ['PGDATABASE'],'user':os.environ['PGUSER'],'password':os.environ['PGPASSWORD'],'kwargs':{'options':'-c default_transaction_read_only=on -c statement_timeout=5000','connect_timeout':'5'}}
    # SQL and its selected columns are fixed; only a normalized ISO date varies.
    kind=request.get('kind','network')
    if kind=='network':
        sql="SELECT region, metrics_json FROM network_daily_indicators WHERE report_date = '"+day+"'"
        columns=('region','metrics_json')
    elif kind=='blackspot':
        sql="SELECT data, monthly_data, CASE WHEN weekly <> '' THEN 'yes' ELSE '' END AS weekly_present, CASE WHEN monthly <> '' THEN 'yes' ELSE '' END AS monthly_present FROM reports WHERE period = '"+day+"'"
        columns=('data','monthly_data','weekly_present','monthly_present')
    else:raise ValueError('invalid query kind')
    with WrenEngine(manifest,'postgres',info) as engine:
        rows=engine.query(sql,limit=10001).to_pylist()
        if len(rows)>10000:raise ValueError('too many rows')
    print(json.dumps([[row[col] for col in columns] for row in rows],ensure_ascii=True))

if __name__=='__main__':
    try:main()
    except Exception:
        print('Wren 本机查询失败，请检查网络日报数据和连接配置。',file=sys.stderr)
        sys.exit(1)
