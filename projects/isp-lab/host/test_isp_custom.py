#!/usr/bin/env python3
"""Offline tests for isp_custom.py.  python3 -B -m unittest test_isp_custom"""
import json, pathlib, sys, tempfile, types, unittest

for _m in ('putfile', 'callfn', 'cave'):          # offline: apply/restore must not reach USB (lv_reload did, 10-28)
    sys.modules.setdefault(_m, types.ModuleType(_m))
import isp_custom as C


class FakeShell:
    def __init__(self, mem):
        self.mem, self.writes = dict(mem), []

    def sh(self, line):
        return 'is_recording -> 0'

    def mem_get(self, a, n=1):
        return [self.mem.get(a + 4 * i, 0) for i in range(n)]

    def mem_set(self, a, v):
        self.writes.append((a, v))
        self.mem[a] = v


class Formula(unittest.TestCase):
    def test_e0_is_the_stock_row(self):
        self.assertEqual(C.plan('E0')['diffs'], [])

    def test_rows_land_in_their_column_and_row(self):
        cols, _ = C.tables()
        for e in ('E2', 'z2048', 'b1x3-z4608x1536'):
            p = C.plan(e)
            self.assertEqual((p['row'], p['profile_id']), (122, 175))
            for a, o, n, off in p['diffs']:
                if off >= 0x1000:                                 # a standby profile word (isp_custom.standby_diffs)
                    continue
                self.assertEqual(a, cols[off] + 4 * 122)

    def test_sizes_follow_the_record_rules(self):
        with self.assertRaises(C.F.NotPossible):                  # v2: horizontal CRCT bin is unusable (R3)
            C.plan('E1')
        self.assertEqual(C.plan('E2')['want']['rec'], (2016, 1138))
        self.assertEqual(C.plan('b1x3-z4608x1536')['want']['rec'], (672, 378))


    def test_parsed_names_match_the_named_ones(self):
        self.assertEqual(C.plan('z1536')['diffs'], C.plan('E2')['diffs'])
        with self.assertRaises(C.F.NotPossible):
            C.plan('b3x3')
        self.assertEqual(C.plan('z2048')['want']['rec'], (1504, 854))
        with self.assertRaises(SystemExit):
            C.plan('q7')


class Install(unittest.TestCase):
    def setUp(self):
        self.p = C.plan('E2')
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.saved = (C.STATE, C._shell, C._flush, C.lv_reload)
        C.STATE = self.tmp / 'state.json'
        C._flush = lambda: None
        C.lv_reload = lambda: None                  # the real one calls the camera through callfn

    def tearDown(self):
        C.STATE, C._shell, C._flush, C.lv_reload = self.saved

    def test_apply_then_restore(self):
        stock = {a: o for a, o, n, off in self.p['diffs']}
        sh = FakeShell(stock)
        C._shell = lambda: sh
        C.apply('E2')
        self.assertEqual({a: sh.mem[a] for a in stock}, {a: n for a, o, n, off in self.p['diffs']})
        C.restore()
        self.assertEqual({a: sh.mem[a] for a in stock}, stock)
        self.assertFalse(C.STATE.exists())

    def test_apply_refuses_a_row_that_is_not_stock(self):
        stock = {a: o for a, o, n, off in self.p['diffs']}
        a0 = next(iter(stock))
        sh = FakeShell({**stock, a0: stock[a0] ^ 1})
        C._shell = lambda: sh
        with self.assertRaises(SystemExit):
            C.apply('E2')
        self.assertEqual(sh.writes, [])
        self.assertFalse(C.STATE.exists())


if __name__ == '__main__':
    unittest.main()
