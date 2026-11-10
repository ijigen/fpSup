#!/usr/bin/env python3
"""Native W v2 fallback during repeated crop changes, without a QS leave callback.

Application mode is an explicit fixture (0/1 use fallback, 2/3 use stock movie
branches). No claim of a measured QS runtime state or GUI/DMA timing.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
import unittest
import test_apply as T
import test_lv_fit as L
import test_lv_branches as B
import test_ui_layers as U
from unicorn import arm_const as R

EVIDENCE = []

class UpdateTests(unittest.TestCase):
    def test_fallback_follows_each_selection_without_leave(self):
        for mode in (0, 1):
            c = B.NativeBranches(0, mode=mode)
            for width, height in ((6048,4040),(5088,4040),(6048,3520),(5600,3800),(6048,4040)):
                with self.subTest(mode=mode, crop=(width,height)):
                    # Same declared 2K 11b 3x2 readout as the existing crop-band suite.
                    rw, rh = width//3//16*16, height//3//2*2
                    sel = L.live3_selection(T,width,height,rw,rh)
                    pair = c.select(sel)
                    got = c.frame('yuv',(rw,rh))
                    EVIDENCE.append(dict(mode=mode,crop=[width,height],pair=pair,rectangle=got['rectangle']))
                    self.assertIn(0xC0307408,c.seen)
                    self.assertEqual(got['rectangle'][2:],L.continuous_rectangle(pair))

    def test_hook_preserves_registers_control_state_and_original_stack(self):
        for active in (False, True):
            for skew in (0, 4):
                with self.subTest(active=active, skew=skew):
                    c=T.Cam(src=U.SOURCE)
                    self.assertEqual(c.init(), T.AP_OK)
                    if active: self.assertEqual(c.apply(T.recipe(*T.V1_ARGS)[0]), T.AP_OK)
                    pair=c.call(T.RATIO,9) if active else 0
                    regs=[getattr(R,'UC_ARM_REG_R'+str(i)) for i in range(13)]+[R.UC_ARM_REG_LR]
                    before=[0x11220000+i*0x101 for i in range(14)]
                    for reg,val in zip(regs,before):c.mu.reg_write(reg,val)
                    sp=T.STACK-0x200-skew
                    c.mu.reg_write(R.UC_ARM_REG_SP,sp)
                    c.mu.reg_write(R.UC_ARM_REG_CPSR,0xA00001D3)
                    c.mu.emu_start(0xC0306F28,0xC0306F2C,count=100000)
                    if c.error:raise c.error
                    expected=before[:];expected[1]=pair if active else sp+0x2C
                    self.assertEqual([c.r(reg) for reg in regs],expected)
                    self.assertEqual(c.r(R.UC_ARM_REG_SP),sp)
                    # NZCV is dead here: unconditional MOV/BL enters the native fitter;
                    # its own arithmetic establishes flags before any conditional use.
                    self.assertEqual(c.r(R.UC_ARM_REG_CPSR)&0x0FFFFFFF,0x000001D3)
                    self.assertEqual(c.r(R.UC_ARM_REG_PC),0xC0306F2C)

    def test_fallback_rgb_stays_native(self):
        for mode in (0,1):
            c, stock = B.NativeBranches(0,mode=mode), B.NativeBranches(0,False,mode=mode)
            for shape in ((1024,682),(512,512)):
                for pf in (0,1):
                    with self.subTest(mode=mode,shape=shape,pf=pf):
                        self.assertEqual(c.frame('rgb',shape,pf)['rectangle'],stock.frame('rgb',shape,pf)['rectangle'])

    def test_fallback_inactive_and_playback_stay_native(self):
        for mode in (0,1):
            for state in ('inactive','active','pbc'):
                with self.subTest(mode=mode,state=state):
                    c, stock = B.NativeBranches(0,mode=mode), B.NativeBranches(0,False,mode=mode)
                    c.cam.mu.mem_write(c.aspect,struct.pack('<2I',1,1))
                    if state == 'inactive': c.cam.put(c.cam.off(9),0)
                    else:
                        pb=c.cam.fn('ap_pb_info',T.MEM)
                        offset=4*T.PB_KEYS.index('active') if state=='active' else T.PB_V1_AT+8
                        c.cam.put(pb+offset,1)
                    self.assertEqual(c.frame('yuv')['rectangle'],stock.frame('yuv')['rectangle'])

    def test_fallback_exact_sixteen_nine(self):
        for mode in (0,1):
            with self.subTest(mode=mode):
                c=B.NativeBranches(0,mode=mode)
                c.select(L.live3_selection(T,6048,3402,2016,1134),aspect_enum=3)
                self.assertEqual(c.frame('yuv',(1620,1080))['rectangle'][2:],L.continuous_rectangle((16,9)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();U.SOURCE=args.source
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UpdateTests))
    args.report.write_text(json.dumps(dict(success=result.wasSuccessful(),tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),cases=EVIDENCE,limitations=__doc__),indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
