#!/usr/bin/env node
'use strict';
// Execute the page's real scripts and event handlers with a small host-side DOM.
// This checks behaviour, not layout or a browser's rendering/accessibility tree.
// node test_catalog_ui.js [index.html]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const page = path.resolve(process.argv[2] || path.join(__dirname, 'index.html'));
const html = fs.readFileSync(page, 'utf8');

class Element {
  constructor(tag, attrs = {}, parent = null) {
    this.tagName = tag.toUpperCase(); this.attrs = attrs; this.parentElement = parent;
    this.children = []; this.dataset = {};
    for (const [key, value] of Object.entries(attrs))
      if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
    this.value = attrs.value || ''; this.checked = 'checked' in attrs;
    this.disabled = 'disabled' in attrs; this.hidden = 'hidden' in attrs;
    this.className = attrs.class || ''; this.textContent = ''; this._html = '';
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      toggle: (name, force) => {
        const classes = new Set(this.className.split(/\s+/).filter(Boolean));
        const on = force === undefined ? !classes.has(name) : !!force;
        if (on) classes.add(name); else classes.delete(name);
        this.className = [...classes].join(' '); return on;
      },
      add: name => this.classList.toggle(name, true),
      remove: name => this.classList.toggle(name, false),
    };
  }
  set innerHTML(value) { this._html = value; this.children = parseTags(value, this); }
  get innerHTML() { return this._html; }
  getAttribute(name) { return name === 'class' ? this.className : this.attrs[name] ?? null; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  insertAdjacentHTML(where, value) { assert.equal(where, 'beforeend'); this.innerHTML += value; }
  addEventListener(name, handler) { this['on' + name] = handler; }
  querySelectorAll(selector) { return descendants(this).filter(node => matches(node, selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) {
    for (let node = this; node; node = node.parentElement) if (matches(node, selector)) return node;
    return null;
  }
  focus() { document.activeElement = this; }
  click() { this.onclick?.(event(this)); }
}
const voidTags = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);
function parseTags(markup, parent) {
  const top = [], stack = [parent];
  for (const hit of markup.matchAll(/<(\/?)([a-z][a-z0-9-]*)\b([^>]*)>/gi)) {
    const tag = hit[2].toLowerCase();
    if (hit[1]) {
      const at = stack.findLastIndex(node => node.tagName.toLowerCase() === tag);
      if (at > 0) stack.length = at;
      continue;
    }
    const attrs = {};
    for (const a of hit[3].matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g))
      attrs[a[1]] = a[2] ?? a[3] ?? a[4] ?? '';
    const owner = stack.at(-1), node = new Element(tag, attrs, owner);
    if (owner === parent) top.push(node); else owner.children.push(node);
    if (!voidTags.has(tag) && !hit[3].trimEnd().endsWith('/')) stack.push(node);
  }
  return top;
}
function descendants(node) { return node.children.flatMap(child => [child, ...descendants(child)]); }
function matches(node, selector) {
  if (selector.startsWith('#')) return node.attrs.id === selector.slice(1);
  if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
  const hit = selector.match(/^(?:([a-z]+))?\[([\w-]+)(?:=["']?([^\]"']+)["']?)?\]$/i);
  assert(hit, 'DOM stub needs explicit support for selector: ' + selector);
  return (!hit[1] || node.tagName.toLowerCase() === hit[1]) && hit[2] in node.attrs &&
    (hit[3] === undefined || node.attrs[hit[2]] === hit[3]);
}
function event(target) { return {target, preventDefault() {}, stopPropagation() {}}; }
const dom = new Element('document');
dom.innerHTML = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
  .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '').replace(/<!--[\s\S]*?-->/g, '');
const catText = html.match(/<script id="cat"[^>]*>([\s\S]*?)<\/script>/)[1];
const catNode = new Element('script', {id: 'cat'}, dom); catNode.textContent = catText;
dom.children.push(catNode);
const body = descendants(dom).find(node => node.tagName === 'BODY') || dom;
const document = {
  body, activeElement: body,
  getElementById: id => descendants(dom).find(node => node.attrs.id === id) || null,
  querySelectorAll: selector => dom.querySelectorAll(selector),
};
class FileReader {
  readAsArrayBuffer(file) {
    this.result = file.bytes.buffer.slice(file.bytes.byteOffset, file.bytes.byteOffset + file.bytes.byteLength);
    this.onload();
  }
}
const ctx = vm.createContext({document, FileReader, TextEncoder, crypto: webcrypto,
  location: {protocol: 'file:'}, localStorage: {getItem() { return null; }, setItem() {}},
  atob: s => Buffer.from(s, 'base64').toString('binary'),
  btoa: s => Buffer.from(s, 'binary').toString('base64'), console});
for (const hit of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/gi)) {
  if (/type=["']application\/json["']/.test(hit[1])) continue;
  vm.runInContext(hit[2], ctx, {filename: page + hit[1]});
}
vm.runInContext(`globalThis.testUI = {
  selected: () => [...on], category: () => activeCategory, fast: () => fastOn,
  bytes: () => current.vshl.bytes, autorun: () => current.autorun,
  cards: CAT.cards, refresh: render, catalogue: renderCatalogue,
  uploadBytes: () => composeVshl([CAT.stage2,
    {a: 0xC1000000, b: btoa('TEST'), k: 'sec', l: 'UI test'}], 0).bytes,
};`, ctx);
const api = ctx.testUI;
const by = (attr, value) => document.querySelectorAll('[' + attr + ']')
  .find(node => node.getAttribute(attr) === value);
const ids = attr => document.querySelectorAll('[' + attr + ']').map(node => node.getAttribute(attr));
const selection = () => [...api.selected()].sort();
const bytes = () => Buffer.from(api.bytes());
function click(attr, value) {
  const node = by(attr, value); assert(node, `missing ${attr}=${value}`);
  assert.equal(typeof node.onclick, 'function'); node.onclick(event(node));
}
function toggle(id, checked) {
  const node = by('data-c', id); assert(node, 'missing product checkbox ' + id);
  node.checked = checked; node.onchange(event(node));
}
function choose(category) { click('data-category', category); }
function chips() { return ids('data-unselect').sort(); }
function assertCategoryOnly(category, expected) {
  const before = {selected: selection(), bin: bytes(), auto: api.autorun(), fast: api.fast()};
  choose(category);
  assert.equal(document.activeElement, by('data-category', category), 'filter button lost keyboard focus');
  assert.deepEqual(ids('data-c').sort(), expected.slice().sort());
  assert.deepEqual(selection(), before.selected);
  assert.deepEqual(bytes(), before.bin, 'filtering changed BIN');
  assert.equal(api.autorun(), before.auto, 'filtering changed AutoRun');
  assert.equal(api.fast(), before.fast, 'filtering changed Fast start');
  assert.equal(document.getElementById('fast').checked, before.fast);
  assert.deepEqual(chips(), selection(), 'selected chips must cross category boundaries');
}

assert.equal(api.cards.length, 4);
assert.deepEqual(selection(), ['gyro', 'og3k']);
assert.equal(api.category(), 'shooting', 'development must not be the initial category');
assert.deepEqual(ids('data-c').sort(), ['gyro', 'og2k', 'og3k']);
assert.deepEqual(ids('data-category').sort(), ['all', 'development', 'shooting']);
for (const node of document.querySelectorAll('[data-c]')) assert(node.closest('.sup-card'), 'product is not a tile');
const fast = document.getElementById('fast');
assert(fast && fast.getAttribute('role') === 'switch', 'Fast start must remain a switch');
assert(!fast.closest('.sup-card') && !fast.closest('.mod'), 'Fast start must not be a product card');
assert.equal(api.fast(), false);
assertCategoryOnly('all', ['shell', 'gyro', 'og3k', 'og2k']);
assertCategoryOnly('development', ['shell']);
assertCategoryOnly('shooting', ['gyro', 'og3k', 'og2k']);

const normalFiles = {bin: bytes(), auto: api.autorun()};
let fastToggle = document.getElementById('fast');
fastToggle.checked = true; fastToggle.onchange(event(fastToggle));
assert.equal(api.fast(), true);
assert.notDeepEqual(bytes(), normalFiles.bin, 'Fast switch did not repackage BIN');
assert.notEqual(api.autorun(), normalFiles.auto, 'Fast switch did not select Fast AutoRun');
assertCategoryOnly('development', ['shell']);
assertCategoryOnly('shooting', ['gyro', 'og3k', 'og2k']);
fastToggle = document.getElementById('fast');
fastToggle.checked = false; fastToggle.onchange(event(fastToggle));
assert.equal(api.fast(), false);
assert.deepEqual(bytes(), normalFiles.bin, 'switching Fast off did not restore normal BIN');
assert.equal(api.autorun(), normalFiles.auto, 'switching Fast off did not restore normal AutoRun');

// Selection is independent of the visible category; chips can deselect a
// hidden product, and OG choices still own the same exclusive menu slot.
choose('development'); click('data-unselect', 'gyro');
assert.deepEqual(selection(), ['og3k']);
choose('shooting'); toggle('gyro', true); toggle('og2k', true);
assert.deepEqual(selection(), ['gyro', 'og2k']);
toggle('og3k', true); assert.deepEqual(selection(), ['gyro', 'og3k']);
choose('development'); toggle('shell', true);
assert.deepEqual(selection(), ['gyro', 'og3k', 'shell']);
const pushOff = bytes(), auto = api.autorun();
const push = document.getElementById('push'); assert(push && typeof push.onchange === 'function');
push.checked = true; push.onchange(event(push));
assert.notDeepEqual(bytes(), pushOff, 'push checkbox no longer changes descriptor sections');
assert.equal(api.autorun(), auto, 'push must not change AutoRun');
assertCategoryOnly('shooting', ['gyro', 'og3k', 'og2k']);
click('data-unselect', 'shell'); assert.deepEqual(selection(), ['gyro', 'og3k']);

// Classification comes from metadata, not a hardcoded list of product IDs.
const gyro = api.cards.find(card => card.id === 'gyro'), oldCategory = gyro.category;
const beforeMetadata = {bin: bytes(), auto: api.autorun(), selected: selection()};
gyro.category = 'future-category'; api.catalogue();
assert(ids('data-category').includes('future-category'));
assertCategoryOnly('future-category', ['gyro']);
assert.deepEqual(bytes(), beforeMetadata.bin);
assert.equal(api.autorun(), beforeMetadata.auto);
assert.deepEqual(selection(), beforeMetadata.selected);
gyro.category = oldCategory; api.catalogue(); choose('shooting');

// Feed the real file-input handler, parser and upload renderer. Removing the
// final upload must leave a useful empty state or move to an available filter.
const upload = {name: 'ui-test.BIN', bytes: Buffer.from(api.uploadBytes())};
const input = document.getElementById('file');
input.files = [upload]; input.onchange(event(input));
const uploaded = selection().find(id => id.startsWith('up'));
assert(uploaded, 'upload was not selected');
assert(ids('data-category').includes('uploaded'));
assertCategoryOnly('uploaded', [uploaded]);
click('data-rm', uploaded);
assert(!selection().includes(uploaded));
assert(!ids('data-c').includes(uploaded));
assert(!ids('data-category').includes('uploaded'), 'empty uploaded category should disappear');
assert(ids('data-c').length || document.getElementById('cards').innerHTML.trim(), 'empty category has no explanation');
assert.deepEqual(selection(), ['gyro', 'og3k']);

console.log('PASS catalogue UI: shooting default, four tiles, category filters preserve files, cross-category chips, ' +
  'OG exclusivity, push, Fast on/off and filter persistence, metadata-derived categories, upload and removal.');
