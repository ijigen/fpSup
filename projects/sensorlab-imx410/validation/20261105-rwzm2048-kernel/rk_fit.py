"""Free-tap least-squares kernel fit, 2:1 RWZM output vs 1:1 reference, per CFA plane.

H fit (case z2048x1024, V 1:1):
    out[y, x] = sum_k w_k * ref[y + dy, 2x + S + k] + b,   k = K0..K1
fitted separately for even and odd output x (phase check), and also with 3 vertical taps
(to prove nothing happens vertically). V fit (case z2048, bonus): the H axis is first reduced
with the measured H kernel, then the same thing on rows.

Errors-in-variables: the regressors are a 3-frame average of the reference, so each tap
carries noise var sigma^2/3 (sigma^2 = per-pixel temporal variance, ddof=1, averaged over
the fit region). The normal matrix is corrected by subtracting n * diag(sigma^2/3) (taps),
which removes the attenuation/smoothing bias. Both raw and corrected weights are printed.

usage: python3 rk_fit.py [S] [K0] [K1]
"""
import sys, json
import numpy as np
from rk_load import frames, plane, PLANES

S = int(sys.argv[1]) if len(sys.argv) > 1 else 3
K0 = int(sys.argv[2]) if len(sys.argv) > 2 else -3
K1 = int(sys.argv[3]) if len(sys.argv) > 3 else 4
MARGIN = 24


def solve(X, y, noise_var_cols):
    n = len(y)
    A = X.T @ X / n
    c = X.T @ y / n
    w_raw = np.linalg.solve(A, c)
    Ac = A - np.diag(noise_var_cols)
    w_eiv = np.linalg.solve(Ac, c)
    res = y - X @ w_raw
    r2 = 1 - res.var() / y.var()
    return w_raw, w_eiv, r2, res


def hfit(ref, refvar, out, dy, s, xsel, vtaps=(0,)):
    """Design matrix for horizontal taps (and optional vertical taps)."""
    H, W = ref.shape
    ho, wo = out.shape
    ys = np.arange(MARGIN, ho - MARGIN)
    xs = np.arange(MARGIN, wo - MARGIN)
    xs = xs[xs % 2 == xsel] if xsel in (0, 1) else xs
    cols, nv = [], []
    for v in vtaps:
        for k in range(K0, K1 + 1):
            cols.append(ref[np.ix_(ys + dy + v, 2 * xs + s + k)].ravel())
            nv.append(refvar)
    cols.append(np.ones(len(ys) * len(xs)))
    nv.append(0.0)
    X = np.stack(cols, 1)
    y = out[np.ix_(ys, xs)].ravel()
    return X, y, np.array(nv)


def fmt(w):
    return '[' + ' '.join(f'{v:+.3f}' for v in w) + ']'


def centroid(w):
    k = np.arange(K0, K1 + 1)
    return float((w * k).sum() / w.sum())


if __name__ == '__main__':
    Rf = frames('z1024')
    Of = frames('z2048x1024')
    R, O = Rf.mean(0), Of.mean(0)
    result = {}
    print(f'H fit, case z2048x1024, ref index 2x+{S}+k, k={K0}..{K1}; centroid in ref-plane samples rel. 2x+{S}')
    for p in PLANES:
        ref, out = plane(R, p), plane(O, p)
        refvar = float(plane(Rf, p).var(0, ddof=1)[MARGIN:-MARGIN, MARGIN:-MARGIN].mean()) / 3
        result[p] = {}
        for xsel, name in ((None, 'all '), (0, 'even'), (1, 'odd ')):
            X, y, nv = hfit(ref, refvar, out, 0, S, xsel)
            wr, we, r2, _ = solve(X, y, nv)
            t = we[:-1]
            print(f'{p:2s} {name} r2={r2:.5f}  raw {fmt(wr[:-1])} sum={wr[:-1].sum():.3f}')
            print(f'          EIV {fmt(t)} sum={t.sum():.3f} b={we[-1]:+.2f} '
                  f'centroid={centroid(t):+.3f} sum_w2/sum_w^2={np.sum(t**2) / t.sum()**2:.3f}')
            result[p][name.strip()] = dict(r2=r2, raw=wr[:-1].tolist(), eiv=t.tolist(), b=we[-1])
        X, y, nv = hfit(ref, refvar, out, 0, S, None, vtaps=(-1, 0, 1))
        wr, we, r2, _ = solve(X, y, nv)
        Wv = we[:-1].reshape(3, -1)
        print(f'   3 vertical taps r2={r2:.5f}; row sums (v=-1,0,+1) EIV: ' +
              ' '.join(f'{v:+.3f}' for v in Wv.sum(1)))
        result[p]['vtaps_rowsum'] = Wv.sum(1).tolist()
    json.dump(dict(S=S, K=[K0, K1], fit=result), open('fit_h.json', 'w'), indent=1)
