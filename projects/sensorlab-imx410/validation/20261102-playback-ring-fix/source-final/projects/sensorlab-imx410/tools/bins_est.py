import sys,json,subprocess,pathlib,numpy as np
sys.path.insert(0,'/Users/dido/Developer.localized/SIGMAfp_re/tools/bayer-jxl'); sys.path.insert(0,'/private/tmp/claude-501/-Users-dido-Developer-localized-SIGMAfp-re/f58271b0-5db4-4cd7-a9d1-abe4b221a3ba/scratchpad')
from bayer_jxl import split_bufa
from lj92est import estimate
SRC=pathlib.Path('/Users/dido/Developer.localized/SIGMAfp_re/projects/imx410-lab/captures')
S=pathlib.Path(sys.argv[1]); sub=sys.argv[2]
for d in sys.argv[3:]:
    g=json.loads((SRC/sub/d/'frame.json').read_text()); bits=g.get('bits',12)
    raw=subprocess.run(['zstd','-q','-dc',str(S/d/'frame.raw.zst')],capture_output=True,check=True).stdout
    px=split_bufa(raw,g['height'],g['line_words'],bits)[0]
    h,w=px.shape; px=px[:h-h%2,:w-w%2]
    est,n=estimate(px,bits,512,512)
    bpp=est*8/px.size
    out={'mode':d,'shape':px.shape,'bits':bits,'bpp':round(bpp,3),'ratio_vs_bits':round(bpp/bits,3),'mean':round(float(px.mean()),1),'p1':int(np.percentile(px,1)),'p99':int(np.percentile(px,99))}
    if bits==12:
        e11,_=estimate((px>>1)<<1,12,512,512); out['bpp_11ad_in12']=round(e11*8/px.size,3)
        e10,_=estimate((px>>2)<<2,12,512,512); out['bpp_10ad_in12']=round(e10*8/px.size,3)
    if bits==14:
        e12,_=estimate(px>>2,12,512,512); out['bpp_as12']=round(e12*8/px.size,3)
    print(json.dumps(out),flush=True)
