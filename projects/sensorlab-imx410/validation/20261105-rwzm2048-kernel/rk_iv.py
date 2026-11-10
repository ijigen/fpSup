"""Instrumental-variable kernel fit (attenuation-free), per CFA plane.

Plain least squares on a noisy regressor shrinks/smooths the kernel (errors in variables).
Here the regressor is ONE reference frame and the instrument is the mean of the OTHER two:
same scene signal, independent noise, so  w = (Z'X)^-1 Z'y  is unbiased without knowing sigma.
Repeated for the 3 choices of the regressor frame and averaged; the spread is printed.

H (case z2048x1024):  out[y, x] = sum_{v,k} w * ref[y + v, 2x + S + k] + b
V (case z2048):       out[y, x] = sum_{v,k} w * ref[2y + SV + v, 2x + S + k] + b

usage: python3 rk_iv.py CASE  [S SV]       (defaults S=3, SV from registration)
"""
import sys, json
import numpy as np
from rk_load import frames, plane, PLANES

case = sys.argv[1] if len(sys.argv) > 1 else 'z2048x1024'
S = int(sys.argv[2]) if len(sys.argv) > 2 else 3
SV = int(sys.argv[3]) if len(sys.argv) > 3 else 0
M = 24
KH = range(-2, 4)            # H taps: plane index 2x+S+k, k=-2..3  (covers 2x+1..2x+6)
vf = 2 if case == 'z2048' else 1
KV = range(-2, 4) if vf == 2 else range(-1, 2)


def design(ref, ys, xs):
    cols, lab = [], []
    for v in KV:
        for k in KH:
            cols.append(ref[np.ix_(vf * ys + SV + v, 2 * xs + S + k)].ravel())
            lab.append((v, k))
    cols.append(np.ones(len(ys) * len(xs)))
    return np.stack(cols, 1), lab


def fit(Rf, out, ys, xs):
    ws = []
    for i in range(3):
        X, lab = design(Rf[i], ys, xs)
        Z, _ = design(np.delete(Rf, i, 0).mean(0), ys, xs)
        y = out[np.ix_(ys, xs)].ravel()
        w = np.linalg.solve(Z.T @ X, Z.T @ y)
        ws.append(w)
    ws = np.array(ws)
    w = ws.mean(0)
    Xm, _ = design(Rf.mean(0), ys, xs)
    y = out[np.ix_(ys, xs)].ravel()
    r2 = 1 - (y - Xm @ w).var() / y.var()
    return w[:-1].reshape(len(KV), len(KH)), ws[:, :-1].std(0).reshape(len(KV), len(KH)), r2


if __name__ == '__main__':
    Rf = frames('z1024')
    O = frames(case).mean(0)
    rep = {}
    for p in PLANES:
        ref = plane(Rf, p)
        out = plane(O, p)
        H, W = ref.shape[1:]
        ho, wo = out.shape
        ys_all = np.arange(M, ho - M)
        ys_all = ys_all[(vf * ys_all + SV + min(KV) >= 0) & (vf * ys_all + SV + max(KV) < H)]
        xs_all = np.arange(M, wo - M)
        xs_all = xs_all[(2 * xs_all + S + max(KH) < W)]
        print(f'\n{case} {p}: ref plane rows {vf}y+{SV}+v (v={min(KV)}..{max(KV)}), cols 2x+{S}+k (k={min(KH)}..{max(KH)})')
        rep[p] = {}
        for tag, ys, xs in (('all', ys_all, xs_all),
                            ('x even', ys_all, xs_all[xs_all % 2 == 0]),
                            ('x odd', ys_all, xs_all[xs_all % 2 == 1]),
                            ('y even', ys_all[ys_all % 2 == 0], xs_all),
                            ('y odd', ys_all[ys_all % 2 == 1], xs_all),
                            ('left 1/3', ys_all, xs_all[xs_all < wo // 3]),
                            ('right 1/3', ys_all, xs_all[xs_all > 2 * wo // 3])):
            w, sd, r2 = fit(ref, out, ys, xs)
            hk, vk = w.sum(0), w.sum(1)
            kk, vv = np.array(list(KH)), np.array(list(KV))
            print(f'  {tag:9s} r2={r2:.5f} H marginal ' + ' '.join(f'{v:+.3f}' for v in hk) +
                  f' | V marginal ' + ' '.join(f'{v:+.3f}' for v in vk) +
                  f' | Hc={(hk * kk).sum() / hk.sum():+.3f} Vc={(vk * vv).sum() / vk.sum():+.3f}'
                  f' sum={w.sum():.3f} max sd={sd.max():.3f}')
            rep[p][tag] = dict(r2=r2, w=w.tolist(), sd=sd.tolist(), H=hk.tolist(), V=vk.tolist())
        w = np.array(rep[p]['all']['w'])
        print('  full 2D (all):')
        for i, v in enumerate(KV):
            print(f'    v={v:+d} ' + ' '.join(f'{x:+.3f}' for x in w[i]))
    json.dump(dict(case=case, S=S, SV=SV, KH=list(KH), KV=list(KV), fit=rep), open(f'iv_{case}.json', 'w'), indent=1)
