# PreCap — pre-capture for high-speed continuous (loader v4 sup)

`release/PreCap_v0.1.0.BIN` is a regular fpSup. Put it in `\fpSup\` on a Loader
v4 card and it loads on the next boot, next to the other sups.

## What it does

In the high-speed continuous drive mode, holding the half press pre-records
into a four-frame ring instead of letting the frames through. Pressing the
shutter all the way hands the newest four (≈0.5 s before the press) to the
firmware, which writes them ahead of the frames taken after the press. Letting
the half press go throws the ring away.

The shutter sound is muted while the ring fills. Other drive modes are
untouched: the key hook only engages when the firmware reports drive kind 9.

The switch is a row on the fpSup page, **ON at every boot**.

## Status

On the camera 2026-10-27, on a Loader v4 card with the other twelve sups, and
test shots again after the release build.

| | |
| --- | --- |
| half press only, then release | `committed 0`, ring dropped, no file, `muted 233` |
| half press → full press | `committed 4`, exactly four frames ahead of the burst, `muted 326 / played 12` |
| single shot | `gate 0x100` — the guard refuses, factory shutter unchanged |
| five power cycles | all four hooks still installed, `CAVE_BUMP` pinned at base+32 |

The test tables and what each one predicts are in `notes/P2_RESEARCH.md`,
`notes/P3_RESEARCH.md` and `notes/P4_RESEARCH.md`; the user-facing summary is
`release/README.txt`. The development history (P1 observer → P4 shutter mute)
is in `build/out/` and `validation/`.

## Layout

| path | what |
| --- | --- |
| `precap.S` | the four hooks, the ring, the key state machine (ARM, position independent) |
| `precap_row.c` | the fpSup-page row `PreCap ON/OFF` (Thumb, `-fropi`, no data) |
| `build/build_precap_sup.py` | assembles both, checks the stock words, wraps in a loader v4 header |
| `build/test_precap_sup.py` | 16 unicorn tests: entry contract, switch, ring, commit, drop, mute |
| `release/` | the shipped BIN plus `README.txt` / `ABOUT.txt` / `build.json` / `STATUS.md` |
| `build/out/p1..p4-dev/` | the four development cards, kept as built |

The four hook sites are `C038F0E8` / `C038F174` (the two HIGHCONT frame
hand-offs), `C02DC108` (key dispatch) and `C03817D4` (the SRec shutter sound).
All four are claimed `SL_EXCL`; none appears in the official card's `LOAD.LOG`,
so nothing collides today.

## Build + test

```sh
cd build
python3 -B build_precap_sup.py --out .   # then move the BIN to ../release/
python3 -B -m unittest test_precap_sup
```

The builder refuses to run if a site does not hold its stock word, if the code
calls a firmware routine outside the known list, or if a direct `bl` is emitted
— a `bl` cannot reach the firmware from the loader's block (about 2 GB away),
which is why the four veneers live in the loader's cave instead.

## Two things that bite when writing a loader v4 sup

Both were hit while making this one; the second is still a live bug in
`fpSup/fp_usb_shell/armasm.py`.

1. `SL_KEEP` is **0** and `SL_RELEASE` is **1**. Returning `SL_RELEASE` frees
   the block — and the fpSup-page row points into it.
2. `ldr reg, =expr` produces a literal pool that is **not filled** for
   expression operands, so it assembles and then reads back 0. Use
   `movw`/`movt`, or `mov rX, pc` plus a symbol offset as the stubs here do.
