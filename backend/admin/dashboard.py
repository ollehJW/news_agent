"""Administrator usage reporting; prices are explicit estimates, never invoice totals."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import json
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from backend.core.auth import admin_user, database, now
from backend.integrations.exa_usage import init_exa_usage, search_count

router = APIRouter(prefix='/api/admin', dependencies=[Depends(admin_user)])
KST = ZoneInfo('Asia/Seoul')


def init_admin_db():
    from backend.subscriptions.usage import init_subscription_usage
    init_subscription_usage()
    init_exa_usage()
    with database() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS llm_pricing (
            provider TEXT NOT NULL, model TEXT NOT NULL,
            input_rate REAL NOT NULL CHECK(input_rate>=0),
            cached_rate REAL NOT NULL CHECK(cached_rate>=0),
            output_rate REAL NOT NULL CHECK(output_rate>=0),
            updated_at TEXT NOT NULL, PRIMARY KEY(provider,model))''')


def period(start: date, end: date):
    if end < start or (end-start).days > 365:
        raise HTTPException(422, '조회 기간은 시작일 이후 최대 366일로 설정해 주세요.')
    return (datetime.combine(start, time.min, KST).astimezone(timezone.utc).isoformat(),
            datetime.combine(end+timedelta(days=1), time.min, KST).astimezone(timezone.utc).isoformat())


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


class Price(BaseModel):
    provider: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)
    input_rate: float = Field(ge=0, le=100000, allow_inf_nan=False)
    cached_rate: float = Field(ge=0, le=100000, allow_inf_nan=False)
    output_rate: float = Field(ge=0, le=100000, allow_inf_nan=False)


@router.put('/llm-pricing')
def save_price(body: Price):
    with database() as db:
        if not db.execute('SELECT 1 FROM llm_requests WHERE provider=? AND model=?', (body.provider, body.model)).fetchone():
            raise HTTPException(404, '사용 기록이 있는 모델만 설정할 수 있습니다.')
        db.execute('''INSERT INTO llm_pricing VALUES (?,?,?,?,?,?) ON CONFLICT(provider,model)
            DO UPDATE SET input_rate=excluded.input_rate,cached_rate=excluded.cached_rate,
            output_rate=excluded.output_rate,updated_at=excluded.updated_at''',
            (body.provider, body.model, body.input_rate, body.cached_rate, body.output_rate, now()))
    return {'ok': True}


@router.get('/operations')
def operations(start: date, end: date):
    bounds = period(start, end)
    with database() as db:
        snapshot = {key: db.execute(sql).fetchone()[0] for key, sql in {
            'users': 'SELECT count(*) FROM users WHERE is_admin=FALSE AND is_active=TRUE',
            'samples': 'SELECT count(*) FROM sample_newsletters WHERE saved_at IS NOT NULL',
            'subscriptions': "SELECT count(*) FROM subscriptions WHERE status='active'",
            'members': "SELECT count(*) FROM subscription_members m JOIN subscriptions s USING(subscription_id) WHERE s.status='active' AND m.status='active'",
        }.items()}
        grouped = {}
        for key, table, stamp in [('samples','sample_runs','started_at'),('collection','subscription_collection_runs','started_at'),('publication','subscription_publication_jobs','started_at')]:
            grouped[key] = rows(db, f'SELECT status,count(*) AS count FROM {table} WHERE {stamp}>=? AND {stamp}<? GROUP BY status', bounds)
        mail = rows(db, 'SELECT results_json,status FROM mailing WHERE created_at>=? AND created_at<?', bounds)
        delivery = defaultdict(int)
        for m in mail:
            delivery['messages'] += 1
            if m['status']=='processing': delivery['processing'] += 1
            for recipient in json.loads(m['results_json'] or '[]'):
                delivery[recipient.get('status','unknown')] += 1
        activity = rows(db, '''SELECT u.user_id,u.full_name,u.employee_id,t.name AS team_name,u.last_login_at,
            (SELECT count(*) FROM sample_runs r WHERE r.user_id=u.user_id AND r.started_at>=? AND r.started_at<?) AS samples,
            (SELECT count(*) FROM llm_requests l WHERE l.user_id=u.user_id AND l.started_at>=? AND l.started_at<?) AS calls,
            (SELECT count(*) FROM subscriptions s WHERE s.user_id=u.user_id AND s.status!='cancelled') AS subscriptions
            FROM users u JOIN teams t USING(team_id) WHERE u.is_admin=FALSE
            ORDER BY samples DESC,calls DESC,u.full_name''', bounds+bounds)
        error_count=db.execute('SELECT count(*) FROM errors WHERE created_at>=? AND created_at<?',bounds).fetchone()[0]
        errors=rows(db, '''SELECT e.error_id,e.step,e.error_type,e.message,e.created_at,u.full_name
            FROM errors e LEFT JOIN users u USING(user_id) WHERE e.created_at>=? AND e.created_at<?
            ORDER BY e.created_at DESC LIMIT 100''',bounds)
    return dict(snapshot=snapshot,jobs=grouped,delivery=dict(delivery),activity=activity,errors=errors,error_count=error_count)


def tally(items):
    result = dict(calls=len(items), input_tokens=0, output_tokens=0, cached_input_tokens=0, total_tokens=0,
                  cost=0, priced_calls=0, unknown_usage=0)
    for item in items:
        for key in ('input_tokens','output_tokens','cached_input_tokens'):
            result[key] += item[key] or 0
        result['total_tokens'] += item['total_tokens'] if item['total_tokens'] is not None else (item['input_tokens'] or 0)+(item['output_tokens'] or 0)
        if item['input_tokens'] is None or item['output_tokens'] is None: result['unknown_usage'] += 1
        if item['cost'] is not None:
            result['cost'] += item['cost']
            result['priced_calls'] += 1
    return result


@router.get('/tokens')
def tokens(start: date, end: date, user_id: str = '', step: str = '', model: str = '', provider: str = '', subscription_id: str = '', offset: int = Query(0,ge=0)):
    bounds=period(start,end)
    with database() as db:
        options=dict(users=rows(db,'SELECT user_id,full_name,employee_id FROM users ORDER BY full_name'),
                     models=rows(db,'SELECT DISTINCT provider,model FROM llm_requests ORDER BY provider,model'),
                     steps=[r[0] for r in db.execute('SELECT DISTINCT step FROM llm_requests ORDER BY step')])
        options['subscriptions']=rows(db,'''SELECT s.subscription_id,s.sample_id,
            COALESCE(st.name,n.topic) AS name,u.full_name AS owner_name
            FROM subscriptions s JOIN sample_details n USING(sample_id)
            JOIN users u ON u.user_id=s.user_id LEFT JOIN subscription_settings st USING(subscription_id)
            WHERE s.status='active' ORDER BY name,s.subscription_id''')
        prices=rows(db,'SELECT * FROM llm_pricing')
        clauses=['l.started_at>=?','l.started_at<?']; args=list(bounds)
        for key,value in [('user_id',user_id),('step',step),('model',model),('provider',provider)]:
            if value: clauses.append(f'l.{key}=?'); args.append(value)
        if subscription_id:
            selected=next((s for s in options['subscriptions'] if s['subscription_id']==subscription_id),None)
            if not selected: raise HTTPException(404,'활성 구독을 찾을 수 없습니다.')
            clauses.append('EXISTS(SELECT 1 FROM subscription_llm_requests sl WHERE sl.request_id=l.request_id AND sl.sample_id=?)')
            args.append(selected['sample_id'])
        exa_results=search_count(db,bounds,user_id,selected['sample_id'] if subscription_id else None)
        requests=rows(db,'''SELECT l.*,u.full_name,u.employee_id,
            (SELECT sample_id FROM subscription_llm_requests sl WHERE sl.request_id=l.request_id) AS subscription_sample_id,
            EXISTS(SELECT 1 FROM errors e WHERE e.request_id=l.request_id) AS has_error
            FROM llm_requests l LEFT JOIN users u USING(user_id) WHERE '''+' AND '.join(clauses)+' ORDER BY l.started_at DESC',args)
    price_map={(p['provider'],p['model']):p for p in prices}
    groups={k:defaultdict(list) for k in ('daily','users','steps','models')}
    for r in requests:
        p=price_map.get((r['provider'],r['model'])); r['cost']=None
        if p and r['input_tokens'] is not None and r['output_tokens'] is not None:
            cached=min(r['input_tokens'],max(0,r['cached_input_tokens'] or 0))
            r['cost']=((r['input_tokens']-cached)*p['input_rate']+cached*p['cached_rate']+r['output_tokens']*p['output_rate'])/1_000_000
        day=datetime.fromisoformat(r['started_at'].replace('Z','+00:00')).astimezone(KST).date().isoformat()
        groups['daily'][day].append(r)
        groups['users'][r['user_id']].append(r)
        groups['steps'][r['step']].append(r)
        groups['models'][r['provider']+' / '+r['model']].append(r)
    grouped={}
    for kind, entries in groups.items():
        grouped[kind]=[dict(key=k,label=(f"{v[0]['full_name']} ({v[0]['employee_id']})" if kind=='users' else k),**tally(v)) for k,v in entries.items()]
        grouped[kind].sort(key=lambda x:x['key'] if kind=='daily' else -x['total_tokens'])
    grouped['subscriptions']=[dict(key=sub['subscription_id'],label=f"{sub['name']} · {sub['owner_name']}",
        **tally([r for r in requests if r['subscription_sample_id']==sub['sample_id']]))
        for sub in options['subscriptions'] if not subscription_id or sub['subscription_id']==subscription_id]
    return dict(exa_search_results=exa_results,unlinked_subscription_calls=sum(r['step'].startswith('subscription_') and not r['subscription_sample_id'] for r in requests),summary=tally(requests),groups=grouped,requests=requests[offset:offset+50],offset=offset,options=options,prices=prices)
