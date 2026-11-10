"""Real C0528700/SurfacePixel buffer rotation plus the actual SensorLab QR observer.
Only UIC rendering, locks, events, logging, display submission and cache flush are modeled.
No camera access. Run with SL_EMU_COUNT=1.
"""
import struct, unittest
from unittest.mock import patch
from unicorn import arm_const as A
import test_slqs as S

Q = S.Q1
RET0 = {0xC0010298,0xC00102D0,0xC036D7E0,0xC0019DC0,0xC001A0D8,
        0xC0528E18,0xC0528650,0xC0528C28,0xC05286D0,0xC000E91C}

class NativeCam(Q.Cam):
    def __init__(self,*args,**kw):
        self.native = None
        super().__init__(*args,**kw)
    def _hook(self,mu,a,size,data):
        n = self.native
        if n is not None:
            if a in RET0:self._ret(0);return
            if a == 0xC036D888:
                self.put(mu.reg_read(A.UC_ARM_REG_R1)+8,4)  # only group 2 scheduled
                self._ret(1);return
            if a == 0xC06D1948:
                desc = mu.reg_read(A.UC_ARM_REG_R1);base = self.w(desc+4)
                b = (base-n.lcd.FB)//n.lcd.BUF
                n.lcd.uic_record(b,n.mode,n.rect)
                drew = n.mode in (0,2) and n.rect[2]>0 and n.rect[3]>0
                if drew:n.lcd.put_buf(b,n.lcd.G,n.rect)
                self._ret(int(drew));return
            if a == 0xC0721370:n.commits += 1  # real commit + ring routine continue
            if a == 0xC001510C:raise AssertionError('QR requested a full-frame copy')
        return super()._hook(mu,a,size,data)

class NativeDraw:
    def __init__(self):
        with patch.object(Q,'Cam',NativeCam):self.c = S.boot(qr_force=0)
        c = self.c;self.lcd = S.QRScreen(c);c.guid(S.FMT_ID)
        self.commits = 0;self.mode = 0;self.rect = (0,0,0,0)
        L = self.lcd.LAYER
        c.put(L,0xC2EF6280);c.put(L+4,1024);c.put(L+8,682)
        for i in range(3):c.put(L+0x3C+4*i,self.lcd.DESC+0x40*i)
        c.put(L+0x48,self.lcd.DESC);c.put(L+0x4C,self.lcd.DESC+0x40);c.put(L+0x50,0)
        c.put(S.UIC_DRAW_OBJ,0xC0D17780)
        c.mu.mem_write(self.lcd.ARG,bytes(64))
        assert c.w(0xC0D17780+0xC) == 0xC06D1948
        c.native = self
    def front(self):return self.c.w(self.c.w(self.lcd.LAYER+0x48)+4)
    def back(self):return self.c.w(self.c.w(self.lcd.LAYER+0x4C)+4)
    def cycle(self,mode=0,rect=(0,0,0,0)):
        self.mode = mode;self.rect = rect
        self.c.call(0xC0528700,r0=self.lcd.CTRL,r1=self.lcd.ARG,r2=self.lcd.ARG+32)
        return bytes(self.c.mu.mem_read(self.front(),1024*682*2))

class Present(unittest.TestCase):
    def test_native_update_only_does_not_present_stale_qs(self):
        d = NativeDraw();c = d.c
        for _ in range(3):d.cycle(2,(0,0,1024,682))
        front = d.front();picture = bytes(c.mu.mem_read(front,1024*682*2));count = d.commits
        back = d.back();stale = b'\x23\xa1'*(1024*682);c.mu.mem_write(back,stale)
        for _ in range(6):
            shown = d.cycle(1,(0,0,1024,682))
            self.assertEqual(d.front(),front);self.assertEqual(d.commits,count)
            self.assertEqual(shown,picture)
            self.assertEqual(bytes(c.mu.mem_read(back,len(stale))),stale)
        for _ in range(3):self.assertEqual(d.cycle(),picture)
        self.assertEqual(d.commits,count)
        d.cycle(2,(0,0,1024,682));self.assertEqual(d.commits,count+1)
        q = S.qr_info(c);x,y,n = q['x0'],q['y0'],q['side']
        import numpy as np
        f = np.frombuffer(bytes(c.mu.mem_read(d.front(),1024*682*2)),'<u2').reshape(682,1024)
        outside = np.ones(f.shape,bool);outside[y:y+n,x:x+n] = False
        self.assertTrue((f[outside] == d.lcd.G[outside]).all())
        code = np.where(f[y:y+n,x:x+n] == 0xF000,0,255).astype(np.uint8)
        self.assertEqual(S.decode_qr(np.pad(code,20,constant_values=255)),S.QR_URL+c.cstr(S.sqt(c,13),64))

    def test_native_renderer_mode_one_has_empty_output(self):
        c = S.boot();out = S.F6.FAKE+0x9200;rec = out+0x40
        c.mu.mem_write(out,bytes([0xA5])*16)
        c.mu.mem_write(rec,struct.pack('<8I',0,0,0,0,1024,682,1,0))
        c.mu.reg_write(A.UC_ARM_REG_R3,rec)
        c.call(0xC05615E0,r0=out,r1=0,r2=1)
        self.assertEqual(bytes(c.mu.mem_read(out,16)),bytes(16))

    def test_restore_waits_for_native_render(self):
        d = NativeDraw();c = d.c
        for _ in range(3):d.cycle(2,(0,0,1024,682))
        self.assertEqual(S.qr_info(c)['nbuf'],3)
        S.press(c,5,1)                                # native DC submenu hides QR
        self.assertEqual(S.qr_info(c)['on'],0)
        front = d.front();count = d.commits
        before = bytes(c.mu.mem_read(d.back(),1024*682*2))
        d.cycle(1,(0,77,1024,454))
        self.assertEqual((d.front(),d.commits),(front,count))
        self.assertEqual(bytes(c.mu.mem_read(d.back(),len(before))),before)
        self.assertEqual(S.qr_info(c)['nbuf'],3)
        for _ in range(3):self.assertEqual(d.cycle(2,(0,0,1024,682)),d.lcd.G.tobytes())
        self.assertEqual(S.qr_info(c)['nbuf'],0)

if __name__ == '__main__':unittest.main()
