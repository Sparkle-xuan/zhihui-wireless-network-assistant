import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as service
import assistant_service
import suspension


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.old_db,self.old_testing=service.DB,service.app.testing
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        service.DB=Path(self.temp.name)/'diagnosis.sqlite3'
        service.app.testing=True
        self.client=service.app.test_client()

    def tearDown(self):
        service.DB,service.app.testing=self.old_db,self.old_testing
        self.temp.cleanup()

    def put_manual(self,month,total,cities,preferred=False):
        response=self.client.post('/api/suspension/manual',json={'month':month,'total':total,'cities':cities,'categories':{},'preferred':preferred})
        self.assertEqual(response.status_code,200)

    @patch('app.diagnose_suspension',return_value='建议核实存量原因，持续跟进闭环。')
    @patch('app.credential_store.get_assistant_key',return_value='test-key')
    def test_selected_version_and_partial_data(self,key,diagnose):
        self.put_manual('2026-06',5,{'合肥':5})
        self.put_manual('2026-07',10,{'合肥':6},True)
        with service.connect() as c:
            c.execute('INSERT INTO suspension_imports (month,source_date,snapshot) VALUES (?,?,?)',('2026-07','2026-07-24',json.dumps({'suspended':{'count':7,'cities':[['合肥',7]],'categories':{'无项目':7}}})))
        response=self.client.post('/api/suspension/diagnose',json={'month':'2026-07','source':'manual','model':'deepseek-flash'})
        self.assertEqual(response.status_code,200)
        evidence=response.get_json()['evidence']
        self.assertIn('挂起 10 处',evidence['facts'][0])
        self.assertIn('增加5 处',evidence['facts'][1])
        self.assertFalse(evidence['cities_complete'])
        self.assertIn('暂不能判断',evidence['facts'][2])
        self.assertNotIn('test-key',response.get_data(as_text=True))
        self.assertNotIn('workorder',str(diagnose.call_args))
        other=self.client.post('/api/suspension/diagnose',json={'month':'2026-07','source':'imported'}).get_json()['evidence']
        self.assertIn('挂起 7 处',other['facts'][0])
        self.assertTrue(other['cities_complete'])

    @patch('app.credential_store.get_assistant_key',return_value='test-key')
    def test_invalid_conditions_are_not_sent_to_model(self,key):
        with patch('app.diagnose_suspension') as diagnose:
            for payload in ({'month':'bad'},{'month':'2026-07','source':'other'},{'month':'2026-07','model':'other'},{'month':'2026-07'}):
                self.assertEqual(self.client.post('/api/suspension/diagnose',json=payload).status_code,400)
            diagnose.assert_not_called()

    def test_estimated_categories_and_no_previous(self):
        data=suspension.summary(json.dumps({'suspended':{'count':3,'cities':[['合肥',3]],'categories':{'无项目':2,'待核实':1}}}),'2026-07-24','imported')
        data['category_estimated']=True
        facts=suspension.diagnostic_facts(data,None,'2026-07')
        self.assertFalse(facts['comparison_available'])
        self.assertTrue(any('关键词初筛' in x for x in facts['facts']))
        self.assertEqual(facts['categories'][1]['name'],'待核实')

    @patch('app.credential_store.get_assistant_key',return_value='test-key')
    @patch('app.diagnose_suspension',side_effect=['首次建议','更新后的建议'])
    def test_cache_auto_restore_and_explicit_refresh(self,diagnose,key):
        self.put_manual('2026-07',7,{'合肥':7})
        payload={'month':'2026-07','source':'manual','model':'deepseek-flash'}
        first=self.client.post('/api/suspension/diagnose',json=payload).get_json()
        self.assertFalse(first['cached']);self.assertEqual(first['reply'],'首次建议')
        self.assertEqual(diagnose.call_count,1)
        with patch('app.credential_store.get_assistant_key',return_value=None):
            self.assertEqual(self.client.post('/api/suspension/diagnose',json=payload).get_json()['reply'],'首次建议')
            saved=self.client.get('/api/suspension/month/2026-07').get_json()['diagnosis']
        self.assertTrue(saved['cached']);self.assertEqual(saved['reply'],'首次建议')
        self.assertEqual(diagnose.call_count,1)
        updated=self.client.post('/api/suspension/diagnose',json={**payload,'force':True}).get_json()
        self.assertFalse(updated['cached']);self.assertEqual(updated['reply'],'更新后的建议')
        self.assertEqual(self.client.get('/api/suspension/month/2026-07').get_json()['diagnosis']['reply'],'更新后的建议')
        self.assertEqual(diagnose.call_count,2)

    @patch('app.credential_store.get_assistant_key',return_value='test-key')
    @patch('app.diagnose_suspension',return_value='建议跟进核实。')
    def test_cache_separates_source_and_invalidates_when_previous_changes(self,diagnose,key):
        self.put_manual('2026-06',3,{'合肥':3})
        self.put_manual('2026-07',7,{'合肥':7},True)
        payload={'month':'2026-07','source':'manual'}
        self.assertEqual(self.client.post('/api/suspension/diagnose',json=payload).status_code,200)
        with service.connect() as c:
            c.execute('INSERT INTO suspension_imports (month,source_date,snapshot) VALUES (?,?,?)',('2026-07','2026-07-24',json.dumps({'suspended':{'count':7,'cities':[['合肥',7]]}})))
        self.assertIsNone(self.client.get('/api/suspension/month/2026-07?source=imported').get_json()['diagnosis'])
        self.assertIsNotNone(self.client.get('/api/suspension/month/2026-07?source=manual').get_json()['diagnosis'])
        with service.connect() as c:
            c.execute('UPDATE suspension_manual SET snapshot=? WHERE month=?',(json.dumps({'suspended':{'count':4,'cities':[['合肥',4]],'partial_cities':True}}),'2026-06'))
        self.assertIsNone(self.client.get('/api/suspension/month/2026-07?source=manual').get_json()['diagnosis'])
        self.assertEqual(self.client.post('/api/suspension/diagnose',json=payload).status_code,200)
        self.assertEqual(diagnose.call_count,2)

    @patch('app.credential_store.get_assistant_key',return_value='test-key')
    def test_failed_refresh_keeps_saved_result(self,key):
        self.put_manual('2026-07',7,{'合肥':7})
        payload={'month':'2026-07','source':'manual'}
        with patch('app.diagnose_suspension',return_value='已有建议'):
            self.assertEqual(self.client.post('/api/suspension/diagnose',json=payload).status_code,200)
        with patch('app.diagnose_suspension',side_effect=ValueError('服务暂不可用')):
            self.assertIsNone(self.client.post('/api/suspension/diagnose',json={**payload,'force':True}).get_json()['reply'])
        self.assertEqual(self.client.get('/api/suspension/month/2026-07').get_json()['diagnosis']['reply'],'已有建议')

    def test_model_advice_checks_unverified_claims(self):
        evidence={'facts':['示例数据']}
        with patch('assistant_service.complete',return_value='建议结合地市反馈核实分类，并持续跟进处理进度。'):
            self.assertIn('建议',assistant_service.diagnose_suspension('key',evidence))
        with patch('assistant_service.complete',return_value='1. 建议复核 5G 覆盖。\n2. 推进地市协调。'):
            self.assertIn('5G',assistant_service.diagnose_suspension('key',evidence))
        with patch('assistant_service.complete',side_effect=['记录有 999 处。','建议先核实归类，再制定推进计划。']) as complete:
            self.assertIn('建议',assistant_service.diagnose_suspension('key',evidence))
            self.assertEqual(complete.call_count,2)
        with patch('assistant_service.complete',return_value='合肥：对涉及7+9的室分方案，评估设备替换并推动纳入项目。'):
            result=assistant_service.diagnose_suspension('key',{'facts':['合肥存在涉及7+9线索']})
            self.assertIn('7+9',result)
        for bad in ('存在 500 处。','合肥情况需要关注。','主要原因是协调问题。','增加五处。','无项目和协调同时出现的记录应核实。','两套字段均指向同一障碍。','建议补充原表并逐单回单。','建议推进玻璃问题整改。'):
            with self.subTest(bad=bad),patch('assistant_service.complete',return_value=bad):
                with self.assertRaises(ValueError):assistant_service.diagnose_suspension('key',evidence)

    def test_city_opportunity_uses_only_same_city_and_record_links(self):
        current={'period':'2026-10-30','kind':'weekly','reason_analysis':{
            'cities':[{'city':'合肥','reason':'涉及7+9','value':3},{'city':'宣城','reason':'涉及无项目','value':7}],
            'issue':{'available':True,'cities':[{'city':'合肥','reason':'涉及玻璃','value':2}]},
            'issue_suspension_cities':[{'city':'合肥','issue':'涉及玻璃','suspension':'涉及7+9','value':1}],
            'city_categories':[{'city':'合肥','category':'无项目','reason':'涉及7+9','value':2}]}}
        result=suspension.city_opportunities(current,'合肥')
        self.assertTrue(result['available']);self.assertIn('设备替换',result['advice'])
        self.assertNotIn('宣城',str(result));self.assertEqual(result['same_record'][0]['value'],1)
        self.assertIn('不能作为已确认原因',result['note'])
        del current['reason_analysis']['issue_suspension_cities'][:]
        result=suspension.city_opportunities(current,'合肥')
        self.assertNotIn('玻璃和7+9的场景',result['advice'])
        self.assertFalse(suspension.city_opportunities({'kind':'manual'},'合肥')['available'])


if __name__=='__main__':unittest.main()
