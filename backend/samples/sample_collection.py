"""Sample-only collection pipeline with progress events and atomic result replacement."""
import asyncio
import json
import uuid
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from backend.core.auth import database, now
from backend.core.error_storage import ErrorRoute, tracked_member_user, record_sample_error
from backend.core.tracking import sample_context
from backend.samples.workflows import owned_sample, sources, issue_rows
from backend.recommendations.query_storage import queries_for_sample
from backend.samples.sample_lifecycle import editable_sample
from backend.samples.runs import create_run,progress_run,set_step
from backend.integrations.exa_search import search_articles
from backend.samples.sample_preprocessing import preprocess_articles
from backend.news.news_scoring import score_articles
from backend.news.article_repository import prepare_articles
from backend.integrations.llm_client import ConfigurationError, InvalidLLMResponse

router=APIRouter(prefix='/api/samples',route_class=ErrorRoute)
# One uvicorn worker is used locally. The final database snapshot check also guards concurrent writers.
_active=set()

def snapshot(db,sid,uid):
    sample=dict(owned_sample(db,sid,uid))
    domains=sources(db,sid);queries=queries_for_sample(db,sid)
    revision={'sample':{k:sample[k] for k in ('sample_id','run_id','user_id','topic','collection_start_date','collection_end_date')},'domains':domains,'queries':queries,'issues':[tuple(r) for r in db.execute('SELECT issue_id,article_id,rank FROM sample_issues WHERE sample_id=? ORDER BY issue_id',(sid,))]}
    return sample,domains,queries,json.dumps(revision,sort_keys=True)

def save_result(sid,uid,revision,articles,scores):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        if snapshot(db,sid,uid)[3]!=revision:raise HTTPException(409,'수집 중 샘플 설정이 변경되었습니다. 변경된 설정으로 다시 수집해 주세요.')
        target,_=editable_sample(db,sid)
        db.execute('DELETE FROM sample_issues WHERE sample_id=?',(target,))
        db.execute('DELETE FROM sample_articles WHERE sample_id=?',(target,))
        stamp=now()
        by_id={a['article_id']:a for a in articles}
        for rank,score in enumerate(scores,1):
            a=by_id[score['article_id']]
            db.execute('INSERT INTO sample_articles (sample_id,article_id,request_id) VALUES (?,?,?)',
                       (target,a['article_id'],a.get('preprocessing_request_id')))
            if rank<=5:
                db.execute('INSERT INTO sample_issues (issue_id,sample_id,article_id,request_id,rank,created_at) VALUES (?,?,?,?,?,?)',
                           (str(uuid.uuid4()),target,a['article_id'],score['request_id'],rank,stamp))
        set_step(db,target,'news_selection')
        return {'sample_id':target,'issues':issue_rows(db,target),'article_count':len(articles),
                'retained_count':len(scores),'excluded_count':len(articles)-len(scores),'data_mode':'live'}

async def run_collection(sid,uid,config,progress):
    sample,domains,queries,revision=config
    start=date.fromisoformat(sample['collection_start_date']);end=date.fromisoformat(sample['collection_end_date'])
    stage='sample_article_collection'
    try:
        await progress(0,'선택한 쿼리와 도메인에서 뉴스를 수집하고 있어요')
        articles,counts=await search_articles(queries,domains,start,end,progress)
        prepare_articles(articles)
        stage='sample_article_preprocessing'
        progress_run(sample['run_id'],'news_preprocessing')
        retained=await preprocess_articles(sample['topic'],articles,progress)
        stage='sample_issue_scoring'
        progress_run(sample['run_id'],'news_scoring')
        await progress(2,f'전처리를 통과한 {len(retained)}개 이슈의 중요도를 평가하고 있어요')
        scores=await score_articles(sample['topic'],retained,end,progress,operation='sample_issue_scoring') if retained else []
        stage='sample_collection_save'
        result=save_result(sid,uid,revision,articles,scores)
        result['collection_stats']=counts
        return result
    except BaseException as error:
        with database() as db:
            db.execute('UPDATE sample_runs SET status=?,completed_at=? WHERE run_id=?',('cancelled' if isinstance(error,asyncio.CancelledError) else 'failed',now(),sample['run_id']))
        if isinstance(error,Exception):record_sample_error(sid,stage,error)
        raise

def event(name,data):return f'event: {name}\ndata: {json.dumps(data,ensure_ascii=False)}\n\n'

async def collection_events(sid,uid,config):
    queue=asyncio.Queue();token=sample_context.set(sid);task=None
    async def progress(stage,message):await queue.put({'stage':stage,'message':message})
    async def execute():
        try:
            async with asyncio.timeout(360):return await run_collection(sid,uid,config,progress)
        finally:await queue.put(None)
    try:
        task=asyncio.create_task(execute())
        while True:
            try:item=await asyncio.wait_for(queue.get(),timeout=10)
            except TimeoutError:
                yield ': heartbeat\n\n';continue
            if item is None:break
            yield event('progress',item)
        result=await task
        yield event('done',result)
    except (asyncio.CancelledError,GeneratorExit):raise
    except Exception as error:
        record_sample_error(sid,'sample_article_collection',error)
        message=error.detail if isinstance(error,HTTPException) else 'LLM 연결 설정을 확인해 주세요.' if isinstance(error,ConfigurationError) else '기사 분석 응답을 검증하지 못했습니다. 다시 시도해 주세요.' if isinstance(error,InvalidLLMResponse) else '뉴스 수집·분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.'
        yield event('error',{'message':message})
    finally:
        if task and not task.done():task.cancel()
        if task:await asyncio.gather(task,return_exceptions=True)
        sample_context.reset(token);_active.discard(sid)

@router.post('/{sample_id}/collect')
async def collect(sample_id:str,user=Depends(tracked_member_user)):
    with database() as db:config=snapshot(db,sample_id,user['user_id'])
    sample,domains,queries,_=config
    if not domains or not queries or not sample['collection_start_date'] or not sample['collection_end_date']:
        raise HTTPException(400,'수집 쿼리, 도메인, 기간을 먼저 설정해 주세요.')
    if sample_id in _active:raise HTTPException(409,'이 샘플의 수집이 이미 진행 중입니다.')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        target,_=editable_sample(db,sample_id)
        current=dict(owned_sample(db,target,user['user_id']))
        if target==sample_id and (current['current_step'] in ('news_collection','news_preprocessing','news_scoring','news_selection') or current['run_status'] in ('failed','cancelled')):
            create_run(db,target,user['user_id'],current['topic'],current['collection_start_date'],current['collection_end_date'])
        set_step(db,target,'news_collection','running')
        config=snapshot(db,target,user['user_id'])
    sample_id=target
    _active.add(sample_id)
    return StreamingResponse(collection_events(sample_id,user['user_id'],config),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
