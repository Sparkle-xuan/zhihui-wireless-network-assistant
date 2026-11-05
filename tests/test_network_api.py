import json, sqlite3, unittest
from contextlib import contextmanager
from unittest.mock import patch
import app, network_daily

class NetworkApiTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');network_daily.schema(self.db)
        @contextmanager
        def connect():
            with self.db: yield self.db
        self.patcher=patch.object(app,'connect',connect);self.patcher.start();app.app.testing=True;self.client=app.app.test_client()
    def tearDown(self):self.patcher.stop();self.db.close()
    def test_generate_save_and_get_preserve_original(self):
        c=self.db;c.execute('INSERT INTO network_daily_reports VALUES (?,?,?,?,?)',('2026-10-21','x','历史日报','s','pending_review'))
        c.execute('INSERT INTO network_daily_indicators VALUES (?,?,?,?,?,?)',('s','2026-10-21','安徽省','h',json.dumps({'nr_upoct':'12'}),'unreviewed'))
        r=self.client.post('/api/network/day/2026-10-21/generate');self.assertEqual(r.status_code,200);self.assertIn('12TB',r.json['content'])
        r=self.client.post('/api/network/day/2026-10-21/save',json={'content':r.json['content']});self.assertEqual(r.status_code,200)
        r=self.client.get('/api/network/day/2026-10-21');self.assertEqual(r.json['original'],'历史日报');self.assertIn('12TB',r.json['draft'])
    @patch('app.send_report')
    def test_send_uses_reviewed_body_and_saved_credential(self,send):
        with patch('credential_store.get_for_sender',return_value='fake'):
            r=self.client.post('/api/network/day/2026-10-21/email',json={'sender':'a@example.com','recipient':'b@example.com','subject':'日报','body':'核对内容','auth_code':''})
        self.assertEqual(r.status_code,200);self.assertEqual(send.call_args.args[-1],'核对内容')
    def test_external_origin_rejected(self):
        r=self.client.get('/api/network/dates',headers={'Origin':'http://bad.example'});self.assertEqual(r.status_code,403)

if __name__=='__main__':unittest.main()
