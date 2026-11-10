// The "add your own .BIN" tile (2026-10-25): the page reads a v4 sup's header
// (display name, sup_id) and its file name's version, puts it on the card as it
// is, and treats a shared sup_id as a clash.  Minimal DOM, as test_ui_v4.js.
const fs = require('fs'), assert = require('assert');
const page = fs.readFileSync(process.env.MERGE_INDEX || __dirname + '/index.html', 'utf8');
const grab = id => page.match(new RegExp(`<script id="${id}"[^>]*>([\\s\\S]*?)</script>`))[1];
const elements = new Map(), handlers = new Map(), stored = {};
const el = id => {
  if (!elements.has(id)) elements.set(id, {innerHTML:'', textContent:'', style:{}, dataset:{}, setAttribute(){}, click(){}});
  return elements.get(id);
};
global.atob = s => Buffer.from(s, 'base64').toString('binary');
global.btoa = s => Buffer.from(s, 'binary').toString('base64');
global.localStorage = {getItem: k => k in stored ? stored[k] : (k === 'fpsup-lang' ? 'en' : null), setItem: (k, v) => { stored[k] = v; }};
global.FileReader = class { readAsArrayBuffer(f){ this.result = f.bytes.buffer; this.onload(); } };
global.document = {
  documentElement: {dataset:{}},
  getElementById: id => id === 'cat' ? {textContent:grab('cat')} : el(id),
  querySelector: s => s.startsWith('#') ? el(s.slice(1)) : null,
  querySelectorAll: () => [],
  addEventListener: (name, fn) => { if (!handlers.has(name)) handlers.set(name, fn); },
};
const api = new Function(grab('compose') + grab('ui') +
  '\nreturn {CAT, compose, checks, plan, readme, picked:()=>picked, addFiles, note:()=>UPNOTE};')();

require('./test_fill.js')(api.CAT);       // the bytes the page would fetch

function sup(sid, name, {magic = 'FSB4', svc = 6} = {}){
  const body = Buffer.alloc(16), nm = Buffer.from(name + '\0');
  const len = 48 + body.length + nm.length + (-(48 + body.length + nm.length) & 3);
  const d = Buffer.alloc(len);
  d.write(magic, 0, 'latin1');
  [48, len, len + 64, 48, 0, 3, svc, 1, 0, 0, 48 + body.length].forEach((v, i) => d.writeUInt32LE(v, 4 + 4 * i));
  d.write(sid, 20, 'latin1');
  nm.copy(d, 48 + body.length);
  return new Uint8Array(d);
}
const file = (name, bytes) => ({name, bytes});
const tiles = () => el('tiles').innerHTML;

assert(tiles().includes('id="drop"') && tiles().includes('Add a .BIN'));          // the tile is back
api.addFiles([file('HelloSup_v1.2.BIN', sup('HELO', 'Hello World'))]);
const up = api.CAT.products.find(p => p.upload);
assert.deepStrictEqual([up.name, up.sup_id, up.version, up.file], ['Hello World', 'HELO', '1.2', 'HelloSup_v1.2.BIN']);
assert(api.picked().includes(up.id));                                             // ticked once added
assert(tiles().includes('Hello World<span class="m">v1.2') && tiles().includes('sup_id HELO'));
let c = api.compose(api.picked());
assert(c.files.some(f => f.name === 'fpSup/HelloSup_v1.2.BIN' && !f.off));
assert(api.checks(api.picked()).every(r => r.ok), JSON.stringify(api.checks(api.picked()).filter(r => !r.ok)));
assert(api.readme(api.picked()).includes('HelloSup_v1.2.BIN'));
assert(JSON.parse(stored['fpsup-merge-v4-uploads']).length === 1);                // kept in this browser

// the same sup_id as one of the page's: a clash, one runs and the other is .OFF
const gyro = api.CAT.products.find(p => p.sup_id === 'GYR2');
api.addFiles([file('MyGyro_v9.BIN', sup('GYR2', 'My Gyro'))]);
const mine = api.CAT.products.find(p => p.file === 'MyGyro_v9.BIN');
assert.deepStrictEqual(mine.excl, [gyro.id]);
handlers.get('change')({target:{dataset:{id: gyro.id}, checked: true}});
const pl = api.plan(api.picked());
assert(pl.on.includes(mine.id) && pl.off.includes(gyro.id));                      // picked first wins
assert(api.compose(api.picked()).files.some(f => f.name === 'fpSup/' + gyro.file.replace(/\.BIN$/, '.OFF')));
assert(api.checks(api.picked()).every(r => r.ok));

// refused, with the reason in the section
api.addFiles([file('Old_v1.BIN', sup('OLDX', 'Old', {magic: 'FSB1'}))]);
assert(api.note().includes('v3 sup'));
api.addFiles([file('LOADER.BIN', sup('LOAD', 'x'))]);
assert(api.note().includes('has that name'));
api.addFiles([file(gyro.file, sup('ZZZZ', 'x'))]);
assert(api.note().includes('has that name'));
api.addFiles([file('New_v1.BIN', sup('NEWX', 'x', {svc: 99}))]);
assert(api.note().includes('service table v99'));
api.addFiles([file('note.txt', sup('NOTE', 'x'))]);
assert(api.note().includes('must be a .BIN'));
api.addFiles([file('Junk.BIN', new Uint8Array(100))]);
assert(api.note().includes('not a Loader v4 sup'));
assert.strictEqual(api.CAT.products.filter(p => p.upload).length, 2);

// remove
handlers.get('click')({target:{closest: () => ({dataset:{rm: up.id}})}});
assert(!api.CAT.products.some(p => p.id === up.id) && !api.picked().includes(up.id));
assert.strictEqual(JSON.parse(stored['fpsup-merge-v4-uploads']).length, 1);
// the tiles show versions, not the snapshot's build label (the user 2026-10-25)
for (const p of api.CAT.products.filter(p => !p.upload && p.category !== 'development' && !p.infra))   // infra: no tile
  assert(tiles().includes(`${p.name}<span class="m">v${p.version}`), p.name);
// select all / clear all (the user 2026-10-25)
const click = ds => handlers.get('click')({target:{closest: () => ({dataset: ds})}});
assert(tiles().includes('data-selall="1"'));
click({selall: '1'});
const rel = api.CAT.products.filter(p => p.category !== 'development' && !p.infra).map(p => p.id);
assert(!api.picked().includes('qs-share'));   // shared plumbing is never picked, only required
assert(rel.every(id => api.picked().includes(id)) && tiles().includes('data-selall="0"'));
assert(api.checks(api.picked()).every(r => r.ok), JSON.stringify(api.checks(api.picked()).filter(r => !r.ok)));
assert(!api.plan(api.picked()).on.some((a, i, on) => on.some(b => a !== b && api.CAT.products.find(p => p.id === a).excl.includes(b))));
click({selall: '0'});
assert(!rel.some(id => api.picked().includes(id)));
console.log('upload tile: ok');
