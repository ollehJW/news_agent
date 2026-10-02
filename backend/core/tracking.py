"""Per-task run context is inherited by parallel domain-description tasks."""
from backend.core.paths import BACKEND_DIR
import os
import psycopg
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
subscription_collection_context = ContextVar('wianews_subscription_collection', default=None)
subject_validation_context = ContextVar('wianews_subject_validation', default=None)


def init_newsletter_db():
    from backend.pgstore import initialize
    initialize()


def start_attempt(operation):
    from backend.subscriptions.usage import subscription_sample_context
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
        subscription_sample = subscription_sample_context.get()
        if subscription_sample and operation.startswith('subscription_'):
            db.execute('INSERT INTO subscription_llm_requests(request_id,sample_id) VALUES (?,?)', (request_id,subscription_sample))
        collection=subscription_collection_context.get()
        if collection:
            db.execute("UPDATE subscription_collection_runs SET request_id=? WHERE run_id=? AND attempt_token=? AND status='running'",(request_id,*collection))
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
