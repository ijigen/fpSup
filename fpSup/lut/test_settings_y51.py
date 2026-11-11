"""The Y5_1 settings page, record by record: what the camera showed on
2026-11-03 (projects/lut-sup/validation/20261103-list-ab-02, diagK).

The emulated core never runs page records, so these read them: a MENU that
does not tell the core it left (LC_Key stayed 0, MENU never left the page) and
a stock value cap that clamps the cube's choice (Rec.709 became Blackmagic and
was written to LUT.BIN) both passed the native tests."""
import struct
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'uishare/tab')]
import color_ui as C                     # noqa: E402
import settings_y51 as Y                 # noqa: E402
import ft6_page as P                     # noqa: E402
import nbu_format as N                   # noqa: E402

u32 = P.u32


class Page:
    def __init__(self):
        self.page, refs, self.row0 = C.make_settings('LUT settings')
        self.img, self.pool = P.stock_pool()
        self.refs = dict(refs)
        self.recs, self.at = [], []
        off = 0
        for r in N.split(self.page):
            self.recs.append(r.to_bytes()); self.at.append(off); off += r.size

    def text(self, i, off):
        """A string field: a private one by its reference, else the stock pool."""
        a = self.at[i] + off
        if off + 4 > len(self.recs[i]):
            return None
        if a in self.refs:
            return self.refs[a]
        v = u32(self.recs[i], off)
        return self.pool.text(v) if v < len(self.pool.data) else None

    def kind(self, i):
        r = self.recs[i]
        return self.pool.text(u32(r, 8)) if len(r) >= 12 and r[:2] == b'\0\1' else None


class SettingsPageRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Page()
        Y.check_settings_page(cls.p.page)

    def test_a_rows_menu_only_tells_the_core(self):
        """diagK3: with the stock Return on the key, the manager came up before
        the core's values and had no focus; the key now only notifies."""
        p, n = self.p, 0
        rows = {u32(r, 20) for r in p.recs if r[:4] == b'\0\1\0\3' and p.pool.text(u32(r, 28)) == 'MenuItem_Select'}
        norm = lambda b: b[:28] + b[32:]
        stock = {norm(r.to_bytes()) for r in N.split(P.SL.set_bytes(Y.BASE))}
        for i, r in enumerate(p.recs):
            if p.kind(i) != 'keyEvent' or p.text(i, 20) != 'Menu':
                continue
            acts = list(range(i + 1, i + 1 + u32(r, 16)))
            if u32(r, 24) in rows:
                self.assertEqual([p.kind(j) for j in acts], ['controlAppVariable'])
                w = acts[0]
                self.assertEqual((len(p.recs[w]), u32(p.recs[w], 32), p.text(w, 36), p.text(w, 41)),
                                 (46, 0x81, 'LC_Key', '70'))
                n += 1
            elif any(p.kind(j) == 'controlAppState' for j in acts):   # header / footer: the stock page's own
                for j in acts:
                    self.assertIn(norm(p.recs[j]), stock)
        self.assertEqual(n, 4)                         # Color space, Gamma, Color matrix, Color chart

    def test_lc_back_sends_the_rows_stock_return(self):
        p = self.p
        ev = [i for i, r in enumerate(p.recs) if p.kind(i) == 'appVariableChangeEvent' and p.text(i, 36) == 'LC_Back']
        self.assertEqual(len(ev), 1)
        r = p.recs[ev[0]]
        self.assertEqual((len(r), u32(r, 32), u32(r, 24), u32(r, 16)), (41, 1, Y.ROOT, 1))
        a = p.recs[ev[0] + 1]
        self.assertEqual((p.kind(ev[0] + 1), u32(a, 20), u32(a, 24)), ('controlAppState', Y.ROOT, u32(r, 28)))
        self.assertEqual((len(a), u32(a, 32), p.text(ev[0] + 1, 36)), (45, 5, Y.BACK_TEXT))
        self.assertIn(Y.BACK_TEXT, C.TEXTS)               # the core rewrites it (T_BACK)
        self.assertIn('LC_Back', {n for _t, n, _v in C.variables()})

    def test_the_stock_return_path_is_kept(self):
        p = self.p
        names = {u32(r, 20): p.pool.text(u32(r, 28)) for r in p.recs if r[:4] == b'\0\1\0\3'}
        self.assertEqual((names.get(Y.RETURN_CHECK), names.get(Y.RETURN)), ('ReturnCheck', 'Return'))
        final = [i for i, r in enumerate(p.recs) if p.kind(i) == 'controlAppState' and u32(r, 20) == Y.RETURN]
        self.assertEqual(sorted(p.text(i, 36) for i in final), ['LV', 'Return'])

    def test_every_literal_write_writes_its_value(self):
        p = self.p
        for i, r in enumerate(p.recs):
            if p.kind(i) == 'controlAppVariable' and p.text(i, 36) in ('LC_Key', 'FT_Go', 'LC_Go'):
                self.assertEqual(u32(r, 32), 0x81, p.text(i, 36))

    def test_no_value_bound_to_a_row_variable_caps_it_below_the_list(self):
        p = self.p
        for spec in (Y.SPACE, Y.GAMMA, Y.MATRIX):
            owners = {u32(r, 24) for i, r in enumerate(p.recs)          # an event: owner +24, variable +40
                      if p.kind(i) == 'appVariableEvent' and p.text(i, 40) == spec['value']}
            self.assertGreaterEqual(len(owners), 3, spec['value'])
            for i, r in enumerate(p.recs):
                if p.kind(i) == 'controlValue' and u32(r, 20) in owners and u32(r, 28) & 2:
                    cap = struct.unpack_from('>f', r, 32 if not u32(r, 28) & 1 else 36)[0]
                    self.assertGreaterEqual(cap, spec['rows'] - 1, (spec['value'], u32(r, 20)))

    def test_the_rows_lists_are_their_own(self):
        p = self.p
        objs = {u32(r, 20) for i, r in enumerate(p.recs) if r[:4] == b'\0\1\0\3'}
        lists = [r for r in p.recs if r[:4] == b'\0\1\0\x08']
        self.assertEqual(len(lists), 4)
        for r in lists:
            self.assertTrue(all(u32(r, o) in objs for o in C.S.template_ids(r)))

    # ---- Bei 2026-11-07: "Color chart" (查看色卡)
    def objects(self):
        p = self.p
        return {u32(r, 20): (u32(r, 24), p.pool.text(u32(r, 28)) if u32(r, 28) < len(p.pool.data) else None)
                for r in p.recs if r[:4] == b'\0\1\0\3'}

    def test_the_chart_row_only_tells_the_core(self):
        """its OK and Right write LC_Key = 81 (no list to open); its title and value text are its own."""
        p = self.p
        titled = [i for i, r in enumerate(p.recs) if p.kind(i) == 'drawText' and p.text(i, 32) == 'Color chart']
        self.assertEqual(len(titled), 1)
        name = u32(p.recs[titled[0]], 20)
        sel = self.objects()[name][0]                                       # Name's parent: the MenuItem_Select
        keys = {}
        for i, r in enumerate(p.recs):
            if p.kind(i) == 'keyEvent' and u32(r, 24) == sel:
                keys[p.text(i, 20)] = [(p.kind(j), p.text(j, 36), p.text(j, 41)) for j in range(i + 1, i + 1 + u32(r, 16))]
        self.assertEqual(keys['OK'], [('controlAppVariable', 'LC_Key', str(Y.CHART_KEY))])
        self.assertEqual(keys['Right'], [('controlAppVariable', 'LC_Key', str(Y.CHART_KEY))])
        self.assertEqual(keys['Menu'], [('controlAppVariable', 'LC_Key', '70')])
        self.assertEqual(Y.CHART_KEY, 81)
        texts = [p.text(i, 40) for i, r in enumerate(p.recs) if p.kind(i) == 'appVariableEvent' and u32(r, 24) in
                 {o for o, (par, _n) in self.objects().items() if par == sel}]
        self.assertIn('LC_ChartT', texts)
        self.assertIn('LC_ChartT', {n for _t, n, _v in C.variables()})
        self.assertIn('Convert again', C.TEXTS)

    def test_the_chart_is_the_pages_own_and_bound_like_the_managers(self):
        """48 drawRects whose colour is LC_P00..47, the match text LC_Match, every object's opacity LC_Chart; the
        chart a Root child ahead of the others (drawn on top); only Y5_1's own component kinds."""
        p = self.p
        binds = {}
        for i, r in enumerate(p.recs):
            if p.kind(i) == 'appVariableEvent':
                binds.setdefault(p.text(i, 40), []).append(u32(r, 24))
        patches = [f'LC_P{k:02d}' for k in range(48)]
        for n in patches:
            self.assertEqual(len(binds.get(n, [])), 1, n)
        self.assertEqual(len(binds['LC_Match']), 1)
        objs = self.objects()
        chart = {o for o in binds['LC_Chart']}
        self.assertEqual(len(chart), 1 + 48 + 1)                             # the box, the halves, the match
        top = [o for o in chart if objs[o][0] == Y.ROOT]
        self.assertEqual(len(top), 1)
        self.assertTrue(all(objs[o][0] == top[0] for o in chart - set(top)))
        self.assertTrue(set(binds[n][0] for n in patches) <= chart)
        heads = [u32(r, 20) for r in p.recs if r[:4] == b'\0\1\0\3' and u32(r, 24) == Y.ROOT]
        self.assertEqual(heads[0], top[0])                                   # first among Root's children
        self.assertFalse(C.P.Lab.duplicate_local_ids(p.page))


if __name__ == '__main__':
    unittest.main()
