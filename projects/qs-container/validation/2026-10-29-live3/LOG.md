# QS Container v0.2.1 + SensorLab-IMX410 v0.1.0test live test 2026-10-29 (run 3)

Shots: `shots/` (copies of /tmp/fp_ui/*). B = 0xC55BC8C0 (LOAD.LOG), status S = B+132288 = 0xC55DCD80.
Reader: scratchpad `qst3.py` (README offsets: S+0..44, +3224..3252, +9992..10028, +10680..10744, +10908..10936; focus [0xC37B72A8+0xBC]).

## Prep
1. 06:33 shell OK, LV_CINE_MEDIUM. Backups: card_backup/fpSup_dir_before.txt, LOAD.LOG.before.
   Values before: SetMovRecFormat 0 (DNG), SetMovRecSize 2 (FHD), SetMovFramerate 5 (59.94), **SetIso 3200** (was 2500 in run 2),
   SetHeadphoneVolume 3. STILL 9 10 11 19 20 22 24 30; **CINE 21 12 23 25 39 50 27 19** (slot 6 is now 50 = K/color temp
   5550K, not ISO 9 as in the brief — changed by someone between run 2 and now; taken as the original).
2. `fl del` QSContainer_v0.2.0.BIN, QSTest_v0.2.0.BIN -> OK, gone. deploy_v3: QSContainer_v0.2.1.BIN 132260 B (sha 63febef4...),
   SensorLab-IMX410_v0.1.0test.BIN 10900 B (sha 80dfa0a9...), both OK with read-back. QSTest not deployed.
3. `ui_drive.py reboot` up 11.9 s. LOAD.LOG (card_backup/LOAD.LOG.boot1): `0D 54435351 00000000 QSC 00000000 C2DEAD7C`,
   `0A C55BC8C0 00000008 QSContainer_v0.2.1.BIN`, `0A C55EDF80 00000000 SensorLab-IMX410_v0.1.0test.BIN`.
   Before MENU: phase 0. After MENU (063522): result 0, phase 2, freeze 0, N 2, recv 2, full 0, bad 0, qs_result 0, qs_ready 1,
   qs_vars 88, released 0 + fresh 1 = 1. PASS.

## Editor
4. MENU RIGHT:10 -> SYSTEM p2 (063545), DOWN:3 RIGHT RIGHT -> editor slot 2 DC (063601). OK, LEFT:9 -> 33/34 "DC" with DC icon (063624), OK.
   RIGHT -> slot 3 (063638: slot 2 DC icon, no value), OK list at 10/34 解析度 (063650), LEFT:10 -> 34/34 "RES" (RES. look) (063709), OK (063721).
   CINE = 21 54 55 25 39 50 27 19. MENU MENU -> LV.

## QS page
5. `key QSON` (063743): hits 126. FORMAT focused, stock values drawn. DC tile: DC icon, bold `HD`, `35.9 × 20.2 mm`;
   RES tile: `RES.`, bold `2K`, `2016×1134 · 3x3`. Values bold like stock (fix 4 PASS). Notes: our big value is larger than stock
   `DNG`/`59.94`; our small line is white (stock `12bit`/`FHD` is grey); `mm` and the `x` in `3x3` are lowercase system font.
6. RIGHT -> DC (063758): ◀ ▶ arrows, "AEL 更多選項", footer `OG HD S35 APS-C S16 SQ` (with 6048×4040… small) centred, HD boxed. PASS (fix 2, 3).
   Dial +1 -> S35 24.9×14.0 mm, RES follows 1.5K 1392×786 · 3x3, box moves (063843). +1+1 -> S16 12.4×7.4, RES 0.7K 688×412 (063857);
   +1 -> SQ 23.9×23.9, RES 1.5K 1344×1344 (063902); +1 -> wraps to OG 35.9×24.0, RES 2K 2016×1346 (063907); +1 -> HD.
   FORMAT unchanged after dialing on DC right after FORMAT focus (10-29 bug stays fixed for this pair).
7. RIGHT -> RES (063922): footer 1K FHD 2K 3K 3.5K UHD 4K (7 shown, 2K boxed at position 3, small text 6x6/3x3/2x2), arrows, hint.
   Dial up to 4K (063938: window scrolled 2K..6K), 6K 6048×3402 · 1x1 (063944), +1 at 6K stays (063949); down to 1K, -1 at 1K stays
   1008×566 · 6x6 (064010); back to 2K (064016). Note: long small line (`6048×3402 · 1x1`) runs under the arrows; both arrows still
   shown at list ends. Settings after all dialing: fmt 0, size 2, fps 5, ISO 3200, hp 3, hp_blocks 0. dials 24 / adjusts 24.
8. AELON on RES (064036): same panel, RES in tile 1 with focus, WIDTH 2016 / HEIGHT 1134 / key icon LOCK 1.778:1, tiles 5-8 empty,
   hint "MENU 退回", sub8 = 65 66 67 68 72 72 72 72. PASS (fix 5 layout). Notes: tile-1 `RES.` title sits right of centre;
   the key/unlock icon overlaps the LOCK/FREE value; `LOCK` letters widely spaced; tile-1 footer still shows the RES preset list.
9. RIGHT -> WIDTH (064049): footer `◀ 2016 ▶` PASS. Dial -1 -> 2000×1124, RES `CUSTOM`, ratio 1.779 (064055; CUSTOM fills the whole
   tile width). +1 -> **2016×1132** (not 1134), ratio 1.781, still CUSTOM, multiplier `3x` (064108) — with lock on, -1/+1 does not
   return to the start; the shown locked ratio drifts each step.
10. RIGHT:2 -> RATIO (064123, footer LOCK|FREE boxed LOCK). +1 -> FREE, unlock icon (064128). LEFT -> HEIGHT `◀ 1132 ▶` (064140),
    +1 -> 1134 -> snaps back to `2K` 2016×1134 · 3x3, 1.778 (064146). PASS. RIGHT, -1 -> LOCK again (064201).
11. **MENU in the sub-QS (focus on RATIO) (064214): QS closed and the stock main MENU (SYSTEM p2, 自定QS row) opened.**
    Counters: menus 1, closes 1, sub_open -1 (container did return), but the stock MENU action ran too. app_current read 5 with the menu shown.
    → §10 "MENU returns to the 8 tiles" FAILS on camera.
12. Then `MENU` (to leave the menu) -> `where` got no mem reply; `key QSON` sent; **USB shell stopped answering** (06:42).
    ping / status fail; restarting fpshd (7 tries over ~2 min) does not help; camera still enumerates on USB.
    Could not make RAM clean (CINE still holds 54/55 in RAM; flash holds stock ids), could not read counters, could not reboot over USB.
    Stopped here per the rules.

## Not done
- DC sub-QS, per-crop RES memory, fix 1 (stock values after in-panel return), FORMAT/RES dial check next to RES, slot restore, final standby.
- Card: QSContainer_v0.2.1.BIN + SensorLab-IMX410_v0.1.0test.BIN on the card, v0.2.0 removed.
- Needed: Bei to look at the camera screen (is the GUI alive?) and power-cycle; after that, `menu SetFunction 12` is not needed if
  the container's save path wrote placeholders (flash holds 12 / 23), but check CINE = 21 12 23 25 39 50 27 19 by mem get, then restore
  in the editor if not.
