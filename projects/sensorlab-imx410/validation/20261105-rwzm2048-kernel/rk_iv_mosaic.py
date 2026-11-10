"""IV (attenuation-free) mosaic-domain fit: every colour within a small window is a regressor,
so cross-colour leakage (e.g. green mixing G1<->G2) is visible.

out[Y, X] = sum_{dy,k} w * ref[vf*Y + OY + dy, 2X + OX + k] + b   (sensor pixels)
regressor = one ref frame, instrument = mean of the other two, averaged over the 3 choices.
usage: python3 rk_iv_mosaic.py CASE OX OY KX KY
"""
import sys, json
import numpy as np
from rk_load import frames, PLANES
case = sys.argv[1]; OX, OY, KX, KY = map(int, sys.argv[2:6])
vf = 2 if case == 'z2048' else 1
M = 24
Rf, O = frames('z1024'), frames(case).mean(0)
H, W = Rf.shape[1:]
rep = {}
names = {v: k for k, v in PLANES.items()}
for p, (sy, sx) in PLANES.items():
    Ys = np.arange(M + sy, O.shape[0] - M, 2); Xs = np.arange(M + sx, O.shape[1] - M, 2)
    cy, cx = vf * Ys + OY, 2 * Xs + OX
    m = (cy - KY >= 0) & (cy + KY < H); Ys, cy = Ys[m], cy[m]
    m = (cx - KX >= 0) & (cx + KX < W); Xs, cx = Xs[m], cx[m]
    def D(img):
        c = [img[np.ix_(cy + dy, cx + k)].ravel() for dy in range(-KY, KY + 1) for k in range(-KX, KX + 1)]
        return np.stack(c + [np.ones(len(cy) * len(cx))], 1)
    y = O[np.ix_(Ys, Xs)].ravel()
    ws = [np.linalg.solve(D(np.delete(Rf, i, 0).mean(0)).T @ D(Rf[i]), D(np.delete(Rf, i, 0).mean(0)).T @ y) for i in range(3)]
    w = np.mean(ws, 0); sd = np.std(ws, 0)
    Wm = w[:-1].reshape(2 * KY + 1, 2 * KX + 1)
    r2 = 1 - (y - D(Rf.mean(0)) @ w).var() / y.var()
    print(f'\n{case} out {p}: ref rows {vf}Y+{OY}+dy, cols 2X+{OX}+k   r2={r2:.5f}  max sd={sd[:-1].max():.3f}')
    print('         ' + ''.join(f'{k:+7d}' for k in range(-KX, KX + 1)))
    bycol = {}
    for i, dy in enumerate(range(-KY, KY + 1)):
        row = ''
        for j, k in enumerate(range(-KX, KX + 1)):
            c = names[((cy[0] + dy) % 2, (cx[0] + k) % 2)]
            bycol[c] = bycol.get(c, 0) + Wm[i, j]
            row += f'{Wm[i, j]:+5.3f}{c[0]:1s} '[:7]
        print(f'  dy={dy:+d}  ' + ''.join(f'{Wm[i, j]:+7.3f}' for j in range(2 * KX + 1)) + '   colours: ' +
              ' '.join(names[((cy[0] + dy) % 2, (cx[0] + k) % 2)] for k in range(-KX, KX + 1)))
    print('  weight by source colour: ' + ' '.join(f'{c}={v:+.3f}' for c, v in bycol.items()))
    rep[p] = dict(r2=r2, w=Wm.tolist(), sd=sd[:-1].reshape(Wm.shape).tolist(), by_colour=bycol)
json.dump(rep, open(f'ivmosaic_{case}.json', 'w'), indent=1)
