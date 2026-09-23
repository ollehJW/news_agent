# WiaNews

기술 주제로 수집 출처를 추천하고 뉴스레터를 구성하는 서비스입니다.
도메인 추천은 Azure OpenAI와 연결되며, 실행·도메인·기사 선택·뉴스레터은 Python 백엔드와 SQLite에 저장합니다.
뉴스 수집과 점수화는 아직 서버의 예시 데이터로 진행하며, 뉴스레터 HTML은 서버 Jinja2 템플릿으로 생성합니다.

## 실행

기존 `.venv`를 사용합니다.

```bash
cd /home/wia/projects/wianews
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 6112
```

별도 터미널:

```bash
cd /home/wia/projects/wianews/frontend
npm install
npm run dev -- --port 6111 --strictPort
```

- 프론트엔드: http://localhost:6111
- 백엔드 API 문서: http://127.0.0.1:6112/docs
- Vite가 `/api` 요청을 `127.0.0.1:6112`로 전달하므로 외부 접속 시에도 프론트엔드의 6111 포트만 사용합니다.
- 운영 배포에서는 `/api`를 Python 서버로 전달하는 리버스 프록시를 설정해야 합니다.

## 환경변수

프로젝트 루트 `.env`의 `OPENAI_MODEL`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_API_VERSION`을 사용합니다. `.env.example`을 참고하세요.
현재 `.env`는 요청에 따라 `wiameet_dev/.env`의 LLM 설정 4개만 복사한 독립 파일이며 원본을 변경하지 않습니다.
프로세스 환경변수가 `.env`보다 우선합니다. 값 수정 시 백엔드를 재시작하세요.
`OPENAI_MODEL`은 Azure 배포 이름, `OPENAI_BASE_URL`은 기존 클라이언트와 같은 Azure endpoint입니다.
API 키는 프론트엔드에 전달하지 않으며 `.env`는 Git에서 제외합니다.

## 도메인 추천 API

`POST /api/domains/recommend/stream` (화면에서 사용하는 SSE 스트리밍)

기존 `POST /api/domains/recommend`는 전체 JSON 응답을 반환합니다.

```json
{"topic": "React 기반 프론트엔드 기술 동향"}
```

주제는 앞뒤 공백을 제거한 단일 문자열이며 1~120자입니다. 배열 입력은 허용하지 않습니다.

```json
{
  "domains": [{
    "host": "react.dev",
    "name": "React 공식 문서",
    "kind": "프로젝트 공식 사이트",
    "desc": "React 팀의 공식 문서와 블로그입니다.",
    "reason": "개발 팀이 릴리스와 API 변경 사항을 직접 발표합니다.",
    "relevance": "React 개발과 관련된 변경 사항을 살펴볼 수 있습니다."
  }],
  "source": "llm",
  "notice": "AI가 제안한 추천 후보입니다. 사이트의 현재 운영 상태와 신뢰성은 별도로 확인해 주세요."
}
```

- Azure OpenAI Chat Completions의 JSON 스키마 응답을 사용합니다. [OpenAI 공식 문서](https://developers.openai.com/api/docs/guides/structured-outputs)를 참고했습니다.
- `backend/integrations/llm_client.py`는 `wiameet_dev/backend/llm_client.py`의 환경변수 이름, Azure 연결 방식, 제한적 재시도 방식을 참고한 비동기 클라이언트입니다.
- 최대 20개 추천 후보를 반환합니다. 알려진 후보가 없으면 빈 배열입니다. 정적 추천 목록으로 대체하지 않습니다.
- 호스트 형식 검증, `www.` 정규화와 중복 제거를 수행합니다. 잘못된 모델 출력은 502로 반환합니다.
- **웹 검색·DNS 확인·사이트 접속은 수행하지 않습니다.** 추천 이유는 모델이 작성한 설명이며 실제 신뢰성 검증 결과가 아닙니다.
- 스트리밍은 `start` → `domain`(완성된 도메인마다) → `done` 이벤트를 전달합니다. 중간 실패는 `error` 이벤트입니다. 불완전한 JSON 조각은 표시하지 않습니다.
- 첫 단계에서 주제와 도메인 목록을 관리하고, 두 번째 단계에서 수집 기간을 설정합니다. AI 추천 팝업의 후보는 기본 전체 선택이며 선택한 후보만 첫 단계 목록에 추가합니다. 직접 추가·삭제는 목록 박스에서 처리합니다.
- 추천 중에도 체크박스를 변경할 수 있습니다. 전체 선택을 해제하면 이후 도착하는 후보도 해제 상태를 따릅니다. 취소하면 기존 목록은 바뀌지 않습니다. 이미 등록된 도메인은 중복 추가하지 않으며, 합계 20개를 초과하면 선택을 줄여야 추가할 수 있습니다.
- 중간 실패 시 받은 후보를 유지하며 처음부터 재시도하거나 부분 목록을 추가할 수 있습니다.
- 추천 후보(host·name)를 먼저 짧게 선정한 후, 도메인마다 개별 LLM 호출로 설명을 작성합니다. 동시에 최대 3개를 처리하고 완료된 출처부터 전달합니다. 공급자가 응답을 모아서 보내더라도 전체 20개 설명이 끝날 때까지 기다리지 않습니다.
- 한 번의 추천에 후보 선정 1회와 후보당 상세 설명 1회가 호출됩니다(최대 21회, 일시 오류 재시도 별도). 상세 설명 일부가 실패하면 성공한 목록을 유지하고 부분 실패를 표시합니다. 팝업을 닫으면 진행 중인 작업을 취소합니다.
- 운영 프록시에서는 SSE 응답 버퍼링을 비활성화해야 합니다(`X-Accel-Buffering: no`).
- 일시적인 연결 오류, 429, 5xx에 한 번만 재시도합니다. 전체 추천 처리 시간은 최대 125초입니다.
- 오류: 422 입력 오류, 429 사용량 제한, 502 제공자 연결/응답 오류, 503 설정 누락, 504 시간 초과.
- 로그에는 호출 시간·토큰 수·예외 종류만 남기며 키, 사용자 주제, 제공자의 원본 오류는 기록하지 않습니다.
- 로그인한 일반 사용자만 호출할 수 있으며, 추천 결과와 LLM 호출별 토큰 사용량을 실행 ID에 연결해 저장합니다.

## 검증

```bash
cd /home/wia/projects/wianews
.venv/bin/python -B -c "from backend.main import app; print(app.title)"
curl --fail http://127.0.0.1:6112/api/health
cd frontend
npm test
npm run build
```

백엔드는 모듈 로딩과 실행 중인 서버의 상태 응답을 확인합니다.

## 주요 코드

백엔드 폴더별 역할은 [backend/README.md](backend/README.md)를 참고하세요.

- `backend/main.py`: FastAPI 엔드포인트와 오류 응답
- `backend/recommendations/streaming.py`: 완성된 도메인을 SSE 이벤트로 전달
- `backend/recommendations/domain_generation.py`: 후보 선정과 최대 3개 동시 상세 생성
- `backend/recommendations/domains.py`: 입력/출력 모델, 추천 프롬프트, 호스트 검증
- `backend/integrations/llm_client.py`: Azure OpenAI 연결과 재시도
- `frontend/src/api.js`: 추천 API 호출
- `frontend/src/main.jsx`: 주제·도메인, 수집 기간과 뉴스레터 화면 흐름
- `frontend/src/DomainSetup.jsx`: 도메인 관리 박스, 추천 스트리밍, 체크박스 선택·추가

## 로그인 및 계정 관리

- 접속: `http://localhost:6111`
- 최초 관리자 사번: `admin`, 비밀번호: `admin123`
- 관리자는 **계정 관리**만 사용하며, 계정·팀을 추가할 수 있습니다.
- 추가한 모든 계정의 초기 비밀번호는 `wia1234!`입니다. 첫 로그인 후 비밀번호 변경을 완료해야 뉴스레터 또는 관리자 기능을 사용할 수 있습니다.
- 새 비밀번호는 영문·숫자·특수문자를 포함한 8~128자입니다.
- 일반 사용자는 뉴스레터 만들기·구독 관리·보관함을 사용합니다. 뉴스레터 보관함과 구독 관계·발행 설정은 서버 DB에 저장합니다. 로그인 전의 공용 저장 자료는 자동으로 다른 계정에 할당하지 않습니다.

### 데이터베이스

서버 시작 시 `backend/app.db`를 생성하고 기본 관리자, `미지정` 팀, 미지정/매니저/책임매니저 직급을 등록합니다. 관리자 여부는 users.is_admin으로 관리합니다. 서버를 다시 시작해도 기존 계정과 비밀번호를 덮어쓰지 않습니다. `WIANEWS_DB_PATH`로 DB 위치를 변경할 수 있습니다.

- `users`: `user_id` (UUID), `employee_id` (고유 사번), `password_hash`, `full_name`, `team_id`, `role_id` (직급), `is_admin` (관리자 여부), `email`, `must_change_password`, `is_active`, `created_at`, `updated_at`, `last_login_at`, `password_changed_at`
- `teams`: `team_id` (UUID), `name`, `created_at`
- `roles` (직급): `role_id` (UUID), `name`, `created_at`
- `sessions`: 해시 처리된 세션 토큰, 사용자 UUID, 생성 및 만료 시각
- `login_attempts`: 반복 로그인 실패 제한

`lost_login_at`은 최근 로그인 시각을 의미하는 `last_login_at`으로 정리했습니다. 비밀번호는 사용자별 무작위 솔트와 PBKDF2-SHA256(600,000회)으로 해시 처리하며 평문으로 저장하지 않습니다. DB 파일과 SQLite 보조 파일은 Git 제외 대상입니다.

### 인증 API

- `POST /api/auth/login`: `{ employee_id, password }`
- `GET /api/auth/me`: 현재 사용자
- `POST /api/auth/password`: `{ current_password, new_password }`
- `POST /api/auth/logout`: 세션 만료
- `GET /api/admin/users`, `POST /api/admin/users`: 관리자 전용 계정 조회·추가
- `GET /api/admin/options`, `POST /api/admin/teams`: 관리자 전용 팀·직급 목록 및 팀 추가

API 변경 요청에는 `X-WiaNews-Request: 1` 헤더가 필요합니다. 브라우저에는 HttpOnly/SameSite=Strict 쿠키만 전달하며, 세션은 8시간 후 만료됩니다. 비밀번호 변경 시 기존 세션을 전부 만료시키고 새 세션을 발급합니다. 뉴스 추천 API에도 로그인·비밀번호 변경 완료·일반 사용자 권한 검사를 적용했습니다. HTTPS 환경에서는 `WIANEWS_COOKIE_SECURE=1`로 실행합니다.

기존 권한용 roles(admin/member)는 자동 마이그레이션합니다. 관리자 여부는 is_admin에 보존하고, 기존 사용자의 직급은 미지정으로 설정합니다. 새 계정 생성 요청에서 role_id와 is_admin을 각각 지정하며, is_admin 기본값은 false입니다.

### 계정 생성 시 팀·직급 자동 등록

계정 추가 화면의 팀과 직급은 자동완성 입력창입니다. 기존 이름의 앞부분을 입력하면 추천하며, 새 이름은 계정 생성과 같은 트랜잭션에서 등록합니다. 띄어쓰기와 영문 대소문자 차이는 같은 이름으로 처리하여 기존 항목을 재사용합니다. 계정 생성에 실패하면 새 팀·직급도 저장하지 않습니다.

`POST /api/admin/users`는 `team_name`, `role_name`을 받습니다. 예: `{ "employee_id": "1001", "full_name": "홍길동", "team_name": "플랫폼팀", "role_name": "책임매니저", "is_admin": false }`. 기존 ID 방식도 지원하지만, 같은 항목에 이름과 ID를 동시에 보내면 거부합니다. 화면의 별도 팀 추가 영역은 제거했습니다.

팀·직급 자동완성은 앞글자 일치만 추천하며, 미지정 항목은 추천 선택지에서 제외합니다. 기존 계정의 미지정 참조는 유지합니다.

### 계정 목록 및 편집·삭제

계정 추가 폼은 항상 표시되며 초기화·등록 버튼을 제공합니다. 등록 성공 후 폼은 비워집니다. 계정 목록은 소속 팀 오름차순 → 대표이사/전무/상무/실장/팀장/책임매니저/책임연구원/매니저/연구원/사원/그 외 직급 → 이름 오름차순으로 표시합니다.

각 행의 편집 아이콘은 수정 팝업을 열며, `PUT /api/admin/users/{user_id}`에 등록과 같은 필드를 전달합니다. 비밀번호와 생성일은 유지합니다. 삭제 아이콘은 확인 팝업 이후 `DELETE /api/admin/users/{user_id}`를 호출합니다. 삭제 시 세션도 함께 삭제됩니다. 관리자 여부가 변경되면 해당 사용자의 기존 세션을 무효화합니다. 로그인 중인 본인의 계정 삭제 및 관리자 권한 해제는 차단합니다.

신규 계정의 사번은 숫자 1~7자리로 입력합니다. 앞자리 0을 유지하며, 기존 admin 로그인과 기존 계정 편집은 유지됩니다. 계정 추가 폼은 한 줄 배치로 제공하고 이름·직급의 짧은 표시 너비에 비해 이메일·소속 팀에 더 넓은 공간을 배분합니다.

관리 열의 열쇠 아이콘으로 비밀번호를 초기화할 수 있습니다. 확인 후 `POST /api/admin/users/{user_id}/reset-password`를 호출하며 `wia1234!`의 새 솔트 해시를 저장합니다. 기존 세션은 모두 만료되고 다음 로그인 시 비밀번호 변경이 필수입니다. 관리자 계정을 포함해 동일한 초기 비밀번호를 적용하며, 본인 계정을 초기화하면 즉시 로그아웃됩니다.


## 뉴스레터 실행 및 사용 기록

서버 시작 시 뉴스레터 관련 테이블을 생성합니다(`backend/newsletter_schema.sql`).

| 테이블 | 저장 내용 |
| --- | --- |
| errors | 사용자별 오류 ID·발생 단계·유형·메시지·LLM 호출 ID·시각 |
| domains | 공통 도메인 ID·호스트·생성 시점 |
| sample_domains | 샘플별 선택 도메인·추천 설명·추천 이유·관련성·LLM 호출 ID |
| sample_articles | 샘플별 수집 기사·본문·요약·대표 이미지 |
| sample_issues | 기사별 분석 호출·항목 점수·순위·중복 관계·최종 선택 |
| sample_newsletters | 샘플 주제·수집 기간·상태·HTML·생성/완성/저장 시각 |
| subscripted_newsletters | 샘플·수집 기간별 공유 발행본·이슈 목록·요약·HTML |
| llm_requests | 호출별 사용자·단계·모델·토큰·시간 |

- 모든 실행·보관함 API는 소유자를 검사합니다. 초기 비밀번호 변경 전 사용자와 관리자는 뉴스레터 API를 사용할 수 없습니다.
- 추천은 `sample_id`를 받아 기존 샘플에 연결하며, 생략하면 새 초안을 생성합니다. 추천 후보는 서명된 토큰으로 전달하고 선택한 출처만 sample_domains에 저장합니다.
- `/api/samples` 생성·조회, `/api/samples/{sample_id}` 상세 조회를 제공합니다. sources, period, selection은 PUT, collect, newsletter는 POST입니다. collect는 SSE 진행 이벤트와 최종 결과를 반환합니다. 수정 API는 현재 sample_id를 반환하며 완성본 수정 시 새 ID로 바뀝니다. 화면은 반환 ID를 다음 요청에 사용합니다.
- 진행 단계는 React 상태로 관리합니다. 서버에 current_step·updated_at·error_message 컬럼을 추가하지 않으며, newsletter_runs 및 단계 이동 API는 제거했습니다.
- `/api/newsletters`는 저장한 뉴스레터 목록이며, `/{newsletter_id}/save`는 POST, `/{newsletter_id}/download`는 GET입니다. 생성 당시 HTML은 이후 재수집해도 유지됩니다.
- `/api/llm-requests`에서 로그인한 사용자 본인의 호출 기록과 사용량 합계를 조회합니다. 공급자가 사용량을 보내지 않은 실패·취소 호출의 토큰은 NULL이며 추정하지 않습니다. 합계는 확인된 사용량만 더합니다.
- Exa `results[].image`는 `image_url`, `favicon`은 `favicon_url`에 대응합니다. `image_storage_path`는 향후 이미지 파일 저장용으로 준비했습니다. 현재 Exa 수집·이미지 다운로드는 구현하지 않았습니다.
- 샘플 수집은 Exa와 LLM을 사용하며 `data_mode=live`로 반환합니다. 주제·중복 통합 전처리와 스코어링 호출은 llm_requests에 기록됩니다.
- 기존 브라우저 보관함 데이터는 자동 이관하지 않습니다. 구독 추가·조회·수정·상태 변경은 DB에 연결되어 있으며 매일 구독 기사 수집은 연결되어 있으며, 구독 자동 발행·발송은 아직 연결하지 않았습니다.
- 기존 `roles.code`는 시작 시 제거하며 직급 ID와 사용자 연결, 비밀번호, 관리자 권한을 유지합니다.


## 구독 데이터베이스

다음 구독 테이블은 서버 시작 시 생성됩니다. 구독 화면은 DB 저장·조회 API를 사용합니다. 기존 localStorage 설정은 자동 이관하지 않습니다. 매일 수집은 구현되었고 자동 발행은 아직 연결하지 않았습니다.

- `subscripted_articles`: 샘플별 전처리 통과 기사 연결. `(sample_id, article_id)`로 중복을 방지하고 수집 실행·LLM 요청·추가 시각을 기록합니다. 원문 정보는 URL이 고유한 `articles`에 저장합니다.
- `subscriptions`: 샘플별 사용자 구독 관계. `subscription_id`, `sample_id`, `user_id`, `status`, `created_at`, `updated_at`을 저장합니다. `(sample_id, user_id)`는 유일하며 상태는 active/paused/cancelled입니다. 기존 newsletter_subscriptions의 구독 관계와 상태·시각을 이관하고 발행 설정 컬럼은 제거합니다.
- `subscripted_issues`: 사용자별 구독에서 자동 선정된 기사와 요약·점수·LLM 요청 참조.
- `subscripted_newsletters`: 샘플·수집 기간별 공유 발행본. `newsletter_id`, `sample_id`, `coverage_start_date`, `coverage_end_date`, `issue_ids`, `summary`, `request_id`, `html_content`, `created_at`, `published_at`을 저장합니다. issue_ids 배열 순서가 표시 순서이며, 샘플·커버 기간 조합은 고유합니다. summary는 이번 호 핵심 요약, request_id는 그 요약 생성 호출입니다. 아직 발행 전이면 published_at은 NULL입니다. JSON 내 이슈의 존재·중복·원문 기사의 해당 샘플 소속은 향후 발행 API에서 검증해야 합니다. 이슈의 subscription_id는 생성 출처를 나타내며, 발행본을 받는 구독은 subscription_history로 관리합니다. 요약 LLM 호출 단계는 `subscription_newsletter_summary`로 구분할 예정입니다.

기준 샘플의 주제는 `sample_newsletters.topic`, 도메인은 `sample_domains`를 사용합니다. 참조 중인 기준 뉴스레터는 삭제를 제한하여 누적 기사와 공동 발행 이력을 보호합니다. 계정 삭제가 구독·발행 참조를 훼손하는 경우 409 오류로 차단합니다.


### 샘플과 실제 발행 결과 분리

- `sample_newsletters`: 뉴스레터 만들기에서 생성한 샘플. 기존 `newsletters` 데이터의 ID, HTML, 소유자, 저장 시점은 유지하여 이관합니다.
- `subscripted_newsletters`: 실제 구독 발행 결과. 기존 `newsletters`와 `newsletter_publications`를 통합합니다. 샘플 생성은 이 테이블에 기록하지 않습니다.
- 발행본은 sample_id로 샘플을 참조합니다. `subscription_history`는 `subscription_id`, `newsletter_id`, `created_at`으로 구성하며 두 ID의 조합이 기본키입니다. 여러 구독이 동일 발행본에 연결될 수 있고, 이력이 있는 구독·발행본 삭제는 제한합니다. 이력의 구독과 발행본은 같은 sample_id인지 향후 API에서 검증해야 합니다.
- 기존 `/api/newsletters` 목록·저장·다운로드 경로는 호환성을 위해 유지하며 샘플 보관함만 반환합니다.
- 실제 발행 생성·조회 API는 아직 추가하지 않았습니다. 샘플 제작은 sample_id를 기준으로 하며, 기사와 이슈는 `sample_articles`, `sample_issues`에 저장합니다.

`domains`는 `domain_id`, `host`, `created_at`으로 구성합니다. 출처 표시는 `domains.host`를 사용합니다.


### 샘플별 도메인 저장

`sample_domains`의 컬럼은 `sample_id`, `domain_id`, `request_id`, `kind`, `description`, `recommendation_reason`, `topic_relevance`, `created_at`입니다. 기본키는 `(sample_id, domain_id)`이며 `kind`는 `recommended` 또는 `manual`입니다. `request_id`는 `llm_requests.request_id`를 참조합니다. 직접 추가와 호출을 특정할 수 없는 과거 추천은 NULL입니다.

작업 시작 시 `sample_newsletters.status='draft'`인 초안을 만들고 선택한 도메인만 연결합니다. 완성된 샘플은 같은 sample_id에서 `status='completed'`로 변경하며 당시 선택 도메인을 보존합니다. 보관함은 저장한 완성 샘플만 표시합니다. 선택하지 않은 추천 후보는 서버 DB에 저장하지 않습니다. 새 추천은 상세 생성의 최종 성공 호출 ID를 연결합니다.

기존 `run_domains`는 이관 후 제거합니다. 완료 샘플은 당시 스냅샷의 출처를, 초안은 해당 실행의 최종 선택 출처를 사용합니다. 동일 호스트는 대소문자·www·URL 경로를 정규화해 하나로 합치며 수동 중복 추가가 AI 추천 정보를 덮어쓰지 않습니다.


### LLM 요청 기록

`llm_requests`는 `request_id`, `user_id`, `step`, `provider`, `model`, `input_tokens`, `output_tokens`, `total_tokens`, `cached_input_tokens`, `started_at`, `completed_at`, `duration_ms`만 저장합니다. 모델은 호출한 Azure 배포 이름입니다. 도메인 후보 선정·상세 설명 단계는 `sample_domain_recommendation`으로 기록합니다.

기존 `ai_requests`의 요청 ID·모델·토큰·시간은 유지하고 사용자 ID는 기존 작업 소유자로 이관합니다. 재시도도 각각 독립 요청으로 저장합니다. 공급자 응답 ID·재시도 그룹·시도 번호·오류 상세는 제거합니다. 호출 조회는 사용자 단위이며 실행별 연결 및 호출 상태 이력은 저장하지 않습니다. 토큰을 받지 못한 호출은 NULL을 저장하며 사용량을 추정하지 않습니다.


### 샘플 기사와 이슈

- `sample_articles`: `article_id`, `sample_id`, `domain_id`, `url`, `title`, `published_at`, `content`, `summary`, `image_url`, `favicon_url`, `image_storage_path`, `collected_at`. 같은 샘플의 동일 URL은 한 기사로 저장합니다.
- `sample_issues`: `issue_id`, `sample_id`, `article_id`, `request_id`, `technical_score`, `organization_score`, `impact_score`, `recency_score`, `total_score`, `rank`, `is_selected`, `duplicate_of_issue_id`, `created_at`. 기사당 최종 분석 한 건을 저장합니다. 점수는 0~100 또는 NULL이며 중복 이슈의 순위는 NULL일 수 있습니다.
- 기사와 대표 이슈는 같은 샘플 소속이어야 합니다. 중복 이슈는 `duplicate_of_issue_id`로 대표를 참조하고 최종 선택할 수 없습니다. 화면에는 대표 이슈만 표시하며 상위 5개를 기본 선택합니다.
- 분석 호출은 `llm_requests.request_id`로 연결할 수 있습니다. 실제 LLM 중복 분석·점수화는 아직 구현하지 않았으며 현재 예시 결과의 request_id는 NULL입니다. 가상 데이터 여부는 기존 작업의 data_mode로 구분합니다.
- 초안 완성은 같은 sample_id를 유지합니다. 완성 후 재수집·설정·선택 변경 시 새 초안으로 분리하고 도메인·기사·이슈를 복사해 기존 샘플을 보존합니다.
- 이전 run_articles/run_issues는 이관 후 제거합니다. 기존 가상 기사에 반복된 홈페이지 URL은 하나로 병합합니다. 이관 전 원본 DB는 별도로 백업합니다. 과거 완성 샘플은 당시 스냅샷에 있는 기사를 기준으로 복원하며 저장된 HTML과 원래 스냅샷은 변경하지 않습니다.


### 사용 이력 테이블 제거

`usage_events`는 초기화 시 삭제하며 별도 이벤트 로그를 저장하지 않습니다. 선택된 도메인·기사·이슈와 완성 샘플, LLM 요청 기록은 각각의 테이블에 유지합니다.

추천 후보는 사용자·작업·설명·호출 ID를 포함한 서버 서명 토큰으로 전달합니다. 선택 시 서명과 사용자·작업을 검증한 후 `sample_domains`에 저장합니다. 유효기간은 2시간이며 서버 재시작 후에는 추천을 다시 받아야 합니다. 현재 서명 키는 단일 서버 프로세스 메모리에 있습니다.

실행별 전체 LLM 집계 API는 제거했습니다. `/api/llm-requests`에서 사용자 본인의 전체 호출과 확인된 토큰 합계를 조회합니다. `llm_requests` 컬럼은 추가하지 않았습니다.


### 구독 원본 기사

`subscripted_articles`는 `sample_id`, `article_id`, `request_id`, `run_id`, `collected_at`으로 구성합니다. 매일 오전 5시(KST)에 샘플별 공유 수집을 실행하며, 원문과 이미지 정보는 `articles`를 재사용합니다. 자세한 동작 및 수동 실행 API는 [backend/README.md](backend/README.md#daily-subscription-collection)를 참고하세요.

최근 7일 비교는 `collected_at`, 발행 커버 기간 후보 조회는 `published_at`을 기준으로 합니다. 두 날짜에 각각 sample_id와의 복합 인덱스를 제공합니다. 중복 판정 호출은 `llm_requests.request_id`를 참조하며 향후 step은 `subscription_article_deduplication`을 사용합니다. 과거 기사에는 대응하는 호출이 없어 request_id를 NULL로 이관합니다. 기존 canonical_url을 url로 사용하고 도메인은 해당 URL 호스트에서 연결합니다.

현재 변경은 DB 스키마와 이관까지이며 매일 수집·최근 7일 LLM 중복 판정은 아직 구현하지 않았습니다.


### 샘플 메타데이터 간소화

`sample_newsletters`는 `sample_id`, `user_id`, `topic`, `collection_start_date`, `collection_end_date`, `status`, `html_content`, `created_at`, `completed_at`, `saved_at`, `last_issued_newsletter_id`를 저장합니다. `last_issued_newsletter_id`는 이 샘플 기준 최신 실제 발행본의 `subscripted_newsletters.newsletter_id`를 참조하며, 발행 이력이 없으면 NULL입니다. 발행 기능 구현 시 발행 성공 트랜잭션에서 갱신합니다. 초안 HTML·완성 시각은 NULL이며 샘플 제작을 완료하면 같은 ID로 갱신합니다. 보관함 저장 여부는 saved_at으로 구분합니다.

기존 run_id·title·issue_count·snapshot_json·template_version·content_hash는 제거합니다. 선택 기사 수는 sample_issues에서 계산하고 출처는 sample_domains를 조회합니다. 제작 API와 도메인 추천·LLM 사용자 연결은 sample_id를 사용합니다. 완료된 샘플에 대한 생성 재요청은 같은 결과를 반환합니다.

완성 후 편집하면 새로운 sample_id의 초안을 생성하여 기존 구독 기준과 완성 HTML을 보존합니다. 기사 선택 변경 응답에는 새 기사·이슈 ID를 반환하며 프론트엔드도 이를 갱신합니다. 기존 DB 이관은 ID·HTML·작성자·저장 시각·관련 기사 및 구독 연결을 유지하고 이전 스냅샷에서 주제·수집 기간을 추출합니다.

### 구독 자동 선정 이슈

`subscripted_issues`는 자동 선정된 이슈만 저장합니다. 컬럼은 `issue_id`, `subscription_id`, `article_id`, `request_id`, `summary`, `technical_score`, `organization_score`, `impact_score`, `recency_score`, `total_score`, `created_at`입니다. 점수는 REAL 타입으로 0~100을 허용하며 NULL도 가능합니다. 사용자별 구독에 연결하고 원문 기사는 공유합니다. 동일 기사를 다른 발행에서 재선정할 수 있도록 기사 유일성 제약을 두지 않습니다. 연결된 구독·원문 삭제는 제한하고, LLM 요청 삭제 시 request_id만 NULL로 변경합니다. 발행본 연결 및 순서는 추후 뉴스레터의 issue_id 목록으로 관리합니다. 자동 선정 실행과 발행 기능은 아직 구현하지 않았습니다.

### 사용자별 오류 기록

`errors`의 컬럼은 `error_id`, `user_id`, `step`, `error_type`, `message`, `request_id`, `created_at`입니다. `/api/errors`는 로그인한 일반 사용자 본인의 오류만 반환합니다. 단계는 sample_domain_recommendation, sample_domain_selection, sample_period_setting, sample_article_collection, sample_issue_selection, sample_newsletter_generation, sample_newsletter_save, sample_newsletter_download 등으로 구분합니다. LLM 실패 시 해당 request_id를 연결하고 그 밖의 오류는 NULL입니다. 재시도 전 실패도 기록하고 정상 취소는 오류로 기록하지 않습니다. 공급자 응답 원문·프롬프트·인증 정보 대신 정제된 오류 메시지를 저장합니다. 기존 newsletter_runs의 error_message는 errors로 이관하고, 샘플이 없는 미완료 작업은 초안을 보존한 후 테이블을 제거합니다. 오류 조회 UI와 자동 구독 실행은 아직 구현하지 않았습니다.

### 구독 저장 API

- `GET /api/subscriptions`: 내 구독 목록(active/paused) 및 발행 설정·기준 샘플 정보.
- `POST /api/subscriptions`: sample_id와 settings(name, frequency, weekdays, month_day, start_date)를 받아 구독 관계와 설정을 한 트랜잭션으로 저장합니다. 마켓플레이스에서도 개인별 설정 팝업을 열어 저장합니다. settings를 생략한 API 요청은 주제 이름·매주 월요일·한국 시간 오늘의 기본값을 사용하며 다른 사용자의 설정을 복사하지 않습니다.
- `PUT /api/subscriptions/{subscription_id}/settings`: 본인의 구독 이름·발행 설정 수정. 구독의 sample_id는 변경하지 않습니다.
- `PATCH /api/subscriptions/{subscription_id}/status`: active/paused/cancelled 변경. `DELETE /api/subscriptions/{subscription_id}`는 cancelled로 변경하며 행을 삭제하지 않습니다.
- `GET /api/subscriptions/marketplace`: 구독 이력이 있는 완성 샘플의 주제·출처·활성 구독자 수·최초 등록 시각(registered_at)·첫 정식 발행 시각(first_published_at)·내 구독 상태. 카드의 발행 시작일은 첫 정식 발행 시각을 한국 날짜로 표시하며 발행본이 없으면 발행 전으로 표시합니다. 개인 구독 이름과 발행 설정은 노출하지 않습니다. 화면은 활성 구독자 수 기준 인기순이 기본이며 최초 등록 시각 기준 최신순을 선택할 수 있습니다. 수집 출처는 팝업에서 전체 목록을 확인합니다.

`subscription_settings`는 subscription_id(PK/FK), name, frequency, weekdays(JSON), month_day, start_date를 저장합니다. 발행 시각은 08:00 KST 고정입니다. 구독 생성은 소유한 저장 샘플 또는 이미 구독 이력이 있는 공개 샘플만 허용하고, 다른 사람의 비공개 샘플·초안은 거절합니다. 중복 구독 요청은 기존 행을 반환하며 cancelled 상태의 재구독은 기존 ID를 재사용합니다. 구독 추가만으로 기사·이슈·발행본·subscription_history·LLM 요청을 만들지 않습니다. 이 API에는 Exa 호출, 예약 실행, 메일 발송이 없습니다.

### 마켓플레이스 뉴스레터 미리보기

`GET /api/subscriptions/marketplace/{sample_id}/preview`는 구독 가능한 샘플만 조회합니다. sample_newsletters.last_issued_newsletter_id가 가리키는 동일 샘플의 실제 발행본(published_at이 있는 행)을 우선 반환하고, 없으면 초기 sample_newsletters.html_content를 반환합니다. 응답은 kind(sample/published), sample_id, newsletter_id, topic, html, published_at, dates를 포함하며 캐시하지 않습니다. 화면의 주제 아래 미리 보기 버튼은 서버 HTML을 sandbox iframe 팝업에 표시합니다. 미리보기는 수집·생성·구독 이력을 만들지 않습니다.

### 제작 전 유사 주제 확인

뉴스레터 만들기에서 **비슷한 뉴스레터 확인** 버튼을 누르면 `POST /api/subject-validations`에 topic을 보냅니다. 현재 active 구독자가 있는 완성 샘플의 주제들을 LLM으로 비교합니다. 비교 대상과 사용자 주제는 지시가 아닌 데이터로 전달하며, 응답 ID가 실제 후보인지 검증합니다. 75점 이상인 유사 주제 최대 5개를 추천하고 낮은 점수는 제외합니다. 비교할 후보가 없으면 LLM 호출 없이 완료합니다. 오류를 빈 추천으로 처리하지 않습니다.

- 유사 주제가 없으면 도메인 설정을 표시합니다. 입력 주제가 바뀌면 확인을 다시 해야 합니다.
- 유사 주제가 있으면 추천 이유와 구독자 수를 팝업에 표시합니다. 새로 만들기는 도메인 설정을 열고, 구독하러 가기는 기본 개인 설정(매주 월요일 08:00 KST, 오늘 시작)으로 구독한 후 내 구독 화면으로 이동합니다. 이미 구독 중이면 재생성하지 않고, 일시정지 상태면 재개합니다. 발행 설정은 내 구독에서 수정할 수 있습니다.
- `subject_validation`: validation_id, user_id, topic, request_id, candidates_json, matches_json, status(processing/completed/failed/cancelled), created_at, completed_at. 비교 대상 주제와 추천 점수·이유의 당시 결과를 보관합니다. request_id는 마지막 LLM 시도를 가리키며 재시도도 각각 llm_requests에 기록됩니다.
- LLM 호출 단계는 `sample_subject_validation`이며 모델·토큰·소요 시간을 llm_requests에 기록합니다. 실패는 errors에 연결하고 `GET /api/subject-validations`에서 본인의 실행 이력만 조회합니다.
- 이 과정은 Exa 수집이나 뉴스레터 발행을 실행하지 않습니다. 실행 전 후보가 없으면 request_id는 NULL입니다.

### 샘플 검색 쿼리

도메인 후보 선정 호출에서 주제에 맞는 영어 중심의 자연어 검색 쿼리 3~5개를 함께 생성합니다. 기본은 영어 4개와 한국어 1개이며, 좁은 주제는 영어 2~3개와 한국어 1개로 구성합니다. 추천 프롬프트는 영어로 작성하고 도메인 설명은 한국어로 출력합니다. 주제 범위에 따라 검색 관점을 분리하며, 검색 도메인·수집 기간은 쿼리에 넣지 않고 이후 검색 필터로 적용합니다.

- `sample_queries`: `query_id` (UUID), `sample_id`, `request_id`, `query`, `position` (1~5), `created_at`.
- `request_id`는 쿼리를 생성한 도메인 추천 LLM 호출을 참조합니다. 별도 LLM 호출은 추가하지 않습니다.
- 추천은 후보로만 전달합니다. 팝업에서 선택한 쿼리·도메인을 추가할 때 함께 저장하며, 취소·실패 시 기존 쿼리를 보존합니다. 직접 추가·삭제도 지원하고 공백·대소문자가 같은 쿼리는 통합합니다. 직접 추가한 쿼리의 request_id는 NULL입니다.
- SSE 응답은 LLM이 쿼리 문장을 완성할 때마다 `query` 이벤트로 미리 표시합니다. 전체 후보 응답 검증 후 `queries` 이벤트로 서명된 추천 후보를 제공하고, 기존 `domain` 이벤트를 이어서 전달합니다. 중단된 미완성 응답의 쿼리는 저장하지 않습니다. 일반 추천 API는 `queries` 문자열 배열과 서명된 `query_recommendations`를 반환하며, `GET /api/samples/{sample_id}`에서 ID를 포함한 저장 결과를 조회합니다.
- 완료된 샘플을 편집해 복제하면 쿼리도 새로운 `query_id`로 복제하고 원래 `request_id`를 유지합니다. Exa 검색 실행은 아직 연결하지 않습니다.


### 실제 샘플 뉴스 수집

`POST /api/samples/{sample_id}/collect`는 저장된 쿼리(최대 5개), 도메인, 수집 기간을 사용합니다. 날짜는 KST 시작일 00:00부터 종료일 다음 날 00:00 미만입니다. 쿼리당 최대 10건을 검색하고, URL 중복·출처 도메인·발행일·본문을 검사합니다. 발행일 누락/기간 밖, 허용 출처 밖, 본문 부족 결과는 제외하며 검색 조건을 임의로 확대하지 않습니다.

모듈 구성:
- `backend/integrations/exa_search.py`: 샘플·구독 공통 Exa 검색 및 기본 결과 검증.
- `backend/samples/sample_preprocessing.py`: 샘플용 주제 적합성·내용 중복을 전체 후보에 대해 한 번에 판단하고 keep_indices 정수 배열만 반환합니다. 구독용 과거 기사 비교는 별도 전처리 모듈로 추가할 예정입니다.
- `backend/news/news_scoring.py`: 샘플·구독 공통 중요도 계산 및 전처리 통과 기사만 한국어 요약 생성. 호출자가 llm_requests step을 전달합니다.
- `backend/news/news_analysis_common.py`: 공통 JSON 결과 ID 검증·동시 실행 제한.
- `backend/samples/sample_collection.py`: 샘플 설정 로딩, 진행 이벤트, 원본·이슈 저장, 상위 5개 기본 선택.

원본 본문·발행일·대표 이미지 URL·favicon은 sample_articles에, 전처리를 통과한 이슈의 점수와 선택 상태는 sample_issues에 저장합니다. 이미지 파일 다운로드는 수행하지 않으므로 image_storage_path는 NULL입니다. 주제·내용 중복으로 제외한 기사는 원본에만 남고 이슈로 선정하지 않습니다. 인덱스만 반환하므로 제외 사유별 개수나 새 중복 관계를 추정해서 저장하지 않습니다. 실패 시 기존 기사·이슈를 교체하지 않으며, 완료된 샘플의 재수집 결과는 새 초안으로 저장합니다.

스코어: 기술 35%, 기술 개발 주체 경쟁력 30%, 파급력 25%, 최신성 10%. 최신성은 수집 종료일 기준 발행 후 경과 일수로 0~1일 100, 2~3일 90, 4~7일 80, 8~14일 65, 15~30일 50, 이후 30점입니다. 총점 내림차순, 발행일 내림차순, URL 순으로 정렬하고 최대 5개를 기본 선택합니다. 사용자가 최종 선택을 변경할 수 있습니다.

환경변수: `EXA_API_KEY` 필수. 사내 CA 환경은 `EXA_CA_BUNDLE`에 인증서 번들을 지정할 수 있으며, 오래된 사내 CA 확장 호환이 필요할 때만 `EXA_LEGACY_CA=1`을 사용합니다. TLS 인증서/호스트 검증은 유지합니다. 검색은 동시 3개, LLM 전처리는 전체 후보 최대 50건을 1회 비교(기사당 본문 최대 6,000자, 전체 본문 최대 180,000자, 출력 한도 1,000토큰), 스코어링·요약은 8기사씩 동시 3개, 전체 수집 제한은 360초입니다. 스트림은 10초마다 heartbeat를 보내고 브라우저 연결 종료 시 남은 작업을 취소합니다.
