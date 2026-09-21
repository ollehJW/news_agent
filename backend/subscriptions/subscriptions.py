"""Subscription persistence; collection and publication are separate workflows."""
import uuid
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal
from backend.core.auth import database, now
from backend.core.error_storage import ErrorRoute, tracked_member_user as member_user

router=APIRouter(prefix='/api/subscriptions',route_class=ErrorRoute,dependencies=[Depends(member_user)])


def owned_subscription(db,subscription_id,user_id):
    row=db.execute('SELECT * FROM subscriptions WHERE subscription_id=? AND user_id=?',(subscription_id,user_id)).fetchone()
    if not row:
        raise HTTPException(404,'구독을 찾을 수 없습니다.')
    return row


def subscribable_sample(db,sample_id,user_id):
    row=db.execute("""SELECT * FROM sample_details n
        WHERE n.sample_id=? AND n.status='completed' AND
        ((n.user_id=? AND n.saved_at IS NOT NULL) OR
         EXISTS(SELECT 1 FROM subscriptions s WHERE s.sample_id=n.sample_id))""",(sample_id,user_id)).fetchone()
    if not row:
        raise HTTPException(404,'구독할 수 있는 뉴스레터를 찾을 수 없습니다.')
    return row


def sample_info(db,sample_id):
    row=db.execute('SELECT * FROM sample_details WHERE sample_id=?',(sample_id,)).fetchone()
    domains=[r[0] for r in db.execute('SELECT d.host FROM sample_domains sd JOIN domains d USING(domain_id) WHERE sd.sample_id=? ORDER BY d.host',(sample_id,))]
    count=db.execute('SELECT count(*) FROM sample_issues WHERE sample_id=?',(sample_id,)).fetchone()[0]
    return {'id':sample_id,'title':row['topic'],'topic':row['topic'],'date':(row['saved_at'] or row['completed_at'] or row['created_at'])[:10],
            'count':count,'domains':domains}


class StatusBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status: Literal['active','paused','cancelled']



class SettingsBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(min_length=1,max_length=80)
    frequency: Literal['daily','weekly','monthly']
    weekdays: list[int]=Field(default_factory=list,max_length=7)
    month_day: int=Field(default=1,ge=1,le=31,strict=True)
    start_date: date

    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        value=value.strip()
        if not value: raise ValueError('구독 이름을 입력해 주세요.')
        return value

    @field_validator('weekdays',mode='before')
    @classmethod
    def valid_days(cls,value):
        if not isinstance(value,list) or any(type(d) is not int or d<0 or d>6 for d in value):
            raise ValueError('발행 요일을 확인해 주세요.')
        return sorted(set(value))

    @model_validator(mode='after')
    def weekly_days(self):
        if self.frequency=='weekly' and not self.weekdays:
            raise ValueError('발행 요일을 선택해 주세요.')
        return self


class CreateBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sample_id: str=Field(min_length=1,max_length=100)
    settings: SettingsBody | None=None


def write_settings(db,sid,settings):
    db.execute('''INSERT INTO subscription_settings (subscription_id,name,frequency,weekdays,month_day,start_date)
        VALUES (?,?,?,?,?,?) ON CONFLICT(subscription_id) DO UPDATE SET
        name=excluded.name,frequency=excluded.frequency,weekdays=excluded.weekdays,
        month_day=excluded.month_day,start_date=excluded.start_date''',
        (sid,settings.name,settings.frequency,json.dumps(settings.weekdays),settings.month_day,settings.start_date.isoformat()))


def settings_info(row,topic):
    return {'name':row['name'] if row else topic,'frequency':row['frequency'] if row else 'weekly',
            'weekdays':json.loads(row['weekdays']) if row else [1],'monthDay':row['month_day'] if row else 1,
            'startDate':row['start_date'] if row else None,'time':'08:00'}


def subscription_info(db,row):
    sample=sample_info(db,row['sample_id'])
    settings=db.execute('SELECT * FROM subscription_settings WHERE subscription_id=?',(row['subscription_id'],)).fetchone()
    return {**dict(row),'id':row['subscription_id'],'newsletterId':row['sample_id'],
            'active':row['status']=='active','newsletter':sample,**settings_info(settings,sample['topic'])}


@router.get('')
def list_subscriptions(user=Depends(member_user)):
    with database() as db:
        rows=db.execute("SELECT * FROM subscriptions WHERE user_id=? AND status!='cancelled' ORDER BY created_at DESC,subscription_id",(user['user_id'],)).fetchall()
        return [subscription_info(db,row) for row in rows]


@router.get('/marketplace')
def marketplace(user=Depends(member_user)):
    with database() as db:
        samples=db.execute("""SELECT n.sample_id,(SELECT min(s.created_at) FROM subscriptions s WHERE s.sample_id=n.sample_id) AS registered_at FROM sample_details n
            WHERE n.status='completed' AND EXISTS(SELECT 1 FROM subscriptions s WHERE s.sample_id=n.sample_id)
            ORDER BY n.created_at DESC,n.sample_id""").fetchall()
        items=[]
        for sample in samples:
            sid=sample['sample_id']
            info=sample_info(db,sid)
            current=db.execute('SELECT status FROM subscriptions WHERE sample_id=? AND user_id=?',(sid,user['user_id'])).fetchone()
            count=db.execute("SELECT count(*) FROM subscriptions WHERE sample_id=? AND status='active'",(sid,)).fetchone()[0]
            first_issued=db.execute('SELECT min(published_at) FROM subscripted_newsletters WHERE sample_id=? AND published_at IS NOT NULL',(sid,)).fetchone()[0]
            items.append({**info,'first_published_at':first_issued,'registered_at':sample['registered_at'],'sample_id':sid,'subscriberCount':count,
                          'subscribed':bool(current and current['status']!='cancelled'),
                          'subscriptionStatus':current['status'] if current else None})
        return items


@router.get('/archive')
def subscription_archive(response: Response,user=Depends(member_user)):
    response.headers['Cache-Control']='no-store'
    with database() as db:
        # Keep historical deliveries accessible after cancellation.
        subscriptions=db.execute("""SELECT s.subscription_id AS id,
            COALESCE(st.name,n.topic) AS name, s.status
            FROM subscriptions s JOIN sample_details n ON n.sample_id=s.sample_id
            LEFT JOIN subscription_settings st USING(subscription_id)
            WHERE s.user_id=? ORDER BY name,s.subscription_id""",(user['user_id'],)).fetchall()
        editions=db.execute("""SELECT h.subscription_id,n.newsletter_id AS id,
            d.topic AS title,n.coverage_start_date,n.coverage_end_date,n.published_at,
            h.created_at AS received_at,json_array_length(n.issue_ids) AS count
            FROM subscription_history h
            JOIN subscriptions s USING(subscription_id)
            JOIN subscripted_newsletters n ON n.newsletter_id=h.newsletter_id AND n.sample_id=s.sample_id
            JOIN sample_details d ON d.sample_id=n.sample_id
            WHERE s.user_id=? AND n.published_at IS NOT NULL
            ORDER BY h.created_at DESC,n.newsletter_id DESC""",(user['user_id'],)).fetchall()
        return {'subscriptions':[dict(row) for row in subscriptions],
                'newsletters':[dict(row) for row in editions]}


@router.get('/archive/{newsletter_id}')
def archived_newsletter(newsletter_id: str,response: Response,user=Depends(member_user)):
    response.headers['Cache-Control']='no-store'
    with database() as db:
        row=db.execute("""SELECT n.newsletter_id AS id,d.topic AS title,n.html_content AS html
            FROM subscripted_newsletters n JOIN sample_details d ON d.sample_id=n.sample_id
            WHERE n.newsletter_id=? AND n.published_at IS NOT NULL AND EXISTS(
                SELECT 1 FROM subscription_history h JOIN subscriptions s USING(subscription_id)
                WHERE h.newsletter_id=n.newsletter_id AND s.sample_id=n.sample_id AND s.user_id=?)""",
            (newsletter_id,user['user_id'])).fetchone()
        if not row: raise HTTPException(404,'전달받은 뉴스레터를 찾을 수 없습니다.')
        return dict(row)


@router.get('/marketplace/{sample_id}/preview')
def preview_newsletter(sample_id: str,response: Response,user=Depends(member_user)):
    response.headers['Cache-Control']='no-store'
    with database() as db:
        sample=subscribable_sample(db,sample_id,user['user_id'])
        edition=None
        if sample['last_issued_newsletter_id']:
            edition=db.execute("""SELECT * FROM subscripted_newsletters
                WHERE newsletter_id=? AND sample_id=? AND published_at IS NOT NULL""",
                (sample['last_issued_newsletter_id'],sample_id)).fetchone()
        if edition:
            return {'sample_id':sample_id,'newsletter_id':edition['newsletter_id'],'kind':'published',
                    'topic':sample['topic'],'html':edition['html_content'],'published_at':edition['published_at'],
                    'dates':{'start':edition['coverage_start_date'],'end':edition['coverage_end_date']}}
        return {'sample_id':sample_id,'newsletter_id':None,'kind':'sample','topic':sample['topic'],
                'html':sample['html_content'],'published_at':None,
                'dates':{'start':sample['collection_start_date'],'end':sample['collection_end_date']}}


@router.post('')
def create_subscription(body: CreateBody,response: Response,user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        sample=subscribable_sample(db,body.sample_id,user['user_id'])
        existing=db.execute('SELECT * FROM subscriptions WHERE sample_id=? AND user_id=?',(body.sample_id,user['user_id'])).fetchone()
        if existing and existing['status']!='cancelled':
            return subscription_info(db,existing)
        settings=body.settings
        if settings is None:
            settings=SettingsBody(name=sample['topic'][:80],frequency='weekly',weekdays=[1],
                month_day=1,start_date=datetime.now(ZoneInfo('Asia/Seoul')).date())
        stamp=now()
        if existing:
            sid=existing['subscription_id']
            db.execute("UPDATE subscriptions SET status='active',updated_at=? WHERE subscription_id=?",(stamp,sid))
        else:
            sid=str(uuid.uuid4())
            db.execute("INSERT INTO subscriptions (subscription_id,sample_id,user_id,status,created_at,updated_at) VALUES (?,?,?,'active',?,?)",(sid,body.sample_id,user['user_id'],stamp,stamp))
            response.status_code=201
        write_settings(db,sid,settings)
        return subscription_info(db,owned_subscription(db,sid,user['user_id']))


@router.put('/{subscription_id}/settings')
def update_settings(subscription_id: str,body: SettingsBody,user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=owned_subscription(db,subscription_id,user['user_id'])
        if row['status']=='cancelled': raise HTTPException(409,'해지한 구독은 재구독 후 수정해 주세요.')
        write_settings(db,subscription_id,body)
        db.execute('UPDATE subscriptions SET updated_at=? WHERE subscription_id=?',(now(),subscription_id))
        return subscription_info(db,owned_subscription(db,subscription_id,user['user_id']))


@router.patch('/{subscription_id}/status')
def update_status(subscription_id: str,body: StatusBody,user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        owned_subscription(db,subscription_id,user['user_id'])
        db.execute('UPDATE subscriptions SET status=?,updated_at=? WHERE subscription_id=?',(body.status,now(),subscription_id))
        return subscription_info(db,owned_subscription(db,subscription_id,user['user_id']))


@router.delete('/{subscription_id}')
def cancel_subscription(subscription_id: str,user=Depends(member_user)):
    return update_status(subscription_id,StatusBody(status='cancelled'),user)
