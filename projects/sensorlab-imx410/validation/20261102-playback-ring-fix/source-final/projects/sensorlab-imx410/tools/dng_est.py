import sys,json,os,rawpy,numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from lj92est import estimate
def grid(w,h):
    best=None
    for tw in range(32,513,32):
        for th in range(16,513,16):
            nx=-(-w//tw); ny=-(-h//th)
            if nx*ny>160: continue
            c=nx*tw*ny*th+32250*nx*ny
            if best is None or c<best[0]: best=(c,tw,th)
    return best[1],best[2]
for p in sys.argv[1:]:
    r=rawpy.imread(p); img=r.raw_image_visible.copy(); h,w=img.shape
    bits=int(np.ceil(np.log2(max(int(r.white_level),2)+1)))
    tw,th=grid(w,h)
    est,n=estimate(img,bits,tw,th)
    bl=float(np.mean(r.black_level_per_channel))
    print(json.dumps({'p':p[-70:],'wh':[w,h],'bits':bits,'tile':[tw,th],'bpp':round(est*8/img.size,3),'ratio':round(est/(img.size*bits/8),3),'sig':round(float(img.mean())-bl,1),'p99':int(np.percentile(img,99))}),flush=True)
