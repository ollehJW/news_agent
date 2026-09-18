"""Regression checks for the former shared sample/publication table."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import auth
from backend.tracking import init_newsletter_db


class SampleMigrationTests(unittest.TestCase):
    def test_legacy_samples_and_publication_links_survive_repeated_initialization(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(auth, 'DB_PATH', Path(directory)/'app.db'):
            auth.init_db()
            schema = (Path(__file__).parent/'test_fixtures'/'before_subscription_editions.sql').read_text()
            a=schema.index('CREATE TABLE IF NOT EXISTS subscriptions (')
            b=schema.index('-- Actual subscription editions',a)
            schema=schema[:a]+"CREATE TABLE IF NOT EXISTS newsletter_subscriptions (\n subscription_id TEXT PRIMARY KEY,\n user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,\n sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE RESTRICT,\n frequency TEXT NOT NULL CHECK(frequency IN ('daily','weekly','monthly')),\n weekdays TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(weekdays) AND json_type(weekdays)='array'),\n month_day INTEGER CHECK(month_day BETWEEN 1 AND 31),\n start_date TEXT NOT NULL,\n status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','cancelled')),\n created_at TEXT NOT NULL, updated_at TEXT NOT NULL,\n CHECK(frequency!='weekly' OR json_array_length(weekdays)>0),\n CHECK(frequency!='monthly' OR month_day IS NOT NULL),\n UNIQUE(user_id,sample_id)\n);\nCREATE INDEX IF NOT EXISTS subscriptions_reference ON newsletter_subscriptions(sample_id,status);\n\n"+schema[b:]
            start = schema.index('-- Actual subscription editions')
            end = schema.index('CREATE TABLE IF NOT EXISTS newsletter_publications',start)
            legacy = (schema[:start]+schema[end:])
            a=legacy.index('CREATE TABLE IF NOT EXISTS sample_newsletters (')
            b=legacy.index('CREATE INDEX IF NOT EXISTS sample_newsletters_owner',a)
            legacy=legacy[:a]+"""CREATE TABLE sample_newsletters (
                sample_id TEXT PRIMARY KEY,run_id TEXT NOT NULL REFERENCES newsletter_runs(run_id),
                user_id TEXT NOT NULL REFERENCES users(user_id),title TEXT NOT NULL,html_content TEXT NOT NULL,
                template_version TEXT NOT NULL,content_hash TEXT NOT NULL,issue_count INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL,created_at TEXT NOT NULL,saved_at TEXT,
                status TEXT NOT NULL DEFAULT 'completed');
                """+legacy[b:]

            legacy = legacy.replace('sample_id TEXT PRIMARY KEY', 'newsletter_id TEXT PRIMARY KEY')
            legacy = legacy.replace('sample_id TEXT REFERENCES sample_newsletters', 'newsletter_id TEXT REFERENCES sample_newsletters')
            legacy = legacy.replace('sample_newsletters(sample_id)', 'sample_newsletters(newsletter_id)')
            legacy = legacy.replace('sample_id', 'reference_newsletter_id').replace('sample_newsletters','newsletters')
            with auth.database() as db:
                db.executescript(legacy)
                uid = db.execute("SELECT user_id FROM users WHERE employee_id='admin'").fetchone()[0]
                stamp = auth.now()
                db.execute("INSERT INTO newsletter_runs (run_id,user_id,topic,created_at,updated_at) VALUES ('run',?,'topic',?,?)",(uid,stamp,stamp))
                for nid in ('sample','edition'):
                    db.execute('INSERT INTO newsletters (newsletter_id,run_id,user_id,title,html_content,template_version,content_hash,issue_count,snapshot_json,created_at,saved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                               (nid,'run',uid,nid,'<h1>'+nid+'</h1>','v1',nid,1,'{}',stamp,stamp))
                db.execute("INSERT INTO domains VALUES ('domain','example.org',?)",(stamp,))
                db.execute("INSERT INTO subscripted_articles (article_id,reference_newsletter_id,domain_id,url,title,collected_at) VALUES ('article','sample','domain','https://example.org/a','a',?)",(stamp,))
                db.execute("INSERT INTO newsletter_subscriptions (subscription_id,user_id,reference_newsletter_id,frequency,start_date,created_at,updated_at) VALUES ('sub',?,'sample','daily','2026-09-01',?,?)",(uid,stamp,stamp))
                db.execute("INSERT INTO newsletter_publications (publication_id,reference_newsletter_id,coverage_start,coverage_end,newsletter_id,status,created_at,updated_at) VALUES ('pub','sample','2026-09-01','2026-09-17','edition','completed',?,?)",(stamp,stamp))
            init_newsletter_db()
            init_newsletter_db()
            with auth.database() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM sample_newsletters').fetchone()[0],2)
                self.assertEqual([r[0] for r in db.execute('SELECT newsletter_id FROM subscripted_newsletters')],['edition'])
                self.assertEqual(db.execute("SELECT html_content FROM sample_newsletters WHERE sample_id='sample'").fetchone()[0],'<h1>sample</h1>')
                self.assertEqual(db.execute("SELECT html_content FROM subscripted_newsletters WHERE newsletter_id='edition'").fetchone()[0],'<h1>edition</h1>')
                self.assertEqual(db.execute('SELECT sample_id FROM subscripted_articles').fetchone()[0],'sample')
                self.assertEqual(db.execute('SELECT sample_id FROM subscriptions').fetchone()[0],'sample')
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='newsletter_subscriptions'").fetchone())
                self.assertEqual({r['name'] for r in db.execute('PRAGMA table_info(subscriptions)')},{'subscription_id','sample_id','user_id','status','created_at','updated_at'})
                refs={r['from']:r['table'] for r in db.execute('PRAGMA foreign_key_list(subscripted_newsletters)')}
                self.assertEqual(refs,{'sample_id':'sample_newsletters','request_id':'llm_requests'})
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("UPDATE subscripted_newsletters SET sample_id='missing'")
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
