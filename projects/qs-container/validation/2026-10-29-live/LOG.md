# QS Container (QSCT) + QSTest live test 2026-10-29

Shots: `shots/` (copies of /tmp/fp_ui/*). Status reader: B = 0xC55BC8C0 (LOAD.LOG), status = B+48832.

## Prep
1. 00:34 shell OK (5.02.0.V91), not recording. Listing + LOAD.LOG backed up (card_backup/fpSup_dir_before.txt, LOAD.LOG.before).
   `fl del \fpSup\SLQSProbe2_v0.1.0.BIN` -> OK, gone from dir.
2. Slots before: STILL 0xC31B07A4 = 9 10 11 19 20 22 24 30; CINE 0xC31B0ABC = 21 12 23 25 39 9 27 19 (matches brief).
3. deploy_v3 --only QSContainer (48804 B, sha 28a67b5b...) + QSTest (632 B, sha c4d391bf...): both OK with read-back.
4. `ui_drive.py reboot` up after 10.6 s. LOAD.LOG (card_backup/LOAD.LOG.boot1): `0D 54435351 00000000 QSC 00000000 C2DEAD7C`,
   `0A C55BC8C0 00000006 QSContainer_v0.1.0.BIN`, `0A C55CB900 00000000 QSTest_v0.1.0.BIN` — both LOADED. app_current 2.
   Status right after boot (LV, no layout load yet): phase 0, N 0. After MENU (shots/003533-menu1): phase 2, freeze 0, N 2, recv 2,
   full 0, bad 0; csv result 0, CSV row counts 0x20 x4; pages result 0 0; copies C570BC8B C57D0F0B.

## A. List
5. Nav: MENU -> RIGHT x9 -> SYSTEM p2 (003631-s2) -> DOWN:3 自定QS CINE (003643-qsrow) -> RIGHT editor (003654-editor) ->
   RIGHT slot 2 (003706-slot2) -> OK list at DC 8/34 (003712-list). Total = **34**.
   LEFT:8 -> **34/34 QS Test B, lock icon** (003732-row34); LEFT -> **33/34 QS Test A, DC-crop icon** (003738-row33).
   Names are text, not numbers. PASS.

## B. Freeze reproduction
6. OK on QS Test A (003751-s6): slot 2 = DC crop icon, value blank, name bar "QS Test A". `mem 0xC31B0AC0` = 0x36 (54). PASS.
7. MENU -> SYSTEM p2, focus on 自定QS (003802-s7out). RIGHT -> editor (003812-s7in): slot 2 tile = crop icon.
   RIGHT -> slot 2 (003823-s7slot2): name bar **"QS Test A"** (not XXXX). PASS.
8. OK on slot 2 (003834-s8ok): **popup opens, cursor on QS Test A 33/34**, name bar QS Test A. RIGHT -> 34/34 QS Test B (003847),
   LEFT -> 33/34 (003853), MENU -> popup closed, slot 2 still QS Test A, footer 退回 (003859). All keys respond. **Freeze fixed.**
   OK again, RIGHT:2 wraps to 1/34 拍攝模式 (003916); RIGHT:7 -> 8/34 DC裁剪模式 (003932); OK (003943): slot 2 = DC / OFF,
   name DC裁剪模式; RAM slot 2 = 12. PASS.
9. Editor DOWN+RIGHT -> slot 7 COLOR (004011). OK -> list 16/34 (004023); LEFT:16 -> 34/34 QS Test B (004048); OK (004059):
   slot 7 = red LOCK icon, name QS Test B, RAM 0xC31B0AD4 = 55. Slot 2 back to QS Test A (004130 list 33/34, 004142).
   CINE group now 21 54 23 25 39 9 55 19. MENU out (004149), RIGHT in (004201: both tiles drawn), slot 7 name bar QS Test B (004210),
   OK -> popup at 34/34 QS Test B (004222), MENU -> back, keys alive (004228). PASS.

## C. Save swap (USB-only variant)
- Before reboot (LV, 004251): saves 0, sanitized 0 (no save path ran while the camera was up).
- `ui_drive.py reboot` (11.6 s). Before collection: CINE = 21 **12** 23 25 39 9 **27** 19 (= what flash held: stock placeholders).
  After MENU (004330): phase 2, **restored = 2**, CINE back to 21 54 ... 55 19. saves/sanitized read 0 (RAM counters of the
  previous boot are lost across reboot; the save evidently ran because the record was written).
- Record in the BIN read back (card_backup/QSC_after_boot2.BIN @48456): 'QSC1' v1, entry 9 = 'QSTSA' placeholder 12,
  entry 14 = 'QSTSB' placeholder 27. Header bytes unchanged, no file created.
- Editor after boot (004412/004419): slot 2 crop icon + "QS Test A", OK opens popup at 33/34; slot 7 red LOCK. PASS.

### 11-12 (optional, done)
- fpSup page (LEFT from SHOOT 1, 004520) -> SupManager (004533) -> page 2 (004545) -> QS Test -> OK -> 關閉 (004602/004616
  "Unload on restart"). Exit (004632), reboot. LOAD.LOG boot3: `13 53545351 ... QSTest_v0.1.0.BIN` (disabled), QSC loaded.
- After MENU: phase 2, freeze 5 (no client), N 0, **orphans = 2**; CINE = 21 12 ... 27 19 (placeholders). Editor (004744): slot 2 DC/OFF,
  slot 7 COLOR/OFF; list total 32/32 (004806). No hang. PASS.
- Step 12: slot 2 -> WB (004817), RAM = 19. SupManager: QSTest_v0.1.0.BIN 關閉 -> 開啟 (004908/004922/004935). Reboot.
  Before collection CINE = 21 **19** ... 27 19 (flash saved WB). After MENU: restored = 1 (slot 7 -> 55), slot 2 stays **19 (WB)**.
  stale counter reads 0 (the drop happened at the previous boot's save; that RAM counter is gone), but the record
  (QSC_after_boot4.BIN) now holds only entry 14 'QSTSB' 27 — entry 9 was dropped, i.e. WB was not overwritten. PASS (behaviour).

## D. QS page
- Editor: slot 2 WB -> QS Test A again (005146..005233). LV. Headphone volume (`menu SetHeadphoneVolume`) = 3.
- `gui image log 1`, `key QSON` (app_current 5). Images loaded: format, mode, resolution, fps, electronicStabilizer, iso, wb (+ set_format_*);
  no crop/lock/color images (slots 2/7 not drawn — expected for stage 1). Can't screenshot QS (capture closes it).
- QS focus read from [0xC37B72A8+0xBC] (FUN_c05666a0 returns 0xC37B72A8): RIGHT -> 0x36 (slot 2).
  CMDDIAL1 ±1, CMDDIAL2 ±1 on slot 2, then on slot 7 (0x37): headphone volume stays 3, **hp_blocks stays 0** (setter path never reached).
  Control on slot 6 (focus 9 = ISO): CMDDIAL1 +1 -> ISO 2500 -> 3200, -1 -> 2500 (dial events do reach QS).
- **BUG found:** when editor shown later, FORMAT read **MOV** (005512). `menu SetMovRecFormat` = 1.
  Reproduced: reopen QS (focus remembered = slot 7), UP -> slot 3 RES (focus 0x17), LEFT -> slot 2 (0x36), CMDDIAL1 -1 ->
  `SetMovRecSize` 2 -> **3** (resolution changed). So the dial on our QS tile drives the setting of the tile focused just before it
  (stale keyEvent; first time it was FORMAT, slot 1, because QS opened there and RIGHT moved to slot 2).
  Restored: CMDDIAL1 +1 on slot 2 -> RecSize 2; LEFT to slot 1 (FORMAT, 0x15), CMDDIAL1 -1 -> RecFormat 0 (DNG).
  Final: RecFormat 0, RecSize 2, Framerate 5, ISO 2500, HeadphoneVolume 3; editor shows DNG / FHD / 59.94 (005729). QSON closed QS.
- Q4 (headphone) itself: volume unchanged, but the hook was not exercised (hp_blocks 0), so Q4 is unproven.

## Finish
- Editor: slot 2 -> DC裁剪模式 8/34 (005751, 005804), slot 7 -> 色彩模式 16/34 (005839, 005853). Exit to LV (005902).
- CINE = 21 12 23 25 39 9 27 19, STILL = 9 10 11 19 20 22 24 30 (both = start values).
- Extra reboot to make sure the record does not bring Test B back: after collection CINE still stock, restored 0;
  record in BIN (QSC_final.BIN) has no entries. LOAD.LOG: both LOADED.
- QSContainer_v0.1.0.BIN + QSTest_v0.1.0.BIN left on the card (SLQSProbe2 removed). Camera in CINE standby, not recording.
