/* Runs the real page logic/render and asynchronous browser adapter in Node.
 * DOM layout, timers and HTTP responses are explicit models; no C build, camera,
 * network, server or shared test libraries. Run: node --test preview/test_client.js
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const html = fs.readFileSync(path.join(__dirname, 'dcres.html'), 'utf8');
const pageScript = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).find(source => source.includes('const S ='));
const dataScript = fs.readFileSync(path.join(__dirname, 'fps_data.js'), 'utf8');
const clientScript = fs.readFileSync(path.join(__dirname, 'simulator.js'), 'utf8');
const siteScript = fs.readFileSync(path.join(__dirname, 'site_page.js'), 'utf8');
const FPS = JSON.parse(dataScript.slice(dataScript.indexOf('const FPSDATA = ') + 16).replace(/;\s*$/, ''));

function browser({client = true, site = false, hash = '', saved = null} = {}) {
  const elements = new Map(), timers = new Map(), requests = [], translated = [], history = [];
  let timerId = 0;
  class Element {
    constructor(id) {
      this.id = id; this.style = {}; this.dataset = {}; this.attributes = {};
      this.textContent = ''; this.html = ''; this.clientWidth = 1024; this.scrollWidth = 1024; this.hidden = false;
      const classes = new Set();
      this.classList = {
        toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
        contains(name) { return classes.has(name); },
      };
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    addEventListener(type, fn) { (this.listeners ||= {})[type] = fn; }
    get innerHTML() { return this.html; }
    set innerHTML(value) {
      this.html = value;
      // The render replaces each complete tile row, destroying that row's old QR node.
      if (this.id !== 'r0' && this.id !== 'r1') return;
      if (elements.get('qr-matrix')?.owner === this.id) elements.delete('qr-matrix');
      const match = value.match(/id="qr-matrix" data-code="([^"]+)"/);
      if (match) {
        const qr = new Element('qr-matrix');
        qr.owner = this.id; qr.dataset.code = match[1]; elements.set(qr.id, qr);
      }
    }
  }
  for (const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1]);
    for (const attribute of match[0].matchAll(/([\w-]+)="([^"]*)"/g))
      element.setAttribute(attribute[1], attribute[2]);
    elements.set(element.id, element);
  }
  for (const match of html.matchAll(/<[^>]+\bdata-(t|th)="([^"]+)"[^>]*>/g)) {   // translated nodes, with or without an id
    const element = new Element(match[0].match(/\bid="([^"]+)"/)?.[1] || null);
    element.dataset[match[1]] = match[2]; translated.push(element);
  }
  const location = {protocol: 'http:', hash: hash ? '#' + hash : '', reloads: 0, reload() { this.reloads++; }};
  const context = vm.createContext({
    document: {getElementById: id => elements.get(id) || null, documentElement: {},
      querySelectorAll: s => s === '[data-t]' ? translated.filter(e => e.dataset.t) : s === '[data-th]' ? translated.filter(e => e.dataset.th) : []},
    location, addEventListener() {}, URLSearchParams,
    localStorage: {getItem: () => saved, setItem() {}},
    history: {replaceState(_s, _t, url) { history.push(url); location.hash = url; }, pushState() { throw new Error('pushState'); }},
    AbortSignal: {timeout: () => ({})},
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
    fetch(url) {
      return new Promise((resolve, reject) => requests.push({url, resolve, reject, settled: false}));
    },
  });
  const run = source => vm.runInContext(source, context);
  vm.runInContext(dataScript, context, {filename: 'fps_data.js'});
  if (site) vm.runInContext(siteScript, context, {filename: 'site_page.js'});
  vm.runInContext(pageScript, context, {filename: 'dcres.html'});
  run('globalThis.renderCalls = 0; const realRender = render; render = function () { renderCalls++; return realRender(); };');
  if (client) vm.runInContext(clientScript, context, {filename: 'simulator.js'});
  return {
    run, elements, requests, translated, history, location,
    // A click / wheel as the browser would deliver it: target.closest(selector) answers from `hits`.
    click(id, hits = {}) {
      const target = {closest: sel => hits[sel] || null};
      return elements.get(id).listeners.click({target, preventDefault() {}});
    },
    wheel(deltaY, shiftKey = false) { elements.get('cam').listeners.wheel({deltaY, deltaX: 0, shiftKey, preventDefault() {}}); },
    value(source) { return JSON.parse(run(`JSON.stringify(${source})`)); },
    flushTimers() {
      const pending = [...timers.values()]; timers.clear(); pending.forEach(fn => fn());
    },
    request(prefix) {
      const found = requests.find(request => !request.settled && request.url.startsWith(prefix));
      assert.ok(found, `missing pending request ${prefix}`); return found;
    },
    async respond(request, data) {
      assert.equal(request.settled, false); request.settled = true;
      request.resolve({ok: true, status: 200, json: async () => data});
      // Drain JSON, then/catch/finally and render-created promises without real timers.
      for (let i = 0; i < 12; i++) await Promise.resolve();
    },
  };
}

async function connected() {
  const b = browser();
  await b.respond(b.request('/api/info'), {version: 'test', core_fingerprint: 'test-source'});
  assert.equal(b.run('simulator.state'), 'ready');
  assert.equal(b.run('Object.keys(FPSDATA.cases).length'), 0, 'server connection discards the saved fallback cells');
  return b;
}

function cell(key, dcw, dch, rw, rh, maxFps = 60, rec = [rw, rh]) {
  // Deliberately controlled recipe data: these tests exercise browser ordering and rendering,
  // while test_server.py verifies the real C calculation and QR encoding independently.
  return {key, clk: 72_000_000, vmax_max: 32767, nominal: [rw - 16, rh - 10],
    case: [[1000, 72_000_000 / (1000 * maxFps), '12b 1x1', {
      key: '12', ad: 12, mh: 1, mv: 1, hbin: 1, vbin: 1, scw: dcw, sch: dch,
      sw: dcw, sh: dch, win: [dcw, dch], zoom: [3072, 3072], path: 'C', rs_ms: 10,
      rec, vis: [rec[0] - 16, rec[1] - 10],
    }]]};
}

function matrix(x, y) {
  const modules = Array.from({length: 37}, () => Array(37).fill(0));
  modules[y][x] = 1; return {size: 37, modules};
}

test('rapid custom crops keep separate cells; a delayed old response only populates its cache', async () => {
  const b = await connected();
  b.run('S.dcLock = false; setDC(6032, 3402); S.fps = 120; render();'); b.flushTimers();
  const a = b.request('/api/qualities');
  assert.equal(new URL(a.url, 'http://local').searchParams.get('dcw'), '6032');
  b.run('setDC(6016, 3402); render();'); b.flushTimers();
  const pending = b.requests.filter(request => request.url.startsWith('/api/qualities'));
  assert.equal(pending.length, 2);
  const current = pending[1];
  assert.equal(new URL(current.url, 'http://local').searchParams.get('dcw'), '6016');
  assert.equal(new URL(current.url, 'http://local').searchParams.get('rw'), '2000');
  await b.respond(current, cell('C6016x3402:2000x1134', 6016, 3402, 2000, 1134, 60));
  assert.equal(b.run('S.fps'), 60, 'the current response clamps to the highest usable standard FPS');
  const payload = b.run('qrCode()'), renders = b.run('renderCalls');
  const picture = b.elements.get('liveview').getAttribute('viewBox');
  await b.respond(a, cell('C6032x3402:2000x1134', 6032, 3402, 2000, 1134, 30));
  assert.equal(b.run('S.fps'), 60, 'the old crop cannot lower current FPS to 30');
  assert.equal(b.run('qrCode()'), payload);
  assert.equal(b.run('renderCalls'), renders, 'a stale response must not repaint the current selection');
  assert.equal(b.elements.get('liveview').getAttribute('viewBox'), picture);
  assert.equal(b.run('simulator.cells.size'), 2);
  assert.equal(b.run('FPSDATA.cases["C6032x3402:2000x1134"][0][1]'), 2400);
  assert.equal(b.run('FPSDATA.cases["C6016x3402:2000x1134"][0][1]'), 1200);
  assert.equal(b.run('simulator.requests.size'), 0);
});

test('an older QR response cannot overwrite the current payload or SVG', async () => {
  const b = await connected(); b.flushTimers();
  await b.respond(b.request('/api/qualities'), cell('HD:2016x1134', 6048, 3402, 2016, 1134, 120));
  const oldCode = b.run('qrCode()'), oldRequest = b.request('/api/qr');
  b.run('FPS.pick(fpsList().findIndex(o => o.f === 30)); render();');
  const code = b.run('qrCode()'); assert.notEqual(code, oldCode);
  const request = b.request(`/api/qr?code=${encodeURIComponent(code)}`);
  b.run('render();');
  assert.equal(b.requests.filter(r => r.url === request.url).length, 1, 'same-payload request is deduplicated');
  await b.respond(request, matrix(4, 3));
  const svg = b.elements.get('qr-matrix').innerHTML;
  assert.match(svg, /viewBox="0 0 41 41"/);
  assert.match(svg, /M6 5h1v1h-1z/);
  await b.respond(oldRequest, matrix(0, 0));
  assert.equal(b.elements.get('qr-matrix').dataset.code, code);
  assert.equal(b.elements.get('qr-matrix').innerHTML, svg);
  assert.equal(b.run('simulator.qr.size'), 2, 'the old matrix may remain cached for a later return');
});

test('liveview uses actual recording raster shape and keeps the DC crop during RES squash', () => {
  const b = browser({client: false});
  b.run('setDC0(5040, 3000); setRes0(2016, 1134); S.fps = 30;');
  const key = b.run('qualityKey()');
  b.run(`FPSDATA.cases[${JSON.stringify(key)}] = ${JSON.stringify(cell(key, 5040, 3000, 2016, 1134, 60, [2016, 1124]).case)}; render();`);
  const g = b.value('previewGeometry()'), lv = b.elements.get('liveview');
  assert.deepEqual([g.x, g.y, g.cw, g.ch], [504, 520, 5040, 3000]);
  assert.deepEqual([g.rw, g.rh], [2016, 1124]);
  assert.equal(g.w, 1024);
  assert.ok(Math.abs(g.h - 1024 * 1124 / 2016) < 1e-9);
  assert.notEqual(g.rh, b.run('res().h'), 'recipe raster can be shorter than the nominal RES');
  assert.notEqual(g.rh, b.run('visible().h'), 'DefaultCrop is not the display-ratio input');
  assert.equal(lv.getAttribute('viewBox'), '504 520 5040 3000');
  assert.equal(lv.getAttribute('preserveAspectRatio'), 'none');
  assert.equal(lv.style.width, '100%');
  assert.ok(Math.abs(parseFloat(lv.style.height) - 100 * g.h / 682) < 1e-9);
  b.run('setRes0(2016, 600); render();');
  const squashed = b.value('previewGeometry()');
  assert.deepEqual([squashed.rw, squashed.rh], [2016, 600]);
  assert.ok(squashed.h < g.h);
  assert.equal(squashed.w, g.w);
  assert.equal(lv.getAttribute('viewBox'), '504 520 5040 3000', 'RES squash retains the sensor crop');
});

test('the real render shows QR on main QS, retains it across focus/AEL, and removes it on sub/close/no recipe', () => {
  const b = browser({client: false});
  const code = b.run('qrCode()'); assert.ok(code);
  assert.equal(b.elements.get('qr-matrix').dataset.code, code);
  b.run("S.focus = 5; act('ael'); act('left');");
  assert.equal(b.elements.get('qr-matrix').dataset.code, code);
  b.run("S.focus = 1; act('ael');");
  assert.equal(b.run('S.sub'), 'dc'); assert.equal(b.elements.has('qr-matrix'), false);
  b.run("act('menu');"); assert.equal(b.elements.get('qr-matrix').dataset.code, code);
  b.run("act('qs');");
  assert.equal(b.elements.has('qr-matrix'), false);
  assert.equal(b.elements.get('cam').classList.contains('closed'), true);
  b.run("act('qs');");
  assert.equal(b.elements.get('cam').classList.contains('closed'), false);
  assert.equal(b.elements.get('qr-matrix').dataset.code, code);
  b.run('FPSDATA.cases = {}; render();');
  assert.equal(b.run('qrVisible()'), false); assert.equal(b.elements.has('qr-matrix'), false);
});

// ---- the merged page (site_page.js): camera QR landing, address sync, languages, frame diagram ----------------------
const DCMAP = {OG: [6048, 4040], HD: [6048, 3402], S35: [4192, 2358], 'APS-C': [3952, 2624], S16: [2096, 1240], SQ: [4032, 4032]};
const site = (hash = '', saved = null) => browser({client: false, site: true, hash, saved});

function presetCells() {
  return Object.entries(FPS.cases).filter(([, c]) => Array.isArray(c)).map(([key, recipes]) => {
    const [dc, wh] = key.split(':'), [rw, rh] = wh.split('x').map(Number);
    return {key, dcw: DCMAP[dc][0], dch: DCMAP[dc][1], rw, rh, recipes};
  });
}

function rng(seed) { return () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; }; }

test('every preset recipe: state -> code -> page loaded from #code is the identical selection', () => {
  const random = rng(410);
  let checked = 0;
  for (const cell of presetCells()) {
    const a = site();
    cell.recipes.forEach(([, , name], i) => {
      const kernels = [Math.floor(random() * 6), Math.floor(random() * 6), Math.floor(random() * 2)];
      a.run(`S.dcW = ${cell.dcw}; S.dcH = ${cell.dch}; S.memory = {}; setRes0(${cell.rw}, ${cell.rh});
        S.recipe = ${JSON.stringify(name)}; S.recipeD = FPSDATA.cases[${JSON.stringify(cell.key)}].find(r => r[2] === ${JSON.stringify(name)})[3];
        S.kh = ${kernels[0]}; S.kv = ${kernels[1]}; S.km = ${kernels[2]}; S.fine = false; S.fpsCustom = null;
        { const q = allQuals().find(q => q.q === ${JSON.stringify(name)}), top = Math.min(q.max, 1000);
          const mode = ${i % 3};
          if (mode === 0) S.fps = top;                                                     // a recipe maximum (or 1000)
          else if (mode === 1) S.fps = STD.filter(f => f <= top + 5e-4).pop() || top;       // a common rate
          else { S.fps = top; S.fine = true; S.fps = fineStep(S.fps, -1, true); fineExit(); }   // a tuned rate
        }
        render();`);
      const code = a.run('qrCode()');
      if (!code || a.run('(curRecipe() || {}).q') !== name) return;     // this recipe cannot be held at that rate
      const b = site(code);
      assert.equal(b.run('qrCode()'), code, `${cell.key} ${name}`);
      assert.deepEqual(b.value('SiteRecipe.PAGE.inexact'), [], `${cell.key} ${name}`);
      assert.equal(b.history.length, 0, 'loading a code must not rewrite the address');
      assert.equal(b.elements.get('notice').style.visibility, 'hidden');
      assert.equal(b.value('SiteRecipe.decodeRecipe(qrCode()).fields.rh'), cell.rh);
      checked++;
    });
  }
  assert.ok(checked >= 740, `only ${checked} preset recipes round-tripped`);   // 823 since 0.0.5test
});

test('random payloads: decode(pack(f)) is the identity, and loading never rewrites the address', () => {
  const random = rng(7), b = site(), widths = b.value('QR_FIELDS');
  for (let n = 0; n < 300; n++) {
    const f = Object.fromEntries(widths.map(([k, w]) => [k, 1 + Math.floor(random() * (2 ** w - 1))]));
    Object.assign(f, {ver: 1, ad: Math.floor(random() * 3), fps: Math.floor(random() * 31), kh: Math.floor(random() * 6), kv: Math.floor(random() * 6)});
    const code = b.run(`qrPack(${JSON.stringify(f)})`);
    assert.deepEqual(b.value(`SiteRecipe.decodeRecipe(${JSON.stringify(code)})`), {fields: f});
  }
  // Camera-like payloads: a preset recipe's code with one field changed. Either the simulator reproduces it exactly,
  // or the page lists exactly the fields it cannot show, keeps the camera's values in the details and the address.
  const cells = presetCells();
  for (let n = 0; n < 120; n++) {
    const cell = cells[Math.floor(random() * cells.length)], [, , name] = cell.recipes[Math.floor(random() * cell.recipes.length)];
    const a = site();
    a.run(`S.dcW = ${cell.dcw}; S.dcH = ${cell.dch}; setRes0(${cell.rw}, ${cell.rh}); S.recipe = ${JSON.stringify(name)};
      S.fps = Math.min(1000, allQuals().find(q => q.q === ${JSON.stringify(name)}).max); render();`);
    const f = a.value('SiteRecipe.decodeRecipe(qrCode()).fields');
    const [k, w] = widths[1 + Math.floor(random() * (widths.length - 1))];
    f[k] = Math.max(1, Math.min(2 ** w - 1, f[k] + (random() < .5 ? -1 : 1) * (1 + Math.floor(random() * 3))));
    if (b.value(`SiteRecipe.decodeRecipe(qrPack(${JSON.stringify(f)})).error || ''`)) continue;
    const code = a.run(`qrPack(${JSON.stringify(f)})`), c = site(code);
    assert.equal(c.history.length, 0);
    assert.equal(c.location.hash, '#' + code);
    const inexact = c.value('SiteRecipe.PAGE.inexact'), pending = c.value('SiteRecipe.PAGE.pending');
    if (pending) { assert.match(c.elements.get('lede').textContent, /Loading/); continue; }   // a custom cell needs the engine
    if (!inexact.length) {                       // 0.0.5test: its inputs come back; derived fields are the core's own
      const g = c.value('SiteRecipe.decodeRecipe(qrCode()).fields');
      for (const k of ['ver', 'dcw', 'dch', 'rw', 'rh', 'ad', 'mh', 'mv', 'hbin', 'vbin', 'kh', 'kv', 'km', 'fmt', 'scw', 'sch'])
        assert.equal(g[k], f[k], k);
      continue;
    }
    for (const [key, camera] of inexact) assert.equal(camera, f[key]);
    assert.equal(c.elements.get('notice').hidden, false);
    assert.match(c.elements.get('title').textContent, new RegExp(`${f.rw}×${f.rh}`), 'details show the camera values');
  }
});

test('changes rewrite the address with replaceState only; no hash means the plain default view', () => {
  const b = site();
  assert.equal(b.history.length, 0, 'the default view leaves the address alone');
  assert.match(b.elements.get('lede').textContent, /Quick Set simulator/);
  const before = b.run('qrCode()');
  b.run("S.focus = 3; act('f-');");
  const code = b.run('qrCode()');
  assert.notEqual(code, before);
  assert.deepEqual(b.history, ['#' + code]);
  b.run("act('f-');");
  assert.equal(b.history.length, 2); assert.equal(b.location.hash, '#' + b.run('qrCode()'));
  assert.match(b.elements.get('lede').textContent, /changes are in the address/);
  const again = site(b.location.hash.slice(1));
  assert.equal(again.run('qrCode()'), b.location.hash.slice(1));
  assert.equal(again.elements.get('qr-matrix').dataset.code, again.run('qrCode()'), 'the QS QR shows the address code');
});

test('invalid codes: a clear error, the default simulator, and the address kept until a change', () => {
  const a = site(), good = a.run('qrCode()'), f = a.value('SiteRecipe.decodeRecipe(qrCode()).fields');
  const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  const xor = (s, i, m) => s.slice(0, i) + B64[B64.indexOf(s[i]) ^ m] + s.slice(i + 1);
  const cases = {length: good.slice(0, -1), chars: good.slice(0, -1) + '+', crc: xor(good, 3, 1), pad: xor(good, 36, 1),
    version: a.run(`qrPack(${JSON.stringify({...f, ver: 2})})`), field: a.run(`qrPack(${JSON.stringify({...f, ad: 3})})`)};
  for (const [reason, code] of Object.entries(cases)) {
    for (const [lang, word] of [[null, 'could not be read'], ['hans', '读不出来'], ['hant', '讀不出來']]) {
      const b = site(code, lang);
      assert.equal(b.value('SiteRecipe.PAGE.error'), reason, reason);
      assert.equal(b.elements.get('notice').hidden, false);
      assert.ok(b.elements.get('notice').innerHTML.includes(word), `${reason} ${lang}`);
      assert.equal(b.run('qrCode()'), good, 'the simulator shows its default');
      assert.equal(b.history.length, 0);
      b.run("S.focus = 3; act('f-');");
      assert.equal(b.elements.get('notice').style.visibility, 'hidden', 'a change clears the error (keeping its space)');
      assert.deepEqual(b.history, ['#' + b.run('qrCode()')]);
    }
  }
});

test('languages: English by default; saved 简 / 繁 translate the page, side panel, hint and engine status', async () => {
  const pick = (b, key) => b.translated.find(e => e.dataset.t === key || e.dataset.th === key);
  for (const saved of [null, '', 'xx', 'en']) {
    const b = site('', saved);
    assert.equal(b.run('document.documentElement.lang'), 'en');
    assert.match(pick(b, 'howTo').textContent, /^Click or tap a tile/);
    assert.match(b.elements.get('ael').innerHTML, /More options/);
  }
  for (const [saved, lang, front, more, lede, engine] of [
    ['hans', 'zh-Hans', '点或轻触格子', '更多选项', '快速设置模拟器', '本机模拟'], ['hant', 'zh-Hant', '點或輕觸格子', '更多選項', '快速設定模擬器', '本機模擬']]) {
    const b = site('', saved);
    assert.equal(b.run('document.documentElement.lang'), lang);
    assert.ok(pick(b, 'howTo').textContent.startsWith(front));
    assert.match(b.elements.get('ael').innerHTML, new RegExp(more));
    assert.ok(b.elements.get('lede').textContent.startsWith(lede));
    assert.ok(!/undefined|NaN/.test(b.elements.get('stats').innerHTML + b.elements.get('legend').innerHTML));
    const c = browser({client: true, site: true, saved});
    await c.respond(c.request('/api/info'), {version: 'test', core_fingerprint: 'x'});
    assert.match(c.elements.get('connection').textContent, new RegExp(engine));
  }
  const b = site('', 'hant');                      // switching back at runtime
  b.run("SiteRecipe.setLang('en'); render();");
  assert.match(pick(b, 'howTo').textContent, /^Click or tap/);
  assert.equal(b.run('document.documentElement.lang'), 'en');
});

// The frame diagram: one shared scale, each stage centred in the one before (the camera's real geometry), never bigger;
// equal stages inset so no two outlines coincide; dashed corner connectors exactly for the deforming steps (binning,
// ISP scale), each joining matching corners, never along a box edge; the colour key below every line, no two key rows
// touching, nothing outside the viewBox; drawn back to front.
function layoutProblems(L, svg, stages, M) {
  const out = [], hit = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  const same = (a, b) => ['x', 'y', 'w', 'h'].every(k => Math.abs(a[k] - b[k]) < .5);
  const tiny = r => r.w <= 2 * 3 + 2 || r.h <= 2 * 3 + 2;
  L.rects.forEach((r, k) => {
    const p = L.rects[k - 1], want = [stages[k].size[0] * L.scale, stages[k].size[1] * L.scale];
    if (!p) return;
    if (r.w > p.w + 1e-9 || r.h > p.h + 1e-9) out.push(['grows', k]);
    const off = stages[k].offset && stages[k].offset[1] !== null;   // a windowed readout sits at its real start row
    const wantY = off ? Math.max(p.y, Math.min(p.y + p.h - r.h, p.y + stages[k].offset[1] * L.scale)) : p.y + (p.h - r.h) / 2;
    if (Math.abs(r.x + r.w / 2 - (p.x + p.w / 2)) > 1 || Math.abs(r.y - wantY) > 1) out.push(['position', k]);
    for (const [i, v] of [[0, r.w], [1, r.h]])                       // true size, unless inset / at the minimum
      if (Math.abs(v - want[i]) > 1 && !(v <= (i ? p.h : p.w) - 6 + 1e-9 && want[i] > (i ? p.h : p.w) - 6) && v > 2 + 1e-9) out.push(['scale', k, i]);
    const equal = !stages[k].pending && stages[k].size[0] >= stages[k - 1].size[0] && stages[k].size[1] >= stages[k - 1].size[1];
    if (equal !== L.labels[k].text.includes(SAME)) out.push(['same-size key', k]);
  });
  L.rects.forEach((a, i) => L.rects.slice(i + 1).forEach(b => same(a, b) && !(tiny(a) && tiny(b)) && out.push(['identical boxes', a.k, b.k])));
  // Exactly 0 / 2 side-middle / 4 corner connectors per step, by which axes change (data ratio and visible size).
  const ratios = {2: [M.mh, M.mv], 4: [M.winW / M.recW, M.winH / M.recH]};
  for (const [from, to] of [[2, 3], [4, 5]]) {
    const A = L.rects[from], B = L.rects[to], [rx, ry] = ratios[from];
    const chX = Math.abs(rx - 1) > 0.02 && A.w - B.w > 6.5, chY = Math.abs(ry - 1) > 0.02 && A.h - B.h > 6.5;
    const pt = {c00: [[0, 0], [0, 0]], c10: [[1, 0], [1, 0]], c01: [[0, 1], [0, 1]], c11: [[1, 1], [1, 1]],
      left: [[0, .5]], right: [[1, .5]], top: [[.5, 0]], bottom: [[.5, 1]]};
    const want = chX && chY ? ['c00', 'c10', 'c01', 'c11'] : chX ? ['left', 'right'] : chY ? ['top', 'bottom'] : [];
    const mine = L.dashed.filter(d => d.from === from);
    if (mine.map(d => d.at).sort().join() !== want.slice().sort().join()) out.push(['connector rule', from, mine.map(d => d.at).join()]);
    for (const d of mine) {
      const [fx, fy] = pt[d.at][0], ok = (v, w) => Math.abs(v - w) < 1e-6;
      if (d.to !== to || !ok(d.x1, A.x + fx * A.w) || !ok(d.y1, A.y + fy * A.h) || !ok(d.tx, B.x + fx * B.w) || !ok(d.ty, B.y + fy * B.h))
        out.push(['connector ends', from, d.at]);
      // The arrowhead end: on the line, just short of the result point (pointing source -> result).
      const len = Math.hypot(d.tx - d.x1, d.ty - d.y1), gap = Math.hypot(d.tx - d.x2, d.ty - d.y2);
      const cross = (d.x2 - d.x1) * (d.ty - d.y1) - (d.y2 - d.y1) * (d.tx - d.x1);
      if (Math.abs(cross) > 1e-6 * len * len || gap <= 0 || gap > 2.5 + 1e-9 || Math.hypot(d.x2 - d.x1, d.y2 - d.y1) >= len) out.push(['arrowhead', from, d.at]);
    }
  }
  for (const d of L.dashed) for (const r of L.rects) {          // never running along a box edge
    const overlap = (p1, p2, q1, q2) => Math.min(Math.max(p1, p2), q2) - Math.max(Math.min(p1, p2), q1) > 0.5;
    if (Math.abs(d.x1 - d.x2) < 1e-6) for (const ex of [r.x, r.x + r.w])
      if (Math.abs(d.x1 - ex) < 1 && overlap(d.y1, d.y2, r.y, r.y + r.h)) out.push(['connector on edge', d.from, r.k]);
    if (Math.abs(d.y1 - d.y2) < 1e-6) for (const ey of [r.y, r.y + r.h])
      if (Math.abs(d.y1 - ey) < 1 && overlap(d.x1, d.x2, r.x, r.x + r.w)) out.push(['connector on edge', d.from, r.k]);
  }
  const bottom = Math.max(...L.rects.map(r => r.y + r.h), ...L.dashed.map(d => Math.max(d.y1, d.y2)));
  L.labels.forEach((a, i) => {
    if (a.y < bottom) out.push(['key crosses a line', a.text]);
    L.labels.slice(i + 1).forEach(b => hit(a, b) && out.push(['label/label', a.text, b.text]));
  });
  for (const b of [...L.labels, ...L.rects, ...L.dashed.map(d => ({x: Math.min(d.x1, d.x2), y: Math.min(d.y1, d.y2), w: Math.abs(d.x2 - d.x1), h: Math.abs(d.y2 - d.y1), k: d.from}))]) if (b.x < 0 || b.y < 0 || b.x + b.w > L.W + 1e-9 || b.y + b.h > L.H + 1e-9) out.push(['outside', b.text || b.k]);
  // Exactly one arrowhead per connector (its own colour's marker at the end), each marker pointing along its line.
  const lines = svg.split('<line class="deform"').slice(1).map(l => l.split('/>')[0]);
  if (lines.length !== L.dashed.length || lines.some((l, i) => l.split('marker-end=').length !== 2 ||
      l.indexOf('marker-end="url(#ah' + L.dashed[i].stroke + ')"') < 0)) out.push(['arrowhead', 'markers']);
  for (const c of new Set(L.dashed.map(d => d.stroke))) {
    const def = (svg.split('<marker id="ah' + c + '"')[1] || '').split('</marker>')[0];
    if (!def || def.indexOf('orient="auto"') < 0 || def.indexOf('fill="var(' + c + ')"') < 0) out.push(['arrowhead', 'marker def', c]);
  }
  const order = [...svg.matchAll(/class="(stage|deform|key)"/g)].map(m => m[1]);
  if (order.join() !== [...L.rects.map(() => 'stage'), ...L.dashed.map(() => 'deform'), ...L.labels.map(() => 'key')].join()) out.push(['draw order']);
  return out;
}
let SAME = 'same size';

test('frame diagram: shared scale, real positions, distinct outlines, key never crossed (all presets + extremes, 3 languages)', () => {
  const b = site(), cases = [];
  for (const cell of presetCells()) for (const [hm, lo, , r] of cell.recipes)
    cases.push({ver: 1, dcw: cell.dcw, dch: cell.dch, rw: cell.rw, rh: cell.rh, fps: 30, vmax: lo, hmax: hm, ad: {11: 0, 12: 1, 14: 2}[r.ad],
      mh: r.mh, mv: r.mv, hbin: r.hbin, vbin: r.vbin, key: 1, kh: 1, kv: 1, km: 0, rcustom: 0, visw: r.vis[0], vish: r.vis[1],
      rs: Math.round(r.rs_ms * 1000), fmt: 0, rescustom: 0, scw: r.scw, sch: r.sch, ww: r.win[0], wh: r.win[1]});
  const extremes = [[6048, 144, 256, 144], [256, 4040, 256, 144], [6048, 4040, 256, 144], [6048, 4040, 6048, 4040], [256, 144, 256, 144],
    [6048, 144, 6048, 144], [256, 4040, 256, 4040], [4032, 4032, 256, 144], [6048, 4040, 6048, 144], [6048, 4040, 256, 4040], [8176, 8190, 8176, 8190]];
  for (const [dcw, dch, rw, rh] of extremes) for (const [mh, mv] of [[1, 1], [3, 3], [1, 3], [3, 1], [3, 6]])
    cases.push({ver: 1, dcw, dch, rw, rh, fps: 30, vmax: 2000, hmax: 900, ad: 2, mh, mv, hbin: 3, vbin: 1, key: 1, kh: 5, kv: 0, km: 1,
      rcustom: 1, visw: Math.max(1, rw - 16), vish: Math.max(1, rh - 10), rs: 131071, fmt: 0, rescustom: 1, scw: dcw, sch: dch,
      ww: Math.floor(dcw / mh), wh: Math.floor(dch / mv)});
  const check = `(${layoutProblems.toString()})`;
  const problems = b.value(`(() => { const out = [];
    for (const lang of ['en', 'hans', 'hant']) { SiteRecipe.setLang(lang); SAME = SiteRecipe.I18N[lang].sameSize;
      for (const f of ${JSON.stringify(cases)}) for (const narrow of [true, false]) {
        const M = SiteRecipe.describe(f), L = SiteRecipe.frameLayout(M, narrow);
        const p = ${check}(L, SiteRecipe.frameSVG(L), SiteRecipe.frameStages(M), M);
        if (L.W !== (narrow ? 340 : 560)) p.push(['drawing box not fixed', L.W, L.H]);
        (globalThis.HEIGHTS ||= {})[narrow] = (HEIGHTS[narrow] || new Set()).add(L.H.toFixed(3));
        if (p.length) out.push({lang, narrow, f: [f.dcw, f.dch, f.rw, f.rh, f.mh, f.mv], p: p.slice(0, 3)});
      } }
    return out; })()`);
  assert.ok(cases.length > 820, `${cases.length}`);   // 0.0.5test: 14 recipes not offered
  assert.deepEqual(b.value('[HEIGHTS.true.size, HEIGHTS.false.size]'), [1, 1], 'one drawing height per breakpoint');
  assert.deepEqual(problems.slice(0, 5), []);
  // The OG 1x2 code: DC = sensor (inset, "same size"), the binned frame half height with 4 binning connectors (the
  // shared left/right edges run inside), and the 2:1 horizontal ISP scale to the recording with its own connectors.
  const og = b.value(`(() => { SiteRecipe.setLang('en'); const M = SiteRecipe.describe(SiteRecipe.decodeRecipe('G9B-QvQfkGKTgOPlCKxIvAfUMpAXoPyL0D7zI').fields);
    const L = SiteRecipe.frameLayout(M, false); return {keys: L.labels.map(l => l.text), dashed: L.dashed.map(d => [d.from, d.at]), r: L.rects.map(r => [r.w, r.h])}; })()`);
  assert.ok(og.r[3][1] < og.r[2][1] * 0.6, 'the 1x2 binned frame is about half the DC height');
  assert.deepEqual(og.dashed.filter(d => d[0] === 2).map(d => d[1]), ['top', 'bottom'], 'binning 1x2: height only -> top/bottom middles');
  assert.deepEqual(og.dashed.filter(d => d[0] === 4).map(d => d[1]), ['left', 'right'], 'ISP 2:1 horizontal -> left/right middles');
  assert.match(og.keys[1], /Readout \(engine/, 'without the engine the readout is marked pending, never guessed');
  // The checker must fail on broken diagrams (mutation check).
  const bad = b.value(`(() => { SAME = 'same size'; SiteRecipe.setLang('en');
    const M = SiteRecipe.describe(SiteRecipe.decodeRecipe('G9B-QvQfkGKTgOPlCKxIvAfUMpAXoPyL0D7zI').fields), S_ = SiteRecipe.frameStages(M);
    const go = edit => { const L = SiteRecipe.frameLayout(M, false); edit(L); return ${check}(L, SiteRecipe.frameSVG(L), S_, M).map(p => p[0]); };
    return [go(L => { L.rects[2].w = L.rects[1].w + 10; }), go(L => { L.labels[1].y = L.labels[0].y; }),
      go(L => { L.rects[3].x += 9; }), go(L => { L.rects[2] = {...L.rects[1], k: 2}; }), go(L => { L.labels[0].y = 0; }),
      go(L => { const d = L.dashed[0]; d.x1 = d.x2 = L.rects[2].x; d.y1 = L.rects[2].y; d.y2 = L.rects[2].y + 40; }),
      go(L => { L.dashed = L.dashed.filter(d => d.from !== 2); }),
      go(L => { L.dashed.push({...L.dashed[0], at: 'c00'}); }), go(L => { L.dashed[0].tx += 4; L.dashed[0].x2 += 4; }),
      go(L => { L.dashed = L.dashed.filter(d => d.at !== 'right'); }),
      go(L => { L.dashed[0].x2 = L.dashed[0].tx; L.dashed[0].y2 = L.dashed[0].ty; }),
      (() => { const L = SiteRecipe.frameLayout(M, false); return ${check}(L, SiteRecipe.frameSVG(L).replace(/ marker-end="[^"]*"/, ''), S_, M).map(p => p[0]); })()]; })()`);
  const expect = ['grows', 'label/label', 'position', 'identical boxes', 'key crosses a line', 'connector on edge',
    'connector rule', 'connector rule', 'connector ends', 'connector rule', 'arrowhead', 'arrowhead'];
  expect.forEach((e, i) => assert.ok(bad[i].includes(e), `${e}: ${bad[i].join()}`));
});

// Every keypad action of the old page is reachable by click / tap or wheel on the simulated screen itself.
test('no keypad: every former keypad action is reachable by click, tap or wheel', () => {
  assert.ok(!/data-k="(up|down|left|right|ok|f\+|f-|r\+|r-|ael|qs|menu)"/.test(html), 'no keypad buttons');
  assert.ok(!/<kbd>/.test(html + siteScript), 'no key legend');
  const snap = b => b.value('{S: Object.fromEntries(Object.entries(S).filter(([k]) => k !== "memory")), sub: S.sub}');
  const starts = [[]];                                   // setup via act() is fine; the action under test is not
  for (let i = 0; i < 8; i++) starts.push([`S.focus = ${i}; render();`]);
  for (const own of [1, 2, 3, 4]) for (let i = 0; i < 6; i++) starts.push([`S.focus = ${own}; act('ael'); S.focus = ${i}; render();`]);
  starts.push(["S.focus = 3; act('ael'); S.focus = 1; act('f+');"]);   // FINE active
  starts.push(["act('qs');"]);                                          // QS closed
  let compared = 0;
  for (const setup of starts) {
    const fresh = () => { const b = site(); setup.forEach(c => b.run(c)); if (b.run('layout()[S.focus]') === undefined) return null; return b; };
    const base = fresh(); if (!base) continue;
    const ways = {
      'f+': [b => b.wheel(40), b => b.click('qs', {'.tarr': {dataset: {d: '1'}}})],
      'f-': [b => b.wheel(-40), b => b.click('qs', {'.tarr': {dataset: {d: '-1'}}})],
      'r+': [b => b.wheel(40, true)], 'r-': [b => b.wheel(-40, true)],
      qs: [b => b.click('qsbtn')], ok: [b => b.run('S.open') && b.click('qsbtn')],
      ael: [b => b.click('qs', {'#ael': {}})], menu: [b => b.click('qs', {'#ael': {}})],
    };
    for (const k of ['left', 'right', 'up', 'down', 'f+', 'f-', 'r+', 'r-', 'ael', 'menu', 'qs', 'ok']) {
      const a = fresh(), before = snap(a); a.run(`act('${k}')`); const want = snap(a);
      if (JSON.stringify(want) === JSON.stringify(before)) continue;     // a no-op there needs no equivalent
      const tries = ways[k] || [b => b.click('qs', {'.tile': {dataset: {i: String(want.S.focus)}, classList: {contains: () => false}}})];
      for (const how of tries) {
        const b = fresh(); how(b);
        assert.deepEqual(snap(b), want, `${setup.join(' ')} ${k}`); compared++;
      }
    }
  }
  assert.ok(compared > 150, `only ${compared} comparisons`);
  // Coarse steps on touch: « » on a numeric footer equal the rear dial.
  for (const d of ['1', '-1']) {
    const a = site(), b = site();
    for (const x of [a, b]) x.run("S.focus = 1; act('ael'); S.focus = 1; render();");   // DC WIDTH spinner
    a.run(`act('${d === '1' ? 'r+' : 'r-'}')`);
    b.click('qs', {'.sp': {dataset: {d, big: '1'}}});
    assert.deepEqual(snap(b), snap(a));
  }
  // A second click on a selected tile with more options opens them, like AEL.
  const a = site(), b = site();
  a.run("S.focus = 1; render(); act('ael');");
  b.run('S.focus = 1; render();'); b.click('qs', {'.tile': {dataset: {i: '1'}, classList: {contains: () => false}}});
  assert.deepEqual(snap(b), snap(a));
});

// Rolling shutter in the live view: the scene's lean is RS x pan speed (frame widths / s) of the frame width,
// bottom row against top row; off = none; the dashed comparison uses the stock FHD 10.556 ms.
function skewProblem(transform, rsMs, v, g) {     // g: previewGeometry(); returns '' when the lean is right
  if (!v) return transform === '' ? '' : 'skew while off';
  const m = /^matrix\(1 0 (\S+) 1 (\S+) 0\)$/.exec(transform);
  if (!m) return 'no skew';
  const k = +m[1], shiftSensor = -k * g.ch;              // bottom row vs top row, sensor px (positive = to the left)
  const screen = shiftSensor / g.cw * g.w, want = v * rsMs / 1000 * g.w;
  if (Math.abs(screen - want) > 1) return `shift ${screen.toFixed(2)} px, want ${want.toFixed(2)} px`;
  if (Math.abs(+m[2] + k * 2020) > 1e-6) return 'not about the centre row';
  return '';
}

test('rolling shutter: the live view leans by RS x pan speed for every preset recipe; off = none; stock compare', () => {
  const b = site(), bad = [];
  let n = 0;
  for (const cell of presetCells()) for (const [, , name, r] of cell.recipes) {
    for (const [mode, v] of [['off', 0], ['slow', 1], ['fast', 4]]) {
      b.run(`S.dcW = ${cell.dcw}; S.dcH = ${cell.dch}; S.memory = {}; setRes0(${cell.rw}, ${cell.rh});
        S.recipe = ${JSON.stringify(name)}; S.recipeD = null; S.fps = Math.min(1000, allQuals().find(q => q.q === ${JSON.stringify(name)}).max);
        SiteRecipe.setPan('${mode}', true); render();`);
      if (b.run('(curRecipe() || {}).q') !== name) continue;
      const g = b.value('previewGeometry()');
      const p = skewProblem(b.elements.get('scene-g').getAttribute('transform'), r.rs_ms, v, g);
      const q = skewProblem(b.elements.get('ghost').getAttribute('transform'), 10.556, v, g);
      if (p || q) bad.push([cell.key, name, mode, p, q]);
      assert.equal(b.elements.get('ghost').style.display, v ? '' : 'none');
      n++;
    }
  }
  assert.ok(n > 2200, `${n}`);   // 0.0.5test: 14 recipes not offered
  assert.deepEqual(bad.slice(0, 5), []);
  b.run("SiteRecipe.setPan('slow', false); render();");
  assert.equal(b.elements.get('ghost').style.display, 'none', 'compare off hides the stock lean');
  assert.match(b.elements.get('rs-now').textContent, /stock FHD 10\.56 ms → 1\.06%/);
  // Mutation check: the checker rejects a lean with swapped axes, twice the time, or none at all.
  const g = {cw: 6048, ch: 3402, w: 1024};
  const swapped = -25.89 / 1000 * 3402 / 6048;      // the axes swapped
  assert.match(skewProblem(`matrix(1 0 ${swapped} 1 ${-swapped * 2020} 0)`, 25.89, 1, g), /^shift/);
  assert.notEqual(skewProblem('', 25.89, 1, g), '');
  const k = -2 * 25.89 / 1000 * 6048 / 3402;
  assert.match(skewProblem(`matrix(1 0 ${k} 1 ${-k * 2020} 0)`, 25.89, 1, g), /^shift/);
  const ok = -25.89 / 1000 * 6048 / 3402;
  assert.equal(skewProblem(`matrix(1 0 ${ok} 1 ${-ok * 2020} 0)`, 25.89, 1, g), '');
});

test('screen: QR bottom-right and WB in its cell on the main QS only; tiles keep their logical index', () => {
  const b = site();
  const cells = id => [...b.elements.get(id).innerHTML.matchAll(/class="tile[^"]*" data-i="(\d)"/g)].map(m => +m[1]);
  assert.deepEqual([...cells('r0'), ...cells('r1')], [0, 1, 2, 3, 4, 7, 6, 5]);
  assert.match(b.elements.get('r1').innerHTML, /data-i="5"><div class="qrsq" id="qr-matrix"[^]*<\/div><\/div>$/, 'QR is the last cell');
  assert.match(b.elements.get('r1').innerHTML.split('data-i="7"')[1].split('data-i="6"')[0], /WB/);
  b.run("S.focus = 1; act('ael');");
  assert.deepEqual([...cells('r0'), ...cells('r1')], [0, 1, 2, 3, 4, 5, 6, 7], 'sub-QS keeps the camera order');
  const c = site();
  c.click('qs', {'.tile': {dataset: {i: '5'}, classList: {contains: () => false}}});
  assert.equal(c.run('S.focus'), 5);
});

test('0.0.5test: every pre-margin code (old corpus) loads its inputs; a common rate out of reach is flagged', () => {
  const corpus = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'qs', 'test-fixtures', 'qr-old-codes', 'corpus.json'), 'utf8'));
  const inputs = ['ver', 'dcw', 'dch', 'rw', 'rh', 'fps', 'ad', 'mh', 'mv', 'hbin', 'vbin', 'kh', 'kv', 'km', 'fmt', 'scw', 'sch'];
  const STDR = [23.976, 24, 25, 29.97, 30, 47.952, 48, 50, 59.94, 60, 72, 90, 96, 100, 119.88, 120, 144, 150, 180, 200,
    239.76, 240, 300, 360, 400, 480, 500, 600, 1000];
  const enc = site();
  let ok = 0, flagged = 0, moved = 0, custom = 0;
  for (const e of corpus) {
    // 0.0.6test: the old ÷6 presets (ev(H / 6) rows) are custom RES now, computed by the engine (not in fps_data.js);
    // the camera client's test_qrscan.OldCodes restores them through the C core
    if (!FPS.cases[e.cell]) { custom++; assert.match(e.cell, /^[A-Z0-9-]+:(1008x(672|566)|688x392|656x436|336x206|672x672)$/); continue; }
    const code = enc.run(`qrPack(${JSON.stringify(Object.fromEntries(enc.value('QR_FIELDS.map(x => x[0])').map((k, i) => [k, e.f[i]])))})`);
    const ad = [11, 12, 14][e.f[8]];
    const q = FPS.cases[e.cell].find(([, , , r]) => r.ad === ad && r.mh === e.f[9] && r.mv === e.f[10] && r.hbin === e.f[11] &&
      r.vbin === e.f[12] && r.scw === e.f[23] && r.sch === e.f[24]);
    const expect = !!q && (e.f[5] >= 29 || FPS.clk / (q[0] * q[1]) >= STDR[e.f[5]] - 5e-4);
    const b = site(code);
    const bad = b.value('SiteRecipe.PAGE.inexact').map(x => x[0]);
    assert.equal(bad.length === 0, expect, `${e.cell} ${e.recipe} mode ${e.mode}: ${bad}`);
    assert.ok(bad.every(k => inputs.includes(k)), 'only input fields are compared');
    if (expect) { ok++; if (b.run('qrCode()') !== code) moved++; } else flagged++;
  }
  assert.ok(ok > 1400 && moved > 300, `${ok} ${moved}`);     // 1467 of 2511: 1044 codes are in the six old ÷6 cells
  assert.ok(custom > 1000 && custom < 1100, `${custom}`);
  assert.equal(flagged, corpus.length - ok - custom);
});
