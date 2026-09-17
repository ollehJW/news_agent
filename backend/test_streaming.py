import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import member_user
from backend.domains import Domain
from backend.llm_client import InvalidLLMResponse
from backend.domain_generation import Candidate, shortlist, describe_candidate, generate_domains
from backend.streaming import recommendation_events
from backend.test_domains import DOMAIN


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_shortlist_validation_and_dedup(self):
        raw = json.dumps({'domains': [{'host':'react.dev','name':'React'}, {'host':'www.react.dev','name':'React'}]})
        with patch('backend.domain_generation.chat_completion', new=AsyncMock(return_value=raw)):
            self.assertEqual(len(await shortlist('React')), 1)
        for raw in ['bad json', '{"domains":[{"host":"localhost","name":"x"}]}']:
            with patch('backend.domain_generation.chat_completion', new=AsyncMock(return_value=raw)):
                with self.assertRaises(InvalidLLMResponse): await shortlist('React')

    async def test_description_keeps_host(self):
        candidate=Candidate(host='react.dev',name='React')
        with patch('backend.domain_generation.chat_completion', new=AsyncMock(return_value=json.dumps(DOMAIN))):
            self.assertEqual((await describe_candidate('React',candidate)).host, 'react.dev')
        with patch('backend.domain_generation.chat_completion', new=AsyncMock(return_value=json.dumps({**DOMAIN,'host':'other.org'}))):
            with self.assertRaises(InvalidLLMResponse): await describe_candidate('React',candidate)

    async def test_bounded_concurrency_and_early_yield(self):
        gate=asyncio.Event()
        candidates=[Candidate(host=f'news{i}.org',name=f'News {i}') for i in range(8)]
        running=peak=0
        async def describe(topic,candidate):
            nonlocal running,peak
            running+=1;peak=max(peak,running)
            try:
                if candidate.host!='news0.org': await gate.wait()
                return Domain(**{**DOMAIN,'host':candidate.host})
            finally: running-=1
        with patch('backend.domain_generation.shortlist', new=AsyncMock(return_value=candidates)), patch('backend.domain_generation.describe_candidate',describe):
            stream=generate_domains('React')
            first=await asyncio.wait_for(anext(stream),1)
            self.assertEqual(first.host,'news0.org')
            self.assertFalse(gate.is_set())
            gate.set()
            rest=[d async for d in stream]
        self.assertEqual(len(rest),7)
        self.assertLessEqual(peak,3)

    async def test_cancel_closes_inflight_work(self):
        gate=asyncio.Event(); running=set()
        candidates=[Candidate(host=f'news{i}.org',name='News') for i in range(6)]
        async def describe(topic,candidate):
            running.add(candidate.host)
            try:
                if candidate.host!='news0.org': await gate.wait()
                return Domain(**{**DOMAIN,'host':candidate.host})
            finally: running.remove(candidate.host)
        with patch('backend.domain_generation.shortlist',new=AsyncMock(return_value=candidates)), patch('backend.domain_generation.describe_candidate',describe):
            stream=generate_domains('React')
            await asyncio.wait_for(anext(stream),1)
            await stream.aclose()
        self.assertEqual(running,set())

    async def test_partial_failure_preserves_success(self):
        candidates=[Candidate(host='react.dev',name='React'), Candidate(host='other.org',name='Other')]
        async def describe(topic,candidate):
            if candidate.host=='other.org': raise InvalidLLMResponse('private error')
            return Domain(**DOMAIN)
        with patch('backend.domain_generation.shortlist',new=AsyncMock(return_value=candidates)), patch('backend.domain_generation.describe_candidate',describe):
            stream=generate_domains('React')
            self.assertEqual((await anext(stream)).host,'react.dev')
            with self.assertRaises(InvalidLLMResponse): await anext(stream)


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def test_domain_event_before_all_descriptions_finish(self):
        gate=asyncio.Event()
        async def domains(topic):
            yield Domain(**DOMAIN)
            await gate.wait()
        with patch('backend.streaming.stream_domains',domains):
            events=recommendation_events('React')
            self.assertIn('event: start',await anext(events))
            self.assertIn('event: domain',await asyncio.wait_for(anext(events),1))
            self.assertFalse(gate.is_set())
            gate.set()
            self.assertIn('event: done',await anext(events))
            await events.aclose()

    async def test_partial_error_event(self):
        async def domains(topic):
            yield Domain(**DOMAIN)
            raise InvalidLLMResponse('secret provider detail')
        with patch('backend.streaming.stream_domains',domains):
            events=[event async for event in recommendation_events('React')]
        self.assertEqual(len(events),3)
        self.assertIn('event: error',events[-1])
        self.assertNotIn('secret',''.join(events))
        self.assertNotIn('event: done',''.join(events))

    def test_endpoint_contract(self):
        async def domains(topic):
            for domain in []: yield domain
        with patch('backend.streaming.stream_domains',domains), patch('backend.streaming.prepare_recommendation', return_value=(None,None)), patch.dict(app.dependency_overrides, {member_user: lambda: {'is_admin': False, 'user_id': 'test-user'}}):
            client = TestClient(app, headers={'X-WiaNews-Request': '1'})
            self.assertEqual(client.post('/api/domains/recommend/stream',json={'topic':''}).status_code,422)
            response=client.post('/api/domains/recommend/stream',json={'topic':'React'})
        self.assertIn('text/event-stream',response.headers['content-type'])
        self.assertIn('event: done',response.text)
        self.assertEqual(response.headers['x-accel-buffering'],'no')
