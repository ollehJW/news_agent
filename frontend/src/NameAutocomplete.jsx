import React, { useId, useState } from 'react';
import { Check, Search } from 'lucide-react';

const normalize = value => value.normalize('NFKC').replace(/\s/g, '').toLowerCase();
export default function NameAutocomplete({label,value,onChange,options}) {
  const id=useId();const [open,setOpen]=useState(false);const [active,setActive]=useState(-1);
  const query=normalize(value);
  const matching=options.filter(item=>normalize(item.name)!=='미지정'&&normalize(item.name).startsWith(query)).slice(0,8);
  const exact=options.some(item=>normalize(item.name)===query);
  const expanded=open&&matching.length>0;
  function select(name){onChange(name);setOpen(false);setActive(-1);}
  function keydown(e){
    if(e.nativeEvent.isComposing)return;
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){
      e.preventDefault();setOpen(true);
      setActive(current=>matching.length?(e.key==='ArrowDown'?(current+1)%matching.length:(current<=0?matching.length:current)-1):-1);
    }else if(e.key==='Enter'&&expanded&&active>=0&&matching[active]){
      e.preventDefault();select(matching[active].name);
    }else if(e.key==='Escape'){e.preventDefault();setOpen(false);setActive(-1);}
  }
  return <div className="name-autocomplete">
    <label htmlFor={id}>{label}</label>
    <div className="name-input-wrap"><input id={id} role="combobox" aria-autocomplete="list" aria-expanded={expanded} aria-controls={`${id}-options`} aria-activedescendant={expanded&&active>=0?`${id}-option-${active}`:undefined} aria-describedby={`${id}-hint`} autoComplete="off" required maxLength={80} value={value} onFocus={()=>setOpen(true)} onBlur={()=>{setOpen(false);setActive(-1);}} onChange={e=>{onChange(e.target.value);setOpen(true);setActive(-1);}} onKeyDown={keydown}/><Search size={16}/></div>
    {expanded&&<div className="name-options" id={`${id}-options`} role="listbox" aria-label={`${label} 추천`}>{matching.map((item,i)=><div key={item.name} id={`${id}-option-${i}`} role="option" aria-selected={i===active} className={i===active?'active':''} onMouseDown={e=>e.preventDefault()} onMouseEnter={()=>setActive(i)} onClick={()=>select(item.name)}><span>{item.name}</span>{normalize(item.name)===query&&<Check size={15}/>}</div>)}</div>}
    <small id={`${id}-hint`}>{value.trim()&&!exact?'계정 생성 시 새 항목으로 등록됩니다.':'등록된 항목을 선택하거나 새 이름을 입력하세요.'}</small>
  </div>;
}
