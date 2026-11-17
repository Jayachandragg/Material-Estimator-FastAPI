// Builds public/static/estimator-ui.js from reference/calculator_v8.html.
// The calculator's screens (HTML, layout, product cards, validation) are copied VERBATIM.
// A bridge at the end replaces compute()/lineInfo() with results from the Python API (/api/calc),
// so every material quantity shown comes from the verified Python engine.
// Usage (from the project root):  node tools/build_ui.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'reference', 'calculator_v8.html'), 'utf8');

const scripts = [...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)];
const main = scripts.find((m) => m[1].trim() === '' && m[2].includes('function compute()'))[2]
  .split(/\r?\n/).filter((l) => !l.startsWith('const P = ') && !l.startsWith('const STEPS = ')).join('\n');
const cards = scripts.find((m) => m[1].includes('product-card-presentation'))[2];
const raw = (main + '\n/* ---- product-card-presentation ---- */\n' + cards)
  .replaceAll('src="UI/uploads/', 'src="/static/UI/uploads/');

const SHELL = `<div id="estimator-app"><header class="topbar">
  <button class="brand brand-home" type="button" id="brand-home" aria-label="Back">
    <div class="brand-mark">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 20V9l9-5 9 5v11"/><path d="M8 20v-6h8v6"/></svg>
    </div>
    <div>
      <div class="brand-name">Material Estimator</div>
      <div class="brand-sub">Outsulation Plus MD system</div>
    </div>
  </button>
  <div class="top-actions">
    <button class="chip-btn" id="to-dashboard" type="button">← Dashboard</button>
    <button class="chip-btn" id="theme" type="button">Dark / light</button>
  </div>
</header>
<div class="layout">
  <aside class="rail"><ol class="steps" id="rail"></ol>
    <div class="rail-foot">Quantities are shown exactly as the coverage math gives them. Confirm final orders with your Dryvit representative.</div>
  </aside>
  <main id="stage"></main>
  <aside class="side" id="side"></aside></div>
</div>`;

const bridge = String.raw`
/* ====================== END verbatim calculator_v8.html ====================== */

/* ---- bridge: snapshot / restore (copied from calculator_v8.html's welcome-ui script) ---- */
function snapshotEstimate(){return {state:JSON.parse(JSON.stringify(S)),project:{...projectDetails}}}
function restoreEstimate(saved){
  Object.keys(S).forEach(key=>delete S[key]);Object.assign(S,JSON.parse(JSON.stringify(saved.state)));
  Object.keys(projectDetails).forEach(key=>projectDetails[key]='');Object.assign(projectDetails,saved.project||{});
  cur=NAV.length-1;renderStage();refresh();
}

/* ---- bridge: every material calculation comes from the Python engine (/api/calc) ---- */
let apiResult={lines:[],errors:{},done:{},noArea:true};
let calcTimer=null, inflight=0, seq=0, waiters=[];
const calcDelay=opts.debounceMs ?? 150;
function toUi(r){
  return {noArea:!!r.noArea, errors:r.errors||{}, done:r.done||{},
    lines:(r.lines||[]).map(x=>({sid:x.sid, tag:x.layer, prod:byId(x.pid)||{id:x.pid,name:x.product,unit:x.unit,ud:''},
      __info:{units:x.units, unit:x.unit, cov:x.coverage, variant:x.variant, ask:x.ask}}))};
}
compute=function(){return apiResult;};
lineInfo=function(l){return l.__info;};
function settle(){ if(!calcTimer && !inflight){ const w=waiters; waiters=[]; w.forEach(f=>f()); } }
function whenReady(){ return (calcTimer||inflight) ? new Promise(r=>waiters.push(r)) : Promise.resolve(); }
const refreshBeforeBridge=refresh;
function showResults(){ refreshBeforeBridge(); if(NAV[cur] && NAV[cur].kind==='review') renderStage(); }
function runCalc(){
  const my=++seq; inflight++;
  Promise.resolve().then(()=>opts.calc(JSON.parse(JSON.stringify(S))))
    .then(r=>{ if(my===seq){ apiResult=toUi(r); if(opts.onCalcOk) opts.onCalcOk(); showResults(); } },
          e=>{ if(my===seq && opts.onCalcError) opts.onCalcError(e); })
    .finally(()=>{ inflight--; settle(); });
}
function scheduleCalc(){ if(calcTimer) clearTimeout(calcTimer); calcTimer=setTimeout(()=>{ calcTimer=null; runCalc(); }, calcDelay); }
refresh=function(){ refreshBeforeBridge(); scheduleCalc(); };
// "Next" checks this page's errors, which come from the calculation: wait for the latest result.
const goBeforeBridge=go;
go=function(i){ whenReady().then(()=>goBeforeBridge(i)); };

/* ---- bridge: PDF / Excel buttons, required-field markers, labels ---- */
function addExportButtons(){
  const box=document.querySelector('#stage .dashboard-actions');
  if(!box||box.querySelector('[data-act="export-pdf"]'))return;
  const save=box.querySelector('[data-act="save-estimate"]');
  for(const [act,label] of [['export-pdf','PDF'],['export-excel','Excel']]){
    const b=document.createElement('button');b.className='btn';b.type='button';b.dataset.act=act;b.textContent=label;
    box.insertBefore(b,save);
  }
  if(save&&opts.saveLabel)save.textContent=opts.saveLabel;
}
function markRequiredFields(){
  if(NAV[cur]?.kind!=='project')return;
  const stage=document.getElementById('stage');
  const star=el=>{
    if(!el||el.querySelector('.req-star'))return;
    const last=el.lastChild;
    if(last&&last.nodeType===3)last.textContent=last.textContent.replace(/:\s*$/,'');
    const s=document.createElement('span');s.className='req-star';s.setAttribute('aria-hidden','true');s.textContent=' *';
    el.appendChild(s);
  };
  for(const key of ['name','architect','installer','estimator','date']){
    star(stage.querySelector('label[for="project-'+key+'"]'));
    stage.querySelector('#project-'+key)?.setAttribute('aria-required','true');
  }
  for(const f of ['area','joints','openings']){
    const input=stage.querySelector('input[data-field="'+f+'"]');
    star(input?.closest('.card')?.querySelector('.lbl'));
    input?.setAttribute('aria-required','true');
  }
  const title=stage.querySelector('#project-details-title');
  if(title&&!stage.querySelector('.req-note')){
    const note=document.createElement('p');note.className='req-note';
    note.innerHTML='Fields marked <span class="req-star">*</span> are required.';
    title.after(note);
  }
}
const renderStageBeforeBridge=renderStage;
renderStage=function(){renderStageBeforeBridge();addExportButtons();markRequiredFields();};

stage.addEventListener('click',e=>{
  const b=e.target.closest('[data-act]');if(!b)return;
  const a=b.dataset.act;
  if(a==='save-estimate'){
    whenReady().then(()=>opts.onSave(snapshotEstimate(),{name:projectDetails.name||'Untitled project',area:S.area,productCount:apiResult.lines.length}));
  }else if(a==='export-pdf'||a==='export-excel'){
    opts.onExport(a==='export-pdf'?'pdf':'xlsx',snapshotEstimate());
  }
});
if(opts.exitLabel)document.getElementById('to-dashboard').textContent=opts.exitLabel;
document.getElementById('brand-home').addEventListener('click',()=>opts.onExit());
document.getElementById('to-dashboard').addEventListener('click',()=>opts.onExit());
if(opts.initial) restoreEstimate(opts.initial); else { renderStage(); scheduleCalc(); }
return { destroy(){ container.innerHTML=''; }, whenReady, snapshot: snapshotEstimate };
`;

const out = `/* GENERATED by tools/build_ui.mjs from reference/calculator_v8.html — do not edit by hand. */
(function(){
var SHELL = ${JSON.stringify(SHELL)};
window.mountEstimator = function(container, opts){
container.innerHTML = SHELL;
const P = opts.products;
const STEPS = opts.steps;
/* ===================== BEGIN verbatim calculator_v8.html ===================== */
${raw}
${bridge}
};
})();
`;
fs.writeFileSync(path.join(root, 'public', 'static', 'estimator-ui.js'), out);
console.log('wrote public/static/estimator-ui.js', out.length);
