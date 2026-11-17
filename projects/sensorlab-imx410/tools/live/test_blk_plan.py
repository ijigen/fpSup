#!/usr/bin/env python3
"""blk_plan.py: the BLK-SNAP coverage plan.  Offline, no camera.

    python3 -B -m unittest test_blk_plan          # a few seconds
    python3 -B test_blk_plan.py --mutate          # every mutant must make a test fail
"""
import os, pathlib, re, shutil, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blk_plan as P                                          # noqa: E402

BEI = 'G9BqVegakGVFwG9VCJRJeQaaFNwXoNSr0DUxa'                # Bei's 11-16 recipe (HD 6048x1700, 12v2, 29.97p)
B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'


def decode(code, layout):
    """written from site_page.js decodeRecipe, on its own: fields, or raise"""
    nbits = sum(w for _, w in layout)
    assert len(code) == -(-(nbits + 8) // 6), 'length'
    bits = [int(b) for ch in code for b in format(B64.index(ch), '06b')]
    pos, f = 0, {}
    for k, w in layout:
        f[k] = int(''.join(map(str, bits[pos:pos + w])), 2)
        pos += w
    crc = 0
    for b in bits[:nbits]:
        top = (crc >> 7 & 1) ^ b
        crc = (crc << 1) & 0xFF
        crc ^= 0x07 if top else 0
    assert int(''.join(map(str, bits[pos:pos + 8])), 2) == crc, 'crc'
    assert not any(bits[pos + 8:]), 'pad'
    return f


class Plan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.consts = P.page_consts()
        cls.data, cls.recs = P.load_list()
        cls.fine, cls.coarse = P.plan(), P.plan(coarse=True)

    def test_bei_recipe_code_is_reproduced_bit_for_bit(self):
        rc = next(r for r in self.recs if r['cell'] == 'HD:6048x1700' and r['r']['key'] == '12v2')
        f = P.qr_fields(rc, self.consts, self.data['clk'], self.data['vmax_max'], 29.97)
        self.assertEqual(P.qr_pack(f, self.consts['qr_fields']), BEI)
        self.assertEqual(decode(BEI, self.consts['qr_fields'])['key'], self.consts['key_names'].index('12v2'))

    def test_every_code_decodes_to_its_own_recipe(self):
        for p in (self.fine, self.coarse):
            for t in p['takes']:
                f = decode(t['code'], self.consts['qr_fields'])
                self.assertEqual(f, t['fields'], t['cell'])
                self.assertEqual(self.consts['key_names'][f['key']], t['key'])
                self.assertEqual((f['ww'], f['wh']), tuple(t['win']))

    def test_every_recipe_is_in_exactly_one_stratum_and_every_stratum_is_taken(self):
        for coarse, p in ((False, self.fine), (True, self.coarse)):
            strata = {P.stratum(r, coarse) for r in self.recs}
            taken = {tuple(t['stratum']) for t in p['takes'] if t['phase'] == 1}
            self.assertEqual(taken, strata)
            self.assertEqual(p['strata'], len(strata))
            self.assertEqual(sum(t['members'] for t in p['takes'] if t['phase'] == 1) // len(p['isos']), len(self.recs))

    def test_each_representative_belongs_to_its_stratum_at_every_iso(self):
        by = {}
        for t in self.fine['takes']:
            if t['phase'] != 1:
                continue
            rc = next(r for r in self.recs if (r['cell'], r['r']['key'], r['label']) == (t['cell'], t['key'], t['label']))
            self.assertEqual(list(P.stratum(rc)), t['stratum'])
            by.setdefault(tuple(t['stratum']), set()).add(t['iso'])
        self.assertTrue(all(v == set(P.ISO_DEFAULT) for v in by.values()))

    def test_the_clamp_factor_is_core_c_rule(self):
        def clamp(w, h, mh=1, mv=1):
            rc = dict(r=dict(win=[w, h], zoom=[1024, 1024], hbin=1, vbin=1, sw=w, sh=h, mh=mh, mv=mv, key='12'))
            return P.stratum(rc)[1] == 'clamp'
        self.assertTrue(clamp(6048, 3402))          # 1.778: stock UHD, the video clamp is on
        self.assertTrue(clamp(6048, 1701, mv=2))    # Bei's take: V2, 1701 merged rows = 3402 sensor rows
        self.assertFalse(clamp(6048, 1701))         # the same rows unmerged: 3.56
        self.assertFalse(clamp(3024, 2014, mv=2))   # smc 12v2 3024x4040 > 3024x2014: 0.75
        self.assertFalse(clamp(6048, 4040))         # 1.497
        self.assertFalse(clamp(17, 10))             # 1.7 exactly: off (strict)
        self.assertFalse(clamp(20, 10))             # 2.0 exactly: off (strict)
        self.assertTrue(clamp(171, 100))

    def test_window_and_crct_factors(self):
        base = dict(win=[6048, 4040], zoom=[2048, 2048], hbin=1, vbin=1, sw=6048, sh=4040, mh=1, mv=1, key='12')
        st = lambda **k: P.stratum(dict(r=dict(base, **k)))
        self.assertEqual(st()[3:], ('-', 'full'))
        self.assertEqual(st(sh=3402)[4], 'win')
        self.assertEqual(st(mv=2, sh=2014)[4], 'full')
        self.assertEqual(st(mv=2, sh=2006)[4], 'full')          # 8 rows short of the V2 full height: still full
        self.assertEqual(st(mv=2, sh=2005)[4], 'win')
        self.assertEqual(st(mv=2, sh=1701)[4], 'win')
        self.assertEqual(st(zoom=[1024, 2049])[2], 'RWZM')     # RWZM on one axis only (HD 6048x1700 '12')
        self.assertEqual(st(zoom=[1024, 1024])[2], '1:1')
        self.assertEqual(st(vbin=3)[3], 'crct')
        self.assertEqual(st(key='12v2w18')[0], '12v2')

    def test_phase_zero_is_the_formula_check(self):
        z = [t for t in self.fine['takes'] if t['phase'] == 0]
        self.assertEqual({(t['cell'], t['key']) for t in z}, set(P.VALIDATE))
        self.assertEqual(sorted({t['iso'] for t in z}), [100, 3200])
        self.assertEqual(next(t['code'] for t in z if t['key'] == '12v2'), BEI)
        self.assertEqual({t['stratum'][1] for t in z if t['cell'].startswith('HD')}, {'clamp'})
        self.assertEqual({t['stratum'][1] for t in z if t['cell'].startswith('OG')}, {'-'})
        self.assertEqual({t['stratum'][2] for t in z}, {'1:1'})

    def test_rate_is_23976_when_reachable_else_the_maximum(self):
        std = self.consts['std']
        for t in self.fine['takes']:
            if t['phase'] != 1:
                continue
            rc = next(r for r in self.recs if (r['cell'], r['r']['key'], r['label']) == (t['cell'], t['key'], t['label']))
            f = t['fields']
            if f['fps'] == 30:
                self.assertEqual(f['vmax'], rc['lo'])
                v = -(-self.data['clk'] // (rc['hm'] * 23.976))
                self.assertFalse(rc['lo'] <= v <= self.data['vmax_max'], 'it reaches 23.976')
            else:
                self.assertEqual(std[f['fps']], 23.976)
                self.assertGreaterEqual(f['vmax'], rc['lo'])
                self.assertLessEqual(f['vmax'], self.data['vmax_max'])

    def test_deterministic(self):
        self.assertEqual(P.plan(), self.fine)

    def test_the_representative_has_the_median_window_area(self):
        groups = {}
        for r in self.recs:
            groups.setdefault(P.stratum(r), []).append(r)
        for t in self.fine['takes']:
            if t['phase'] != 1:
                continue
            areas = sorted(m['r']['win'][0] * m['r']['win'][1] for m in groups[tuple(t['stratum'])])
            self.assertEqual(t['win'][0] * t['win'][1], areas[(len(areas) - 1) // 2], t['stratum'])


MUTANTS = [
    ("    clamp = 17 * den < 10 * num < 20 * den", "    clamp = 17 * den <= 10 * num < 20 * den", 'test_the_clamp_factor_is_core_c_rule'),
    ("    num, den = r['sw'] * r['mh'], r['sh'] * r['mv']", "    num, den = r['win'][0], r['win'][1]", 'test_the_clamp_factor_is_core_c_rule'),
    ("    path = '1:1' if r['zoom'] == [1024, 1024] else 'RWZM'", "    path = '1:1' if r['zoom'][0] == 1024 else 'RWZM'",
     'test_window_and_crct_factors'),
    ("    crct = 'crct' if (r['hbin'], r['vbin']) != (1, 1) else '-'", "    crct = 'crct' if r['hbin'] != 1 else '-'",
     'test_window_and_crct_factors'),
    ("FULL_ROWS = {1: 4040, 2: 2014, 3: 1358, 6: 672}", "FULL_ROWS = {1: 4040, 2: 2020, 3: 1358, 6: 672}",
     'test_window_and_crct_factors'),
    ("    return re.sub(r'w(18|03|2C|2B)$', '', key)", "    return key", 'test_window_and_crct_factors'),
    ("        if top:\n            crc ^= 0x07", "        if top:\n            crc ^= 0x05", 'test_bei_recipe_code_is_reproduced_bit_for_bit'),
    ("                ad={11: 0, 12: 1, 14: 2}[r['ad']]", "                ad={11: 1, 12: 0, 14: 2}[r['ad']]",
     'test_bei_recipe_code_is_reproduced_bit_for_bit'),
    ("    if lo <= v <= vmax_max:", "    if v <= vmax_max:", 'test_rate_is_23976_when_reachable_else_the_maximum'),
    ("        for iso in isos:", "        for iso in isos[:1]:", 'test_each_representative_belongs_to_its_stratum_at_every_iso'),
    ("    med = statistics.median_low(areas)", "    med = areas[0]", 'test_the_representative_has_the_median_window_area'),
]


def mutate():
    bad = []
    src = (HERE / 'blk_plan.py').read_text()
    for i, (old, new, test) in enumerate(MUTANTS):
        if src.count(old) != 1:
            print(f'mutant {i:2d} text not found once'); bad.append(i); continue
        t = pathlib.Path(tempfile.mkdtemp(prefix='blkplan-mut-'))
        (t / 'blk_plan.py').write_text(src.replace(old, new))
        shutil.copy(HERE / 'test_blk_plan.py', t / 'test_blk_plan.py')
        (t / 'blk_plan.py').write_text((t / 'blk_plan.py').read_text().replace(
            "HERE = pathlib.Path(__file__).resolve().parent", f"HERE = pathlib.Path({str(HERE)!r})"))
        env = dict(os.environ, PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix='blkplan-pyc-'))
        r = subprocess.run([sys.executable, '-B', '-m', 'unittest', f'test_blk_plan.Plan.{test}'], cwd=t,
                           capture_output=True, text=True, env=env)
        ok = r.returncode != 0 and re.search(r'Ran [1-9]', r.stderr)
        print(f'mutant {i:2d} {test[:60]:60s} {"caught" if ok else "SURVIVED"}')
        if not ok:
            bad.append(i)
        shutil.rmtree(t, ignore_errors=True)
    print('all caught' if not bad else f'survived: {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(mutate())
    unittest.main()
