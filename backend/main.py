import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from .auth import router as auth_router, init_db, member_user
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from .domains import RecommendationRequest, RecommendationResponse, recommend_domains
from .llm_client import ConfigurationError, InvalidLLMResponse

from .streaming import router as streaming_router
from .tracking import init_newsletter_db, run_context
from .workflows import router as workflow_router, prepare_recommendation, store_recommendation, recommendation_finished

@asynccontextmanager
async def lifespan(app):
    init_db()
    init_newsletter_db()
    yield


app = FastAPI(title='WiaNews API', version='0.2.0', lifespan=lifespan)
app.include_router(auth_router)
app.include_router(workflow_router)
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


@app.post('/api/domains/recommend', response_model=RecommendationResponse, dependencies=[Depends(member_user)])
async def recommend(request: RecommendationRequest, user=Depends(member_user)):
    run_id, batch = prepare_recommendation(request.topic, user['user_id'], request.run_id)
    token = run_context.set(run_id)
    state, count = 'failed', 0
    try:
        async with asyncio.timeout(125):
            result = await recommend_domains(request.topic)
            if run_id:
                for rank, domain in enumerate(result.domains, 1):
                    store_recommendation(run_id,batch,domain,rank)
                    count += 1
            result.run_id = run_id
            state = 'completed'
            return result
    except ConfigurationError:
        raise HTTPException(503, 'LLM 연결 설정이 필요합니다. 서버의 환경변수를 확인해 주세요.') from None
    except (TimeoutError, APITimeoutError):
        raise HTTPException(504, '추천 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.') from None
    except RateLimitError:
        raise HTTPException(429, '추천 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.') from None
    except APIConnectionError:
        raise HTTPException(502, 'LLM 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.') from None
    except (APIStatusError, InvalidLLMResponse):
        raise HTTPException(502, '유효한 추천 결과를 받지 못했습니다. 다시 시도해 주세요.') from None
    finally:
        run_context.reset(token)
        if run_id:
            recommendation_finished(run_id,batch,state,count)
