# SensorLab-IMX410 v0.7.33test: a SensorLab QR code never reaches SIGMA's save page (2026-11-04, offline candidate)

Follows the v0.7.32test live run (`../20261104-qr-scan-build/live/`, SS3152/SS3153). QSContainer stays **v0.3.7**: it is unchanged and is already on the card.

## Live finding → cause → fix

**Live (v0.7.32test):**
- The read page opened from AEL.
- Our decoder read the version-5 code (`decodes 1315`, `ours_ok 4`).
- Our result hook accepted it 4×.
- But `oks 0`: the page went to "Select Destination Mode" with the name line `URL[i] − i`.

**Cause [C], from the Y5_ReadQR page data and the handler:**
- **There is no OK step.** Object 4262 "Processing" answers the state `ProcessingComplete` with a 2 s `timerEvent` → `controlAppState "Y5_ReadQR_SaveSettings"` (0xC2D19D7E..0xC2D19EE9).
- **The parser accepted our URL.** The stock v62 had already run its parser, and `FUN_c052bd38` accepted our URL as a SIGMA settings payload on the camera. My earlier offline guess that it would reject was wrong.
- **v8 is not the trigger.** The OK we hooked in v8 is never the trigger.

**Fix (v62 only; v8 is no longer hooked):**

| Result | Now |
|---|---|
| SensorLab URL, restores exactly | Applied at once (selection, dirty, `sq_push`). Only `MenuHandlerSubBase::v62` sees the message, then the page leaves through its stock back (read mode off → end message → "Return" to the setup menu). There is no `ProcessingComplete`, so no timer, no save page, and no parse. |
| SensorLab URL, refused / invalid | Handed to the stock v62 with the result code forced to 2 (and put back afterwards). That shows the stock "Incompatible QR code." through the branch that never parses. `QR refused <FIELD>` / `QR invalid` appears on the QR tile for 30 s. |
| Anything else (SIGMA's codes, other URLs) | The stock handler, untouched → `ProcessingComplete` → its save page. |

**Behaviour change:** there is no "show, then OK" step. A matching code is applied when it is read, because the page has no OK step to hang it on. If a confirmation step is wanted, it needs its own UI (e.g. a SensorLab page).

## Builds

| File | Bytes | sha256 |
|---|---|---|
| `card-settings-build/fpSup/SensorLab-IMX410_v0.7.33test.BIN` (**card**: settings from the card copy `../20261104-qr-scan-build/live/rb-SensorLab-IMX410_v0.7.32test.BIN`) | 203396 | `53d66f0facb18dbe75c87dc5a17001eaeb2faade538966c122fe307e545ce3cb` |
| `default-build/fpSup/SensorLab-IMX410_v0.7.33test.BIN` (blank record; frozen migration fixture) | 203396 | `686f8ef4357f227cc8cfbaa01669b9a2c808d96e871f27ef3127e05feb5856c5` |

- **Replace** the card's v0.7.32test with this file and delete the old one.
- **Resync** stays off, as in v0.7.32test.

## Tests

| Suite | Result |
|---|---|
| `qs/test_qrscan.py` (18) | OK (`qrscan-suite.log`); **mutants 22/22** (`qrscan-mutants.log`) |
| `qs/test_slqs.py` (68) | OK |
| `qs/test_settings_migration.py` (8, new fixture) | OK |
| `site/test_site.py` (9; local copy regenerated, version string only) | OK |
| `tools/test.py fast` | PASS |

The decoder (`qrdec.c`), the apply unit and the container did not change since build 1 (decoder mutants 18/18, apply 80 OK, container suites OK).

The parser's answer had to be forced in some tests. In emulation, `FUN_c052bd38` rejects our URL (its settings object is the harness's fake); on the camera it accepted it. Where a test needs the camera's answer, `stock_parse` is forced to 1: the live-bug reproduction, the SensorLab path, the refusal and "another URL completes as stock". The SensorLab path proves the parser is **not called** at all.

## Live check (after loading)

1. AEL on the QR tile → read page. Show the site's V5 code of a different mode.
   - Expect the page to close by itself (to the setup menu) within about a second of detection.
   - In QS: `QR applied`; DC/RES/FPS/RECIPE equal the code's; the QR tile's code equals the scanned one.
   - `sq_test 40`: `accepted = applied = 1`, `refused 0`.
2. A refused code (e.g. one with VMAX edited): "Incompatible QR code.", no destination page, nothing applied, tile `QR refused VMAX`.
3. SIGMA's own settings QR (Save to QR Code): stock flow → Select Destination Mode → save, unchanged.
4. Exits (MENU / QS / half-press) and recording, as in build 1. Check `0xC3588D68 = 0xC2DFE860` after leaving.
