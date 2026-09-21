import React, { useEffect, useRef, useState } from 'react';
import SubscriptionMarketplace from './SubscriptionMarketplace';
import { authRequest, postAuth } from './authApi';
import { CalendarClock, Plus, Clock3, FileText, Pencil, Trash2, X, RotateCcw, Search } from 'lucide-react';
import { PUBLISH_TIME, DAYS, koreaDate, validateSchedule, nextOccurrence, formatOccurrence, frequencyLabel } from './schedules';

export default function Scheduling({ newsletters, notify }) {
  const [schedules,setSchedules]=useState([]);
  const [marketplace,setMarketplace]=useState([]);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [editor,setEditor]=useState(null);
  const [filter,setFilter]=useState('all');
  const [query,setQuery]=useState('');
  const [undo,setUndo]=useState(null);
  const [now,setNow]=useState(()=>new Date());
  useEffect(()=>{const id=setInterval(()=>setNow(new Date()),60000);return()=>clearInterval(id);},[]);
  useEffect(()=>{
    let active=true;
    Promise.all([authRequest('/subscriptions'),authRequest('/subscriptions/marketplace')])
      .then(([own,market])=>{if(active){setSchedules(own);setMarketplace(market);}})
      .catch(err=>{if(active)setError(err.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[]);
  async function refresh() {
    try {const [own,market]=await Promise.all([authRequest('/subscriptions'),authRequest('/subscriptions/marketplace')]);setSchedules(own);setMarketplace(market);setError('');}
    catch(err){setError(err.message);}
  }
  function applyItem(item) {setSchedules(current=>[item,...current.filter(s=>s.id!==item.id)].filter(s=>s.status!=='cancelled'));}
  const available=new Map([...newsletters,...schedules.map(s=>s.newsletter),...(editor?.marketplaceSample?[editor.marketplaceSample]:[])].map(n=>[n.id,n]));
  const visible=schedules.filter(s=>(filter==='all'||(filter==='active'?s.active:!s.active))&&`${s.name} ${available.get(s.newsletterId)?.title||''}`.toLowerCase().includes(query.toLowerCase()));
  function settings(draft) {return {name:draft.name.trim(),frequency:draft.frequency,weekdays:draft.weekdays,month_day:draft.monthDay,start_date:draft.startDate};}
  async function commit(draft) {
    if(busy)return;
    setBusy(true);setError('');
    try {
      const item=editor.id
        ?await authRequest(`/subscriptions/${editor.id}/settings`,{method:'PUT',body:JSON.stringify(settings(draft))})
        :await postAuth('/subscriptions',{sample_id:draft.newsletterId,settings:settings(draft)});
      applyItem(item);setEditor(null);setUndo(null);notify('구독 설정을 저장했습니다.');await refresh();
    } finally {setBusy(false);}
  }
  async function changeStatus(item,status) {
    if(busy)return;
    setBusy(true);setError('');
    try {const updated=await authRequest(`/subscriptions/${item.id}/status`,{method:'PATCH',body:JSON.stringify({status})});applyItem(updated);setUndo(null);await refresh();}
    catch(err){setError(err.message);}finally{setBusy(false);}
  }
  async function remove(item) {
    if(busy)return;
    setBusy(true);setError('');
    try {const updated=await authRequest(`/subscriptions/${item.id}`,{method:'DELETE'});applyItem(updated);setUndo(item);await refresh();}
    catch(err){setError(err.message);}finally{setBusy(false);}
  }
  function subscribe(item) {
    if(busy)return;
    setEditor({newsletterId:item.id,name:item.topic.slice(0,80),marketplaceSample:item});
  }
  return <div className="scheduling-page">
    <section className="panel schedule-list-panel">
      <div className="section-title"><div><h2>내 구독 <span className="count">{schedules.length}</span></h2><p>저장된 뉴스레터를 기준으로 발행 주기를 설정하세요.</p></div><button className="button primary" disabled={loading||busy||!newsletters.length} onClick={()=>setEditor({})}><Plus size={15}/>구독 추가</button></div>
      {error&&<div className="error" role="alert">{error} <button className="button" disabled={busy} onClick={refresh}>다시 불러오기</button></div>}
      {loading&&<p role="status">구독을 불러오는 중입니다.</p>}
      {undo&&<div className="schedule-undo" role="status"><span>‘{undo.name}’ 구독을 삭제했습니다.</span><button disabled={busy} onClick={()=>changeStatus(undo,undo.status)}><RotateCcw size={12}/>되돌리기</button><button aria-label="삭제 알림 닫기" onClick={()=>setUndo(null)}><X size={13}/></button></div>}
      {loading?null:!newsletters.length&&!schedules.length?<div className="empty schedule-empty"><span className="large-schedule-icon"><FileText size={30}/></span><h3>먼저 뉴스레터를 보관함에 저장해 주세요</h3><p>저장된 뉴스레터를 선택하면 발행 주기를 설정할 수 있어요.</p></div>:<>
        <div className="schedule-toolbar"><div className="schedule-filters">{[['all','전체'],['active','구독 중'],['paused','일시정지']].map(([key,label])=><button key={key} className={filter===key?'active':''} onClick={()=>setFilter(key)}>{label}</button>)}</div><label className="schedule-search"><Search size={15}/><input aria-label="구독 검색" placeholder="구독 또는 뉴스레터 검색" value={query} onChange={e=>setQuery(e.target.value)}/></label></div>
        {visible.length?<div className="schedule-table-wrap"><table className="schedule-table"><thead><tr><th>구독 / 뉴스레터</th><th>발행 주기</th><th>다음 발행 예정 <small>KST</small></th><th>구독 상태</th><th>관리</th></tr></thead><tbody>{visible.map(item=>{
          const newsletter=available.get(item.newsletterId);
          return <tr key={item.id}><td><strong>{item.name}</strong><span className={!newsletter?'missing-newsletter':''}><FileText size={12}/>{newsletter?.title||'원본 뉴스레터를 찾을 수 없습니다'}</span></td><td><b>{frequencyLabel(item)}</b><small>오전 8시 · KST</small></td><td className="next-occurrence">{!newsletter?'원본 확인 필요':item.active?formatOccurrence(nextOccurrence(item,now)):'일시정지'}</td><td><button className="schedule-switch" role="switch" aria-checked={item.active} aria-label={`${item.name} 구독 상태`} disabled={busy||!newsletter} onClick={()=>changeStatus(item,item.active?'paused':'active')}><span/></button></td><td><div className="schedule-row-actions"><button className="icon-button" disabled={busy} aria-label={`${item.name} 수정`} onClick={()=>setEditor(item)}><Pencil size={15}/></button><button className="icon-button" disabled={busy} aria-label={`${item.name} 삭제`} onClick={()=>remove(item)}><Trash2 size={15}/></button></div></td></tr>;
        })}</tbody></table></div>:<div className="empty schedule-empty"><CalendarClock size={33}/><h3>{schedules.length?'조건에 맞는 구독이 없어요':'첫 번째 뉴스레터를 구독해 보세요'}</h3><p>{schedules.length?'검색어나 상태 필터를 변경해 주세요.':'뉴스레터와 반복 주기를 선택하면 예정 일정을 확인할 수 있어요.'}</p>{!schedules.length&&<button className="button" disabled={busy||loading} onClick={()=>setEditor({})}><Plus size={15}/>구독 추가</button>}</div>}
      </>}
      <div className="schedule-list-footer"><span>저장된 뉴스레터 {newsletters.length}개 · 자동 실행 이력은 아직 제공되지 않습니다.</span></div>
    </section>
    <SubscriptionMarketplace items={marketplace} loading={loading} busy={busy} onSubscribe={subscribe}/>
    {editor&&<ScheduleEditor initial={editor} newsletters={[...available.values()]} saving={busy} onClose={()=>{if(!busy)setEditor(null);}} onSave={commit}/>}
  </div>;
}

function ScheduleEditor({initial,newsletters,onClose,onSave,saving}) {
  const dialog=useRef(null);
  const [draft,setDraft]=useState(()=>({name:'',newsletterId:newsletters[0]?.id||'',frequency:'weekly',weekdays:[1],monthDay:1,active:true,...initial,startDate:initial.startDate||koreaDate(),time:PUBLISH_TIME}));
  const [error,setError]=useState('');
  const selected=newsletters.find(n=>n.id===draft.newsletterId);
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  const change=(key,value)=>{setDraft(current=>({...current,[key]:value}));setError('');};
  async function submit(e) {e.preventDefault();if(saving)return;const message=validateSchedule(draft)||(!selected?'뉴스레터를 다시 선택해 주세요.':'');if(message){setError(message);return;}try{await onSave(draft);}catch(err){setError(err.message);}}
  return <dialog ref={dialog} className="schedule-dialog" aria-labelledby="schedule-dialog-title" onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===dialog.current)onClose();}}>
    <div className="modal-head"><span className="modal-icon"><CalendarClock size={23}/></span><div><span className="eyebrow">PLAN YOUR TECH BRIEF</span><h2 id="schedule-dialog-title">{initial.id?'구독 수정':'구독 추가'}</h2><p>발행 주기를 정해 주세요. 발행 시간은 오전 8시(KST)입니다.</p></div><button className="icon-button" aria-label="구독 창 닫기" disabled={saving} onClick={onClose}><X size={19}/></button></div>
    <form onSubmit={submit} className="schedule-form">
      <div className="schedule-form-body">
        <label className="schedule-field">구독 이름<input autoFocus value={draft.name} maxLength={80} placeholder="예: 월요일 아침 AI 기술 브리핑" onChange={e=>change('name',e.target.value)}/></label>
        <label className="schedule-field">저장된 뉴스레터<select disabled={Boolean(initial.id||initial.marketplaceSample)||saving} value={draft.newsletterId} onChange={e=>change('newsletterId',e.target.value)}><option value="">뉴스레터를 선택해 주세요</option>{!selected&&draft.newsletterId&&<option value={draft.newsletterId}>원본 뉴스레터 없음 · 다시 선택해 주세요</option>}{newsletters.map(n=><option key={n.id} value={n.id}>{n.title} · {n.date}</option>)}</select></label>
        {selected&&<div className="selected-newsletter"><FileText size={17}/><div><strong>{selected.title}</strong><span>{selected.date} 저장 · 핵심 이슈 {selected.count}개</span>{selected.topic&&<span>주제 · {selected.topic}</span>}</div></div>}
        <div className="schedule-form-divider"/>
        <fieldset className="frequency-field"><legend>발행 주기</legend><div>{[['daily','매일'],['weekly','매주'],['monthly','매월']].map(([value,label])=><label className={draft.frequency===value?'selected':''} key={value}><input type="radio" name="frequency" value={value} checked={draft.frequency===value} onChange={()=>change('frequency',value)}/>{label}</label>)}</div></fieldset>
        {draft.frequency==='weekly'&&<fieldset className="weekdays-field"><legend>발행 요일 <span>여러 요일 선택 가능</span></legend><div>{[1,2,3,4,5,6,0].map(day=><button type="button" key={day} aria-label={`${DAYS[day]}요일`} aria-pressed={draft.weekdays.includes(day)} onClick={()=>change('weekdays',draft.weekdays.includes(day)?draft.weekdays.filter(d=>d!==day):[...draft.weekdays,day])}>{DAYS[day]}</button>)}</div></fieldset>}
        {draft.frequency==='monthly'&&<label className="schedule-field">매월 발행일<select value={draft.monthDay} onChange={e=>change('monthDay',Number(e.target.value))}>{Array.from({length:31},(_,i)=><option key={i} value={i+1}>{i+1}일</option>)}</select><small>해당 날짜가 없는 달에는 마지막 날을 기준으로 합니다.</small></label>}
        <label className="schedule-field">시작일<input type="date" value={draft.startDate} onChange={e=>change('startDate',e.target.value)}/></label>
        <p className="hint">뉴스는 이전 발행일(첫 발행은 시작일)부터 이번 발행일까지, 양쪽 날짜를 포함해 수집합니다.</p>
        <div className="schedule-preview"><Clock3 size={18}/><div><span>다음 발행 예정 · 한국 시간</span><strong>{draft.active?formatOccurrence(nextOccurrence({...draft,name:draft.name||'미리보기'})):'일시정지 상태로 저장됩니다'}</strong><p>일정 미리보기이며, 실제 자동 실행은 아직 제공되지 않습니다.</p></div></div>
        {error&&<p className="error" role="alert">{error}</p>}
      </div>
      <div className="modal-footer"><span/><button className="button" type="button" disabled={saving} onClick={onClose}>취소</button><button className="button primary" type="submit" disabled={saving}>{saving?'저장 중…':initial.id?'변경사항 저장':'구독 저장'}</button></div>
    </form>
  </dialog>;
}
