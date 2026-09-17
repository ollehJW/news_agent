CREATE TABLE IF NOT EXISTS newsletter_runs (
 run_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
 topic TEXT NOT NULL, start_date TEXT, end_date TEXT, current_step INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'draft', data_mode TEXT NOT NULL DEFAULT 'demo',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT, error_message TEXT
);
CREATE INDEX IF NOT EXISTS runs_owner ON newsletter_runs(user_id,created_at);
CREATE TABLE IF NOT EXISTS domains (
 domain_id TEXT PRIMARY KEY, host TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_domains (
 run_domain_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES newsletter_runs(run_id) ON DELETE CASCADE,
 domain_id TEXT NOT NULL REFERENCES domains(domain_id), recommendation_batch_id TEXT,
 name TEXT NOT NULL, kind TEXT, description TEXT, recommendation_reason TEXT, topic_relevance TEXT,
 recommendation_rank INTEGER, added_by TEXT NOT NULL CHECK(added_by IN ('ai','manual')),
 is_selected INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS run_domains_run ON run_domains(run_id,domain_id);
CREATE TABLE IF NOT EXISTS run_articles (
 article_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES newsletter_runs(run_id) ON DELETE CASCADE,
 domain_id TEXT REFERENCES domains(domain_id), issue_id TEXT REFERENCES run_issues(issue_id) ON DELETE SET NULL,
 url TEXT NOT NULL, title TEXT NOT NULL, source TEXT, author TEXT, published_at TEXT,
 content_text TEXT, summary TEXT, image_url TEXT, favicon_url TEXT, image_storage_path TEXT,
 image_alt TEXT, data_mode TEXT NOT NULL DEFAULT 'demo', collected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS articles_run ON run_articles(run_id);
CREATE TABLE IF NOT EXISTS run_issues (
 issue_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES newsletter_runs(run_id) ON DELETE CASCADE,
 title TEXT NOT NULL, summary TEXT, representative_article_id TEXT REFERENCES run_articles(article_id) ON DELETE SET NULL,
 technical_score INTEGER, organization_score INTEGER, impact_score INTEGER, recency_score INTEGER,
 total_score INTEGER, rank INTEGER, is_default_selected INTEGER NOT NULL DEFAULT 0,
 is_selected INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS issues_run ON run_issues(run_id,rank);
CREATE TABLE IF NOT EXISTS newsletters (
 newsletter_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES newsletter_runs(run_id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE, title TEXT NOT NULL,
 html_content TEXT NOT NULL, template_version TEXT NOT NULL, content_hash TEXT NOT NULL,
 issue_count INTEGER NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL, saved_at TEXT,
 UNIQUE(run_id,content_hash)
);
CREATE INDEX IF NOT EXISTS newsletters_owner ON newsletters(user_id,saved_at);
CREATE TABLE IF NOT EXISTS usage_events (
 event_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
 run_id TEXT REFERENCES newsletter_runs(run_id) ON DELETE CASCADE,
 newsletter_id TEXT REFERENCES newsletters(newsletter_id) ON DELETE SET NULL,
 event_type TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run ON usage_events(run_id,created_at);
CREATE TABLE IF NOT EXISTS ai_requests (
 request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES newsletter_runs(run_id) ON DELETE CASCADE,
 logical_call_id TEXT NOT NULL, operation TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
 provider_request_id TEXT, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
 cached_input_tokens INTEGER, status TEXT NOT NULL, attempt_number INTEGER NOT NULL,
 duration_ms INTEGER, error_message TEXT, created_at TEXT NOT NULL, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS ai_requests_run ON ai_requests(run_id,operation);
