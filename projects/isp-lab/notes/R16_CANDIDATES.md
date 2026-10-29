# R16 candidates (2026-10-29, offline, waiting for a live test)

## The rule
R16 (quality.candidates, mirrored bit for bit in sensorlab-imx410/core): some readouts cannot window the DC. The
3x6 and 3x6fast readouts only run at full height, and some V3 windows have a margin that leaves the readable rows.
Such a readout now reads the full-height frame. The TIM keeps only the DC's rows, centred:
- `readout_cfg.plan(..., hdr, rows)`: `out_h = rows`, `y_skip += (full - rows) // 4 * 2`, so smc y0 moves down by that many rows.
- `rows = (DC height // mv) & ~1`. This never keeps more rows than the DC. R16 refuses when the full frame holds fewer rows than the DC (new V3 at 4032).

The ISP raster, the record and the DNG are therefore the DC's. RWZM and CRCT then take the frame to the RES as in any other case. The sensor still sends every line, so lines, fps and rolling shutter equal OG's.

R16 only adds cases. The other 639 matrix cases are unchanged. matrix.json has not been regenerated.
- `test_matrix.test_matrix_json_is_current` and test_core's `preset = matrix.json` hold the R16 cases out.
- Remove that filter when matrix.json is regenerated.

## Cases R16 adds (matrix.py, cap 59.94)
| id | DC RES | readout | readout_id | window | zoom | path | TIM rows dropped on top | fps |
|---|---|---|---|---|---|---|---|---|
| e99daa71 | HD 1008x566 | 3x6 | `3x6:6048x4040>2016x566@59.94+rows566` | 2016x566 | 2048x1024 | E1 | 52 | 59.947 |
| 285b7ac3 | HD 1008x566 | 3x6fast | `3x6fast:6048x4040>2016x566@59.94+rows566` | 2016x566 | 2048x1024 | E1 | 52 | 59.94 |
| dea3c262 | S35 688x386 | 3x6 | `3x6:4192x4040>1397x392@59.94+rows392` | 1408x392 | 2095x1039 | E1 | 140 | 59.947 |
| 7a1b05bb | S35 688x386 | 3x6fast | `3x6fast:4192x4040>1397x392@59.94+rows392` | 1408x392 | 2095x1039 | E1 | 140 | 59.94 |
| cf4e16ee | APSC 656x434 | 3x6 | `3x6:3958x4040>1319x438@59.94+rows438` | 1328x438 | 2072x1033 | E1 | 116 | 59.947 |
| a4298a4d | APSC 656x434 | 3x6fast | `3x6fast:3958x4040>1319x438@59.94+rows438` | 1328x438 | 2072x1033 | E1 | 116 | 59.94 |
| f134f5d6 | S16 336x198 | 3x6 | `3x6:2108x4040>702x208@59.94+rows208` | 704x208 | 2145x1075 | E1 | 232 | 59.947 |
| 3c168abf | S16 336x198 | 3x6fast | `3x6fast:2108x4040>702x208@59.94+rows208` | 704x208 | 2145x1075 | E1 | 232 | 59.94 |

Uncapped max fps (VMAX floor):

| Preset | Before | After (R16) |
|---|---|---|
| HD 1K | 185.53 (11b 3x3) | 289.37 (11b 3x6) |
| S35 688 | 263.50 | 289.37 |
| APS-C 656 | 237.67 | 289.37 |
| S16 336 | 476.38, stays 3x3 | 476.38 |

## What the live test must check (per case)
1. **DNG size = RES.** ImageWidth/Length must be, for example, 1008x566, not 1008x672. This proves the crop reduces the data. The CDNG bytes per frame then drop: HD 1K is 855,792 B against OG 1K's 1,016,064 B, at the same lines and fps.
2. **fov check passes**, both rec_lv and standby (`case.FOV_SCALE_TOL` 0.02).
   - The vertical offset must also be centred. Drift would show as a vertical misregistration against the DC.
   - Compare against a windowed case of the same DC, such as HD 1K 3x3fast.
3. **fps.** The measured frame interval must match the plan at the case's rate: 59.94 on the FHD60 host.
   - The headline 289.37 fps of 3x6fast needs the high-rate route, beyond the 100/120 gate. Test that rate separately once the route allows it.

## Open (only a camera can answer)
- The TIM y0 offset has been live-proven only up to 28 rows (V3_FULL_SKIP; V3_MARGIN 16). R16 drops 52 to 232 rows. The smc rules take the moved y0, but the R68 defect y offset `dyo` is fixed per class. A hot-pixel check should confirm that the defect map follows the crop.
- Is the full-height frame's middle the DC's centre? Windows centre on sensor row 2080, and R16 assumes the full frame is symmetric about the same row.
- The E1 preview of a 2016x566 raster cut from a 672-row frame.
