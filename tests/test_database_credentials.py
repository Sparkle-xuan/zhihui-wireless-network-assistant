import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'.deps'))
import app
import credential_store
import launch
import database
import psycopg

class DBTests(unittest.TestCase):
    def setUp(self): self.old_testing=app.app.testing;app.app.testing=True
    def tearDown(self): app.app.testing=self.old_testing

    def test_storage_separates_database_and_qq_credentials(self):
        saved={}
        with patch('credential_store.win32cred.CredWrite',side_effect=lambda item,flags:saved.update(item)):
            credential_store.save_database('test_user','test_db','not-a-real-password')
        self.assertEqual(saved['TargetName'],credential_store.DATABASE_TARGET)
        self.assertNotEqual(saved['TargetName'],credential_store.TARGET)
        with patch('credential_store.win32cred.CredRead',return_value=saved):
            self.assertEqual(credential_store.get_database(),{'user':'test_user','dbname':'test_db','password':'not-a-real-password'})

    def test_launch_saved_credentials_no_prompt(self):
        saved={'user':'test_user','dbname':'test_db','password':'not-a-real-password'}
        result={'already_migrated':True,'existing':0,'found':0,'copied':0}
        out=io.StringIO()
        with patch('credential_store.get_database',return_value=saved),patch('database.initialize_postgres',return_value=result),patch('subprocess.call',return_value=0),patch('builtins.input',side_effect=AssertionError('unexpected prompt')),contextlib.redirect_stdout(out):
            self.assertEqual(launch.main(),0)
        self.assertNotIn(saved['password'],out.getvalue())

    def test_settings_validate_before_save_and_never_return_password(self):
        class FakeConnection:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def execute(self,*args): pass
        saved={'user':'test_user','dbname':'test_db','password':'not-a-real-password'}
        client=app.app.test_client()
        with patch('credential_store.get_database',return_value=saved):
            response=client.get('/api/database/credential')
            self.assertEqual(response.json,{'configured':True,'user':'test_user','dbname':'test_db'})
            self.assertNotIn(saved['password'],response.get_data(as_text=True))
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            with patch('credential_store.save_database') as save,patch('psycopg.connect',return_value=FakeConnection()):
                response=client.post('/api/database/credential',json={'user':'test_user','dbname':'test_db','password':''})
                self.assertEqual(response.status_code,200)
                save.assert_called_once_with('test_user','test_db','not-a-real-password')
                self.assertNotIn(saved['password'],response.get_data(as_text=True))
            with patch('credential_store.save_database') as save:
                response=client.post('/api/database/credential',json={'user':'other_user','dbname':'test_db','password':''})
                self.assertEqual(response.status_code,400);save.assert_not_called()
                response=client.post('/api/database/credential',json={'user':'test_user','dbname':'test_db','password':'wrong'},headers={'Origin':'https://example.com'})
                self.assertEqual(response.status_code,403);save.assert_not_called()
            with patch('credential_store.save_database') as save,patch('psycopg.connect',side_effect=psycopg.OperationalError('failed')):
                response=client.post('/api/database/credential',json={'user':'test_user','dbname':'test_db','password':'wrong'})
                self.assertEqual(response.status_code,400);save.assert_not_called()

if __name__=='__main__': unittest.main()
