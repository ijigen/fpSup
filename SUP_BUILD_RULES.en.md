# Building a sup: AutoRun → loader → stage2 → entry

[中文](SUP_BUILD_RULES.md) · English. The two say the same thing; a change to
one is made to both in the same commit. This is the contract; the walkthrough
that explains the whole process from the start is [BUILDING.md](BUILDING.md).

Applies to: SIGMA fp Ver.5.02, the load chain as unified on 2026-09-23.
Readers: anyone — agent or person — writing a new sup, changing an existing one,
or maintaining the merged builds.

This is a build contract, not another development log. The evidence and the
historical numbers are in the
[shared load-chain record](../projects/usb-shell-sup/notes/CARD_BUILD_PIPELINE.md),
and the OG restore / recording / Quick Set evidence in the
[OG stability record](../projects/open-gate/notes/OG_BOOT_RESTORE_STABILITY_REVIEW_2026-09-23.md).
Both live in the full research project and may be missing from a bare fpSup
checkout; if they are, say which evidence is missing rather than filling it in
as "verified". Where the current code and the latest verification disagree with
an older comment, settle the difference first; do not copy the historical
version.

## 1. Five things first

1. **New features go in the BIN, through the shared loader.** No sup gets its own
   copy of the loader, stage2 or AutoRun generator.
2. **An entry installs and returns.** Resident work runs in the sup's own
   worker/task, never in a loop inside the load entry.
3. **Keep both passes and the existing entry ABI.** Do not delete pass 2 because
   one card does not use it; do not add a third pass or interpret an entry's
   return value.
4. **A compatible payload update changes only the BIN.** No runtime BIN hash,
   version pairing, pair ID, or anything else that forces a new AutoRun with
   every BIN.
5. **Change only what this change needs.** No general state machine, cross-sup
   failure transaction, global configuration framework or unrelated cleanup on
   the side. When the contract really has to change, propose the reason and the
   compatibility impact first.

## 2. One build line

A product builder prepares its own content and calls the `--loader` path of
[build_autorun.py](fp_usb_shell/build_autorun.py), which produces `AutoRun.txt`
and `fpSup.BIN`. Merged cards are packaged by the existing composer from the
same AutoRun / stage2 / Fast templates; nobody writes another loader. A card
built with the generic builder directly, without the diagnostic shell, uses
`--no-shell`.

- Code or data at a fixed address: the existing `--also` / `--also-bin`.
- Initialisation that runs where the file was loaded: `--boot-bin FILE:OFFSET`.
  This suits a launcher that allocates its own memory and moves resident code
  into it.
- An initialiser that already sits at a fixed address: `--vshl-entry ADDRESS`.
- **No entry, no argument.** Do not pass `--vshl-entry 0` as if it were an entry:
  0 is the header's "no entry" value and the end marker of the multi-entry
  table.
- A packaging layer keeps every non-zero upstream entry. It must not re-pack the
  sections and drop the entry, and it must not assume every product's entry
  is 0.
- Chain entries through [entries.S](fp_usb_shell/templates/entries.S); no sup
  calls the next sup itself. The generic builder's order is worker → each
  boot-bin (in argument order) → vshl-entry; today's OG + gyro is
  worker → gyro → restore. A new sup with an initialisation dependency has it
  arranged and verified where the card is assembled, not by changing the entry
  ABI or by sups handing off to each other privately.

Use each product's current builder: gyro is
[build_base_card.py](gyro/build_base_card.py); OpenGate is the full project's
[build_og3k_gyro.py](../projects/open-gate/build/build_og3k_gyro.py), with its
UI from [build_og3k_ui_candidate.py](../projects/open-gate/build/build_og3k_ui_candidate.py).
Do not go back to a historical builder, hand-edit a generated BIN or AutoRun, or
overwrite a frozen release to make a comparison pass.

Product cards and the final Fast packaging are separate: the gyro and OG release
flows do not carry Fast. Merged releases are managed by
[card-composer](tools/card-composer/build_catalogue.py); a development merged
card uses `--dev-card`, plus `--fast` when it needs Fast. `--reference` is a
comparison baseline and does not pass itself off as a card that has been booted
or released.

## 3. The load order is not negotiable

1. AutoRun places and calls the loader. On a Fast hit, store_boot copies the
   loader, does the D/I cache maintenance and tail-calls it.
2. The loader allocates its own staging buffer, opens, reads and closes the
   file, and checks the existing VBIN magic.
3. **The loader cleans the D-cache, then invalidates the I-cache, before it
   first runs the stage2 in staging.**
4. Before placing anything, stage2 allocates the write-back journal and
   registers the loader's power-off callback in both of `XC_PowerOffMgr`'s
   lists. Pass 1 then places the fixed-address sections, copying each firmware
   word outside the cave into the journal before overwriting it, and publishes
   D/I. At power-off the callback writes the journal back, so the camera powers
   off stock.
5. It calls the header entry. With several entries it calls each in turn, and
   **each must return**.
6. stage2 runs pass 2: it places the pool-offset sections, then publishes D/I
   again.
7. Only a Fast Start 2 package has the store provisioning, the abort and the
   loader hook. stage2 arms the abort only when an AutoRun is actually running,
   and points `0xC03DA420` (the call that starts the AutoRun) at the loader's
   `+4` entry, so a warm restart loads without the AutoRun. stage2 returns and
   the loader frees staging. On a **Fast hit with the load complete**, the next
   `echo` runs the abort and skips the slow path. On a
   first boot or a miss, the fallback loader returns, AutoRun restores the echo
   slot and finishes normally, and does not call the abort. An ordinary card
   finishes through its AutoRun as it always has.

**"Below `0x40000000`" means two different things:**

| field | 0 | non-zero, below `0x40000000` | `0x40000000` and above |
|---|---|---|---|
| section destination | stays in the file, not moved (stage2, launcher…) | pool offset, pass 2 | absolute destination, pass 1 |
| header / multi-entry table entry | header: no entry; table: end | offset in the file's staging buffer | absolute address to call |

Positions and offsets are recomputed by the builder. Never hard-code an in-file
offset from one build into another package. "The entry was called" means only
that execution got there; **it does not mean every sup succeeded**. The chain
does not look at r0 and does not stop later entries.

## 4. Entry, memory and cache duties

- An entry receives **its own resolved address in r0** — not a shared settings
  object, a pool pointer or a success flag. Preserve the callee-saved registers
  you use; save LR if you make calls, and keep SP 8-byte aligned at every call.
- A boot entry runs in the loader's task context; later hooks do not
  necessarily run in the same kind of context. IRQ-like callbacks must not block
  or do file I/O at will; resident, waiting or heavy work uses the proven task
  approach.
- A launcher that leaves resident code or data behind first allocates memory it
  owns, copies and initialises into it, and only then installs its hooks.
  **No task, hook or resident data may keep pointing into staging**: the loader
  frees it on return.
- Do not assume an earlier sup has allocated memory. `0xC3757A7C` is the
  existing pool publication word. It is not the loader's staging address, and
  it is not a public variable every new sup must overwrite. Manage pool, offsets
  and lifetime by the pass 2 protocol only if you really use that protocol; do
  not add shared dependencies for a new sup.
- Put large resident bodies in memory you allocated; the cave holds only the
  short code and pointers that must be there. Use the current allocation
  mechanism and check what is occupied. "It reads zero" does not make an address
  free, and you do not move another sup's or the USB transport's work area.
- When installing a hook at run time, first prepare the code, pointers and
  resources it will use, finish the publication they need, and arm it last. If
  an allocation fails, do not let that hook take effect, and keep a path that
  returns normally. This does not mean adding an all-or-nothing rollback for
  other sups.
- **Every firmware word a card changes is written back at power-off by the
  loader, not by the sup.** Sections are journaled by stage2 automatically. A
  sup that arms hooks at run time declares each site as a four-byte section
  holding the firmware's own word, so stage2 journals it before the entry runs
  (reference: gyro's `hook_sites()` in `build_base_card.py`). A sup does not
  register a power-off routine of its own. A hook must still behave correctly
  when it fires with no recording in progress. Why, and the history, are in
  [HOOKS_AT_POWER_OFF.md](HOOKS_AT_POWER_OFF.md).
- When state words move, **their initial values move with them**. Test the value
  the code starts with, not just the address.
- **The power switch is a warm restart: the image and the cave are kept, BSS is
  cleared, the heap starts again.** A sup must not assume the words it patches
  are still stock when it loads (the previous card, or an older build of itself,
  may be there); anything registered with the firmware is registered again on
  every load; nothing that points into the pool may be left for the next boot
  (the loader's write-back takes care of every declared site).
  The detail is written in one place only,
  [HOOKS_AT_POWER_OFF.md](HOOKS_AT_POWER_OFF.md).
- Newly written ARM code gets the proven **`0xC000E91C()` → `0xC000EABC()`**
  before it first runs. A DSB, a correct read-back of memory, or "the new code
  flushes once it is running" does not replace cache maintenance before the
  first execution.
- A static hook placed by pass 1 can be reached by a stock background path
  before your entry runs, so it must cope safely with uninitialised state. Load
  order is not a lock against REC or Quick Set, and does not make installing
  during recording safe.

## 5. Fast start and "only the BIN changes"

The merge page's option is **Fast Start 2**: this settings-block fast path plus
the loader hook, built in one `--store-boot --loader-hook --four-box-bar` run.
A warm restart then loads about 1.4 s after power-on without the AutoRun and
shows the four-box screen; a cold start runs the short Fast AutoRun. Single
product releases carry neither.

Fast only shortens the work of AutoRun spelling out the loader. It is not a
second sup initialisation path; **a hit still re-reads the BIN**. When
store_boot's loader magic matches, it copies the loader → D/I → restores LR and
tail-calls. On a miss it returns and the same AutoRun takes the slow path.
stage2's provisioning writes the body first and the magic last.

The magic is derived at build time from the **loader bytes**. It is not the BIN
version, and it is not a hash of the stored body computed at boot. Do not let
product names, content lengths, entries or feature versions into it. The
bootstrap, the loader and the Fast stage2 / abort must come out of one
consistent packaging build; do not splice old and new pieces by hand. A card
that already has Fast is not an ordinary merge input: Fast is added once, by the
final packaging, and no sup carries its own.

- **Only a compatible payload or entry changed, loader and packaging unchanged:**
  shipping just the BIN is allowed; confirm on the host that AutoRun is
  unchanged.
- **The loader bytes, ABI, file name, Fast switch or its packaging really
  changed:** update AutoRun and BIN together, once, and say why. Fast must not
  mix a new BIN's provisioning with an old loader.
- **Only the date or product version changed:** that is no reason to change
  AutoRun. Do not write each payload's version or a timestamp into the banner
  automatically. If the user explicitly wants the on-screen name updated, the
  AutoRun change is a display requirement, not the loader demanding a version
  match.

Fast uses a settings block that persists; it cannot be described as "never
writes anything persistent". That does not license changing other settings
fields, nor an agent installing the card in the camera on its own.

## 6. Minimum acceptance and handover

Build into a fresh local output directory; do not overwrite cards or frozen
releases. Pick tests by what the change touches; a small change does not need
unrelated products re-run.

- **Every sup:** confirm the expected sections, entry and assembly order are all
  there, and use the existing build-time size, alignment and overlap checks. A
  new placement no existing check covers gets its own offline check; do not
  remove a guard to get through.
- **Merge / Fast support:** verify your own ordinary, debug, Fast and related
  combinations. With the same loader configuration, a payload change must leave
  AutoRun unchanged.
- **The shared load chain was touched:** from `fpSup/fp_usb_shell` run
  `python3 -B -m unittest test_boot_chain test_loader_hook test_splash`.
  `test_loader_hook` runs the real loader and stage2 under unicorn against the
  firmware image (hook path, journal, power-off write-back, three-way boot).
  A new test that passes first time must be broken on purpose, one line, to
  show it can fail (the research tree's skill `fp-unicorn-emulation`).
- **An OG entry, gyro pass-through or catalogue refs were touched:** run
  `python3 -B projects/open-gate/build/test_boot_entry_chain.py` from the full
  project root; by default it uses a fresh temporary output directory. Keep
  entry 0 / guard-off compatibility. Catalogue verification calls only refs; do
  not run anything that rewrites the site's main branch for a test.
- **A sup that installs hooks:** on the camera, boot, do not record, power off,
  then boot with a card in the slot — about ten times. Recording tests never
  reach this path (see [HOOKS_AT_POWER_OFF.md](HOOKS_AT_POWER_OFF.md)).
- **Loading over a previous card:** boot another card (or an older build of your
  own), power off with the switch, then boot yours; check it is still correct
  when the image it finds is not stock.
- **A new product outside the existing tests:** add that product's minimal
  entry / installation test; an OG test passing is not its acceptance.
- **Camera and release are separate:** record build, machine-code checks,
  simulation and camera results separately. A simulator that did not run is
  "unverified". Without explicit authorisation, do not write cards, operate the
  camera, commit, push or publish.

A handover states at least: what changed, the build commands and output
location, which tests passed / failed / were not run, and whether AutoRun must
change. Record the SHA-256 of anything put in a camera or handed over, to
identify those exact files — **for traceability only, never as a runtime
pairing requirement**. Logs go into the existing shared notes, coordinated with
the other agents involved. This contract is updated only when the build
contract really changes, not with a running log of each experiment.

## 7. Read the code, not remembered numbers

- [loader.S](fp_usb_shell/templates/loader.S), [stage2.S](fp_usb_shell/templates/stage2.S),
  [store_boot.S](fp_usb_shell/templates/store_boot.S), [entries.S](fp_usb_shell/templates/entries.S):
  the execution contract.
- [build_autorun.py](fp_usb_shell/build_autorun.py): the container, the entry
  table, capacity and packaging options.
- [test_boot_chain.py](fp_usb_shell/test_boot_chain.py): regression for the
  shared chain.
- [test_loader_hook.py](fp_usb_shell/test_loader_hook.py): the loader hook and
  the power-off write-back, emulated.
- [releases/README.md](releases/README.md): naming and packaging rules for when a
  release is actually approved. Look up version numbers in the current tags and
  artefacts; do not copy old examples.

The loader's size, AutoRun's command count and speeds are results of a specific
build; a new product does not carry its own hard-coded copy of them.
