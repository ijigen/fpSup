# 20261027-discard-take-01 — a real take with every block dropped at the device write (ISPL discard sink)

Card (test card, user 10-27): LOADER, SUPMGR, USB-Shell (dev build), EarlyFlush, Stop-FX, Lossless (OFF in the menu), **ISPL**
(81b5a551…, WR_BLOCK back to UnlockWriter's 8 MiB, recstate+4 fix, single stop press). Removed for the test, backed up in
`card-backup/` (SHA256SUMS): UnlockWriter, ISPC, Desqueeze, TapToZoom, ScreenFlip, Gyro2, RES-Custom, RAW-View, Backlight, LUT.BIN.
LOAD.LOG: all 6 sups loaded (`0E 7 7`), ISPL 3 claims.

Take: CINE, CinemaDNG FHD 12-bit (user set), half-press AF 1.5 s, `ispl.py take --discard --start-ms 3000 --rec-ms 2000`;
host silent from the arm until 15 s after the planned stop.

| check | result |
|---|---|
| start / stop | ctl `done`, recstate started 1 / saved 1, **2 presses**; REC at +3638 ms, stopped 2509 ms later |
| writer | 24 blocks taken, **24 discarded, 0 written** (24 × 8 MiB ≈ 59 frames of 3.24 MB) |
| card | `A001_045`: 61 DNG entries of 3,244,544 B + WAV 401,408 B + SPP_metadata.xmp. Frame 30 read back = a **2026-10-15** DNG (stale clusters) → no image data written |
| RAW class after | MOVIE_REC_DNG, used 0, **used(max) 16 MB** (65 MB on a normal SD take: in flight stays short) |
| CDNG | rawpool scan: **4 DNGs of this take** (04:37:44, uncompressed 3,244,220 B) + 4 lossless ones from 10-15 at the arena bottom |

Notes: the file system still creates the clip and allocates clusters (card free space shrinks; junk clips need cleanup);
audio is not on our writer and is written normally. Fewer frames survive in RAW (4 vs 14) because completions come back fast.
