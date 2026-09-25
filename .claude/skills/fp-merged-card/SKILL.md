---
name: fp-merged-card
description: Building a SIGMA fp card to test with — one product or several (open gate, the gyro logger, the USB shell), with or without Fast Start 2, where a power-switch restart loads through the loader hook without the AutoRun and a cold start runs the short AutoRun from the settings block — and getting it onto the camera and reading back which boot path it took. Use when a change needs verifying on the camera, when a card should boot fast or instantly, when a page-composed card has to be reproduced offline, or when a test result has to be attached to specific bytes. Covers what a script-built card shares with the ones fpSup-Merge hands out, and where they differ.
---

# A card to test with

Build any combination here, Fast Start 2 included. The cards people download
come from `fpSup/tools/card-composer/index.html`; that is about distribution and
the checks the page runs, not about what a script is allowed to make (2026-09-20,
the user's call).

What the older rule protected against is still real: `build_og3k_gyro.py`
emitted wrong merged cards for weeks — the card said gyro, the payload was not
the shipped gyro, nothing failed, and only a section-by-section comparison
showed it. The defence is the composer's own verification, which rebuilds five
combinations from the shipped artifacts and refuses to write the page if one
does not reproduce. **Run it after changing a card**, whatever built the card.

## What every card does now (2026-09-25)

- **Power-off write-back, always.** stage2 journals every firmware word it
  overwrites and a power-off callback writes them back; the camera powers off
  stock. gyro relies on it (its own `poff_disarm` is gone), so a gyro card built
  on an older loader must not be combined with this gyro.
- **The loader hook, opt-in (`--loader-hook`).** `0xC03DA420` points at the
  loader's `+4` entry: a power-switch restart loads ~1.4 s after power-on with no
  AutoRun. Single-product releases do not carry it; the merge page's
  **Fast Start 2** does, together with the settings-block fast path and the
  four-box splash.

Design, camera results, the open case: `projects/usb-shell-sup/notes/LOADER_V2.md`.

## Build one

```sh
# gyro + shell (the gyro card's own debug edition)
python3 fpSup/gyro/build_base_card.py --edition gcsv --debug \
        --version dev --banner 'fpSup-DEV!' --out DIR [--loader-hook]

# open gate + gyro + shell
python3 projects/open-gate/build/build_og3k_gyro.py --dev-card --out DIR
OG_TARGET=og2k python3 projects/open-gate/build/build_og3k_gyro.py --dev-card --out DIR

# a released product's tested sections, byte for byte, on the current loader
python3 projects/usb-shell-sup/cards/warm-boot-2026-09-25/repack_release.py \
        fpSup/releases/fpsup-og3k-v0.2.6a DIR -- [build_autorun flags]
```

`--out` is required; a merged card must not sit in the tree as a product. Put
test cards under `projects/usb-shell-sup/cards/<topic>/`, **not on the
Desktop** (the user's rule).

`build_og3k_gyro.py` could not build from og3k v0.2.5a until 2026-09-25 (its UI
word count missed the 12-word `ui_layout` state); fixed, and
`test_boot_entry_chain.py` passes. `--dev-card` produces the bytes `--reference`
does and prints how it differs from the page's card.

`repack_release.py` is what the og3k v0.2.6a / og2k v0.1.3a releases were made
with: every section except destination 0, from the release, on the current
loader and stage2, then a check that all of them arrived unchanged.

## Fast Start 2

```sh
python3 projects/open-gate/build/build_og3k_gyro.py --dev-card --fast \
        --loader-hook --four-box-bar [--loader-hook-mark 0xC072E040] --out DIR
# gyro only: build_base_card.py ... --store-boot --loader-hook --four-box-bar
# DIR/FPSUPUI/ goes on the card beside the two files
```

Three ways the card starts:

| path | when | what you see | `LOAD_DONE_US` (`0xC072F6F8`) |
|---|---|---|---|
| instant | power-switch restart, USB unplugged, image kept | no progress; four-box appears ~3 s, holds 2 s, UI back | ~1.3–1.5 s |
| fast | image reloaded: cold start, battery, **USB attached at power-off**, and some unplugged restarts anyway | the boxes fill one by one, short | ~11–12 s |
| slow | first boot, or the stored loader's fingerprint does not match | long progress | ~15–16 s |

With the four-box display both AutoRun paths show boxes too: tell instant from
fast by whether the boxes **fill one by one** (fast) or appear finished (instant).

**One build owns all the pieces, and that is physics rather than policy.**
`store_boot`, the stage2 that writes the loader to flash, the abort, the magic
(sha256 of the loader the same AutoRun spells out) and the loader-hook entry
word stage2 checks all come out of one `--store-boot --loader-hook` run. Mixed
from two builds they disagree at boot, with no shell to recover with. stage2
also refuses to arm the hook if the loader's `+4` is not the entry it expects.

Fast Start 2 is dev-card or page packaging only. A single-product release must
not carry it: it writes the settings block, which survives a battery pull and
outlives deleting `AutoRun.txt`. `release_card.py` refuses a card with the abort.

Booted 2026-09-25 on shell, og3k+shell, gyro+og3k+shell script cards and on a
page-composed shell+gyro+og3k card: all three paths seen; the journal read back
after a warm boot matched the stock image word for word. Unplugged restarts fell
back to fast 10–30% of the time on one afternoon and far more on another —
not understood (the IPL decides whether the image is kept).

## Compose the page's card offline

The page's compose code runs in node; no browser, same bytes the user gets:

```js
// node, from fpSup/tools/card-composer, after build_catalogue.py
const fs=require('fs'), vm=require('vm');
const html=fs.readFileSync('index.html','utf8');
const block=id=>html.match(new RegExp('<script id="'+id+'"[^>]*>([\\s\\S]*?)<\\/script>'))[1];
const CAT=JSON.parse(block('cat'));
const ctx=vm.createContext({CAT, atob:s=>Buffer.from(s,'base64').toString('binary'),
                            btoa:s=>Buffer.from(s,'binary').toString('base64')});
vm.runInContext(block('compose')+`globalThis.api={composed,composeVshl,composeAutorun,runChecks,
  select(ids,fast,push){on.clear();ids.forEach(i=>on.add(i));fastOn=fast;pushOn=push;}};`, ctx);
const api=ctx.api; api.select(['shell','gyro','og3k'], true /* Fast Start 2 */, false);
const c=api.composed(), v=api.composeVshl(c.recs,c.entry), ar=api.composeAutorun('fpSup-X!');
// checks: api.runChecks(c.recs, v, 'fpSup-X!', c.entry, c.entries).every(x=>x.ok)
// write ar, v.bytes, and CAT.fast.ui[] as FPSUPUI/<n>
```

## How it differs from what a user downloads

Measured 2026-09-20 (og3k+gyro+shell), still the shape today:

| | |
|---|---|
| `AutoRun.txt` | byte for byte identical |
| `fpSup.BIN` | the page's carries six more sections |
| shared sections | every one identical |
| only on the page's | six EP 0x83 push patches, four bytes each |
| the trampoline | on both; its table words differ because offsets do |
| order | different |

**A script-built card is the page's minus the push endpoint, rearranged.** What
holds on a script-built card holds on the page's; not the reverse. The order
differs because `build_autorun.py` appends the worker *before* `--also-bin` and a
`--boot-bin` payload *after* it, and a merge walks cards in catalogue order.

## Putting it on the camera

The camera has to be running a card with the USB shell (`fpshd` up, `fpsh ping`
answers). Then **hot-update, never the Desktop**:

```sh
cd fpSup/fp_usb_shell
python3 -B putfile.py DIR/fpSup.BIN '\fpSup.BIN'          # BIN first
python3 -B putfile.py DIR/AutoRun.txt '\AutoRun.txt'
python3 -B putfile.py DIR/FPSUPUI/0.BIN '\FPSUPUI\0.BIN'   # ...4.BIN
python3 -B getfile.py '\fpSup.BIN' OUT --size 61440        # read back, compare sha
```

- **Read everything back.** A write is not a write until the bytes compare.
- **`getfile` needs `--size` for a file in a subfolder**: it looks names up in
  the root listing only, so `\FPSUPUI\n.BIN` reads as "not in dir" when it is
  there. `putfile` prints the same false warning.
- **`putfile` does not truncate.** A shorter file leaves the old tail; the
  builders pad with comment lines, so a leftover `###` line is harmless.
  Compare the first N bytes, where N is the new file's length.
- The `FPSUPUI` folder has to exist; `putfile` does not create folders.
- The next boot after a hot update runs the **old** loader hook (if one is
  armed) on the **new** BIN — expected; judge from the boot after that.

To see the instant path, power off with the **USB cable unplugged**; plug in
only after the boot to read. Read the state with
`python3 -B loader_hook_check.py` (a `--loader-hook-mark` card): hook armed or
stock, journal entries against the stock image, power-off runs since the image
was last reloaded, and `LOAD_DONE_US` above. `runs` survives only a warm restart,
so a fast boot with `runs=0` means the image was reloaded **or** the power-off
never ran — not proof on its own; a canary word written from the shell is.

**Recovery card:** only an `AutoRun.txt` that writes `mem set 0xC03DA420
0xEB0000CC`, and **no `fpSup.BIN`** — with a BIN on the card the hook loads it
and the AutoRun never runs. (`projects/usb-shell-sup/cards/warm-boot-2026-09-25/
fpsup-loader-hook-1/recovery-noBIN/`.)

## Prove the card carries what you think

The composer's checks say the card is coherent, not that it is the card you
meant. Compare, section by section, against the bytes that were released:

```
"VBIN" | count | entry | payload_len | (dest, len) * count | blobs, 4-aligned
```

Index the card's sections by destination and check every release section is
present with identical bytes. Skip destination zero only for stage2 (the first
section; a merge replaces it); other destination-zero sections are launchers and
must match. A number that moves is the question, not the noise.

Before it goes near the camera, run it under emulation — skill
`fp-unicorn-emulation` (hook path, journal against the stock image, power-off
write-back, fallback with no file).

## Rebuilding does not give you what you tested

```
the card that wrote A001_947   launch section 10,836 bytes  0b04c2681f59
released gyro v1.12.0          launch section 10,836 bytes  0b04c2681f59
rebuilt the next morning       launch section 10,964 bytes  4dbafdf396de
```

128 bytes, from one source file edited after the release was cut. Take tested
bytes from `releases/fpsup-<product>-v<version>/`; do not rebuild and assume.
**Attach a camera result to bytes, not to a command line.**

## Before saying a card works

- The banner names the build; a dev card should say so. (Fast Start 2's instant
  path shows the four-box screen, not the banner.)
- Boot with USB **unplugged**, then attach: the gadget is built on attach and the
  descriptor patches have to land first. Power off unplugged too, or every start
  is cold.
- For anything that arms hooks: boot, do **not** record, power off, start again —
  about ten times — plus once right after a take.
- After any change to a card, run `tools/card-composer/build_catalogue.py`.
- A script-built card does not go into `releases/`. Releases are cut by
  `gyro/release_card.py`, the open-gate builder's `--release`, or
  `repack_release.py` for a payload that did not change.

## Driving the page from a session

**Serve it; do not open the file** (`python3 -m http.server 8731 --bind
127.0.0.1` in `tools/card-composer/`). **The drop zone is behind "Show the
technical detail".** **Match the title line, not the block** — OG2K's text says
"not with fpSup-OG3K":

```js
const find = re => [...document.querySelectorAll('input[type=checkbox]')]
  .find(c => { const m = c.closest('.mod');
               return m && re.test(m.innerText.split('\n')[0]); });
```

**Uploading re-renders and clears the ticks** — set them again after. **If the
download does not land**, the bytes are in `current.autorun` /
`current.vshl.bytes`, the checks in `current.ok`. Or skip the browser: see
*Compose the page's card offline*.

## Where the detail is

`projects/usb-shell-sup/notes/LOADER_V2.md` (the current load chain) and
`DEV_MERGED_CARDS.md` (merged-card history) in the research tree beside this
repo; `tools/card-composer/README.md` here is the design.
