#!/usr/bin/env python3
"""T-C analysis: bits.py's metrics on BUFA0 14-bit frames (frame.raw / frame2.raw + frame.json per stage dir).

    tc_bits.py RUN_DIR      -> RUN_DIR/bits.json, RUN_DIR/<stage>/view.png; prints one line per stage
"""
import json, pathlib, sys
import numpy as np
sys.path.insert(0, '/Users/dido/Developer.localized/SIGMAfp_re/projects/imx410-lab')
from decode14 import decode14                                                    # noqa: E402


def stats(px):
    v = px.ravel().astype(np.int64)
    r4 = np.bincount(v % 4, minlength=4) / v.size
    r16 = np.bincount(v % 16, minlength=16) / v.size
    ent = lambda r: float(-(r[r > 0] * np.log2(r[r > 0])).sum())
    lo, hi = np.percentile(v, [2, 98]).astype(int)
    sel = v[(v >= lo) & (v <= hi)]
    return dict(r4=[round(float(x), 4) for x in r4], ent4=round(ent(r4), 3), ent16=round(ent(r16), 3),
                r2_even=round(float((v % 2 == 0).mean()), 4), occ=round(len(np.unique(sel)) / (hi - lo + 1), 3),
                vmin=int(v.min()), vmed=int(np.median(v)), vmax=int(v.max()))


def png(img, path):
    import zlib, struct
    a = img.astype(np.float64)
    lo, hi = np.percentile(a, [1, 99.5])
    g = (np.clip((a - lo) / max(hi - lo, 1), 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)
    g = g[::2, ::2]
    raw = b''.join(b'\x00' + g[y].tobytes() for y in range(g.shape[0]))
    c = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + c(b'IHDR', struct.pack('>IIBBBBB', g.shape[1], g.shape[0], 8, 0, 0, 0, 0))
                     + c(b'IDAT', zlib.compress(raw, 6)) + c(b'IEND', b''))


def main():
    run = pathlib.Path(sys.argv[1]); res = {}
    for d in sorted(p for p in run.iterdir() if (p / 'frame.json').exists()):
        m = json.loads((d / 'frame.json').read_text())
        fr = [decode14((d / n).read_bytes(), m['height'], m['line_words']).astype(np.int64)
              for n in ('frame.raw', 'frame2.raw') if (d / n).exists()]
        top = (m['window'] >> 16) + 2
        a = fr[0][top:, 16:-16]
        r = dict(stage=m.get('stage'), mux=m.get('mux'), shape=list(fr[0].shape), img=stats(a),
                 ob=stats(fr[0][2:max(3, top - 4), 100:-100]) if top > 8 else None)
        if len(fr) > 1:
            b = fr[1][top:, 16:-16]
            r['tnoise'] = round(float(np.std(a - b) / np.sqrt(2)), 2)
            r['identical'] = bool((a == b).all())
        g = a[0::2, 1::2].astype(float); rr = a[0::2, 0::2].astype(float); bb = a[1::2, 1::2].astype(float)
        bl = float(np.median(fr[0][2:max(3, top - 4)])) if top > 8 else 1024.0
        gm = g.mean() - bl
        r['R/G'], r['B/G'] = round((rr.mean() - bl) / gm, 3), round((bb.mean() - bl) / gm, 3)
        r['dx2'] = round(float(np.abs(a[:, 2:] - a[:, :-2]).mean()), 2)
        png(a, d / 'view.png')
        res[d.name] = r
        i = r['img']
        print(f"{d.name} mux {r['mux']} {r['shape']} r4 {i['r4']} ent16 {i['ent16']} occ {i['occ']} "
              f"tnoise {r.get('tnoise')} identical {r.get('identical')} R/G {r['R/G']} B/G {r['B/G']} dx2 {r['dx2']}")
    (run / 'bits.json').write_text(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
