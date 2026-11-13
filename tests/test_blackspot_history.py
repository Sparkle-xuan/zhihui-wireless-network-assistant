import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import app as service
import blackspot_history
import query_router
from analysis_report import create_report
from core import CITIES
from smart_query import query


class HistoricSnapshotsTests(unittest.TestCase):
    def setUp(self):
        self.old_db,self.old_testing=service.DB,service.app.testing
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        service.DB=Path(self.tmp.name)/'history.sqlite3';service.app.testing=True
        self.data={'cities':[{'city':c,'included':10,'qualified':5} for c in CITIES],'total':{'included':160,'qualified':80}}
    def tearDown(self):
        service.DB,service.app.testing=self.old_db,self.old_testing
        self.tmp.cleanup()
    def report(self,period):
        with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',(period,json.dumps(self.data),'{}','weekly',''))
    def test_historical_date_is_preserved_in_report_and_comparison(self):
        self.report('2026-10-30')
        blackspot_history.save(service.connect,'2026-09-24',self.data)
        result=create_report('2026-10',service.connect)
        self.assertEqual(result['facts']['trend'][1]['period'],'2026-09-24')
        self.assertTrue(result['facts']['previous_available'])
        self.assertEqual(result['facts']['cities'][0]['change'],0)
        with patch('credential_store.get_assistant_key',return_value=None):
            html=service.app.test_client().post('/api/analysis-report',json={'month':'2026-10'}).json['html']
        self.assertIn('2026-09-24',html)
        self.assertIn('历史工单表汇总',html)
        plan=query_router.city_comparison_plan([{'role':'user','content':'2026年10月各地市黑点解决率和上月相比'}])
        compared=query_router.execute_city_comparison(plan,service.connect)
        self.assertIn('2026-09-24',compared['evidence'])
        self.assertNotIn('2026-09-25',compared['evidence'])
    def test_official_month_end_report_wins_over_import(self):
        blackspot_history.save(service.connect,'2026-09-24',self.data)
        self.report('2026-09-25')
        result=query(service.connect,'query_city_metrics',{'month':'2026-09','city':'全部地市','metric':'解决率'},structured=True)
        self.assertEqual(result['source_info']['period'],'2026-09-25')
        self.assertEqual(result['source_info']['kind'],'周报')
    def test_existing_legacy_import_is_migrated_without_overwrite(self):
        with service.connect() as c:
            c.execute('CREATE TABLE blackspot_history_imports (month TEXT PRIMARY KEY, source_date TEXT NOT NULL, snapshot TEXT NOT NULL)')
            c.execute('INSERT INTO blackspot_history_imports VALUES (?,?,?)',('2026-09','2026-09-24',json.dumps(self.data)))
        self.assertEqual(blackspot_history.versions(service.connect,'2026-09')['selected'],'2026-09-24')
        self.assertTrue(blackspot_history.save(service.connect,'2026-09-25',self.data))
        self.assertEqual(blackspot_history.versions(service.connect,'2026-09')['selected'],'2026-09-24')
        with service.connect() as c:
            self.assertEqual(c.execute('SELECT source_date FROM blackspot_history_imports WHERE month=?',('2026-09',)).fetchone()[0],'2026-09-24')
    def test_identical_import_safe_conflict_does_not_overwrite(self):
        self.assertTrue(blackspot_history.save(service.connect,'2026-09-24',self.data))
        self.assertFalse(blackspot_history.save(service.connect,'2026-09-24',self.data))
        self.assertTrue(blackspot_history.save(service.connect,'2026-09-25',self.data))
        result=query(service.connect,'query_city_metrics',{'month':'2026-09','city':'全部地市','metric':'解决率'},structured=True)
        self.assertEqual(result['source_info']['period'],'2026-09-24')
        client=service.app.test_client()
        result=client.get('/api/blackspot/history/versions?month=2026-09').json
        self.assertEqual(result['dates'],['2026-09-25','2026-09-24'])
        self.assertEqual(result['selected'],'2026-09-24')
        self.assertEqual(client.post('/api/blackspot/history/versions',json={'month':'2026-09','source_date':'2026-09-25'}).status_code,200)
        result=query(service.connect,'query_city_metrics',{'month':'2026-09','city':'全部地市','metric':'解决率'},structured=True)
        self.assertEqual(result['source_info']['period'],'2026-09-25')
        self.assertEqual(client.post('/api/blackspot/history/versions',json={'month':'2026-09','source_date':'2026-08-28'}).status_code,400)
        self.assertEqual(client.post('/api/blackspot/history/versions',json=['invalid']).status_code,400)
        changed={**self.data,'total':{'included':1,'qualified':0}}
        with self.assertRaises(ValueError):blackspot_history.save(service.connect,'2026-09-25',changed)
    def test_missing_and_failure_are_different(self):
        self.report('2026-10-30')
        def broken(_):raise ValueError('Wren 连接失败')
        with self.assertRaisesRegex(ValueError,'Wren'):create_report('2026-10',service.connect,source_reader=broken)
    def test_import_endpoint_requires_matching_source_date(self):
        with patch('app.analyze',return_value=self.data):
            client=service.app.test_client()
            good=client.post('/api/blackspot/history/import',data={'source_date':'2026-09-24','file':(BytesIO(b'data'),'2026-0924.xlsx')},content_type='multipart/form-data')
            self.assertEqual(good.status_code,200)
            bad=client.post('/api/blackspot/history/import',data={'source_date':'2026-09-25','file':(BytesIO(b'data'),'2026-0924.xlsx')},content_type='multipart/form-data')
            self.assertEqual(bad.status_code,400)


if __name__=='__main__':unittest.main()
