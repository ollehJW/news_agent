import React, { useEffect, useRef, useState } from 'react';
import { Sparkles, X, Users, ArrowRight, Plus, Loader2, Layers3, Eye, Search, Check } from 'lucide-react';
import { SourceDialog, PreviewDialog } from './SubscriptionMarketplace';

export default function SubjectValidationDialog({ validation, pending, selectedId, error, onClose, onCreate, onSubscribe }) {
  const dialog=useRef(null);
  const [sources,setSources]=useState(null);
  const [preview,setPreview]=useState(null);
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  return <><dialog ref={dialog} className="subject-validation-dialog" aria-labelledby="subject-validation-title" onCancel={e=>{e.preventDefault();if(!pending)onClose();}} onClick={e=>{if(e.target===dialog.current&&!pending)onClose();}}>
    <header className="subject-validation-header"><span className="tile-icon"><Sparkles size={22}/></span><div><h2 id="subject-validation-title">비슷한 주제의 뉴스레터가 있어요</h2><p>‘{validation.topic}’와 관련 있는 뉴스레터를 확인해 보세요.</p></div><button className="icon-button" aria-label="비슷한 뉴스레터 닫기" disabled={pending} onClick={onClose}><X size={20}/></button></header>
    <div className="subject-validation-results">{validation.matches.map((item,index)=><article className="subject-match" key={item.sample_id}>
      <div className="subject-match-masthead"><span><Layers3 size={18}/>WiaNews</span><span className="subject-match-number">{String(index+1).padStart(2,'0')}</span></div>
      <div className="subject-match-copy"><h3>{item.topic}</h3><div className="subject-match-meta"><span><Users size={14}/>{item.subscriberCount}명 구독</span>{item.subscriptionStatus==='active'&&<span className="subject-match-status"><Check size={12}/>구독 중</span>}</div></div>
      <div className="subject-match-reason"><span><Sparkles size={13}/>이 주제와 비슷해요</span><p>{item.reason}</p></div>
      <div className="subject-match-actions">
        <button className="button" disabled={pending} aria-haspopup="dialog" aria-label={`${item.topic} 미리보기`} onClick={()=>setPreview({...item,id:item.sample_id})}><Eye size={14}/>미리보기</button>
        <button className="button" disabled={pending} aria-haspopup="dialog" aria-label={`${item.topic} 수집 출처`} onClick={()=>setSources(item)}><Search size={14}/>수집 출처</button>
        <button className="button primary" disabled={pending} onClick={()=>onSubscribe(item)}>{pending&&selectedId===item.sample_id?<Loader2 size={14} className="spin"/>:<ArrowRight size={14}/>}바로 구독</button>
      </div>
    </article>)}</div>
    {error&&<p className="error subject-validation-error" role="alert">{error}</p>}
    <footer className="subject-validation-footer"><span>다른 관점으로 수집하고 싶다면 새로 만들 수 있어요.</span><button className="button primary" disabled={pending} onClick={onCreate}><Plus size={15}/>새로 만들기</button></footer>
  </dialog>
    {preview&&<PreviewDialog item={preview} onClose={()=>setPreview(null)}/>}
    {sources&&<SourceDialog item={sources} onClose={()=>setSources(null)}/>}
  </>;
}

export function SubjectValidationStatusDialog({ loading = false, onConfirm }) {
  const dialog=useRef(null);
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  return <dialog ref={dialog} className="subject-validation-dialog subject-status-dialog" aria-labelledby="subject-status-title" onCancel={e=>{e.preventDefault();if(!loading)onConfirm();}}>
    <div className={`subject-status-icon ${loading?'':'complete'}`}>{loading?<Search size={27}/>:<Check size={27}/>}</div>
    <h2 id="subject-status-title" role="status">{loading?'비슷한 뉴스레터가 있는지 찾아보는 중…':'비슷한 뉴스레터가 없습니다.'}</h2>
    {loading?<div className="subject-status-progress" role="progressbar" aria-label="비슷한 뉴스레터 검색 중"><span/></div>:<><p>바로 시작해 보세요.</p><button className="button primary" onClick={onConfirm}>확인</button></>}
  </dialog>;
}
