"""Keep application credentials in the current Windows user's vault."""
import json
import pywintypes
import win32cred
from mailing import ADDRESS

TARGET='Zhihui/QQMail/SMTP'
DATABASE_TARGET='Zhihui/PostgreSQL/local'
ASSISTANT_TARGET='Zhihui/DeepSeek/API'

def _read(target=TARGET):
    try:
        return win32cred.CredRead(target,win32cred.CRED_TYPE_GENERIC,0)
    except pywintypes.error as exc:
        if exc.winerror==1168: return None
        raise RuntimeError('无法读取 Windows 凭据管理器，请检查当前 Windows 账户。') from exc

def status():
    credential=_read()
    return {'configured':bool(credential),'sender':credential['UserName'] if credential else ''}

def save(sender,code):
    if not isinstance(sender,str) or not ADDRESS.fullmatch(sender.strip()) or len(sender.strip())>254:
        raise ValueError('请输入有效的 QQ 发件邮箱地址。')
    if not isinstance(code,str) or not code or len(code)>256 or '\x00' in code:
        raise ValueError('请输入有效的 QQ 邮箱 SMTP 授权码。')
    try:
        win32cred.CredWrite({'Type':win32cred.CRED_TYPE_GENERIC,'TargetName':TARGET,'CredentialBlob':code,'Persist':win32cred.CRED_PERSIST_LOCAL_MACHINE,'UserName':sender.strip()},0)
    except pywintypes.error as exc:
        raise RuntimeError('无法保存至 Windows 凭据管理器，请检查当前 Windows 账户。') from exc

def get_for_sender(sender):
    credential=_read()
    if not credential or credential['UserName'].casefold()!=sender.strip().casefold(): return None
    blob=credential['CredentialBlob']
    try: return bytes(blob).decode('utf-16-le') if not isinstance(blob,str) else blob
    except (UnicodeDecodeError,TypeError) as exc: raise RuntimeError('已保存的授权码无法读取，请重新保存。') from exc

def delete():
    try:
        win32cred.CredDelete(TARGET,win32cred.CRED_TYPE_GENERIC,0)
    except pywintypes.error as exc:
        if exc.winerror!=1168: raise RuntimeError('无法删除 Windows 凭据，请检查当前 Windows 账户。') from exc

def _blob_text(credential):
    blob=credential['CredentialBlob']
    try: return blob if isinstance(blob,str) else bytes(blob).decode('utf-16-le')
    except (UnicodeDecodeError,TypeError) as exc: raise RuntimeError('数据库凭据无法读取，请重新设置。') from exc

def get_database():
    credential=_read(DATABASE_TARGET)
    if not credential: return None
    try:
        value=json.loads(_blob_text(credential))
        if not isinstance(value,dict) or any(not isinstance(value.get(k),str) or not value[k] for k in ('user','dbname','password')): raise ValueError()
        return value
    except (ValueError,TypeError) as exc: raise RuntimeError('数据库凭据格式无效，请重新设置。') from exc

def save_database(user,dbname,password):
    if any(not isinstance(x,str) or not x.strip() or '\x00' in x for x in (user,dbname,password)):
        raise ValueError('请填写数据库用户名、名称和密码。')
    if len(user)>63 or len(dbname)>63 or len(password)>512:
        raise ValueError('数据库用户名、名称或密码过长。')
    blob=json.dumps({'user':user.strip(),'dbname':dbname.strip(),'password':password},ensure_ascii=False)
    if len(blob.encode('utf-16-le'))>2400: raise ValueError('数据库凭据过长。')
    try:
        win32cred.CredWrite({'Type':win32cred.CRED_TYPE_GENERIC,'TargetName':DATABASE_TARGET,'CredentialBlob':blob,'Persist':win32cred.CRED_PERSIST_LOCAL_MACHINE,'UserName':user.strip()},0)
    except pywintypes.error as exc: raise RuntimeError('无法保存数据库凭据，请检查 Windows 凭据管理器。') from exc

def get_assistant_key():
    credential=_read(ASSISTANT_TARGET)
    return _blob_text(credential) if credential else None

def save_assistant_key(key):
    if not isinstance(key,str) or not 12<=len(key.strip())<=256 or any(c.isspace() for c in key.strip()) or '\x00' in key:
        raise ValueError('请输入有效的 DeepSeek API 密钥。')
    try:
        win32cred.CredWrite({'Type':win32cred.CRED_TYPE_GENERIC,'TargetName':ASSISTANT_TARGET,'CredentialBlob':key.strip(),'Persist':win32cred.CRED_PERSIST_LOCAL_MACHINE,'UserName':'DeepSeek'},0)
    except pywintypes.error as exc: raise RuntimeError('无法保存 DeepSeek 密钥，请检查 Windows 凭据管理器。') from exc

def delete_assistant_key():
    try: win32cred.CredDelete(ASSISTANT_TARGET,win32cred.CRED_TYPE_GENERIC,0)
    except pywintypes.error as exc:
        if exc.winerror!=1168: raise RuntimeError('无法删除 DeepSeek 密钥，请检查 Windows 凭据管理器。') from exc
