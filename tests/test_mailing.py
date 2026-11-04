import json
import smtplib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import load_workbook
from io import BytesIO

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import app
import mailing

class FakeSMTP:
    messages=[]
    def __init__(self,host,port,timeout,context):
        assert (host,port)==('smtp.qq.com',465)
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def login(self,sender,code):
        if code=='invalid': raise smtplib.SMTPAuthenticationError(535,b'failed')
    def send_message(self,message): self.messages.append(message); return {}

class MailTests(unittest.TestCase):
    def setUp(self): self.old_testing=app.app.testing;app.app.testing=True
    def tearDown(self): app.app.testing=self.old_testing
    def test_weekly_send_and_validation(self):
        with patch('mailing.smtplib.SMTP_SSL',FakeSMTP):
            mailing.send_report('sender@qq.com','to@example.com','code','周报','正文')
            msg=FakeSMTP.messages[-1]
            self.assertEqual(msg['To'],'to@example.com'); self.assertEqual(msg.get_body().get_content().strip(),'正文')
            with self.assertRaisesRegex(ValueError,'验证失败'): mailing.send_report('sender@qq.com','to@example.com','invalid','周报','正文')
            with self.assertRaisesRegex(ValueError,'收件'): mailing.send_report('sender@qq.com','a@example.com,b@example.com','code','周报','正文')
            with self.assertRaisesRegex(ValueError,'主题'): mailing.send_report('sender@qq.com','to@example.com','code','周报\nBcc: x@y.com','正文')

    def test_monthly_attachment_matches_edited_report(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tests') as tmp:
            original=app.DB; app.DB=Path(tmp)/'test.sqlite3'
            try:
                city={'city':'示例','included':1,'qualified':1,'rate':1,'after':0,'solved':1,'reduction':1}
                data={'cities':[city],'total':{k:v for k,v in city.items() if k!='city'},'suspended':{'count':0}}
                with app.connect() as c:
                    c.execute('INSERT INTO reports (period,data,notes,weekly,monthly,monthly_data) VALUES (?,?,?,?,?,?)',('2026-10-30',json.dumps(data),'{}','','原月报',json.dumps(data)))
                payload={'kind':'monthly','sender':'sender@qq.com','recipient':'to@example.com','auth_code':'code','subject':'月报','body':'编辑后的月报','attach':True}
                with patch('mailing.smtplib.SMTP_SSL',FakeSMTP):
                    response=app.app.test_client().post('/api/report/2026-10-30/email',json=payload)
                self.assertEqual(response.status_code,200)
                msg=FakeSMTP.messages[-1]; attachment=next(msg.iter_attachments())
                self.assertEqual(load_workbook(BytesIO(attachment.get_payload(decode=True)),data_only=True).active['A4'].value,'编辑后的月报')
                self.assertEqual(msg.get_body().get_content().strip(),'编辑后的月报')
                self.assertEqual(app.app.test_client().post('/api/report/2026-10-30/email',json={**payload,'kind':'weekly'}).status_code,400)
                with patch('credential_store.get_for_sender',return_value='saved-code') as get_saved, patch('mailing.smtplib.SMTP_SSL',FakeSMTP):
                    sent=app.app.test_client().post('/api/report/2026-10-30/email',json={**payload,'auth_code':''})
                self.assertEqual(sent.status_code,200);get_saved.assert_called_once_with('sender@qq.com')
                with patch('credential_store.get_for_sender',return_value=None):
                    missing=app.app.test_client().post('/api/report/2026-10-30/email',json={**payload,'auth_code':''})
                self.assertEqual(missing.status_code,400)
                with app.connect() as c:
                    self.assertNotIn('code',str(c.execute('SELECT * FROM reports').fetchone()))
            finally: app.DB=original

if __name__=='__main__': unittest.main()
