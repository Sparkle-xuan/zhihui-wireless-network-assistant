"""Initialize a dedicated PostgreSQL database and copy existing report snapshots."""
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent / '.deps'))
import psycopg
from psycopg import sql

FIELDS=('period','data','notes','weekly','monthly','monthly_data','weekly_generated_at','monthly_generated_at','weekly_updated_at','monthly_updated_at')
DB_PATH=Path(__file__).parent/'instance'/'zhihui.sqlite3'

def initialize_postgres(*, host, port, user, password, dbname, sqlite_path=DB_PATH):
    args={'host':host,'port':port,'user':user,'password':password,'connect_timeout':5}
    try:
        connection=psycopg.connect(dbname=dbname,**args)
    except psycopg.OperationalError as first_error:
        # Connection-time failures can arrive as OperationalError even when the
        # requested database does not exist. Verify existence independently;
        # never try to create a database merely because authentication failed.
        try:
            admin=psycopg.connect(dbname='postgres',autocommit=True,**args)
        except psycopg.OperationalError as exc:
            raise ValueError('无法使用该用户名和密码连接 PostgreSQL。请检查用户名、密码，以及该用户是否可以连接 postgres 数据库。') from exc
        with admin:
            exists=admin.execute('SELECT 1 FROM pg_database WHERE datname=%s',(dbname,)).fetchone()
            if exists:
                raise ValueError(f'数据库 {dbname} 已存在，但当前用户无法连接。请检查该数据库的连接权限。') from first_error
            try:
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(dbname)))
            except psycopg.errors.InsufficientPrivilege as exc:
                raise ValueError(f'数据库 {dbname} 尚未创建，当前用户没有创建数据库权限。请在 Navicat 中为该角色启用“可创建数据库”。') from exc
        connection=psycopg.connect(dbname=dbname,**args)
    with connection:
        connection.execute('CREATE TABLE IF NOT EXISTS zhihui_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        connection.execute('''CREATE TABLE IF NOT EXISTS reports (
            period TEXT PRIMARY KEY, data TEXT NOT NULL, notes TEXT NOT NULL,
            weekly TEXT NOT NULL, monthly TEXT NOT NULL, monthly_data TEXT,
            weekly_generated_at TEXT, monthly_generated_at TEXT,
            weekly_updated_at TEXT, monthly_updated_at TEXT)''')
        if connection.execute("SELECT value FROM zhihui_meta WHERE key=%s",('sqlite_migration_v1',)).fetchone():
            return {'found':0,'copied':0,'existing':0,'already_migrated':True}
        old_rows=[]
        if sqlite_path.exists():
            old=sqlite3.connect(f'{sqlite_path.resolve().as_uri()}?mode=ro',uri=True)
            old.row_factory=sqlite3.Row
            try:
                exists=old.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reports'").fetchone()
                if exists:
                    cols={r[1] for r in old.execute('PRAGMA table_info(reports)')}
                    for row in old.execute('SELECT * FROM reports'):
                        record={name:row[name] if name in cols else None for name in FIELDS}
                        if 'monthly_data' not in cols and record['monthly']: record['monthly_data']=record['data']
                        old_rows.append(tuple(record[name] for name in FIELDS))
            finally: old.close()
        columns=sql.SQL(',').join(map(sql.Identifier,FIELDS))
        placeholders=sql.SQL(',').join(sql.Placeholder() for _ in FIELDS)
        insert=sql.SQL('INSERT INTO reports ({}) VALUES ({}) ON CONFLICT (period) DO NOTHING').format(columns,placeholders)
        copied=0; unchanged=0
        for row in old_rows:
            existing=connection.execute(sql.SQL('SELECT {} FROM reports WHERE period=%s').format(columns),(row[0],)).fetchone()
            if existing is None:
                copied+=connection.execute(insert,row).rowcount
            elif tuple(existing)==row:
                unchanged+=1
            else:
                raise ValueError(f'PostgreSQL 中 {row[0]} 的报告与 SQLite 版本不同，已停止迁移，未覆盖任何数据。')
        connection.execute('INSERT INTO zhihui_meta (key,value) VALUES (%s,%s)',('sqlite_migration_v1','complete'))
    return {'found':len(old_rows),'copied':copied,'existing':unchanged,'already_migrated':False}
