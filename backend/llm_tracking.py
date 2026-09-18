"""Compact per-user LLM request records."""
from pathlib import Path


def step_name(operation):
    return 'sample_domain_recommendation' if operation in ('domain_shortlist','domain_detail','domain_recommendation') else operation


def migrate_llm_requests(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_requests'").fetchone():
        return
    db.execute('ALTER TABLE ai_requests RENAME TO llm_requests')
    schema=Path(__file__).with_name('newsletter_schema.sql').read_text()
    start=schema.index('CREATE TABLE IF NOT EXISTS llm_requests (')
    statement=schema[start:schema.index(';',start)+1].replace('IF NOT EXISTS llm_requests','llm_requests_replacement')
    db.execute(statement)
    for row in db.execute('SELECT a.*,r.user_id FROM llm_requests a JOIN newsletter_runs r USING(run_id)').fetchall():
        db.execute('INSERT INTO llm_requests_replacement VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (row['request_id'],row['user_id'],step_name(row['operation']),row['provider'],row['model'],
                    row['input_tokens'],row['output_tokens'],row['total_tokens'],row['cached_input_tokens'],
                    row['created_at'],row['completed_at'],row['duration_ms']))
    db.execute('DROP TABLE llm_requests')
    db.execute('ALTER TABLE llm_requests_replacement RENAME TO llm_requests')


def requests_for_user(db,user_id):
    return [dict(r) for r in db.execute('SELECT * FROM llm_requests WHERE user_id=? ORDER BY started_at,request_id',(user_id,))]


def owned_recommendation_request(db,request_id,user_id):
    return db.execute("SELECT 1 FROM llm_requests WHERE request_id=? AND user_id=? AND step='sample_domain_recommendation' AND completed_at IS NOT NULL",(request_id,user_id)).fetchone() is not None
