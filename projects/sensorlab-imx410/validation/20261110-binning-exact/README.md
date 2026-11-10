# Exact merges: 2x2 / 3x3 / 6x6 / 1x2 / 1x3 (0.0.6test, 2026-11-10, offline)

Bei 11-10: 「2x2 3x3 6x6 ... 這是最重要的東西」「這是讓用戶能輕鬆使用像素合併的重點」;「現在只要有一邊是RWZM就都顯示RWZM
我整個不知道有沒有調整到正確的地方」. Goal: the merge presets are **real merges** — both axes 1:1, RWZM off, record = RES —
and the QS shows what each axis does. Offline only (no camera, no USB). [C] code / emulation, [I] inference.

Tables: `binning_table.py` → `tables.md`, `impact.json`. 0.0.5test sources: `before-sources/` (+ `presets-0.0.5test.json`).

## 1. Rules (quality.py in lockstep with core.c `q_isp`; the product list only)

`quality.qualities(..., vmargin_floor=...)` (= `core_qualities_tol`, slqs / ap_calc / page) now also applies the exact
rules inside `isp()` (`exact=`; default on with the floor). `core_qualities` / matrix.py / `tol=None` are unchanged.

- **(E) exact merge** — no CRCT bin, and per axis the merged extent (the readout window, or the DC on the readout grid
  when larger) is at most **CROP_W = 16 px** wider and **CROP_H = 4 rows** taller than the RES, losing at most
  **CROP_FOV = 1.5 %** of the DC on the readout grid → Zh = Zv = 1024 (RWZM off), record = (RES w, min(RES h, window
  h) even), the firmware centres the crop. If the ISP plan refuses the crop the old scale stays (never seen: §6).
- **(V) spare-row crop** — a recipe that keeps the RWZM (a horizontal ratio, or a CRCT bin: R2) and whose vertical
  ratio is above the aspect-keeping one `Zu = Zh·mh·hbin / (mv·vbin)` takes Zu, else 1:1, when that leaves
  **1..VCROP = 12** spare rows over the RES and keeps the vertical-margin floor (4.875 rows; at 1:1 R − N ≥ 9 → y0 4,
  margin ≥ 5). Pixels stay square, the record is the RES. A bin whose other axis is then 1:1 too takes R2 (1025, the
  +16 px readout) as before.
- **÷6 preset = ev(DC_h / 6) − VM_ROWS (10)**: the least even R − N with Zv = 1024 that keeps the floor (y0 4,
  margin 6). So 6x6 (2x2 + ISP 3x3) and 3x6 + RWZM H 2:1 record exactly the shown RES (no hidden shortening), and
  S16's ÷6 6x6 is back.

**Why these limits.** Every merge preset needs at most 16 px / 2 rows (`tables.md`): the RES grid is a16, and the
readouts' windows are a16 of DC/mh (e.g. S16 2x2 1056 for 1040; S35 3x3 1408 for 1392); rows are at most 2 over
(ev rounding). 16 px is also WIDEN (R2's one readout step). 4 rows = the stock UHD CROP profiles (2174 → 2170 at
1:1, RWZM off); stock FHD CROP crops 84 rows 1:1. FOV lost vs the DC on the readout grid: max 1.43 % (S16 3x3
698 → 688), i.e. only the preset's own a16 rounding. Larger gaps (a 2x2 at a /3 RES...) keep the scale.
VCROP 12 = the ÷6 presets' 10 rows + up to 2 from the 2x2/3 rounding (S35 / APS-C / HD R − N = 11).

## 2. Merge presets, before → after (12-bit; 11-bit fast and 14-bit variants identical)

`z` = Zh/Zv, rec = recorded raster. 1x2 / 1x3 were custom RES before (not presets). Full list in `tables.md`.

| format | merge | RES | recipe | 0.0.5test | 0.0.6test |
|---|---|---|---|---|---|
| OG | 2x2 | 3024×2020 | 2x2 | 1024/1024 · 3024×2014 · off | same (window 2014 rows: delivery, in tol) |
| OG | 3x3 | 2016×1346 | 3x3 | 1024/1024 · 2016×1344 · off | same |
| OG | 6x6 | 1008×672 → **1008×662** | 2x2+ISP3x3 / 3x6 | 1026/1024 · 1008×**664**; 2048/1024 · 1008×662 | 1026/1024 · **1008×662**; 2048/1024 · **1008×662** (RWZM on) |
| OG | 1x2 / 1x3 | 6048×2020 / 6048×1346 | 12v2 / 12v3 | off · 6048×2014 / 6048×1330 | same (V3 delivers 1330: tol) |
| HD | 2x2 / 3x3 | 3024×1700 / 2016×1134 | | off, = RES | same |
| HD | 6x6 | 1008×566 → **1008×556** | 2x2+ISP3x3 / 3x6 | 1026/1024 · 1008×**560**; 2048/1024 · 556 | **1026/1026** · 1008×556; 2048/1024 · 1008×556 |
| HD | 1x2 / 1x3 | 6048×1700 / 6048×1134 | | off, = RES | same |
| SQ | 2x2 / 3x3 | 2016² / 1344² | | off, = RES | same |
| SQ | 6x6 | 672×672 → **672×662** | | 1031/1024 · 672×662; 2048/1024 · 672×662 | same zooms, record = RES |
| SQ | 1x3 | 4032×1344 | 12v3 | off · 4032×1330 | same (V3 1330: tol) |
| S35 | 2x2 | 2096×1178 | 2x2 | off, = RES | same |
| S35 | 3x3 | 1392×786 | 3x3 | **1035/1024 · 1392×776 · ON** | **1024/1024 · 1392×786 · off** |
| S35 | 6x6 | 688×392 → **688×382** | | 1038/1026; 2095/1024 · 688×382 | 1038/**1024**; 2095/1024 · 688×382 |
| S35 | 1x2 / 1x3 | 4192×1178 / 4192×786 | | off, = RES | same |
| APS-C | 2x2 | 1968×1312 | 2x2 | **1032/1024 · 1968×1302 · ON** | **1024/1024 · 1968×1312 · off** |
| APS-C | 3x3 | 1312×874 | 3x3 | **1036/1026 · 1312×864 · ON** | **1024/1024 · 1312×874 · off** |
| APS-C | 6x6 | 656×436 → **656×426** | | 1031/1026; 2072/1024 · 656×426 | 1031/**1024**; 2072/1024 · 656×426 |
| APS-C | 1x3 | 3952×874 | 12v3 | **1024/1026 · 3952×864 · ON** | **off · 3952×874** |
| S16 | 2x2 | 1040×620 | 2x2 | **1039/1024 · 1040×610 · ON** | **1024/1024 · 1040×620 · off** |
| S16 | 3x3 | 688×412 | 3x3 | **1045/1026 · 688×406 · ON** | **1024/1024 · 688×412 · off** |
| S16 | 6x6 | 336×206 → **336×196** | 2x2+ISP3x3 / 3x6 | **not offered** (0.0.5test) | 1072/1024 · 336×196; 2145/1024 · 336×196 |
| S16 | 1x3 | 2096×412 | 12v3 | **1024/1028 · 2096×402 · ON** | **off · 2096×412** |

Every 2x2 / 3x3 / 1x2 / 1x3 preset: RWZM off, both axes 1:1, the readout (RS, fps) unchanged. Record = RES except
where the readout itself delivers fewer rows (OG 2x2 2014 / 2020, OG & SQ 1x3 1330 / 1346 / 1344: the existing 2 %
tolerance, shown yellow as before). Every ÷6 6x6 / 3x6: record = the shown RES, margin ≥ floor.

## 3. Impact on the other recipes

- **39 preset cells kept from 0.0.5test (489 recipes):** 473 unchanged; **10 (E)** = exactly the merges above
  (APS-C 2x2 / 3x3, S35 3x3, S16 2x2 / 3x3, each 12b + fast); **6 other**: APS-C 1K (1024×678) 1×1 / 1×1-h3 at 12 /
  fast / 14 — (V) gives the aspect-keeping ratio (3944/3955 → 3952/3952; 1314/3955 → 1317/3951), same readout and
  record. No recipe newly dropped or added, no readout change (asserted per cell in test_core "keeps the readout").
- **÷6 cells** (all recipes, before → after): record = RES 16→58 (OG), 36→58 (HD), 28→58 (SQ), 44→58 (S35 / APS-C),
  44→58 (S16, 14 recipes back); DNG DefaultScale (anisotropic) 0→0, 0→0, 2→2, 58→16, 12→8, 44→30. Cost: the ÷6 RES
  is 10 rows shorter (vertical FOV −1.5 % OG … −4.9 % S16, the price of square 1:1 rows with the margin).
- Presets: 45 → **57 cells** (+1x2, +1x3 per format; the 6 ÷6 cells move), 823 → **930 recipes**.
- 2x1 / 3x2 / 2x3 presets **not added**: 2x1 reads full height (OG 4040 rows > the R12 1710-row standby gate), 3x2 /
  2x3 are scaled on one axis at any /k preset, and HD would exceed the 12-row RES menu page.

## 4. UI (slqs.c + dcres.html in lockstep; site_page.js; menu)

- **Hint**: always the merge per axis `mh·hbin x mv·vbin`, `+RW` when the RWZM is on (either axis ≠ 1024, the forced
  1025 included): "2x2" (exact) vs "3x6+RW", "6x6+RW", "1x2+RW". Longest "9x18+RW" = 7 chars: the 8-byte buffer fits.
- **RES WIDTH / HEIGHT small line**: + " /2.00" = that axis' RWZM ratio (Zh or Zv / 1024) when the RWZM is on and the
  line stays ≤ 23 bytes (QSC_VALUE); "→3024×2004 · 1x2+RW" (22 B) has no room, so it is left out there.
- **RES list**: + `1x2` / `1x3` (full width, ev(H/2), ev(H/3)), labelled by the merge, picked by label like the K
  presets (`KL_N` 9 / 10, `resk`), after 6K; ÷6 height − 10 (`bin_h` / `binH`); div_text "6" for it.
- **Native menu RES page**: 10 → **12 rows** (HD: 11 presets + CUSTOM; `slm_page.py` SPEC cap, `menu_lists.CAP`,
  `slm_runtime.h`; `slm_page.h` regenerated). The FPS page already uses 50 rows with the same generator.
- Version **0.0.6test** (`fpSup/loader-v4/names_v4.py` SL41 + comment, `qs/build_slqs.py`).

## 5. Old QR codes (the 0.0.5test input-field rule, unchanged)

- Camera (`test_qrscan.OldCodes`, SLQS_SCAN_ALL=1): **2469 restored, 42 refused** — the same split as 0.0.5test
  (the 42 = the 14 S16 336×206 recipes, still not offered at that now-custom RES). The six old ÷6 cells are custom
  RES now; their expected recipes come from `gen_fps.case` (C core on the camera).
- Page (`test_client.js`): 1467 codes in preset cells restore their inputs; the 1044 codes in the six old ÷6 cells
  are custom cells computed by the engine (wasm / local server), not in `fps_data.js`, so the node harness skips them.
- `site_page.js ispZoom` mirrors (E) and (V) when it rebuilds the zoom from a code.

## 6. Tests

- `core/test_core.py` (quick + full in prelive): PASS. New step `exact`: every page preset cell (57) compared C vs
  Python with settings; **invariant** (C fields): each format's /2 2x2, /3 3x3, 1x2, 1x3 has a 12-bit merge with
  Zh = Zv = 1024 and record inside tol of the RES, the ÷6 6x6 and 3x6 record = RES, every RWZM-on recipe ≥ floor;
  **the invariant fails without the spare rows** (asserted); crop-limit cells (±16 px, 0..14 rows, odd heights, small
  DCs for the 1.5 % bound) and random cells near a merge. Core mutants: **13 new `exact:` mutants, 13/13 caught**
  (no (E), limits 15 px / 2 rows / 6 rows, no FOV bound, odd record, no (V), (V) not Zu first, Zu truncated, VCROP 9,
  floor not checked, (V) on a plain 1:1). Dropped as equivalent: "(E) with CRCT bins" (R2 refuses 1:1 with a bin,
  the same fallback) and "(E) refusal not caught" (no 1:1 crop within the limits is refused on any tested cell).
- qs: `test_slqs` 81 OK, `test_qrscan` (all) OK, `test_qr_present`, `test_settings_migration` 9 OK (frozen
  0.0.6test default fixture added), `test_resmagnet` 5 OK, `test_bootapply` 15 OK. Updated expectations: "RWZM" →
  "HxV+RW"; 14b 1x2 / 1x3 at 1:1 record true 14 (policy unchanged: RWZM off, no bin); counts 823 → 930, 45 → 57.
- menu: `test_menu` 15, `test_page` 13, `test_runtime` 14 OK (RES cap 12; mutant "RES cap too small" = 11).
- web: `test_client.js` 14/14, `test_web` 6/6, `test_server` 8/8, `test_site` 9/9 (published copy rebuilt locally).
- `tools/test.py fast`: PASS. `prelive`: see §8.

## 7. Builds

| build | file | sha256 |
|---|---|---|
| product | `out-product/fpSup/SensorLab-IMX410_v0.0.6test.BIN` (211 820 B) | `36f24a1267596cafaa99ed24830f3d4d9df20e58282e2da57661483edc470b83` |

`sq_test_off` 0x99F1 (`out-product/build-0.0.6test.json`). Sources: quality.py `60d0b75c…`, core.c `d9bf03e2…`,
slqs.c `0a1a14f2…`, dcres.html `9a6eb2b6…`, site_page.js `9350db21…`, slm_page.h `6fb53c0b…`. Site:
`fpSup/sensor_lab_imx410/` rebuilt locally (not published). QS-Share unchanged (0.0.2test). Before deploying,
rebuild with `--settings-from` the card's BIN.

## 8. prelive

`tools/test.py prelive` (log `tools/test-logs/prelive-20261110-203651/`): every unit suite **PASS** (slqs 81, apply,
lv-*, menu, menu-page, qsc, site, ui-layers, core script); mutants apply 141/141, qsc 43/43, qsc-page 84/84, lv-fit,
menu all caught. **5 FAILs were stale mutant patterns** (the code they mutate was replaced here, not survivors):
core "vm: est without the rounding half" (pattern now twice: the (V) code) and slqs "small DC forgets the ratio",
"hint: RWZM never shown", "hint: RWZM 1025 not unity", "hint: sub-items by geometry". Patterns updated / replaced and
rerun one by one: **all caught**, plus new ones caught: core "exact: (V) est without the rounding half"; slqs "÷6
without the spare rows", "no 1x2 / 1x3 presets", "hint: +RW only for a vertical ratio", "hint: the other axis'
ratio", "hint: ratio past the small line". The whole prelive was not rerun after these test-file-only edits.

## 9. Needs the camera

1. **Crop centring with RWZM off** [I]: S16 2x2 1056 → 1040 and S35 / APS-C / S16 3x3 (16 px, 2 rows) — DNG
   size = RES, no edge column / row of garbage, centred (compare to the 0.0.5test scaled framing).
2. **Purple**: OG / S16 2x2, 3x3 (RWZM off: expected 0, like OG 2x2 0/10); ÷6 6x6 (2x2 + ISP 3x3, R − N = 9 rows,
   margin 5) and 3x6 (margin 6) at OG and S16 — ~10 takes each; these are the first RWZM-on recipes with a 1:1
   vertical crop of 9–11 rows (the floor 4.875 rests on stock FHD).
3. RES menu page with 12 rows on HD (scrolls, CUSTOM last row reachable); the RES list's 1x2 / 1x3 rows; the hint
   "6x6+RW" / "/2.00" text on the LCD.
4. HD 6x6 now at Zv 1026 (aspect-keeping) instead of 1024: DNG DefaultScale off, framing.
