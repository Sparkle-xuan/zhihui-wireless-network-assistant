"""Bridge to local Wren worker. Password stays in process environment."""
import json,os,subprocess,sys
from datetime import date
from pathlib import Path

def _read(day,kind,width):
    if not isinstance(day,str) or len(day)!=10 or date.fromisoformat(day).isoformat()!=day:raise ValueError('日报日期无效。')
    python=Path(os.environ.get('ZHIHUI_WREN_PYTHON',r'E:\zhihui-wren\venv\Scripts\python.exe'))
    worker=Path(__file__).with_name('wren_daily_worker.py')
    if not python.is_file():raise ValueError('Wren 环境不存在，请检查 E 盘 Wren 安装。')
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0) if sys.platform=='win32' else 0
    try:
        result=subprocess.run([str(python),str(worker)],input=json.dumps({'day':day,'kind':kind}),capture_output=True,text=True,encoding='utf-8',timeout=30,creationflags=flags,check=False)
        if result.returncode:raise ValueError('Wren 本机查询失败，请检查数据库连接和 Wren 配置。')
        rows=json.loads(result.stdout)
        if not isinstance(rows,list) or any(not isinstance(x,list) or len(x)!=width for x in rows):raise ValueError()
        return rows
    except (subprocess.TimeoutExpired,OSError,ValueError,TypeError):
        raise ValueError('Wren 本机查询失败，请检查数据库连接和 Wren 配置。') from None


def read_rows(day):
    return _read(day,'network',2)

def read_snapshot(day):
    rows=_read(day,'blackspot',4)
    if len(rows)>1:raise ValueError('Wren 返回重复报告，需核对统计数据。')
    return rows[0] if rows else None
