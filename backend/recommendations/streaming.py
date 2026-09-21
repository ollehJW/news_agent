"""Incremental, validated domain events for the recommendation dialog."""
import asyncio
import json
from contextlib import aclosing

from fastapi import APIRouter, Depends
from backend.core.error_storage import tracked_member_user as member_user, ErrorRoute, record_sample_error
from backend.core.tracking import sample_context
from backend.samples.workflows import prepare_recommendation, store_recommendation
from fastapi.responses import StreamingResponse
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from backend.recommendations.domains import RecommendationRequest
from backend.recommendations.query_storage import QueryBatch, QueryPreview, recommend_queries
from backend.integrations.llm_client import ConfigurationError, InvalidLLMResponse

router = APIRouter(route_class=ErrorRoute)


from backend.recommendations.domain_generation import generate_domains as stream_domains


def sse(event, data):
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


async def recommendation_events(topic, sample_id=None, batch=None):
    token = sample_context.set(sample_id)
    count = 0
    state = 'failed'
    try:
        yield sse('start', {'limit': 20, 'sample_id': sample_id})
        async with asyncio.timeout(125):
            async with aclosing(stream_domains(topic)) as domains:
                async for domain in domains:
                    if isinstance(domain, QueryPreview):
                        yield sse('query', domain.model_dump())
                        continue
                    if isinstance(domain, QueryBatch):
                        queries = recommend_queries(sample_id, domain) if sample_id else domain.queries
                        yield sse('queries', {'queries': queries})
                        continue
                    count += 1
                    data = domain.model_dump()
                    if sample_id:
                        data['recommendation_id'] = store_recommendation(sample_id,batch,domain,domain._recommendation_rank or count)
                    data['request_id'] = domain._request_id
                    data['kind'] = 'recommended'
                    yield sse('domain', data)
        state = 'completed'
        yield sse('done', {'count': count})
    except ConfigurationError as error:
        record_sample_error(sample_id,'sample_domain_recommendation',error)
        yield sse('error', {'message': 'LLM 연결 설정을 확인해 주세요.'})
    except (TimeoutError, APITimeoutError) as error:
        record_sample_error(sample_id,'sample_domain_recommendation',error)
        yield sse('error', {'message': '추천 시간이 초과되었습니다. 받은 목록을 사용하거나 다시 추천받을 수 있어요.'})
    except RateLimitError as error:
        record_sample_error(sample_id,'sample_domain_recommendation',error)
        yield sse('error', {'message': '추천 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.'})
    except (APIConnectionError, APIStatusError, InvalidLLMResponse) as error:
        record_sample_error(sample_id,'sample_domain_recommendation',error)
        yield sse('error', {'message': '추천이 중단되었습니다. 받은 목록을 사용하거나 다시 추천받을 수 있어요.'})

    except (asyncio.CancelledError, GeneratorExit):
        state = 'cancelled'
        raise
    except Exception as error:
        record_sample_error(sample_id,'sample_domain_recommendation',error)
        yield sse('error', {'message': '추천 처리 또는 기록 저장에 실패했습니다. 다시 시도해 주세요.'})
    finally:
        sample_context.reset(token)


@router.post('/api/domains/recommend/stream')
async def recommend_stream(request: RecommendationRequest, user=Depends(member_user)):
    sample_id, batch = prepare_recommendation(request.topic, user['user_id'], request.sample_id)
    return StreamingResponse(recommendation_events(request.topic, sample_id, batch), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
