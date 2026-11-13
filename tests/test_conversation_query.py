import unittest
from unittest.mock import patch
import app as service
import conversation_query as cq
from core import CITIES


def m(*questions):return [{'role':'user','content':q} for q in questions]

class ConversationQueryTests(unittest.TestCase):
    def setUp(self):
        self.old_testing=service.app.testing;service.app.testing=True;self.client=service.app.test_client()
        self.current={'kind':'weekly','period':'2026-10-30','total':31,'city_note':'','cities':[{'name':c,'value':3 if i<3 else 1} for i,c in enumerate(CITIES)]}
        self.old={'kind':'manual','period':None,'total':22,'city_note':'仅记录部分地市','cities':[{'name':'合肥','value':4},{'name':'宣城','value':2}]}
    def tearDown(self):service.app.testing=self.old_testing
    def test_suspension_multi_turn_context_and_topic_reset(self):
        self.assertEqual(cq.suspension_plan(m('2026年10月合肥挂起多少','宣城呢')),{'action':'lookup','month':'2026-10','city':'宣城'})
        self.assertEqual(cq.suspension_plan(m('2026年10月合肥挂起多少','宣城呢','和上个月比呢')),{'action':'compare','month':'2026-10','other_month':'2026-09','city':'宣城'})
        self.assertIsNone(cq.suspension_plan(m('2026年10月合肥挂起多少','聊聊天','宣城呢')))
        self.assertIsNone(cq.suspension_plan(m('2026年10月合肥挂起多少','5G流量呢')))
    def test_explicit_baseline_does_not_replace_current_month(self):
        expected={'action':'compare','month':'2026-10','other_month':'2026-09','city':'合肥'}
        self.assertEqual(cq.suspension_plan(m('2026年10月合肥挂起多少','和9月比呢')),expected)
        self.assertEqual(cq.suspension_plan(m('2026年10月合肥挂起与9月相比')),expected)
        self.assertIn('error',cq.suspension_plan(m('2026年10月合肥挂起多少','和10月比呢')))

    def test_selected_version_and_missing_city(self):
        plan=cq.suspension_plan(m('2026年10月合肥挂起多少','宣城呢','和上个月比呢'))
        reader=lambda month:self.current if month=='2026-10' else self.old
        result=cq.execute_suspension(plan,reader)
        self.assertIn('减少1处',result['reply']);self.assertIn('未提供',result['evidence'])
        plan['city']='安庆';self.assertIn('未提供',cq.execute_suspension(plan,reader)['reply'])
        plan['city']='全省';self.assertIn('增加9处',cq.execute_suspension(plan,reader)['reply'])
    def test_ranking_ties_and_partial_refusal(self):
        plan=cq.suspension_plan(m('2026年10月各地市挂起数量最多的前两名'))
        result=cq.execute_suspension(plan,lambda month:self.current)
        self.assertEqual(len(result['table']['rows']),3);self.assertIn('并列',result['evidence'])
        self.assertIn('不完整',cq.execute_suspension(plan,lambda month:self.old)['reply'])
    def test_no_implicit_zero_or_period(self):
        self.assertIn('未提供',cq.execute_suspension({'action':'lookup','month':'2026-09','city':'安庆'},lambda _:self.old)['reply'])
        self.assertIn('没有已保存',cq.execute_suspension({'action':'lookup','month':'2026-09','city':'全省'},lambda _:None)['reply'])
    def test_network_explicit_and_followup_dates(self):
        p=cq.daily_comparison_plan(m('2026年10月21日全省5G流量与10月20日相比怎么样'))
        self.assertEqual((p['day'],p['base_day'],p['city']),('2026-10-21','2026-10-20','全省'))
        p=cq.daily_comparison_plan(m('2026年10月21日合肥5G流量是多少','和10月20日比呢'))
        self.assertEqual((p['day'],p['base_day'],p['city']),('2026-10-21','2026-10-20','合肥'))
        self.assertIsNone(cq.daily_comparison_plan(m('2026年10月21日合肥5G流量是多少','聊聊天','和10月20日比呢')))
        self.assertIn('error',cq.daily_comparison_plan(m('2026年10月21日合肥和宣城5G流量与10月20日相比怎么样')))
    def test_network_comparison_uses_two_actual_values(self):
        def sample(connect,args,**kwargs):
            value={'2026-10-21':'10','2026-10-20':'8'}[args['day']]
            return {'available':True,'stat':{'value':value,'unit':'TB'},'reply':args['day']+' 数据'}
        with patch('network_query.query',side_effect=sample):
            plan=cq.daily_comparison_plan(m('2026年10月21日全省5G流量与10月20日相比怎么样'))
            result=__import__('network_query').compare(None,plan)
        self.assertIn('增长2.00TB',result['reply']);self.assertIn('2026-10-20',result['evidence'])
    def test_network_comparison_missing_day_never_invents_zero(self):
        def sample(connect,args,**kwargs):
            return {'available':False,'reply':'没有保存数据'} if args['day']=='2026-10-20' else {'available':True,'stat':{'value':'10','unit':'TB'},'reply':'2026-10-21 数据'}
        with patch('network_query.query',side_effect=sample):
            plan=cq.daily_comparison_plan(m('2026年10月21日全省5G流量与10月20日相比怎么样'))
            result=__import__('network_query').compare(None,plan)
        self.assertFalse(result['available']);self.assertIn('没有保存数据',result['reply'])

    def test_endpoint_does_not_call_llm_for_suspension(self):
        with patch('credential_store.get_assistant_key',return_value='fake'),patch('app.selected_suspension',side_effect=lambda x:self.current if x=='2026-10' else self.old),patch('app.plan_query') as planner:
            messages=m('2026年10月合肥挂起多少','宣城呢','和上个月比呢')
            response=self.client.post('/api/assistant/query-chat',json={'messages':messages})
            self.assertEqual(response.status_code,200);self.assertIn('减少1处',response.json['reply']);planner.assert_not_called()

if __name__=='__main__':unittest.main()
