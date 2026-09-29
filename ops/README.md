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
