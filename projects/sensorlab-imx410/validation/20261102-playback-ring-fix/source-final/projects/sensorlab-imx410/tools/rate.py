import math
HDR_U=79184; HDR_C=79872+2048; TILE_HDR=80
def grid(w,h):
    best=None
    for tw in range(32,513,32):
        for th in range(16,513,16):
            nx=-(-w//tw); ny=-(-h//th)
            if nx*ny>160: continue
            c=nx*tw*ny*th+32250*nx*ny
            if best is None or c<best[0]: best=(c,tw,th,nx,ny)
    return best[1:]
def bpp(iso,b,u): return min(b, 4.7+0.5*math.log2(max(iso,100)/100)+(b-12)+1.5*u)
def rates(w,h,ad,fps,iso,u=0):
    b=12 if ad<=12 else 14
    Fu=w*h*b/8+HDR_U
    tw,th,nx,ny=grid(w,h); padA=nx*tw*ny*th
    Fc=min(Fu, w*h*bpp(iso,b,u)/8+TILE_HDR*nx*ny+HDR_C)
    tc=4.7*padA/1e6+0.46e-3*nx*ny*th+2.0
    praw=max(0.0,1-1000/(fps*tc))
    return Fu*fps/1e6, fps*((1-praw)*Fc+praw*Fu)/1e6, tc, praw, (tw,th)
for name,w,h,ad,fps,iso,u in [("FHD",1936,1090,12,29.97,100,0),("FHD",1936,1090,12,29.97,3200,0),("FHD",1936,1090,12,59.94,800,0),
  ("FHD",1936,1090,12,119.88,800,0),("OG3K",3024,2010,12,23.976,800,0),("OG3K",3024,2010,12,29.97,800,0),("OG3K",3024,2010,12,29.97,3200,0),
  ("UHD",3856,2170,12,23.976,800,0),("UHD",3856,2170,12,29.97,800,0),("M12",1008,672,12,119.88,800,0),("M12",1008,672,12,239.76,800,0),
  ("OG2K",2016,1344,12,59.94,100,0),("6K14",6064,4042,14,23.976,100,1),("1x1 crop",3008,2000,11,29.97,800,1)]:
    U,L,tc,pr,t=rates(w,h,ad,fps,iso,u)
    print(f"| {name} {w}x{h} AD{ad} | {fps} | ISO{iso} | {U:.1f} | {L:.1f} | {L/U*100:.0f}% | {t[0]}x{t[1]} | {tc:.1f} | {pr*100:.0f}% |")
