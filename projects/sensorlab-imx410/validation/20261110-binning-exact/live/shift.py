
import sys, json, numpy as np, rawpy
a, b = (rawpy.imread(p).raw_image_visible[40:-40, 40:-40].astype(np.float32) for p in sys.argv[1:3])
H, W = a.shape; r = {}
for dy in range(-3, 4):
    for dx in range(-2, 3):
        A = a[max(dy,0):H+min(dy,0), max(dx,0):W+min(dx,0)]; B = b[max(-dy,0):H-max(dy,0), max(-dx,0):W-max(dx,0)]
        r[(dy, dx)] = float(np.abs(A - B).mean())
k = min(r, key=r.get)
print(json.dumps(dict(dy=k[0], dx=k[1], err=round(r[k], 2), err00=round(r[(0, 0)], 2), shape=list(a.shape))))
