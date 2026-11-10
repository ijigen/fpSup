# v0.7.28test: the firmware's own sensor pause / resume + link resync at REC start (offline, 2026-11-04)

Status: **offline only**. I did not touch the camera, the USB shell or fpshd. The build is not deployed.
This is option B of `notes/FIRST_FRAME_SENSOR_RESET.md` §2, chosen by Bei after the v0.7.27test live trace showed
the shift is already there at BUFA1 completion (capture side).
[C] = code or emulation of the real image. [I] = inference.

v0.7.28test is v0.7.27test plus one hook. **The trace and the sentinel are unchanged**, so the same live procedure
measures the effect.

## What v27 does [C, decomp `blk_c03.c` 25410 + ARM]

`XC_ImageSensorIMX410::v27(obj, suspend)` at C0325110 is reached through the imager's vtable, `*(obj+0xD0) + 0x74`.
The IMX410 table at 0xC0B5FCC0 holds C0325110 in that slot.

- **Guard.** It does anything only when `C0125CA8() > 15000`.
  - `C0125CA8` returns the frame period in µs, computed from the live TG HMAX/VMAX/tail.
  - So v27 is a no-op above about 66.7 fps: 100 and 119.88 fps never get it, while 23.976–59.94 fps do (59.94 is
    16.7 ms).
- **Suspend (1):**
  1. `00CA=0`
  2. sleep 1 ms (`C03705D8`, an OS sleep)
  3. `0000 = shadow|2`, then the shadow is updated (`C0325840` / `C0325858`, shadow at C343B688)
  4. `00C6=1`
  5. `00C5=0x11`
  6. GPIO 0x544: configure (`C00FDCF0`), then drive 1 (`C00FE3A8`)
- **Resume (0):**
  1. `0000 = shadow&~2`, then the shadow is updated
  2. GPIO 0x544: configure, then drive 0
  3. sleep 12 ms
  4. `00C6=0`
  5. `00C5=0`
  6. `00CA=1`
  7. sleep 1 ms
  8. v21 at C0325078, the receiver link:
     - `C0128E68(0x29)` sets the forced flag;
     - `C0128D60(1,0)` sets 0x30100B00 bit 0, runs a ~210 µs calibrated busy delay (`C0000A08(0xD2)`), then writes
       0x30100B08 = 0xFF.
- **Sensor writes** all go through the common writer `C0322C70`. This build writes no sensor register directly.
- **The 0000 shadow mismatch.**
  - The imager init (v1, C03233D8) writes physical `0000=4` but sets the shadow to 0.
  - v27 then writes `0000 = 2` (pause) and `0000 = 0` (resume). Bit 2 is cleared from the first resync until the next
    v1 (sensor init).
  - The mode table (161 registers) does not write 0000.
  - Any native long exposure on the fp ends in the same state, so this is native behaviour, kept as is. But it is a
    lasting change that a later stock take in the same session also inherits. [C writes / I effect]
  - The alternative, setting the shadow to 4 first so the resume restores 4, would depart from the firmware and was
    not done.
- **Native callers.** The long-exposure loops (`blk_c03.c` ≈17437–17529, 18012–18036, 20370–20392, stop cleanup
  20549):
  - They suspend after a few frames of a long exposure, resume, then wait for one VD (`C01269A8`).
  - They run on the capture path's tasks, with the TG running and BUFA idle or waiting. They are never used at an
    ordinary mode set.

## Call point [C]

**Hook `H_RESYNC` at C031BF88**, the `bl SetImgMode_s(imgmode, mode)` inside `ContSet_Adr1`.

- `ldr r1,[r6,#0x1c]` at C031BF80 gives the record mode, and `ldr r0,[sp,#0x30]` at C031BF84 the image-mode object.
- ContSet_Adr1 calls it only when the record mode differs from the current one. A REC start always switches, from
  standby mode 8 to the record mode.
- After SetImgMode_s returns (its 161 writes, `0011=0→1`, the link retrain and the 3 ms sleep), and only when the
  mode is the live slot's id, it runs the native sequence, as the long-exposure loops do:
  1. `v27(1)`
  2. VD
  3. `v27(0)`
  4. VD
- `rs_last` records why a resync was skipped: 1 = frame period ≤ 15 ms, 2 = the imager's v27 is not C0325110. Neither
  case calls anything.

Why this point is safe:

- **Same task, same kind of work.** ContSet_Adr1 itself writes sensor registers (SetImgMode_s, the SHS write v13),
  sleeps (`C03705D8`) and waits for VD (`C01269A8`) in this very task, before and after this point. The added calls
  are the same kinds, in the same context. [C structure; I: no lock is held that ContSet's own sleeps would not also
  hold]
- **Before everything that arms BUFA1.** It runs ahead of the shutter branch, the arm-timing guard and the whole BUFA1
  block (reset, stop, format, crop, destination at C031C948, start at C031CAE0).
- **BUFA1 is not disturbed.** In the emulated REC start, the MMIO writes with and without the resync are compared
  with equal stubbed frame periods. The only difference made by the resync is the receiver link write:
  0x30100B00 = 0x100 → 0x101, then 0x30100B08 = 0xFF. **All 35 BUFA1/crop writes are identical.**
- **AE** (AeDev, per frame) keeps writing gain registers during the pause, as it does during native long exposures.
  [I]
- **Cost.** The REC start gets later by 1 ms + 1 VD + 12 ms + 1 ms + ~0.2 ms + 1 VD, about 47–80 ms at 29.97 fps.
  `resync_us` reports the real figure. [I]
  - **Whether audio starts before this point is not known.** Check A/V alignment live.

## Trace words 5–6

The v0.7.27test live run found that words 5–6 (0x30100588 / 0x30100590) are not frame or line counters: they read 0
and arbitrary values. The ring layout is kept unchanged, so the v0.7.27 baseline and this build stay comparable, but
`read_trace.py` now drops both fields from its output. Timing comes from epoch / raw (`t_us`).

## Status (`sq_test 17`, AP_ABI 3, now 41 words)

The new last three words are `resync_calls`, `resync_skips` and `resync_us`.

## Tests [C] (`apply/test_apply.py ResyncTests`, plus the existing FirstFrameTests)

All tests run the emulated REC start (`mmio_diff`: SetImgMode_s + ContSet_Adr1 with the apply hooks live). GPIO,
sleep and VD are recorded stubs; sensor writes are recorded in one ordered log.

- **12v2 and 1×1 12-bit.** After the last `0011=1`, the exact native sequence runs once:
  `CA=0, sleep 1, 0000=2, C6=1, C5=0x11, GPIO 0x544 cfg / =1, VD, 0000=0, GPIO cfg / =0, sleep 12, C6=0, C5=0, CA=1,
  sleep 1, v21, VD`. That is before the BUFA1 arm and the start.
  - `resync_calls = 1`. The 0000 shadow is 0 afterwards. The trace still arms.
- **Stock.** UHD30 (BUFA1) and FHD106, with no slot, and UHD30 with a SensorLab slot live but stock's mode recorded:
  no resync, no GPIO, nothing armed.
- **Frame period.** At exactly 15000 µs it is skipped (`resync_skips = 1`, no call) and the trace still arms; at
  15001 µs it runs.
- **Site words.** The SetImgMode_s call, the argument loads, v27 and the IMX410 vtable slot.
- **Mutants.** 7 new mutants in `MUTANTS` (#111–117), all caught: gate removed, guard off by one, halves swapped,
  either VD removed, resync before the mode switch, counter.

Runs:

- `test_apply` 79/79.
- `tools/test.py fast`: PASS.
- `test_settings_migration` + `test_slqs` Build / ApplyUnit: 15/15.
- `tools/test.py mutants --only apply`: 114 of 118 caught (`tools/test-logs/mutants-20261103-234535/`). The four
  failures are the known pre-existing "mutant text not found" entries (#48, 54, 56, 61), unrelated to this change.

## Build

- `default-build/fpSup/SensorLab-IMX410_v0.7.28test.BIN`: 188,988 B, sha256
  `ff734e5fc2387578a028c4578ae074ce2c0aaa2e3b2e371eae4c064cc330130e`, block 573,568 B.
- It is also in `qs/test-fixtures/settings-migration/frozen/`, with a README.txt entry.

## Live test plan (for Bei, not run)

1. **Setup.** Deploy, read back and compare the BIN, reboot, and commit through MENU. Note `sq_test 17`: `armed`, and
   `resync_*` all 0.
2. **12v2 ×10 and 12h2 ×10.** Use 29.97 fps CinemaDNG and 2 s takes. After each take, while idle:
   - run `../20261104-first-frame-trace/read_trace.py --load-log … --build default-build/build-0.7.28test.json`;
   - run `takes.py`, which gives the DNG dy.
   - Per take, record:
     - `resync_calls` (+1 per take) and `resync_us`;
     - the trace verdict;
     - arm → first completion time;
     - the DNG first-frame shift.
3. **Compare with the v0.7.27test baseline:**
   - 12v2 about 100 %;
   - 12h2 1/5;
   - stock UHD 0/29.
   - If the shift rate drops clearly, the pause / resume and resync matter. If it does not, the sensor-side standby is
     ruled out as a fix, and the receiver / crop start is next (§5 step 2).
4. **Controls.**
   - One stock UHD take: expect `resync_calls` unchanged and normal.
   - One 12v2 take at 119.88 fps (or any > 66.7 fps): expect `resync_skips` +1.
5. **Also check:**
   - A/V alignment of one take against v0.7.27test (the REC start is ~50–80 ms longer);
   - that standby LV and later stock takes look normal, since 0000 bit 2 stays cleared;
   - that the camera behaves normally throughout.

## Not verified

- **Whether a pause / resume clears whatever causes the first-frame line offset.** That is the experiment.
- Whether the VD wait behaves as in the emulator while the sensor is paused. The TG keeps running, and the native
  loops do the same. [I]
- The physical meaning of 0000 bit 2, of GPIO 0x544, and of `00C5` / `00C6` / `00CA`. Only the native order is
  reproduced.
