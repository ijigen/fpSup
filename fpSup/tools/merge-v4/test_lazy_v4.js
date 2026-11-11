// node tools/merge-v4/test_lazy_v4.js
// The page holds no sup bytes (Bei 2026-11-10): ticking a tile fetches that
// sup from the site (`src`), the bytes are kept only if they are the
// catalogue's, and "Download zip" requests each GitHub Release asset once so
// GitHub counts it.  fetch is a stand-in that serves this folder; no network.
const fs = require('fs'), path = require('path'), assert = require('assert');
const page = fs.readFileSync(process.env.MERGE_INDEX || __dirname + '/index.html', 'utf8');
const grab = id => page.match(new RegExp(`<script id="${id}"[^>]*>([\\s\\S]*?)</script>`))[1];

function boot({served = '', corrupt = null, down = false, hosted = true, api = null, host = 'ijigen.github.io', counts = null} = {}){
  const elements = new Map(), handlers = new Map(), calls = [], clicked = [];
  const el = id => {
    if (!elements.has(id)) elements.set(id, {innerHTML:'', textContent:'', style:{}, dataset:{}, disabled:false, setAttribute(){}, click(){}});
    return elements.get(id);
  };
  const g = {
    atob: s => Buffer.from(s, 'base64').toString('binary'), btoa: s => Buffer.from(s, 'binary').toString('base64'),
    localStorage: {getItem: k => k === 'fpsup-lang' ? 'en' : null, setItem(){}},
    location: hosted ? {protocol: 'https:', hostname: host} : {protocol: 'file:', hostname: ''},
    Blob: class { constructor(parts){ this.parts = parts; } },
    URL: {createObjectURL: () => 'blob:x', revokeObjectURL(){}},
    setTimeout: () => 0,
    document: {
      documentElement: {dataset:{}}, body: {appendChild(){}},
      createElement: () => ({click(){ clicked.push(this.download); }, remove(){}}),
      getElementById: id => id === 'cat' ? {textContent: grab('cat')} : el(id),
      querySelector: s => s.startsWith('#') ? el(s.slice(1)) : null,
      querySelectorAll: () => [],
      addEventListener: (name, fn) => handlers.set(name, fn),
    },
    fetch: async (url, opt) => {
      calls.push({url, opt});
      if (url.startsWith('https://api.github.com/')){
        if (!api) return {ok: false, status: 403};
        return {ok: true, json: async () => api(url)};
      }
      if (url === '/counts.json' || url === 'https://fpsup.ijigen.xyz/counts.json'){
        if (!counts) throw new TypeError('Failed to fetch');
        return {ok: true, json: async () => counts};
      }
      if (url.startsWith('/count/')) return {ok: true, status: 204};
      if (url.startsWith('https://github.com/')) return {type: 'opaque', ok: false, status: 0};
      if (down) throw new TypeError('Failed to fetch');
      if (!url.startsWith(served)) return {ok: false, status: 404};
      const rel = decodeURIComponent(url.slice(served.length));
      const file = path.join(__dirname, rel);
      if (!fs.existsSync(file)) return {ok: false, status: 404};
      const b = Buffer.from(fs.readFileSync(file));
      if (corrupt && rel.endsWith(corrupt)) b[b.length - 1] ^= 1;
      return {ok: true, status: 200, arrayBuffer: async () => b.buffer.slice(b.byteOffset, b.byteOffset + b.length)};
    },
  };
  const names = Object.keys(g);
  const page_ = new Function(...names, grab('compose') + grab('ui') +
    '\nreturn {CAT, compose, checks, missing, assets, zipFor, picked:()=>picked};')(...names.map(k => g[k]));
  return {...page_, el, calls, clicked, g,
    change: (dataset, checked) => handlers.get('change')({target: {dataset, checked}}),
    click: target => handlers.get('click')({target: {closest: () => target}}),
    settle: async () => { for (let i = 0; i < 50; i++) await new Promise(r => setImmediate(r)); }};
}
const siteFetches = p => p.calls.filter(c => !c.url.startsWith('https://') && !c.url.startsWith('/count'));

(async () => {
  // 1. nothing is in the page, nothing is fetched until a tile is ticked
  let p = boot();
  await p.settle();
  const prods = p.CAT.products;
  assert(prods.length >= 10 && prods.every(x => x.data == null && x.src && x.asset), 'no sup bytes embedded; every sup has src + asset');
  assert(prods.every(x => [...x.data_files, ...x.support_files].every(d => d.data == null && d.src && d.asset)), 'data files too');
  assert.strictEqual(siteFetches(p).length, 0, 'no sup fetched on load');
  assert(page.length < 1200000, 'page is smaller than with every sup embedded');

  // 2. ticking one sup fetches that sup only; the card is ready when its bytes are the catalogue's
  const lossless = prods.find(x => x.id === 'lossless'), fcap = prods.find(x => x.id === 'fcap');
  p.change({id: 'stopfx'}, true);
  assert(/Getting 1 file/.test(p.el('status').textContent) && p.el('dl').disabled, 'waits, download disabled');
  assert(p.el('tree').innerHTML.includes('Stop-FX'), 'the card list shows at once');
  assert.throws(() => p.compose(p.picked()), /not downloaded yet/);
  await p.settle();
  assert.deepStrictEqual(siteFetches(p).map(c => c.url), ['inputs/v4-20261027/Stop-FX_v0.1.0.BIN']);
  assert(/Ready to download/.test(p.el('status').textContent) && !p.el('dl').disabled);
  assert(p.checks(p.picked()).every(r => r.ok) && lossless.data == null);
  // lossless links fcap: both, each once; stopfx is not fetched again
  p.change({id: 'lossless'}, true);
  await p.settle();
  assert.deepStrictEqual(siteFetches(p).map(c => c.url).sort(),
    ['inputs/v4-20261027/EarlyFlush_v0.1.0.BIN', 'inputs/v4-20261110c/Lossless_v0.3.2test.BIN', 'inputs/v4-20261027/Stop-FX_v0.1.0.BIN'].sort());
  assert(lossless.data != null && fcap.data != null);

  // 3. download: the zip, then one request per release asset, unreadable (no-cors); once per visit
  assert.strictEqual(p.calls.filter(c => c.url.startsWith('https://github.com/')).length, 0, 'nothing counted before the download');
  p.click({id: 'dl', dataset: {}});
  const counted = () => p.calls.filter(c => c.url.startsWith('https://github.com/'));
  assert.strictEqual(p.clicked.length, 1);
  assert.deepStrictEqual(counted().map(c => c.url).sort(), [
    'https://github.com/ijigen/fpSup/releases/download/fpsup-fcap-v0.1.0/EarlyFlush_v0.1.0.BIN',
    'https://github.com/ijigen/fpSup/releases/download/fpsup-lossless-v0.3.2test/Lossless_v0.3.2test.BIN',
    'https://github.com/ijigen/fpSup/releases/download/fpsup-stopfx-v0.1.0/Stop-FX_v0.1.0.BIN']);
  assert(counted().every(c => c.opt.mode === 'no-cors'));
  p.click({id: 'dl', dataset: {}});
  assert.strictEqual(p.clicked.length, 2);
  assert.strictEqual(counted().length, 3, 'a second download in the same visit is not counted again');
  // data files are assets of their sup's release, counted when they go on the card
  p.change({id: 'res-custom'}, true);
  await p.settle();
  p.click({id: 'dl', dataset: {}});
  const rc = counted().map(c => c.url).filter(u => u.includes('/fpsup-res-custom-v'));
  assert(rc.length === 6 && rc.some(u => u.endsWith('/OG3K.RCD')) && rc.some(u => /RES-Custom_v[\d.]+\.BIN$/.test(u)), 'res-custom + its 5 formats');

  // 4. wrong bytes are refused: no card, and the reason is shown; Retry fetches again
  p = boot({corrupt: 'Stop-FX_v0.1.0.BIN'});
  p.change({id: 'stopfx'}, true);
  await p.settle();
  assert(p.CAT.products.find(x => x.id === 'stopfx').data == null, 'bytes that are not the catalogue\'s are not kept');
  assert(/Could not get Stop-FX_v0\.1\.0\.BIN \(sha256\)/.test(p.el('status').textContent), p.el('status').textContent);
  assert.strictEqual(p.el('dl').textContent, 'Retry');
  const before = siteFetches(p).length;
  p.click({id: 'dl', dataset: {}});
  await p.settle();
  assert(siteFetches(p).length > before && p.clicked.length === 0, 'Retry fetches again and downloads nothing');

  // 5. no connection: said so, nothing downloaded, nothing counted
  p = boot({down: true});
  p.change({id: 'stopfx'}, true);
  await p.settle();
  assert(/Could not get .*Failed to fetch/.test(p.el('status').textContent));
  p.click({id: 'dl', dataset: {}});
  await p.settle();
  assert(p.clicked.length === 0 && !p.calls.some(c => c.url.startsWith('https://github.com/')));

  // 6. the copy in tools/card-composer/ finds the same files one folder over, and then asks there first
  p = boot({served: '../merge-v4/'});
  p.change({id: 'stopfx'}, true);
  await p.settle();
  assert(/Ready to download/.test(p.el('status').textContent));
  p.change({id: 'fcap'}, true);
  await p.settle();
  assert.strictEqual(siteFetches(p).pop().url, '../merge-v4/inputs/v4-20261027/EarlyFlush_v0.1.0.BIN');
  assert.strictEqual(siteFetches(p).length, 3, '404 at the first place once, not per file');

  // 7. opened from disk (or localhost): cards work, nothing is counted and GitHub's API is not asked
  p = boot({hosted: false});
  p.change({id: 'stopfx'}, true);
  await p.settle();
  p.click({id: 'dl', dataset: {}});
  assert(p.clicked.length === 1 && !p.calls.some(c => c.url.startsWith('https://')));

  // 8. the tile shows GitHub's count: the sup's .BIN over all its versions (data files and other sups not added in)
  const rel = (tag, assets) => ({tag_name: tag, draft: false, assets: assets.map(([name, download_count]) => ({name, download_count}))});
  p = boot({api: url => /[?&]page=1$/.test(url) ? [
    rel('fpsup-res-custom-v0.1.5', [['RES-Custom_v0.1.5.BIN', 1200], ['OG3K.RCD', 900]]),
    rel('fpsup-res-custom-v0.1.4', [['RES-Custom_v0.1.4.BIN', 34]]),
    rel('fpsup-raw-view-v0.3.1', [['RAW-View_v0.3.1.BIN', 7]]),
    rel('some-other-tag', [['X.BIN', 99999]])] : []});
  await p.settle();
  const tiles = p.el('tiles').innerHTML;
  assert(/↓ 1,234 downloads/.test(tiles) && /↓ 7 downloads/.test(tiles), 'counts on the tiles');
  assert(!/99,999/.test(tiles) && !/2,134/.test(tiles));
  assert((tiles.match(/class="dls"/g) || []).length === 2, 'only sups GitHub has a release for show a number');
  // the API refusing (rate limit) changes nothing else
  p = boot();
  await p.settle();
  assert(!p.el('tiles').innerHTML.includes('class="dls"'));

  // 6. the mirror's counts.json (GitHub's numbers + the mirror's own) is read first, from either site
  const both = {github: {'fpsup-lossless-v0.3.2test/Lossless_v0.3.2test.BIN': 100, 'fpsup-lossless-v0.3.1test/Lossless_v0.3.1test.BIN': 20,
                         'fpsup-res-custom-v0.1.0/OG3K.RCD': 5000},
                mirror: {'fpsup-lossless-v0.3.2test/Lossless_v0.3.2test.BIN': 7, 'fpsup-nope-v1/X.BIN': 9}};
  for (const host of ['ijigen.github.io', 'fpsup.ijigen.xyz']){
    p = boot({host, counts: both, api: () => { throw new Error('GitHub is not asked when the mirror answered'); }});
    await p.settle();
    const t = p.el('tiles').innerHTML;
    assert(/title="all versions; v0\.3\.2test: 107; 7 of all through the mirror">↓ 127 downloads/.test(t), host + ': ' + (t.match(/class="dls"[^<]*<\/span>/) || [t.slice(0, 200)])[0]);
    assert((t.match(/class="dls"/g) || []).length === 1 && !/5,000/.test(t), 'data files and unknown tags are not counted');
    assert(p.calls.some(c => c.url === (host === 'fpsup.ijigen.xyz' ? '/counts.json' : 'https://fpsup.ijigen.xyz/counts.json')));
  }
  // 7. on the mirror a download is counted by the mirror, and GitHub is never contacted
  p = boot({host: 'fpsup.ijigen.xyz', counts: both});
  await p.settle();
  p.change({id: 'stopfx'}, true);
  p.change({id: 'lossless'}, true);
  await p.settle();
  p.click({id: 'dl', dataset: {}});
  p.click({id: 'dl', dataset: {}});
  assert.deepStrictEqual(p.calls.filter(c => c.url.startsWith('/count/')).map(c => c.opt.method + ' ' + c.url).sort(), [
    'POST /count/fpsup-fcap-v0.1.0/EarlyFlush_v0.1.0.BIN',
    'POST /count/fpsup-lossless-v0.3.2test/Lossless_v0.3.2test.BIN',
    'POST /count/fpsup-stopfx-v0.1.0/Stop-FX_v0.1.0.BIN']);
  assert(!p.calls.some(c => /github\.com/.test(c.url)), 'nothing on the mirror depends on GitHub');
  console.log('lazy fetch, sha256 gate, release counting, download counts, mirror counts: ok');
})().catch(e => { console.error(e); process.exit(1); });
