"""Separate sample artifacts from execution metadata and preserve old ownership."""
import uuid
from backend.core.paths import BACKEND_DIR

VIEW='''CREATE VIEW sample_details AS
SELECT n.*,r.run_id,r.user_id,r.topic,r.collection_start_date,r.collection_end_date,
       CASE WHEN r.status='completed' THEN 'completed' ELSE 'draft' END AS status,
       r.status AS run_status,r.current_step,r.started_at,r.completed_at
FROM sample_newsletters n JOIN sample_runs r ON r.run_id=(
 SELECT x.run_id FROM sample_runs x WHERE x.sample_id=n.sample_id ORDER BY x.rowid DESC LIMIT 1)
'''

def migrate_sample_runs(db):
    schema=(BACKEND_DIR/'newsletter_schema.sql').read_text()
    for table in ('sample_runs',):
        a=schema.index(f'CREATE TABLE IF NOT EXISTS {table} (');db.execute(schema[a:schema.index(';',a)+1])
    cols={r['name'] for r in db.execute('PRAGMA table_info(sample_newsletters)')}
    if 'user_id' in cols:
        db.execute('DROP VIEW IF EXISTS sample_details')
        for row in db.execute('SELECT * FROM sample_newsletters').fetchall():
            step='newsletter_completed' if row['status']=='completed' else 'news_selection' if db.execute('SELECT 1 FROM sample_articles WHERE sample_id=?',(row['sample_id'],)).fetchone() else 'period_setup' if row['collection_end_date'] else 'source_setup' if db.execute('SELECT 1 FROM sample_domains WHERE sample_id=?',(row['sample_id'],)).fetchone() else 'topic_setup'
            db.execute('INSERT INTO sample_runs (run_id,sample_id,user_id,topic,collection_start_date,collection_end_date,current_step,status,started_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (str(uuid.uuid4()),row['sample_id'],row['user_id'],row['topic'],row['collection_start_date'],row['collection_end_date'],step,row['status'],row['created_at'],row['completed_at']))
        a=schema.index('CREATE TABLE IF NOT EXISTS sample_newsletters (')
        db.execute(schema[a:schema.index(';',a)+1].replace('IF NOT EXISTS sample_newsletters','sample_newsletters_compact'))
        db.execute('INSERT INTO sample_newsletters_compact (sample_id,html_content,created_at,saved_at,last_issued_newsletter_id) SELECT sample_id,html_content,created_at,saved_at,last_issued_newsletter_id FROM sample_newsletters')
        db.execute('DROP TABLE sample_newsletters')
        db.execute('ALTER TABLE sample_newsletters_compact RENAME TO sample_newsletters')
    db.execute('CREATE INDEX IF NOT EXISTS sample_runs_sample ON sample_runs(sample_id,started_at)')
    db.execute('CREATE INDEX IF NOT EXISTS sample_runs_user ON sample_runs(user_id,started_at)')
    db.execute('DROP VIEW IF EXISTS sample_details')
    db.execute(VIEW)
