---
name: fp-merged-card
description: Building a SIGMA fp card that carries more than one product — open gate plus the gyro logger plus the USB shell — and building it with fast start, where the loader lives in the settings block and every boot after the first is twenty-six commands. Use when a change needs verifying on the camera and one product's card is not enough, when a card should boot fast, or when a test result has to be attached to specific bytes. Covers what a script-built card shares with the ones fpSup-Merge hands out, and where they differ.
---

# A card to test with

Build any combination here, fast start included. The cards people download come
from `fpSup/tools/card-composer/index.html`, and that is about distribution and
the checks the page runs, not about what a script is allowed to make
(2026-09-20, the user's call, replacing an earlier rule that put every merged
card behind the page).

What the older rule was protecting against is still real and worth knowing:
`build_og3k_gyro.py` emitted wrong merged cards for weeks — the card said gyro,
the payload was not the shipped gyro, nothing failed, and it took a
section-by-section comparison to notice. The defence now is the composer's own
verification, which rebuilds five combinations from the shipped artifacts and
refuses to write the page if one does not reproduce. **Run it after changing a
card**, whatever built the card.

## Build one

```sh
# gyro + shell.  The gyro card's own debug edition; always been allowed.
python3 fpSup/gyro/build_base_card.py --edition gcsv --debug \
        --version dev --banner 'fpSup-DEV!' --out DIR

# open gate + gyro + shell
python3 projects/open-gate/build/build_og3k_gyro.py --dev-card --out DIR
OG_TARGET=og2k python3 projects/open-gate/build/build_og3k_gyro.py --dev-card --out DIR
```

`--out` is required. A merged card must not sit in the tree as a product.

`--dev-card` produces the same bytes `--reference` does; the difference is that
it says what it is and prints how it differs from the page's card.

## How it differs from what a user downloads

Measured 2026-09-20, the tested og3k+gyro+shell card against the same
combination from the page:

| | |
|---|---|
| `AutoRun.txt` | byte for byte identical |
| `fpSup.BIN` | dev 97 sections, page 103 |
| the 96 they share | every one identical |
| only on the page's | six EP 0x83 push patches, four bytes each |
| the trampoline | on both; its table words differ because offsets do |
| order | different |

**A script-built card is the page's minus the push endpoint, rearranged.** What is
observed on a script-built card holds for the page's; the reverse does not follow,
because the page's card also opens EP 0x83.

The order differs because `build_autorun.py` appends the worker *before*
`--also-bin` and a `--boot-bin` payload *after* it, and a merge walks cards in
catalogue order and cannot tell those two apart. That is also what the two
remaining STALE checks in `build_catalogue.py` are about.

## Fast start

```sh
python3 projects/open-gate/build/build_og3k_gyro.py --dev-card --fast --out DIR
```

Boots in twenty-six commands after the first: the loader lives in
XC_CommonSaveData, the AutoRun checks it and branches instead of spelling it
out. The first boot is the slow one and seeds the block.

**One build owns all four pieces, and that is physics rather than policy.** The
AutoRun's `store_boot`, the stage2 that writes the loader to flash, the abort
routine, and the magic all come out of one `--store-boot` run, because the magic
is a sha256 of the loader that same AutoRun spells out. Mix a `store_boot` from
one build with a loader from another and they disagree — at boot, that is a
branch into the settings block with no shell to recover with. `--fast` passes
`--store-boot` down the one chain that builds all four together; there is no
way to bolt it on afterwards, and nothing should try.

`--fast` only works with `--dev-card`. A single-product release does not get one:
a fast card writes into the settings block, which survives a battery pull and
outlives deleting `AutoRun.txt`, so it is not something to hand someone who did
not ask. `release_card.py` refuses a card carrying the abort routine.

Verified 2026-09-20 against the same selection from the composer page with Fast
start ticked: **`AutoRun.txt` byte for byte identical**, and the payload differs
exactly as the slow card does — the page's carries the six EP 0x83 patches and
a different section order.

**Still not booted on a combined card.** Fast start has been written, booted and
confirmed on a shell-only card: first boot slow, every boot after it twenty-six
commands, banner drawn once instead of twice. Two boots close it — the first
seeds, the second should show the banner once and no `fpSup[####....]050`.

The card waiting for those two boots, built from the page 2026-09-20 — gyro
v1.12.1, OG2K v0.1.1a, shell v3.1.1, fast start, banner `fpSup-DEV-OG2K-Fast!`:

```
AutoRun.txt   0178cc6020d16fcf6d61dcdf...
fpSup.BIN     083e6df989cdc4038975a77d...
```

Its gyro sections were compared against `releases/fpsup-gyro-v1.12.1/`:
12 identical, 0 different, 0 missing. Whatever those two boots show belongs to
these bytes and not to the command line that made them.

## Driving the page from a session

Four things about it cost a round trip each, 2026-09-20.

**Serve it; do not open the file.** Chrome refuses to navigate to `file://`
from `chrome://newtab`. `python3 -m http.server 8731 --bind 127.0.0.1` in
`tools/card-composer/` and open `http://127.0.0.1:8731/index.html`.

**The drop zone is behind "Show the technical detail".** The simple view hides
the upload box, the section table and the checks. Nothing works until it is
open.

**Match the title line, not the block.** The OG2K card's own description reads
"not with fpSup-OG3K", so a regex run over the whole `.mod` matches both cards
and the ticks fight each other:

```js
const find = re => [...document.querySelectorAll('input[type=checkbox]')]
  .find(c => { const m = c.closest('.mod');
               return m && re.test(m.innerText.split('\n')[0]); });
```

**Uploading re-renders and clears the ticks.** Set the products, upload the
payload, then set them *again* and read them back before downloading.

**If the download does not land**, Chrome raised a native save dialog a session
cannot see. The composed bytes are in page scope -- `current.autorun` and
`current.vshl.bytes` -- and `current.ok` is the checks. POST them somewhere
local rather than fighting the dialog.

## Prove the card carries what you think

The composer's own checks say the card is coherent, not that it is the card you
meant. That is the distinction the historical failure lived in: the card said
gyro and the payload was not the shipped gyro. So compare, section by section,
against the bytes that were released:

```
"VBIN" | count | entry | payload_len | (dest, len) * count | blobs, 4-aligned
```

Parse both, index the card's sections by destination, and check every section
of the release is present with identical bytes. Skip destination zero: it is
the loader-owned stage2 helper and a merge canonicalizes it. Expect
"12 identical, 0 different, 0 missing" for a gyro card -- a number that moves
is the question, not the noise.

## Rebuilding does not give you what you tested

```
the card that wrote A001_947   launch section 10,836 bytes  0b04c2681f59
released gyro v1.12.0          launch section 10,836 bytes  0b04c2681f59
rebuilt the next morning       launch section 10,964 bytes  4dbafdf396de
```

128 bytes, from one source file edited after the release was cut. Take the
tested bytes from `releases/fpsup-<product>-v<version>/`; do not rebuild and
assume.

**Attach a camera result to bytes, not to a command line.** Record the sha of
both files, or at least of the `launch` section — it is the part that moves.

## Before saying a card works

- The banner names the build. Two cards look identical in the camera and this
  is the only way to tell which one is in it. A dev card should say so.
- Boot with USB **unplugged**, then attach. The gadget is built on attach and
  the descriptor patches have to land first.
- After any change to a card, run `tools/card-composer/build_catalogue.py`. It
  checks five combinations against script-built references and refuses to write
  the page if one does not reproduce.
- A script-built card does not go into `releases/`. A release is cut by
  `release_card.py` or the open-gate builder's `--release`, which run the
  checks a release needs; this path runs fewer.

## Where the detail is

`projects/usb-shell-sup/notes/DEV_MERGED_CARDS.md` — the measurements above,
the history, and why the policy exists. That path is in the research tree
beside this repo, not in it; a reader who only has this repository has the
numbers above and `tools/card-composer/README.md`, which is the design.

The builders this skill drives are in the same research tree
(`projects/open-gate/build/`). The gyro one, `gyro/build_base_card.py`, is
here.
