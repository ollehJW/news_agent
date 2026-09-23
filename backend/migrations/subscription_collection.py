"""Share raw subscription articles by sample while retaining previous links."""
from backend.core.paths import BACKEND_DIR


def migrate_subscription_collection(db):
    for statement in (BACKEND_DIR/'subscriptions/collection_schema.sql').read_text().split(';'):
        if statement.strip():db.execute(statement)
    columns={r['name'] for r in db.execute('PRAGMA table_info(subscripted_articles)')}
    if 'subscription_id' in columns:
        db.execute('''CREATE TABLE subscripted_articles_new (
            sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE CASCADE,
            article_id TEXT NOT NULL REFERENCES articles(article_id) ON DELETE RESTRICT,
            request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
            run_id TEXT REFERENCES subscription_collection_runs(run_id) ON DELETE SET NULL,
            collected_at TEXT NOT NULL, PRIMARY KEY(sample_id,article_id))''')
        # Prior schema did not record link time; reuse known LLM completion or article collection time.
        db.execute('''INSERT OR IGNORE INTO subscripted_articles_new
            SELECT s.sample_id,sa.article_id,sa.request_id,NULL,COALESCE(l.completed_at,a.collected_at)
            FROM subscripted_articles sa JOIN subscriptions s USING(subscription_id)
            JOIN articles a USING(article_id) LEFT JOIN llm_requests l ON l.request_id=sa.request_id
            ORDER BY COALESCE(l.completed_at,a.collected_at),sa.subscription_id''')
        # Issues still belong to individual subscriptions; their article FK now targets shared articles.
        db.execute('''CREATE TABLE subscripted_issues_new (
            issue_id TEXT PRIMARY KEY,
            subscription_id TEXT NOT NULL REFERENCES subscriptions(subscription_id) ON DELETE RESTRICT,
            article_id TEXT NOT NULL REFERENCES articles(article_id) ON DELETE RESTRICT,
            request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
            summary TEXT,rank INTEGER NOT NULL CHECK(rank>0),created_at TEXT NOT NULL)''')
        db.execute('INSERT INTO subscripted_issues_new SELECT issue_id,subscription_id,article_id,request_id,summary,rank,created_at FROM subscripted_issues')
        db.execute('DROP TABLE subscripted_issues')
        db.execute('DROP TABLE subscripted_articles')
        db.execute('ALTER TABLE subscripted_articles_new RENAME TO subscripted_articles')
        db.execute('ALTER TABLE subscripted_issues_new RENAME TO subscripted_issues')
    db.execute('CREATE INDEX IF NOT EXISTS subscripted_articles_article ON subscripted_articles(article_id)')
    db.execute('CREATE INDEX IF NOT EXISTS subscripted_articles_collected ON subscripted_articles(sample_id,collected_at)')
    db.execute('CREATE INDEX IF NOT EXISTS subscripted_issues_subscription ON subscripted_issues(subscription_id,created_at)')
    db.execute('CREATE INDEX IF NOT EXISTS subscripted_issues_article ON subscripted_issues(article_id)')
    db.execute('CREATE INDEX IF NOT EXISTS subscripted_issues_request ON subscripted_issues(request_id)')
