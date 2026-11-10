# First-frame RAW DMA start at REC start (offline RE, 2026-11-03)

Status: offline only. No camera, USB shell or product code touched. [C] = code-proven (function @addr, decomp line), [I] = inference, [D] = measured from archived data in `validation/20261103-first-frame-purple*` and `validation/20261103-defect-virtual/live`.
Scratch scripts (not in repo): scratchpad `shift1.py`, `period.py`, `prefix_match.py`.

## 1. Stock movie start sequence

Call chain [C]: CinemaDNG REC start `FUN_c0378a50` (blk_c03.c:82818) copies the 0x1B0-byte descriptor template `DAT_c0b99d90`, fills +0x14 = mode (ctx+0x60), +0x18 = bit format (ctx+0x30), +0x20 (ctx+0x50), +0x30 = RAW dest (ctx+0x4C), then calls `FUN_c030cf98` → `ContSet_Adr1` @c031be60 (logs `Start_Cont_s` … `Start_Cont_e`).
**So ContSet_Adr1 is the movie path, not only stills continuous.** In ContSet_Adr1, `param_2 = desc - 8`, so +0x1C = mode, +0x20 = format, +0x38 = dest.

ContSet_Adr1 order [C, blk_c03.c:19730–20216]:
1. If the current mode differs → `SetImgMode_s` @c0313400 → `FUN_c0314708` (tables, R10/receiver window) + `FUN_c03149b0` (sync generator start `FUN_c0126560(0)`, link retrain vtable+0x5C, **sleep max(desc+0xB0 = 3 ms, ceil(readout_start))**, receiver enable `FUN_c0635e38`, second DCLP write). The sensor `0x0011` 0→1 write comes from `XC_ImageSensorIMX410::v16` @c0324f40 (IMXB lr 0xC0324F54/60).
2. Geometry from `FUN_c04370e8` (local_124: [0],[1] = output w/h, [0x12],[0x13] = rec RWZM ratio, [0x14],[0x15] = rec hbin/vbin). Centred crop offsets `local_e8/e4 = ((META_w,h(0x77)/bin·0x400/rwzm − out) >> 2) << 1`.
3. BUFA selector `FUN_c031d988` → `XC_ImageSensorIMX410::v37` @c0325228. **Rec RWZM ≠ 0x400 and LV RWZM = 0x400 → BUFA1 only ("CrctRwzmToBufA")**. Rec RWZM = 0x400 → BUFA0 (Crmf tap).
4. **Shutter branch** (desc shutter ≠ current): loop {wait for VD event (`FUN_c01269a8`, flag DAT_c2f14a1c)} until frame counter `0x30100588&0x7FF` == TG target `0x30100048[26:16]`, then `FUN_c0319ea0` (→ v13 → `FUN_c03257b0`: SHS = sensor 0x0005/0x0006, plus 0x0007/0x0008 = 0), then sleep max(3 ms, readout_start).
5. **Arm-timing guard** (the only "wait" before arming):
   `elapsed = frame_time·line_ctr(0x30100590[29:16]) / (VMAX−1)`, `need = max(desc+0xB0·1000 = 3000 µs, readout_start)`.
   If elapsed ≤ need, sleep (need−elapsed)/1000+1 ms. If frame_time − elapsed < need (checked with the **stale** pre-sleep elapsed), wait 1 VD and sleep max(3, ceil(rs)) ms.
   - frame_time = `FUN_c0321160` = (TIM HMAX·(VMAX−1)+tail)·1000/72000 µs.
   - readout_start = `FUN_c032ca20` = R14+0xD · (TIM y0 + META+0x5C)·frame_time/VMAX.
6. BUFA1 programming [C]:
   - `FUN_c0630fa0`: reset pulse 0x30000804 bit1.
   - `FUN_c0631c08(100)`: **immediate** stop that clears 0x30182004 bits 2/3. Only a non-1/2/100 argument gives the frame-aligned stop, which checks 0x3010058C bit12.
   - `FUN_c0630d08(fmt)`.
   - `c06340c8(2,{0})` then `c06340c8(2,{1,0…})`: toggles the 0x300F0004 bit12 crop enable live.
   - `FUN_c06319e0`: crop x0/12, (x1+11)/12, y0|y1, x%12 into 0x300F0680/684/68C. kind = 1 whenever either RWZM axis ≠ 0x400. Then `c0630bf0`: 0x30182210 = height (y1−y0 − exclusion), 0x30182220 flags.
   - `FUN_c0631b98(dest)`: 0x30182280 = phys>>2.
   - `FUN_c0630e90(w, fmt)`: line words 0x30182214 = w·3/8 (12-bit), chunk 0x30182218 = ceil-split into ≤0x3F8-word chunks.
7. Start: `FUN_c0631c08(1)` → 0x30002060 |= 0x10, **0x30182004 = 4**. This is the single start for the whole recording. No VD wait, no frame counter and no "skip N frames" is tied to the start.
8. After the start: a gain branch with the same VD-count loop, then per-frame callbacks are registered, then `Start_Cont_e`.

Later frames [C]:
- BUFA1 IRQ: 0x30182048 bit4 → `FUN_c0630d60` → callback `FUN_c031bca0` ("Bufa1Int_Adr") hands the slot address to AcqInThr.
- The next buffer goes through `Cont_Pause` → `FUN_c0631b98(next)` only ("ContSet_Mem1"). Crop, line length and height are **never reprogrammed**, so the shared registers are not wrong for frame 1 only. Frame 1 differs only by start-up transient state. [C structure → I conclusion]
- Exactly +1 row with the last row missing fits BUFA1 counting a fixed 0x30182210 lines: one extra leading "line" pushes the last real line out. [C register / I behaviour]

Timeline from the bus logs [D]:
- REC-start writes at 0x0011, then SHS/AE at +0.14 ms and at **+4.0–5.1 ms** (the 3 ms sleep plus tick jitter).
- **SHS only at +133.9 ms** (≈ 4.01 frames; it matches step 4's VD-count exit, I).
- Per-frame AE (v10) from +167.9 ms at the frame period. The arm is therefore probably at about +137–168 ms, around frame 4–5 after the restart. [I]

## 2. Per-mode inputs and how they compare

| | stock 106 | 12v2 (230) | 1×1 key1 (231) | 14v2 (231) |
|---|---|---|---|---|
| first frame bad | 0/9 | 10/11 (+8/8 windowed) | 3/14 | ~all (33/33, 4/4) |
| HMAX / VMAX / tail | 445 / 5398 / 735 | 445 / 5399 / 445 | 445 / ≈5399 (AE cadence 33.46 ms, same as 106) | 911 / 2638 / 911 |
| frame time | 33.37 ms | 33.37 ms | ≈33.4 ms | 33.38 ms |
| TIM y0, META+0x5C (=2·v016) | 172, 70 | 20, 70 | 40, 70 | 20, 70 |
| readout_start | 1.50 ms | 0.56 ms | ~0.8 ms | 1.14 ms |
| guard `need`, post-switch sleep | **3 ms / 3 ms** | **3 / 3** | **3 / 3** | **3 / 3** |
| R10 (FE clock) | 6 (48 MHz) | 3 (96) | 3 (96) | 2 (42.7) |
| rec RWZM h/v (≈) | 1600/1600 | 2048/1024 | 2048/2048 | 2048/1024 |
| BUFA | 1 | 1 | 1 | 1 |
| out w → line words → chunks | 1936 → 726 → **1** | 3024 → 1134 → **2** | 3024 → **2** | 3024 → **2** |
| RWZM initial phase (`FUN_c0633e60`) | 0xE0 | 0 | 0 | 0 |

Notes on the table:
- Stock 106 DNG is 1936×1090 from META 3032×1708, so its rec RWZM is about 1.56. By v37's rules it records through BUFA1, the same engine as ours. The FP3K native trace also shows stock UHD24 on CrctRwzmToBufA. [C rules + D size → I]
- The y0 and v016 values come from `core_data.h` (`cd_base_y0`, `cd_ro`).

**The frame-time hypothesis is contradicted.**
- 12v2 has the same HMAX and VMAX as stock 106 (445/5399 vs 445/5398) and the same frame period. The 1×1 dark set ran at the same 33.4 ms cadence.
- Every firmware wait (the 3 ms guard, the post-switch sleep and the VD-count loops) evaluates identically for all four modes, because readout_start < 3 ms everywhere. [C formula + table values]
- Rates still go 0% / 21% / ~100%.
- The bus timeline is identical within about 50 µs at +133.9 and +167.9 ms for good and bad takes. The only jitter is the +4–5 ms tick, and it does not correlate with the outcome: good 4.01–4.92 ms, bad 4.08–5.04 ms. [D]

## 3. Candidates, ranked

1. **Start-up transient line into BUFA1 from the live RWZM/crop path, reprogrammed mid-stream.** [I, best fit]
   - Evidence [D]: row 0 of bad frames carries 12–48 px of data, then stale DRAM. In 9 of 23 bad bus takes (t02, t04, t05, t09, t16, t19, t28, t30, t31) the first 48 px are an **exact 4× repeat of one 12-pixel (18-byte) group** (t02: 472,384,476,386,473,381,470,378,464,381,473,381 ×4). Real sensor data cannot repeat noise-exactly. 12 px is the front-end word size (0x3010000C/0x300F0680 work in 12-px words).
   - The prefix does not consistently match any row of frame 2. This argues against "DMA caught the tail of a real line of this frame".
   - Mechanism [C]: the RWZM ratio (selector), crop window/enable, reset and immediate stop are all written while the sensor is streaming the new mode. BUFA1 then counts the short line as row 0.
   - Possible per-mode discriminators [I]: rec vertical RWZM 1:1 with horizontal 2:1 (unique to the ~100% group), output line split into **2 chunks** (all ours, not stock), RWZM phase 0 vs 0xE0, and the crop x%12 alignment (stock x0 = 2 / x1 = 1938 unaligned; ours 0/3024 aligned).
   - Duty-cycle model [I]: chance that a line is in flight at the random arm phase. 1×2 ≈ 85–93%, 1×1 about half (v 2:1). This ranks ours as 1×2 > 1×1. Stock 0/9 still needs a separate factor (1 chunk/line or a different RWZM phase).
2. **Sensor first frame after restart in vertical-add modes emits a short extra row** (the original sensor-side idea). [I] It fits 1×2 ≫ 1×1, but stock 106 also vertically adds (2×2) and is 0/9. The 12-px replication points to a SoC word path more than the sensor.
3. **R10 / FE clock.** [I, weak] 12v2 (R10 3) and 14v2 (R10 2) are both ~100% while 1×1 (R10 3) is 21%, so R10 alone does not separate them.
4. **Frame time / VD wait / skip-N-frames.** Ruled out by §2. [C + D] No software skip of the first frame exists in ContSet_Adr1. [C] The downstream AcqInThr/CDNG writer was not traced.

## 4. Cheapest checks that would tell these apart

Offline:
- Run ContSet_Adr1 under the existing unicorn harness (or the FP3K native-trace fixture) with stock-106 vs 230/231 descriptors. Log every write to 0x300F0004/0680–068C/0900–090C and 0x30182200–2224/2280, and confirm the chunk, alignment and RWZM-phase differences listed above.
- Re-run `period.py` on all bad frames, including 14v2/dark, to count 12-px exact-repeat prefixes.

On camera (describe only; not run):
- (a) Stock UHD CinemaDNG ×10. It uses BUFA1 with 3840 px = 1440 words → 2 chunks/line and RWZM ≈1.58. Any +1 points to chunk/width; 0/10 points to the vertical-RWZM/our-config side. No sup needed.
- (b) A SensorLab 12v2 variant whose output is ≤1016 words (one chunk, for example RWZM h 3:1 → 2016 px) with v still 1:1. This isolates chunks from vertical 1:1.
- (c) A read-only hook at `FUN_c0631c08(1)` entry and at the first `FUN_c031bca0`. Log 0x30100590 (line), 0x30100588 (frame), 0x3010058C bit12 (frame active), 0x301821E0–F8 (DMA status), 0x300F0900–090C, and a 64 B digest of dest rows 0/1. Compare good vs bad. If row 0 is already short at the first completion, the cause is acquisition; also look at the arm phase relative to the line.
- (d) Mitigation experiment only, for Bei to decide: start BUFA1 right after a VD, or reprogram RWZM/crop before the sensor restart.
