# QR scan: QS shows the scan, REC records the old settings (2026-11-08, offline)

Bei, live 11-08: scan a SensorLab QR (QR tile → AEL → Y5_ReadQR → our decoder) → back in QS_CINE the tiles show the
scanned settings, but the recording uses the settings from before the scan. Offline only: no camera, no USB, no card.

## Cause

The commit runs **inside the read page's settings session**, and the page throws that session away when it exits.

1. `MenuQrCodeReadHandler::v72` (0xC0476B38) calls `FUN_c0057d38(settings)`. That calls `MenuSettingStorage_w71c1`
   (0xC31AE3B0) vt+0x1C = v5 `0xC00884F0` → `FUN_c0089720`. It copies the live settings (+0xC, 0x4F00 + 0x9C0 B) into the
   work copy at +0x58D4 and sets the flag +0xB19C. While the flag is set, the item accessors (`FUN_c008cdd0`) use the work
   copy. (out/decomp/full/blk_c04.c:87639, blk_c00.c:64496, 99897, 103610)
2. `v73` (0xC0476BB0) calls `FUN_c0057da0(settings, 0)` → v6 `0xC0088E10` with 0. That clears +0xB19C and **does not
   copy the work copy back**. Argument 1 would copy it back (`FUN_c0089640`); stock "OK" handlers do that, for example
   `MenuCinemagraphColorModeAdvancedHandler::v13`. The page uses 0 so that its two temporary items (`FUN_c0059fb0` /
   `FUN_c005a078`) are not kept. (blk_c04.c:87663, blk_c00.c:100310)
3. Before this fix, `sl_mqr_v62` (slqs.c) called `qr_restore(..,1)` → `sq_push` → `ap_request` → `ap_commit` **on the page**.
   That built the new slot and called the native frame-rate setter `AP_FR_SET(obj, carrier)` (0xC005C0B8). The setter
   wrote into the work copy. At page exit the carrier went back to the pre-scan rate. `ap.c` still had `have == want`
   and `result == AP_OK`.
4. QS re-entry: `leave()` → `sq_push` → `ap_request` found `owed = 0` and returned `AP_IDLE`, so it did not commit again.
5. At REC the picker gets a TAB3 key named after the stock frame rate (the old one). `ap_key_rate` does not match the live
   slot's suffix, so the picker gives **the stock route at the pre-scan frame rate**. A standby LV restart asks the
   same table, so it also goes stock. The QS still shows `st->s` (the scan).
   The bug shows only when the old and new recipes have different carriers.

Hypotheses 1 and 2 of the task (DEFER/REFUSED on the page; re-entry overwriting `st->s`/the record) are ruled out by the
emulation: the commit on the page returns `AP_OK`, and the fields after re-entry equal the scan. The cause is hypothesis
3 (the stock frame-rate carrier), by the mechanism above.

### Emulation (real BIN, real v4 core and container, real stock v62/v72/v73 handlers; the session stub follows v5/v6 as decompiled)

Script: `qr_evidence.py`, run in a scratch directory. A = 119.88 carrier (7), B = 100 carrier (6). Current code before the fix:

```
model_session False   (no session discard: what the old tests assumed)
 A committed: result 0 carrier 7 FR 7 rec_pick (True, 7)
 after v62 (on page): ap_rc 0 commits +1 carrier 6 FR 6
 after v73 (page exit): FR 6
 after QS leave x2: pushes +2 commits +0 result 0 owed 0 carrier 6 FR 6 fields==B True rec_pick (True, 6)
model_session True    (v72 begin / v73 end(0) as in the firmware)
 A committed: result 0 carrier 7 FR 7 rec_pick (True, 7)
 after v62 (on page): ap_rc 0 commits +1 carrier 6 FR 6
 after v73 (page exit): FR 7                      <- the carrier set on the page is dropped
 after QS leave x2: pushes +2 commits +0 result 0 owed 0 carrier 6 FR 7 fields==B True rec_pick (False, 7)
                                                  <- QS = B, live slot = B, REC key = old rate -> stock
```

New test before the fix: `RecAfterScan.test_scanned_selection_is_what_rec_picks` FAIL `7 != 6 : the stock frame rate is the live slot carrier`.

## Fix (qs/slqs.c only; ap.c unchanged)

- `sl_mqr_v62`: an applied scan sets `scan.pending = 1` (the word already existed and was always 0) instead of calling `sq_push`.
- `sl_mqr_v73`: the stock exit runs first and closes the session with 0. Then, if pending: `sq_push` (when not `busy()`),
  with pending cleared. So the commit and its `AP_FR_SET` go into the live settings.
- `sq_push`: returns early while `scan.pending && scan.on_page`. A `leave()` before the page exit (the order of v73 and the
  QS layout load is not known offline) cannot commit into the session either.
- `scan_result` no longer clears `pending`.

No other behaviour change: same selection, same record write, same path back to QS. The commit only moves from v62 to
just after the stock v73.

## Tests

- `qs/test_qrscan.py`: `ScanCam.model_session` models the session (begin: snapshot `FR_WORD`; end(0): put it back).
  New class `RecAfterScan`:
  - commit A → scan B on the page → v73 → leave ×2 → REC picker with the key of the stock rate → must be ours, carrier B;
  - the same with a `leave()` before v73.
  Both FAIL before the fix and PASS after.
- `Page.test_ours_applies...` changed: no push at v62 (`pending` 1), one push at v73, none on a second v73.
- `python3 -B -m unittest test_qrscan`: 26 of 27 PASS. One failure that was already there before this change:
  `Tile.test_ael_go_needs_api7_and_no_recording` expects container API 8, but QS-Share 0.0.2test is API 9. Not fixed (out of scope).
- Mutants (in `test_qrscan.MUTANTS`): `accepted owes no push`, `accepted pushes inside the page session`,
  `exit does not push`, `exit pushes before the stock exit`, `leave pushes inside the page session`, `exit owes forever`. See
  "Mutation" below.
- Note: `test_qrscan` (and `test_bootapply`) are **not in `tools/test.py`**, so `fast`/`prelive` do not run them. Run directly:
  `cd qs && python3 -B -m unittest test_qrscan`.

## Mutation

All 35 of `test_qrscan.MUTANTS` were run with `qr_mut.py` (in this directory). It is the same as `test_qrscan.py --mutate`, minus
`Tile.test_ael_go_needs_api7...`: that test already fails before any mutation, so the built-in runner would count every mutant
as "caught". **All 6 new mutants are caught.** `exit does not push` failed to compile on the first run (owed unused) and
was rewritten. The two survivors, `go ignores the api version` and `go ignores recording`, are covered only by the stale Tile
test that was left out. They are not related to this change.

## Gates

- `tools/test.py fast`: all PASS except `site` (see below).
- `tools/test.py prelive` (log `tools/test-logs/prelive-20261108-030520`): every mutation suite has 0 surviving mutants,
  including slqs (103), apply, core, qsc and qsc-page. All unit suites PASS except two:
  - `settings-migration`: the frozen default-build fixture for 0.0.2test. It was refreshed to `542bc89e…`
    (`qs/test-fixtures/settings-migration/README.txt` records this) and now passes: 9 of 9 PASS.
  - `site`: `fpSup/sensor_lab_imx410/wasm_info.json` holds a source fingerprint of `slqs.c`. A scratch regeneration gives
    `index.html`, `sensorlab.wasm` and `wasm_backend.js` **byte-identical**; only the fingerprint differs. **Not
    regenerated** (that is the published shared tree): run `python3 -B projects/sensorlab-imx410/site/build_site.py` when
    the site is published.

## Builds (offline, 11-08; VERSION 0.0.2test unchanged)

| build | command (in `qs/`) | size | sha256 | sq_test_off |
|---|---|---|---|---|
| product | `python3 -B build_slqs.py --out out` | 206 368 B | `542bc89ec69f0afbaf47361668a3d5ed13ac05d84cf8ea067c573826bb46d4fa` | 0x9BC1 |
| TEST (rec delay) | `python3 -B build_slqs.py --rec-delay-test --out out-rec-delay-test` | 207 240 B | `f29f039a9b63f23ec4f59f32406d3347bab4ea2f8461b09aa49c9e4dda62237e` | 0x9DCD |

These replace 11-07's `c5c1ddad…` / `32d9293b…`. The product build is reproducible: a second build to another directory gives
the same sha256. The record format and the claims are unchanged. QS-Share is not affected.

## Live check

1. Commit selection A, with a carrier different from B's (for example a 119.88-max recipe vs 100 or 48), and leave QS.
   Record a short take as the control.
2. Scan a QR of B. Back in QS_CINE, with no other key: `sq_test 40` (scan): `applied +1`, `pending 0`, `on_page 0`.
   `sq_test 17` (ap_status): `commits +1`, `result 0`, `carrier` = B's. The stock frame-rate enum
   (`FUN_c005c0f0(settings)`, or the menu's FPS) = that carrier.
3. Close QS and record: after the take (≥12 s, no USB during REC), `ap_status.picks` went up, and the DNG has B's size and rate.
4. Old build (control): in step 2 the frame-rate enum would be A's while `carrier` is B's, and the take would be stock.
