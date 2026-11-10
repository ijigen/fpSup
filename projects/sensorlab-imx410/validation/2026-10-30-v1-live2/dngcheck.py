"""dngcheck.py DNG PREVIEW.png -- metadata, mod-4 bits, dark levels vs BlackLevel, colour preview (tools/analyze_dng.py)."""
import sys, json, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'tools'))
import numpy as np, analyze_dng as A
src, prev = sys.argv[1], sys.argv[2]
data = pathlib.Path(src).read_bytes()
t = A.Tiff(data); raw = A.choose_raster(t.ifds)
rep = A.analyze(data, source=src, source_size=len(data), preview=prev)
md = rep['metadata']
keep = ('raster', 'bits_per_sample', 'compression', 'active_area', 'default_crop_origin', 'default_crop_size',
        'default_scale', 'black_level', 'white_level', 'as_shot_neutral', 'frame_rate', 'masked_areas')
res = {'file': pathlib.Path(src).name, 'bytes': len(data), **{k: md.get(k) for k in keep}}
_, blocks = A.decode_pixels(data, raw, 0, ())
a = np.concatenate([b for _, b in blocks]).astype(np.int64)
res['min'], res['max'], res['mean'] = int(a.min()), int(a.max()), float(a.mean())
m4 = np.bincount((a & 3).ravel(), minlength=4) / a.size
res['mod4_all'] = [round(float(x), 4) for x in m4]
dark = a[a <= np.percentile(a, 2)]
res['mod4_dark2pct'] = [round(float(x), 4) for x in np.bincount(dark & 3, minlength=4) / dark.size]
res['p0.1'], res['p1'], res['p50'] = (float(np.percentile(a, q)) for q in (0.1, 1, 50))
for name, sl in (('left16', a[:, :16]), ('right16', a[:, -16:]), ('top8', a[:8]), ('bottom8', a[-8:])):
    res[name] = [round(float(sl.mean()), 1), int(sl.min()), int(sl.max())]
res['preview'] = rep.get('preview', {}).get('path') or rep.get('preview')
print(json.dumps(res))
open(pathlib.Path(__file__).with_name('results.jsonl'), 'a').write(json.dumps(dict(tag='dng', **res), default=str) + '\n')
