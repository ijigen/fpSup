# 20261027-isp-custom-E1 — ISP custom formula, record CRCT bin 3×3 + RWZM 1:1 on the FHD 29.97 route: FAIL (crop, not bin)

`isp_custom.py apply E1`: Want = stock FHD30 (row 122) with bin (3,3), RWZM unity → rec 1008×568, act 992×558
→ declare() → 21 words (incl. record bin enums +0x58/+0x5C/+0xC4/+0xC8, RWZM 0x3FF, preview +0x38). Take as E2; restored.

| check | result |
|---|---|
| take | started 1 / saved 1, 2 presses, **8 blocks** discarded (≈ 75 frames × 0.86 MB), stop normal |
| CDNG size | **1008×568**, DefaultCrop 992×558 = predicted |
| CDNG picture | **the top-left 1/3 of the field, unscaled** (`shots/full/cdng.jpg` vs `standby_lv.jpg`); field correlation with the standby LV **r = 0.11** (E2: 0.963) |
| LV during REC | the same top-left crop: while recording the display shows the record path's output |

Conclusion: the profile's record-bin fields alone do NOT make the CRCT bin the recording path. The record path took
the unbinned 3032×1708 readout and cut its top-left 1008×568 (geometry and DNG metadata follow the profile, the pixels
do not). The CRCT record bin (path selector branch C, never seen running) needs more than the profile row — next: find
what else branch C reads. Verdict tooling: case.py now also checks the field of view (size alone said "pass").
