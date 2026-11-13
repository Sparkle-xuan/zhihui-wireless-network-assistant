import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as service
from core import CITIES
from analysis_report import create_report


class AnalysisReportTests(unittest.TestCase):
    def setUp(self):
        self.old_db,self.old_testing=service.DB,service.app.testing
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        service.DB=Path(self.tmp.name)/'report.sqlite3';service.app.testing=True
        self.client=service.app.test_client()
        rows=[{'city':city,'included':10,'qualified':i if i<4 else 8} for i,city in enumerate(CITIES)]
        rows[-1]={'city':CITIES[-1],'included':0,'qualified':0}
        self.snapshot={'cities':rows,'total':{'included':150,'qualified':100}}
        with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',('2026-10-30',json.dumps(self.snapshot),'{}','REPORT_BODY_SENTINEL',''))

    def tearDown(self):
        service.DB,service.app.testing=self.old_db,self.old_testing
        self.tmp.cleanup()

    def test_workflow_ranks_and_does_not_invent_missing_months(self):
        result=create_report('2026-10',service.connect)
        facts=result['facts']
        self.assertEqual(facts['lowest'],list(CITIES[:3]))
        self.assertIsNone(facts['cities'][-1]['rate'])
        self.assertFalse(facts['trend'][0]['available'])
        self.assertIsNone(facts['trend'][1]['rate'])
        self.assertEqual(facts['period'],'2026-10-30')

    def test_ties_included_and_invalid_numbers_rejected(self):
        self.snapshot['cities'][3]['qualified']=2
        with service.connect() as c:c.execute('UPDATE reports SET data=? WHERE period=?',(json.dumps(self.snapshot),'2026-10-30'))
        self.assertEqual(len(create_report('2026-10',service.connect)['facts']['lowest']),4)
        self.snapshot['cities'][0]['qualified']=11
        with service.connect() as c:c.execute('UPDATE reports SET data=? WHERE period=?',(json.dumps(self.snapshot),'2026-10-30'))
        with self.assertRaises(ValueError):create_report('2026-10',service.connect)

    def test_model_receives_only_summary_and_unverified_numbers_fall_back(self):
        calls=[]
        def model(key,messages,**kwargs):
            calls.append(messages);return '建议立即整改99处。'
        result=create_report('2026-10',service.connect,key='fake',model='deepseek-flash',complete_fn=model)
        self.assertIn('AI 建议暂不可用',result['advice_notice'])
        self.assertNotIn('99',result['advice'])
        self.assertNotIn('REPORT_BODY_SENTINEL',str(calls))

    def test_chinese_numeric_claims_are_rejected(self):
        for advice in ['还有三处尚未完成。','解决率为百分之五十。','超过半数地市需要推进。']:
            with self.subTest(advice=advice):
                result=create_report('2026-10',service.connect,key='fake',complete_fn=lambda *args,**kwargs:advice)
                self.assertIn('AI 建议暂不可用',result['advice_notice'])
        result=create_report('2026-10',service.connect,key='fake',complete_fn=lambda *args,**kwargs:'建议进一步统筹推进并结合实际落实。')
        self.assertEqual(result['advice'],'建议进一步统筹推进并结合实际落实。')

    def test_endpoint_returns_self_contained_html_and_missing_error(self):
        with patch('credential_store.get_assistant_key',return_value=None):
            response=self.client.post('/api/analysis-report',json={'month':'2026-10'})
            self.assertEqual(response.status_code,200)
            html=response.json['html']
            self.assertIn('各地市统计明细',html);self.assertIn('暂无数据',html)
            self.assertNotIn('<script',html)
            missing=self.client.post('/api/analysis-report',json={'month':'2098-10'})
            self.assertEqual(missing.status_code,400)
            self.assertIn('缺少',missing.json['error'])

    def test_readiness_discloses_missing_previous_and_source_dates(self):
        result=self.client.get('/api/analysis-report/readiness?month=2026-10').json
        self.assertTrue(result['can_generate']);self.assertFalse(result['can_compare'])
        self.assertEqual(result['current']['period'],'2026-10-30')
        self.assertFalse(result['previous']['available'])
        with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',('2026-09-25',json.dumps(self.snapshot),'{}','周报',''))
        result=self.client.get('/api/analysis-report/readiness?month=2026-10').json
        self.assertTrue(result['can_compare']);self.assertEqual(result['previous']['period'],'2026-09-25')
        self.assertEqual(self.client.get('/api/analysis-report/readiness?month=2026-13').status_code,400)

    def test_readiness_requires_at_least_one_comparable_denominator(self):
        for row in self.snapshot['cities']:row['included']=row['qualified']=0
        with service.connect() as c:
            c.execute('UPDATE reports SET data=? WHERE period=?',(json.dumps(self.snapshot),'2026-10-30'))
            c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',('2026-09-25',json.dumps(self.snapshot),'{}','周报',''))
        result=self.client.get('/api/analysis-report/readiness?month=2026-10').json
        self.assertTrue(result['can_generate']);self.assertFalse(result['can_compare'])
        self.assertIn('分母',result['comparison_message'])


if __name__=='__main__':unittest.main()
