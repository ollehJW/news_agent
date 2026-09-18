import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import auth
from backend.tracking import init_newsletter_db


class ArticleMigrationTests(unittest.TestCase):
    def test_legacy_url_merging_duplicate_links_and_audit_preservation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(auth,'DB_PATH',Path(directory)/'app.db'):
            auth.init_db();init_newsletter_db()
            with auth.database() as db:
                db.executescript("CREATE TABLE IF NOT EXISTS newsletter_runs (\n run_id TEXT PRIMARY KEY, sample_id TEXT REFERENCES sample_newsletters(sample_id) ON DELETE SET NULL, user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,\n topic TEXT NOT NULL, start_date TEXT, end_date TEXT, current_step INTEGER NOT NULL DEFAULT 0,\n status TEXT NOT NULL DEFAULT 'draft', data_mode TEXT NOT NULL DEFAULT 'demo',\n created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT, error_message TEXT\n);\nCREATE INDEX IF NOT EXISTS runs_owner ON newsletter_runs(user_id,created_at);\n")
                db.executescript('''CREATE TABLE run_articles (
                    article_id TEXT PRIMARY KEY,run_id TEXT,domain_id TEXT,issue_id TEXT,url TEXT,title TEXT,
                    published_at TEXT,content_text TEXT,summary TEXT,image_url TEXT,favicon_url TEXT,image_storage_path TEXT,collected_at TEXT);
                    CREATE TABLE run_issues (issue_id TEXT PRIMARY KEY,run_id TEXT,representative_article_id TEXT,
                    technical_score INTEGER,organization_score INTEGER,impact_score INTEGER,recency_score INTEGER,
                    total_score INTEGER,rank INTEGER,is_selected INTEGER,created_at TEXT);''')
                uid=db.execute("SELECT user_id FROM users WHERE employee_id='admin'").fetchone()[0]
                stamp=auth.now()
                db.execute("INSERT INTO newsletter_runs (run_id,user_id,topic,created_at,updated_at) VALUES ('run',?,'topic',?,?)",(uid,stamp,stamp))
                db.execute("INSERT INTO domains VALUES ('domain','example.org',?)",(stamp,))
                for aid,url,iid in [('a','https://example.org/a','i'),('b','https://example.org/b','i'),('c','https://example.org/a','j')]:
                    db.execute('INSERT INTO run_articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (aid,'run','domain',iid,url,aid,'2026-09-17','content','summary','https://example.org/image.png',None,None,stamp))
                db.execute("INSERT INTO run_issues VALUES ('i','run','a',90,80,70,60,80,1,0,?)",(stamp,))
                db.execute("INSERT INTO run_issues VALUES ('j','run','c',80,70,60,50,70,2,1,?)",(stamp,))
            init_newsletter_db();init_newsletter_db()
            with auth.database() as db:
                self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('run_articles','run_issues')").fetchone())
                self.assertEqual(db.execute('SELECT count(*) FROM sample_articles').fetchone()[0],2)
                self.assertEqual(db.execute('SELECT count(*) FROM sample_issues').fetchone()[0],2)
                representative=db.execute('SELECT * FROM sample_issues WHERE duplicate_of_issue_id IS NULL').fetchone()
                self.assertTrue(representative['is_selected'])
                self.assertEqual(representative['total_score'],80)
                duplicate=db.execute('SELECT * FROM sample_issues WHERE duplicate_of_issue_id IS NOT NULL').fetchone()
                self.assertEqual(duplicate['duplicate_of_issue_id'],representative['issue_id'])
                self.assertFalse(duplicate['is_selected'])
                self.assertIsNone(duplicate['request_id'])
                self.assertEqual(db.execute('SELECT image_url FROM sample_articles LIMIT 1').fetchone()[0],'https://example.org/image.png')
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
