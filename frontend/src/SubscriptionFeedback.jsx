import React,{useEffect,useRef,useState} from 'react';
import {X,MessageSquareText,Loader2,Send} from 'lucide-react';
import {postAuth} from './authApi';
import './feedback.css';

export default function SubscriptionFeedback({item,onClose,onSent}){
 const ref=useRef(null),request=useRef(null);
 const [content,setContent]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{const previous=document.activeElement;ref.current.showModal();return()=>previous?.focus();},[]);
 async function submit(e){e.preventDefault();if(busy)return;setBusy(true);setError('');
  if(!request.current||request.current.content!==content.trim())request.current={request_id:crypto.randomUUID(),content:content.trim()};
  try{await postAuth(`/subscriptions/${item.id}/feedback`,request.current);onSent();}catch(e){setError(e.message);}finally{setBusy(false);}
 }
 return <dialog ref={ref} className="feedback-dialog" aria-labelledby="feedback-title" onCancel={e=>{e.preventDefault();if(!busy)onClose();}}><div className="feedback-dialog-head"><span className="feedback-mark"><MessageSquareText size={23}/></span><div><h2 id="feedback-title">수집 조건 변경 요청</h2><p>{item.name}</p></div><button className="icon-button" disabled={busy} aria-label="피드백 닫기" onClick={onClose}><X size={20}/></button></div>
 <form onSubmit={submit}><div className="feedback-guide"><strong>어떤 내용을 요청하면 되나요?</strong><ul><li><b>쿼리 추가·제거</b> — 더 찾아보고 싶은 검색어 또는 제외하고 싶은 검색어</li><li><b>도메인 추가·제거</b> — 수집할 사이트 주소 또는 제외할 사이트 주소</li><li><b>변경 이유</b> — 놓치는 소식, 관련 없는 기사 등 개선이 필요한 점</li></ul><p>예: 쿼리 ‘AI agent benchmarks’를 추가해 주세요. 성능 평가 소식이 부족합니다.<br/>도메인 example.com은 광고성 기사가 많아 제외를 요청합니다.</p></div>
 <details className="feedback-current"><summary>현재 쿼리·도메인 확인</summary><p><b>쿼리</b><br/>{item.newsletter?.queries?.join(' / ')||'등록된 쿼리 없음'}</p><p><b>도메인</b><br/>{item.newsletter?.search_all_domains?'전체 도메인 검색':item.newsletter?.domains?.join(', ')||'등록된 도메인 없음'}</p></details>
 <label className="feedback-input">요청 내용<textarea autoFocus required minLength={10} maxLength={4000} rows={7} value={content} disabled={busy} onChange={e=>setContent(e.target.value)} placeholder={'변경 대상: 쿼리 또는 도메인\n요청 사항: 추가 / 제거할 항목\n변경 이유:'}/></label><div className="feedback-helper"><span>관리자가 검토한 뒤 계정 이메일로 결과를 안내합니다.</span><span>{content.length} / 4,000</span></div>{error&&<p className="auth-error" role="alert">{error}</p>}<footer className="feedback-actions"><button type="button" className="button" disabled={busy} onClick={onClose}>취소</button><button className="button primary" disabled={busy||content.trim().length<10}>{busy?<Loader2 className="spin" size={16}/>:<Send size={16}/>}요청 보내기</button></footer></form></dialog>;
}
