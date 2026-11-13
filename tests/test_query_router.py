import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as service
import query_router
from core import CITIES


class QueryRouterTests(unittest.TestCase):
    def setUp(self):
        self.old_db,self.old_testing=service.DB,service.app.testing
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        service.DB=Path(self.tmp.name)/'data.sqlite3';service.app.testing=True
        self.client=service.app.test_client()
        for period,values in [('2026-10-30',[1,2,3,3]+[9]*12),('2026-09-25',[2,4,4,0]+[8]*12)]:
            rows=[{'city':city,'included':0 if period=='2026-09-25' and i==3 else 10,'qualified':value} for i,(city,value) in enumerate(zip(CITIES,values))]
            snap={'snapshot_version':2,'total':{'included':160,'qualified':100},'cities':rows,'suspended':{'count':0,'cities':[]}}
            with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',(period,json.dumps(snap,ensure_ascii=False),'{}','周报',''))
    def tearDown(self):
        service.DB,service.app.testing=self.old_db,self.old_testing
        self.tmp.cleanup()
    def ask(self,questions):
        messages=[]
        for question in questions:
            if messages:messages.append({'role':'assistant','content':'上一轮已执行统计查询，具体结果不随历史记录再次发送。'})
            messages.append({'role':'user','content':question})
        with patch('credential_store.get_assistant_key',return_value='fake'),patch('app.plan_query') as model:
            response=self.client.post('/api/assistant/query-chat',json={'messages':messages})
            model.assert_not_called()
            self.assertEqual(response.status_code,200)
            return response.get_json()
    def test_rank_then_followup_recomputes_selected_cities_and_ties(self):
        result=self.ask(['2026年10月各地市黑点解决率','倒数前三呢','和9月比呢'])
        self.assertEqual([r[1] for r in result['table']['rows']],list(CITIES[:4]))
        self.assertEqual(result['table']['rows'][0][-1],'-10.00个百分点')
        self.assertEqual(result['table']['rows'][3][-1],'无法比较')
        self.assertIn('并列',result['evidence'])
    def test_compound_lowest_previous_month_and_missing_data(self):
        result=self.ask(['2026年10月哪个地市黑点解决率最低，和上个月比怎么样'])
        self.assertEqual(result['table']['rows'][0][1],CITIES[0]);self.assertIn('2026-09',str(result))
        result=self.ask(['2026年10月黑点解决率倒数前三和8月比怎么样'])
        self.assertIn('对照数据不可用',result['reply']);self.assertNotIn('table',result)
    def test_no_stale_context_inference(self):
        msgs=[{'role':'user','content':'2026年10月各地市黑点解决率'}, {'role':'user','content':'倒数前三'}, {'role':'user','content':'今天天气怎么样'}, {'role':'user','content':'和9月比呢'}]
        self.assertIsNone(query_router.ranked_comparison_plan(msgs))
    def test_all_cities_compare_real_rates_and_missing_denominator(self):
        result=self.ask(['2026年10月各地市黑点解决率和上月相比'])
        self.assertEqual(len(result['table']['rows']),16)
        self.assertEqual(result['table']['rows'][0], [CITIES[0],'10.00%','20.00%','-10.00个百分点'])
        self.assertEqual(result['table']['rows'][3][-1], '无法比较')
        self.assertIn('1个因分母为零无法比较', result['reply'])
    def test_all_cities_compare_missing_month(self):
        result=self.ask(['2026年10月各地市黑点解决率和8月相比'])
        self.assertIn('对照数据不可用',result['reply'])
        self.assertNotIn('table',result)
        msgs=[{'role':'user','content':'2026年10月黑点解决率倒数前三和9月比怎么样，项目进展呢'}]
        self.assertIsNone(query_router.ranked_comparison_plan(msgs))
    def test_reasons_use_selected_summary_and_disclose_qualifications(self):
        current={'period':'2026-10-30','kind':'weekly','reason_analysis':{'counts':[{'name':'涉及无项目','value':4},{'name':'涉及协调或阻挠','value':2}],'cities':[{'city':'合肥','reason':'涉及无项目','value':3}], 'issue':{'available':True,'counts':[{'name':'涉及玻璃','value':2}],'cities':[{'city':'合肥','reason':'涉及玻璃','value':2}]}}}
        with patch('app.selected_suspension',return_value=current):
            a=self.ask(['2026年10月合肥挂起原因是什么'])
            self.assertIn('涉及无项目 3处',a['reply']);self.assertIn('不是已确认',a['evidence']);self.assertIn('2026-10-30',a['evidence'])
            b=self.ask(['2026年10月合肥挂起问题形成原因'])
            self.assertEqual(b['table']['rows'],[['涉及玻璃','2']])
        with patch('app.selected_suspension',return_value={'period':'2026-10-30','kind':'weekly'}):
            self.assertIn('未保存原因',self.ask(['2026年10月合肥挂起原因是什么'])['reply'])
    def test_multiple_cities_clarifies(self):
        self.assertIn('指定一个',self.ask(['2026年10月各地市挂起原因'])['reply'])

if __name__=='__main__':unittest.main()
