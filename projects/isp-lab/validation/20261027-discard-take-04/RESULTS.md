# 20261027-discard-take-04 — the sup pushes the take's CinemaDNGs itself after the stop (ix_cdng.c), live

Same test card / ISPL 81b5a551 / fpshd 3.3.0. AF half-press, then
`take --discard --start-ms 3000 --rec-ms 2000 --lv-every-ms 250 --lv-max 40 --cd-after-ms 2000 --listen push/`.

- Take: ctl done, started 1 / saved 1, 2 presses, **26 blocks discarded / 0 written**, REC +3636 ms, stopped 2511 ms later.
- Push: **45 images = 40 LV + 5 CDNG**, 143.9 MB, 0 skipped / torn / resync / leftover, all CRC good.
- CDNG (camera counters): arena 0x53B00900..0x7FF1FF00 scanned, **found 5, newest take 5 (DateTime 2026:10:27 04:55:10),
  sent 5, skipped 0; scan + push 448 ms**. Each 3,244,220 B (1936×1090, 12-bit, uncompressed) in ~13 ms (≈ 240 MB/s),
  ~2.3 s after the stop. Header TIFF, BitsPerSample 12; decoded picture correct (`cdng_green.png`).
- Note: the RAW is very dark (255..355 of 4095): CinemaDNG 12-bit ISO is metadata only (IMX410_RULES §61) — test scenes need
  light / shutter / aperture, not ISO.
