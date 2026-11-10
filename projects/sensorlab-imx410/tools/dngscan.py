import struct, sys, os, json
def parse(path):
    f=open(path,'rb'); d=f.read(); f.close()
    bo='<' if d[:2]==b'II' else '>'
    def ifd(off):
        n=struct.unpack(bo+'H',d[off:off+2])[0]; t={}
        for i in range(n):
            e=d[off+2+12*i:off+14+12*i]
            tag,typ,cnt=struct.unpack(bo+'HHI',e[:8])
            sz={1:1,2:1,3:2,4:4,5:8,7:1,9:4,10:8,11:4,12:8,13:4}.get(typ,1)*cnt
            vo=e[8:12] if sz<=4 else d[struct.unpack(bo+'I',e[8:12])[0]:][:sz]
            if typ==3: v=list(struct.unpack(bo+'%dH'%cnt,vo[:2*cnt]))
            elif typ in (4,13): v=list(struct.unpack(bo+'%dI'%cnt,vo[:4*cnt]))
            elif typ==5: v=[struct.unpack(bo+'II',vo[8*k:8*k+8]) for k in range(cnt)]
            elif typ==2: v=vo[:cnt].rstrip(b'\0').decode('latin1')
            else: v=vo
            t[tag]=v
        nxt=struct.unpack(bo+'I',d[off+2+12*n:off+6+12*n])[0]
        return t,nxt
    off=struct.unpack(bo+'I',d[4:8])[0]
    t,_=ifd(off)
    sub=t.get(330)
    if sub: t2,_=ifd(sub[0]); t2.update({k:v for k,v in t.items() if k not in t2}); t=t2
    r={}
    r['w']=t.get(256,[0])[0]; r['h']=t.get(257,[0])[0]; r['bits']=t.get(258,[0])[0]; r['comp']=t.get(259,[0])[0]
    tw=t.get(322); tl=t.get(323)
    r['tile']=(tw[0],tl[0]) if tw else None
    bc=t.get(325) or t.get(279)
    r['pix_bytes']=sum(bc) if bc else None
    r['ntile']=len(bc) if bc else 0
    bl=t.get(50714)
    if bl:
        if isinstance(bl[0],tuple): bl=[a/b for a,b in bl]
        r['black']=sum(bl)/len(bl)
    r['white']=t.get(50717,[None])[0]
    exif=t.get(34665)
    if exif:
        e,_=ifd(exif[0]); iso=e.get(34855); r['iso']=iso[0] if iso else None
        et=e.get(33434); r['exp']=et[0][0]/et[0][1] if et else None
    r['size']=len(d)
    return r
for p in sys.argv[1:]:
    try: r=parse(p)
    except Exception as ex: r={'err':str(ex)}
    r['path']=p; print(json.dumps(r))
