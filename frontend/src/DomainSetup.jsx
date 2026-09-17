import React, { useEffect, useRef, useState } from 'react';
import { Plus, X, Sparkles, Globe2, ShieldCheck, ExternalLink, Loader2, RotateCcw, Check } from 'lucide-react';
import { normalizeDomain } from './lib';
import { streamRecommendedDomains } from './api';

const LIMIT = 20;

export function DomainBox({ domains, onChange, onRecommend, disabled=false }) {
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  function add(event) {
    event.preventDefault();
    try {
      const host = normalizeDomain(input);
      if (domains.some(d => d.host === host)) throw new Error('이미 목록에 추가된 도메인이에요.');
      if (domains.length >= LIMIT) throw new Error('도메인은 최대 20개까지 추가할 수 있어요.');
      onChange([...domains, { host, name: host, mark: host[0].toUpperCase(), kind: '직접 추가', custom: true,
        desc: '사용자가 등록한 수집 출처', reason: '운영 주체와 출처 공개 여부를 직접 확인해 주세요.' }]);
      setInput(''); setError('');
    } catch (err) { setError(err.message); }
  }
  return <section className="panel source-panel" aria-labelledby="source-panel-title">
    <div className="section-title">
      <div className="section-label"><span className="tile-icon"><Globe2 size={20}/></span><div><h2 id="source-panel-title">수집할 도메인 <span className="count">{domains.length}</span></h2><p>뉴스를 모을 출처를 직접 관리하세요.</p></div></div>
      <button className="button primary" disabled={disabled} onClick={onRecommend}><Sparkles size={15}/>AI로 도메인 추천 받기</button>
    </div>
    <div className="managed-domains" aria-label="등록한 도메인 목록">
      {domains.length ? domains.map(d => <article className="managed-domain" key={d.host}>
        <span className="domain-mark">{d.mark}</span>
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
  </section>;
}

export function DomainRecommendationModal({ topic, existing, onClose, onAdd, runId, saving=false }) {
  const dialog = useRef(null);
  const allCheckbox = useRef(null);
  const selectIncoming = useRef(true);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [requestError, setRequestError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const existingHosts = new Set(existing.map(d=>d.host));
  const available = items.filter(d=>!existingHosts.has(d.host));
  const selected = available.filter(d=>d.selected);
  const allSelected = available.length ? selected.length === available.length : selectIncoming.current;
  const overLimit = existing.length + selected.length > LIMIT;

  useEffect(()=>{
    const controller = new AbortController();
    let active = true;
    selectIncoming.current = true;
    setItems([]); setLoading(true); setRequestError('');
    const timeout = setTimeout(()=>controller.abort(),135000);
    streamRecommendedDomains(topic,controller.signal,domain=>{
      if(active) setItems(items=>[...items,{...domain,selected:selectIncoming.current}]);
    },runId).catch(err=>{if(active)setRequestError(err.name==='AbortError'?'추천 시간이 초과되었습니다. 받은 후보를 추가하거나 다시 추천받을 수 있어요.':err.message);})
      .finally(()=>{clearTimeout(timeout);if(active)setLoading(false);});
    return()=>{active=false;clearTimeout(timeout);controller.abort();};
  },[topic,attempt,runId]);
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  useEffect(()=>{allCheckbox.current.indeterminate=selected.length>0&&!allSelected;},[selected.length,allSelected]);

  function toggleAll(checked) {
    selectIncoming.current = checked;
    setItems(items=>items.map(d=>({...d,selected:checked})));
  }
  async function confirm() {
    if(loading||saving||overLimit||!selected.length)return;
    try{await onAdd(selected.map(({selected,...domain})=>domain));}catch(err){setRequestError(err.message);}
  }
  return <dialog ref={dialog} onCancel={e=>{if(saving)e.preventDefault();else onClose();}} onClick={e=>{if(!saving&&e.target===dialog.current)onClose();}} className="domain-dialog" aria-labelledby="domain-dialog-title">
    <div className="modal-head"><div className="modal-icon"><Sparkles size={23}/></div><div><span className="eyebrow">CURATE YOUR SOURCES</span><h2 id="domain-dialog-title">AI 추천 도메인</h2><p>추천 이유를 살펴보고, 목록에 추가할 출처를 선택하세요.</p></div><button className="icon-button" aria-label="팝업 닫기" disabled={saving} onClick={onClose}><X size={20}/></button></div>
    <div className="modal-body">
      <div className="modal-keywords"><span>관심 주제</span><span className="topic-value">{topic}</span></div>
      <div className="source-list-head"><label className="select-all"><input ref={allCheckbox} type="checkbox" checked={allSelected} onChange={e=>toggleAll(e.target.checked)}/>전체 선택</label><span>추천 {items.length}개 · 추가할 {selected.length}개</span></div>
      <p className="recommendation-notice">AI가 제안한 후보입니다. 사이트의 현재 운영 상태와 신뢰성은 별도로 확인해 주세요.</p>
      <div className="domain-list" aria-live="polite" aria-busy={loading}>
        {loading&&<div className="stream-progress" role="status"><Loader2 className="spin" size={18}/><div><b>{items.length?`${items.length}개 출처를 찾았어요. 계속 추천 중입니다.`:'주제에 맞는 출처를 찾고 있어요'}</b><p>완성된 출처부터 표시합니다. 추천 중에도 선택을 변경할 수 있어요.</p></div></div>}
        {requestError&&<div className="stream-error"><p className="error" role="alert">{requestError}</p><button className="button" onClick={()=>setAttempt(n=>n+1)}><RotateCcw size={14}/>처음부터 다시 추천</button></div>}
        {items.map(d=>{
          const registered=existingHosts.has(d.host);
          return <article className={`domain-card selectable ${d.selected||registered?'selected':''}`} key={d.host}>
            <input className="domain-checkbox" type="checkbox" aria-label={`${d.host} 선택`} checked={registered||d.selected} disabled={registered} onChange={e=>setItems(items=>items.map(item=>item.host===d.host?{...item,selected:e.target.checked}:item))}/>
            <span className="domain-mark">{d.mark}</span><div className="domain-copy"><div><h3>{d.name}</h3><span className="source-kind">{d.kind}</span>{registered&&<span className="registered-label"><Check size={11}/>추가됨</span>}<a href={`https://${d.host}`} target="_blank" rel="noreferrer" aria-label={`${d.name} 홈페이지 열기`}><ExternalLink size={13}/></a></div><span className="domain-host">{d.host}</span><p>{d.desc}</p><p className="domain-relevance">주제 관련성 · {d.relevance}</p><div className="reason"><ShieldCheck size={14}/><span>{d.reason}</span></div></div>
          </article>;
        })}
        {!loading&&!requestError&&!items.length&&<div className="empty compact"><Globe2 size={26}/><h3>추천할 도메인을 찾지 못했어요</h3><p>주제를 구체적으로 바꾸거나 목록에서 직접 추가해 주세요.</p></div>}
      </div>
    </div>
    <div className="modal-footer"><span className={overLimit?'selection-limit-error':''}>{overLimit?`최대 20개까지 등록할 수 있어요. ${existing.length+selected.length-LIMIT}개를 해제해 주세요.`:`기존 ${existing.length}개 + 선택 ${selected.length}개`}</span><button className="button" disabled={saving} onClick={onClose}>취소</button><button className="button primary" disabled={loading||saving||overLimit||!selected.length} onClick={confirm}><Plus size={15}/>선택한 {selected.length}개 추가</button></div>
  </dialog>;
}
