"""Persist sample settings, article selections, and generated newsletters."""
from backend.news.newsletter_rendering import render_newsletter
from backend.news.newsletter_summary import generate_newsletter_summary
from backend.core.tracking import sample_context
from backend.core.error_storage import record_sample_error
from backend.samples.runs import create_run,set_step,prepare_configuration
from backend.news.scoring_rules import weighted_scores
import json
import asyncio
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from backend.core.auth import database, now
from backend.core.error_storage import tracked_member_user as member_user, ErrorRoute
from backend.recommendations.domains import Topic, normalize_host
from backend.samples.sample_lifecycle import editable_sample
from backend.core.llm_tracking import requests_for_user, owned_recommendation_request
from backend.core.recommendation_tokens import sign_recommendation, verify_recommendation
from backend.recommendations.query_storage import queries_for_sample, QueryInput, save_selected_queries

router = APIRouter(prefix='/api', route_class=ErrorRoute, dependencies=[Depends(member_user)])
TEMPLATE_VERSION = 'hyundai-wia-v1'


def owned_sample(db, sample_id, user_id):
    row = db.execute('SELECT * FROM sample_details WHERE sample_id=? AND user_id=?', (sample_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, '생성 작업을 찾을 수 없습니다.')
    return row


def new_sample(topic, user_id):
    sample_id = str(uuid.uuid4())
    with database() as db:
        db.execute('INSERT INTO sample_newsletters (sample_id,created_at) VALUES (?,?)',(sample_id,now()))
        create_run(db,sample_id,user_id,topic)
    return sample_id


def prepare_recommendation(topic, user_id, sample_id=None):
    sample_id = sample_id or new_sample(topic, user_id)
    with database() as db:
        sample = owned_sample(db, sample_id, user_id)
        if sample['topic'] != topic:
            raise HTTPException(409, '작업 주제가 변경되었습니다. 새 작업을 시작해 주세요.')
        sample_id, _ = editable_sample(db, sample_id)
        set_step(db,sample_id,'source_setup')
        batch = str(uuid.uuid4())
    return sample_id, batch


def shared_domain(db, host):
    stamp = now()
    db.execute('''INSERT INTO domains (domain_id,host,created_at)
        VALUES (?,?,?) ON CONFLICT(host) DO NOTHING''',
        (str(uuid.uuid4()), host, stamp))
    return db.execute('SELECT domain_id FROM domains WHERE host=?', (host,)).fetchone()[0]


def store_recommendation(sample_id, batch, domain, rank):
    with database() as db:
        uid = db.execute('SELECT user_id FROM sample_details WHERE sample_id=?',(sample_id,)).fetchone()[0]
    return sign_recommendation(uid,sample_id,{
        'host':domain.host,'request_id':domain._request_id,
        'desc':domain.desc,'reason':domain.reason,'relevance':domain.relevance})



def sources(db, sample_id, selected_only=True):
    sid = sample_id
    rows = db.execute('SELECT sd.*,d.host FROM sample_domains sd JOIN domains d USING(domain_id) WHERE sd.sample_id=? ORDER BY sd.created_at,sd.domain_id',(sid,)).fetchall()
    selected = [{'sample_id':sid,'domain_id':r['domain_id'],'request_id':r['request_id'],
        'host':r['host'],'name':r['host'],'kind':r['kind'],'desc':r['description'] or '',
        'reason':r['recommendation_reason'],'relevance':r['topic_relevance'],
        'custom':r['kind']=='manual','mark':r['host'][:2],'selected':True} for r in rows]
    if selected_only:
        return selected
    return [r for r in selected if not r['custom']]


def issue_rows(db, sample_id):
    rows = db.execute('''SELECT a.*,i.issue_id,i.rank AS selected_rank,d.host
        FROM sample_articles sa JOIN articles a ON a.article_id=sa.article_id
        LEFT JOIN sample_issues i ON i.article_id=a.article_id AND i.sample_id=sa.sample_id
        LEFT JOIN domains d ON d.domain_id=a.domain_id
        WHERE sa.sample_id=?''', (sample_id,)).fetchall()
    sample = db.execute('SELECT topic,collection_end_date FROM sample_details WHERE sample_id=?', (sample_id,)).fetchone()
    topic=sample['topic']
    rows=[dict(r) for r in rows]
    for r in rows:r.update(weighted_scores(r))
    rows.sort(key=lambda r:(-(r['total_score'] or 0),-date.fromisoformat(r['published_at']).toordinal() if r['published_at'] else 0,r['url']))
    return [{'id': r['article_id'], 'issue': r['issue_id'], 'article_id':r['article_id'], 'title': r['newsletter_title'] or r['title'], 'originalTitle':r['title'], 'newsletterTitle':r['newsletter_title'], 'summary': r['summary'],
             'url': r['url'], 'source': r['host'], 'host': r['host'], 'date': r['published_at'],
             'imageUrl': r['image_url'], 'imageAlt': r['newsletter_title'] or r['title'], 'tag': topic,
             'scores': [r['technical_score'],r['organization_score'],r['impact_score']],
             'score': r['total_score'], 'duplicates': 0, 'selected': r['issue_id'] is not None,
             'rank':r['selected_rank'], 'default_selected': index<5} for index,r in enumerate(rows)]


class SampleBody(BaseModel):
    topic: Topic


@router.post('/samples', status_code=201)
def create_sample(body: SampleBody, user=Depends(member_user)):
    return {'sample_id': new_sample(body.topic, user['user_id'])}


@router.get('/samples')
def list_samples(user=Depends(member_user)):
    with database() as db:
        return [dict(r) for r in db.execute('SELECT * FROM sample_details WHERE user_id=? ORDER BY created_at DESC LIMIT 100', (user['user_id'],))]


@router.get('/sample-runs')
def list_sample_runs(user=Depends(member_user)):
    with database() as db:
        return [dict(r) for r in db.execute('SELECT * FROM sample_runs WHERE user_id=? ORDER BY started_at DESC,rowid DESC LIMIT 200',(user['user_id'],))]


@router.get('/samples/{sample_id}')
def get_sample(sample_id: str, user=Depends(member_user)):
    with database() as db:
        sample = dict(owned_sample(db, sample_id, user['user_id']))
        return {**sample, 'domains': sources(db, sample_id), 'recommendations': sources(db, sample_id, False),
                'issues': issue_rows(db, sample_id), 'queries': queries_for_sample(db, sample_id)}


class SourceInput(BaseModel):
    host: str
    recommendation_id: str | None = Field(default=None,max_length=16000)
    custom: bool = False

    @field_validator('host')
    @classmethod
    def host_valid(cls, value):
        return normalize_host(value)


class SourcesBody(BaseModel):
    domains: list[SourceInput] = Field(max_length=20)
    queries: list[QueryInput] | None = Field(default=None,max_length=5)


@router.put('/samples/{sample_id}/sources')
def set_sources(sample_id: str, body: SourcesBody, user=Depends(member_user)):
    # Normalize first, then merge repeated hosts. Keep AI provenance when both are provided.
    unique={}
    for item in body.domains:
        current=unique.get(item.host)
        if current is None or (item.recommendation_id and not current.recommendation_id):
            unique[item.host]=item
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        owned_sample(db, sample_id, user['user_id'])
        sid,_=editable_sample(db,sample_id)
        prepare_configuration(db,sid)
        chosen=[]
        for item in unique.values():
            did=shared_domain(db,item.host)
            existing=db.execute('SELECT * FROM sample_domains WHERE sample_id=? AND domain_id=?',(sid,did)).fetchone()
            data=None
            if item.recommendation_id:
                data=verify_recommendation(item.recommendation_id,user['user_id'],sample_id)
                if data['host']!=item.host:
                    raise HTTPException(400,'추천 도메인이 일치하지 않습니다.')
            if data:
                request_id=data.get('request_id')
                if request_id and not owned_recommendation_request(db,request_id,user['user_id']):
                    raise HTTPException(400,'추천 호출 기록이 해당 작업에 속하지 않습니다.')
                # Re-adding manually must not discard the existing AI recommendation.
                db.execute('''INSERT INTO sample_domains VALUES (?,?,?,'recommended',?,?,?,?)
                    ON CONFLICT(sample_id,domain_id) DO UPDATE SET request_id=excluded.request_id,
                    kind=excluded.kind,description=excluded.description,recommendation_reason=excluded.recommendation_reason,
                    topic_relevance=excluded.topic_relevance''',
                    (sid,did,request_id,data.get('desc'),data.get('reason'),data.get('relevance'),now()))
            elif not existing:
                db.execute("INSERT INTO sample_domains (sample_id,domain_id,kind,created_at) VALUES (?,?,'manual',?)",(sid,did,now()))
            chosen.append(did)
        for row in db.execute('SELECT domain_id FROM sample_domains WHERE sample_id=?',(sid,)).fetchall():
            if row[0] not in chosen:
                db.execute('DELETE FROM sample_domains WHERE sample_id=? AND domain_id=?',(sid,row[0]))
        if body.queries is not None:
            save_selected_queries(db,sid,sample_id,user['user_id'],body.queries)
        set_step(db,sid,'source_setup')
        return {'sample_id':sid,'domains':sources(db,sid),'queries':queries_for_sample(db,sid)}


class PeriodBody(BaseModel):
    start: date
    end: date


@router.put('/samples/{sample_id}/period')
def set_period(sample_id: str, body: PeriodBody, user=Depends(member_user)):
    if body.start > body.end:
        raise HTTPException(400, '수집 시작일과 종료일을 확인해 주세요.')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        owned_sample(db,sample_id,user['user_id'])
        sid,_=editable_sample(db,sample_id)
        prepare_configuration(db,sid)
        db.execute('UPDATE sample_runs SET collection_start_date=?,collection_end_date=? WHERE run_id=(SELECT run_id FROM sample_details WHERE sample_id=?)',(body.start.isoformat(),body.end.isoformat(),sid))
        set_step(db,sid,'period_setup')
    return {'sample_id':sid}


class SelectionBody(BaseModel):
    article_ids: list[str] = Field(max_length=100)


@router.put('/samples/{sample_id}/selection')
def set_selection(sample_id: str, body: SelectionBody, user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        owned_sample(db,sample_id,user['user_id'])
        existing={r[0] for r in db.execute('SELECT article_id FROM sample_articles WHERE sample_id=?',(sample_id,))}
        chosen=list(dict.fromkeys(body.article_ids))
        if not set(chosen).issubset(existing):
            raise HTTPException(400,'선택한 기사가 해당 작업에 속하지 않습니다.')
        sid,mapping=editable_sample(db,sample_id)
        chosen=[mapping.get(aid,aid) for aid in chosen]
        previous={r['article_id']:dict(r) for r in db.execute('SELECT * FROM sample_issues WHERE sample_id=?',(sid,))}
        db.execute('DELETE FROM sample_issues WHERE sample_id=?',(sid,))
        for rank,aid in enumerate(chosen,1):
            old=previous.get(aid)
            request=db.execute('SELECT request_id FROM articles WHERE article_id=?',(aid,)).fetchone()[0]
            db.execute('INSERT INTO sample_issues (issue_id,sample_id,article_id,request_id,rank,created_at) VALUES (?,?,?,?,?,?)',
                       (old['issue_id'] if old else str(uuid.uuid4()),sid,aid,request,rank,old['created_at'] if old else now()))
        set_step(db,sid,'news_selection')
        return {'sample_id':sid,'selected_ids':chosen,'issues':issue_rows(db,sid)}


def newsletter_dict(db,row):
    count=db.execute('SELECT count(*) FROM sample_issues WHERE sample_id=?',(row['sample_id'],)).fetchone()[0]
    return {'id':row['sample_id'],'title':row['topic'],'html':row['html_content'],
            'date':(row['saved_at'] or row['completed_at'] or row['created_at'])[:10], 'count':count,
            'topic':row['topic'],'total_summary':row['total_summary'],'request_id':row['request_id'],'domains':sources(db,row['sample_id']),
            'dates':{'start':row['collection_start_date'],'end':row['collection_end_date']},'saved_at':row['saved_at']}


_summary_active=set()


def summary_input(db,sid,uid):
    sample=dict(owned_sample(db,sid,uid))
    issues=sorted((i for i in issue_rows(db,sid) if i['selected']),key=lambda i:i['rank'])
    revision=json.dumps({'run_id':sample['run_id'],'topic':sample['topic'],
        'start':sample['collection_start_date'],'end':sample['collection_end_date'],'issues':issues},sort_keys=True,ensure_ascii=False)
    return sample,issues,revision


@router.post('/samples/{sample_id}/newsletter')
async def make_newsletter(sample_id: str, user=Depends(member_user)):
    with database() as db:
        sample,issues,revision=summary_input(db,sample_id,user['user_id'])
        if sample['status']=='completed' and sample.get('total_summary') and 1<=len(sample['total_summary'].splitlines())<=3 and all(len(line.removeprefix('- '))<=90 for line in sample['total_summary'].splitlines()):
            return newsletter_dict(db,sample)
    if not issues:raise HTTPException(400,'뉴스레터에 포함할 이슈를 선택해 주세요.')
    if sample_id in _summary_active:raise HTTPException(409,'이번 호 핵심 요약을 생성하고 있습니다.')
    _summary_active.add(sample_id)
    token=sample_context.set(sample_id)
    try:
        with database() as db:set_step(db,sample_id,'newsletter_summary','running')
        async with asyncio.timeout(125):
            total_summary,request_id=await generate_newsletter_summary(sample['topic'],issues)
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            if summary_input(db,sample_id,user['user_id'])[2]!=revision:
                raise HTTPException(409,'생성 중 기사 선택이나 설정이 변경되었습니다. 다시 생성해 주세요.')
            html=render_newsletter(title=sample['topic'],
                dates={'start':sample['collection_start_date'],'end':sample['collection_end_date']},issues=issues,total_summary=total_summary)
            stamp=now()
            db.execute('UPDATE sample_newsletters SET html_content=?,total_summary=?,request_id=? WHERE sample_id=?',(html,total_summary,request_id,sample_id))
            db.execute("UPDATE sample_runs SET status='completed',current_step='newsletter_completed',completed_at=? WHERE run_id=?",(stamp,sample['run_id']))
            return newsletter_dict(db,db.execute('SELECT * FROM sample_details WHERE sample_id=?',(sample_id,)).fetchone())
    except BaseException as error:
        with database() as db:
            # Keep previously completed outputs usable if upgrading an older newsletter fails.
            if sample['run_status']=='completed':
                db.execute("UPDATE sample_runs SET status='completed',current_step=?,completed_at=? WHERE run_id=? AND current_step='newsletter_summary'",(sample['current_step'],sample['completed_at'],sample['run_id']))
            else:
                db.execute("UPDATE sample_runs SET status=?,completed_at=? WHERE run_id=? AND current_step='newsletter_summary'",('cancelled' if isinstance(error,asyncio.CancelledError) else 'failed',now(),sample['run_id']))
        if isinstance(error,Exception):record_sample_error(sample_id,'sample_newsletter_summary',error)
        if isinstance(error,HTTPException) or not isinstance(error,Exception):raise
        raise HTTPException(502,'이번 호 핵심 요약을 생성하지 못했습니다. 다시 시도해 주세요.') from None
    finally:
        sample_context.reset(token);_summary_active.discard(sample_id)


def owned_newsletter(db, nid, uid):
    row=db.execute("SELECT * FROM sample_details WHERE sample_id=? AND user_id=? AND status='completed'",(nid,uid)).fetchone()
    if not row:
        raise HTTPException(404,'뉴스레터를 찾을 수 없습니다.')
    return row


@router.get('/newsletters')
def list_newsletters(user=Depends(member_user)):
    with database() as db:
        return [newsletter_dict(db,r) for r in db.execute('SELECT * FROM sample_details WHERE user_id=? AND saved_at IS NOT NULL ORDER BY saved_at DESC',(user['user_id'],))]


@router.post('/newsletters/{sample_id}/save')
def save_newsletter(sample_id: str, user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=owned_newsletter(db,sample_id,user['user_id'])
        if not row['saved_at']:
            db.execute('UPDATE sample_newsletters SET saved_at=? WHERE sample_id=?',(now(),sample_id))
        return newsletter_dict(db,owned_newsletter(db,sample_id,user['user_id']))


@router.get('/newsletters/{sample_id}/download')
def download_newsletter(sample_id: str, user=Depends(member_user)):
    with database() as db:
        row=owned_newsletter(db,sample_id,user['user_id'])
        return Response(row['html_content'],media_type='text/html',headers={'Content-Disposition':'attachment; filename="wianews.html"','Cache-Control':'no-store'})


@router.get('/llm-requests')
def llm_usage(user=Depends(member_user)):
    with database() as db:
        rows=requests_for_user(db,user['user_id'])
        totals={key:sum(r[key] for r in rows if r[key] is not None) for key in ('input_tokens','output_tokens','total_tokens','cached_input_tokens')}
        return {**totals,'call_count':len(rows),'unknown_usage_count':sum(r['total_tokens'] is None for r in rows),'requests':rows}


@router.get('/errors')
def list_errors(user=Depends(member_user)):
    with database() as db:
        return [dict(r) for r in db.execute('SELECT * FROM errors WHERE user_id=? ORDER BY created_at DESC,error_id DESC',(user['user_id'],))]
