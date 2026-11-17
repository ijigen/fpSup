# 2026-11-17 — Lossless 0.3.2test + Sensor Lab fast AD x V3 1:1: stale frames. Lossless 0.3.5test

Follows validation/20261117-clamp-all/LOG.md (the recipes that failed there pass with Lossless OFF).

## What was wrong (measured, not guessed)
1. **APS-C 3952x874 (f12v3w2C) and 1312x874 (3x3fast), 1:1.** In these modes the firmware queues a CinemaDNG frame
   BEFORE its pixels are in the buffer. Evidence:
   - diag100/ (clip A001_100): frame 19's top 360 rows are byte-for-byte frame 14's compressed payload (found at file
     offset 82944 + 100 of frame 14), frame 20's are frame 12's; frame 18 is the same picture as frame 9.
   - take2/ (diag build 0.3.4test: arrival trace with two raster words sampled at the hook): for the frames that went
     out uncompressed, the word at the arrival is old payload bytes and the file has pixels -- the data landed after
     the arrival. Every compressed frame of the take is a stale picture: 8 = 1, 12 = 7, 14 = 5, 22 = 13, 24 = 16,
     25 = 20, 27 = 21 (each "U" frame's buffer came back as a later compressed frame), the rest carry an earlier
     payload on top.
   - take1/ (0.3.3test trace): frame records, handles and the spare are all consistent (no double owner); event kind
     05 comes 1 ms before the arrival; no later per-frame event marks the data.
   - Lossless OFF: no repeats, files right (the stock writer reads the buffer a frame later).
   Why these two modes and not 12v3 / f12v2 / 2x2fast: not known. All run at 23.976 fps (vmax 9101 at hmax 330).
2. **SQ 1024x1024 with 512x512 tiles.** The stream is right (scratchpad ljpeg.py, an independent SOF3 decoder: no
   empty rows, all bits used). LibRaw's lossless_dng_load_raw takes "2 components and 2 x tile width == image width"
   as one row holding both halves and misplaces the rows (LibRaw row 2k = our row k; rows 1, 3, 7, 11 ... empty).

## Lossless 0.3.5test (fpSup/lossless: native/frame_hold.c/.h, native/card.c, native/tile_grid.h)
- Late data: the take's first frame (never held) is sampled when it arrives and when the next arrives; each held
  frame's source is sampled at admission and when its job is collected. A change = the pixels came after the arrival:
  that result is dropped (the frame goes out as it is), `late` is set and nothing more is held that take.
  So those takes are recorded UNCOMPRESSED and right. Compressing them (start the job one frame later) is not done.
- Tile grid: never a tile width that is half the image width.
- Offline: test_frame_hold 215 OK (26 new tests, 14 mutants caught), test_tile_grid 6 OK (1 new mutant), and
  codec_job / bulk_policy / header_tag / lossless14_roundtrip / card_emulation / v4 / v3 / frame_pipeline / control /
  menu_page / native_permissions / native_port / play_decode / producer_facts / raw_workspace / rec_hook /
  rec_workspace / record_diag / workspace_layout / direct_control_arm / frame_pipeline_arm / ui_control OK.
  test_native_variable: 25 errors ("'NoneType' object has no attribute 'BindingProbe'") -- not looked into; whether
  it ran before this change is not known.
- Card: build035/ (sha16 c2b58dab508f047a), LOAD-035.LOG. 0.3.3test / 0.3.4test on the card are the diagnostic
  builds (skipped as older).

## Live on 0.3.5test + Sensor Lab 0.0.10test (lens capped, 3 s, 40 frames)
- accept035a: f12v3 1:1 and 3x3fast 1:1, ISO 100: pass, no repeats, no garbage, 0 of 40 compressed. Lossless status:
  late data YES, found by 1 (first-frame probe), frames not held 65, results dropped 0.
- accept035b: the 4 smoke recipes, ISO 100: pass, no repeats; 9/18, 15/30, 24/40, 21/35 frames compressed (the rest
  "both lanes busy"); late data no, probe compared 1.
- accept035: the 36 non-16:9 strata x ISO 100 / 3200 -- see accept035.log.

## Not tested / not covered
- Data landing after the collect (a frame collected at stop sooner than one frame period) is not caught.
- A static scene whose 16 sampled words do not change is not seen as late (and is then compressed stale = the same).
- Lit scenes, long takes, SSD (write timing differs: the first-frame probe is skipped when frame 1 is already
  written), MOV, playback of these clips on the camera, DaVinci Resolve reading the new 1024-wide tile grid.
- Whether other recipes have late data at other frame rates.

## 21:30 — full acceptance on Lossless 0.3.5test + Sensor Lab 0.0.10test

`accept035/` (`accept035.log`): the 36 non-16:9 strata + 4 smoke recipes, ISO 100 and 3200, lens cap on, SD card:
**80 takes, 0 failing** (clip, decode, steady, fresh, black). Largest frame-to-frame deviation 0.011 DN12;
no repeated frames; no flat rows (SQ 1024x1024 through RWZM now reads right in LibRaw: 40 of 40 compressed).
`s-12fastW---11` (6048 wide, 12-bit fast, 1:1) keeps 1 frame on this SD card: steadiness not judged there.

Compressed frames per take: 40 of 40 in 20 takes, partly in 14, **0 of 40 in 44 takes**:
- 4 takes are the two late-data recipes (f12v3 1:1, 3x3fast 1:1): intended, see above.
- 40 takes are RWZM outputs other than 1024x1024. One checked on the camera (`rwzm-check/`, s-12v2---RWZM,
  1024x678 12-bit): late data **no**; the hardware engine refused all 62 held frames (wait pattern bit 4,
  "output would not fit"), codec job 2.3 ms.
- Not this version's tile change: with the grid forced to 512x352 (the grid before today) and to 256x352
  (`force_grid.py`, `rwzm-force-*/`) the engine refuses every frame the same way. And on 0.3.2test
  (`../20261117-clamp-all/accept-nonhd.log`) these takes read back clean in LibRaw at a grid that would have
  been two tiles across, so they were not compressed then either.
- Cause not known. The files are correct (uncompressed); only the saving is missing. OPEN.

Not tested: lit scenes, long takes, SSD, in-camera playback of these clips, DaVinci on the new 1024-wide grid,
`native/test_native_variable.py` (25 errors, not investigated, not known whether older than this change).

## 22:20 — why the small RWZM outputs are never compressed (offline, firmware reading)

The takes with 0 compressed frames are exactly the small rasters: 1024x678 (1,041,420 B), 1008x662, 656x426.
The smallest that compresses is 1024x1024 (1,572,864 B).

Firmware: `FUN_c062f5a8` (F_INIT) sets the destination length to align_kib(bits x w x h / 8) -- the raw size.
`FUN_c062fff8` (the engine set-up) writes the output limit register
`300D0090 = (dst + dst_len + 0xBFF00000) >> 10`, where the other address registers use `+ 0xC0000000`:
**the engine's output limit is 1 MiB before the end of the room it is told.** So

    room = raw size - 1 MiB

- raw size <= 1 MiB: room <= 0, every frame is refused at once (codec job 2.3 ms where the model gives ~9 ms).
  This is 1024x678, 1008x662, 656x426: 40 of the 80 takes.
- Prediction, NOT measured (lens cap on): a frame is also refused when its compressed size > raw - 1 MiB.
  1024x1024 12-bit: refused above 33 % of raw; 1312x874: above 39 %; 1968x1312: above 73 %. A lit scene
  usually compresses to 50-65 %, so the first two would probably not compress in real use either.
- Not known: whether the limit is exact or the engine can run past it (why stock keeps 1 MiB).

Ways out (not done; makes formats compress that did not -- Bei decides):
- B (keeps the stock margin): for small rasters, do not swap; encode into an own buffer of raw + 1 MiB and copy
  the payload into the frame (the non-swapping path exists). Cost: 1 MiB per lane, one copy of < 1 MB per frame.
- A (no memory, no copy): tell the engine length + 1 MiB so the limit lands on the true end. Only after
  measuring on the camera that the engine never writes past the limit.
