import unittest
from unittest.mock import patch
import app as service


class ComplaintApiTests(unittest.TestCase):
    def setUp(self):
        self.previous=service.app.testing
        service.app.testing=True
        self.client=service.app.test_client()

    def tearDown(self):service.app.testing=self.previous

    def test_page_and_local_draft(self):
        response=self.client.get('/complaints')
        self.assertEqual(response.status_code,200)
        self.assertIn('用户安抚话术指导',response.get_data(as_text=True))
        with patch('complaint_routes.complete') as model:
            result=self.client.post('/api/complaints/guidance',json={'scenario':'first_contact','mode':'local','global_customer':True})
        self.assertEqual(result.status_code,200)
        self.assertTrue(result.json['text'].startswith('尊敬的全球通用户，'))
        model.assert_not_called()

    def test_ai_requires_consent_and_does_not_send_obvious_identifiers(self):
        data={'scenario':'appointment','mode':'ai','description':'室内信号弱','global_customer':False}
        with patch('complaint_routes.complete') as model:
            self.assertEqual(self.client.post('/api/complaints/guidance',json=data).status_code,400)
            self.assertEqual(self.client.post('/api/complaints/guidance',json={**data,'confirm_send':True,'description':'手机号13800138000'}).status_code,400)
            model.assert_not_called()
        self.assertEqual(self.client.post('/api/complaints/guidance',json={**data,'scenario':[]}).status_code,400)

    def test_ai_uses_only_opted_in_description(self):
        data={'scenario':'appointment','mode':'ai','description':'室内信号弱','global_customer':True,'confirm_send':True}
        with patch('complaint_routes.credential_store.get_assistant_key',return_value='secret'),patch('complaint_routes.complete',return_value='您好，欢迎预约。') as model:
            response=self.client.post('/api/complaints/guidance',json=data)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['text'].startswith('尊敬的全球通用户，'))
        self.assertIn('室内信号弱',str(model.call_args))
        self.assertNotIn('secret',response.get_data(as_text=True))

    def test_cross_origin_rejected(self):
        response=self.client.post('/api/complaints/guidance',json={'scenario':'appointment'},headers={'Origin':'https://example.com'})
        self.assertEqual(response.status_code,403)

    def test_simulation_multi_turn_and_privacy(self):
        messages=[{'role':'user','content':'用户反映信号弱'},{'role':'assistant','content':'可以先了解使用情况。'},{'role':'user','content':'如果暂时无法解决呢？'}]
        with patch('complaint_routes.credential_store.get_assistant_key',return_value='secret'),patch('complaint_routes.complete',return_value='可以说明正在跟进，不承诺时限。') as model:
            self.assertEqual(self.client.post('/api/complaints/simulate',json={'messages':messages}).status_code,400)
            response=self.client.post('/api/complaints/simulate',json={'messages':messages,'confirm_send':True})
            self.assertEqual(response.status_code,200)
            sent=model.call_args.args[1]
            self.assertIn('投诉触点服务规范',model.call_args.kwargs['system'])
            self.assertIn('你扮演安徽移动无线网络客服',model.call_args.kwargs['system'])
            self.assertIn('每次只输出你要对用户说的话',model.call_args.kwargs['system'])
            self.assertEqual(sent,messages)
            bad=[{'role':'user','content':'电话13800138000'}]
            self.assertEqual(self.client.post('/api/complaints/simulate',json={'messages':bad,'confirm_send':True}).status_code,400)
            self.assertEqual(model.call_count,1)

    def test_simulation_accepts_long_assistant_reply_but_limits_user_input(self):
        messages=[{'role':'user','content':'我家网络慢'},{'role':'assistant','content':'您' * 2000},{'role':'user','content':'是手机网络'}]
        with patch('complaint_routes.credential_store.get_assistant_key',return_value='test-key'), patch('complaint_routes.complete',return_value='请问多久了？') as model:
            response=self.client.post('/api/complaints/simulate',json={'messages':messages,'confirm_send':True})
            self.assertEqual(response.status_code,200)
            self.assertEqual(model.call_args.args[1],messages)
            messages[-1]['content']='网' * 1501
            self.assertEqual(self.client.post('/api/complaints/simulate',json={'messages':messages,'confirm_send':True}).status_code,400)
            self.assertEqual(model.call_count,1)

    def test_simulation_invalid_history_and_origin(self):
        with patch('complaint_routes.complete') as model:
            for history in ([],[{'role':'assistant','content':'hello'}],[{'role':'user','content':'a'},{'role':'user','content':'b'}]):
                self.assertEqual(self.client.post('/api/complaints/simulate',json={'messages':history,'confirm_send':True}).status_code,400)
            self.assertEqual(self.client.post('/api/complaints/simulate',json={'messages':[{'role':'user','content':'你好'}],'confirm_send':True},headers={'Origin':'https://example.com'}).status_code,403)
            model.assert_not_called()


if __name__=='__main__':unittest.main()
