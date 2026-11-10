# REC-start delay sweep (TEST build only, 2026-11-07, offline: not run on the camera)

Question (Bei 11-07): a SensorLab UHD 48p recipe shows the first-frame purple (frame 1 one row down) without Gyro2
on the card but not with it; 1×2 is purple either way. Hypothesis: the error depends on the phase at which the
first frame is armed. Test: delay the REC start by N ms right before ContSet_Adr1 and sweep N.

## What the TEST build does

- Hook `0xC0379180` `bl FUN_c030cf98` (stock `EBFE4F84`) in `FUN_c0378a50` (CinemaDNG REC start). `FUN_c030cf98(r0, r1, r2)`
  copies the 0x1B0-byte descriptor and calls `ContSet_Adr1` (mode switch, VD waits, BUFA1 arm and start). Three register
  arguments, no stack arguments. The caller uses only r0 afterwards.
- The hook: t0 = tick, then `FUN_c03705d8(N)` if N > 0, then t1, then the original call, then t2. It returns the original r0.
  `FUN_c03705d8(ms)` is `tk_dly_tsk(ms)` (`0xC01F89C4`) that asserts on an error. ContSet_Adr1 uses the same call, in the same thread, for its
  "sleep max(3 ms, readout start)". N is clamped to 200 ms.
- N = 0 calls no sleep and passes the arguments and return value through unchanged. It still writes the timestamps into the ring.
- It applies to **every** CinemaDNG REC start (stock modes too), so a stock take can serve as the control.
- Claimed like the other apply hooks (SL_EXCL, journalled, the loader writes the stock word back at power off). Test
  build: 1 claim more than the product in `LOAD.LOG`.
- Owner check: no sup in the tree claims `0xC0379180`. **Correction to the brief**: the current Gyro2 (GYR2 0.2.1,
  `projects/gyro2-sup/src/gyr2.S`) does not hook `0xC03790B8`. Its sites are `0xC050D4C8` (CHAIN) and `0xC0125480` (EXCL),
  plus a firmware tag observer whose mode-2 call (`C0378F70`) runs inside `FUN_c0378a50` before `0xC0379180`. The
  `0xC03790B8` hook is the old logger card's (`fpSup/gyro/rec_trigger.S`). Either way, Gyro2 changes the REC-start timing
  ahead of this site.

## Builds (offline, 2026-11-07)

| build | command (in `qs/`) | file | sha256 |
|---|---|---|---|
| product 0.0.2test | `python3 -B build_slqs.py --out out` | `out/fpSup/SensorLab-IMX410_v0.0.2test.BIN` (206 272 B) | `c5c1ddad39e37b4d323516b9ba2e728fdf09f3c43c6b81de2dbfdc8ccb621220` |
| **TEST** (rec delay) | `python3 -B build_slqs.py --rec-delay-test --out out-rec-delay-test` | `out-rec-delay-test/fpSup/SensorLab-IMX410_v0.0.2test.BIN` (207 144 B) | `32d9293bf8083d378a59afc28454afe11430cfece8bdb1f0bf14e88b9cbf415c` |
| container | `cd ../../qs-container && python3 -B build_qsct.py --out out` | `out/fpSup/QS-Share_v0.0.2test.BIN` | `4939f399abb21076576dcb337d2ba8b6e66ad8375868f37e97aa976485e372b2` |

- **Both SensorLab files have the same name.** Only the directory tells them apart. The builder refuses
  `--rec-delay-test` unless `--out` names a `*rec-delay*` directory. Never copy the TEST BIN into a release or the merge page.
- Without the flag the build is byte-identical whether or not the TEST code is present: `#ifdef AP_REC_DELAY_TEST` only. Checked by
  building the same tree with the ifdef blocks stripped and the old `ap.c`/`ap.h`: same sha256 `c5c1ddad…`.
- The TEST build's `out-rec-delay-test/build-0.0.2test.json` has its own `sq_test_off` (`0x9D69`). Never use the product json with it.

## The delay word and the ring

`block` = the SensorLab line of `LOAD.LOG` (`0A <block> <claims> SensorLab-IMX410_v0.0.2test.BIN`). Offsets are from
`out-rec-delay-test/build-0.0.2test.json` → `rec_delay`. Each `rec_delay.base_off` equals `state_off`: `struct ap_rd`
is the first member of the client's state. A unicorn test checks this against `sq_test 49`.

| what | address | |
|---|---|---|
| `magic` | block + `0x32940` | `0x594C4452` "RDLY" once attached at boot |
| **N (ms)** | **block + `0x32944`** | host-written. `mem set` before the take, then read it back (`mem set` can drop a write). 0 at every boot |
| `ver, n` | + `0x32948`, + `0x3294C` | 1; REC starts seen |
| `sleeps, clamped, rec_words, nmax` | + `0x32950..0x3295C` | |
| ring | block + `0x32960`, 16 × 48 B | record `(n − 1) & 15` is the newest |

Record words: `seq, ms, t0, t1, t2, rc, line0, line2, arm_us, arm_line, ff, pad`.
- t0/t1/t2 are tick µs (`FUN_c002b6e0`) at entry, after the sleep, and after `FUN_c030cf98` returned.
- line0/line2: `0x30100590` (TG line counter, decode `[29:16]`).
- arm_us/arm_line: the first-frame arm in ContSet_Adr1, the same instant the existing trace (`sq_test 33`, record 0) logs.
  SensorLab modes only; 0 for stock.
- ff: the existing first-frame sentinel check at the frame's writer arrival. 1 = shifted (row 0's end never written), 2 = written,
  0 = not checked (stock mode, or no arrival yet).
- arm − t1 is the delay from the end of our sleep to the BUFA1 arm. arm − t0 includes N.

## Proposed live protocol (not run; follow AGENT_BRIEF "Live rules": broadcast first, no USB while recording, 12 s after a stop)

1. Card: the TEST BIN (from `out-rec-delay-test/`), QS-Share 0.0.2test, **no Gyro2**, everything else as for the
   11-07 observation. Reboot with `ui_drive.py reboot`. Read `LOAD.LOG` for `block`, then check the magic word.
2. Recipe A: the UHD 48p recipe that showed the purple (frame 20.8 ms). For N in **0, 5, 10, 15, 20 ms**, record about
   **5 takes each** (2 s each, `fpSup/fp_usb_shell/rec_take.sh` / `run_checklist.py`'s `rec` step). Interleave N
   (0,5,10,15,20, 0,5,…) so drift does not line up with N. Per take:
   - idle: `mem set block+0x32944 N` and read it back;
   - record; wait 12 s;
   - `mem get block+0x32940 0x320` (the header and the ring) → seq/ms/t0/t1/t2/arm_us/ff;
   - optionally the full trace: `validation/20261104-first-frame-trace/read_trace.py` (sq_test 33, with the TEST json);
   - fetch frames 1–2 of the clip. Frame-1 shift: the `SHIFT` snippet in `validation/20261103-first-frame-purple/takes.py`
     (`dy=1` = purple), or `validation/20261103-first-frame-purple-review/audit_rows.py`. DNG sanity: the mod-4 / bits
     check of `tools/live/run_checklist.py` (`dngcheck`) and a colour preview.
3. Recipe B: 1×2 (the 12v2 recipe, purple even with Gyro2), the same sweep.
4. Controls: a few takes with Gyro2 on the card and N = 0, to reproduce the 11-07 observation with this build, and one
   stock UHD take (ff = 0, DNG shift only).
5. Read the result as a table of purple rate per N and recipe, against (arm_us − t1) and arm_line. If the rate changes with
   N, the phase hypothesis holds and Gyro2's effect is a timing effect. If it stays the same, timing is ruled out for this
   window.

Risk notes: the sleep runs in the REC-start thread before the sensor and DMA start, at most 200 ms. Audio starts just
before this site (`XC_AudioRecorder::Start`), so audio leads video by N more ms. The file content is otherwise
unchanged. Never send USB during a take.

## Offline evidence

- `apply/test_apply.py RecDelayTests` (9) checks: the image words at the site and in the sleep wrapper; the product never claims or
  touches the site; the TEST build claims it (one more claim) through a cave veneer; not attached = straight down;
  N = 0 = no sleep, same arguments and return value, t0 = t1; N = 7 sleeps 7 before the call, t1 − t0 = 7 ms; clamp 200; ring
  wrap; arm and ff of a shifted / written first frame land in the record; a stock take has no arm. 9 mutants, all caught.
- `qs/test_slqs.py RecDelayBuild` (2) checks on the real loader: the product leaves the site stock and outside the journal; the TEST
  build hooks it, journals it, attaches at entry (RDLY, N = 0), `sq_test 49` = block + json `base_off`, and power
  off restores the stock word. 2 mutants (attach removed, json offset), both caught.
