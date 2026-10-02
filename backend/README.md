> 2026-10-02: PostgreSQL 및 AX for Works 통합 로그인으로 전환했습니다. 현재 DB 설정·이관·운영 절차는 [wianews PostgreSQL 가이드](../POSTGRESQL.md)를 따르세요. 아래 SQLite/app.db 및 서비스별 로그인 설명은 전환 전 기록입니다.

# Backend 구조

실행: 프로젝트 루트에서 `.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 6112`

| 위치 | 역할 |
| --- | --- |
| `main.py` | FastAPI 진입점, 라우터 연결, 시작 처리 |
| `core/` | 인증·계정, DB 초기화, LLM 사용량·오류 기록, 추천 서명, 리소스 경로 |
| `integrations/` | Exa 검색 및 Azure OpenAI 연결 |
| `recommendations/` | 주제 중복 확인, 검색 쿼리·도메인 추천, 추천 SSE |
| `news/` | 샘플·구독 공통 스코어링 및 LLM 분석 보조 함수 |
| `samples/` | 샘플 생성·설정·기사 저장·인덱스 기반 전처리·수집 실행·뉴스레터 렌더링 |
| `subscriptions/` | 구독 설정, 마켓플레이스, 발행본 미리보기 API |
| `migrations/` | 구버전 DB 테이블을 현재 구조로 변환하는 호환 코드 |
| `newsletter_schema.sql` | 현재 뉴스레터 DB 스키마 |
| `app.db` | 로컬 SQLite DB, Git 제외 |
| `template/` | 뉴스레터 HTML 템플릿 |

## 수집 흐름

`samples/sample_collection.py` → `integrations/exa_search.py` → `samples/sample_preprocessing.py` → `news/news_scoring.py` → 샘플 기사·이슈 저장.

구독 버전은 Exa 수집 모듈을 공유하고, 최근 7일간의 세부 주제 중복 비교는 별도 구독 전처리 모듈에서 수행합니다. 구독 수집 후 공통 평가 모듈로 미평가 기사를 평가합니다.

`core/paths.py`에서 프로젝트·백엔드 기준 경로를 관리합니다. `.env`는 프로젝트 루트, DB·SQL 스키마·템플릿은 기존 backend 경로를 사용합니다.

`migrations/`는 서버 시작 시 DB 초기화에서 참조하므로 현재 DB에서 변환 작업이 없더라도 임의로 삭제하지 않습니다. 샘플 복제 등 현재 실행 기능과 결합된 일부 마이그레이션 함수는 `samples/`와 `core/`에 남아 있습니다.

### 공통 기사와 레터 연결

- `articles`: 정규화 URL을 UNIQUE 키로 기사 정보, highlights, 요약, 점수 4종을 한 번 저장합니다. `request_id`는 평가 LLM 호출입니다. `score_version`, `scored_at`는 평가 버전과 평가 시간을 기록합니다.
- `sample_articles(sample_id, article_id, request_id)`: 전처리를 통과한 기사 연결입니다. `request_id`는 해당 수집의 주제·중복 전처리 호출입니다.
- `subscripted_articles(sample_id, article_id, request_id, run_id, collected_at)`: 같은 샘플을 구독하는 사용자들이 공유하는 전처리 통과 기사 연결입니다. collected_at은 해당 샘플에 추가한 시각입니다.
- `sample_issues`, `subscripted_issues`: 레터에 선택한 기사와 `rank`만 관리하며 점수는 기사에서 읽습니다. 샘플의 기본 선택은 상위 5개입니다.
- URL이 같고 평가 버전·기본 점수 3종·요약이 유효하면 평가 LLM을 생략합니다. 주제는 평가 입력에서 제외하며 주제 적합성·중복 전처리는 수집마다 실행합니다. 전처리 탈락 기사는 이번 샘플에 연결하지 않습니다.
- 총점은 기술적 중요성 40%, 기술 주체 경쟁력 30%, 파급력 30%를 합산해 정수로 반올림합니다. 최신성은 점수에 포함하지 않습니다.
- 동일 URL의 동시 평가를 프로세스 내 잠금으로 합칩니다. DB URL UNIQUE 제약은 여러 프로세스에서도 기사 행 중복을 막습니다. 여러 워커를 운영할 경우 평가 호출 자체의 중복까지 막으려면 분산 잠금이 추가로 필요합니다.
- 완성된 샘플을 복사해도 기사 ID는 재사용하고 연결·선택 행만 복사합니다. 선택 API는 순서가 있는 `article_ids` 배열을 받습니다.
- 기존 전처리 호출을 정확히 역추적할 수 없는 샘플 연결의 `request_id`는 NULL로 이전합니다. 기존 평가 요청은 `articles.request_id`로 보존합니다.
- 구독 자동 수집·평가와 오전 8시 자동 선정·발행·구독별 묶음 메일 발송이 연결되어 있습니다.

### 샘플 결과와 실행 이력

- `sample_newsletters`: `sample_id`, `html_content`, `total_summary`, 요약 LLM `request_id`, `created_at`, `saved_at`, `last_issued_newsletter_id`를 저장합니다.
- `sample_runs`: `run_id`, `sample_id`, `user_id`, `topic`, `collection_start_date`, `collection_end_date`, `current_step`, `status`, `started_at`, `completed_at`를 저장합니다.
- 단계는 `topic_setup` → `source_setup` → `period_setup` → `news_collection` → `news_preprocessing` → `news_scoring` → `news_selection` → `newsletter_completed`입니다. 상태는 draft/running/completed/failed/cancelled입니다.
- 동일 샘플을 재수집하면 새 실행 ID를 만듭니다. 수집 후 설정을 수정할 때도 기존 실행 설정을 보존하고 새 실행으로 전환합니다. 완성된 샘플을 수정하면 새 샘플과 실행을 생성합니다.
- `sample_details` 뷰는 샘플 결과와 최신 실행을 합쳐 기존 API·구독 화면의 응답 형식을 유지합니다. `/api/sample-runs`는 로그인한 사용자의 실행 이력을 반환합니다.
- 과거 데이터는 샘플별로 보존된 메타데이터와 현재 상태에서 추정한 단계로 실행 1건을 이전합니다. 과거 재시도·단계별 시각을 복원한 기록은 아닙니다. 오류 상세는 기존 `errors`에 기록합니다.

- 뉴스레터 생성 시 선택된 N개 기사의 제목·요약을 한 번의 LLM 요청(`sample_newsletter_summary`)에 전달해 기사 전체의 흐름을 종합한 최대 3개 핵심 하이라이트를 생성합니다. `total_summary`는 각 줄이 `- `로 시작하는 문자열이며 호출 ID와 함께 저장합니다. 생성 단계는 `newsletter_summary`이며, 설정·선택 변경 충돌 시 결과를 저장하지 않습니다.

## Newsletter email

`POST /api/newsletter-email` accepts `request_id`, `kind` (`sample` or `subscription`), `newsletter_id`, and `user_ids` (up to 100). It loads authorized HTML and recipient addresses from the database, sends one HTML MIME message with all unique selected addresses in To through Gmail SMTP SSL (465), and records results in `mailing`. Repeating a request ID returns its stored results without resending. `sent` means SMTP acceptance, not guaranteed inbox delivery; `unknown` is not automatically retried.

Set `GMAIL_USER` and `GMAIL_APP_PASSWORD` in the ignored root `.env`. The normal account password is not used. `GMAIL_CA_BUNDLE` and `GMAIL_LEGACY_CA=1` support an already trusted legacy corporate CA while keeping certificate/hostname verification enabled. SMTP network access is required.

On this network, Gmail disconnects after EHLO. Delivery therefore uses the existing AI Lounge handshake: TLS-verified SMTP SSL 465, HELO, then AUTH PLAIN inside TLS. Credentials and authentication payloads must never be logged.

### Mailing history

`mailing` stores one row per send request: UUID `mailing_id`, requesting `user_id`, idempotency `request_id`, `kind`, `newsletter_id` (sample_id when kind=sample), subject, sender_email, mailing_list (JSON user/name/email snapshots), results_json (per-recipient status/email/sent_at/completed_at), status, created_at, sent_at (latest known SMTP acceptance), completed_at. Timestamps use UTC. A completed request can contain failed or unknown recipients; inspect results_json. GET /api/newsletter-email/history returns only the current user's latest 200 requests. Legacy rows are migrated atomically; unavailable historical addresses/acceptance times remain NULL.

### Article images and email CID

Article images are downloaded after shared scoring and saved as validated, resized JPEGs under `backend/workspace/{article_id}/image-{url_hash}.jpg`. `articles.image_storage_path` is relative to backend/. Workspace files are ignored by Git and must be backed up with app.db. Downloads check public hosts and redirects, bound size, and retain TLS verification. Mail preparation retries missing files, attaches local images once per shared message, and sends multipart/related CID inline attachments (up to 10 MiB of image data per newsletter). Unavailable images are omitted from email; original HTML and image links remain unchanged. Existing caches survive startup migrations.

## Daily subscription collection

- FastAPI lifespan starts an in-process scheduler. With the backend running, polling every 30 seconds triggers collection from 05:00 Asia/Seoul. The target is the previous calendar day, 00:00 inclusive through next 00:00 exclusive KST. This version uses exactly that day, without overlapping search windows.
- Collect once per sample with at least one active subscription and active account. The first eligible collection date is the later of subscription creation date (KST) and configured start_date; the earliest eligible active subscription sets the shared start. Daily/weekly/monthly settings affect future publication, not daily collection.
- Restart catches up missing dates oldest first (up to seven dates per sample per pass). Failures retry after an hour, up to three attempts per date; authenticated manual calls can retry afterward. SQLite enforces one running collection per sample and one record per sample/date. Runs time out after 360 seconds; abandoned claims can be reclaimed after ten minutes using an attempt token, preventing stale writers from committing.
- Shared Exa queries (up to five) -> canonical URL deduplication -> remove all URLs already linked to this sample, even if older than seven days -> one subscription-specific LLM pass over new candidates and articles linked within the preceding seven days. Strict **specific-subtopic** deduplication rejects incremental features, new figures and follow-up coverage of the same specific subtopic. Broad company/category matches alone do not exclude everything. LLM evidence is title/date/URL/highlights, never full content; response contains only new candidate indices.
- Atomically insert raw `articles` by globally unique URL and link survivors in `subscripted_articles`. Existing global article IDs/content/evaluations are reused unchanged. New rows have NULL scoring, summary, newsletter_title and evaluation request_id. Rejected candidates are not stored. Link request_id points to preprocessing; run_id points to the daily execution. Optional image caching runs afterward.
- `subscription_collection_runs` records sample, date, initiating user, attempts, configuration snapshot, LLM request, counts and timestamps. Counts include search results, invalid results, URL duplicates, previously linked URLs, input candidates, retained and saved articles. `llm_requests` records model/tokens/timing under `subscription_article_preprocessing`; scheduled calls are attributed to the earliest active subscriber. Failures are recorded in `errors` with the executing step. No issues, editions, subscription delivery history, or mailings are created.
- `POST /api/subscriptions/{subscription_id}/collect` with `{}` collects yesterday, or supply `{"collection_date":"YYYY-MM-DD"}` for an earlier date. Caller must own an active subscription; today/future dates are rejected. Repeating a completed sample/date returns its result without external calls.
- `GET /api/subscriptions/{subscription_id}/collections` returns shared execution history to that subscription's owner, including paused/cancelled subscriptions. Prompt/configuration snapshots and lease tokens are not exposed.
- `WIANEWS_SUBSCRIPTION_COLLECTION_ENABLED=0` disables automatic scheduling (manual API remains available). The publication scheduler is separate from collection; no frontend collection controls are included.
- Migration merges previous per-subscription article links into `(sample_id, article_id)`, preserving issues. Legacy link time falls back to known preprocessing completion/article collection time because the old schema did not record link timestamps. Future links always use actual insertion time.

Group email sends one SMTP DATA transaction to up to 100 selected users; duplicate addresses are collapsed. SMTP recipient refusals are recorded per user, successful recipients are not resent, and disconnected submissions remain unknown. Recipients can see the full To list.

## Shared Hyundai Wia newsletter design

`backend/template/newsletter.html` is the single table-based, inline-styled template used by sample generation, browser previews, HTML downloads and email rendering. `backend/mail/newsletter_email.html` is a symlink to that source. The palette is navy #00287a, red #c8102e, and footer #001a52, with a white HYUNDAI WIA masthead, centered WiaNews hero, numbered highlights, article sections and source buttons. Summaries remain justified and preserve line breaks. Browser/export use original image URLs; email preparation substitutes CID sources and retains original-image links. The HTML carries data-newsletter markers so email conversion can preserve the complete article data and safely re-render the same design. Legacy stored HTML remains readable by the converter.

### Subscription scoring
- After collection commits, `subscriptions/scoring.py` loads all articles linked to that sample and evaluates only rows for which `evaluation_complete` is false. Existing valid scores, Korean newsletter headlines and summaries are reused across samples/subscriptions.
- Uses shared `news/news_scoring.py`: technical 40%, organization 30%, impact 30%. Results, headline, summary, score version/time and evaluation request_id are stored in `articles`; `llm_requests.step` is `subscription_article_scoring`, with the triggering user and token usage. Preprocessing request IDs in collection runs and article links are preserved.
- Evaluation failure does not undo collection. Raw rows remain available; the next daily collection or a manual collection call retries incomplete evaluations, including older articles. Calling an already completed collection skips Exa/preprocessing and retries evaluation only. Scoring has a separate 360-second timeout. The scoring step itself does not create issues, editions or emails; scheduled publication handles these separately.

### Subscription members
`subscription_members` stores typed recipients with `member_id`, `subscription_id`, `member_type` (`internal` / `external`), `user_id`, `email_address`, and `created_at`. Internal members have only user_id; external members have only email_address. The database enforces exclusive identities and uniqueness per subscription. Legacy subscriptions.email_addresses is migrated and removed: an unambiguous existing account email maps to an internal member; other addresses remain external.
Subscription settings use a `members` array. Owners manage schedules and recipients; internal members can see the subscription, marketplace membership, and linked archive editions. Owners alone receive the full member list. External email entries do not grant account access. Counts use distinct resolved email addresses in active subscriptions. Internal addresses resolve from users at read time.

The shared recipient dialog has employee and other-email tabs in both subscription settings and archive mailing. Mail requests accept `recipients: [{member_type, user_id, email_address}]` (legacy user_ids requests remain supported). `mailing_list` and `results_json` store member_type, user_id, name and the actual email_address used at send time; external recipients have null user_id. Old mailing JSON is migrated without resending. Recipient identities govern retry protection, while SMTP addresses are deduplicated across internal and external entries.

### Scheduled subscription publication and mailing
- `subscriptions/publication.py` and a separate scheduler task evaluate daily/weekly/monthly schedules every 30 seconds. Eligible active subscriptions created by 08:00 KST are processed at/after 08:00 on the scheduled date. A late restart catches up on the same day; older missed publication dates are not automatically mailed. Month-end dates clamp to the last day of shorter months.
- Coverage ends yesterday, because 05:00 collection fetches yesterday. The first period starts at the later of configured start_date and subscription creation date (KST). Following periods start the day after the prior delivered coverage end (the previous publication date for normal 08:00 editions). This preserves inclusive publication-day boundaries without counting an unfinished current day.
- Require yesterday's shared collection to be complete and all stored period candidates to have valid evaluations. Take the top five candidates with total_score >=50 (score descending, then publication date descending and article ID). A subscription-specific index-only LLM call checks final relevance and redundancy; retained issues keep this score order. Then generate issue highlights via the shared summary prompt, tracked as subscription_newsletter_summary. Empty/low-quality periods do not send empty newsletters.
- Store selected subscripted_issues, a shared subscripted_newsletters edition, and last_issued_newsletter_id. One edition is reused for the same sample_id and coverage period; source subscriptions retain their individual delivery jobs. The service runs a single worker; per-edition async locks avoid duplicate generation and the DB unique coverage key prevents duplicate edition records.
- Each subscription resolves current internal users.email and external email_address immediately before sending. Inactive internal users are excluded. Send one MIME message with all distinct addresses in To; A10 and B20 produce two SMTP submissions. Existing inline image attachments and newsletter rendering are reused. Manual sending stays available.
- `mailing.subscription_id` links automatic delivery to its subscription; a unique subscription/edition index and durable request identity prevent duplicate submissions. Recipient snapshots, per-address results, and timestamps remain in mailing. At least one accepted recipient creates subscription_history; actual SMTP acceptance is not an inbox delivery guarantee.
- `subscription_publication_jobs` stores each subscription/date execution with a renewable-on-recovery attempt token and 15-minute stale lease. Generation has a 10-minute timeout. Failures before mail submission retry after an hour, up to three scheduled attempts on the same day. Once a mailing row is claimed, failures/unknown outcomes are marked for review rather than automatically resent. Review and errors are recorded; no external messages are sent for diagnostics.
- `WIANEWS_SUBSCRIPTION_PUBLICATION_ENABLED=0` disables publication/mailing separately from collection. Both schedulers require a running backend.

### 멤버별 수신 상태

- `subscription_members.status`: `active`(ON), `paused`(OFF). 기존 전체 일시정지 구독은 멤버 전원을 OFF로 이관하고 구독 자체는 활성 상태로 전환합니다.
- `PATCH /api/subscriptions/{id}/members/status`: `member_ids`와 `status`로 선택한 멤버의 수신 상태를 변경합니다. 관리자는 자기 구독의 멤버, 참여자는 본인만 변경할 수 있습니다.
- 내 구독 스위치는 본인의 수신 상태를 표시합니다. 관리자가 수신 멤버가 아닌 경우에는 ON 멤버 존재 여부를 표시합니다. 팝업에서 일시정지/재개 및 대상 멤버를 고릅니다.
- 멤버 편집 시 기존 ON/OFF 상태는 유지됩니다. OFF 멤버는 발송 직전 수신자 조회에서 제외되며, 재개 시 다음 발행부터 포함됩니다. 이미 메일 서버에 제출된 메일은 회수하지 않습니다.
- 구독 전체의 `status` 변경 API는 취소만 허용합니다. 모든 멤버가 OFF여도 구독/멤버를 삭제하지 않으며 수집은 유지됩니다.

### 전체 도메인 검색

- `sample_newsletters.search_all_domains`는 0(등록한 도메인 제한, 기본값) / 1(전체 검색)입니다. 샘플 조회·저장·복제와 구독 수집 설정에 함께 전달됩니다.
- AI 추천이 정상 완료됐지만 도메인이 0개면 팝업에서 전체 검색을 제안합니다. 사용자가 추가를 누르면 선택한 검색 쿼리와 전체 검색 여부를 저장합니다. 연결 오류는 빈 추천 결과와 구분합니다.
- 전체 검색에서는 Exa 요청의 `includeDomains`를 생략합니다. 수집 기간, URL 정규화, 내용·발행일 검증, 주제·중복 전처리 및 점수 평가는 유지합니다. 실제 수집 출처는 공용 `domains`에 저장하고 기사에 연결합니다.
- Step 1의 전체 검색 체크를 해제하면 기존 등록 도메인으로 다시 제한할 수 있습니다.
