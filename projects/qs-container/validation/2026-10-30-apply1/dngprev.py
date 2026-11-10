# dngprev.py DNG OUT.png: 12-bit packed (MSB first) RGGB -> black-subtracted, WB'd, half-res colour PNG + stats
import sys, numpy as np
from PIL import Image
p, out = sys.argv[1], sys.argv[2]
W, H, OFF, BL, WL = 2016, 1330, 78848, 256, 4095
wb = (1/0.5089463221, 1.0, 1/0.5871559633)
b = np.frombuffer(open(p,'rb').read()[OFF:OFF+W*H*3//2], np.uint8).astype(np.uint16).reshape(-1,3)
a = np.empty(b.shape[0]*2, np.uint16)
a[0::2] = (b[:,0]<<4) | (b[:,1]>>4); a[1::2] = ((b[:,1]&15)<<8) | b[:,2]
r = a.reshape(H, W).astype(np.float32)
R, G1, G2, B = r[0::2,0::2], r[0::2,1::2], r[1::2,0::2], r[1::2,1::2]
for n,c in (('R',R),('G1',G1),('G2',G2),('B',B)):
    print(f'{n}: mean {c.mean():.1f} min {c.min():.0f} max {c.max():.0f} p1 {np.percentile(c,1):.0f} p99 {np.percentile(c,99):.0f}')
print('G1/G2 mean diff', round(float((G1-G2).mean()),2), ' rows 0-4 mean', [round(float(r[i].mean()),1) for i in range(5)],
      ' last rows', [round(float(r[i].mean()),1) for i in range(H-3,H)])
print('R/G', round(float((R-BL).mean()/((G1+G2)/2-BL).mean()),3), 'B/G', round(float((B-BL).mean()/((G1+G2)/2-BL).mean()),3))
rgb = np.stack([(R-BL)*wb[0], ((G1+G2)/2-BL)*wb[1], (B-BL)*wb[2]], -1).clip(0, None)/(WL-BL)
rgb = rgb/ max(np.percentile(rgb, 99.5), 1e-6)
img = (np.clip(rgb,0,1)**(1/2.2)*255).astype(np.uint8)
Image.fromarray(img).save(out); print('saved', out, img.shape)
