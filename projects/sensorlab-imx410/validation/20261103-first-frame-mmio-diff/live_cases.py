"""The two 12v2 selections actually recorded live on 2026-11-03 (Bei's default RES 3024x2020 -> 2014-row DNGs, and
the memory-set custom RES 3008x2004 -> 1998-row DNGs, 10/10 shifted): what vertical RWZM / crop / RX window
does the record start program?"""
import sys
from fractions import Fraction
import mmio_diff as M
M.CASES['12v2_live2020'] = (6048, 4040, 3024, 2020, '1x2', 12)
M.CASES['12v2_live2004'] = (6048, 4040, 3008, 2004, '1x2', 12, Fraction(25))
WATCH = {0x300F0900: 'RWZM enable', 0x300F0908: 'RWZM h', 0x300F090C: 'RWZM v', 0x300F0680: 'crop x', 0x300F0684: 'crop y/h',
         0x300F068C: 'crop', 0x30182210: 'BUFA1 lines', 0x30182214: 'line words', 0x30100024: 'RX y window',
         0x30100314: 'RX y window 2'}
for case in sys.argv[1:] or ('12v2', '12v2_live2020', '12v2_live2004', '1x1_12'):
    cam, rc, pre = M.run_case(case)
    last = {}
    for seq, pc, a, sz, v, _ in cam.mmio:
        if a in WATCH:
            last[a] = v
    print(case, 'mode', cam.mode, 'rc', rc, {WATCH[a]: hex(v) for a, v in sorted(last.items())})
