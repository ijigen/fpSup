# 2026-11-19 standby autofocus misses in Sensor Lab formats a hair narrower than 3:2 — Sensor Lab 0.0.12test

## What Bei saw (by hand, standby only)
- With Sensor Lab loaded, half-press AF misses in OG 3.5K / 4K / 5K / 6K; right in OG 1K / 2K / 3K. Card out: right.
- Same with 0.0.10test and 0.0.11test (they differ in 5 bytes of the playback limit).
- OG 3K "12b 1x1": wrong. OG 3K "12b 1x2": right. OG 3.5K "14b 1x1" <= 19 fps: wrong. Wrong right after power-on too.
- RES-Custom's 3.5K / 4K: right.

## Cause (firmware read offline, numbers reproduced; D = 1620x1080 and the AF frame position are inferred from the fit)
`apc_box` (apply/ap_calc.c, ported from isp-lab `isp_custom.py lv_box`, Bei 2026-10-27: the LV fits the record's shape,
one side touching) gave a record narrower than 3:2 the box `floor16(1080 a) x 1080`. OG 3.5K is 3584x2394 = 1.497, so
its box was 1616x1080. The firmware's AF-frame conversion (`FUN_c0686800`, writer `FUN_c06862b0` -> 0x30050010/18)
takes the picture to fill the LCD's width: imgH = 1080 * 1620 / 1616 = 1082 > 1080, the unsigned letterbox term
`(D_h - imgH + 1) >> 1` wraps, and the 16 x (60x60) evaluation window is pinned to the top of the frame.
The floor to 16 has no recorded basis (the nearest rule is about the ISP's visible raster; the LCD's 1620 is not a
multiple of 16). The split is the record's aspect, not the readout: OG 3K 1x1 is 1.497 too; 1x2 is 1.509, 2x2 1.5015,
RES-Custom's formats are exactly 3:2.

## Measured on the camera (read-only `mem get`; af_read.py, af_grid.py; *.json here)
Standby, pid 5, raster 2016x1344, `imager mode_now` MONIT1_60 in every case.

| state | visible | window (cell w, h, y0, x0) |
|---|---|---|
| 0.0.11test OG 3.5K 12b 1x1 (AF wrong) | 2000x1334 | 60, 60, **2**, 473 |
| 0.0.11test, same, visible still stock | 2000x1125 | 60, 52, **54**, 473 |
| 0.0.11test OG 3K 12b 1x2 (AF right) | 2000x1322 | 60, 60, **304**, 473 |
| 0.0.12test OG 3.5K 12b 1x1 | 2000x1125 | 60, 52, **309**, 473 |

The same arithmetic gives 304 for stock CINE standby. At a half-press the registers flip for ~70 ms to a 6x6 grid
(112x90 at 112, 20), identical in good and bad. 0x30050500 / 0x30050540.. stay 0.

## Fix: 0.0.12test
A record within 0.5 % of 3:2 gets the whole LCD, 1620x1080 (the 16:9 rule's tolerance). The LV is drawn up to 0.5 %
wider than the record's true shape (4 px of 1620 for 1.497). In `apc_box` and its reference `isp_custom.py lv_box`,
each with name / purpose / basis / cost; the narrower branch's floor-16 is marked "no recorded basis".
Bei 2026-11-19, 0.0.12test on the camera (sha256 910a3bf4..., his settings record): standby AF right ("準").

Tests: `tools/test.py full` PASS (all suites and all mutation runs); new asserts in test_apply
(`apc_display_host` swept +-0.5 % around 3:2 against isp_custom, and 3584x2394, 6032x4030, 3008x2010 -> 1620x1080,
3024x2004 -> 1620x1074, 2016x2016 -> 1072x1080). No new mutant was added for the snap.

## Prediction for AF WHILE RECORDING (not tested by anyone)
Same conversion, same box. Expected with 0.0.12test: OG 1K..6K and 16:9-class formats focus; square / 4:3-like formats
miss as in standby. Lower confidence for 4040-row 1:1 recipes: while recording the firmware uses the recipe's raw size
and Sensor Lab's record canvas words (preview bins, zoom, the x3 rule), not checked numerically.

## Not fixed / not tested
- Formats really narrower than 3:2 (square, 4:3-like DC): box still narrower than 1620, AF expected to miss.
- AF while recording; AF-C; face detection; the magnifier; HDMI; which formats Bei tried on 0.0.12test beyond his "準".
- The window after an LV restart on 0.0.12test (visible 1334) was not read back; 304 is computed.
- D, the picker pair and the AF frame coordinates were not read on the camera.

## Incidents during this work
- Shell stopped after `key MENU` over USB in OG 3.5K 12b 1x1 (camera normal; Bei power-cycled). Not reproduced, cause unknown.
- 2026-11-18: `\fpSup` held 33 BINs, Loader v4 takes 32, USB-Shell was dropped (see 20261118-og4k-play/LOG.md).
