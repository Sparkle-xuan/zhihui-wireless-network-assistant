import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import app
import credential_store

class CredentialTests(unittest.TestCase):
    def setUp(self): self.old_testing=app.app.testing;app.app.testing=True
    def tearDown(self): app.app.testing=self.old_testing
    def test_save_and_retrieve_for_matching_sender_only(self):
        captured={}
        def write(item,flags): captured.update(item)
        with patch('credential_store.win32cred.CredWrite',side_effect=write):
            credential_store.save('Sender@qq.com','example-code')
        self.assertEqual(captured['UserName'],'Sender@qq.com')
        self.assertEqual(captured['CredentialBlob'],'example-code')
        with patch('credential_store.win32cred.CredRead',return_value=captured):
            self.assertEqual(credential_store.status(),{'configured':True,'sender':'Sender@qq.com'})
            self.assertEqual(credential_store.get_for_sender('sender@qq.com'),'example-code')
            self.assertIsNone(credential_store.get_for_sender('other@qq.com'))

    def test_endpoint_never_returns_authorization_code_and_rejects_other_origin(self):
        client=app.app.test_client()
        with patch('credential_store.status',return_value={'configured':True,'sender':'sender@qq.com'}):
            response=client.get('/api/mail/credential')
        self.assertEqual(response.json,{'configured':True,'sender':'sender@qq.com'})
        with patch('credential_store.save') as save:
            response=client.post('/api/mail/credential',json={'sender':'sender@qq.com','auth_code':'example-code'})
            self.assertEqual(response.status_code,200); save.assert_called_once_with('sender@qq.com','example-code')
            self.assertNotIn('example-code',response.get_data(as_text=True))
            blocked=client.post('/api/mail/credential',json={'sender':'sender@qq.com','auth_code':'x'},headers={'Origin':'https://example.com'})
            self.assertEqual(blocked.status_code,403);self.assertEqual(save.call_count,1)
        with patch('credential_store.delete') as delete:
            response=client.delete('/api/mail/credential',json={})
            self.assertEqual(response.status_code,200);delete.assert_called_once()

if __name__=='__main__': unittest.main()
