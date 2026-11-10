#!/usr/bin/env python3
"""Real W v2 branch predicates with declared application/display state inputs.

Allocator, plane dimensions, physical display aspect and state objects are
fixtures. Constructors, kind getters, predicates, branches and fitting run ROM.
No camera I/O. The scene selected by the user's current camera is not known.
"""
import argparse
import json
import struct
from pathlib import Path
import sys
import unittest

import test_apply as T
import test_lv_fit as L
import test_lv_outer as O
import test_ui_layers as U

PREDICATES = ((0xC0307280, 0xC03077C0), (0xC02E9F78, 0xC02EA014))
EVIDENCE = []


class NativeBranches(U.Layers):
    def __init__(self, flag, product=True, mode=2):
        self.flag, self.mode_state, self.seen = flag, mode, set()
        super().__init__(product)
        self.invalidate_predicates()

    def invalidate_predicates(self):
        for lo, hi in PREDICATES:
            self.cam.mu.ctl_remove_cache(lo, hi)

    def select(self, selection, aspect_enum=9):
        result = super().select(selection, aspect_enum)
        self.invalidate_predicates()
        return result

    def _code(self, mu, address, size, data):
        if address in (0xC0307810, 0xC03078E0):
            self.seen.clear()
            self.cam.mu.mem_write(O.ROOT + 0x800, bytes(0x600))
            self.cam.put(O.STATE + 0x1F8, self.mode_state)
            self.cam.put(O.STATE + 0x23C, self.flag)
            self.cam.put(O.ROOT + 0x800 + 0x44, 1)
        if address in (0xC0021C00, 0xC0021C40):
            self.fixture_calls.append('camera state fixture: zero-filled, +44=1')
            return self.cam.ret(O.ROOT + 0x800)
        if any(lo <= address and address + size <= hi for lo, hi in PREDICATES):
            self.seen.add(address)
            return
        return super()._code(mu, address, size, data)


class BranchTests(unittest.TestCase):
    def test_both_native_yuv_branches_keep_custom_eight_fifths(self):
        for flag in (0, 1):
            with self.subTest(state_23c=flag):
                c = NativeBranches(flag)
                result = c.frame('yuv', (2016, 1346))
                EVIDENCE.append(dict(state_23c=flag, result=result))
                self.assertIn(0xC0307280, c.seen)
                self.assertIn(0xC0307680 if flag else 0xC0307408, c.seen)
                self.assertEqual(result['rectangle'][2:], L.continuous_rectangle((8, 5)))

    def test_rgb_ui_stays_native_for_both_states(self):
        for flag in (0, 1):
            current, native = NativeBranches(flag), NativeBranches(flag, False)
            for shape in ((1024, 682), (1620, 1080), (1920, 1080), (512, 512)):
                for pf in (0, 1):
                    with self.subTest(flag=flag, shape=shape, format=pf):
                        got = current.frame('rgb', shape, pf)
                        self.assertEqual(got['rectangle'], native.frame('rgb', shape, pf)['rectangle'])
                        self.assertNotIn(0xC0307280, current.seen)

    def test_inactive_and_playback_keep_native_three_two(self):
        for state in ('inactive', 'active', 'pbc'):
            with self.subTest(state=state):
                c, native = NativeBranches(1), NativeBranches(1, False)
                # A square cannot accidentally pass via the stock 3:2 snap.
                c.cam.mu.mem_write(c.aspect, struct.pack('<2I', 1, 1))
                if state == 'inactive':
                    c.cam.put(c.cam.off(9), 0)
                else:
                    pb = c.cam.fn('ap_pb_info', T.MEM)
                    offset = 4*T.PB_KEYS.index('active') if state == 'active' else T.PB_V1_AT+8
                    c.cam.put(pb+offset, 1)
                self.assertEqual(c.frame('yuv')['rectangle'], native.frame('yuv')['rectangle'])

    def test_true_sixteen_nine_is_not_fitted_as_three_two(self):
        selection = L.live3_selection(T, 6048, 3402, 2016, 1134)
        for flag in (0, 1):
            with self.subTest(state_23c=flag):
                c = NativeBranches(flag)
                c.select(selection, aspect_enum=3)
                self.assertEqual(c.frame('yuv', (2016, 1134))['rectangle'][2:],
                                 L.continuous_rectangle((16, 9)))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    U.SOURCE = args.source
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BranchTests))
    args.report.write_text(json.dumps(dict(success=result.wasSuccessful(), tests=result.testsRun,
        failures=len(result.failures), errors=len(result.errors), cases=EVIDENCE,
        limitations=__doc__), indent=2)+'\n')
    sys.exit(0 if result.wasSuccessful() else 1)
