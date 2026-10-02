# PostgreSQL 및 통합 로그인

계정·팀·역할·세션은 `platform` 스키마를 함께 사용합니다. 업무 데이터만 `wianews` 스키마에 저장합니다.
로그인은 AX for Works `/login`에서만 제공하며, 미인증 방문자는 로그인 후 요청했던 서비스 경로로 돌아옵니다.
공통 쿠키는 Secure/HttpOnly/SameSite=Strict, Path=/ 이며 로그아웃·관리자 비밀번호 초기화는 모든 서비스 세션에 반영됩니다.
세 서비스는 같은 HTTPS 호스트에서 제공해야 합니다. 기존 서비스별 로그인 쿠키는 사용하지 않습니다.

## 운영 환경 설정

`config.example.yaml`을 `config.yaml`로 복사하고 PostgreSQL host/port/name/user와 비밀번호를 설정합니다.
`password_env`에 환경변수 이름을 지정하거나, 이 키를 삭제하고 `password`에 직접 입력할 수 있습니다.
비밀번호를 입력한 파일은 Git에 넣지 말고 `chmod 600 config.yaml`로 보호하세요.
현재 서버는 사용자 systemd drop-in의 EnvironmentFile로 플랫폼 `.env`에서 비밀번호만 참조합니다.
운영 서버는 해당 서비스만의 환경파일을 사용해도 됩니다. 설정 파일 경로는 `AX_wianews_CONFIG`로 변경 가능합니다.
스키마 이름은 고정입니다. `auth.platform_origin`은 통합 로그인 서버 HTTPS origin으로 설정하세요.
운영 원격 DB는 인증서 설정에 맞춰 `sslmode: verify-full`을 사용하세요.
설정 변경 후 backend를 재시작합니다. SQLite로 자동 대체하지 않으며 DB 연결 실패 시 오류를 반환합니다.

## 최초 이관

1. 플랫폼 계정을 먼저 준비합니다. 원본 계정의 사번과 user_id가 platform과 일치해야 합니다.
2. SQLite를 사용하는 backend/예약 작업을 중지하고 app.db를 백업합니다. WAL이 있으면 SQLite backup API를 사용하세요.
3. 프로젝트 루트에서 실행합니다(서비스 Python 가상환경 사용).

```bash
python -m backend.migrate_postgres --source backend/app.db --config config.yaml --dry-run
python -m backend.migrate_postgres --source backend/app.db --config config.yaml
```

시험 실행은 모든 변경을 롤백합니다. 실제 실행은 한 트랜잭션에서 테이블·인덱스·뷰·외래키를 생성하고
전체 행의 모든 값을 비교한 뒤 커밋합니다. 대상 업무 테이블에 데이터가 있으면 덮어쓰지 않고 중단합니다.
`users`, `teams`, `roles`, `sessions`, `login_attempts`는 복사하지 않습니다.
이전 rowid로 정렬/페이지 조회하던 데이터는 `entry_seq` identity 열로 순서를 보존합니다.
서비스 부팅 시 과거 SQLite 마이그레이션은 실행하지 않습니다.

## 백업과 복구

이전 app.db와 전환 전 소스는 백업으로 유지합니다. PostgreSQL 전환 뒤 새로 저장한 데이터가 있으므로
단순히 SQLite 버전으로 되돌리지 마세요. 복구 시 쓰기 작업을 중단하고 최신 PostgreSQL 데이터를 먼저 보관해야 합니다.
기존 SQLite 테스트/마이그레이션은 과거 버전 자료이며 현재 환경에서 실행하지 않습니다.
