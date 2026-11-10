import json,os,sys,glob,subprocess,struct,tempfile,shutil,collections
import numpy as np
sys.path.insert(0,'/Users/dido/Developer.localized/SIGMAfp_re/projects/isp-lab/host')
from case import dng_tags, unpack_msb
V='/Users/dido/Developer.localized/SIGMAfp_re/projects/isp-lab/validation'
TMP=os.path.join(tempfile.gettempdir(),'rwzm14')
def rational_or_int(b,t,tag):
    if tag not in t: return None
    typ,cnt,val=t[tag]
    if typ==3: return [val&0xFFFF] if cnt==1 else list(struct.unpack_from('<%dH'%cnt,b,val)) if cnt>2 else [val&0xFFFF,val>>16][:cnt]
    if typ==4: return [val] if cnt==1 else list(struct.unpack_from('<%dI'%cnt,b,val))
    if typ==5:
        r=struct.unpack_from('<%dI'%(2*cnt),b,val if cnt>0 else 0); return [r[2*i]/r[2*i+1] for i in range(cnt)]
def analyse(b):
    t=dng_tags(b)
    w,h,bps=t[256][2],t[257][2],t[258][2]&0xFFFF
    off=t[273][2]
    px=unpack_msb(b[off:off+w*h*bps//8],bps,w*h).reshape(h,w).astype(np.int32)
    bl=rational_or_int(b,t,0xC61A); wl=rational_or_int(b,t,0xC61D)
    v=px.ravel()
    r4=np.bincount(v%4,minlength=4)/v.size
    r16=np.bincount(v%16,minlength=16)/v.size
    ent4=float(-(r4[r4>0]*np.log2(r4[r4>0])).sum())
    ent16=float(-(r16[r16>0]*np.log2(r16[r16>0])).sum())
    # flattest 16x16 tile per green phase
    g=px[0::2,1::2]
    best=None
    for y in range(0,g.shape[0]-16,8):
        for x in range(0,g.shape[1]-16,8):
            tl=g[y:y+16,x:x+16]; s=tl.std()
            if best is None or s<best[0]: best=(s,tl)
    tl=best[1]; u=np.unique(tl)
    occ=len(u)/(u.max()-u.min()+1)
    # code occupancy over the populated range between p1..p99 of whole image
    lo,hi=np.percentile(v,[2,98]).astype(int)
    sel=v[(v>=lo)&(v<=hi)]
    used=len(np.unique(sel)); span=hi-lo+1
    # dark region occupancy (lowest 5%)
    d_lo=v.min(); d_hi=int(np.percentile(v,5))
    dsel=v[v<=d_hi]; dused=len(np.unique(dsel)); dspan=d_hi-d_lo+1
    return dict(w=w,h=h,bps=bps,black=bl,white=wl,r4=[round(x,4) for x in r4],ent4=round(ent4,3),ent16=round(ent16,3),
        r2=round(float((v%2==0).mean()),4),flat_std=round(float(best[0]),2),flat_distinct=len(u),flat_occ=round(occ,3),
        occ=round(used/span,3),span=int(span),dark_occ=round(dused/dspan,3),dark_span=int(dspan),vmin=int(v.min()),vmax=int(v.max()))
def frames(run,maxn=3):
    d=V+'/'+run
    out=[]
    if os.path.exists(d+'/evidence.cdngt'):
        man=json.load(open(d+'/EVIDENCE.json'))
        names=[m['name'] for m in man['members'] if m['name'].startswith('push/cdng_')][:maxn]
        if not names: return out
        dest=TMP+'/'+run; os.makedirs(dest,exist_ok=True)
        if not all(os.path.exists(dest+'/'+n) for n in names):
            subprocess.run([sys.executable,'/Users/dido/Developer.localized/SIGMAfp_re/projects/isp-lab/host/evidence_jxl.py','unpack',d,dest]+names,check=True,capture_output=True)
        out=[open(dest+'/'+n,'rb').read() for n in names]
    elif os.path.exists(d+'/evidence.tar.zst'):
        dest=TMP+'/'+run; os.makedirs(dest,exist_ok=True)
        if not glob.glob(dest+'/push/cdng_*'):
            subprocess.run('zstd -dc %s/evidence.tar.zst | tar -xf - -C %s --include "push/cdng_*"'%(d,dest),shell=True,check=True)
        out=[open(f,'rb').read() for f in sorted(glob.glob(dest+'/push/cdng_*'))[:maxn]]
    else:
        out=[open(f,'rb').read() for f in sorted(glob.glob(d+'/push/cdng_*'))[:maxn]]
    return out
if __name__=='__main__':
    rows=json.load(open(os.path.dirname(os.path.abspath(__file__))+'/rows.json'))
    want=sys.argv[1]  # '14' or '12'
    lim=int(sys.argv[2]) if len(sys.argv)>2 else 10**9
    res=[]
    sel=[r for r in rows if str(r['dngbits'])==want]
    n=0
    for r in sel:
        if n>=lim: break
        try: fs=frames(r['run'])
        except Exception as e: print('ERR',r['run'],e,file=sys.stderr); continue
        if not fs: continue
        n+=1
        a=[]
        for b in fs:
            try: a.append(analyse(b))
            except Exception as e: print('AERR',r['run'],e,file=sys.stderr)
        res.append(dict(r,frames=a))
        print(r['run'],r['zoom'],r['bin'],[(x['r4'],x['ent4'],x['flat_occ'],x['occ']) for x in a][:1],flush=True)
        shutil.rmtree(TMP+'/'+r['run'],ignore_errors=True)
    json.dump(res,open(os.path.dirname(os.path.abspath(__file__))+'/res%s.json'%want,'w'))
