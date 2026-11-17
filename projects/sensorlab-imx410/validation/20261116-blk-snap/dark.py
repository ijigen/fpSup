#!/usr/bin/env python3
"""Dark-frame black of a lens-capped DNG (rawpy raw_image, the active area): per CFA channel mean and the tag."""
import sys, json, numpy as np, rawpy
def dark(path):
    with rawpy.imread(str(path)) as r:
        v = r.raw_image_visible.astype(np.float64)
        bl = list(r.black_level_per_channel); pat = r.raw_pattern
    tag = float(__import__('subprocess').run(['exiftool', '-s3', '-BlackLevel', str(path)], capture_output=True,
                text=True).stdout.split()[0])
    h, w = v.shape
    core = v[h // 8: h - h // 8, w // 8: w - w // 8]
    ch = {f'{y}{x}': core[y::2, x::2] for y in (0, 1) for x in (0, 1)}
    means = {k: float(c.mean()) for k, c in ch.items()}
    rs = v.std(1)
    return dict(tag=tag, mean=float(core.mean()), means=means, std=float(core.std()),
                p_hi=float(np.percentile(core, 99.9)), offset=float(core.mean()) - tag, shape=[h, w],
                flat_rows=int((rs == 0).sum()),                 # a real dark row has noise: 0 = not sensor data
                # inside the stock 5-row DefaultCrop margin a flat row is tolerated (11-16: APS-C 1312-row V2 / 2x2
                # recipes end in 2 rows of 1..4, outside the crop)
                valid=bool(not any(5 <= i < h - 5 for i in np.nonzero(rs == 0)[0]) and float(np.percentile(core, 99.9)) - tag < 64 * (4 if tag > 600 else 1)))
if __name__ == '__main__':
    for p in sys.argv[1:]:
        print(p, json.dumps(dark(p)))
