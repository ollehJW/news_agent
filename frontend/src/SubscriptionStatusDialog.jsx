import React,{useEffect,useRef,useState} from 'react';
import {X,UserRound,UsersRound} from 'lucide-react';
import './subscription-cancel.css';

export default function SubscriptionStatusDialog({item,busy,onClose,onConfirm}) {
  const dialog=useRef(null),members=item.members||[],self=members.find(m=>m.is_self);
  const [status,setStatus]=useState(item.active?'paused':'active');
  const [mode,setMode]=useState(self?'self':'selected'),[selected,setSelected]=useState([]),[error,setError]=useState('');
  const action=status==='paused'?'일시정지':'재개';
  const eligible=members.filter(m=>m.status!==status);
  const ids=mode==='self'?(self&&self.status!==status?[self.member_id]:[]):selected.filter(id=>eligible.some(m=>m.member_id===id));
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  async function confirm(){if(busy||!ids.length)return;setError('');try{await onConfirm(ids,status);}catch(e){setError(e.message);}}
  return <dialog ref={dialog} className="subscription-cancel-dialog" aria-labelledby="status-sub-title" onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>
    <div className="modal-head"><div><h2 id="status-sub-title">구독 수신 상태 변경</h2><p>{item.name}</p></div><button className="icon-button" disabled={busy} onClick={onClose} aria-label="수신 상태 창 닫기"><X size={19}/></button></div>
    <div className="subscription-cancel-body">
      <div className="schedule-filters" role="group" aria-label="변경할 수신 상태" style={{marginBottom:20}}>{[['paused','OFF · 일시정지'],['active','ON · 수신 재개']].map(([value,label])=><button key={value} disabled={busy} className={status===value?'active':''} aria-pressed={status===value} onClick={()=>{setStatus(value);setSelected([]);setError('');}}>{label}</button>)}</div>
      <div className="subscription-cancel-modes" role="group" aria-label="변경 대상">
        <button disabled={busy||!self} aria-pressed={mode==='self'} onClick={()=>setMode('self')}><UserRound size={19}/><strong>나만 {action}</strong><small>{self?`현재 ${self.status==='paused'?'OFF · 일시정지':'ON · 수신 중'}`:'본인은 수신 목록에 없습니다'}</small></button>
        {item.can_manage!==false&&<button disabled={busy||!members.length} aria-pressed={mode==='selected'} onClick={()=>setMode('selected')}><UsersRound size={19}/><strong>선택한 멤버 {action}</strong><small>변경할 사람을 직접 선택합니다</small></button>}
      </div>
      {mode==='selected'&&<div className="cancel-member-list">{members.map(m=><label key={m.member_id}><input type="checkbox" disabled={busy||m.status===status} checked={ids.includes(m.member_id)} onChange={()=>setSelected(current=>current.includes(m.member_id)?current.filter(id=>id!==m.member_id):[...current,m.member_id])}/><span><strong>{m.full_name}{m.is_self?' (나)':''} · {m.status==='paused'?'OFF':'ON'}</strong><small>{m.email} · {m.member_type==='external'?'기타':'임직원'}</small></span></label>)}</div>}
      <p className="hint">{status==='paused'?'선택한 멤버의 메일 수신만 잠시 멈춥니다. 언제든 다시 켤 수 있습니다.':'선택한 멤버가 다음 발행부터 메일을 받습니다.'}</p>
      {error&&<p className="error" role="alert">{error}</p>}
    </div>
    <div className="modal-footer"><span>{ids.length}명 선택</span><button className="button" disabled={busy} onClick={onClose}>닫기</button><button className="button primary" disabled={busy||!ids.length} onClick={confirm}>{busy?'처리 중…':`수신 ${action}`}</button></div>
  </dialog>;
}
