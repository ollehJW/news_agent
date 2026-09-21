"""Per-task run context is inherited by parallel domain-description tasks."""
from backend.core.paths import BACKEND_DIR
import os
import sqlite3
import uuid
from contextvars import ContextVar
from backend.core.auth import database, now
from backend.migrations.sample_storage import migrate_run_domains
from backend.samples.sample_lifecycle import migrate_sample_newsletters
from backend.migrations.subscription_newsletter_storage import migrate_subscription_newsletters, create_legacy_edition_tables, migrate_shared_newsletters
from backend.migrations.legacy_sample_articles import migrate_sample_articles
from backend.migrations.subscription_article_storage import migrate_subscription_articles
from backend.core.llm_tracking import migrate_llm_requests, step_name

sample_context = ContextVar('wianews_sample', default=None)
llm_user_context = ContextVar('wianews_llm_user', default=None)
subject_validation_context = ContextVar('wianews_subject_validation', default=None)


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
        legacy_articles = 'run_articles' in tables or any('url' in {r['name'] for r in db.execute(f'PRAGMA table_info({table})')} for table in ('sample_articles','subscripted_articles'))
        old_sample='user_id' in {r['name'] for r in db.execute('PRAGMA table_info(sample_newsletters)')}
        schema_path=BACKEND_DIR / ('migrations/legacy_articles.sql' if legacy_articles else 'migrations/pre_sample_runs.sql' if old_sample else 'newsletter_schema.sql')
        statement = ''
        for line in schema_path.read_text().splitlines(True):
            statement += line
            if sqlite3.complete_statement(statement):
                db.execute(statement)
                statement = ''
        if old_sample and 'status' not in {r['name'] for r in db.execute('PRAGMA table_info(sample_newsletters)')}:
            db.execute("ALTER TABLE sample_newsletters ADD COLUMN status TEXT NOT NULL DEFAULT 'completed' CHECK(status IN ('draft','completed'))")
        if legacy_articles and 'highlights' not in {r['name'] for r in db.execute('PRAGMA table_info(sample_articles)')}:
            db.execute('ALTER TABLE sample_articles ADD COLUMN highlights TEXT')
        from backend.migrations.article_scores import migrate_article_scores
        if legacy_articles: migrate_article_scores(db)
        migrate_run_domains(db)
        if legacy_articles: migrate_sample_articles(db)
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
            from backend.samples.sample_lifecycle import legacy_current_sample
            for run in db.execute('SELECT * FROM newsletter_runs').fetchall():
                legacy_current_sample(db,run['run_id'])
                if run['error_message']:
                    db.execute('INSERT INTO errors (error_id,user_id,step,error_type,message,created_at) VALUES (?,?,?,?,?,?)',
                               (str(uuid.uuid4()),run['user_id'],{0:'sample_domain_recommendation',1:'sample_article_collection',2:'sample_issue_selection',3:'sample_newsletter_generation'}.get(run['current_step'],'sample_creation'),'LegacyRunError',run['error_message'],run['updated_at']))
            db.execute('DROP TABLE newsletter_runs')
        db.execute('DROP TABLE IF EXISTS usage_events')
        if legacy_articles:
            from backend.migrations.shared_articles import migrate_shared_articles
            migrate_shared_articles(db)
        from backend.migrations.remove_recency import remove_recency
        remove_recency(db)
        from backend.migrations.sample_runs import migrate_sample_runs
        migrate_sample_runs(db)
        from backend.migrations.compact_articles import compact_articles
        compact_articles(db)
        if 'image_storage_path' not in {r['name'] for r in db.execute('PRAGMA table_info(articles)')}:
            db.execute('ALTER TABLE articles ADD COLUMN image_storage_path TEXT')
        if 'newsletter_title' not in {r['name'] for r in db.execute('PRAGMA table_info(articles)')}:
            db.execute('ALTER TABLE articles ADD COLUMN newsletter_title TEXT')
        sample_columns={r['name'] for r in db.execute('PRAGMA table_info(sample_newsletters)')}
        if 'total_summary' not in sample_columns:db.execute('ALTER TABLE sample_newsletters ADD COLUMN total_summary TEXT')
        if 'request_id' not in sample_columns:db.execute('ALTER TABLE sample_newsletters ADD COLUMN request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Newsletter migration violated foreign key constraints')


def start_attempt(operation):
    sample_id = sample_context.get()
    user_id = llm_user_context.get()
    if not sample_id and not user_id:
        return None
    request_id = str(uuid.uuid4())
    with database() as db:
        if user_id is None:
            user_id = db.execute('SELECT user_id FROM sample_details WHERE sample_id=?',(sample_id,)).fetchone()[0]
        db.execute('''INSERT INTO llm_requests
            (request_id,user_id,step,provider,model,started_at) VALUES (?,?,?,?,?,?)''',
            (request_id,user_id,step_name(operation),'azure_openai',os.getenv('OPENAI_MODEL',''),now()))
        validation_id=subject_validation_context.get()
        if validation_id:
            db.execute('UPDATE subject_validation SET request_id=? WHERE validation_id=? AND user_id=?',(request_id,validation_id,user_id))
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
        from backend.core.error_storage import record_error
        with database() as db:
            row=db.execute('SELECT user_id,step FROM llm_requests WHERE request_id=?',(request_id,)).fetchone()
        if row:
            record_error(row['user_id'],row['step'],error,request_id=request_id)
