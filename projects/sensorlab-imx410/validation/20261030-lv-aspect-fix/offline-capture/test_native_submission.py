#!/usr/bin/env python3
"""Offline-only fit -> native display submission packet characterization.

The C00E9C20 packet producer executes ROM, stopping at C00DF428 before driver
or hardware writes. It is called directly after the streaming-fit descriptor
is made; the queue/observer chain is not executed. Metadata dimensions, source
buffer and display state are declared fixtures. This proves packet geometry,
not actual consumer selection, LCD scanout or CAPTURE.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest

SL = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SL/'apply'))
import test_apply as T
import test_lv_fit as L
import test_lv_outer as O
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm_const as R

PACK, DRIVER = 0xC00E9C20, 0xC00DF428
PACK_END = 0xC00E9F70
PACK_RANGES = ((PACK,PACK_END),(0xC00E1EE0,0xC00E1F90),(0xC00E2290,0xC00E22A0))
CASES = ((6048,4040,2016,1346), (6048,3800,2016,1266),
         (6048,3500,2016,1166), (5088,4040,1696,1346),
         (5008,4040,1664,1346), (4800,4040,1600,1346))


class Submission(O.OuterTrace):
    def __init__(self):
        self.packet = None
        self.pack_addresses = set()
        self.round_pack_addresses = set()
        self.reached_driver = False
        super().__init__()
        c = self.cam
        # Explicitly select the normal submission branch and disable the
        # alternate live hardware state; ROM/BSS defaults are not runtime data.
        c.mu.mem_write(0xC2EFCE1C, bytes(6))
        c.put(0xC2EFC458, 0)
        for lo,hi in PACK_RANGES:
            c.mu.ctl_remove_cache(lo,hi)

    def _code(self, mu, address, size, _):
        c = self.cam
        if address == 0xC0015058:
            # Non-geometric memset, with its entire declared effect checked.
            dst, val, n = [c.r(x) for x in (R.UC_ARM_REG_R0,R.UC_ARM_REG_R1,R.UC_ARM_REG_R2)]
            assert n==0xAC and val==0 and T.STACK-0x10000 <= dst < T.STACK
            mu.mem_write(dst, bytes(n))
            self.fixture_calls.append('zero packet memory')
            return c.ret(dst)
        if address == DRIVER:
            self.reached_driver = True
            ptr=c.r(R.UC_ARM_REG_R0)
            assert T.STACK-0x10000 <= ptr and ptr+0xAC < T.STACK
            self.packet=bytes(mu.mem_read(ptr,0xAC))
            self.fixture_calls.append('stop before display driver; return success')
            return c.ret(0)
        if any(lo<=address and address+size<=hi for lo,hi in PACK_RANGES):
            self.pack_addresses.add(address)
            self.round_pack_addresses.add(address)
            return
        super()._code(mu,address,size,_)

    def submit(self, dcw,dch,rw,rh, *, layer=0, origin_control=False):
        c=self.cam
        sel=T.recipe(dcw,dch,rw,rh,'3x2',11,fps=T.Fraction(72000000,3784294))[0]
        # Selection preparation uses the established apply harness with its
        # explicit hardware fixtures, before the strict display trace begins.
        c.mu.hook_del(self.guard)
        try:
            self.assert_apply(c.apply(sel))
            assert c.status()['active']==1
            self.aspect=c.call(T.RATIO,9)
        finally:
            self.guard=c.mu.hook_add(UC_HOOK_CODE,self._code)
        for lo,hi,_ in O.NATIVE:
            c.mu.ctl_remove_cache(lo,hi)
        for lo,hi in PACK_RANGES:
            c.mu.ctl_remove_cache(lo,hi)
        for lo,hi in ((T.BLOB,T.BLOB+len(c.img)),(T.MEM,T.MEM+T.AP_MEM),
                      (T.CAVE_ARENA,T.CAVE_ARENA+0x1000)):
            c.mu.ctl_remove_cache(lo,hi)
        pair=struct.unpack('<2I',c.mu.mem_read(self.aspect,8))
        self.canvas=(1620,1080)
        c.mu.mem_write(O.ROOT,bytes(0xB00))
        c.put(O.INPUT+8,1)
        c.mu.mem_write(O.ZOOM,struct.pack('<10I',O.INPUT,rw,rh,0,0,rw,rh,3,0,O.VTABLE))
        c.call(O.STREAM_SETUP,O.ZOOM,O.BUFFER)
        c.call(O.STREAM_DISPATCH,O.ZOOM,O.BUFFER)
        fitted=self.rectangle()
        # Fixture: one plane, explicit layer ID and framebuffer address. The
        # source/destination geometry is kept from the native streaming path.
        c.put(O.BUFFER,layer)
        c.put(O.BUFFER+4,1)
        c.put(O.BUFFER+8,0x45001000)
        c.put(O.BUFFER+0x70,1)
        before=bytes(c.mu.mem_read(O.BUFFER,0x9C))
        if origin_control:
            # An isolated control proves the packet assertion detects lost
            # offsets; no product source or saved BIN is changed.
            c.mu.mem_write(O.BUFFER+0x80,bytes(4))
        def write_guard(mu,access,address,size,value,data):
            if not T.STACK-0x10000 <= address or address+size > T.STACK:
                raise AssertionError(f'packet producer wrote outside private stack: {address:#x}')
        h=c.mu.hook_add(UC_HOOK_MEM_WRITE,write_guard)
        try:
            self.packet=None
            self.round_pack_addresses=set()
            self.reached_driver=False
            saved={getattr(R,'UC_ARM_REG_R'+str(n)):c.r(getattr(R,'UC_ARM_REG_R'+str(n))) for n in range(4,12)}
            rc=c.call(PACK,O.BUFFER,thumb=True,sp=T.STACK-0x1000)
            assert c.r(R.UC_ARM_REG_SP)==T.STACK-0x1000,'packet producer did not restore SP'
            assert all(c.r(k)==v for k,v in saved.items()),'packet producer damaged callee-saved register'
        finally:
            c.mu.hook_del(h)
        assert rc==0 and self.packet is not None and self.reached_driver
        assert PACK in self.round_pack_addresses,'this case bypassed strict native packet observation'
        after=bytes(c.mu.mem_read(O.BUFFER,0x9C))
        if not origin_control: assert before==after,'packet producer modified its input descriptor'
        p=self.packet
        return {'dc':[dcw,dch],'raster':[rw,rh],'pair':pair,'layer':layer,
                'fitted':fitted,'source6':struct.unpack_from('<6H',p,0x64),
                'destination6':struct.unpack_from('<6H',p,0x76),
                'buffer0':struct.unpack_from('<I',p)[0],
                'driver_layer':p[0x83], 'pixel_format':p[0x84],
                'expected':L.continuous_rectangle(pair),
                'packet_sha256':hashlib.sha256(p).hexdigest(),
                'native_pack_instructions_observed':len(self.round_pack_addresses),
                'origin_control':origin_control}

    @staticmethod
    def assert_apply(rc):
        assert rc in (T.AP_OK,T.AP_IDLE),rc


class SubmissionTests(unittest.TestCase):
    def test_six_fit_geometries_preserved_for_two_packet_layer_ids(self):
        c=Submission()
        for case in CASES:
            for layer in (0,3):
                with self.subTest(case=case,layer=layer):
                    r=c.submit(*case,layer=layer)
                    x,y,w,h=r['expected']
                    self.assertEqual(r['destination6'],(1620,1080,w,h,x,y),r)
                    self.assertEqual(r['source6'],(case[2],case[3],case[2],case[3],0,0),r)
                    self.assertEqual(r['driver_layer'],layer)
                    self.assertEqual(r['buffer0'],(0x45001000+0xC0000000 & 0xFFFFFFFF)>>2)

    def test_isolated_lost_origin_control_changes_native_packet(self):
        c=Submission()
        r=c.submit(*CASES[1],origin_control=True)
        x,y,w,h=r['expected']
        self.assertGreater(y,0)
        self.assertNotEqual(r['destination6'],(1620,1080,w,h,x,y))
        self.assertEqual(r['destination6'][-2:],(0,0))

    def test_unknown_driver_execution_is_refused(self):
        c=Submission()
        with self.assertRaisesRegex(AssertionError,'unapproved outer-chain execution'):
            c.cam.call(DRIVER+4)


def report(path):
    c=Submission();cases=[c.submit(*v,layer=l) for v in CASES for l in (0,3)]
    data={'firmware_sha256':hashlib.sha256(L.image()).hexdigest(),
          'product_unit_sha256':hashlib.sha256(c.cam.img).hexdigest(),
          'cases':cases,'native_packet_producer':hex(PACK),'stop_before':hex(DRIVER),
          'executed_pack_addresses':sorted(hex(v) for v in c.pack_addresses),
          'execution_boundary':'Native streaming fit, then direct packet producer call; no queue or observers.',
          'case_count_meaning':'Six fit geometries times two packet-layer IDs; layer assigned after fit.',
          'limitations':['Synthetic metadata/source/layer fixtures, not captured live descriptors.',
                         'Source geometry is seeded in the zoom object, not obtained from a live H_OUT descriptor.',
                         'Display driver, MMIO, scheduling, physical LCD and CAPTURE do not execute.',
                         'A passing packet does not establish which descriptor the camera selected.']}
    Path(path).write_text(json.dumps(data,indent=2)+'\n')


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--report':report(sys.argv[2])
    else:unittest.main(verbosity=2)
