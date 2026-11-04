"""Send a user-reviewed report through QQ Mail."""
import re
import smtplib
import ssl
from email.message import EmailMessage

ADDRESS=re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}$")

def send_report(sender,recipient,auth_code,subject,body,attachment=None):
    sender=sender.strip(); recipient=recipient.strip()
    if len(sender)>254 or not ADDRESS.fullmatch(sender): raise ValueError('请输入有效的发件邮箱地址。')
    if len(recipient)>254 or not ADDRESS.fullmatch(recipient): raise ValueError('请输入一个有效的收件邮箱地址。')
    if not auth_code or len(auth_code)>256: raise ValueError('请输入 QQ 邮箱 SMTP 授权码。')
    if not subject.strip() or len(subject)>200 or '\n' in subject or '\r' in subject: raise ValueError('邮件主题不能为空，且不能包含换行。')
    if not body.strip() or len(body)>100000: raise ValueError('报告文字不能为空或过长。')
    message=EmailMessage()
    message['From']=sender; message['To']=recipient; message['Subject']=subject.strip()
    message.set_content(body)
    if attachment:
        data,filename=attachment
        message.add_attachment(data,maintype='application',subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename=filename)
    try:
        with smtplib.SMTP_SSL('smtp.qq.com',465,timeout=20,context=ssl.create_default_context()) as smtp:
            smtp.login(sender,auth_code)
            refused=smtp.send_message(message)
            if refused: raise ValueError('邮件服务器未接受该收件人，请核对地址。')
    except smtplib.SMTPAuthenticationError as exc:
        raise ValueError('QQ 邮箱验证失败，请检查邮箱、SMTP 服务和授权码。') from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise ValueError('邮件服务器未接受该收件人，请核对地址。') from exc
    except (smtplib.SMTPException,OSError) as exc:
        raise ValueError('连接或发送状态未确认。请先检查发件箱，再决定是否重试。') from exc
