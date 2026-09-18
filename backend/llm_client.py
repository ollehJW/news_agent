"""Azure OpenAI connection patterned after wiameet_dev/backend/llm_client.py."""
import asyncio
import logging
import os
import time
from .tracking import start_attempt, finish_attempt
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import AsyncAzureOpenAI, APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
log = logging.getLogger(__name__)


class CompletionText(str):
    def __new__(cls, content, request_id):
        value = super().__new__(cls, content)
        value.request_id = request_id
        return value


class ConfigurationError(Exception):
    pass


class InvalidLLMResponse(Exception):
    pass


def create_llm_client():
    values = {key: os.getenv(key, '') for key in ('OPENAI_MODEL', 'OPENAI_API_KEY', 'OPENAI_BASE_URL')}
    if not all(values.values()):
        raise ConfigurationError('LLM configuration is incomplete')
    return AsyncAzureOpenAI(
        azure_endpoint=values['OPENAI_BASE_URL'],
        api_key=values['OPENAI_API_KEY'],
        api_version=os.getenv('OPENAI_API_VERSION', '2025-04-01-preview'),
        timeout=httpx.Timeout(60, connect=10),
        max_retries=0,
    )


def retryable(exc):
    return isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)) or (
        isinstance(exc, APIStatusError) and exc.status_code >= 500
    )


def retry_delay(exc):
    headers = getattr(getattr(exc, 'response', None), 'headers', {})
    try:
        if headers.get('retry-after-ms'):
            return min(5, max(0, float(headers['retry-after-ms']) / 1000))
        return min(5, max(0, float(headers.get('retry-after', '1'))))
    except ValueError:
        return 1


async def chat_completion(messages, schema, max_tokens=16000, operation="domain_recommendation"):
    for attempt in range(2):
        started = time.monotonic()
        request_id = start_attempt(operation)
        response = None
        try:
            async with create_llm_client() as client:
                response = await client.chat.completions.create(
                    model=os.environ['OPENAI_MODEL'], messages=messages,
                    response_format={'type': 'json_schema', 'json_schema': {
                        'name': 'domain_recommendations', 'strict': True, 'schema': schema}},
                    max_completion_tokens=max_tokens,
                )
            if not response.choices:
                raise InvalidLLMResponse('No choices returned')
            choice = response.choices[0]
            if choice.finish_reason != 'stop' or choice.message.refusal or not choice.message.content:
                raise InvalidLLMResponse('Incomplete or refused response')
            finish_attempt(request_id, 'success', round((time.monotonic()-started)*1000), response)
            return CompletionText(choice.message.content, request_id)
        except asyncio.CancelledError as exc:
            finish_attempt(request_id, 'cancelled', round((time.monotonic()-started)*1000), response, exc)
            raise
        except Exception as exc:
            finish_attempt(request_id, 'failed', round((time.monotonic()-started)*1000), response, exc)
            log.warning('domain_recommendation failed attempt=%s type=%s status=%s',
                        attempt + 1, type(exc).__name__, getattr(exc, 'status_code', None))
            if attempt == 1 or not retryable(exc):
                raise
            await asyncio.sleep(retry_delay(exc))
