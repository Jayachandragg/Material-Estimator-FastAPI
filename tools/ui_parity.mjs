// Screen parity: original calculator_v8.html vs the FastAPI app's calculator screens
// (public/static/estimator-ui.js, every quantity calculated by the Python server), driven by
// identical random user actions. Compares the side panel after every page, the review table, the
// material lines and validation stops.
// Usage: start the server (uvicorn app.main:app --port 8765), then
//        node tools/ui_parity.mjs [runs] [firstSeed] [baseUrl]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const { JSDOM } = createRequire(path.join(here, 'package.json'))('jsdom');

const RUNS = Number(process.argv[2] || 50);
const START = Number(process.argv[3] || 1);
const BASE = process.argv[4] || 'http://127.0.0.1:8765';
const html = fs.readFileSync(path.join(root, 'reference', 'calculator_v8.html'), 'utf8');
const uiJs = fs.readFileSync(path.join(root, 'public', 'static', 'estimator-ui.js'), 'utf8');
const products = JSON.parse(fs.readFileSync(path.join(root, 'app', 'data', 'products.json'), 'utf8'));
const steps = JSON.parse(fs.readFileSync(path.join(root, 'app', 'data', 'steps.json'), 'utf8'));
// The original page formats numbers with this machine's locale; ask the server for the same one.
const LOCALE = new Intl.NumberFormat().resolvedOptions().locale === 'en-IN' ? 'en-IN' : 'en-US';

const stub = (w) => { w.scrollTo = () => {}; w.print = () => {}; w.HTMLElement.prototype.scrollIntoView = () => {}; };
let jsErrors = 0;
const watch = (dom) => dom.virtualConsole.on('jsdomError', (e) => { jsErrors++; if (jsErrors <= 3) console.error('page JS error:', e.message); });

async function apiCalc(state) {
  const r = await fetch(BASE + '/api/calc', { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: BASE },
    body: JSON.stringify({ state, locale: LOCALE }) });
  if (!r.ok) throw new Error('calc HTTP ' + r.status + ' ' + (await r.text()));
  return r.json();
}

function makeOriginal() {
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse: stub });
  watch(dom);
  const w = dom.window;
  w.document.getElementById('estimator-app').hidden = false;
  return { w, doc: w.document, settle: async () => {},
    lines: () => w.eval('compute().lines.map(l=>{const i=lineInfo(l);return {layer:l.tag,product:l.prod.name,variant:i.variant||"",coverage:i.cov||"",units:i.ask?null:i.units,unit:i.unit||"",ask:!!i.ask}})') };
}

function makeFastApi() {
  const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', { runScripts: 'outside-only', pretendToBeVisual: true });
  watch(dom);
  const w = dom.window; stub(w);
  w.eval(uiJs);
  let snapshot = null;
  const inst = w.mountEstimator(w.document.getElementById('root'), {
    products, steps, debounceMs: 0, calc: apiCalc,
    onCalcError: (e) => { jsErrors++; console.error('calc error:', e.message); },
    onSave() {}, onExit() {}, onExport: (_k, snap) => { snapshot = snap; },
  });
  const settle = async () => { for (let k = 0; k < 3; k++) { await inst.whenReady(); await new Promise((r) => setTimeout(r, 0)); } };
  return { w, doc: w.document, settle, snapshot: () => snapshot };
}

function rng(seed) { return () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 2 ** 32; }; }
const pick = (r, arr) => arr[Math.floor(r() * arr.length)];
const fire = (w, el, type) => el.dispatchEvent(new w.Event(type, { bubbles: true }));
const setVal = (w, el, v, type) => { el.value = v; fire(w, el, type); };

function act(env, r) {
  const { w, doc } = env;
  const stage = doc.getElementById('stage');
  for (const el of stage.querySelectorAll('input[data-project-field]')) setVal(w, el, el.type === 'date' ? '2026-11-16' : 'Test ' + el.dataset.projectField, 'input');
  for (const f of ['area', 'joints', 'openings', 'qty', 'thick', 'dr-len']) {
    for (const el of stage.querySelectorAll(`input[data-field="${f}"]`)) {
      if (['area', 'openings'].includes(f) || r() < 0.75) setVal(w, el, String(f === 'area' ? Math.floor(r() * 20000) + 1 : f === 'thick' ? (Math.floor(r() * 16) + 1) / 4 : Math.floor(r() * 3000)), 'input');
    }
  }
  for (const el of stage.querySelectorAll('input[type="checkbox"][data-field]')) if (r() < 0.5) { el.checked = !el.checked; fire(w, el, 'change'); }
  for (const el of [...stage.querySelectorAll('select[data-field="pid"]')]) {
    const o = [...el.querySelectorAll('option')].map((x) => x.value).filter(Boolean);
    if (o.length) setVal(w, el, pick(r, o), 'change');
  }
  for (const el of [...stage.querySelectorAll('select[data-field="ri"], select[data-field="aqW"], select[data-field="aqC"]')]) {
    const o = [...el.querySelectorAll('option')].map((x) => x.value).filter((v) => v !== '');
    if (o.length && r() < 0.8) setVal(w, el, pick(r, o), 'change');
  }
  const add = stage.querySelector('[data-act="add"]');
  if (add && r() < 0.3) add.click();
}

// Remove markup that only the production bridge adds (export buttons, required-field markers).
const norm = (s) => s.replace(/ id="[^"]*"| for="[^"]*"| aria-describedby="[^"]*"| aria-required="true"/g, '');
const pick7 = (l) => ({ layer: l.layer, product: l.product, variant: l.variant, coverage: l.coverage, units: l.units, unit: l.unit, ask: l.ask });
let failures = 0, checks = 0, totalLines = 0, reviews = 0, blocked = 0;

for (let run = START; run < START + RUNS; run++) {
  const A = makeOriginal(), B = makeFastApi();
  try { await compareRun(run, A, B); }
  catch (e) { failures++; console.log(`run ${run}: test error`, e.stack.split('\n').slice(0, 3).join(' | ')); }
  finally { await B.settle(); A.w.close(); B.w.close(); }
}

async function compareRun(run, A, B) {
  const ra = rng(run), rb = rng(run);
  const navCount = A.doc.querySelectorAll('#rail [data-nav]').length;
  for (let i = 0; i < navCount; i++) {
    for (const [env, r] of [[A, ra], [B, rb]]) {
      env.doc.querySelector(`#rail [data-nav="${i}"]`)?.click();
      await env.settle();
      act(env, r);
      await env.settle();
    }
    checks++;
    if (norm(A.doc.getElementById('side').innerHTML) !== norm(B.doc.getElementById('side').innerHTML)) {
      failures++; if (failures <= 3) console.log(`run ${run} page ${i}: side panel differs`);
    }
  }
  for (const env of [A, B]) { env.doc.querySelector(`#rail [data-nav="${navCount - 1}"]`).click(); await env.settle(); }
  const exportBtn = B.doc.querySelector('[data-act="export-pdf"]');
  if (!exportBtn) {
    blocked++; checks++;
    const ea = A.doc.querySelector('#navigation-errors')?.textContent, eb = B.doc.querySelector('#navigation-errors')?.textContent;
    const ca = A.doc.querySelector('#rail .active')?.textContent, cb = B.doc.querySelector('#rail .active')?.textContent;
    if (ea !== eb || ca !== cb) { failures++; console.log(`run ${run}: stopped differently`, ca, '|', cb); }
    return;
  }
  exportBtn.click();
  // The export sends the snapshot to the server; recalculate it there and compare with the original.
  const lb = (await apiCalc(B.snapshot().state)).lines.map(pick7);
  const la = A.lines();
  checks += 2; totalLines += la.length; reviews++;
  if (JSON.stringify(la) !== JSON.stringify(lb)) { failures++; if (failures <= 3) console.log(`run ${run}: material lines differ`, la.length, lb.length); }
  const ta = A.doc.querySelector('#stage table')?.textContent ?? '', tb = B.doc.querySelector('#stage table')?.textContent ?? '';
  if (ta !== tb) { failures++; if (failures <= 3) console.log(`run ${run}: review table differs`); }
}
console.log(`runs=${RUNS} reached review=${reviews} stopped by validation (same step+message checked)=${blocked} checks=${checks} material lines compared=${totalLines} page JS errors=${jsErrors} failures=${failures}`);
process.exit(failures || jsErrors ? 1 : 0);
