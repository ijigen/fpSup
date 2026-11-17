#!/usr/bin/env python3
"""Set the Lossless card's tile_force word (tile_grid.h: w << 16 | h, 0 = default) and read it back.
    python3 -B force_grid.py LAYOUT W H      (0 0 = default)"""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'fpSup/fp_usb_shell'), str(ROOT / 'fpSup/lossless')]
import putfile as pf
import card_status as S
lay = json.loads(pathlib.Path(sys.argv[1]).read_text())
rec = S.find_record(pf.mem_get)
assert rec, 'no Lossless record'
block, state, base = rec
at = state + lay['fields']['tile_force']
v = int(sys.argv[2]) << 16 | int(sys.argv[3])
print('before 0x%08X' % pf.mem_get(at)[0])
pf.mem_set(at, v)
got = pf.mem_get(at)[0]
print('at 0x%08X now 0x%08X' % (at, got))
assert got == v
