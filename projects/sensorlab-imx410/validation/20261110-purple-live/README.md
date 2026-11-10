# First-frame purple: stock-diff toggles, live (2026-11-10)

Card: SensorLab-IMX410 0.0.4test PURPLE TEST build (`out-purple-live/`, sha256 f0ed1eca…, settings from the card's
0.0.2test), QS-Share 0.0.2test, Gyro2 disabled. Recipe A = UHD 29.97 12b 1×1 (DC 6048×3402 → 3840×2160, key 1, AD 12,
HMAX 445, VMAX 5399), set over USB with `setrecipe.py`. Takes: 1 s, `rec_take.sh`, `ff` from the ring (1 = row 0's end
never written = purple, 2 = written). Every take: SetImgMode_s ran at REC start, stock standby mode 8 → ours (230/231).

| toggles (bits, smode) | purple |
|---|---|
| none (baseline) | **24/42** (`takes-baseline-A.jsonl`) |
| ROWS\|RWZM (12, 7): stock-identical at BUFA1 start | **0/6** |
| ROWS (4, 7): stock sensor/RX/TG tables, our raster 3840×2160 / RWZM 1612 | **0/6** |
| RWZM (8): our readout (3402 rows), stock raster 3856×2170 / RWZM 1600 | **0/6** |
| NOWIN (2): sensor full height, RX still y0 40 / 3402 rows | 4/6 |
| SBSTOCK (16): stock standby | 2/6 |
| TWIN (1) | not run: the mode switch already happens at every REC start |

Reading [推]: both ROWS and RWZM alone clear it; NOWIN does not. Common factor: the vertical margin between the rows the
receiver delivers and the rows the RWZM scaler needs. Ours: 2160 × 1612/1024 = 3400.3 of 3402 rows (≈2 spare).
Stock raster: 2170 × 1600/1024 = 3390.6 of 3402 (≈11 spare). Stock rows: full height, far more. A first frame that
starts one row short then pushes the output down one row. Next: a product fix that leaves ≥ ~12 spare rows, then re-run.

Files: `takes-baseline-A.jsonl`, `takes.jsonl`, `live.py`, `setrecipe.py`, `LOAD-*.LOG`, `card-before/` (restore).
