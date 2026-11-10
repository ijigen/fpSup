#!/usr/bin/env python3
"""High-rate canvas contract through native configuration and descriptor code.

The report is an offline data-flow check, not a simulation of a sustained
recording. Sensor/DMA/RTOS timing and the user's freeze remain hardware tests.
The S16 0.3K preset is 336x206; the user's exact recipe was not supplied.
"""
import argparse
import dataclasses
import json
import struct
import unittest
from fractions import Fraction
from pathlib import Path

import test_apply as T

SOURCE = None
EVIDENCE = []
CANVAS, HOLDER, CFG, FRAME = (T.WORK + x for x in (0xA000, 0xA200, 0xA400, 0xA800))


class Native(T.Cam):
    # Camera services and two unrelated descriptor inputs are stubbed explicitly.
    # The field under test is never supplied by a stub; it is copied by ROM.
    SERVICES = {0xC00178D8: 'state_init', 0xC0017AC8: 'state', 0xC032C900: 'sensor_meta',
                0xC01259C0: 'sensor_mmio_flag', 0xC01D7948: 'unrelated_queue_flag'}
    RANGES = ((0xC0434EF8, 0xC0435428), (0xC01D1630, 0xC01D1958),
              (0xC01D8638, 0xC01D8650), (0xC01CABA0, 0xC01CABF0),
              (0xC01D0640, 0xC01D0660), (0xC01D3CB0, 0xC01D3CD0),
              (0xC01D7CE8, 0xC01D7D70), (0xC01D3558, 0xC01D3580),
              (0xC01D3B10, 0xC01D3B30), (0xC01D3DD8, 0xC01D3E00),
              (0xC01259C0, 0xC01259D8), (0xC01D7948, 0xC01D7970))

    def _hook(self, mu, a, size, data):
        if a in self.SERVICES:
            return self.ret(T.WORK + 0xB000 if self.SERVICES[a] == 'state' else 0)
        return super()._hook(mu, a, size, data)

    def guard(self, mu, a, size, data):
        if a in self.SERVICES or a == T.DONE or any(lo <= a < hi for lo, hi in self.RANGES):
            return
        raise AssertionError(f'unmodeled native instruction {a:08x}')

    def prefix(self, start, end, *args):
        self.mu.reg_write(T.UC_ARM_REG_SP, T.STACK - 0x1004)
        for r, v in zip((T.UC_ARM_REG_R0, T.UC_ARM_REG_R1), args):
            self.mu.reg_write(r, v)
        self.mu.emu_start(start | 1, end, count=20000)
        assert self.r(T.UC_ARM_REG_PC) == end

    def native_fields(self, words):
        self.mu.reg_write(T.UC_ARM_REG_FPEXC, 0x40000000)
        for a, n in self.SERVICES.items():
            self.stub(a, n)
        self.mu.mem_write(CANVAS, struct.pack('<67I', *words))
        self.put(HOLDER + 4, CANVAS)
        h = self.mu.hook_add(T.UC_HOOK_CODE, self.guard)
        try:
            self.call(0xC0434EF8, HOLDER, CFG)
            # Execute initialization through the B0 store, before hardware work.
            self.prefix(0xC01D1630, 0xC01D1958, 0, CFG)
            # This classification call normally appears later in initialization.
            self.call(0xC01D7CE8, self.w(CFG + 0x88), self.w(CFG + 0x14), 0, thumb=True)
            self.prefix(0xC01CABA0, 0xC01CABF0, 0, FRAME)
            return [words[0xB0 // 4], self.w(CFG + 0x14),
                    self.w(0xC31DF578), self.w(FRAME + 0xC)]
        finally:
            self.mu.hook_del(h)


def cell_of(merge):
    """S16 336 x 206 (the high-rate cell); 3x6 there has no vertical margin since 0.0.5test (not offered), so it
    takes HD 1008 x 566: 3x6 reads the full height either way (the same rates)"""
    return (6048, 3402, 1008, 566) if merge == '3x6' else (2096, 1240, 336, 206)


class HighRatePreview(unittest.TestCase):
    def apply(self, fps, merge='3x6', ad=12):
        cam = Native(SOURCE)
        self.assertEqual(cam.init(), T.AP_OK)
        sel, _, _, _, spec = T.recipe(*cell_of(merge), merge, ad, fps=Fraction(fps))
        self.assertEqual(cam.apply(sel), T.AP_OK, cam.status())
        return cam, sel, spec

    def test_native_carriers_and_custom_rates_carry_the_high_rate_field(self):
        # Native 100/120 use engine 50/60, so testing engine >99 is wrong.
        for fps, want in ((30, 0), (Fraction(60000, 1001), 0), (60, 1), (72, 1), (100, 1),
                          (Fraction(120000, 1001), 1), (120, 1), (144, 1), (200, 1),
                          (Fraction(240000, 1001), 1)):
            with self.subTest(fps=str(fps)):
                cam, sel, spec = self.apply(fps)
                words = cam.canvas(cam.status()['pid'])
                fields = cam.native_fields(words)
                EVIDENCE.append(dict(requested_fps=str(fps), actual_fps=T.CLK/(sel['hm']*sel['vmax']),
                                     carrier=cam.fr, engine=struct.unpack('<f', struct.pack('<I', words[12]))[0],
                                     canvas_cfg_state_frame=fields))
                self.assertEqual(fields, [want] * 4)

    def test_native_stock_100_120_reference_has_one_and_30_60_have_zero(self):
        for key, want in (('FHD30', 0), ('FHD60', 0), ('FHD100', 1), ('FHD120', 1)):
            cam = Native()
            entry = cam.call(T.PICKER, 0, T.TAB3, cam.key(key))
            words = cam.canvas(cam.w(entry + 4))
            fields = cam.native_fields(words)
            EVIDENCE.append(dict(native_stock_key=key, canvas_cfg_state_frame=fields))
            self.assertEqual(fields, [want] * 4, key)

    def test_canvas_words_follow_the_shared_formula(self):
        for merge in ('2x3', '3x2', '1x2', '1x3', '2x2', '3x3', '3x6'):
            with self.subTest(merge=merge):
                cam, sel, spec = self.apply(200, merge)
                words = cam.canvas(cam.status()['pid'])
                want = T.F.row(dataclasses.replace(spec, record_preview=True), T.profile_rows()[171])
                want[0x30 // 4] = T.f32(T.CLK/(sel['hm']*sel['vmax']))
                # The Python model includes the explicit preview policy; B0 is
                # independently checked against native high-rate carriers.
                diff = {4*i for i in range(65) if words[i] != want[i]}
                self.assertEqual(diff, {0xB0})
                self.assertEqual(words[0xB0 // 4], 1)

    def test_standby_stock_and_deactivation_do_not_inherit_high_rate_field(self):
        cam, sel, _ = self.apply(200)
        pid = cam.status()['pid']
        self.assertEqual(cam.canvas(pid + 2)[0xB0 // 4], T.profile_rows()[5][0xB0 // 4])
        ref = T.Cam()
        for p in (83, 175, 178, 179):
            self.assertEqual(cam.canvas(p), ref.canvas(p))
        self.assertEqual(cam.apply(sel, valid=0), T.AP_OK)
        self.assertEqual(cam.canvas(175), ref.canvas(175))
        self.assertEqual(cam.w(T.CLK_SITE), T.CLK_STOCK)

    def test_return_to_low_rate_clears_the_field(self):
        cam, _, _ = self.apply(200)
        self.assertEqual(cam.canvas(cam.status()['pid'])[0xB0 // 4], 1)
        low = T.recipe(*cell_of('3x6'), '3x6', 12, fps=Fraction(25))[0]
        self.assertEqual(cam.apply(low), T.AP_OK)
        self.assertEqual(cam.native_fields(cam.canvas(cam.status()['pid'])), [0] * 4)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path)
    p.add_argument('--report', type=Path)
    args = p.parse_args()
    SOURCE = args.source
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HighRatePreview))
    if args.report:
        args.report.write_text(json.dumps(dict(passed=result.wasSuccessful(), tests=result.testsRun,
                                              failures=len(result.failures), errors=len(result.errors),
                                              evidence=EVIDENCE, hardware_verified=False), indent=2)+'\n')
    raise SystemExit(not result.wasSuccessful())
