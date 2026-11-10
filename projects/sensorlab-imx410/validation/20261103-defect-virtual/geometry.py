#!/usr/bin/env python3
"""DEFECT_VIRTUAL_MODES geometry evidence (offline; no camera).

    python3 -B geometry.py hot        G7 dark frames -> hot_g7.json (measured hot pixels, sensor receiver coordinates)
    python3 -B geometry.py cover      coverage of hot_g7.json by the converted tables vs. the untranslated table 97
    <cdng venv python> geometry.py dng   the SensorLab DNGs of 20261103-first-frame-purple at the predicted positions

hot:   imx410-lab captures/g7/{stock_97, gen_12v2, gen_14v2}/dark -- BUFA0 grabs (before DEFC, DEFECT_CORRECTION.md),
       lens capped, VMAX 16000, 30 dB, SHS 4, two frames; hot = > median + 12 robust sigma in both (g7_probe.hot).
       Frame column c, row r of a grab are receiver (TIM) column c + x0, row r (x0 = 8 for all three: mode 97's TIM and
       g7's generated plans) -- stock_97's hot pixels sit on flash table 97 at offset (0, 0) with this (98 %).
cover: for each SensorLab recipe the R68 row core/smc writes, converted with the Python port of FUN_c0310740 (the unit
       test test_apply.DefectTests runs the firmware's own converter and checks it equals this port), compared in the
       recipe's raster (receiver - (TIM x0, y0)); 1 px tolerance as g7_probe.
dng:   residual (pixel - median of its 8 same-colour neighbours) averaged over the predicted defect positions mapped
       through the RWZM 2:1 Bayer decimation, against random positions.
"""
import json, pathlib, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
IMXL = ROOT / 'projects' / 'imx410-lab'
APPLY = ROOT / 'projects' / 'sensorlab-imx410' / 'apply'
CLASSES = {'stock_97': 8, 'gen_12v2': 8, 'gen_14v2': 8}       # frame column 0 = receiver column x0


def hot():
    sys.path[:0] = [str(IMXL), str(IMXL / 'offline')]
    import numpy as np, resweep as R, g7_probe as G
    out = {}
    with tempfile.TemporaryDirectory(prefix='defc-g7-') as t:
        for cls, x0 in CLASSES.items():
            src = IMXL / 'captures' / 'g7' / cls
            d = pathlib.Path(t) / cls
            (d / 'dark').mkdir(parents=True)
            subprocess.run([sys.executable, '-B', str(ROOT / 'tools/bayer-jxl/bayer_jxl.py'), 'unpack', str(src / 'dark'),
                            str(d / 'dark')], check=True, capture_output=True)
            (d / 'dark' / 'frame.json').write_text((src / 'dark' / 'frame.json').read_text())
            m = json.loads((src / 'meta.json').read_text())
            f, _ = R.decode(d / 'dark')
            top = m['top']
            meas = G.hot(f[0][top:, 8:-8]) & G.hot(f[1][top:, 8:-8])
            rx = sorted((c + 8 + x0, r + top) for r, c in meas)              # receiver (TIM) coordinates
            out[cls] = dict(meta=m, frames=[list(a.shape) for a in f], receiver=rx,
                            how='g7_probe.hot (median + 12 robust sigma) in both frames; receiver = (col + x0, row)')
            print(cls, len(rx), 'hot pixels', flush=True)
    (HERE / 'hot_g7.json').write_text(json.dumps(out, indent=0) + '\n')


def recipes():
    sys.path[:0] = [str(APPLY)]
    import test_apply as T
    return T, (('12v2 DC 6048x4040 -> 3024x2014', T.R12V2, 'gen_12v2'), ('14v2 -> 3024x2014', T.R14V2, 'gen_14v2'),
               ('14-bit 1x1 key 0 -> 3024x2020 (RWZM /2)', T.R14_1X1, 'stock_97'))


def cover():
    T, rs = recipes()
    import smc, defect_tables as DT
    hotj = json.loads((HERE / 'hot_g7.json').read_text())
    buf = (IMXL / 'captures/defect/flashbuf.bin').read_bytes()
    src, _ = DT.table(buf, 0x61)
    words = DT.parse(buf)['tables'][0x61][1] // 4
    raw = set(DT.points(src))
    rows = []
    for name, args, cls in rs:
        _, _, plan, tabs, _ = T.recipe(*args)
        a = smc.attrs_from_plan(plan)
        r = T.r68_of(tabs)
        conv, _ = DT.translate(src, r['win'], r['types'], r['offs'], r['W'], r['H'], size_words=words)
        P = set(DT.points(conv))
        meas = [(x - a['x0'], y - a['y0']) for x, y in hotj[cls]['receiver']]

        def near(S, dx=0, dy=0):
            return sum(any((x + dx + i, y + dy + j) in S for i in (-1, 0, 1) for j in (-1, 0, 1)) for x, y in meas) / len(meas)
        best_old = max(((near(raw, dx, dy), dx, dy) for dx in range(-10, 11, 2) for dy in range(-4, 5, 2)))
        rows.append(dict(recipe=name, tim_x0=a['x0'], tim_y0=a['y0'], r68=r, hot=len(meas), converted_points=len(P),
                         covered_by_converted=round(near(P), 4), covered_by_untranslated_97=round(near(raw), 4),
                         untranslated_best_shift=best_old))
        print(f"{name:42s} hot {len(meas):5d}  converted {near(P):.3f}  untranslated 97 {near(raw):.3f}"
              f"  (97 best at shift {best_old[1]:+d},{best_old[2]:+d}: {best_old[0]:.3f})", flush=True)
    (HERE / 'cover.json').write_text(json.dumps(rows, indent=1) + '\n')


def dng():
    import glob
    import numpy as np, tifffile
    sys.path[:0] = [str(IMXL / 'offline')]
    import defect_tables as DT
    ff = ROOT / 'projects/sensorlab-imx410/validation/20261103-first-frame-purple'
    buf = (IMXL / 'captures/defect/flashbuf.bin').read_bytes()
    src, _ = DT.table(buf, 0x61)
    words = DT.parse(buf)['tables'][0x61][1] // 4

    def resid(a):
        R = np.zeros_like(a)
        for py in (0, 1):
            for px in (0, 1):
                s = a[py::2, px::2]
                H, W = s.shape
                P = np.pad(s, 1, mode='edge')
                nb = np.stack([P[1 + dy:1 + dy + H, 1 + dx:1 + dx + W] for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx])
                R[py::2, px::2] = s - np.median(nb, axis=0)
        return R
    q = lambda c: 2 * (c >> 2) + (c & 1)                                         # noqa: E731  Bayer 2:1
    out = {}
    for name, files, win, types, offs, W, H, vy in (
            ('14-bit 1x1 A001_014 f2-3', sorted(glob.glob(str(ff / 'card/A001_014_*')))[1:], (8, 0, 6048, 4040), (0, 0), (0, 0), 6048, 4040, True),
            ('12v2 t03-t05 f2', sorted(glob.glob(str(ff / 'bus/t0[345]/*_000002.DNG'))), (8, 8, 6048, 4042), (0, 7), (0, 2), 6048, 2014, False)):
        R = np.mean([resid(tifffile.imread(p).astype(np.float32)) for p in files], axis=0)
        conv, _ = DT.translate(src, win, types, offs, W, H, size_words=words)
        pts = DT.points(conv)
        X = np.array([q(x) for x, _ in pts])
        Y = np.array([q(y) if vy else y for _, y in pts])
        ok = (X < R.shape[1]) & (Y < R.shape[0])
        rng = np.random.default_rng(1)
        ctrl = R[rng.integers(0, R.shape[0], 20000), rng.integers(0, R.shape[1], 20000)]
        best = max((float(R[np.clip(Y[ok] + dy, 0, R.shape[0] - 1), np.clip(X[ok] + dx, 0, R.shape[1] - 1)].mean()), dx, dy)
                   for dx in range(-6, 7) for dy in range(-6, 7))
        out[name] = dict(files=[pathlib.Path(p).name for p in files], predicted=int(ok.sum()),
                         mean_resid_at_predicted=round(float(R[Y[ok], X[ok]].mean()), 3),
                         mean_resid_random=round(float(ctrl.mean()), 3), sd_resid=round(float(R.std()), 3),
                         best_shift=[round(best[0], 3), best[1], best[2]])
        print(name, out[name], flush=True)
    (HERE / 'dng_null.json').write_text(json.dumps(out, indent=1) + '\n')


if __name__ == '__main__':
    {'hot': hot, 'cover': cover, 'dng': dng}[sys.argv[1]]()
