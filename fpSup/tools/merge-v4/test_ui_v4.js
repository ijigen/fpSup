// Unit-test the page's actual render/change handlers with a minimal DOM.
// No browser, camera or external service is involved.
const fs = require('fs'), assert = require('assert');
const page = fs.readFileSync(process.env.MERGE_INDEX || __dirname + '/index.html', 'utf8');
const grab = id => page.match(new RegExp(`<script id="${id}"[^>]*>([\\s\\S]*?)</script>`))[1];
const elements = new Map(), handlers = new Map();
const el = id => {
  if (!elements.has(id)) elements.set(id, {innerHTML:'', textContent:'', style:{}, dataset:{}, setAttribute(){}});
  return elements.get(id);
};
global.atob = s => Buffer.from(s, 'base64').toString('binary');
global.localStorage = {getItem: () => 'zh', setItem(){}};
global.document = {
  documentElement: {dataset:{}},
  getElementById: id => id === 'cat' ? {textContent:grab('cat')} : el(id),
  querySelector: s => s.startsWith('#') ? el(s.slice(1)) : null,
  querySelectorAll: () => [],
  addEventListener: (name, fn) => handlers.set(name, fn),
};
const api = new Function(grab('compose') + grab('ui') +
  '\nreturn {BOOT, CAT, DATA_OFF, compose, checks, readme, zipFor, picked:()=>picked, history:p=>versionHistory(p,T[lang])};')();
require('./test_fill.js')(api.CAT);       // the bytes the page would fetch (test_lazy_v4.js covers the fetching)
const change = (dataset, checked) => handlers.get('change')({target:{dataset, checked}});
const startup = () => el('startup').innerHTML;
const checked = key => new RegExp(`data-boot="${key}" checked`).test(startup());
assert(checked('instant') && !checked('fast'));
assert(/data-boot="manager" checked disabled/.test(startup()));   // v4: always on
assert(startup().includes('瞬間啟動') && startup().includes('快速啟動'));
assert(startup().includes('type="checkbox" data-boot="fast"') && !startup().includes('role="switch"'));
const id = api.CAT.products[0].id;
change({id}, true);
assert.deepStrictEqual(api.picked(), [id]);
const original = api.compose([id]).files;
change({boot:'fast'}, true);
assert(checked('instant') && checked('fast'));
assert.deepStrictEqual(api.picked(), [id]);
assert(api.checks([id]).every(r => r.ok));
const now = api.compose([id]).files;
assert.notStrictEqual(now.find(f => f.name === 'AutoRun.txt').sha256, original.find(f => f.name === 'AutoRun.txt').sha256);
assert.strictEqual(now.find(f => f.p).sha256, original.find(f => f.p).sha256);
change({boot:'instant'}, false);
assert(!checked('instant') && checked('fast'));
assert.deepStrictEqual(api.picked(), [id]);
change({boot:'fast'}, false);
assert(!checked('instant') && !checked('fast'));
assert(api.checks([id]).every(r => r.ok));
change({boot:'instant'}, true);
assert(checked('instant') && !checked('fast'));
assert(api.checks([id]).every(r => r.ok));
change({id}, false);
change({boot:'manager'}, false);                    // disabled checkbox: no effect
assert(checked('manager') && !el('dl').disabled);
assert(api.compose([]).files.some(f => f.name === 'fpSup/UI/FPSUP.BIN'));
assert(!api.compose([]).files.some(f => f.name === 'fpSup/UI/ALLSUPS.BIN'));
if (api.CAT.products.some(p => p.id === 'res-lab')){
  const lab = api.CAT.products.find(p => p.id === 'res-lab');
  assert.strictEqual(lab.name, 'RES-Lab v0.1.0test');
  assert.strictEqual(lab.file, '50RES-Lab v0.1.0test.BIN');
  assert(el('tiles').innerHTML.includes('RES-Lab v0.1.0test<span class="m">v'));   // the version, not the build label (2026-10-25)
  change({id:'res-lab'}, true);
  assert.deepStrictEqual(api.picked(), ['res-lab']);
  assert(/data-boot="manager" checked disabled/.test(startup()));
  assert(/data-id="res-custom" checked disabled/.test(el('tiles').innerHTML));
  assert(!el('dl').disabled && el('tree').innerHTML.includes('fpSup 管理頁'));
  assert(api.compose(api.picked()).on.includes('res-custom'));
  assert(!api.compose(api.picked()).files.some(f => f.name.endsWith('.RCD')));
  const file = api.CAT.products.find(p => p.id === 'res-custom').data_files[0].path;
  change({file,of:'res-custom'}, true);
  assert(api.compose(api.picked()).files.some(f => f.name === file));
  change({file,of:'res-custom'}, false);
  assert(!api.compose(api.picked()).files.some(f => f.name.endsWith('.RCD')));
  change({boot:'fast'}, true);
  assert(!el('dl').disabled && checked('fast'));
  change({id:'res-lab'}, false);
  assert(!checked('manager') && el('dl').disabled);
}
for (const id of ['desqueeze', 'tap-to-zoom']){
  const p = api.CAT.products.find(p => p.id === id);
  assert(p && p.author === 'Jose Hurtado' && p.category === 'monitor');
  assert(el('tiles').innerHTML.includes(`data-id="${id}"`));
  assert(el('tiles').innerHTML.includes(`../../guide/${id}.html`));
  change({id}, true);
}
assert.deepStrictEqual(api.picked(), ['desqueeze', 'tap-to-zoom']);
assert(api.checks(api.picked()).every(r => r.ok) && !el('dl').disabled);
const monitorFiles = api.compose(api.picked()).files.filter(f => f.p);
const fileOf = id => 'fpSup/' + api.CAT.products.find(p => p.id === id).file;   // names_v4 names (2026-10-25)
assert.deepStrictEqual(monitorFiles.map(f => f.name), ['desqueeze', 'tap-to-zoom'].map(fileOf).sort());
assert(el('tiles').innerHTML.includes('作者 <b>Jose Hurtado</b>'));
assert(api.readme(api.picked()).includes('by Jose Hurtado'));
for (const id of ['desqueeze', 'tap-to-zoom']) change({id}, false);
assert(!el('dl').disabled);              // v4: the fpSup page alone is a card
const stopfx = api.CAT.products.find(p => p.id === 'stopfx');
assert(stopfx && stopfx.author === 'Ruari');
assert(el('tiles').innerHTML.includes('作者 <b>Ruari</b>'));
for (const id of ['stopfx', 'fcap']){
  change({id}, true);
  assert.deepStrictEqual(api.picked(), [id]);
  assert.deepStrictEqual(api.compose(api.picked()).on, [id]);
  assert(api.checks(api.picked()).every(r => r.ok) && !el('dl').disabled);
  change({id}, false);
}
// Ticking Lossless ticks FCAP too (user 2026-10-15), but FCAP stays optional
change({id:'lossless'}, true);
assert.deepStrictEqual(api.picked(), ['lossless', 'fcap']);
assert(api.checks(api.picked()).every(r => r.ok) && !el('dl').disabled);
change({id:'fcap'}, false);
assert.deepStrictEqual(api.compose(api.picked()).on, ['lossless']);
assert(api.checks(api.picked()).every(r => r.ok) && !el('dl').disabled);
change({id:'lossless'}, false);
change({id:'fcap'}, true);                         // FCAP first: Lossless adds nothing twice
change({id:'lossless'}, true);
assert.deepStrictEqual(api.picked(), ['fcap', 'lossless']);
change({id:'stopfx'}, true);
assert.deepStrictEqual(api.compose(api.picked()).files.filter(f => f.p).map(f => f.name),
  ['fcap', 'lossless', 'stopfx'].map(fileOf).sort());
assert(api.readme(api.picked()).includes('by Ruari'));
assert(api.checks(api.picked()).every(r => r.ok) && !el('dl').disabled);
change({id:'lossless'}, false);
assert(api.compose(api.picked()).on.includes('stopfx') && !api.compose(api.picked()).on.includes('lossless'));
for (const id of api.compose(api.picked()).on.slice()) change({id}, false);
assert(!el('dl').disabled);              // v4: the fpSup page alone is a card

// History is available on every tile, including Sups without a release.
for (const p of api.CAT.products.concat(api.CAT.pending || []).filter(p => !p.infra)){   // infra: no tile (below)
  assert(el('tiles').innerHTML.includes(`data-history="${p.id}"`));
  const html = api.history(p);
  assert(html.includes('版本改動'));
  if (p.history.length){
    for (const h of p.history){
      assert(html.includes(h.label));
      if (h.source && h.source_kind !== 'manifest') assert(html.includes(`href="${h.source}"`));
    }
    assert.strictEqual(p.history.filter(h => h.current).length, p.release ? 1 : 0);
  } else assert(html.includes('尚無版本改動紀錄'));
}
const raw = api.CAT.products.find(p => p.id === 'raw-view');
const rawLegacy = ['0.3.0test','0.2.3test','0.2.2test','0.2.1test','0.2.0test','0.1.0test'];
assert.deepStrictEqual(raw.history.filter(h => rawLegacy.includes(h.version)).map(h => h.version), rawLegacy);
const beforeHistory = Buffer.from(api.zipFor(['raw-view']));
const toggle = open => handlers.get('toggle')({target:{dataset:{history:'raw-view'},open}});
const language = lang => handlers.get('click')({target:{closest:()=>({dataset:{lang}})}});
toggle(true);
change({id:'raw-view'}, true);
assert(el('tiles').innerHTML.includes('data-history="raw-view" open'));
language('en');
assert(api.history(raw).includes('Version changes') && api.history(raw).includes('Currently offered'));
assert(api.history(raw).includes('data-history="raw-view" open'));
language('cn');
assert(api.history(raw).includes('版本改动') && api.history(raw).includes('完整版本说明'));
language('zh');
toggle(false);
change({id:'raw-view'}, false);
assert(!api.history(raw).includes('data-history="raw-view" open'));
assert.deepStrictEqual(api.picked(), []);
assert(Buffer.from(api.zipFor(['raw-view'])).equals(beforeHistory));
const unsafe = api.history({id:'example',name:'<example>',history:[{label:'v1',
  changes:{en:['<script>unsafe</script>'],zh:['<script>unsafe</script>']}}]});
assert(!unsafe.includes('<script>') && unsafe.includes('&lt;script&gt;'));
// Sensor Lab (Bei 2026-11-07): QS-Share has no tile and cannot be ticked or picked by Select all; it comes with
// Sensor Lab, shown in the summary as shared.  Sensor Lab <-> RES-Custom: the second one ticked goes on the card off.
if (api.CAT.products.some(p => p.id === 'sensor-lab')){
  const tiles = () => el('tiles').innerHTML;
  assert(tiles().includes('data-id="sensor-lab"') && !tiles().includes('data-id="qs-share"') && !tiles().includes('data-history="qs-share"'));
  assert(tiles().includes('QS-Share') && tiles().includes('QSContainer_v*.BIN'));   // the hint and the upgrade note on Sensor Lab's tile
  change({id:'sensor-lab'}, true);
  assert.deepStrictEqual(api.picked(), ['sensor-lab']);
  assert(el('tree').innerHTML.includes('QS-Share (共用元件，自動附上)') && el('tree').innerHTML.includes('Sensor Lab-IMX410'));
  assert(api.compose(api.picked()).on.includes('qs-share') && !el('dl').disabled);
  change({id:'qs-share'}, false);                   // no such tile; a stray event changes nothing it needs
  assert(api.compose(api.picked()).on.includes('qs-share'));
  change({id:'res-custom'}, true);
  assert.deepStrictEqual(api.compose(api.picked()).off, ['res-custom']);
  assert(tiles().includes('data-yield="sensor-lab"') || tiles().includes('data-swap="res-custom"'));
  assert(api.checks(api.picked()).every(r => r.ok) && !el('dl').disabled);
  change({id:'res-custom'}, false); change({id:'sensor-lab'}, false);
  assert.deepStrictEqual(api.picked(), []);
  handlers.get('click')({target:{closest:()=>({dataset:{selall:'1'}})}});
  assert(api.picked().includes('sensor-lab') && !api.picked().includes('qs-share'));
  handlers.get('click')({target:{closest:()=>({dataset:{selall:'0'}})}});
  assert.deepStrictEqual(api.picked(), []);
}
console.log('passed: boot choices, selections, download checks, version history, languages and retained disclosure state');

const resSimple = api.CAT.products.find(p => p.id === 'res-custom');
assert(!/consumer|dev-r19|RCD|宣告/.test(api.history(resSimple)));
assert(!api.history(stopfx).includes('manifest.json'));
assert(page.includes('<small>Loader v4</small>') && !page.includes('id="hashtbl"'));
assert.strictEqual(api.CAT.products.find(p => p.id === 'gyro2').credits.length, 0);
