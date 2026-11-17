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

## 22:40-00:30 — small rasters compressed: Lossless 0.3.6test (test build), 0.3.7test

Bei: do B; lens cap off (room light, static scene).

**The prediction, measured on 0.3.5test with light** (`lit035/`, compressed frames of 40):

| recipe | ISO 100 | ISO 3200 |
|---|---|---|
| 1024x1024 (s-12---RWZM) | 40 | **0** |
| 1312x874 (s-3x3---11) | 40 | **0** |
| 1968x1312 (s-2x2---11) | 40 | 40 |
| 1024x678 (s-12v2---RWZM) | 0 | 0 |

So with noise or detail the engine refuses 1024x1024 and 1312x874 too, as the 1 MiB rule says.

**0.3.6test** (never committed; `build036/`): a take whose told length is under 2 MiB gets one output buffer a lane
of raw + 1 MiB (class 10, the frames' allocator) instead of the spares; the engine is told raw + 1 MiB
(`destination_margin`, codec_job) so its limit is one raw frame and the stock 1 MiB stays behind it in memory we
own; the payload is copied into the frame's own raster (the copy-back path). Takes of 2 MiB and more swap as before.
- `lit036a/`: 1024x678 ISO 3200: 40 of 40 compressed, engine refused 0, 62 margin jobs.
- `lit036/`: 1008x662, 656x426, 1024x678, 1968x1312 all 40 of 40 at both ISOs; **1024x1024 ISO 3200 36 of 40,
  1312x874 ISO 3200 27 of 40** (`lit036b/`: 20 of 64 frames "both lanes busy", each lane starting a job every
  123 ms = 3 frame periods, engine job 8.2 ms). The CPU copy through the uncached alias (about 70 MB/s, 44.9 ms
  for an FHD frame, BUFFER_RESEARCH.md) held the arrival side so long that frames came in bunches.

**0.3.7test** (`build037/`, sha256 0464758b4d65869d): the payload copy is the firmware's DMA copy C00FBB90 (the
one the swap moves the header with); the CPU copy only if it refuses.
- `lit037a/`: 1312x874 ISO 3200: **40 of 40**, both lanes busy 0, 61 DMA copies, 0 refused, lane B not needed.

Steadiness on the lit scene: several takes fail the 0.15 DN12 step gate (1 to 8 frames of 40) -- the same takes
fail it uncompressed on 0.3.5test (s-12v2---RWZM ISO 3200: 8 of 40 both times), and compressed and uncompressed
frames follow the same curve (s-12---RWZM ISO 3200: scene drift 489..511). Read as room light / scene, not judged.

Offline: test_frame_hold 234 OK (MarginTests, MarginLaneTests, 6 margin mutants; the copy-back tests now ask for
the DMA), test_codec_job 48 OK (5 margin tests, 5 mutants), test_card_emulation 34 OK, test_v4_lossless 10 OK,
test_tile_grid, test_rec_workspace, test_rec_hook OK.

## 11-18 00:30-02:10 — full acceptance on Lossless 0.3.7test, lit scene (`accept037/`, `accept037.log`)

80 takes (40 recipes x ISO 100 / 3200), lens cap off, static lit scene, SD.

- decode: every fetched clip decodes; fresh: no repeats in any take; no take with a flat row.
- compressed, against 0.3.5test (`accept035.log`, dark): every RWZM recipe that was 0 of 40 is 40 of 40 at both
  ISOs, except the late-data ones, which stay 0 by design: f12v3 (1:1 and RWZM), 3x3fast (1:1 and RWZM),
  f12h2v3 RWZM, 3x6fast RWZM (status after a 3x6fast take: "late data: YES", found on the first frame).
- 1 of 80 with no clip: s-3x6fast---RWZM-iso3200 (A001_296, 0 frames fetched). Recorded again alone
  (`lit037b/`): 40 frames, passes. Cause not found (not reproduced once).
- steady: 26 takes fail (1-16 of 40 frames step > 0.15 DN12), all but two at ISO 3200, on compressed and
  uncompressed takes alike (f12v3 1:1 ISO 3200, 0 compressed, fails too). Read as the lit scene, as before;
  NOT proven -- this check was made for a capped lens.
- s-14---11-iso3200 (6048x4040 14 bit): 16 of 40 compressed here, 28 of 40 in the dark run. Not looked into
  (a lit scene compresses less and takes longer; this format is not touched by the small-raster path).
- black: not judged (not dark).

Not tested: compressed = uncompressed bit for bit; the steady check with a controlled light; SSD; long takes;
playback in camera; DaVinci; the 0.3.7test dark run (black level) -- the last dark run is 0.3.5test.

## 11-18 — dark acceptance on Lossless 0.3.7test (`dark037/`, `dark037.log`; one trial take in `dark037a/`)

80 takes (40 recipes x ISO 100 / 3200), lens cap on, SD.

- 79 pass. decode: every fetched clip; fresh: no repeats.
- steady: largest frame-to-frame deviation 0.011 DN12 (gate 0.15).
- black: largest |mean - tag| 0.258 DN12 (s-2x2---11-iso3200); largest channel spread 0.422 (s-12fastW---RWZM-iso3200).
- compressed: 0 of 40 only on the late-data recipes (f12v3 and 3x3fast, 1:1 and RWZM; f12h2v3 RWZM; 3x6fast RWZM);
  every other RWZM recipe 40 of 40. The large 1:1 / full-height recipes are partly compressed as in the 0.3.5test
  run (for example 28 of 40 at 6048-wide 1:1, about half at full height).
- the 1 failure: s-12fastW---11-iso100, 0 frames fetched. This recipe keeps 1-2 frames on SD (known; the same take
  failed the same way in accept035.log) and the tool reads from frame 2. Not a 0.3.7test change.
- s-3x6fast---RWZM-iso3200, which gave no clip once in the lit run, has 40 frames here.

Not tested: compressed = uncompressed bit for bit; SSD; long takes; playback in camera; DaVinci.
