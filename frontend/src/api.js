import { normalizeDomain } from './lib.js';

function parseDomain(domain) {
  if (!domain || !['host', 'name', 'kind', 'desc', 'reason', 'relevance'].every(key => typeof domain[key] === 'string' && domain[key].trim())) {
    throw new Error('추천 결과의 형식이 올바르지 않습니다. 다시 시도해 주세요.');
  }
  return { ...domain, host: normalizeDomain(domain.host), mark: domain.name.slice(0, 2) };
}

export async function streamRecommendedDomains(topic, signal, onDomain, sampleId, onQuery=()=>{}, onQueries=()=>{}) {
  const response = await fetch('/api/domains/recommend/stream', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-WiaNews-Request': '1' },
    body: JSON.stringify({ topic, sample_id: sampleId }), signal,
  });
  if (!response.ok || !response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
    if (response.status === 401 && typeof window !== 'undefined') window.dispatchEvent(new Event('wianews-session-expired'));
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === 'string' ? data.detail : '도메인 추천에 실패했습니다. 서버 연결을 확인해 주세요.');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let complete = false;
  const seen = new Set();
  function processEvent(block) {
    const lines = block.split('\n');
    const type = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
    const raw = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!raw) return;
    const data = JSON.parse(raw);
    if (type === 'error') throw new Error(data.message || '추천이 중단되었습니다. 다시 시도해 주세요.');
    if (type === 'done') { complete = true; return; }
    if (type === 'query') {
      if(typeof data.query !== 'string' || !data.query.trim())throw new Error('검색 쿼리 형식이 올바르지 않습니다.');
      onQuery(data); return;
    }
    if (type === 'queries') {
      if(!Array.isArray(data.queries)||data.queries.length>5||data.queries.some(q=>typeof q.query !== 'string'))throw new Error('검색 쿼리 형식이 올바르지 않습니다.');
      onQueries(data.queries); return;
    }
    if (type === 'domain') {
      const domain = parseDomain(data);
      if (seen.has(domain.host)) return;
      if (seen.size >= 20) throw new Error('추천 개수가 한도를 초과했습니다.');
      seen.add(domain.host);
      onDomain(domain);
    }
  }
  try {
    while (!complete) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value, {stream: !done});
      let index;
      while ((index = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        processEvent(block);
        if (complete) break;
      }
      if (buffer.length > 200000) throw new Error('추천 응답이 너무 큽니다.');
      if (done) break;
    }
    if (!complete) throw new Error('연결이 끊어졌습니다. 받은 목록을 사용하거나 다시 추천받을 수 있어요.');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
