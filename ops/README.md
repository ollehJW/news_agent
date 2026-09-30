# WiaNews 운영

- 접속 주소: https://dev-axforwork.wia.co.kr:9802
- 프론트엔드: 빌드된 React 파일을 HTTPS 9802 포트로 제공하고 `/api` 요청을 백엔드로 전달합니다. 스트리밍 응답도 그대로 전달합니다.
- 백엔드: `127.0.0.1:9801`. 외부에서는 프론트엔드의 HTTPS 주소로 API를 사용합니다.
- `wia` 사용자 systemd 서비스입니다. linger가 활성화되어 로그아웃 이후와 재부팅 후에도 실행됩니다. 프로세스 종료 시 5초 후 다시 시작합니다.

## 상태와 로그

```bash
systemctl --user status wianews-backend wianews-frontend
journalctl --user -u wianews-backend -u wianews-frontend -f
```

## 변경 반영

프로젝트 루트(`/home/wia/projects/wianews`)에서 실행합니다.

```bash
# 프론트엔드 변경
npm run build --prefix frontend
systemctl --user restart wianews-frontend

# 백엔드 코드 또는 .env 변경
systemctl --user restart wianews-backend
```

백엔드는 루트 `.env`를 읽습니다. 구독 스케줄러 중복 실행을 방지하기 위해 worker는 1개로 유지합니다. 서비스 실행 중 별도 개발용 백엔드를 동시에 실행하지 않습니다.

## 서비스 설정

`~/.config/systemd/user/wianews-*.service`는 이 폴더의 `systemd/` 설정 파일을 참조합니다. 설정 수정 후 적용합니다.

```bash
systemctl --user daemon-reload
systemctl --user restart wianews-backend wianews-frontend
```

## HTTPS 인증서

- 인증서: `/home/wia/.local/share/wianews/tls/fullchain.pem`
- 개인 키: `/home/wia/.local/share/wianews/tls/privkey.pem`
- 설치한 인증서 만료: 2027-01-23 23:59:59 UTC

인증서와 키는 Git에 저장하지 않습니다. 갱신한 파일로 교체하고 프론트엔드 서비스를 재시작합니다. 파일 권한은 600, 디렉터리는 700으로 유지합니다.

## 관리자 운영·토큰 대시보드

관리자 로그인 시 계정 관리, 운영 관리, 토큰 관리 메뉴를 제공합니다.
`/api/admin/operations`, `/api/admin/tokens`, `/api/admin/llm-pricing`은 관리자 권한을 검사합니다.
조회 기간은 한국 시간 기준 양 끝 날짜를 포함하며 최대 366일입니다.

- 운영 관리: 현재 계정·저장된 샘플·활성 구독·수신 멤버 수, 기간 내 샘플/수집/발행 작업 상태,
  수신자별 메일 결과, 사용자별 활동, 최근 오류 100건.
- 최근 로그인은 마지막 로그인 시각이며, 로그인 횟수나 접속 이력 통계가 아닙니다.
- 토큰 관리: 일별/사용자별/단계별/모델별 집계, 조건 필터, 호출 기록 50건 단위 조회.
- `llm_pricing`은 `(provider, model)`별 100만 토큰당 USD 입력/캐시 입력/출력 단가와 변경 시각을 저장합니다.
  실제 계약 단가를 관리자가 입력해야 합니다. 기본 단가는 없습니다.
- 비용은 저장된 현재 단가로 과거 조회 기간도 다시 계산하는 추정치입니다. 청구 이력이 아닙니다.
  입력에서 캐시 입력을 빼고 각각의 단가를 적용합니다. 캐시 기록이 없으면 일반 입력 단가를 적용합니다.
  단가 미설정 또는 입출력 토큰 누락 호출은 비용 합계에서 제외하고 제외 건수를 표시합니다.
- 호출 종료 기록은 성공을 보장하지 않습니다. 연결된 오류가 있으면 별도 표시합니다.
