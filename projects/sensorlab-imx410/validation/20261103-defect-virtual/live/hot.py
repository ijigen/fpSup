"""Stable hot pixels in frames 2 and 3 of a dark take: > median + 12 x robust sigma in both (DEFECT_CORRECTION method)."""
import sys, json, numpy as np, tifffile
def hot(p):
    a = tifffile.imread(p).astype(np.float32)[8:-8, 8:-8]
    med = np.median(a); mad = 1.4826 * np.median(np.abs(a - med)) + 1e-6
    ys, xs = np.nonzero(a > med + 12 * mad)
    return set(zip(ys.tolist(), xs.tolist())), a, med, mad
for d in (sys.argv[1:] if __name__ == "__main__" else []):
    import glob
    f = sorted(glob.glob(d + '/*.DNG'))
    h2, a2, m2, s2 = hot(f[1]); h3, a3, _, _ = hot(f[2])
    st = h2 & h3
    vals = sorted((float(a2[y, x]) for y, x in st), reverse=True)
    print(json.dumps(dict(take=d, shape=list(a2.shape), median=float(m2), mad=round(float(s2), 2), hot2=len(h2), hot3=len(h3),
                          stable=len(st), top=vals[:5], max=float(a2.max()))))
