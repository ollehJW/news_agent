import React, { useId, useState, useEffect } from 'react';
import { Building2, Check } from 'lucide-react';

export default function TeamAutocomplete({value,onChange,teams}) {
  const id=useId();
  const [open,setOpen]=useState(false), [active,setActive]=useState(-1);
  const prefix=value.trim();
  const matches=[...new Set(teams.filter(Boolean))].filter(team=>team.startsWith(prefix)).sort((a,b)=>a.localeCompare(b,'ko'));
  const visible=open&&Boolean(prefix);
  useEffect(()=>{if(visible&&active>=0)document.getElementById(`${id}-${active}`)?.scrollIntoView({block:'nearest'});},[active,visible,id]);
  function choose(team){onChange(team);setOpen(false);setActive(-1);}
  function keyDown(e){
    if(e.nativeEvent.isComposing||e.keyCode===229){if(e.key==='Enter')e.preventDefault();return;}
    if(e.key==='Escape'&&visible){e.preventDefault();e.stopPropagation();setOpen(false);return;}
    if((e.key==='ArrowDown'||e.key==='ArrowUp')&&prefix&&matches.length){
      e.preventDefault();setOpen(true);setActive(i=>Math.max(0,Math.min(matches.length-1,i+(e.key==='ArrowDown'?1:-1))));
    }else if(e.key==='Enter'&&visible&&active>=0&&matches[active]){e.preventDefault();choose(matches[active]);}
    else if(e.key==='Enter'||e.key==='Tab')setOpen(false);
  }
  return <div className="rs-team-field">
    <label htmlFor={id}>소속 팀</label>
    <div className={`rs-team-autocomplete ${visible?'is-open':''}`}>
      <input id={id} role="combobox" aria-autocomplete="list" aria-expanded={visible} aria-controls={`${id}-list`} aria-activedescendant={visible&&active>=0?`${id}-${active}`:undefined} value={value} onChange={e=>{onChange(e.target.value);setActive(-1);setOpen(true);}} onFocus={()=>setOpen(true)} onBlur={()=>setOpen(false)} onKeyDown={keyDown} maxLength={120} autoComplete="off"/>
      {visible&&<div className="rs-team-suggestions">
        <div className="rs-team-suggestion-heading">추천 소속 팀 <span>{matches.length}</span></div>
        <div id={`${id}-list`} role="listbox" aria-label="소속 팀 추천" className="rs-team-options">
          {matches.map((team,index)=><div key={team} id={`${id}-${index}`} role="option" aria-selected={value===team} className={`rs-team-option ${active===index?'is-active':''}`} onPointerMove={()=>setActive(index)} onMouseDown={e=>e.preventDefault()} onClick={()=>choose(team)}><Building2 size={16} aria-hidden="true"/><span><strong>{team.slice(0,prefix.length)}</strong>{team.slice(prefix.length)}</span>{value===team&&<Check size={15} aria-hidden="true"/>}</div>)}
        </div>
        {!matches.length&&<p className="rs-team-no-results" role="status">일치하는 소속 팀이 없습니다.</p>}
      </div>}
    </div>
  </div>;
}
