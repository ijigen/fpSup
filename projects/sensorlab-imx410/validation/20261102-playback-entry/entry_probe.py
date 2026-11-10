"""Offline investigation, not a camera test. Native setPlayInfo/v2/v11, mocked I/O and tag parser."""
import sys,json,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'projects/sensorlab-imx410/apply'))
import test_playback_checked as C
T=C.T
SEQ=T.WORK+0x9000
VIEW=T.WORK+0xA000
class Entry(C.NativePrepare):
    IO={0xC0013090:'once',0xC03C0C80:'timer',0xC03C0CD0:'timer_end',
        0xC03D4C00:'view',0xC03B7C58:'copy_path',0xC069B930:'media',
        0xC069B568:'filename',0xC0013CF8:'copy',
        0xC00178D8:'state_init',0xC0017AC8:'camera_state',
        0xC001D860:'alloc_init',0xC001D948:'alloc_data',0xC001D8F8:'free',
        0xC0365E90:'file_init',0xC069B9B8:'filepath',0xC0365FB0:'open',
        0xC0366060:'read',0xC0365ED0:'file_free',0xC00C1508:'tiff_init',
        0xC05BDD68:'file_size',0xC05BFF80:'audio',0xC05C1BD8:'timecode',
        0xC0055F20:'tiff_free',0xC0015AE0:'udiv',
        T.WORK+0xB000:'view0',T.WORK+0xB004:'view1'}
    def __init__(self):
        super().__init__()
        self.trace=[]
        del self.by_addr[0xC05BCB60]
        self.mu.mem_write(0xC05BCB60,struct.pack('<I',T.iw(0xC05BCB60)))
        self.mu.mem_write(T.OBJ+0x34,T.image()[0x2DFDF4C:0x2DFDF4C+100])
        self.put(T.OBJ+4,0xC2DFDE50)
        self.put(SEQ+8,T.OBJ);self.put(SEQ+0x3C,32*1024*1024)
        self.put(VIEW,VIEW+0x100)
        self.put(VIEW+0x110,T.WORK+0xB000);self.put(VIEW+0x114,T.WORK+0xB004)
        self.mu.mem_write(T.WORK+0xB100,b'A001_001_000001.DNG\0'.ljust(64,b'\0'))
        for a,n in self.IO.items():self.stub(a,n)
        self.handle=self.mu.hook_add(C.UC_HOOK_CODE,self.guard)
    def guard(self,mu,a,size,data):
        self.trace.append(a)
        if len(self.trace)>60:self.trace.pop(0)
        if (a in self.by_addr or a==T.DONE or T.BLOB<=a<T.BLOB+len(self.img) or
            T.MEM<=a<T.MEM+40*88 or T.CAVE_ARENA<=a<T.CAVE_ARENA+0x1000 or
            0xC05BCB60<=a<0xC05BCC38 or 0xC05BDE28<=a<0xC05BE3A0 or 0xC05BC408<=a<0xC05BC490 or 0xC05BDAD0<=a<0xC05BDAF8 or
            0xC03BAB68<=a<0xC03BAE30 or 0xC05BCF28<=a<0xC05BCF80 or
            0xC05BDB08<=a<0xC05BDD68 or 0xC05C1A58<=a<0xC05C1BD8 or
            0xC03B86A0<=a<0xC03B86D8 or 0xC06A0770<=a<0xC06A08D0 or 0xC00159D0<=a<0xC0015A00):return
        raise AssertionError(f'unmodeled {a:08x}; tail={[hex(v) for v in self.trace[-14:]]}')
    def _hook(self,mu,a,size,data):
        if a==0xC05BCB60:return  # Execute ROM; SelectedCam otherwise intercepts this by address.
        if a not in self.IO:return super()._hook(mu,a,size,data)
        n=self.IO[a];r=[self.r(x) for x in (T.UC_ARM_REG_R0,T.UC_ARM_REG_R1,T.UC_ARM_REG_R2,T.UC_ARM_REG_R3)]
        self.calls.append((n,*r[:2]))
        if n=='once':return self.ret(0)
        if n=='view':return self.ret(VIEW)
        if n in ('view0','view1'):return self.ret(0)
        if n=='camera_state':return self.ret(T.WORK+0xC000)
        if n=='alloc_init':self.put(r[0]+8,0x500000)
        if n=='alloc_data':return self.ret(T.WORK+0x100000)
        if n in ('filename','filepath'):return self.ret(T.WORK+0xB100)
        if n=='copy':mu.mem_write(r[0],bytes(mu.mem_read(r[1],r[2])))
        if n=='open':return self.ret(1)
        if n=='read':self.put(r[3],200000);return self.ret(1)
        if n=='tiff_init':self.put(r[0],T.TIFF)
        if n=='file_size':
            self.put(r[0]+0xA0,4*1024*1024);self.put(r[0]+0xA4,0)
            self.put(r[2]+0xC,4);self.put(r[2]+0x10,16*1024*1024);self.put(r[2]+0x14,0)
        if n=='udiv':return self.ret(r[0]//r[1])
        return self.ret(0)
    def entry(self,tags):
        self.tags=tags
        result=self.call(0xC03BAB68,SEQ,T.WORK+0xD000,1,0)
        return result
if __name__=='__main__':
    c=Entry()
    try:
        result=c.entry(C.movie())
        print(json.dumps(dict(result=result,pb=c.pb(),obj={hex(o):c.w(T.OBJ+o) for o in (0x54,0x58,0x68,0x88,0x98,0x9C,0xA8)}),indent=2))
        print('prepare',C.SelectedCam.prepare(c))
    except Exception:
        print('calls',c.calls[-20:]);raise
