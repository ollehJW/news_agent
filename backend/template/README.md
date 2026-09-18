# 뉴스레터 템플릿

`newsletter.html`은 현재 프론트엔드 뉴스레터를 옮긴 Jinja2 형식의 HTML 템플릿입니다. WiaNews SVG 로고와 스타일을 포함하므로 별도 이미지·CSS 파일이 필요하지 않습니다.

## 입력 데이터

- `title`: HTML 문서 제목. 수집 주제를 사용합니다.
- `topic`: 헤더에 표시할 수집 주제
- `dates.start`, `dates.end`: 수집 기간 (`YYYY-MM-DD`)
- `issues`: 사용자가 최종 선택한 기사 목록, 표시할 순서대로 전달
  - `title`, `tag`, `summary`: 기사 제목, 주제, 요약
  - `source`, `url`, `date`: 출처 이름, 링크, 발행일
  - `imageUrl`: 대표 이미지 URL (선택, 없으면 이미지 영역 생략)
  - `imageAlt`: 이미지 대체 텍스트 (선택, 없으면 기사 제목 사용)

백엔드에서 렌더링할 때 HTML 자동 이스케이프를 활성화하고, 출처 및 이미지 URL은 HTTP/HTTPS 주소인지 검증해 전달합니다. 수집 결과의 `image` 필드는 `imageUrl`로 매핑합니다.

`POST /api/samples/{sample_id}/newsletter`에서 이 템플릿을 렌더링하고 샘플 HTML을 `sample_newsletters`에 저장합니다. 도메인·기사·선정 결과는 각 샘플별 테이블에 저장합니다. 프론트엔드 미리보기 및 다운로드는 서버가 생성한 HTML을 사용합니다. 뉴스 수집과 핵심 요약 문장은 현재 예시 데이터입니다.
