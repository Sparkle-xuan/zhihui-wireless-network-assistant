import unittest
from unittest.mock import Mock,patch
import json
import ranking_planner as r

class RankingPlannerTests(unittest.TestCase):
    def test_user_and_followup(self):
        first={'role':'user','content':'现在10月地市黑点解决率倒数前三'}
        follow={'role':'user','content':'10月倒数前三地市'}
        for messages in ([first],[first,{'role':'assistant','content':'旧回答'},follow]):
            self.assertTrue(r.should_plan(messages));p=r.fallback(messages)
            self.assertEqual(p['direction'],'asc');self.assertEqual(p['limit'],3)
    def test_current_month_replaces_old_comparison_months(self):
        m=[{'role':'user','content':'2099年10月哪个地市黑点解决率最高，和9月相比'}, {'role':'assistant','content':'缺失'}, {'role':'user','content':'2099年10月地市黑点解决率倒数前三'}]
        self.assertEqual(r.rank_months(m),{'2099-10'})
        self.assertEqual(r.fallback(m)['month'],'2099-10')
        m[-1]['content']='10月倒数前三地市'
        self.assertEqual(r.rank_months(m),{'2099-10'})

    def test_bad_model_values_never_execute(self):
        messages=[{'role':'user','content':'2026年10月地市黑点解决率倒数前三'}]
        p={'operation':'rank','month':'2026-10','direction':'asc','limit':3,'metric':'blackspot_resolution_rate'}
        self.assertIsNotNone(r.validate(p,messages))
        for change in ({'direction':'desc'},{'limit':5},{'month':'2026-09'},{'metric':'other'}):
            self.assertIsNone(r.validate({**p,**change},messages))
    def test_other_metric_not_inferred_from_old_context(self):
        m=[{'role':'user','content':'10月黑点解决率'}, {'role':'user','content':'5G流量倒数前三'}]
        self.assertFalse(r.should_plan(m))
    @patch('ranking_planner.requests.post')
    def test_only_user_question_sent(self,post):
        plan={'operation':'rank','month':'2026-10','direction':'asc','limit':3,'metric':'blackspot_resolution_rate'}
        post.return_value=Mock(status_code=200,json=lambda:{'choices':[{'message':{'tool_calls':[{'function':{'name':'plan_city_ranking','arguments':json.dumps(plan)}}]}}]})
        m=[{'role':'user','content':'2026年10月黑点解决率'}, {'role':'assistant','content':'敏感数据987'}, {'role':'user','content':'10月倒数前三地市'}]
        self.assertEqual(r.create_plan('fake',m,'deepseek-flash')['limit'],3)
        self.assertNotIn('敏感数据987',str(post.call_args.kwargs['json']))

if __name__=='__main__':unittest.main()
