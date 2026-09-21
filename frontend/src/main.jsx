import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { UserRound, ArrowRight, ArrowLeft, Check, ChevronRight, Plus, X, Sparkles, Globe2, FileText, Layers3, Search, CalendarClock, CalendarDays, Download, ExternalLink, Loader2, CircleHelp, SlidersHorizontal, Bookmark, RotateCcw, Radio, Hash, CheckCheck } from 'lucide-react';
import { initialDates } from './lib';
import { DomainBox, DomainRecommendationModal } from './DomainSetup';
import Scheduling from './Scheduling';
import NewsletterArchive from './NewsletterArchive';
import SubjectValidationDialog, { SubjectValidationStatusDialog } from './SubjectValidation';
import './subject-validation.css';
import NewsSelection from './NewsSelection';
import { collectSample } from './collectionApi';
import AuthGate from './Auth';
import { authRequest, postAuth } from './authApi';
import './styles.css';
import './scheduling.css';
import './readability.css';


const steps = ['주제·도메인 설정', '수집 기간 설정', '뉴스 분석·선정', '뉴스레터 완성'];
const weights = [['기술적 중요성',40],['기술 주체 경쟁력',30],['파급력',30]];
function Button({children, primary, className='', ...props}) { return <button className={`button ${primary?'primary':''} ${className}`} {...props}>{children}</button>; }
function NewsletterSummaryProgress() {
  const dialog=useRef(null);
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  return <dialog ref={dialog} className="subject-validation-dialog subject-status-dialog" aria-labelledby="newsletter-summary-title" onCancel={e=>e.preventDefault()}>
    <div className="subject-status-icon"><Sparkles size={27}/></div>
    <h2 id="newsletter-summary-title" role="status">이번 호 핵심 요약 생성중...</h2>
    <div className="subject-status-progress" role="progressbar" aria-label="핵심 요약 생성 중"><span/></div>
  </dialog>;
}
function App({user,onLogout}) {
  const sampleRef = useRef(null);
  const validationController = useRef(null);
  const collectionController = useRef(null);
  const [collectionMessage,setCollectionMessage]=useState('');
  const [collectionStats,setCollectionStats]=useState(null);
  useEffect(()=>()=>collectionController.current?.abort(),[]);
  const [approvedTopic,setApprovedTopic]=useState('');
  const [validation,setValidation]=useState(null);
  const [validationOpen,setValidationOpen]=useState(false);
  const [checkingTopic,setCheckingTopic]=useState(false);
  const [selectedSubscription,setSelectedSubscription]=useState(null);
  const [subscriptionError,setSubscriptionError]=useState('');
  const [topic,setTopic] = useState('');
  const [dates,setDates] = useState(initialDates);
  const [step,setStep] = useState(0);
  const [domains,setDomains] = useState([]);
  const [queries,setQueries] = useState([]);
  const [modal,setModal] = useState(false);
  const [candidates,setCandidates] = useState([]);
  const [pending,setPending] = useState(false);
  const [generated,setGenerated] = useState(null);
  const [generatingSummary,setGeneratingSummary]=useState(false);
  const [issues,setIssues] = useState([]);
  const [progress,setProgress] = useState(-1);
  const [view,setView] = useState('studio');
  const title = topic.trim();
  const [toast,setToast] = useState('');
  const [error,setError] = useState('');
  const [saved,setSaved] = useState([]);
  const [opened,setOpened] = useState(null);
  const busy = pending || (progress>=0 && progress<3);
  useEffect(()=>{let active=true;authRequest('/newsletters').then(rows=>{if(active)setSaved(rows);}).catch(err=>{if(active)setError(err.message);});return()=>{active=false;};},[]);
  useEffect(()=>{if(!toast)return; const id=setTimeout(()=>setToast(''),3500);return()=>clearTimeout(id)},[toast]);
  const topicApproved=Boolean(topic.trim())&&approvedTopic===topic.trim();
  useEffect(()=>()=>validationController.current?.abort(),[]);
  function updateTopic(value) {
    if(value.trim()!==topic.trim()){
      validationController.current?.abort();setApprovedTopic('');setValidation(null);setValidationOpen(false);
      sampleRef.current=null;setQueries([]);setDomains([]);setCandidates([]);setIssues([]);setGenerated(null);
    }
    setTopic(value);setError('');
  }
  async function checkTopic() {
    if(pending)return;
    if(!topic.trim()||topic.trim().length>120){setError('관심 주제를 1~120자로 입력해 주세요.');return;}
    validationController.current?.abort();const controller=new AbortController();validationController.current=controller;
    setPending(true);setCheckingTopic(true);setError('');setSubscriptionError('');setApprovedTopic('');
    try {
      const result=await authRequest('/subject-validations',{method:'POST',body:JSON.stringify({topic:topic.trim()}),signal:controller.signal});
      if(controller.signal.aborted)return;
      setValidation(result);
      setValidationOpen(true);
    }catch(err){if(!controller.signal.aborted)setError(err.message);}
    finally{if(validationController.current===controller){setPending(false);setCheckingTopic(false);}}
  }
  function continueCreation() {setApprovedTopic(validation.topic);setValidationOpen(false);setSubscriptionError('');}
  async function subscribeToMatch(item) {
    if(pending)return;
    setPending(true);setSelectedSubscription(item.sample_id);setSubscriptionError('');
    try {
      const subscription=await postAuth('/subscriptions',{sample_id:item.sample_id});
      if(subscription.status==='paused')await authRequest(`/subscriptions/${subscription.id}/status`,{method:'PATCH',body:JSON.stringify({status:'active'})});
      setValidationOpen(false);setView('schedules');setOpened(null);setToast(subscription.status==='active'&&item.subscriptionStatus==='active'?'이미 구독 중인 뉴스레터입니다.':'구독을 추가했습니다. 발행 주기는 내 구독에서 변경할 수 있어요.');
    }catch(err){setSubscriptionError(err.message);}finally{setPending(false);setSelectedSubscription(null);}
  }
  async function ensureSample() {
    if(sampleRef.current?.topic===topic.trim())return sampleRef.current.id;
    const data=await postAuth('/samples',{topic:topic.trim()});
    sampleRef.current={id:data.sample_id,topic:topic.trim()};return data.sample_id;
  }
  function adoptSample(id) {
    sampleRef.current={id,topic:topic.trim()};
    setDomains(current=>current.map(d=>({...d,sampleId:id})));
  }
  async function syncSources(id,items,queryItems) {
    const result=await authRequest(`/samples/${id}/sources`,{method:'PUT',body:JSON.stringify({queries:queryItems?.map(q=>({query:q.query,recommendation_id:q.recommendation_id})),domains:items.map(d=>({host:d.host,custom:d.custom||d.sampleId!==id,recommendation_id:d.sampleId===id?d.recommendation_id:undefined}))})});
    adoptSample(result.sample_id);
    const mapped=result.domains.map(d=>({...d,sampleId:result.sample_id}));setDomains(mapped);setQueries(result.queries||[]);return result.sample_id;
  }
  async function changeDomains(items) {
    if(pending)return;
    if(!topic.trim()){setDomains(items);return;}
    setPending(true);setError('');
    try{await syncSources(await ensureSample(),items);}catch(err){setError(err.message);}finally{setPending(false);}
  }
  async function changeQueries(items) {
    if(pending)return;
    setPending(true);setError('');
    try{await syncSources(await ensureSample(),domains,items);}catch(err){setError(err.message);throw err;}finally{setPending(false);}
  }
  function validSources() {
    if(!topicApproved){setError('비슷한 뉴스레터를 먼저 확인해 주세요.');return false;}
    if(!topic.trim() || topic.trim().length>120){setError('관심 주제를 1~120자로 입력해 주세요.');return false;}
    if(!queries.length){setError('수집할 쿼리를 1개 이상 추가해 주세요.');return false;}
    if(!domains.length){setError('수집할 도메인을 1개 이상 추가해 주세요.');return false;}
    return true;
  }
  async function openDomains() {
    if(!topic.trim() || topic.trim().length>120){setError('관심 주제를 1~120자로 입력해 주세요.');return;}
    setPending(true);setError('');
    try{await syncSources(await ensureSample(),domains);setModal(true);}catch(err){setError(err.message);}finally{setPending(false);}
  }
  async function addRecommended(selected,selectedQueries=[]) {
    setPending(true);setError('');
    try{const merged=new Map(domains.map(d=>[d.host,d]));for(const domain of selected)if(!merged.has(domain.host))merged.set(domain.host,{...domain,sampleId:sampleRef.current.id});const combined=new Map(queries.map(q=>[q.query.trim().replace(/\s+/g,' ').toLocaleLowerCase(),q]));for(const q of selectedQueries){const key=q.query.trim().replace(/\s+/g,' ').toLocaleLowerCase();if(!combined.has(key))combined.set(key,q);}await syncSources(sampleRef.current.id,[...merged.values()],[...combined.values()]);setModal(false);}catch(err){setError(err.message);throw err;}finally{setPending(false);}
  }
  async function nextPeriod() {
    if(!validSources())return;
    setPending(true);setError('');
    try{let id=await syncSources(await ensureSample(),domains);const period=await authRequest(`/samples/${id}/period`,{method:'PUT',body:JSON.stringify(dates)});id=period.sample_id;adoptSample(id);setStep(1);}catch(err){setError(err.message);}finally{setPending(false);}
  }
  async function collect() {
    if(!validSources()){setStep(0);return;}
    if(!dates.start||!dates.end||dates.start>dates.end){setError('수집 시작일과 종료일을 확인해 주세요.');return;}
    collectionController.current?.abort();const controller=new AbortController();collectionController.current=controller;
    setCollectionMessage('선택한 출처에서 뉴스를 수집하고 있어요');setCollectionStats(null);
    setError('');setPending(true);setStep(2);setProgress(0);setCandidates([]);setIssues([]);setGenerated(null);
    try{let id=await syncSources(await ensureSample(),domains);const period=await authRequest(`/samples/${id}/period`,{method:'PUT',body:JSON.stringify(dates)});id=period.sample_id;adoptSample(id);const result=await collectSample(id,({stage,message})=>{setProgress(stage);setCollectionMessage(message);},controller.signal);setCollectionStats(result);adoptSample(result.sample_id);setCandidates(result.issues);setIssues(result.issues.filter(n=>n.selected));setProgress(3);}catch(err){setError(err.message);setProgress(-1);setStep(1);}finally{setPending(false);}
  }
  async function toggleIssue(id) {
    if(pending)return;
    const selectedIds=new Set(issues.map(n=>n.id));if(selectedIds.has(id))selectedIds.delete(id);else selectedIds.add(id);
    setPending(true);setError('');
    try{const result=await authRequest(`/samples/${sampleRef.current.id}/selection`,{method:'PUT',body:JSON.stringify({article_ids:[...selectedIds]})});adoptSample(result.sample_id);setCandidates(result.issues);setIssues(result.issues.filter(n=>n.selected));setGenerated(null);}catch(err){setError(err.message);}finally{setPending(false);}
  }
  async function makeNewsletter() {
    if(pending)return;
    setPending(true);setGeneratingSummary(true);setError('');
    try{const letter=await postAuth(`/samples/${sampleRef.current.id}/newsletter`);setGenerated(letter);setStep(3);}catch(err){setError(err.message);}finally{setGeneratingSummary(false);setPending(false);}
  }
  function previousStep() {setError('');setStep(current=>Math.max(0,current-1));}
  const html=generated?.html||'';
  async function download(letter=generated) {
    if(!letter)return;
    setPending(true);
    try{const response=await fetch(`/api/newsletters/${letter.id}/download`);if(!response.ok){if(response.status===401)window.dispatchEvent(new Event('wianews-session-expired'));throw new Error('다운로드하지 못했습니다. 다시 시도해 주세요.');}const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='wianews.html';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);setToast('HTML 파일을 다운로드했습니다.');}catch(err){setError(err.message);}finally{setPending(false);}
  }
  async function save() {
    if(!generated)return;
    setPending(true);setError('');
    try{const entry=await postAuth(`/newsletters/${generated.id}/save`);setGenerated(entry);setSaved(current=>[entry,...current.filter(n=>n.id!==entry.id)]);setToast('뉴스레터를 보관함에 저장했습니다.');}catch(err){setError(err.message);}finally{setPending(false);}
  }
  function reset(){validationController.current?.abort();validationController.current=null;setCheckingTopic(false);setPending(false);setApprovedTopic('');setValidation(null);setValidationOpen(false);sampleRef.current=null;setQueries([]);setStep(0);setProgress(-1);setCandidates([]);setIssues([]);setGenerated(null);setOpened(null);setError('');setView('studio');}
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e=>{e.preventDefault();setView('studio')}}><span className="brand-icon"><Layers3 size={24}/></span><div>WiaNews<small>NEWSLETTER AGENT</small></div></a>
      <div className="workspace-label">WORKSPACE</div>
      <nav><button className={view==='studio'?'active':''} onClick={()=>{setView('studio');setOpened(null)}}><Sparkles size={17}/>뉴스레터 만들기<ChevronRight size={14}/></button><button className={view==='archive'?'active':''} onClick={()=>{setView('archive');setOpened(null)}}><Bookmark size={17}/>뉴스레터 보관함</button><button className={view==='schedules'?'active':''} onClick={()=>{setView('schedules');setOpened(null)}}><CalendarClock size={17}/>구독 관리</button></nav>
      <div className="side-bottom"><div className="profile"><span aria-hidden="true"><UserRound size={20}/></span><div>{user.full_name}<small>{user.team_name}</small></div><span className="online"/></div><button className="sidebar-logout" onClick={onLogout}>로그아웃</button></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div>Workspace<ChevronRight size={13}/><strong>{view==='studio'?'뉴스레터 만들기':view==='schedules'?'구독 관리':'뉴스레터 보관함'}</strong></div></header>
    <main>
      <div className="page-heading"><div><div className="eyebrow">YOUR WEEKLY TECH INTELLIGENCE</div><h1>{view==='schedules'?'구독 관리':view==='archive'?'뉴스레터 보관함':'기술의 흐름을, 한눈에.'}</h1><p>{view==='schedules'?'관심 있는 뉴스레터를 구독하고, 원하는 발행 주기를 설정하세요.':view==='archive'?'직접 만든 샘플과 구독으로 받아본 뉴스레터를 확인하세요.':'관심 있는 주제 하나를 알려주세요. 꼭 알아야 할 기술 소식을 Agent가 정리합니다.'}</p></div></div>
      {error&&<p className="error" role="alert">{error}</p>}
      {view==='schedules'?<Scheduling newsletters={saved} notify={setToast}/>:view==='archive'? <NewsletterArchive samples={saved} onCreate={reset} onDownload={download} pending={pending}/>:<>
      <div className="stepper">{steps.map((s,i)=><React.Fragment key={s}><div className={`step ${step===i?'active':''} ${step>i?'done':''}`}><span>{step>i?<Check size={15}/>:String(i+1).padStart(2,'0')}</span><div><small>STEP {i+1}</small><b>{s}</b></div></div>{i<3&&<div className="step-line"/>}</React.Fragment>)}</div>
      <div className="setup-grid studio-grid"><div className="studio-content">{step===0?<div className="setup-main"><section className="panel keyword-panel topic-panel"><div className="section-title"><div className="section-label"><span className="tile-icon"><Hash size={20}/></span><div><h2>어떤 주제를 살펴볼까요?</h2><p>뉴스레터로 받아보고 싶은 주제 하나를 입력해 주세요.</p></div></div></div>
        <label className="field-label" htmlFor="topic-input">뉴스레터 주제 <span>{topic.length}/120자</span></label>
        <div className="keyword-input"><Search size={18}/><input id="topic-input" placeholder="예: Agentic AI 기술 및 활용 동향" value={topic} disabled={pending} maxLength={120} onChange={e=>updateTopic(e.target.value)} aria-describedby="topic-hint" onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();checkTopic();}}}/></div>
        <p id="topic-hint" className="hint topic-hint">하나의 주제를 자유롭게 적어 주세요. 관심 분야와 살펴볼 관점을 함께 쓰면 좋아요.</p>
        <div className="topic-bottom-row"><div className="suggestions"><span><Sparkles size={13}/>주제 예시</span>{['Agentic AI 기술 및 활용 동향','전기차 통합 열관리 시스템 기술 동향','산업용 로보틱스 기술 동향'].map(example=><button key={example} disabled={pending} onClick={()=>updateTopic(example)}>{example}</button>)}</div>
        <div className="subject-check-action"><Button primary disabled={pending||!topic.trim()} onClick={checkTopic}>{checkingTopic?<Loader2 size={15} className="spin"/>:<Search size={15}/>} {checkingTopic?'주제 확인 중…':'이 주제로 시작하기'}</Button>{topicApproved&&<span className="subject-check-complete"><Check size={14}/>주제 확인 완료</span>}</div></div>
      </section>
      {topicApproved&&<DomainBox onQueriesChange={changeQueries} queries={queries} domains={domains} disabled={pending} onChange={changeDomains} onRecommend={openDomains}/>}
      
      
      </div>
:step===1?<section className="panel period-panel">
        <div className="section-title"><div className="section-label"><span className="tile-icon"><CalendarDays size={20}/></span><div><h2>어느 기간의 뉴스를 모을까요?</h2><p>뉴스 수집 시작일과 종료일을 설정하세요.</p></div></div><span className="eyebrow">STEP 02</span></div>
        <label className="field-label">뉴스 수집 기간</label><div className="period"><div className="date-field"><CalendarDays size={16}/><input aria-label="수집 시작일" type="date" value={dates.start} max={dates.end} onChange={e=>setDates({...dates,start:e.target.value})}/><span>—</span><input aria-label="수집 종료일" type="date" min={dates.start} value={dates.end} onChange={e=>setDates({...dates,end:e.target.value})}/></div><Button onClick={()=>setDates(initialDates())}>최근 7일</Button></div><p className="hint period-hint">시작일과 종료일을 포함한 기간의 뉴스를 수집합니다.</p>
        
      </section>:step===2?<>
        <NewsSelection progress={progress} progressMessage={collectionMessage} collectionStats={collectionStats} candidates={candidates} selected={issues} busy={progress>=0&&progress<3} disabled={pending} onToggle={toggleIssue}/>
      </>:<section className="panel newsletter-panel"><div className="section-title"><div><div className="eyebrow">READY TO READ</div><h2>이번 주의 기술 뉴스레터가 완성됐어요.</h2></div></div><div className="preview-toolbar"><span><span className="preview-dot"/> HTML 미리보기</span></div><iframe title="뉴스레터 HTML 미리보기" sandbox="allow-popups allow-popups-to-escape-sandbox" srcDoc={html}/></section>}
      <nav className="step-navigation" aria-label="단계 이동">
        <div className="step-navigation-back">{step>0&&<Button disabled={busy} onClick={previousStep}><ArrowLeft size={15}/>이전 · {steps[step-1]}</Button>}</div>
        <div className="step-navigation-next">{step===0?<Button primary disabled={busy||!topicApproved} onClick={nextPeriod}>다음 · 수집 기간 설정<ArrowRight size={15}/></Button>:step===1?<Button primary disabled={busy} onClick={collect}>뉴스 수집 시작<ArrowRight size={15}/></Button>:step===2?<Button primary disabled={busy||!issues.length} onClick={makeNewsletter}>뉴스레터 만들기<ArrowRight size={15}/></Button>:<><Button disabled={pending} onClick={reset}><RotateCcw size={15}/>새로 만들기</Button><Button disabled={pending||!generated} onClick={()=>download()}><Download size={15}/>HTML 다운로드</Button><Button primary disabled={pending||!generated} onClick={save}><Bookmark size={15}/>보관함에 저장</Button></>}</div>
      </nav>
      </div><aside className="right-column"><section className="panel outcome"><div className="eyebrow">LESS NOISE, MORE SIGNAL</div><h2>읽어야 할 뉴스만,<br/>잘 정리된 한 통으로.</h2><p>여러 사이트를 오갈 필요 없이<br/>기술의 변화와 핵심 소식을 함께.</p><div className="mini-letter"><div className="mini-letter-top"><span>WiaNews</span><span>WEEKLY ↗</span></div><b>이번 주 기술 인사이트</b><div className="mini-summary"><span/><span/></div>{[1,2,3].map(i=><div className="mini-item" key={i}><em>0{i}</em><div><span/><span/></div></div>)}<div className="mini-bottom">CURATED BY YOUR AGENT</div></div><div className="outcome-bottom"><CheckCheck size={16}/>핵심 요약 · 선정 이슈 · 출처 링크</div></section><section className="panel criteria"><div className="section-title"><h3><SlidersHorizontal size={16}/>이렇게 선정해요</h3><span>100점 기준</span></div>{weights.map(([name,w])=><div className="weight" key={name}><span title={name==='기술 주체 경쟁력'?'보도 매체가 아닌 개발기업·연구주체의 규모, 기술력, 연구 성과 및 시장 경쟁력':undefined}>{name}</span><div><i style={{width:`${w*2}%`}}/></div><b>{w}%</b></div>)}<p>중요도 순으로 상위 5개를 기본 선택합니다. 최종 후보는 직접 변경할 수 있습니다.</p></section></aside></div>
      </>}
      <footer className="page-footer"><span>WiaNews <span>·</span> 기술을 읽는 더 나은 방법</span><span>Designed for your next idea.</span></footer>
    </main></div>
    {generatingSummary&&<NewsletterSummaryProgress/>}
    {checkingTopic&&<SubjectValidationStatusDialog loading/>}
    {!checkingTopic&&validationOpen&&validation&&!validation.matches.length&&<SubjectValidationStatusDialog onConfirm={continueCreation}/>}
    {!checkingTopic&&validationOpen&&validation&&validation.matches.length>0&&<SubjectValidationDialog validation={validation} pending={pending} selectedId={selectedSubscription} error={subscriptionError} onClose={()=>setValidationOpen(false)} onCreate={continueCreation} onSubscribe={subscribeToMatch}/>}
    {modal&&<DomainRecommendationModal existingQueries={queries} sampleId={sampleRef.current?.id} saving={pending} topic={topic.trim()} existing={domains} onClose={()=>setModal(false)} onAdd={addRecommended}/>}
    {toast&&<div className="toast" role="status"><Check size={17}/>{toast}</div>}
  </div>;
}
createRoot(document.getElementById('root')).render(<AuthGate>{(user,onLogout)=><App key={user.user_id} user={user} onLogout={onLogout}/>}</AuthGate>);
