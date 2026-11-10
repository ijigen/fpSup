// node tools/merge-v4/test_merge_v4.js
// Runs the page's own compose block (no DOM) against the built index.html and
// checks it against the frozen release folders on disk.
const fs = require('fs'), path = require('path'), crypto = require('crypto'), zlib = require('zlib');
// MERGE_INDEX / MERGE_RELEASES: a page built from another releases folder
// (test_data_files.sh builds one with a synthetic res-custom).
const HERE = __dirname;
const RELEASES = process.env.MERGE_RELEASES || path.join(HERE, '..', '..', 'releases');
const page = fs.readFileSync(process.env.MERGE_INDEX || path.join(HERE, 'index.html'), 'utf8');
const grab = id => page.match(new RegExp(`<script id="${id}"[^>]*>([\\s\\S]*?)</script>`))[1];

global.atob = s => Buffer.from(s, 'base64').toString('binary');
global.TextEncoder = TextEncoder;
global.document = {getElementById: () => ({textContent: grab('cat')})};
const api = new Function(grab('compose') +
  '\nreturn {CAT, DATA_OFF, BOOT, bootFiles, selected, managerEnabled, payloadFor, plan, compose, checks, readme, zipFor, cardName, sha256hex};')();
const {CAT, DATA_OFF, BOOT, bootFiles, selected, managerEnabled, payloadFor, plan, compose, checks, zipFor, cardName, sha256hex} = api;
// The page holds no sup bytes (2026-11-10): it fetches each record's `src`.  Here they come from disk.
const EMBEDDED = CAT.products.filter(p => !p.upload && p.data != null).map(p => p.id);
const FILLED = require('./test_fill.js')(CAT);

let fails = 0;
const ok = (c, what) => { console.log((c ? 'ok   ' : 'FAIL ') + what); if (!c) fails++; };
const sha = b => crypto.createHash('sha256').update(b).digest('hex');

// Unzip a stored zip (what zipStore writes) -> {name: Buffer}
function unzip(u8){
  const b = Buffer.from(u8), out = {};
  let o = 0;
  while (b.readUInt32LE(o) === 0x04034B50){
    const n = b.readUInt16LE(o + 26), x = b.readUInt16LE(o + 28), len = b.readUInt32LE(o + 18);
    const crc = b.readUInt32LE(o + 14);
    const name = b.slice(o + 30, o + 30 + n).toString();
    const data = b.slice(o + 30 + n + x, o + 30 + n + x + len);
    if (zlib.crc32 && zlib.crc32(data) !== crc) throw new Error('crc ' + name);
    out[name] = data; o += 30 + n + x + len;
  }
  return out;
}

// 0a. the page's UI script parses (the compose block runs above; this one is DOM-only)
try { new Function(grab('ui')); ok(true, 'ui script parses'); } catch (e) { ok(false, 'ui script parses: ' + e.message); }

// 0b. no sup bytes in the page: every product and data file names where the site serves it and its release asset
ok(EMBEDDED.length === 0 && FILLED >= CAT.products.length, `no sup embedded; ${FILLED} files read from the snapshots by their src`);
ok(CAT.products.every(p => [p, ...p.data_files, ...p.support_files].every(r =>
     r.asset === `https://github.com/${CAT.repo}/releases/download/${p.release}/${path.basename(r.src)}`)),
   'every file is an asset of its product\'s release tag');

// 0. the page's sha256 is SHA-256
ok(sha256hex(new Uint8Array(0)) === sha(Buffer.alloc(0)) &&
   sha256hex(new Uint8Array(1000).fill(7)) === sha(Buffer.alloc(1000, 7)), 'sha256hex matches node');

ok(BOOT.instant === true && BOOT.fast === false && BOOT.manager === true, 'Instant on by default; Fast opt-in; fpSup page always (v4)');

function sourceFiles(p){
  if (!p.provenance) return null;
  const manifest = path.resolve(HERE, p.provenance.manifest);
  const meta = JSON.parse(fs.readFileSync(manifest, 'utf8'));
  ok(Object.entries(meta.files).every(([rel, f]) => {
    const b = fs.readFileSync(path.join(path.dirname(manifest), rel));
    return b.length === f.size && sha(b) === f.sha256;
  }), `${p.id}: all development input bytes match their snapshot manifest`);
  const entry = meta.products[p.id];
  ok(p.sha256 === meta.files[entry.file].sha256 &&
     (!p.virtual || p.virtual.sha256 === meta.files[entry.virtual].sha256), `${p.id}: exact intended payloads embedded`);
  return {dir:path.dirname(manifest), entry};
}

// 1. Frozen products and artwork stay exact. Boot files come as coherent pairs
// from the maintained builder, whose actual ARM execution is tested separately.
for (const p of CAT.products){
  const z = unzip(zipFor([p.id])), root = cardName([p.id]) + '/';
  sourceFiles(p);
  const composed = compose([p.id]).files;
  const want = composed.map(f => f.name);
  const same = composed.every(f => z[root + f.name] && z[root + f.name].equals(Buffer.from(f.data)));
  if (!p.provenance){
    const rel = path.join(RELEASES, p.release);
    ok(z[root + 'fpSup/' + p.file].equals(fs.readFileSync(path.join(rel, 'fpSup', p.file))), `${p.id}: exact frozen sup bytes`);
    for (const d of p.data_files || []) ok(z[root + d.path].equals(fs.readFileSync(path.join(rel, d.path))), `${p.id}: exact frozen ${d.path}`);
    for (const i of [0,1,2,3,4]) ok(z[root + `fpSup/UI/${i}.BIN`].equals(fs.readFileSync(path.join(rel, `fpSup/UI/${i}.BIN`))), `${p.id}: exact released artwork ${i}`);
  }
  const extra = Object.keys(z).filter(k => !want.includes(k.slice(root.length)) && k !== root + 'README.txt');
  ok(same && !extra.length && checks([p.id]).every(r => r.ok), `${p.id}: released product bytes, current boot pair`);
  const ar = z[root + 'AutoRun.txt'];
  const meta = CAT.shared.find(f => f.path === 'AutoRun.txt');
  ok(ar.length === meta.size && sha(ar) === meta.sha256 && ar.at(-1) === 10 &&
     !ar.includes('# pad -- see PAD_TO:'), `${p.id}: real AutoRun EOF and hash`);
}

for (const manager of [true]) for (const instant of [false, true]) for (const fast of [false, true]){
  BOOT.instant = instant; BOOT.fast = fast; BOOT.manager = manager;
  // Test both manager states directly; RES-Lab's automatic manager is below.
  // every sup that can run together (Sensor Lab / RES-Custom clash: the later one would change LOADER.BIN's list)
  const picked = plan(CAT.products.filter(p => !p.needs_manager).map(p => p.id)).on;
  const z = unzip(zipFor(picked)), root = cardName(picked) + '/';
  const pair = CAT.boot.variants[`${manager ? 'm1' : ''}i${+instant}f${+fast}`].files;
  ok(pair.every(f => z[root + f.path].equals(Buffer.from(f.data, 'base64')) &&
      sha(z[root + f.path]) === f.sha256 && z[root + f.path].length === f.size)
      && checks(picked).every(r => r.ok), `Manager ${manager}, Instant ${instant}, Fast ${fast}: exact boot pair in zip`);
  ok(CAT.products.filter(p => picked.includes(p.id)).every(p => z[root + 'fpSup/' + p.file] || z[root + 'fpSup/' + p.file.replace(/\.BIN$/, '.OFF')]),
     `Instant ${instant}, Fast ${fast}: selections retained`);
  const readme = z[root + 'README.txt'].toString();
  ok(readme.includes('Instant Start: ' + (instant ? 'ON' : 'OFF')) &&
     readme.includes('Fast Start: ' + (fast ? 'ON' : 'OFF')), 'README records boot choices');
  const bin = z[root + 'fpSup/LOADER.BIN'];
  const end = 16 + 8 * bin.readUInt32LE(4) + bin.readUInt32LE(12);
  ok(bin.length === end + (manager ? 128 : 0) && (!manager || (bin.readUInt32LE(end) === 0x53445346 && bin.readUInt32LE(end+4) === 0)), 'actual VBIN length plus empty manager disabled list');
  ok(CAT.boot.manager_files.every(f => z[root + f.path] && sha(z[root + f.path]) === f.sha256) && !z[root + 'fpSup/UI/ALLSUPS.BIN'] &&
     readme.includes('fpSup page: ON'), 'fpSup page and SupManager on every card, no v3 ALLSUPS');
  ok(Object.keys(z).filter(k => /\/fpSup\/[^/]+\.BIN$/.test(k) && !k.endsWith('/LOADER.BIN'))
       .every(k => z[k].readUInt32LE(0) === 0x34425346 && z[k].readUInt32LE(4) === 48), 'every sup on the card is FSB4');
  const f = pair[1], saved = f.data;
  const bad = Buffer.from(saved, 'base64'); bad[32] ^= 1; f.data = bad.toString('base64');
  ok(checks(picked).some(r => !r.ok), 'flipped boot byte blocks download');
  f.data = saved;
}
Object.assign(BOOT, CAT.boot.default);

BOOT.manager = false;
ok(checks([]).every(r => r.ok) && compose([]).files.some(f => f.name === 'fpSup/UI/FPSUP.BIN') &&
   compose([]).files.some(f => f.name === 'fpSup/SUPMGR.BIN'), 'fpSup page alone downloads, and stays even with the old checkbox state off');
Object.assign(BOOT, CAT.boot.default);
ok(CAT.products.every(p => !/^\d{2}/.test(p.file)), 'v4 file names (no v3 NN prefix)');
if (CAT.products.some(p => p.id === 'res-lab')){
  const ids = ['res-lab'], {on, files} = compose(ids);
  ok(on.includes('res-lab') && on.includes('res-custom') && checks(ids).every(r => r.ok), 'RES-Lab includes and runs separate RES-CUSTOM consumer');
  const core = CAT.products.find(p => p.id === 'res-custom');
  ok(files.find(f => f.name === 'fpSup/' + core.file).sha256 === core.virtual.sha256 &&
     files.some(f => f.name === 'fpSup/UI/ALLSUPS.BIN') && files.some(f => f.name === 'fpSup/RESCUS/README.TXT'), 'RES-Lab includes virtual core, manager and SAVE directory');
  ok(!files.some(f => f.name.endsWith('.RCD')), 'RES-Lab alone does not fill the resolution list with fixed formats');
  ok(compose(['res-custom']).files.find(f => f.p).sha256 === core.sha256, 'RES-CUSTOM alone uses standalone core, without reserving a virtual row');
  DATA_OFF['res-custom'] = core.data_files.map(f => f.path);
  ok(checks(ids).every(r => r.ok), 'RES-Lab applies without any saved RCD file');
  delete DATA_OFF['res-custom'];
  for (const instant of [false,true]) for (const fast of [false,true]){
    BOOT.instant = instant; BOOT.fast = fast;
    const z = unzip(zipFor(ids)), root = cardName(ids) + '/';
    const pair = CAT.boot.variants[`m1i${+instant}f${+fast}`].files;
    ok(pair.every(f => z[root + f.path].equals(Buffer.from(f.data,'base64'))) &&
       sha(z[root + 'fpSup/' + core.file]) === core.virtual.sha256 &&
       checks(ids).every(r => r.ok), `RES-Lab Instant ${instant}, Fast ${fast}: manager pair and virtual consumer`);
  }
  Object.assign(BOOT, CAT.boot.default);
  const saved = core.virtual.data, bad = Buffer.from(saved,'base64');
  bad[bad.length-1] ^= 1; core.virtual.data = bad.toString('base64');
  ok(checks(ids).some(r => !r.ok), 'flipped virtual consumer byte blocks RES-Lab download');
  core.virtual.data = saved;
}
{
  BOOT.manager = true;
  const f = CAT.boot.manager_files[0], saved = f.data, bad = Buffer.from(saved,'base64');
  bad[bad.length-1] ^= 1; f.data = bad.toString('base64');
  ok(checks([]).some(r => !r.ok), 'flipped manager UI byte blocks download');
  f.data = saved;
}

// 2. everything at once: clashing ones parked in OFF, the rest run, checks pass
const all = CAT.products.map(p => p.id);
const pl = plan(all), {files} = compose(all);
const byFile = Object.fromEntries(CAT.products.map(p => [p.id, p.file]));
ok(pl.on.every(a => pl.on.every(b => a === b || !CAT.products.find(p => p.id === a).excl.includes(b))),
   'no two running sups clash');
ok(pl.off.every(id => files.some(f => f.off && f.p.id === id)), 'parked sups are on the card, off');
ok(checks(all).every(r => r.ok), `all ${all.length} ticked: checks pass (off: ${pl.off.join(',') || '-'})`);

// 3. a clashing pair (made up from the first two sups when the catalogue has
//    none): first ticked runs; the other is installed as .BIN with its sup_id on
//    LOADER.BIN's disabled list, so the camera's SupManager can switch them
//    (the user 2026-10-25).  The same sup_id: NAME.OFF instead.
{
  const [A, B] = CAT.products, saved = A.excl;
  if (!A.excl.includes(B.id)) A.excl = [...A.excl, B.id];
  ok(plan([A.id, B.id]).on.join() === A.id && plan([B.id, A.id]).on.join() === B.id,
     'first ticked of a clashing pair runs');
  const z = unzip(zipFor([A.id, B.id])), root = cardName([A.id, B.id]) + '/';
  ok(z[root + 'fpSup/' + A.file] && z[root + 'fpSup/' + B.file] && !z[root + 'fpSup/' + B.file.replace(/\.BIN$/, '.OFF')],
     `zip: ${A.file} and ${B.file} both .BIN`);
  const L = z[root + 'fpSup/LOADER.BIN'], o = L.length - 128;
  ok(L.readUInt32LE(o) === 0x53445346 && L.readUInt32LE(o + 4) === 1 && L.slice(o + 8, o + 12).toString() === B.sup_id
     && L.readUInt32LE(o + 12) === 0, `LOADER.BIN disabled list = [${B.sup_id}]`);
  ok(Object.keys(z).every(k => !k.includes('/OFF/')), 'no OFF folder');
  ok(/SupManager/.test(z[root + 'README.txt'].toString()), 'README says how to switch');
  ok(checks([A.id, B.id]).every(r => r.ok), 'a clash is not a failed check');
  const sid = B.sup_id;
  B.sup_id = A.sup_id;                                  // the same sup: the list cannot tell them apart
  const z2 = unzip(zipFor([A.id, B.id]));
  ok(z2[root + 'fpSup/' + B.file.replace(/\.BIN$/, '.OFF')] && !z2[root + 'fpSup/' + B.file], 'same sup_id: NAME.OFF');
  ok(checks([A.id, B.id]).every(r => r.ok), 'same sup_id clash checks pass');
  B.sup_id = sid;
  A.excl = saved;
}

// 4. a corrupted byte is caught by the self-check (mutation)
const p0 = CAT.products[0], keep = p0.data;
const bytes = Buffer.from(keep, 'base64'); bytes[bytes.length - 1] ^= 1; p0.data = bytes.toString('base64');
ok(checks([p0.id]).some(r => !r.ok), 'flipped bit in a sup fails the self-check');
p0.data = keep;

// 5. same selection -> same zip bytes
ok(sha(Buffer.from(zipFor(all))) === sha(Buffer.from(zipFor(all))), 'zip is reproducible');

// 5b. data files: all by default, untick one -> it leaves the card, untick all -> refused
for (const p of CAT.products.filter(p => (p.data_files || []).length)){
  const root = cardName([p.id]) + '/', n = p.data_files.length;
  const has = z => p.data_files.filter(d => z[root + d.path]).length;
  ok(has(unzip(zipFor([p.id]))) === n, `${p.id}: all ${n} data files by default`);
  DATA_OFF[p.id] = [p.data_files[0].path];
  const z = unzip(zipFor([p.id]));
  ok(has(z) === n - 1 && !z[root + p.data_files[0].path], `${p.id}: unticked ${p.data_files[0].label} is left out`);
  DATA_OFF[p.id] = p.data_files.map(d => d.path);
  ok(checks([p.id]).some(r => !r.ok), `${p.id}: no data file ticked is refused`);
  delete DATA_OFF[p.id];
}

// 6. the guide link, when there is one, points at a page that exists
for (const p of [...CAT.products, ...(CAT.pending || [])]){
  if (p.guide) ok(fs.existsSync(path.join(HERE, p.guide)), `${p.id} guide ${p.guide} exists`);
  else console.log(`todo ${p.id}: no guide page yet`);
}

// 6b. everyone thanked on a product's guide page is thanked on its tile
for (const p of [...CAT.products, ...(CAT.pending || [])]){
  if (!p.guide) continue;
  const g = fs.readFileSync(path.join(HERE, p.guide), 'utf8');
  // every "Thank you, ..." box on the page, not just the first
  const names = [...g.matchAll(/credit-h"><span class="en">Thank you, ([^<]+)</g)]
    .flatMap(m => m[1].split(/,\s*|\s+and\s+/)).map(x => x.trim()).filter(Boolean);
  if (!names.length) continue;
  ok(names.every(n => p.credits.some(c => c.startsWith(n))), `${p.id}: tile thanks ${names.join(', ')}`);
}

// 6c. the AutoRun speed-up is on every card, so its thanks is on the page
ok(CAT.shared.some(f => f.path === 'AutoRun.txt' && Buffer.from(f.data, 'base64').toString().startsWith('mem set 0xC04215F4 0xE320F000'))
   && /Andy_hal9000/.test(grab('ui')), 'AutoRun has the no-delay patch, page thanks Andy_hal9000');

// 6d. the zip keeps the loader's (file name) order whatever the page order is
{
  const {files} = compose(CAT.products.map(p => p.id).reverse());
  const sups = files.filter(f => f.p && !f.off).map(f => f.p.file);
  ok(sups.join() === [...sups].sort().join(), 'sups in the zip are in file-name order');
}

// 7. credits survive (author is empty for the site's own sups)
ok(CAT.products.every(p => Array.isArray(p.credits) && typeof p.author === 'string'), 'author/credits fields present');

// Independent products: choosing one must never silently install the other.
if (CAT.products.some(p => p.id === 'stopfx')){
  const stopfx = CAT.products.find(p => p.id === 'stopfx');
  ok(stopfx.author === 'Ruari', 'STOPFX credits its author Ruari');
  for (const ids of [['lossless'], ['stopfx'], ['fcap'], ['lossless', 'stopfx']]){
    const z = unzip(zipFor(ids)), root = cardName(ids) + '/';
    // FCAP is only ticked along with Lossless on the page (links), never forced
    const want = ids.map(id => CAT.products.find(p => p.id === id).file).sort();
    const actual = Object.keys(z).filter(n => /^fpSup\/[^/]+\.(BIN|OFF)$/.test(n.slice(root.length)) &&
                                              !/\/(LOADER|SUPMGR)\.BIN$/.test(n))
      .map(n => n.slice((root + 'fpSup/').length)).sort();
    ok(actual.join() === want.join() && plan(ids).off.length === 0 && checks(ids).every(r => r.ok),
       `${ids.join('+')}: ZIP has exactly the independently selected products`);
    if (ids.includes('stopfx')) ok(z[root + 'README.txt'].toString().includes('by Ruari'), 'ZIP README retains Ruari attribution');
  }
}

// 8. Sensor Lab (Bei 2026-11-07): QS-Share is shared plumbing, added with it and never a choice of its own;
//    Sensor Lab and RES-Custom claim the same hook sites, so they clash like OG3K / OG2K.
if (CAT.products.some(p => p.id === 'sensor-lab')){
  const byId = id => CAT.products.find(p => p.id === id);
  const sl = byId('sensor-lab'), qs = byId('qs-share'), rc = byId('res-custom');
  ok(qs && qs.infra && !sl.infra && qs.sup_id === 'QSCT' && sl.sup_id === 'SL41', 'QS-Share is infra (sup_id QSCT), Sensor Lab is not');
  ok(sl.name === 'Sensor Lab-IMX410' && sl.file === 'SensorLab-IMX410_v0.0.1test.BIN' && sl.version === '0.0.1test' &&
     qs.name === 'QS-Share' && qs.file === 'QS-Share_v0.0.1test.BIN' && qs.version === '0.0.1test', 'names_v4 names and versions');
  const hdrName = p => { const d = Buffer.from(p.data, 'base64'), o = d.readUInt32LE(44); return d.slice(o, d.indexOf(0, o)).toString(); };
  ok(hdrName(sl) === sl.name && hdrName(qs) === qs.name, 'header display names = page names (no font_menu_SB_kigou_09)');
  ok(sl.requires.includes('qs-share') && selected(['sensor-lab']).includes('qs-share'), 'Sensor Lab selects QS-Share');
  {
    const ids = ['sensor-lab'], {on, files} = compose(ids), z = unzip(zipFor(ids)), root = cardName(ids) + '/';
    ok(on.includes('sensor-lab') && on.includes('qs-share') && checks(ids).every(r => r.ok), 'Sensor Lab alone: both run, checks pass');
    ok(z[root + 'fpSup/' + qs.file] && sha(z[root + 'fpSup/' + qs.file]) === qs.sha256 &&
       z[root + 'fpSup/' + sl.file] && sha(z[root + 'fpSup/' + sl.file]) === sl.sha256, 'zip has QS-Share and Sensor Lab, exact bytes');
    ok(cardName(ids) === sl.release + '-IS', 'card name is Sensor Lab\'s release (QS-Share not a choice)');
    const r = z[root + 'README.txt'].toString();
    ok(r.includes('shared, included for Sensor Lab-IMX410') && r.includes('BEFORE YOU COPY') && r.includes('QSContainer_v*.BIN'),
       'README: QS-Share marked shared, the upgrade note (delete old SensorLab / QSContainer)');
    const L = z[root + 'fpSup/LOADER.BIN'];
    ok(L.readUInt32LE(L.length - 128) === 0x53445346 && L.readUInt32LE(L.length - 124) === 0, 'no clash: empty disabled list');
  }
  ok(!selected(['lossless']).includes('qs-share') && !compose(['lossless']).files.some(f => f.name.endsWith(qs.file)),
     'QS-Share is not added without Sensor Lab');
  ok(sl.excl.includes('res-custom') && rc.excl.includes('sensor-lab'), 'Sensor Lab <-> RES-Custom excl is symmetric');
  for (const [first, second] of [['sensor-lab', 'res-custom'], ['res-custom', 'sensor-lab']]){
    const ids = [first, second], pl = plan(ids), {files} = compose(ids);
    ok(pl.on.includes(first) && pl.off.join() === second && !(pl.on.includes('sensor-lab') && pl.on.includes('res-custom')),
       `${first} first: ${first} runs, ${second} is off`);
    const L = files.find(f => f.name === 'fpSup/LOADER.BIN');
    ok(L.disabled && L.disabled.join() === byId(second).sup_id && checks(ids).every(r => r.ok),
       `${first} first: LOADER.BIN disabled list = [${byId(second).sup_id}], checks pass`);
    ok(pl.on.includes('qs-share') && files.some(f => f.name === 'fpSup/' + qs.file && !f.off), `${first} first: QS-Share still on the card, running`);
  }
}

console.log(fails ? `${fails} FAILED` : 'all passed');
process.exit(fails ? 1 : 0);
