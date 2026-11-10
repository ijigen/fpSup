"""Native TIFF reader on recorded DNG bytes, no device I/O."""
from entry_probe import *
class Parser(Entry):
    RUNTIME={0xC03D8BD0:'new',0xC001349C:'delete',0xC03D8E20:'delete',0xC0014DAC:'memcpy',0xC001510C:'memcpy'}
    def __init__(self,path):
        self.tagcalls=[];self.pending=[]
        self.data=path.read_bytes();self.heap=0x48500000
        super().__init__()
        self.mu.mem_map(self.heap,0x800000)
        self.mu.mem_map(0x49000000,0x800000)
        self.mu.mem_write(0x49000000,self.data)
        for address in (0xC00C1508,0xC0055F20,*[T.PB[n] for n in ('TAG_E40','TAG_DB8','TAG_ED0','TAG_458','TAG_4D8')]):
            self.by_addr.pop(address,None)
            self.mu.mem_write(address,struct.pack('<I',T.iw(address)))
        for a,n in self.RUNTIME.items():self.stub(a,n)
    def guard(self,mu,a,size,data):
        if a in (0xC05C1DB8,0xC05C1E40,0xC05C1ED0):
            self.pending.append((self.r(T.UC_ARM_REG_LR)&~1,self.r(T.UC_ARM_REG_R2),self.r(T.UC_ARM_REG_R3),a))
        if self.pending and a==self.pending[-1][0]:
            lr,tag,p,callee=self.pending.pop()
            self.tagcalls.append((hex(callee),hex(tag),self.r(T.UC_ARM_REG_R0),bytes(mu.mem_read(p,8)).hex()))
        if (0xC00B8000<=a<0xC00C3000 or 0xC05A4D70<=a<0xC05A4F18 or
            0xC05C1DB8<=a<0xC05C1FE8 or 0xC0055F20<=a<0xC0055F80 or 0xC01F57CC<=a<0xC01F57F4 or 0xC03D8F80<=a<0xC03D8FA8):return
        return super().guard(mu,a,size,data)
    def _hook(self,mu,a,size,data):
        if a in (0xC00C1508,0xC0055F20):return
        r=[self.r(x) for x in (T.UC_ARM_REG_R0,T.UC_ARM_REG_R1,T.UC_ARM_REG_R2,T.UC_ARM_REG_R3)]
        if a==0xC001D948:return self.ret(0x49000000)
        if a==0xC0366060:self.put(r[3],len(self.data));return self.ret(1)
        if a in self.RUNTIME:
            n=self.RUNTIME[a]
            if n=='new':
                p=self.heap;self.heap+=(r[0]+15)&~15
                assert self.heap<0x48D00000
                return self.ret(p)
            if n=='memcpy':mu.mem_write(r[0],bytes(mu.mem_read(r[1],r[2])));return self.ret(r[0])
            return self.ret(0)
        return super()._hook(mu,a,size,data)
if __name__=='__main__':
    p=T.DNG_DIR/'A001_261_000001.DNG'
    c=Parser(p)
    try:
        print('entry',c.entry({}))
        print('obj',{hex(o):c.w(T.OBJ+o) for o in (0x54,0x58,0x68,0x88,0x98,0x9C,0xA8)})
        print('prepare',C.SelectedCam.prepare(c))
        print('tags',c.tagcalls)
        c.mu.hook_del(c.handle)
        print('check',struct.unpack('<13I',c.mu.mem_read((c.fn('ap_pb_info',T.MEM)&0xffffffff)+720,52)))
    except Exception:
        print('tailcalls',c.calls[-12:]);raise
