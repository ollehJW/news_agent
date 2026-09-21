"""Sample-owned domain selections and draft samples."""
import json
import uuid
from backend.core.auth import now


def ensure_draft(db, run_id):
    if 'run_id' not in {r['name'] for r in db.execute('PRAGMA table_info(sample_newsletters)')}:
        from backend.samples.sample_lifecycle import legacy_current_sample
        return legacy_current_sample(db,run_id)
    row = db.execute("SELECT sample_id FROM sample_newsletters WHERE run_id=? AND status='draft'", (run_id,)).fetchone()
    if row:
        return row[0]
    run = db.execute('SELECT * FROM newsletter_runs WHERE run_id=?', (run_id,)).fetchone()
    sid = str(uuid.uuid4())
    snapshot = json.dumps({'topic':run['topic'],'domains':[],'issues':[],
                           'dates':{'start':run['start_date'],'end':run['end_date']}},ensure_ascii=False)
    db.execute('''INSERT INTO sample_newsletters
        (sample_id,run_id,user_id,title,html_content,template_version,content_hash,issue_count,snapshot_json,created_at,status)
        VALUES (?,?,?,?,?,'draft','draft',0,?,?,'draft')''',
        (sid,run_id,run['user_id'],run['topic'],'',snapshot,now()))
    return sid


def migrate_run_domains(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_domains'").fetchone():
        return
    rows = [dict(r) for r in db.execute('SELECT rd.*,d.host FROM run_domains rd JOIN domains d USING(domain_id) ORDER BY rd.created_at,rd.run_domain_id')]
    by_id = {r['run_domain_id']:r for r in rows}
    # Each completed sample keeps its own sources, rather than the run's latest choices.
    for sample in db.execute("SELECT * FROM sample_newsletters WHERE status='completed'").fetchall():
        for item in json.loads(sample['snapshot_json']).get('domains',[]):
            domain=db.execute('SELECT domain_id FROM domains WHERE host=?',(item.get('host'),)).fetchone()
            if not domain:
                continue
            old=by_id.get(item.get('run_domain_id'),{})
            manual=item.get('custom',old.get('added_by')=='manual')
            db.execute('''INSERT OR IGNORE INTO sample_domains
                (sample_id,domain_id,kind,description,recommendation_reason,topic_relevance,created_at)
                VALUES (?,?,?,?,?,?,?)''',(sample['sample_id'],domain[0],'manual' if manual else 'recommended',
                item.get('desc',old.get('description')),item.get('reason',old.get('recommendation_reason')),
                item.get('relevance',old.get('topic_relevance')),sample['created_at']))
    for run_id in {r['run_id'] for r in rows}:
        sid=ensure_draft(db,run_id)
        for row in (r for r in rows if r['run_id']==run_id and r['is_selected']):
            db.execute('''INSERT OR REPLACE INTO sample_domains
                (sample_id,domain_id,kind,description,recommendation_reason,topic_relevance,created_at)
                VALUES (?,?,?,?,?,?,?)''',(sid,row['domain_id'],'manual' if row['added_by']=='manual' else 'recommended',
                row['description'],row['recommendation_reason'],row['topic_relevance'],row['created_at']))
    db.execute('DROP TABLE run_domains')
