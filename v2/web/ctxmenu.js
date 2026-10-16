/* Right-click menu + real clipboard for Aether Lite / Code (shared). Uses the Mac pasteboard via the Python API. */
(function(){
  const api=()=>window.pywebview&&window.pywebview.api;
  const css=document.createElement('style');css.textContent=`
  #aeMenu{position:fixed;z-index:99999;min-width:190px;padding:5px;border-radius:14px;background:var(--glass-strong,rgba(36,41,58,.9));-webkit-backdrop-filter:blur(40px) saturate(190%);backdrop-filter:blur(40px) saturate(190%);box-shadow:0 18px 44px -10px rgba(0,0,0,.45),inset 0 0 0 .5px var(--glass-line,rgba(255,255,255,.1));font:13px -apple-system,system-ui,sans-serif;color:var(--text,#f2f4fa);user-select:none;-webkit-user-select:none}
  #aeMenu div{padding:6px 12px;border-radius:9px;cursor:default;display:flex;justify-content:space-between;gap:24px}
  #aeMenu div:hover{background:var(--accent,#5b8cff);color:#fff}#aeMenu div.off{opacity:.4;pointer-events:none}#aeMenu hr{border:0;height:1px;margin:4px 6px;background:var(--glass-line,rgba(255,255,255,.12))}
  #aeMenu kbd{opacity:.55;font:11px ui-monospace,Menlo,monospace}`;
  document.head.appendChild(css);
  const menu=document.createElement('div');menu.id='aeMenu';menu.hidden=true;document.body.appendChild(menu);
  const hide=()=>{menu.hidden=true};
  addEventListener('click',hide);addEventListener('blur',hide);addEventListener('scroll',hide,true);addEventListener('keydown',e=>{if(e.key==='Escape')hide()});
  const sel=()=>String(window.getSelection&&window.getSelection().toString()||'');
  const toast=m=>{if(window.toast)window.toast(m,1100)};
  const copy=async t=>{if(t){await api().clip_set(t);toast('Copied')}};
  function insertAt(el,text){const s=el.selectionStart??el.value.length,e=el.selectionEnd??el.value.length;el.setRangeText(text,s,e,'end');el.dispatchEvent(new Event('input',{bubbles:true}))}
  function build(e){
    const t=e.target,items=[];
    const hasX=typeof X!=='undefined';const mon=hasX&&X.editor&&t.closest&&t.closest('.monaco-editor');
    const term=hasX&&X.terms&&t.closest&&t.closest('.term');
    const field=t.closest&&t.closest('input,textarea');
    if(mon){const ed=X.editor,m=ed.getModel(),sl=ed.getSelection(),has=sl&&!sl.isEmpty();
      items.push(['Cut',has,async()=>{await copy(m.getValueInRange(sl));ed.executeEdits('ctx',[{range:sl,text:''}])}],
        ['Copy',has,()=>copy(m.getValueInRange(sl))],
        ['Paste',true,async()=>{const txt=await api().clip_get();ed.executeEdits('ctx',[{range:ed.getSelection(),text:txt,forceMoveMarkers:true}]);ed.focus()}],'-',
        ['Select All',true,()=>{ed.focus();ed.setSelection(m.getFullModelRange())}],
        ['Go to File…  ⌘P',true,()=>window.quickOpen&&quickOpen('file')],['Command Palette  ⇧⌘P',true,()=>window.quickOpen&&quickOpen('cmd')]);
    }else if(term){const tm=X.terms.find(x=>x.el.contains(t));const s=tm&&tm.term.getSelection();
      items.push(['Copy',!!s,()=>copy(s)],['Paste',true,async()=>{const txt=await api().clip_get();tm.term.paste(txt)}],['Select All',true,()=>tm.term.selectAll()],'-',['Clear',true,()=>tm.term.clear()]);
    }else if(field){const has=field.selectionStart!==field.selectionEnd,ro=field.readOnly;
      items.push(['Cut',has&&!ro,async()=>{await copy(field.value.slice(field.selectionStart,field.selectionEnd));field.setRangeText('',field.selectionStart,field.selectionEnd,'end');field.dispatchEvent(new Event('input',{bubbles:true}))}],
        ['Copy',has,()=>copy(field.value.slice(field.selectionStart,field.selectionEnd))],
        ['Paste',!ro,async()=>{field.focus();insertAt(field,await api().clip_get())}],'-',['Select All',true,()=>{field.focus();field.select()}]);
    }else{const s=sel(),bub=t.closest&&t.closest('.bub'),pre=t.closest&&t.closest('pre'),tool=t.closest&&t.closest('.tool');
      items.push(['Copy',!!s,()=>copy(s)]);
      if(pre)items.push(['Copy code block',true,()=>copy(pre.innerText.replace(/\n$/,''))]);
      if(bub)items.push(['Copy message',true,()=>copy((bub.querySelector('.body')||bub).innerText.trim())]);
      if(bub&&bub.querySelector('.tool'))items.push(['Copy message with tool calls',true,()=>copy(bub.innerText.trim())]);
      items.push('-',['Select All',true,()=>{const r=document.createRange();r.selectNodeContents(bub||document.getElementById('msgs')||document.body);const g=getSelection();g.removeAllRanges();g.addRange(r)}]);
      const inp=document.getElementById('in');
      if(inp)items.push(['Paste into message box',true,async()=>{inp.focus();insertAt(inp,await api().clip_get())}]);
    }
    return items}
  document.addEventListener('contextmenu',e=>{
    if(e.target.closest&&e.target.closest('#tree,#tabs,.tr'))return;           // the IDE has its own file menu there
    e.preventDefault();e.stopPropagation();
    const items=build(e);menu.innerHTML=items.map((it,i)=>it==='-'?'<hr>':`<div data-i="${i}" class="${it[1]?'':'off'}">${it[0]}</div>`).join('');
    menu.hidden=false;const w=menu.offsetWidth,h=menu.offsetHeight;menu.style.left=Math.min(e.clientX,innerWidth-w-8)+'px';menu.style.top=Math.min(e.clientY,innerHeight-h-8)+'px';
    menu.onclick=ev=>{const d=ev.target.closest('div[data-i]');if(!d)return;ev.stopPropagation();hide();items[+d.dataset.i][2]()}},true);
  // ⌘C / ⌘V inside the terminal
  window.aeTermKeys=(term)=>term.attachCustomKeyEventHandler(ev=>{
    if(ev.type!=='keydown'||!ev.metaKey)return true;
    if(ev.key==='c'&&term.hasSelection()){api().clip_set(term.getSelection());return false}
    if(ev.key==='v'){api().clip_get().then(t=>term.paste(t));return false}
    return true});
})();
