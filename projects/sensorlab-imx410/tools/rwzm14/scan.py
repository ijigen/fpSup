import json,glob,os,collections
V='/Users/dido/Developer.localized/SIGMAfp_re/projects/isp-lab/validation'
rows=[]
for cj in glob.glob(V+'/*/case.json'):
    d=os.path.dirname(cj)
    try: c=json.load(open(cj))
    except Exception: continue
    e=c.get('experiment') or {}
    w=e.get('want') or {}
    ap=os.path.join(d,'applied.json')
    sm=vm=None
    if os.path.exists(ap):
        try:
            a=json.load(open(ap)); sm=a.get('sensor_mode'); vm=(a.get('vmode') or [None])[0]
        except Exception: pass
    cd=(c.get('checkpoints') or {}).get('cdng') or {}
    rows.append(dict(run=os.path.basename(d),bits=w.get('bits'),dngbits=cd.get('bits'),zoom=w.get('zoom'),scale=w.get('scale'),bin=w.get('bin'),name=e.get('name'),sm=sm,vm=vm,ncdng=(c.get('counts')or{}).get('cdng'),verdict=c.get('verdict'),hasev=os.path.exists(d+'/evidence.tar.zst')))
print(len(rows))
cnt=collections.Counter((r['bits'],r['dngbits']) for r in rows); print(cnt)
json.dump(rows,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'rows.json'),'w'))
r14=[r for r in rows if r['dngbits']==14]
def cls(r):
    z=r['zoom'] or [1024,1024]; b=r['bin'] or [1,1]
    t=[]
    if b!=[1,1]: t.append('bin%dx%d'%tuple(b))
    if z[0]!=1024 or z[1]!=1024: t.append('rwzm')
    return '+'.join(t) or '1:1'
print(collections.Counter(cls(r) for r in r14))
print(collections.Counter(r['sm'] for r in r14))
for r in r14[:5]: print(r)
