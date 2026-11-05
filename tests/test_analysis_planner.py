import json,unittest
from unittest.mock import Mock,patch
from datetime import date
import analysis_planner as planner

class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.messages=[{'role':'user','content':'2026年10月哪个地市黑点解决率最高，与9月相比如何'}]
        self.plan={'operation':'highest_compare','month':'2026-10','other_month':'2026-09','city':'全部地市','clarification':''}
    def test_plan_must_be_grounded_in_question(self):
        self.assertIsNotNone(planner.validate_plan(self.plan,self.messages))
        self.assertIsNone(planner.validate_plan({**self.plan,'other_month':'2026-08'},self.messages))
        self.assertIsNone(planner.validate_plan({**self.plan,'month':'2026-09','other_month':'2026-10'},self.messages))
        self.assertIsNone(planner.validate_plan({**self.plan,'city':'合肥'},self.messages))
        self.assertIsNone(planner.validate_plan({**self.plan,'operation':'drop'},self.messages))
    def test_followup_keeps_user_dates(self):
        messages=[{'role':'user','content':'2026年10月合肥黑点解决率如何'},{'role':'assistant','content':'敏感信息123'}, {'role':'user','content':'和上个月比怎么样'}]
        self.assertTrue(planner.should_plan(messages))
        self.assertEqual(planner._possible_months(messages,date(2026,11,5)),{'2026-10','2026-09'})
        valid={'operation':'compare','month':'2026-10','other_month':'2026-09','city':'合肥','clarification':''}
        self.assertIsNotNone(planner.validate_plan(valid,messages))
        self.assertIsNone(planner.validate_plan({**valid,'city':'芜湖'},messages))
    def test_stale_unrelated_context_does_not_supply_month(self):
        messages=[{'role':'user','content':'2026年9月合肥解决率'}, {'role':'user','content':'今天有什么新闻'}, {'role':'user','content':'2026年10月合肥黑点解决率和9月比'}]
        self.assertEqual(planner._possible_months(messages,date(2026,11,5)),{'2026-10','2026-09'})
        messages[-1]['content']='2026年10月合肥黑点解决率和上月比'
        self.assertEqual(planner._possible_months(messages,date(2026,11,5)),{'2026-10','2026-09'})
        messages[-1]['content']='2026年10月合肥黑点解决率比较'
        self.assertEqual(planner._possible_months(messages,date(2026,11,5)),{'2026-10'})

    @patch('analysis_planner.requests.post')
    def test_planner_transmits_only_user_questions(self,post):
        calls=[{'function':{'name':'plan_blackspot_analysis','arguments':json.dumps(self.plan,ensure_ascii=False)}}]
        post.return_value=Mock(status_code=200,json=lambda:{'choices':[{'message':{'tool_calls':calls}}]})
        messages=[self.messages[0],{'role':'assistant','content':'敏感原始数据123'},{'role':'user','content':'再和9月比'}]
        result=planner.create_plan('fake',messages,'deepseek-flash')
        self.assertEqual(result['operation'],'highest_compare')
        self.assertNotIn('敏感原始数据123',str(post.call_args.kwargs['json']))
    @patch('analysis_planner.requests.post')
    def test_malformed_model_output_is_not_executed(self,post):
        post.return_value=Mock(status_code=200,json=lambda:{'choices':[{'message':{'tool_calls':[{'function':{'name':'other','arguments':'{}'}}]}}]})
        self.assertIsNone(planner.create_plan('fake',self.messages,'deepseek-flash'))

if __name__=='__main__':unittest.main()
