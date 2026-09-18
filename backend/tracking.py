"""Per-task run context is inherited by parallel domain-description tasks."""
import os
import sqlite3
import uuid
from contextvars import ContextVar
from pathlib import Path
from .auth import database, now
from .sample_storage import migrate_run_domains
from .sample_lifecycle import migrate_sample_newsletters
from .subscription_newsletter_storage import migrate_subscription_newsletters, create_legacy_edition_tables, migrate_shared_newsletters
from .article_storage import migrate_sample_articles
from .subscription_article_storage import migrate_subscription_articles
from .llm_tracking import migrate_llm_requests, step_name

sample_context = ContextVar('wianews_sample', default=None)


def init_newsletter_db():
    with database() as db:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        legacy = 'newsletters' in tables and 'run_id' in {
            r['name'] for r in db.execute('PRAGMA table_info(newsletters)')}
        migrate_publications = legacy and 'newsletter_publications' in tables
        if legacy:
            # SQLite updates existing foreign keys to follow the renamed sample table.
            db.execute('ALTER TABLE newsletters RENAME TO sample_newsletters')
            db.execute('DROP INDEX IF EXISTS newsletters_owner')
            if migrate_publications:
                db.execute('ALTER TABLE newsletter_publications RENAME TO newsletter_publications_legacy')
                db.execute('DROP INDEX IF EXISTS publications_status')
        if 'newsletter_samples' in tables:
            db.execute('ALTER TABLE newsletter_samples RENAME TO sample_newsletters')
            db.execute('DROP INDEX IF EXISTS newsletter_samples_owner')
        # Rename keys before creating indexes that use the new names.
        for table, old, new in (
            ('sample_newsletters', 'newsletter_id', 'sample_id'),
            ('subscripted_articles', 'reference_newsletter_id', 'sample_id'),
            ('newsletter_subscriptions', 'reference_newsletter_id', 'sample_id'),
            ('newsletter_publications', 'reference_newsletter_id', 'sample_id'),
            ('newsletter_publications_legacy', 'reference_newsletter_id', 'sample_id'),
        ):
            columns = {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
            if old in columns:
                db.execute(f'ALTER TABLE {table} RENAME COLUMN {old} TO {new}')
        migrate_shared_newsletters(db)
        migrate_llm_requests(db)
        # Avoid executescript's implicit commit so schema and data migrate atomically.
        statement = ''
        for line in Path(__file__).with_name('newsletter_schema.sql').read_text().splitlines(True):
            statement += line
            if sqlite3.complete_statement(statement):
                db.execute(statement)
                statement = ''
        if 'status' not in {r['name'] for r in db.execute('PRAGMA table_info(sample_newsletters)')}:
            db.execute("ALTER TABLE sample_newsletters ADD COLUMN status TEXT NOT NULL DEFAULT 'completed' CHECK(status IN ('draft','completed'))")
        migrate_run_domains(db)
        migrate_sample_articles(db)
        if migrate_publications:
            create_legacy_edition_tables(db)
            # Only rows already used as publication results are also actual editions.
            db.execute("""INSERT INTO newsletters
                (newsletter_id,title,html_content,template_version,content_hash,issue_count,snapshot_json,created_at)
                SELECT sample_id,title,html_content,template_version,content_hash,issue_count,snapshot_json,created_at
                FROM sample_newsletters WHERE sample_id IN
                (SELECT newsletter_id FROM newsletter_publications_legacy WHERE newsletter_id IS NOT NULL)""")
            db.execute('INSERT INTO newsletter_publications SELECT * FROM newsletter_publications_legacy')
            db.execute('DROP TABLE newsletter_publications_legacy')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(domains)')}
        for column in ('kind', 'description', 'name', 'updated_at'):
            if column in columns:
                db.execute(f'ALTER TABLE domains DROP COLUMN {column}')
        migrate_subscription_articles(db)
        migrate_sample_newsletters(db)
        if 'newsletter_subscriptions' in tables:
            db.execute('''INSERT INTO subscriptions
                (subscription_id,sample_id,user_id,status,created_at,updated_at)
                SELECT subscription_id,sample_id,user_id,status,created_at,updated_at
                FROM newsletter_subscriptions''')
            db.execute('DROP TABLE newsletter_subscriptions')
            db.execute('CREATE INDEX IF NOT EXISTS subscriptions_reference ON subscriptions(sample_id,status)')
        migrate_subscription_newsletters(db)
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='newsletter_runs'").fetchone():
            from .sample_lifecycle import legacy_current_sample
            for run in db.execute('SELECT * FROM newsletter_runs').fetchall():
                legacy_current_sample(db,run['run_id'])
                if run['error_message']:
                    db.execute('INSERT INTO errors (error_id,user_id,step,error_type,message,created_at) VALUES (?,?,?,?,?,?)',
                               (str(uuid.uuid4()),run['user_id'],{0:'sample_domain_recommendation',1:'sample_article_collection',2:'sample_issue_selection',3:'sample_newsletter_generation'}.get(run['current_step'],'sample_creation'),'LegacyRunError',run['error_message'],run['updated_at']))
            db.execute('DROP TABLE newsletter_runs')
        db.execute('DROP TABLE IF EXISTS usage_events')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Newsletter migration violated foreign key constraints')


def start_attempt(operation):
    sample_id = sample_context.get()
    if not sample_id:
        return None
    request_id = str(uuid.uuid4())
    with database() as db:
        user_id = db.execute('SELECT user_id FROM sample_newsletters WHERE sample_id=?',(sample_id,)).fetchone()[0]
        db.execute('''INSERT INTO llm_requests
            (request_id,user_id,step,provider,model,started_at) VALUES (?,?,?,?,?,?)''',
            (request_id,user_id,step_name(operation),'azure_openai',os.getenv('OPENAI_MODEL',''),now()))
    return request_id


def finish_attempt(request_id, status, duration_ms, response=None, error=None):
    if not request_id:
        return
    usage = getattr(response, 'usage', None)
    details = getattr(usage, 'prompt_tokens_details', None)
    with database() as db:
        db.execute('''UPDATE llm_requests SET input_tokens=?,output_tokens=?,total_tokens=?,cached_input_tokens=?,
            duration_ms=?,completed_at=? WHERE request_id=?''',
            (getattr(usage, 'prompt_tokens', None), getattr(usage, 'completion_tokens', None),
             getattr(usage, 'total_tokens', None), getattr(details, 'cached_tokens', None),
             duration_ms, now(), request_id))

    if status == 'failed' and error is not None:
        from .error_storage import record_error
        with database() as db:
            row=db.execute('SELECT user_id,step FROM llm_requests WHERE request_id=?',(request_id,)).fetchone()
        if row:
            record_error(row['user_id'],row['step'],error,request_id=request_id)
