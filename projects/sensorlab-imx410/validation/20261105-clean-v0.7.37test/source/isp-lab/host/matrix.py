#!/usr/bin/env python3
"""IMX410-Lab test matrix (notes/IMX410_LAB_SPEC.md §2): every preset DC x its preset RES x every quality, max fps.

    matrix.py [--json matrix.json]      list the cases; isp_custom runs case n as experiment `FHD60:M<n>`

A quality = an IMX410 custom readout (readout_cfg.plan: sensor crop + merge, the DC) + the ISP v2 formula
(record RWZM to the RES, optionally the CRCT vertical bin).  Both formulas decide what exists: a cell the readout
planner or isp_formula refuses is not a case.  The host is the FHD60 route (mode 27), so fps is capped at 59.94
until the 100/120 gate is bypassed.  Fast readouts (11-bit AD) are in since smc writes R10 (10-27 afternoon).
The per-cell logic (readout + R11 HMAX, isp RWZM, WIDEN retry, pick) is quality.py, shared with SensorLab-IMX410 core.
"""
import argparse, hashlib, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
IMXL = HERE.parents[1] / 'imx410-lab'
sys.path[:0] = [str(IMXL), str(IMXL / 'offline')]
import quality as Q                                                 # noqa: E402

OUT = HERE / 'matrix.json'
HOST_FPS = 59.94
DC = {'OG': (6048, 4040), 'HD': (6048, 3402), 'S35': (4192, 2358), 'APSC': (3958, 2628), 'S16': (2108, 1248),
      'SQ': (4040, 4040)}
RES_F = [(1, 1), (2, 3), (1, 2), (1, 3), (1, 6)]
EXTRA = {'HD': [(3840, 2160), (1920, 1080)]}                        # UHD / FHD only on HD
QUAL = Q.QUAL                                                       # every readout class (40)
quality_of = Q.quality_of


def res_list(dc):
    w, h = DC[dc]
    out = [(w * a // b // 16 * 16, (w * a // b // 16 * 16) * h // w & ~1) for a, b in RES_F]
    return out + EXTRA.get(dc, [])


def readout(key, cw, ch, rows=None):
    """The plan at the fastest rate the host can record: max fps, capped at HOST_FPS (R11 in quality.readout;
    rows = R16's row crop)."""
    return Q.readout(key, cw, ch, HOST_FPS, rows)


def cases():
    """quality.candidates over every preset DC x RES at the host cap (readout x CRCT bin, R2 1025 + WIDEN retry)."""
    out = []
    for dc, (cw, ch) in DC.items():
        for rw, rh in res_list(dc):
            out += [dict(dc=dc, **c) for c in Q.candidates(cw, ch, rw, rh, HOST_FPS)]
    return pick_windows(out)


def pick_windows(cs):
    """One case per DC x RES x quality: of its window variants the fastest (quality.pick), named and hashed."""
    out = Q.pick(cs, lambda c: (c['dc'], tuple(c['res'])))
    for c in out:
        m, ad, hb, vb = quality_of(c)
        c['name'] = f"{c['dc']} {c['res'][0]}x{c['res'][1]} · {m} · {ad}b · h{hb}v{vb} · {c['fps']:.3f}p"
        c['id'] = case_id(c)
    return out


def case_id(c):
    """What gets installed, hashed: the folder name that survives a reordered matrix."""
    keep = {k: c[k] for k in ('readout', 'merge', 'bits', 'hbin', 'vbin', 'window', 'zoom', 'rec')}
    return hashlib.sha1(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:8]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', default=str(OUT))
    a = ap.parse_args()
    cs = cases()
    for i, c in enumerate(cs):
        print(f'C{c["id"]} M{i:<4}{c["dc"]:5}{c["res"][0]:>5}x{c["res"][1]:<5}{c["quality"]:7}{c["fps"]:>8} {c["path"]:3} '
              f'z{c["zoom"][0]}x{c["zoom"][1]}  rec {c["rec"][0]}x{c["rec"][1]}  {c["readout_id"]}')
    pathlib.Path(a.json).write_text(json.dumps(cs, indent=1))
    print(f'{len(cs)} cases -> {a.json}')


if __name__ == '__main__':
    main()
