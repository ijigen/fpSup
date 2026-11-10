#!/usr/bin/env python3
"""Strict, offline execution of the Ver.5.02 live-view rectangle fitter.

Stock characterization needs no compiler. Product regressions use test_apply's
temporary ARM unit build; no shared build output, USB, card or camera is used. The fitter,
rounding helper, integer fit and division all execute the actual ROM bytes.
Unknown execution and writes outside the private stack/rectangle fail closed.

    python3 -B test_lv_fit.py                       # stock + product regression
    python3 -B test_lv_fit.py --stock-only          # stock characterization
    python3 -B test_lv_fit.py --expect-continuous   # MUST fail on unpatched ROM
    python3 -B test_lv_fit.py --expect-continuous --bypass-snap

The last mode injects one branch in emulator memory only, skipping the stock
aspect snap. It checks the repair expectation independently of product code;
it does not validate the SensorLab hook. Mac sandbox/JIT failures are failures,
not skipped tests; run the same offline command with normal approval outside
the sandbox if required.

fit_native(mu, call, source_ptr, work=...) is reusable with test_apply.Cam:
    fit_native(cam.mu, cam.call, cam.call(RATIO, 9), work=WORK + 0x3F0000)
This deliberately uses the slot's real aspect pointer, allowing a guarded
SensorLab fitting hook to identify it. The caller owns the 0x80-byte work area.
"""
import argparse
import functools
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm_const as reg

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('SL_ROOT', HERE.parents[2]))
IMAGE = ROOT / 'out' / 'MAIN_c0000000.bin'
ROM, ROM_BYTES = 0xC0000000, 0x03000000
FIT = 0xC02F4410
SNAP_BEGIN, SNAP_END = 0xC02F44F0, 0xC02F455C
ROUND = 0xC067E244

# Every permitted native range is a complete, named arithmetic routine. A
# division-by-zero/error path is intentionally absent: reaching it must fail.
NATIVE_RANGES = (
    (FIT, 0xC02F466C, 'FUN_c02f4410'),
    (0xC02DAD20, 0xC02DAEC4, 'FUN_c02dad20'),
    (ROUND, 0xC067E2AC, 'FUN_c067e244'),
    (0xC01F8348, 0xC01F8470, 'FUN_c01f8348'),
    (0xC0015938, 0xC00159FC, 'FUN_c0015938'),
    (0xC0015A00, 0xC0016000, 'FUN_c0015a00/FUN_c0015a38'),
)
HEIGHTS = (4040, 3800, 3600, 3520, 3500, 3400, 3300, 3100)
WIDTHS = (6048, 5600, 5088, 5040, 5008, 4800, 4144, 3984, 3504)
LIVE3 = tuple((f'HEIGHT {h}', (6048, h)) for h in HEIGHTS) + tuple(
    (f'WIDTH {w}', (w, 4040)) for w in WIDTHS)
PRODUCT_CASES = ((6048, 3800, 2016, 1266), (6048, 3520, 2016, 1172),
                 (6048, 3500, 2016, 1166), (6048, 3300, 2016, 1100),
                 (5088, 4040, 1696, 1346), (5040, 4040, 1680, 1346),
                 (5008, 4040, 1664, 1346), (4800, 4040, 1600, 1346))


def live3_selection(T, dcw, dch, rw, rh):
    """The live3 11-bit-AD 3x2 recipe/carrier: key 21, HMAX 330, VMAX 7269."""
    return T.recipe(dcw, dch, rw, rh, '3x2', 11, fps=T.Fraction(30018, 1000))[0]


@functools.lru_cache(None)
def image():
    return IMAGE.read_bytes()


def words(mu, address, count):
    return struct.unpack(f'<{count}I', mu.mem_read(address, 4 * count))


def fit_native(mu, call, source, *, work, raster=(1620, 1080), display=(3, 2)):
    """Execute the native fitter with a pair or an existing aspect-pair pointer.

    call(address, r0, r1, r2) must execute and return normally (Cam.call already
    supplies that API). The return tuple is x, y, width, height. source/display
    must remain immutable; only the rectangle is a native output.
    """
    if work & 7:
        raise ValueError('fit work area must be 8-byte aligned')
    source_ptr = source if isinstance(source, int) else work + 0x20
    if not isinstance(source, int):
        mu.mem_write(source_ptr, struct.pack('<2I', *source))
    display_ptr = work + 0x40
    mu.mem_write(display_ptr, struct.pack('<2I', *display))
    mu.mem_write(work, struct.pack('<4I', 0, 0, *raster))
    before = bytes(mu.mem_read(source_ptr, 8)), bytes(mu.mem_read(display_ptr, 8))
    call(FIT, work, source_ptr, display_ptr)
    after = bytes(mu.mem_read(source_ptr, 8)), bytes(mu.mem_read(display_ptr, 8))
    if after != before:
        raise AssertionError('native fitter changed an input aspect pair')
    return words(mu, work, 4)


def continuous_rectangle(source, raster=(1620, 1080)):
    """Independent exact-rational fit oracle, without the native aspect snap.

    This covers the 3:2 LCD fixture, with integer dimensions/centred offsets as
    the stock integer fitter. It is independent of ap_calc / isp_custom.
    """
    n, d = source
    w, h = raster
    if w * d // n == h or h * n // d == w:
        return 0, 0, w, h
    if w * d < h * n:
        nh = w * d // n
        return 0, (h - nh) // 2, w, nh
    nw = h * n // d
    return (w - nw) // 2, 0, nw, h


def stock_ratio(source):
    """Characterization oracle for positive native round-half-away snap tests."""
    n, d = source
    if (18 * n + d) // (2 * d) == 16:
        return 16, 9
    if (4 * n + d) // (2 * d) == 3:
        return 3, 2
    return n, d


class NativeFit:
    """One strict ROM-only fixture; there are no firmware call stubs."""
    DATA, STACK, STOP = 0x10000000, 0x10010000, 0x10030000
    INITIAL_SP = STACK + 0xFFF0

    def __init__(self, *, bypass_snap=False):
        self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.mu.mem_map(ROM, ROM_BYTES)
        self.mu.mem_write(ROM, image()[:ROM_BYTES])
        self.mu.mem_map(self.DATA, 0x1000)
        self.mu.mem_map(self.STACK, 0x10000)
        self.mu.mem_map(self.STOP, 0x1000)
        self.mu.reg_write(reg.UC_ARM_REG_C1_C0_2, 0xF00000)
        self.mu.reg_write(reg.UC_ARM_REG_FPEXC, 0x40000000)
        self.mu.reg_write(reg.UC_ARM_REG_FPSCR, 0)
        self.reached_stop = False
        self.executed = set()
        self.writes = []
        self._output = None
        self.bypass_snap = bypass_snap
        if bypass_snap:
            self.patch(SNAP_BEGIN, 0xEE056A10,
                       0xEA000000 | ((SNAP_END - SNAP_BEGIN - 8) >> 2))
        self.mu.hook_add(UC_HOOK_CODE, self._code)
        self.mu.hook_add(UC_HOOK_MEM_WRITE, self._write)

    def patch(self, address, expected, replacement):
        """Inject an explicitly checked word into emulator memory only."""
        actual, = words(self.mu, address, 1)
        if actual != expected:
            raise AssertionError(f'ROM mismatch at {address:#x}: {actual:#x} != {expected:#x}')
        self.mu.mem_write(address, struct.pack('<I', replacement))

    def _code(self, mu, address, size, _data):
        if address == self.STOP:
            self.reached_stop = True
            mu.emu_stop()
            return
        for lo, hi, name in NATIVE_RANGES:
            if lo <= address and address + size <= hi:
                self.executed.add(name)
                return
        raise AssertionError(f'unapproved native execution at {address:#x}')

    def _write(self, mu, access, address, size, value, _data):
        if self.STACK <= address and address + size <= self.STACK + 0x10000:
            return
        if self._output is not None and self._output <= address and address + size <= self._output + 16:
            self.writes.append((address - self._output, size))
            return
        raise AssertionError(f'unapproved native write at {address:#x}, {size} bytes')

    def call(self, address, *args):
        self.reached_stop = False
        saved = {getattr(reg, f'UC_ARM_REG_R{n}'): 0x55550000 + n for n in range(4, 12)}
        for number, value in saved.items():
            self.mu.reg_write(number, value)
        self.mu.reg_write(reg.UC_ARM_REG_SP, self.INITIAL_SP)
        self.mu.reg_write(reg.UC_ARM_REG_LR, self.STOP)
        for n, value in enumerate(args):
            self.mu.reg_write(getattr(reg, f'UC_ARM_REG_R{n}'), value)
        self.mu.emu_start(address, self.STOP + 4, count=100000)
        if not self.reached_stop:
            raise AssertionError('native arithmetic did not return within its instruction budget')
        if self.mu.reg_read(reg.UC_ARM_REG_SP) != self.INITIAL_SP:
            raise AssertionError('native arithmetic did not restore SP')
        for number, value in saved.items():
            if self.mu.reg_read(number) != value:
                raise AssertionError(f'native arithmetic damaged saved register {number}')
        return self.mu.reg_read(reg.UC_ARM_REG_R0)

    def fit(self, source):
        self._output = self.DATA
        self.writes = []
        try:
            return fit_native(self.mu, self.call, source, work=self.DATA)
        finally:
            self._output = None

    def round(self, value):
        self.mu.reg_write(reg.UC_ARM_REG_D0, struct.unpack('<Q', struct.pack('<d', value))[0])
        self.call(ROUND)
        return self.mu.reg_read(reg.UC_ARM_REG_R0) | self.mu.reg_read(reg.UC_ARM_REG_R1) << 32


class StockFitTests(unittest.TestCase):
    def test_eight_fifths_is_stretched_to_three_halves(self):
        c = NativeFit()
        self.assertEqual(c.fit((8, 5)), (0, 0, 1620, 1080))
        self.assertEqual(continuous_rectangle((8, 5)), (0, 34, 1620, 1012))
        self.assertIn('FUN_c067e244', c.executed)
        self.assertIn('FUN_c01f8348', c.executed)

    def test_live3_source_ratios_follow_the_native_snap(self):
        c = NativeFit()
        for label, source in LIVE3:
            with self.subTest(label=label):
                self.assertEqual(c.fit(source), continuous_rectangle(stock_ratio(source)))

    def test_snap_thresholds(self):
        c = NativeFit()
        cases = (((1249, 1000), (1249, 1000)), ((5, 4), (3, 2)),
                 ((1722, 1000), (3, 2)), ((1723, 1000), (16, 9)),
                 ((1833, 1000), (16, 9)), ((1834, 1000), (1834, 1000)))
        for source, snapped in cases:
            with self.subTest(source=source):
                self.assertEqual(stock_ratio(source), snapped)
                self.assertEqual(c.fit(source), continuous_rectangle(snapped))

    def test_native_rounding_half_away(self):
        c = NativeFit()
        for value, expected in ((2.48, 2), (2.496, 2), (2.5, 3), (2.518, 3), (15.46, 15), (15.55, 16)):
            with self.subTest(value=value):
                self.assertEqual(c.round(value), expected)

    def test_injected_snap_bypass_changes_the_observed_failure(self):
        stock, changed = NativeFit(), NativeFit(bypass_snap=True)
        self.assertNotEqual(stock.fit((8, 5)), changed.fit((8, 5)))
        self.assertEqual(changed.fit((8, 5)), continuous_rectangle((8, 5)))

    def test_strict_execution_guard_rejects_unknown_native_code(self):
        c = NativeFit()
        with self.assertRaisesRegex(AssertionError, 'unapproved native execution'):
            c.call(0xC02F4670)


class ProductFitTests(unittest.TestCase):
    source = None

    def live(self):
        import test_apply as T
        c = T.Cam(src=self.source)
        self.assertEqual(c.init(), T.AP_OK)
        self.assertEqual(c.apply(T.recipe(*T.V1_ARGS)[0]), T.AP_OK)
        c.mu.reg_write(reg.UC_ARM_REG_C1_C0_2, 0xF00000)
        c.mu.reg_write(reg.UC_ARM_REG_FPEXC, 0x40000000)
        c.mu.reg_write(reg.UC_ARM_REG_FPSCR, 0)
        return c

    def eight_fifths(self, c):
        import test_apply as T
        source_ptr = c.call(T.RATIO, 9)
        self.assertTrue(T.MEM <= source_ptr < T.MEM + T.AP_MEM)
        c.mu.mem_write(source_ptr, struct.pack('<2I', 8, 5))
        return source_ptr

    def fit(self, c, source_ptr):
        import test_apply as T
        return fit_native(c.mu, c.call, source_ptr, work=T.WORK + 0x3F0000)

    def test_live_slot_pair_keeps_eight_fifths_through_the_real_fitter(self):
        # The active-slot identity and the pointer returned by H_RATIO are real
        # product state. The 8:5 pair is a deliberate emulator-only fixture,
        # isolating the fitting hook from recipe/readout-plan arithmetic.
        c = self.live()
        got = self.fit(c, self.eight_fifths(c))
        self.assertEqual(got, continuous_rectangle((8, 5)),
                         'the live SensorLab aspect must survive the complete native fit')

    def test_actual_live3_recipe_pairs_keep_their_calculated_aspect(self):
        import test_apply as T
        c = self.live()
        for dcw, dch, rw, rh in PRODUCT_CASES:
            with self.subTest(dc=(dcw, dch), raster=(rw, rh)):
                sel = live3_selection(T, dcw, dch, rw, rh)
                self.assertEqual((sel['key'], sel['hm'], sel['vmax']), (21, 330, 7269))
                self.assertEqual(c.apply(sel), T.AP_OK, c.status())
                source_ptr = c.call(T.RATIO, 9)
                source = words(c.mu, source_ptr, 2)
                self.assertEqual(self.fit(c, source_ptr), continuous_rectangle(source))

    def test_equal_pair_at_an_unrelated_pointer_keeps_the_stock_fit(self):
        c = self.live()
        self.eight_fifths(c)
        self.assertEqual(self.fit(c, (8, 5)), (0, 0, 1620, 1080),
                         'pair equality does not grant ownership of another fitting request')

    def test_inactive_live_slot_keeps_the_stock_fit(self):
        c = self.live()
        source_ptr = self.eight_fifths(c)
        c.put(c.off(9), 0)  # ap_sizes_t exposes offsetof(struct ap, active).
        self.assertEqual(self.fit(c, source_ptr), (0, 0, 1620, 1080))

    def test_playback_active_keeps_the_stock_fit(self):
        import test_apply as T
        c = self.live()
        source_ptr = self.eight_fifths(c)
        pb = c.fn('ap_pb_info', T.MEM) & 0xFFFFFFFF
        c.put(pb + 4 * T.PB_KEYS.index('active'), 1)
        self.assertEqual(self.fit(c, source_ptr), (0, 0, 1620, 1080))

    def test_stock_playback_canvas_keeps_the_stock_fit(self):
        import test_apply as T
        c = self.live()
        source_ptr = self.eight_fifths(c)
        pb = c.fn('ap_pb_info', T.MEM) & 0xFFFFFFFF
        c.put(pb + T.PB_V1_AT + 8, 1)  # The appended public playback-info pbc word.
        self.assertEqual(self.fit(c, source_ptr), (0, 0, 1620, 1080))


class ContinuousFitChecks:
    """Repair contract: intentionally fails with the unchanged ROM fitter."""
    bypass_snap = False

    def test_continuous_eight_fifths_and_live3_ratios(self):
        c = NativeFit(bypass_snap=self.bypass_snap)
        for label, source in (('8:5', (8, 5)),) + LIVE3:
            with self.subTest(label=label):
                self.assertEqual(c.fit(source), continuous_rectangle(source),
                                 'native fit must retain the supplied arbitrary aspect')


def report(bypass_snap=False):
    c = NativeFit(bypass_snap=bypass_snap)
    cases = []
    for label, source in (('8:5', (8, 5)),) + LIVE3:
        cases.append(dict(label=label, source=source, native=c.fit(source),
                          continuous=continuous_rectangle(source), stock_snap=stock_ratio(source)))
    return dict(image=str(IMAGE), image_sha256=hashlib.sha256(image()).hexdigest(),
                bypass_snap=bypass_snap, firmware_stubs=[], native_routines=sorted(c.executed),
                cases=cases, limitations='Synthetic 3:2 LCD fixture and requested source ratios; not the actual '
                'SensorLab calculated aspect pairs, runtime branch selection, QS/LV composition or hardware.')


def product_report():
    """Record the actual apply-generated aspect pairs for the live3 selections."""
    import test_apply as T
    test = ProductFitTests()
    c = test.live()
    cases = []
    for dcw, dch, rw, rh in PRODUCT_CASES:
        sel = live3_selection(T, dcw, dch, rw, rh)
        if c.apply(sel) != T.AP_OK:
            raise AssertionError(c.status())
        source_ptr = c.call(T.RATIO, 9)
        source = words(c.mu, source_ptr, 2)
        got = test.fit(c, source_ptr)
        cases.append(dict(dc=(dcw, dch), raster=(rw, rh), recipe='11-bit AD 3x2',
                          key=sel['key'], hmax=sel['hm'], vmax=sel['vmax'],
                          aspect=source, native=got, continuous=continuous_rectangle(source)))
    return dict(ap_source_sha256=hashlib.sha256((HERE / 'ap.c').read_bytes()).hexdigest(),
                cases=cases, limitations='Real apply-generated slot pairs and direct C02F4410 execution. '
                'The parent Cam stubs settings, LV stop/start and sensor I/O; no LCD composition or hardware.')


FIT_GUARD = ('if (!s || s->is169 || A->pb.active || A->pb.pbc || '
             'f[11] != (u32)(uintptr_t)s->asp) return 0;')
MUTANTS = (
    ('remove_ratio_restore', 'f[6] = s->asp[0]; f[7] = s->asp[1];',
     '/* mutation: leave the native snapped pair */'),
    ('remove_pointer_guard', FIT_GUARD,
     'if (!s || s->is169 || A->pb.active || A->pb.pbc) return 0;'),
    ('remove_playback_active_guard', FIT_GUARD,
     FIT_GUARD.replace('A->pb.active || ', '')),
    ('remove_stock_playback_canvas_guard', FIT_GUARD,
     FIT_GUARD.replace('A->pb.pbc || ', '')),
    ('skip_displaced_movw', 'return 0;                                                  /* replay movw lr:',
     'return 1;                                                  /* mutation: skip movw lr:'),
)


def run_mutants():
    """Bounded ap.c mutants, compiled/executed from separate temporary copies."""
    import test_apply as T
    original = (HERE / 'ap.c').read_text()
    killed = []
    try:
        for label, before, after in MUTANTS:
            if original.count(before) != 1:
                raise AssertionError(f'{label}: mutation target count {original.count(before)} != 1')
            with tempfile.TemporaryDirectory(prefix='sl-lvfit-mutant-') as tmp:
                target = Path(tmp)
                for source in list(HERE.glob('*.c')) + list(HERE.glob('*.h')):
                    shutil.copy2(source, target / source.name)
                (target / 'ap.c').write_text(original.replace(before, after))
                # Compile through the exact cache/API Cam uses before running
                # unittest: build errors must abort, never count as a kill.
                T.built(target)
                ProductFitTests.source = target
                stream = io.StringIO()
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProductFitTests)
                result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
                if result.wasSuccessful():
                    raise AssertionError(f'{label}: SURVIVED\n{stream.getvalue()}')
                if result.testsRun != 6:
                    raise AssertionError(f'{label}: suite did not run six product regressions\n{stream.getvalue()}')
                killed.append(dict(label=label, failed=len(result.failures), errors=len(result.errors)))
                print(f'{label}: KILLED ({len(result.failures)} failures, {len(result.errors)} errors)')
    finally:
        ProductFitTests.source = None
    return killed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect-continuous', action='store_true')
    parser.add_argument('--bypass-snap', action='store_true')
    parser.add_argument('--stock-only', action='store_true')
    parser.add_argument('--mutate', action='store_true', help='run isolated product ap.c fitting mutants')
    parser.add_argument('--report', type=Path, help='write this run\'s native geometry evidence as JSON')
    args = parser.parse_args()
    if args.bypass_snap and not args.expect_continuous:
        parser.error('--bypass-snap requires --expect-continuous')
    if args.stock_only and args.expect_continuous:
        parser.error('--stock-only and --expect-continuous are separate modes')
    if args.mutate:
        if args.stock_only or args.expect_continuous:
            parser.error('--mutate runs the product regression suite separately')
        killed = run_mutants()
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(dict(mutants=killed), indent=2) + '\n')
        return 0
    if args.expect_continuous:
        # Create this intentionally failing contract only for the explicit CLI
        # mode, so normal unittest discovery never collects a permanent red.
        cls = type('ContinuousFitTests', (ContinuousFitChecks, unittest.TestCase),
                   {'bypass_snap': args.bypass_snap})
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(cls)
    else:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(StockFitTests)
        if not args.stock_only:
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ProductFitTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        evidence = report(args.bypass_snap)
        if not args.expect_continuous and not args.stock_only:
            evidence['product'] = product_report()
        args.report.write_text(json.dumps(evidence, indent=2) + '\n')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
