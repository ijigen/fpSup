# SensorLab-IMX410 v0.5.0test apply step, first live run, 2026-10-30 (apply1)

BIN `SensorLab-IMX410_v0.5.0test.BIN` 98 824 B, sha256 82f84a21… (out/build-0.5.0test.json), with QSContainer_v0.2.4.
Checklist: `projects/sensorlab-imx410/qs/README.md`, the last section "V1 上機清單".
Scripts in this folder: `apstat.py` reads the apply status with `mem get` only; `-s` adds the 26 sites and the clock word.
`qst.py` is a copy of live7 qst7.py. `shot.sh N tag` is the live7 script. `dngprev.py` makes the colour preview
(black level subtracted, AsShotNeutral WB, half-res, gamma 2.2).
Shots are `shots/NNNN-tag.jpg` (SS__2738..2762), and I looked at every one. No S1/S2 sent, no MENU pressed in a sub-QS,
no USB during recording.

## 0. Card and stock state before the run
- `card_backup/fpSup_dir_before.txt`, `LOAD.LOG.before`. RES-Custom is **not** loaded: there is no `RES-Custom_*.BIN`.
  Only an AppleDouble stub `._RES-Custom_v0.1.5.BIN` (4096 B) and the data folder `RESCUS\` (.RCD files) are left over.
  LOAD.LOG lists no RES-Custom. I carried on.
- Stock settings: CinemaDNG (Format 0), 12 bit, FHD (Size 2), 59.94 (Framerate enum 5), ISO 3200, SD.
  STILL slots 9 10 11 19 20 22 24 30; CINE slots 58 54 55 56 57 50 59 60.

## 1. Deploy and load: PASS
- `fl del \fpSup\SensorLab-IMX410_v0.4.0test.BIN` returned OK. `v3/deploy_v3.py card/` returned
  `OK \fpSup\SensorLab-IMX410_v0.5.0test.BIN 98824 B`, with a full read-back.
- I ran `ui_drive.py reboot` as a separate step; it was up in 11.0 s.
- `LOAD.LOG.boot1` has `0A C55F8200 0000001B SensorLab-IMX410_v0.5.0test.BIN`.
  The claim count is **0x1B = 27**; the baseline (v0.4.0test, LOAD.LOG.before) is 0.
- Status after boot:
  - magic 31504C53, abi 2, armed 1, svc C503B6C0, clk_ok 1, clk_open 0;
  - ap_mem C561C250, so block = C55F8200 (= LOAD.LOG);
  - callfn of the getter C0407E20 returned 1;
  - `sq_test(21)` (ap_init rc) returned **0**; `sq_test(20)` (pushes) returned 0.
- Entry at block+0x7110 is `E92D4FF0` (Thumb push.w), so the call address is +0x7111.

## 2. Hook sites: PASS
All 26 sites read `EA…` (B), or `EB…` (BL) for the K_BL sites. Each one goes to a trampoline at C072E120 + 8·i,
which holds `E51FF004 <veneer>`. The veneers are at C561C250 + 0x58·i, inside the block. `apstat.py -s` prints
`sites bad = 0`. The clock word 0xC0189440 = `2C49F241` (stock, gate not opened). I checked again after sq_test(22):
nothing changed.

## 3. First MENU after boot: the boot record was committed (observation)
- The first `MENU` (layout load → leave()) committed the selection that came with the BIN:
  - ap_sel was DC 6048×3402 / RES 2016×1134, key 23, hm 911, vmax 1319, 59.94, standby 1;
  - QS showed this as HD / 2K / 59.94 / 14b 1x3 (defaultPick).
- Result: active 1, cur 1, commits 1, lv_reloads 1, **commit_us 11 853**, carrier_sets 0
  (the stock rate was already 59.94).
- So SensorLab was live before step 4 began. This matches the design ("first leave() hands out the record").

## 4. Carrier rate: PASS
- Stock menu: 記錄設定 → 每秒幀數 → 24 fps (shots 2740–2742); Framerate enum 12. SensorLab was active at the time.
  The stock rate stayed 24 until the next push, then the first QS dial step set the carrier back
  (carrier_sets 0 → 1).
- QS steps (each dial step is one commit):
  - DC +1 = S35 (2745), −2 = **OG** (2746);
  - FPS stepped down to **29.97** (2747–2750; the list has many breakpoints: 52.619, 47.952, 41.267, 39.386,
    38.745, 37.140);
  - RECIPE stepped to **12b 2x3** (2757: `RS 8.59 ms · 2000×1320`, RES tile `2000×1320 · 3x3` yellow, MB/s 123).
  - The OG 2K recipe list runs 12b 1x1 … 11b 1x3. 12b 2x3 is near the left end; the default was 12b 3x3.
- After the last step:
  - result **0**, active **1**, cur **0** (→ mode 230), commits 38, refusals 0, lv_reloads 38, carrier_sets 4,
    clk_open 0, owed 0;
  - **commit_us 9 177 µs**;
  - handed-out ap_sel: `76 2 1 0 6048 4040 2016 1346 14 1 1 445 5399 2997 100 1 1 0 1`
    (OG, RES 2016×1346, key 14, hm 445, vmax 5399, 29.97, standby 1).
  - 72e6/(445·5399) = 29.9681 fps.
- Stock menu → 記錄設定 now reads **29.97 fps** (shot 2760). `menu SetMovFramerate` = 3.
- commit_us across all 12 reads: 8 908 – 27 030 µs (11 853, 27 030, 17 402, 10 204, 22 897, 10 144, 22 636,
  15 058, 8 908, 11 290, 16 067, 9 177). That is well under the 60–150 ms estimate.

## 5. Standby: PASS for the image; standby_picks stays 0 (deviates from the checklist)
- QS closed at 2758. LV is now **full-height 3:2**: no black bars, more scene at the top and bottom than the stock
  16:9 LV (2738/2743). No garbage, colours normal.
- Over 30 s, ping every 5 s: 6/6 pong (01:55:19–01:55:44). Shot 2759 at t+30 s is identical to 2758. No freeze.
- Counters while in standby: picks 224 → 3039 in about 30 s (≈ 94/s), lookups go up the same way, canvases 4 → 7.
- **standby_picks = 0 the whole run**, and picked = 1, not 0x101.
  - The standby LV picker is entered with the record route table AP_TAB3 and a key that matches the rate, so
    `H_PICK`'s first branch (ap.c:315-319) serves it with the record entry.
  - The `AP_TABS` "MOV" branch (ap.c:322-325) never ran.
  - So standby runs our record entry (mode 230/231), not `sentry`. The image is right, but the checklist's
    "standby_picks > 0" does not hold. Bei or the designer should say whether that is intended.
- 0xC343B590 read 0x0C in standby, before any take. It only reports the mode used once a take has run.
- Flicker: a screenshot cannot show it, and I did not look at the LCD.
  - Every dial step reloaded the LV (38 reloads).
  - The shell survived all of them, and every QS screenshot drew normally.

## 6. Record 3 s: PASS
- MOVON/OFF pulse, 3 s, pulse, then 10 s with no USB (same as rec_take.sh, but waiting 10 s instead of 5 s before
  the ping). Ping OK.
- The take is folder `\CINEMA\A001_261`.
- **0xC343B590 = 0xE6 = 230.**
- picks 7205, lookups 9641, canvases 351, recrates **1**, result 0: all > 0.

## 7. DNG: PASS
`dng/A001_261_000001.DNG`, `_000002.DNG`, 4 101 120 B each. Fetched by name; no `dir` of the take folder.

| Tag | Value |
|---|---|
| ImageWidth × Height | **2016 × 1330** |
| DefaultCropOrigin / Size | 8 5 / **2000 × 1320** |
| ActiveArea | 0 0 1330 2016 |
| BitsPerSample | **12**, Uncompressed, 4 021 920 B strip |
| FrameRate | **14400000/480511 = 29.96810** |
| Black / White | 256 / 4095 |
| CFA | RGGB |
| ExposureTime / ISO | 1/125 / 3200 (same as stock) |

- FrameRate:
  - the real rate 29.9681 is **64.5 ppm** below 30000/1001, so by the README rule (50 ppm) it is written as the
    reduced real fraction (72e6/2402555), not 30000/1001;
  - correct per the spec; the brief expected "29.97", and this is why it differs.
- Colour preview: `shots/A001_261_000001-preview.png` (and `_000002`). Real image, same scene and 3:2 framing as
  the LV, correct colours (white and grey cat, orange spot).
- Stats, frame 1:
  - R 283.2, G1 304.5, G2 304.5, B 281.0 (means, DN);
  - G1−G2 0.01; R/G 0.562, B/G 0.516;
  - no bad rows: the first rows are ≈ 284, the last rows ≈ 276.
  - Frame 2 is the same to within 0.2 DN.
- The scene is dim: about 50 DN above black.
- Stock reference from step 8 (`A001_262_000001_stock.DNG`, 1936×1090, same exposure): R 284.3, G 306.1,
  B 281.7; R/G 0.564, B/G 0.514. Levels and colour ratios are the same, so the dimness is the scene, not the readout.
- No isp-lab shell-path DNG of OG 2K 12b 2x3 exists: isp-lab/validation has only 1936×1090 DNGs. No comparison made.

## 8. Back to stock: PASS
- callfn `sq_test(22)` (0xC55FF311, r0 22) returned **0**.
- Then: active 0, result 0, lv_reloads 39, sites still armed (pass-through), clock word stock `2C49F241`.
- LV is back to 16:9 with bars (2762).
- 2 s stock take `A001_262`: **0xC343B590 = 0x6A = 106** (stock FHD 29.97).
  - The DNG is 1936×1090, crop 1920×1080, FrameRate 29.97002997.
- Stock frame rate stays **29.97** (enum 3). The revert does not restore the user's earlier 24, and at session
  start it was 59.94.

## End state
Standby LV, QS closed, ping OK.
- Stock: CinemaDNG 12 bit FHD **29.97** (was 59.94 at the start), ISO 3200.
- SensorLab inactive (active 0) and hooks armed.
- Card: QSContainer_v0.2.4 and SensorLab-IMX410_v0.5.0test. The v0.4.0test file is deleted.
