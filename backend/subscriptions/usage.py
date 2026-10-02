"""Attribute shared subscription LLM work to its sample, including failed attempts."""
from contextvars import ContextVar
from backend.core.auth import database

subscription_sample_context = ContextVar('subscription_usage_sample', default=None)


def init_subscription_usage():
    with database() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS subscription_llm_requests (
            request_id TEXT PRIMARY KEY REFERENCES llm_requests(request_id) ON DELETE CASCADE,
            sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE CASCADE)''')
        db.execute('CREATE INDEX IF NOT EXISTS subscription_llm_sample ON subscription_llm_requests(sample_id)')
        # Backfill only unambiguous persisted links. Reused global article scores must
        # not be attributed to every sample that later consumed the cached result.
        db.execute("INSERT INTO subscription_llm_requests(request_id,sample_id)\n            SELECT x.request_id,min(x.sample_id) FROM (\n                SELECT request_id,sample_id FROM subscription_collection_runs\n                UNION SELECT request_id,sample_id FROM subscripted_articles\n                UNION SELECT n.request_id,n.sample_id FROM subscripted_newsletters n\n                UNION SELECT i.request_id,s.sample_id FROM subscripted_issues i\n                    JOIN subscriptions s USING(subscription_id)\n                UNION SELECT a.request_id,sa.sample_id FROM articles a\n                    JOIN subscripted_articles sa USING(article_id)\n            ) x JOIN llm_requests l ON l.request_id=x.request_id\n            WHERE l.step LIKE 'subscription_%'\n            GROUP BY x.request_id HAVING count(DISTINCT x.sample_id)=1 ON CONFLICT DO NOTHING")
