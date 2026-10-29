"""quality.py's opt-in visible tolerance (tol=, notes/VISIBLE_TOLERANCE.md): short rasters at the clean pitch, one
each recipe its own visible size, the RES's nominal, default unchanged.  Every rule has a mutant below that one of these tests catches."""
import importlib.util, io, pathlib, sys, unittest

import quality as Q
import readout_cfg as RCF
import isp_formula as F

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))      # quality puts imx410-lab first; keep this dir's matrix.py ahead for other tests
OG, SQ = (6048, 4040), (4032, 4032)


def by_q(cs):
    return {c['quality']: c for c in cs}


class VisibleTol(unittest.TestCase):
    def test_default_unchanged(self):
        """tol off: the RES is recorded exactly (3x3 on OG 1K keeps 672 rows) and no case carries `visible`"""
        cs = Q.qualities(*OG, 1008, 672)
        self.assertTrue(all(c['rec'] == [1008, 672] and 'visible' not in c for c in cs))
        self.assertEqual(by_q(cs)['3x3']['rec'], [1008, 672])
        self.assertNotIn('2x2', by_q(Q.qualities(*OG, 3024, 2020)))

    def test_og3k_takes_the_v2_readouts(self):
        """OG 3K: V2 full height is 2014 rows -> 3024 x 2014 shows 3008 x 2004; 1x1 keeps the nominal 3008 x 2010"""
        cs = by_q(Q.qualities(*OG, 3024, 2020, tol=0.02))
        self.assertEqual((cs['14v2']['rec'], cs['14v2']['visible']), ([3024, 2014], [3008, 2004]))
        self.assertEqual((cs['12']['rec'], cs['12']['visible']), ([3024, 2020], [3008, 2010]))
        self.assertAlmostEqual(cs['14v2']['fps'], 37.14, 1)
        self.assertTrue(all(c['nominal'] == [3008, 2010] for c in cs.values()))

    def test_one_pitch_per_case(self):
        """a short delivery loses rows, never stretches: every recipe's record pixel covers the same sensor area
        (OG 1K 14b 1x3 is 664 rows, not 672 stretched), so a visible size means one field of view in every recipe"""
        cs = Q.qualities(*OG, 1008, 672, tol=0.02)
        c = by_q(cs)['14v3']
        self.assertEqual(c['rec'], [1008, 664])
        for ax, m in ((0, 'mh'), (1, 'mv')):
            pitch = [c['zoom'][ax] / 1024 * RCF.BY_KEY[c['readout'][0]][m] * (c['hbin'], c['vbin'])[ax] for c in cs]
            self.assertLess(max(pitch) / min(pitch), 1.003, ax)    # 1025 (R2) is 0.1 %

    def test_each_recipe_its_own_visible(self):
        for cell in ((*OG, 1008, 672), (*OG, 2016, 1346), (*SQ, 1344, 1344)):
            cs = Q.qualities(*cell, tol=0.02)
            for c in cs:
                self.assertEqual(c['visible'], [c['rec'][0] - 16, c['rec'][1] - 10], cell)
                self.assertEqual(c['nominal'], [cell[2] - 16, cell[3] - 10], cell)
                self.assertTrue(Q.short_ok(c['rec'], cell[2], cell[3], 0.02), cell)
            self.assertGreater(len({tuple(c['visible']) for c in cs}), 1, cell)      # no shared minimum
        self.assertEqual(by_q(Q.qualities(*OG, 2016, 1346, tol=0.02))['3x3fast']['visible'], [2000, 1334])

    def test_beyond_the_tolerance_is_left_out(self):
        """a recipe further short is not listed"""
        cs = by_q(Q.qualities(*OG, 3024, 2020, tol=0.002))           # V2 is 0.3 % short
        self.assertNotIn('14v2', cs)
        cs = by_q(Q.qualities(*OG, 1008, 672, tol=0.005))            # 1x3 is 1.2 % short
        self.assertNotIn('14v3', cs)
        self.assertIn('14v2', cs)

    def test_widen_still_buys_back_1025(self):
        """the 1025 record still takes the WIDEN retry under tol (a short width would show 976 wide)"""
        cs = by_q(Q.qualities(*OG, 1008, 672, tol=0.02))
        self.assertEqual(cs['2x2-h3-v3']['rec'][0], 1008)

    def test_r16_takes_a_slightly_short_frame(self):
        """SQ 1.5K: the new V3 full frame (1330 rows) is 1 % short of the DC's 1344 -> R16 keeps all of it"""
        self.assertNotIn('12v3', by_q(Q.qualities(*SQ, 1344, 1344)))
        c = by_q(Q.qualities(*SQ, 1344, 1344, tol=0.02))['12v3']
        self.assertEqual((Q.rows_of(c), c['rec'], c['visible']), (1330, [1344, 1330], [1328, 1320]))


MUTANTS = {
    'pitch from the delivery (stretch)': ("    bw, bh = (W, H) if nom is None else (max(W, nom[0]), max(H, nom[1]))\n",
                                          "    bw, bh = W, H\n"),
    'visible from the clean RES': ("c['visible'], c['nominal'] = visible_of(c['rec']), visible_of((ow, oh))",
                                   "c['visible'], c['nominal'] = visible_of((ow, oh)), visible_of((ow, oh))"),
    'nominal from the recipe': ("c['visible'], c['nominal'] = visible_of(c['rec']), visible_of((ow, oh))",
                                "c['visible'], c['nominal'] = visible_of(c['rec']), visible_of(c['rec'])"),
    'height tolerance ignored': ("and rh - rec[1] <= tol * rh", "and True"),
    'R16 ignores tol': ("    if tol is not None and rows > RCF.full_rows(key) >= rows * (1 - tol):\n", "    if False:\n"),
    'tol leaks into the default': ("        nom = None if tol is None else (cw", "        nom = None if False else (cw"),
    'margin not the stock one': ("    return [rec[0] - F.MARGIN[0], rec[1] - F.MARGIN[1]]", "    return [rec[0] - 16, rec[1] - 16]"),
}


class VisibleTolMutation(unittest.TestCase):
    def test_every_mutant_is_caught(self):
        global Q
        keep = Q, sys.modules['quality']
        path = HERE / 'quality.py'
        try:
            for name, (old, new) in MUTANTS.items():
                src = path.read_text()
                self.assertEqual(src.count(old), 1, name)
                m = importlib.util.module_from_spec(importlib.util.spec_from_loader('quality', loader=None))
                m.__file__ = str(path)
                sys.modules['quality'] = m
                exec(compile(src.replace(old, new), str(path), 'exec'), m.__dict__)
                Q = m
                r = unittest.TextTestRunner(stream=io.StringIO()).run(
                    unittest.TestLoader().loadTestsFromTestCase(VisibleTol))
                self.assertFalse(r.wasSuccessful(), f'mutant survived: {name}')
        finally:
            Q, sys.modules['quality'] = keep


if __name__ == '__main__':
    unittest.main()
