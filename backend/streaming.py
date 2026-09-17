"""Incremental, validated domain events for the recommendation dialog."""
import asyncio
import json
from contextlib import aclosing

from fastapi import APIRouter, Depends
from .auth import member_user
from .tracking import run_context
from .workflows import prepare_recommendation, store_recommendation, recommendation_finished
from fastapi.responses import StreamingResponse
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from .domains import RecommendationRequest
from .llm_client import ConfigurationError, InvalidLLMResponse

router = APIRouter()


from .domain_generation import generate_domains as stream_domains


def sse(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


async def recommendation_events(topic, run_id=None, batch=None):
    token = run_context.set(run_id)
    count = 0
    state = 'failed'
    try:
        yield sse('start', {'limit': 20, 'run_id': run_id})
        async with asyncio.timeout(125):
            async with aclosing(stream_domains(topic)) as domains:
                async for domain in domains:
                    count += 1
                    data = domain.model_dump()
                    if run_id:
                        data['run_domain_id'] = store_recommendation(run_id,batch,domain,domain._recommendation_rank or count)
                    yield sse('domain', data)
        state = 'completed'
        yield sse('done', {'count': count})
    except ConfigurationError:
        yield sse('error', {'message': 'LLM 연결 설정을 확인해 주세요.'})
    except (TimeoutError, APITimeoutError):
        yield sse('error', {'message': '추천 시간이 초과되었습니다. 받은 목록을 사용하거나 다시 추천받을 수 있어요.'})
    except RateLimitError:
        yield sse('error', {'message': '추천 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.'})
    except (APIConnectionError, APIStatusError, InvalidLLMResponse):
        yield sse('error', {'message': '추천이 중단되었습니다. 받은 목록을 사용하거나 다시 추천받을 수 있어요.'})

    except (asyncio.CancelledError, GeneratorExit):
        state = 'cancelled'
        raise
    except Exception:
        yield sse('error', {'message': '추천 처리 또는 기록 저장에 실패했습니다. 다시 시도해 주세요.'})
    finally:
        run_context.reset(token)
        if run_id:
            recommendation_finished(run_id,batch,state,count)


@router.post('/api/domains/recommend/stream')
async def recommend_stream(request: RecommendationRequest, user=Depends(member_user)):
    run_id, batch = prepare_recommendation(request.topic, user['user_id'], request.run_id)
    return StreamingResponse(recommendation_events(request.topic, run_id, batch), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
