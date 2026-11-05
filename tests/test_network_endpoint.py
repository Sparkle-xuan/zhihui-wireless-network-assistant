import io, sqlite3, unittest
from contextlib import contextmanager
from unittest.mock import patch
import app

class NetworkImportEndpointTests(unittest.TestCase):
    def test_local_import_and_origin_guard(self):
        db=sqlite3.connect(':memory:')
        @contextmanager
        def connect():
            with db: yield db
        with patch.object(app, 'connect', connect):
            app.app.testing=True
            client=app.app.test_client()
            report='全省无线网络运行日报（2026年10月21日）\n测试正文'.encode()
            denied=client.post('/api/network/history/import',headers={'Origin':'http://evil.invalid'},data={'reports':(io.BytesIO(report),'r.txt')})
            self.assertEqual(denied.status_code,403)
            ok=client.post('/api/network/history/import',data={'reports':(io.BytesIO(report),'r.txt')})
            self.assertEqual(ok.status_code,200)
            self.assertEqual(ok.json['report_dates'],['2026-10-21'])
            self.assertNotIn('测试正文',ok.get_data(as_text=True))
        db.close()

if __name__=='__main__': unittest.main()
