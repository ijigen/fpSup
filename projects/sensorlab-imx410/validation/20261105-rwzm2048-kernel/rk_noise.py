"""Temporal-noise checks.

1. Spatial autocorrelation of the temporal noise (frame differences) in the mosaic domain,
   for each case and each CFA site: lag (dy, dx) in sensor pixels. A 1:1 path with no filter has
   ~0 at every lag != 0. In the 2:1 output, lag 2 (= next same-colour output sample) tells how much
   two neighbouring outputs share reference samples.
2. Photon-transfer: per-pixel temporal variance (3 frames, ddof=1) binned by mean signal, per plane,
   for every case; ratio sigma_out / sigma_ref at equal signal (geometric mean over the common bins).

usage: python3 rk_noise.py
"""
import json
import numpy as np
from rk_load import frames, plane, PLANES, CASES

M = 24


def autocorr(F, site, lags):
    d = (F[1] - F[0])
    out = {}
    sy, sx = site
    H, W = d.shape
    ys = np.arange(M + sy, H - M, 2)
    xs = np.arange(M + sx, W - M, 2)
    a = d[np.ix_(ys, xs)]
    for (ly, lx) in lags:
        b = d[np.ix_(ys + ly, xs + lx)]
        out[f'{ly},{lx}'] = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
    return out


def ptc(F, p, edges):
    P = plane(F, p)[:, M // 2:-M // 2, M // 2:-M // 2]
    m = P.mean(0).ravel()
    v = P.var(0, ddof=1).ravel()
    idx = np.digitize(m, edges)
    res = []
    for i in range(1, len(edges)):
        s = idx == i
        res.append((float(m[s].mean()) if s.sum() else np.nan, float(v[s].mean()) if s.sum() > 2000 else np.nan,
                    int(s.sum())))
    return res


if __name__ == '__main__':
    lags = [(0, 1), (0, 2), (0, 3), (0, 4), (1, 0), (2, 0), (1, 1), (4, 0)]
    F = {c: frames(c) for c in CASES}
    rep = {'autocorr': {}, 'ptc': {}}
    print('noise autocorrelation of frame difference f1-f0 (mosaic lags dy,dx):')
    for c in CASES:
        for p, site in PLANES.items():
            ac = autocorr(F[c], site, lags)
            rep['autocorr'][f'{c}/{p}'] = ac
            print(f'  {c:11s} {p:2s} ' + ' '.join(f'{k}:{v:+.3f}' for k, v in ac.items()))
    edges = np.array([60, 100, 140, 180, 220, 260, 300, 360, 420, 500, 600])
    print('\nphoton transfer: sigma(out)/sigma(ref) at equal signal, per bin then weighted mean')
    for p in PLANES:
        ref = ptc(F['z1024'], p, edges)
        for c in ('z2048x1024', 'z2048'):
            o = ptc(F[c], p, edges)
            ratios, wts = [], []
            for (mr, vr, nr), (mo, vo, no) in zip(ref, o):
                if np.isfinite(vr) and np.isfinite(vo):
                    ratios.append(np.sqrt(vo / vr)); wts.append(min(nr, no))
            ratios, wts = np.array(ratios), np.array(wts)
            rep['ptc'][f'{c}/{p}'] = dict(ratio=float((ratios * wts).sum() / wts.sum()),
                                          per_bin=ratios.round(3).tolist())
            print(f'  {p:2s} {c:11s} ratio={rep["ptc"][f"{c}/{p}"]["ratio"]:.3f}  bins {ratios.round(3).tolist()}')
        print(f'  {p:2s} ref var/mean per bin: ' + ' '.join(f'{vr / mr:.2f}' for mr, vr, n in ref if np.isfinite(vr)))
    json.dump(rep, open('noise.json', 'w'), indent=1)
