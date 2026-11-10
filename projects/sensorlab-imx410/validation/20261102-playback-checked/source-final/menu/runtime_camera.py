"""Declared native UI-service models for the compiled SensorLab menu bridge.

Real loader, client, container and fpui_stock run. Registry and modelCSV
services are Python substitutes; this does not emulate GUI rendering.
"""
import pathlib
import struct
import sys
from unittest.mock import patch
import test_slqs as S
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'apply'))

Q = S.Q1
R = Q.T3
LOOKUP = 0xC05DB418
MODELS = {0xC05E0320:'resource',0xC05D8BD8:'loaded',0xC05D8B78:'load',
          0xC05D8BF8:'instance',0xC05D8358:'interface',0xC05D83A8:'notify',
          0xC05F4860:'count',0xC05F4878:'row',0xC05F4928:'cell',
          0xC05F4940:'insert',0xC05F4958:'delete'}

# v0.7.1test (live v1 item 3 froze on a RES pick): what a change-event callback of the popup list must never reach.
# The event runs inside the stock list's commit action sequence; posts (C0593F30 / C0593FE0) only enqueue and are
# allowed. The apply stubs (test_slqs.AP_STUBS) sit at the firmware addresses, so a commit that gets that far hits them.
EVENT_FORBIDDEN = {0xC005C0B8:'carrier setter', 0xC049EE78:'list recompute', 0xC049EC58:'list manager',
                   0xC0423C48:'LV holder', 0xC0423D28:'LV stop', 0xC0423C88:'LV start', 0xC05E84D8:'NBR load',
                   0xC05E0320:'model resource', 0xC05F4940:'model insert', 0xC05F4958:'model delete',
                   0xC05F4928:'model cell', 0xC05D83A8:'model notify'}

class Cam(Q.Cam):
    def call(self, pc, r0=0, r1=0, r2=0, lr=R.DONE, sp=R.STACK-0x1004, thumb=False):
        # Applying two large menu copies exceeds the base harness's 20M
        # instruction cap. Keep a bounded 100M cap and assert a real return.
        mu=self.mu;mu.reg_write(R.UC_ARM_REG_SP,sp)
        for reg,value in ((R.UC_ARM_REG_R0,r0),(R.UC_ARM_REG_R1,r1),(R.UC_ARM_REG_R2,r2)):
            mu.reg_write(reg,value & 0xFFFFFFFF)
        mu.reg_write(R.UC_ARM_REG_LR,lr)
        S.TC.emu_start(mu,pc | bool(thumb),R.DONE,100_000_000)   # wall-clock cap; SL_EMU_COUNT=1: the counter
        if self.error:raise self.error
        assert self.r(R.UC_ARM_REG_PC)==R.DONE,hex(self.r(R.UC_ARM_REG_PC))
        return self.r(R.UC_ARM_REG_R0),self.r(R.UC_ARM_REG_SP)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mov_format = 0
        self.descriptors = {}; self.model_rows = {1:[],2:[]}; self.row_at = {1:0,2:0}
        self.notices = []; self.next_desc = 0xC3FC1000; self.interface_bad = False
        self.in_event = False; self.event_calls = []
        # This variable belongs to the stock UI registry before the sup loads.
        self.format_descriptor = 0xC3FC0F00
        self.mu.mem_write(0xC3FC0F40, b'MV_RecordingFormat\0')
        self.descriptors['MV_RecordingFormat'] = self.format_descriptor
        for off, value in ((0, 0), (4, 0xC3FC0F40), (8, self.mov_format)):
            self.put(self.format_descriptor + off, value)
        self.registered_names = []
        # C057A448 subscribes the stock format controller to MV_RecordingFormat.
        # C05D9EB8 has one callback slot (+0x18), not a multicast subscriber list.
        self.subs.append((0xC37B7048, 'MV_RecordingFormat', 0xC057A598))
        self.subscription_failures = []
        self.stock_format_calls = 0
        self.page_event_trace = []
        self.put(Q.F6.APP + 0x888, 0xC3FC0000)
        self.iface = 0xC3FC0800
        for off, a in ((0x14,0xC05F4861),(0x18,0xC05F4879),(0x30,0xC05F4929),
                       (0x34,0xC05F4941),(0x38,0xC05F4959)):
            self.put(self.iface + off,a)
        # Preserve the container's existing page entries and add our stock pages.
        pages = ('B2_5','MainB2','Playback')
        old = self.w(Q.F6.READER + 0xAC); count = self.w(Q.F6.READER + 0xA8)
        table, names = 0xC3FB0000, 0xC3FB1000
        self.mu.mem_write(table, bytes(self.mu.mem_read(old, 44 * count)))
        import slm_page as P
        import pb_page as PB
        offsets = {name:P.B.SETS[name][0]-0xC18C0460 for name in pages[:2]}
        offsets['Playback'] = PB.source()[1] - 0xC18C0460
        for i,name in enumerate(pages):
            e = table + (count+i)*44
            self.mu.mem_write(e, bytes(44)); self.mu.mem_write(names+i*32,name.encode()+b'\0')
            self.put(e+4,names+i*32); self.put(e+8,offsets[name])
        self.put(Q.F6.READER+0xA8,count+len(pages));self.put(Q.F6.READER+0xAC,table)

    def _hook(self,mu,addr,size,data):
        r0,r1,r2,r3 = (self.r(getattr(R,'UC_ARM_REG_R'+str(i))) for i in range(4))
        if self.in_event and addr in EVENT_FORBIDDEN:
            self.event_calls.append(EVENT_FORBIDDEN[addr])
        if addr == 0xC005BE90:
            return self._ret(self.mov_format)
        if addr == 0xC057A598:
            # The stock controller's setting/UI services are outside this fixture.
            self.stock_format_calls += 1
            return self._ret(0)
        if addr == Q.F6.VAR_SUBSCRIBE:
            name = self.cstr(r1)
            if any(n == name for _ctx, n, _fn in self.subs):
                self.subscription_failures.append((r0, name, r2, 2))
                return self._ret(0)  # C0560FB0 logs the C05D9EB8 error, without replacing the slot.
        if addr == LOOKUP:
            self.put(r2,self.descriptors.get(self.cstr(r1),0))
            return self._ret(0 if self.w(r2) else 1)
        if addr == Q.F6.VAR_REGISTER:
            for i in range(r1):
                ty,p,v = struct.unpack('<3I',bytes(mu.mem_read(r2+12*i,12)))
                name = self.cstr(p)
                self.registered_names.append(name)
                if name.startswith(('SLM_','EXCL_SLM_')):
                    d=self.next_desc;self.next_desc+=16;self.descriptors[name]=d
                    self.put(d,ty);self.put(d+4,p);self.put(d+8,v)
            return super()._hook(mu,addr,size,data)
        if addr == Q.F6.NBR_LOAD and b'SLM_RES' in bytes(mu.mem_read(r1,r2)):
            self.nbr_calls.append(([r0,r1,r2,r3],self.r(R.UC_ARM_REG_SP),bytes(mu.mem_read(r1,r2))))
            self.put(r3,Q.F6.NEW_RD); return self._ret(0)
        if addr in (Q.F6.POST_INT,Q.F6.POST_STR):
            d=self.descriptors.get(self.cstr(r1))
            if d:self.put(d+8,r2) # queued silent update, never call its subscriber
            return super()._hook(mu,addr,size,data)
        kind=MODELS.get(addr)
        if kind:
            if kind=='resource':
                name=self.cstr(r1);self.put(r2,{'SLM_RES':1,'SLM_FPS':2}.get(name,0));return self._ret(0)
            if kind=='loaded':self.put(r1,1)
            elif kind=='instance':self.put(r1,r0)
            elif kind=='interface':self.put(r1,self.iface if not self.interface_bad else 0)
            elif kind=='count':self.put(r1,len(self.model_rows[r0]))
            elif kind=='row':self.row_at[r0]=r1
            elif kind=='delete':del self.model_rows[r0][r1:r1+r2]
            elif kind=='insert':self.model_rows[r0][r1:r1]=[['']*6 for _ in range(r2)]
            elif kind=='cell':self.model_rows[r0][self.row_at[r0]][r1]=self.cstr(r2)
            elif kind=='notify':self.notices.append((r0,len(self.model_rows[r0])))
            return self._ret(0)
        return super()._hook(mu,addr,size,data)

    def confirm(self,k,value):
        name=('SLM_PickDc','SLM_PickRes','SLM_PickFps')[k]
        d=self.descriptors[name];self.put(d+8,value)
        callbacks=[fn for _ctx,n,fn in self.subs if n==name]
        assert len(callbacks)==1
        fn=callbacks[0];return self.event(fn,d)

    def event(self, fn, d):
        """a variable change callback, as the GUI runs it: inside the page's action sequence (in_event)"""
        self.in_event=True
        try:return self.call(fn & ~1,r0=d,thumb=bool(fn & 1))
        finally:self.in_event=False

    def format_actions(self, page):
        """Read the format forwarding actions from the actually loaded FPUI copy.

        This models the declared page binding, not native GUI event scheduling.
        The page bytes and private string relocations came from the compiled sup.
        """
        import slm_page as P
        p = next(p for p in P.pages() if p.name == page)
        table, count = self.w(Q.F6.READER + 0xAC), self.w(Q.F6.READER + 0xA8)
        entry = next(table + i * 44 for i in range(count) if self.cstr(self.w(table + i * 44 + 4)) == page)
        address = (P.NBU + self.w(entry + 8)) & 0xFFFFFFFF
        records = [r.to_bytes() for r in P.B.N.split(bytes(self.mu.mem_read(address, len(p.assemble()))))]
        def text(value):
            if value < len(p.im.pool):
                return p.im.text(value)
            return self.cstr(value + 0x80000000 if 0x40000000 <= value < 0x80000000 else value)
        owners = [P.u32(r, 20) for r in records if P.u32(r, 0) == 0x10003 and text(P.u32(r, 28)) == 'SLM_FormatEvent']
        if not owners:
            return []
        owner, = owners
        event, = [r for r in records if P.u32(r, 0) == 0x10006 and P.B.owner(r) == owner]
        assert (P.u32(event, 32), text(P.u32(event, 36)), P.u32(event, 41)) == (3, 'MV_RecordingFormat', 3)
        result = []
        for r in records:
            if P.u32(r, 0) == 0x10009 and P.B.owner(r) == owner:
                assert (text(P.u32(r, 8)), P.u32(r, 24), P.u32(r, 32)) == ('controlAppVariable', 1, 0x81)
                result.append((text(P.u32(r, 36)), int(text(P.u32(r, 41)))))
        return result

    def change_format(self, value, page='B2_5'):
        """Stock setter/controller, then the compiled page's forwarding actions."""
        self.mov_format = value
        self.put(self.format_descriptor + 8, value)
        callbacks = [(ctx, fn) for ctx, name, fn in self.subs if name == 'MV_RecordingFormat']
        assert len(callbacks) == 1, callbacks
        ctx, fn = callbacks[0]
        assert ctx == 0xC37B7048, hex(ctx)
        self.event(fn, self.format_descriptor)
        for name, value in self.format_actions(page):
            self.page_event_trace.append((name, value))
            d = self.descriptors[name]
            if self.w(d + 8) == value & 0xFFFFFFFF:
                continue
            self.put(d + 8, value)
            callbacks = [fn for _ctx, n, fn in self.subs if n == name]
            assert len(callbacks) == 1, callbacks
            fn, = callbacks
            self.event(fn, d)


def boot(**kw):
    with patch.object(Q,'Cam',Cam):
        return S.boot(**kw)
