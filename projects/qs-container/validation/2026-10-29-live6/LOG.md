# QS Container v0.2.4 + SensorLab-IMX410 v0.3.0test live test 2026-10-29 (run 6, MB/s tile)

Shots: `shots/NNNN-tag.jpg` (NNNN = SS__NNNN.JPG, fetched by number with `shot.sh N tag`; every one viewed).
`2685-preexisting-old.jpg` was already on the card (someone else's shot, not this run); this run's shots start at 2686.
Reader: `qst6.py` = live5 `qst5.py` unchanged (container still v0.2.4 at B = 0xC55BC8C0).
Expected values: `mbps_expect.py` = recipes from `preview/gen_fps.py` case() (quality.py, tol 2 %), then the
v2 formula (notes/MBPS_TILE_RESEARCH.md v2 + §3/§5) redone in Python integer math; recording size = vis + 16 x 10.
Dials `fpsh "key CMDDIAL1 ±1"`. No S1/S2/MOV, no MENU in sub-QS.

## Deploy
1. 21:25 shell OK. `card_backup/fpSup_dir_before.txt`, `LOAD.LOG.before` (v0.2.4 @C55BC8C0, v0.2.2test @C55F8200).
2. `fl del \fpSup\SensorLab-IMX410_v0.2.2test.BIN` -> OK. `v3/deploy_v3.py card/` (full read-back):
   `SensorLab-IMX410_v0.3.0test.BIN` 75444 B (sha eb71a697...). OK. dir: QSContainer_v0.2.4.BIN 173888 untouched.
3. `ui_drive.py reboot` (separate step) up 11.6 s. LOAD.LOG (`card_backup/LOAD.LOG.boot1`): `QSC 00000000 C2DEAD7C`,
   `0A C55BC8C0 QSContainer_v0.2.4.BIN`, `0A C55F8200 SensorLab-IMX410_v0.3.0test.BIN`, rest unchanged. Before MENU all 0;
   after first MENU: result 0, phase 2, freeze 0, **N 6, recv 6**, qs_result 0, qs_ready 1, qs_vars 193, fresh 1. PASS.
   CINE after first MENU = 58 54 55 56 57 50 27 19 (slot record carried over this time: the container BIN was not replaced).

## Editor (SYSTEM p2 = MainY2 -> 自定QS)
4. Slot 7 COLOR (2689) -> OK: list now **38** items (was 37) (2690). RIGHT:22 -> 38/38 name strip `MB/s` (2691). OK ->
   editor tile 7 + name `MB/s` (2692). CINE = **58 54 55 56 57 50 59 19**. PASS.
   Ugly: the list icon and the editor tile for MB/s show the borrowed DC icon (same as RECIPE, live5 §4), no text.

## MB/s tile (medium SD UHS-II, A0 B0 / R0 M01 S3 every time)
5. QS open (first QS key: two LIBUSB timeouts on the screenshot keys, QS opened; retry OK). Main QS (2693): 8 tiles,
   MB/s in slot 7: big `210`, small `LL ~91` grey. Focus MB/s (2694, zoom 2694-footer-zoom.png): footer item 1
   `SD UHS-II` / `RAW 91% LL 42%`, item 2 `A0 B0` / `R0 M01 S3`. PASS.

| # | setting (DC / RES raster / recipe / fps) | tile big / small | expected big / small (duty RAW / LL) | shot |
|---|---|---|---|---|
| a | HD 6048x3402 / 2K 2016x1134 / 12b 2x3 / 59.94 | 210 / LL ~91 grey | 210 / 91, 91 % / 42 % | 2693, 2694 |
| b | same / 61.668 | 216 / LL ~93 | 216.4 / 93.2 (fps from the label) | 2695 |
| c | same / 90 | 316 / **LL ~184 yellow**, footer RAW 137% LL 83% | 316 / 184 yellow, 137 / 83 | 2696, 2697 |
| d | same / 12b 1x3 / 90 | 316 / 184 | 316 / 184 (same raster) | 2699 |
| e | same / **14b 1x3** / 59.94 | 245 / LL ~125, footer RAW 108% LL 55% | 245 / 125, 108 / 55 | 2702, 2703 |
| f | HD / 3K 3024x1700 / 11b 1x2 / 59.94 (RES +1) | 467 / LL ~325 yellow | 467 / 325 yellow | 2704 |
| g | S35 4192x2358 / 2K 2096x1178 / 14b 1x2 / 59.94 (DC +1) | 264 / LL ~138 | 264 / 138 | 2705 |
| h | S16 2096x1240 / 1K 1040x620 / 14b 1x2 / 59.94 | 72 / LL ~39 | 72 / 39 | 2706 |
| i | S16 / 2K 2096x1240 / **14b 1x1 (1x1 +1.5 bpp branch)** / 59.94 | 277 / LL ~177 yellow | 277 / 177 yellow | 2707 |
| j | HD / 6K 6048x3402 / 11b 1x1 / 48 (DC back) | 1485 / LL ~1369 yellow, footer RAW 624% LL 574% | 1485 / 1369, 624 / 574 | 2708, 2709 |
| k | HD / 2K / 14b 1x3 / 48 | 196 / LL ~100 | 196 / 100 | 2710 |

   All 11 equal. Tile updated on every DC / RES / FPS / RECIPE change. PASS.
6. Footer item 1 is wider than its focus box: `SD UHS-II` and `RAW 91% LL 42%` stick out on both sides (2694-footer-zoom);
   the small line is auto-shrunk at 3-digit duties (2697, 2709). Cosmetic.
7. Case j: 6K 11b 1x1 compressed frame 16.8 MB > 16 MiB — research note §6.5 says lossless refuses such frames and the
   tile should show `—`; the tile shows `LL ~1369`. Not in the v0.3.0test spec, noted only.

## Regression
8. Back to HD / 2K / 59.94 / 12b 2x3 (2711: 210 / LL ~91). AEL on RECIPE opened the sub-QS on the first press this time
   (2712: RECIPE, ADC 12bit, DC WIDTH S 6048, DC HEIGHT S 3402, SENSOR HBIN 2, VBIN 3, ISP HBIN 1 `RWZM 1/1.50`,
   ISP VBIN 1 `RWZM 1:1`); AEL back to the main QS, focus on RECIPE (2713). FPS changed both ways (2695/2696/2700). PASS.
   Observed: DC S16 -> HD came back with RES 6K and FPS 48 (was 3K / 59.94 before leaving HD); FPS stayed 48 afterwards.
9. QS key -> QS closed, LV_CINE_MEDIUM (2714). STILL 9 10 11 19 20 22 24 30, CINE 58 54 55 56 57 50 59 19;
   SetMovRecFormat 0 / SetMovRecSize 2 / SetMovFramerate 5 / ISO 3200 / headphone 3 = as at start. PASS.
   Counters: keys 39, dials 37, aels 2, opens 1, closes 1, adjusts 37, menus 0.

## Recording (step 7): skipped
sq_apply only records the QS selection; the stock mode that would record is FHD 12-bit (SetMovRecSize 2), whose
frame size (1936x1090: W*H*1.5 + 79 184 = 3 244 064 B) is already measured in MBPS_TILE_RESEARCH §1. The tile describes
2016x1134 (3 508 400 B), a raster that does not record yet, so a take would not test the tile. No recording made.

## End
Camera in live view, QS closed, ping OK. Card: QSContainer_v0.2.4.BIN + SensorLab-IMX410_v0.3.0test.BIN.
Slot 7 left as MB/s (Bei: test slots need not be restored).
