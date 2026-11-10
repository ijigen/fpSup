"""Output temporal-noise covariance fingerprint, normalised to the reference's white noise.

Noise n_i = f_i - mean_f (3 frames, scaled by sqrt(3/2) so var is unbiased). Each site's
covariance with the pixel at mosaic lag (dy, dx) is divided by the reference noise level
g * sqrt(mean_a * mean_b) (g = reference var/mean of the same colours, measured, ~0.104),
so lag (0,0) is the variance ratio sum(w^2) and other lags are sum(w_a * w_b) over shared inputs.
usage: python3 rk_noisecov.py
"""
import json
import numpy as np
from rk_load import frames, PLANES, CASES
M = 24
LAGS = [(0, 0), (0, 1), (0, 2), (0, 4), (1, 0), (2, 0), (4, 0), (1, 1), (1, -1), (2, 2), (1, 2), (2, 1)]


def fingerprint(F, g):
    mu = F.mean(0)
    n = (F - mu) * np.sqrt(3 / 2)
    H, W = mu.shape
    out = {}
    for p, (sy, sx) in PLANES.items():
        ys = np.arange(M + sy, H - M, 2); xs = np.arange(M + sx, W - M, 2)
        a = n[:, ys][:, :, xs]; ma = mu[np.ix_(ys, xs)]
        row = {}
        for dy, dx in LAGS:
            b = n[:, ys + dy][:, :, xs + dx]; mb = mu[np.ix_(ys + dy, xs + dx)]
            cov = (a * b).mean(0)
            row[f'{dy},{dx}'] = float(cov.sum() / (g * np.sqrt(np.clip(ma * mb, 1, None))).sum())
        out[p] = row
    return out


if __name__ == '__main__':
    F = {c: frames(c) for c in CASES}
    mu = F['z1024'].mean(0)
    v = F['z1024'].var(0, ddof=1)
    g = float(v[M:-M, M:-M].sum() / mu[M:-M, M:-M].sum())
    print(f'reference var/mean g = {g:.4f}')
    rep = {}
    for c in CASES:
        fp = fingerprint(F[c], g)
        rep[c] = fp
        print(f'\n{c}:        ' + ''.join(f'{k:>8s}' for k in fp['R']))
        for p, row in fp.items():
            print(f'  {p:2s}           ' + ''.join(f'{x:+8.3f}' for x in row.values()))
    json.dump(dict(g=g, fp=rep), open('noisecov.json', 'w'), indent=1)
