// Generates parity test cases by running the ORIGINAL calculator_v8.html (the verified source)
// in a simulated browser, and recording its exact results for many inputs.
// Usage (from the project root):  cd tools && npm install && cd .. && node tools/make_cases.mjs [syntheticCount] [uiCount]
// Writes tests/cases.jsonl.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const require = createRequire(path.join(here, 'package.json'));
const { JSDOM } = require('jsdom');

const SYN = Number(process.argv[2] || 4000);
const UI = Number(process.argv[3] || 300);
const html = fs.readFileSync(path.join(root, 'reference', 'calculator_v8.html'), 'utf8');
const STEPS = JSON.parse(fs.readFileSync(path.join(root, 'app', 'data', 'steps.json'), 'utf8'));
const PRODUCTS = JSON.parse(fs.readFileSync(path.join(root, 'app', 'data', 'products.json'), 'utf8'));
const byId = Object.fromEntries(PRODUCTS.map((p) => [p.id, p]));

function page() {
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true,
    beforeParse: (w) => { w.scrollTo = () => {}; w.print = () => {}; w.HTMLElement.prototype.scrollIntoView = () => {}; } });
  dom.virtualConsole.on('jsdomError', (e) => { jsErrors++; if (jsErrors <= 3) console.error('JS error in calculator:', e.message); });
  const w = dom.window;
  w.document.getElementById('estimator-app').hidden = false;
  // The oracle: the prototype's own compute() + lineInfo(), with the review/export row shape.
  w.eval(`window.__setLocale = (loc) => { Number.prototype.toLocaleString = function(){ return new Intl.NumberFormat(loc).format(this); }; };
    window.__oracle = (json) => {
      const st = JSON.parse(json);
      Object.keys(S).forEach(k => delete S[k]); Object.assign(S, st);
      const res = compute();
      const jv = jointsValue();
      return JSON.stringify({ noArea: res.noArea, joints: jv === undefined ? null : jv, errors: res.errors, done: res.done,
        lines: res.lines.map(l => { const i = lineInfo(l); return { layer: l.tag, product: l.prod.name, variant: i.variant || '',
          coverage: i.cov || '', units: i.ask ? null : i.units, unit: i.unit || '', ask: !!i.ask }; }) });
    };`);
  return w;
}

let jsErrors = 0;
function rng(seed) { return () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 2 ** 32; }; }
const OMIT = Symbol('omit');

function syntheticState(r) {
  const pick = (a) => a[Math.floor(r() * a.length)];
  const dec = (max, places) => Math.round(r() * max * 10 ** places) / 10 ** places;
  const numv = (validBias = 0.75) => r() < validBias
    ? pick([() => Math.floor(r() * 50000) + 1, () => dec(50000, pick([1, 2, 3, 4])), () => dec(5, 4) + 0.0001,
        () => (2 * Math.floor(r() * 5000) + 1) / 0.9, () => pick([1, 0.5, 1234567.8915, 1e15 + 0.5, 123456789.1235, 0.0004, 99999.9995])])()
    : pick([null, OMIT, 0, -1, -0.5]);
  const S = { uid: 0, rows: {}, dr: {}, on: {} };
  const set = (o, k, v) => { if (v !== OMIT) o[k] = v; };
  set(S, 'area', numv(0.85));
  set(S, 'joints', numv(0.6));
  set(S, 'jointsDirty', pick([true, false, false, OMIT, 1, 0]));
  set(S, 'openings', numv(0.7));
  for (const s of STEPS) {
    if (s.dualToggle) {
      for (const d of s.dualToggle) {
        if (r() < 0.1) continue;
        S.dr[d.pid] = r() < 0.05 ? {} : { on: pick([true, false, true, 1, 0]), len: numv(0.7) === OMIT ? null : numv(0.7) };
      }
      continue;
    }
    if (!s.req) { const v = pick([true, false, OMIT, 1, 0, 'yes']); set(S.on, s.id, v); }
    if (r() < 0.06) continue; // rows missing for this step
    const pids = s.pids || (s.groups || []).flatMap((g) => g.pids);
    const n = pick([0, 1, 1, 1, 2, 2, 3]);
    const rows = [];
    for (let i = 0; i < n; i++) {
      const pid = r() < 0.1 ? '' : pick(pids);
      const rates = pid ? byId[pid].rates.length : 1;
      const row = { uid: 'r' + (++S.uid), sid: s.id, pid };
      set(row, 'ri', pick([0, 0, 1, 2, 3, rates - 1, rates, -1, OMIT, null]));
      set(row, 'thick', pick([null, 0, 0.5, 1, 1.5, 2, 2.5, 3.75, 4, 6, dec(8, 3), -1, OMIT]));
      set(row, 'jt', pick([true, false, OMIT]));
      set(row, 'aqW', pick(['', '4', '6', '9', '5', 4, OMIT]));
      set(row, 'aqC', pick(['', 'small', 'large', 'other', OMIT]));
      set(row, 'qty', pick([null, OMIT, 0, 1, 2, 3, 7, 2.5, -3, 1000, 0.4, dec(50, 2)]));
      set(row, 'qtyDirty', pick([true, false, OMIT]));
      rows.push(row);
    }
    S.rows[s.id] = rows;
  }
  return S;
}

// UI-driven states: the same random-user driver as the app's parity test.
function uiState(w, r) {
  const doc = w.document, stage = doc.getElementById('stage');
  const pick = (a) => a[Math.floor(r() * a.length)];
  const fire = (el, t) => el.dispatchEvent(new w.Event(t, { bubbles: true }));
  const navCount = doc.querySelectorAll('#rail [data-nav]').length;
  for (let i = 0; i < navCount; i++) {
    doc.querySelector(`#rail [data-nav="${i}"]`)?.click();
    for (const el of stage.querySelectorAll('input[data-project-field]')) { el.value = el.type === 'date' ? '2026-11-16' : 'x'; fire(el, 'input'); }
    for (const f of ['area', 'joints', 'openings', 'qty', 'thick', 'dr-len']) {
      for (const el of stage.querySelectorAll(`input[data-field="${f}"]`)) {
        if (['area', 'openings'].includes(f) || r() < 0.75) { el.value = String(f === 'area' ? Math.floor(r() * 20000) + 1 : f === 'thick' ? (Math.floor(r() * 16) + 1) / 4 : Math.floor(r() * 3000)); fire(el, 'input'); }
      }
    }
    for (const el of stage.querySelectorAll('input[type="checkbox"][data-field]')) if (r() < 0.5) { el.checked = !el.checked; fire(el, 'change'); }
    for (const el of [...stage.querySelectorAll('select[data-field="pid"]')]) { const o = [...el.options].map((x) => x.value).filter(Boolean); if (o.length) { el.value = pick(o); fire(el, 'change'); } }
    for (const el of [...stage.querySelectorAll('select[data-field="ri"], select[data-field="aqW"], select[data-field="aqC"]')]) { const o = [...el.options].map((x) => x.value).filter((v) => v !== ''); if (o.length && r() < 0.8) { el.value = pick(o); fire(el, 'change'); } }
    if (r() < 0.3) stage.querySelector('[data-act="add"]')?.click();
  }
  return w.eval('JSON.stringify(S)');
}

const out = fs.createWriteStream(process.argv[4] || path.join(root, 'tests', 'cases.jsonl'));
const w = page();
const LOCALES = ['en-IN', 'en-US'];
let count = 0;
function record(id, source, stateJson) {
  for (const loc of LOCALES) {
    w.__setLocale(loc);
    const expected = JSON.parse(w.__oracle(stateJson));
    out.write(JSON.stringify({ id, source, locale: loc, state: JSON.parse(stateJson), expected }) + '\n');
    count++;
  }
}
const r = rng(20261116);
for (let i = 0; i < SYN; i++) record(`syn-${i}`, 'synthetic', JSON.stringify(syntheticState(r)));
for (let i = 0; i < UI; i++) {
  const u = page();
  const st = uiState(u, rng(1000 + i));
  u.close();
  record(`ui-${i}`, 'ui', st);
}
out.end(() => {
  console.log(`wrote ${count} cases (${SYN} synthetic + ${UI} UI-driven states x ${LOCALES.length} locales); calculator JS errors: ${jsErrors}`);
  if (jsErrors) process.exitCode = 1;
});
