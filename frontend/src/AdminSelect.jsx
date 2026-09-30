import React, {useEffect,useId,useRef,useState} from 'react';
import {Check,ChevronDown} from 'lucide-react';

export default function AdminSelect({label,value,options,onChange}) {
  const id=useId(),root=useRef(null),trigger=useRef(null),typed=useRef({text:'',at:0});
  const [open,setOpen]=useState(false),[active,setActive]=useState(0);
  const selected=Math.max(0,options.findIndex(o=>o.value===value));
  const activeIndex=Math.min(active,Math.max(0,options.length-1));
  useEffect(()=>{
    if(!open)return;
    const close=e=>{if(!root.current?.contains(e.target))setOpen(false);};
    document.addEventListener('pointerdown',close);
    return()=>document.removeEventListener('pointerdown',close);
  },[open]);
  useEffect(()=>{if(open){const option=document.getElementById(`${id}-${activeIndex}`),list=document.getElementById(`${id}-list`);if(option&&list){const top=option.offsetTop,bottom=top+option.offsetHeight;if(top<list.scrollTop)list.scrollTop=top;else if(bottom>list.scrollTop+list.clientHeight)list.scrollTop=bottom-list.clientHeight;}}},[open,activeIndex,id]);
  function choose(index){if(!options[index])return;onChange(options[index].value);setOpen(false);trigger.current?.focus();}
  function keyDown(e){
    if(e.nativeEvent.isComposing)return;
    if(['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(e.key)){
      e.preventDefault();
      if(!open){setActive(e.key==='Home'?0:e.key==='End'?options.length-1:selected);setOpen(true);return;}
      if(e.key==='Enter'||e.key===' '){choose(activeIndex);return;}
      setActive(e.key==='Home'?0:e.key==='End'?options.length-1:Math.max(0,Math.min(options.length-1,activeIndex+(e.key==='ArrowDown'?1:-1))));
    }else if(e.key==='Escape'){e.preventDefault();setOpen(false);}
    else if(e.key==='Tab')setOpen(false);
    else if(e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){
      const stamp=Date.now();typed.current={text:(stamp-typed.current.at<700?typed.current.text:'')+e.key.toLowerCase(),at:stamp};
      const match=options.findIndex(o=>`${o.label} ${o.description||''}`.toLowerCase().startsWith(typed.current.text));
      if(match>=0){setActive(match);setOpen(true);}
    }
  }
  return <div className="admin-select-field"><span id={`${id}-label`}>{label}</span><div ref={root} className={`admin-select ${open?'is-open':''}`} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setOpen(false);}}>
    <button ref={trigger} type="button" className="admin-select-trigger" role="combobox" aria-labelledby={`${id}-label`} aria-expanded={open} aria-controls={`${id}-list`} aria-haspopup="listbox" aria-activedescendant={open?`${id}-${activeIndex}`:undefined} onKeyDown={keyDown} onClick={()=>{setActive(selected);setOpen(v=>!v);}} title={[options[selected]?.label,options[selected]?.description].filter(Boolean).join(' · ')}><span>{options[selected]?.label||'선택'}</span><ChevronDown size={16} aria-hidden="true"/></button>
    {open&&<div id={`${id}-list`} role="listbox" aria-labelledby={`${id}-label`} className="admin-select-options">{options.map((o,i)=><div key={o.value} id={`${id}-${i}`} role="option" aria-selected={o.value===value} className={`admin-select-option ${activeIndex===i?'is-active':''}`} onPointerMove={()=>setActive(i)} onMouseDown={e=>e.preventDefault()} onClick={()=>choose(i)}><span><strong>{o.label}</strong>{o.description&&<small>{o.description}</small>}</span>{o.value===value&&<Check size={16} aria-hidden="true"/>}</div>)}</div>}
  </div></div>;
}
