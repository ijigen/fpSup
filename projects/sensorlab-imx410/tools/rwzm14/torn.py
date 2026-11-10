import sys,json,numpy as np
sys.path.insert(0,'.'); import bits
from case import dng_tags,unpack_msb
for run in sys.argv[1:]:
    fs=bits.frames(run)
    for i,b in enumerate(fs):
        t=dng_tags(b); w,h=t[256][2],t[257][2]; off=t[273][2]
        px=unpack_msb(b[off:off+w*h*14//8],14,w*h).reshape(h,w).astype(int)
        rowz=( (px%4)==0).mean(axis=1)
        good=rowz>0.99
        # blocks of 16 rows
        seg=''.join('#' if g else '.' for g in good[::max(1,h//64)])
        print(run,i,w,h,'rows mod4-clean %.3f'%good.mean(),seg)
