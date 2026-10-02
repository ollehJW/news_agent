"""Admin-only subscription maintenance with optimistic writes and shared-source guards."""
import hashlib
import json
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from backend.core.auth import admin_user, database, now
from backend.subscriptions.members import MemberBody, members_info
from backend.subscriptions.subscriptions import SettingsBody, settings_info, write_settings
from backend.recommendations.domains import normalize_host

router=APIRouter(prefix='/api/admin/subscriptions',dependencies=[Depends(admin_user)])


def active(db,sid):
    row=db.execute("SELECT * FROM subscriptions WHERE subscription_id=? AND status='active'",(sid,)).fetchone()
    if not row:raise HTTPException(404,'활성 구독을 찾을 수 없습니다.')
    return row


def detail(db,sid):
    sub=active(db,sid)
    sample=db.execute('SELECT * FROM sample_details WHERE sample_id=?',(sub['sample_id'],)).fetchone()
    settings=db.execute('SELECT * FROM subscription_settings WHERE subscription_id=?',(sid,)).fetchone()
    owner=db.execute('''SELECT u.full_name,u.employee_id,t.name AS team_name,r.name AS role_name
        FROM users u LEFT JOIN teams t USING(team_id) LEFT JOIN roles r USING(role_id)
        WHERE u.user_id=?''',(sub['user_id'],)).fetchone()
    result={**dict(sub),**settings_info(settings,sample['topic']), 'topic':sample['topic'],
        'owner_name':owner['full_name'],'owner_employee_id':owner['employee_id'],
        'owner_team_name':owner['team_name'],'owner_role_name':owner['role_name'],
        'members':members_info(db,sid),'search_all_domains':bool(sample['search_all_domains']),
        'queries':[r[0] for r in db.execute('SELECT query FROM sample_queries WHERE sample_id=? ORDER BY position',(sub['sample_id'],))],
        'domains':[r[0] for r in db.execute('SELECT d.host FROM sample_domains sd JOIN domains d USING(domain_id) WHERE sd.sample_id=? ORDER BY host',(sub['sample_id'],))],
        'shared_subscriptions':[dict(r) for r in db.execute('''SELECT s.subscription_id,COALESCE(st.name,?) AS name,u.full_name AS owner_name
            FROM subscriptions s JOIN users u ON u.user_id=s.user_id LEFT JOIN subscription_settings st USING(subscription_id)
            WHERE s.sample_id=? AND s.status='active' ORDER BY s.subscription_id''',(sample['topic'],sub['sample_id']))]}
    result['revision']=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return result


def check_revision(current,revision):
    if current['revision']!=revision:raise HTTPException(409,'다른 사용자가 구독 정보를 변경했습니다. 새로고침 후 다시 수정해 주세요.')


@router.get('')
def list_active_subscriptions():
    with database() as db:
        return [dict(r) for r in db.execute('''SELECT s.subscription_id,s.sample_id,s.created_at,
            COALESCE(st.name,n.topic) AS name,n.topic,u.full_name AS owner_name,u.employee_id AS owner_employee_id,
            COALESCE(st.frequency,'weekly') AS frequency,COALESCE(st.weekdays,'[1]') AS weekdays,
            COALESCE(st.month_day,1) AS month_day,
            (SELECT count(*) FROM subscription_members m WHERE m.subscription_id=s.subscription_id) AS member_count,
            (SELECT count(*) FROM subscription_members m WHERE m.subscription_id=s.subscription_id AND m.status='active') AS active_member_count,
            (SELECT count(*) FROM subscription_history h WHERE h.subscription_id=s.subscription_id) AS issued_count
            FROM subscriptions s JOIN sample_details n USING(sample_id)
            JOIN users u ON u.user_id=s.user_id LEFT JOIN subscription_settings st USING(subscription_id)
            WHERE s.status='active' ORDER BY s.created_at DESC,s.subscription_id''')]


@router.get('/directory')
def directory():
    with database() as db:
        return [dict(r) for r in db.execute('''SELECT u.user_id,u.employee_id,u.full_name,u.email,t.name AS team_name,r.name AS role_name
            FROM users u LEFT JOIN teams t USING(team_id) LEFT JOIN roles r USING(role_id)
            WHERE u.is_active=TRUE AND u.is_admin=FALSE ORDER BY t.name,u.full_name,u.employee_id''')]


@router.get('/{sid}')
def get_subscription(sid: str):
    with database() as db:return detail(db,sid)


class AdminMember(MemberBody):
    status: Literal['active','paused']='active'


class MembersUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision: str=Field(min_length=64,max_length=64)
    members: list[AdminMember]=Field(max_length=100)


@router.put('/{sid}/members')
def update_members(sid: str,body: MembersUpdate):
    with database() as db:
        db.execute("SELECT pg_advisory_xact_lock(741902630)")
        current=detail(db,sid);check_revision(current,body.revision)
        existing={(m['member_type'],m['user_id'] or m['email_address']):m for m in current['members']}
        incoming={}
        for m in body.members:
            key=(m.member_type,m.user_id or m.email_address)
            if key in incoming:raise HTTPException(422,'중복된 구독자가 있습니다.')
            incoming[key]=m
            if m.member_type=='internal' and key not in existing:
                if not db.execute('SELECT 1 FROM users WHERE user_id=? AND is_active=TRUE AND is_admin=FALSE',(m.user_id,)).fetchone():
                    raise HTTPException(422,'활성 일반 사용자를 선택해 주세요.')
        for key,m in existing.items():
            if key not in incoming:db.execute('DELETE FROM subscription_members WHERE member_id=?',(m['member_id'],))
        for key,m in incoming.items():
            if key in existing:
                db.execute('UPDATE subscription_members SET status=? WHERE member_id=?',(m.status,existing[key]['member_id']))
            else:
                db.execute('''INSERT INTO subscription_members(member_id,subscription_id,member_type,user_id,email_address,status,created_at)
                    VALUES(?,?,?,?,?,?,?)''',(str(uuid.uuid4()),sid,m.member_type,m.user_id,m.email_address,m.status,now()))
        db.execute('UPDATE subscriptions SET updated_at=? WHERE subscription_id=?',(now(),sid))
        return detail(db,sid)


class SourceConditions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    queries: list[str]=Field(min_length=1,max_length=5)
    domains: list[str]=Field(default_factory=list,max_length=100)
    search_all_domains: StrictBool=False

    @field_validator('queries')
    @classmethod
    def clean_queries(cls,values):
        unique={}
        for value in values:
            value=' '.join(value.split())
            if not 1<=len(value)<=400:raise ValueError('검색 쿼리는 1~400자로 입력해 주세요.')
            unique.setdefault(value.casefold(),value)
        return list(unique.values())

    @field_validator('domains')
    @classmethod
    def clean_domains(cls,values):
        return sorted(set(normalize_host(v) for v in values))

    @model_validator(mode='after')
    def conditions(self):
        if not self.search_all_domains and not self.domains:raise ValueError('도메인을 추가하거나 전체 도메인 검색을 선택해 주세요.')
        return self


class PublicationUpdate(SettingsBody,SourceConditions):
    revision: str=Field(min_length=64,max_length=64)

    @model_validator(mode='after')
    def separate_members(self):
        if self.members is not None:raise ValueError('구독자는 구독자 관리에서 수정해 주세요.')
        return self


@router.put('/{sid}/settings')
def update_publication(sid: str,body: PublicationUpdate):
    with database() as db:
        db.execute("SELECT pg_advisory_xact_lock(741902630)")
        return update_publication_in_db(db,sid,body)


def update_publication_in_db(db,sid,body):
    current=detail(db,sid);check_revision(current,body.revision);sample_id=current['sample_id']
    sources_changed=(current['queries']!=body.queries or current['domains']!=body.domains or current['search_all_domains']!=body.search_all_domains)
    if db.execute("SELECT 1 FROM subscription_publication_jobs WHERE subscription_id=? AND status='running'",(sid,)).fetchone():
        raise HTTPException(409,'발행 중인 구독은 발행 완료 후 수정해 주세요.')
    if sources_changed and (db.execute("SELECT 1 FROM subscription_collection_runs WHERE sample_id=? AND status='running'",(sample_id,)).fetchone() or
        db.execute("SELECT 1 FROM subscription_publication_jobs j JOIN subscriptions s USING(subscription_id) WHERE s.sample_id=? AND j.status='running'",(sample_id,)).fetchone()):
        raise HTTPException(409,'같은 샘플의 수집 또는 발행이 진행 중입니다. 완료 후 수정해 주세요.')
    write_settings(db,sid,body)
    if sources_changed:
        existing={r['query'].casefold():dict(r) for r in db.execute('SELECT * FROM sample_queries WHERE sample_id=?',(sample_id,))}
        db.execute('DELETE FROM sample_queries WHERE sample_id=?',(sample_id,))
        for pos,query in enumerate(body.queries,1):
            old=existing.get(query.casefold(),{})
            db.execute('INSERT INTO sample_queries(query_id,sample_id,request_id,query,position,created_at) VALUES(?,?,?,?,?,?)',
                (old.get('query_id',str(uuid.uuid4())),sample_id,old.get('request_id'),query,pos,old.get('created_at',now())))
        domain_ids=[]
        for host in body.domains:
            db.execute('INSERT INTO domains(domain_id,host,created_at) VALUES(?,?,?) ON CONFLICT(host) DO NOTHING',(str(uuid.uuid4()),host,now()))
            did=db.execute('SELECT domain_id FROM domains WHERE host=?',(host,)).fetchone()[0];domain_ids.append(did)
            db.execute("INSERT INTO sample_domains(sample_id,domain_id,kind,created_at) VALUES(?,?,'manual',?) ON CONFLICT DO NOTHING",(sample_id,did,now()))
        for row in db.execute('SELECT domain_id FROM sample_domains WHERE sample_id=?',(sample_id,)).fetchall():
            if row[0] not in domain_ids:db.execute('DELETE FROM sample_domains WHERE sample_id=? AND domain_id=?',(sample_id,row[0]))
        db.execute('UPDATE sample_newsletters SET search_all_domains=? WHERE sample_id=?',(int(body.search_all_domains),sample_id))
    db.execute('UPDATE subscriptions SET updated_at=? WHERE subscription_id=?',(now(),sid))
    return detail(db,sid)

@router.get('/{sid}/history')
def history(sid: str,offset: int=Query(0,ge=0)):
    with database() as db:
        active(db,sid)
        count=db.execute('SELECT count(*) FROM subscription_publication_jobs WHERE subscription_id=?',(sid,)).fetchone()[0]
        jobs=[dict(r) for r in db.execute('''SELECT j.job_id,j.scheduled_date,j.status,j.attempt,j.newsletter_id,j.started_at,j.completed_at,
            n.coverage_start_date,n.coverage_end_date,n.published_at,jsonb_array_length(n.issue_ids::jsonb) AS article_count
            FROM subscription_publication_jobs j LEFT JOIN subscripted_newsletters n USING(newsletter_id)
            WHERE j.subscription_id=? ORDER BY j.scheduled_date DESC LIMIT 50 OFFSET ?''',(sid,offset))]
        for job in jobs:
            m=db.execute('SELECT status,results_json FROM mailing WHERE subscription_id=? AND newsletter_id=?',(sid,job['newsletter_id'])).fetchone()
            results=json.loads(m['results_json']) if m else []
            job['delivery']={s:sum(r.get('status')==s for r in results) for s in ['sent','failed','unknown']}
            job['mail_status']=m['status'] if m else None
        # Include legacy/manual editions that have delivery history without a job.
        delivered=[dict(r) for r in db.execute('''SELECT n.newsletter_id,n.coverage_start_date,n.coverage_end_date,n.published_at,h.created_at,
            jsonb_array_length(n.issue_ids::jsonb) AS article_count FROM subscription_history h JOIN subscripted_newsletters n USING(newsletter_id)
            WHERE h.subscription_id=? ORDER BY h.created_at DESC LIMIT 50 OFFSET ?''',(sid,offset))]
        delivered_count=db.execute('SELECT count(*) FROM subscription_history WHERE subscription_id=?',(sid,)).fetchone()[0]
    return dict(jobs=jobs,total=count,delivered=delivered,delivered_total=delivered_count,offset=offset)


@router.get('/{sid}/editions/{newsletter_id}')
def edition(sid: str,newsletter_id: str):
    with database() as db:
        sub=active(db,sid)
        row=db.execute('''SELECT n.html_content AS html FROM subscripted_newsletters n WHERE n.newsletter_id=? AND n.sample_id=?
            AND (EXISTS(SELECT 1 FROM subscription_history h WHERE h.subscription_id=? AND h.newsletter_id=n.newsletter_id)
              OR EXISTS(SELECT 1 FROM subscription_publication_jobs j WHERE j.subscription_id=? AND j.newsletter_id=n.newsletter_id))''',
            (newsletter_id,sub['sample_id'],sid,sid)).fetchone()
        if not row:raise HTTPException(404,'해당 구독의 발행본을 찾을 수 없습니다.')
        return dict(row)
