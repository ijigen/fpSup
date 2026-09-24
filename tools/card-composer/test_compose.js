#!/usr/bin/env node
'use strict';
// Offline checks of the exact code shipped in the page, without a browser,
// camera, network, or npm dependencies. Generate the page before running this.
//   node tools/card-composer/test_compose.js [path/to/index.html]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const page = path.resolve(process.argv[2] || path.join(__dirname, 'index.html'));
const html = fs.readFileSync(page, 'utf8');
const block = id => {
  const hit = html.match(new RegExp('<script id="' + id + '"[^>]*>([\\s\\S]*?)<\\/script>'));
  assert(hit, 'missing ' + id + ' block');
  return hit[1];
};
const CAT = JSON.parse(block('cat'));
const ctx = vm.createContext({CAT,
  atob: s => Buffer.from(s, 'base64').toString('binary'),
  btoa: s => Buffer.from(s, 'binary').toString('base64')});
vm.runInContext(block('compose') + `
  globalThis.api = {composed, composeVshl, composeAutorun, runChecks, templateName,
    select(ids, fast, push) {
      on.clear(); ids.forEach(id => on.add(id)); fastOn = fast; pushOn = push;
    }};`, ctx, {filename: page + '#compose'});
const api = ctx.api;
const decode = r => Buffer.from(r.b, 'base64');
const byId = new Map(CAT.cards.map(c => [c.id, c]));

// Parse output independently: assertions inspect actual table/data bytes, not
// the composer-provided entry list or its offsetsOf implementation.
function parse(bytes) {
  const b = Buffer.from(bytes);
  assert.equal(b.toString('ascii', 0, 4), 'VBIN');
  const count = b.readUInt32LE(4), entry = b.readUInt32LE(8);
  const records = [];
  let off = 16 + 8 * count;
  for (let i = 0; i < count; i++) {
    const a = b.readUInt32LE(16 + 8 * i), n = b.readUInt32LE(20 + 8 * i);
    assert(off + n <= b.length, 'section exceeds output file');
    records.push({a, off, bytes: b.subarray(off, off + n)});
    off += (n + 3) & ~3;
  }
  assert.equal(off - (16 + 8 * count), b.readUInt32LE(12));
  assert(b.subarray(off).every(v => v === 0), 'nonzero file padding');
  return {records, entry, used: off};
}

function sourceEntry(card, output) {
  const entry = card.entry >>> 0;
  if (entry >= 0x40000000 || entry === 0) return entry;
  let off = 16 + 8 * card.records.length;
  for (const r of card.records) {
    const b = decode(r);
    if (off <= entry && entry < off + b.length) {
      const relocated = output.records.filter(s => s.a === (r.a >>> 0) && s.bytes.equals(b));
      assert.equal(relocated.length, 1, card.id + ' entry body must survive exactly once');
      return relocated[0].off + entry - off;
    }
    off += (b.length + 3) & ~3;
  }
  assert.fail(card.id + ' source entry is outside its records');
}

// Do not copy patch addresses into this test: use the maintained source list.
const patchSource = fs.readFileSync(path.join(root, 'fp_usb_shell/patches.py'), 'utf8');
const pushSource = patchSource.match(/^PUSH = \[([\s\S]*?)^\]/m);
assert(pushSource, 'cannot read PUSH definitions');
const pushWords = [...pushSource[1].matchAll(/\((0x[\dA-Fa-f]+),\s*(0x[\dA-Fa-f]+)/g)]
  .map(m => [Number(m[1]), Number(m[2])]);
assert(pushWords.length > 0, 'empty PUSH definitions');

function checkEntries(cards, out) {
  // Required product order is worker -> gyro -> OG restore, regardless of the
  // order checkboxes were clicked. Do not derive this expectation from sel().
  const ordered = ['shell', 'gyro', 'og3k', 'og2k'].filter(id => cards.some(c => c.id === id));
  const expected = ordered.map(id => sourceEntry(byId.get(id), out)).filter(Boolean);
  if (expected.length < 2) {
    assert.equal(out.entry, expected[0] || 0);
    return;
  }
  const trampoline = out.records.at(-1), stub = Buffer.from(CAT.trampoline.b, 'base64');
  assert.equal(trampoline.a, 0);
  assert.equal(out.entry, trampoline.off, 'header must call the entry trampoline');
  assert(trampoline.bytes.subarray(0, CAT.trampoline.tbl).equals(stub.subarray(0, CAT.trampoline.tbl)),
    'entry trampoline code differs from the assembled template');
  assert.equal(trampoline.bytes.readUInt32LE(CAT.trampoline.tbl), trampoline.off + CAT.trampoline.tbl);
  const actual = expected.map((_, i) => trampoline.bytes.readUInt32LE(CAT.trampoline.tbl + 4 + 4 * i));
  assert.deepEqual(actual, expected, 'entry order or relocation is wrong');
  assert.equal(trampoline.bytes.readUInt32LE(CAT.trampoline.tbl + 4 + 4 * expected.length), 0);
}

function frozen(card) {
  const version = card.name.match(/ v(.+)$/);
  assert(version, card.name + ': missing release version');
  const product = card.id === 'shell' ? 'usbshell' : card.id;
  const dir = path.join(root, 'releases', 'fpsup-' + product + '-v' + version[1]);
  const file = ['fpSup.BIN', 'VSHL.BIN'].map(n => path.join(dir, n)).find(fs.existsSync);
  assert(file, 'missing frozen release ' + dir);
  return fs.readFileSync(file);
}

let selections = 0, cases = 0, frozenChecks = 0;
const autoByMode = new Map();
for (let mask = 1; mask < 2 ** CAT.cards.length; mask++) {
  const cards = CAT.cards.filter((_, i) => mask & (1 << i));
  const ids = cards.map(c => c.id);
  if (cards.some(c => (c.excl || []).some(id => ids.includes(id)))) continue;
  selections++;
  for (const fast of [false, true]) {
    for (const push of (ids.includes('shell') ? [false, true] : [false])) {
      const label = ids.join('+') + (fast ? ' Fast' : ' normal') + (push ? ' push' : '');
      try {
        // Reverse checkbox order intentionally: catalogue order must win.
        api.select(ids.slice().reverse(), fast, push);
        assert.equal(api.templateName(), !ids.includes('shell') ? 'plain' : push ? 'shellpush' : 'shell');
        const composed = api.composed();
        const built = api.composeVshl(composed.recs, composed.entry);
        const auto = api.composeAutorun('fpSup-Test!');
        const bad = api.runChecks(composed.recs, built, 'fpSup-Test!', composed.entry, composed.entries)
          .filter(c => !c.ok).map(c => c.t + ': ' + c.d);
        assert.equal(bad.length, 0, bad.join('\n'));
        assert.equal(auto.length, CAT.pad_to);
        assert(auto.endsWith('\n'));
        const mode = `${fast}/${api.templateName()}`;
        if (autoByMode.has(mode)) assert.equal(auto, autoByMode.get(mode), 'payload selection changed AutoRun');
        else autoByMode.set(mode, auto);
        const out = parse(built.bytes);
        assert.equal(out.used, built.used);
        assert.equal(out.records[0].a, 0, 'first section must be stage2');
        if (fast || cards.length > 1)
          assert(out.records[0].bytes.equals(decode(fast ? CAT.fast.stage2 : CAT.stage2)));
        const aborts = out.records.filter(r => r.a === (CAT.fast.abort.a >>> 0));
        assert.equal(aborts.length, fast ? 1 : 0);
        if (fast) assert(aborts[0].bytes.equals(decode(CAT.fast.abort)));
        checkEntries(cards, out);
        for (const [address, value] of pushWords) {
          const records = out.records.filter(r => r.a === address);
          assert.equal(records.length, push ? 1 : 0, 'EP 0x83 option did not change BIN at ' + address.toString(16));
          if (push) assert.equal(records[0].bytes.readUInt32LE(), value);
        }
        // Push-off deliberately transforms a shell release that shipped with
        // push. In its shipped configuration every normal single BIN is exact.
        if (!fast && cards.length === 1 && (!cards[0].shell || push === (cards[0].template === 'shellpush'))) {
          assert(Buffer.from(built.bytes).equals(frozen(cards[0])), 'single normal BIN differs from frozen release');
          frozenChecks++;
        }
        cases++;
      } catch (error) {
        throw new Error(label + ': ' + error.message, {cause: error});
      }
    }
  }
}
assert.equal(frozenChecks, CAT.cards.length, 'not every frozen release was checked');

// Crossing the usual USB-write padding is legal; crossing the loader's read
// capacity must be a visible failed check, not an exception that blanks the UI.
api.select(['gyro'], false, false);
for (const need of [CAT.pad_to, CAT.pad_to + 4, CAT.read_cap, CAT.read_cap + 4]) {
  const helperSize = (decode(CAT.stage2).length + 3) & ~3;
  const records = [CAT.stage2, {a: 0xC1000000, k: 'sec', l: 'padding boundary test',
    b: Buffer.alloc(need - 32 - helperSize).toString('base64')}];
  const built = api.composeVshl(records, 0);
  assert.equal(built.used, need);
  assert.equal(built.bytes.length, Math.max(need, need <= CAT.pad_to ? CAT.pad_to : CAT.read_cap));
  const failures = api.runChecks(records, built, 'fpSup-Test!', 0, []).filter(c => !c.ok);
  assert.equal(failures.length, need > CAT.read_cap ? 1 : 0);
  if (need > CAT.read_cap)
    assert.equal(failures[0].t, 'The loader can read the whole card');
}

// Verify the embedded AutoRun machine code, not merely the current .S file:
// an unregenerated page must fail even if the source templates are fixed.
const LOADER = 0xC072DE64, STORE = 0xC072F700;
function writes(text) {
  return new Map([...text.matchAll(/^mem set (0x[\dA-Fa-f]+) (0x[\dA-Fa-f]+)/gm)]
    .map(m => [Number(m[1]), Number(m[2])]));
}
function contiguousWords(map, base) {
  const out = [];
  for (let at = base; map.has(at); at += 4) out.push(map.get(at));
  return out;
}
function branchTarget(word, at) {
  const delta = (word << 8) >> 8;
  return (at + 8 + 4 * delta) >>> 0;
}
for (const [mode, auto] of autoByMode) {
  const map = writes(auto), loader = contiguousWords(map, LOADER);
  const calls = loader.map((word, i) => (word >>> 24) === 0xEB
    ? {i, target: branchTarget(word, LOADER + 4 * i)} : null).filter(Boolean);
  const d = calls.filter(c => c.target === 0xC000E91C), ic = calls.filter(c => c.target === 0xC000EABC);
  assert.equal(d.length, 1, mode + ': missing loader D-cache call');
  assert.equal(ic.length, 1, mode + ': missing loader I-cache call');
  assert.equal(ic[0].i, d[0].i + 1, mode + ': D/I order');
  assert.equal(loader[d[0].i + 6], 0xE12FFF31, mode + ': stage2 must execute after publication');
  if (mode.startsWith('true/')) {
    const bootstrap = contiguousWords(map, STORE);
    assert.equal(bootstrap[0], 0xE92D41F0, 'Fast saves six registers (8-byte SP alignment)');
    assert.equal(bootstrap[17], 0xE8BD41F0, 'Fast hit restores saved registers and LR');
    assert.equal(bootstrap[20], 0xE8BD81F0, 'Fast miss returns with the matching stack');
  }
}
console.log(`PASS ${selections} legal selections / ${cases} normal-Fast-push cases; ` +
  `${frozenChecks} frozen single BINs; entry relocation/order, payload-independent AutoRun, ` +
  `4 padding/read-cap boundaries, embedded D/I and Fast stack.`);
