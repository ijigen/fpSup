#!/usr/bin/env python3
"""H_BLV (2026-11-16): the DNG BlackLevel value of our recipes, corrected for the clamp's pedestal move and the 1:1 12-bit
truncation (validation/20261116-blk-snap/LOG.md).  Offline: unicorn on the real image -- FUN_c02ca190 from its rational
set-up (C02CA254) through the hooked call to the tag writer FUN_c05a4bc0 (stubbed: it records what it was handed).

    cd projects/sensorlab-imx410/apply
    python3 -B -m unittest test_blv
    python3 -B test_blv.py --mutate
"""
import os, pathlib, re, shutil, struct, subprocess, sys, tempfile, unittest
from fractions import Fraction

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_argv = list(sys.argv)
import test_apply as T                                      # noqa: E402
import test_blk_snap as S                                   # noqa: E402
sys.argv[:] = _argv
from unicorn import UC_HOOK_CODE                            # noqa: E402
from unicorn.arm_const import (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_PC,  # noqa: E402
                               UC_ARM_REG_LR)

WRITER, SETUP, AFTER = 0xC05A4BC0, 0xC02CA254, 0xC02CA2A4
PED = 0x300F0318
BLACK12 = 0x3FFF8                                           # what +0x208 gives at 12 bit (255.992 DN12 x 1024)
# (name, recipe args, recorded bits, 1:1) -- written out here, not taken from ap_calc.c
CASES = {
    '12_1x1': (dict(args=(6048, 4040, 6048, 4040, '1x1', 12), fps=Fraction(15)), 12, True),
    '12_rwzm': (dict(args=T.V1_ARGS, fps=Fraction(15)), 12, False),
    '14ad_rwzm_12c': (dict(args=(6048, 4040, 3024, 2020, '1x1', 14), fps=Fraction(15)), 12, False),
    '14_1x1': (dict(args=(6048, 4040, 6048, 4040, '1x1', 14), fps=Fraction(15)), 14, True),
    'fast_1x1': (dict(args=(6048, 4040, 6048, 4040, '1x1', 11), fps=Fraction(15)), 12, True),
}
GAIN = 0xC343B5AC                                           # the sensor gain word (imager +0x24), the firmware's v35 test


def want(case, ped, gain=0):
    """the release rule, written out here: the pedestal term always; -0.375 DN12 for every 12-bit 1:1 record (normal
    or fast AD), at every gain -- the replay of 431 takes chose it over the exceptions (LOG.md 11-16)"""
    _, bits, one = CASES[case]
    return (ped - 1024) * (1024 if bits == 14 else 256) - (384 if bits == 12 and one else 0)


def cam_for(case=None):
    cam = S.snap_cam(defines=())
    got = []

    def writer(mu, addr, size, data):
        sp = mu.reg_read(UC_ARM_REG_SP)
        n, p = struct.unpack('<2I', mu.mem_read(sp, 8))
        got.append((n, struct.unpack('<8I', mu.mem_read(p, 32)), mu.reg_read(UC_ARM_REG_R4)))
    cam.mu.mem_write(WRITER, struct.pack('<I', 0xE12FFF1E))   # bx lr: the writer only records (not Cam.stub: named)
    cam.mu.hook_add(UC_HOOK_CODE, writer, begin=WRITER, end=WRITER)
    cam.got = got
    if case:
        rc = CASES[case][0]
        sel = T.recipe(*rc['args'], fps=rc['fps'])
        assert cam.apply(sel[0]) == T.AP_OK, case
        cam.call(T.PICKER, 0, T.TAB3, cam.key('UHD24'))
        cam.call(T.PICKER, 0, T.TAB3, cam.key('UHD23_98'))
    return cam


def blk(cam):
    """H_BLK, as FUN_c02ca190 makes it (the mode-0 branch): -> the bits it answers"""
    return S.hook_call(cam, 0xC02CA218, 0x08)


def blv(cam, black, ped, gain=0):
    """from the rationals' set-up through the hooked writer call: -> (count, the 8 words, r4)"""
    cam.put(PED, ped | ped << 16)
    cam.put(GAIN, gain)
    cam.mu.reg_write(UC_ARM_REG_R12, black)
    cam.mu.reg_write(UC_ARM_REG_R4, 0)
    cam.mu.reg_write(UC_ARM_REG_R5, T.WORK + 0x7000)
    cam.mu.reg_write(UC_ARM_REG_SP, T.STACK - 0x3000)
    n0 = len(cam.got)
    cam.mu.emu_start(SETUP, AFTER, count=200000)
    if cam.error:
        raise cam.error
    assert len(cam.got) == n0 + 1, 'the writer was not reached once'
    return cam.got[-1]


def nums(w):
    return [w[i] for i in (0, 2, 4, 6)], [w[i] for i in (1, 3, 5, 7)]


class BlvTests(unittest.TestCase):
    def expect(self, case, ped, gain=0):
        cam = cam_for(case)
        _, bits, one = CASES[case]
        self.assertEqual(blk(cam), bits, case)
        black = BLACK12 << 2 if bits == 14 else BLACK12
        n, w, _ = blv(cam, black, ped, gain)
        num, den = nums(w)
        d = want(case, ped, gain)
        self.assertEqual(n, 4)
        self.assertEqual(den, [0x400] * 4)
        self.assertEqual(num, [(black + d) & 0xFFFFFFFF] * 4, (case, ped))
        return num[0] / 1024

    def test_pedestal_and_truncation_per_recipe(self):
        for case in CASES:
            for ped in (1021, 1022, 1023, 1024):
                with self.subTest(case=case, ped=ped):
                    self.expect(case, ped)

    def test_the_gain_word_does_not_change_the_correction(self):
        for gain in (0, 0x3D9, 0x500, 0x501, 0x60A, 0x800, 0x801, 0x807, 0x9EC, 0xC03):
            for case in ('12_1x1', '12_rwzm', '14_1x1', 'fast_1x1'):
                with self.subTest(case=case, gain=hex(gain)):
                    self.expect(case, 1021, gain)

    def test_every_recipe_has_the_video_clamp_bits(self):
        """0.0.9test: a 3:2 readout (the formula leaves the bits off: stock's stills modes) records with them on"""
        for args, hd in (((6048, 4040, 6048, 2020, '1x2', 14), False), ((6048, 4040, 6048, 4040, '1x1', 12), False),
                         ((6048, 3402, 6048, 1700, '1x2', 12), True)):
            sel, c, plan, rows, spec = T.recipe(*args, fps=Fraction(15))
            raw = T.smc.create(plan)[1]['R38']
            self.assertEqual(bool(raw[4] & 8) and (raw[0x19] & 0xC0) == 0xC0, hd, args)
            cam = cam_for(None)
            self.assertEqual(cam.apply(sel), T.AP_OK)
            row = cam.row_via_lookup(3, cam.status()['mode_id'])
            self.assertEqual(row[4] & 8, 8, args)
            self.assertEqual(row[0x19] & 0xC0, 0xC0, args)
            self.assertEqual(bytes(row[8:0x18]), bytes(raw[8:0x18]), 'the clamp geometry is the formula\'s')

    def test_bei_take_numbers(self):
        """12v2-like 1:1 12 bit, pedestal 1021: 255.992 -> 254.867 (data measured 254.776; 11-16 table)"""
        v = self.expect('12_1x1', 1021)
        self.assertAlmostEqual(v, BLACK12 / 1024 - 0.75 - 0.375, places=6)

    def test_stock_is_untouched(self):
        cam = cam_for(None)                                  # nothing applied: the stock slot
        self.assertEqual(blk(cam), 12)
        _, w, _ = blv(cam, BLACK12, 1021)
        self.assertEqual(nums(w), ([BLACK12] * 4, [0x400] * 4))

    def test_applied_but_not_picked_is_untouched(self):
        """our slot is live but the picker has not handed it out: the record is stock's"""
        cam = cam_for(None)
        sel = T.recipe(6048, 4040, 6048, 4040, '1x1', 12, fps=Fraction(15))
        self.assertEqual(cam.apply(sel[0]), T.AP_OK)
        self.assertEqual(blk(cam), 12)
        _, w, _ = blv(cam, BLACK12, 1021)
        self.assertEqual(nums(w)[0], [BLACK12] * 4)

    def test_without_a_fresh_blk_nothing_moves(self):
        cam = cam_for('12_1x1')
        blk(cam)
        _, w1, _ = blv(cam, BLACK12, 1021)
        _, w2, _ = blv(cam, BLACK12, 1021)                   # a second writer call with no H_BLK before it
        self.assertNotEqual(nums(w1)[0], [BLACK12] * 4)
        self.assertEqual(nums(w2)[0], [BLACK12] * 4)

    def test_a_template_it_does_not_know_is_left_alone(self):
        cam = cam_for('12_1x1')
        blk(cam)
        tpl = 0xC09704C4
        old = cam.w(tpl + 4)
        cam.put(tpl + 4, 0x200)                              # a denominator that is not 0x400
        try:
            _, w, _ = blv(cam, BLACK12, 1021)
        finally:
            cam.put(tpl + 4, old)
        self.assertEqual(nums(w)[0], [BLACK12] * 4)

    def test_a_pedestal_outside_the_table_is_left_alone(self):
        for ped in (1011, 1028, 0x700):
            with self.subTest(ped=ped):
                cam = cam_for('12_1x1')
                blk(cam)
                _, w, _ = blv(cam, BLACK12, ped)
                self.assertEqual(nums(w)[0], [BLACK12] * 4)
        for ped in (1012, 1027):                             # the table's two ends are used
            with self.subTest(ped=ped):
                self.expect('12_1x1', ped)
                self.expect('14_1x1', ped)

    def test_the_core_holds_no_formula(self):
        """H_BLV's body: a lookup and an add -- no multiply, no truncation constant, no recipe test (Bei 11-16)"""
        src = (HERE / 'ap.c').read_text()
        body = src[src.index('    case H_BLV: {'):]
        body = body[:body.index('        return 0;                                                    /* down')]
        code = re.sub(r'/\*.*?\*/', '', body, flags=re.S).replace('0x400u', '').replace('0x3FFFu', '')
        for bad in ('384', '1024', '256', 'one2one', 'rec14', 'zh', 'hbin', 'vbin'):
            self.assertNotIn(bad, code, bad)
        self.assertIsNone(re.search(r'[\w)\]]\s*\*\s*[\w(]', code.replace('u32 *v', '').replace('struct ap_slot *s', '')
                                    .replace('(u32 *)', '')), 'a multiplication')

    def test_a_table_for_another_depth_is_not_used(self):
        """a 12-bit recipe's table never lands on a 14-bit tag (plane code 1: the depth query answers 14)"""
        cam = cam_for('12_1x1')
        self.assertEqual(S.hook_call(cam, 0xC02CA218, 0x08, 1), 14)
        _, w, _ = blv(cam, BLACK12 << 2, 1021)
        self.assertEqual(nums(w)[0], [BLACK12 << 2] * 4)

    def test_pedestal_1024_and_rwzm_is_a_no_op(self):
        cam = cam_for('12_rwzm')
        blk(cam)
        _, w, _ = blv(cam, BLACK12, 1024)
        self.assertEqual(nums(w)[0], [BLACK12] * 4)


MUTANTS = [   # (file, old, new, the test that must fail)
    ('ap_calc.c', '    o->mode.r38[0x04] |= 0x08u;\n', '', 'test_every_recipe_has_the_video_clamp_bits'),
    ('ap_calc.c', '    o->mode.r38[0x19] |= 0xC0u;', '    o->mode.r38[0x19] |= 0x40u;', 'test_every_recipe_has_the_video_clamp_bits'),
    ('ap_calc.c', ' - (one ? 384 : 0);', ';', 'test_pedestal_and_truncation_per_recipe'),
    ('ap_calc.c', 'w->spec.bits == 14 ? dped * 1024 : dped * 256', 'w->spec.bits == 14 ? dped * 256 : dped * 256',
     'test_pedestal_and_truncation_per_recipe'),
    ('ap_calc.c', 'u32 one = w->spec.zh == 1024 && w->spec.zv == 1024 && w->spec.hbin == 1 && w->spec.vbin == 1;',
     'u32 one = 1;', 'test_pedestal_and_truncation_per_recipe'),
    ('ap_calc.c', ' - (one ? 384 : 0);', ' - (one && q->ad == 12 ? 384 : 0);', 'test_pedestal_and_truncation_per_recipe'),
    ('ap_calc.c', '#define APC_BLV_BASE 1012u', '#define APC_BLV_BASE 1013u', 'test_a_pedestal_outside_the_table_is_left_alone'),
    ('ap.c', '    for (u32 i = 0; i < 16u; i++) s->blv_tab[i] = o->blv_tab[i];', '',
     'test_pedestal_and_truncation_per_recipe'),
    ('ap.c', '        s32 d = s->blv_tab[idx];', '        s32 d = AP_W(0xC343B5ACu) == 0x60Au ? 0 : s->blv_tab[idx];',
     'test_the_gain_word_does_not_change_the_correction'),
    ('ap.c', 'if (bits != s->blv_bits || idx >= 16u)', 'if (idx >= 16u)', 'test_a_table_for_another_depth_is_not_used'),
    ('ap.c', 'if (bits != s->blv_bits || idx >= 16u)', 'if (bits != s->blv_bits)', 'test_a_pedestal_outside_the_table_is_left_alone'),
    ('ap.c', '        A->blk_ours = 0;', '', 'test_without_a_fresh_blk_nothing_moves'),
    ('ap.c', 'v[1] != 0x400u ||', '', 'test_a_template_it_does_not_know_is_left_alone'),
    ('ap.c', 'if (!ours || !s || (bits != 12u && bits != 14u)) return 0;', 'if (!s) return 0;', 'test_stock_is_untouched'),
    ('ap.c', '(s32)v[i] + d', '(s32)v[i] - d', 'test_pedestal_and_truncation_per_recipe'),
    ('ap.c', 'A->blk_ours = s && ap_rec_picked(A) && A->pick_bits == 12u;', 'A->blk_ours = 1;',
     'test_applied_but_not_picked_is_untouched'),
    ('ap.c', '        s32 d = s->blv_tab[idx];', '        s32 d = (s32)(idx + APC_BLV_BASE - 1024u) * 256;',
     'test_the_core_holds_no_formula'),
]


def mutate():
    bad = []
    for i, (fname, old, new, test) in enumerate(MUTANTS):
        t = pathlib.Path(tempfile.mkdtemp(prefix='blv-mut-'))
        for f in ('ap.c', 'ap_calc.c', 'ap.h', 'pb_glyph.h', 'pb_glyph.py', 'pb_page.h', 'build_apply.py',
                  'test_apply.py', 'test_blk_snap.py', 'test_blv.py'):
            if (HERE / f).exists():
                shutil.copy(HERE / f, t / f)
        shutil.copy(S.LIVE / 'blk_snap.py', t / 'blk_snap.py')
        src = (t / fname).read_text()
        if src.count(old) != 1:
            print(f'mutant {i:2d} text not found once'); bad.append(i); continue
        (t / fname).write_text(src.replace(old, new))
        env = dict(os.environ, SL_ROOT=str(T.ROOT), PYTHONPYCACHEPREFIX=tempfile.mkdtemp(prefix='blv-pyc-'))
        r = subprocess.run([sys.executable, '-B', '-m', 'unittest', f'test_blv.BlvTests.{test}'], cwd=t,
                           capture_output=True, text=True, env=env)
        ok = r.returncode != 0 and re.search(r'Ran [1-9]', r.stderr)
        print(f'mutant {i:2d} {test[:56]:56s} {"caught" if ok else "SURVIVED"}')
        if not ok:
            bad.append(i)
        shutil.rmtree(t, ignore_errors=True)
    print('all caught' if not bad else f'survived: {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(mutate())
    unittest.main()
