import React, { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Bookmark, Download, FileText, Mail, Plus, Search, Users, Trash2 } from 'lucide-react';
import { authRequest } from './authApi';
import './archive.css';
import SubscriptionSelect from './SubscriptionSelect';
import RecipientSearchDialog from './RecipientSearchDialog';

export default function NewsletterArchive({samples,onSamplesChange,onCreate,onDownload,pending}) {
  const [tab,setTab]=useState('samples');
  const [recipientLetter,setRecipientLetter]=useState(null);
  const [data,setData]=useState({subscriptions:[],newsletters:[]});
  const [subscription,setSubscription]=useState('');
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [opened,setOpened]=useState(null);
  const [opening,setOpening]=useState(false);
  const [retry,setRetry]=useState(0);
  const [deleting,setDeleting]=useState(null);
  const [query,setQuery]=useState('');
  const [from,setFrom]=useState('');
  const [to,setTo]=useState('');
  const [sort,setSort]=useState('newest');
  useEffect(()=>{
    let active=true;
    setLoading(true);setError('');
    authRequest(tab==='samples'?'/newsletters':'/subscriptions/archive').then(result=>{if(active){if(tab==='samples')onSamplesChange(result);else setData(result);}})
      .catch(err=>{if(active)setError(err.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[tab,retry,onSamplesChange]);
  const isSample=tab==='samples';
  const allItems=isSample?samples:data.newsletters.filter(n=>!subscription||n.subscription_id===subscription);
  const dateValue=item=>isSample?(item.saved_at||item.date):(item.published_at||'');
  const koreanDate=value=>/^\d{4}-\d{2}-\d{2}$/.test(value)?value:!value||Number.isNaN(Date.parse(value))?'':new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const invalidPeriod=Boolean(from&&to&&from>to);
  const items=allItems.filter(item=>{
    const day=koreanDate(dateValue(item));
    return !invalidPeriod&&`${item.title} ${item.topic||''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())&&(!from||day>=from)&&(!to||Boolean(day)&&day<=to);
  }).sort((a,b)=>{const aTime=Date.parse(dateValue(a))||0,bTime=Date.parse(dateValue(b))||0;return (sort==='newest'?bTime-aTime:aTime-bTime)||a.id.localeCompare(b.id);});
  const hasFilters=Boolean(query||from||to);
  function clearFilters(){setQuery('');setFrom('');setTo('');setSort('newest');}
  function switchTab(value){clearFilters();setTab(value);setOpened(null);setError('');}
  async function open(item){
    if(isSample){setOpened(item);return;}
    setOpening(true);setError('');
    try{setOpened(await authRequest(`/subscriptions/archive/${encodeURIComponent(item.id)}`));}
    catch(err){setError(err.message);}finally{setOpening(false);}
  }
  async function removeSample(item){
    if(deleting||!window.confirm(`‘${item.title}’을 샘플 보관함에서 삭제할까요?`))return;
    setDeleting(item.id);setError('');
    try{await authRequest(`/newsletters/${encodeURIComponent(item.id)}`,{method:'DELETE'});onSamplesChange(current=>current.filter(n=>n.id!==item.id));}
    catch(err){setError(err.message);try{onSamplesChange(await authRequest('/newsletters'));}catch{}}
    finally{setDeleting(null);}
  }
  function download(){
    if(isSample){onDownload(opened);return;}
    const url=URL.createObjectURL(new Blob([opened.html],{type:'text/html;charset=utf-8'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download='wianews.html';anchor.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <section className="panel archive newsletter-archive">
    <div className="archive-tabs" aria-label="보관함 종류">
      <button className={isSample?'active':''} aria-pressed={isSample} disabled={opening} onClick={()=>switchTab('samples')}><Bookmark size={17}/>샘플 보관함</button>
      <button className={!isSample?'active':''} aria-pressed={!isSample} disabled={opening} onClick={()=>switchTab('subscriptions')}><Mail size={17}/>구독 보관함</button>
    </div>
    <div className="archive-list-toolbar" hidden={isSample&&Boolean(opened)}>
      {!opened&&<h2>{isSample?'저장한 샘플':'받아본 뉴스레터'} <span className="count">{items.length}</span></h2>}
      {!isSample&&<SubscriptionSelect subscriptions={data.subscriptions} value={subscription} disabled={loading||opening} onChange={value=>{setSubscription(value);setOpened(null);}}/>}
      {isSample&&!opened&&<button className="button" disabled={pending} onClick={onCreate}><Plus size={15}/>새 뉴스레터</button>}
    </div>
    {!opened&&<div className="archive-filters">
      <label className="archive-search"><Search size={16}/><input aria-label="뉴스레터 제목·주제 검색" placeholder="제목·주제 검색" value={query} onChange={e=>setQuery(e.target.value)}/></label>
      <div className="archive-date-filter"><span>{isSample?'저장 기간':'발행 기간'} · KST</span><input type="date" aria-label="기간 시작일" value={from} onChange={e=>setFrom(e.target.value)}/><span>—</span><input type="date" aria-label="기간 종료일" value={to} onChange={e=>setTo(e.target.value)}/></div>
      <select aria-label="뉴스레터 정렬" value={sort} onChange={e=>setSort(e.target.value)}><option value="newest">최신순</option><option value="oldest">오래된순</option></select>
      {(hasFilters||sort!=='newest')&&<button className="button" onClick={clearFilters}>초기화</button>}
    </div>}
    {!opened&&invalidPeriod&&<p className="error" role="alert">시작일은 종료일보다 늦을 수 없습니다.</p>}
    {error&&<div className="error" role="alert">{error} <button className="button" onClick={()=>setRetry(n=>n+1)}>다시 불러오기</button></div>}
    {loading?<div className="empty" role="status">보관함을 불러오는 중입니다.</div>:opened?<>
      <button className="button archive-back" onClick={()=>setOpened(null)}><ArrowLeft size={15}/>목록으로</button>
      <div className="preview-toolbar"><strong>{opened.title}</strong><button className="button" disabled={pending} onClick={download}><Download size={15}/>HTML 다운로드</button></div>
      <iframe title={isSample?'샘플 뉴스레터':'구독 뉴스레터'} sandbox="allow-popups allow-popups-to-escape-sandbox" srcDoc={opened.html}/>
    </>:<>

      {items.length?<div className="archive-scroll-list" key={`${tab}-${subscription}-${query}-${from}-${to}-${sort}`} role="region" aria-label={isSample?'샘플 뉴스레터 목록':'구독 뉴스레터 목록'} tabIndex={0}>{items.map(item=><div className="archive-row" key={isSample?item.id:`${item.subscription_id}-${item.id}`}>
        <span className="tile-icon"><FileText size={22}/></span><div><h3>{item.title}</h3><p>{isSample?`${koreanDate(dateValue(item))} · 핵심 이슈 ${item.count}개`:`${item.coverage_start_date} — ${item.coverage_end_date} · 발행 ${koreanDate(item.published_at)} · 핵심 이슈 ${item.count}개`}</p></div>
        <div className="archive-row-actions">{isSample&&(item.subscriber_count>0||item.has_subscriptions)&&<span className="archive-subscriber-count"><Users size={13}/>{item.subscriber_count>0?`${item.subscriber_count}명 구독 중`:'구독 연결됨 · 수신 일시정지'}</span>}<button className="button archive-preview-button" disabled={opening} onClick={()=>open(item)} title="뉴스레터 보기" aria-label={`${item.title} 뉴스레터 보기`}><Search size={18} aria-hidden="true"/></button><button className="button archive-preview-button" onClick={()=>setRecipientLetter({...item,kind:isSample?'sample':'subscription'})} title="이메일 수신자 검색" aria-label={`${item.title} 이메일 수신자 검색`}><Mail size={18} aria-hidden="true"/></button>{isSample&&item.can_delete&&<button className="button archive-preview-button archive-delete-button" disabled={Boolean(deleting)||pending} onClick={()=>removeSample(item)} title="샘플 보관함에서 삭제" aria-label={`${item.title} 샘플 삭제`}><Trash2 size={18} aria-hidden="true"/></button>}</div>
      </div>)}</div>:allItems.length>0?<div className="empty"><Search size={32}/><h3>조건에 맞는 뉴스레터가 없어요</h3><p>검색어나 기간을 변경해 주세요.</p><button className="button" onClick={clearFilters}>필터 초기화</button></div>:<div className="empty">{isSample?<Bookmark size={36}/>:<Mail size={36}/>}<h3>{isSample?'아직 저장한 샘플이 없어요':'아직 받아본 뉴스레터가 없어요'}</h3><p>{isSample?'뉴스레터를 완성한 뒤 보관함에 저장해 보세요.':'구독으로 전달받은 뉴스레터가 이곳에 쌓입니다.'}</p>{isSample&&<button className="button primary" onClick={onCreate}>첫 뉴스레터 만들기<ArrowRight size={15}/></button>}</div>}
    </>}
    {recipientLetter&&<RecipientSearchDialog newsletter={recipientLetter} onClose={()=>setRecipientLetter(null)}/>}
  </section>;
}
