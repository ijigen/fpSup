# QS probe live test 2026-10-28 (stages 1-2)

## 0. Baseline
- Shell answers (5.02.0.V91), app_current 2 (CINE), not recording.
- \fpSup\: LOADER.BIN 22040 (v4), EarlyFlush, ISPL, Lossless_v0.3.1, LUT, Stop-FX, SUPMGR, USB-Shell_v3.4.0; no RES-Custom BIN (only `._` AppleDouble stubs + RESCUS\ data dir) -> nothing moved aside. No SLQSProbe*.
- Listing: card_backup/fpSup_dir_before.txt; LOAD.LOG: card_backup/LOAD.LOG.before.
- Slot groups before:
  - 0xC31B07A4 (+0x23E8): 9 10 11 19 20 22 24 30
  - 0xC31B0ABC (+0x2700): 21 12 23 25 39 9 27 19
  - MV_QSMENU_QS1..8 (UI ids): 20 17 21 22 39 4 27 25
- 21:2x HOLD from coordinator after Probe1 write (verified). No restart yet.
- Coordinator: continue (9d not using camera).
- Echo slot 0xC0BAC2F8 = 0xC03D99A0 (stock) checked before restart.
- Restart: `fastreboot.py now` (poff 2). Camera did NOT come back: fastreboot gave up after 30 daemon retries; fp absent from ioreg (`device 1003:c432 not found`), still absent after a further 90 s poll (~3+ min total).
- STOPPED per rules. Camera state unknown (off / frozen while booting with SLQSProbe1 + LUT + ISPL + Lossless...). No keys sent, no QS slot changed, LOAD.LOG of this boot not read.
- Card: \fpSup\SLQSProbe1_v0.1.0.BIN is present (verified write); everything else as card_backup/fpSup_dir_before.txt.

## 1. Stage 1 (Bei tested by hand after the poff restart failed; camera power-cycled by Bei)
- LOAD.LOG: `0D 50514C53 00000000 QSP 1 00000000 00000000 00000010` + `SLQSProbe1_v0.1.0.BIN` loaded — as expected.
- Bei: our four entries appear in the custom-QS editor; choosing one turns the slot into 拍攝模式 ("mode") — as expected (UI 49→internal 0).
- mem after: +0x2700 group slot 2 changed 12 → 0 (+0x23E8 unchanged) ⇒ **+0x2700 (0xC31B0ABC) is the CINE group**.
- `poff 2` restart did not bring the camera back on USB (~3 min); cause unknown; restarts from here are by the power switch.

## 2. Stage 2 deploy 21:44
- `fl del \fpSup\SLQSProbe1_v0.1.0.BIN`; deploy_v3 `SLQSProbe2_v0.1.0.BIN` 13408 B OK (read-back verified). Awaiting Bei's power-cycle.

## 3. Stage 2 live (21:50-22:41)
- Restart via `ui_drive.py reboot` OK (11.3 s); LOAD.LOG `QSP 2 00000000 C2DEAD7C 00000010`.
- Bei put DC into slot 2: RAM 0xC31B0AC0 = 54, MV_QSMENU_QS2 = 49 (converter works). Editor tile = MODE icon, name bar 拍攝模式.
- Slot 2 then could not be changed: RIGHT / OK / MENU gave identical screenshots, `where` stayed QS2C. Bei: 「我放入的自訂QS無法改動」.
- Analysis: projects/qs-touch/notes/QS_EDITOR_ID_PATHS.md. 0xC3033469 = 0 (no assert loop).
- Rescue: `menu SetFunction 12` → +0x2700 group back to 21 12 23 25 39 9 27 19, +0x23E8 unchanged, no 54..57 left (flash-safe). MV_QSMENU_QS2 still reads 49 (not re-posted).
- After the rescue, MENU works again (left the editor to the SYSTEM page): the GUI was alive, so this is not a native hang. Likely candidate B (focus in the List with no item), tied to the slot holding 49.

## 4. Discrimination test (23:20-23:28, stage 2)
- Control: slot 1 OK → list opens at the current function (9/32). Total count still reads 32; our rows show as 33/32..36/32, with raw private-string ids as names (e.g. 1163655400). KEY resolution doesn't work in this list → use stock keys or another label path.
- Choosing our DC (row 33) in slot 2 → RAM 54. Tile keeps its previous frame. **OK on the slot right after works** (list opens at the previous position, 8/32). MENU / RIGHT / LEFT normal. Repeating with MODE as the previous frame also works.
- **Reproducible trigger:** leave the editor and re-enter it while the slot holds 49. The slot's name bar shows **"XXXX"** (string never set at page build). OK on it → grey tile, no popup, name 拍攝模式, and every key (RIGHT, MENU) does nothing for at least 3 min. 0xC3033469 = 0.
- `gui seti MENU_Level3 85` → no visible change. `menu SetFunction 12` → RAM clean (no 54..57 in either group); the tile does not redraw and MENU is still dead (not an un-stick).
- Recovered by `ui_drive.py reboot` (11.8 s) after verifying RAM clean.
- ⇒ The page-build path is the trigger, not the selection: Icon01 (0..48) never fires for 49, so the tile's string/list-index state stays uninitialised ("XXXX") and the OK path breaks.
