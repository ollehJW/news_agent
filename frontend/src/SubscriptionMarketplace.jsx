import React, { useEffect, useRef, useState } from 'react';
import { Store, Search, Users, X, ExternalLink, Layers3, Eye, Check, Plus, Loader2 } from 'lucide-react';
import { DAYS } from './schedules';
import './marketplace-frequency.css';
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
        <header className="marketplace-masthead"><span className="marketplace-wordmark"><Layers3 size={16} aria-hidden="true"/>Wia<span>News</span></span><div className="marketplace-frequencies" aria-label="설정된 발행 주기">{item.publication_schedules?.length?item.publication_schedules.map(schedule=><span className="marketplace-frequency" key={`${schedule.frequency}-${schedule.weekdays.join(',')}-${schedule.monthDay}`}>
          {schedule.frequency==='daily'?'일간 · 매일':schedule.frequency==='monthly'?`월간 · 매월 ${schedule.monthDay}일`:`주간 · 매주 ${[1,2,3,4,5,6,0].filter(day=>schedule.weekdays.includes(day)).map(day=>DAYS[day]).join('·')}요일`}
        </span>):<span>등록된 발행 일정 없음</span>}</div></header>
        <div className="marketplace-card-heading"><span className="marketplace-edition-label"><Users size={12}/>{item.subscriberCount}명 구독</span>{item.subscribed&&<span className="marketplace-subscribed"><Check size={11}/>{item.subscriptionStatus==='paused'?'일시정지':'구독 중'}</span>}</div>
        <div className="marketplace-headline"><h3 title={item.topic}>{item.topic}</h3></div>
        <div className="marketplace-start-date"><span>발행 시작일</span><span>{publicationStart(item.first_published_at)}</span></div>
        <div className="marketplace-publish-options marketplace-issued-count">총 <strong>{item.published_count??0}호</strong> 발행</div>
        <div className="marketplace-details"><button className="marketplace-preview-button" aria-label={`${item.topic} 미리 보기`} aria-haspopup="dialog" onClick={()=>setPreview(item)}><Eye size={14}/>미리 보기</button><button className="marketplace-sources-button" aria-label={`${item.topic} 수집 조건 보기`} aria-haspopup="dialog" onClick={()=>setSources(item)}>수집 조건<Search size={14}/></button></div>
      </div>
      <footer className="marketplace-card-footer">
        <button className={`button ${item.subscribed?'':'primary'}`} disabled={item.subscribed||busy||pendingId!==null} onClick={()=>onSubscribe?.(item)}>{pendingId===item.id?<Loader2 size={14} className="spin"/>:item.subscribed?<Check size={14}/>:<Plus size={14}/>} {item.subscribed?'내 구독에 있음':'구독하기'}</button>
      </footer>
    </article>)}</div> : <div className="empty marketplace-empty"><Store size={32}/><h3>{query?'검색 결과가 없어요':'아직 등록된 구독 뉴스레터가 없어요'}</h3><p>{query?'다른 주제나 도메인으로 검색해 보세요.':'구독 이력이 있는 뉴스레터가 이곳에 표시됩니다.'}</p></div>}
    {preview&&<PreviewDialog item={preview} onClose={()=>setPreview(null)}/>}
    {sources&&<SourceDialog item={sources} onClose={()=>setSources(null)}/>}
  </section>;
}


export function SourceDialog({item,onClose}) {
  const dialog=useRef(null);
  const [data,setData]=useState(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
  const id=item.sample_id||item.id;
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  useEffect(()=>{
    const controller=new AbortController();setData(null);setError('');
    authRequest(`/subscriptions/marketplace/${encodeURIComponent(id)}/conditions`,{signal:controller.signal})
      .then(result=>{if(!controller.signal.aborted)setData(result);})
      .catch(err=>{if(!controller.signal.aborted)setError(err.message);});
    return()=>controller.abort();
  },[id,attempt]);
  return <dialog ref={dialog} className="marketplace-sources-dialog collection-conditions-dialog" aria-labelledby="marketplace-sources-title" onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===dialog.current)onClose();}}>
    <div className="marketplace-sources-header"><div><h3 id="marketplace-sources-title">수집 조건</h3><p>{item.topic||item.title}</p></div><button className="icon-button" aria-label="수집 조건 닫기" onClick={onClose}><X size={19}/></button></div>
    {error?<div className="marketplace-preview-state" role="alert"><p>{error}</p><button className="button" onClick={()=>setAttempt(n=>n+1)}>다시 불러오기</button></div>:!data?<div className="marketplace-preview-state" role="status"><Loader2 size={22} className="spin"/><p>수집 조건을 불러오는 중입니다.</p></div>:<div className="collection-conditions-body">
      <section><h4><Search size={15}/>검색 쿼리 <span>{data.queries?.length||0}개</span></h4>{data.queries?.length?<ol className="conditions-query-list">{data.queries.map((query,index)=><li key={index}>{query}</li>)}</ol>:<p className="hint">등록된 검색 쿼리가 없습니다.</p>}</section>
      <section><h4><Layers3 size={15}/>수집 도메인 <span>{data.search_all_domains?'전체':`${data.domains?.length||0}개`}</span></h4>{data.search_all_domains?<p className="conditions-all-domains">전체 도메인 검색 · 특정 사이트로 제한하지 않습니다.</p>:data.domains?.length?<ul className="marketplace-sources-list">{data.domains.map(host=><li key={host}><a href={`https://${host}`} target="_blank" rel="noopener noreferrer"><span>{host}</span><ExternalLink size={14} aria-hidden="true"/></a></li>)}</ul>:<p className="hint">등록된 수집 도메인이 없습니다.</p>}</section>
    </div>}
  </dialog>;
}


export function PreviewDialog({item,onClose}) {
  const dialog=useRef(null);
  const [data,setData]=useState(null);
  const [editions,setEditions]=useState([]);
  const [selectedId,setSelectedId]=useState('');
  const [error,setError]=useState('');
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  useEffect(()=>{
    const controller=new AbortController();
    setData(null);setError('');
    authRequest(`/subscriptions/marketplace/${encodeURIComponent(item.id)}/preview${selectedId?`?newsletter_id=${encodeURIComponent(selectedId)}`:''}`,{signal:controller.signal})
      .then(result=>{if(!controller.signal.aborted){setData(result);setEditions(result.editions||[]);}})
      .catch(err=>{if(!controller.signal.aborted)setError(err.message);});
    return()=>controller.abort();
  },[item.id,attempt,selectedId]);
  return <dialog ref={dialog} className="marketplace-preview-dialog" aria-labelledby="marketplace-preview-title" onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===dialog.current)onClose();}}>
    <header className="marketplace-preview-header"><div><h3 id="marketplace-preview-title">뉴스레터 미리 보기</h3><p>{item.topic}</p></div><div className="marketplace-preview-actions">{!editions.length&&data&&<span>초기 샘플</span>}<button className="icon-button" aria-label="뉴스레터 미리 보기 닫기" onClick={onClose}><X size={20}/></button></div></header>
    {editions.length>0&&<div className="marketplace-edition-toolbar"><label htmlFor="marketplace-edition-select">발행호 선택</label><div className="marketplace-edition-select"><select id="marketplace-edition-select" value={selectedId||data?.newsletter_id||''} onChange={e=>setSelectedId(e.target.value)}>{editions.map(edition=><option key={edition.newsletter_id} value={edition.newsletter_id}>{edition.issue_number}호 · {publicationStart(edition.published_at)} 발행</option>)}</select></div><span>총 {editions.length}호</span></div>}
    {error?<div className="marketplace-preview-state" role="alert"><p>{error}</p><button className="button" onClick={()=>setAttempt(n=>n+1)}>다시 불러오기</button></div>:data?<iframe title={`${item.topic} 뉴스레터 미리 보기`} sandbox="allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" srcDoc={data.html}/>:<div className="marketplace-preview-state" role="status"><Loader2 size={24} className="spin"/><p>뉴스레터를 불러오는 중입니다.</p></div>}
  </dialog>;
}
