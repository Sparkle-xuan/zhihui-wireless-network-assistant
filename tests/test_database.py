import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'.deps'))
import database
import app

class FakePostgres:
    """Exercise migration control flow without accessing a real user database."""
    def __init__(self,path): self.db=sqlite3.connect(path)
    def __enter__(self): return self
    def __exit__(self,t,v,b):
        if t: self.db.rollback()
        else: self.db.commit()
        self.db.close()
    def execute(self,query,params=()):
        if not isinstance(query,str): query=query.as_string(None)
        return self.db.execute(query.replace('%s','?'),params)

class DatabaseTests(unittest.TestCase):
    def test_create_missing_database_when_connection_raises_operational_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as tmp:
            target=Path(tmp)/'target.sqlite3'
            class Admin:
                def __init__(self): self.created=[]
                def __enter__(self): return self
                def __exit__(self,*args): pass
                def execute(self,query,params=()):
                    if isinstance(query,str) and query.startswith('SELECT'):
                        class Empty:
                            def fetchone(self): return None
                        return Empty()
                    self.created.append(query.as_string(None)); return None
            admin=Admin(); attempts=[]
            def connect(**kwargs):
                attempts.append(kwargs['dbname'])
                if kwargs['dbname']=='postgres': return admin
                if attempts.count('zhihui')==1: raise database.psycopg.OperationalError('connection failed')
                return FakePostgres(target)
            with patch('database.psycopg.connect',side_effect=connect):
                result=database.initialize_postgres(host='127.0.0.1',port='5432',user='test',password='test',dbname='zhihui',sqlite_path=Path(tmp)/'missing.sqlite3')
            self.assertEqual(attempts,['zhihui','postgres','zhihui'])
            self.assertEqual(admin.created,['CREATE DATABASE "zhihui"'])
            self.assertEqual(result['copied'],0)

    def test_authentication_failure_never_creates_database(self):
        with patch('database.psycopg.connect',side_effect=database.psycopg.OperationalError('failed')) as connect:
            with self.assertRaisesRegex(ValueError,'用户名和密码'):
                database.initialize_postgres(host='127.0.0.1',port='5432',user='test',password='test',dbname='zhihui')
        self.assertEqual(connect.call_count,2)

    def test_existing_database_is_not_recreated(self):
        class Admin:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def execute(self,query,params=()):
                class Exists:
                    def fetchone(self): return (1,)
                return Exists()
        def connect(**kwargs):
            if kwargs['dbname']=='postgres': return Admin()
            raise database.psycopg.OperationalError('denied')
        with patch('database.psycopg.connect',side_effect=connect):
            with self.assertRaisesRegex(ValueError,'已存在'):
                database.initialize_postgres(host='127.0.0.1',port='5432',user='test',password='test',dbname='zhihui')

    def test_copy_is_repeatable_and_does_not_overwrite_conflicts(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as tmp:
            source=Path(tmp)/'old.sqlite3'; target=Path(tmp)/'target.sqlite3'
            with closing(sqlite3.connect(source)) as c, c:
                c.execute('CREATE TABLE reports(period TEXT PRIMARY KEY,data TEXT,notes TEXT,weekly TEXT,monthly TEXT)')
                c.execute('INSERT INTO reports VALUES (?,?,?,?,?)',('2026-10-30','{}','{}','示例周报','示例月报'))
            with patch('database.psycopg.connect',side_effect=lambda **kw: FakePostgres(target)):
                opts=dict(host='127.0.0.1',port='5432',user='test',password='test',dbname='test',sqlite_path=source)
                self.assertEqual(database.initialize_postgres(**opts),{'found':1,'copied':1,'existing':0,'already_migrated':False})
                with closing(sqlite3.connect(target)) as c, c: c.execute("UPDATE reports SET weekly='不同的历史报告'")
                self.assertTrue(database.initialize_postgres(**opts)['already_migrated'])
                with closing(sqlite3.connect(target)) as c, c: c.execute('DELETE FROM zhihui_meta')
                with self.assertRaisesRegex(ValueError,'不会覆盖|未覆盖'):
                    database.initialize_postgres(**opts)
            with closing(sqlite3.connect(source)) as c: self.assertEqual(c.execute('SELECT weekly FROM reports').fetchone()[0],'示例周报')
            with closing(sqlite3.connect(target)) as c: self.assertEqual(c.execute('SELECT weekly FROM reports').fetchone()[0],'不同的历史报告')

    def test_postgres_backend_converts_placeholders(self):
        class FakeRaw:
            def __init__(self): self.calls=[]; self.closed=False
            def execute(self,q,p): self.calls.append((q,p)); return self
            def fetchone(self): return (1,)
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def close(self): self.closed=True
        raw=FakeRaw()
        with patch.dict(os.environ,{'ZHIHUI_DATABASE':'postgres','PGUSER':'test','PGDATABASE':'test'}), patch('psycopg.connect',return_value=raw):
            with app.connect() as c: c.execute('SELECT * FROM reports WHERE period=?',('2026-10-30',))
        self.assertEqual(raw.calls,[('SELECT * FROM reports WHERE period=%s',('2026-10-30',))])
        self.assertTrue(raw.closed)

    def test_status_uses_selected_database(self):
        class FakeRaw:
            def execute(self,q,p): self.query=q; return self
            def fetchone(self): return (1,)
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def close(self): pass
        with patch.dict(os.environ,{'ZHIHUI_DATABASE':'postgres'}), patch('psycopg.connect',return_value=FakeRaw()):
            response=app.app.test_client().get('/api/status')
        self.assertEqual(response.json,{'database':'postgres','connected':True})

if __name__=='__main__': unittest.main()
