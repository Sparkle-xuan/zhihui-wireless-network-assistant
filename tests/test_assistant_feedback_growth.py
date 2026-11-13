import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as service
import conversation_query
import intent_router
from core import CITIES


class GrowthTests(unittest.TestCase):
    def setUp(self):
        self.plan = intent_router.route([{'role': 'user', 'content': '2026年10月哪些地市挂起数量连续两个月增长'}])

    def test_growth_uses_three_snapshots_and_strict_increases(self):
        self.assertEqual(self.plan[0], 'suspension_growth')
        def sample(month):
            n = {'2026-08': 1, '2026-09': 2, '2026-10': 3}[month]
            return {'kind': 'weekly', 'period': month+'-25', 'city_note': '',
                    'cities': [{'name': city, 'value': n if i == 0 else 4} for i, city in enumerate(CITIES)]}
        result = conversation_query.execute_growth(self.plan[1], sample)
        self.assertEqual(result['table']['rows'], [[CITIES[0], '1', '2', '3']])
        self.assertIn('累计存量', result['evidence'])

    def test_missing_and_partial_are_not_zero(self):
        result = conversation_query.execute_growth(self.plan[1], lambda _: None)
        self.assertIn('无法判断', result['reply'])
        partial = {'cities': [{'name': CITIES[0], 'value': 1}], 'city_note': '部分地市未提供'}
        self.assertIn('不完整', conversation_query.execute_growth(self.plan[1], lambda _: partial)['reply'])

    def test_reason_question_routes_to_existing_keyword_summary(self):
        route, plan = intent_router.route([{'role':'user', 'content':'2026年10月合肥挂起主要问题是什么'}])
        self.assertEqual(route, 'suspension_reason')
        self.assertEqual((plan['month'], plan['city']), ('2026-10', '合肥'))

    def test_endpoint_calls_selected_snapshot_not_model(self):
        service.app.testing = True
        with patch('credential_store.get_assistant_key', return_value='fake'), patch('app.selected_suspension', return_value=None), patch('app.plan_query') as model:
            result = service.app.test_client().post('/api/assistant/query-chat', json={'messages': [{'role':'user', 'content':'2026年10月哪些地市挂起连续两个月增长'}]})
        self.assertEqual(result.status_code, 200)
        self.assertIn('无法判断', result.json['reply'])
        model.assert_not_called()


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.old_db, self.old_testing = service.DB, service.app.testing
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        service.DB = Path(self.tmp.name) / 'feedback.sqlite3'
        service.app.testing = True
        self.client = service.app.test_client()

    def tearDown(self):
        service.DB, service.app.testing = self.old_db, self.old_testing
        self.tmp.cleanup()

    def test_feedback_saves_only_explicit_fields(self):
        payload = {'question':'模拟问题', 'rating':'incorrect', 'reason':'意图识别', 'answer':'不应保存'}
        self.assertEqual(self.client.post('/api/assistant/feedback', json=payload).status_code, 200)
        items = self.client.get('/api/assistant/feedback').json['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['question'], '模拟问题')
        self.assertNotIn('不应保存', str(items))

    def test_incorrect_feedback_requires_reason(self):
        response = self.client.post('/api/assistant/feedback', json={'question':'模拟问题', 'rating':'incorrect'})
        self.assertEqual(response.status_code, 400)

    def test_incorrect_feedback_accepts_bounded_free_text(self):
        response = self.client.post('/api/assistant/feedback', json={'question':'模拟问题', 'rating':'incorrect', 'reason':'  排名漏掉并列地市  '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/assistant/feedback').json['items'][0]['reason'], '排名漏掉并列地市')
        for reason in ('   ', '错' * 501, None):
            self.assertEqual(self.client.post('/api/assistant/feedback', json={'question':'模拟问题', 'rating':'incorrect', 'reason':reason}).status_code, 400)
    def test_reviewed_feedback_is_recorded_without_changing_router(self):
        self.client.post('/api/assistant/feedback',json={'question':'模拟问题','rating':'incorrect','reason':'意图识别'})
        item=self.client.get('/api/assistant/feedback').json['items'][0]
        self.assertEqual(item['expected'],'')
        result=self.client.post('/api/assistant/feedback/review',json={'id':item['id'],'expected':'应查询地市解决率'})
        self.assertEqual(result.status_code,200)
        item=self.client.get('/api/assistant/feedback').json['items'][0]
        self.assertEqual(item['expected'],'应查询地市解决率');self.assertTrue(item['reviewed_at'])
        self.assertEqual(self.client.post('/api/assistant/feedback/review',json={'id':item['id'],'expected':''}).status_code,400)


if __name__ == '__main__':
    unittest.main()
