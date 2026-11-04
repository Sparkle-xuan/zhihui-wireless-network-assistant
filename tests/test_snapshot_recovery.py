import copy
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import app as service
from core import CITIES, STAGES


def fixture():
    base={'platform':4,'platform_complaints':9,'included':3,'complaints':8,'five':1,
          'suspended':1,'investment':2,'cost':1,'qualified':2,'rate':2/3,'after':2,
          'solved':6,'reduction':.75,'stages':{stage:0 for stage in STAGES}}
    return {'total':dict(base),'cities':[dict(copy.deepcopy(base),city=city) for city in CITIES],
            'qualified_complaints':{'before':8,'after':2,'reduction':.75},
            'archive':{'count':1,'before':3,'after':0,'reduction':1},
            'global':{'count':1,'qualified':1,'rate':1,'opening':0},
            'suspended':{'count':4,'cities':[('合肥',4)],'categories':{'无项目':4}},'legacy':None}


class SnapshotRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.old_db=service.DB; self.old_testing=service.app.testing
        service.DB=Path(self.temp.name)/'snapshot.sqlite3';service.app.testing=True
        self.client=service.app.test_client();self.full=fixture()
        self.old={'total':{k:self.full['total'][k] for k in ('included','qualified','rate','after','solved','reduction')},
                  'cities':[{k:row[k] for k in ('city','included','qualified','rate','after','solved','reduction')} for row in self.full['cities']],
                  'suspended':{'count':4}}
        with service.connect() as c:
            c.execute('INSERT INTO reports (period,data,notes,weekly,monthly,monthly_data) VALUES (?,?,?,?,?,?)',('2026-10-30',json.dumps(self.old),'{}','用户编辑过的周报','用户编辑过的月报','{}'))

    def tearDown(self):
        service.DB=self.old_db;service.app.testing=self.old_testing;self.temp.cleanup()

    def submit(self,data):
        with patch('app.analyze',return_value=data):
            return self.client.post('/api/report/2026-10-30/supplement-statistics',data={'current':(BytesIO(b'fake'),'2026.xlsx')},content_type='multipart/form-data')

    def test_backfill_enables_query_without_overwriting_reports(self):
        response=self.submit(self.full)
        self.assertEqual(response.status_code,200)
        with service.connect() as c: row=c.execute('SELECT data,weekly,monthly,monthly_data FROM reports WHERE period=?',('2026-10-30',)).fetchone()
        stored=json.loads(row[0]);self.assertEqual(row[1:4],('用户编辑过的周报','用户编辑过的月报','{}'))
        self.assertEqual(stored['cities'][0]['platform'],4)
        self.assertEqual(stored['suspended']['cities'],[['合肥',4]])
        self.assertEqual(stored['snapshot_version'],2)

    def test_mismatched_file_does_not_write_anything(self):
        changed=copy.deepcopy(self.full);changed['cities'][0]['included']+=1
        response=self.submit(changed)
        self.assertEqual(response.status_code,400)
        with service.connect() as c: row=c.execute('SELECT data,weekly FROM reports WHERE period=?',('2026-10-30',)).fetchone()
        self.assertEqual(json.loads(row[0]),self.old);self.assertEqual(row[1],'用户编辑过的周报')

    def test_recovery_can_be_repeated_and_preserves_existing_data(self):
        self.assertEqual(self.submit(self.full).status_code,200)
        with service.connect() as c: first=c.execute('SELECT data FROM reports WHERE period=?',('2026-10-30',)).fetchone()[0]
        self.assertEqual(self.submit(self.full).status_code,200)
        with service.connect() as c: second=c.execute('SELECT data FROM reports WHERE period=?',('2026-10-30',)).fetchone()[0]
        self.assertEqual(first,second)

if __name__=='__main__':unittest.main()
