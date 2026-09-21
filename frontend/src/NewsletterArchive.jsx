import React, { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Bookmark, Download, FileText, Mail, Plus, Search } from 'lucide-react';
import { authRequest } from './authApi';
import './archive.css';
import SubscriptionSelect from './SubscriptionSelect';
import RecipientSearchDialog from './RecipientSearchDialog';

export default function NewsletterArchive({samples,onCreate,onDownload,pending}) {
  const [tab,setTab]=useState('samples');
  const [recipientLetter,setRecipientLetter]=useState(null);
  const [data,setData]=useState({subscriptions:[],newsletters:[]});
  const [subscription,setSubscription]=useState('');
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [opened,setOpened]=useState(null);
  const [opening,setOpening]=useState(false);
  const [retry,setRetry]=useState(0);
  useEffect(()=>{
    if(tab!=='subscriptions')return;
    let active=true;
    setLoading(true);setError('');
    authRequest('/subscriptions/archive').then(result=>{if(active)setData(result);})
      .catch(err=>{if(active)setError(err.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[tab,retry]);
  const isSample=tab==='samples';
  const items=isSample?samples:data.newsletters.filter(n=>!subscription||n.subscription_id===subscription);
  function switchTab(value){setTab(value);setOpened(null);setError('');}
  async function open(item){
    if(isSample){setOpened(item);return;}
    setOpening(true);setError('');
    try{setOpened(await authRequest(`/subscriptions/archive/${encodeURIComponent(item.id)}`));}
    catch(err){setError(err.message);}finally{setOpening(false);}
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
    {error&&<div className="error" role="alert">{error} <button className="button" onClick={()=>setRetry(n=>n+1)}>다시 불러오기</button></div>}
    {loading?<div className="empty" role="status">구독 보관함을 불러오는 중입니다.</div>:opened?<>
      <button className="button archive-back" onClick={()=>setOpened(null)}><ArrowLeft size={15}/>목록으로</button>
      <div className="preview-toolbar"><strong>{opened.title}</strong><button className="button" disabled={pending} onClick={download}><Download size={15}/>HTML 다운로드</button></div>
      <iframe title={isSample?'샘플 뉴스레터':'구독 뉴스레터'} sandbox="allow-popups allow-popups-to-escape-sandbox" srcDoc={opened.html}/>
    </>:<>

      {items.length?items.map(item=><div className="archive-row" key={isSample?item.id:`${item.subscription_id}-${item.id}`}>
        <span className="tile-icon"><FileText size={22}/></span><div><h3>{item.title}</h3><p>{isSample?`${item.date} · 핵심 이슈 ${item.count}개`:`${item.coverage_start_date} — ${item.coverage_end_date} · 발행 ${item.published_at.slice(0,10)} · 핵심 이슈 ${item.count}개`}</p></div>
        <div className="archive-row-actions"><button className="button archive-preview-button" disabled={opening} onClick={()=>open(item)} title="뉴스레터 보기" aria-label={`${item.title} 뉴스레터 보기`}><Search size={18} aria-hidden="true"/></button><button className="button archive-preview-button" onClick={()=>setRecipientLetter({...item,kind:isSample?'sample':'subscription'})} title="이메일 수신자 검색" aria-label={`${item.title} 이메일 수신자 검색`}><Mail size={18} aria-hidden="true"/></button></div>
      </div>):<div className="empty">{isSample?<Bookmark size={36}/>:<Mail size={36}/>}<h3>{isSample?'아직 저장한 샘플이 없어요':'아직 받아본 뉴스레터가 없어요'}</h3><p>{isSample?'뉴스레터를 완성한 뒤 보관함에 저장해 보세요.':'구독으로 전달받은 뉴스레터가 이곳에 쌓입니다.'}</p>{isSample&&<button className="button primary" onClick={onCreate}>첫 뉴스레터 만들기<ArrowRight size={15}/></button>}</div>}
    </>}
    {recipientLetter&&<RecipientSearchDialog newsletter={recipientLetter} onClose={()=>setRecipientLetter(null)}/>}
  </section>;
}
