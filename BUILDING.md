# How a fpSup card works, and how to build one

English · [中文](BUILDING.zh.md)

This is the walkthrough: what is on a card, what happens when the camera boots
it, how to write your own feature (a "sup"), how to combine it with others, test
it and release it. It is written to be read front to back.

The short, strict version is [SUP_BUILD_RULES.en.md](SUP_BUILD_RULES.en.md).
That is the contract; this explains it. Where the two disagree, the rules win,
and this file should be fixed.

SIGMA fp, firmware Ver.5.02 only. Everything here is about that firmware; the
addresses mean nothing on any other.

---

## 1. The idea in one paragraph

The fp's firmware runs a script called `AutoRun.txt` from the SD card at boot,
if it finds one. That script can write words into memory. We use it to write a
small **loader**, and the loader reads a second file, `fpSup.BIN`, which holds
everything else: code, data, and patches to the firmware. Nothing is written to
the camera's flash (one opt-in exception, *Fast Start 2*, section 7). What is
loaded lives in RAM, but **switching the camera off and on is not enough to clear
it**: that is a warm restart, and the patched firmware survives it (section 4).
Remove the card and take the battery out to get a stock camera back — that
clears the heap (measured); that it also clears the patched image is expected
but not yet measured.

A **sup** is one feature packaged this way: the gyro logger, open gate, the USB
shell. Several sups can share one card.

## 2. What is on the card

```
SD card root
├── AutoRun.txt    a text script, padded to a fixed length (about 32 KB)
└── fpSup.BIN      a container of "sections", padded to 32 KiB or more
```

**AutoRun.txt** draws a progress bar, writes the loader into memory one word at a
time (`mem set` lines), borrows the firmware's `echo` command to run it, and
finally draws the banner — `fpSup-Gyro-v1.13.1!` and so on. The banner is how you
tell which card is in the camera.

**fpSup.BIN** starts with a small header, then a table of sections, then their
bytes:

```
"VBIN" | section count | entry | payload length
(destination, length)  × count
section bytes, each padded to 4
```

A section's **destination** says where its bytes go:

| destination | meaning |
|---|---|
| 0 | stays where the file was loaded; it runs from there (the helper code, launchers) |
| below `0x40000000` | an offset into memory the payload asked for at boot (the "pool") |
| `0x40000000` and up | an absolute address in the camera's memory (firmware patches, cave code) |

The **entry** is where to call once the sections are placed. 0 means "none".

## 3. What happens when the camera boots

```
power on
  │
  ├─ firmware boots normally, finds AutoRun.txt, starts running it
  │
  ├─ AutoRun: progress bar, then about 70 `mem set` lines write the LOADER
  │           into a small free area of firmware memory (the "cave")
  │
  ├─ AutoRun: points the `echo` command at the loader and runs `echo`
  │    │
  │    └─ LOADER:  asks the memory allocator for a staging buffer,
  │                reads fpSup.BIN into it, checks "VBIN",
  │                cleans the caches, and jumps to the first section:
  │         │
  │         └─ STAGE2 (the helper that travels inside the BIN):
  │              pass 1  place every section with an absolute destination
  │              ─────── clean the caches
  │              call the entry — each sup's installer, one after another;
  │              every one must return
  │              pass 2  place every section with a pool destination
  │              ─────── clean the caches, return
  │
  │         loader frees the staging buffer and returns
  │
  └─ AutoRun: puts `echo` back, draws the banner. Done.
```

Two things to take from this:

- **Your code runs once at boot, inside the loader, and must return.** Anything
  that should keep running afterwards is either a patch the firmware calls into
  (a hook) or a task you create.
- **The caches must be cleaned before new code runs.** The ARM core keeps
  separate caches for data and for instructions; bytes you just wrote are not
  yet visible as instructions. The loader and stage2 do this for everything they
  place. If your own code writes code at run time, it must call
  `0xC000E91C()` then `0xC000EABC()` itself before running it.

## 4. Where things live in memory

| region | what it is | after the power switch (warm restart) |
|---|---|---|
| firmware image `0xC0000000…0xC2F30800` | the firmware's own code and data. Patches go here | **kept** — every patch is still in place |
| the **cave** `0xC072DE64…0xC0730000` | a few KB of unused firmware image. The loader, and small pieces that must be at a fixed address | **kept** — code, pointers and state in it survive |
| firmware variables (BSS) `0xC3000000…0xC38D6FB0` | the firmware's lists and registrations: observers, power-off callbacks, the pool pointer `0xC3757A7C` | **cleared** — the only range the boot code zeroes |
| allocator memory (the **pool**, the heap) | memory asked for at boot. Large code, buffers, image data | **gone** — the allocator starts again and hands it to others |
| settings block `XC_CommonSaveData` | the camera's own saved settings | **kept**, even through a battery pull. Only Fast Start 2 writes here |

**The power switch does not restart the camera from scratch.** The DRAM keeps
refreshing while it is off, and on the next boot the firmware runs the image
that is already in memory — patches included. Measured 2026-09-25: an open-gate
card, powered off with the switch, then a card with only the USB shell; all of
open gate's patches and its cave code were still there, three restarts in a
row, and open gate recorded correctly before AutoRun had even run. What clears
it is not yet pinned down: earlier measurements saw memory above the firmware's
variables lost after 10–25 minutes off, and after a battery pull.

What that means for a sup:

- **Code and data in the image or the cave outlive the card.** On the next warm
  boot they are there before AutoRun — whichever card is in the slot, or none.
  So a sup must never assume the words it patches are still stock when it
  loads; the previous card, or an older version of itself, may be there.
- **Anything registered with the firmware is gone**, because the lists are in
  BSS. Register again on every load.
- **Anything pointing into the pool is dangling.** A hook left in the image that
  branches into the pool jumps into someone else's memory on the next boot. That
  is why every firmware word a card changes is written back at power-off
  (section 5).

The cave is small and shared, so it has a tiny allocator: one word at
`0xC072E060` holds the next free address, stage2 resets it every boot, and a
sup takes what it needs by adding to it. Do not pick a cave address yourself.

## 5. Two ways a sup changes the camera

**Static patches.** A section with an absolute destination overwrites firmware
words at load time. Open gate works this way: a few hundred words of tables and
branches, all placed by stage2 before anything else runs. Simple, and the code
they branch to also lives in firmware memory (the cave), so it stays valid —
and, as section 4 says, it is still there after a warm restart.

**Run-time hooks.** Your entry allocates memory, copies code into it, and then
overwrites one firmware instruction with a branch to that code. The gyro logger
works this way, because its code is too large for the cave. This is more
flexible, and it has one rule that is easy to miss:

> **Declare every site you will hook as a four-byte section holding the
> firmware's own word.**

The loader writes back every firmware word a card changed when the camera
powers off (since 2026-09-25): stage2 records each section's destination before
placing it, and a power-off callback it registers writes the records back. It
cannot see a word your entry writes later -- unless the site was also a section.
Writing the firmware's own word there at load is harmless, and puts the site in
the record. gyro's `hook_sites()` in `gyro/build_base_card.py` is the reference.
Do not register a power-off routine of your own.

A hook left in place fires on the next boot and jumps into memory the allocator
has since given to someone else. That froze cameras with gyro v1.13. The story
and the firmware's power-off API are in
[HOOKS_AT_POWER_OFF.md](HOOKS_AT_POWER_OFF.md).

## 6. Writing and building a sup

### What you need

- Python 3
- `clang` able to target `armv7-none-eabi` — any recent clang, no cross toolchain
- the firmware image `out/MAIN_c0000000.bin` if you want to check addresses
- a SIGMA fp on Ver.5.02 and an SD card, to test

### Writing the code

Sups are ARM assembly (`.S`), assembled by `fp_usb_shell/armasm.py`, which
calls clang. The camera has no dynamic linker: code is copied as raw words, so
it must work at the address it is placed (or be position-independent if it is
copied at boot).

For an **entry** (the installer stage2 calls):

- `r0` is the entry's own address. Keep the callee-saved registers you use,
  save `lr` if you call anything, and keep `sp` 8-byte aligned at every call —
  the firmware's `LDRD`s fault otherwise.
- Do the work, then **return**. Never loop forever here.
- Ask the allocator for memory; do not assume another sup already did.
- For a hook: declare its site (section 5), prepare its code and data first,
  then write the branch last.
- If an allocation fails, arm nothing and return normally. A card that half
  works is worse than one that does nothing.

For a **hook** (code the firmware branches into later):

- It can run at any time, in whatever task the firmware was in — possibly an
  interrupt-like context. Do not block, and do not do file I/O from there;
  hand heavy work to a task.
- It must behave correctly when nothing is recording, and before your entry has
  run if it was placed statically.
- When state moves from one place to another, carry its initial value with it.
  "0xFFFFFFFF means not yet" is easy to lose.

### Building

Everything goes through one tool, `fp_usb_shell/build_autorun.py --loader`,
which writes `AutoRun.txt` and `fpSup.BIN` together. The options that matter:

| option | use it for |
|---|---|
| `--also ADDR:SRC` | assemble `SRC` and place it at a fixed address |
| `--also-bin ADDR:FILE` | place raw bytes at a fixed address (or a pool offset, below `0x40000000`) |
| `--boot-bin FILE:OFFSET` | a launcher that runs where the file was loaded: allocates, copies itself, installs |
| `--vshl-entry ADDRESS` | an installer already placed at a fixed address |
| `--no-shell` | leave the USB shell out — every product card uses this |
| `--banner TEXT` | the text shown when loading is done, 19 characters at most |
| `--out DIR` | where to write the two files |

The existing products each have a builder that calls it with the right
arguments. Use them rather than calling it by hand:

```sh
# gyro (Gyroflow logger)
python3 gyro/build_base_card.py --edition gcsv --version dev --out /tmp/gyro-card
# the same with the USB shell in, for debugging on the camera
python3 gyro/build_base_card.py --edition gcsv --debug --version dev --out /tmp/gyro-dbg
```

The open-gate builder lives in the full research project
(`projects/open-gate/build/build_og3k_gyro.py`), not in this repository.

Every builder runs checks before it writes anything: sections must not overlap,
must fit what the loader can read, and must not land where the loader is
working. If one fails, fix the cause; do not remove the check.

## 7. Combining sups, and Fast Start 2

**fpSup-Merge** combines released sups into one card in the browser:
<https://ijigen.github.io/fpSup/tools/card-composer/>. Tick the cards, get
`AutoRun.txt` and `fpSup.BIN`. You can also drop in your own `fpSup.BIN`.

What it does when it combines:

- keeps every card's sections, and folds identical ones together
- drops each card's own stage2 and puts in **one** current copy
- chains the entries in a fixed order (USB shell → gyro → open gate restore)
- writes the AutoRun from its own template, so every card it makes uses the
  current loader
- checks the result and disables the download buttons if any check fails —
  including a check that refuses an uploaded card built for a newer stage2
  than the page carries

**Fast Start 2** is a switch on that page. It gives a card three ways to start:

- **Instant** -- a restart with the power switch keeps the firmware in memory,
  and with it a hook at the one call that starts the AutoRun. The card loads
  about 1.4 s after power-on without running the AutoRun, and shows the
  four-box screen (the `FPSUPUI` folder the zip carries).
- **Fast** -- when the firmware was reloaded (a cold start, a battery pull, or a
  power-off with the USB cable attached), the script checks a fingerprint and
  runs the loader stored in the camera's settings block instead of spelling it
  out again.
- **Slow** -- the first boot, or a fingerprint mismatch (a different card, a
  newer loader): the script spells the loader out and stores it.

Some power-switch restarts come up cold anyway; they take the fast path.

Fast Start 2 is the **only** thing that writes to persistent memory. It survives a
battery pull and outlives deleting `AutoRun.txt`, so it is a choice for the
person who installs it; single-product releases never include it. Resetting
the camera's settings from the menu is expected to clear it, but that has not
been tested.

## 8. Testing on the camera

1. **Boot with the USB cable unplugged**, card in.
2. Watch the progress bar. It runs from `fpSup[........]000` to the banner.
   **A bar that stops is a load that stopped there**, and its position tells you
   roughly where.
3. Check the banner names the build you meant to test.
4. Do what the sup is for: record, open the menu, switch modes.
5. For anything that installs hooks, also: boot, **do not record**, power off,
   and boot again **with a card in the slot**. Do it about ten times. Recording
   tests never reach this path.
6. For a Fast Start 2 card: boot once (slow, stores the loader), restart with the
   power switch with the USB cable unplugged (instant: no progress, the four-box
   screen), and power off with the cable attached then start (fast: a short
   progress).

A `--debug` build carries the USB shell, so you can read memory over USB after
something goes wrong (`fp_usb_shell/README.md`). Release cards never carry it.

If the camera freezes: remove the card, take the battery out (with the USB
cable unplugged), and boot. Switching it off and on is not enough — the previous
card's patches are still in memory after a warm restart (section 4). A USB cable
can keep the camera powered with the battery out, so unplug it first. Write down the card's SHA-256 before testing, so a result
belongs to exact bytes and not to a command line.

## 9. Releasing

A release is a folder in `releases/`:

```
releases/fpsup-<product>-v<version>/
├── AutoRun.txt
├── fpSup.BIN
├── ABOUT.txt     one line in English, one in Chinese, for the website table
└── README.txt    for the person installing it
```

Its bytes are frozen: a release is never rebuilt or edited in place. The steps:

1. Build the card with the product's release script — for gyro,
   `gyro/release_card.py gcsv v1.13.1`, which rebuilds, checks every section is
   there, and writes the zip and checksums.
2. Put it in `releases/fpsup-<product>-v<version>/` with an `ABOUT.txt`.
3. `python3 tools/build_releases.py` — regenerates the tables on the website
   and in `README.md`. The GitHub Pages workflow fails if they are stale.
4. `python3 tools/card-composer/build_catalogue.py` — regenerates fpSup-Merge.
   It refuses to write the page if a combination does not reproduce.
5. Tag it with the folder's name: `git tag -a fpsup-<product>-v<version>`.
6. Push `main` and the tag. GitHub Pages deploys the site and the page.
7. The Claude Artifact copy of fpSup-Merge is separate: publish
   `tools/card-composer/artifact.html` to it by hand.

Version numbers continue from the tags (`git tag`), not from notes.

**Withdrawing** a release: move its folder to `history/withdrawn-<date>/` with a
README saying why, delete its tag, regenerate the tables and the page. When a
fix ships, say in that README what replaced it.

## 10. Words

| word | meaning |
|---|---|
| sup | one feature loaded from the card (gyro, open gate, USB shell) |
| AutoRun | the boot script the firmware runs from the card |
| loader | the small program AutoRun writes, which reads `fpSup.BIN` |
| stage2 | the helper inside `fpSup.BIN` that places sections and calls entries |
| section | one piece of the BIN, with a destination |
| entry | a sup's installer, called once by stage2 |
| cave | a small unused area of firmware memory, shared through an allocator |
| pool | memory a sup asks the camera's allocator for at boot |
| hook | a firmware instruction replaced by a branch into sup code |
| Fast Start 2 | the merge-page option: instant start after a power-switch restart (loader hook), fast after a cold start (loader kept in the settings block) |
| banner | the text shown when loading finishes; it names the build |
