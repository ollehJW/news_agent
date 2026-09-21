import React, { useEffect, useRef, useState } from 'react';
import { Plus, X, Sparkles, Globe2, ShieldCheck, ExternalLink, Loader2, RotateCcw, Check, Search } from 'lucide-react';
import { normalizeDomain } from './lib';
import { streamRecommendedDomains } from './api';

const LIMIT = 20;
const queryKey=q=>q.trim().replace(/\s+/g,' ').toLocaleLowerCase();

export function DomainBox({ queries=[], domains, onQueriesChange, onChange, onRecommend, disabled=false }) {
  const [input, setInput] = useState('');
  const [queryInput,setQueryInput]=useState('');
  const [queryError,setQueryError]=useState('');
  async function updateQueries(items){try{await onQueriesChange(items);setQueryError('');return true;}catch(err){setQueryError(err.message);return false;}}
  async function addQuery(e){e.preventDefault();const query=queryInput.trim().replace(/\s+/g,' ');if(!query)return;if(queries.some(q=>queryKey(q.query)===queryKey(query))){setQueryInput('');return;}if(queries.length>=5){setQueryError('검색 쿼리는 최대 5개까지 추가할 수 있어요.');return;}if(await updateQueries([...queries,{query}]))setQueryInput('');}
  const [error, setError] = useState('');
  function add(event) {
    event.preventDefault();
    try {
      const host = normalizeDomain(input);
      if (domains.some(d => normalizeDomain(d.host) === host)) { setInput(''); setError(''); return; }
      if (domains.length >= LIMIT) throw new Error('도메인은 최대 20개까지 추가할 수 있어요.');
      onChange([...domains, { host, name: host, mark: host[0].toUpperCase(), kind: 'manual', custom: true,
        desc: '사용자가 등록한 수집 출처', reason: '운영 주체와 출처 공개 여부를 직접 확인해 주세요.' }]);
      setInput(''); setError('');
    } catch (err) { setError(err.message); }
  }
  return <section className="panel source-panel" aria-labelledby="source-panel-title">
    <div className="section-title">
      <div className="section-label"><span className="tile-icon"><Globe2 size={20}/></span><div><h2 id="source-panel-title">수집할 쿼리 및 도메인</h2><p>검색 쿼리와 뉴스를 모을 출처를 관리하세요.</p></div></div>
      <button className="button primary" disabled={disabled} onClick={onRecommend}><Sparkles size={15}/>AI 추천 받기</button>
    </div>
    <div className="collection-settings-grid">
    <section className="collection-query-section" aria-labelledby="collection-query-title"><h3 id="collection-query-title"><Search size={16}/>수집할 쿼리 <span className="count">{queries.length}</span></h3>
      {queries.length?<ol className="collection-query-list">{queries.map((q,i)=><li key={q.query_id||i}><span>{String(i+1).padStart(2,'0')}</span><p>{q.query}</p><button className="icon-button" disabled={disabled} aria-label={`${q.query} 쿼리 삭제`} onClick={()=>updateQueries(queries.filter((_,index)=>index!==i))}><X size={15}/></button></li>)}</ol>:<div className="source-empty"><Search size={27}/><h3>아직 추가한 쿼리가 없어요</h3><p>AI 추천을 받거나 아래에서 직접 추가해 주세요.</p></div>}
      <form className="custom-domain" onSubmit={addQuery}><label htmlFor="direct-query"><Plus size={15}/>검색 쿼리 직접 추가</label><div><input id="direct-query" disabled={disabled} maxLength={400} placeholder="예: Agentic AI research and applications" value={queryInput} onChange={e=>setQueryInput(e.target.value)}/><button type="submit" className="button" disabled={disabled||!queryInput.trim()||queries.length>=5}><Plus size={14}/>추가</button></div>{queryError&&<p className="error" role="alert">{queryError}</p>}</form><p className="source-limit">최대 5개 · 검색에 사용할 문장을 입력해 주세요.</p>
    </section>
    <section className="collection-domain-section" aria-labelledby="collection-domain-title"><h3 id="collection-domain-title"><Globe2 size={16}/>수집할 도메인 <span className="count">{domains.length}</span></h3>
    <div className="managed-domains" aria-label="등록한 도메인 목록">
      {domains.length ? domains.map(d => <article className="managed-domain" key={d.host}>
        <span className="domain-mark"><Globe2 size={19}/></span>
        <div className="managed-domain-copy"><div><strong>{d.name}</strong><span className="source-kind">{d.kind}</span></div><a href={`https://${d.host}`} target="_blank" rel="noreferrer">{d.host}<ExternalLink size={11}/></a><p>{d.desc}</p></div>
        <button className="icon-button" disabled={disabled} aria-label={`${d.host} 목록에서 삭제`} onClick={()=>{onChange(domains.filter(item=>item.host!==d.host));setError('');}}><X size={16}/></button>
      </article>) : <div className="source-empty"><Globe2 size={27}/><h3>아직 추가한 도메인이 없어요</h3><p>AI 추천을 받거나 아래에서 직접 추가해 주세요.</p></div>}
    </div>
    <form className="custom-domain" onSubmit={add}>
      <label htmlFor="direct-domain"><Plus size={15}/>도메인 직접 추가</label>
      <div><input disabled={disabled} id="direct-domain" placeholder="예: technologyreview.com" value={input} onChange={e=>setInput(e.target.value)}/><button className="button" type="submit" disabled={disabled||!input.trim()||domains.length>=LIMIT}><Plus size={14}/>추가</button></div>
      {error&&<p className="error" role="alert">{error}</p>}
    </form>
    <p className="source-limit">최대 20개 · AI 추천과 직접 추가한 도메인을 함께 관리합니다.</p>
    </section></div>
  </section>;
}

export function DomainRecommendationModal({ topic, existing, onClose, onAdd, sampleId, existingQueries=[], saving=false }) {
  const dialog = useRef(null);

  const [queries,setQueries]=useState([]);
  const [queriesReady,setQueriesReady]=useState(false);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [requestError, setRequestError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const existingHosts = new Set(existing.map(d=>d.host));
  const available = items.filter(d=>!existingHosts.has(d.host));
  const selected = available.filter(d=>d.selected);
  const checkedDomainCount=items.filter(d=>d.selected||existingHosts.has(d.host)).length;
  const checkedQueryCount=queries.filter(q=>q.selected||existingQueries.some(old=>queryKey(old.query)===queryKey(q.query))).length;
  const selectedQueries=queriesReady?queries.filter(q=>q.selected&&!existingQueries.some(old=>queryKey(old.query)===queryKey(q.query))):[];
  const queryOverLimit=existingQueries.length+selectedQueries.length>5;
  const overLimit = existing.length + selected.length > LIMIT;

  useEffect(()=>{
    const controller = new AbortController();
    let active = true;
    setItems([]); setQueries([]); setQueriesReady(false); setLoading(true); setRequestError('');
    const timeout = setTimeout(()=>controller.abort(),135000);
    streamRecommendedDomains(topic,controller.signal,domain=>{
      if(active) setItems(items=>[...items,{...domain,selected:true}]);
    },sampleId,query=>{if(active)setQueries(current=>[...current,{...query,selected:true}]);},rows=>{if(active){setQueries(current=>rows.map(q=>({...q,selected:current.find(old=>queryKey(old.query)===queryKey(q.query))?.selected??true})));setQueriesReady(true);}}).catch(err=>{if(active)setRequestError(err.name==='AbortError'?'추천 시간이 초과되었습니다. 받은 후보를 추가하거나 다시 추천받을 수 있어요.':err.message);})
      .finally(()=>{clearTimeout(timeout);if(active)setLoading(false);});
    return()=>{active=false;clearTimeout(timeout);controller.abort();};
  },[topic,attempt,sampleId]);
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);

  async function confirm() {
    if(loading||saving||overLimit||queryOverLimit||(!selected.length&&!selectedQueries.length))return;
    try{await onAdd(selected.map(({selected,...domain})=>domain),selectedQueries.map(({selected,...q})=>q));}catch(err){setRequestError(err.message);}
  }
  return <dialog ref={dialog} onCancel={e=>{if(saving)e.preventDefault();else onClose();}} onClick={e=>{if(!saving&&e.target===dialog.current)onClose();}} className="domain-dialog" aria-labelledby="domain-dialog-title">
    <div className="modal-head"><div className="modal-icon"><Sparkles size={23}/></div><div><span className="eyebrow">CURATE YOUR SOURCES</span><h2 id="domain-dialog-title">AI 추천 쿼리 및 도메인</h2><p>검색 쿼리를 확인하고, 목록에 추가할 출처를 선택하세요.</p></div><button className="icon-button" aria-label="팝업 닫기" disabled={saving} onClick={onClose}><X size={20}/></button></div>
    <div className="modal-body">
      <div className="modal-keywords"><span>관심 주제</span><span className="topic-value">{topic}</span></div>
      <section className="recommend-query-section" aria-labelledby="recommend-query-title">
        <h3 id="recommend-query-title"><span className="recommend-step">01</span>검색 쿼리 <span className="count">{checkedQueryCount}/{queries.length}</span>{queriesReady&&<Check size={16}/>}</h3>
        <ol className="collection-query-list" aria-live="polite">{queries.map((q,i)=><li key={q.query_id||i}><input className="domain-checkbox" type="checkbox" aria-label={`${q.query} 쿼리 선택`} checked={existingQueries.some(old=>queryKey(old.query)===queryKey(q.query))||q.selected} disabled={saving||existingQueries.some(old=>queryKey(old.query)===queryKey(q.query))} onChange={e=>setQueries(current=>current.map((item,index)=>index===i?{...item,selected:e.target.checked}:item))}/><p>{q.query}</p></li>)}</ol>
        {loading&&!queriesReady&&<div className="stream-progress" role="status"><Loader2 className="spin" size={17}/><b>주제에 맞는 검색 쿼리를 만들고 있어요</b></div>}
        {queryOverLimit&&<p className="error">검색 쿼리는 최대 5개입니다. 선택한 쿼리를 줄여 주세요.</p>}
        {!loading&&!queriesReady&&queries.length>0&&<p className="hint">완료되지 않은 쿼리는 저장되지 않았습니다.</p>}
      </section>
      <h3 className="recommend-domain-title"><span className="recommend-step">02</span>수집 도메인 <span className="count">{checkedDomainCount}/{items.length}</span>{loading&&!queriesReady&&<span className="hint">쿼리 추천 후 이어집니다</span>}</h3>
      <p className="recommendation-notice">AI가 제안한 후보입니다. 사이트의 현재 운영 상태와 신뢰성은 별도로 확인해 주세요.</p>
      <div className="domain-list" aria-live="polite" aria-busy={loading}>
        {loading&&queriesReady&&<div className="stream-progress" role="status"><Loader2 className="spin" size={18}/><div><b>{items.length?`${items.length}개 출처를 찾았어요. 계속 추천 중입니다.`:'주제에 맞는 출처를 찾고 있어요'}</b><p>완성된 출처부터 표시합니다. 추천 중에도 선택을 변경할 수 있어요.</p></div></div>}
        {requestError&&<div className="stream-error"><p className="error" role="alert">{requestError}</p><button className="button" onClick={()=>setAttempt(n=>n+1)}><RotateCcw size={14}/>처음부터 다시 추천</button></div>}
        {items.map(d=>{
          const registered=existingHosts.has(d.host);
          return <article className={`domain-card selectable ${d.selected||registered?'selected':''}`} key={d.host}>
            <input className="domain-checkbox" type="checkbox" aria-label={`${d.host} 선택`} checked={registered||d.selected} disabled={registered} onChange={e=>setItems(items=>items.map(item=>item.host===d.host?{...item,selected:e.target.checked}:item))}/>
            <span className="domain-mark"><Globe2 size={19}/></span><div className="domain-copy"><div><h3>{d.name}</h3><span className="source-kind">{d.kind}</span>{registered&&<span className="registered-label"><Check size={11}/>추가됨</span>}<a href={`https://${d.host}`} target="_blank" rel="noreferrer" aria-label={`${d.name} 홈페이지 열기`}><ExternalLink size={13}/></a></div><span className="domain-host">{d.host}</span><p>{d.desc}</p><p className="domain-relevance">주제 관련성 · {d.relevance}</p><div className="reason"><ShieldCheck size={14}/><span>{d.reason}</span></div></div>
          </article>;
        })}
        {!loading&&!requestError&&!items.length&&<div className="empty compact"><Globe2 size={26}/><h3>추천할 도메인을 찾지 못했어요</h3><p>주제를 구체적으로 바꾸거나 목록에서 직접 추가해 주세요.</p></div>}
      </div>
    </div>
    <div className="modal-footer"><span className={overLimit?'selection-limit-error':''}>{overLimit?`최대 20개까지 등록할 수 있어요. ${existing.length+selected.length-LIMIT}개를 해제해 주세요.`:`쿼리 ${selectedQueries.length}개 · 도메인 ${selected.length}개 선택`}</span><button className="button" disabled={saving} onClick={onClose}>취소</button><button className="button primary" disabled={loading||saving||overLimit||queryOverLimit||(!selected.length&&!selectedQueries.length)} onClick={confirm}>추가</button></div>
  </dialog>;
}
