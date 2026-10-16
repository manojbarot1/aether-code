// Agents panel (lower half of the sidebar): what each engineer is doing right now, across all sessions.
(()=>{
const A={}, MID={}, LAST={};   // A: eid → state · MID: message id → eid · LAST: session → eid whose command is about to run
const byName=n=>S.cfg?.engineers.find(e=>e.name===n);
const short=(s,n=70)=>{s=String(s||'').replace(/\s+/g,' ').trim();return s.length>n?s.slice(0,n)+'…':s};
const ago=t=>{const s=Math.round((Date.now()-t)/1000);return s<60?`${s}s`:s<3600?`${Math.floor(s/60)}m`:`${Math.floor(s/3600)}h`};
const sessTitle=sid=>(S.sessions||[]).find(s=>s.id===sid)?.title||'';
function set(eid,patch){if(!eid)return;A[eid]={...(A[eid]||{}),...patch};render()}

const prev=window.onEvent;
window.onEvent=ev=>{
  try{track(ev)}catch(e){}
  return prev(ev)};

function track(ev){
  const sid=ev.sid;
  if(ev.t==='start'){
    if(ev.eid==='shell'){const eid=LAST[sid];MID[ev.mid]='shell:'+eid;set(eid,{state:'run',detail:'Running '+short(ev.shell,60),sid});return}
    MID[ev.mid]=ev.eid;
    set(ev.eid,{state:'work',detail:ev.via?`Starting (${ev.via})…`:'Starting…',since:A[ev.eid]?.state==='work'||A[ev.eid]?.state==='run'?A[ev.eid].since:Date.now(),sid});
  }else if(ev.t==='thought'){set(MID[ev.mid],{detail:'Thinking…'})}
  else if(ev.t==='text'){const e=MID[ev.mid];if(e&&!e.startsWith('shell:')&&A[e]?.detail!=='Writing the reply…')set(e,{detail:'Writing the reply…'})}
  else if(ev.t==='tool'){const t=ev.tool||{};set(MID[ev.mid],{detail:short(`${t.name||'tool'}${t.command?': '+t.command:''}`)})}
  else if(ev.t==='approval'){const e=byName(ev.who);if(e){LAST[sid]=e.id;set(e.id,{state:'wait',detail:'Waiting for your OK: '+short(ev.cmd,50)})}}
  else if(ev.t==='autoapproved'){const e=byName(ev.who);if(e){LAST[sid]=e.id;set(e.id,{state:'run',detail:'Running '+short(ev.cmd,60)})}}
  else if(ev.t==='end'){
    const e=MID[ev.mid];delete MID[ev.mid];if(!e)return;
    if(e.startsWith('shell:')){set(e.slice(6),{state:'work',detail:'Reading command output…'});return}
    const a=A[e]||{};
    set(e,{state:ev.ok?'done':'fail',detail:ev.ok?`Finished in ${Math.round(a.since?(Date.now()-a.since)/1000:ev.dur||0)}s`:short(ev.error||'Failed',80),at:Date.now()});
  }else if(ev.t==='idle'){
    for(const[k,a]of Object.entries(A))if(a.sid===sid&&['work','run','wait'].includes(a.state))A[k]={...a,state:'done',detail:'Stopped',at:Date.now()};
    render();
  }
}

const LABEL={work:'working',run:'running',wait:'needs you',done:'idle',fail:'failed'};
function render(){
  const box=document.getElementById('agents-list');if(!box||!S.cfg)return;
  const engs=S.cfg.engineers, busy=e=>['work','run','wait'].includes(A[e.id]?.state);
  const n=engs.filter(busy).length;
  document.getElementById('agents-sum').textContent=n?`${n} working`:'all idle';
  document.getElementById('agents-sum').className='agents-sum'+(n?' on':'');
  const rows=[...engs].sort((a,b)=>busy(b)-busy(a));
  box.innerHTML=rows.map(e=>{
    const a=A[e.id]||{}, st=S.status?.engineers?.[e.id]||{}, s=a.state||'';
    const live=busy(e);
    const offline=!live&&st.state&&st.state!=='online';
    const detail=live?a.detail:offline?(st.detail||st.state):a.detail?`${a.detail} · ${ago(a.at||Date.now())} ago`:'Idle';
    const other=live&&a.sid&&a.sid!==S.cur?.id?`<span class="ag-sess" title="${esc(sessTitle(a.sid))}">in ${esc(short(sessTitle(a.sid),18))}</span>`:'';
    return `<div class="ag ${s} ${live?'live':''} ${offline?'off':''}" title="${esc(e.name)} · ${esc(e.role)}${a.detail?'\n'+esc(a.detail):''}">
      <div class="av" style="background:${e.color}">${esc(e.avatar||'●')}<i class="sdot ${st.state||''}"></i></div>
      <div class="ag-t"><div class="ag-top"><b>${esc(e.name)}</b><span class="ag-state">${live?esc(LABEL[s]):offline?'offline':s==='fail'?'failed':''}</span>${other}${live&&a.since?`<span class="ag-time">${ago(a.since)}</span>`:''}</div>
      <div class="ag-d">${esc(detail||'')}</div></div></div>`}).join('')||'<div class="ag-empty">No engineers yet</div>';
}

const _rs=renderSide;renderSide=function(){_rs();render()};
document.getElementById('agents-head').onclick=()=>{
  const sec=document.getElementById('agents');sec.classList.toggle('collapsed');
  try{localStorage.setItem('aether.agents.collapsed',sec.classList.contains('collapsed')?'1':'')}catch(e){}};
try{if(localStorage.getItem('aether.agents.collapsed'))document.getElementById('agents').classList.add('collapsed')}catch(e){}
setInterval(()=>{if(Object.values(A).some(a=>['work','run','wait'].includes(a.state))||Object.keys(A).length)render()},1000);
render();
})();
