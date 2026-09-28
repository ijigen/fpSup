# Open-gate mode isolation fix (gated rowpatch)

## Problem
The open-gate test build repurposes the FHD/29.97 CinemaDNG preset and arms a
FieldAngle canvas hook at `0xC043A19C` whose payload (`rowpatch_v4.S`) decides
whether to rewrite geometry **using the row dimensions only** (1936x1090). But
other CinemaDNG framerates on the same FHD family (e.g. FHD/25) also build a
1936x1090 FieldAngle row, so the hook fires for them too and stretches them to
3032x2012 against a sensor that is not mode 117 — corrupting those modes
(purple lines / small offset frame / white).

## Root cause (measured on hardware, fp Ver.5.02, over the USB shell)
The FieldAngle build function `0xC043A158` receives a **selector r5** and maps it
through the profile table `0xC0BD05D4` (`table[r5]` = profile index). Measured
selector values while the hook fired:

| preset (CinemaDNG) | selector r5 | builds 1936x1090 row |
|---|---|---|
| FHD/29.97 (open gate, mode 117) | **175 (0xAF)** | yes |
| FHD/25 | 180 (0xB4) | yes |

r5 is passed straight into the hook, so it is correct at hook time (unlike the
selected-mode register `0xC343B590`, which is only 117 mid-take — gating on it
made the hook never fire and broke open gate itself). During a real open-gate
take the hook fired 474x in ~3 s, r5 == 175 every time (stable standby + record).

## Fix
`rowpatch_gated.S` adds two gates to `rowpatch_v4`'s logic:
1. an `ARMED` flag word at `0xC072FA10` (lets a controller enable/disable without
   unhooking), and
2. **`r5 == 175`** — the open-gate selector — before the dimension check.

So the canvas rewrite happens only for the actual open-gate take; every other
framerate/mode falls through as a byte-for-byte no-op and records as stock.
Verified: on hardware, open gate still records 3032x2012 while FHD/25 and the
other modes record cleanly; in an ARM emulator all gate paths pass (rewrite only
for armed + 1936x1090 + r5==175).

## Build
`build_gated_autorun.py` reuses `build_test_autorun.py`'s verified helpers/data
patches and emits an AutoRun with the gated payload at `0xC072F800`, the ARMED
flag at `0xC072FA10`, and the hook armed last (banner `fpOGgate!`):

    ./build_gated_autorun.py --firmware /path/to/MAIN_c0000000.bin

RAM-only, reverts on power-off (battery out), same as the test build.

## Files
- `rowpatch_gated.S` — the r5-gated canvas hook.
- `build_gated_autorun.py` — builder (mirrors build_test_autorun.py).
