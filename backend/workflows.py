"""Persist the existing newsletter workflow; collection remains explicitly demo data."""
import json
import math
import uuid
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field, field_validator

from .auth import database, now
from .error_storage import tracked_member_user as member_user, ErrorRoute
from .domains import Topic, normalize_host
from .sample_lifecycle import editable_sample
from .llm_tracking import requests_for_user, owned_recommendation_request
from .recommendation_tokens import sign_recommendation, verify_recommendation
from .demo_data import TOPICS

router = APIRouter(prefix='/api', route_class=ErrorRoute, dependencies=[Depends(member_user)])
templates = Environment(loader=FileSystemLoader(Path(__file__).with_name('template')),
                        autoescape=select_autoescape(['html']))
TEMPLATE_VERSION = 'wianews-v1'


def owned_sample(db, sample_id, user_id):
    row = db.execute('SELECT * FROM sample_newsletters WHERE sample_id=? AND user_id=?', (sample_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, '생성 작업을 찾을 수 없습니다.')
    return row


def new_sample(topic, user_id):
    sample_id = str(uuid.uuid4())
    with database() as db:
        db.execute('INSERT INTO sample_newsletters (sample_id,user_id,topic,created_at) VALUES (?,?,?,?)',
                   (sample_id,user_id,topic,now()))
    return sample_id


def prepare_recommendation(topic, user_id, sample_id=None):
    sample_id = sample_id or new_sample(topic, user_id)
    with database() as db:
        sample = owned_sample(db, sample_id, user_id)
        if sample['topic'] != topic:
            raise HTTPException(409, '작업 주제가 변경되었습니다. 새 작업을 시작해 주세요.')
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
        uid = db.execute('SELECT user_id FROM sample_newsletters WHERE sample_id=?',(sample_id,)).fetchone()[0]
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
    sid=sample_id
    rows = db.execute('''SELECT i.*,a.title,a.summary,a.url,a.published_at,a.image_url,d.host,
        (SELECT count(*) FROM sample_issues x WHERE x.sample_id=i.sample_id AND x.duplicate_of_issue_id=i.issue_id) AS duplicates
        FROM sample_issues i JOIN sample_articles a ON a.article_id=i.article_id AND a.sample_id=i.sample_id
        LEFT JOIN domains d ON d.domain_id=a.domain_id
        WHERE i.sample_id=? AND i.duplicate_of_issue_id IS NULL ORDER BY i.rank,i.issue_id''', (sid,))
    topic = db.execute('SELECT topic FROM sample_newsletters WHERE sample_id=?', (sample_id,)).fetchone()[0]
    return [{'id': r['issue_id'], 'issue': r['issue_id'], 'article_id':r['article_id'], 'title': r['title'], 'summary': r['summary'],
             'url': r['url'], 'source': r['host'], 'host': r['host'], 'date': r['published_at'],
             'imageUrl': r['image_url'], 'imageAlt': r['title'], 'tag': topic,
             'scores': [r['technical_score'],r['organization_score'],r['impact_score'],r['recency_score']],
             'score': r['total_score'], 'duplicates': r['duplicates'], 'selected': bool(r['is_selected']),
             'default_selected': bool(r['rank'] and r['rank']<=5 and (r['total_score'] or 0)>=70)} for r in rows]


class SampleBody(BaseModel):
    topic: Topic


@router.post('/samples', status_code=201)
def create_sample(body: SampleBody, user=Depends(member_user)):
    return {'sample_id': new_sample(body.topic, user['user_id'])}


@router.get('/samples')
def list_samples(user=Depends(member_user)):
    with database() as db:
        return [dict(r) for r in db.execute('SELECT * FROM sample_newsletters WHERE user_id=? ORDER BY created_at DESC LIMIT 100', (user['user_id'],))]


@router.get('/samples/{sample_id}')
def get_sample(sample_id: str, user=Depends(member_user)):
    with database() as db:
        sample = dict(owned_sample(db, sample_id, user['user_id']))
        return {**sample, 'domains': sources(db, sample_id), 'recommendations': sources(db, sample_id, False),
                'issues': issue_rows(db, sample_id)}


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
        return {'sample_id':sid,'domains':sources(db,sid)}


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
        db.execute('UPDATE sample_newsletters SET collection_start_date=?,collection_end_date=? WHERE sample_id=?',(body.start.isoformat(),body.end.isoformat(),sid))
    return {'sample_id':sid}


@router.post('/samples/{sample_id}/collect-demo')
def collect_demo(sample_id: str, user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        sample = owned_sample(db,sample_id,user['user_id'])
        selected = sources(db,sample_id)
        if not selected or not sample['collection_start_date'] or not sample['collection_end_date']:
            raise HTTPException(400, '수집 도메인과 기간을 먼저 설정해 주세요.')
        sid,_=editable_sample(db,sample_id)
        db.execute('DELETE FROM sample_issues WHERE sample_id=?',(sid,))
        db.execute('DELETE FROM sample_articles WHERE sample_id=?',(sid,))
        for i, item in enumerate(TOPICS):
            domain = selected[i % len(selected)]
            title, summary = f"{sample['topic']} · {item[0]}", item[1]
            scores = [96-i*4,94-i*3,92-i*4,95-i*2]
            score = math.floor(sum(a*b for a,b in zip(scores,[.35,.30,.25,.10]))+.5)
            issue_id, article_id = str(uuid.uuid4()), str(uuid.uuid4())
            stamp=now()
            # Fragments distinguish mock records while keeping links on the source homepage.
            url=f"https://{domain['host']}/#wianews-demo-{i+1}"
            db.execute('''INSERT INTO sample_articles (article_id,sample_id,domain_id,url,title,published_at,content,summary,collected_at)
                VALUES (?,?,?,?,?,?,?,?,?)''', (article_id,sid,domain['domain_id'],url,title,sample['collection_end_date'],summary,summary,stamp))
            db.execute('''INSERT INTO sample_issues (issue_id,sample_id,article_id,technical_score,organization_score,
                impact_score,recency_score,total_score,rank,is_selected,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (issue_id,sid,article_id,*scores,score,i+1,int(i<5),stamp))
            if i<3:
                duplicate_article,duplicate_issue=str(uuid.uuid4()),str(uuid.uuid4())
                db.execute('''INSERT INTO sample_articles (article_id,sample_id,domain_id,url,title,published_at,content,summary,collected_at)
                    VALUES (?,?,?,?,?,?,?,?,?)''', (duplicate_article,sid,domain['domain_id'],url+'-related',title,sample['collection_end_date'],summary,summary,stamp))
                db.execute('''INSERT INTO sample_issues (issue_id,sample_id,article_id,technical_score,organization_score,
                    impact_score,recency_score,total_score,is_selected,duplicate_of_issue_id,created_at)
                    VALUES (?,?,?,?,?,?,?,?,0,?,?)''', (duplicate_issue,sid,duplicate_article,*scores,score,issue_id,stamp))
        return {'sample_id':sid,'issues':issue_rows(db,sid),'article_count':9,'data_mode':'demo'}


class SelectionBody(BaseModel):
    issue_ids: list[str] = Field(max_length=100)


@router.put('/samples/{sample_id}/selection')
def set_selection(sample_id: str, body: SelectionBody, user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        owned_sample(db,sample_id,user['user_id'])
        sid=sample_id
        existing = {r['issue_id']:bool(r['is_selected']) for r in db.execute('SELECT issue_id,is_selected FROM sample_issues WHERE sample_id=? AND duplicate_of_issue_id IS NULL',(sid,))}
        chosen=set(body.issue_ids)
        if not chosen.issubset(existing):
            raise HTTPException(400,'선택한 이슈가 해당 작업에 속하지 않습니다.')
        sid,mapping=editable_sample(db,sample_id)
        for iid,was_selected in existing.items():
            selected=iid in chosen
            if was_selected!=selected:
                db.execute('UPDATE sample_issues SET is_selected=? WHERE issue_id=?',(int(selected),mapping.get(iid,iid)))
        return {'sample_id':sid,'selected_ids':[mapping.get(iid,iid) for iid in chosen],'issues':issue_rows(db,sid)}


def newsletter_dict(db,row):
    count=db.execute('SELECT count(*) FROM sample_issues WHERE sample_id=? AND is_selected=1',(row['sample_id'],)).fetchone()[0]
    return {'id':row['sample_id'],'title':row['topic'],'html':row['html_content'],
            'date':(row['saved_at'] or row['completed_at'] or row['created_at'])[:10], 'count':count,
            'topic':row['topic'],'domains':sources(db,row['sample_id']),
            'dates':{'start':row['collection_start_date'],'end':row['collection_end_date']},'saved_at':row['saved_at']}


@router.post('/samples/{sample_id}/newsletter')
def make_newsletter(sample_id: str, user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        owned_sample(db,sample_id,user['user_id'])
        sid=sample_id
        sample=db.execute('SELECT * FROM sample_newsletters WHERE sample_id=?',(sid,)).fetchone()
        if sample['status']=='completed':
            return newsletter_dict(db,sample)
        issues=[i for i in issue_rows(db,sample_id) if i['selected']]
        if not issues:
            raise HTTPException(400,'뉴스레터에 포함할 이슈를 선택해 주세요.')
        html=templates.get_template('newsletter.html').render(title=sample['topic'],topic=sample['topic'],
            dates={'start':sample['collection_start_date'],'end':sample['collection_end_date']},issues=issues)
        stamp=now()
        db.execute("UPDATE sample_newsletters SET html_content=?,status='completed',completed_at=? WHERE sample_id=?",(html,stamp,sid))
        return newsletter_dict(db,db.execute('SELECT * FROM sample_newsletters WHERE sample_id=?',(sid,)).fetchone())


def owned_newsletter(db, nid, uid):
    row=db.execute("SELECT * FROM sample_newsletters WHERE sample_id=? AND user_id=? AND status='completed'",(nid,uid)).fetchone()
    if not row:
        raise HTTPException(404,'뉴스레터를 찾을 수 없습니다.')
    return row


@router.get('/newsletters')
def list_newsletters(user=Depends(member_user)):
    with database() as db:
        return [newsletter_dict(db,r) for r in db.execute('SELECT * FROM sample_newsletters WHERE user_id=? AND saved_at IS NOT NULL ORDER BY saved_at DESC',(user['user_id'],))]


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
