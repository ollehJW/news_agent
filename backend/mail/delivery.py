"""User-triggered HTML newsletter delivery with durable retry protection."""
from backend.subscriptions.members import ACCESS,MemberBody
import base64
import json
import os
import re
import smtplib
import ssl
import uuid
from pathlib import Path
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, formatdate
from typing import Literal
from dotenv import dotenv_values
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator, ConfigDict
from backend.mail.email_html import email_html
from backend.mail.inline_images import prepare_inline_images
from backend.core.paths import PROJECT_DIR
from backend.core.auth import database, now
from backend.core.error_storage import ErrorRoute, tracked_member_user

router=APIRouter(prefix='/api/newsletter-email',route_class=ErrorRoute)


def init_mail_db():
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        for statement in Path(__file__).with_name('schema.sql').read_text().split(';'):
            if statement.strip():db.execute(statement)
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='newsletter_email_requests'").fetchone():
            for row in db.execute('SELECT * FROM newsletter_email_requests').fetchall():
                results=json.loads(row['results_json'])
                names={r['user_id']:r.get('name') for r in results}
                # Legacy records never captured email addresses or SMTP acceptance times.
                recipients=[{'user_id':uid,'name':names.get(uid),'email':None} for uid in json.loads(row['recipient_ids'])]
                db.execute("""INSERT INTO mailing (mailing_id,user_id,request_id,kind,newsletter_id,
                    mailing_list,results_json,status,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()),row['user_id'],row['request_id'],row['kind'],row['newsletter_id'],
                     json.dumps(recipients,ensure_ascii=False),row['results_json'],row['status'],row['created_at'],row['completed_at']))
            db.execute('DROP TABLE newsletter_email_requests')
        if 'subscription_id' not in {r['name'] for r in db.execute('PRAGMA table_info(mailing)')}:
            db.execute('ALTER TABLE mailing ADD COLUMN subscription_id TEXT REFERENCES subscriptions(subscription_id) ON DELETE RESTRICT')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS mailing_subscription_edition ON mailing(subscription_id,newsletter_id) WHERE subscription_id IS NOT NULL')
        for row in db.execute('SELECT mailing_id,mailing_list,results_json FROM mailing').fetchall():
            recipients=json.loads(row['mailing_list']);results=json.loads(row['results_json'])
            changed=False
            for recipient in recipients+results:
                if 'member_type' not in recipient or 'email' in recipient:
                    recipient['member_type']='internal' if recipient.get('user_id') else 'external'
                    recipient['email_address']=recipient.pop('email',recipient.get('email_address'))
                    changed=True
            if changed:
                db.execute('UPDATE mailing SET mailing_list=?,results_json=? WHERE mailing_id=?',
                    (json.dumps(recipients,ensure_ascii=False),json.dumps(results,ensure_ascii=False),row['mailing_id']))



class SendBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: str=Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9-]+$')
    kind: Literal['sample','subscription']
    newsletter_id: str=Field(min_length=1,max_length=100)
    recipients: list[MemberBody] | None=Field(default=None,min_length=1,max_length=100)
    user_ids: list[str] | None=Field(default=None,min_length=1,max_length=100)

    @model_validator(mode='after')
    def recipient_input(self):
        if (self.recipients is None)==(self.user_ids is None):
            raise ValueError('수신자 목록을 하나 지정해 주세요.')
        return self

    def members(self):
        return self.recipients if self.recipients is not None else [MemberBody(member_type='internal',user_id=uid) for uid in self.user_ids]


def recipient_key(recipient):
    return (recipient.get('member_type','internal'),recipient.get('user_id') or (recipient.get('email_address') or '').strip().lower())


def mail_settings():
    settings={**dotenv_values(PROJECT_DIR/'.env'),**os.environ}
    address=settings.get('GMAIL_USER','')
    password=''.join((settings.get('GMAIL_APP_PASSWORD') or '').split())
    if not address or not password:
        raise HTTPException(503,'메일 발송 계정 설정이 필요합니다.')
    return address,password


def load_letter(db,body,user_id):
    if body.kind=='sample':
        row=db.execute('''SELECT topic AS title,html_content FROM sample_details
            WHERE sample_id=? AND user_id=? AND saved_at IS NOT NULL AND status='completed' ''',
            (body.newsletter_id,user_id)).fetchone()
    else:
        row=db.execute(f'''SELECT d.topic AS title,n.html_content FROM subscripted_newsletters n
            JOIN sample_details d ON d.sample_id=n.sample_id
            WHERE n.newsletter_id=? AND n.published_at IS NOT NULL AND EXISTS(
                SELECT 1 FROM subscription_history h JOIN subscriptions s USING(subscription_id)
                WHERE h.newsletter_id=n.newsletter_id AND s.sample_id=n.sample_id AND {ACCESS})''',
            (body.newsletter_id,user_id,user_id)).fetchone()
    if not row or not row['html_content']:raise HTTPException(404,'발송할 뉴스레터를 찾을 수 없습니다.')
    return dict(row)


def mail_tls_context():
    settings={**dotenv_values(PROJECT_DIR/'.env'),**os.environ}
    context=ssl.create_default_context(cafile=settings.get('GMAIL_CA_BUNDLE') or None)
    if settings.get('GMAIL_LEGACY_CA')=='1':
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def deliver(sender,password,recipients,title,html,*,prepared=None,raw_html=False,text_body=None):
    recipients=list(dict.fromkeys(address.strip().casefold() for address in recipients))
    message=EmailMessage()
    message['From']=formataddr(('WiaNews',sender))
    message['To']=', '.join(recipients)
    message['Subject']='[WiaNews] '+' '.join(title.split())
    message['Date']=formatdate(localtime=False)
    message['Message-ID']=make_msgid(domain=sender.split('@')[-1])
    message.set_content(text_body or 'WiaNews 기술 뉴스레터입니다. HTML을 지원하는 메일 앱에서 확인해 주세요.')
    sources,attachments=prepared if prepared is not None else prepare_inline_images(html)
    message.add_alternative(html if raw_html else email_html(html,sources),subtype='html')
    html_part=message.get_payload()[-1]
    for image in attachments:
        html_part.add_related(image['data'],maintype='image',subtype='jpeg',
            cid='<'+image['cid']+'>',filename=image['filename'],disposition='inline')
    # Submit one MIME message with all selected addresses in To and SMTP RCPT TO.
    stage='connect'
    smtp=None
    try:
        smtp=smtplib.SMTP_SSL('smtp.gmail.com',465,local_hostname='wianews.local',timeout=25,context=mail_tls_context())
        # Same verified handshake as AI Lounge: EHLO is disconnected on this network.
        code,reply=smtp.helo('wianews.local')
        if code!=250:raise smtplib.SMTPHeloError(code,reply)
        token=base64.b64encode(('\0'+sender+'\0'+password).encode('utf-8')).decode('ascii')
        code,reply=smtp.docmd('AUTH','PLAIN '+token)
        if code!=235:raise smtplib.SMTPAuthenticationError(code,reply)
        stage='send'
        refused=smtp.send_message(message,from_addr=sender,to_addrs=recipients)
        rejected={address.casefold() for address in refused}
        return {address:('failed' if address in rejected else 'sent') for address in recipients}
    except (smtplib.SMTPAuthenticationError,smtplib.SMTPRecipientsRefused,smtplib.SMTPSenderRefused,smtplib.SMTPDataError):
        return {address:'failed' for address in recipients}
    except (OSError,smtplib.SMTPException):
        # An interrupted DATA response may already have been accepted; never retry automatically.
        return {address:('unknown' if stage=='send' else 'failed') for address in recipients}
    finally:
        if smtp:
            try:smtp.close()
            except OSError:pass


@router.post('')
def send_newsletter(body: SendBody,user=Depends(tracked_member_user)):
    members={recipient_key(m.model_dump()):m for m in body.members()}
    keys=sorted(members)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT * FROM mailing WHERE user_id=? AND request_id=?',
            (user['user_id'],body.request_id)).fetchone()
        if existing:
            if (existing['kind'],existing['newsletter_id'],sorted(set(recipient_key(r) for r in json.loads(existing['mailing_list']))))!=(body.kind,body.newsletter_id,keys):
                raise HTTPException(409,'다른 발송 요청에 사용된 ID입니다.')
            if existing['status']=='processing':raise HTTPException(409,'발송 처리 중이거나 결과를 확인 중입니다. 중복 발송하지 말고 잠시 후 확인해 주세요.')
            return {'mailing_id':existing['mailing_id'],'results':json.loads(existing['results_json'])}
        letter=load_letter(db,body,user['user_id'])
        recipients=[]
        for key in keys:
            member=members[key]
            if member.member_type=='internal':
                row=db.execute('SELECT user_id,full_name,email FROM users WHERE user_id=? AND is_active=1 AND is_admin=0',(member.user_id,)).fetchone()
                if not row or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',row['email'] or ''):
                    raise HTTPException(422,'이메일이 없거나 사용할 수 없는 수신자가 있습니다. 선택 목록을 확인해 주세요.')
                recipients.append({'member_type':'internal','user_id':row['user_id'],'name':row['full_name'],'email_address':row['email'].strip().lower()})
            else:
                recipients.append({'member_type':'external','user_id':None,'name':member.email_address,'email_address':member.email_address})
        sender,password=mail_settings()
        mailing_id=str(uuid.uuid4())
        mailing_list=recipients
        db.execute("""INSERT INTO mailing (mailing_id,user_id,request_id,kind,newsletter_id,subject,sender_email,
            mailing_list,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (mailing_id,user['user_id'],body.request_id,body.kind,body.newsletter_id,
             '[WiaNews] '+' '.join(letter['title'].split()),sender,
             json.dumps(mailing_list,ensure_ascii=False),'processing',now()))
    prepared=prepare_inline_images(letter['html_content'])
    addresses=list(dict.fromkeys(r['email_address'].casefold() for r in recipients))
    statuses=deliver(sender,password,addresses,letter['title'],letter['html_content'],prepared=prepared)
    completed_at=now()
    results=[{**r,'status':statuses[r['email_address'].casefold()],
        'sent_at':completed_at if statuses[r['email_address'].casefold()]=='sent' else None,
        'completed_at':completed_at} for r in recipients]
    with database() as db:
        db.execute("""UPDATE mailing SET results_json=?,sent_at=?,status='completed',completed_at=?
            WHERE user_id=? AND request_id=?""",
            (json.dumps(results,ensure_ascii=False),completed_at if any(r['status']=='sent' for r in results) else None,
             completed_at,user['user_id'],body.request_id))
    return {'mailing_id':mailing_id,'results':results}


@router.get('/history')
def mailing_history(user=Depends(tracked_member_user)):
    with database() as db:
        rows=db.execute('SELECT * FROM mailing WHERE user_id=? ORDER BY created_at DESC LIMIT 200',(user['user_id'],)).fetchall()
        return [{**dict(row),'mailing_list':json.loads(row['mailing_list']),
                 'results_json':json.loads(row['results_json'])} for row in rows]
