CREATE TABLE IF NOT EXISTS mailing (
 mailing_id TEXT PRIMARY KEY,
 user_id TEXT REFERENCES users(user_id) ON DELETE SET NULL,
 request_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('sample','subscription')),
 newsletter_id TEXT NOT NULL,
 subject TEXT,
 sender_email TEXT,
 mailing_list TEXT NOT NULL CHECK(json_valid(mailing_list) AND json_type(mailing_list)='array'),
 results_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(results_json) AND json_type(results_json)='array'),
 status TEXT NOT NULL CHECK(status IN ('processing','completed')),
 created_at TEXT NOT NULL,
 sent_at TEXT,
 completed_at TEXT,
 UNIQUE(user_id,request_id)
);
CREATE INDEX IF NOT EXISTS mailing_newsletter ON mailing(kind,newsletter_id,created_at);
CREATE INDEX IF NOT EXISTS mailing_user ON mailing(user_id,created_at);
