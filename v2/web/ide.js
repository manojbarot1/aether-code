/* Aether Code — IDE logic: workspace, explorer, Monaco tabs, terminals, search, git, quick open, layout. */
const IC={
 files:'<svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
 search:'<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>',
 git:'<svg viewBox="0 0 24 24"><circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="9" r="2"/><path d="M6 7v10M18 11c0 4-6 3-12 6"/></svg>',
 chat:'<svg viewBox="0 0 24 24"><path d="M4 5h16v11H9l-5 4z"/></svg>',
 gear:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/></svg>',
 ssh:'<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/></svg>',
 brain:'<svg viewBox="0 0 24 24"><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 4 3 3 0 0 0 6 1V5a2 2 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 4 3 3 0 0 1-6 1"/></svg>',
 side:'<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg>',
 panel:'<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 14h18"/></svg>',
 chatp:'<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></svg>',
 newfile:'<svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M12 11v6M9 14h6"/></svg>',
 newdir:'<svg viewBox="0 0 24 24"><path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 10v5M9.5 12.5h5"/></svg>',
 refresh:'<svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/></svg>',
 collapse:'<svg viewBox="0 0 24 24"><path d="M8 4 4 8l4 4M16 20l4-4-4-4M4 8h9M20 16h-9"/></svg>',
 plus:'<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
 trash:'<svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>',
 x:'<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
 term:'<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 10 3 2-3 2M13 15h4"/></svg>',
 menu:'<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
 chev:'<svg viewBox="0 0 24 24" style="width:10px;height:10px;stroke-width:2.4"><path d="m9 6 6 6-6 6"/></svg>',
};
const icon=n=>IC[n]||'';
function paintIcons(){
  document.querySelectorAll('.ico[data-i]').forEach(e=>e.innerHTML=icon(e.dataset.i));
  const map={'tg-side':'side','tg-panel':'panel','tg-chat':'chatp','act-eng':'gear','act-ssh':'ssh','act-mem':'brain','pt-new':'plus','pt-vm':'ssh','pt-kill':'trash','pt-close':'x','chat-menu':'menu'};
  for(const [id,i] of Object.entries(map)){const e=$(id);if(e)e.innerHTML=icon(i)}
  document.querySelectorAll('.act[data-view]').forEach(b=>b.innerHTML=icon({explorer:'files',search:'search',git:'git'}[b.dataset.view]));
  document.querySelectorAll('.vact button[data-a]').forEach(b=>{const m={newfile:'newfile',newdir:'newdir',refresh:'refresh',collapse:'collapse',gitrefresh:'refresh'};b.innerHTML=icon(m[b.dataset.a])});
}
function jsLog(m){try{api().js_log(String(m))}catch(e){}}
window.addEventListener('error',e=>jsLog('ERR '+e.message+' @'+(e.filename||'')+':'+e.lineno));
window.addEventListener('unhandledrejection',e=>{if(e.reason&&(e.reason.name==='Canceled'||e.reason.message==='Canceled'))return;jsLog('REJ '+(e.reason&&e.reason.stack||e.reason))});

/* ───────── state ───────── */
const W={target:'local',path:'',name:''};          // workspace
const X={tabs:[],active:null,tree:new Map(),expanded:new Set(),sel:null,monaco:null,editor:null,terms:[],termActive:null,index:[],git:{branch:null,changes:[]},recent:[]};
const join=(a,b)=>a.replace(/\/+$/,'')+'/'+b;
const base=p=>p.split('/').filter(Boolean).pop()||p;
const dirname=p=>{const i=p.replace(/\/+$/,'').lastIndexOf('/');return i<=0?'/':p.slice(0,i)};
const rel=p=>p.startsWith(W.path)?p.slice(W.path.length).replace(/^\//,''):p;
const hostName=()=>W.target==='local'?'This Mac':(S.cfg.ssh.find(h=>h.id===W.target)?.name||'remote');
function toast(msg,ms=2200){const t=$('toast');t.textContent=msg;t.hidden=false;clearTimeout(toast.t);toast.t=setTimeout(()=>t.hidden=true,ms)}
const EXT_COL={js:'#f5d04c',ts:'#4aa3ff',jsx:'#4ad0f5',tsx:'#4ad0f5',py:'#6aa7ff',json:'#e8a23d',html:'#ff7a45',css:'#a678ff',md:'#8fd0ff',sh:'#6fe39a',yml:'#ff6b81',yaml:'#ff6b81',go:'#5fd7e8',rs:'#ff9a62',java:'#ff7a45',c:'#7aa7ff',cpp:'#7aa7ff',h:'#a0b0ff',txt:'#9aa5b8',png:'#6fe3b0',jpg:'#6fe3b0',svg:'#ffb84a'};
function fileIcon(n){const e=(n.split('.').pop()||'').toLowerCase();return `<span class="fi" style="color:${EXT_COL[e]||'var(--text-3)'}">◆</span>`}

/* ───────── layout: toggles, splitters ───────── */
function setLayout(k,on){const row=$('mainrow');if(k==='side')row.classList.toggle('no-side',!on);if(k==='chat')row.classList.toggle('no-chat',!on);
  if(k==='panel'){$('panel').classList.toggle('hidden',!on);$('sp-panel').classList.toggle('hidden',!on);if(on)fitTerms()}
  X.editor&&X.editor.layout();saveLayout()}
const lay=k=>k==='side'?!$('mainrow').classList.contains('no-side'):k==='chat'?!$('mainrow').classList.contains('no-chat'):!$('panel').classList.contains('hidden');
function saveLayout(){api().ide_save({layout:{side:lay('side'),chat:lay('chat'),panel:lay('panel'),sbw:getComputedStyle(document.documentElement).getPropertyValue('--sbw').trim(),chw:getComputedStyle(document.documentElement).getPropertyValue('--chw').trim(),ph:getComputedStyle(document.documentElement).getPropertyValue('--ph').trim()}})}
function dragSplit(id,fn){const el=$(id);el.addEventListener('mousedown',e=>{e.preventDefault();el.classList.add('drag');document.body.style.userSelect='none';
  const mv=ev=>{fn(ev);X.editor&&X.editor.layout();fitTerms()};const up=()=>{el.classList.remove('drag');document.body.style.userSelect='';removeEventListener('mousemove',mv);removeEventListener('mouseup',up);saveLayout()};
  addEventListener('mousemove',mv);addEventListener('mouseup',up)})}
function initSplits(){
  const R=document.documentElement.style;
  dragSplit('sp-side',e=>R.setProperty('--sbw',Math.max(160,Math.min(600,e.clientX-8-44))+'px'));
  dragSplit('sp-chat',e=>R.setProperty('--chw',Math.max(300,Math.min(760,innerWidth-8-e.clientX))+'px'));
  dragSplit('sp-panel',e=>{const top=$('center').getBoundingClientRect();R.setProperty('--ph',Math.max(120,Math.min(top.height-160,top.bottom-e.clientY))+'px')});
}

/* ───────── Monaco ───────── */
function monacoTheme(){const dark=matchMedia('(prefers-color-scheme: dark)').matches;return dark?'glass-dark':'glass-light'}
function loadMonaco(){return new Promise(res=>{
  require.config({paths:{vs:'vendor/monaco/vs'}});
  require(['vs/editor/editor.main'],()=>{const m=window.monaco;X.monaco=m;
    m.editor.defineTheme('glass-dark',{base:'vs-dark',inherit:true,rules:[],colors:{'editor.background':'#00000000','editorGutter.background':'#00000000','minimap.background':'#00000000','editor.lineHighlightBackground':'#ffffff0f','editorLineNumber.foreground':'#7d869c','editor.selectionBackground':'#5b8cff44','editorWidget.background':'#1c202ef0','editorSuggestWidget.background':'#1c202ef0','scrollbarSlider.background':'#ffffff1c'}});
    m.editor.defineTheme('glass-light',{base:'vs',inherit:true,rules:[],colors:{'editor.background':'#00000000','editorGutter.background':'#00000000','minimap.background':'#00000000','editor.lineHighlightBackground':'#2f6bff10','editorWidget.background':'#f4f6fbf5','editorSuggestWidget.background':'#f4f6fbf5'}});
    X.editor=m.editor.create($('monaco'),{theme:monacoTheme(),automaticLayout:true,fontFamily:'ui-monospace,"SF Mono",Menlo,monospace',fontSize:13,lineHeight:20,minimap:{enabled:true,scale:1},smoothScrolling:true,cursorSmoothCaretAnimation:'on',cursorBlinking:'smooth',renderLineHighlight:'all',bracketPairColorization:{enabled:true},guides:{bracketPairs:true},padding:{top:8},scrollBeyondLastLine:false,fontLigatures:true,roundedSelection:true,wordWrap:'off',model:null});
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>m.editor.setTheme(monacoTheme()));
    X.editor.onDidChangeCursorPosition(updatePos);
    X.editor.addCommand(m.KeyMod.CtrlCmd|m.KeyCode.KeyS,saveActive);
    res()})})}
function updatePos(){const t=X.active;const e=X.editor;if(!t||t.kind!=='text'){$('st-pos').textContent='';$('st-lang').textContent='';$('st-eol').textContent='';return}
  const p=e.getPosition();$('st-pos').textContent=`Ln ${p.lineNumber}, Col ${p.column}`;$('st-lang').textContent=t.model.getLanguageId();$('st-eol').textContent=t.crlf?'CRLF':'LF'}

/* ───────── tabs & files ───────── */
const tabKey=p=>W.target+':'+p;
function showPane(k){$('monaco').hidden=k!=='text';$('viewer').hidden=!(k==='image'||k==='binary'||k==='error');$('welcome').hidden=k!=='welcome'}
function renderTabs(){
  $('tabs').innerHTML=X.tabs.map(t=>`<div class="tab ${t===X.active?'on':''} ${t.dirty?'dirty':''}" data-k="${esc(t.key)}" title="${esc(t.path)}">${fileIcon(t.path)}<span class="nm">${esc(base(t.path))}</span><span class="x" data-x="1"><span>✕</span></span></div>`).join('');
  $('crumbs').textContent=X.active?(X.active.target==='local'?'':hostName()+' › ')+rel(X.active.path).split('/').join(' › '):'';
  $('crumbs').style.display=X.active?'':'none';
  document.title=(X.active?base(X.active.path)+' — ':'')+(W.name||'Aether Code');
  renderCtx()}
$('tabs').addEventListener('click',e=>{const tab=e.target.closest('.tab');if(!tab)return;const t=X.tabs.find(x=>x.key===tab.dataset.k);if(e.target.closest('[data-x]'))closeTab(t);else activate(t)});
$('tabs').addEventListener('auxclick',e=>{const tab=e.target.closest('.tab');if(tab&&e.button===1)closeTab(X.tabs.find(x=>x.key===tab.dataset.k))});
async function openFile(path,opts={}){
  const key=tabKey(path);let t=X.tabs.find(x=>x.key===key);
  if(!t){const r=await api().fs_read(W.target,path);
    if(r.error){toast('⚠ '+r.error,3500);return}
    t={key,path,target:W.target,kind:r.kind,mtime:r.mtime,crlf:r.crlf};
    if(r.kind==='text'){const uri=X.monaco.Uri.parse((W.target==='local'?'file://':'vm://'+W.target)+encodeURI(path));
      t.model=X.monaco.editor.getModel(uri)||X.monaco.editor.createModel(r.text,undefined,uri);t.saved=t.model.getAlternativeVersionId();
      t.model.onDidChangeContent(()=>{const d=t.model.getAlternativeVersionId()!==t.saved;if(d!==t.dirty){t.dirty=d;renderTabs()}})}
    else if(r.kind==='image')t.src=`data:${r.mime};base64,${r.b64}`;
    X.tabs.push(t)}
  activate(t);
  if(opts.line&&t.kind==='text'){X.editor.revealLineInCenter(opts.line);X.editor.setPosition({lineNumber:opts.line,column:opts.col||1});X.editor.focus()}
  persistOpen()}
function activate(t){
  if(X.active&&X.active.kind==='text'&&X.active.model)X.active.view=X.editor.saveViewState();
  X.active=t;X.sel=t?t.path:null;
  if(!t){showPane('welcome');X.editor&&X.editor.setModel(null)}
  else if(t.kind==='text'){showPane('text');X.editor.setModel(t.model);if(t.view)X.editor.restoreViewState(t.view);X.editor.focus()}
  else if(t.kind==='image'){showPane('image');$('viewer').innerHTML=`<img src="${t.src}">`}
  else{showPane('binary');$('viewer').innerHTML=`<div>${esc(base(t.path))}<br><span class="sm">Binary file — can't be shown in the editor</span></div>`}
  renderTabs();updatePos();markTree();checkBanner()}
async function closeTab(t,force){
  if(!t)return;
  if(t.dirty&&!force){const r=await choose3(`Save changes to ${base(t.path)}?`,['Save','Don\'t save','Cancel']);if(r==='Cancel'||r==null)return;if(r==='Save'){activate(t);await saveActive()}}
  const i=X.tabs.indexOf(t);X.tabs.splice(i,1);if(t.model)t.model.dispose();
  if(X.active===t)activate(X.tabs[Math.min(i,X.tabs.length-1)]||null);else renderTabs();persistOpen()}
function persistOpen(){api().ide_save({open:X.tabs.filter(t=>t.target==='local'||t.target===W.target).map(t=>({target:t.target,path:t.path}))})}
async function saveActive(){const t=X.active;if(!t||t.kind!=='text')return;
  const r=await api().fs_write(t.target,t.path,t.model.getValue());
  if(r.ok){t.saved=t.model.getAlternativeVersionId();t.dirty=false;t.mtime=r.mtime;renderTabs();toast('Saved '+base(t.path),1200);refreshGit()}else toast('⚠ Save failed: '+(r.error||''),4000)}
function choose3(msg,labels){return new Promise(res=>{modal(`<h3>${esc(msg)}</h3><div class="row">${labels.map((l,i)=>`<button class="btn ${i===0?'primary':''}" data-i="${i}">${esc(l)}</button>`).join('')}</div>`);
  $('card').querySelectorAll('button[data-i]').forEach(b=>b.onclick=()=>{closeModal();res(labels[+b.dataset.i])})})}
/* external changes (engineers edit files; terminals; other tools) */
async function checkExternal(){
  const ts=X.tabs.filter(t=>t.kind==='text'&&t.target===W.target);if(!ts.length)return;
  const m=await api().fs_stat(W.target,ts.map(t=>t.path));
  for(const t of ts){const mt=m[t.path];if(mt==null||Math.abs(mt-t.mtime)<0.001)continue;
    if(!t.dirty){const r=await api().fs_read(t.target,t.path);if(r.kind==='text'){const v=X.active===t&&X.editor.saveViewState();t.model.pushEditOperations([],[{range:t.model.getFullModelRange(),text:r.text}],()=>null);t.saved=t.model.getAlternativeVersionId();t.dirty=false;t.mtime=r.mtime;renderTabs()}}
    else{t.conflict=true;t.mtime=mt}}
  checkBanner()}
function checkBanner(){const t=X.active;const b=$('banner');if(t&&t.conflict){b.hidden=false;b.innerHTML=`<span>⚠ ${esc(base(t.path))} changed on disk while you have unsaved edits.</span><button class="btn sm" id="bn-reload">Reload from disk</button><button class="btn sm" id="bn-keep">Keep mine</button>`;
  $('bn-reload').onclick=async()=>{const r=await api().fs_read(t.target,t.path);if(r.kind==='text'){t.model.setValue(r.text);t.saved=t.model.getAlternativeVersionId();t.dirty=false;t.mtime=r.mtime;t.conflict=false;renderTabs();checkBanner()}};
  $('bn-keep').onclick=()=>{t.conflict=false;checkBanner()}}else b.hidden=true}
window.ideOnIdle=async()=>{await refreshTree();await checkExternal();refreshGit()};
window.addEventListener('focus',()=>{checkExternal();refreshTree()});
setInterval(()=>{if(document.hasFocus())checkExternal()},W.target==='local'?6000:15000);

/* ───────── explorer ───────── */
async function loadDir(path){const r=await api().fs_list(W.target,path);if(r.error&&!r.items.length)toast('⚠ '+r.error,3500);X.tree.set(path,r.items||[]);if(r.path&&W.target!=='local'&&path===W.path&&r.path!==path){W.path=r.path}return r}
async function refreshTree(){if(!W.path)return;const dirs=[W.path,...[...X.expanded]];for(const d of dirs)if(X.tree.has(d)||d===W.path)await loadDir(d);renderTree()}
function renderTree(){const out=[];
  const walk=(path,depth)=>{for(const it of X.tree.get(path)||[]){const p=join(path,it.name);const open=it.dir&&X.expanded.has(p);const g=X.git.changes.find(c=>W.target&&(p===join(W.path,c.path)));
    out.push(`<div class="tr ${X.sel===p?'sel':''}" data-p="${esc(p)}" data-d="${it.dir?1:0}" style="padding-left:${6+depth*14}px"><span class="chev ${open?'open':''}">${it.dir?icon('chev'):''}</span>${it.dir?'<span class="fi">▣</span>':fileIcon(it.name)}<span class="nm">${esc(it.name)}</span>${g?`<span class="git git-${esc(g.status[0])}">${esc(g.status[0])}</span>`:''}</div>`);
    if(open)walk(p,depth+1)}};
  walk(W.path,0);$('tree').innerHTML=out.join('')||'<p class="sm" style="padding:14px">Empty folder</p>'}
function markTree(){document.querySelectorAll('#tree .tr').forEach(e=>e.classList.toggle('sel',e.dataset.p===X.sel))}
$('tree').addEventListener('click',async e=>{const r=e.target.closest('.tr');if(!r||r.querySelector('input'))return;const p=r.dataset.p;X.sel=p;
  if(r.dataset.d==='1'){if(X.expanded.has(p))X.expanded.delete(p);else{X.expanded.add(p);if(!X.tree.has(p))await loadDir(p)}renderTree()}else{markTree();openFile(p)}});
$('tree').addEventListener('contextmenu',e=>{e.preventDefault();const r=e.target.closest('.tr');ctxMenu(e,r?{p:r.dataset.p,d:r.dataset.d==='1'}:{p:W.path,d:true,root:true})});
function ctxMenu(e,n){const dir=n.d?n.p:dirname(n.p);
  const items=[['New File…',()=>newEntry(dir,false)],['New Folder…',()=>newEntry(dir,true)],'-',
    ...(n.root?[]:[['Rename…',()=>renameEntry(n.p)],['Delete',()=>deleteEntry(n.p,n.d),'dng'],'-']),
    ['Open in Terminal',()=>newTerm(W.target,dir)],['Copy Path',()=>{navigator.clipboard?.writeText(n.p);toast('Path copied')}],
    ...(W.target==='local'?[['Reveal in Finder',()=>api().reveal(n.p)]]:[])];
  const m=$('ctxmenu');m.innerHTML=items.map((it,i)=>it==='-'?'<div class="mi sep"></div>':`<div class="mi ${it[2]||''}" data-i="${i}">${esc(it[0])}</div>`).join('');
  m.hidden=false;m.style.left=Math.min(e.clientX,innerWidth-210)+'px';m.style.top=Math.min(e.clientY,innerHeight-m.offsetHeight-10)+'px';
  m.onclick=ev=>{const i=ev.target.closest('.mi[data-i]');if(!i)return;m.hidden=true;items[+i.dataset.i][1]()}}
addEventListener('click',()=>$('ctxmenu').hidden=true);addEventListener('blur',()=>$('ctxmenu').hidden=true);
async function newEntry(dir,isDir){const name=await askBox(isDir?'New folder name':'New file name','',  'Create');if(!name||!name.trim())return;
  const p=join(dir,name.trim());const r=await api().fs_new(W.target,p,isDir);if(!r.ok){toast('⚠ '+r.error,3500);return}
  X.expanded.add(dir);await loadDir(dir);renderTree();if(!isDir)openFile(p)}
async function renameEntry(p){const nn=await askBox('Rename to',base(p),'Rename');if(!nn||nn===base(p))return;const np=join(dirname(p),nn.trim());
  const r=await api().fs_rename(W.target,p,np);if(!r.ok){toast('⚠ '+r.error,3500);return}
  for(const t of X.tabs.filter(t=>t.path===p||t.path.startsWith(p+'/')))closeTab(t,true);await refreshTree()}
async function deleteEntry(p,isDir){const msg=W.target==='local'?`Move "${base(p)}" to the Trash?`:`Permanently delete "${base(p)}" on ${hostName()}? This cannot be undone.`;
  if(await askBox(msg,null,W.target==='local'?'Move to Trash':'Delete')===null)return;
  const r=await api().fs_delete(W.target,p);if(!r.ok){toast('⚠ '+r.error,3500);return}
  for(const t of X.tabs.filter(t=>t.path===p||t.path.startsWith(p+'/')))closeTab(t,true);await refreshTree()}
document.addEventListener('click',e=>{const b=e.target.closest('.vact button[data-a]');if(!b)return;const a=b.dataset.a;
  if(a==='refresh')refreshTree();else if(a==='collapse'){X.expanded.clear();renderTree()}else if(a==='gitrefresh')refreshGit();
  else{const sel=X.sel;const dir=sel&&X.tree.has(sel)?sel:(sel?dirname(sel):W.path);newEntry(dir,a==='newdir')}});

/* ───────── views ───────── */
function showView(v){document.querySelectorAll('.act[data-view]').forEach(b=>b.classList.toggle('on',b.dataset.view===v));
  ['explorer','search','git'].forEach(k=>$('view-'+k).hidden=k!==v);setLayout('side',true);if(v==='search')$('q').focus();if(v==='git')refreshGit()}
document.querySelectorAll('.act[data-view]').forEach(b=>b.onclick=()=>{const on=lay('side')&&b.classList.contains('on');if(on)setLayout('side',false);else showView(b.dataset.view)});
let qTimer;$('q').addEventListener('input',()=>{clearTimeout(qTimer);qTimer=setTimeout(runSearch,350)});$('q-case').onclick=function(){this.classList.toggle('primary');runSearch()};
async function runSearch(){const q=$('q').value;if(!q.trim()){$('results').innerHTML='';return}$('results').innerHTML='<p class="sm" style="padding:10px">Searching…</p>';
  const r=await api().search(W.target,W.path,q,$('q-case').classList.contains('primary'));const by={};(r.results||[]).forEach(x=>(by[x.path]??=[]).push(x));
  $('results').innerHTML=Object.keys(by).length?Object.entries(by).map(([f,rs])=>`<div class="rf">${fileIcon(f)}${esc(base(f))}<span class="sm">${esc(dirname(f)==='/'?'':dirname(f))}</span><span class="c">${rs.length}</span></div>`+rs.map(x=>`<div class="rl" data-f="${esc(f)}" data-l="${x.line}"><span class="ln">${x.line}</span><span class="tx">${esc(x.text)}</span></div>`).join('')).join(''):'<p class="sm" style="padding:10px">No results</p>'}
$('results').addEventListener('click',e=>{const r=e.target.closest('.rl');if(r)openFile(join(W.path,r.dataset.f),{line:+r.dataset.l})});
async function refreshGit(){if(!W.path)return;const g=await api().git_info(W.target,W.path);X.git=g;
  $('st-branch').hidden=!g.branch;$('st-branch').textContent='⎇ '+g.branch;
  $('gitlist').innerHTML=g.branch?(g.changes.length?g.changes.map(c=>`<div class="tr" data-gp="${esc(c.path)}"><span class="git git-${esc(c.status[0])}" style="margin:0 8px 0 10px">${esc(c.status[0])}</span><span class="nm">${esc(c.path)}</span></div>`).join(''):'<p class="sm" style="padding:14px">No changes — working tree clean.</p>'):'<p class="sm" style="padding:14px">This folder is not a git repository.</p>';
  renderTree()}
$('gitlist').addEventListener('click',e=>{const r=e.target.closest('[data-gp]');if(r)openFile(join(W.path,r.dataset.gp))});

/* ───────── quick open & palette ───────── */
function fuzzy(q,s){q=q.toLowerCase();s=s.toLowerCase();let qi=0,score=0,last=-1;for(let i=0;i<s.length&&qi<q.length;i++){if(s[i]===q[qi]){score+=(last===i-1?3:1)+(i===0||'/_-. '.includes(s[i-1])?4:0);last=i;qi++}}return qi===q.length?score-s.length*.01:-1}
let qoLoading=null;
async function quickOpen(mode='file'){
  modal(`<div class="qo"><input class="field" id="qo-in" placeholder="${mode==='cmd'?'Type a command…':'Go to file…'}" autocomplete="off" spellcheck="false"><div class="list2" id="qo-list"></div></div>`);$('card').classList.add('wide');const inp=$('qo-in');inp.focus();
  let items=[],idx=0;
  const cmds=[['Open Folder…',openFolderDialog],['Switch Workspace Host…',switchHost],['Toggle Sidebar',()=>setLayout('side',!lay('side'))],['Toggle Terminal',()=>setLayout('panel',!lay('panel'))],['Toggle AI Team Panel',()=>setLayout('chat',!lay('chat'))],['New Terminal',()=>newTerm()],['New File…',()=>newEntry(W.path,false)],['Save',saveActive],['Close Editor',()=>closeTab(X.active)],['Find in Files',()=>showView('search')],['Source Control',()=>showView('git')],['Engineers…',()=>editEngineer()],['SSH Connections…',sshModal],['Shared Memory…',memModal],['New Chat Session',newSession]];
  if(mode==='file'){if(!X.index.length||X.indexFor!==W.target+W.path){X.index=[];X.indexFor=W.target+W.path;qoLoading=api().files_index(W.target,W.path).then(r=>{X.index=r;if($('qo-in'))render()})}}
  const render=()=>{const q=inp.value.trim();
    if(mode==='cmd')items=cmds.map(c=>({t:c[0],f:c[1],s:q?fuzzy(q,c[0]):0})).filter(x=>x.s>=0).sort((a,b)=>b.s-a.s);
    else items=(q?X.index.map(p=>({t:base(p),p,s:Math.max(fuzzy(q,p),fuzzy(q,base(p))+2)})).filter(x=>x.s>=0).sort((a,b)=>b.s-a.s):X.index.slice(0,40).map(p=>({t:base(p),p,s:0}))).slice(0,60);
    idx=Math.min(idx,Math.max(0,items.length-1));
    $('qo-list').innerHTML=items.length?items.map((x,i)=>`<div class="qi ${i===idx?'on':''}" data-i="${i}"><span>${esc(x.t)}</span><span class="p">${esc(x.p?dirname(x.p)==='.'?'':x.p:'')}</span></div>`).join(''):`<p class="sm" style="padding:10px">${mode==='file'&&!X.index.length?'Indexing…':'No matches'}</p>`};
  const go=i=>{const x=items[i];if(!x)return;closeModal();$('card').classList.remove('wide');if(mode==='cmd')x.f();else openFile(join(W.path,x.p))};
  inp.oninput=()=>{idx=0;render()};inp.onkeydown=e=>{if(e.key==='ArrowDown'){idx=Math.min(items.length-1,idx+1);render();e.preventDefault()}else if(e.key==='ArrowUp'){idx=Math.max(0,idx-1);render();e.preventDefault()}else if(e.key==='Enter')go(idx);else if(e.key==='Escape'){closeModal();$('card').classList.remove('wide')}};
  $('qo-list').onclick=e=>{const i=e.target.closest('.qi');if(i)go(+i.dataset.i)};render()}

/* ───────── workspace ───────── */
function renderTop(){$('ws-folder').textContent='📁 '+(W.name||'Open folder…');$('st-remote').textContent=(W.target==='local'?'💻 ':'🖥 ')+hostName();$('ws-title').textContent=(W.name||'EXPLORER').toUpperCase();
  $('ws-target').innerHTML='<option value="local">💻 This Mac</option>'+S.cfg.ssh.map(h=>`<option value="${h.id}">🖥 ${esc(h.name)}</option>`).join('');$('ws-target').value=W.target;
  $('cmdtext').textContent=W.name?`Search ${W.name}`:'Open a folder to begin'}
function pushRecent(){const key=W.target+'|'+W.path;X.recent=[{target:W.target,path:W.path},...X.recent.filter(r=>r.target+'|'+r.path!==key)].slice(0,8);api().ide_save({workspace:{target:W.target,path:W.path},recent:X.recent})}
async function setWorkspace(target,path,{keepTabs=false}={}){
  if(!keepTabs){for(const t of [...X.tabs])await closeTab(t,true)}
  W.target=target;X.tree.clear();X.expanded.clear();X.index=[];X.sel=null;
  const r=await api().fs_list(target,path);if(r.error&&!r.items.length){toast('⚠ Cannot open folder: '+r.error,4000)}
  W.path=(target!=='local'&&r.path)?r.path:path;W.name=base(W.path);X.tree.set(W.path,r.items||[]);
  renderTop();renderTree();pushRecent();refreshGit();syncSession();
  $('welcome').querySelector('#w-recent').innerHTML=recentHtml();
  if(!X.terms.length)newTerm()}
async function openFolderDialog(){
  if(W.target==='local'&&false){}
  const tid=W.target;browseFolder(tid,W.path||'~',(p)=>setWorkspace(tid,p))}
function browseFolder(tid,path,onPick){
  modal('<h3>Open folder</h3><p class="sm">Loading…</p>');
  api().list_dirs(tid,path).then(r=>{const tg=S.cfg.ssh.find(h=>h.id===tid);
    modal(`<h3>Open folder <span class="badge accent">${tg?esc(tg.name):'This Mac'}</span></h3>
    <div class="f" style="grid-template-columns:auto 1fr auto"><button class="btn sm" ${r.parent?'':'disabled'} id="bf-up">↑ Up</button><input class="field" id="bf-path" value="${esc(r.path||path)}"><button class="btn sm" id="bf-home">Home</button></div>
    ${r.error?`<p class="sm" style="color:var(--err)">${esc(r.error)}</p>`:''}
    <div class="glass sunken" style="max-height:280px;overflow:auto;padding:6px;margin:8px 0;border-radius:var(--r-md)">${(r.dirs||[]).map(d=>`<div class="item" data-d="${esc(d)}">📁 <span class="t">${esc(d)}</span></div>`).join('')||'<p class="sm" style="padding:8px">No sub-folders</p>'}</div>
    <div class="row">${tid==='local'?'<button class="btn" id="bf-fd">Choose in Finder…</button>':''}<button class="btn" onclick="closeModal()">Cancel</button><button class="btn primary" id="bf-ok">Open this folder</button></div>`);
    const go=p=>browseFolder(tid,p,onPick);
    $('bf-up').onclick=()=>go(r.parent);$('bf-home').onclick=()=>go('~');$('bf-path').onkeydown=e=>{if(e.key==='Enter')go(e.target.value)};
    $('card').querySelectorAll('.item[data-d]').forEach(i=>i.onclick=()=>go(r.path.replace(/\/$/,'')+'/'+i.dataset.d));
    $('bf-ok').onclick=()=>{const p=$('bf-path').value.trim()||r.path;closeModal();onPick(p)};
    const fd=$('bf-fd');if(fd)fd.onclick=async()=>{const d=await api().pick_folder();if(d){closeModal();onPick(d)}}})}
function switchHost(){const opts=[['local','💻 This Mac'],...S.cfg.ssh.map(h=>['' +h.id,'🖥 '+h.name])];
  modal(`<h3>Open workspace on…</h3>${opts.map(o=>`<div class="item" data-t="${esc(o[0])}">${esc(o[1])}</div>`).join('')}<div class="row"><button class="btn" onclick="closeModal()">Cancel</button></div>`);
  $('card').querySelectorAll('.item[data-t]').forEach(i=>i.onclick=()=>{closeModal();const t=i.dataset.t;W.target=t;browseFolder(t,t==='local'?'~':(S.cfg.ssh.find(h=>h.id===t)?.cwd||'~'),p=>setWorkspace(t,p))})}
$('ws-target').onchange=e=>{const t=e.target.value;const old=W.target;e.target.value=old;W.target=old;browseFolder(t,t==='local'?'~':(S.cfg.ssh.find(h=>h.id===t)?.cwd||'~'),p=>setWorkspace(t,p))};
function recentHtml(){return X.recent.length?'<div class="sm" style="margin-top:6px">Recent</div>'+X.recent.map((r,i)=>`<a data-r="${i}">${r.target==='local'?'💻':'🖥'} ${esc(r.path)}</a>`).join(''):''}
$('w-recent').onclick=e=>{const a=e.target.closest('a[data-r]');if(a){const r=X.recent[+a.dataset.r];setWorkspace(r.target,r.path)}};
$('w-open').onclick=openFolderDialog;$('w-file').onclick=()=>quickOpen('file');$('ws-folder').onclick=openFolderDialog;$('st-remote').onclick=switchHost;$('cmdcenter').onclick=()=>quickOpen('file');
function syncSession(){if(!S.cur||!W.path)return;const st=S.cur.settings;st.target=W.target;if(W.target==='local')st.cwd=W.path;else st.rcwd=W.path;api().update_settings(S.cur.id,st);renderCtx()}

window.ideOnSettings=s=>{const p=W.target==='local'?s.cwd:s.rcwd;if(p&&p!==W.path&&s.target===W.target)setWorkspace(W.target,p,{keepTabs:true})};
/* chat ↔ editor context */
function ideContext(){if(!$('ctx-on').checked||!W.path)return'';const t=X.active;let c=`Workspace: ${hostName()} · ${W.path}\n`;
  if(t&&t.kind==='text'){c+=`Active file: ${t.path}${t.dirty?' (has unsaved edits in the editor)':''}\n`;const sel=X.editor.getModel()===t.model?X.editor.getSelection():null;
    if(sel&&!sel.isEmpty()){c+=`Selected lines ${sel.startLineNumber}-${sel.endLineNumber}:\n\`\`\`\n${t.model.getValueInRange(sel).slice(0,4000)}\n\`\`\`\n`}else c+=`Cursor at line ${X.editor.getPosition().lineNumber}.\n`}
  return c}
function renderCtx(){const t=X.active;$('ctx-name').textContent=t?base(t.path):'(no file open)'}
$('chat-menu').onclick=()=>{const d=$('drawer');d.hidden=!d.hidden};
document.addEventListener('click',e=>{const d=$('drawer');if(!d.hidden&&!e.target.closest('#drawer')&&!e.target.closest('#chat-menu')&&!e.target.closest('.modal'))d.hidden=true},true);
const _open=openSession;openSession=async id=>{await _open(id);syncSession();$('drawer').hidden=true};

/* ───────── terminals ───────── */
function termTheme(){const d=matchMedia('(prefers-color-scheme: dark)').matches;return d?{background:'rgba(0,0,0,0)',foreground:'#e6e9f2',cursor:'#7aa7ff',selectionBackground:'#5b8cff55',black:'#1b1f2b',brightBlack:'#6b7488'}:{background:'rgba(0,0,0,0)',foreground:'#1b2236',cursor:'#2f6bff',selectionBackground:'#2f6bff33'}}
async function newTerm(target,cwd){target=target??W.target;cwd=cwd??W.path??'~';if(!lay('panel'))setLayout('panel',true);
  const el=document.createElement('div');el.className='term';$('termhost').appendChild(el);
  const term=new Terminal({fontFamily:'ui-monospace,"SF Mono",Menlo,monospace',fontSize:12.5,cursorBlink:true,allowTransparency:true,theme:termTheme(),scrollback:5000,macOptionIsMeta:true});
  const fit=new FitAddon.FitAddon();term.loadAddon(fit);term.open(el);if(window.aeTermKeys)aeTermKeys(term);
  const entry={term,fit,el,target,id:null,label:(target==='local'?'zsh':hostName())};X.terms.push(entry);activateTerm(entry);fit.fit();
  entry.id=await api().term_open(target,cwd||'~',term.cols,term.rows);
  let buf='',tm=0;term.onData(d=>{buf+=d;if(!tm)tm=setTimeout(()=>{api().term_write(entry.id,buf);buf='';tm=0},4)});
  term.onResize(({cols,rows})=>entry.id&&api().term_resize(entry.id,cols,rows));
  new ResizeObserver(()=>{if(el.classList.contains('on'))try{fit.fit()}catch(e){}}).observe(el);
  renderTermTabs()}
window.termData=(id,b64)=>{const t=X.terms.find(x=>x.id===id);if(t){const bin=atob(b64);const u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);t.term.write(u)}};
window.termExit=id=>{const t=X.terms.find(x=>x.id===id);if(t){t.term.write('\r\n\x1b[2m[process exited — press any key to close]\x1b[0m');t.dead=true;t.term.onKey(()=>closeTerm(t))}};
function activateTerm(t){X.termActive=t;X.terms.forEach(x=>x.el.classList.toggle('on',x===t));renderTermTabs();setTimeout(()=>{try{t.fit.fit()}catch(e){}t.term.focus()},30)}
function closeTerm(t){if(!t)return;api().term_close(t.id);t.term.dispose();t.el.remove();X.terms=X.terms.filter(x=>x!==t);if(X.termActive===t)X.termActive=X.terms[X.terms.length-1]||null;
  if(X.termActive)activateTerm(X.termActive);else{renderTermTabs();setLayout('panel',false)}}
function renderTermTabs(){$('pt-list').innerHTML=X.terms.map((t,i)=>`<div class="pt ${t===X.termActive?'on':''}" data-i="${i}">${icon('term')}<span>${esc(t.label)} ${i+1}</span><span class="x" data-x="1">✕</span></div>`).join('')}
$('pt-list').onclick=e=>{const p=e.target.closest('.pt');if(!p)return;const t=X.terms[+p.dataset.i];if(e.target.closest('[data-x]'))closeTerm(t);else activateTerm(t)};
$('pt-new').onclick=()=>newTerm();$('pt-kill').onclick=()=>closeTerm(X.termActive);$('pt-close').onclick=()=>setLayout('panel',false);
$('pt-vm').onclick=e=>{const opts=[['local','💻 This Mac'],...S.cfg.ssh.map(h=>[h.id,'🖥 '+h.name])];const m=$('ctxmenu');m.innerHTML=opts.map((o,i)=>`<div class="mi" data-i="${i}">New terminal on ${esc(o[1])}</div>`).join('');m.hidden=false;const r=e.target.getBoundingClientRect();m.style.left=(r.left-120)+'px';m.style.top=(r.top-m.offsetHeight-6)+'px';
  setTimeout(()=>{m.style.top=(r.top-m.offsetHeight-6)+'px'},0);m.onclick=ev=>{const i=ev.target.closest('.mi');if(!i)return;m.hidden=true;const o=opts[+i.dataset.i];newTerm(o[0],o[0]===W.target?W.path:(o[0]==='local'?'~':(S.cfg.ssh.find(h=>h.id===o[0])?.cwd||'~')))};e.stopPropagation()};
function fitTerms(){X.terms.forEach(t=>{if(t.el.classList.contains('on'))try{t.fit.fit()}catch(e){}})}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>X.terms.forEach(t=>t.term.options.theme=termTheme()));
addEventListener('resize',fitTerms);

/* ───────── status bar & keys ───────── */
function renderEngStatus(){const es=S.cfg.engineers,on=es.filter(e=>(S.status.engineers[e.id]||{}).state==='online').length;$('st-eng').innerHTML=Object.keys(S.status.engineers).length?`<span style="color:${on===es.length?'var(--ok)':on?'var(--warn)':'var(--err)'}">●</span> ${on}/${es.length} engineers online`:'checking engineers…'}
const _rs=renderSide;renderSide=function(){_rs();renderEngStatus();renderTop()};
$('st-eng').onclick=()=>{$('mainrow').classList.remove('no-chat');$('drawer').hidden=false;refreshStatus()};
$('tg-side').onclick=()=>setLayout('side',!lay('side'));$('tg-panel').onclick=()=>setLayout('panel',!lay('panel'));$('tg-chat').onclick=()=>setLayout('chat',!lay('chat'));
$('act-eng').onclick=()=>editEngineer();$('act-ssh').onclick=sshModal;$('act-mem').onclick=memModal;
addEventListener('keydown',e=>{const k=e.key.toLowerCase(),c=e.metaKey||e.ctrlKey;if(!c)return;
  if(k==='p'&&!e.shiftKey){e.preventDefault();quickOpen('file')}
  else if(k==='p'&&e.shiftKey){e.preventDefault();quickOpen('cmd')}
  else if(k==='s'&&!e.shiftKey){e.preventDefault();saveActive()}
  else if(k==='b'&&!e.altKey){e.preventDefault();setLayout('side',!lay('side'))}
  else if(k==='j'){e.preventDefault();setLayout('panel',!lay('panel'))}
  else if(k==='`'){e.preventDefault();setLayout('panel',!lay('panel'))}
  else if(k==='w'&&!e.shiftKey){e.preventDefault();closeTab(X.active)}
  else if(k==='f'&&e.shiftKey){e.preventDefault();showView('search')}
  else if(k==='e'&&e.shiftKey){e.preventDefault();showView('explorer')}
  else if(k==='c'&&e.altKey){e.preventDefault();setLayout('chat',!lay('chat'))}
  else if(k===','){e.preventDefault();editEngineer()}},true);
document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('ctxmenu').hidden=true;if($('modal').classList.contains('show')){closeModal();$('card').classList.remove('wide')}}});
const _cm=closeModal;closeModal=function(){_cm();$('card').classList.remove('wide')};

/* ───────── boot ───────── */
async function boot(){
  paintIcons();initSplits();
  const b=await api().ide_boot();chatInit(b);X.recent=b.ide.recent||[];
  await loadMonaco();
  const L=(b.ide.layout)||null;
  if(L){const R=document.documentElement.style;L.sbw&&R.setProperty('--sbw',L.sbw);L.chw&&R.setProperty('--chw',L.chw);L.ph&&R.setProperty('--ph',L.ph);if(L.side===false)$('mainrow').classList.add('no-side');if(L.chat===false)$('mainrow').classList.add('no-chat');if(L.panel===false){$('panel').classList.add('hidden');$('sp-panel').classList.add('hidden')}}
  S.sessions.forEach(s=>s.settings={cwd:b.home,target:'local',mode:'edit',team:true,active:[],...s.settings});
  const first=S.sessions.find(s=>!s.archived)||S.sessions[0];S.cur=first;
  renderTop();showPane('welcome');$('w-recent').innerHTML=recentHtml();
  const ws=b.ide.workspace;
  if(ws&&ws.path){await setWorkspace(ws.target,ws.path,{keepTabs:true});
    for(const o of (b.ide.open||[]).slice(0,12)){if(o.target===W.target)try{await openFile(o.path)}catch(e){}}}
  else{renderTree()}
  await openSession(first.id);refreshStatus();
  addEventListener('beforeunload',()=>X.terms.forEach(t=>api().term_close(t.id)));
}
window.addEventListener('pywebviewready',boot);
