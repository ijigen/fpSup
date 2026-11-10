#!/usr/bin/env python3
"""Expected MB/s tile values (notes/MBPS_TILE_RESEARCH.md v2) for one DC x RES cell + recipe + fps.

    python3 -B mbps_expect.py DCW DCH RW RH RECIPE FPS_N FPS_D [SDMODE]
    e.g. 6048 3402 2016 1134 "12b 2x3" 5994 100 3

RW x RH = the RES raster (the tile shows raster - 16 x 10). The recipe's vis comes from gen_fps.case (quality.py, the
same data the client's C core reproduces); then the C's integer math of slqs.c mbps_of() is redone here in Python
(independent rewrite from the note, not a call into the client).
"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path('/Users/dido/Developer.localized/SIGMAfp_re/projects/sensorlab-imx410/preview')))
import gen_fps as G

dcw, dch, rw, rh = map(int, sys.argv[1:5])
name = sys.argv[5]; fn, fd = int(sys.argv[6]), int(sys.argv[7])
sdmode = int(sys.argv[8]) if len(sys.argv) > 8 else 3
cs = G.case(dcw, dch, rw, rh, 0.02)
rec = [c[3] for c in cs if c[2] == name]
if not rec:
    sys.exit('recipe %r not in cell; have %s' % (name, sorted({c[2] for c in cs})))
r = rec[0]
vw, vh = r['vis']
W, H = vw + 16, vh + 10
b = 12 if r['ad'] <= 12 else 14
one = r['mh'] * r['mv'] == 1 and r['hbin'] * r['vbin'] == 1 and r['zoom'][0] <= 1028 and r['zoom'][1] <= 1028
b16 = min(80 + 32 * (b == 14) + 24 * one, 16 * b)
px = W * H
fu = px * b // 8 + 79184
best = None
for tw in range(32, 513, 32):
    for th in range(16, 513, 16):
        nx, ny = -(-W // tw), -(-H // th)
        if nx * ny > 160: continue
        cost = nx * tw * ny * th + 32250 * nx * ny
        if best is None or cost < best[0]: best = (cost, nx * ny, nx, nx * tw, ny * th, tw, th)
_, gn, gnx, gpw, gph, tw, th = best
fc = min(px * b16 // 128 + 80 * gn + 80896, fu)
tc = gpw * gph * 47 // 10000 + gnx * gph * 46 // 100 + 2000          # us
fpsm = fn * 1000 // fd
lim = 1000000000 // tc
raw_m = max(fpsm - lim, 0)
u_m = fpsm * fu
ll_m = (fpsm - raw_m) * fc + raw_m * fu
R, cl, med = (240, 131072, 'SD UHS-II') if sdmode == 3 else (87, 131072, 'SD UHS-I' if sdmode == 2 else 'SD')
fl = ll_m // fpsm
tu = (-(-fu // cl) * cl) // R + 510
tl = (-(-fl // cl) * cl) // R + 510
du, dl = fpsm * tu // 1000000, fpsm * tl // 1000000
rnd = lambda m: (m // 1000 + 500000) // 1000000
print(f'{name} vis {vw}x{vh} rec {W}x{H} ad{r["ad"]} b{b} 1x1={int(one)} bpp16={b16} tile {tw}x{th} n{gn} tc {tc}us '
      f'raw {raw_m/1000:.2f}/s  frame_u {fu} B  frame_c {fc} B')
print(f'EXPECT big {rnd(u_m)}  small LL ~{rnd(ll_m)}{" (yellow)" if dl > 750 else ""}  footer {med} RAW {(du+5)//10}% '
      f'LL {(dl+5)//10}%   [exact {u_m/1e9:.2f} / {ll_m/1e9:.2f} MB/s, duty {du} / {dl} permille]')
