"""Persist returned Exa results before filtering, including partial collection successes."""
import uuid
from backend.core.auth import database, now


def init_exa_usage():
    with database() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS exa_search_usage (
            usage_id TEXT PRIMARY KEY,
            user_id TEXT REFERENCES users(user_id) ON DELETE SET NULL,
            sample_id TEXT REFERENCES sample_newsletters(sample_id) ON DELETE SET NULL,
            kind TEXT NOT NULL CHECK(kind IN ('sample','subscription')),
            run_id TEXT,
            result_count INTEGER NOT NULL CHECK(result_count>=0),
            created_at TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS exa_usage_time ON exa_search_usage(created_at)')
        db.execute('CREATE INDEX IF NOT EXISTS exa_usage_run ON exa_search_usage(run_id)')
        # Historical samples did not persist raw search counts; never infer them
        # from retained articles. Only existing subscription counts can be recovered.
        db.execute('''INSERT OR IGNORE INTO exa_search_usage
            SELECT 'legacy:'||r.run_id,r.user_id,r.sample_id,'subscription',r.run_id,r.search_results,r.started_at
            FROM subscription_collection_runs r WHERE r.search_results>0
            AND NOT EXISTS(SELECT 1 FROM exa_search_usage e WHERE e.run_id=r.run_id)''')


def record_results(count):
    from backend.core.tracking import sample_context,llm_user_context,subscription_collection_context
    from backend.subscriptions.usage import subscription_sample_context
    sample_id=subscription_sample_context.get() or sample_context.get()
    if not sample_id:return
    kind='subscription' if subscription_sample_context.get() else 'sample'
    user_id=llm_user_context.get()
    with database() as db:
        sample=db.execute('SELECT user_id,run_id FROM sample_details WHERE sample_id=?',(sample_id,)).fetchone()
        if not sample:return
        collection=subscription_collection_context.get()
        run_id=collection[0] if kind=='subscription' and collection else sample['run_id'] if kind=='sample' else None
        db.execute('INSERT INTO exa_search_usage VALUES(?,?,?,?,?,?,?)',
            (str(uuid.uuid4()),user_id or sample['user_id'],sample_id,kind,run_id,count,now()))


def search_count(db,bounds,user_id='',sample_id=None):
    conditions=['created_at>=?','created_at<?'];args=list(bounds)
    if user_id:conditions.append('user_id=?');args.append(user_id)
    if sample_id:conditions.extend(["kind='subscription'",'sample_id=?']);args.append(sample_id)
    return db.execute('SELECT COALESCE(sum(result_count),0) FROM exa_search_usage WHERE '+' AND '.join(conditions),args).fetchone()[0]
