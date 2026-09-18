import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend import auth
from backend.tracking import init_newsletter_db
from backend.sample_storage import ensure_draft


class SubscriptionArticleMigrationTests(unittest.TestCase):
    def test_raw_articles_preserve_content_and_gain_domain_and_request_links(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(auth,'DB_PATH',Path(directory)/'app.db'):
            auth.init_db();init_newsletter_db()
            with auth.database() as db:
                uid=db.execute("SELECT user_id FROM users WHERE employee_id='admin'").fetchone()[0]
                stamp=auth.now()
                sid='sample'
                db.execute("INSERT INTO sample_newsletters (sample_id,user_id,topic,created_at) VALUES (?,?,'topic',?)",(sid,uid,stamp))
                db.execute('DROP TABLE subscripted_articles')
                db.execute('''CREATE TABLE subscripted_articles (
                    article_id TEXT PRIMARY KEY,sample_id TEXT,url TEXT,canonical_url TEXT,title TEXT,
                    source TEXT,author TEXT,published_at TEXT,collected_at TEXT,content TEXT,summary TEXT,
                    image_url TEXT,favicon_url TEXT,image_storage_path TEXT,UNIQUE(sample_id,canonical_url))''')
                db.execute('INSERT INTO subscripted_articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('article',sid,'https://www.example.org/a?tracking=1','https://example.org/a','title','source','author',
                     '2026-09-17',stamp,'original content','old summary','https://example.org/image.png','https://example.org/icon.ico','images/a.png'))
            init_newsletter_db();init_newsletter_db()
            with auth.database() as db:
                row=db.execute('SELECT * FROM subscripted_articles').fetchone()
                self.assertEqual(set(row.keys()),{'article_id','sample_id','domain_id','request_id','url','title','published_at','content','image_url','favicon_url','image_storage_path','collected_at'})
                self.assertEqual(row['article_id'],'article');self.assertEqual(row['sample_id'],sid)
                self.assertEqual(row['url'],'https://example.org/a')
                self.assertEqual(row['content'],'original content');self.assertEqual(row['collected_at'],stamp)
                self.assertEqual(row['image_storage_path'],'images/a.png');self.assertIsNone(row['request_id'])
                self.assertEqual(db.execute('SELECT host FROM domains WHERE domain_id=?',(row['domain_id'],)).fetchone()[0],'example.org')
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute('INSERT INTO subscripted_articles SELECT ?,sample_id,domain_id,request_id,url,title,published_at,content,image_url,favicon_url,image_storage_path,collected_at FROM subscripted_articles',('duplicate',))
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("UPDATE subscripted_articles SET request_id='missing'")
                indexes={r['name'] for r in db.execute('PRAGMA index_list(subscripted_articles)')}
                self.assertTrue({'subscripted_articles_period','subscripted_articles_collected'}.issubset(indexes))
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
