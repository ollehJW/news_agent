"""Compact sample records and copy-on-edit lifecycle."""
import json
import uuid
from pathlib import Path
from .auth import now


def migrate_sample_newsletters(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='newsletter_runs'").fetchone():
        return
    if 'sample_id' not in {r['name'] for r in db.execute('PRAGMA table_info(newsletter_runs)')}:
        db.execute('ALTER TABLE newsletter_runs ADD COLUMN sample_id TEXT REFERENCES sample_newsletters(sample_id) ON DELETE SET NULL')
    if 'run_id' not in {r['name'] for r in db.execute('PRAGMA table_info(sample_newsletters)')}:
        if 'last_issued_newsletter_id' not in {r['name'] for r in db.execute('PRAGMA table_info(sample_newsletters)')}:
            db.execute('ALTER TABLE sample_newsletters ADD COLUMN last_issued_newsletter_id TEXT REFERENCES subscripted_newsletters(newsletter_id) ON DELETE SET NULL')
        return
    schema=Path(__file__).with_name('newsletter_schema.sql').read_text()
    start=schema.index('CREATE TABLE IF NOT EXISTS sample_newsletters (')
    ddl=schema[start:schema.index(';',start)+1].replace('IF NOT EXISTS sample_newsletters','sample_newsletters_replacement')
    db.execute(ddl)
    for row in db.execute('SELECT s.*,r.topic AS run_topic,r.start_date,r.end_date,r.completed_at AS run_completed_at FROM sample_newsletters s JOIN newsletter_runs r USING(run_id)').fetchall():
        snapshot=json.loads(row['snapshot_json'])
        dates=snapshot.get('dates') or {}
        complete=row['status']=='completed'
        db.execute('INSERT INTO sample_newsletters_replacement (sample_id,user_id,topic,collection_start_date,collection_end_date,status,html_content,created_at,completed_at,saved_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (row['sample_id'],row['user_id'],snapshot.get('topic') or row['run_topic'],
                    dates.get('start') or row['start_date'],dates.get('end') or row['end_date'],
                    row['status'],row['html_content'] if complete else None,row['created_at'],
                    row['created_at'] if complete else None,row['saved_at']))
    for run in db.execute('SELECT * FROM newsletter_runs').fetchall():
        # Completed runs point at their completed edition; unfinished runs prefer drafts.
        preferred='completed' if run['status']=='completed' else 'draft'
        row=db.execute('SELECT sample_id FROM sample_newsletters WHERE run_id=? ORDER BY (status=?) DESC,created_at DESC,sample_id LIMIT 1',(run['run_id'],preferred)).fetchone()
        if row:
            db.execute('UPDATE newsletter_runs SET sample_id=? WHERE run_id=?',(row[0],run['run_id']))
    db.execute('DROP TABLE sample_newsletters')
    db.execute('ALTER TABLE sample_newsletters_replacement RENAME TO sample_newsletters')
    db.execute('CREATE INDEX sample_newsletters_owner ON sample_newsletters(user_id,saved_at)')


def legacy_current_sample(db,run_id):
    row=db.execute('SELECT * FROM newsletter_runs WHERE run_id=?',(run_id,)).fetchone()
    if row['sample_id']:
        return row['sample_id']
    sid=str(uuid.uuid4())
    db.execute('''INSERT INTO sample_newsletters
        (sample_id,user_id,topic,collection_start_date,collection_end_date,status,created_at)
        VALUES (?,?,?,?,?,'draft',?)''',(sid,row['user_id'],row['topic'],row['start_date'],row['end_date'],now()))
    db.execute('UPDATE newsletter_runs SET sample_id=? WHERE run_id=?',(sid,run_id))
    return sid


def editable_sample(db,sid):
    from .article_storage import copy_sample_articles
    row=db.execute('SELECT * FROM sample_newsletters WHERE sample_id=?',(sid,)).fetchone()
    if row['status']=='draft':
        return sid,{}
    new_id=str(uuid.uuid4())
    db.execute('''INSERT INTO sample_newsletters
        (sample_id,user_id,topic,collection_start_date,collection_end_date,status,created_at)
        VALUES (?,?,?,?,?,'draft',?)''',(new_id,row['user_id'],row['topic'],row['collection_start_date'],row['collection_end_date'],now()))
    db.execute('INSERT INTO sample_domains SELECT ?,domain_id,request_id,kind,description,recommendation_reason,topic_relevance,created_at FROM sample_domains WHERE sample_id=?',(new_id,sid))
    _,issue_ids=copy_sample_articles(db,sid,new_id)
    return new_id,issue_ids
