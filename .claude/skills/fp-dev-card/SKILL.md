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
