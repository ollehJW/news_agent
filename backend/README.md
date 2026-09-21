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

구독 버전도 수집·스코어링 모듈을 공유하며, 과거 기사와의 중복 비교 등은 향후 구독 전처리 모듈로 추가합니다.

`core/paths.py`에서 프로젝트·백엔드 기준 경로를 관리합니다. `.env`는 프로젝트 루트, DB·SQL 스키마·템플릿은 기존 backend 경로를 사용합니다.

`migrations/`는 서버 시작 시 DB 초기화에서 참조하므로 현재 DB에서 변환 작업이 없더라도 임의로 삭제하지 않습니다. 샘플 복제 등 현재 실행 기능과 결합된 일부 마이그레이션 함수는 `samples/`와 `core/`에 남아 있습니다.

### 공통 기사와 레터 연결

- `articles`: 정규화 URL을 UNIQUE 키로 기사 정보, highlights, 요약, 점수 4종을 한 번 저장합니다. `request_id`는 평가 LLM 호출입니다. `score_version`, `scored_at`는 평가 버전과 평가 시간을 기록합니다.
- `sample_articles(sample_id, article_id, request_id)`: 전처리를 통과한 기사 연결입니다. `request_id`는 해당 수집의 주제·중복 전처리 호출입니다.
- `subscripted_articles(subscription_id, article_id, request_id)`: 구독별 전처리 통과 기사 연결입니다. 동일 기사에 여러 구독을 연결할 수 있습니다.
- `sample_issues`, `subscripted_issues`: 레터에 선택한 기사와 `rank`만 관리하며 점수는 기사에서 읽습니다. 샘플의 기본 선택은 상위 5개입니다.
- URL이 같고 평가 버전·기본 점수 3종·요약이 유효하면 평가 LLM을 생략합니다. 주제는 평가 입력에서 제외하며 주제 적합성·중복 전처리는 수집마다 실행합니다. 전처리 탈락 기사는 이번 샘플에 연결하지 않습니다.
- 총점은 기술적 중요성 40%, 기술 주체 경쟁력 30%, 파급력 30%를 합산해 정수로 반올림합니다. 최신성은 점수에 포함하지 않습니다.
- 동일 URL의 동시 평가를 프로세스 내 잠금으로 합칩니다. DB URL UNIQUE 제약은 여러 프로세스에서도 기사 행 중복을 막습니다. 여러 워커를 운영할 경우 평가 호출 자체의 중복까지 막으려면 분산 잠금이 추가로 필요합니다.
- 완성된 샘플을 복사해도 기사 ID는 재사용하고 연결·선택 행만 복사합니다. 선택 API는 순서가 있는 `article_ids` 배열을 받습니다.
- 기존 전처리 호출을 정확히 역추적할 수 없는 샘플 연결의 `request_id`는 NULL로 이전합니다. 기존 평가 요청은 `articles.request_id`로 보존합니다.
- 구독 자동 수집·선정 실행은 아직 구현하지 않았으며 공통 평가 함수와 저장 구조를 재사용할 수 있습니다.

### 샘플 결과와 실행 이력

- `sample_newsletters`: `sample_id`, `html_content`, `total_summary`, 요약 LLM `request_id`, `created_at`, `saved_at`, `last_issued_newsletter_id`를 저장합니다.
- `sample_runs`: `run_id`, `sample_id`, `user_id`, `topic`, `collection_start_date`, `collection_end_date`, `current_step`, `status`, `started_at`, `completed_at`를 저장합니다.
- 단계는 `topic_setup` → `source_setup` → `period_setup` → `news_collection` → `news_preprocessing` → `news_scoring` → `news_selection` → `newsletter_completed`입니다. 상태는 draft/running/completed/failed/cancelled입니다.
- 동일 샘플을 재수집하면 새 실행 ID를 만듭니다. 수집 후 설정을 수정할 때도 기존 실행 설정을 보존하고 새 실행으로 전환합니다. 완성된 샘플을 수정하면 새 샘플과 실행을 생성합니다.
- `sample_details` 뷰는 샘플 결과와 최신 실행을 합쳐 기존 API·구독 화면의 응답 형식을 유지합니다. `/api/sample-runs`는 로그인한 사용자의 실행 이력을 반환합니다.
- 과거 데이터는 샘플별로 보존된 메타데이터와 현재 상태에서 추정한 단계로 실행 1건을 이전합니다. 과거 재시도·단계별 시각을 복원한 기록은 아닙니다. 오류 상세는 기존 `errors`에 기록합니다.

- 뉴스레터 생성 시 선택된 N개 기사의 제목·요약을 한 번의 LLM 요청(`sample_newsletter_summary`)에 전달해 기사 전체의 흐름을 종합한 최대 3개 핵심 하이라이트를 생성합니다. `total_summary`는 각 줄이 `- `로 시작하는 문자열이며 호출 ID와 함께 저장합니다. 생성 단계는 `newsletter_summary`이며, 설정·선택 변경 충돌 시 결과를 저장하지 않습니다.

## Newsletter email

`POST /api/newsletter-email` accepts `request_id`, `kind` (`sample` or `subscription`), `newsletter_id`, and `user_ids` (up to 100). It loads authorized HTML and recipient addresses from the database, sends separate HTML MIME messages through Gmail SMTP SSL (465), and records results in `mailing`. Repeating a request ID returns its stored results without resending. `sent` means SMTP acceptance, not guaranteed inbox delivery; `unknown` is not automatically retried.

Set `GMAIL_USER` and `GMAIL_APP_PASSWORD` in the ignored root `.env`. The normal account password is not used. `GMAIL_CA_BUNDLE` and `GMAIL_LEGACY_CA=1` support an already trusted legacy corporate CA while keeping certificate/hostname verification enabled. SMTP network access is required.

On this network, Gmail disconnects after EHLO. Delivery therefore uses the existing AI Lounge handshake: TLS-verified SMTP SSL 465, HELO, then AUTH PLAIN inside TLS. Credentials and authentication payloads must never be logged.

### Mailing history

`mailing` stores one row per send request: UUID `mailing_id`, requesting `user_id`, idempotency `request_id`, `kind`, `newsletter_id` (sample_id when kind=sample), subject, sender_email, mailing_list (JSON user/name/email snapshots), results_json (per-recipient status/email/sent_at/completed_at), status, created_at, sent_at (latest known SMTP acceptance), completed_at. Timestamps use UTC. A completed request can contain failed or unknown recipients; inspect results_json. GET /api/newsletter-email/history returns only the current user's latest 200 requests. Legacy rows are migrated atomically; unavailable historical addresses/acceptance times remain NULL.

### Article images and email CID

Article images are downloaded after shared scoring and saved as validated, resized JPEGs under `backend/workspace/{article_id}/image-{url_hash}.jpg`. `articles.image_storage_path` is relative to backend/. Workspace files are ignored by Git and must be backed up with app.db. Downloads check public hosts and redirects, bound size, and retain TLS verification. Mail preparation retries missing files, reuses local images across recipients, and sends multipart/related CID inline attachments (up to 10 MiB of image data per newsletter). Unavailable images are omitted from email; original HTML and image links remain unchanged. Existing caches survive startup migrations.
