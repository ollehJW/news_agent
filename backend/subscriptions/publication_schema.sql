CREATE TABLE IF NOT EXISTS subscription_publication_jobs (
 job_id TEXT PRIMARY KEY,
 subscription_id TEXT NOT NULL REFERENCES subscriptions(subscription_id) ON DELETE RESTRICT,
 scheduled_date TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('running','completed','skipped','failed','review')),
 attempt INTEGER NOT NULL DEFAULT 1,
 attempt_token TEXT NOT NULL,
 newsletter_id TEXT REFERENCES subscripted_newsletters(newsletter_id) ON DELETE RESTRICT,
 started_at TEXT NOT NULL,
 completed_at TEXT,
 UNIQUE(subscription_id,scheduled_date)
);
