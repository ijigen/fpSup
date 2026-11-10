#!/usr/bin/env python3
"""Real ROM RGB/YUV constructors and dispatch; no camera, DMA or GUI rasterizer.

The application view's pixel-format constructor selects the native W v4
bitmap path. Preserve its original fit while the SensorLab YUV crop is active.
Allocator/display metadata and branch predicates are explicit fixtures.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_apply as T
import test_lv_fit as L
import test_lv_outer as O
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm_const as R

EXTRA = ((0xC0307810, 0xC0307948, 'native W constructor wrappers'),
         (0xC0307E08, 0xC0307EF8, 'native W constructor implementations'),
         (0xC02F3CB0, 0xC02F3E30, 'native rectangle/bitmap zoom construction'),
         (0xC02F4670, 0xC02F4910, 'native source kind and rectangle conversion'))
SOURCE = None
EVIDENCE = []


class Layers(O.OuterTrace):
    def __init__(self, product=True):
        self.cam = c = T.Cam(src=SOURCE)
        self.product, self.aspect = product, None
        if product:
            assert c.init() == T.AP_OK
            assert c.apply(T.recipe(*T.V1_ARGS)[0]) == T.AP_OK
            self.aspect = c.call(T.RATIO, 9)
            c.mu.mem_write(self.aspect, struct.pack('<2I', 8, 5))
        self.trace, self.fixture_calls = [], []
        self.mode, self.canvas = 'v2', (1620, 1080)
        c.mu.reg_write(R.UC_ARM_REG_C1_C0_2, 0xF00000)
        c.mu.reg_write(R.UC_ARM_REG_FPEXC, 0x40000000)
        c.mu.reg_write(R.UC_ARM_REG_FPSCR, 0)
        self.guard = c.mu.hook_add(UC_HOOK_CODE, self._code)
        for lo, hi, _ in O.NATIVE + EXTRA:
            c.mu.ctl_remove_cache(lo, hi)
        for lo, hi in ((T.BLOB, T.BLOB+len(c.img)),
                       (T.MEM, T.MEM+T.AP_MEM),
                       (T.CAVE_ARENA, T.CAVE_ARENA+0x1000)):
            c.mu.ctl_remove_cache(lo, hi)

    def select(self, selection, aspect_enum=9):
        c = self.cam
        c.mu.hook_del(self.guard)
        try:
            assert c.apply(selection) in (T.AP_OK, T.AP_IDLE)
            self.aspect = c.call(T.RATIO, aspect_enum)
            pair = L.words(c.mu, self.aspect, 2)
        finally:
            self.guard = c.mu.hook_add(UC_HOOK_CODE, self._code)
        for lo, hi, _ in O.NATIVE + EXTRA:
            c.mu.ctl_remove_cache(lo, hi)
        for lo, hi in ((T.BLOB, T.BLOB+len(c.img)), (T.MEM, T.MEM+T.AP_MEM),
                       (T.CAVE_ARENA, T.CAVE_ARENA+0x1000)):
            c.mu.ctl_remove_cache(lo, hi)
        return pair

    def _code(self, mu, address, size, data):
        if address == 0xC0307F48:
            assert self.cam.r(R.UC_ARM_REG_R0) == 0x28
            self.fixture_calls.append('allocator: private zoom object')
            return self.cam.ret(O.ZOOM)
        if any(lo <= address and address+size <= hi for lo,hi,_ in EXTRA):
            return
        super()._code(mu, address, size, data)

    def frame(self, kind, shape=(1024, 682), pixel_format=0):
        c = self.cam
        self.trace, self.fixture_calls = [], []
        c.mu.mem_write(O.ROOT, bytes(0xB00))
        c.put(O.INPUT+8, 1)
        holder, desc, scale = O.ROOT+0x600, O.ROOT+0x700, O.ROOT+0x780
        w,h = shape
        source = (w,h,0,0,w,h,0,0,pixel_format,0,0)
        c.mu.mem_write(desc, struct.pack('<11I', *source))
        c.mu.mem_write(scale, struct.pack('<2I',1,1))
        original = bytes(c.mu.mem_read(desc,44))
        def write_guard(mu, access, addr, size, value, data):
            if (O.ROOT <= addr and addr+size <= O.ROOT+0xB00 or
                    T.STACK-0x10000 <= addr and addr+size <= T.STACK):
                return
            raise AssertionError(f'non-private display write: {addr:#x}')
        handle = c.mu.hook_add(UC_HOOK_MEM_WRITE, write_guard)
        try:
            entry = 0xC03078E0 if kind == 'rgb' else 0xC0307810
            c.call(entry,holder,O.INPUT,desc,scale)
            assert c.w(holder) == O.ZOOM
            obj = struct.unpack('<10I', c.mu.mem_read(O.ZOOM,40))
            assert obj[9] == O.VTABLE
            expected_kind = (4 if pixel_format==0 else 3) if kind=='rgb' else 0
            assert obj[7] == expected_kind, obj
            c.call(O.STREAM_SETUP,O.ZOOM,O.BUFFER)
            c.call(O.STREAM_DISPATCH,O.ZOOM,O.BUFFER)
        finally:
            c.mu.hook_del(handle)
        assert bytes(c.mu.mem_read(desc,44)) == original
        reached = [x['pc'] for x in self.trace]
        target = O.V4 if kind=='rgb' else O.V2
        assert f'{target:08X}' in reached
        assert reached.count(f'{L.FIT:08X}') == 1
        return dict(kind=kind,source=shape,pixel_format=pixel_format,
                    native_kind=obj[7],rectangle=self.rectangle(),
                    trace=self.trace,fixtures=sorted(set(self.fixture_calls)))


class UIIsolation(unittest.TestCase):
    def test_rgb_bitmap_fit_is_native_while_custom_live_is_active(self):
        current, native = Layers(), Layers(False)
        for shape in ((1024,682),(1620,1080),(1920,1080),(512,512)):
            for pixel_format in (0,1):
                with self.subTest(shape=shape,pixel_format=pixel_format):
                    got=current.frame('rgb',shape,pixel_format)
                    stock=native.frame('rgb',shape,pixel_format)
                    EVIDENCE.append(dict(product=got,native=stock))
                    self.assertEqual(got['rectangle'],stock['rectangle'],
                                     'custom sensor aspect must not resize the RGB/UI layer')

    def test_yuv_live_fit_retains_custom_aspect(self):
        current,native=Layers(),Layers(False)
        got=current.frame('yuv',(2016,1346))
        stock=native.frame('yuv',(2016,1346))
        self.assertEqual(got['rectangle'][2:],L.continuous_rectangle((8,5)))
        self.assertNotEqual(got['rectangle'],stock['rectangle'])
        EVIDENCE.append(dict(product=got,native=stock))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();SOURCE=args.source
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(UIIsolation)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    args.report.write_text(json.dumps(dict(
        result='PASS' if result.wasSuccessful() else 'FAIL',
        tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        product_source=str(SOURCE or T.HERE),
        product_source_sha256=hashlib.sha256(((SOURCE or T.HERE)/'ap.c').read_bytes()).hexdigest(),
        native_gui_provenance='C02E8730 -> C03078E0 -> C0307EA8 -> C02F3DC8 -> C02F3E30 -> W v4',
        native_live_provenance='C02E8030 -> C0307810 -> C0307E08 -> C02F3D10 -> C02F3E30 -> W v2',
        limitations='Allocator/display metadata/UI predicates are explicit fixtures. No GUI drawing, queue, DMA, LCD or camera executes.',
        cases=EVIDENCE),indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
