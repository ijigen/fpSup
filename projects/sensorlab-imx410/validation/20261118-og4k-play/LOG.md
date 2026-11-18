# Sensor Lab 0.0.11test: in-camera playback of OG 4K (2026-11-18)

Bei: OG 4K clips show "file content cannot be viewed"; only 6K ever froze. "Try it."

Cause: Sensor Lab's own guard `AP_PB_MAX_AREA` (apply/ap.c, added in v0.7.24test after 6K playback
froze) refused every raster above 4112x2170 before any buffer was taken. OG 4K's raster is 3968x2634.
Change: the limit is now 3968x2634 pixels of area. 6064x4050 stays refused.
FieldAngle work area by the firmware's arithmetic (open-gate/build/og4k_offline/og4k_sizes), pool 48 MiB:
DCI 4K 15,696,544 B; OG 4K 18,291,856 B; 6064x4050 42,815,976 B (the one that froze).

Card: SensorLab-IMX410_v0.0.11test.BIN 215008 B sha256 2a4a9007617e4df3 (settings record copied from the
card's 0.0.10test, backup/), with Lossless 0.3.11test and the card's other sups. LOAD.LOG: Sensor Lab at
0xC52D6480, Lossless at 0xC50B61C0.

On the camera (SD, lit room):
- New clips s-12---11 (3952x2624 12-bit, A001_406 ISO 100, A001_407 ISO 3200) by raw_accept.py, 4 frames
  fetched each, decode ok, no repeats, 2 of 4 compressed. ISO 3200 "steady" FAIL is the known lit-scene
  false alarm of that check (it is made for a capped lens).
- play_last.sh 25 on A001_407: no freeze, shell answers afterwards, live view back. Lossless counters:
  frame size 15,639,552, 43 frames decoded as one job each, 0 row by row, 0 refused.
- Speed is NOT enough for real time: engine 44.3 ms a frame, card read 39 ms, 19 ms between hooks;
  about 69 ms a frame (about 14.5 fps), engine job open 72 %. Bei, looking at the screen: does not
  freeze, decoding does not keep up.

Not tested: the picture itself beyond Bei's glance (no screenshot, no pixel check of playback), 14-bit
OG 4K, sizes between DCI 4K and OG 4K, uncompressed OG 4K only clips, long clips, SSD, HDMI, pause /
fast forward / reverse / clip change, playback right after a cold start, other sups absent.
Offline: tools/test.py prelive -- apply and core tests and mutants pass; 6 settings-migration errors are
the missing frozen fixtures (none exist for any 0.0.x version, same at 0.0.10test).
