"""Start locally with Windows Credential Manager or a one-time prompt."""
import getpass
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'.deps'))

def main():
    try:
        from database import initialize_postgres
        import credential_store
    except ImportError:
        print('缺少 PostgreSQL 驱动。请先按 README 安装 requirements.txt。')
        return 1
    print('智徽 · PostgreSQL 本机启动')
    print('密码存储于当前 Windows 账户的凭据管理器，不写入项目文件。')
    try: saved=credential_store.get_database()
    except RuntimeError as exc:
        print(str(exc)); saved=None
    result=None
    if saved:
        user,dbname,password=saved['user'],saved['dbname'],saved['password']
        print(f'正在使用已保存的数据库配置（用户 {user}，数据库 {dbname}）。')
        try: result=initialize_postgres(host='127.0.0.1',port='5432',user=user,password=password,dbname=dbname)
        except Exception:
            print('已保存的数据库配置连接失败，请重新输入。旧配置暂时保留。')
    if result is None:
        default_user=saved['user'] if saved else 'zhihui_app'
        default_db=saved['dbname'] if saved else 'zhihui'
        user=input(f'PostgreSQL 用户名 [{default_user}]：').strip() or default_user
        dbname=input(f'智徽数据库名称 [{default_db}]：').strip() or default_db
        password=getpass.getpass('PostgreSQL 密码：')
        try:
            result=initialize_postgres(host='127.0.0.1',port='5432',user=user,password=password,dbname=dbname)
        except Exception as exc:
            print('数据库连接或初始化失败：',str(exc))
            print('请确认用户名、密码及创建数据库权限，或联系管理员。SQLite 原数据未删除。')
            return 1
        try:
            credential_store.save_database(user,dbname,password)
            print('数据库连接信息已保存，下次启动会自动连接。')
        except (ValueError,RuntimeError) as exc:
            print('连接成功，但未能保存数据库凭据：',str(exc))
    if result['already_migrated']:
        print('已连接 PostgreSQL，历史数据此前已迁移。')
    else:
        print(f"已连接 PostgreSQL。发现本地旧快照 {result['found']} 条，复制 {result['copied']} 条，相同记录 {result['existing']} 条。")
    if result['existing']: print('已有的相同快照未重复导入。')
    env=os.environ.copy()
    env.update({'ZHIHUI_DATABASE':'postgres','PGHOST':'127.0.0.1','PGPORT':'5432','PGUSER':user,'PGDATABASE':dbname,'PGPASSWORD':password})
    print('正在启动。请打开 http://127.0.0.1:5088/；关闭此窗口会停止服务。',flush=True)
    return subprocess.call([sys.executable,str(ROOT/'app.py')],cwd=ROOT,env=env)

if __name__=='__main__': sys.exit(main())
