"""Execution history for sample creation; errors remain in the errors table."""
import uuid
from backend.core.auth import now,database

def create_run(db,sid,uid,topic,start=None,end=None,step='topic_setup'):
    rid=str(uuid.uuid4())
    db.execute('INSERT INTO sample_runs (run_id,sample_id,user_id,topic,collection_start_date,collection_end_date,current_step,started_at) VALUES (?,?,?,?,?,?,?,?)',
               (rid,sid,uid,topic,start,end,step,now()))
    return rid


def set_step(db,sid,step,status='draft'):
    db.execute('UPDATE sample_runs SET current_step=?,status=? WHERE run_id=(SELECT run_id FROM sample_details WHERE sample_id=?)',(step,status,sid))


def progress_run(rid,step,status='running'):
    with database() as db:
        db.execute('UPDATE sample_runs SET current_step=?,status=? WHERE run_id=?',(step,status,rid))


def prepare_configuration(db,sid):
    row=db.execute('SELECT * FROM sample_details WHERE sample_id=?',(sid,)).fetchone()
    if row['current_step'].startswith('news_') or row['run_status'] in ('failed','cancelled'):
        create_run(db,sid,row['user_id'],row['topic'],row['collection_start_date'],row['collection_end_date'])
