# WiaNews

기술 주제로 수집 출처를 추천하고 뉴스레터를 구성하는 서비스입니다.
도메인 추천은 Azure OpenAI와 연결되며, 실행·도메인·기사 선택·뉴스레터·사용 이력은 Python 백엔드와 SQLite에 저장합니다.
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
- `backend/llm_client.py`는 `wiameet_dev/backend/llm_client.py`의 환경변수 이름, Azure 연결 방식, 제한적 재시도 방식을 참고한 비동기 클라이언트입니다.
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
.venv/bin/python -m unittest discover -s backend -p 'test_*.py' -v
cd frontend
npm test
npm run build
```

백엔드 테스트는 실제 LLM 호출 없이 입력·도메인 검증, JSON 파싱, 중복 제거, 재시도와 오류 응답을 검증합니다.

## 주요 코드

- `backend/main.py`: FastAPI 엔드포인트와 오류 응답
- `backend/streaming.py`: 완성된 도메인을 SSE 이벤트로 전달
- `backend/domain_generation.py`: 후보 선정과 최대 3개 동시 상세 생성
- `backend/domains.py`: 입력/출력 모델, 추천 프롬프트, 호스트 검증
- `backend/llm_client.py`: Azure OpenAI 연결과 재시도
- `frontend/src/api.js`: 추천 API 호출
- `frontend/src/main.jsx`: 주제·도메인, 수집 기간과 뉴스레터 화면 흐름
- `frontend/src/DomainSetup.jsx`: 도메인 관리 박스, 추천 스트리밍, 체크박스 선택·추가

## 로그인 및 계정 관리

- 접속: `http://localhost:6111`
- 최초 관리자 사번: `admin`, 비밀번호: `admin123`
- 관리자는 **계정 관리**만 사용하며, 계정·팀을 추가할 수 있습니다.
- 추가한 모든 계정의 초기 비밀번호는 `wia1234!`입니다. 첫 로그인 후 비밀번호 변경을 완료해야 뉴스레터 또는 관리자 기능을 사용할 수 있습니다.
- 새 비밀번호는 영문·숫자·특수문자를 포함한 8~128자입니다.
- 일반 사용자는 뉴스레터 만들기·구독 관리·보관함을 사용합니다. 뉴스레터 보관함은 서버 DB에 저장하고 구독 설정은 사용자 UUID별 브라우저 키로 분리했습니다. 로그인 전의 공용 저장 자료는 자동으로 다른 계정에 할당하지 않습니다.

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

서버 시작 시 다음 8개 테이블을 생성합니다(`backend/newsletter_schema.sql`).

| 테이블 | 저장 내용 |
| --- | --- |
| newsletter_runs | 사용자별 주제, 수집 기간, 진행 단계와 상태 |
| domains | 공통 도메인 ID·호스트·출처 이름·생성/수정 시점 |
| run_domains | 추천 회차별 출처 분류·설명·추천 이유·주제 관련성, 선택 여부, 직접 추가 여부 |
| run_articles | 원문 기사, 발행일, 요약, 대표 이미지 URL·파비콘 URL·이미지 저장 경로 |
| run_issues | 중복 통합 이슈, 평가 항목별 점수, 순위, 초기·최종 선택 여부 |
| newsletters | 생성 HTML과 당시 데이터 스냅샷, 보관함 저장 시점 |
| usage_events | 도메인 변경, 수집, 기사 선택, 생성·저장·다운로드 요청 기록 |
| ai_requests | run_id별 LLM 호출·재시도·실패·취소, 실제 응답 토큰 사용량 |

- 모든 실행·보관함 API는 소유자를 검사합니다. 초기 비밀번호 변경 전 사용자와 관리자는 뉴스레터 API를 사용할 수 없습니다.
- 추천은 `run_id`를 받아 기존 실행에 연결하며, 생략하면 새 실행을 생성합니다. 스트리밍 후보는 하나씩 DB에 저장한 후 전달합니다. 선택하지 않은 추천 정보도 남습니다.
- `/api/runs` 생성·조회, `/api/runs/{run_id}` 상세 조회를 제공합니다. `sources`, `period`, `selection`은 PUT, `collect-demo`, `newsletter`, `step`은 POST입니다.
- `/api/newsletters`는 저장한 뉴스레터 목록이며, `/{newsletter_id}/save`는 POST, `/{newsletter_id}/download`는 GET입니다. 생성 당시 HTML은 이후 재수집해도 유지됩니다.
- `/api/runs/{run_id}/usage`에서 호출 기록과 사용량 합계를 조회합니다. 공급자가 사용량을 보내지 않은 실패·취소 호출의 토큰은 NULL이며 추정하지 않습니다. 합계는 확인된 사용량만 더합니다.
- Exa `results[].image`는 `image_url`, `favicon`은 `favicon_url`에 대응합니다. `image_storage_path`는 향후 이미지 파일 저장용으로 준비했습니다. 현재 Exa 수집·이미지 다운로드는 구현하지 않았습니다.
- 예시 수집은 `data_mode=demo`로 구분하며 LLM 토큰 사용량을 생성하지 않습니다.
- 기존 브라우저 보관함 데이터는 자동 이관하지 않습니다. 구독 관리는 프론트엔드 설정 기능이며 자동 실행·발송 백엔드는 아직 없습니다.
- 기존 `roles.code`는 시작 시 제거하며 직급 ID와 사용자 연결, 비밀번호, 관리자 권한을 유지합니다.
