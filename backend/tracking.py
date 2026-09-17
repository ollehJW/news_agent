"""Per-task run context is inherited by parallel domain-description tasks."""
import json
import os
import uuid
from contextvars import ContextVar
from pathlib import Path
from .auth import database, now

run_context = ContextVar('wianews_run', default=None)


def init_newsletter_db():
    with database() as db:
        db.executescript(Path(__file__).with_name('newsletter_schema.sql').read_text())
        # Recommendation-specific fields live only in run_domains.
        db.execute('BEGIN IMMEDIATE')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(domains)')}
        for column in ('kind', 'description'):
            if column in columns:
                db.execute(f'ALTER TABLE domains DROP COLUMN {column}')



def event(db, user_id, run_id, event_type, metadata=None, newsletter_id=None):
    db.execute('INSERT INTO usage_events VALUES (?,?,?,?,?,?,?)',
               (str(uuid.uuid4()), user_id, run_id, newsletter_id, event_type,
                json.dumps(metadata or {}, ensure_ascii=False), now()))


def start_attempt(logical_id, operation, attempt):
    run_id = run_context.get()
    if not run_id:
        return None
    request_id = str(uuid.uuid4())
    with database() as db:
        db.execute('''INSERT INTO ai_requests
            (request_id,run_id,logical_call_id,operation,provider,model,status,attempt_number,created_at)
            VALUES (?,?,?,?,?,?,'running',?,?)''',
            (request_id, run_id, logical_id, operation, 'azure_openai', os.getenv('OPENAI_MODEL', ''), attempt, now()))
    return request_id


def finish_attempt(request_id, status, duration_ms, response=None, error=None):
    if not request_id:
        return
    usage = getattr(response, 'usage', None)
    details = getattr(usage, 'prompt_tokens_details', None)
    with database() as db:
        db.execute('''UPDATE ai_requests SET input_tokens=?,output_tokens=?,total_tokens=?,cached_input_tokens=?,
            provider_request_id=?,status=?,duration_ms=?,error_message=?,completed_at=? WHERE request_id=?''',
            (getattr(usage, 'prompt_tokens', None), getattr(usage, 'completion_tokens', None),
             getattr(usage, 'total_tokens', None), getattr(details, 'cached_tokens', None),
             getattr(response, 'id', None), status, duration_ms,
             type(error).__name__ if error else None, now(), request_id))
