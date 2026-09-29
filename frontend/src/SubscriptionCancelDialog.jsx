import React,{useEffect,useRef,useState} from 'react';
import {X,UserRound,UsersRound} from 'lucide-react';
import './subscription-cancel.css';

export default function SubscriptionCancelDialog({item,busy,onClose,onConfirm}) {
  const dialog=useRef(null),members=item.members||[],self=members.find(m=>m.is_self);
  const [mode,setMode]=useState(self?'self':'selected'),[selected,setSelected]=useState([]),[error,setError]=useState('');
  const ids=mode==='self'?(self?[self.member_id]:[]):selected;
  useEffect(()=>{const previous=document.activeElement;dialog.current.showModal();return()=>previous?.focus();},[]);
  async function confirm(){if(busy)return;setError('');try{await onConfirm(ids);}catch(e){setError(e.message);}}
  return <dialog ref={dialog} className="subscription-cancel-dialog" aria-labelledby="cancel-sub-title" onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>
    <div className="modal-head"><div><h2 id="cancel-sub-title">구독 수신 해제</h2><p>{item.name}</p></div><button className="icon-button" disabled={busy} onClick={onClose} aria-label="수신 해제 창 닫기"><X size={19}/></button></div>
    <div className="subscription-cancel-body">
      <div className="subscription-cancel-modes" role="group" aria-label="해제 대상">
        <button disabled={busy||!self} aria-pressed={mode==='self'} onClick={()=>setMode('self')}><UserRound size={19}/><strong>나만 수신 해제</strong><small>{self?'다른 멤버는 계속 받습니다':'본인은 수신 목록에 없습니다'}</small></button>
        <button disabled={busy||!members.length} aria-pressed={mode==='selected'} onClick={()=>setMode('selected')}><UsersRound size={19}/><strong>선택한 멤버 수신 해제</strong><small>해제할 사람을 직접 선택합니다</small></button>
      </div>
      {mode==='selected'&&members.length>0&&<div className="cancel-member-list">{members.map(m=><label key={m.member_id}><input type="checkbox" disabled={busy} checked={selected.includes(m.member_id)} onChange={()=>setSelected(current=>current.includes(m.member_id)?current.filter(id=>id!==m.member_id):[...current,m.member_id])}/><span><strong>{m.full_name}{m.is_self?' (나)':''}</strong><small>{m.email} · {m.member_type==='external'?'기타':'임직원'}</small></span></label>)}</div>}
      <p className="hint">{!members.length?'수신 멤버가 없는 구독입니다. 구독을 종료할 수 있습니다.':ids.length===members.length?'모든 수신 멤버가 해제되어 구독이 종료됩니다.':'선택한 멤버만 수신 목록에서 제외됩니다. 구독 관리 권한은 유지됩니다.'}</p>
      {error&&<p className="error" role="alert">{error}</p>}
    </div>
    <div className="modal-footer"><span>{ids.length}명 선택</span><button className="button" disabled={busy} onClick={onClose}>닫기</button><button className="button primary" disabled={busy||(members.length>0&&!ids.length)} onClick={confirm}>{busy?'처리 중…':members.length?'수신 해제':'구독 종료'}</button></div>
  </dialog>;
}
