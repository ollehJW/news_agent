CREATE TABLE IF NOT EXISTS domains (
 domain_id TEXT PRIMARY KEY, host TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sample_newsletters (
 sample_id TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
 topic TEXT NOT NULL,
 collection_start_date TEXT, collection_end_date TEXT,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','completed')),
 html_content TEXT, created_at TEXT NOT NULL, completed_at TEXT, saved_at TEXT,
 last_issued_newsletter_id TEXT REFERENCES subscripted_newsletters(newsletter_id) ON DELETE SET NULL,
 CHECK(collection_start_date IS NULL OR collection_end_date IS NULL OR collection_end_date>=collection_start_date),
 CHECK(status!='completed' OR (html_content IS NOT NULL AND completed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS sample_newsletters_owner ON sample_newsletters(user_id,saved_at);
CREATE TABLE IF NOT EXISTS llm_requests (
 request_id TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
 step TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
 input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, cached_input_tokens INTEGER,
 started_at TEXT NOT NULL, completed_at TEXT, duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS llm_requests_user_step ON llm_requests(user_id,step,started_at);

-- Daily collection is shared by reference newsletter; publication time is fixed at 08:00 KST.
CREATE TABLE IF NOT EXISTS subscripted_articles (
 article_id TEXT PRIMARY KEY,
 sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE RESTRICT,
 domain_id TEXT NOT NULL REFERENCES domains(domain_id),
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 url TEXT NOT NULL CHECK(length(trim(url))>0), title TEXT NOT NULL,
 published_at TEXT, content TEXT, image_url TEXT, favicon_url TEXT, image_storage_path TEXT,
 collected_at TEXT NOT NULL,
 technical_score REAL CHECK(technical_score BETWEEN 0 AND 100),
 organization_score REAL CHECK(organization_score BETWEEN 0 AND 100),
 impact_score REAL CHECK(impact_score BETWEEN 0 AND 100),
 recency_score REAL CHECK(recency_score BETWEEN 0 AND 100),
 total_score REAL CHECK(total_score BETWEEN 0 AND 100),
 UNIQUE(sample_id,url)
);
CREATE INDEX IF NOT EXISTS subscripted_articles_period ON subscripted_articles(sample_id,published_at);
CREATE INDEX IF NOT EXISTS subscripted_articles_collected ON subscripted_articles(sample_id,collected_at);

CREATE TABLE IF NOT EXISTS subscriptions (
 subscription_id TEXT PRIMARY KEY,
 sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE RESTRICT,
 user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','cancelled')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(sample_id,user_id)
);
CREATE INDEX IF NOT EXISTS subscriptions_reference ON subscriptions(sample_id,status);

-- One shared edition per sample and coverage period.
CREATE TABLE IF NOT EXISTS subscripted_newsletters (
 newsletter_id TEXT PRIMARY KEY,
 sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE RESTRICT,
 coverage_start_date TEXT NOT NULL,
 coverage_end_date TEXT NOT NULL CHECK(coverage_end_date>=coverage_start_date),
 issue_ids TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(issue_ids) AND json_type(issue_ids)='array'),
 summary TEXT,
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 html_content TEXT NOT NULL,
 created_at TEXT NOT NULL, published_at TEXT,
 UNIQUE(sample_id,coverage_start_date,coverage_end_date)
);
CREATE INDEX IF NOT EXISTS subscripted_newsletters_sample ON subscripted_newsletters(sample_id,published_at);
CREATE INDEX IF NOT EXISTS subscripted_newsletters_request ON subscripted_newsletters(request_id);

CREATE TABLE IF NOT EXISTS subscription_history (
 subscription_id TEXT NOT NULL REFERENCES subscriptions(subscription_id) ON DELETE RESTRICT,
 newsletter_id TEXT NOT NULL REFERENCES subscripted_newsletters(newsletter_id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL,
 PRIMARY KEY(subscription_id,newsletter_id)
);
CREATE INDEX IF NOT EXISTS subscription_history_newsletter ON subscription_history(newsletter_id);

CREATE TABLE IF NOT EXISTS sample_domains (
 sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE CASCADE,
 domain_id TEXT NOT NULL REFERENCES domains(domain_id),
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 kind TEXT NOT NULL CHECK(kind IN ('recommended','manual')),
 description TEXT, recommendation_reason TEXT, topic_relevance TEXT,
 created_at TEXT NOT NULL,
 PRIMARY KEY(sample_id,domain_id),
 CHECK(kind!='manual' OR request_id IS NULL)
);
CREATE INDEX IF NOT EXISTS sample_domains_request ON sample_domains(request_id);


CREATE TABLE IF NOT EXISTS sample_articles (
 article_id TEXT PRIMARY KEY,
 sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE CASCADE,
 domain_id TEXT REFERENCES domains(domain_id),
 url TEXT NOT NULL, title TEXT NOT NULL, published_at TEXT, content TEXT, summary TEXT, highlights TEXT,
 image_url TEXT, favicon_url TEXT, image_storage_path TEXT, collected_at TEXT NOT NULL,
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 technical_score REAL CHECK(technical_score BETWEEN 0 AND 100),
 organization_score REAL CHECK(organization_score BETWEEN 0 AND 100),
 impact_score REAL CHECK(impact_score BETWEEN 0 AND 100),
 recency_score REAL CHECK(recency_score BETWEEN 0 AND 100),
 total_score REAL CHECK(total_score BETWEEN 0 AND 100),
 UNIQUE(sample_id,url), UNIQUE(sample_id,article_id)
);
CREATE TABLE IF NOT EXISTS sample_issues (
 issue_id TEXT PRIMARY KEY,
 sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE CASCADE,
 article_id TEXT NOT NULL,
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 rank INTEGER NOT NULL CHECK(rank>0), created_at TEXT NOT NULL,
 UNIQUE(sample_id,article_id), UNIQUE(sample_id,rank),
 FOREIGN KEY(sample_id,article_id) REFERENCES sample_articles(sample_id,article_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS sample_issues_rank ON sample_issues(sample_id,rank);

-- Only automatically selected subscription issues are stored here.
CREATE TABLE IF NOT EXISTS subscripted_issues (
 issue_id TEXT PRIMARY KEY,
 subscription_id TEXT NOT NULL REFERENCES subscriptions(subscription_id) ON DELETE RESTRICT,
 article_id TEXT NOT NULL REFERENCES subscripted_articles(article_id) ON DELETE RESTRICT,
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 summary TEXT,
 rank INTEGER NOT NULL CHECK(rank>0),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS subscripted_issues_subscription ON subscripted_issues(subscription_id,created_at);
CREATE INDEX IF NOT EXISTS subscripted_issues_article ON subscripted_issues(article_id);
CREATE INDEX IF NOT EXISTS subscripted_issues_request ON subscripted_issues(request_id);

CREATE TABLE IF NOT EXISTS errors (
 error_id TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
 step TEXT NOT NULL,
 error_type TEXT NOT NULL,
 message TEXT NOT NULL,
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS errors_user_step ON errors(user_id,step,created_at);
CREATE INDEX IF NOT EXISTS errors_request ON errors(request_id);

CREATE TABLE IF NOT EXISTS subscription_settings (
 subscription_id TEXT PRIMARY KEY REFERENCES subscriptions(subscription_id) ON DELETE CASCADE,
 name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 80),
 frequency TEXT NOT NULL CHECK(frequency IN ('daily','weekly','monthly')),
 weekdays TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(weekdays) AND json_type(weekdays)='array'),
 month_day INTEGER NOT NULL DEFAULT 1 CHECK(month_day BETWEEN 1 AND 31),
 start_date TEXT NOT NULL,
 CHECK(frequency!='weekly' OR json_array_length(weekdays)>0)
);

CREATE TABLE IF NOT EXISTS subject_validation (
 validation_id TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
 topic TEXT NOT NULL,
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 candidates_json TEXT NOT NULL CHECK(json_valid(candidates_json) AND json_type(candidates_json)='array'),
 matches_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(matches_json) AND json_type(matches_json)='array'),
 status TEXT NOT NULL CHECK(status IN ('processing','completed','failed','cancelled')),
 created_at TEXT NOT NULL, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS subject_validation_user ON subject_validation(user_id,created_at);
CREATE INDEX IF NOT EXISTS subject_validation_request ON subject_validation(request_id);

CREATE TABLE IF NOT EXISTS sample_queries (
 query_id TEXT PRIMARY KEY,
 sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE CASCADE,
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 query TEXT NOT NULL CHECK(length(trim(query)) BETWEEN 1 AND 400),
 position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 5),
 created_at TEXT NOT NULL,
 UNIQUE(sample_id,position), UNIQUE(sample_id,query)
);
CREATE INDEX IF NOT EXISTS sample_queries_request ON sample_queries(request_id);
