RWZM 14-bit check (2026-10-30). Offline, reads isp-lab/validation only.
  python3 scan.py          -> rows.json (every case: want.bits, zoom, bin, sensor_mode)
  python3 bits.py 14       -> res14.json (3 cdng frames per 14-bit case: mod 4/16 residues, code occupancy, flat tile)
  python3 bits.py 12 40    -> res12.json (12-bit control)
  python3 torn.py RUN...   -> per-row mod-4 cleanliness (shows torn/stale frames)
Result: ../../notes/RWZM_14BIT_CHECK.md
