# 0.0.5test proportional-zoom fix (no extra rows): live check (2026-11-10)

PURPLE TEST build (toggles 0), settings from the card, sha256 prefix 5a882f15; same card otherwise (COL-Share, LUT,
RAW-View 0.4.0test, QS-Share 0.0.2test, Gyro2 off). Recipe A now Zh = Zv 1608 (was 1612), window 3402, RS 21.348 ms
(unchanged from pre-fix); UHD25 RS 20.052 ms (unchanged).

| recipe | baseline | extra-rows build (live/) | this build |
|---|---|---|---|
| A: UHD 29.97 12b 1×1 | 24/42 | 0/10 | **0/10** (ff; DNG 12 522 496 B = 3840×2160×12) |
| UHD 25p 12fastW | 13/27 | 0/10 | **0/10** (ff) |
| Bei's 14b 1×2 OG2K | — | 0/10 | **0/10** (DNG dy = 0) |

Clips A001_149..178. Selection restored to Bei's OG2K recipe at the end.
