import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app as service

class ReportReplacementTests(unittest.TestCase):
    def setUp(self):
        self.old_db=service.DB;self.old_testing=service.app.testing;service.app.testing=True
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);service.DB=Path(self.temp.name)/'data.sqlite3';self.client=service.app.test_client()
        with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',('2026-07-24',json.dumps({'total':{'included':1,'qualified':1}}),'{}','用户修改内容',''))
    def tearDown(self):service.DB=self.old_db;service.app.testing=self.old_testing;self.temp.cleanup()
    def generate(self,revision=None):
        data={'period':'2026-07-24','kind':'weekly','current':(io.BytesIO(b'test'),'test.xlsx')}
        if revision is not None:data['overwrite_revision']=revision
        with patch.object(service,'analyze',return_value={'total':{}}),patch.object(service,'reports',return_value=('新报告',None)),patch.object(service,'compact_snapshot',return_value={'total':{'included':2,'qualified':1}}):
            return self.client.post('/api/generate',data=data,content_type='multipart/form-data')
    def text(self):
        with service.connect() as c:return c.execute('SELECT weekly FROM reports WHERE period=?',('2026-07-24',)).fetchone()[0]
    def test_overwrite_requires_current_revision(self):
        first=self.generate();self.assertEqual(first.status_code,409);self.assertEqual(self.text(),'用户修改内容')
        revision=first.get_json()['revision']
        with service.connect() as c:c.execute('UPDATE reports SET weekly=? WHERE period=?',('后来修改','2026-07-24'))
        stale=self.generate(revision);self.assertEqual(stale.status_code,409);self.assertEqual(self.text(),'后来修改')
        result=self.generate(stale.get_json()['revision']);self.assertEqual(result.status_code,200);self.assertEqual(self.text(),'新报告')
