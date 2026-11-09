import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
import app as service
import suspension
import suspension_reasons
from core import CITIES


def workbook(rows):
    book=Workbook();sheet=book.active;sheet.title='挂起'
    sheet.append(['工单Id','地市','不纳入原因','问题形成原因','waitingClassifyName'])
    for row in rows:sheet.append(row)
    result=io.BytesIO();book.save(result);result.seek(0);return result


ROWS=[
    ['1','合肥','无项目，业主阻挠','室分覆盖不足','无项目'],
    ['2','合肥','等待进一步确认','基站故障','纠纷协调类工单'],
    ['3','安庆','', '容量不足', '低价值'],
]


class ReasonAggregationTests(unittest.TestCase):
    def test_specific_topics_and_same_record_cross_field_evidence(self):
        rows=[['1','合肥','无项目，拟采用7+9室分','玻璃造成覆盖受限','无项目'],
              ['2','合肥','无项目，室分建设','玻璃相关覆盖','无项目'],
              ['3','宣城','7+9室分','覆盖问题','低价值']]
        result=suspension.workbook_summary(workbook(rows))['suspended']['reason_analysis']
        self.assertIn('涉及7+9', {x['name'] for x in result['counts']})
        self.assertIn('涉及玻璃', {x['name'] for x in result['issue']['counts']})
        self.assertIn({'city':'合肥','issue':'涉及玻璃','suspension':'涉及7+9','value':1},result['issue_suspension_cities'])
        self.assertNotIn('玻璃造成覆盖受限',json.dumps(result,ensure_ascii=False))

    def test_separate_fields_overlap_and_no_raw_data(self):
        result=suspension.workbook_summary(workbook(ROWS))['suspended']['reason_analysis']
        self.assertEqual((result['matched'],result['unmatched'],result['blank'],result['multi']),(1,1,1,1))
        self.assertEqual({x['name']:x['value'] for x in result['counts']},{'涉及无项目':1,'涉及协调或阻挠':1})
        issue=result['issue'];self.assertTrue(issue['available'])
        self.assertEqual({x['name']:x['value'] for x in issue['counts']},{'涉及覆盖':1,'涉及容量':1,'涉及故障':1,'涉及室分':1,'涉及站址或基站':1})
        self.assertIn({'city':'合肥','reason':'涉及覆盖','value':1},issue['cities'])
        self.assertIn({'category':'无项目','reason':'涉及覆盖','value':1},issue['categories'])
        encoded=json.dumps(result,ensure_ascii=False)
        self.assertNotIn('业主阻挠',encoded);self.assertNotIn('室分覆盖不足',encoded)
        self.assertIsNotNone(suspension_reasons.validate(result,3,CITIES))

    def test_validation_rejects_arbitrary_raw_reason(self):
        result=suspension.workbook_summary(workbook(ROWS))['suspended']['reason_analysis']
        result['counts'][0]['name']='这里是工单原文'
        self.assertIsNone(suspension_reasons.validate(result,3,CITIES))


class ReasonSupplementTests(unittest.TestCase):
    def setUp(self):
        self.old_db=service.DB;self.old_testing=service.app.testing;service.app.testing=True
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent);service.DB=Path(self.temp.name)/'data.sqlite3';self.client=service.app.test_client()
        group=suspension.workbook_summary(workbook(ROWS))['suspended'];group.pop('reason_analysis')
        with service.connect() as c:
            c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',('2026-10-30',json.dumps({'suspended':group},ensure_ascii=False),'{}','用户编辑过的报告',''))

    def tearDown(self):service.DB=self.old_db;service.app.testing=self.old_testing;self.temp.cleanup()

    def upload(self,rows=ROWS,name='2026-1030.xlsx'):
        return self.client.post('/api/suspension/reasons/import',data={'month':'2026-10','file':(workbook(rows),name)},content_type='multipart/form-data')

    @patch('app.credential_store.get_assistant_key',return_value='fake')
    @patch('app.diagnose_suspension',return_value='建议结合原因核实后制定推进计划。')
    def test_supplement_enriches_selected_snapshot_without_changing_report(self,diagnose,key):
        response=self.upload();self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        data=self.client.get('/api/suspension/month/2026-10').get_json()
        self.assertEqual(data['reason_analysis']['total'],3)
        self.assertTrue(data['reason_analysis']['issue']['available'])
        result=self.client.post('/api/suspension/diagnose',json={'month':'2026-10'}).get_json()
        self.assertIn('问题形成原因关键词初筛',str(result['evidence']['facts']))
        self.assertNotIn('室分覆盖不足',str(diagnose.call_args))
        with service.connect() as c:
            summary=c.execute('SELECT summary FROM suspension_reason_summaries').fetchone()[0]
            report=c.execute('SELECT weekly FROM reports WHERE period=?',('2026-10-30',)).fetchone()[0]
        self.assertNotIn('业主阻挠',summary);self.assertEqual(report,'用户编辑过的报告')

    def test_different_date_or_city_rejected(self):
        self.assertEqual(self.upload(name='2026-1023.xlsx').status_code,400)
        other=[*ROWS,['4','宣城','无项目','覆盖不足','无项目']]
        self.assertEqual(self.upload(other).status_code,400)
        self.assertNotIn('reason_analysis',self.client.get('/api/suspension/month/2026-10').get_json())

    @patch('app.credential_store.get_assistant_key',return_value='fake')
    @patch('app.diagnose_suspension',return_value='建议核实。')
    def test_supplement_invalidates_old_diagnosis(self,diagnose,key):
        self.assertEqual(self.client.post('/api/suspension/diagnose',json={'month':'2026-10'}).status_code,200)
        self.assertIsNotNone(self.client.get('/api/suspension/month/2026-10').get_json()['diagnosis'])
        self.assertEqual(self.upload().status_code,200)
        self.assertIsNone(self.client.get('/api/suspension/month/2026-10').get_json()['diagnosis'])
        self.assertEqual(self.client.post('/api/suspension/diagnose',json={'month':'2026-10'}).status_code,200)
        self.assertEqual(diagnose.call_count,2)

    @patch('app.credential_store.get_assistant_key',return_value='fake')
    @patch('app.diagnose_suspension',side_effect=ValueError('模型建议未通过数据核验'))
    def test_local_fallback_is_labelled_and_saved(self,diagnose,key):
        self.assertEqual(self.upload().status_code,200)
        result=self.client.post('/api/suspension/diagnose',json={'month':'2026-10'}).get_json()
        self.assertEqual(result['model'],'local')
        self.assertIn('合肥',result['reply'])
        self.assertIn('纳入项目',result['reply'])
        self.assertNotIn('业主阻挠',result['reply'])
        saved=self.client.get('/api/suspension/month/2026-10').get_json()['diagnosis']
        self.assertEqual(saved['model'],'local');self.assertEqual(saved['reply'],result['reply'])

    @patch('app.credential_store.get_assistant_key',return_value='fake')
    @patch('app.diagnose_suspension',side_effect=ValueError('模型建议未通过数据核验'))
    def test_local_fallback_does_not_invent_partial_manual_causes(self,diagnose,key):
        self.client.post('/api/suspension/manual',json={'month':'2026-07','total':5,'cities':{'合肥':3},'categories':{}})
        result=self.client.post('/api/suspension/diagnose',json={'month':'2026-07','source':'manual'}).get_json()
        self.assertEqual(result['model'],'local');self.assertIn('不完整',result['reply'])
        self.assertNotIn('玻璃',result['reply'])


if __name__=='__main__':unittest.main()
