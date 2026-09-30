"""Subscription source feedback and durable administrator-result notifications."""
import json
import re
from uuid import UUID
from pathlib import Path
from typing import Literal
from jinja2 import Environment,FileSystemLoader,select_autoescape
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from backend.core.auth import database,now,admin_user,member_user
from backend.subscriptions.members import ACCESS
from backend.subscriptions.subscriptions import sample_info
from backend.mail import delivery
from backend.admin.subscriptions import SourceConditions,PublicationUpdate,detail as subscription_detail,update_publication_in_db

router=APIRouter(prefix='/api')
templates=Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1]/'template'),autoescape=select_autoescape(['html']))


def init_feedback_db():
    with database() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS subscription_feedback (
            feedback_id TEXT PRIMARY KEY,
            subscription_id TEXT REFERENCES subscriptions(subscription_id) ON DELETE SET NULL,
            sample_id TEXT REFERENCES sample_newsletters(sample_id) ON DELETE SET NULL,
            user_id TEXT REFERENCES users(user_id) ON DELETE SET NULL,
            requester_name TEXT NOT NULL,requester_email TEXT NOT NULL,
            subscription_name TEXT NOT NULL,topic TEXT NOT NULL,
            conditions_json TEXT NOT NULL CHECK(json_valid(conditions_json) AND json_type(conditions_json)='object'),content TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','held')),
            revision INTEGER NOT NULL DEFAULT 0,
            response TEXT,handled_by TEXT REFERENCES users(user_id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,handled_at TEXT,
            notifications_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(notifications_json) AND json_type(notifications_json)='array'))''')
        db.execute('CREATE INDEX IF NOT EXISTS feedback_status_created ON subscription_feedback(status,created_at)')
        # A process may have stopped after SMTP accepted the message. Do not resend.
        for row in db.execute("SELECT feedback_id,notifications_json FROM subscription_feedback"):
            events=json.loads(row['notifications_json']);changed=False
            for event in events:
                if event['mail_status']=='processing':event['mail_status']='unknown';changed=True
            if changed:db.execute('UPDATE subscription_feedback SET notifications_json=? WHERE feedback_id=?',(json.dumps(events,ensure_ascii=False),row['feedback_id']))


def unpack(row):
    value=dict(row)
    value['conditions']=json.loads(value.pop('conditions_json'))
    value['notifications']=json.loads(value.pop('notifications_json'))
    return value


class FeedbackBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: UUID
    content: str=Field(min_length=10,max_length=4000)

    @field_validator('content')
    @classmethod
    def clean(cls,value):
        value=value.strip()
        if len(value)<10:raise ValueError('변경할 쿼리·도메인과 이유를 10자 이상 작성해 주세요.')
        return value


@router.post('/subscriptions/{sid}/feedback')
def create_feedback(sid: str,body: FeedbackBody,user=Depends(member_user)):
    fid=str(body.request_id)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        sub=db.execute(f"SELECT s.* FROM subscriptions s WHERE s.subscription_id=? AND s.status!='cancelled' AND {ACCESS}",(sid,user['user_id'],user['user_id'])).fetchone()
        if not sub:raise HTTPException(404,'피드백을 요청할 수 있는 구독을 찾을 수 없습니다.')
        existing=db.execute('SELECT * FROM subscription_feedback WHERE feedback_id=?',(fid,)).fetchone()
        if existing:
            if existing['user_id']!=user['user_id'] or existing['subscription_id']!=sid or existing['content']!=body.content:raise HTTPException(409,'다른 요청에 사용된 요청 ID입니다.')
            return {'feedback_id':fid,'status':existing['status']}
        person=db.execute('SELECT full_name,email FROM users WHERE user_id=?',(user['user_id'],)).fetchone()
        email=person['email'].strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise HTTPException(422,'처리 결과를 받을 이메일이 없습니다. 관리자에게 계정 이메일 등록을 요청해 주세요.')
        sample=sample_info(db,sub['sample_id'])
        setting=db.execute('SELECT name FROM subscription_settings WHERE subscription_id=?',(sid,)).fetchone()
        conditions={k:sample[k] for k in ('queries','domains','search_all_domains')}
        db.execute('''INSERT INTO subscription_feedback(feedback_id,subscription_id,sample_id,user_id,requester_name,requester_email,
            subscription_name,topic,conditions_json,content,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (fid,sid,sub['sample_id'],user['user_id'],person['full_name'],email,setting['name'] if setting else sample['topic'],sample['topic'],json.dumps(conditions,ensure_ascii=False),body.content,now()))
    return {'feedback_id':fid,'status':'pending'}


@router.get('/admin/feedback')
def list_feedback(status: Literal['all','pending','held','completed']='all',offset: int=Query(0,ge=0),user=Depends(admin_user)):
    with database() as db:
        where='WHERE status=?' if status!='all' else '';args=(status,) if status!='all' else ()
        total=db.execute('SELECT count(*) FROM subscription_feedback '+where,args).fetchone()[0]
        items=[unpack(r) for r in db.execute('SELECT * FROM subscription_feedback '+where+' ORDER BY created_at DESC,feedback_id LIMIT 30 OFFSET ?',args+(offset,))]
        counts={r[0]:r[1] for r in db.execute('SELECT status,count(*) FROM subscription_feedback GROUP BY status')}
    return dict(items=items,total=total,counts=counts)


class SourceEdit(SourceConditions):
    revision: str=Field(min_length=64,max_length=64)


class DecisionBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id: UUID
    revision: int=Field(ge=0,strict=True)
    status: Literal['completed','held']
    response: str=Field(min_length=1,max_length=3000)
    sources: SourceEdit | None=None

    @model_validator(mode='after')
    def sources_required(self):
        if self.status=='completed' and self.sources is None:raise ValueError('반영할 쿼리·도메인을 확인해 주세요.')
        if self.status=='held' and self.sources is not None:raise ValueError('보류 시 수집 조건은 변경할 수 없습니다.')
        return self

    @field_validator('response')
    @classmethod
    def clean(cls,value):
        if not value.strip():raise ValueError('처리 내용 또는 보류 이유를 입력해 주세요.')
        return value.strip()


def send_notification(fid,event_id):
    with database() as db:
        row=unpack(db.execute('SELECT * FROM subscription_feedback WHERE feedback_id=?',(fid,)).fetchone())
    event=next(e for e in row['notifications'] if e['id']==event_id)
    label='반영' if event['status']=='completed' else '보류'
    outcome='failed'
    try:
        sender,password=delivery.mail_settings()
        html=templates.get_template('feedback_result.html').render(feedback=row,event=event,status_label=label)
        outcome='unknown'
        results=delivery.deliver(sender,password,[event['email']],f"피드백 {label} · {row['subscription_name']}",html,
            prepared=({},[]),raw_html=True,text_body=f"WiaNews 피드백 {label}\n{row['subscription_name']}\n\n{event['response']}")
        outcome=results.get(event['email'],'unknown')
    except Exception:
        # Configuration/rendering failures are safe failures. Exceptions after
        # entering delivery are ambiguous and must not trigger automatic resends.
        pass
    with database() as db:
        fresh=db.execute('SELECT * FROM subscription_feedback WHERE feedback_id=?',(fid,)).fetchone()
        events=json.loads(fresh['notifications_json'])
        for item in events:
            if item['id']==event_id:item.update(mail_status=outcome,mail_completed_at=now())
        db.execute('UPDATE subscription_feedback SET notifications_json=? WHERE feedback_id=?',(json.dumps(events,ensure_ascii=False),fid))
        return unpack(db.execute('SELECT * FROM subscription_feedback WHERE feedback_id=?',(fid,)).fetchone())


@router.post('/admin/feedback/{fid}/decision')
def decide(fid: str,body: DecisionBody,user=Depends(admin_user)):
    event_id=str(body.request_id)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM subscription_feedback WHERE feedback_id=?',(fid,)).fetchone()
        if not row:raise HTTPException(404,'피드백을 찾을 수 없습니다.')
        events=json.loads(row['notifications_json'])
        prior=next((e for e in events if e['id']==event_id),None)
        if prior:
            if prior['status']!=body.status or prior['response']!=body.response or prior.get('source_input')!=(body.sources.model_dump() if body.sources else None):raise HTTPException(409,'이미 사용된 처리 요청입니다.')
            return unpack(row)
        if any(e['mail_status']=='processing' for e in events):raise HTTPException(409,'처리 결과 메일을 발송 중입니다. 잠시 후 새로고침해 주세요.')
        if row['revision']!=body.revision:raise HTTPException(409,'다른 관리자가 처리한 요청입니다. 새로고침 후 확인해 주세요.')
        if row['status']=='completed':raise HTTPException(409,'이미 반영된 피드백입니다.')
        changes={}
        if body.status=='completed':
            if not row['subscription_id']:raise HTTPException(409,'원본 구독이 없어 반영할 수 없습니다.')
            current=subscription_detail(db,row['subscription_id'])
            if current['sample_id']!=row['sample_id']:raise HTTPException(409,'피드백의 원본 샘플과 구독이 일치하지 않습니다.')
            settings=PublicationUpdate(name=current['name'],frequency=current['frequency'],weekdays=current['weekdays'],
                month_day=current['monthDay'],start_date=current['startDate'] or current['created_at'][:10],**body.sources.model_dump())
            saved=update_publication_in_db(db,row['subscription_id'],settings)
            changes={key:{k:value[k] for k in ('queries','domains','search_all_domains')}
                for key,value in [('before',current),('after',saved)]}
        stamp=now()
        events.append(dict(id=event_id,status=body.status,response=body.response,email=row['requester_email'],handled_by=user['user_id'],handled_at=stamp,mail_status='processing',mail_completed_at=None,source_input=body.sources.model_dump() if body.sources else None,source_changes=changes))
        db.execute('''UPDATE subscription_feedback SET status=?,response=?,handled_by=?,handled_at=?,revision=revision+1,notifications_json=? WHERE feedback_id=?''',
            (body.status,body.response,user['user_id'],stamp,json.dumps(events,ensure_ascii=False),fid))
    return send_notification(fid,event_id)


class RetryBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    event_id: UUID


@router.post('/admin/feedback/{fid}/retry-email')
def retry_email(fid: str,body: RetryBody,user=Depends(admin_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM subscription_feedback WHERE feedback_id=?',(fid,)).fetchone()
        if not row:raise HTTPException(404,'피드백을 찾을 수 없습니다.')
        events=json.loads(row['notifications_json']);event=events[-1] if events else None
        if not event or event['id']!=str(body.event_id) or event['mail_status']!='failed':raise HTTPException(409,'발송 실패가 확인된 최신 결과만 재발송할 수 있습니다.')
        event['mail_status']='processing';event['mail_completed_at']=None
        db.execute('UPDATE subscription_feedback SET notifications_json=? WHERE feedback_id=?',(json.dumps(events,ensure_ascii=False),fid))
    return send_notification(fid,str(body.event_id))
