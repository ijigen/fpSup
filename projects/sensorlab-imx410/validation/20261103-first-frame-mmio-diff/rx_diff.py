"""Receiver / front-end side of the REC start: stock UHD (BUFA1, 0/29 shifted) vs our BUFA1 recipes (12v2 9/10, 12h2 1/5,
1x1 3/14).  Final value of every write in 0x3010xxxx (receiver/TG) and 0x300F0000-0x300F2FFF (front-end/crop/RWZM)."""
import sys
from fractions import Fraction
import mmio_diff as M
M.CASES['12v2_live'] = (6048, 4040, 3024, 2020, '1x2', 12)
M.CASES['12h2_live'] = (6048, 4040, 3024, 2020, '2x1', 12)
cases = ['stockUHD30', '12v2_live', '12h2_live', '1x1_12']
fin = {}
for c in cases:
    cam, rc, pre = M.run_case(c)
    d = {}
    for seq, pc, a, sz, v, _ in cam.mmio:
        if 0x30100000 <= a < 0x30110000 or 0x300F0000 <= a < 0x300F3000:
            d[a] = (v, M.owner(pc))
    fin[c] = d
    print(c, 'mode', cam.mode, 'rc', rc, 'n', len(d), file=sys.stderr)
addrs = sorted(set().union(*[set(d) for d in fin.values()]))
print('addr        ' + '  '.join(f'{c:>12}' for c in cases) + '  writer')
for a in addrs:
    vals = [fin[c].get(a, (None, ''))[0] for c in cases]
    if len(set(vals)) > 1:
        w = next(fin[c][a][1] for c in cases if a in fin[c])
        print(f'{a:#010x}  ' + '  '.join(f'{v:>12}' if v is None else f'{v:>#12x}' for v in vals) + f'  {w}')
