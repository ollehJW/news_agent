import React, { useEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown, Mail } from 'lucide-react';
export default function SubscriptionSelect({subscriptions,value,onChange,disabled}) {
  const id=useId(), root=useRef(null), trigger=useRef(null);
  const [open,setOpen]=useState(false), [active,setActive]=useState(0);
  const options=[{id:'',name:'전체 구독'},...subscriptions.map(s=>({...s,name:`${s.name}${s.status==='cancelled'?' (해지)':s.status==='paused'?' (일시정지)':''}`}))];
  const selected=Math.max(0,options.findIndex(s=>s.id===value));
  useEffect(()=>{if(disabled)setOpen(false);},[disabled]);
  useEffect(()=>{
    if(!open)return;
    const close=e=>{if(!root.current?.contains(e.target))setOpen(false);};
    document.addEventListener('pointerdown',close);
    return()=>document.removeEventListener('pointerdown',close);
  },[open]);
  useEffect(()=>{if(open)document.getElementById(`${id}-${active}`)?.scrollIntoView({block:'nearest'});},[open,active,id]);
  function choose(index){onChange(options[index].id);setOpen(false);trigger.current?.focus();}
  function keyDown(e){
    if(['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(e.key)){
      e.preventDefault();
      if(!open){setActive(e.key==='Home'?0:e.key==='End'?options.length-1:selected);setOpen(true);return;}
      if(e.key==='Enter'||e.key===' '){choose(active);return;}
      setActive(i=>e.key==='Home'?0:e.key==='End'?options.length-1:Math.max(0,Math.min(options.length-1,i+(e.key==='ArrowDown'?1:-1))));
    }else if(e.key==='Escape'){e.preventDefault();setOpen(false);}
    else if(e.key==='Tab')setOpen(false);
  }
  return <div className="archive-subscription-filter">
    <span id={`${id}-label`} className="archive-filter-label">구독 뉴스레터</span>
    <div ref={root} className={`archive-select-wrap ${open?'is-open':''}`} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setOpen(false);}}>
      <button ref={trigger} type="button" className="archive-select-trigger" role="combobox" aria-labelledby={`${id}-label ${id}-value`} aria-expanded={open} aria-controls={`${id}-list`} aria-haspopup="listbox" aria-activedescendant={open?`${id}-${active}`:undefined} disabled={disabled} onKeyDown={keyDown} onClick={()=>{setActive(selected);setOpen(v=>!v);}}>
        <Mail size={17} aria-hidden="true"/><span id={`${id}-value`}>{options[selected].name}</span><ChevronDown size={16} className="archive-dropdown-chevron" aria-hidden="true"/>
      </button>
      {open&&<div id={`${id}-list`} role="listbox" aria-labelledby={`${id}-label`} className="archive-select-options">
        {options.map((option,index)=><div key={option.id} id={`${id}-${index}`} role="option" aria-selected={option.id===value} className={`archive-select-option ${active===index?'is-active':''}`} onPointerMove={()=>setActive(index)} onMouseDown={e=>e.preventDefault()} onClick={()=>choose(index)}><span>{option.name}</span>{option.id===value&&<Check size={16} aria-hidden="true"/>}</div>)}
      </div>}
    </div>
  </div>;
}
