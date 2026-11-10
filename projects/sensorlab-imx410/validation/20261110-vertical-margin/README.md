# First-frame purple: the vertical margin (2026-11-10, offline)

Status: offline design + tests; **live checks passed 2026-11-10** (PURPLE builds, toggles 0: 0/30 twice, §8, `live/`, `live2/`). [C] = firmware code / emulation, [D] = archived live data,
[I] = inference. Tables are printed by `margin_table.py` (`tables.md`, `impact.json`).

## 1. The margin, as the firmware computes it [C]

`ContSet_Adr1` (C031BE60, `out/decomp/full/blk_c03.c` 19833–19853) lays the record into the RWZM output itself:

- `R = META_h / vbin` (`FUN_c032c860(…, 0x77)`, `FUN_c022ee90`), for our modes META_h = the receiver rows (TIM);
- if `Zv > 0x400`: `est = (Zv/2 + R·1024) / Zv` (the scaler's output rows), else `est = R`;
- crop `y0 = ((est − N) >> 2) << 1` when `est > N` (0x300F0684 = `y0 << 16 | y0 + N`; stock UHD 6..2176 ✓);
- RWZM phase (`FUN_c0633e60`) is a sub-row phase `< 0x200`; it adds no rows.
- The RWZM (0x300F0900) is on when either axis ≠ 0x400 (`FUN_c032d9a0`); both 1:1 → no scaler (BUFA0 route).

**margin = R − (y0 + N)·Zv/1024** rows of RWZM input left below the record (`quality.vmargin`, ×1024 integer).

## 2. Does it explain the archived data?

| condition | route | R | N | Zv | y0 | margin | purple |
|---|---|---|---|---|---|---|---|
| 12v2 full height 3024×2014 | BUFA1 | 2014 | 2014 | 1024 | 0 | 0.00 | 15/18 |
| 12v2 window DC 4020 → 3024×2010 | BUFA1 | 2010 | 2010 | 1024 | 0 | 0.00 | 8/8 |
| 14v2 full height (archive / defect-virtual) | BUFA1 | 2014 | 2014 | 1024 | 0 | 0.00 | 33/33, 4/4 |
| 14v2 HMAX 1000 | BUFA1 | 2014 | 2014 | 1024 | 0 | 0.00 | 8/10 |
| 12v2 RES 3008×2004 (rec 1998, Zv 1032) | BUFA1 | 2014 | 1998 | 1032 | 0 | 0.39 | 10/10 |
| 1×1 12-bit OG → 3024×2020 (2:1) | BUFA1 | 4040 | 2020 | 2048 | 0 | 0.00 | 3/14 |
| 12h2 OG → 3024×2020 (v 2:1) | BUFA1 | 4040 | 2020 | 2048 | 0 | 0.00 | 1/5 |
| 14 1×1 OG → 3024×2020 | BUFA1 | 4040 | 2020 | 2048 | 0 | 0.00 | 0/1 |
| SensorLab 2×2 OG → 3024×2014 (1:1 both) | no RWZM | 2014 | 2014 | 1024 | — | n/a | 0/10 |
| A baseline / NOWIN / SBSTOCK | BUFA1 | 3402 | 2160 | 1612 | 0 | 1.69 | 24/42, 4/6, 2/6 |
| A + ROWS (RX 3412) | BUFA1 | 3412 | 2160 | 1612 | 2 | 8.54 | 0/6 |
| A + RWZM (2170 @1600) | BUFA1 | 3402 | 2170 | 1600 | 2 | 8.25 | 0/6 |
| A + ROWS\|RWZM | BUFA1 | 3412 | 2170 | 1600 | 6 | 12.00 | 0/6 |
| UHD 25p 12fastW | BUFA1 | 3402 | 2160 | 1612 | 0 | 1.69 | 13/27 |
| stock UHD 29.97 (mode 7) | BUFA1 | 3412 | 2170 | 1600 | 6 | 12.00 | 0/29 |
| stock FHD 29.97 (mode 106) | BUFA7 | 1708 | 1090 | 1600 | 0 | 4.88 | 0/9 |

- **Clean / purple split: yes, every RWZM-on row fits.** Every purple condition has margin ≤ 1.69 (and y0 = 0);
  every clean one has margin ≥ 4.875. 113/193 purple at ≤ 1.69 vs 0/56 at ≥ 4.875 (one 0/1 at margin 0 is n = 1).
- **Exception 1 — 2×2 (0/10) at margin 0:** both axes 1:1, so no RWZM and not BUFA1 (v27 trace). The rule only
  applies with the RWZM on. Consistent, not a contradiction.
- **Exception 2 — the rate inside the purple group is not explained by the margin:** it follows the vertical ratio
  (1:1 / 1.03 ≈ 95–100 %, 1.574 ≈ 54 %, 2:1 ≈ 21 %), all at margin 0..1.7. The margin is the switch, not the rate.
- **1:1 vertical with the RWZM on (1×2 recipes):** Zv = 0x400 so est = R and the scaler passes rows 1:1; the margin
  is RX rows − BUFA1 lines (0x30182210 = N) − y0: 0 in every 12v2 / 14v2 take (RX 2010/2014 = BUFA1 2010/2014).
- Untested gap: no BUFA1 data between 1.69 and 8.25. The 4.875 floor rests on stock FHD (BUFA7). The live check decides.

## 3. The floor: least stock margin = 4.875 rows

All 28 stock CinemaDNG movie routes (`raw-profiles.json`, rows checked against the TIM rows of `mode_tables.csv`):
UHD ×4 = 12.000, FHD ×9 (modes 27/115/220/106/125/218/109/58/89) = **4.875** (1708 rows, 1090 at 1600, y0 0),
CROP ×15 = 1:1 both axes (RWZM off, no margin; UHD CROP 2174 → 2170). Floor `quality.VMARGIN = 1708·1024 −
1090·1600 = 4992` (/1024 = 4.875), exported as `CD_Q_VMARGIN`.

## 4. The change (core + Python reference in lockstep) — Bei 11-10: never read more rows

First candidate (ext rows, recipe A window 3402 → 3410) passed live (§8) but raised RS; Bei (community: do not raise
rolling shutter) replaced it the same day. **0.0.5test reads no extra rows: every offered recipe keeps its readout, RS,
VMAX range and fps exactly as the pre-fix core.**

- `isp-lab/host/quality.py`: `vmargin()`, `_margin_fix()`, opt-in `qualities(..., vmargin_floor=)`, applied **after**
  `pick()` (a quality keeps the readout variant it had; else its fps could move). `tol=None` / matrix.py unchanged.
- `core/core.c|h`: `vmargin`, `q_margin`; `core_qualities_tol` (the product list: slqs, ap_calc, preview, wasm)
  applies the floor after the pick, `core_qualities` does not (= matrix). No new struct field; `core_quality` layout
  unchanged.
- A recipe below the floor, on the same readout:
  1. **both RWZM ratios smaller by one factor**: the largest `Zv' < Zv` that keeps the floor, `Zh' = round(Zh × Zv' /
     Zv)` (exactly the same factor when Zh = Zv; else the pixel aspect moves ≤ 0.047 %). Record size (RES) unchanged;
     the firmware centres the smaller crop (x0 / y0) in the same input window. Horizontal always fits (less input).
  2. **an axis at 1:1** (no ratio to shrink, e.g. 12v2 vertical 1:1, 12h2 horizontal 1:1): a **shorter record** at
     the same ratios, inside the 2 % tolerance (12v2 OG 3024×2020: 2014 → 2004 rows).
  3. **both together** (Bei 11-10: keep offering them): the longest record inside the 2 % tolerance, at the largest
     common ratio that keeps the floor.
  4. **steps 2–3 again with the tolerance widened to 3 %** (Bei 11-10, option 2) — only reached by recipes 1–3 cannot
     keep; the longest record that reaches the floor, so the widening is exactly what each needs (≤ 3 %). All other
     recipes stay at 2 %. `quality.VM_TOL` = `CD_Q_VM_TOL_NUM / _DEN` = 3/100.
  5. else **not offered** (14 presets, all S16 336×206: they would need ≈ 4.9 %, see §5).
- **Recipe A** (UHD 29.97 12b 1×1, DC 6048×3402 → 3840×2160): window 3402 (unchanged), **Zh = Zv = 1612 → 1608**,
  record 3840×2160; crop x0 4 / y0 2 (firmware est 3851 × 2166); input used 6030 × 3392 of 6048 × 3402 (FOV −0.25 %
  both axes); **margin 6.98 rows** (was 1.69); RS 21.348 ms and fps max 46.628 unchanged. UHD25 12fastW: same zoom.
- `preview/fps_data.js` regenerated (`gen_fps.py` passes `vmargin_floor`); `preview/site_page.js` `ispZoom` mirrors
  step 1 (QR decode). VERSION 0.0.5test (`qs/build_slqs.py`, local `fpSup/loader-v4/names_v4.py` SL41).
- Not changed: `dcres.html` logic, ap.c, apply gates, MB/s (rec unchanged except the shorter records).
  The published site copy (`fpSup/sensor_lab_imx410/`) was **not** rebuilt (`test_site` publication test fails until it is).

## 5. Impact on the 45 preset cells (837 recipes before; `tables.md`, `impact.json`)

| kind | recipes |
|---|---|
| both ratios smaller | 535 |
| shorter record | 246 |
| both ratios smaller + shorter record | 10 |
| RWZM off (unchanged) | 32 |
| **not offered** | **14** (all S16 336×206) |

- 38 recipes use the wider tolerance (record 2–2.55 % short of the RES): S35 688×392 14, APS-C 656×436 14,
  S16 688×412 8, OG 1008×672 2. Every other shorter record is within 2 %.
- RS, VMAX range and fps of every offered recipe: **identical** to the pre-fix core (asserted in `margin_table.py`
  and per cell in `test_core` "vmargin keeps the readout").
- FOV loss (ratio shrink): median 0.39 %, max 1.21 % (low vertical ratios, e.g. CRCT v3 at Zv ≈ 1075).
- DNG DefaultScale: on/off unchanged for every recipe; 143 recipes that already had one (anisotropic by design, e.g.
  S35 688×392 12b 1×1 78/77 → 856/845) move ≤ 0.047 % to the new Zh/Zv. No recipe gains a DefaultScale.
- **The 14 not offered** (S16 336×206: `12v2-v3`, `14v2-v3`, `2x2-v3`, `3x6` … list in `tables.md`): the input rows equal
  the record (Zv 1024, or Zh 1024), so the floor needs R − y0 − N ≥ 4.875 with y0 = (R − N)/4·2 → N = R − 10 = 196
  of 206 ≈ 4.9 % short (> 3 %).
- Custom cell 5904×3320 → 2000×1124 keeps all 20 (10 of them with a record up to 3 % short).

## 6. Builds (core.c `c3ad41c6…`, quality.py `0cfde6fe…`, slqs.c `ff9a0fee…` = the 0.0.4test client + §9, ap.c `582287fd…`)

Version stays **0.0.5test** (only the superseded extra-rows PURPLE build ever reached a card; tell them apart by
sha256 and by recipe A's window: 3410 rows there, 3402 here).

| build | file | sha256 |
|---|---|---|
| product | `out-product/fpSup/SensorLab-IMX410_v0.0.5test.BIN` (210 000 B) | `dd00aea48cded59e570aeb04f22a8cdefe999c737cd8b620858d99a86255dd45` |
| PURPLE TEST | `out-purple-test/fpSup/SensorLab-IMX410_v0.0.5test.BIN` (212 288 B) | `3a7c9d589afc212732be3e30dec93fd0f7dce5d581d42fcd642d614b72da8d62` |

Product `sq_test_off` 0x99E9; PURPLE `sq_test_off` 0x9D7F, `rec_delay.base_off` / ring at block + 0x33D40, purple
`bits_off` +0x33D60 (use the json of the build actually deployed). Default settings: **rebuild with `--settings-from`
the card's BIN before deploying** (`--purple-test --out <dir named *purple*>`). Never release the PURPLE BIN.
STATE_RESERVE unchanged. Sources before the change: `before-sources/`; the superseded extra-rows sources are not kept.

## 7. Tests (offline, 2026-11-10, current build)

- `core/test_core.py` full: **PASS**. New per compared tol cell: `vmargin floor` (every product recipe ≥ floor, from the C
  fields by an independent copy of the firmware formula) and `vmargin keeps the readout` (same args / window / fps as the
  list without the margin; Zh' = round(Zh·Zv'/Zv)); small-RES cells at tol 0 / 2 / 3 % with VMAX steps (steps 3–5).
  Core mutants: **84/84 caught** (22 `vm:` ones). Two candidate mutants were dropped as equivalent on all data: "3 % retry for every tol"
  (a tol ≥ 3 % retries with the same or a narrower band) and "record not put back after step 2" (only matters if
  `core_isp_plan` refuses a shorter record, which never happens in the compared sets).
- `margin_table.py`: RS, VMAX range and fps identical for all 823 offered preset recipes (asserted).
- Web: `test_server` 8/8, `test_web` 6/6, `test_client.js` 14/14 (old-code corpus 2469 / 42), `test_site` all but the
  publication copy (published `fpSup/sensor_lab_imx410/` not rebuilt).
- Camera client (`SLQS_SCAN_ALL=1`): `test_qrscan` + `test_slqs` + `test_qr_present` + `test_dc_steps` +
  `test_settings_migration`: 124 tests OK. QR mutants (`test_qrscan.py --mutate`): **42/42 caught** (new: inputs only,
  the AD / sensor crop are inputs, no rate map, rate-map max / clamp / AD, 29↔30 after a map). The two `Tile` tests
  that failed before this change (container API 9, the 0.0.4test FORMAT dial) were updated to those values.
- apply (`test_apply`, hirate preview/route, lv-*: 135 OK), `test_purple` 11/11, menu (12/12 mutants),
  `tools/test.py fast`: PASS except the site publication copy.
- Tests changed for the new values (ground truth = `qualities(..., vmargin_floor)`): FF_12V2 record 2010 → 2000;
  HD 3x2 live2 visible 1686 → 1677; the S16 336×206 3x6 high-rate cases move to HD 1008×566 3x6 (S16 336×206 3x6 is
  not offered; same full-height readout and rates; record 556 rows); the 16:9 LV-fit tests use UHD 1×1 (live3 HD 2K
  3x2 now records 2016×1128); preset counts 837 → 823; BIN budget +2 KiB; frozen 0.0.5test default fixture.
- Not re-run on the final build: the full `prelive` (an earlier one on the extra-rows build passed apply 141 / core 77
  / qsc 43 / qsc-page 84 / slqs 122 mutants; this change touches only core.c, quality.py, slqs.c qr_restore and the
  web page).

## 8. Live results

**Proportional-zoom build (`live2/README.md`, PURPLE sha 5a882f15, toggles 0; steps 1–2, before step 3 was added):**
recipe A **0/10** (Zh = Zv 1608, window 3402, RS 21.348 ms unchanged), UHD 25p 12fastW **0/10** (RS 20.052 ms
unchanged), Bei's 14b 1×2 OG2K **0/10** (DNG dy). Step 3 changes none of these three recipes (it only touches the
10 recipes that steps 1–2 could not keep), so the result carries over to the current build; not re-run.

### 8.1 Superseded extra-rows build (`live/README.md`)

That card ran the first 0.0.5test (recipe A window 3410, RS 21.397). It shows the margin is the cause; the current
build (same floor, smaller ratios instead of rows) needs the same re-check. PURPLE TEST, toggles 0, settings from the card: **recipe A 0/10** (ring ff; was 24/42), **UHD 25p 12fastW
0/10** (was 13/27), **Bei's 14b 1×2 OG2K 6048×4040 → 2016×1346 0/10** (DNG dy check; ring not armed). The 1×2 12v2
shorter-record case was not run separately.

## 8a. Live protocol for the current build

1. Deploy the PURPLE TEST 0.0.5test (rebuilt `--settings-from`), QS-Share 0.0.2test, no Gyro2; reboot with
   `ui_drive.py reboot`. `bits` = 0 (toggles off: the new margin is the thing under test).
2. Recipes, ~10 takes each (2 s, ring `ff`: 1 = purple, 2 = written), plus one DNG spot check each:
   - **A**: UHD 29.97 12b 1×1 (DC 6048×3402 → 3840×2160). Sensor V window **3402 rows (unchanged, RX 40..3442)**, RS
     21.348 ms, rec RWZM **1608 / 1608** (0x300F0908/090C = `0x00DC_0648`, phase 0xDC per FUN_c0633e60), BUFA1 crop y0 2 / x0 4 output px (0x300F0684 = `0x0002_0872`), DNG 3840×2160.
   - **UHD 25p 12fastW** (same DC/RES): same window.
   - **12v2** and **14v2** OG → RES 3024×2020: DNG must be **3024×2004** (shorter record), RX 2014 rows.
3. Expect **0 purple** in every set (baseline was 24/42, 13/27, ~95 %). One purple take = the floor is too low for
   BUFA1: next step is the stock UHD margin (12 rows) as the floor.
4. Freeze: stop, log the last action, report.

## 9. Old QR codes keep working (Bei, 2026-11-10)

A code is accepted when its **input** fields come back from the restored selection; the others are derived by the
current core and may differ (`slqs.c` `QF_INPUT` / `qr_diff` / `qr_map_rate`, `site_page.js` `QR_INPUTS`, same rule).

- **Inputs (17):** VER, DCW, DCH, RESW, RESH, FPS pick, AD, MH, MV, HBIN, VBIN, KH, KV, KM, FMT, SCW, SCH.
- **Derived (10):** VMAX, HMAX (for a pick 29 / 30 only the code's rate), KEY (the readout variant the core picks),
  RCP and RESC flags (follow HBIN/VBIN and RES), VISW, VISH, RS, WINW, WINH.
- **Rate rule:** a common rate (pick 0..28) is that rate. A pick 29 / 30 first restores its exact rate; if the inputs
  do not come back (the rate is past the recipe's maximum), `qr_map_rate` takes the same recipe (AD MH MV HBIN VBIN SCW
  SCH): pick 30 → its maximum (VMAX = lo); pick 29 → `ceil(VMAX × HMAX / hm)` (the fastest step not faster than the
  code's rate — what any rate restores to) clamped to lo..16384. After a map, 29 and 30 count as the same pick (a
  tuned rate past the maximum becomes the maximum; a CRCT-bin maximum is not a QS "mark" and shows as 29).
- **Still refused:** bad CRC / version / format, inputs that give no recipe — now including the **14 recipes no longer
  offered** — and a common rate the recipe cannot reach (none in the corpus: fps are unchanged).
- **Corpus** (`qs/test-fixtures/qr-old-codes/`, `gen_corpus.js` = the page's encoder over the 0.0.4test
  `before-sources/fps_data.js`): 2511 codes (837 recipes × max / highest common rate / tuned; 881 pick 30, 841 pick
  29, 789 common). Camera client (`test_qrscan.OldCodes`, `SLQS_SCAN_ALL=1`): **2469 restored with the same inputs**
  (624 with other derived fields: the shrunk RWZM changes no field in the payload, the shorter records change VISH),
  **42 refused = exactly the 3 codes of each of the 14 recipes not offered**. Web page (`test_client.js`): same split.
- The rate map is not needed by any corpus code (RS / fps unchanged); `test_qrscan.Restore.test_a_rate_the_recipe_cannot_
  give_maps_inside_its_range` covers it with synthetic codes (30 past the maximum, 29 past it, 29 on another HMAX).
