# QSContainer v0.3.8 (API 8, "dial guide"), offline build, 2026-11-05

Offline only: no camera, no USB, no card. Source: `projects/qs-container/` (README section
"v0.3.8（2026-11-05，轉盤提示）"). SensorLab files were not edited.

| File | Bytes | sha256 |
|---|---|---|
| `fpSup/QSContainer_v0.3.8.BIN` (= `default-build/`, blank settings record) | 202888 | `cf297822fbd206a805e23cbcf79a64a3edfff0a12933ff7751ba7d519c690aa0` |
| `card-settings-build/fpSup/QSContainer_v0.3.8.BIN` (record from `../20261104-qr-scan-build/live/rb-QSContainer_v0.3.7.BIN`, sha256 `4bf8211f…cc9d3`) | 202888 | `5b2044392736ade9e2b58482c124589009f73a237883dfbbc657f628843b28ed` |

`build-0.3.8.json` next to each BIN (dial_off 198748, go_text_off 198716, state_off 202944). Command:
`cd projects/qs-container && python3 -B build_qsct.py --out <dir> [--settings-from <BIN>]`. Deterministic (two builds,
same sha256). The two BINs differ only in the 332-byte settings record (202532..202863), which equals the card copy's.

## Contract (qsc.h)

```c
#define QSC_F_DIAL_HINT 0x00001000u   /* api->version >= 8 */
```
Opt-in per function. Shown while the focus is on the function's tile (fine mode and sub-QS tile 1 included) or one of
its sub-items, when that item has `adjust()` and is not locked (`state()` non-0, or `QSC_F_LOCK_REC` while recording).
Hidden on no-adjust items, locked items, GO tiles, the blank tile, stock tiles (their stock guide is untouched).
Rear step from the table: API 4 `±10`, API 3/2 `±1`. Older containers (v0.3.7, v0.3.2, v0.2.3 BINs run offline)
ignore the bit: the function registers and works as before, no guide. So SensorLab may set it without a version check.

## Expected look (not seen on the camera)

QS (CINE), focus on a flagged tile whose dials act: in the band directly above the option strip (screen y 539..608,
where stock shows `[AEL] Further Options` at the right), at the LEFT end: a 60 % black box from the screen's left
edge to x ≈ 450; inside, left-aligned from x 55: front-dial glyph `font_G_dial_front`, `font_G_plusminus`, `1`
(white, the stock guide font, size 54), a 44 px gap, rear-dial glyph `font_G_dial_rear`, `±`, `10`. Glyph opaque
rows at y 546..607. The stock right-hand `AEL Further Options` stays when the tile has sub-items / fine mode.

## Tests and mutants (offline, real ARM under unicorn, real firmware image)

| Suite | Tests | --mutate |
|---|---|---|
| test_api8 (new) | 12 OK | 18/18 caught |
| test_qsct | 33 OK | 43/43 caught |
| test_qs_page | 61 OK (1 skip: QSCT_MENU_BACK=1 only, as before) | 84/84 caught (4 parts) |
| test_api5 | 15 OK (version assert 7 -> 8) | 20/20 caught |
| test_api7 | 11 OK (version assert 7 -> 8; one mutant's pattern follows the new registration line) | 21/21 caught |

## live-check (unproven)

1. Inline glyph placement in a LEFT-aligned drawText (live 3 measured only a centred one; stock menu rows are
   left-aligned with these glyphs).
2. Vertical: assumed line top = rect y + (h - 54) / 2 with images top-aligned (live 3); digits may then sit ~11 px
   above the glyph centre.
3. The plain font's digit widths: the box's right end (x 450) is an estimate.
4. The box under the text (same parent/child shape as the stock Option > BG), the toggleVisible under Footer
   (the strip's box toggle is proven, under QSMode).
