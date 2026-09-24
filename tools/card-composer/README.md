# fpSup-Merge

Select ordinary product cards and download `AutoRun.txt` plus `fpSup.BIN`.
Both files go in the SD card root. This is the merged-card composition path;
product builders still create individual cards and temporary test references.

Open `index.html` locally: it is self-contained and needs no server or packages.
GitHub's raw HTML view is source text, not the rendered tool; use the downloaded
file or the repository's published Pages site. `artifact.html` contains the same
catalogue and composition code for embedding.

## Browsing and selection

Sup tiles are grouped by category. The page opens on **Shooting**, not All;
Development is hidden and unselected by default. Open Development or All to
see Shell, then explicitly select it to include it. Changing categories only
filters the display: it does not select, deselect or remove a previously
selected sup from the merged output. OG3K and OG2K remain mutually exclusive.
Fast start stays a separate, off-by-default settings switch, not a sup tile.

When adding a sup, set its `category` string in `PRODUCTS` in
`build_catalogue.py` (`shooting` or `development` for the current products).
The page derives category buttons from the catalogue, including new category
names; missing metadata falls back to `uncategorized`.

## Current inputs and boot contract

`build_catalogue.py` selects the latest frozen directory for each product from
`releases/`; it never rebuilds or overwrites a frozen release. The 2026-09-24
refresh uses USB Shell 3.2.0, gyro 1.13, OG3K 0.2.5a and OG2K 0.1.2a.
OG3K and OG2K are mutually exclusive. New sup authors should first read
[SUP_BUILD_RULES.md](../../SUP_BUILD_RULES.md).

The loader, stage2 and optional Fast pieces come from the shared
`fp_usb_shell/build_autorun.py` and assembly templates. The sequence remains:

1. AutoRun invokes the loader; it reads the BIN into its staging buffer.
2. Loader publishes D-cache then I-cache before executing stage2.
3. Stage2 pass 1 places absolute-address sections, then publishes D/I.
4. It calls the payload entries: **worker → gyro → OG restore**, omitting
   absent products. Every entry must return.
5. Pass 2 places pool-offset sections, then publishes D/I. Loader returns
   and frees staging. Only Fast packaging adds provisioning and script abort.

Entry 0 means no entry; a nonzero entry below `0x40000000` is a **file offset**,
not a pool offset. An entry at or above that boundary is an absolute address.
Current OG cards have restore entry `0xC0731600`; they are not static-writes-only
cards. The merger relocates file entries and uses the existing `entries.S`
trampoline when several entries must run.

## What composition changes

The container is `VBIN`, section count, entry, body length, followed by `(dest,
length)` records and four-byte-aligned bodies. Only the **first** section is
replaced by the common stage2 during a merge. Other destination-zero sections
are run-in-place launchers and must survive; they do not imply USB Shell.

- A single ordinary card with unchanged options retains its frozen BIN bytes.
- A merge uses the current common stage2, deduplicates identical records and
  relocates entries. Payload code is retained, not rebuilt by the browser.
- Fast always replaces stage2 and adds the matching abort section.
- The built-in Shell's **EP 0x83** option controls the six exact descriptor
  records derived from `fp_usb_shell/patches.py` (`PUSH`). Off omits them; on
  retains the shipped set. The interface-class patch stays. Off is the page
  default, so a standalone Shell with this option off is intentionally
  repackaged, not byte-identical to its frozen release.
- Uploaded ordinary BINs retain their own patches. The page does not guess
  which destination-zero launcher is a shell, nor expose an EP option for them.

The named `plain`, `shell` and `shellpush` AutoRun template slots are retained
for compatibility, but their executable commands are now the same: worker
creation, state and descriptor patches reside in the BIN. Changing the EP
option does **not** add AutoRun commands. The current normal script has 104
commands; the Fast script has 169 in total, not 26.

BIN output retains 32 KiB padding when it fits. Larger output is padded to the
loader's `MAXLEN`, currently `0xF000` (61,440 bytes), and output exceeding that
read capacity is rejected. The browser, catalogue composer and common builder
use the same policy. The loader owns a separate staging allocation: its read
buffer is no longer a reserved region of the payload's shared pool.

## Fast start and replacing only the BIN

Fast is optional and off by default. It stores the loader in flash-backed
settings. On a matching loader marker it copies that loader, publishes D/I,
and loads the BIN normally; on a mismatch it takes the slow AutoRun path.
The marker is derived from **loader bytes**, not the BIN's hash, length,
version or entry. It is not a runtime integrity check of the stored body.

**A compatible payload update with the same loader and packaging needs only a
new BIN.** Keep the same banner to keep AutoRun byte-identical. A changed
loader, filename, Fast configuration or boot contract requires the matching
AutoRun and BIN to be updated together once. This refresh changes the loader,
so adopting it is such a one-time paired update—not a new per-BIN requirement.

Do not feed an already-Fast card back into the merger. Compose ordinary inputs,
then enable Fast on the final output so its bootstrap, loader, stage2 and abort
come from one build. This convention does not add runtime BIN validation.

## Build-time checks and their limits

The page checks overlapping writes, cave and pool bounds, loader read capacity,
entry placement/trampoline references and banner format before enabling
downloads. These are packaging checks, **not** proof that a payload's code is
safe or that a composed card has been tested on a camera. Uploaded code may do
more than its section destinations suggest. Do not infer whole-card hardware
validation from an individual product's earlier test results.

## Regenerating and testing

From the fpSup repository root:

```sh
python3 -B tools/card-composer/build_catalogue.py
python3 -B tools/card-composer/render.py --check
node tools/card-composer/test_compose.js
node tools/card-composer/test_catalog_ui.js
python3 -B fp_usb_shell/test_boot_chain.py
```

The catalogue generator requires the existing ARM toolchain. It verifies all
four frozen payload round-trips, then creates temporary source references from
the current gyro builder and frozen OG sections, preserving the OG entry.
Plain gyro+OG references must match byte for byte. Shell+gyro+OG references
use the same EP configuration and compare every section's bytes and ordered
entry targets: the shell bootstrap's position differs between the direct
builder and browser layout, so file offsets alone cannot be byte-identical.
The checker validates the known trampoline's code, table and terminator before
normalizing only those layout offsets. There are no tolerated `STALE` results.

`test_compose.js` executes the **actual generated page's composition block**,
not a copied merger. It covers all 11 legal nonempty selections, normal/Fast,
Shell EP off/on, entry relocation and order, frozen standalone bytes, embedded
loader cache calls, Fast stack alignment, payload-independent AutoRun, and
32 KiB/read-capacity boundaries. No browser, npm packages or camera is required.

`test_catalog_ui.js` runs the generated page's scripts and event handlers with
a small offline DOM stub. It checks category defaults, selection across filters,
OG exclusivity, upload/removal and the independent Fast switch. This tests UI
behaviour, not browser layout or on-camera operation.

`render.py` without `--check` is only for presentation edits: it reuses the
already embedded catalogue. To refresh releases or boot templates, run
`build_catalogue.py`; rendering alone cannot update those bytes.

Building locally does not publish the website, authorize writing a card, or
confirm camera operation. Development results belong in the existing shared
`projects/usb-shell-sup/notes/CARD_BUILD_PIPELINE.md` in the full research tree,
not in a second release diary.

## Using the same merger from a script

The `cat` and `compose` script blocks in `index.html` contain the inputs and
DOM-free implementation. For example, in Node:

```js
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('tools/card-composer/index.html', 'utf8');
const block = id => html.match(new RegExp(
  '<script id="' + id + '"[^>]*>([\\s\\S]*?)<\\/script>'))[1];
const ctx = vm.createContext({
  CAT: JSON.parse(block('cat')),
  atob: s => Buffer.from(s, 'base64').toString('binary'),
  btoa: s => Buffer.from(s, 'binary').toString('base64')
});
vm.runInContext(block('compose') + `
  on.clear(); on.add('gyro'); on.add('og3k'); // also: shell or og2k
  fastOn = false; pushOn = false;
  const banner = 'fpSup-Merged!';
  const c = composed(), bin = composeVshl(c.recs, c.entry);
  const failed = runChecks(c.recs, bin, banner, c.entry, c.entries)
    .filter(x => !x.ok);
  if (failed.length) throw new Error(failed.map(x => x.t + ': ' + x.d).join('; '));
  globalThis.result = {bin: bin.bytes, auto: composeAutorun(banner)};
`, ctx);
fs.writeFileSync('fpSup.BIN', Buffer.from(ctx.result.bin));
fs.writeFileSync('AutoRun.txt', ctx.result.auto);
```

Run this in a fresh output directory, adjusting the HTML path accordingly;
do not overwrite a release or mounted card as a side effect of testing.
