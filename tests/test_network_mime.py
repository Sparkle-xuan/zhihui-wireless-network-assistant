import unittest
from unittest.mock import patch
from mailing import send_report

class SMTP:
    message=None
    def __init__(self,*a,**kw):pass
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def login(self,*a):pass
    def send_message(self,msg): SMTP.message=msg;return {}

class NetworkMimeTests(unittest.TestCase):
    @patch('mailing.smtplib.SMTP_SSL',SMTP)
    def test_html_mail_has_text_and_table_alternatives(self):
        send_report('a@example.com','b@example.com','fake','日报','标题\n合肥\t1',html_body='<p>标题</p><table><tr><td>合肥</td></tr></table>')
        msg=SMTP.message
        self.assertEqual(msg.get_content_type(),'multipart/alternative')
        plain,rich=list(msg.iter_parts())
        self.assertIn('合肥',plain.get_content());self.assertIn('<table>',rich.get_content());self.assertEqual(rich.get_content_type(),'text/html')

if __name__=='__main__':unittest.main()
