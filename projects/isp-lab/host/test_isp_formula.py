#!/usr/bin/env python3
"""ISP formula v2 offline: the stock rows as a regression, the rules as properties, mutations.

    python3 -B -m unittest test_isp_formula
"""
import pathlib, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'open-gate' / 'build'))
import test_imx410_profile as T                     # noqa: E402  (stock rows, routes, mode scales)
import isp_formula as F                             # noqa: E402

BASE = T.BYID[171]
ENGINE_FPS = 0x30


def spec_of(route):
    st = T.BYROW[route['profile_row']]
    return F.Spec(window=tuple(route['sensor_raster']), zoom=tuple(max(z, 1024) for z in route['zoom']),
                  rec=tuple(route['raw_dimensions']),
                  scale=T.SCALE[route['sensor_mode']], bits=T.BITS[st[0x84 // 4]], hirate=bool(st[0xB0 // 4]))


class Stock(unittest.TestCase):
    def test_every_stock_movie_row(self):
        for r in T.ROUTES:
            got, want = F.row(spec_of(r), BASE), T.BYROW[r['profile_row']]
            bad = [hex(4 * i) for i in range(65) if 4 * i != ENGINE_FPS and got[i] != want[i]]
            self.assertEqual(bad, [], (r['name'], r['format_enum'], F.plan(spec_of(r)).path))


class Rules(unittest.TestCase):
    WINDOWS = ((3032, 1708), (6064, 3412), (2088, 1174), (4176, 2174), (6064, 4042), (3032, 2020), (2016, 672),
               (2032, 4040), (2096, 2358))                          # R12: narrow and tall (SQ / S35 2x1)
    ZOOMS = (1024, 1200, 1536, 1600, 2048, 3072, 4096, 6144, 8191)

    def plans(self):
        for W in self.WINDOWS:
            for zh in self.ZOOMS:
                for zv in self.ZOOMS:
                    for vb in (1, 3):
                        try:
                            yield F.Spec(window=W, zoom=(zh, zv), vbin=vb), F.plan(F.Spec(window=W, zoom=(zh, zv), vbin=vb))
                        except F.NotPossible:
                            pass

    def test_never_branch_f(self):
        n = 0
        for s, p in self.plans():
            n += 1
            rec_scaled = s.zoom != (1024, 1024)
            pre_unity = p.preview[2] == 1023 and p.preview[3] == 1023
            equal = p.preview[2:] == (F._z(s.zoom[0]), F._z(s.zoom[1]))
            self.assertTrue(not rec_scaled or pre_unity or equal, (s, p.path, p.preview))
        self.assertGreater(n, 500)

    def test_preview_inside_its_source(self):
        for s, p in self.plans():
            self.assertLessEqual(p.source[0], F.SRC_MAX, s)
            self.assertLessEqual(p.raster[0], p.source[0], s)
            self.assertLessEqual(p.raster[1], p.source[1], s)
            self.assertLessEqual(p.visible[0], F.VIS_MAX_W, s)
            self.assertLessEqual(p.raster[1], F.SRC_MAX_H, s)                # R12
            self.assertEqual(p.visible[0] % 16, 0, s)

    def test_no_horizontal_bin_and_vertical_only_in_c(self):
        for s, p in self.plans():
            self.assertEqual(p.words[0x5C], 0, s)
            if s.vbin == 3:
                self.assertEqual((p.path, p.words[0xC8], p.preview[1]), ('C', 1, 1), s)

    def test_impossible_combinations_say_why(self):
        for s in (F.Spec(window=(3032, 1708), zoom=(8192, 8192)), F.Spec(window=(3032, 1708), zoom=(1024, 1024), vbin=3),
                  F.Spec(window=(6064, 3412), zoom=(1536, 1536), vbin=3), F.Spec(window=(8000, 3000), zoom=(2048, 2048)),
                  F.Spec(window=(2016, 672), zoom=(1024, 1024), vbin=3)):
            with self.assertRaises(F.NotPossible):
                F.plan(s)

    def test_plane_codes_measured(self):
        """night1e d8/d10, night2 d12, night3 d14: these codes gave 8/10/12/14-bit CinemaDNG on any route."""
        for bits, codes in ((8, (10, 10)), (10, (10, 9)), (12, (7, 7)), (14, (7, 8))):
            w = F.plan(F.Spec(window=(3032, 1708), zoom=(1600, 1600), bits=bits)).words
            self.assertEqual((w[0x80], w[0x84]), codes, bits)

    def test_measured_cases(self):
        """The live night1-4 geometry (ISP_CAPABILITY_MAP §0.5) under v2."""
        fhd = dict(window=(3032, 1708), scale=(2, 2))
        self.assertEqual(F.plan(F.Spec(zoom=(1200, 1200), **fhd)).path, 'E3')            # was F: zoomed REC LV
        self.assertEqual(F.plan(F.Spec(zoom=(4096, 4096), **fhd)).path, 'C')             # was F: record /3 too; C past 3x: mx1
        s35 = F.Spec(window=(2096, 1180), zoom=(3119, 3119), scale=(2, 2), rec=(688, 386))  # mx1 M74: E1 cropped the REC LV
        self.assertEqual(F.plan(s35).path, 'C')                                          # cmax: C 0.97 for 0.977
        for win in ((2096, 1180), (4192, 2358)):                                         # sby M60 / M55: 0.95 of it
            p = F.plan(F.Spec(window=win, zoom=(1024, 1024)))
            k = (p.preview[2] if p.preview[2] > 1023 else 1024) / 1024
            self.assertEqual(p.path, 'D', win)
            self.assertGreaterEqual(p.visible[0] * k, 0.98 * p.act[0], win)      # the recording LV shows the record
        p = F.plan(F.Spec(zoom=(4608, 1536), vbin=3, **fhd))                              # night1d b1x3-z4608x1536
        self.assertEqual((p.path, p.rec), ('C', (672, 378)))
        self.assertEqual(F.plan(F.Spec(zoom=(1536, 1536), **fhd)).rec, (2016, 1138))     # night1 z1536 DNG


    def test_r14_the_preview_holds_the_record(self):
        """E1 / E3 only where C cannot take it, or where they show all of the record."""
        n = 0
        for W in self.WINDOWS + ((2112, 416), (2096, 2358), (2112, 624), (1360, 2014)):
            for zh in self.ZOOMS:
                for zv in self.ZOOMS:
                    s = F.Spec(window=W, zoom=(zh, zv))
                    try:
                        p = F.plan(s)
                    except F.NotPossible:
                        continue
                    if p.path in ('E1', 'E3'):
                        k = F.UNITY if p.path == 'E1' else 3 * F.UNITY
                        c_fits = W[0] * F.UNITY // zh <= F.SRC_MAX and W[1] * F.UNITY // zv <= F.SRC_MAX_H
                        c_ok = c_fits and F._shows_all(s, p.act, zh, zv)
                        self.assertTrue(not c_ok or F._shows_all(s, p.act, k, k), (s, p.path, p.visible))
                    if p.path == 'C' and zh != zv:          # R14's C shows all of the record
                        self.assertTrue(F._shows_all(s, p.act, zh, zv), (s, p.visible))
                    n += p.path == 'C' and zh != zv
        self.assertGreater(n, 20)

    def test_r14_measured(self):
        """10-28 p5: S16 688x406 1x3 (E3 showed 0.948 of it) and APSC 1312 1x3 now preview at the record."""
        for w, z, rec in (((2112, 416), (3143, 1049), (688, 406)), ((3968, 876), (3096, 1031), (1312, 870))):
            p = F.plan(F.Spec(window=w, zoom=z, rec=rec))
            self.assertEqual((p.path, p.preview[2:]), ('C', (F._z(z[0]), F._z(z[1]))), w)
        # p6r14: S35 2096 at C hit the 2000 visible cap (0.958) -> stays E3
        self.assertEqual(F.plan(F.Spec(window=(4192, 2358), zoom=(2048, 2049), rec=(2096, 1178))).path, 'E3')


class LineRate(unittest.TestCase):
    def test_r11_measured(self):
        """10-27 hmax400 / 405: 12fastW and 12fastW-v3 at 6048 fail at HMAX 400, pass from 405 (f12v3 from 420)."""
        self.assertGreater(F.min_line_clk(6048), 400)
        self.assertLessEqual(F.min_line_clk(6048), 420)
        self.assertLessEqual(F.min_line_clk(3032), 330)            # 2x2fast at its floor passed (g1)

    def test_r15_measured(self):
        """10-28 hs sweep: 14 bit at 6048 needs 911 (905 broke h3v3 frames), 4192 keeps the class floor."""
        self.assertEqual(F.min_line_clk(6048, 14), 911)
        self.assertEqual(F.min_line_clk(6064, 14), 911)
        self.assertLess(F.min_line_clk(4192, 14), 870)
        self.assertLess(F.min_line_clk(6048, 12), 870)


MUTANTS = {
    'R12 dropped (tall E1 preview)': ("    if W <= SRC_MAX and H <= SRC_MAX_H:  ", "    if W <= SRC_MAX:  "),
    'R12 dropped (tall D preview)': (", -(-H // SRC_MAX_H))", ")"),
    'R11 at the measured edge': ('LINE_PX_PER_CLK = (29, 2)', 'LINE_PX_PER_CLK = (152, 10)'),
    'branch F allowed': ('    if W <= SRC_MAX and H <= SRC_MAX_H:              # R12: a tall 1:1 preview froze the take (SQ 2032x4040 E1)\n        e = \'E1\'', '    if True:\n        return \'C2\', fh, fv\n    if W <= SRC_MAX:\n        e = \'E1\''),
    'RWZM 8192 accepted': ('RWZM_MAX = 8191', 'RWZM_MAX = 8192'),
    'C capped at 3x again (E1 crops the recording LV)': ('    if fh == fv and c_fits:', '    if fh == fv and fh < 3 * UNITY and c_fits:'),
    'D at the smallest fitting ratio, not an integer': ('        k = max(-(-W // SRC_MAX), -(-aw // VIS_MAX_W), -(-H // SRC_MAX_H))', '        k = max(W / SRC_MAX, aw / VIS_MAX_W, H / SRC_MAX_H)'),
    'D ignores the visible cap': ('        k = max(-(-W // SRC_MAX), -(-aw // VIS_MAX_W), -(-H // SRC_MAX_H))', '        k = max(-(-W // SRC_MAX), -(-H // SRC_MAX_H))'),
    'E3 past three sources': ('E3_W_MAX = 3 * SRC_MAX ', 'E3_W_MAX = 4 * SRC_MAX '),
    'unity record bins': ("    if (s.vbin == 3 or s.hbin == 3) and zh == UNITY and zv == UNITY:\n", "    if False:\n"),
    '14 bit in the 16 bit code': ('14: (7, 8)}', '14: (7, 11)}'),
    'R15 dropped (14 bit full width at 870)': ('    if bits == 14 and w > WIDE14_W:', '    if False:'),
    'R15 edge at 6048': ('WIDE14_W, WIDE14_HMAX = 4192, 911', 'WIDE14_W, WIDE14_HMAX = 6048, 911'),
    'R14 takes a C that clips too': (' and _shows_all(s, act, fh, fv):   # R14', ':   # R14'),
    'R14 dropped (E3 clamps the record)': ('    if act and c_fits and not _shows_all(s, act, e[1], e[2])', '    if False and not _shows_all(s, act, e[1], e[2])'),
}


class Mutation(unittest.TestCase):
    def test_every_mutant_is_caught(self):
        import importlib.util, io
        src = (HERE / 'isp_formula.py').read_text()
        for name, (old, new) in MUTANTS.items():
            self.assertEqual(src.count(old), 1, name)
            spec = importlib.util.spec_from_loader('isp_formula', loader=None)
            mod = importlib.util.module_from_spec(spec)
            sys.modules['isp_formula'] = mod
            exec(src.replace(old, new), mod.__dict__)
            global F
            keep, F = F, mod
            try:
                suite = unittest.TestSuite([Stock('test_every_stock_movie_row')] + [Rules(n) for n in (
                    'test_never_branch_f', 'test_preview_inside_its_source', 'test_no_horizontal_bin_and_vertical_only_in_c',
                    'test_impossible_combinations_say_why', 'test_measured_cases', 'test_plane_codes_measured',
                    'test_r14_the_preview_holds_the_record', 'test_r14_measured')] +
                    [LineRate('test_r11_measured'), LineRate('test_r15_measured')])
                r = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
                self.assertFalse(r.wasSuccessful(), f'mutant survived: {name}')
            finally:
                F = keep
                sys.modules['isp_formula'] = keep


if __name__ == '__main__':
    unittest.main()
