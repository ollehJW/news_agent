import React, { useEffect, useRef, useState } from 'react';
import { Store, Search, Users, X, ExternalLink, Layers3, Eye, Check, Plus, Loader2 } from 'lucide-react';
import { authRequest } from './authApi';

function publicationStart(value) {
  if(!value)return '발행 전';
  const date=new Date(value);
  if(Number.isNaN(date.getTime()))return '발행 전';
  return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);
}

export default function SubscriptionMarketplace({ items = [], loading = false, pendingId = null, busy = false, onSubscribe }) {
  const [query, setQuery] = useState('');
  const [sources,setSources]=useState(null);
  const [sort,setSort]=useState('popular');
  const [preview,setPreview]=useState(null);
  const newestFirst=(a,b)=>(b.registered_at||b.date||'').localeCompare(a.registered_at||a.date||'');
  const visible = items.filter(item => `${item.topic} ${(item.domains || []).join(' ')}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
    .sort((a,b)=>(sort==='popular'?(b.subscriberCount||0)-(a.subscriberCount||0):0)||newestFirst(a,b)||a.id.localeCompare(b.id));
  return <section className="panel marketplace-panel" aria-labelledby="marketplace-title">
    <div className="section-title"><div><h2 id="marketplace-title"><Store size={20}/>구독 마켓플레이스 <span className="count">{items.length}</span></h2><p>다른 사용자가 구독한 뉴스레터를 찾아 함께 받아보세요.</p></div></div>
    <div className="marketplace-toolbar"><label className="schedule-search marketplace-search"><Search size={16}/><input aria-label="마켓플레이스 검색" placeholder="주제, 도메인 검색" value={query} onChange={e=>setQuery(e.target.value)}/></label><div className="marketplace-sort-tabs" role="group" aria-label="마켓플레이스 정렬">{[['popular','인기순'],['newest','최신순']].map(([value,label])=><button key={value} type="button" aria-pressed={sort===value} onClick={()=>setSort(value)}>{label}</button>)}</div></div>
    {loading ? <div className="empty" role="status"><Loader2 size={25} className="spin"/><p>구독 가능한 뉴스레터를 불러오고 있어요.</p></div> : visible.length ? <div className="marketplace-grid">{visible.map(item => <article className="marketplace-card" key={item.id}>
      <div className="marketplace-cover">
        <header className="marketplace-masthead"><span className="marketplace-wordmark"><Layers3 size={16} aria-hidden="true"/>Wia<span>News</span></span></header>
        <div className="marketplace-card-heading"><span className="marketplace-edition-label"><Users size={12}/>{item.subscriberCount}명 구독</span>{item.subscribed&&<span className="marketplace-subscribed"><Check size={11}/>{item.subscriptionStatus==='paused'?'일시정지':'구독 중'}</span>}</div>
        <div className="marketplace-headline"><h3 title={item.topic}>{item.topic}</h3></div>
        <div className="marketplace-start-date"><span>발행 시작일</span><span>{publicationStart(item.first_published_at)}</span></div>
        <div className="marketplace-publish-options"><span>일간 / 주간 / 월간</span> 발행 가능</div>
        <div className="marketplace-details"><button className="marketplace-preview-button" aria-label={`${item.topic} 미리 보기`} aria-haspopup="dialog" onClick={()=>setPreview(item)}><Eye size={14}/>미리 보기</button><button className="marketplace-sources-button" aria-label={`${item.topic} 수집 출처 보기`} aria-haspopup="dialog" onClick={()=>setSources(item)}>수집 출처<Search size={14}/></button></div>
      </div>
      <footer className="marketplace-card-footer">
        <button className={`button ${item.subscribed?'':'primary'}`} disabled={item.subscribed||busy||pendingId!==null} onClick={()=>onSubscribe?.(item)}>{pendingId===item.id?<Loader2 size={14} className="spin"/>:item.subscribed?<Check size={14}/>:<Plus size={14}/>} {item.subscribed?'내 구독에 있음':'함께 구독하기'}</button>
      </footer>
    </article>)}</div> : <div className="empty marketplace-empty"><Store size={32}/><h3>{query?'검색 결과가 없어요':'아직 등록된 구독 뉴스레터가 없어요'}</h3><p>{query?'다른 주제나 도메인으로 검색해 보세요.':'구독 이력이 있는 뉴스레터가 이곳에 표시됩니다.'}</p></div>}
    {preview&&<PreviewDialog item={preview} onClose={()=>setPreview(null)}/>}
    {sources&&<SourceDialog item={sources} onClose={()=>setSources(null)}/>}
  </section>;
}


export function SourceDialog({item,onClose}) {
  const dialog=useRef(null);
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  return <dialog ref={dialog} className="marketplace-sources-dialog" aria-labelledby="marketplace-sources-title" onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===dialog.current)onClose();}}>
    <div className="marketplace-sources-header"><div><h3 id="marketplace-sources-title">수집 출처 <span>{item.domains?.length||0}</span></h3><p>{item.topic}</p></div><button className="icon-button" aria-label="수집 출처 닫기" onClick={onClose}><X size={19}/></button></div>
    {item.domains?.length?<ul className="marketplace-sources-list">{item.domains.map(host=><li key={host}><a href={`https://${host}`} target="_blank" rel="noopener noreferrer"><span>{host}</span><ExternalLink size={14} aria-hidden="true"/></a></li>)}</ul>:<p className="marketplace-no-sources">등록된 수집 출처가 없습니다.</p>}
  </dialog>;
}


export function PreviewDialog({item,onClose}) {
  const dialog=useRef(null);
  const [data,setData]=useState(null);
  const [error,setError]=useState('');
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  useEffect(()=>{
    const controller=new AbortController();
    setData(null);setError('');
    authRequest(`/subscriptions/marketplace/${encodeURIComponent(item.id)}/preview`,{signal:controller.signal})
      .then(result=>{if(!controller.signal.aborted)setData(result);})
      .catch(err=>{if(!controller.signal.aborted)setError(err.message);});
    return()=>controller.abort();
  },[item.id,attempt]);
  return <dialog ref={dialog} className="marketplace-preview-dialog" aria-labelledby="marketplace-preview-title" onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===dialog.current)onClose();}}>
    <header className="marketplace-preview-header"><div><h3 id="marketplace-preview-title">뉴스레터 미리 보기</h3><p>{item.topic}</p></div><div className="marketplace-preview-actions">{data&&<span>{data.kind==='published'?'최신 발행본':'초기 샘플'}</span>}<button className="icon-button" aria-label="뉴스레터 미리 보기 닫기" onClick={onClose}><X size={20}/></button></div></header>
    {error?<div className="marketplace-preview-state" role="alert"><p>{error}</p><button className="button" onClick={()=>setAttempt(n=>n+1)}>다시 불러오기</button></div>:data?<iframe title={`${item.topic} 뉴스레터 미리 보기`} sandbox="allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" srcDoc={data.html}/>:<div className="marketplace-preview-state" role="status"><Loader2 size={24} className="spin"/><p>뉴스레터를 불러오는 중입니다.</p></div>}
  </dialog>;
}
