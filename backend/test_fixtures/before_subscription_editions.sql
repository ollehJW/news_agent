CREATE TABLE IF NOT EXISTS newsletter_runs (
 run_id TEXT PRIMARY KEY, sample_id TEXT REFERENCES sample_newsletters(sample_id) ON DELETE SET NULL, user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
 topic TEXT NOT NULL, start_date TEXT, end_date TEXT, current_step INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'draft', data_mode TEXT NOT NULL DEFAULT 'demo',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT, error_message TEXT
);
CREATE INDEX IF NOT EXISTS runs_owner ON newsletter_runs(user_id,created_at);
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
 last_issued_newsletter_id TEXT REFERENCES newsletters(newsletter_id) ON DELETE SET NULL,
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

-- Actual subscription editions are shared outputs, independent of sample ownership.
CREATE TABLE IF NOT EXISTS newsletters (
 newsletter_id TEXT PRIMARY KEY,
 title TEXT NOT NULL, html_content TEXT NOT NULL, template_version TEXT NOT NULL,
 content_hash TEXT NOT NULL, issue_count INTEGER NOT NULL CHECK(issue_count>=0),
 snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS newsletter_publications (
 publication_id TEXT PRIMARY KEY,
 sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE RESTRICT,
 coverage_start TEXT NOT NULL, coverage_end TEXT NOT NULL CHECK(coverage_end>=coverage_start),
 newsletter_id TEXT UNIQUE REFERENCES newsletters(newsletter_id) ON DELETE SET NULL,
 selected_article_ids TEXT NOT NULL DEFAULT '[]'
   CHECK(json_valid(selected_article_ids) AND json_type(selected_article_ids)='array'),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','completed','failed')),
 published_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(sample_id,coverage_start,coverage_end)
);
CREATE INDEX IF NOT EXISTS publications_status ON newsletter_publications(status,created_at);


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
 url TEXT NOT NULL, title TEXT NOT NULL, published_at TEXT, content TEXT, summary TEXT,
 image_url TEXT, favicon_url TEXT, image_storage_path TEXT, collected_at TEXT NOT NULL,
 UNIQUE(sample_id,url), UNIQUE(sample_id,article_id)
);
CREATE TABLE IF NOT EXISTS sample_issues (
 issue_id TEXT PRIMARY KEY,
 sample_id TEXT NOT NULL REFERENCES sample_newsletters(sample_id) ON DELETE CASCADE,
 article_id TEXT NOT NULL,
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 technical_score INTEGER CHECK(technical_score BETWEEN 0 AND 100),
 organization_score INTEGER CHECK(organization_score BETWEEN 0 AND 100),
 impact_score INTEGER CHECK(impact_score BETWEEN 0 AND 100),
 recency_score INTEGER CHECK(recency_score BETWEEN 0 AND 100),
 total_score INTEGER CHECK(total_score BETWEEN 0 AND 100), rank INTEGER CHECK(rank>0),
 is_selected INTEGER NOT NULL DEFAULT 0 CHECK(is_selected IN (0,1)),
 duplicate_of_issue_id TEXT, created_at TEXT NOT NULL,
 UNIQUE(sample_id,article_id), UNIQUE(sample_id,issue_id),
 FOREIGN KEY(sample_id,article_id) REFERENCES sample_articles(sample_id,article_id) ON DELETE CASCADE,
 FOREIGN KEY(sample_id,duplicate_of_issue_id) REFERENCES sample_issues(sample_id,issue_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK(duplicate_of_issue_id IS NULL OR (is_selected=0 AND duplicate_of_issue_id!=issue_id))
);
CREATE INDEX IF NOT EXISTS sample_issues_rank ON sample_issues(sample_id,rank);
CREATE INDEX IF NOT EXISTS sample_issues_duplicate ON sample_issues(sample_id,duplicate_of_issue_id);

-- Only automatically selected subscription issues are stored here.
CREATE TABLE IF NOT EXISTS subscripted_issues (
 issue_id TEXT PRIMARY KEY,
 subscription_id TEXT NOT NULL REFERENCES subscriptions(subscription_id) ON DELETE RESTRICT,
 article_id TEXT NOT NULL REFERENCES subscripted_articles(article_id) ON DELETE RESTRICT,
 request_id TEXT REFERENCES llm_requests(request_id) ON DELETE SET NULL,
 summary TEXT,
 technical_score REAL CHECK(technical_score BETWEEN 0 AND 100),
 organization_score REAL CHECK(organization_score BETWEEN 0 AND 100),
 impact_score REAL CHECK(impact_score BETWEEN 0 AND 100),
 recency_score REAL CHECK(recency_score BETWEEN 0 AND 100),
 total_score REAL CHECK(total_score BETWEEN 0 AND 100),
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS subscripted_issues_subscription ON subscripted_issues(subscription_id,created_at);
CREATE INDEX IF NOT EXISTS subscripted_issues_article ON subscripted_issues(article_id);
CREATE INDEX IF NOT EXISTS subscripted_issues_request ON subscripted_issues(request_id);
