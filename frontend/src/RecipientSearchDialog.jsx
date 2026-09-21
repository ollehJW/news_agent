import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Search, X, Plus, ArrowRight, UsersRound, UserRound, Check, Mail } from 'lucide-react';
import { authRequest } from './authApi';
import './recipient-search.css';
import TeamAutocomplete from './TeamAutocomplete';

export default function RecipientSearchDialog({newsletter,onClose}) {
  const dialog=useRef(null);
  const [users,setUsers]=useState([]), [chosen,setChosen]=useState([]);
  const [team,setTeam]=useState(''), [name,setName]=useState('');
  const [filter,setFilter]=useState({team:'',name:''});
  const [loading,setLoading]=useState(true), [error,setError]=useState('');
  const [retry,setRetry]=useState(0);
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('');
    authRequest('/users/directory',{signal:controller.signal}).then(setUsers).catch(e=>{if(!controller.signal.aborted)setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[retry]);
  const results=users.filter(u=>(u.team_name||'').includes(filter.team)&&((u.full_name||'').startsWith(filter.name)||u.employee_id.startsWith(filter.name)));
  const selected=new Set(chosen.map(u=>u.user_id));
  const available=results.filter(u=>!selected.has(u.user_id));
  const add=people=>setChosen(current=>{const ids=new Set(current.map(u=>u.user_id));return [...current,...people.filter(u=>!ids.has(u.user_id))];});
  const person=u=><div className="rs-person-text"><b>{u.full_name}<span>{u.role_name}</span></b><small>{u.team_name} · {u.employee_id}</small><small>{u.email||'이메일 미등록'}</small></div>;
  return createPortal(<dialog ref={dialog} className="rs-dialog" aria-labelledby="rs-title" onCancel={e=>{e.preventDefault();onClose();}}>
    <header className="rs-header"><div className="rs-title-icon"><Mail size={24}/></div><div><h2 id="rs-title">이메일 수신자 검색</h2><p><strong>{newsletter.title}</strong> · 수신자를 검색하고 선택하세요.</p></div><button className="rs-icon" onClick={onClose} aria-label="검색 닫기"><X size={20}/></button></header>
    <form className="rs-filters" onSubmit={e=>{e.preventDefault();setFilter({team:team.trim(),name:name.trim()});}}>
      <TeamAutocomplete value={team} onChange={setTeam} teams={users.map(u=>u.team_name)}/>
      <label>이름 / 사번<input value={name} onChange={e=>setName(e.target.value)} maxLength={120} autoComplete="off" onKeyDown={e=>{if(e.key==='Enter'&&e.nativeEvent.isComposing)e.preventDefault();}}/></label>
      <button className="rs-primary" disabled={loading}><Search size={16}/>조회</button><button type="button" className="rs-secondary" onClick={()=>{setTeam('');setName('');setFilter({team:'',name:''});}}>초기화</button>
    </form>
    {error&&<div className="rs-error" role="alert">{error} <button className="rs-link" onClick={()=>setRetry(n=>n+1)}>다시 불러오기</button></div>}
    <div className="rs-columns">
      <section className="rs-results" aria-label="검색 결과"><div className="rs-panel-heading"><h3>검색 결과 <span>{loading?'…':results.length}</span></h3><button className="rs-link" disabled={loading||!available.length} onClick={()=>add(available)}>전체 담기<ArrowRight size={14}/></button></div>
        <div className="rs-list" aria-busy={loading}>{loading?<p className="rs-empty" role="status">사용자를 불러오는 중입니다…</p>:!results.length?<p className="rs-empty">검색 결과가 없습니다.</p>:results.map(u=><div className={`rs-person ${selected.has(u.user_id)?'is-picked':''}`} key={u.user_id}><span className="rs-avatar"><UserRound size={18}/></span>{person(u)}<button className="rs-pick" disabled={selected.has(u.user_id)} aria-label={`${u.full_name} ${u.employee_id} 담기`} onClick={()=>add([u])}>{selected.has(u.user_id)?<><Check size={13}/>선택됨</>:<><Plus size={14}/>담기</>}</button></div>)}</div>
      </section>
      <section className="rs-selected" aria-label="선택한 수신자"><div className="rs-panel-heading"><h3>선택한 수신자 <span>{chosen.length}</span></h3><button className="rs-link" disabled={!chosen.length} onClick={()=>setChosen([])}>전체 비우기</button></div><div className="rs-list">{!chosen.length?<div className="rs-empty"><UsersRound size={30}/><p>왼쪽에서 수신자를 담아 주세요.</p></div>:chosen.map(u=><div className="rs-person" key={u.user_id}>{person(u)}<button className="rs-icon" aria-label={`${u.full_name} ${u.employee_id} 선택 취소`} onClick={()=>setChosen(current=>current.filter(p=>p.user_id!==u.user_id))}><X size={16}/></button></div>)}</div></section>
    </div>
    <footer className="rs-footer"><span>선택한 수신자 <b aria-live="polite">{chosen.length}명</b> · 현재는 검색·선택 미리보기입니다.</span><button className="rs-secondary" onClick={onClose}>닫기</button></footer>
  </dialog>,document.body);
}
