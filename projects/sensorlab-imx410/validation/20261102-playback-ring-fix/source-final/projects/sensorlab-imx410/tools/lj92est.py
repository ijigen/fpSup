import numpy as np, heapq, rawpy, sys, json, os
def huff_lengths(freq):
    items=[(f,i) for i,f in enumerate(freq) if f>0]
    if len(items)==1: return {items[0][1]:1}
    h=[(f,[i]) for f,i in items]; heapq.heapify(h); L={i:0 for _,i in items}
    while len(h)>1:
        a=heapq.heappop(h); b=heapq.heappop(h)
        for i in a[1]+b[1]: L[i]+=1
        heapq.heappush(h,(a[0]+b[0],a[1]+b[1]))
    return L
def cat(d):
    a=np.abs(d).astype(np.int64)
    c=np.zeros_like(a); nz=a>0
    c[nz]=np.floor(np.log2(a[nz])).astype(np.int64)+1
    return c
def tile_bits(t, bits):
    # t: HxW (W even) CFA; components = even/odd columns; predictor 1 (left same comp), col0 from above
    t=t.astype(np.int64)
    pred=np.empty_like(t)
    pred[:,2:]=t[:,:-2]
    pred[1:,:2]=t[:-1,:2]
    pred[0,:2]=1<<(bits-1)
    d=t-pred
    total=0
    for c in (0,1):
        cc=cat(d[:,c::2]).ravel()
        freq=np.bincount(cc,minlength=17)
        L=huff_lengths(freq)
        total+=sum(freq[k]*(L[k]+k) for k in L)
    return total
def estimate(img,bits,tw,th):
    H,W=img.shape
    nx=-(-W//tw); ny=-(-H//th)
    P=np.pad(img,((0,ny*th-H),(0,nx*tw-W)),mode='edge')
    tot=0
    for y in range(ny):
        for x in range(nx):
            tot+=tile_bits(P[y*th:(y+1)*th,x*tw:(x+1)*tw],bits)
    hdr=nx*ny*72
    return tot/8+hdr, nx*ny
if __name__=='__main__':
    tw,th=int(sys.argv[1]),int(sys.argv[2]); bits=int(sys.argv[3])
    for p in sys.argv[4:]:
        r=rawpy.imread(p); img=r.raw_image_visible.copy()
        est,n=estimate(img,bits,tw,th)
        print(json.dumps({'path':p,'shape':img.shape,'est_bytes':int(est),'bpp':est*8/img.size,'mean':float(img.mean()),'std':float(img.std())}))
