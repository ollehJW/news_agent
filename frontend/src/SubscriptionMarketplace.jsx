import React, { useState } from 'react';
import { Store, Search, Users, CalendarClock, Check, Plus, Loader2 } from 'lucide-react';
import { frequencyLabel } from './schedules';

export default function SubscriptionMarketplace({ items = [], loading = false, pendingId = null, onSubscribe }) {
  const [query, setQuery] = useState('');
  const visible = items.filter(item => `${item.name} ${item.topic} ${(item.domains || []).join(' ')}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return <section className="panel marketplace-panel" aria-labelledby="marketplace-title">
    <div className="section-title"><div><h2 id="marketplace-title"><Store size={20}/>구독 마켓플레이스 <span className="count">{items.length}</span></h2><p>다른 사용자가 구독한 뉴스레터를 찾아 함께 받아보세요.</p></div></div>
    <label className="schedule-search marketplace-search"><Search size={16}/><input aria-label="마켓플레이스 검색" placeholder="뉴스레터, 주제, 도메인 검색" value={query} onChange={e=>setQuery(e.target.value)}/></label>
    {loading ? <div className="empty" role="status"><Loader2 size={25} className="spin"/><p>구독 가능한 뉴스레터를 불러오고 있어요.</p></div> : visible.length ? <div className="marketplace-grid">{visible.map(item => <article className="marketplace-card" key={item.id}>
      <div className="marketplace-card-heading"><span className="tile-icon"><Store size={20}/></span>{item.subscribed&&<span className="marketplace-subscribed"><Check size={13}/>구독 중</span>}</div>
      <h3>{item.name}</h3><p className="marketplace-topic">{item.topic}</p>
      <div className="marketplace-domains">{(item.domains||[]).slice(0,3).map(host=><span key={host}>{host}</span>)}{item.domains?.length>3&&<span>+{item.domains.length-3}</span>}</div>
      <div className="marketplace-details"><span><CalendarClock size={15}/>{frequencyLabel(item)} · 오전 8시 KST</span><span><Users size={15}/>구독자 {item.subscriberCount}명</span></div>
      <button className={`button ${item.subscribed?'':'primary'}`} disabled={item.subscribed||pendingId!==null} onClick={()=>onSubscribe?.(item)}>{pendingId===item.id?<Loader2 size={15} className="spin"/>:item.subscribed?<Check size={15}/>:<Plus size={15}/>} {item.subscribed?'구독 중':'함께 구독하기'}</button>
    </article>)}</div> : <div className="empty marketplace-empty"><Store size={32}/><h3>{query?'검색 결과가 없어요':'아직 등록된 구독 뉴스레터가 없어요'}</h3><p>{query?'다른 뉴스레터 이름이나 주제로 검색해 보세요.':'구독 이력이 있는 뉴스레터가 이곳에 표시됩니다.'}</p></div>}
  </section>;
}
