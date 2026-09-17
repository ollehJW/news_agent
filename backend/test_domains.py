import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from openai import APIStatusError, RateLimitError, APITimeoutError
from pydantic import ValidationError

from backend.domains import RecommendationRequest, normalize_host, recommend_domains
from backend.llm_client import ConfigurationError, InvalidLLMResponse, chat_completion, retryable, retry_delay
from backend.main import app
from backend.auth import member_user

DOMAIN = {'host': 'react.dev', 'name': 'React', 'kind': '공식 사이트', 'desc': 'React 공식 소식',
          'reason': '개발 팀이 발표하는 1차 출처', 'relevance': 'React 릴리스와 개발 방식'}


class DomainTests(unittest.IsolatedAsyncioTestCase):
    def test_topic_validation(self):
        self.assertEqual(RecommendationRequest(topic=' React 기반 웹 개발 ').topic, 'React 기반 웹 개발')
        for value in ['', ' ', 'x'*121, ['React'], None]:
            with self.assertRaises(ValidationError):
                RecommendationRequest(topic=value)

    def test_public_host_validation(self):
        self.assertEqual(normalize_host('https://www.React.dev/blog'), 'react.dev')
        for value in ['javascript:alert(1)', '127.0.0.1', 'localhost', 'service.local', 'https://a:b@react.dev', 'https://react.dev:443', '-bad.com', 'foo..com']:
            with self.assertRaises(ValueError):
                normalize_host(value)

    async def test_deduplication_and_prompt_data(self):
        with patch('backend.domains.chat_completion', new_callable=AsyncMock) as call:
            call.return_value = json.dumps({'domains': [DOMAIN, {**DOMAIN, 'host': 'www.react.dev'}]})
            result = await recommend_domains('React')
            self.assertEqual(len(result.domains), 1)
            self.assertEqual(result.source, 'llm')
            self.assertEqual(json.loads(call.call_args.args[0][1]['content']), {'topic': 'React'})

    async def test_bad_and_empty_provider_output(self):
        for raw in ['not json', '{"domains":[{}]}', json.dumps({'domains': [{**DOMAIN, 'host': 'localhost'}]})]:
            with patch('backend.domains.chat_completion', new=AsyncMock(return_value=raw)):
                with self.assertRaises(InvalidLLMResponse):
                    await recommend_domains('React')
        with patch('backend.domains.chat_completion', new=AsyncMock(return_value='{"domains":[]}')):
            self.assertEqual((await recommend_domains('React')).domains, [])

    async def test_llm_request_and_retry(self):
        response = httpx.Response(429, request=httpx.Request('POST', 'https://example.com'), headers={'retry-after-ms': '0'})
        rate_error = RateLimitError('secret upstream body', response=response, body=None)
        result = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(refusal=None, content='{"domains":[]}'))], usage=None)
        create = AsyncMock(side_effect=[rate_error, result])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        context = AsyncMock(); context.__aenter__.return_value = client
        with patch('backend.llm_client.create_llm_client', return_value=context), patch.dict('os.environ', {'OPENAI_MODEL': 'test-deployment'}):
            self.assertEqual(await chat_completion([], {}), '{"domains":[]}')
        self.assertEqual(create.await_count, 2)
        self.assertEqual(create.call_args.kwargs['response_format']['json_schema']['strict'], True)
        self.assertEqual(create.call_args.kwargs['model'], 'test-deployment')
        self.assertTrue(retryable(rate_error))
        self.assertEqual(retry_delay(rate_error), 0)


class APITests(unittest.TestCase):
    def setUp(self):
        self.override = patch.dict(app.dependency_overrides, {member_user: lambda: {'is_admin': False, 'user_id': 'test-user'}})
        self.override.start()
        self.addCleanup(self.override.stop)
        self.prepare = patch('backend.main.prepare_recommendation', return_value=(None,None))
        self.prepare.start()
        self.addCleanup(self.prepare.stop)
        self.client = TestClient(app, headers={'X-WiaNews-Request': '1'})

    def test_health_and_request_validation(self):
        self.assertEqual(self.client.get('/api/health').json()['service'], 'WiaNews')
        with patch('backend.main.recommend_domains', new_callable=AsyncMock) as call:
            for body in [{}, {'topic': ''}, {'topic': ['React']}, {'keywords': ['React']}, {'topic': 'React', 'extra': 1}]:
                self.assertEqual(self.client.post('/api/domains/recommend', json=body).status_code, 422)
            call.assert_not_called()

    def test_success_contract(self):
        with patch('backend.domains.chat_completion', new=AsyncMock(return_value=json.dumps({'domains': [DOMAIN]}))):
            response = self.client.post('/api/domains/recommend', json={'topic': 'React'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['domains'][0]['host'], 'react.dev')

    def test_safe_error_messages(self):
        request = httpx.Request('POST', 'https://example.com')
        exceptions = [
            (ConfigurationError('secret'), 503), (InvalidLLMResponse('secret'), 502),
            (APITimeoutError(request=request), 504),
            (RateLimitError('secret', response=httpx.Response(429, request=request), body=None), 429),
            (APIStatusError('secret', response=httpx.Response(401, request=request), body=None), 502),
        ]
        for exc, status in exceptions:
            with patch('backend.main.recommend_domains', new=AsyncMock(side_effect=exc)):
                response = self.client.post('/api/domains/recommend', json={'topic': 'React'})
            self.assertEqual(response.status_code, status)
            self.assertNotIn('secret', response.text)


if __name__ == '__main__':
    unittest.main()
