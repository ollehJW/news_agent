"""Persist the existing newsletter workflow; collection remains explicitly demo data."""
import hashlib
import json
import math
import uuid
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field, field_validator

from .auth import database, member_user, now
from .domains import Topic, normalize_host
from .tracking import event
from .demo_data import TOPICS

router = APIRouter(prefix='/api', dependencies=[Depends(member_user)])
templates = Environment(loader=FileSystemLoader(Path(__file__).with_name('template')),
                        autoescape=select_autoescape(['html']))
TEMPLATE_VERSION = 'wianews-v1'


def owned_run(db, run_id, user_id):
    row = db.execute('SELECT * FROM newsletter_runs WHERE run_id=? AND user_id=?', (run_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, '생성 작업을 찾을 수 없습니다.')
    return row


def new_run(topic, user_id):
    run_id, stamp = str(uuid.uuid4()), now()
    with database() as db:
        db.execute('INSERT INTO newsletter_runs (run_id,user_id,topic,created_at,updated_at) VALUES (?,?,?,?,?)',
                   (run_id, user_id, topic, stamp, stamp))
        event(db, user_id, run_id, 'run_started')
    return run_id


def prepare_recommendation(topic, user_id, run_id=None):
    run_id = run_id or new_run(topic, user_id)
    with database() as db:
        run = owned_run(db, run_id, user_id)
        if run['topic'] != topic:
            raise HTTPException(409, '작업 주제가 변경되었습니다. 새 작업을 시작해 주세요.')
        batch = str(uuid.uuid4())
        event(db, user_id, run_id, 'domain_recommendation_started', {'batch_id': batch})
    return run_id, batch


def shared_domain(db, host, name, *, update_name=False):
    stamp = now()
    db.execute('''INSERT INTO domains (domain_id,host,name,created_at,updated_at)
        VALUES (?,?,?,?,?) ON CONFLICT(host) DO UPDATE SET
        name=CASE WHEN ? THEN excluded.name ELSE domains.name END,
        updated_at=excluded.updated_at''',
        (str(uuid.uuid4()), host, name, stamp, stamp, update_name))
    return db.execute('SELECT domain_id FROM domains WHERE host=?', (host,)).fetchone()[0]


def store_recommendation(run_id, batch, domain, rank):
    snapshot_id, stamp = str(uuid.uuid4()), now()
    with database() as db:
        did = shared_domain(db, domain.host, domain.name, update_name=True)
        db.execute('''INSERT INTO run_domains
            (run_domain_id,run_id,domain_id,recommendation_batch_id,name,kind,description,recommendation_reason,
             topic_relevance,recommendation_rank,added_by,created_at,updated_at)
             VALUES (?,?,?,?,?,?,?,?,?,?,'ai',?,?)''',
            (snapshot_id, run_id, did, batch, domain.name, domain.kind, domain.desc, domain.reason,
             domain.relevance, rank, stamp, stamp))
    return snapshot_id


def recommendation_finished(run_id, batch, state, count):
    with database() as db:
        row = db.execute('SELECT user_id FROM newsletter_runs WHERE run_id=?', (run_id,)).fetchone()
        if row:
            event(db, row[0], run_id, 'domain_recommendation_'+state, {'batch_id': batch, 'count': count})


def sources(db, run_id, selected_only=True):
    rows = db.execute('''SELECT rd.*, d.host FROM run_domains rd JOIN domains d USING(domain_id)
        WHERE rd.run_id=?'''+(' AND rd.is_selected=1' if selected_only else '')+' ORDER BY rd.created_at,rd.run_domain_id', (run_id,))
    return [{'run_domain_id': r['run_domain_id'], 'domain_id': r['domain_id'], 'host': r['host'],
             'name': r['name'], 'kind': r['kind'] or '직접 추가', 'desc': r['description'] or '',
             'reason': r['recommendation_reason'], 'relevance': r['topic_relevance'],
             'custom': r['added_by']=='manual', 'mark': r['name'][:2],
             'selected': bool(r['is_selected']), 'recommendation_rank': r['recommendation_rank']} for r in rows]


def issue_rows(db, run_id):
    rows = db.execute('''SELECT i.*,a.url,a.source,a.published_at,a.image_url,a.image_alt,d.host,
        (SELECT count(*)-1 FROM run_articles x WHERE x.issue_id=i.issue_id) AS duplicates
        FROM run_issues i JOIN run_articles a ON a.article_id=i.representative_article_id
        LEFT JOIN domains d ON d.domain_id=a.domain_id WHERE i.run_id=? ORDER BY i.rank''', (run_id,))
    topic = db.execute('SELECT topic FROM newsletter_runs WHERE run_id=?', (run_id,)).fetchone()[0]
    return [{'id': r['issue_id'], 'issue': r['issue_id'], 'title': r['title'], 'summary': r['summary'],
             'url': r['url'], 'source': r['source'], 'host': r['host'], 'date': r['published_at'],
             'imageUrl': r['image_url'], 'imageAlt': r['image_alt'], 'tag': topic,
             'scores': [r['technical_score'],r['organization_score'],r['impact_score'],r['recency_score']],
             'score': r['total_score'], 'duplicates': r['duplicates'], 'selected': bool(r['is_selected']),
             'default_selected': bool(r['is_default_selected'])} for r in rows]


class RunBody(BaseModel):
    topic: Topic


@router.post('/runs', status_code=201)
def create_run(body: RunBody, user=Depends(member_user)):
    return {'run_id': new_run(body.topic, user['user_id'])}


@router.get('/runs')
def list_runs(user=Depends(member_user)):
    with database() as db:
        return [dict(r) for r in db.execute('SELECT * FROM newsletter_runs WHERE user_id=? ORDER BY created_at DESC LIMIT 100', (user['user_id'],))]


@router.get('/runs/{run_id}')
def get_run(run_id: str, user=Depends(member_user)):
    with database() as db:
        run = dict(owned_run(db, run_id, user['user_id']))
        return {**run, 'domains': sources(db, run_id), 'recommendations': sources(db, run_id, False),
                'issues': issue_rows(db, run_id)}


class SourceInput(BaseModel):
    host: str
    run_domain_id: str | None = None
    custom: bool = False

    @field_validator('host')
    @classmethod
    def host_valid(cls, value):
        return normalize_host(value)


class SourcesBody(BaseModel):
    domains: list[SourceInput] = Field(max_length=20)


@router.put('/runs/{run_id}/sources')
def set_sources(run_id: str, body: SourcesBody, user=Depends(member_user)):
    if len({d.host for d in body.domains}) != len(body.domains):
        raise HTTPException(400, '중복 도메인은 추가할 수 없습니다.')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        owned_run(db, run_id, user['user_id'])
        before = {d['host'] for d in sources(db, run_id)}
        chosen = []
        for item in body.domains:
            row = None
            if item.run_domain_id:
                row = db.execute('''SELECT rd.run_domain_id FROM run_domains rd JOIN domains d USING(domain_id)
                    WHERE rd.run_id=? AND rd.run_domain_id=? AND d.host=?''', (run_id,item.run_domain_id,item.host)).fetchone()
                if not row:
                    raise HTTPException(400, '추천 도메인이 해당 작업에 속하지 않습니다.')
            if not row and not item.custom:
                row = db.execute('''SELECT rd.run_domain_id FROM run_domains rd JOIN domains d USING(domain_id)
                    WHERE rd.run_id=? AND d.host=? ORDER BY rd.created_at DESC LIMIT 1''', (run_id,item.host)).fetchone()
            if row:
                chosen.append(row[0])
            else:
                did = shared_domain(db, item.host, item.host)
                existing = db.execute("SELECT run_domain_id FROM run_domains WHERE run_id=? AND domain_id=? AND added_by='manual' LIMIT 1", (run_id,did)).fetchone()
                rid = existing[0] if existing else str(uuid.uuid4())
                if not existing:
                    db.execute('''INSERT INTO run_domains (run_domain_id,run_id,domain_id,name,kind,added_by,created_at,updated_at)
                        VALUES (?,?,?,?,'직접 추가','manual',?,?)''', (rid,run_id,did,item.host,now(),now()))
                    event(db,user['user_id'],run_id,'domain_manually_added',{'host':item.host})
                chosen.append(rid)
        db.execute('UPDATE run_domains SET is_selected=0,updated_at=? WHERE run_id=?', (now(),run_id))
        for rid in chosen:
            db.execute('UPDATE run_domains SET is_selected=1 WHERE run_domain_id=?', (rid,))
        after = {d.host for d in body.domains}
        event(db,user['user_id'],run_id,'domains_selected',{'added':sorted(after-before),'removed':sorted(before-after),'count':len(after)})
        db.execute('UPDATE newsletter_runs SET updated_at=? WHERE run_id=?',(now(),run_id))
        return sources(db,run_id)


class PeriodBody(BaseModel):
    start: date
    end: date


@router.put('/runs/{run_id}/period')
def set_period(run_id: str, body: PeriodBody, user=Depends(member_user)):
    if body.start > body.end:
        raise HTTPException(400, '수집 시작일과 종료일을 확인해 주세요.')
    with database() as db:
        owned_run(db,run_id,user['user_id'])
        db.execute('UPDATE newsletter_runs SET start_date=?,end_date=?,current_step=1,updated_at=? WHERE run_id=?',
                   (body.start.isoformat(),body.end.isoformat(),now(),run_id))
        event(db,user['user_id'],run_id,'period_configured',{'start':body.start.isoformat(),'end':body.end.isoformat()})
    return {'ok':True}


@router.post('/runs/{run_id}/collect-demo')
def collect_demo(run_id: str, user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        run = owned_run(db,run_id,user['user_id'])
        selected = sources(db,run_id)
        if not selected or not run['start_date'] or not run['end_date']:
            raise HTTPException(400, '수집 도메인과 기간을 먼저 설정해 주세요.')
        event(db,user['user_id'],run_id,'collection_started',{'mode':'demo'})
        db.execute('DELETE FROM run_issues WHERE run_id=?',(run_id,))
        db.execute('DELETE FROM run_articles WHERE run_id=?',(run_id,))
        for i, item in enumerate(TOPICS):
            domain = selected[i % len(selected)]
            title, summary = f"{run['topic']} · {item[0]}", item[1]
            scores = [96-i*4,94-i*3,92-i*4,95-i*2]
            score = math.floor(sum(a*b for a,b in zip(scores,[.35,.30,.25,.10]))+.5)
            issue_id, article_id = str(uuid.uuid4()), str(uuid.uuid4())
            stamp=now()
            db.execute('''INSERT INTO run_articles (article_id,run_id,domain_id,url,title,source,published_at,content_text,summary,collected_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''', (article_id,run_id,domain['domain_id'],f"https://{domain['host']}/",title,domain['name'],run['end_date'],summary,summary,stamp))
            db.execute('''INSERT INTO run_issues (issue_id,run_id,title,summary,representative_article_id,technical_score,organization_score,
                impact_score,recency_score,total_score,rank,is_default_selected,is_selected,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (issue_id,run_id,title,summary,article_id,*scores,score,i+1,int(i<5),int(i<5),stamp,stamp))
            db.execute('UPDATE run_articles SET issue_id=? WHERE article_id=?',(issue_id,article_id))
            if i<3:
                db.execute('''INSERT INTO run_articles (article_id,run_id,domain_id,issue_id,url,title,source,published_at,content_text,summary,collected_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (str(uuid.uuid4()),run_id,domain['domain_id'],issue_id,f"https://{domain['host']}/",title,domain['name'],run['end_date'],summary,summary,stamp))
        db.execute("UPDATE newsletter_runs SET current_step=2,status='ready',error_message=NULL,updated_at=? WHERE run_id=?",(now(),run_id))
        event(db,user['user_id'],run_id,'collection_completed',{'mode':'demo','article_count':9,'issue_count':6})
        event(db,user['user_id'],run_id,'default_issues_selected',{'count':5})
        return {'issues':issue_rows(db,run_id),'article_count':9,'data_mode':'demo'}


class SelectionBody(BaseModel):
    issue_ids: list[str] = Field(max_length=100)


@router.put('/runs/{run_id}/selection')
def set_selection(run_id: str, body: SelectionBody, user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        owned_run(db,run_id,user['user_id'])
        existing = {r['issue_id']:bool(r['is_selected']) for r in db.execute('SELECT issue_id,is_selected FROM run_issues WHERE run_id=?',(run_id,))}
        chosen=set(body.issue_ids)
        if not chosen.issubset(existing):
            raise HTTPException(400,'선택한 이슈가 해당 작업에 속하지 않습니다.')
        for iid,was_selected in existing.items():
            selected=iid in chosen
            if was_selected!=selected:
                db.execute('UPDATE run_issues SET is_selected=?,updated_at=? WHERE issue_id=?',(int(selected),now(),iid))
                event(db,user['user_id'],run_id,'issue_selected' if selected else 'issue_deselected',{'issue_id':iid})
        return {'selected_ids':list(chosen)}


def newsletter_dict(row):
    snapshot=json.loads(row['snapshot_json'])
    return {'id':row['newsletter_id'],'run_id':row['run_id'],'title':row['title'],'html':row['html_content'],
            'date':(row['saved_at'] or row['created_at'])[:10], 'count':row['issue_count'],
            'topic':snapshot['topic'],'domains':snapshot['domains'],'dates':snapshot['dates'],'saved_at':row['saved_at']}


@router.post('/runs/{run_id}/newsletter')
def make_newsletter(run_id: str, user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        run=owned_run(db,run_id,user['user_id'])
        issues=[i for i in issue_rows(db,run_id) if i['selected']]
        if not issues:
            raise HTTPException(400,'뉴스레터에 포함할 이슈를 선택해 주세요.')
        snapshot={'topic':run['topic'],'dates':{'start':run['start_date'],'end':run['end_date']},'issues':issues,'domains':sources(db,run_id)}
        html=templates.get_template('newsletter.html').render(title=run['topic'],**snapshot)
        digest=hashlib.sha256(html.encode()).hexdigest()
        row=db.execute('SELECT * FROM newsletters WHERE run_id=? AND content_hash=?',(run_id,digest)).fetchone()
        if not row:
            nid=str(uuid.uuid4())
            db.execute('''INSERT INTO newsletters (newsletter_id,run_id,user_id,title,html_content,template_version,content_hash,issue_count,snapshot_json,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',(nid,run_id,user['user_id'],run['topic'],html,TEMPLATE_VERSION,digest,len(issues),json.dumps(snapshot,ensure_ascii=False),now()))
            event(db,user['user_id'],run_id,'newsletter_created',{'issue_count':len(issues)},nid)
            row=db.execute('SELECT * FROM newsletters WHERE newsletter_id=?',(nid,)).fetchone()
        db.execute("UPDATE newsletter_runs SET current_step=3,status='completed',completed_at=?,updated_at=? WHERE run_id=?",(now(),now(),run_id))
        return newsletter_dict(row)


def owned_newsletter(db, nid, uid):
    row=db.execute('SELECT * FROM newsletters WHERE newsletter_id=? AND user_id=?',(nid,uid)).fetchone()
    if not row:
        raise HTTPException(404,'뉴스레터를 찾을 수 없습니다.')
    return row


@router.get('/newsletters')
def list_newsletters(user=Depends(member_user)):
    with database() as db:
        return [newsletter_dict(r) for r in db.execute('SELECT * FROM newsletters WHERE user_id=? AND saved_at IS NOT NULL ORDER BY saved_at DESC',(user['user_id'],))]


@router.post('/newsletters/{newsletter_id}/save')
def save_newsletter(newsletter_id: str, user=Depends(member_user)):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=owned_newsletter(db,newsletter_id,user['user_id'])
        if not row['saved_at']:
            db.execute('UPDATE newsletters SET saved_at=? WHERE newsletter_id=?',(now(),newsletter_id))
            event(db,user['user_id'],row['run_id'],'newsletter_saved',newsletter_id=newsletter_id)
        return newsletter_dict(owned_newsletter(db,newsletter_id,user['user_id']))


@router.get('/newsletters/{newsletter_id}/download')
def download_newsletter(newsletter_id: str, user=Depends(member_user)):
    with database() as db:
        row=owned_newsletter(db,newsletter_id,user['user_id'])
        event(db,user['user_id'],row['run_id'],'newsletter_download_requested',newsletter_id=newsletter_id)
        return Response(row['html_content'],media_type='text/html',headers={'Content-Disposition':'attachment; filename="wianews.html"','Cache-Control':'no-store'})


class StepBody(BaseModel):
    step: int = Field(ge=0,le=3)


@router.post('/runs/{run_id}/step')
def record_step(run_id: str, body: StepBody, user=Depends(member_user)):
    with database() as db:
        owned_run(db,run_id,user['user_id'])
        db.execute('UPDATE newsletter_runs SET current_step=?,updated_at=? WHERE run_id=?',(body.step,now(),run_id))
        event(db,user['user_id'],run_id,'step_changed',{'step':body.step})
    return {'ok':True}


@router.get('/runs/{run_id}/usage')
def run_usage(run_id: str, user=Depends(member_user)):
    with database() as db:
        owned_run(db,run_id,user['user_id'])
        rows=[dict(r) for r in db.execute('SELECT * FROM ai_requests WHERE run_id=? ORDER BY created_at',(run_id,))]
        totals={key:sum(r[key] for r in rows if r[key] is not None) for key in ('input_tokens','output_tokens','total_tokens','cached_input_tokens')}
        return {'run_id':run_id,**totals,'call_count':len(rows),'failed_count':sum(r['status']=='failed' for r in rows),
                'unknown_usage_count':sum(r['total_tokens'] is None for r in rows),'requests':rows}
