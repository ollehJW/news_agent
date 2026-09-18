import asyncio
import json
import sqlite3
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
from backend.tracking import sample_context, init_newsletter_db
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
        self.sample=self.client.post('/api/samples',json={'topic':'AI Agent'}).json()['sample_id']

    def tearDown(self):
        for c in self.clients:c.close()
        self.admin.__exit__(None,None,None);self.patch.stop();self.temp.cleanup()

    def prepare(self):
        self.assertEqual(self.client.put(f'/api/samples/{self.sample}/sources',json={'domains':[{'host':'example.org','custom':True}]}).status_code,200)
        self.assertEqual(self.client.put(f'/api/samples/{self.sample}/period',json={'start':'2026-09-11','end':'2026-09-17'}).status_code,200)
        response=self.client.post(f'/api/samples/{self.sample}/collect-demo')
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['issues']

    def test_eight_tables_full_flow_snapshots_images_and_events(self):
        expected={'errors','domains','sample_domains','sample_articles','sample_issues','sample_newsletters','subscripted_newsletters','llm_requests'}
        with auth.database() as db:
            self.assertTrue(expected.issubset({r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}))
        issues=self.prepare();self.assertEqual(len(issues),6);self.assertEqual(sum(i['selected'] for i in issues),5)
        with auth.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sample_articles WHERE sample_id=?",(self.sample,)).fetchone()[0],9)
            self.assertEqual(db.execute('SELECT count(*) FROM sample_issues WHERE duplicate_of_issue_id IS NULL').fetchone()[0],6)
            db.execute("UPDATE sample_articles SET image_url='https://example.org/image.png',favicon_url='https://example.org/icon.ico' WHERE article_id=(SELECT article_id FROM sample_issues WHERE issue_id=?)",(issues[-1]['id'],))
        self.client.put(f'/api/samples/{self.sample}/selection',json={'issue_ids':[issues[-1]['id']]})
        response=self.client.post(f'/api/samples/{self.sample}/newsletter');self.assertEqual(response.status_code,200,response.text)
        letter=response.json();self.assertEqual(letter['count'],1);self.assertIn('https://example.org/image.png',letter['html']);self.assertIn('WiaNews',letter['html'])
        self.assertEqual(self.client.post(f'/api/samples/{self.sample}/newsletter').json()['id'],letter['id'])
        with auth.database() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sample_newsletters WHERE status='completed'").fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM subscripted_newsletters').fetchone()[0],0)

        self.assertEqual(self.client.get('/api/newsletters').json(),[])
        for _ in range(2):self.assertEqual(self.client.post(f"/api/newsletters/{letter['id']}/save").status_code,200)
        self.assertEqual(len(self.client.get('/api/newsletters').json()),1)
        response=self.client.get(f"/api/newsletters/{letter['id']}/download");self.assertEqual(response.status_code,200);self.assertEqual(response.text,letter['html'])
        self.client.post(f'/api/samples/{self.sample}/collect-demo')
        self.assertEqual(self.client.get('/api/newsletters').json()[0]['html'],letter['html'])
        with auth.database() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='usage_events'").fetchone())
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_subscription_tables_constraints_and_shared_publication(self):
        self.prepare()
        letter = self.client.post(f'/api/samples/{self.sample}/newsletter').json()['id']
        init_newsletter_db()
        stamp = auth.now()
        with auth.database() as db:
            users = [r[0] for r in db.execute("SELECT user_id FROM users WHERE employee_id IN ('50001','50002') ORDER BY employee_id")]
            def article(aid, ref=letter, url='https://example.org/article'):
                db.execute('INSERT INTO subscripted_articles (article_id,sample_id,domain_id,url,title,collected_at) VALUES (?,?,?,?,?,?)',
                           (aid,ref,db.execute('SELECT domain_id FROM domains LIMIT 1').fetchone()[0],url,'Test article',stamp))
            article('article-1')
            with self.assertRaises(sqlite3.IntegrityError): article('article-2')
            with self.assertRaises(sqlite3.IntegrityError): article('article-3',ref='missing')
            def subscribe(sid, uid, status='active'):
                db.execute('INSERT INTO subscriptions (subscription_id,user_id,sample_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                           (sid,uid,letter,status,stamp,stamp))
            subscribe('subscription-1',users[0])
            subscribe('subscription-2',users[1])
            with self.assertRaises(sqlite3.IntegrityError): subscribe('duplicate',users[0])
            db.execute("UPDATE subscriptions SET status='cancelled' WHERE subscription_id='subscription-1'")
            self.assertEqual(db.execute('SELECT count(*) FROM subscriptions').fetchone()[0],2)
            db.execute('DELETE FROM subscriptions WHERE subscription_id=?',('subscription-1',))
            with self.assertRaises(sqlite3.IntegrityError): subscribe('bad-status',users[0],status='unknown')
            subscribe('resubscribed',users[0],status='paused')
            def issue(iid, subscription='subscription-2', article='article-1', score=87.5, request=None):
                db.execute('INSERT INTO subscripted_issues (issue_id,subscription_id,article_id,request_id,summary,total_score,created_at) VALUES (?,?,?,?,?,?,?)',
                           (iid,subscription,article,request,'Selected summary',score,stamp))
            issue('issue-1')
            issue('issue-2')  # A later edition may select the same article again.
            issue('issue-3',subscription='resubscribed')
            with self.assertRaises(sqlite3.IntegrityError): issue('bad-subscription',subscription='missing')
            with self.assertRaises(sqlite3.IntegrityError): issue('bad-article',article='missing')
            with self.assertRaises(sqlite3.IntegrityError): issue('bad-request',request='missing')
            with self.assertRaises(sqlite3.IntegrityError): issue('bad-score',score=101)
            with self.assertRaises(sqlite3.IntegrityError): db.execute("DELETE FROM subscriptions WHERE subscription_id='subscription-2'")
            with self.assertRaises(sqlite3.IntegrityError): db.execute("DELETE FROM subscripted_articles WHERE article_id='article-1'")
            def publication(pid, end='2026-09-17', selected='["issue-1"]'):
                db.execute('INSERT INTO subscripted_newsletters (newsletter_id,sample_id,coverage_start_date,coverage_end_date,issue_ids,html_content,created_at) VALUES (?,?,?,?,?,?,?)',
                           (pid,letter,'2026-09-11',end,selected,'<h1>Edition</h1>',stamp))
            publication('publication-1')
            for sid in ('subscription-2','resubscribed'):
                db.execute('INSERT INTO subscription_history VALUES (?,?,?)',(sid,'publication-1',stamp))
            with self.assertRaises(sqlite3.IntegrityError): db.execute('INSERT INTO subscription_history VALUES (?,?,?)',('resubscribed','publication-1',stamp))
            with self.assertRaises(sqlite3.IntegrityError): db.execute('INSERT INTO subscription_history VALUES (?,?,?)',('resubscribed','missing',stamp))
            with self.assertRaises(sqlite3.IntegrityError): db.execute("DELETE FROM subscripted_newsletters WHERE newsletter_id='publication-1'")
            with self.assertRaises(sqlite3.IntegrityError): publication('duplicate')
            with self.assertRaises(sqlite3.IntegrityError): publication('bad-period',end='2026-09-01')
            with self.assertRaises(sqlite3.IntegrityError): publication('bad-json',end='2026-09-18',selected='{}')
            publication('publication-2',end='2026-09-18')
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name IN ('newsletters','newsletter_publications')").fetchone())
            db.execute('UPDATE sample_newsletters SET last_issued_newsletter_id=? WHERE sample_id=?',('publication-1',letter))
            with self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM sample_newsletters WHERE sample_id=?',(letter,))
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_shared_edition_migration_preserves_history_and_latest_reference(self):
        self.prepare()
        sample_id=self.client.post(f'/api/samples/{self.sample}/newsletter').json()['id']
        stamp=auth.now()
        with auth.database() as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute('DROP TABLE subscripted_newsletters')
            db.execute("""CREATE TABLE subscripted_newsletters (
                newsletter_id TEXT PRIMARY KEY,subscription_id TEXT NOT NULL REFERENCES subscriptions(subscription_id),
                coverage_start_date TEXT NOT NULL,coverage_end_date TEXT NOT NULL,issue_ids TEXT NOT NULL,
                summary TEXT,request_id TEXT,html_content TEXT NOT NULL,created_at TEXT NOT NULL,published_at TEXT,
                UNIQUE(subscription_id,coverage_start_date,coverage_end_date))""")
            users=db.execute("SELECT user_id FROM users WHERE employee_id IN ('50001','50002') ORDER BY employee_id").fetchall()
            for index,user in enumerate(users):
                db.execute('INSERT INTO subscriptions VALUES (?,?,?,?,?,?)',(f'sub-{index}',sample_id,user[0],'active',stamp,stamp))
                db.execute('INSERT INTO subscripted_newsletters VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (f'edition-{index}',f'sub-{index}','2026-09-01','2026-09-17','[]','Summary',None,'<h1>Shared</h1>',stamp,stamp))
            db.execute('UPDATE sample_newsletters SET last_issued_newsletter_id=? WHERE sample_id=?',('edition-1',sample_id))
        init_newsletter_db()
        init_newsletter_db()
        with auth.database() as db:
            rows=db.execute('SELECT * FROM subscripted_newsletters').fetchall()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['sample_id'],sample_id)
            self.assertEqual(rows[0]['summary'],'Summary')
            self.assertEqual(rows[0]['html_content'],'<h1>Shared</h1>')
            self.assertNotIn('subscription_id',rows[0].keys())
            self.assertEqual([tuple(r) for r in db.execute('SELECT subscription_id,newsletter_id FROM subscription_history ORDER BY subscription_id')],
                             [('sub-0','edition-0'),('sub-1','edition-0')])
            self.assertEqual(db.execute('SELECT last_issued_newsletter_id FROM sample_newsletters WHERE sample_id=?',(sample_id,)).fetchone()[0],'edition-0')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_sample_article_issue_constraints_and_frozen_results(self):
        issues=self.prepare()
        with auth.database() as db:
            row=db.execute('SELECT * FROM sample_articles LIMIT 1').fetchone()
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO sample_articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',('duplicate',row['sample_id'],*(row[k] for k in ['domain_id','url','title','published_at','content','summary','image_url','favicon_url','image_storage_path','collected_at'])))
            duplicate=db.execute('SELECT * FROM sample_issues WHERE duplicate_of_issue_id IS NOT NULL LIMIT 1').fetchone()
            self.assertEqual(duplicate['is_selected'],0)
            self.assertIsNone(duplicate['request_id'])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE sample_issues SET is_selected=1 WHERE issue_id=?',(duplicate['issue_id'],))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE sample_issues SET total_score=101 WHERE issue_id=?',(issues[0]['id'],))
        self.assertEqual(self.client.put(f'/api/samples/{self.sample}/selection',json={'issue_ids':[duplicate['issue_id']]}).status_code,400)
        letter=self.client.post(f'/api/samples/{self.sample}/newsletter').json()
        with auth.database() as db:
            articles=[tuple(r) for r in db.execute('SELECT * FROM sample_articles WHERE sample_id=? ORDER BY article_id',(letter['id'],))]
            final_issues=[tuple(r) for r in db.execute('SELECT * FROM sample_issues WHERE sample_id=? ORDER BY issue_id',(letter['id'],))]
            self.assertEqual(len(articles),9);self.assertEqual(len(final_issues),9)
            self.assertEqual(letter['id'],self.sample)
            self.assertEqual({r[0] for r in db.execute('SELECT issue_id FROM sample_issues WHERE sample_id=? AND duplicate_of_issue_id IS NULL',(letter['id'],))},{i['id'] for i in issues})
        self.client.post(f'/api/samples/{self.sample}/collect-demo')
        with auth.database() as db:
            self.assertEqual(articles,[tuple(r) for r in db.execute('SELECT * FROM sample_articles WHERE sample_id=? ORDER BY article_id',(letter['id'],))])
            self.assertEqual(final_issues,[tuple(r) for r in db.execute('SELECT * FROM sample_issues WHERE sample_id=? ORDER BY issue_id',(letter['id'],))])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_stable_sample_id_and_copy_on_edit_after_completion(self):
        with auth.database() as db:
            original=self.sample
            row=db.execute('SELECT * FROM sample_newsletters WHERE sample_id=?',(original,)).fetchone()
            self.assertIsNone(row['html_content']);self.assertIsNone(row['completed_at'])
        issues=self.prepare()
        letter=self.client.post(f'/api/samples/{self.sample}/newsletter').json()
        self.assertEqual(letter['id'],original)
        self.assertEqual(self.client.post(f'/api/samples/{self.sample}/newsletter').json()['id'],original)
        self.client.post(f'/api/newsletters/{original}/save')
        selected=self.client.put(f'/api/samples/{self.sample}/selection',json={'issue_ids':[issues[-1]['id']]})
        self.assertEqual(selected.status_code,200,selected.text)
        self.sample=selected.json()['sample_id']
        current_issues=selected.json()['issues']
        self.assertEqual(sum(r['selected'] for r in current_issues),1)
        self.assertNotEqual(selected.json()['selected_ids'][0],issues[-1]['id'])
        followup=self.client.put(f'/api/samples/{self.sample}/selection',json={'issue_ids':[current_issues[0]['id']]})
        self.assertEqual(followup.status_code,200,followup.text)
        with auth.database() as db:
            current=self.sample
            self.assertNotEqual(current,original)
            old=db.execute('SELECT * FROM sample_newsletters WHERE sample_id=?',(original,)).fetchone()
            self.assertEqual(old['html_content'],letter['html'])
            self.assertEqual(old['status'],'completed')
            self.assertEqual(db.execute('SELECT count(*) FROM sample_issues WHERE sample_id=? AND is_selected=1',(original,)).fetchone()[0],5)
            self.assertEqual({r['name'] for r in db.execute('PRAGMA table_info(sample_newsletters)')},
                {'sample_id','user_id','topic','collection_start_date','collection_end_date','status','html_content','created_at','completed_at','saved_at','last_issued_newsletter_id'})
            self.assertIsNone(old['last_issued_newsletter_id'])
        newer=self.client.post(f'/api/samples/{self.sample}/newsletter').json()
        self.assertEqual(newer['id'],current);self.assertEqual(newer['count'],1)
        self.assertEqual(self.client.get('/api/newsletters').json()[0]['id'],original)

    def test_ownership_and_validation(self):
        issues=self.prepare();letter=self.client.post(f'/api/samples/{self.sample}/newsletter').json()
        paths=[('GET',f'/api/samples/{self.sample}',None),('GET',f'/api/samples/{self.sample}/usage',None),('PUT',f'/api/samples/{self.sample}/sources',{'domains':[]}),('PUT',f'/api/samples/{self.sample}/period',{'start':'2026-09-01','end':'2026-09-02'}),('PUT',f'/api/samples/{self.sample}/selection',{'issue_ids':[]}),('POST',f'/api/samples/{self.sample}/collect-demo',{}),('POST',f'/api/samples/{self.sample}/newsletter',{}),('POST',f'/api/samples/{self.sample}/step',{'step':1}),('POST',f"/api/newsletters/{letter['id']}/save",{}),('GET',f"/api/newsletters/{letter['id']}/download",None),('POST','/api/domains/recommend/stream',{'topic':'AI Agent','sample_id':self.sample})]
        for method,path,body in paths:
            response=self.other.request(method,path,json=body)
            self.assertEqual(response.status_code,404,(path,response.text))
        self.assertEqual(self.other.get('/api/newsletters').json(),[])
        self.assertEqual(self.client.put(f'/api/samples/{self.sample}/selection',json={'issue_ids':['foreign-id']}).status_code,400)
        self.sample=self.client.put(f'/api/samples/{self.sample}/selection',json={'issue_ids':[]}).json()['sample_id']
        self.assertEqual(self.client.post(f'/api/samples/{self.sample}/newsletter').status_code,400)
        self.assertEqual(self.client.put(f'/api/samples/{self.sample}/period',json={'start':'2026-10-01','end':'2026-09-01'}).status_code,400)
        self.assertEqual(self.client.post('/api/domains/recommend/stream',json={'topic':'Changed','sample_id':self.sample}).status_code,409)
        self.assertEqual(self.admin.get('/api/samples').status_code,403)

    def test_errors_are_persisted_per_user_and_step_without_provider_secrets(self):
        self.assertEqual(self.client.put(f'/api/samples/{self.sample}/period',json={'start':'2026-10-01','end':'2026-09-01'}).status_code,400)
        self.assertEqual(self.client.put(f'/api/samples/{self.sample}/period',json={'start':'invalid','end':'2026-09-01'}).status_code,422)
        async def failed(topic):
            raise InvalidLLMResponse('secret provider payload')
            yield
        with patch('backend.streaming.stream_domains',failed):
            result=self.client.post('/api/domains/recommend/stream',json={'topic':'AI Agent','sample_id':self.sample})
        self.assertIn('event: error',result.text)
        errors=self.client.get('/api/errors').json()
        self.assertEqual(len(errors),3)
        self.assertEqual({e['step'] for e in errors},{'sample_period_setting','sample_domain_recommendation'})
        self.assertEqual({e['error_type'] for e in errors},{'HTTPException','RequestValidationError','InvalidLLMResponse'})
        self.assertNotIn('secret',json.dumps(errors))
        self.assertEqual(len({e['error_id'] for e in errors}),3)
        self.assertEqual(self.other.get('/api/errors').json(),[])
        self.assertEqual(self.admin.get('/api/errors').status_code,403)
        with auth.database() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='newsletter_runs'").fetchone())
            self.assertFalse({'current_step','updated_at','error_message'} & {r['name'] for r in db.execute('PRAGMA table_info(sample_newsletters)')})

    def test_old_runs_are_removed_without_losing_samples_and_errors(self):
        self.prepare()
        legacy= (Path(__file__).parent/'test_fixtures'/'before_subscription_editions.sql').read_text()
        with auth.database() as db:
            db.executescript(legacy[:legacy.index('CREATE TABLE IF NOT EXISTS domains')])
            sample=dict(db.execute('SELECT * FROM sample_newsletters WHERE sample_id=?',(self.sample,)).fetchone())
            db.execute("INSERT INTO newsletter_runs (run_id,sample_id,user_id,topic,current_step,error_message,created_at,updated_at) VALUES ('old',?,?,?,2,'Previous selection failed',?,?)",
                       (self.sample,sample['user_id'],sample['topic'],sample['created_at'],sample['created_at']))
            db.execute("INSERT INTO newsletter_runs (run_id,user_id,topic,created_at,updated_at) VALUES ('orphan',?,'Unfinished topic',?,?)",(sample['user_id'],sample['created_at'],sample['created_at']))
        init_newsletter_db();init_newsletter_db()
        with auth.database() as db:
            self.assertEqual(dict(db.execute('SELECT * FROM sample_newsletters WHERE sample_id=?',(self.sample,)).fetchone()),sample)
            self.assertEqual(db.execute("SELECT count(*) FROM sample_newsletters WHERE topic='Unfinished topic'").fetchone()[0],1)
            errors=db.execute('SELECT * FROM errors').fetchall()
            self.assertEqual(len(errors),1)
            self.assertEqual(errors[0]['step'],'sample_issue_selection')
            self.assertEqual(errors[0]['message'],'Previous selection failed')
            self.assertEqual(errors[0]['user_id'],sample['user_id'])
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='newsletter_runs'").fetchone())
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_recommendation_snapshots_selection_and_partial_failure(self):
        async def generated(topic):
            yield Domain(**DOMAIN)
            raise InvalidLLMResponse('secret detail')
        with patch('backend.streaming.stream_domains',generated):
            response=self.client.post('/api/domains/recommend/stream',json={'topic':'AI Agent','sample_id':self.sample})
        self.assertIn('event: domain',response.text);self.assertIn('event: error',response.text);self.assertNotIn('secret detail',response.text)
        stored=[json.loads(block.split('data: ',1)[1]) for block in response.text.split('\n\n') if block.startswith('event: domain')];self.assertEqual(len(stored),1)
        self.assertEqual(stored[0]['reason'],DOMAIN['reason']);self.assertEqual(stored[0]['relevance'],DOMAIN['relevance'])
        self.client.put(f'/api/samples/{self.sample}/sources',json={'domains':[{'host':DOMAIN['host'],'recommendation_id':stored[0]['recommendation_id']}]})
        self.client.put(f'/api/samples/{self.sample}/sources',json={'domains':[]})
        self.assertEqual(self.client.get(f'/api/samples/{self.sample}').json()['recommendations'],[])
        with auth.database() as db:self.assertEqual(db.execute('SELECT count(*) FROM sample_domains').fetchone()[0],0)

    def test_domain_column_migration_preserves_recommendations_and_references(self):
        from backend.workflows import store_recommendation, shared_domain
        snapshot_id = store_recommendation(self.sample, 'batch', Domain(**DOMAIN), 1)
        self.prepare()
        with auth.database() as db:
            before = [dict(r) for r in db.execute('SELECT * FROM sample_domains ORDER BY sample_id,domain_id')]
            articles = [tuple(r) for r in db.execute('SELECT article_id,domain_id FROM sample_articles ORDER BY article_id')]
            domain_ids = [tuple(r) for r in db.execute('SELECT domain_id,host FROM domains ORDER BY host')]
            db.execute("ALTER TABLE domains ADD COLUMN name TEXT NOT NULL DEFAULT 'legacy'")
            db.execute("ALTER TABLE domains ADD COLUMN updated_at TEXT NOT NULL DEFAULT 'legacy'")
            db.execute('ALTER TABLE domains ADD COLUMN kind TEXT')
            db.execute('ALTER TABLE domains ADD COLUMN description TEXT')
            db.execute("UPDATE domains SET kind='legacy',description='legacy description'")
        init_newsletter_db()
        init_newsletter_db()
        with auth.database() as db:
            self.assertEqual({r['name'] for r in db.execute('PRAGMA table_info(domains)')},
                             {'domain_id','host','created_at'})
            self.assertEqual([dict(r) for r in db.execute('SELECT * FROM sample_domains ORDER BY sample_id,domain_id')], before)
            self.assertEqual([tuple(r) for r in db.execute('SELECT article_id,domain_id FROM sample_articles ORDER BY article_id')], articles)
            self.assertEqual([tuple(r) for r in db.execute('SELECT domain_id,host FROM domains ORDER BY host')], domain_ids)
            shared_domain(db, DOMAIN['host'])
            self.assertEqual(db.execute('SELECT count(*) FROM domains WHERE host=?', (DOMAIN['host'],)).fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        selected=self.client.put(f'/api/samples/{self.sample}/sources',json={'domains':[{'host':DOMAIN['host'],'recommendation_id':snapshot_id}]})
        self.assertEqual(selected.status_code,200,selected.text)
        self.assertEqual(selected.json()['domains'][0]['desc'],DOMAIN['desc'])

    def test_retried_recommendation_request_and_duplicate_hosts(self):
        from backend.domain_generation import Candidate
        usage=SimpleNamespace(prompt_tokens=10,completion_tokens=20,total_tokens=30,prompt_tokens_details=None)
        response=SimpleNamespace(id='provider',usage=usage,choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(DOMAIN),refusal=None))])
        error=RateLimitError('retry',response=httpx.Response(429,request=httpx.Request('POST','https://example.org'),headers={'retry-after-ms':'0'}),body=None)
        context=AsyncMock()
        context.__aenter__.return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=[error,response]))))
        with patch('backend.domain_generation.shortlist',AsyncMock(return_value=[Candidate(host=DOMAIN['host'],name=DOMAIN['name'])])), patch('backend.llm_client.create_llm_client',return_value=context):
            result=self.client.post('/api/domains/recommend/stream',json={'topic':'AI Agent','sample_id':self.sample})
        self.assertIn('event: done',result.text)
        recommendation=next(json.loads(block.split('data: ',1)[1]) for block in result.text.split('\n\n') if block.startswith('event: domain'))
        host=DOMAIN['host']
        selected=self.client.put(f'/api/samples/{self.sample}/sources',json={'domains':[
            {'host':'https://www.'+host.upper()+'/news','custom':True},
            {'host':host,'recommendation_id':recommendation['recommendation_id']}]})
        self.assertEqual(selected.status_code,200,selected.text)
        self.assertEqual(len(selected.json()['domains']),1)
        self.assertEqual(selected.json()['domains'][0]['kind'],'recommended')
        self.assertEqual(selected.json()['domains'][0]['name'],host)
        sid=selected.json()['domains'][0]['sample_id']
        with auth.database() as db:
            from backend.llm_tracking import requests_for_user
            uid=db.execute('SELECT user_id FROM sample_newsletters WHERE sample_id=?',(self.sample,)).fetchone()[0]
            attempts=requests_for_user(db,uid)
            self.assertEqual([r['total_tokens'] for r in attempts],[None,30])
            row=db.execute('SELECT * FROM sample_domains WHERE sample_id=?',(sid,)).fetchone()
            self.assertEqual(row['request_id'],attempts[1]['request_id'])
            self.assertEqual(row['description'],DOMAIN['desc'])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO sample_domains (sample_id,domain_id,kind,created_at) VALUES (?,?,'manual',?)",(sid,row['domain_id'],auth.now()))
        # A manual duplicate retains AI provenance and the original timestamp.
        self.client.put(f'/api/samples/{self.sample}/sources',json={'domains':[{'host':host,'custom':True},{'host':host}]})
        self.assertEqual(self.client.get(f'/api/samples/{self.sample}').json()['domains'][0]['request_id'],attempts[1]['request_id'])
        other_run=self.other.post('/api/samples',json={'topic':'Other'}).json()['sample_id']
        self.assertEqual(self.other.put(f'/api/samples/{other_run}/sources',json={'domains':[{'host':host,'recommendation_id':recommendation['recommendation_id']}]}).status_code,400)
        self.client.put(f'/api/samples/{self.sample}/period',json={'start':'2026-09-01','end':'2026-09-17'})
        self.client.post(f'/api/samples/{self.sample}/collect-demo')
        sample=self.client.post(f'/api/samples/{self.sample}/newsletter').json()
        changed=self.client.put(f'/api/samples/{self.sample}/sources',json={'domains':[]}).json()
        self.sample=changed['sample_id']
        with auth.database() as db:
            self.assertEqual(db.execute('SELECT request_id FROM sample_domains WHERE sample_id=?',(sample['id'],)).fetchone()[0],attempts[1]['request_id'])
            self.assertEqual(sample['id'],sid)
            current=self.sample
            self.assertNotEqual(current,sid)
            self.assertEqual(db.execute('SELECT count(*) FROM sample_domains WHERE sample_id=?',(current,)).fetchone()[0],0)

    def test_token_retry_failure_cancel_and_concurrent_run_isolation(self):
        other_run=self.other.post('/api/samples',json={'topic':'Other'}).json()['sample_id']
        usage=SimpleNamespace(prompt_tokens=100,completion_tokens=20,total_tokens=120,prompt_tokens_details=SimpleNamespace(cached_tokens=30))
        response=SimpleNamespace(id='provider-id',usage=usage,choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='{}',refusal=None))])
        error=RateLimitError('secret',response=httpx.Response(429,request=httpx.Request('POST','https://example.org'),headers={'retry-after-ms':'0'}),body=None)
        context=AsyncMock();create=AsyncMock(side_effect=[error,response,asyncio.CancelledError(),response]);context.__aenter__.return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        async def run():
            token=sample_context.set(self.sample)
            try:
                await chat_completion([],{},operation='domain_shortlist')
                with self.assertRaises(asyncio.CancelledError):await chat_completion([],{},operation='domain_detail')
            finally:sample_context.reset(token)
            token=sample_context.set(other_run)
            try:await chat_completion([],{},operation='domain_detail')
            finally:sample_context.reset(token)
        with patch('backend.llm_client.create_llm_client',return_value=context),patch.dict('os.environ',{'OPENAI_MODEL':'test-model'}):asyncio.run(run())
        result=self.client.get('/api/llm-requests').json()
        self.assertEqual(result['call_count'],3);self.assertEqual(result['total_tokens'],120);self.assertEqual(result['cached_input_tokens'],30)
        self.assertEqual(result['unknown_usage_count'],2)
        self.assertNotEqual(result['requests'][0]['request_id'],result['requests'][1]['request_id'])
        self.assertEqual({r['step'] for r in result['requests']},{'sample_domain_recommendation'})
        self.assertTrue(all(r['user_id'] for r in result['requests']))
        self.assertIsNone(result['requests'][0]['input_tokens'])
        self.assertEqual(self.other.get('/api/llm-requests').json()['total_tokens'],120)
        errors=self.client.get('/api/errors').json()
        self.assertEqual(len(errors),1)
        self.assertEqual(errors[0]['request_id'],result['requests'][0]['request_id'])
        self.assertEqual(errors[0]['error_type'],'RateLimitError')
        self.assertEqual(self.other.get('/api/errors').json(),[])
