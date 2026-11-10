# QR scan build: SensorLab-IMX410 v0.7.32test + QSContainer v0.3.7 (2026-11-04, offline candidate)

Not tested on the camera. Design: [notes/QR_SCAN_DESIGN.md](../../notes/QR_SCAN_DESIGN.md) §9–§11. Code:
- SensorLab: [qs/README.md](../../qs/README.md) v0.7.32test;
- container: [qs-container/README.md](../../../qs-container/README.md) v0.3.7.

## What is in it

| | |
|---|---|
| **AEL on the QR tile** | Container API 7 `QSC_F_GO(QSC_GO_READQR)`. The QS opens SIGMA's "Load from QR Code" page (`Y5_ReadQR`) through a private state machine `QS_CINE —"Y5_ReadQR"→ Y5_ReadQR`. |
| **Decoder fallback** | On page entry (handler v72), and only if the reader's decoder vtable word `0xC3588D68` holds the stock `0xC2DFE860`, it is pointed at SensorLab's copy. That copy runs the stock decoder first, then `qrdec.c` (V5-L). Our bytes are written back as `byte − i`. The word is put back at page exit (v73) and at any `leave()` off the page. |
| **Results** (handler v62) | A SensorLab URL is checked with `qr_unpack`, then must give back all 27 fields after restoring. Exact match → the stock `ProcessingComplete` state. Otherwise → the stock "Incompatible QR code.", and the QR tile shows `QR refused <FIELD>` for 30 s. Anything else, including SIGMA's own settings codes, runs the stock handler unchanged. |
| **OK** (handler v8) | Applies the selection (selection, dirty, `sq_push`; the record is written at the next `leave()`), shows `QR applied` on the tile, then leaves through the stock back path. The stock back goes to "Return", i.e. the setup menu (MainY5). The QS button returns to QS and half-press goes to live view. |
| **Recording** | Nothing runs: the go, the decoder fallback and the result check are all off. |
| **REC-start resync** (v0.7.28/29) | **Switched off** (`AP_RESYNC 0`). `validation/20261104-resync-review` shows v29 ran but the first-frame fault stayed at 8/10. It also adds 50–80 ms to the REC start and leaves `0000` bit2 cleared. Its hooks still count (`resync_seen` / `resync_ours`), and `resync_skips` reason 3 means switched off. **The behaviour is therefore that of the card's v0.7.28test, where the resync never ran.** The apply tests build with `-DAP_RESYNC=1`, so the resync code stays covered. |

## Builds

| File | Bytes | sha256 | Use |
|---|---|---|---|
| `sensorlab/card-settings-build/fpSup/SensorLab-IMX410_v0.7.32test.BIN` | 203660 | `0a7f064d…28903` | **card**: settings record taken from the card's v0.7.28test (`../20261104-first-frame-resync2/card-before/`) |
| `sensorlab/default-build/fpSup/SensorLab-IMX410_v0.7.32test.BIN` | 203660 | `f07a9118…4734d` | blank record; frozen as the migration fixture |
| `qs-container/card-settings-build/fpSup/QSContainer_v0.3.7.BIN` | 201416 | `4bf8211f…cc9d3` | **card**: settings record from the card's v0.3.6 (`qs-container/validation/20261103-editor-title/readback.BIN`) |
| `qs-container/default-build/fpSup/QSContainer_v0.3.7.BIN` | 201416 | `646ef520…1abbc` | blank record; the same bytes as the container session's build; frozen fixture |

**Deploy both card builds together.** SensorLab v0.7.32test on container v0.3.6 still loads, but AEL on the QR tile then does nothing (it asks for API 7).

**Source tree versions:**
- SensorLab was at v0.7.29test code. The v0.7.29 resync is kept as code but switched off (see above).
- Everything else of v0.7.29 (the hook at `C030D168`, the counters) is in.

**Removing the old files:** remove the card's `SensorLab-IMX410_v0.7.28test.BIN` and `QSContainer_v0.3.6.BIN` (`fl del`). The same-name, newer-version rule loads only the newest, but delete the old files anyway.

## Tests (offline, all against the real firmware image under unicorn where marked)

| Suite | Result |
|---|---|
| `qs/test_qrdec.py` (decoder: 1 137 codes clean, rate floors, RS, format, byte mode, white box) | see `qrdec-suite.log`; mutants 18/18 (`../20261104-qr-scan-design/mutants.log`) |
| `qs/test_qrscan.py` (16: install, restore round trip over 40 site recipes + refusals, the real `FUN_c05c49f0` → our decoder, the real handler v62/v8/v12/v72/v73, the go, resync off) | `qrscan-suite.log`; **mutants 19/19** (`qrscan-mutants.log`) |
| `qs/test_slqs.py` (68) | `slqs-suite.log` |
| `qs/test_settings_migration.py` (8; new frozen fixtures) | `settings-migration.log` |
| `apply/test_apply.py` (80, built with `-DAP_RESYNC=1`) | `apply-suite.log` OK; mutants 117 caught, 4 patterns already stale before this change (48, 54, 56, 61: their text is no longer in ap.c; unrelated to resync) — `apply-mutants.log` |
| `tools/test.py fast` | `tools-fast.log` |
| QSContainer: test_qsct 33, test_qs_page 61 (+1 skip), test_api5 15, test_api7 11 | all OK; mutants 43/43, 84/84, 20/20, 21/21 (`qs-container/BUILD.md`, `api7-mutants.log`) |
| `site/test_site.py` (9) | OK after regenerating the local publication copy (version string only) |

`test_slqs --mutate` (the full SensorLab mutant set) was not rerun. This change does not touch the code those mutants target, except the size guard (+16 KiB).

## Live plan (phase 0 first; broadcast before using the camera; not while recording or in playback)

**Phase 0: SIGMA's reader alone, no new BIN**

0.1 **Version-20 sanity check.** On the camera as it is now (v0.7.28test / v0.3.6), LV standby, USB shell:
- run `qr decode_log` (log on), and optionally `qr dump_y8`;
- show a phone a **version-20** QR of a SensorLab URL (any generator with a forced version 20, or the stock `qr play_make`);
- run `qr lv_read`;
- expect `result = 0` and a hex dump equal to `URL[i] − i`.

This proves the reader, the crop and the focus on a phone screen.

0.2 **Our version 5 is not read by SIGMA.** Same as 0.1 with the site's normal **V5** code. Expect result 1 or 2: the stock gate.

0.3 **Stock UX.** Menu → Save / Load settings → Load from QR Code, with the V5 code. Expect "No compatible QR code found." / "Incompatible QR code.". Try the dial ×4/×8 on an fp LCD tile. Note where MENU, the QS button and half-press lead.

**Phase 1: the new BINs** (both together: SensorLab needs container API 7)

1.1 **Load.** Install both card-settings builds and check LOAD.LOG. In the QS, the QR tile still shows its code.
- `sq_test 40`: `vt_ok = 1`.
- The container `go_result` (`qsc_api.timing + 112`) = 0.

1.2 **AEL on the QR tile.** Expect the read page to open with live view and "Detecting QR code...".
- If nothing happens: `sq_test 40 goes` tells whether we were asked.
- Check whether the container's `QSC_Go` event fired (container live item 1/2).

1.3 **Phone, site V5 code of a different mode** (15–40 cm, then ×4).
- Expect `ProcessingComplete`.
- `sq_test 40`: `armed 1`, `decodes > 0`, `ours_ok ≥ 1`, `sensorlab 1`, `accepted 1`, `pending 1`.

1.4 **OK.** Expect the page to close to the setup menu; the selection is the code's mode.
- Back in the QS: `QR applied`, the DC/RES/FPS/RECIPE tiles changed, and the QR tile's own code equals the scanned one.
- Record one short clip to confirm the mode really applies.

1.5 **Refusal.** A code whose derived fields this build does not produce, e.g. a site code edited in VMAX (the tests' VMAX+1 case, or one from another SensorLab version). Expect "Incompatible QR code.", nothing applied, and `QR refused VMAX` on the tile.

1.6 **fp → fp.** Another fp's QR tile at ×4 / ×8 from 20–30 cm.

1.7 **SIGMA's own settings QR** (Save to QR Code on this camera, then read it). Expect the stock flow unchanged: SaveSettings, overwrite, saved.

1.8 **Exits.** MENU / QS button / half-press from the read page, then re-open the QS.
- No bounce back to the read page (container live item 4).
- `0xC3588D68` back to `0xC2DFE860` (`mem get`).

1.9 **Recording.** While recording, AEL on the QR tile does nothing (the tile is locked). Stop, wait 10 s, then the rest works.

## Unproven (the live items)

- Whether the stock decoder decodes in emulation: it does not even on its own version-20 output (it finds the finders, then `FUN_c05cb960` sampling fails; probably runtime state the firmware builds [I]). So "stock success → ours never runs" is proven with a stub of the stock decode.
- Whether the decoder input offsets `p+0x10/0x14/0x18/0x1C/0x20` hold on the camera. They are from `FUN_c05c49f0`'s locals [C] and pass through the real `FUN_c05c49f0` in emulation.
- Whether the v62 "ProcessingComplete after the stock incompatible" reads cleanly on screen (two state changes in one message), and whether the stock name line shows a stale name.
- That v8 is the OK key and v12 the back key: from the decompile [C/I]. The emulation runs the real functions with a fake handler object.
- The container items listed in its BUILD.md.
