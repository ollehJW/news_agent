import asyncio
from contextlib import asynccontextmanager

from backend.mail.delivery import router as mail_router, init_mail_db
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from backend.core.auth import router as auth_router, init_db
from backend.core.error_storage import tracked_member_user as member_user, ErrorRoute, record_sample_error
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from backend.recommendations.domains import RecommendationRequest, RecommendationResponse, recommend_domains
from backend.recommendations.query_storage import QueryBatch, recommend_queries
from backend.integrations.llm_client import ConfigurationError, InvalidLLMResponse

from backend.recommendations.streaming import router as streaming_router
from backend.subscriptions.subscriptions import router as subscriptions_router
from backend.recommendations.subject_validation import router as subject_validation_router
from backend.samples.sample_collection import router as sample_collection_router
from backend.core.tracking import init_newsletter_db, sample_context
from backend.samples.workflows import router as workflow_router, prepare_recommendation, store_recommendation

@asynccontextmanager
async def lifespan(app):
    init_db()
    init_newsletter_db()
    init_mail_db()
    yield


app = FastAPI(title='WiaNews API', version='0.2.0', lifespan=lifespan)
app.router.route_class = ErrorRoute
app.include_router(auth_router)
app.include_router(mail_router)
app.include_router(workflow_router)
app.include_router(subscriptions_router)
app.include_router(subject_validation_router)
app.include_router(sample_collection_router)
app.include_router(streaming_router, dependencies=[Depends(member_user)])


@app.middleware('http')
async def csrf_guard(request: Request, call_next):
    # Cross-origin forms cannot supply this header. No cross-origin CORS is enabled.
    if request.url.path.startswith('/api/') and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if request.headers.get('X-WiaNews-Request') != '1':
            return JSONResponse({'detail': '허용되지 않은 요청입니다.'}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith('/api/auth/') or request.url.path.startswith('/api/admin/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'service': 'WiaNews'}


def recommendation_failure(sample_id, error, status, message):
    record_sample_error(sample_id,'sample_domain_recommendation',error)
    failure=HTTPException(status,message)
    failure._wianews_error_logged=getattr(error,'_wianews_error_logged',False)
    return failure


@app.post('/api/domains/recommend', response_model=RecommendationResponse, dependencies=[Depends(member_user)])
async def recommend(request: RecommendationRequest, user=Depends(member_user)):
    sample_id, batch = prepare_recommendation(request.topic, user['user_id'], request.sample_id)
    token = sample_context.set(sample_id)
    state, count = 'failed', 0
    try:
        async with asyncio.timeout(125):
            result = await recommend_domains(request.topic)
            if sample_id:
                query_batch = QueryBatch(queries=result.queries)
                query_batch._request_id = result._request_id
                result.query_recommendations = recommend_queries(sample_id, query_batch)
                for rank, domain in enumerate(result.domains, 1):
                    store_recommendation(sample_id,batch,domain,rank)
                    count += 1
            result.sample_id = sample_id
            state = 'completed'
            return result
    except ConfigurationError as error:
        raise recommendation_failure(sample_id,error,503, 'LLM 연결 설정이 필요합니다. 서버의 환경변수를 확인해 주세요.') from None
    except (TimeoutError, APITimeoutError) as error:
        raise recommendation_failure(sample_id,error,504, '추천 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.') from None
    except RateLimitError as error:
        raise recommendation_failure(sample_id,error,429, '추천 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.') from None
    except APIConnectionError as error:
        raise recommendation_failure(sample_id,error,502, 'LLM 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.') from None
    except (APIStatusError, InvalidLLMResponse) as error:
        raise recommendation_failure(sample_id,error,502, '유효한 추천 결과를 받지 못했습니다. 다시 시도해 주세요.') from None
    finally:
        sample_context.reset(token)
