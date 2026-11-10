# 0.0.5test vertical-margin fix: live check (2026-11-10)

Card: SensorLab-IMX410 0.0.5test PURPLE TEST build, toggles 0 (`out-purple-live/`, settings from the card's 0.0.4test,
sha256 prefix 9dd6c169), QS-Share 0.0.2test, Gyro2 disabled, RAW-View 0.4.0test on (Bei's setting), COL-Share/LUT as is.
Takes: 1 s via `rec_take.sh`; result from the ring `ff` (1 shifted, 2 written) and, where ff = 0 (not armed), the frame-1
vs frame-2 row-shift check (`og2k-dng/shift.py` = takes.py SHIFT).

| recipe | before (baseline) | 0.0.5test |
|---|---|---|
| A: UHD 29.97 12b 1×1 (6048×3402 → 3840×2160), RS 21.348 → 21.397 ms | 24/42 | **0/10** (ff) |
| UHD 25p 12fastW (same DC/RES, AD 11) | 13/27 | **0/10** (ff) |
| Bei's 14b 1×2 OG2K (6048×4040 → 2016×1346) | not measured | **0/10** (DNG dy = 0; ff not armed) |

Clips A001_119..148. Selection restored to Bei's OG2K recipe at the end.
