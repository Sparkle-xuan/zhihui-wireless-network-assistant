import unittest
from unittest.mock import Mock, patch

import assistant_service
from app import app


class AssistantServiceTest(unittest.TestCase):
    @patch('assistant_service.requests.post')
    def test_report_is_included_only_when_requested(self, post):
        post.return_value = Mock(status_code=200, json=lambda: {'choices': [{'message': {'content': '回答'}}]})
        messages = [{'role': 'user', 'content': '请分析'}]
        self.assertEqual(assistant_service.complete('fake-key', messages), '回答')
        first = post.call_args.kwargs['json']
        self.assertNotIn('报告内容', str(first))
        self.assertEqual(first['model'], 'deepseek-flash')
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        assistant_service.complete('fake-key', messages, '报告内容')
        self.assertIn('报告内容', str(post.call_args.kwargs['json']))

    @patch('assistant_service.requests.post')
    def test_validation_and_safe_error(self, post):
        with self.assertRaises(ValueError):
            assistant_service.complete('fake-key', [{'role': 'system', 'content': 'x'}])
        post.assert_not_called()
        post.return_value = Mock(status_code=401)
        with self.assertRaises(ValueError) as error:
            assistant_service.complete('fake-key', [{'role': 'user', 'content': 'hello'}])
        self.assertNotIn('fake-key', str(error.exception))

    @patch('assistant_service.requests.post')
    def test_supported_model_is_sent_to_deepseek(self, post):
        post.return_value=Mock(status_code=200,json=lambda:{'choices':[{'message':{'content':'回答'}}]})
        assistant_service.complete('fake-key',[{'role':'user','content':'你好'}],model='deepseek-v4-pro')
        self.assertEqual(post.call_args.kwargs['json']['model'],'deepseek-v4-pro')


class AssistantApiTest(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    @patch('credential_store.get_assistant_key', return_value='secret-test-key')
    def test_key_status_does_not_reveal_key_and_rejects_cross_origin(self, get_key):
        response = self.client.get('/api/assistant/key')
        self.assertEqual(response.json, {'configured': True})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get('/api/assistant/key', headers={'Origin': 'http://evil.test'}).status_code, 403)

    @patch('app.complete_chat', return_value='答复')
    @patch('credential_store.get_assistant_key', return_value='secret-test-key')
    def test_chat_passes_only_explicit_context(self, get_key, complete):
        messages = [{'role': 'user', 'content': '你好'}]
        response = self.client.post('/api/assistant/chat', json={'messages': messages})
        self.assertEqual(response.json, {'reply': '答复'})
        complete.assert_called_once_with('secret-test-key', messages, '', model='deepseek-flash')
        self.assertNotIn('secret-test-key', response.get_data(as_text=True))

    @patch('credential_store.get_assistant_key', return_value=None)
    def test_missing_key(self, get_key):
        self.assertEqual(self.client.post('/api/assistant/chat', json={'messages': []}).status_code, 400)

if __name__ == '__main__':
    unittest.main()
