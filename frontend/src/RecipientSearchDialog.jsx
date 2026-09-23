import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Search, X, Plus, ArrowRight, UsersRound, UserRound, Check, Mail } from 'lucide-react';
import { authRequest, postAuth } from './authApi';
import './recipient-search.css';
import TeamAutocomplete from './TeamAutocomplete';

export default function RecipientSearchDialog({newsletter,onClose}) {
  const dialog=useRef(null);
  const [users,setUsers]=useState([]), [chosen,setChosen]=useState([]);
  const [team,setTeam]=useState(''), [name,setName]=useState('');
  const [filter,setFilter]=useState({team:'',name:''});
  const [loading,setLoading]=useState(true), [error,setError]=useState('');
  const [retry,setRetry]=useState(0);
  const [sending,setSending]=useState(false), [delivery,setDelivery]=useState(null);
  const sendRequest=useRef(null);
  const [locked,setLocked]=useState(false);
  const close=()=>{if(!sending)onClose();};
  async function send(){
    if(sending||delivery||!chosen.length)return;
    if(!sendRequest.current)sendRequest.current={request_id:globalThis.crypto?.randomUUID?.()||Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join(''),kind:newsletter.kind,newsletter_id:newsletter.id,user_ids:chosen.map(u=>u.user_id)};
    setSending(true);setLocked(true);setError('');
    try{setDelivery(await postAuth('/newsletter-email',sendRequest.current));}
    catch(e){setError(e.message);if(e.status&&e.status!==409&&e.status<500){sendRequest.current=null;setLocked(false);}}
    finally{setSending(false);}
  }
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('');
    authRequest('/users/directory',{signal:controller.signal}).then(setUsers).catch(e=>{if(!controller.signal.aborted)setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[retry]);
  const results=users.filter(u=>(u.team_name||'').includes(filter.team)&&((u.full_name||'').startsWith(filter.name)||u.employee_id.startsWith(filter.name)));
  const selected=new Set(chosen.map(u=>u.user_id));
  const available=results.filter(u=>u.email&&!selected.has(u.user_id));
  const add=people=>{
    const additions=people.filter(u=>!selected.has(u.user_id));
    if(chosen.length+additions.length>100){setError('한 번에 최대 100명까지 선택할 수 있습니다.');return;}
    setChosen(current=>[...current,...additions]);setError('');
  };
  const person=u=><div className="rs-person-text"><b>{u.full_name}<span>{u.role_name}</span></b><small>{u.team_name} · {u.employee_id}</small><small>{u.email||'이메일 미등록'}</small></div>;
  return createPortal(<dialog ref={dialog} className="rs-dialog" aria-labelledby="rs-title" onCancel={e=>{e.preventDefault();close();}}>
    <header className="rs-header"><div className="rs-title-icon"><Mail size={24}/></div><div><h2 id="rs-title">이메일 수신자 검색</h2><p><strong>{newsletter.title}</strong> · 수신자를 검색하고 선택하세요.</p></div><button className="rs-icon" onClick={close} disabled={sending} aria-label="검색 닫기"><X size={20}/></button></header>
    <form className="rs-filters" onSubmit={e=>{e.preventDefault();setFilter({team:team.trim(),name:name.trim()});}}>
      <TeamAutocomplete value={team} onChange={setTeam} teams={users.map(u=>u.team_name)}/>
      <label>이름 / 사번<input value={name} onChange={e=>setName(e.target.value)} maxLength={120} autoComplete="off" onKeyDown={e=>{if(e.key==='Enter'&&e.nativeEvent.isComposing)e.preventDefault();}}/></label>
      <button className="rs-primary" disabled={loading}><Search size={16}/>조회</button><button type="button" className="rs-secondary" onClick={()=>{setTeam('');setName('');setFilter({team:'',name:''});}}>초기화</button>
    </form>
    {error&&<div className="rs-error" role="alert">{error} {!locked&&<button className="rs-link" onClick={()=>setRetry(n=>n+1)}>다시 불러오기</button>}</div>}
    <div className="rs-columns">
      <section className="rs-results" aria-label="검색 결과"><div className="rs-panel-heading"><h3>검색 결과 <span>{loading?'…':results.length}</span></h3><button className="rs-link" disabled={loading||locked||!available.length} onClick={()=>add(available)}>전체 담기<ArrowRight size={14}/></button></div>
        <div className="rs-list" aria-busy={loading}>{loading?<p className="rs-empty" role="status">사용자를 불러오는 중입니다…</p>:!results.length?<p className="rs-empty">검색 결과가 없습니다.</p>:results.map(u=><div className={`rs-person ${selected.has(u.user_id)?'is-picked':''}`} key={u.user_id}><span className="rs-avatar"><UserRound size={18}/></span>{person(u)}<button className="rs-pick" disabled={locked||!u.email||selected.has(u.user_id)} aria-label={`${u.full_name} ${u.employee_id} 담기`} onClick={()=>add([u])}>{!u.email?'이메일 없음':selected.has(u.user_id)?<><Check size={13}/>선택됨</>:<><Plus size={14}/>담기</>}</button></div>)}</div>
      </section>
      <section className="rs-selected" aria-label="선택한 수신자"><div className="rs-panel-heading"><h3>선택한 수신자 <span>{chosen.length}</span></h3><button className="rs-link" disabled={locked||!chosen.length} onClick={()=>setChosen([])}>전체 비우기</button></div><div className="rs-list">{!chosen.length?<div className="rs-empty"><UsersRound size={30}/><p>왼쪽에서 수신자를 담아 주세요.</p></div>:chosen.map(u=><div className="rs-person" key={u.user_id}>{person(u)}<button className="rs-icon" disabled={locked} aria-label={`${u.full_name} ${u.employee_id} 선택 취소`} onClick={()=>setChosen(current=>current.filter(p=>p.user_id!==u.user_id))}><X size={16}/></button></div>)}</div></section>
    </div>
    {delivery&&<div className="rs-delivery-result" role="status"><strong>발송 완료 {delivery.results.filter(r=>r.status==='sent').length}명</strong>{delivery.results.some(r=>r.status!=='sent')&&<><p>실패 {delivery.results.filter(r=>r.status==='failed').length}명 · 결과 확인 필요 {delivery.results.filter(r=>r.status==='unknown').length}명</p>{delivery.results.filter(r=>r.status!=='sent').map(r=><p key={r.user_id}>{r.name} · {r.status==='failed'?'발송 실패':'수신 여부를 확인해 주세요. 중복 방지를 위해 자동 재발송하지 않습니다.'}</p>)}</>}</div>}
    <footer className="rs-footer"><span>선택한 수신자 <b aria-live="polite">{chosen.length} / 100명</b> · 한 통으로 발송{sending&&<span role="status"> · 메일 발송 중…</span>}</span><button className="rs-secondary" onClick={close} disabled={sending}>닫기</button><button className="rs-primary" onClick={send} disabled={sending||loading||!chosen.length||Boolean(delivery)}><Mail size={16}/>{sending?'발송 중…':delivery?'발송 처리 완료':locked?'발송 결과 확인':'메일 보내기'}</button></footer>
  </dialog>,document.body);
}
