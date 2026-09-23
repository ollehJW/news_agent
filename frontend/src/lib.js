export function normalizeDomain(value) {
  const raw = value.trim();
  if (!raw || /\s/.test(raw)) throw new Error('올바른 도메인을 입력해 주세요. 예: engineering.example.com');
  let url;
  try { url = new URL(raw.includes('://') ? raw : `https://${raw}`); } catch { throw new Error('올바른 도메인을 입력해 주세요.'); }
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.port || !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/i.test(url.hostname)) throw new Error('공개 웹사이트의 도메인을 입력해 주세요.');
  return url.hostname.toLowerCase().replace(/^www\./, '');
}
export function dateString(date) { return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(date); }
export function initialDates() { const end = new Date(); const start = new Date(end); start.setDate(start.getDate()-6); return { start: dateString(start), end: dateString(end) }; }
const topics = [
  ['새로운 기능 공개와 개발 워크플로의 변화', '기능 확장과 사용 방식의 변화를 살펴보는 예시 이슈입니다.', '기존 도구와의 차이를 이해하고 도입 우선순위를 판단할 수 있습니다.', '작은 검증 프로젝트에서 품질과 비용을 비교해 보세요.'],
  ['성능 최적화: 실무 적용을 위한 핵심 포인트', '실행 효율과 자원 사용량 개선을 다루는 예시 이슈입니다.', '성능 개선은 운영 비용과 사용자 경험에 직접 연결됩니다.', '현재 서비스의 병목을 측정하고 동일 조건에서 성능을 비교하세요.'],
  ['오픈소스 생태계에서 주목할 기술', '공개 도구와 개발 생태계의 확장을 보여주는 예시 이슈입니다.', '기술 선택의 폭과 유지보수 전략에 영향을 줍니다.', '라이선스, 커뮤니티 활동과 기존 시스템의 호환성을 확인하세요.'],
  ['프로덕션 운영을 위한 안정성 가이드', '배포·모니터링·오류 대응을 다루는 예시 이슈입니다.', '실험에서 서비스 운영으로 넘어갈 때 필요한 조건입니다.', '관측 지표와 롤백 절차를 정리하고 장애 시나리오를 점검하세요.'],
  ['보안과 거버넌스, 도입 전에 살펴볼 변화', '접근 제어와 데이터 관리에 관한 예시 이슈입니다.', '확대 적용 전에 운영 정책과 데이터 경계를 검토해야 합니다.', '데이터 흐름과 접근 권한을 문서화하고 내부 검토를 진행하세요.'],
  ['개발 경험을 개선하는 도구 활용 사례', '반복 작업을 줄이는 개발 도구의 예시 이슈입니다.', '팀의 개발 생산성을 검토하는 참고 자료가 됩니다.', '반복 작업 한 가지를 선정해 도입 전후 시간을 비교하세요.'],
];
export function collectDemo(topic, domains, dates) {
  return topics.flatMap((t,i) => {
    const source = domains[i % domains.length];
    const item = { id: `issue-${i}`, issue: `topic-${i}`, title: `${topic} · ${t[0]}`, summary: t[1], why: t[2], tag: topic, source: source.name, host: source.host, url: `https://${source.host}/`, date: dates.end, scores: [96-i*4, 94-i*3, 92-i*4, 95-i*2] };
    return i < 3 ? [item, { ...item, id: `${item.id}-duplicate` }] : [item];
  });
}
export function rankAllNews(items) {
  return [...new Map(items.map(n => [n.issue,n])).values()].map(n => ({...n, score: Math.round((n.scores[0]*40+n.scores[1]*30+n.scores[2]*30)/100), duplicates: items.filter(x=>x.issue===n.issue).length-1 })).sort((a,b)=>b.score-a.score);
}
export function rankNews(items) { return rankAllNews(items).filter(n=>n.score>=70).slice(0,5); }
export function escapeHTML(value) { return String(value).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
