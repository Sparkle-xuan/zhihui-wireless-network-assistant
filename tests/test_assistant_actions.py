import unittest
from datetime import date
from unittest.mock import patch
import assistant_actions
import app as service

class AssistantActionsTests(unittest.TestCase):
    def test_navigate_precise_destinations_and_dates(self):
        today=date(2026,11,10)
        cases={
            '打开10月挂起库':{'type':'open_suspension','month':'2026-10'},
            '打开2025年12月挂起库':{'type':'open_suspension','month':'2025-12'},
            '打开2026年11月2日网络运行日报':{'type':'open_network','day':'2026-11-02'},
            '进入话术模拟':{'type':'open_complaint_simulation'},
            '帮我生成10月月报':{'type':'open_reports'},
            '打开2026年10月黑点月报':{'type':'open_reports','day':'2026-10-30','kind':'monthly'},
            '打开2026年10月30日黑点周报':{'type':'open_reports','day':'2026-10-30','kind':'weekly'},
            '生成2026年10月黑点解决率分析报告':{'type':'open_analysis_report','month':'2026-10'},
            '生成2026年10月黑点解决率分析报告并发送邮件':{'type':'open_analysis_report','month':'2026-10'},
            '准备2026年10月地市告警并发送邮件':{'type':'open_city_alerts','month':'2026-10'},
            '打开2026年10月地市告警':{'type':'open_city_alerts','month':'2026-10'},
        }
        for q,expected in cases.items():
            with self.subTest(q=q):self.assertEqual(assistant_actions.plan(q,today)['action'],expected)
    def test_invalid_dates_and_queries_do_not_navigate(self):
        for q in ['打开2026年13月挂起库','打开2026年10月和9月挂起库','打开2026年11月31日网络日报','打开11月1日和11月2日网络日报','打开2026年11月31日黑点月报']:
            with self.subTest(q=q):self.assertNotIn('action',assistant_actions.plan(q,date(2026,11,10)))
        for q in ['10月挂起库有多少','给我10月挂起库有多少','发送月报邮件','删除挂起库']:
            with self.subTest(q=q):self.assertIsNone(assistant_actions.plan(q))
    def test_local_navigation_needs_no_key_and_does_not_call_model(self):
        old=service.app.testing;service.app.testing=True
        try:
            with patch('credential_store.get_assistant_key',return_value=None),patch('app.plan_query') as model:
                response=service.app.test_client().post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'打开2026年10月挂起库'}]})
                self.assertEqual(response.status_code,200);self.assertEqual(response.json['action'],{'type':'open_suspension','month':'2026-10'});model.assert_not_called()
                response=service.app.test_client().post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':'你好'}]})
                self.assertEqual(response.status_code,400)
        finally:service.app.testing=old

    def test_clarified_blackspot_analysis_report_opens_without_model(self):
        messages=[{'role':'user','content':'给我一个10月分析报告'},
                  {'role':'assistant','content':'请确认范围：全省还是某个地市？以及报告的内容侧重。'},
                  {'role':'user','content':'2026年10月全省黑点统计分析报告'}]
        with patch('credential_store.get_assistant_key',return_value='test-key'),patch('app.plan_query',side_effect=ValueError('DeepSeek 返回内容异常，请稍后重试。')) as model:
            response=service.app.test_client().post('/api/assistant/query-chat',json={'messages':messages},base_url='http://127.0.0.1:5088')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json.get('action'),{'type':'open_analysis_report','month':'2026-10'})
        model.assert_not_called()

    def test_report_clarification_is_local_and_uses_previous_month(self):
        first='给我一个2026年10月分析报告'
        with patch('credential_store.get_assistant_key',return_value=None),patch('app.plan_query') as model:
            client=service.app.test_client()
            response=client.post('/api/assistant/query-chat',json={'messages':[{'role':'user','content':first}]},base_url='http://127.0.0.1:5088')
            self.assertEqual(response.status_code,200);self.assertIn('报告类型',response.json['reply'])
            messages=[{'role':'user','content':first},{'role':'assistant','content':'上一轮已执行统计查询，具体结果不随历史记录再次发送。'},{'role':'user','content':'全省黑点'}]
            response=client.post('/api/assistant/query-chat',json={'messages':messages},base_url='http://127.0.0.1:5088')
            self.assertEqual(response.json.get('action'),{'type':'open_analysis_report','month':'2026-10'})
            model.assert_not_called()

    def test_report_clarification_does_not_misrepresent_scope_or_cancellation(self):
        base=[{'role':'user','content':'给我一个2026年10月分析报告'},{'role':'assistant','content':'请说明报告类型。'}]
        for last in ['合肥黑点分析报告','不用生成黑点报告了']:
            with self.subTest(last=last):
                result=assistant_actions.report_conversation(base+[{'role':'user','content':last}],date(2026,11,10))
                self.assertTrue(result is None or 'action' not in result)
        result=assistant_actions.report_conversation(base+[{'role':'user','content':'2026年9月全省黑点分析报告'}],date(2026,11,10))
        self.assertEqual(result['action']['month'],'2026-09')
        old=[{'role':'user','content':'给我一个2025年10月分析报告'},{'role':'assistant','content':'请说明报告类型。'}]
        result=assistant_actions.report_conversation(old+[{'role':'user','content':'全省9月黑点分析报告'}],date(2026,11,10))
        self.assertEqual(result['action']['month'],'2025-09')

if __name__=='__main__':unittest.main()
