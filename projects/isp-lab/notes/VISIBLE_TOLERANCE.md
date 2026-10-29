# Visible tolerance: each recipe's own visible RES (2026-10-29)

Bei 10-29 (QS_DC_RES_SPEC.md 看到的尺寸與寬容), final model of the day:

- The UI shows only the **visible** size = DNG DefaultCrop = raster − stock 16 × 10.
- **Nominal** visible per DC × RES = clean raster − 16 × 10 (OG 3K = 3008×2010).  It is remembered.
- A recipe whose raster is at most **2 % short per axis** is listed.  Selecting it shows the RES at that recipe's own
  visible size (OG 3K + 14b 1x2 → 3008×2004); selecting a full recipe again restores the nominal.  No shared minimum,
  so switching recipes never drifts the RES.  (Superseded the same day: a shared visible size = smallest raster, and a
  0.5 % limit.)

Offline only.  Code: `quality.qualities(..., tol=0.02)` → each case gets `visible` (its own) and `nominal`; default off,
so matrix.json and every existing test are unchanged.  Data: `projects/sensorlab-imx410/preview/fps_data.js`
(`gen_fps.py --tol 0.02`): recipe `rec` (raster) + `vis` (own visible), top-level `tol` and `nominal["DC:WxH"]`.  The
case keys stay the clean raster.

## Mechanism

- **Only rows come short**, and only on full-height vertical merges.  V2 full frame 2014 rows for 4040/2 = 2020
  (−0.30 %); 3x3 1344 for 1346.7 (−0.20 %); new V3 (1x3, 2x3, 14b 1x3) 1330 for 1346.7 (−1.24 %); at SQ the new V3 full
  frame 1330 for 4032/3 = 1344 (−1.04 %): R16 now keeps the whole frame instead of refusing.  Widths are never short:
  `readout_cfg.plan` trims a format within 0.5 % and refuses anything wider, so `quality.readout` never returns a raster
  narrower than the DC.  f12v3w18 (1324 rows, −1.68 %) is within 2 %, but no preset DC picks it: w2C or W covers every
  preset width it could serve.
- **The pixel pitch stays the clean one, and the raster is short.**  With `tol`, `isp()` takes each axis' RWZM from the
  DC on the readout grid (`nom = cw/mh, ch/mv`) instead of from what the readout delivered.  At scale 1 the raster is
  just shorter (OG 3K V2: 3024×2014).  On a downscaled RES the shortfall also shows up as rows (OG 1K 14b 1x3:
  1008×**664**), not as today's silent 1.2 % vertical stretch into 672 rows.  Every recipe of a case then has the same
  record-pixel pitch (within 0.1 %, the R2 1025), so a recipe's visible size is a true fraction of the DC's field of view.
  FOV loss = rows short / clean raster.
  Side effect: recipes that are exact today record 2–8 rows fewer under `tol`, so their raster differs from
  matrix.json.  These are the OG 1K/2K 1x2, 2x2, 3x2, 3x3, 1x3 and 2x3 classes, which today are scaled to the full RES.
- **Margin**: the stock 16 × 10, always.  No recipe crops more than stock, so the act words (0x24/0x2C =
  rec − 16/10) and DefaultCrop work as today.  Alignment holds: rasters are ×16 wide and even high (R8).
- **Accept rule** (`quality.short_ok`): raster ≤ clean RES, and each axis at most `tol` short.  At 2 % no recipe that
  qualifies today is lost (checked over all 45 presets).  At 0.5 % OG 1K/2K and SQ would have lost every 1x3/2x3 recipe:
  once they are no longer stretched, they are 1.2 % short.
- **Centring (unmeasured)**: the R16 row crop is centred in the delivered frame.  A full-height short delivery sits
  wherever the readout's y0 puts it: V2 from y0 = 20, new V3 from 20 + 28 skip.  Its centre offset vs 1x1 is at most
  the shortfall (≤ 0.6 % of height).

## Summary: recipes that show a reduced RES

Only full-height DCs change: **OG** 1K / 2K / 3K and **SQ** 0.7K / 1K / 1.5K.  HD, S35, APS-C and S16 use windows that
deliver exact rows, so nothing changes there.  OG/SQ ≥ 2.5K: only 1x1 recipes qualify, and none is short.  87 recipes
show a reduced RES, 53 of them newly listed.  Widths never shrink.

- OG 1K (nominal 992×662): **992×660** (−2 rows, 0.30 %): 12b 3x2, 12b 1x2, 14b 1x2, 12b 2x2, 11b 2x2, 12b 3x3, 11b 3x3, 11b 3x2, 11b 1x2 (+17 ISP-bin); **992×654** (−8 rows, 1.19 %): 12b 2x3, 12b 1x3, 14b 1x3, 11b 2x3, 11b 1x3 (+5 ISP-bin)
- OG 2K (nominal 2000×1336): **2000×1334** (−2 rows, 0.15 %): 12b 3x3, 11b 3x3; **2000×1332** (−4 rows, 0.30 %): 12b 3x2, 12b 1x2, 14b 1x2, 12b 2x2, 11b 2x2, 11b 3x2, 11b 1x2 (+3 ISP-bin); **2000×1320** (−16 rows, 1.19 %): 12b 2x3, 12b 1x3, 14b 1x3, 11b 2x3, 11b 1x3 (+3 ISP-bin)
- OG 3K (nominal 3008×2010): **3008×2004** (−6 rows, 0.30 %): 12b 1x2, 14b 1x2, 12b 2x2, 11b 2x2, 11b 1x2
- SQ 0.7K (nominal 656×662): **656×654** (−8 rows, 1.19 %): 12b 2x3, 12b 1x3, 14b 1x3, 11b 2x3, 11b 1x3 (+5 ISP-bin)
- SQ 1K (nominal 1008×1014): **1008×1002** (−12 rows, 1.17 %): 12b 2x3, 12b 1x3, 14b 1x3, 11b 2x3, 11b 1x3 (+3 ISP-bin)
- SQ 1.5K (nominal 1328×1334): **1328×1320** (−14 rows, 1.04 %): 12b 2x3, 12b 1x3, 14b 1x3, 11b 2x3, 11b 1x3 (+3 ISP-bin)

Max-fps gains from the newly listed recipes: **OG 3K 52.2 → 105.1** (11b 2x2 at 3008×2004; 14b 1x2 37.1, 12b 1x2 76.0)
and **OG 2K 105.1 → 146.9** (11b 3x3 at 2000×1334).  OG 1K and SQ gain recipes (SQ 1x3/2x3 at 55–145 fps) but not
the case's max fps.

## All presets

| DC | RES | clean raster | nominal visible | recipes today → 2 % | full / reduced | reduced visible sizes (height loss) | max fps today → 2 % (all) | main list h1v1 |
|---|---|---|---|---|---|---|---|---|
| OG | 1K | 1008×672 | 992×662 | 46 → 58 | 22 / 36 | 992×660 (−0.30 %), 992×654 (−1.19 %) | 289.4 → 289.4 | 289.4 → 289.4 |
| OG | 2K | 2016×1346 | 2000×1336 | 26 → 36 | 16 / 20 | 2000×1334 (−0.15 %), 2000×1332 (−0.30 %), 2000×1320 (−1.19 %) | 105.1 → 146.9 | 105.1 → 146.9 |
| OG | 3K | 3024×2020 | 3008×2010 | 5 → 10 | 5 / 5 | 3008×2004 (−0.30 %) | 52.2 → 105.1 | 52.2 → 105.1 |
| OG | 3.5K | 3584×2394 | 3568×2384 | 3 → 3 | 3 / 0 | — | 41.3 → 41.3 | 41.3 → 41.3 |
| OG | 4K | 4032×2692 | 4016×2682 | 3 → 3 | 3 / 0 | — | 41.3 → 41.3 | 41.3 → 41.3 |
| OG | 5K | 5120×3420 | 5104×3410 | 3 → 3 | 3 / 0 | — | 41.3 → 41.3 | 41.3 → 41.3 |
| OG | 6K | 6048×4040 | 6032×4030 | 3 → 3 | 3 / 0 | — | 41.3 → 41.3 | 41.3 → 41.3 |
| HD | 1K | 1008×566 | 992×556 | 58 → 58 | 58 / 0 | — | 289.4 → 289.4 | 289.4 → 289.4 |
| HD | FHD | 1920×1080 | 1904×1070 | 36 → 36 | 36 / 0 | — | 171.5 → 171.5 | 171.5 → 171.5 |
| HD | 2K | 2016×1134 | 2000×1124 | 36 → 36 | 36 / 0 | — | 171.5 → 171.5 | 171.5 → 171.5 |
| HD | 3K | 3024×1700 | 3008×1690 | 10 → 10 | 10 / 0 | — | 124.1 → 124.1 | 124.1 → 124.1 |
| HD | 3.5K | 3584×2016 | 3568×2006 | 3 → 3 | 3 / 0 | — | 48.7 → 48.7 | 48.7 → 48.7 |
| HD | UHD | 3840×2160 | 3824×2150 | 3 → 3 | 3 / 0 | — | 48.7 → 48.7 | 48.7 → 48.7 |
| HD | 4K | 4032×2268 | 4016×2258 | 3 → 3 | 3 / 0 | — | 48.7 → 48.7 | 48.7 → 48.7 |
| HD | 5K | 5120×2880 | 5104×2870 | 3 → 3 | 3 / 0 | — | 48.7 → 48.7 | 48.7 → 48.7 |
| HD | 6K | 6048×3402 | 6032×3392 | 3 → 3 | 3 / 0 | — | 48.7 → 48.7 | 48.7 → 48.7 |
| S35 | 0.7K | 688×392 | 672×382 | 58 → 58 | 58 / 0 | — | 289.4 → 289.4 | 289.4 → 289.4 |
| S35 | 1K | 1024×576 | 1008×566 | 36 → 36 | 36 / 0 | — | 236.1 → 236.1 | 236.1 → 236.1 |
| S35 | 1.5K | 1392×786 | 1376×776 | 36 → 36 | 36 / 0 | — | 236.1 → 236.1 | 236.1 → 236.1 |
| S35 | 2K | 2096×1178 | 2080×1168 | 10 → 10 | 10 / 0 | — | 176.5 → 176.5 | 176.5 → 176.5 |
| S35 | 2.5K | 2784×1566 | 2768×1556 | 3 → 3 | 3 / 0 | — | 85.0 → 85.0 | 85.0 → 85.0 |
| S35 | 3K | 3072×1728 | 3056×1718 | 3 → 3 | 3 / 0 | — | 85.0 → 85.0 | 85.0 → 85.0 |
| S35 | 3.5K | 3584×2016 | 3568×2006 | 3 → 3 | 3 / 0 | — | 85.0 → 85.0 | 85.0 → 85.0 |
| S35 | 4K | 4192×2358 | 4176×2348 | 3 → 3 | 3 / 0 | — | 85.0 → 85.0 | 85.0 → 85.0 |
| APS-C | 0.6K | 656×436 | 640×426 | 58 → 58 | 58 / 0 | — | 289.4 → 289.4 | 289.4 → 289.4 |
| APS-C | 1K | 1024×678 | 1008×668 | 36 → 36 | 36 / 0 | — | 215.2 → 215.2 | 215.2 → 215.2 |
| APS-C | 1.5K | 1312×874 | 1296×864 | 36 → 36 | 36 / 0 | — | 215.2 → 215.2 | 215.2 → 215.2 |
| APS-C | 2K | 1968×1312 | 1952×1302 | 10 → 10 | 10 / 0 | — | 159.5 → 159.5 | 159.5 → 159.5 |
| APS-C | 2.5K | 2624×1742 | 2608×1732 | 3 → 3 | 3 / 0 | — | 79.1 → 79.1 | 79.1 → 79.1 |
| APS-C | 3K | 3072×2038 | 3056×2028 | 3 → 3 | 3 / 0 | — | 79.1 → 79.1 | 79.1 → 79.1 |
| APS-C | 3.5K | 3584×2378 | 3568×2368 | 3 → 3 | 3 / 0 | — | 79.1 → 79.1 | 79.1 → 79.1 |
| APS-C | 4K | 3952×2624 | 3936×2614 | 3 → 3 | 3 / 0 | — | 79.1 → 79.1 | 79.1 → 79.1 |
| S16 | 0.3K | 336×206 | 320×196 | 58 → 58 | 58 / 0 | — | 395.3 → 395.3 | 395.3 → 395.3 |
| S16 | 0.7K | 688×412 | 672×402 | 36 → 36 | 36 / 0 | — | 395.3 → 395.3 | 395.3 → 395.3 |
| S16 | 1K | 1040×620 | 1024×610 | 10 → 10 | 10 / 0 | — | 322.8 → 322.8 | 322.8 → 322.8 |
| S16 | 1.5K | 1392×822 | 1376×812 | 3 → 3 | 3 / 0 | — | 158.8 → 158.8 | 158.8 → 158.8 |
| S16 | 2K | 2096×1240 | 2080×1230 | 3 → 3 | 3 / 0 | — | 158.8 → 158.8 | 158.8 → 158.8 |
| SQ | 0.7K | 672×672 | 656×662 | 48 → 58 | 48 / 10 | 656×654 (−1.19 %) | 289.4 → 289.4 | 289.4 → 289.4 |
| SQ | 1K | 1024×1024 | 1008×1014 | 28 → 36 | 28 / 8 | 1008×1002 (−1.17 %) | 147.2 → 147.2 | 147.2 → 147.2 |
| SQ | 1.5K | 1344×1344 | 1328×1334 | 28 → 36 | 28 / 8 | 1328×1320 (−1.04 %) | 147.2 → 147.2 | 147.2 → 147.2 |
| SQ | 2K | 2016×2016 | 2000×2006 | 10 → 10 | 10 / 0 | — | 105.3 → 105.3 | 105.3 → 105.3 |
| SQ | 2.5K | 2688×2688 | 2672×2678 | 3 → 3 | 3 / 0 | — | 52.4 → 52.4 | 52.4 → 52.4 |
| SQ | 3K | 3072×3072 | 3056×3062 | 3 → 3 | 3 / 0 | — | 52.4 → 52.4 | 52.4 → 52.4 |
| SQ | 3.5K | 3584×3584 | 3568×3574 | 3 → 3 | 3 / 0 | — | 52.4 → 52.4 | 52.4 → 52.4 |
| SQ | 4K | 4032×4032 | 4016×4022 | 3 → 3 | 3 / 0 | — | 52.4 → 52.4 | 52.4 → 52.4 |

Recipe counts include ISP-bin variants; "main list" = h1v1 only, which is what the preview's FPS list counts.

## Per recipe (cases with a reduced recipe; tol 2 %)

"short" = clean raster − recipe raster.  "readout live at this DC" = the same readout (key, crop, R16 rows) appears in
a live isp-lab record at any RES (verdicts seen); **never** = no live record.  No recipe here has been recorded at its
tolerance raster (no matching case id in validation/).


### OG 1K — raster 1008×672, nominal 992×662

| recipe | raster | visible (RES shown) | short (cols, rows) | short % (h) | ≤ 2 % | fps | status vs today | readout live at this DC |
|---|---|---|---|---|---|---|---|---|
| 12b 2x3 | 1008×664 | 992×654 | 0, 8 | 1.19 | yes | 107.7 | today 1008×672 (scaled to the RES) | fail/pass |
| 12b 2x3 h3v1 | 1008×664 | 992×654 | 0, 8 | 1.19 | yes | 107.7 | today 1008×672 (scaled to the RES) | fail/pass |
| 12b 3x2 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 76.0 | today 1008×672 (scaled to the RES) | fail/pass |
| 12b 3x2 h1v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 76.0 | new | fail/pass |
| 12b 1x2 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 76.0 | today 1008×672 (scaled to the RES) | fail/pass |
| 12b 1x2 h1v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 76.0 | new | fail/pass |
| 12b 1x2 h3v1 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 76.0 | today 1008×672 (scaled to the RES) | fail/pass |
| 12b 1x2 h3v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 76.0 | new | fail/pass |
| 12b 1x3 | 1008×664 | 992×654 | 0, 8 | 1.19 | yes | 107.7 | today 1008×672 (scaled to the RES) | pass |
| 12b 1x3 h3v1 | 1008×664 | 992×654 | 0, 8 | 1.19 | yes | 107.7 | today 1008×672 (scaled to the RES) | pass |
| 14b 1x2 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 37.1 | today 1008×672 (scaled to the RES) | fail/pass |
| 14b 1x2 h1v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 37.1 | new | fail/pass |
| 14b 1x2 h3v1 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 37.1 | today 1008×672 (scaled to the RES) | fail/pass |
| 14b 1x2 h3v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 37.1 | new | fail/pass |
| 14b 1x3 | 1008×664 | 992×654 | 0, 8 | 1.19 | yes | 52.6 | today 1008×672 (scaled to the RES) | pass |
| 14b 1x3 h3v1 | 1008×664 | 992×654 | 0, 8 | 1.19 | yes | 52.6 | today 1008×672 (scaled to the RES) | pass |
| 12b 2x2 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 77.0 | today 1008×672 (scaled to the RES) | fail/pass |
| 12b 2x2 h1v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 77.0 | new | fail/pass |
| 12b 2x2 h3v1 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 77.0 | today 1008×672 (scaled to the RES) | fail/pass |
| 12b 2x2 h3v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 77.0 | new | never |
| 11b 2x2 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 105.1 | today 1008×672 (scaled to the RES) | fail/pass |
| 11b 2x2 h1v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 105.1 | new | fail/pass |
| 11b 2x2 h3v1 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 105.1 | today 1008×672 (scaled to the RES) | fail/pass |
| 11b 2x2 h3v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 105.1 | new | never |
| 12b 3x3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 109.0 | today 1008×672 (scaled to the RES) | pass |
| 11b 3x3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 146.9 | today 1008×672 (scaled to the RES) | pass |
| 11b 2x3 | 1008×664 | 992×654 | 0, 8 | 1.19 | yes | 145.3 | today 1008×672 (scaled to the RES) | fail/pass |
| 11b 2x3 h3v1 | 1008×664 | 992×654 | 0, 8 | 1.19 | yes | 145.3 | today 1008×672 (scaled to the RES) | fail/pass |
| 11b 3x2 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 102.5 | today 1008×672 (scaled to the RES) | fail/pass |
| 11b 3x2 h1v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 102.5 | new | fail/pass |
| 11b 1x2 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 80.9 | today 1008×672 (scaled to the RES) | fail/pass |
| 11b 1x2 h1v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 80.9 | new | fail/pass |
| 11b 1x2 h3v1 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 80.9 | today 1008×672 (scaled to the RES) | fail/pass |
| 11b 1x2 h3v3 | 1008×670 | 992×660 | 0, 2 | 0.30 | yes | 80.9 | new | fail/pass |
| 11b 1x3 | 1008×664 | 992×654 | 0, 8 | 1.19 | yes | 114.7 | today 1008×672 (scaled to the RES) | pass |
| 11b 1x3 h3v1 | 1008×664 | 992×654 | 0, 8 | 1.19 | yes | 114.7 | today 1008×672 (scaled to the RES) | pass |
| *22 full recipes* (11b 1x1, 11b 2x1, 11b 3x6, 12b 1x1, 12b 2x1, 12b 3x6, 14b 1x1) | 1008×672 | 992×662 (nominal) | 0, 0 | 0 | yes | | 0 new | |

### OG 2K — raster 2016×1346, nominal 2000×1336

| recipe | raster | visible (RES shown) | short (cols, rows) | short % (h) | ≤ 2 % | fps | status vs today | readout live at this DC |
|---|---|---|---|---|---|---|---|---|
| 12b 2x3 | 2016×1330 | 2000×1320 | 0, 16 | 1.19 | yes | 107.7 | new | fail/pass |
| 12b 3x2 | 2016×1342 | 2000×1332 | 0, 4 | 0.30 | yes | 76.0 | today 2016×1346 (scaled to the RES) | fail/pass |
| 12b 1x2 | 2016×1342 | 2000×1332 | 0, 4 | 0.30 | yes | 76.0 | today 2016×1346 (scaled to the RES) | fail/pass |
| 12b 1x2 h3v1 | 2016×1342 | 2000×1332 | 0, 4 | 0.30 | yes | 76.0 | today 2016×1346 (scaled to the RES) | fail/pass |
| 12b 1x3 | 2016×1330 | 2000×1320 | 0, 16 | 1.19 | yes | 107.7 | new | pass |
| 12b 1x3 h3v1 | 2016×1330 | 2000×1320 | 0, 16 | 1.19 | yes | 107.7 | new | never |
| 14b 1x2 | 2016×1342 | 2000×1332 | 0, 4 | 0.30 | yes | 37.1 | today 2016×1346 (scaled to the RES) | fail/pass |
| 14b 1x2 h3v1 | 2016×1342 | 2000×1332 | 0, 4 | 0.30 | yes | 37.1 | today 2016×1346 (scaled to the RES) | fail/pass |
| 14b 1x3 | 2016×1330 | 2000×1320 | 0, 16 | 1.19 | yes | 52.6 | new | pass |
| 14b 1x3 h3v1 | 2016×1330 | 2000×1320 | 0, 16 | 1.19 | yes | 52.6 | new | never |
| 12b 2x2 | 2016×1342 | 2000×1332 | 0, 4 | 0.30 | yes | 77.0 | today 2016×1346 (scaled to the RES) | fail/pass |
| 11b 2x2 | 2016×1342 | 2000×1332 | 0, 4 | 0.30 | yes | 105.1 | today 2016×1346 (scaled to the RES) | fail/pass |
| 12b 3x3 | 2016×1344 | 2000×1334 | 0, 2 | 0.15 | yes | 109.0 | new | pass |
| 11b 3x3 | 2016×1344 | 2000×1334 | 0, 2 | 0.15 | yes | 146.9 | new | pass |
| 11b 2x3 | 2016×1330 | 2000×1320 | 0, 16 | 1.19 | yes | 145.3 | new | fail/pass |
| 11b 3x2 | 2016×1342 | 2000×1332 | 0, 4 | 0.30 | yes | 102.5 | today 2016×1346 (scaled to the RES) | fail/pass |
| 11b 1x2 | 2016×1342 | 2000×1332 | 0, 4 | 0.30 | yes | 80.9 | today 2016×1346 (scaled to the RES) | fail/pass |
| 11b 1x2 h3v1 | 2016×1342 | 2000×1332 | 0, 4 | 0.30 | yes | 80.9 | today 2016×1346 (scaled to the RES) | fail/pass |
| 11b 1x3 | 2016×1330 | 2000×1320 | 0, 16 | 1.19 | yes | 114.7 | new | pass |
| 11b 1x3 h3v1 | 2016×1330 | 2000×1320 | 0, 16 | 1.19 | yes | 114.4 | new | never |
| *16 full recipes* (11b 1x1, 11b 2x1, 12b 1x1, 12b 2x1, 14b 1x1) | 2016×1346 | 2000×1336 (nominal) | 0, 0 | 0 | yes | | 0 new | |

### OG 3K — raster 3024×2020, nominal 3008×2010

| recipe | raster | visible (RES shown) | short (cols, rows) | short % (h) | ≤ 2 % | fps | status vs today | readout live at this DC |
|---|---|---|---|---|---|---|---|---|
| 12b 1x2 | 3024×2014 | 3008×2004 | 0, 6 | 0.30 | yes | 76.0 | new | fail/pass |
| 14b 1x2 | 3024×2014 | 3008×2004 | 0, 6 | 0.30 | yes | 37.1 | new | fail/pass |
| 12b 2x2 | 3024×2014 | 3008×2004 | 0, 6 | 0.30 | yes | 77.0 | new | fail/pass |
| 11b 2x2 | 3024×2014 | 3008×2004 | 0, 6 | 0.30 | yes | 105.1 | new | fail/pass |
| 11b 1x2 | 3024×2014 | 3008×2004 | 0, 6 | 0.30 | yes | 80.9 | new | fail/pass |
| *5 full recipes* (11b 1x1, 11b 2x1, 12b 1x1, 12b 2x1, 14b 1x1) | 3024×2020 | 3008×2010 (nominal) | 0, 0 | 0 | yes | | 0 new | |

### SQ 0.7K — raster 672×672, nominal 656×662

| recipe | raster | visible (RES shown) | short (cols, rows) | short % (h) | ≤ 2 % | fps | status vs today | readout live at this DC |
|---|---|---|---|---|---|---|---|---|
| 12b 2x3 | 672×664 | 656×654 | 0, 8 | 1.19 | yes | 107.7 | new | never |
| 12b 2x3 h3v1 | 672×664 | 656×654 | 0, 8 | 1.19 | yes | 107.7 | new | never |
| 12b 1x3 | 672×664 | 656×654 | 0, 8 | 1.19 | yes | 107.7 | new | never |
| 12b 1x3 h3v1 | 672×664 | 656×654 | 0, 8 | 1.19 | yes | 107.7 | new | never |
| 14b 1x3 | 672×664 | 656×654 | 0, 8 | 1.19 | yes | 55.1 | new | never |
| 14b 1x3 h3v1 | 672×664 | 656×654 | 0, 8 | 1.19 | yes | 55.1 | new | never |
| 11b 2x3 | 672×664 | 656×654 | 0, 8 | 1.19 | yes | 145.3 | new | never |
| 11b 2x3 h3v1 | 672×664 | 656×654 | 0, 8 | 1.19 | yes | 145.3 | new | never |
| 11b 1x3 | 672×664 | 656×654 | 0, 8 | 1.19 | yes | 145.3 | new | never |
| 11b 1x3 h3v1 | 672×664 | 656×654 | 0, 8 | 1.19 | yes | 145.3 | new | never |
| *48 full recipes* (11b 1x1, 11b 1x2, 11b 2x1, 11b 2x2, 11b 3x2, 11b 3x3, 11b 3x6, 12b 1x1, 12b 1x2, 12b 2x1, 12b 2x2, 12b 3x2, 12b 3x3, 12b 3x6, 14b 1x1, 14b 1x2) | 672×672 | 656×662 (nominal) | 0, 0 | 0 | yes | | 0 new | |

### SQ 1K — raster 1024×1024, nominal 1008×1014

| recipe | raster | visible (RES shown) | short (cols, rows) | short % (h) | ≤ 2 % | fps | status vs today | readout live at this DC |
|---|---|---|---|---|---|---|---|---|
| 12b 2x3 | 1024×1012 | 1008×1002 | 0, 12 | 1.17 | yes | 107.7 | new | never |
| 12b 1x3 | 1024×1012 | 1008×1002 | 0, 12 | 1.17 | yes | 107.7 | new | never |
| 12b 1x3 h3v1 | 1024×1012 | 1008×1002 | 0, 12 | 1.17 | yes | 107.7 | new | never |
| 14b 1x3 | 1024×1012 | 1008×1002 | 0, 12 | 1.17 | yes | 55.1 | new | never |
| 14b 1x3 h3v1 | 1024×1012 | 1008×1002 | 0, 12 | 1.17 | yes | 55.1 | new | never |
| 11b 2x3 | 1024×1012 | 1008×1002 | 0, 12 | 1.17 | yes | 145.3 | new | never |
| 11b 1x3 | 1024×1012 | 1008×1002 | 0, 12 | 1.17 | yes | 145.3 | new | never |
| 11b 1x3 h3v1 | 1024×1012 | 1008×1002 | 0, 12 | 1.17 | yes | 145.3 | new | never |
| *28 full recipes* (11b 1x1, 11b 1x2, 11b 2x1, 11b 2x2, 11b 3x2, 11b 3x3, 12b 1x1, 12b 1x2, 12b 2x1, 12b 2x2, 12b 3x2, 12b 3x3, 14b 1x1, 14b 1x2) | 1024×1024 | 1008×1014 (nominal) | 0, 0 | 0 | yes | | 0 new | |

### SQ 1.5K — raster 1344×1344, nominal 1328×1334

| recipe | raster | visible (RES shown) | short (cols, rows) | short % (h) | ≤ 2 % | fps | status vs today | readout live at this DC |
|---|---|---|---|---|---|---|---|---|
| 12b 2x3 | 1344×1330 | 1328×1320 | 0, 14 | 1.04 | yes | 107.7 | new | never |
| 12b 1x3 | 1344×1330 | 1328×1320 | 0, 14 | 1.04 | yes | 107.7 | new | never |
| 12b 1x3 h3v1 | 1344×1330 | 1328×1320 | 0, 14 | 1.04 | yes | 107.7 | new | never |
| 14b 1x3 | 1344×1330 | 1328×1320 | 0, 14 | 1.04 | yes | 55.1 | new | never |
| 14b 1x3 h3v1 | 1344×1330 | 1328×1320 | 0, 14 | 1.04 | yes | 55.1 | new | never |
| 11b 2x3 | 1344×1330 | 1328×1320 | 0, 14 | 1.04 | yes | 145.3 | new | never |
| 11b 1x3 | 1344×1330 | 1328×1320 | 0, 14 | 1.04 | yes | 145.3 | new | never |
| 11b 1x3 h3v1 | 1344×1330 | 1328×1320 | 0, 14 | 1.04 | yes | 145.3 | new | never |
| *28 full recipes* (11b 1x1, 11b 1x2, 11b 2x1, 11b 2x2, 11b 3x2, 11b 3x3, 12b 1x1, 12b 1x2, 12b 2x1, 12b 2x2, 12b 3x2, 12b 3x3, 14b 1x1, 14b 1x2) | 1344×1344 | 1328×1334 (nominal) | 0, 0 | 0 | yes | | 0 new | |

## Live checks needed

1. **Every recipe in the per-recipe tables**: none has been recorded at its short raster.  Check that the DNG is the
   predicted raster, DefaultCrop = raster − 16×10, and fov passes against the nominal.  First priority, readout never
   live at that DC: all **SQ** V3 recipes (12b/14b 1x3, 12b/11b 2x3, 11b 1x3 w2C; R16 rows 1330), OG 1K 12b/11b 2x2
   h3v3, and OG 2K 12b/14b/11b 1x3 h3v1 (31 recipes in all).
2. Centring of the short full-height frames (V2 2014, new V3 1330) against 1x1, as a fraction of the DC.
3. The UI side: does selecting a reduced recipe show its `vis`, and does a full recipe restore `nominal`
   (no drift over repeated switches)?

## Code

- `projects/isp-lab/host/quality.py`: `candidates/qualities(..., tol=None)`, `short_ok`, `visible_of`,
  `r16_rows(..., tol)`, `isp(..., nom)`.  The default path is the old decisions unchanged (test_matrix and
  test_core pass).
- `projects/isp-lab/host/test_visible_tol.py`: 7 tests and 7 mutants, each caught.  Mutants: stretch instead of short,
  visible from the clean RES, nominal from the recipe, height tolerance ignored, R16 ignores tol, tol leaking into the
  default, non-stock margin.
- `projects/sensorlab-imx410/preview/gen_fps.py --tol 0.02|off` (default 0.02).
