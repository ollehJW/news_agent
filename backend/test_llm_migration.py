import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import auth
from backend.tracking import init_newsletter_db
from backend.sample_storage import ensure_draft
from backend.llm_tracking import requests_for_user, owned_recommendation_request


class LLMRequestMigrationTests(unittest.TestCase):
    def test_compact_requests_preserve_usage_ownership_and_domain_links(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(auth,'DB_PATH',Path(directory)/'app.db'):
            auth.init_db()
            schema=Path(__file__).with_name('newsletter_schema.sql').read_text()
            schema="CREATE TABLE IF NOT EXISTS newsletter_runs (\n run_id TEXT PRIMARY KEY, sample_id TEXT REFERENCES sample_newsletters(sample_id) ON DELETE SET NULL, user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,\n topic TEXT NOT NULL, start_date TEXT, end_date TEXT, current_step INTEGER NOT NULL DEFAULT 0,\n status TEXT NOT NULL DEFAULT 'draft', data_mode TEXT NOT NULL DEFAULT 'demo',\n created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT, error_message TEXT\n);\nCREATE INDEX IF NOT EXISTS runs_owner ON newsletter_runs(user_id,created_at);\n"+schema
            a=schema.index('CREATE TABLE IF NOT EXISTS llm_requests')
            b=schema.index('-- Daily collection',a)
            legacy=schema[:a]+'''CREATE TABLE ai_requests (
                request_id TEXT PRIMARY KEY, run_id TEXT REFERENCES newsletter_runs(run_id),
                logical_call_id TEXT, operation TEXT, provider TEXT, model TEXT, provider_request_id TEXT,
                input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, cached_input_tokens INTEGER,
                status TEXT, attempt_number INTEGER, duration_ms INTEGER, error_message TEXT,
                created_at TEXT, completed_at TEXT);
                '''+schema[b:].replace('REFERENCES llm_requests(request_id)','REFERENCES ai_requests(request_id)')
            with auth.database() as db:
                db.executescript(legacy)
                uid=db.execute("SELECT user_id FROM users WHERE employee_id='admin'").fetchone()[0]
                stamp=auth.now()
                db.execute("INSERT INTO newsletter_runs (run_id,user_id,topic,created_at,updated_at) VALUES ('run',?,'topic',?,?)",(uid,stamp,stamp))
                sid=ensure_draft(db,'run')
                for rid,status,tokens in [('success','success',30),('failure','failed',None)]:
                    db.execute('INSERT INTO ai_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (rid,'run','logical','domain_detail','azure_openai','deployment','provider-id',tokens,0 if tokens else None,tokens,0 if tokens else None,status,1,123,None,stamp,stamp))
                db.execute("INSERT INTO domains VALUES ('domain','example.org',?)",(stamp,))
                db.execute("INSERT INTO sample_domains (sample_id,domain_id,request_id,kind,created_at) VALUES (?,'domain','success','recommended',?)",(sid,stamp))
            init_newsletter_db();init_newsletter_db()
            with auth.database() as db:
                cols={r['name'] for r in db.execute('PRAGMA table_info(llm_requests)')}
                self.assertEqual(cols,{'request_id','user_id','step','provider','model','input_tokens','output_tokens','total_tokens','cached_input_tokens','started_at','completed_at','duration_ms'})
                self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='ai_requests'").fetchone())
                rows=requests_for_user(db,uid)
                self.assertEqual(len(rows),2)
                self.assertEqual({r['user_id'] for r in rows},{uid})
                self.assertEqual({r['step'] for r in rows},{'sample_domain_recommendation'})
                self.assertEqual(sum(r['total_tokens'] or 0 for r in rows),30)
                self.assertTrue(owned_recommendation_request(db,'success',uid))
                self.assertFalse(owned_recommendation_request(db,'success','another-user'))
                self.assertEqual(db.execute('SELECT request_id FROM sample_domains').fetchone()[0],'success')
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
