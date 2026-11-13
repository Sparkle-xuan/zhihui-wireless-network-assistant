import unittest
from unittest.mock import patch

import app as service
import intent_router


def messages(*texts):
    return [{'role': 'user', 'content': text} for text in texts]


class IntentRoutingAcceptanceTests(unittest.TestCase):
    def test_business_questions_route_to_the_expected_tools(self):
        cases = [
            ('2026年10月合肥挂起多少', 'general'),
            ('2026年10月各地市挂起数量最多的前三名', 'suspension'),
            ('2026年10月合肥挂起原因是什么', 'suspension_reason'),
            ('2026年10月哪个地市黑点解决率最低，和上个月比怎么样', 'ranked_comparison'),
            ('2026年10月哪个地市黑点解决率最高', 'highest_resolution'),
            ('2026年10月21日全省5G流量与10月20日相比怎么样', 'daily_comparison'),
            ('2026年11月2日简述日报内容', 'network_overview'),
            ('2026年10月21日合肥5G流量是多少', 'network_metric'),
            ('你好', 'general'),
        ]
        for question, expected in cases:
            with self.subTest(question=question):
                self.assertEqual(intent_router.route(messages(question))[0], expected)

    def test_followup_preserves_context_and_new_topic_resets_it(self):
        route, plan = intent_router.route(messages('2026年10月合肥挂起多少', '宣城呢', '和上个月比呢'))
        self.assertEqual(route, 'suspension')
        self.assertEqual((plan['month'], plan['other_month'], plan['city']), ('2026-10', '2026-09', '宣城'))
        route, plan = intent_router.route(messages('2026年10月合肥挂起多少', '2026年10月21日全省5G流量是多少'))
        self.assertEqual(route, 'network_metric')
        self.assertEqual(plan['arguments']['city'], '全省')

    def test_comparison_keeps_both_dates_and_scope(self):
        route, plan = intent_router.route(messages('2026年10月21日合肥5G流量是多少', '和10月20日比呢'))
        self.assertEqual(route, 'daily_comparison')
        self.assertEqual((plan['day'], plan['base_day'], plan['city']), ('2026-10-21', '2026-10-20', '合肥'))

    def test_missing_data_is_not_reported_as_zero(self):
        old_testing = service.app.testing
        service.app.testing = True
        self.addCleanup(setattr, service.app, 'testing', old_testing)
        client = service.app.test_client()
        with patch('credential_store.get_assistant_key', return_value='fake'), \
             patch('app.selected_suspension', return_value=None), \
             patch('app.plan_query') as model:
            response = client.post('/api/assistant/query-chat', json={'messages': messages('2026年10月各地市挂起数量最多的前三名')})
        self.assertEqual(response.status_code, 200)
        self.assertIn('没有已保存', response.json['reply'])
        model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
