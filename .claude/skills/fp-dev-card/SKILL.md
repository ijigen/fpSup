---
name: fp-dev-card
description: Building a merged SIGMA fp card for camera testing — open gate plus the gyro logger plus the USB shell on one card — and knowing how it differs from what fpSup-Merge gives a user. Use when a change needs verifying on the camera and one product's card is not enough, or when a test result has to be attached to specific bytes.
---

# A card to test with

Shipped merged cards come from `fpSup/tools/card-composer/index.html` and
nowhere else. That policy is not a formality: `build_og3k_gyro.py` emitted
wrong merged cards for weeks — the card said gyro, the payload was not the
shipped gyro, nothing failed, and it took a section-by-section comparison to
notice.

But development needs merged cards in the camera. The USB shell is how a fault
is looked at, and a fault in the gyro logger during an open-gate take needs all
three on one card. So there is a named path for it.

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

**A dev card is the page's card minus the push endpoint, rearranged.** What is
observed on a dev card holds for the page's; the reverse does not follow,
because the page's card also opens EP 0x83.

The order differs because `build_autorun.py` appends the worker *before*
`--also-bin` and a `--boot-bin` payload *after* it, and a merge walks cards in
catalogue order and cannot tell those two apart. That is also what the two
remaining STALE checks in `build_catalogue.py` are about.

## A dev card never starts fast, and that is the design

`--dev-card` produces a slow-load card, always. Nothing in the chain passes
`--store-boot`, and it should not: fast start is added by the step that packages
a card, not by the build that makes one.

The reason is in the bytes. A fast card's four pieces -- the AutoRun with
`store_boot` in it, a stage2 that writes the loader to flash, the abort routine,
and the magic -- all have to come from one `--store-boot` build, because the
magic is a sha256 of the loader that same AutoRun spells out. Mix a `store_boot`
from one build with a loader from another and they verify against each other and
disagree; at boot, that is a branch into the settings block with no shell to
recover with. So one build owns all four, and the page swaps them in as a set.

**To test fast start on a combined card, use the page.** Tick the products, tick
Fast start, download both files. The page builds those four pieces from one
`--store-boot` build and a check in `build_catalogue.py` refuses to write the
page if the magic does not match the loader beside it.

A card that already starts fast is the wrong file to feed back into the page:
taking its fast start apart means recomputing that hash, and a hash the tool may
recompute is a check that always agrees with itself.

**Not yet booted on a combined card.** As of 2026-09-20 fast start has been
written, booted and confirmed on a shell-only card: first boot slow and seeds
the settings block, every boot after it twenty-six commands, and the banner
drawn once instead of twice. The same three pieces go onto a combined card and
nothing about them is card-specific, but nobody has powered one on. Closing it
is two boots: the first seeds, the second should show the banner once and no
`fpSup[####....]050` frame.

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
- A dev card never goes into `releases/` and never goes to anyone else.

## Where the detail is

`projects/usb-shell-sup/notes/DEV_MERGED_CARDS.md` — the measurements above,
the history, and why the policy exists. That path is in the research tree
beside this repo, not in it; a reader who only has this repository has the
numbers above and `tools/card-composer/README.md`, which is the design.

The builders this skill drives are in the same research tree
(`projects/open-gate/build/`). The gyro one, `gyro/build_base_card.py`, is
here.
