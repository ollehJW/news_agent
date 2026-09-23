CREATE TABLE IF NOT EXISTS subscription_collection_runs (
 run_id TEXT PRIMARY KEY,
 sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(user_id),
 collection_date TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('running','completed','failed','cancelled')),
 attempt INTEGER NOT NULL DEFAULT 1,
 attempt_token TEXT NOT NULL,
 configuration_json TEXT NOT NULL,
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 search_results INTEGER NOT NULL DEFAULT 0,
 url_duplicates INTEGER NOT NULL DEFAULT 0,
 invalid_results INTEGER NOT NULL DEFAULT 0,
 history_url_excluded INTEGER NOT NULL DEFAULT 0,
 candidate_count INTEGER NOT NULL DEFAULT 0,
 retained_count INTEGER NOT NULL DEFAULT 0,
 saved_count INTEGER NOT NULL DEFAULT 0,
 started_at TEXT NOT NULL,
 completed_at TEXT,
 UNIQUE(sample_id,collection_date)
);
CREATE UNIQUE INDEX IF NOT EXISTS subscription_collection_running ON subscription_collection_runs(sample_id) WHERE status='running';
CREATE INDEX IF NOT EXISTS subscription_collection_date ON subscription_collection_runs(collection_date,status);
