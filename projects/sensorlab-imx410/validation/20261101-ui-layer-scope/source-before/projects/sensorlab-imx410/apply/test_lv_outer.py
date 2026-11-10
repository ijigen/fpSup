#!/usr/bin/env python3
"""Offline outer display composition and the W71C1 streaming fit dispatch.

All rectangle copying, ratio classification, scaling and fitting execute ROM.
The display metadata getters and W71C1 branch predicates are explicit fixtures;
this is not evidence that these are the camera's actual runtime descriptors.
The two widths are live3's 5008/4800 DC samples, with real 1664/1600 x 1346
record rasters. Product geometry uses a deliberate exact DC-aspect fixture.

Native source provenance (decomp/full/blk_c04.c and blk_c02.c): H_OUT's
C0437E98 descriptor is read through C0438490 by C0436D98, copied into an output
row by C0436538, and converted to display image state by C04382C8/C042B8C8.
C02E5010/C02E7F30 retain that state for C02E8030's streaming submission, which
calls C02F4010 -> C02F3E30, never C02F4098. The external source_rect6 belongs
to C02E4EE0/C02E85C8's image submission, with a separate requested viewport.

Run here with: python3 -B test_lv_outer.py
"""
import json
import struct
import unittest

import test_apply as T
import test_lv_fit as L
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as R

OUTER, DISPATCH, STREAM_SETUP, STREAM_DISPATCH = 0xC02F4098, 0xC02F3ED0, 0xC02F4010, 0xC02F3E30
V2, V3, V4, V5 = 0xC0306DF8, 0xC0306DD8, 0xC0306D90, 0xC03079C8
ROOT = T.WORK + 0x3E0000
ZOOM, BUFFER, SOURCE, INPUT = ROOT, ROOT + 0x100, ROOT + 0x200, ROOT + 0x300
STATE, VTABLE = ROOT + 0x400, 0xC0B54F00

NATIVE = L.NATIVE_RANGES + (
    (0xC02F3E30, 0xC02F3FA0, 'native streaming and outer dispatch'),
    (0xC02F4010, 0xC02F4410, 'metadata load and rectangle move'),
    (0xC02F4810, 0xC02F4910, 'rectangle six-word readers'),
    (0xC02F49D0, 0xC02F4C10, 'rectangle load/store'),
    (0xC02DAFA0, 0xC02DB1D8, 'ratio table and classifier'),
    (0xC0306D40, 0xC0306DF8, 'W71C1 v4 and v3'),
    (0xC0306DF8, 0xC0307280, 'W71C1 v2 and conditional crop'),
    (0xC03079C8, 0xC03079E0, 'W71C1 v5'),
    (0xC00E9B88, 0xC00E9C1C, 'native metadata-to-buffer copy'),
    (0xC00DEC20, 0xC00DEC38, 'metadata type predicate'),
)


class OuterTrace:
    """Real installed product hooks, with strict native arithmetic coverage."""
    def __init__(self, *, product=True):
        self.cam = c = T.Cam()
        if product:
            if c.init() != T.AP_OK or c.apply(T.recipe(*T.V1_ARGS)[0]) != T.AP_OK:
                raise AssertionError('product fixture could not initialize')
            self.aspect = c.call(T.RATIO, 9)
        else:
            self.aspect = None
        self.product = product
        self.trace, self.fixture_calls = [], []
        self.mode, self.canvas = 'v2', (1620, 1080)
        c.mu.reg_write(R.UC_ARM_REG_C1_C0_2, 0xF00000)
        c.mu.reg_write(R.UC_ARM_REG_FPEXC, 0x40000000)
        c.mu.reg_write(R.UC_ARM_REG_FPSCR, 0)
        self.guard = c.mu.hook_add(UC_HOOK_CODE, self._code)
        # Cam initialization already executed product and ratio code. Invalidate
        # translated blocks after installing the strict observer, so no cached
        # block can run without the new execution guard / trace callbacks.
        for lo, hi, _name in NATIVE:
            c.mu.ctl_remove_cache(lo, hi)
        for lo, hi in ((T.BLOB, T.BLOB + len(c.img)), (T.MEM, T.MEM + T.AP_MEM),
                       (T.CAVE_ARENA, T.CAVE_ARENA + 0x1000)):
            c.mu.ctl_remove_cache(lo, hi)

    def _return(self, value):
        self.cam.ret(value)

    def _code(self, mu, address, size, _):
        c = self.cam
        # These return externally selected state, never computed geometry.
        fixtures = {
            0xC00DEA98: ('metadata handle', 1),
            0xC00DE490: ('plane width', self.canvas[0]),
            0xC00DE538: ('plane height', self.canvas[1]),
            0xC00DE5C8: ('canvas width', self.canvas[0]),
            0xC00DE630: ('canvas height', self.canvas[1]),
            0xC00DE6F8: ('plane flags', 0),
            0xC02E9E00: ('physical display aspect enum', 2),
            0xC0307280: ('v2 special 3:2 branch', 0),
            0xC0307408: ('v2 movie fit branch', 1),
            0xC0307520: ('v2 secondary source crop', 0),
            0xC00178D8: ('display state holder', STATE),
            0xC0017AC8: ('display state', STATE),
            0xC0021C00: ('camera state holder', STATE),
            0xC0021C40: ('camera state', STATE),
        }
        if address in fixtures:
            label, value = fixtures[address]
            self.fixture_calls.append(label)
            return self._return(value)
        if address == T.DONE:
            return
        if address in (OUTER, DISPATCH, STREAM_SETUP, STREAM_DISPATCH, V2, V3, V4, V5, L.FIT, L.SNAP_END):
            self.trace.append(dict(pc=f'{address:08X}', rect=self.rectangle()))
        if any(lo <= address and address + size <= hi for lo, hi, _name in NATIVE):
            return
        if self.product and (T.BLOB <= address < T.BLOB + len(c.img) or
                             T.MEM <= address < T.MEM + T.AP_MEM or
                             T.CAVE_ARENA <= address < T.CAVE_ARENA + 0x1000):
            return
        raise AssertionError(f'unapproved outer-chain execution {address:#x}')

    def rectangle(self):
        b = bytes(self.cam.mu.mem_read(BUFFER + 0x78, 12))
        w, h, vw, vh, x, y = struct.unpack('<6H', b)
        return (w, h, x, y, vw, vh)

    def run(self, width, *, route='v2', source_layout='raster', entry='stream', empty_external=False):
        c = self.cam
        self.mode = route
        self.trace, self.fixture_calls = [], []
        # Private object/state memory: all non-fixture predicates read zero.
        c.mu.mem_write(ROOT, bytes(0xB00))
        raster_w = {5008: 1664, 4800: 1600}[width]
        if source_layout == 'raster':
            source = (raster_w, 1346, 0, 0, raster_w, 1346)
        elif source_layout == 'lcd':
            source = (1620, 1080, 0, 0, 1620, 1080)
        else:
            raise ValueError(source_layout)
        # Real, unmodified ROM vtable, including the two ABI metadata words:
        # +10=v2, +14=v3, +18=v4, +1c=v5. Streaming dispatch uses v2/v4;
        # external nonempty-source dispatch uses v3/v5 after its own scaling.
        c.put(INPUT + 8, 1)
        obj = (INPUT, *source, 0 if route == 'v2' else 3, 0, VTABLE)
        c.mu.mem_write(ZOOM, struct.pack('<10I', *obj))
        c.mu.mem_write(SOURCE, struct.pack('<6I', *((0,) * 6 if empty_external else source)))
        if self.aspect is not None:
            c.mu.mem_write(self.aspect, struct.pack('<2I', width, 4040))
        original = bytes(c.mu.mem_read(SOURCE, 24))
        if entry == 'stream':
            c.call(STREAM_SETUP, ZOOM, BUFFER)
        elif entry == 'external':
            c.call(OUTER, ZOOM, BUFFER, SOURCE)
        else:
            raise ValueError(entry)
        moved = self.rectangle()
        if entry == 'stream':
            c.call(STREAM_DISPATCH, ZOOM, BUFFER)
        else:
            c.call(DISPATCH, ZOOM, BUFFER, SOURCE)
        fitted = self.rectangle()
        if bytes(c.mu.mem_read(SOURCE, 24)) != original:
            raise AssertionError('outer chain changed its input rectangle')
        return dict(width=width, route=route, source_layout=source_layout, entry=entry,
                    empty_external=empty_external,
                    source=source, moved=moved, fitted=fitted,
                    expected=L.continuous_rectangle((width, 4040)),
                    trace=list(self.trace), fixtures=sorted(set(self.fixture_calls)))


class OuterCompositionTests(unittest.TestCase):
    def test_product_streaming_chain_keeps_both_widths(self):
        c = OuterTrace()
        for width in (5008, 4800):
            for route in ('v2', 'v4'):
                for layout in ('raster', 'lcd'):
                    with self.subTest(width=width, route=route, layout=layout):
                        r = c.run(width, route=route, source_layout=layout)
                        reached = [step['pc'] for step in r['trace']]
                        self.assertEqual(reached.count(f'{L.FIT:08X}'), 1)
                        self.assertIn(f'{V2 if route == "v2" else V4:08X}', reached)
                        self.assertEqual(r['fitted'][2:], r['expected'], json.dumps(r))

    def test_external_nonempty_source_does_not_fit_twice(self):
        c = OuterTrace(product=False)
        for width in (5008, 4800):
            for route, virtual in (('v2', V3), ('v4', V5)):
                for layout in ('raster', 'lcd'):
                    with self.subTest(width=width, route=route, layout=layout):
                        r = c.run(width, route=route, source_layout=layout, entry='external')
                        self.assertEqual(r['moved'], r['fitted'])
                        reached = [step['pc'] for step in r['trace']]
                        self.assertIn(f'{virtual:08X}', reached)
                        self.assertNotIn(f'{L.FIT:08X}', reached)

    def test_external_empty_source_fits_once_via_streaming_dispatch(self):
        c = OuterTrace()
        for width in (5008, 4800):
            for route in ('v2', 'v4'):
                with self.subTest(width=width, route=route):
                    r = c.run(width, route=route, source_layout='lcd',
                              entry='external', empty_external=True)
                    reached = [step['pc'] for step in r['trace']]
                    self.assertEqual(reached.count(f'{L.FIT:08X}'), 1)
                    self.assertEqual(r['fitted'][2:], r['expected'], json.dumps(r))

    def test_strict_observer_rejects_unknown_native_execution(self):
        c = OuterTrace()
        with self.assertRaisesRegex(AssertionError, 'unapproved outer-chain execution'):
            c.cam.call(0xC02F4670, INPUT)


def report():
    import hashlib
    stock, product = OuterTrace(product=False), OuterTrace()
    cases = []
    for width in (5008, 4800):
        for route in ('v2', 'v4'):
            for layout in ('raster', 'lcd'):
                for name, cam in (('stock', stock), ('product', product)):
                    for entry in ('stream', 'external'):
                        result = cam.run(width, route=route, source_layout=layout, entry=entry)
                        result['variant'] = name
                        cases.append(result)
    return dict(cases=cases, vtable=f'{VTABLE:08X}',
                firmware_sha256=hashlib.sha256(L.image()).hexdigest(),
                product_test_unit_sha256=hashlib.sha256(product.cam.img).hexdigest(),
                source_provenance='C0437E98 -> C0438490 -> C0436D98/C0436538 -> '
                'C04382C8/C042B8C8 -> C02E5010/C02E7F30 -> C02E8030 -> C02F4010/C02F3E30. '
                'External C02E4EE0/C02E85C8 instead uses C02F4098/C02F3ED0.',
                limitations='The streaming and external dispatches, arithmetic and vtable are real ROM. '
                'Metadata dimensions/physical aspect and branch predicates are declared fixtures; '
                'the two raster sources are diagnostic inputs, not captured live descriptors. '
                'No hardware timing, frame ownership or screen composition is proved.')


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--report':
        from pathlib import Path
        Path(sys.argv[2]).write_text(json.dumps(report(), indent=2) + '\n')
        sys.exit(0)
    unittest.main(verbosity=2)
