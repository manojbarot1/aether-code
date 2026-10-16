// Chat engine UI — generated from Aether Lite v1 (sessions, engineers, team mode, memory, SSH, models, activity view).

let S={status:{engineers:{},ssh:{}},cfg:{engineers:[],ssh:[]},sessions:[],cur:null,memory:[],busy:false,home:''};
const $=id=>document.getElementById(id);
const api=()=>window.pywebview.api;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const eng=id=>S.cfg.engineers.find(e=>e.id===id);
const engByName=n=>S.cfg.engineers.find(e=>e.name===n);

function md(src){
  const blocks=[];src=String(src||'').replace(/```(\w*)\n?([\s\S]*?)```/g,(_,l,c)=>{blocks.push(c.replace(/\n$/,''));return `\u0000${blocks.length-1}\u0000`});
  let h=esc(src).replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g,'<b>$1</b>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank">$1</a>');
  const out=[];let list=null;
  for(const ln of h.split('\n')){
    const li=ln.match(/^\s*(?:[-*]|\d+\.)\s+(.*)/);
    if(li){const t=/^\s*\d/.test(ln)?'ol':'ul';if(list!==t){if(list)out.push(`</${list}>`);out.push(`<${t}>`);list=t}out.push(`<li>${li[1]}</li>`);continue}
    if(list){out.push(`</${list}>`);list=null}
    const hd=ln.match(/^#{1,4}\s+(.*)/);out.push(hd?`<p><b>${hd[1]}</b></p>`:(ln.trim()?`<p>${ln}</p>`:''));
  }
  if(list)out.push(`</${list}>`);
  return out.join('').replace(/\u0000(\d+)\u0000/g,(_,i)=>`<pre><code>${esc(blocks[i])}</code></pre>`).replace(/<p>(<pre>[\s\S]*?<\/pre>)<\/p>/g,'$1');
}

// ── rendering
function avatar(name){const e=engByName(name);return e?`<div class="av" style="background:${e.color}">${esc(e.avatar||'●')}</div>`:`<div class="av" style="background:#64748b">›</div>`}
function toolHtml(t){return `<div class="tool" id="t-${esc(t.id)}"><div onclick="this.parentNode.classList.toggle('open')"><span class="st-${t.state}">${t.state==='running'?'◔':t.state==='done'?'✓':'✕'}</span><span class="nm">${esc(t.name)}</span><span class="cmd">${esc(t.command)}</span></div><pre>${esc(t.output||'')}</pre></div>`}
function msgHtml(m){
  if(m.role==='user')return `<div class="m user" data-id="${m.id}"><div class="bub">${esc(m.content).replace(/\n/g,'<br>')}</div></div>`;
  if(m.role==='system')return m.author==='Team'?`<div class="phase" data-id="${m.id}">${esc(m.content)}</div>`:`<div class="m" data-id="${m.id}"><div class="bub sm">${esc(m.content)}</div></div>`;
  if(m.role==='shell'||m.meta?.shell)return `<div class="m" data-id="${m.id}">${avatar('')}<div class="bub shell"><div class="who">Shell</div><pre><code>${esc(m.content)}</code></pre></div></div>`;
  const act=activityHtml(m.meta||{});
  const vd=(m.content||'').match(/VERDICT:\s*(PASS|FAIL|UNVERIFIED)/);const vb=vd?`<span class="badge ${vd[1]==='PASS'?'ok':vd[1]==='FAIL'?'err':'warn'}">${vd[1]==='PASS'?'✓ verified':vd[1]==='FAIL'?'✕ failed':'unverified'}</span>`:'';
  return `<div class="m" data-id="${m.id}">${avatar(m.author)}<div class="bub"><div class="who">${esc(m.author)}${m.meta?.phase?`<span class="badge accent">${m.meta.phase}</span>`:''}${vb}</div>${act}<div class="body">${md(m.content)}</div></div></div>`;
}
function activityHtml(meta,live){const tools=meta.tools||[];const th=(meta.thoughts||'').trim();if(!tools.length&&!th&&!live)return'';
  const n=tools.length+(th?1:0);
  return `<div class="actv"><div class="sum">${live?'<span class="spin"></span>':`<span class="${meta.error&&meta.error!=='Stopped'?'bad':'ok'}">${meta.error&&meta.error!=='Stopped'?'✕':'✓'}</span>`}<span class="now">${live?'Starting…':`${n} step${n===1?'':'s'}${meta.dur?` · ${meta.dur}s`:''}`}</span><span class="el"></span></div><div class="steps">${th?`<div class="step th"><b>Thinking</b>${esc(th)}</div>`:''}${tools.map(toolHtml).join('')}</div></div>`}
document.addEventListener('click',e=>{const s=e.target.closest&&e.target.closest('.actv>.sum');if(s)s.parentElement.classList.toggle('open')});
let PH='',stick=true;
function scroll(force){const e=$('msgs');if(force)stick=true;if(stick)e.scrollTop=e.scrollHeight;const j=$('jump');if(j)j.hidden=stick||!S.busy}
function jumpLatest(){scroll(true)}
(function(){const e=document.getElementById('msgs');if(e)e.addEventListener('scroll',()=>{stick=e.scrollHeight-e.scrollTop-e.clientHeight<70;const j=$('jump');if(j)j.hidden=stick||!S.busy})})();
function fmtEl(t0){const s=Math.round((Date.now()-t0)/1000);return s<60?s+'s':Math.floor(s/60)+'m '+(s%60)+'s'}
function nowText(box,txt){const n=box.el.querySelector('.now');if(n&&box.state!==txt){n.textContent=txt;box.state=txt}}
function renderProgress(){const p=$('progress');if(!p)return;const ls=Object.entries(live).filter(([,b])=>!b.shell);
  p.innerHTML=ls.length?(PH?`<span class="pchip ph">${esc(PH)}</span>`:'')+ls.map(([id,b])=>`<span class="pchip" data-m="${id}"><span class="spin"></span><b>${esc(b.author)}</b><span class="t">${esc(b.step||'Starting…')}</span><span class="e">${fmtEl(b.t0)}</span></span>`).join(''):''}
document.addEventListener('click',e=>{const c=e.target.closest&&e.target.closest('.pchip[data-m]');if(c&&live[c.dataset.m]){live[c.dataset.m].el.scrollIntoView({behavior:'smooth',block:'center'});const d=live[c.dataset.m].el.querySelector('.actv');if(d)d.classList.add('open')}});
setInterval(()=>{for(const b of Object.values(live)){if(!b.shell){const el=b.el.querySelector('.el');if(el)el.textContent=fmtEl(b.t0)}}renderProgress()},1000);

function renderMsgs(ms){
  $('msgs').innerHTML=ms.length?ms.map(msgHtml).join(''):`<div class="empty"><b>Aether Lite</b>Ask the team anything. Use @name to pick an engineer.</div>`;scroll();
}
function renderSide(){
  const live_=S.sessions.filter(x=>!x.archived),arch=S.sessions.filter(x=>x.archived);
  const row=(x,a)=>`<div class="item ${x.id===S.cur?.id?'on':''}" onclick="openSession('${x.id}')" title="${esc(x.summary||x.title)}"><span class="t">${esc(x.title)}</span><span class="x" title="Rename" onclick="event.stopPropagation();renameSession('${x.id}')">✎</span><span class="x" title="${a?'Restore':'Archive'}" onclick="event.stopPropagation();archiveSession('${x.id}',${!a})">${a?'↩':'🗄'}</span><span class="x" title="Delete" onclick="event.stopPropagation();delSession('${x.id}')">✕</span></div>`;
  $('sessions').innerHTML=live_.map(x=>row(x,false)).join('')+(arch.length?`<div class="sec" style="cursor:pointer" onclick="S.showArch=!S.showArch;renderSide()">${S.showArch?'▾':'▸'} Archived (${arch.length})</div>`+(S.showArch?arch.map(x=>row(x,true)).join(''):''):'');
  const act=S.cur?.settings.active||[];
  $('engs').innerHTML=S.cfg.engineers.map(e=>`<div class="item eng ${act.includes(e.id)?'on':''}" onclick="toggleEng('${e.id}')"><div class="av" style="background:${e.color}">${esc(e.avatar||'●')}<i class="sdot ${(S.status.engineers[e.id]||{}).state||''}" title="${esc((S.status.engineers[e.id]||{}).detail||'checking…')}"></i></div><div class="t"><div>${esc(e.name)}${act[0]===e.id&&act.length>1&&S.cur.settings.team?' <span class="badge accent">lead</span>':''}</div><div class="sub">${esc(e.role)}</div></div><span class="x" onclick="event.stopPropagation();editEngineer('${e.id}')">✎</span></div>`).join('');
  $('title').textContent=S.cur?.title||'';{const on=((S.cur?.settings.autoapprove)||'full')!=='ask';if($('ap-on')){$('ap-on').setAttribute('aria-pressed',on);$('ap-off').setAttribute('aria-pressed',!on)}}
  const es=S.cfg.engineers,on=es.filter(e=>(S.status.engineers[e.id]||{}).state==='online').length;
  $('stat').innerHTML=Object.keys(S.status.engineers).length?`<span style="color:${on===es.length?'var(--ok)':on?'var(--warn)':'var(--err)'}">●</span> ${on}/${es.length} online`:'checking…';
  $('target').innerHTML='<option value="local">💻 This Mac</option>'+S.cfg.ssh.map(h=>`<option value="${h.id}">${({online:'🟢',offline:'🔴'})[(S.status.ssh[h.id]||{}).state]||'⚪️'} ${esc(h.name)}</option>`).join('');
  const st=S.cur?.settings||{};$('target').value=st.target||'local';$('mode').value=st.mode||'edit';const tg=S.cfg.ssh.find(h=>h.id===st.target);$('cwd').value=tg?(st.rcwd||tg.cwd||'~'):(st.cwd||'');$('cwd').title=tg?'Folder on '+tg.name+' — click to change':'Working directory — click to change';
  const tm=!!st.team&&act.length>1;$('solo').setAttribute('aria-pressed',!tm);$('team').setAttribute('aria-pressed',tm);
  const names=act.map(i=>eng(i)?.name).filter(Boolean);$('chips').textContent=!names.length?'No engineer selected':tm?`Team: ${names[0]} leads → ${names.slice(1).join(', ')} work → ${names[0]} reviews`:`Replying: ${names.join(', ')} · @name to choose`;
}

// ── sessions
async function openSession(id){S.cur=S.sessions.find(s=>s.id===id);renderSide();renderMsgs(await api().load_session(id))}
async function newSession(){const s=await api().new_session();S.sessions.unshift(s);openSession(s.id)}
async function delSession(id){const x=S.sessions.find(s=>s.id===id);if(await askBox(`Delete "${x.title}" and its messages? This can't be undone.`,null,'Delete')===null)return;
  await api().delete_session(id);S.sessions=S.sessions.filter(s=>s.id!==id);
  if(!S.sessions.some(s=>!s.archived))return newSession();
  if(S.cur.id===id)openSession(S.sessions.find(s=>!s.archived).id);else renderSide()}
async function renameSession(id){const x=S.sessions.find(s=>s.id===id);const t=await askBox('Rename session',x.title,'Rename');if(t&&t.trim()){await api().rename_session(id,t.trim());x.title=t.trim();renderSide()}}
function renameCur(){renameSession(S.cur.id)}
async function archiveSession(id,flag){await api().archive_session(id,flag);const x=S.sessions.find(s=>s.id===id);x.archived=flag;
  if(flag&&S.cur.id===id){const n=S.sessions.find(s=>!s.archived);if(n)openSession(n.id);else await newSession()}else renderSide()}
async function saveSettings(){await api().update_settings(S.cur.id,S.cur.settings);renderSide()}
async function setSet(){S.cur.settings.target=$('target').value;S.cur.settings.mode=$('mode').value;
  if(S.cur.settings.mode==='auto'&&!S.autoWarned){S.autoWarned=1;await askBox('Auto mode lets engineers run any command without asking, on '+$('target').selectedOptions[0].text+'. Use it only for folders you trust.',null,'Got it')}
  saveSettings()}
async function pickDir(){const tg=S.cfg.ssh.find(h=>h.id===S.cur.settings.target);
  browse(tg?(S.cur.settings.rcwd||tg.cwd||'~'):S.cur.settings.cwd)}
let BR={};
async function browse(path){const tid=S.cur.settings.target;BR.tid=tid;
  modal('<h3>Choose working folder</h3><p class="sm">Loading…</p>');
  const r=await api().list_dirs(tid,path);BR.path=r.path;const tg=S.cfg.ssh.find(h=>h.id===tid);
  const recents=[...new Set(S.sessions.map(x=>tid==='local'?x.settings.cwd:x.settings.rcwd).filter(Boolean))].slice(0,5);
  modal(`<h3>Choose working folder <span class="badge accent">${tg?esc(tg.name):'This Mac'}</span></h3>
  <div class="f" style="grid-template-columns:auto 1fr auto"><button class="btn sm" ${r.parent?`onclick="browse('${esc(r.parent).replace(/'/g,"\\'")}')"`:'disabled'}>↑ Up</button><input class="field" id="br_path" value="${esc(r.path||path)}" onkeydown="if(event.key==='Enter')browse(this.value)"><button class="btn sm" onclick="browse('~')">Home</button></div>
  ${r.error?`<p class="sm" style="color:var(--err)">${esc(r.error)}</p>`:''}
  <div class="glass sunken" style="max-height:260px;overflow:auto;padding:6px;margin:8px 0;border-radius:var(--r-md)">${(r.dirs||[]).map(d=>`<div class="item" data-d="${esc(d)}" onclick="browse(BR.path.replace(/\\/$/,'')+'/'+this.dataset.d)">📁 <span class="t">${esc(d)}</span></div>`).join('')||'<p class="sm" style="padding:8px">No sub-folders</p>'}</div>
  ${recents.length?`<div class="sm">Recent: ${recents.map(x=>`<a href="#" onclick="browse(this.dataset.p);return false" data-p="${esc(x)}" style="color:var(--accent);margin-right:8px">${esc(x)}</a>`).join('')}</div>`:''}
  <div class="row">${tid==='local'?'<button class="btn" onclick="finderPick()">Choose in Finder…</button>':''}<button class="btn" onclick="closeModal()">Cancel</button><button class="btn primary" onclick="useFolder()">Use this folder</button></div>`)}
function useFolder(){const p=$('br_path').value.trim()||BR.path;if(BR.tid==='local')S.cur.settings.cwd=p;else S.cur.settings.rcwd=p;closeModal();saveSettings()}
async function finderPick(){const d=await api().pick_dir();if(d){S.cur.settings.cwd=d;closeModal();saveSettings()}}
function setAppr(v){S.cur.settings.autoapprove=v;saveSettings()}
function setTeam(v){S.cur.settings.team=v;saveSettings()}
function toggleEng(id){const a=S.cur.settings.active;const i=a.indexOf(id);i<0?a.push(id):a.splice(i,1);saveSettings()}

// ── chat
const live={};
async function send(){
  if(S.busy){await api().stop(S.cur.id);return}
  const t=$('in').value.trim();if(!t)return;$('in').value='';autosize();
  const m=await api().send(S.cur.id,t,window.ideContext?ideContext():'');if(!m)return;
  if($('msgs').querySelector('.empty'))$('msgs').innerHTML='';
  $('msgs').insertAdjacentHTML('beforeend',msgHtml(m));scroll(true);setBusy(true);
  if(S.cur.title==='New session'){S.cur.title=t.slice(0,48);renderSide()}
}
function setBusy(b){S.busy=b;$('go').textContent=b?'Stop':'Send';$('go').classList.toggle('danger',b)}
window.onEvent=ev=>{
  if(ev.sid&&ev.sid!==S.cur?.id){if(ev.t==='idle')setBusy(false);return}
  const box=ev.mid&&live[ev.mid];
  if(ev.t==='start'){
    const e=engByName(ev.author);const shell=ev.eid==='shell';
    const html=shell?`<div class="m" data-id="${ev.mid}">${avatar('')}<div class="bub shell"><div class="who">Shell</div><pre><code class="body">$ ${esc(ev.shell)}\n</code></pre></div></div>`
      :`<div class="m" data-id="${ev.mid}">${avatar(ev.author)}<div class="bub"><div class="who">${esc(ev.author)}${ev.via?`<span class="badge">${esc(ev.via)}</span>`:''}</div>${activityHtml({},true)}<div class="body cursor"></div></div></div>`;
    $('msgs').insertAdjacentHTML('beforeend',html);const el=$('msgs').lastElementChild;
    live[ev.mid]={el,text:'',shell,t0:Date.now(),author:ev.author,steps:0,step:'Starting…'};scroll();renderProgress();
  }else if(ev.t==='text'&&box){box.text+=ev.d;const b=box.el.querySelector('.body');if(box.shell)b.textContent+=ev.d;else{b.innerHTML=md(box.text);if(!box.shell){box.step='Writing the answer…';nowText(box,'Writing the answer…')}}scroll()}
  else if(ev.t==='tool'&&box){const t=box.el.querySelector('.steps');const ex=box.el.querySelector('[id="t-'+CSS.escape(ev.tool.id)+'"]');
    if(ex){const o=ex.classList.contains('open');ex.outerHTML=toolHtml(ev.tool);if(o)box.el.querySelector('[id="t-'+CSS.escape(ev.tool.id)+'"]').classList.add('open')}else{t.insertAdjacentHTML('beforeend',toolHtml(ev.tool));box.steps++}box.step=(ev.tool.state==='running'?'▶ ':ev.tool.state==='error'?'✕ ':'✓ ')+ev.tool.name+(ev.tool.command?': '+ev.tool.command:'');nowText(box,box.step);scroll()}
  else if(ev.t==='thought'&&box){const st=box.el.querySelector('.steps');let th=st.lastElementChild;if(!th||!th.classList.contains('th')){st.insertAdjacentHTML('beforeend','<div class="step th"><b>Thinking</b><span></span></div>');th=st.lastElementChild;box.steps++}th.lastElementChild.textContent+=ev.d;box.step='Thinking…';nowText(box,'Thinking…');if(stick)st.scrollTop=st.scrollHeight;scroll()}
  else if(ev.t==='end'&&box){const vd=(ev.content||'').match(/VERDICT:\s*(PASS|FAIL|UNVERIFIED)/);if(vd)box.el.querySelector('.who').insertAdjacentHTML('beforeend',`<span class="badge ${vd[1]==='PASS'?'ok':vd[1]==='FAIL'?'err':'warn'}">${vd[1]==='PASS'?'✓ verified':vd[1]==='FAIL'?'✕ failed':'unverified'}</span>`);const b=box.el.querySelector('.body');b.classList.remove('cursor');if(!box.shell)b.innerHTML=md(ev.content||'');
    {const sm=box.el.querySelector('.actv>.sum');if(sm){const bad=ev.error&&ev.error!=='Stopped';const sp=sm.querySelector('.spin');if(sp)sp.outerHTML=`<span class="${bad?'bad':'ok'}">${bad?'✕':'✓'}</span>`;const n=box.steps;nowText(box,(n?n+' step'+(n===1?'':'s'):'No tool calls')+' · '+(ev.dur??Math.round((Date.now()-box.t0)/1000))+'s');const el=sm.querySelector('.el');if(el)el.textContent='';if(!n&&!box.el.querySelector('.step')){const d=box.el.querySelector('.actv');if(d)d.remove()}}}
    delete live[ev.mid];renderProgress();if(ev.memory)S.memory=ev.memory}
  else if(ev.t==='settings'){if(S.cur&&S.cur.id===ev.sid){S.cur.settings=ev.settings;renderSide();if(window.ideOnSettings)ideOnSettings(ev.settings)}}
  else if(ev.t==='autoapproved'){if($('msgs').querySelector('.empty'))$('msgs').innerHTML='';$('msgs').insertAdjacentHTML('beforeend',`<div class="m"><div class="bub sm" style="padding:2px 10px;background:none;box-shadow:none">✓ ${esc(ev.who)} ran <code>${esc(ev.cmd.length>90?ev.cmd.slice(0,90)+'…':ev.cmd)}</code> <span class="sm">(${esc(ev.why)})</span></div></div>`);scroll()}
  else if(ev.t==='approval'){if($('msgs').querySelector('.empty'))$('msgs').innerHTML='';
    $('msgs').insertAdjacentHTML('beforeend',`<div class="m" id="ap-${ev.cid}">${avatar(ev.who)}<div class="bub"><div class="who">${esc(ev.who)} wants to run a command <span class="badge accent">${esc(ev.where)}</span></div><pre><code>$ ${esc(ev.cmd)}</code></pre><div class="sm">in ${esc(ev.cwd)}</div><div class="apb" style="display:flex;gap:8px;margin-top:8px"><button class="btn sm primary" onclick="apv('${ev.cid}',true)">Run</button><button class="btn sm" onclick="apv('${ev.cid}',false)">Skip</button>${ev.risky?'<span class="sm" style="align-self:center">⚠ risky — always asks</span>':`<button class="btn sm ghost" onclick="apv('${ev.cid}',true,'session')" title="Run it, and run every non-risky command this session without asking">Allow all this session</button>`}</div></div></div>`);scroll()}
  else if(ev.t==='message'){if(ev.message.author==='Team'&&ev.message.role==='system')PH=ev.message.content.split(' · ')[0];if($('msgs').querySelector('.empty'))$('msgs').innerHTML='';$('msgs').insertAdjacentHTML('beforeend',msgHtml(ev.message));scroll()}
  else if(ev.t==='memory'){S.memory=ev.memory;if(ev.learned){const c=$('chips');const o=c.textContent;c.textContent='🧠 Memory updated';setTimeout(renderSide,2500)}}
  else if(ev.t==='idle'){if(window.ideOnIdle)ideOnIdle();PH='';renderProgress();$('jump')&&($('jump').hidden=true);setBusy(false);S.sessions.sort((a,b)=>0)}
};
function apv(cid,ok,scope){api().approve(cid,ok,scope||'');const el=document.getElementById('ap-'+cid);if(el){const b=el.querySelector('.apb');if(b)b.outerHTML=`<div class="sm">${ok?'✓ approved — running':'✕ skipped'}</div>`}}
// composer
function autosize(){const e=$('in');e.style.height='auto';e.style.height=Math.min(e.scrollHeight,180)+'px'}
$('in').addEventListener('input',()=>{autosize();mention()});
$('in').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('hint').style.display='none';send()}if(e.key==='Escape')$('hint').style.display='none'});
function mention(){const v=$('in').value;const m=v.match(/@([\w-]*)$/);const h=$('hint');
  if(!m){h.style.display='none';return}
  const opts=[...S.cfg.engineers.map(e=>e.name),'all'].filter(n=>n.toLowerCase().startsWith(m[1].toLowerCase()));
  if(!opts.length){h.style.display='none';return}
  h.innerHTML=opts.map(n=>`<div class="item" onmousedown="event.preventDefault();pick('${n}')">@${esc(n)}</div>`).join('');h.style.display='block'}
function pick(n){const i=$('in');i.value=i.value.replace(/@[\w-]*$/,'@'+n+' ');$('hint').style.display='none';i.focus()}

// ── modals
function modal(html){$('card').innerHTML=html;$('modal').classList.add('show')}
function closeModal(){$('modal').classList.remove('show')}
const PROVIDERS={claude_cli:'Claude Code (claude)',antigravity_cli:'Google Antigravity (agy)',bob_cli:'IBM Bob (bob)',openai_api:'API: ChatGPT / Ollama (Llama) / FreeLLMAPI / any OpenAI-compatible',custom:'Custom CLI (prompt on stdin)'};
const PRESETS=[['OpenAI (ChatGPT)','https://api.openai.com/v1'],['Ollama (Llama, local)','http://localhost:11434/v1'],['FreeLLMAPI (local agent)','http://localhost:3001/v1'],['Custom URL','']];
const CMDS={claude_cli:'claude',antigravity_cli:'agy',bob_cli:'bob',openai_api:'',custom:''};
function editEngineer(id){
  const e=id?eng(id):{name:'',provider:'claude_cli',command:'claude',model:'',role:'Software Engineer',color:'#7aa7ff',avatar:'◆',args:''};
  modal(`<h3>${id?'Edit':'Add'} engineer</h3>
  <div class="f"><label>Name</label><input class="field" id="e_name" data-id="${id||''}" value="${esc(e.name)}"></div>
  <div class="f"><label>Role</label><input class="field" id="e_role" value="${esc(e.role)}"></div>
  <div class="f"><label>Provider</label><select class="field" id="e_prov" onchange="provChange()">${Object.entries(PROVIDERS).map(([k,v])=>`<option value="${k}" ${k===e.provider?'selected':''}>${v}</option>`).join('')}</select></div>
  <div class="f" id="r_url"><label>API endpoint</label><div style="display:flex;gap:6px"><select class="field" id="e_preset" onchange="presetPick()" style="width:auto">${PRESETS.map(([l,u])=>`<option value="${u}" ${u===(e.base_url||'')?'selected':''}>${l}</option>`).join('')}</select><input class="field" id="e_url" value="${esc(e.base_url||'')}" placeholder="http://host:port/v1" onchange="fetchModels()"></div></div>
  <div class="f" id="r_cmd"><label>Command</label><input class="field" id="e_cmd" value="${esc(e.command)}"></div>
  <div class="f"><label>Model</label><div style="display:flex;gap:6px"><select class="field" id="e_modelsel" onchange="modelPick()"><option value="${esc(e.model)}">${esc(e.model||'Default')}</option></select><input class="field" id="e_model" value="${esc(e.model)}" style="display:none" placeholder="model id"><button class="btn sm" onclick="fetchModels()" id="e_fetch">↻ Fetch</button></div></div>
  <div class="f"><label>API key</label><input class="field" id="e_key" type="password" autocomplete="off" placeholder="${e.has_key?'✓ saved — type to replace':'optional · stored locally (chmod 600)'}"></div>
  <div class="f" id="r_args"><label>Extra args</label><input class="field" id="e_args" value="${esc(e.args)}"></div>
  <div class="f"><label>Avatar / colour</label><div style="display:flex;gap:8px"><input class="field" id="e_av" value="${esc(e.avatar)}" style="width:70px"><input class="field" id="e_col" type="color" value="${e.color}" style="padding:0;width:50px;height:30px"></div></div>
  <div class="row">${id?`<button class="btn danger" onclick="delEngineer('${id}')">Delete</button>`:''}<button class="btn" onclick="closeModal()">Cancel</button><button class="btn primary" onclick="saveEngineer('${id||''}')">Save</button></div>`);provRows();fetchModels()}
function provRows(){const a=$('e_prov').value==='openai_api';$('r_url').style.display=a?'':'none';$('r_cmd').style.display=$('r_args').style.display=a?'none':'';
  if(a&&!$('e_url').value){$('e_url').value=PRESETS[0][1];$('e_preset').value=PRESETS[0][1]}
  if(a)$('e_key').placeholder=$('e_key').placeholder.startsWith('✓')?$('e_key').placeholder:'OpenAI key · FreeLLMAPI unified key · blank for Ollama'}
function presetPick(){const u=$('e_preset').value;$('e_url').value=u;if(u){fetchModels()}else $('e_url').focus()}
function provChange(){$('e_cmd').value=CMDS[$('e_prov').value];provRows();$('e_model').value='';$('e_modelsel').innerHTML='<option value="">Default</option>';fetchModels()}
function modelPick(){const v=$('e_modelsel').value;const c=v==='__custom';$('e_model').style.display=c?'':'none';if(!c)$('e_model').value=v;else $('e_model').focus()}
async function fetchModels(){const b=$('e_fetch');b.textContent='Fetching…';const cur=$('e_model').value;
  const r=await api().list_models({id:$('e_name')?.dataset.id||'',provider:$('e_prov').value,command:$('e_cmd').value,base_url:$('e_url').value.trim(),api_key:$('e_key').value});
  const ms=r.models||[];const opts=[['','Default']].concat(ms.map(m=>[m.id,m.label+(m.label!==m.id?` — ${m.id}`:'')]));
  if(cur&&!ms.some(m=>m.id===cur))opts.push([cur,cur]);opts.push(['__custom','Custom…']);
  $('e_modelsel').innerHTML=opts.map(([v,l])=>`<option value="${esc(v)}">${esc(l)}</option>`).join('');$('e_modelsel').value=cur||'';
  b.textContent=r.error?'↻ Retry':`↻ ${ms.length} found`;if(r.error)b.title=r.error}
async function saveEngineer(id){
  const e={id:id||undefined,name:$('e_name').value.trim(),role:$('e_role').value,provider:$('e_prov').value,command:$('e_cmd').value.trim(),model:$('e_model').value.trim(),api_key:$('e_key').value.trim()||undefined,args:$('e_args').value,avatar:$('e_av').value,color:$('e_col').value};
  if(e.provider==='openai_api'){e.base_url=$('e_url').value.trim().replace(/\/+$/,'');if(!e.base_url)return}
  if(!e.name)return;S.cfg=await api().save_engineer(e);closeModal();renderSide()}
async function delEngineer(id){S.cfg=await api().delete_engineer(id);S.sessions.forEach(s=>s.settings.active=s.settings.active.filter(x=>x!==id));closeModal();renderSide()}
function sshModal(){
  modal(`<h3>SSH connections</h3><p class="sm">Commands (and engineers) run on the remote machine over key-based SSH. Engineers need their CLI (claude / agy) installed there. Use the "Run here" selector in the top bar.</p>
  ${S.cfg.ssh.map(h=>`<div class="mem"><span><b>${esc(h.name)}</b> <span class="sm">${esc(h.user)}@${esc(h.host)}:${h.port||22}</span></span><button class="btn sm" onclick="testSsh('${h.id}')">Test</button><button class="btn sm" onclick="sshForm('${h.id}')">✎</button></div>`).join('')||'<p class="sm" style="margin-top:10px">None yet.</p>'}
  <pre id="sshout" class="sm" style="white-space:pre-wrap;margin-top:8px"></pre>
  <div class="f" style="grid-template-columns:1fr auto"><input class="field" id="s_quick" placeholder="Quick add: user@192.168.1.50 or user@host:2222" onkeydown="if(event.key==='Enter')quickSsh()"><button class="btn" onclick="quickSsh()">Add</button></div>
  <div class="row"><button class="btn" onclick="importSsh()">Import from ~/.ssh/config</button><button class="btn" onclick="closeModal()">Close</button><button class="btn primary" onclick="sshForm()">＋ Manual</button></div>`)}
async function quickSsh(){const v=$('s_quick').value.trim();const m=v.match(/^(?:([^@\s]+)@)?([^:\s]+)(?::(\d+))?$/);if(!m)return;
  S.cfg=await api().save_ssh({name:m[2],host:m[2],user:m[1]||'',port:+m[3]||22,key:S.defKey||'',cwd:'~'});sshModal();renderSide()}
async function importSsh(){const hs=await api().ssh_config_hosts();if(!hs.length){$('sshout').textContent='No Host entries found in ~/.ssh/config';return}
  for(const h of hs){if(!S.cfg.ssh.some(x=>x.name===h.name))S.cfg=await api().save_ssh(h)}sshModal();renderSide()}
function sshForm(id){const h=S.cfg.ssh.find(x=>x.id===id)||{name:'',host:'',user:'',port:22,key:S.defKey||'',cwd:'~'};
  modal(`<h3>${id?'Edit':'New'} SSH connection</h3>
  <div class="f"><label>Name</label><input class="field" id="s_name" value="${esc(h.name)}" placeholder="Ubuntu VM"></div>
  <div class="f"><label>Host / IP</label><input class="field" id="s_host" value="${esc(h.host)}"></div>
  <div class="f"><label>User</label><input class="field" id="s_user" value="${esc(h.user)}"></div>
  <div class="f"><label>Port</label><input class="field" id="s_port" value="${h.port||22}"></div>
  <div class="f"><label>Key file</label><input class="field" id="s_key" value="${esc(h.key)}" placeholder="optional — blank uses ssh defaults / agent"></div>
  <div class="f"><label>Start folder</label><input class="field" id="s_cwd" value="${esc(h.cwd||'~')}" placeholder="~"></div>
  <div class="row">${id?`<button class="btn danger" onclick="delSsh('${id}')">Delete</button>`:''}<button class="btn" onclick="sshModal()">Back</button><button class="btn primary" onclick="saveSsh('${id||''}')">Save</button></div>`)}
const sshVal=()=>({name:$('s_name').value.trim(),host:$('s_host').value.trim(),user:$('s_user').value.trim(),port:+$('s_port').value||22,key:$('s_key').value.trim(),cwd:$('s_cwd').value.trim()||'~'});
async function saveSsh(id){const h=sshVal();if(!h.host)return;if(id)h.id=id;S.cfg=await api().save_ssh(h);sshModal();renderSide()}
async function delSsh(id){S.cfg=await api().delete_ssh(id);S.sessions.forEach(s=>{if(s.settings.target===id)s.settings.target='local'});sshModal();renderSide()}
async function testSsh(id){$('sshout').textContent='Connecting…';const r=await api().test_ssh(S.cfg.ssh.find(h=>h.id===id));$('sshout').textContent=(r.ok?'✓ ':'✕ ')+r.output+(!r.ok&&/denied|publickey/i.test(r.output)?'\n\nKey login isn\'t set up. Run once in Terminal:  ssh-copy-id '+(h=>`${h.user?h.user+'@':''}${h.host}`)(S.cfg.ssh.find(h=>h.id===id)):'')}
function memModal(){
  modal(`<h3>🧠 Shared memory</h3><p class="sm">Every engineer sees these notes in every session. The app learns new ones from your chats automatically (one quick background call after each reply); <code>/remember …</code> also works.</p>
  <label style="display:flex;gap:8px;align-items:center;margin:10px 0"><input type="checkbox" ${S.cfg.auto_memory?'checked':''} onchange="S.cfg.auto_memory=this.checked;api().set_auto_memory(this.checked)"> Learn from chats automatically</label>
  <div id="memlist">${S.memory.map(m=>`<div class="mem"><span>${esc(m.text)} <span class="sm">· ${esc(m.source)}</span></span><button class="btn sm" onclick="delMem('${m.id}')">✕</button></div>`).join('')||'<p class="sm" style="margin-top:10px">Nothing yet.</p>'}</div>
  <div class="f" style="grid-template-columns:1fr auto;margin-top:12px"><input class="field" id="m_new" placeholder="Add a note…" onkeydown="if(event.key==='Enter')addMem()"><button class="btn primary" onclick="addMem()">Add</button></div>
  <div class="row"><button class="btn" onclick="closeModal()">Close</button></div>`)}
async function addMem(){const v=$('m_new').value;S.memory=await api().add_memory(v,'you');memModal()}
async function delMem(id){S.memory=await api().delete_memory(id);memModal()}

function askBox(title,value,okLabel='OK'){return new Promise(res=>{
  modal(`<h3>${esc(title)}</h3>${value===null?'':`<input class="field" id="ask_v" value="${esc(value)}">`}<div class="row"><button class="btn" id="ask_c">Cancel</button><button class="btn primary" id="ask_o">${okLabel}</button></div>`);
  const v=$('ask_v');if(v){v.focus();v.select();v.onkeydown=e=>{if(e.key==='Enter')$('ask_o').click()}}
  $('ask_c').onclick=()=>{closeModal();res(null)};$('ask_o').onclick=()=>{const r=v?v.value:true;closeModal();res(r)}})}
async function refreshStatus(){$('stat').textContent='checking…';try{S.status=await api().check_status()}catch(e){}renderSide()}
setInterval(()=>{if(window.pywebview&&!S.busy)refreshStatus()},45000);

function chatInit(b){S.cfg=b.config;S.defKey=b.default_key;S.sessions=b.sessions;S.memory=b.memory;S.home=b.home;
  S.sessions.forEach(s=>s.settings={cwd:b.home,target:'local',mode:'edit',team:true,active:[],...s.settings});}
