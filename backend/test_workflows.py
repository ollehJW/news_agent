import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from openai import RateLimitError
from backend import auth
from backend.main import app
from backend.domains import Domain
from backend.test_domains import DOMAIN
from backend.llm_client import chat_completion, InvalidLLMResponse
from backend.tracking import run_context, init_newsletter_db
from backend.streaming import recommendation_events

HEADERS={'X-WiaNews-Request':'1'}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.object(auth,'DB_PATH',Path(self.temp.name)/'app.db');self.patch.start()
        self.admin=TestClient(app,headers=HEADERS);self.admin.__enter__()
        self.admin.post('/api/auth/login',json={'employee_id':'admin','password':'admin123'})
        opts=self.admin.get('/api/admin/options').json()
        self.clients=[]
        for employee in ['50001','50002']:
            result=self.admin.post('/api/admin/users',json={'employee_id':employee,'full_name':employee,'team_id':opts['teams'][0]['team_id'],'role_id':next(r['role_id'] for r in opts['roles'] if r['name']=='매니저')})
            self.assertEqual(result.status_code,201,result.text)
            c=TestClient(app,headers=HEADERS);c.post('/api/auth/login',json={'employee_id':employee,'password':auth.INITIAL_PASSWORD});c.post('/api/auth/password',json={'current_password':auth.INITIAL_PASSWORD,'new_password':'Testpass123!'})
            self.clients.append(c)
        self.client,self.other=self.clients
        self.run=self.client.post('/api/runs',json={'topic':'AI Agent'}).json()['run_id']

    def tearDown(self):
        for c in self.clients:c.close()
        self.admin.__exit__(None,None,None);self.patch.stop();self.temp.cleanup()

    def prepare(self):
        self.assertEqual(self.client.put(f'/api/runs/{self.run}/sources',json={'domains':[{'host':'example.org','custom':True}]}).status_code,200)
        self.assertEqual(self.client.put(f'/api/runs/{self.run}/period',json={'start':'2026-09-11','end':'2026-09-17'}).status_code,200)
        response=self.client.post(f'/api/runs/{self.run}/collect-demo')
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['issues']

    def test_eight_tables_full_flow_snapshots_images_and_events(self):
        expected={'newsletter_runs','domains','run_domains','run_articles','run_issues','newsletters','usage_events','ai_requests'}
        with auth.database() as db:
            self.assertTrue(expected.issubset({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}))
        issues=self.prepare();self.assertEqual(len(issues),6);self.assertEqual(sum(i['selected'] for i in issues),5)
        with auth.database() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM run_articles WHERE run_id=?',(self.run,)).fetchone()[0],9)
            self.assertEqual(db.execute('SELECT count(DISTINCT issue_id) FROM run_articles').fetchone()[0],6)
            db.execute("UPDATE run_articles SET image_url='https://example.org/image.png',favicon_url='https://example.org/icon.ico' WHERE issue_id=?",(issues[-1]['id'],))
        self.client.put(f'/api/runs/{self.run}/selection',json={'issue_ids':[issues[-1]['id']]})
        response=self.client.post(f'/api/runs/{self.run}/newsletter');self.assertEqual(response.status_code,200,response.text)
        letter=response.json();self.assertEqual(letter['count'],1);self.assertIn('https://example.org/image.png',letter['html']);self.assertIn('WiaNews',letter['html'])
        self.assertEqual(self.client.post(f'/api/runs/{self.run}/newsletter').json()['id'],letter['id'])
        self.assertEqual(self.client.get('/api/newsletters').json(),[])
        for _ in range(2):self.assertEqual(self.client.post(f"/api/newsletters/{letter['id']}/save").status_code,200)
        self.assertEqual(len(self.client.get('/api/newsletters').json()),1)
        response=self.client.get(f"/api/newsletters/{letter['id']}/download");self.assertEqual(response.status_code,200);self.assertEqual(response.text,letter['html'])
        self.client.post(f'/api/runs/{self.run}/collect-demo')
        self.assertEqual(self.client.get('/api/newsletters').json()[0]['html'],letter['html'])
        with auth.database() as db:
            counts={r[0]:r[1] for r in db.execute('SELECT event_type,count(*) FROM usage_events WHERE run_id=? GROUP BY event_type',(self.run,))}
            self.assertEqual(counts['newsletter_saved'],1);self.assertEqual(counts['newsletter_download_requested'],1)
            self.assertIn('issue_deselected',counts);self.assertIn('issue_selected',counts)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_ownership_and_validation(self):
        issues=self.prepare();letter=self.client.post(f'/api/runs/{self.run}/newsletter').json()
        paths=[('GET',f'/api/runs/{self.run}',None),('GET',f'/api/runs/{self.run}/usage',None),('PUT',f'/api/runs/{self.run}/sources',{'domains':[]}),('PUT',f'/api/runs/{self.run}/period',{'start':'2026-09-01','end':'2026-09-02'}),('PUT',f'/api/runs/{self.run}/selection',{'issue_ids':[]}),('POST',f'/api/runs/{self.run}/collect-demo',{}),('POST',f'/api/runs/{self.run}/newsletter',{}),('POST',f'/api/runs/{self.run}/step',{'step':1}),('POST',f"/api/newsletters/{letter['id']}/save",{}),('GET',f"/api/newsletters/{letter['id']}/download",None),('POST','/api/domains/recommend/stream',{'topic':'AI Agent','run_id':self.run})]
        for method,path,body in paths:
            response=self.other.request(method,path,json=body)
            self.assertEqual(response.status_code,404,(path,response.text))
        self.assertEqual(self.other.get('/api/newsletters').json(),[])
        self.assertEqual(self.client.put(f'/api/runs/{self.run}/selection',json={'issue_ids':['foreign-id']}).status_code,400)
        self.client.put(f'/api/runs/{self.run}/selection',json={'issue_ids':[]})
        self.assertEqual(self.client.post(f'/api/runs/{self.run}/newsletter').status_code,400)
        self.assertEqual(self.client.put(f'/api/runs/{self.run}/period',json={'start':'2026-10-01','end':'2026-09-01'}).status_code,400)
        self.assertEqual(self.client.post('/api/domains/recommend/stream',json={'topic':'Changed','run_id':self.run}).status_code,409)
        self.assertEqual(self.admin.get('/api/runs').status_code,403)

    def test_recommendation_snapshots_selection_and_partial_failure(self):
        async def generated(topic):
            yield Domain(**DOMAIN)
            raise InvalidLLMResponse('secret detail')
        with patch('backend.streaming.stream_domains',generated):
            response=self.client.post('/api/domains/recommend/stream',json={'topic':'AI Agent','run_id':self.run})
        self.assertIn('event: domain',response.text);self.assertIn('event: error',response.text);self.assertNotIn('secret detail',response.text)
        stored=self.client.get(f'/api/runs/{self.run}').json()['recommendations'];self.assertEqual(len(stored),1)
        self.assertFalse(stored[0]['selected']);self.assertEqual(stored[0]['reason'],DOMAIN['reason']);self.assertEqual(stored[0]['relevance'],DOMAIN['relevance'])
        self.client.put(f'/api/runs/{self.run}/sources',json={'domains':[{'host':DOMAIN['host'],'run_domain_id':stored[0]['run_domain_id']}]})
        self.client.put(f'/api/runs/{self.run}/sources',json={'domains':[]})
        stored=self.client.get(f'/api/runs/{self.run}').json()['recommendations'];self.assertEqual(len(stored),1);self.assertFalse(stored[0]['selected'])
        with auth.database() as db:self.assertEqual(db.execute('SELECT description FROM run_domains').fetchone()[0],DOMAIN['desc'])

    def test_domain_column_migration_preserves_recommendations_and_references(self):
        from backend.workflows import store_recommendation, shared_domain
        snapshot_id = store_recommendation(self.run, 'batch', Domain(**DOMAIN), 1)
        self.prepare()
        with auth.database() as db:
            before = [dict(r) for r in db.execute('SELECT * FROM run_domains ORDER BY run_domain_id')]
            articles = [tuple(r) for r in db.execute('SELECT article_id,domain_id FROM run_articles ORDER BY article_id')]
            domain_ids = [tuple(r) for r in db.execute('SELECT domain_id,host FROM domains ORDER BY host')]
            db.execute('ALTER TABLE domains ADD COLUMN kind TEXT')
            db.execute('ALTER TABLE domains ADD COLUMN description TEXT')
            db.execute("UPDATE domains SET kind='legacy',description='legacy description'")
        init_newsletter_db()
        init_newsletter_db()
        with auth.database() as db:
            self.assertEqual({r['name'] for r in db.execute('PRAGMA table_info(domains)')},
                             {'domain_id','host','name','created_at','updated_at'})
            self.assertEqual([dict(r) for r in db.execute('SELECT * FROM run_domains ORDER BY run_domain_id')], before)
            self.assertEqual([tuple(r) for r in db.execute('SELECT article_id,domain_id FROM run_articles ORDER BY article_id')], articles)
            self.assertEqual([tuple(r) for r in db.execute('SELECT domain_id,host FROM domains ORDER BY host')], domain_ids)
            shared_domain(db, DOMAIN['host'], DOMAIN['host'])
            self.assertEqual(db.execute('SELECT name FROM domains WHERE host=?', (DOMAIN['host'],)).fetchone()[0], DOMAIN['name'])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        recommendations = self.client.get(f'/api/runs/{self.run}').json()['recommendations']
        item = next(r for r in recommendations if r['run_domain_id'] == snapshot_id)
        self.assertEqual(item['kind'], DOMAIN['kind'])
        self.assertEqual(item['desc'], DOMAIN['desc'])

    def test_token_retry_failure_cancel_and_concurrent_run_isolation(self):
        other_run=self.other.post('/api/runs',json={'topic':'Other'}).json()['run_id']
        usage=SimpleNamespace(prompt_tokens=100,completion_tokens=20,total_tokens=120,prompt_tokens_details=SimpleNamespace(cached_tokens=30))
        response=SimpleNamespace(id='provider-id',usage=usage,choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='{}',refusal=None))])
        error=RateLimitError('secret',response=httpx.Response(429,request=httpx.Request('POST','https://example.org'),headers={'retry-after-ms':'0'}),body=None)
        context=AsyncMock();create=AsyncMock(side_effect=[error,response,asyncio.CancelledError(),response]);context.__aenter__.return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        async def run():
            token=run_context.set(self.run)
            try:
                await chat_completion([],{},operation='domain_shortlist')
                with self.assertRaises(asyncio.CancelledError):await chat_completion([],{},operation='domain_detail')
            finally:run_context.reset(token)
            token=run_context.set(other_run)
            try:await chat_completion([],{},operation='domain_detail')
            finally:run_context.reset(token)
        with patch('backend.llm_client.create_llm_client',return_value=context),patch.dict('os.environ',{'OPENAI_MODEL':'test-model'}):asyncio.run(run())
        result=self.client.get(f'/api/runs/{self.run}/usage').json()
        self.assertEqual(result['call_count'],3);self.assertEqual(result['total_tokens'],120);self.assertEqual(result['cached_input_tokens'],30)
        self.assertEqual(result['unknown_usage_count'],2);self.assertEqual(result['failed_count'],1)
        self.assertEqual(result['requests'][0]['logical_call_id'],result['requests'][1]['logical_call_id'])
        self.assertIsNone(result['requests'][0]['input_tokens']);self.assertEqual(result['requests'][2]['status'],'cancelled')
        self.assertEqual(self.other.get(f'/api/runs/{other_run}/usage').json()['total_tokens'],120)
