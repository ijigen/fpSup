"""Coarse registration: 2:1 output plane vs 1:1 reference plane (same colour).

Model: out[y, x] ~ ref[y + dy, 2x + s] (per colour plane; s in reference-plane samples).
Search integer dy and integer s with a 2-tap box on the reference, score = correlation of
high-passed images on a central window. Also does the same per horizontal third to look for
a scale error (zoom 1023 vs 1024 in the reference would drift ~1.5 plane samples across the frame).

usage: python3 rk_register.py [case] [axis]   case=z2048x1024 (H) or z2048 (H and V)
"""
import sys
import numpy as np
from rk_load import frames, plane, PLANES


def hp(a):
    # remove low frequencies: subtract 9x9 box mean (separable cumsum)
    def box(v, k, ax):
        c = np.cumsum(np.pad(v, [(k, k) if i == ax else (0, 0) for i in range(v.ndim)], mode='edge'), axis=ax)
        sl = lambda s, e: tuple(slice(s, e) if i == ax else slice(None) for i in range(v.ndim))
        return (c[sl(2 * k, None)] - c[sl(0, -2 * k)]) / (2 * k)
    return a - box(box(a, 4, 0), 4, 1)[:a.shape[0], :a.shape[1]]


def predict(ref, dy, s, vfac, n_out):
    """box-2 prediction of the output from the reference for integer offsets (s, dy in ref-plane units)."""
    H, W = ref.shape
    ho, wo = n_out
    xs = 2 * np.arange(wo) + s
    if vfac == 1:
        ys = np.arange(ho) + dy
        ok = (ys >= 0) & (ys < H)
        rows = ref[np.clip(ys, 0, H - 1)]
    else:
        ys = 2 * np.arange(ho) + dy
        ok = (ys >= 0) & (ys + 1 < H)
        rows = 0.5 * (ref[np.clip(ys, 0, H - 1)] + ref[np.clip(ys + 1, 0, H - 1)])
    okx = (xs >= 0) & (xs + 1 < W)
    p = 0.5 * (rows[:, np.clip(xs, 0, W - 1)] + rows[:, np.clip(xs + 1, 0, W - 1)])
    return p, ok, okx


def search(ref, out, vfac, rng=12, cols=None):
    best = None
    ho, wo = out.shape
    O = hp(out)
    for dy in range(-rng, rng + 1):
        for s in range(-rng, rng + 1):
            p, ok, okx = predict(ref, dy, s, vfac, out.shape)
            m = np.outer(ok, okx)
            m[:16] = m[-16:] = False
            m[:, :16] = m[:, -16:] = False
            if cols is not None:
                cm = np.zeros(wo, bool); cm[cols] = True; m &= cm[None, :]
            P = hp(p)
            a, b = P[m], O[m]
            r = np.corrcoef(a, b)[0, 1]
            if best is None or r > best[0]:
                best = (r, dy, s)
    return best


if __name__ == '__main__':
    case = sys.argv[1] if len(sys.argv) > 1 else 'z2048x1024'
    vfac = 2 if case == 'z2048' else 1
    R = frames('z1024').mean(0)
    O = frames(case).mean(0)
    for p in PLANES:
        ref, out = plane(R, p), plane(O, p)
        r, dy, s = search(ref, out, vfac)
        thirds = []
        wo = out.shape[1]
        for k in range(3):
            thirds.append(search(ref, out, vfac, rng=12, cols=slice(k * wo // 3, (k + 1) * wo // 3)))
        print(f'{case} {p}: best r={r:.4f} dy={dy} s={s} | thirds ' +
              ' '.join(f'(r={t[0]:.3f} dy={t[1]} s={t[2]})' for t in thirds))
