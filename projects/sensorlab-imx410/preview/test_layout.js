/* Layout stability in a real browser: headless Chrome (CDP, no packages) opens the generated page
 * (fpSup/sensor_lab_imx410/, served by a private loopback server) at 360 and 1280 px, makes ~50 random setting
 * changes per width, and requires every top-level section to keep its box (<= 1 px) and the scroll position to stay.
 * Skips when Chrome is not installed. Run: node --test preview/test_layout.js
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const test = require('node:test');

const ROOT = path.resolve(__dirname, '../../../fpSup/sensor_lab_imx410');
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.wasm': 'application/wasm', '.png': 'image/png'};
const sleep = ms => new Promise(r => setTimeout(r, ms));
// The sections whose boxes must not move; the diagram's drawing (#frame) is a fixed box too.
const SECTIONS = ['main > header', 'main > .sim', '#cam', '#side', '.frame-card', '#frame', '#details > .grid2',
  '#details > section:last-child', 'main > .page-foot'];

async function browser() {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html';
    const file = path.resolve(ROOT, rel.endsWith('/') ? rel + 'index.html' : rel);
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end(); }
    res.writeHead(200, {'content-type': TYPES[path.extname(file)] || 'application/octet-stream'});
    fs.createReadStream(file).pipe(res);
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = 9300 + Math.floor(Math.random() * 600), dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sl-layout-'));
  const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${port}`,
    `--user-data-dir=${dir}`, '--no-first-run', 'about:blank'], {stdio: 'ignore'});
  let targets;
  for (let i = 0; i < 80 && !targets; i++) { try { targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); } catch { await sleep(100); } }
  const ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const wait = new Map();
  ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && wait.has(m.id)) { wait.get(m.id)(m); wait.delete(m.id); } });
  const send = (method, params = {}) => new Promise(r => { const n = ++id; wait.set(n, r); ws.send(JSON.stringify({id: n, method, params})); });
  const evaluate = async expression => {
    const r = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || 'evaluate failed');
    return r.result.result.value;
  };
  await send('Page.enable');
  return {send, evaluate, url: `http://127.0.0.1:${server.address().port}/`,
    close() { ws.close(); chrome.kill(); server.close(); setTimeout(() => { try { fs.rmSync(dir, {recursive: true, force: true}); } catch { /* Chrome may still be exiting */ } }, 500); }};
}

const measure = `(() => ({scrollY: Math.round(scrollY), boxes: ${JSON.stringify(SECTIONS)}.map(sel => {
  const e = document.querySelector(sel); if (!e) return null;
  const r = e.getBoundingClientRect(); return [sel, r.left, r.top + scrollY, r.width, r.height]; })}))()`;

test('changing settings never moves a section or the scroll position (360 and 1280 px, real Chrome)',
  {skip: !fs.existsSync(CHROME) && 'Chrome not installed', timeout: 600000}, async () => {
    const b = await browser();
    try {
      for (const [width, height, mobile] of [[360, 780, true], [1280, 900, false]]) {
        for (const hash of ['', '#G9B-QvQfkGKTgOPlCKxIvAfUMpAXoPyL0D7zI']) {
          await b.send('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: mobile ? 2 : 1, mobile});
          await b.send('Page.navigate', {url: b.url + hash});
          await sleep(2500);
          await b.evaluate('document.fonts.ready.then(() => 1)');
          await b.evaluate('scrollTo(0, Math.round(document.documentElement.scrollHeight / 3)); 1');
          let seed = width + hash.length;
          const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
          const nav = ['left', 'right', 'up', 'down', 'ael', 'menu', 'right', 'left'], dial = ['f+', 'f-', 'r+', 'r-'];
          await sleep(300);
          let before = await b.evaluate(measure);
          const moved = [], codes = new Set();
          for (let n = 0; n < 50; n++) {
            const k = [nav[Math.floor(rnd() * nav.length)], dial[Math.floor(rnd() * dial.length)]];   // move, then change a value
            await b.evaluate(`act(${JSON.stringify(k[0])}); act(${JSON.stringify(k[1])}); 1`);
            await sleep(160);                           // the engine's new cell, the QR, the re-render
            const after = await b.evaluate(measure);
            codes.add(await b.evaluate('qrCode()'));
            if (after.scrollY !== before.scrollY) moved.push([n, k, 'scrollY', before.scrollY, after.scrollY]);
            after.boxes.forEach((box, i) => {
              const old = before.boxes[i];
              if (!box || !old) return;
              for (let j = 1; j < 5; j++) if (Math.abs(box[j] - old[j]) > 1) moved.push([n, k, box[0], ['left', 'top', 'width', 'height'][j - 1], old[j], box[j]]);
            });
            before = after;
          }
          assert.deepEqual(moved.slice(0, 8), [], `${width}px ${hash || 'no hash'}`);
          assert.ok(codes.size >= 10, `only ${codes.size} different selections were visited`);
          // The measurement can fail: a 40 px insertion at the top must be seen (mutation check).
          await b.evaluate("document.querySelector('main > header').prepend(Object.assign(document.createElement('div'), {style: 'height:40px'})); 1");
          const shifted = await b.evaluate(measure);
          assert.ok(Math.abs(shifted.boxes[0][4] - before.boxes[0][4]) >= 39, 'the check sees a 40 px jump');
        }
      }
    } finally { b.close(); }
  });
