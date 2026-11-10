# QS Container v0.2.0 + QSTest v0.2.0 live test 2026-10-29 (run 2)

Shots: `shots/` (copies of /tmp/fp_ui/*). B = 0xC55BC8C0 (LOAD.LOG), status S = B+88128 = 0xC55D2100.
Reader: scratchpad qst.py (mem get of S+0..44, +3224..3252, +6408..6444, +6968..7032; focus [0xC37B72A8+0xBC]).

## Prep
1. 02:36 shell OK (5.02.0.V91), app_current 2, not recording. Backups: card_backup/fpSup_dir_before.txt, LOAD.LOG.before.
   `fl del \fpSup\QSContainer_v0.1.0.BIN`, `fl del \fpSup\QSTest_v0.1.0.BIN` -> OK, gone from dir. No ZQS / SLQSProbe on card.
2. Slots: STILL 9 10 11 19 20 22 24 30; CINE 21 12 23 25 39 9 27 19. SetMovRecFormat 0 (DNG), SetMovRecSize 2 (FHD),
   SetMovFramerate 5 (59.94), SetHeadphoneVolume 3, SetIso 2500.
3. deploy_v3 --only both: OK QSContainer_v0.2.0.BIN 88096 B (sha b048c417...), QSTest_v0.2.0.BIN 1252 B (sha efc5cc1a...), read back.
4. `ui_drive.py reboot` up 12.2 s. LOAD.LOG (card_backup/LOAD.LOG.boot1): `0D 54435351 00000000 QSC 00000000 C2DEAD7C`,
   `0A C55BC8C0 00000007 QSContainer_v0.2.0.BIN`, `0A C55D7300 00000000 QSTest_v0.2.0.BIN`. Before MENU: phase 0, N 0.
   After MENU (023708-menu1): result 0, phase 2, freeze 0, N 2, recv 2, full 0, bad 0, qs_result 0, qs_ready 1, qs_vars 25,
   txt 16, **reparse 0** (README expected 1; still 0 after entering editor and back to LV — see step 6 for hits).
5. MENU, RIGHT:10 -> SYSTEM p2 (023742), DOWN:3 自定QS (023754), RIGHT RIGHT -> editor slot 2 DC (023808), OK list 8/34 (023820),
   LEFT:9 -> 33/34 QS Test A crop icon (023837), OK (023849): slot 2 crop icon, name bar QS Test A.
   DOWN RIGHT -> slot 7 COLOR (023902), OK, LEFT:16 -> 34/34 QS Test B lock icon (023929), OK (023941).
   CINE = 21 54 23 25 39 9 55 19. MENU MENU -> LV (023954; green dot top centre, nothing else on LV).

## D. QS page
6. 02:40 `key QSON` (reply timed out, shell back after ~3 s), app_current 5. **hits = 114**, qs_result 0, foreign 0, reparse 0, focus 0x15 (FORMAT).
   **Screenshot works with QS open** (024040-qs; app_current stays 5): slot 2 = DC-crop icon + "N=0"; slot 7 = red "LOCK" + "QS Test B";
   other 6 tiles stock. Our value text is a thinner/regular font vs the stock bold values (Bei to judge). Footer: DNG/MOV list on FORMAT.
7. RIGHT -> focus 0x36. CMDDIAL1 +1: fmt 0, N=1 (024133); CMDDIAL1 -1; CMDDIAL2 +1: N=1 (024150); CMDDIAL2 -1.
   After each: **SetMovRecFormat 0 (unchanged)**, size 2, fps 5, ISO 2500, hp 3; keys/dials/adjusts 1->4; hp_blocks 0. **PASS (bug fixed).**
   Footer on our tile: an empty highlighted box under the tile (no list items), remains from the stock Footer list.
8. RIGHT -> 0x17 (RES), LEFT -> 0x36. CMDDIAL1 -1: **SetMovRecSize 2 (unchanged)**, N=999 (024216, wrap); +1, CMDDIAL2 +1, -1 -> N=0.
   keys/dials/adjusts 8. fmt 0, fps 5, ISO 2500, hp 3. **PASS** (yesterday the same move took RecSize 2 -> 3).
9. RIGHT, DOWN -> 0x37 (slot 7, QS Test B). CMDDIAL1 ±1, CMDDIAL2 ±1: dials 8->12, adjusts stays 8, nothing changed, **hp 3**, hp_blocks 0.
   (024246) B tile focused still shows ◀ ▶ arrows and footer "AEL 更多選項" though it has no dial action / no sub-QS.
   No stock headphone-volume tile in this layout, so the stock-tile half of step 9 was not applicable.
13a. AELON on slot 7 (B): aels 1, opens 0, sub_open -1, screen unchanged (024301). PASS.
10. UP, LEFT -> 0x36; AELON (024333): sub-QS in the same panel: slot 1 "Count / N=0", slot 2 unchanged (crop + N=0), slot 3 "Toggle / Off",
    slots 4-8 empty. opens 1, sub_open 0 (= function index; -1 = closed), sub8 = 65 49 66 72 72 72 72 72. CINE settings unchanged (21 54 23 25 39 9 55 19).
    LEFT -> 0x46 Count, CMDDIAL1 +1 -> Count N=1 and slot 2 N=1 (024350); -1 back to 0. RIGHT:2 -> 0x47 Toggle, CMDDIAL1 +1 -> On (024409), +1 -> Off.
    fmt/size/fps/ISO/hp unchanged throughout. PASS. Sub tiles have no icon (label in the icon row) — looks fine; footer still "AEL 更多選項" + empty box.
11. AELON on Toggle -> closes 1, sub_open -1; 8 tiles back with icons/labels and focus box on slot 3 RES, footer UHD/FHD (024427).
    **BUG (visual): the 6 stock tiles show their label but NO value text** (FORMAT/RES/FPS/ES/ISO/WB values blank); our A/B tiles fine.
    Dial on RES works on RES itself: CMDDIAL1 -1 -> SetMovRecSize 3, fps 2 (024445, footer UHD); +1 -> size 2, fps 5 (restored).
    Values still blank after the change and after moving focus to slot 2 (024506). [+0xBC focus read stayed 0x47 until the LEFT, as README notes.]
12. On slot 2 AELON -> sub-QS again (opens 2, sub_open 0). `key QSON` closes QS (app 2): closes 2, sub_open -1.
    `key QSON` again (024545): the original 8 tiles, **all values drawn again** (DNG/FHD/59.94/OFF/2500/5550K, N=0, QS Test B). PASS.
    (So the blank stock values of step 11 are only after an in-panel AEL return; a fresh QS open is fine.)
13b. LEFT -> FORMAT (0x15), AELON -> stock 記錄設定 CINE page (024605); aels counter unchanged (stock key path). MENU -> back to QS,
    focus FORMAT, footer DNG/MOV, all values drawn (024619). PASS.

## Finish
- QSON closed QS. MENU (opened at SHOOT p2 記錄設定, remembered from the AEL jump), UP:2, RIGHT:9 -> SYSTEM p2, DOWN:3, RIGHT RIGHT -> editor slot 2
  (024732: slot 2 crop "QS Test A", slot 7 red LOCK). OK, RIGHT:9 -> 8/34 DC裁剪模式 (024753), OK. DOWN RIGHT -> slot 7, OK, RIGHT:16 -> 16/34 色彩模式 (024826), OK.
- **CINE = 21 12 23 25 39 9 27 19, STILL = 9 10 11 19 20 22 24 30** (both = prep). MENU MENU -> LV (024852).
- Final: SetMovRecFormat 0, SetMovRecSize 2, SetMovFramerate 5, SetIso 2500, SetHeadphoneVolume 3 (all = prep). app 2, is_recording 0.
- Final counters: keys 20, dials 16, aels 4, opens 2, closes 2, adjusts 12, locked 0, txt 54, hp_blocks 0, hits 114, foreign 0, reparse 0,
  qs_result 0, freeze 0. No freeze, no shell wedge (each `key QSON` reply times out once; shell answers ~2-3 s later).
- v0.2.0 BINs left on the card; v0.1.0 removed. Step E (recording) not done — for Bei by hand.

## Open items
- Step 11 visual bug: after AEL-return inside the panel the stock tiles' value text (Icon02) is blank until QS is reopened.
- reparse counter stayed 0 all session (README expected 1 after MENU); hits = 114 on first QSON anyway, so the layer was applied.
- Cosmetic for Bei: our value font is regular weight vs stock bold; B tile shows ◀ ▶ and "AEL 更多選項" though inert;
  empty highlighted footer box under our tiles / sub-QS.
