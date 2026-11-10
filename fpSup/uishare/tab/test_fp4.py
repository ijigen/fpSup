#!/usr/bin/env python3
"""Loader v4's UI data (build_fp4.py, home4_page.py) offline: the pages through
the stock interpreter, every variable a page binds is registered, the routes
through the stock matcher.

    cd fpSup/uishare/tab && python3 -B -m unittest test_fp4
"""
import re
import struct
import unittest
from unittest.mock import patch

import build_fp4 as FP4
import build_ft6 as FT
import ft6_page as F
import home4_page as H
import manage_page as MP

VAR_NAME = re.compile(r'^(FT|SM)_[A-Za-z]+\d*[abc]?$')
NOT_VARS = {'FT_Y6', 'FT_LIST'}


def bound_names(refs):
    return {t for _o, t in refs if VAR_NAME.match(t) and t not in NOT_VARS and not t.startswith('FT_LOGO')}


class Fp4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img, cls.pool = F.stock_pool()
        cls.home = H.build_home(cls.img, cls.pool)
        cls.home_file, cls.home_info = FP4.home_file()
        cls.sm_file, cls.sm_info = FP4.supmgr_file()

    def test_home_through_the_native_interpreter(self):
        page, _refs, row0 = self.home
        shape = F.check_page(page, self.img, self.pool)
        self.assertFalse(F.Lab.duplicate_local_ids(page))
        self.assertEqual(shape['objects'][F.ROWS_PARENT]['child_count'], 1 + H.SLOTS)
        # FT_Row0's first value: slot 0's MainY5 Select, the first of the six rows
        self.assertEqual(shape['objects'][row0]['name'], 'MenuItem_SelectJump_4')
        self.assertEqual(shape['objects'][shape['objects'][row0]['parent_id']]['parent_id'], F.ROWS_PARENT)

    def test_rows_are_hidden_by_a_watcher_not_by_themselves(self):
        """The user 2026-11-10: back from a one-row page, one row was left --
        a row that binds its own is-visible hides and is never told again.
        MainY5's way: an always-visible object's value events change it."""
        manage, _refs, _row0 = MP.build_manage(self.img, self.pool, v4=True)
        for label, page in (('home', self.home[0]), ('SupManager', manage)):
            recs = [bytearray(r.to_bytes()) for r in F.N.split(page)]
            pg = MP.Management(self.img, self.pool)
            text = lambda o: self.pool.text(o) or ''
            parent = {F.u32(r, 20): F.u32(r, 24) for r in recs if F.u32(r, 0) == 0x10003}
            own = [text(F.u32(r, 40)) for r in recs if F.u32(r, 0) == 0x10006
                   and F.pool_name(pg, r) == 'appVariableEvent' and len(r) == 58
                   and text(F.u32(r, 49)) in ('is-visible', 'opacity', 'tab-index')]
            self.assertTrue(own, label)                                     # FT_Title, the tabs ...
            self.assertFalse([n for n in own if 'Visible' in n and 'Tab' not in n], label)
            acts = [r for r in recs if F.u32(r, 0) == 0x10009 and F.pool_name(pg, r) == 'changePropertyByControl'
                    and len(r) in (50, 55) and parent.get(F.u32(r, 20)) == 1 and text(F.u32(r, 45)) == 'is-visible']
            rows = {}
            for a in acts:
                rows.setdefault(F.u32(a, 36), []).append((F.u32(a, 20), len(a)))
            self.assertEqual(len(rows), 6, label)
            for row, hits in rows.items():
                self.assertEqual(parent[row], F.ROWS_PARENT, label)
                self.assertEqual(sorted(n for _o, n in hits), [50, 55], label)      # == 0: hide, == 1: show
                self.assertEqual(len({o for o, _n in hits}), 1, label)
                watcher = [r for r in recs if F.u32(r, 0) != 0x10003 and len(r) >= 28
                           and F.u32(r, 24 if F.u32(r, 0) == 0x10006 else 20) == hits[0][0]]
                value = [r for r in watcher if F.pool_name(pg, r) == 'controlValue']
                self.assertEqual([bytes(r[28:]) for r in value], [struct.pack('>If', 4, 1.0)], label)
                self.assertEqual([len(r) for r in watcher if F.pool_name(pg, r) == 'controlValueEvent'], [40, 44], label)
                self.assertEqual(sum(F.pool_name(pg, r) == 'appVariableEvent' for r in watcher), 1, label)

    def test_menu_leaves_the_menu(self):
        # MENU on FT_Y6 must be MainY5's own exit (48-byte controlAppState, no
        # request): TransFtTab has no Return from FT_Y6 (MENU did nothing, camera).
        page, _refs, _row0 = self.home
        recs = [bytearray(r.to_bytes()) for r in F.N.split(page)]
        pg = MP.Management(self.img, self.pool)
        menus = []
        for i, r in enumerate(recs):
            if F.u32(r, 0) == 0x10006 and F.pool_name(pg, r) == 'keyEvent' and F.u32(r, 16) \
                    and self.pool.text(F.u32(r, 20)) == 'Menu':
                menus.append([recs[j] for j in range(i + 1, i + 1 + F.u32(r, 16))])
        exits = {F.u32(a, 20) for acts in menus for a in acts
                 if F.pool_name(pg, a) == 'controlAppState' and len(a) == 48}
        self.assertLessEqual({3451, self.home[2]}, exits)          # the title row, slot 0
        named = [a for acts in menus for a in acts if F.pool_name(pg, a) == 'controlAppState' and len(a) == 41]
        self.assertEqual(named, [], 'a Return request left on FT_Y6')

    def test_every_bound_variable_is_registered(self):
        home = {n for _t, n, _v in FP4.home_file_vars()}
        self.assertLessEqual(bound_names(self.home[1]), home)
        sm = {n for _t, n, _v in FP4.supmgr_vars()}
        refs = self.sm_info['strings']
        self.assertLessEqual({t for t in refs if t.startswith('SM_')}, sm)
        self.assertFalse({t for t in refs if VAR_NAME.match(t) and t.startswith('FT_')} - NOT_VARS
                         - {t for t in refs if t.startswith('FT_LOGO')}
                         - {FP4.GO_VAR}, 'an FT_ variable left in SupManager')   # the home's, written on entry

    def test_home_vars_match_the_core_indices(self):
        names = [n for _t, n, _v in FP4.home_vars()]
        # fpsup_ui.c: V_KEY .. V_ROW0, then G_* x 6 slots (0..5), then 4 x HOME_TABS
        self.assertEqual(names[:8], ['FT_Key', 'FT_OK', 'FT_PageText', 'FT_Version', 'FT_Focus',
                                     'FT_Title', 'FT_Row0', 'FT_HeadOn'])
        self.assertEqual(names[8:14], [f'FT_N{k}' for k in range(6)])
        self.assertEqual(names[8 + 6 * 8], 'FT_Choice0')
        self.assertEqual(names[8 + 6 * 12:8 + 6 * 15:6], ['FT_Tog0', 'FT_TOff0', 'FT_TOn0'])   # G_TOG..G_TON
        self.assertEqual(len(names), 8 + 15 * 6 + 4 * FP4.HOME_TABS)

    def test_file_header(self):
        for data in (self.home_file, self.sm_file):
            w = struct.unpack_from('<17I', data)                      # fpsup-ui struct fpui_file
            self.assertEqual(w[0], FP4.FT4_MAGIC)
            self.assertEqual(w[16], len(data))
            self.assertEqual(w[1] + w[2], len(data))                 # the page pack last

    def test_routes_through_the_stock_matcher(self):
        pack = FT.build_pack([(FT.PAGE, self.home[0])], machine=FP4.HOME_MACHINE, trans=FT.TRANSITIONS)
        old, FT.SL.MACHINE = FT.SL.MACHINE, FP4.HOME_MACHINE
        try:
            import nbu_probe
            with patch.object(nbu_probe.NbuProbe, 'BLOB_MAX', 0x70000):
                got = FT.SL.native_switch(pack, [(FT.PAGE, 'Menu01'), (FT.PAGE, 'Menu12')])
        finally:
            FT.SL.MACHINE = old
        self.assertEqual(got[(FT.PAGE, 'Menu01')][0], 'MainB1')
        self.assertEqual(got[(FT.PAGE, 'Menu12')][0], 'MainY5')


if __name__ == '__main__':
    unittest.main()
