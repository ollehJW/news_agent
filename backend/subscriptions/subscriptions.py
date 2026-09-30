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

from backend.subscriptions.members import MemberBody,write_members,members_info,ACCESS

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
            'queries':[r[0] for r in db.execute('SELECT query FROM sample_queries WHERE sample_id=? ORDER BY position',(sample_id,))],'count':count,'domains':domains,'search_all_domains':bool(row['search_all_domains'])}


class StatusBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status: Literal['active','paused','cancelled']



class SettingsBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    members: list[MemberBody] | None=Field(default=None,max_length=100)
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


class JoinBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(min_length=1,max_length=80)
    members: list[MemberBody] | None=Field(default=None,max_length=100)

    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        value=value.strip()
        if not value:raise ValueError('구독 이름을 입력해 주세요.')
        return value


class EditBody(JoinBody):
    members: list[MemberBody] | None=Field(default=None,max_length=100)


class CreateBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    sample_id: str=Field(min_length=1,max_length=100)
    settings: SettingsBody | None=None
    join: JoinBody | None=None

    @model_validator(mode='after')
    def one_settings_source(self):
        if self.join is not None and self.settings is not None:raise ValueError('기존 구독의 발행 설정은 변경할 수 없습니다.')
        return self


def write_settings(db,sid,settings):
    if settings.members is not None:write_members(db,sid,settings.members)
    db.execute('''INSERT INTO subscription_settings (subscription_id,name,frequency,weekdays,month_day,start_date)
        VALUES (?,?,?,?,?,?) ON CONFLICT(subscription_id) DO UPDATE SET
        name=excluded.name,frequency=excluded.frequency,weekdays=excluded.weekdays,
        month_day=excluded.month_day,start_date=excluded.start_date''',
        (sid,settings.name,settings.frequency,json.dumps(settings.weekdays),settings.month_day,settings.start_date.isoformat()))


def settings_info(row,topic):
    return {'name':row['name'] if row else topic,'frequency':row['frequency'] if row else 'weekly',
            'weekdays':json.loads(row['weekdays']) if row else [1],'monthDay':row['month_day'] if row else 1,
            'startDate':row['start_date'] if row else None,'time':'08:00'}


def subscription_info(db,row,viewer_id=None):
    sample=sample_info(db,row['sample_id'])
    settings=db.execute('SELECT * FROM subscription_settings WHERE subscription_id=?',(row['subscription_id'],)).fetchone()
    viewer=viewer_id or row['user_id']
    can_manage=viewer==row['user_id']
    members=[{**m,'is_self':m['user_id']==viewer} for m in members_info(db,row['subscription_id'])]
    own=next((m for m in members if m['is_self']),None)
    active=own['status']=='active' if own else any(m['status']=='active' for m in members)
    return {**dict(row),'can_manage':can_manage,'members':members if can_manage else [m for m in members if m['is_self']],
            'id':row['subscription_id'],'newsletterId':row['sample_id'],
            'active':row['status']=='active' and active,'newsletter':sample,**settings_info(settings,sample['topic'])}



@router.get('')
def list_subscriptions(user=Depends(member_user)):
    with database() as db:
        rows=db.execute(f"SELECT s.* FROM subscriptions s WHERE {ACCESS} AND s.status!='cancelled' ORDER BY s.created_at DESC,s.subscription_id",(user['user_id'],user['user_id'])).fetchall()
        return [subscription_info(db,row,user['user_id']) for row in rows]


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
            current=db.execute(f"SELECT s.* FROM subscriptions s WHERE s.sample_id=? AND {ACCESS} AND s.status!='cancelled' ORDER BY CASE s.status WHEN 'active' THEN 0 ELSE 1 END LIMIT 1",(sid,user['user_id'],user['user_id'])).fetchone()
            count=db.execute("""SELECT count(DISTINCT lower(trim(CASE WHEN m.member_type='internal' THEN u.email ELSE m.email_address END)))
                FROM subscriptions s JOIN subscription_members m USING(subscription_id)
                LEFT JOIN users u ON u.user_id=m.user_id
                WHERE s.sample_id=? AND s.status='active' AND m.status='active'
                AND (m.member_type='external' OR u.is_active=1)
                AND trim(COALESCE(u.email,m.email_address,''))!=''""",(sid,)).fetchone()[0]
            publication_schedules=[]
            seen_schedules=set()
            for schedule in db.execute("""SELECT st.* FROM subscriptions s
                LEFT JOIN subscription_settings st USING(subscription_id)
                WHERE s.sample_id=? AND s.status!='cancelled'
                ORDER BY s.created_at,s.subscription_id""",(sid,)):
                setting=settings_info(schedule if schedule['subscription_id'] else None,info['topic'])
                frequency=setting['frequency']
                weekdays=sorted(set(setting['weekdays'])) if frequency=='weekly' else []
                month_day=setting['monthDay'] if frequency=='monthly' else None
                key=(frequency,tuple(weekdays),month_day)
                if key not in seen_schedules:
                    seen_schedules.add(key)
                    publication_schedules.append({'frequency':frequency,'weekdays':weekdays,'monthDay':month_day})
            publication_schedules.sort(key=lambda s:({'daily':0,'weekly':1,'monthly':2}[s['frequency']],s['weekdays'],s['monthDay'] or 0))
            publication=db.execute('SELECT min(published_at),count(*) FROM subscripted_newsletters WHERE sample_id=? AND published_at IS NOT NULL',(sid,)).fetchone()
            first_issued,published_count=publication
            items.append({**info,'publication_schedules':publication_schedules,'published_count':published_count,'first_published_at':first_issued,'registered_at':sample['registered_at'],'sample_id':sid,'subscriberCount':count,
                          'subscribed':bool(current and current['status']!='cancelled'),
                          'subscriptionStatus':('active' if subscription_info(db,current,user['user_id'])['active'] else 'paused') if current else None})
        return items


@router.get('/archive')
def subscription_archive(response: Response,user=Depends(member_user)):
    response.headers['Cache-Control']='no-store'
    with database() as db:
        # Keep historical deliveries accessible after cancellation.
        subscriptions=db.execute(f"""SELECT s.subscription_id AS id,
            COALESCE(st.name,n.topic) AS name, s.status
            FROM subscriptions s JOIN sample_details n ON n.sample_id=s.sample_id
            LEFT JOIN subscription_settings st USING(subscription_id)
            WHERE {ACCESS} ORDER BY name,s.subscription_id""",(user['user_id'],user['user_id'])).fetchall()
        editions=db.execute(f"""SELECT h.subscription_id,n.newsletter_id AS id,
            d.topic AS title,n.coverage_start_date,n.coverage_end_date,n.published_at,
            h.created_at AS received_at,json_array_length(n.issue_ids) AS count
            FROM subscription_history h
            JOIN subscriptions s USING(subscription_id)
            JOIN subscripted_newsletters n ON n.newsletter_id=h.newsletter_id AND n.sample_id=s.sample_id
            JOIN sample_details d ON d.sample_id=n.sample_id
            WHERE {ACCESS} AND n.published_at IS NOT NULL
            ORDER BY h.created_at DESC,n.newsletter_id DESC""",(user['user_id'],user['user_id'])).fetchall()
        return {'subscriptions':[dict(row) for row in subscriptions],
                'newsletters':[dict(row) for row in editions]}


@router.get('/archive/{newsletter_id}')
def archived_newsletter(newsletter_id: str,response: Response,user=Depends(member_user)):
    response.headers['Cache-Control']='no-store'
    with database() as db:
        row=db.execute(f"""SELECT n.newsletter_id AS id,d.topic AS title,n.html_content AS html
            FROM subscripted_newsletters n JOIN sample_details d ON d.sample_id=n.sample_id
            WHERE n.newsletter_id=? AND n.published_at IS NOT NULL AND EXISTS(
                SELECT 1 FROM subscription_history h JOIN subscriptions s USING(subscription_id)
                WHERE h.newsletter_id=n.newsletter_id AND s.sample_id=n.sample_id AND {ACCESS})""",
            (newsletter_id,user['user_id'],user['user_id'])).fetchone()
        if not row: raise HTTPException(404,'전달받은 뉴스레터를 찾을 수 없습니다.')
        return dict(row)


@router.get('/marketplace/{sample_id}/conditions')
def collection_conditions(sample_id: str,response: Response,user=Depends(member_user)):
    response.headers['Cache-Control']='no-store'
    with database() as db:
        subscribable_sample(db,sample_id,user['user_id'])
        return sample_info(db,sample_id)


@router.get('/marketplace/{sample_id}/preview')
def preview_newsletter(sample_id: str,response: Response,newsletter_id: str | None=None,user=Depends(member_user)):
    response.headers['Cache-Control']='no-store'
    with database() as db:
        sample=subscribable_sample(db,sample_id,user['user_id'])
        editions=[{**dict(row),'issue_number':index} for index,row in enumerate(db.execute(
            """SELECT newsletter_id,published_at,coverage_start_date,coverage_end_date
            FROM subscripted_newsletters WHERE sample_id=? AND published_at IS NOT NULL
            ORDER BY published_at,created_at,newsletter_id""",(sample_id,)),1)]
        by_id={e['newsletter_id']:e for e in editions}
        selected=newsletter_id or (sample['last_issued_newsletter_id'] if sample['last_issued_newsletter_id'] in by_id else editions[-1]['newsletter_id'] if editions else None)
        if newsletter_id and newsletter_id not in by_id:
            raise HTTPException(404,'해당 뉴스레터의 발행본을 찾을 수 없습니다.')
        if selected:
            edition=db.execute('SELECT * FROM subscripted_newsletters WHERE newsletter_id=? AND sample_id=?',(selected,sample_id)).fetchone()
            return {'sample_id':sample_id,'newsletter_id':selected,'kind':'published',
                    'issue_number':by_id[selected]['issue_number'],'editions':editions,
                    'topic':sample['topic'],'html':edition['html_content'],'published_at':edition['published_at'],
                    'dates':{'start':edition['coverage_start_date'],'end':edition['coverage_end_date']}}
        return {'sample_id':sample_id,'newsletter_id':None,'kind':'sample','issue_number':None,'editions':[],
                'topic':sample['topic'],'html':sample['html_content'],'published_at':None,
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
        if body.join is not None:
            # Cards group by sample. Prefer the earliest active schedule, then paused/history.
            source=db.execute("""SELECT st.* FROM subscriptions s JOIN subscription_settings st USING(subscription_id)
                WHERE s.sample_id=? ORDER BY CASE s.status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,
                s.created_at,s.subscription_id LIMIT 1""",(body.sample_id,)).fetchone()
            if not source:raise HTTPException(409,'기존 구독의 발행 설정을 찾을 수 없습니다.')
            settings=SettingsBody(name=body.join.name,members=body.join.members,
                frequency=source['frequency'],weekdays=json.loads(source['weekdays']),
                month_day=source['month_day'],start_date=source['start_date'])
        if settings is None:
            settings=SettingsBody(name=sample['topic'][:80],frequency='weekly',weekdays=[1],
                month_day=1,start_date=datetime.now(ZoneInfo('Asia/Seoul')).date())
        if not existing and settings.members is None:
            settings.members=[MemberBody(member_type='internal',user_id=user['user_id'])]
        if existing:
            saved=db.execute('SELECT * FROM subscription_settings WHERE subscription_id=?',(existing['subscription_id'],)).fetchone()
            if saved:
                previous={'frequency':saved['frequency'],'weekdays':json.loads(saved['weekdays']),
                    'month_day':saved['month_day'],'start_date':date.fromisoformat(saved['start_date'])}
                if body.settings is not None and any(getattr(body.settings,key)!=value for key,value in previous.items()):
                    raise HTTPException(409,'한 번 생성한 구독의 발행 설정은 변경할 수 없습니다.')
                settings=SettingsBody(name=settings.name,members=settings.members,**previous)
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
def update_settings(subscription_id: str,body: EditBody,user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=owned_subscription(db,subscription_id,user['user_id'])
        if row['status']=='cancelled': raise HTTPException(409,'해지한 구독은 재구독 후 수정해 주세요.')
        if not db.execute('SELECT 1 FROM subscription_settings WHERE subscription_id=?',(subscription_id,)).fetchone():
            raise HTTPException(409,'기존 구독 설정을 찾을 수 없습니다.')
        if body.members is not None:write_members(db,subscription_id,body.members)
        db.execute('UPDATE subscription_settings SET name=? WHERE subscription_id=?',(body.name,subscription_id))
        db.execute('UPDATE subscriptions SET updated_at=? WHERE subscription_id=?',(now(),subscription_id))
        return subscription_info(db,owned_subscription(db,subscription_id,user['user_id']))


@router.patch('/{subscription_id}/status')
def update_status(subscription_id: str,body: StatusBody,user=Depends(member_user)):
    if body.status!='cancelled':raise HTTPException(422,'멤버별 수신 상태를 변경해 주세요.')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        owned_subscription(db,subscription_id,user['user_id'])
        db.execute('UPDATE subscriptions SET status=?,updated_at=? WHERE subscription_id=?',(body.status,now(),subscription_id))
        return subscription_info(db,owned_subscription(db,subscription_id,user['user_id']))


@router.delete('/{subscription_id}')
def cancel_subscription(subscription_id: str,user=Depends(member_user)):
    return update_status(subscription_id,StatusBody(status='cancelled'),user)


@router.delete('/{subscription_id}/members/me')
def leave_subscription(subscription_id: str,user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT user_id FROM subscriptions WHERE subscription_id=?',(subscription_id,)).fetchone()
        if not row:raise HTTPException(404,'구독을 찾을 수 없습니다.')
        if row['user_id']==user['user_id']:
            raise HTTPException(409,'구독 관리자는 멤버 수정 또는 구독 종료를 이용해 주세요.')
        deleted=db.execute("DELETE FROM subscription_members WHERE subscription_id=? AND member_type='internal' AND user_id=?",(subscription_id,user['user_id'])).rowcount
        if not deleted:raise HTTPException(404,'수신 멤버로 등록된 구독이 아닙니다.')
        db.execute('UPDATE subscriptions SET updated_at=? WHERE subscription_id=?',(now(),subscription_id))
        return {'subscription_id':subscription_id,'left':True}


class RemoveMembersBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    member_ids: list[str]=Field(max_length=100)


@router.post('/{subscription_id}/members/remove')
def remove_subscription_members(subscription_id: str,body: RemoveMembersBody,user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=owned_subscription(db,subscription_id,user['user_id'])
        if row['status']=='cancelled':raise HTTPException(409,'이미 종료된 구독입니다.')
        members={r['member_id'] for r in db.execute('SELECT member_id FROM subscription_members WHERE subscription_id=?',(subscription_id,))}
        selected=set(body.member_ids)
        if (not selected and members) or not selected.issubset(members):raise HTTPException(409,'수신 멤버가 변경되었습니다. 목록을 새로 불러와 주세요.')
        db.executemany('DELETE FROM subscription_members WHERE subscription_id=? AND member_id=?',[(subscription_id,mid) for mid in selected])
        status=row['status'] if members-selected else 'cancelled'
        db.execute('UPDATE subscriptions SET status=?,updated_at=? WHERE subscription_id=?',(status,now(),subscription_id))
        return subscription_info(db,owned_subscription(db,subscription_id,user['user_id']))


class MemberStatusBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    member_ids: list[str]=Field(min_length=1,max_length=100)
    status: Literal['active','paused']


@router.patch('/{subscription_id}/members/status')
def update_member_status(subscription_id: str,body: MemberStatusBody,user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute(f"SELECT s.* FROM subscriptions s WHERE s.subscription_id=? AND {ACCESS}",
            (subscription_id,user['user_id'],user['user_id'])).fetchone()
        if not row:raise HTTPException(404,'구독을 찾을 수 없습니다.')
        if row['status']=='cancelled':raise HTTPException(409,'이미 종료된 구독입니다.')
        members={r['member_id']:r for r in db.execute('SELECT * FROM subscription_members WHERE subscription_id=?',(subscription_id,))}
        selected=set(body.member_ids)
        if not selected.issubset(members):raise HTTPException(409,'수신 멤버가 변경되었습니다. 목록을 새로 불러와 주세요.')
        if row['user_id']!=user['user_id'] and any(members[mid]['user_id']!=user['user_id'] for mid in selected):
            raise HTTPException(403,'본인의 수신 상태만 변경할 수 있습니다.')
        db.executemany('UPDATE subscription_members SET status=? WHERE subscription_id=? AND member_id=?',
            [(body.status,subscription_id,mid) for mid in selected])
        db.execute('UPDATE subscriptions SET updated_at=? WHERE subscription_id=?',(now(),subscription_id))
        return subscription_info(db,db.execute('SELECT * FROM subscriptions WHERE subscription_id=?',(subscription_id,)).fetchone(),user['user_id'])
