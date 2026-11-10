"""First-frame row shift on the 2026-11-03 dark takes (defect-virtual/live/*): hot pixels are fixed sensor positions,
so the shift of frame 1 against frame 2 is the dy that maximises the overlap of their hot-pixel sets.  Also row 0's mean
and its bytes for an FF C4 / FF DA pair (the JPEG remnant of the bus/tNN review)."""
import glob, json, pathlib, sys
import numpy as np, tifffile
LIVE = pathlib.Path(sys.argv[1])


def hot(a):
    med = np.median(a); mad = 1.4826 * np.median(np.abs(a - med)) + 1e-6
    return set(zip(*np.nonzero(a > med + 12 * mad)))


rows = []
for d in sorted(p for p in LIVE.iterdir() if p.is_dir()):
    f = sorted(glob.glob(str(d / '*.DNG')))
    if len(f) < 2:
        continue
    a1, a2 = (tifffile.imread(p).astype(np.float32) for p in f[:2])
    h1, h2 = hot(a1[2:-2]), hot(a2[2:-2])
    best = {dy: len({(y + dy, x) for y, x in h2} & h1) for dy in range(-3, 4)}
    dy = max(best, key=best.get)
    with tifffile.TiffFile(f[0]) as t:
        p = t.pages[0]; off = p.dataoffsets[0]; w = p.imagewidth; bps = p.bitspersample
    raw = pathlib.Path(f[0]).read_bytes()[off:off + w * bps // 8]
    jpeg = b'\xff\xc4' in raw and b'\xff\xda' in raw
    mode = (d / 'mode_now.txt').read_text().split('take_mode')[-1].strip() if (d / 'mode_now.txt').exists() else '?'
    rows.append(dict(take=d.name, mode=mode, shape=list(a1.shape), dy=dy, overlap=best[dy], n_hot2=len(h2),
                     row0_mean=round(float(a1[0].mean()), 1), row1_mean=round(float(a1[1].mean()), 1),
                     f2_row0_mean=round(float(a2[0].mean()), 1), row0_jpeg=jpeg))
for r in rows:
    print(json.dumps(r))
