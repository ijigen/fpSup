#!/usr/bin/env python3
"""fpSup management pages offline, and the fake UI app the loader
tests (fp_usb_shell/v3/test_allsups.py) run Loader v3's built-in page against:
the stock NBR loader C05E84D8, the variable registry, subscription, the GUI's
post queue and the file rename are Python; the rest of the image is real.
The pack goes through the stock interpreter and matcher (sl_pages
native_switch).

    python3 -B fpSup/uishare/tab/test_ft6.py
"""
import struct
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_ft6 as F                                           # noqa: E402 (sets sys.path)
sys.path.insert(0, str(F.ROOT / 'fpSup/fp_usb_shell/v3'))
import test_v3 as T                                             # noqa: E402
import nbu_format as _N                                         # noqa: E402

GUI_OBJECT, NBR_LOAD, SITE = 0xC37B7048, 0xC05E84D8, 0xC056461C
FAKE = 0xC3F00000                       # the fake UI app and its vectors
APP, SCREENS, SCREEN0, READER, MACHS, NAMES, NEW_RD = (FAKE + o for o in (
    0x0, 0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000))
GROUP, LANG_RES = FAKE + 0x7000, FAKE + 0x7800     # [APP+0x888], the language resource [GROUP+0x5C]
STOCK_MACHINES = 17
_img, _base, _rows, (POOL_AT, POOL_LEN) = _N.load_sets()
VAR_REGISTER, VAR_SUBSCRIBE, POST_INT, POST_STR, F_RENAME = (
    0xC05DB308, 0xC0560FB0, 0xC0593F30, 0xC0593FE0, 0xC0366508)
LANG_STALE = 0xC05DE6B0                 # stock: mark the language stale (texts bound again on the GUI pass)
UI_BUSY, LANG_APPLY = 0xC05DCCB8, 0xC05DE5B8   # stock: a GUI pass is running / translate the stale texts now
SLEEP_MS = 0xC01F89C4                   # stock tk_dly_tsk(ms)


class Cam(T.Camera):
    def __init__(self, files, dirs, nbr_result=0, new_name=F.MACHINE, grow=1, write_ok=True,
                 machine_capacity=24):
        super().__init__(files, dirs)
        self.nbr_result, self.new_name, self.grow, self.write_ok = nbr_result, new_name, grow, write_ok
        self.nbr_calls, self.vars, self.subs, self.posts, self.renames = [], {}, [], [], []
        self.mu.mem_write(NBR_LOAD, struct.pack('<H', 0x4770))     # Thumb bx lr
        self.mu.mem_write(VAR_REGISTER, struct.pack('<H', 0x4770))
        for a in (LANG_STALE, UI_BUSY, LANG_APPLY):
            self.mu.mem_write(a, struct.pack('<H', 0x4770))
        self.lang_stale, self.lang_apply = [], []                  # (app, pack loads so far)
        self.ui_busy = getattr(self, 'ui_busy', 0)                 # sleeps until the GUI is idle again
        self.sleeps = []
        self.mu.mem_write(SLEEP_MS, struct.pack('<I', 0xE12FFF1E))   # ARM bx lr
        for a in (VAR_SUBSCRIBE, POST_INT, POST_STR, F_RENAME):
            self.mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))   # ARM bx lr
        self.put(GUI_OBJECT, APP)
        self.put(APP + 0x888, GROUP)
        self.put(GROUP + 0x5C, LANG_RES)
        self.gui_trace = []                             # 'busy?', 'sleep', 'load', 'stale', 'apply' in order
        self.put(APP + 0x80, 221)
        self.put(APP + 0x84, 224)
        self.put(APP + 0x8C, SCREENS)
        self.put(SCREENS, SCREEN0)
        self.put(SCREEN0 + 0x24, READER)
        self.put(READER + 0x08, APP)
        self.put(READER + 0x10, POOL_LEN)
        self.put(READER + 0x14, POOL_AT)
        self.put(READER + 0x24, 0xC18C0460)
        self.put(APP + 0xF8, STOCK_MACHINES)
        self.put(APP + 0xFC, machine_capacity)
        self.put(APP + 0x104, MACHS)
        for i in range(STOCK_MACHINES + 1):
            m = FAKE + 0x8000 + 0x40 * i
            name = f'Stock{i}' if i < STOCK_MACHINES else self.new_name
            self.mu.mem_write(NAMES + 0x20 * i, name.encode() + b'\0')
            self.put(m + 8, NAMES + 0x20 * i)
            if i < STOCK_MACHINES:
                self.put(MACHS + 4 * i, m)
        self.new_machine = FAKE + 0x8000 + 0x40 * STOCK_MACHINES

    def _hook(self, mu, addr, size, data):
        r0, r1, r2, r3 = (self.r(x) for x in (T.UC_ARM_REG_R0, T.UC_ARM_REG_R1,
                                               T.UC_ARM_REG_R2, T.UC_ARM_REG_R3))
        if addr == SLEEP_MS:
            self.sleeps.append(r0)
            self.gui_trace.append('sleep')
            self.ui_busy = max(0, self.ui_busy - 1)
            return self._ret(0)
        if addr == LANG_STALE:
            self.gui_trace.append('stale')
            self.lang_stale.append((r0, len(self.nbr_calls)))
            return self._ret(0)
        if addr == UI_BUSY:
            return self._ret(1 if self.ui_busy else 0)
        if addr == LANG_APPLY:
            self.gui_trace.append('apply')
            self.lang_apply.append((r0, len(self.nbr_calls), len(self.lang_stale)))
            self.texts_bound = True
            return self._ret(0)
        if addr == VAR_REGISTER:
            for i in range(r1):
                ty, name, first = struct.unpack('<3I', bytes(mu.mem_read(r2 + 12 * i, 12)))
                self.vars[self.cstr(name)] = (ty, self.cstr(first, 256) if ty == 2 else first)
            return self._ret(0)
        if addr == VAR_SUBSCRIBE:
            self.subs.append((r0, self.cstr(r1), r2))
            return self._ret(0)
        if addr in (POST_INT, POST_STR):
            name = self.cstr(r1)
            value = self.cstr(r2, 256) if addr == POST_STR else r2
            self.posts.append((name, value))
            if name in self.vars:
                self.vars[name] = (self.vars[name][0], value)
            return self._ret(0)
        if addr == F_RENAME:                          # nothing may rename a file now
            self.renames.append((self.cstr(r1),))
            return self._ret(0)
        if addr == T.F['F_WRITE'] and not self.write_ok:
            return self._ret(0)
        if addr == NBR_LOAD:
            self.gui_trace.append('load')
            self.bound_at_load = getattr(self, 'bound_at_load', []) + [getattr(self, 'texts_bound', True)]
            self.texts_bound = False            # stock C05E0940: every resource unbound
            sp = self.r(T.UC_ARM_REG_SP)
            self.nbr_calls.append(([r0, r1, r2, r3], sp, bytes(mu.mem_read(r1, r2))))
            if self.nbr_result == 0:
                if self.nbr_calls[-1][2].startswith(F.NBR.MAGIC):
                    F.NBR.inspect(self.nbr_calls[-1][2])
                    return self._ret(0)  # image resources add no screens/machines
                count = self.w(APP + 0x80) + len(F.SL.native_rows(self.nbr_calls[-1][2]))
                if count > self.w(APP + 0x84):
                    # Explicit declared stub effect: stock registration can grow
                    # the vector. This does not emulate the native allocator.
                    cap = (count + 31) & ~31
                    vector = self._alloc(4 * cap)
                    mu.mem_write(vector, bytes(mu.mem_read(self.w(APP + 0x8C), 4 * self.w(APP + 0x80))))
                    self.put(APP + 0x84, cap)
                    self.put(APP + 0x8C, vector)
                self.put(APP + 0x80, count)
                n = self.w(APP + 0xF8)
                if self.grow:
                    vector = self.w(APP + 0x104)
                    if n == self.w(APP + 0xFC):
                        cap = (n + 32) & ~31
                        grown = self._alloc(4 * cap)
                        mu.mem_write(grown, bytes(mu.mem_read(vector, 4 * n)))
                        vector = grown
                        self.put(APP + 0xFC, cap)
                        self.put(APP + 0x104, vector)
                    self.put(vector + 4 * n, self.new_machine)
                    self.put(APP + 0xF8, n + 1)
                self.put(r3, NEW_RD)
            return self._ret(self.nbr_result)
        return super()._hook(mu, addr, size, data)

    def machines(self):
        vector = self.w(APP + 0x104)
        return [self.cstr(self.w(self.w(vector + 4 * i) + 8)) for i in range(self.w(APP + 0xF8))]

    def press(self, k):
        """FT_Key = k, as the GUI tells its subscriber: fn(descriptor)."""
        self.notify('FT_Key', k)

    def notify(self, var, value):
        """`var` changed to `value`, as the GUI tells its subscriber."""
        fn, = [f for _o, name, f in self.subs if name == var]
        k = value
        desc = FAKE + 0x7800
        self.put(desc, 0)
        self.put(desc + 8, k)
        self.call(fn & ~1, r0=desc, thumb=bool(fn & 1))

    def page_id(self, name):
        """Run the site's branch target as FUN_c05645e8 would: r1 = the name."""
        word = self.w(SITE)
        off = word & 0xFFFFFF
        target = SITE + 8 + ((off - (1 << 24) if off & 0x800000 else off) << 2)
        self.mu.mem_write(FAKE + 0x7000, name.encode() + b'\0')
        r0, _ = self.call(target, r0=0, r1=FAKE + 0x7000)
        return r0


class PageTests(unittest.TestCase):
    def test_pack_through_the_stock_matcher(self):
        import sl_pages as SL
        import ft6_page as FP
        img, pool = FP.stock_pool()
        y6, _ = FP.build(img, pool)
        lst, _ = FP.build_grid(img, pool)
        old, SL.MACHINE = SL.MACHINE, F.MACHINE
        try:
            pack = F.build_pack([(F.PAGE, y6), ('FT_LIST', lst)], trans=F.TRANSITIONS + F.LIST_TRANSITIONS)
            got = SL.native_switch(pack, [('MainY5', 'Menu01'), ('MainB1', 'Menu13'),
                                          (F.PAGE, 'Menu01'), (F.PAGE, 'Menu12'),
                                          ('MainY5', 'Menu12'), (F.PAGE, 'FT_LIST'),
                                          ('FT_LIST', 'Return'), ('FT_LIST', 'Menu01')])
        finally:
            SL.MACHINE = old
        self.assertEqual(got[('MainY5', 'Menu01')][0], F.PAGE)
        self.assertEqual(got[('MainB1', 'Menu13')][0], F.PAGE)
        self.assertEqual(got[(F.PAGE, 'Menu01')][0], 'MainB1')
        self.assertEqual(got[(F.PAGE, 'Menu12')][0], 'MainY5')
        self.assertIsNone(got[('MainY5', 'Menu12')], 'Y5 Left stays stock')
        self.assertEqual(got[(F.PAGE, 'FT_LIST')][0], 'FT_LIST')
        self.assertEqual(got[('FT_LIST', 'Return')][0], F.PAGE)
        self.assertIsNone(got[('FT_LIST', 'Menu01')], 'no tab turning from the list')

    def test_page_structure(self):
        import ft6_page as FP
        img, pool = FP.stock_pool()
        page, refs = FP.build(img, pool)
        objs = FP.check_page(page, img, pool)['objects']
        self.assertEqual(objs[FP.ROWS_PARENT]['child_count'], 1)
        self.assertEqual(objs[FP.BAR_Y]['child_count'], 7)
        self.assertEqual(sorted(t for _o, t in refs), ['All Sups', 'FT_LIST', 'FT_LIST'])
        page, refs = FP.build_grid(img, pool)
        objs = FP.check_page(page, img, pool, base=FP.GRID_BASE)['objects']
        self.assertTrue(all(c in objs for c in FP.GRID_CELLS))
        self.assertFalse(set(FP.GRID_DROP) & set(objs), 'the first-boot flow and the marker went')
        texts = sorted(t for _o, t in refs)
        for k in range(1, len(FP.GRID_CELLS) + 1):
            for part, _c in FP.CELL_PARTS:
                self.assertEqual(texts.count(FP.part_var(part, k)), 1)
        self.assertEqual(texts.count(FP.KEY_VAR), 2 * len(FP.GRID_CELLS), 'OK and AEL on each cell')
        self.assertEqual(texts.count(FP.FOCUS_VAR), 21, 'the cursor: cells, Menu, FirstFocus')
        self.assertEqual(texts.count(FP.LIST_TITLE), 1)

    def test_each_cell_ok_writes_ft_key(self):
        """Camera r3e3: the cells' OK lost its FT_Key write (a drawText took
        its place: one name for two templates) and nothing happened on OK."""
        import struct as st
        import nbu_format as N
        import ft6_page as FP
        img, pool = FP.stock_pool()
        page, refs = FP.build_grid(img, pool)
        key_at = {o for o, t in refs if t == FP.KEY_VAR}
        cur, ev, at, found = None, None, 0, {}
        for r in N.split(page):
            d = r.to_bytes()
            if r.tag == 0x10003:
                cur = r.words(7)[3]
            elif r.tag == 0x10006:
                ev = pool.text(st.unpack_from('>I', d, 20)[0]) if pool.text(st.unpack_from('>I', d, 8)[0]) == 'keyEvent' else None
            elif cur in FP.GRID_CELLS and ev == 'OK' and r.tag == 0x10009:
                if pool.text(st.unpack_from('>I', d, 8)[0]) == 'controlAppVariable' and at + 36 in key_at:
                    found[cur] = pool.text(st.unpack_from('>I', d, 41)[0])
            at += len(d)
        self.assertEqual(found, {c: str(k) for k, c in enumerate(FP.GRID_CELLS, 1)})
        # AEL on each cell: FT_Key = AEL_BASE + k (the value may be a private string: "101")
        cur, ev, at, ael = None, None, 0, {}
        vals = dict(refs)
        for r in N.split(page):
            d = r.to_bytes()
            if r.tag == 0x10003:
                cur = r.words(7)[3]
            elif r.tag == 0x10006:
                ev = pool.text(st.unpack_from('>I', d, 20)[0]) if pool.text(st.unpack_from('>I', d, 8)[0]) == 'keyEvent' else None
            elif cur in FP.GRID_CELLS and ev == 'AEL' and r.tag == 0x10009 and at + 36 in key_at:
                ael[cur] = vals.get(at + 41) or pool.text(st.unpack_from('>I', d, 41)[0])
            at += len(d)
        self.assertEqual(ael, {c: str(FP.AEL_BASE + k) for k, c in enumerate(FP.GRID_CELLS, 1)})
        # and each event listens to its own key: the record's last word
        codes = {}
        cur = None
        for r in N.split(page):
            d = r.to_bytes()
            if r.tag == 0x10003:
                cur = r.words(7)[3]
            elif cur in FP.GRID_CELLS and r.tag == 0x10006 and pool.text(st.unpack_from('>I', d, 8)[0]) == 'keyEvent':
                codes.setdefault(pool.text(st.unpack_from('>I', d, 20)[0]), set()).add(st.unpack_from('>I', d, len(d) - 4)[0])
        self.assertEqual(codes['OK'], {FP.KEY_OK_CODE})
        self.assertEqual(codes['AEL'], {FP.KEY_AEL_CODE}, 'camera r3g: an AEL event copied from OK listened to OK')

    def test_the_grid_writes_no_setting(self):
        """Nothing on the list page names a stock variable the language page
        writes (CM_Language is the setting; SYS_LangSetting the first-boot flag)."""
        import struct as st
        import nbu_format as N
        import ft6_page as FP
        img, pool = FP.stock_pool()
        page, _ = FP.build_grid(img, pool)
        schemas = FP.P.load_schemas(img)
        named = set()
        for r in N.split(page):
            d = r.to_bytes()
            for off, kind in FP.P.typed_fields(d, pool, schemas):
                if kind in ('str', 'text'):
                    named.add(pool.text(st.unpack_from('>I', d, off)[0]))
        self.assertFalse(named & {'CM_Language', 'CM_LanguageAj', 'SYS_LangSetting', 'SYS_DateSetting'})

    def test_only_the_planned_records_change(self):
        """Outside the rows that go, a record of FT_Y6 differs from MainY5's
        only where the plan says (camera r2: renumbered action orders and
        dropped empty events broke the header -- SHOOT showed, not SYSTEM)."""
        from collections import Counter
        import nbu_format as N
        import sl_pages as SL
        import ft6_page as FP
        img, pool = FP.stock_pool()
        old = N.split(SL.set_bytes(FP.BASE))
        new = N.split(FP.build(img, pool)[0])

        def owned(rs):
            out, cur = [], -1
            for r in rs:
                if r.tag == 0x10003:
                    cur = r.words(7)[3]
                out.append((cur, r.tag, r.to_bytes()))
            return out
        objs = FP.SZ.objects(old, pool)
        gone = set()
        for root in [k for k, v in objs.items() if v['parent'] == FP.ROWS_PARENT][1:]:
            gone |= FP.SZ.subtree(objs, root)
        changed = {c for (c, _t, _b) in (Counter(owned(old)) - Counter(owned(new))) if c not in gone}
        self.assertEqual(changed, {-1, 33510, FP.BAR_Y, *FP.Y_TABS, FP.ROWS_PARENT, FP.ROW_NAME,
                                   FP.ROW_ITEM})
        self.assertEqual(sum(1 for c, t, _b in owned(new) if c == FP.Y_TABS[4] and t == 0x1000A), 1,
                         'Tab05 keeps its own clip')


if __name__ == '__main__':
    unittest.main()
