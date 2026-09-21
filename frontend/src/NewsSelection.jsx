import React from 'react';
import { Check, Plus, Eye, ExternalLink, Loader2, X } from 'lucide-react';

const weights = [['기술적 중요성', 40], ['기술 주체 경쟁력', 30], ['파급력', 30]];

export default function NewsSelection({ candidates, selected, busy, progress=0, progressMessage='', collectionStats=null, disabled=false, onToggle }) {
  return <section className="panel result-panel">
    <div className="selection-heading">
      <h2>수집한 뉴스 <span className="count">{busy ? '—' : candidates.length}</span></h2>
      <span aria-live="polite">최종 후보 <b>{selected.length}개</b> 선택</span>
      <p>중복을 제외한 뉴스입니다. 상위 5개가 기본 선택되며, 선택 버튼으로 최종 후보를 변경할 수 있습니다.</p>
    </div>
    {busy ? <div className="empty" role="status"><Loader2 size={32} className="spin"/><h3>{progressMessage||'Agent가 뉴스를 분석하고 있습니다'}</h3><ol className="collection-stage-list">{['뉴스 수집','주제 확인·중복 통합','중요도 평가'].map((label,i)=><li key={label} className={i===progress?'active':i<progress?'done':''}>{i<progress?<Check size={14}/>:<span>{i+1}</span>}{label}</li>)}</ol></div>
      : !candidates.length?<div className="empty"><h3>선정할 뉴스가 없습니다</h3><p>수집 기간이나 쿼리·도메인을 조정해 다시 수집해 주세요.</p></div>: candidates.map(n => <article className={`news-row selectable-news ${selected.some(item => item.id === n.id) ? 'is-selected' : ''}`} key={n.id}>
        <label className="news-select-control" title={selected.some(item => item.id === n.id) ? '최종 후보에서 제외' : '최종 후보에 추가'}>
          <input className="news-checkbox" type="checkbox" disabled={disabled} aria-label={`${n.title} 선택`} checked={selected.some(item => item.id === n.id)} onChange={() => onToggle(n.id)}/>
          <span className="news-select-indicator" aria-hidden="true"><Check className="selected-mark" size={17} strokeWidth={2.5}/><Plus className="unselected-mark" size={17}/></span>
        </label>
        <div className="news-copy">
          <h3>{n.title}</h3>
          <div className="news-source"><span className="news-host" title={n.host}>{n.host}</span><time dateTime={n.date}>{n.date}</time><a href={n.url} target="_blank" rel="noreferrer">기사 원문<ExternalLink size={12}/></a></div>
        </div>
        <div className="news-actions">
          <button className="score score-trigger summary-trigger" popoverTarget={`summary-${n.id}`} aria-label={`${n.title} 요약 보기`}><Eye size={24}/><span>요약 보기</span></button>
          <button className="score score-trigger" popoverTarget={`reason-${n.id}`} aria-label={`중요도 ${n.score}점 추천 이유 보기`}><b>{n.score}</b><span>중요도 점수</span></button>
        </div>
        <div className="score-popover summary-popover" id={`summary-${n.id}`} popover="auto" role="dialog" aria-labelledby={`summary-title-${n.id}`}>
          <header><h3 id={`summary-title-${n.id}`}>기사 요약</h3><button popoverTarget={`summary-${n.id}`} popoverTargetAction="hide" aria-label="기사 요약 닫기"><X size={18}/></button></header>
          <p className="reason-news-title">{n.title}</p>
          {n.imageUrl&&<React.Fragment key={n.imageUrl}>
            <button className="summary-image-button" popoverTarget={`image-${n.id}`} aria-label={`${n.title} 이미지 원본 크기로 보기`} title="클릭하여 원본 크기로 보기">
              <img className="summary-article-image" src={n.imageUrl} alt={n.imageAlt||n.title} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={event=>{event.currentTarget.parentElement.hidden=true;}}/>
            </button>
            <div className="article-image-viewer" id={`image-${n.id}`} popover="auto" role="dialog" aria-label="기사 이미지 원본 크기">
              <header><strong>원본 이미지</strong><button popoverTarget={`image-${n.id}`} popoverTargetAction="hide" aria-label="원본 이미지 닫기"><X size={20}/></button></header>
              <div className="article-image-scroll"><img src={n.imageUrl} alt={n.imageAlt||n.title} loading="lazy" referrerPolicy="no-referrer"/></div>
            </div>
          </React.Fragment>}
          <p className="summary-article-text">{n.summary}</p>
        </div>
        <div className="score-popover" id={`reason-${n.id}`} popover="auto" role="dialog" aria-labelledby={`reason-title-${n.id}`}>
          <header><h3 id={`reason-title-${n.id}`}>추천 이유 <span>{n.score}점</span></h3><button popoverTarget={`reason-${n.id}`} popoverTargetAction="hide" aria-label="추천 이유 닫기"><X size={18}/></button></header>
          <dl>{weights.map(([label, weight], i) => <div key={label}><dt title={label==='기술 주체 경쟁력'?'보도 매체가 아닌 개발기업·연구주체의 규모, 기술력, 연구 성과 및 시장 경쟁력':undefined}>{label} <small>{weight}%</small></dt><dd>{n.scores[i]}점</dd></div>)}</dl>
        </div>
      </article>)}
  </section>;
}
