"""Collect subscription articles once per sample/day, then evaluate missing scores."""
import asyncio
import json
import uuid
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from backend.core.auth import database,now
from backend.core.error_storage import ErrorRoute,tracked_member_user,record_error
from backend.core.tracking import llm_user_context,subscription_collection_context
from backend.integrations.exa_search import search_articles,canonical_url
from backend.news.article_images import article_image_url
from backend.news.image_storage import ensure_article_image
from backend.subscriptions.preprocessing import preprocess_subscription_articles
from backend.subscriptions.scoring import score_sample_articles

KST=ZoneInfo('Asia/Seoul')
router=APIRouter(prefix='/api/subscriptions',route_class=ErrorRoute)


def configuration(db,sample_id):
    sample=db.execute('SELECT topic FROM sample_details WHERE sample_id=?',(sample_id,)).fetchone()
    if not sample:raise HTTPException(404,'샘플을 찾을 수 없습니다.')
    queries=[dict(r) for r in db.execute('SELECT query FROM sample_queries WHERE sample_id=? ORDER BY position',(sample_id,))]
    domains=[dict(r) for r in db.execute('SELECT d.domain_id,d.host FROM sample_domains sd JOIN domains d USING(domain_id) WHERE sd.sample_id=? ORDER BY d.host',(sample_id,))]
    return {'topic':sample['topic'],'queries':queries,'domains':domains}


def active_subscriptions(db,sample_id):
    return db.execute("""SELECT s.* FROM subscriptions s JOIN users u USING(user_id)
        WHERE s.sample_id=? AND s.status='active' AND u.is_active=1
        ORDER BY s.created_at,s.subscription_id""",(sample_id,)).fetchall()


def claim_run(sample_id,day,user_id):
    stamp=now();expired=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        if not any(s['user_id']==user_id for s in active_subscriptions(db,sample_id)):
            raise HTTPException(409,'활성 구독이 있어야 수집할 수 있습니다.')
        # Reclaim interrupted processes after the bounded 360-second execution window.
        db.execute("UPDATE subscription_collection_runs SET status='failed',completed_at=? WHERE sample_id=? AND status='running' AND started_at<?",(stamp,sample_id,expired))
        existing=db.execute('SELECT * FROM subscription_collection_runs WHERE sample_id=? AND collection_date=?',(sample_id,day.isoformat())).fetchone()
        if existing and existing['status']=='completed':return dict(existing),None
        if db.execute("SELECT 1 FROM subscription_collection_runs WHERE sample_id=? AND status='running'",(sample_id,)).fetchone():
            raise HTTPException(409,'이 뉴스레터의 기사를 이미 수집 중입니다.')
        config=configuration(db,sample_id)
        encoded=json.dumps(config,sort_keys=True,ensure_ascii=False)
        run_id=existing['run_id'] if existing else str(uuid.uuid4())
        token=str(uuid.uuid4())
        if existing:
            db.execute("""UPDATE subscription_collection_runs SET user_id=?,attempt=attempt+1,attempt_token=?,
                status='running',configuration_json=?,request_id=NULL,search_results=0,url_duplicates=0,
                invalid_results=0,history_url_excluded=0,candidate_count=0,retained_count=0,saved_count=0,
                started_at=?,completed_at=NULL WHERE run_id=?""",(user_id,token,encoded,stamp,run_id))
        else:
            db.execute("""INSERT INTO subscription_collection_runs
                (run_id,sample_id,user_id,collection_date,status,attempt_token,configuration_json,started_at)
                VALUES (?,?,?,?,'running',?,?,?)""",(run_id,sample_id,user_id,day.isoformat(),token,encoded,stamp))
        return dict(db.execute('SELECT * FROM subscription_collection_runs WHERE run_id=?',(run_id,)).fetchone()),config


def deduplicate_urls(articles,known):
    unique={}
    for article in articles:
        url=canonical_url(article.get('url'))
        if not url:continue
        value={**article,'url':url}
        if url not in unique or len(value.get('content') or '')>len(unique[url].get('content') or ''):unique[url]=value
    return [a for url,a in unique.items() if url not in known],len(articles)-len(unique),sum(url in known for url in unique)


def recent_history(sample_id,started_at):
    cutoff=(datetime.fromisoformat(started_at)-timedelta(days=7)).isoformat()
    with database() as db:
        known={canonical_url(r[0]) for r in db.execute('SELECT a.url FROM subscripted_articles sa JOIN articles a USING(article_id) WHERE sa.sample_id=?',(sample_id,))}
        history=[dict(r) for r in db.execute('''SELECT a.title,a.published_at,a.url,a.highlights
            FROM subscripted_articles sa JOIN articles a USING(article_id)
            WHERE sa.sample_id=? AND julianday(sa.collected_at)>=julianday(?) AND julianday(sa.collected_at)<=julianday(?)
            ORDER BY sa.collected_at,a.article_id''',(sample_id,cutoff,started_at))]
    return known,history


def save_candidates(run,config,retained,request_id,counts):
    stamp=now();saved=[]
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT * FROM subscription_collection_runs WHERE run_id=?',(run['run_id'],)).fetchone()
        if not current or current['status']!='running' or current['attempt_token']!=run['attempt_token']:
            raise HTTPException(409,'수집 실행이 만료되었습니다.')
        if configuration(db,run['sample_id'])!=config:raise HTTPException(409,'수집 중 주제·쿼리·도메인이 변경되었습니다.')
        if not active_subscriptions(db,run['sample_id']):raise HTTPException(409,'활성 구독이 없어 수집을 중단했습니다.')
        for article in retained:
            aid=str(uuid.uuid4())
            # Preserve existing article content, title, summary and evaluation on global URL matches.
            db.execute('''INSERT INTO articles
                (article_id,domain_id,url,title,published_at,content,highlights,image_url,collected_at)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO NOTHING''',
                (aid,article.get('domain_id'),article['url'],article['title'],article.get('published_at'),article.get('content'),
                 json.dumps(article.get('highlights') or [],ensure_ascii=False),
                 article_image_url(article.get('image_url'),article.get('favicon_url')),stamp))
            aid=db.execute('SELECT article_id FROM articles WHERE url=?',(article['url'],)).fetchone()[0]
            inserted=db.execute('''INSERT INTO subscripted_articles (sample_id,article_id,request_id,run_id,collected_at)
                VALUES (?,?,?,?,?) ON CONFLICT(sample_id,article_id) DO NOTHING''',
                (run['sample_id'],aid,request_id,run['run_id'],stamp)).rowcount
            if inserted:saved.append(aid)
        db.execute("""UPDATE subscription_collection_runs SET status='completed',request_id=?,
            search_results=?,url_duplicates=?,invalid_results=?,history_url_excluded=?,candidate_count=?,
            retained_count=?,saved_count=?,completed_at=? WHERE run_id=? AND attempt_token=?""",
            (request_id,counts['search_results'],counts['url_duplicates'],counts['invalid_results'],counts['history_url_excluded'],counts['candidate_count'],len(retained),len(saved),stamp,run['run_id'],run['attempt_token']))
        result=dict(db.execute('SELECT * FROM subscription_collection_runs WHERE run_id=?',(run['run_id'],)).fetchone())
    return result,saved


async def collect_sample(sample_id,day,user_id):
    result=await _collect_sample(sample_id,day,user_id)
    # Collection is already committed. Scoring failures retain raw articles and
    # are retried on the next collection or manual call, without repeating search.
    result['scoring']=await score_sample_articles(sample_id,day,user_id)
    return result


async def _collect_sample(sample_id,day,user_id):
    run,config=claim_run(sample_id,day,user_id)
    if config is None:return public_run(run)
    user_token=llm_user_context.set(user_id)
    context_token=subscription_collection_context.set((run['run_id'],run['attempt_token']))
    stage='subscription_article_collection'
    async def progress(*args):pass
    try:
        async with asyncio.timeout(360):
            if not config['queries'] or not config['domains']:raise HTTPException(422,'저장된 검색 쿼리와 도메인이 필요합니다.')
            articles,counts=await search_articles(config['queries'],config['domains'],day,day,progress)
            known,history=recent_history(sample_id,run['started_at'])
            candidates,duplicates,excluded=deduplicate_urls(articles,known)
            counts['url_duplicates']+=duplicates
            counts.update(history_url_excluded=excluded,candidate_count=len(candidates))
            with database() as db:
                db.execute('''UPDATE subscription_collection_runs SET search_results=?,url_duplicates=?,invalid_results=?,
                    history_url_excluded=?,candidate_count=? WHERE run_id=? AND attempt_token=? AND status='running' ''',
                    (counts['search_results'],counts['url_duplicates'],counts['invalid_results'],excluded,len(candidates),run['run_id'],run['attempt_token']))
            stage='subscription_article_preprocessing'
            retained,request_id=await preprocess_subscription_articles(config['topic'],candidates,history)
            stage='subscription_article_storage'
            result,ids=save_candidates(run,config,retained,request_id,counts)
        # Images are optional; a missing image must not undo successful collection.
        semaphore=asyncio.Semaphore(4)
        async def image(aid):
            async with semaphore:
                try:await asyncio.to_thread(ensure_article_image,aid)
                except Exception as error:record_error(user_id,'subscription_article_image',error)
        await asyncio.gather(*(image(aid) for aid in ids))
        return public_run(result)
    except BaseException as error:
        with database() as db:
            db.execute("UPDATE subscription_collection_runs SET status=?,completed_at=? WHERE run_id=? AND attempt_token=? AND status='running'",('cancelled' if isinstance(error,asyncio.CancelledError) else 'failed',now(),run['run_id'],run['attempt_token']))
        if isinstance(error,Exception):record_error(user_id,stage,error)
        raise
    finally:
        subscription_collection_context.reset(context_token);llm_user_context.reset(user_token)


def public_run(run):
    return {key:value for key,value in run.items() if key not in ('attempt_token','configuration_json')}


class CollectBody(BaseModel):
    collection_date: date | None=None


@router.post('/{subscription_id}/collect')
async def collect_subscription(subscription_id: str,body: CollectBody,user=Depends(tracked_member_user)):
    with database() as db:
        sub=db.execute('SELECT * FROM subscriptions WHERE subscription_id=? AND user_id=?',(subscription_id,user['user_id'])).fetchone()
    if not sub:raise HTTPException(404,'구독을 찾을 수 없습니다.')
    if sub['status']!='active':raise HTTPException(409,'구독 중 상태에서만 수집할 수 있습니다.')
    today=datetime.now(KST).date();day=body.collection_date or today-timedelta(days=1)
    if day>=today:raise HTTPException(422,'한국 시간 기준 어제까지의 날짜만 수집할 수 있습니다.')
    return await collect_sample(sub['sample_id'],day,user['user_id'])


@router.get('/{subscription_id}/collections')
def collection_history(subscription_id: str,user=Depends(tracked_member_user)):
    with database() as db:
        sub=db.execute('SELECT sample_id FROM subscriptions WHERE subscription_id=? AND user_id=?',(subscription_id,user['user_id'])).fetchone()
        if not sub:raise HTTPException(404,'구독을 찾을 수 없습니다.')
        return [public_run(dict(r)) for r in db.execute('SELECT * FROM subscription_collection_runs WHERE sample_id=? ORDER BY collection_date DESC LIMIT 200',(sub['sample_id'],))]
