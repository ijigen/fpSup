"""matrix.py cases are what isp_custom installs: same readout, same v2 plan, nothing the formulas refuse."""
import pathlib, sys, unittest

import isp_custom as C
import isp_formula as F
import matrix as M
import quality as Q
import readout_cfg as RCF

HERE = pathlib.Path(__file__).resolve().parent


class MatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = M.cases()

    def test_every_case_is_installable_as_planned(self):
        for i, c in enumerate(self.cases):
            vp = C.readout_plan(c['readout'])
            self.assertEqual(vp['id'], c['readout_id'], i)
            s = F.Spec(window=tuple(c['window']), zoom=tuple(c['zoom']), vbin=c['vbin'], hbin=c['hbin'], bits=c['bits'],
                       scale=tuple(int(x) for x in c['merge'].split('x')), rec=tuple(c['rec']))
            pl = F.plan(s)
            self.assertEqual((list(pl.rec), pl.path), (c['rec'], c['path']), i)
            self.assertEqual(c['window'], [vp['raster_w'], vp['out_h']], i)

    def test_args_replay_the_plan(self):
        """the case's readout args rebuild the very plan it came from: HMAX, VMAX, 0016 (no cap the plan did not use)"""
        import readout_cfg as RCF
        for i, c in enumerate(self.cases):
            a = c['readout']
            want = M.readout(*a[:3], Q.rows_of(c))
            got = RCF.plan(*a)
            self.assertEqual((got['soc'], [x for x in got['sensor'] if x[0] == 0x0016], got['id']),
                             (want['soc'], [x for x in want['sensor'] if x[0] == 0x0016], c['readout_id']), i)

    def test_isp_custom_reads_the_case(self):
        j = C.tables()[1]
        cases = [c for c in self.cases if Q.rows_of(c) is None]       # M<n> = matrix.json (R16 held out, see below)
        for i in (0, len(cases) // 2, len(cases) - 1):
            c = cases[i]
            _, w, _ = C.experiment(j, f'FHD60:M{i}')
            self.assertEqual(F.plan(C.spec_of(w)).rec, tuple(c['rec']))
            self.assertEqual(C.vmode_of(f'FHD60:M{i}'), c['readout'])

    def test_matrix_json_is_current(self):
        """isp_custom runs M<n> from matrix.json: a formula change that moves the cases needs `matrix.py` rerun.
        R16's cases (notes/R16_CANDIDATES.md) are held out until their live test: they only ADD cases, the rest is
        unchanged -- drop the filter when matrix.json is regenerated with them."""
        import json
        self.assertEqual(json.loads(M.OUT.read_text()),
                         json.loads(json.dumps([c for c in self.cases if Q.rows_of(c) is None])))

    def test_rules_hold(self):
        for c in self.cases:
            self.assertLessEqual(c['fps'], M.HOST_FPS + 0.01)
            self.assertLessEqual(c['res'][0], M.DC[c['dc']][0])
            self.assertTrue(c['rec'][0] == c['res'][0] and c['rec'][1] >= 0.97 * c['res'][1], c)

    def test_hd_alone_has_uhd_and_fhd(self):
        for dc in M.DC:
            has = {tuple(c['res']) for c in self.cases if c['dc'] == dc} & {(3840, 2160), (1920, 1080)}
            self.assertEqual(bool(has), dc == 'HD', dc)


HD1K, OG1K = (6048, 3402, 1008, 566), (6048, 4040, 1008, 672)


def q_of(cell, key):
    return next((c for c in Q.qualities(*cell) if c['readout'][0] == key), None)


class R16(unittest.TestCase):
    """R16: a readout that cannot window the DC reads full height, the TIM keeps the DC's rows (centred)."""

    def test_hd1k_gets_the_og_readout_cropped(self):
        """Bei 10-29: HD 1K on 3x6fast at OG 1K's rate, the raster / record / DNG the DC's rows, no vertical scale"""
        hd, og = q_of(HD1K, '3x6fast'), q_of(OG1K, '3x6fast')
        self.assertIsNotNone(hd)
        self.assertEqual(hd['fps'], og['fps'])
        self.assertEqual(hd['readout'][2], RCF.SENSOR_H)
        self.assertEqual((hd['window'], hd['zoom'][1], hd['rec']), ([2016, 566], 1024, [1008, 566]))
        p = Q.settings(hd)[0]
        self.assertEqual((p['out_h'], p['receiver_lines']), (566, Q.settings(og)[0]['receiver_lines']))

    def test_crop_is_centred(self):
        """the TIM drops as many rows above as below (even: Bayer phase); smc's y0 starts below the top ones"""
        import smc
        for cell in (HD1K, (4192, 2358, 688, 386), (2108, 1248, 336, 198)):
            for c in Q.qualities(*cell):
                rows = Q.rows_of(c)
                if rows is None:
                    continue
                p = Q.settings(c)[0]
                full = RCF.full_rows(c['readout'][0])
                top = p['y_skip']
                self.assertEqual(top % 2, 0)
                self.assertLessEqual(abs(top - (full - rows - top)), 2, (cell, c['quality']))
                a = smc.attrs_from_plan(p)
                b = smc.attrs_from_plan(RCF.plan(c['readout'][0], c['readout'][1], RCF.SENSOR_H, c['readout'][3], full))
                self.assertEqual((a['y0'] - b['y0'], a['y1'] - a['y0']), (top, rows), (cell, c['quality']))

    def test_field_of_view_is_the_dc(self):
        """the rows kept are the DC's, never more, and lose less than one row pair of it"""
        for c in M.cases():
            rows = Q.rows_of(c)
            if rows is None:
                continue
            mv, ch = RCF.BY_KEY[c['readout'][0]]['mv'], M.DC[c['dc']][1]
            self.assertLessEqual(rows * mv, ch, c['name'])
            self.assertLess(ch - rows * mv, 2 * mv, c['name'])
            self.assertEqual(c['window'][1], rows, c['name'])

    def test_only_where_no_window(self):
        """R16 only for a readout whose own DC plan the rules refuse; full-height DCs never"""
        n = 0
        for c in M.cases():
            if Q.rows_of(c) is None:
                continue
            n += 1
            self.assertNotEqual(c['dc'], 'OG')
            with self.assertRaises(ValueError):
                Q.readout(c['readout'][0], *M.DC[c['dc']])
        self.assertGreaterEqual(n, 8)

    def test_never_a_frame_shorter_than_the_dc(self):
        """SQ 4032: the new V3 full frame is 1330 rows = 3990 sensor rows, less than the DC -> no R16 case"""
        for cell in ((4032, 4032, 1024, 1024), (4032, 4032, 672, 672)):
            for c in Q.qualities(*cell):
                if Q.rows_of(c) is not None:
                    mv = RCF.BY_KEY[c['readout'][0]]['mv']
                    self.assertLess(cell[1] - Q.rows_of(c) * mv, 2 * mv, c['quality'])

    def test_the_crop_reduces_the_data(self):
        """MB/s: HD 1K's DNG on 3x6fast is 566 rows, at the same fps as OG 1K's 672"""
        hd, og = q_of(HD1K, '3x6fast'), q_of(OG1K, '3x6fast')
        mb = lambda c: c['rec'][0] * c['rec'][1] * c['bits'] / 8 * c['fps'] / 1e6
        self.assertLess(mb(hd), mb(og) * 0.85)

    def test_a_row_crop_is_cut_from_full_height(self):
        with self.assertRaises(ValueError):
            RCF.plan('3x3fast', 6048, 3402, 2016, 1000, None, None, None, 0, 1000)    # a window
        for bad in (565, 0, 674):
            with self.assertRaises(ValueError):
                RCF.plan('3x6fast', 6048, 4040, 2016, 500, None, None, None, 0, bad)


R16_MUTANTS = {      # (file, old, new): each must make an R16 test fail
    'R16 dropped': ('quality.py', "            if ch >= RCF.SENSOR_H:\n                continue\n            # R16",
                    "            if True:\n                continue\n            # R16"),
    'R16 keeps the whole frame (scales instead)': ('quality.py', "    rows = ch // RCF.BY_KEY[key]['mv'] & ~1\n",
                                                   "    rows = RCF.full_rows(key)\n"),
    'R16 rows rounded up (more than the DC)': ('quality.py', "    rows = ch // RCF.BY_KEY[key]['mv'] & ~1\n",
                                               "    rows = -(-ch // RCF.BY_KEY[key]['mv']) + 1 & ~1\n"),
    'R16 on a frame shorter than the DC': ('quality.py', "    return rows if rows <= RCF.full_rows(key) else None",
                                           "    return min(rows, RCF.full_rows(key))"),
    'crop at the top, not centred': ('readout_cfg.py', '        y_crop = (rows_out - rows) // 4 * 2\n', '        y_crop = 0\n'),
    'crop not moved into the TIM y0': ('readout_cfg.py', '    y_skip += y_crop ', '    y_skip += 0 '),
    'crop centred off phase (odd)': ('readout_cfg.py', '        y_crop = (rows_out - rows) // 4 * 2\n', '        y_crop = (rows_out - rows) // 2\n'),
    'row crop allowed on a window': ('readout_cfg.py', "        if windowed:\n            raise ValueError(f'{key}: a row crop", "        if False:\n            raise ValueError(f'{key}: a row crop"),
}


class R16Mutation(unittest.TestCase):
    def test_every_mutant_is_caught(self):
        import importlib.util, io
        global Q, RCF
        keep = Q, RCF, M.Q, sys.modules['quality'], sys.modules['readout_cfg']
        paths = {'quality.py': HERE / 'quality.py', 'readout_cfg.py': pathlib.Path(RCF.__file__)}
        try:
            for name, (fn, old, new) in R16_MUTANTS.items():
                srcs = {f: pth.read_text() for f, pth in paths.items()}
                self.assertEqual(srcs[fn].count(old), 1, name)
                srcs[fn] = srcs[fn].replace(old, new)
                mods = {}
                for mod, f in (('readout_cfg', 'readout_cfg.py'), ('quality', 'quality.py')):
                    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(mod, loader=None))
                    m.__file__ = str(paths[f])
                    sys.modules[mod] = mods[mod] = m
                    exec(compile(srcs[f], str(paths[f]), 'exec'), m.__dict__)
                Q, RCF, M.Q = mods['quality'], mods['readout_cfg'], mods['quality']
                suite = unittest.TestLoader().loadTestsFromTestCase(R16)
                r = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
                self.assertFalse(r.wasSuccessful(), f'mutant survived: {name}')
        finally:
            Q, RCF, M.Q, sys.modules['quality'], sys.modules['readout_cfg'] = keep


if __name__ == '__main__':
    unittest.main()
