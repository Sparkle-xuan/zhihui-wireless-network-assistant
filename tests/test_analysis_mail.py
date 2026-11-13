import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as service
import analysis_mail
import mailing
from core import CITIES


class FakeSMTP:
    messages=[]
    def __init__(self,*args,**kwargs):pass
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def login(self,sender,code):pass
    def send_message(self,message):self.messages.append(message);return {}


class AnalysisMailTests(unittest.TestCase):
    def setUp(self):
        self.old_db,self.old_testing=service.DB,service.app.testing
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        service.DB=Path(self.tmp.name)/'test.sqlite3';service.app.testing=True
        rows=[{'city':city,'included':10,'qualified':5} for city in CITIES]
        with service.connect() as c:c.execute('INSERT INTO reports (period,data,notes,weekly,monthly) VALUES (?,?,?,?,?)',('2026-10-30',json.dumps({'cities':rows,'total':{'included':160,'qualified':80}}),'{}','周报',''))
        self.client=service.app.test_client()
    def tearDown(self):
        service.DB,service.app.testing=self.old_db,self.old_testing
        self.tmp.cleanup()
    def generate(self):
        with patch('credential_store.get_assistant_key',return_value=None):
            response=self.client.post('/api/analysis-report',json={'month':'2026-10'})
        self.assertEqual(response.status_code,200)
        return response.json
    def payload(self,report_id):
        return {'report_id':report_id,'sender':'sender@qq.com','recipient':'to@example.com','auth_code':'','subject':'测试报告','body':'您好，<测试>\n请查收。'}
    def test_generation_does_not_send_and_email_matches_preview(self):
        with patch('mailing.smtplib.SMTP_SSL',FakeSMTP),patch('credential_store.get_for_sender',return_value='fake'):
            FakeSMTP.messages.clear()
            report=self.generate()
            self.assertEqual(FakeSMTP.messages,[])
            sent=self.client.post('/api/analysis-report/email',json=self.payload(report['report_id']))
            self.assertEqual(sent.status_code,200)
            msg=FakeSMTP.messages[-1]
            html=msg.get_body(preferencelist=('html',)).get_content()
            self.assertIn('各地市统计明细',html)
            self.assertIn('&lt;测试&gt;',html)
            attachment=next(msg.iter_attachments())
            self.assertEqual(attachment.get_content_type(),'text/html')
            self.assertEqual(attachment.get_payload(decode=True).decode('utf-8'),report['html'])
            repeat=self.client.post('/api/analysis-report/email',json=self.payload(report['report_id']))
            self.assertEqual(repeat.status_code,400)
            self.assertEqual(len(FakeSMTP.messages),1)
    def test_missing_credential_bad_recipient_and_expired_report_do_not_send(self):
        report=self.generate()
        with patch('credential_store.get_for_sender',return_value=None),patch('app.send_report') as send:
            self.assertEqual(self.client.post('/api/analysis-report/email',json=self.payload(report['report_id'])).status_code,400)
            send.assert_not_called()
        with patch('credential_store.get_for_sender',return_value='fake'),patch('app.send_report') as send:
            invalid={**self.payload(report['report_id']),'recipient':'a@example.com,b@example.com'}
            self.assertEqual(self.client.post('/api/analysis-report/email',json=invalid).status_code,400)
            self.assertEqual(self.client.post('/api/analysis-report/email',json=self.payload('0'*32)).status_code,400)
            send.assert_not_called()
    def test_uncertain_delivery_cannot_be_repeated_without_regeneration(self):
        report=self.generate();payload=self.payload(report['report_id'])
        with patch('credential_store.get_for_sender',return_value='fake'),patch('app.send_report',side_effect=ValueError('连接或发送状态未确认。')) as send:
            self.assertEqual(self.client.post('/api/analysis-report/email',json=payload).status_code,400)
            self.assertEqual(self.client.post('/api/analysis-report/email',json=payload).status_code,400)
            self.assertEqual(send.call_count,1)
    def test_authentication_rejection_can_retry_same_report(self):
        report=self.generate();payload=self.payload(report['report_id'])
        with patch('credential_store.get_for_sender',return_value='fake'),patch('app.send_report',side_effect=[mailing.MailNotSentError('验证失败'),None]):
            self.assertEqual(self.client.post('/api/analysis-report/email',json=payload).status_code,400)
            self.assertEqual(self.client.post('/api/analysis-report/email',json=payload).status_code,200)
    def test_smtp_authentication_error_is_known_not_sent(self):
        import smtplib
        class RejectedSMTP(FakeSMTP):
            def login(self,sender,code):raise smtplib.SMTPAuthenticationError(535,b'bad credentials')
        with patch('mailing.smtplib.SMTP_SSL',RejectedSMTP):
            with self.assertRaises(mailing.MailNotSentError):mailing.send_report('sender@qq.com','to@example.com','bad','提醒','正文')


if __name__=='__main__':unittest.main()
