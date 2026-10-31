'use strict';
const el = id => document.getElementById(id);
let snapshot = {state: 'idle'}, previous = {}, busy = false, history = [], lastStop = '';
function text(tag, value, cls) { const node = document.createElement(tag); node.textContent = value; if (cls) node.className = cls; return node; }
function controls() {
  const stopped = snapshot.state === 'stopped';
  ['continue', 'step', 'source-step'].forEach(id => el(id).disabled = busy || !stopped);
  el('pause').disabled = busy || snapshot.state !== 'running';
  el('stop').disabled = busy || !['running','stopped'].includes(snapshot.state);
  el('launch').disabled = busy;
  el('breakForm').querySelector('button').disabled = busy || !stopped;
}
async function command(command, argument = '') {
  if (busy) return;
  busy = true; controls();
  try {
    const response = await fetch('/api/command', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({command, argument})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Command failed');
    if (command === 'launch' && !data.error) { history=[]; previous={}; lastStop=''; }
    render(data);
  } catch (error) { el('error').textContent=error.message; el('error').hidden=false; }
  finally { busy=false; controls(); }
}
function render(data) {
  snapshot=data;
  el('error').hidden=!data.error; el('error').textContent=data.error || '';
  el('state').textContent=data.state; el('state').className='state '+data.state;
  el('binary').textContent=data.binary || 'No executable loaded';
  el('reason').textContent=data.reason || 'Launch an example to begin.';
  el('pid').textContent=data.pid > 0 ? 'PID '+data.pid : 'PID —';
  el('output').textContent=data.output || 'Waiting for program output…';
  const registers=el('registers'); registers.replaceChildren();
  for (const [name,value] of Object.entries(data.registers || {})) {
    const row=text('div','', 'reg'+(previous[name] && previous[name]!==value ? ' changed':''));
    row.append(text('span',name.toUpperCase()),text('b',value)); registers.append(row);
  }
  if(data.state==='stopped') previous={...data.registers};
  const bps=el('breakpoints'); bps.replaceChildren(); el('bpCount').textContent=(data.breakpoints || []).length;
  for(const address of data.breakpoints || []) { const row=text('div','','bp'); const remove=text('button','×'); remove.setAttribute('aria-label','Remove breakpoint '+address); remove.onclick=()=>command('delete',address); row.append(text('span',address),remove); bps.append(row); }
  const symbols=el('symbols'); symbols.replaceChildren();
  for(const symbol of data.symbols || []) { const button=text('button',symbol.label || symbol.name); button.disabled=data.state!=='stopped'; button.onclick=()=>command('break',symbol.name); symbols.append(button); }
  const stack=el('stack'); stack.replaceChildren(); el('frameCount').textContent=(data.stack || []).length+' FRAMES';
  for(const [i,frame] of (data.stack || []).entries()) { const row=text('div',`#${i}  ${frame.name}`, 'frame'); row.append(text('small',frame.address+' · '+frame.location)); stack.append(row); }
  const memory=el('memory'); memory.replaceChildren();
  for(const item of data.memory || []) { const row=text('div','','memrow'); row.append(text('span',item.address),text('span',item.value)); memory.append(row); }
  if(data.source) {
    el('sourceName').textContent=data.source.name; el('location').textContent='LINE '+data.source.line;
    const source=el('source'); source.replaceChildren();
    data.source.text.split('\n').forEach((line,i)=>{ const row=text('div','','source-line'+(i+1===data.source.line?' current':'')); row.append(text('span',String(i+1),'ln'),text('code',line)); source.append(row); });
    source.querySelector('.current')?.scrollIntoView({block:'nearest'});
  } else if(data.state!=='idle') {
    el('sourceName').textContent='SOURCE'; el('location').textContent='No source mapping';
    el('source').replaceChildren(text('p',data.state==='running'?'Process running. Pause to inspect.':'No example source at this address. Set a breakpoint at main, then continue.','empty-small'));
  }
  const stopKey=data.state+JSON.stringify(data.registers)+data.reason;
  if(data.state==='stopped' && stopKey!==lastStop) {
    lastStop=stopKey;
    history.unshift({time:new Date().toISOString(),reason:data.reason,registers:{...data.registers},stack:data.stack || []});
    history=history.slice(0,100);
  }
  el('historyCount').textContent=history.length;
  const historyView=el('history'); historyView.replaceChildren();
  for(const [i,item] of history.slice(0,8).entries()) { const row=text('div','','history-entry'); row.append(text('span',String(history.length-i).padStart(2,'0')),text('span',item.reason),text('small',item.registers.rip)); historyView.append(row); }
  controls();
}
el('launch').onclick=()=>command('launch',el('target').value);
['continue','step','source-step','pause','stop'].forEach(id=>el(id).onclick=()=>command(id));
el('breakForm').onsubmit=event=>{event.preventDefault(); command('break',el('address').value.trim());};
el('export').onclick=()=>{ const url=URL.createObjectURL(new Blob([JSON.stringify({format:'stillpoint-stops-v1',history},null,2)],{type:'application/json'})); const a=document.createElement('a'); a.href=url; a.download='stillpoint-stops.json'; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); };
document.addEventListener('keydown',event=>{if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName))return; if(event.key==='F8'||event.key==='F10'){event.preventDefault();if(snapshot.state==='stopped')command(event.key==='F8'?'continue':'step');}});
setInterval(async()=>{if(busy || snapshot.state!=='running')return; busy=true; try {const response=await fetch('/api/status');if(response.ok)render(await response.json());}catch(error){el('error').textContent=error.message;el('error').hidden=false;}finally{busy=false;controls();}},750);
controls();
fetch('/api/status').then(response=>response.json()).then(render).catch(error=>{
  el('error').textContent=error.message; el('error').hidden=false;
});
fetch('/api/targets').then(response=>response.json()).then(data=>{
  const labels={ledger:'ledger · successful settlement',crash:'crash · invalid pointer',loop:'loop · pause and resume'};
  el('target').replaceChildren();
  for(const target of data.targets) { const option=text('option',labels[target] || target); option.value=target; el('target').append(option); }
  if(data.targets.includes('ledger')) el('target').value='ledger';
}).catch(()=>{});
