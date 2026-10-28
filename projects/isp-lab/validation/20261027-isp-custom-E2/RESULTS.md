# 20261027-isp-custom-E2 — ISP custom formula, RWZM 1536 on the FHD 29.97 route, in a real (discard) take

`isp_custom.py apply E2`: Want = stock FHD30 (row 122, profile 175, mode 106 raster 3032×1708) with RWZM 1536/1536 →
rec 2016×1138, act 2000×1128 (ISP_SIZE_RULES §1.1/1.3) → declare() → 16 words changed in RAM (each checked stock first,
readback-checked). No menu toggle. AF half-press; `take --discard ... --lv-every-ms 500 --cd-after-ms 2000 --report`.
Then `restore` (16 words back, readback-checked).

| check | result |
|---|---|
| take | started 1 / saved 1, 2 presses, 26 blocks discarded / 0 written, stop normal |
| CDNG (5 pushed) | **2016×1138** (stock 1936×1090); DefaultCropOrigin **(8, 5)**, DefaultCropSize **2000×1128** = the formula's prediction |
| picture | complete, no corruption (`cdng_green.png`); G median 487, p99.9 816 (ISO 3200, 1/30) |
| LV during REC | 1920×1080 (the display path is unchanged by the record RWZM) |

Conclusions: (1) a profile row changed in RAM in standby is used by the next take — no route re-selection needed;
(2) the record RWZM accepts a ratio stock never records with (1536), and declare() predicts the DNG geometry exactly.
