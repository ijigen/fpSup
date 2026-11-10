# CinemaDNG 8 / 10-bit (0.0.3test, 2026-11-08, offline)

Bei 11-08: 「嘗試讓 Sensor Lab 支援 10bit、8bit、MOV」. This note covers 8 / 10-bit; MOV is `MOV_FEASIBILITY.md`.
Levels: **[驗]** emulated against `out/MAIN_c0000000.bin` or read from the image's data; **[推]** inferred, not run;
nothing here ran on the camera.

## Design

**Source of truth = the stock bit-depth setting** (`MV_DNGQuality` / eRawBitType), as RES-Custom does.
- The menu's BIT row already keeps that stock variable (MENU_DESIGN §2.4). v1 greyed `8 bit` / `10 bit`; 0.0.3test
  makes them selectable. No new UI and no new strings. `RAW bit` (stock 12) means "the recipe's own 12 / 14".
- The QS FORMAT tile stays as Bei defined it: `DNG` plus the recorded bits as the small line, MOV greyed. It now shows
  `8bit` / `10bit` under those stock settings. It does not choose the depth; whether it should is open question 1.

## Why one slot serves all three depths

| Fact | Level | Where |
|---|---|---|
| `FUN_c043b828` picks the table from cfg `+0x20`: 4 → TAB1 `0xC0BE5810`, 3 → TAB2 `0xC0BE59B0`, else TAB3 | [驗] decomp | `out/decomp/full/blk_c04.c` |
| TAB1 / TAB2 / TAB3 have the same 26 keys. Each key uses the **same sensor mode** in all three; only the profile id differs (131.. / 151.. / 171..). The exceptions are 12-bit `FHD120CROP` / `FHD100CROP` (modes 132 / 133 instead of 103 / 118) | [驗] | `test_apply.CommitTests.test_stock_cdng_tables_share_the_sensor_mode_per_key` |
| The stock profiles 131 / 151 / 171 have canvas `+0x80/+0x84` = 10/10, 10/9, 7/7 | [驗] native gather | `test_8_and_10_bit_tables_give_their_plane_codes_and_the_stock_black` |

So stock 8 / 10-bit is **the same readout and AD; the ISP drops bits** through the plane codes. Sensor Lab follows
that: the slot (virtual mode + profile) is built once. The picker answers TAB1 / TAB2 / TAB3 with the same entry, and
the canvas hook writes the plane codes of the table it last answered from. The core's R7 table (`core.c`) and
RES-Custom `ogc_canvas` use the same codes.

## What changed

| Where | Change |
|---|---|
| `apply/ap.c` H_PICK | Answers TAB1 / TAB2 as well as TAB3. It latches `pick_bits` (8 / 10 / 12) and counts `low_picks` |
| `apply/ap.c` H_CANVAS | A record canvas (not the MOV-table standby copy) after an 8 / 10 pick gets `+0x80/+0x84` = 10/10 or 10/9. TAB3 keeps the slot's 7/7, or 7/8 for true 14 |
| `apply/ap.c` H_BLK6 / H_BLK | The true-14 BlackLevel shift applies only after a TAB3 pick. 8 / 10 keep the stock black |
| `apply/ap.c` `ap_raw_bits()` | Reads the stock depth: `C005BF28` with FUN_c043b828's rule |
| `ap_status` | Two words appended: `rec_bits`, `low_picks` (AP_ABI unchanged; the size check covers it) |
| `qs/slqs.c` | `depth_now()` reads the stock depth once per layout, like the medium (`sq_test 11` bits 16..23 replace it offline). `out_bits()` gives FORMAT's small line, MB/s, and defaultPick's bits step. Lossless is refused at 8-bit (`LL —`) |
| `menu/menu_lists.py` | `BIT_ROWS`: 8 / 10 selectable, and each row sets the stock value 0 / 1 / 2 |
| `preview/dcres.html`, `site_page.js` | `S.bits` stands in for the stock setting (`outBits`); the tests send `bits:N`. The page has no control for it (question 3) |

Not changed: the readout, rates and FPS limits (same sensor mode), the standby gate, QR payload v1 (it carries no
depth, like the medium), the 14-bit policy at RAW bit.

## Interplay

- **Lossless** (`fpSup/lossless/control.c` `capture_eligible`) accepts `bits` 10 or 12 only. At 8-bit it refuses ON
  (`FPL_UNSUPPORTED`), so the MB/s tile shows `LL —`. Side finding: the same check also refuses **14**, yet the MB/s
  tile shows an LL estimate for true-14 recipes. That predates this change; it is not fixed here (open question 5).
- **Unlock Writer** (`projects/rec-core/writer/wr_card.c`): has no bit-depth logic; it writes frames by size. [推]
- **Defect tables / first-frame trace**: depend on the mode, not the depth. `ap_ff_arm` only knows formats 0 / 1
  (12 / 14). For 8 / 10 it does not arm (it counts `ff_skips`): trace only, no behaviour change. [驗 code]
- **Playback v1**: `ap_pb_tag` already maps BitsPerSample 8 / 10 (en 4 / 3); the non-stock refusal is unchanged.

## Live checks (not done)

1. Stock BIT 10 and 8 on a 12b recipe and on a true 14b 1:1 recipe. In the DNG check BitsPerSample, WhiteLevel and
   BlackLevel per depth (expect the stock 8 / 10-bit values: 255 / 1023 white, black scaled down) and the mod-4 /
   colour check. `sq_test 17` should show `rec_bits` 8 / 10 and `low_picks` > 0.
   **Risk [推]:** stock pairs the 8 / 10 plane codes only with its own 12-bit-AD modes. Whether 10/9 or 10/10 takes the
   right bits from a **14-bit AD** (true 14, and the scaled 14 → 12 container) or an 11-bit AD readout is unproven. Look
   for a dark or clipped image and check that the histogram top is 1023 / 255.
2. MB/s against the real file sizes at 8 / 10.
3. The BIT row: picking 8 / 10 in the menu and returning to the QS. LV reload / picker re-ask happens on return [推];
   the FORMAT line must follow.
4. The stock normaliser may push the depth away from what the user picked at some carriers (MENU_DESIGN risk 2,
   `bitnorm` not ported). Record which carriers do.

## 0.0.4test (11-08): the QS FORMAT dial picks the depth (open question 1, Bei: yes)

- Stock: the CINE QS FMT tile's dial switches only DNG / MOV; the depth is chosen by AEL -> B2_5
  (`research/ui/CUSTOM_QS.md` §12.1) [驗 NBU]. Bei chose to dial it in the tile instead (spec, 11-08 section).
- The menu BIT row's stock write path [驗 decomp]: `UicGuiMenuMovieRecord__v25` subscribes `MV_DNGQuality` ->
  `FUN_c057a5f0` -> converter `FUN_c06bd770` (table `C2E401CC`: row 0 / 1 / 2 -> eRawBitType 4 / 3 / 0) -> the GUI
  handler's `+0x130` = `MenuAction_w71c1__v74 @C04AAE08` = `FUN_c005bef0(FUN_c0057ae8(), type, 0)`. The QS GUI
  (`UicGuiMenuQs`) subscribes only `ST_DNGQuality` (stills), so the tile calls `C04AAE08` itself and posts the row
  value to `MV_DNGQuality` (`C0593F30`). Same setter, same value as the row.
- Options `8bit` / `10bit` / `<own>bit` / `MOV` (grey); ends stop. FORMAT / MB/s / defaultPick re-read at once.
- Harness: `BIT_GET` reads a RAM word, `C04AAE08` writes it; `bits:N` (the menu row) writes that word too.
- Live checks to add: dial 12 -> 10 -> 8 in the QS, then open the menu: the BIT row shows the same; record one take
  per depth (`sq_test 17` rec_bits). [推] whether the stock normaliser pushes the value back at some carriers
  (risk 4 above) -- the tile re-reads, so it would show the value that stuck.
