#!/usr/bin/env python3
"""jfit.c (the joint fit in C) against the Python reference (projects/lut-sup/probes/joint_fit_eval.py).

Host build only (clang -O2 -shared): the same C source the sup compiles for the camera.  Checks:
  1. the chain + Lab for a fitted teal_orange / fade solution and random perturbations: max |ΔLab| small;
  2. the fit from the same start lands at a cost no worse than Python's and an equal held-out ΔE;
  3. mutations (sparse window too narrow, a wrong CEQ wrap) are caught.
"""
import ctypes
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'projects/lut-sup/probes'))
import lv_fit as F                    # noqa: E402
import lut_batch_eval as E            # noqa: E402
import joint_fit_eval as JF           # noqa: E402
from cube import Cube                 # noqa: E402

SOL = ROOT / 'projects/lut-sup/validation/20261104-lut-joint-02'
FP = ctypes.POINTER(ctypes.c_float)


def build(src_text=None, defines=()):
    td = Path(tempfile.mkdtemp())
    src = HERE / 'native/host/jfit_host.c'
    if src_text is not None:                       # a mutant: copy the tree with one file changed
        (td / 'native/host').mkdir(parents=True)
        (td / 'native/jfit.c').write_text(src_text)
        (td / 'native/host/jfit_host.c').write_text(src.read_text())
        src = td / 'native/host/jfit_host.c'
    lib = td / 'jfit.dylib'
    subprocess.run(['clang', '-O2', '-shared', '-fPIC', *defines, '-o', str(lib), str(src)], check=True)
    L = ctypes.CDLL(str(lib))
    L.jf_host_lab.argtypes = [FP, FP, ctypes.c_uint32, FP, FP]
    L.jf_host_fit.argtypes = [FP, FP, ctypes.c_uint32, FP, FP, FP, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    L.jf_host_fit.restype = ctypes.c_float
    L.jf_host_dense.argtypes = [ctypes.c_int]
    return L


def f32(a):
    """float32, contiguous; a 140-parameter P padded with JFIT v6's CKNEE off (native P is 148: jfit.c JF_NP)"""
    a = np.asarray(a)
    if a.ndim == 1 and len(a) == 140:
        a = np.r_[a, [8.0, 1.0] * 4]
    return np.ascontiguousarray(a, dtype=np.float32)


def ptr(a):
    return a.ctypes.data_as(FP)


def c_lab(L, P, bt, xs):
    P, bt, xs = f32(P), f32(bt / F.TONE_MAX), f32(xs)
    out = np.zeros_like(xs)
    L.jf_host_lab(ptr(P), ptr(bt), len(xs), ptr(xs), ptr(out))
    return out


def py_lab(P, bt, xs):
    return F.lab709(JF.chain(xs, P, bt, split=False))


class JfitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.L = build()
        cls.sols = {n: np.load(SOL / f'{n}_joint.npy') for n in ('teal_orange', 'fade')}

    def test_chain_matches_python(self):
        rng = np.random.default_rng(3)
        xs = E.lvb_samples()
        for name, sol in self.sols.items():
            P, bt = sol[:140].copy(), sol[140:].reshape(3, F.N_TONE)
            for trial in range(4):
                Q = P.copy()
                if trial:
                    Q[:9] += rng.normal(0, 0.02, 9); Q[51:75] += rng.normal(0, 3, 24); Q[123:] += rng.normal(0, 0.01, 17)
                Q[9:18] = Q[:9]
                d = np.abs(c_lab(self.L, Q, bt, xs) - py_lab(Q, bt, xs)).max()
                self.assertLess(d, 0.05, (name, trial, d))

    def fit_both(self, L, name):
        sol = self.sols[name]
        case = next(x for x in E.cases(SOL / 'cubes') if x[0] == name)
        target = F.make_target(Cube.read(case[1]), **case[2])
        fit = E.fit_lvb(target, 100)
        xs = E.lvb_samples()
        want = F.lab709(target(xs, 100))
        w = np.sqrt((1 - 2.5 * F.saturation(target(xs, 0)) / 8) ** 8)
        P0 = np.r_[np.eye(3).ravel(), np.eye(3).ravel(), np.zeros(27), E.POST_ID]   # the identity start
        t = time.time(); Pp, bt, cost_py = JF.fit_joint(target, 100, fit, E.POST_ID.copy(), split=False, start_M=np.eye(3))
        tp = time.time() - t
        Pc = f32(P0); es = (ctypes.c_uint32 * 2)()
        t = time.time(); cost_c = L.jf_host_fit(ptr(Pc), ptr(f32(bt / F.TONE_MAX)), len(xs), ptr(f32(xs)), ptr(f32(want)),
                                               ptr(f32(w)), 10, es); tc = time.time() - t
        sets = E.sample_sets()
        dp = E.score_set(target(sets['色卡'], 100), JF.chain(sets['色卡'], Pp, bt, split=False)).mean()
        dc = E.score_set(target(sets['色卡'], 100), JF.chain(sets['色卡'], Pc.astype(float), bt, split=False)).mean()
        return cost_py, float(cost_c), dp, dc, tp, tc, list(es)

    def test_fit_matches_python(self):
        for name in ('fade', 'teal_orange'):
            cost_py, cost_c, dp, dc, tp, tc, es = self.fit_both(self.L, name)
            print(f'\n  {name}: cost py {cost_py:.1f} c {cost_c:.1f}  色卡 ΔE py {dp:.2f} c {dc:.2f}  '
                  f'time py {tp:.1f}s c {tc:.2f}s  evals/steps {es}')
            self.assertLess(cost_c, cost_py * 1.10)
            self.assertLess(dc, dp + 0.3)

    def one_step(self, L, name, dense):
        sol = self.sols[name]; P, bt = sol[:140].copy(), sol[140:].reshape(3, F.N_TONE)
        case = next(x for x in E.cases(SOL / 'cubes') if x[0] == name)
        target = F.make_target(Cube.read(case[1]), **case[2])
        xs = E.lvb_samples(); want = F.lab709(target(xs, 100))
        w = np.sqrt((1 - 2.5 * F.saturation(target(xs, 0)) / 8) ** 8)
        P = P.copy(); P[51:75] += 2.0                    # off the optimum: every column matters
        Pc = f32(P); es = (ctypes.c_uint32 * 2)()
        L.jf_host_dense(1 if dense else 0)
        L.jf_host_fit(ptr(Pc), ptr(f32(bt / F.TONE_MAX)), len(xs), ptr(f32(xs)), ptr(f32(want)), ptr(f32(w)), 1, es)
        L.jf_host_dense(0)
        return Pc.astype(float)[:len(P)] - P

    def test_sparse_jacobian_equals_dense(self):
        for name in ('teal_orange', 'fade'):
            a, b = self.one_step(self.L, name, False), self.one_step(self.L, name, True)
            self.assertLess(np.abs(a - b).max(), 1e-3 + 1e-3 * np.abs(b).max(), name)

    def test_damping_retries_go_further(self):
        """11-05: a refused step is retried with 10x the damping (JF_DAMP_TRIES) instead of ending the fit; with the
        grey axis (jft.grey_samples) and 20 iterations the cost ends lower than "first refusal stops" (TRIES 1)."""
        import jft
        old = build(defines=('-DJF_DAMP_TRIES=1',))
        gains = []
        for name in ('teal_orange', 'fade'):
            case = next(x for x in E.cases(SOL / 'cubes') if x[0] == name)
            target = F.make_target(Cube.read(case[1]), **case[2])
            fit = E.fit_lvb(target, 100); bt = fit['tone'].astype(float)
            if fit['shift']:
                bt = np.stack([np.interp(np.arange(F.N_TONE) / 2 ** fit['shift'], np.arange(F.N_TONE), bt[k]) for k in range(3)])
            xs = np.r_[E.lvb_samples(), jft.grey_samples()]; want = F.lab709(target(xs, 100))
            w = np.sqrt((1 - 2.5 * F.saturation(target(xs, 0)) / 8) ** 8)
            P0 = np.r_[np.eye(3).ravel(), np.eye(3).ravel(), np.zeros(27), E.POST_ID]
            costs = []
            for L in (old, self.L):
                Pc = f32(P0); es = (ctypes.c_uint32 * 2)()
                costs.append(float(L.jf_host_fit(ptr(Pc), ptr(f32(bt / F.TONE_MAX)), len(xs), ptr(f32(xs)), ptr(f32(want)),
                                                 ptr(f32(w)), jft.CONV_ITERS, es)))
            print(f'\n  {name}: cost first-refusal {costs[0]:.1f}  LM {costs[1]:.1f}')
            self.assertLessEqual(costs[1], costs[0] * 1.0001, name)
            gains.append(costs[1] / costs[0])
        self.assertLess(min(gains), 0.98)

    def test_mutants_are_caught(self):
        src = (HERE / 'native/jfit.c').read_text()
        muts = {'窄窗(CEQ ±7.5°)': ('return d > -15.0001f && d < 15.0001f;', 'return d > -7.5f && d < 7.5f;'),
                'CEQ 不繞回': ('int a1 = a == 23 ? 0 : a + 1;', 'int a1 = a == 23 ? 23 : a + 1;')}
        for label, (a, b) in muts.items():
            self.assertEqual(src.count(a), 1, label)
            L = build(src.replace(a, b))
            L.jf_host_dense.argtypes = [ctypes.c_int]
            if label.startswith('CEQ 不繞回'):
                sol = self.sols['teal_orange']; P, bt = sol[:140].copy(), sol[140:].reshape(3, F.N_TONE)
                d = np.abs(c_lab(L, P, bt, E.lvb_samples()) - py_lab(P, bt, E.lvb_samples())).max()
                self.assertGreater(d, 0.5, label)
            else:
                a, b = self.one_step(L, 'teal_orange', False), self.one_step(L, 'teal_orange', True)
                self.assertGreater(np.abs(a - b).max(), 1e-3 + 1e-3 * np.abs(b).max(), label)


# ================================================================ 11-07: the tone-knot sparsity on a monotone curve, the copy
OLD_WINDOW = ("""        int ch = (k - 18) / JF_KN;                                 /* interpolates, moved in the knot's perturbed table? */
        int i0 = (int)pr[ch]; if (i0 > JF_NTONE - 2) i0 = JF_NTONE - 2;   /* (11-07: the curve is monotone -- a knot that */
        const float *pt = J->pert + (k - 18) * JF_NTONE, *t = J->tone + ch * JF_NTONE;   /* lifts a plateau moves every */
        return pt[i0] != t[i0] || pt[i0 + 1] != t[i0 + 1];          /* entry the plateau holds, not just its neighbours) */""",
              """        int ch = (k - 18) / JF_KN, kn = (k - 18) % JF_KN;
        float x = pr[ch] / (float)(JF_NTONE - 1) * (float)(JF_KN - 1);
        return x > (float)kn - 1.0001f && x < (float)kn + 1.0001f;""")
COPY_PER_COLUMN = ("""                float h = jf_step(k), lab[3];
                if (k >= 18 && k < 45) {""", """                float h = jf_step(k), lab[3];
                for (int i = 0; i < JF_NP; i++) Qp[i] = J->P[i];
                if (k >= 18 && k < 45) {""")


def plateau_problem(name):
    """the long-plateau case (a curve flat over 0.35..0.7 code) or a film cube at the repo root (P3-D60 / linear)."""
    if name == 'plateau':
        p = Path(tempfile.mkdtemp()) / 'plateau.cube'
        E.write_cube(p, lambda x: np.where(x < 0.35, x, np.where(x < 0.7, 0.35, x - 0.35)))
        target = F.make_target(Cube.read(p), space='rec709', gamma='gamma24')
    else:
        target = F.make_target(Cube.read(ROOT / name), space='p3-d60', gamma='linear')
    import jft
    fit = E.fit_lvb(target, 100); bt = fit['tone'].astype(float) / F.TONE_MAX
    if fit['shift']:
        bt = np.stack([np.interp(np.arange(F.N_TONE) / 2 ** fit['shift'], np.arange(F.N_TONE), bt[k]) for k in range(3)])
    xs = np.r_[E.lvb_samples(), jft.grey_samples()]; want = F.lab709(target(xs, 100))
    w = np.sqrt((1 - 2.5 * F.saturation(target(xs, 0)) / 8) ** 8)
    return [f32(a) for a in (bt, xs, want, w)]


def fit_c(L, prob, P, iters, dense=False):
    bt, xs, want, w = prob
    Pc = np.array(f32(P), np.float32); es = (ctypes.c_uint32 * 2)()        # a copy: the call writes it
    L.jf_host_dense(1 if dense else 0)
    c = L.jf_host_fit(ptr(Pc), ptr(bt), len(xs), ptr(xs), ptr(want), ptr(w), iters, es)
    L.jf_host_dense(0)
    return Pc, c


class KnotSparsityTests(unittest.TestCase):
    """jf_affects for a tone knot: the curve is cummax'd, so a knot that lifts a plateau moves every entry the plateau
    holds.  The knot's perturbed table (pert) decides: a sample is reached iff one of its two interpolated entries moved."""
    NAMES = ('plateau', 'Kodak2383_1.6K.cube', 'Fujifilm3513DI_1.6K.cube')

    @classmethod
    def setUpClass(cls):
        cls.L = build()
        cls.probs = {n: plateau_problem(n) for n in cls.NAMES}
        P0 = np.r_[np.eye(3).ravel(), np.eye(3).ravel(), np.zeros(27), E.POST_ID]
        cls.P20 = {n: fit_c(cls.L, p, P0, 20)[0] for n, p in cls.probs.items()}      # a fitted solution: knots in use

    def step_gap(self, L):
        out = {}
        for n, p in self.probs.items():
            a, _ = fit_c(L, p, self.P20[n], 1); b, _ = fit_c(L, p, self.P20[n], 1, dense=True)
            out[n] = float(np.abs(a.astype(float) - b.astype(float)).max())
        return out

    def test_sparse_step_equals_every_sample(self):
        gap = self.step_gap(self.L)
        print('\n  sparse vs dense step |dP| max:', {k: f'{v:.1e}' for k, v in gap.items()})
        for n, g in gap.items():
            self.assertLess(g, 1e-5, n)

    def test_the_old_window_is_caught(self):
        src = (HERE / 'native/jfit.c').read_text()
        self.assertEqual(src.count(OLD_WINDOW[0]), 1)
        gap = self.step_gap(build(src.replace(*OLD_WINDOW)))
        print('\n  old window: sparse vs dense |dP| max:', {k: f'{v:.1e}' for k, v in gap.items()})
        self.assertGreater(max(gap.values()), 1e-4)

    def test_one_copy_an_iteration_is_bitwise_the_same(self):
        """the parameters copied once an iteration (each column restores its own and its tied M1) == a copy per column."""
        src = (HERE / 'native/jfit.c').read_text()
        self.assertEqual(src.count(COPY_PER_COLUMN[0]), 1)
        ref = build(src.replace(*COPY_PER_COLUMN))
        P0 = np.r_[np.eye(3).ravel(), np.eye(3).ravel(), np.zeros(27), E.POST_ID]
        for n, p in self.probs.items():
            for start in (P0, self.P20[n]):
                a, ca = fit_c(self.L, p, start, 20); b, cb = fit_c(ref, p, start, 20)
                self.assertEqual(a.tobytes(), b.tobytes(), n)
                self.assertEqual(ca, cb, n)



# ================================================================ 11-10: the CEQ hue order (magenta in Fuji 3513DI / Kodak 2383 greens)
FILM = {'Fuji': 'fp_p3d60_Fuji 3513DI D65.cube', 'Kodak': 'fp_p3d60_Kodak 2383 D65.cube'}
CAMERA_JFT = ROOT / 'projects/lut-sup/private/card-20261110/jft-20261110'     # read back from the camera 11-10 (v3)
HINGE = '    for (int a = 0; a < 24; a++) *r++ = jf_hinge(J, P, a);'
FORWARD = '    return d < -15.0f ? d + 360.0f : d;'


def gaps(dh):
    dh = np.asarray(dh, float)
    return 15 + np.roll(dh, -1) - dh


class HueOrderTests(unittest.TestCase):
    """The ISP interpolates a CEQ destination pair forward mod 360: a decreasing pair (dest[k+1] < dest[k]) goes the
    long way round and the hues between sweep the circle (camera 11-10: Fuji node 16 -> 17 step -2730, Kodak -964).
    The fit keeps every forward gap 15 + dh[a+1] - dh[a] >= jft.HUE_GAP (the hinge), the pack clamps and checks."""

    @classmethod
    def setUpClass(cls):
        import jft
        cls.jft = jft
        from cinemadng import COLOR_SPACES, COMMON_GAMMAS
        cls.color, cls.gamma = list(COLOR_SPACES).index('p3-d60'), COMMON_GAMMAS.index('linear')

    def convert(self, name, lib=None):
        """jft.convert of a repo-root film cube -> (the refined P as the fit left it, before any clamp; JFT bytes; stats)"""
        jft = self.jft
        seen, route, old = {}, jft.route, jft._LIB
        def spy(*a, **k):
            out = route(*a, **k); seen['P'] = np.array(out[0][0], float); return out
        jft.route = spy
        if lib is not None:
            lib.jf_host_direct.argtypes = lib.jf_host_fit.argtypes; lib.jf_host_direct.restype = ctypes.c_float
            lib.jf_host_hsv.argtypes = [FP]
            jft._LIB = lib
        try:
            data, st = jft.convert(ROOT / FILM[name], self.color, self.gamma)
        finally:
            jft.route = route; jft._LIB = old
        return seen['P'], data, st

    def test_film_cubes_keep_the_hue_order(self):
        for name in FILM:
            P, data, st = self.convert(name)
            words = self.jft.unpack(data)['hw']['ceq'][2]
            print(f'\n  {name}: {self.jft.match_percent(st[0])}% match, fitted min gap {gaps(P[51:75]).min():.2f} deg, '
                  f'min step {min(self.jft.hue_steps(words))} words')
            self.assertGreaterEqual(gaps(P[51:75]).min(), self.jft.HUE_GAP, name)   # the fit itself, no clamp needed
            self.assertTrue(self.jft.hue_in_order(words), (name, self.jft.hue_steps(words)))

    def test_without_the_hinge_the_fit_breaks_the_order(self):
        """mutation: the hinge rows zero -> the fit runs against the wrap (gap ~0); with the old linear CEQ model too
        (the v3 that shipped) the pair turns decreasing -- the camera's bug, which the pack clamp still catches."""
        src = (HERE / 'native/jfit.c').read_text()
        self.assertEqual(src.count(HINGE), 1); self.assertEqual(src.count(FORWARD), 1)
        no_hinge = src.replace(HINGE, HINGE.replace('jf_hinge(J, P, a)', '0'))
        P, _data, _st = self.convert('Fuji', build(no_hinge))
        print(f'\n  no hinge: Fuji fitted min gap {gaps(P[51:75]).min():.2f} deg')
        self.assertLess(gaps(P[51:75]).min(), self.jft.HUE_GAP)
        v3 = no_hinge.replace(FORWARD, '    return d;')
        safe = self.jft.hue_safe
        for name in FILM:
            P, data, _st = self.convert(name, build(v3))
            print(f'  v3 model: {name} fitted min gap {gaps(P[51:75]).min():.2f} deg')
            self.assertLess(gaps(P[51:75]).min(), 0, name)                         # a decreasing pair: the bug
            self.assertTrue(self.jft.hue_in_order(self.jft.unpack(data)['hw']['ceq'][2]), name)   # clamped at the pack
            bt = np.stack([np.linspace(0, 1, F.N_TONE)] * 3)
            self.jft.hue_safe = lambda dh: np.asarray(dh, float).copy()           # mutation: no clamp
            try:
                with self.assertRaises(ValueError):                               # ... the pack refuses it
                    self.jft.quantise(P, bt)
            finally:
                self.jft.hue_safe = safe

    def test_a_decreasing_pair_is_detected(self):
        jft = self.jft
        good = list(jft.ORG_H)
        self.assertTrue(jft.hue_in_order(good))
        bad = list(good); bad[17] = (bad[16] - 2730) % 65536                      # the camera's Fuji pair
        self.assertFalse(jft.hue_in_order(bad))
        self.assertFalse(jft.hue_in_order([(v + 20000) % 65536 if k % 2 else v for k, v in enumerate(good)]))
        self.assertFalse(jft.hue_in_order([(v + 2100 * (k == 5)) % 65536 for k, v in enumerate(good)]))   # a step < floor
        if CAMERA_JFT.is_dir():                                                    # the files the camera showed
            order = {p.name: jft.hue_in_order(jft.unpack(p.read_bytes())['hw']['ceq'][2]) for p in sorted(CAMERA_JFT.glob('*.JFT'))}
            print('\n  camera 11-10 JFTs in order:', order)
            self.assertEqual(sorted(order.values()), [False, False, True, True])  # Fuji, Kodak bad; ARRI, RED fine
        # the model: forward mod 360 (the hardware), not np.interp -- midway along a pair 30 deg down, +165 not -15
        dh = np.zeros(24); dh[17] = -30
        self.assertAlmostEqual(float(E.hue_lerp(16.5 * 15, dh)), 165.0, places=6)
        self.assertAlmostEqual(float(np.interp(16.5 * 15, np.arange(25) * 15., np.r_[dh, dh[0]])), -15.0)
        self.assertAlmostEqual(float(E.hue_lerp(7.25 * 15, dh)), 0.0)            # elsewhere unchanged
        # the C chain models it the same way (a fitted solution with a decreasing pair), and the old interp is caught
        sol = np.load(SOL / 'teal_orange_joint.npy'); P, bt = sol[:140].copy(), sol[140:].reshape(3, F.N_TONE)
        P[51 + 17] = P[51 + 16] - 40
        xs = E.lvb_samples()
        self.assertLess(np.abs(c_lab(build(), P, bt, xs) - py_lab(P, bt, xs)).max(), 0.05)
        src = (HERE / 'native/jfit.c').read_text()
        lin = build(src.replace(FORWARD, '    return d;'))
        self.assertGreater(np.abs(c_lab(lin, P, bt, xs) - py_lab(P, bt, xs)).max(), 5)


# ---------------------------------------------------------------- JFIT v5 (Bei 2026-11-11): M1 untied
def lib_v5(src_text=None):
    """build() + the v5 entries (jfit_host.c: jf_host_untied / _normal / _packed_lab / _dense_samples)"""
    L = build(src_text)
    D = ctypes.POINTER(ctypes.c_double)
    L.jf_host_untied.argtypes = L.jf_host_fit.argtypes; L.jf_host_untied.restype = ctypes.c_float
    L.jf_host_direct.argtypes = L.jf_host_fit.argtypes; L.jf_host_direct.restype = ctypes.c_float
    L.jf_host_normal.argtypes = [FP, ctypes.c_int, FP, ctypes.c_uint32, FP, FP, FP, D, D]
    L.jf_host_normal.restype = ctypes.c_double
    L.jf_host_packed_lab.argtypes = [ctypes.c_char_p, ctypes.c_uint32, FP, FP]
    L.jf_host_hsv.argtypes = [FP]
    L.jf_host_dense_samples.argtypes = [FP]
    L.jf_host_ndx.restype = ctypes.c_uint32
    L.jf_host_packed_cost.argtypes = [ctypes.c_char_p, ctypes.c_uint32, FP, FP, FP]
    L.jf_host_packed_cost.restype = ctypes.c_double
    L.jf_host_untied_k.argtypes = L.jf_host_fit.argtypes + [ctypes.c_int]; L.jf_host_untied_k.restype = ctypes.c_float
    return L


def py_cost_v5(P, bt, xs, want, w, untied=True):
    """the untied refine's cost in float64: joint_fit_eval.chain(split=True) + jfit.c's tail (CEQ smoothness 0.02 / 2 / 2,
    curve edits 2.0, hue-order hinge 10 below 4.75 deg) + the YCMAT yr + yb hinge (3000 above 4094 / 4096)"""
    r = ((F.lab709(JF.chain(xs, P, bt, split=untied)) - want) * w[:, None]).ravel()
    q = P[51:123].reshape(3, 24)
    sm = ((q - np.roll(q, -1, 1)) * np.array([0.02, 2.0, 2.0])[:, None]).ravel()
    gap = 15 + np.roll(P[51:75], -1) - P[51:75]
    hinge = np.where(gap < 4.75, (4.75 - gap) * 10.0, 0.0)
    yg = max(P[45] + P[46] - 4094 / 4096, 0.0) * 3000.0 if untied else 0.0
    return float(r @ r + sm @ sm + (P[18:45] * 2.0) @ (P[18:45] * 2.0) + hinge @ hinge + yg * yg)


def hw_lab_py(hw, xs):
    """a .JFT's packed tables through joint_fit_eval.chain (split=True): the Python twin of jfit.c jf_unpack"""
    import jft
    def rows(t):
        rr, rg, rb, gg, gr, gb, bb, br, bg = t
        return np.array([rr, rg, rb, gr, gg, gb, br, bg, bb], float) / 512
    P = np.zeros(140)
    P[:9], P[9:18] = rows(hw['m2']), rows(hw['m1'])
    yr, yg_, yb, cbr, cbb, crr, crb = hw['ycmat']
    P[45:51] = [yr / 4096, yb / 4096, cbr / 512, cbb / 512, crr / 512, crb / 512]
    L_, S_, H_ = (np.array(v, float) for v in hw['ceq'])
    P[51:75] = ((H_ - np.array(jft.ORG_H) + 32768) % 65536 - 32768) * 360 / 65536
    P[75:99], P[99:123] = S_ / 683, L_ / 512
    w = hw['ygam']; kn = []
    for k in range(1, 9): kn += [w[k] & 0xFFFF, w[k] >> 16]
    P[123:140] = np.array([w[0] >> 16] + kn[:15] + [kn[14] + (w[16] >> 16) + w[17] - 1], float) / 4095
    tone = np.asarray(hw['tone'], float) / 8190 * F.TONE_MAX
    if hw.get('knee'):                                                     # JFIT v6: the CKNEE's codes, as jf_unpack reads them
        P = np.r_[P, jft.knee_values(hw['knee'])]
    return F.lab709(jft.chain(xs, P, tone))


class UntiedTests(unittest.TestCase):
    """JFIT v5 (validation/20261111-fit-ceiling-01): RGBLMAT set 1 (M1, P[9:18], the luma) apart from set 2 (M2, the
    chroma) -- the chain luma_preserve, the untied refine's exact Jacobian, the m1 table in the .JFT, the choice."""

    @classmethod
    def setUpClass(cls):
        import jft
        cls.jft = jft
        cls.L = lib_v5()
        sol = np.load(SOL / 'teal_orange_joint.npy')
        cls.P, cls.bt = sol[:140].copy(), sol[140:].reshape(3, F.N_TONE)
        rng = np.random.default_rng(5)
        cls.Pu = cls.P.copy(); cls.Pu[9:18] = cls.P[:9] + rng.normal(0, 0.04, 9)     # an untied solution
        case = next(x for x in E.cases(SOL / 'cubes') if x[0] == 'teal_orange')
        cls.target = staticmethod(F.make_target(Cube.read(case[1]), **case[2]))

    def test_split_chain_matches_python(self):
        """jf_chain_t with M1 != M2 = joint_fit_eval.chain(split=True) (lv_fit.luma_preserve); tied = split=False."""
        xs = E.lvb_samples()
        d = np.abs(c_lab(self.L, self.Pu, self.bt, xs) - F.lab709(JF.chain(xs, self.Pu, self.bt, split=True))).max()
        self.assertLess(d, 0.05)
        off = np.abs(c_lab(self.L, self.Pu, self.bt, xs) - F.lab709(JF.chain(xs, self.Pu, self.bt, split=False))).max()
        self.assertGreater(off, 1.0)                                       # the split is seen
        T = self.P.copy(); T[9:18] = T[:9]
        self.assertTrue((c_lab(self.L, T, self.bt, xs) == c_lab(self.L, np.r_[T[:9], T[:9] + 0, T[18:]], self.bt, xs)).all())

    def normal(self, L, P, untied, xs, want, w):
        nf = 140 if untied else 131
        g = np.zeros(nf); co = ctypes.c_double()
        c = L.jf_host_normal(ptr(f32(P)), untied, ptr(f32(self.bt / F.TONE_MAX)), len(xs), ptr(f32(xs)), ptr(f32(want)),
                             ptr(f32(w)), g.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), ctypes.byref(co))
        return c, co.value, g

    def grad_gap(self, L):
        """jf2_normal's gradient (untied) against central differences of the float64 cost, on the parameters the untie
        adds (M1) and on M2, YCMAT (the hinge active), a knot, a CEQ anchor, a YGAM node: max relative error"""
        xs = E.lvb_samples()[::3]
        want = F.lab709(self.target(xs, 100)); w = np.sqrt((1 - 2.5 * F.saturation(self.target(xs, 0)) / 8) ** 8)
        P = self.Pu.copy(); P[45], P[46] = 0.6, 0.45                       # yr + yb above 4094 / 4096: the hinge
        c, co, g = self.normal(L, P, 1, xs, want, w)
        self.assertAlmostEqual(c / co, 1, delta=1e-6)                      # jf2_normal's and jf2_cost's agree
        self.assertAlmostEqual(c / py_cost_v5(P, self.bt, xs, want, w), 1, delta=2e-3)
        worst = 0
        for group in (range(9), range(9, 18), [45, 46, 18 + 13, 51 + 7, 75 + 3, 123 + 9]):   # M2, M1 (the untie), others
            num = np.array([(py_cost_v5(np.r_[P[:k], P[k] + 1e-4, P[k + 1:]], self.bt, xs, want, w) -
                             py_cost_v5(np.r_[P[:k], P[k] - 1e-4, P[k + 1:]], self.bt, xs, want, w)) / 4e-4 for k in group])
            worst = max(worst, np.linalg.norm(g[list(group)] - num) / np.linalg.norm(num))   # (tied: the same ~1 %)
        return worst

    def test_untied_gradient_is_exact(self):
        gap = self.grad_gap(self.L)
        print(f'\n  untied gradient vs central differences: max rel err {gap:.2e}')
        self.assertLess(gap, 0.01)

    @classmethod
    def kodak(cls):
        """jft.convert's v4 problem for the Kodak 2383 film cube (P3-D60 / Linear): the dense set, base tone and the v4
        result (route + choose) -- what conv_untie starts from"""
        if not hasattr(cls, '_kodak'):
            jft = cls.jft
            target = F.make_target(Cube.read(ROOT / FILM['Kodak']), space='p3-d60', gamma='linear')
            fit = E.fit_lvb(target, 100)
            base = np.r_[E.lvb_samples(), jft.grey_samples()]
            xs = np.r_[base, jft.hsv_samples()]; want = F.lab709(target(xs, 100))
            w = np.r_[np.sqrt((1 - 2.5 * F.saturation(target(base, 0)) / 8) ** 8), np.ones(jft.NHSV)]
            bt = fit['tone'].astype(float) / F.TONE_MAX
            if fit['shift']:
                bt = np.stack([np.interp(np.arange(2048) / 2 ** fit['shift'], np.arange(2048), bt[k]) for k in range(3)])
            M = np.asarray(fit['q'], float) / F.Q9 * 2 ** fit['shift']
            starts = [np.r_[M0.ravel(), M0.ravel(), np.zeros(27), E.POST_ID] for M0 in (np.eye(3), M)]
            P, hw = jft.choose(jft.route(xs, want, w, bt, starts, len(base))[0], bt)
            cls._kodak = jft.dense_set(xs, want, w, target, 100) + (bt, P, hw)
        return cls._kodak

    def test_the_untied_refine_frees_m1_and_beats_the_tied_one(self):
        """from the v4 result (Kodak 2383), jf_fit_untied moves M1 off M2 and ends well below what jf_fit_direct reaches
        from there (same 15 steps, the same dense set)."""
        xs, want, w, bt, T, _hw = self.kodak()
        Pd, cd = self.jft.native_direct(xs, want, w, bt, T, 15)
        Pu, cu = self.jft.native_untied(xs, want, w, bt, T, 15, knee=False)      # v5's refine (v6: KneeTests)
        print(f'\n  Kodak, 15 steps from v4: tied {cd:.1f}  untied {cu:.1f}  |M1 - M2| {np.abs(Pu[9:18] - Pu[:9]).max():.3f}')
        self.assertTrue((Pd[9:18] == Pd[:9]).all())
        self.assertGreater(np.abs(Pu[9:18] - Pu[:9]).max(), 0.05)
        self.assertLess(cu, 0.97 * cd)
        self.assertAlmostEqual(cu / py_cost_v5(Pu, bt * F.TONE_MAX, xs, want, w), 1, delta=5e-3)

    def test_untied_packing_round_trip(self):
        """quantise -> pack -> unpack keeps m1 apart from m2 (one shift for both); the packed tables through jfit.c
        jf_unpack + the chain = through the Python twin; a v4 file (no m1) still reads, tied."""
        jft = self.jft
        bt = self.bt / F.TONE_MAX
        P = self.Pu.copy(); P[9] = 4.5                                     # set 1 alone needs the shift (> 2047 / 512)
        hw = jft.quantise(P, bt)
        self.assertEqual(hw['shift'], 1)
        data = jft.pack((b'\1' * 8, 0, 0, 100, 0), hw, (1.0, 2.0, 3.0))
        self.assertEqual(len(data), jft.HEADER + jft.PAYLOAD)
        u = jft.unpack(data)['hw']
        self.assertEqual((u['m1'], u['m2'], u['shift']), (hw['m1'], hw['m2'], hw['shift']))
        self.assertNotEqual(u['m1'], u['m2'])
        self.assertEqual(u['m1'][0], int(round(4.5 / 2 * 512)))
        xs = E.lvb_samples()
        d = np.abs(jft.packed_lab(data, xs) - hw_lab_py(u, xs)).max()
        print(f'\n  packed tables: jf_unpack chain vs Python twin max dLab {d:.4f}')
        self.assertLess(d, 0.05)
        # and close to the float chain it was packed from (packing loss only)
        self.assertLess(np.median(np.linalg.norm(jft.packed_lab(data, xs) - c_lab(self.L, P, self.bt, xs), axis=1)), 0.5)
        v4 = bytearray(data[:jft.HEADER + jft.PAYLOAD_V4]); struct.pack_into('<I', v4, 12, len(v4))
        struct.pack_into('<I', v4, 56, jft.fnv(bytes(v4[jft.HEADER:])))
        o = jft.unpack(bytes(v4))['hw']
        self.assertEqual(o['m1'], o['m2'])
        with self.assertRaises(ValueError):                                # set 1 beyond even shift 2
            q = P.copy(); q[9] = 17.0; jft.quantise(q, bt)

    def test_the_choice_takes_the_cheaper_packed_one(self):
        """jft.untie: the refined one kept only when its packed tables cost less on the dense set (jf_packed_cost);
        never when it does not pack.  (v5's refine, knee=False; JFIT v6's choice with the CKNEE: KneeTests)"""
        jft = self.jft
        xs, want, w, bt, T, hw = self.kodak()
        P, hw2, info = jft.untie(T, hw, xs, want, w, bt, 15, knee=False)
        print(f"\n  Kodak packed cost on the dense set: v4 {info['cost_tied']:.1f}  untied {info['cost_untied']:.1f}")
        self.assertEqual(info['kept'], 'untied'); self.assertLess(info['cost_untied'], info['cost_tied'])
        self.assertNotEqual(hw2['m1'], hw2['m2'])
        self.assertIsNone(hw2['knee']); self.assertFalse(info['knee'])
        self.assertEqual(info['cost_tied'], jft.packed_cost(jft.payload(hw), xs, want, w))
        self.assertEqual(info['cost_untied'], jft.packed_cost(jft.payload(hw2), xs, want, w))
        nu = jft.native_untied
        try:
            jft.native_untied = lambda *a, **k: (np.r_[T[:45], 2.0, 2.0, T[47:]], 0.0)   # YCMAT beyond 12 bits
            self.assertEqual(jft.untie(T, hw, xs, want, w, bt)[2]['kept'], 'tied')
            worse = T.copy(); worse[51:75] += np.linspace(0, 3, 24)            # packs, costs more
            jft.native_untied = lambda *a, **k: (worse, 0.0)
            P3, hw3, info3 = jft.untie(T, hw, xs, want, w, bt)
            self.assertEqual(info3['kept'], 'tied'); self.assertIs(hw3, hw); self.assertIs(P3, T)
            self.assertGreater(info3['cost_untied'], info3['cost_tied'])
        finally:
            jft.native_untied = nu

    def test_dense_samples(self):
        """jf_dense_samples: 2720 camera RGB (0..CMAX), 340 near-greys (0..1, 1 in ~7 exact), 297 HSV; Q20-exact"""
        xs, nw = self.jft.dense_samples()
        self.assertEqual((len(xs), nw), (3357, 3060))
        self.assertTrue((np.round(xs * 2 ** 20) == xs * 2 ** 20).all())
        cam, grey = xs[:2720], xs[2720:3060]
        self.assertTrue(((cam >= 0) & (cam <= 2047 / 1918 + 1e-6)).all())
        self.assertGreater(np.median(cam), 0.2); self.assertLess(np.median(cam), 0.35)       # CMAX u^2.2: median 0.3
        spread = (grey.max(1) - grey.min(1)) / grey.max(1)
        self.assertTrue((spread < 0.07).all())
        self.assertAlmostEqual((spread == 0).mean(), 1 / 7, delta=0.05)
        self.assertEqual(xs.tolist(), self.jft.dense_samples()[0].tolist())      # deterministic

    def test_mutants_are_caught(self):
        """the tests above fail without the untie: (a) jf_fit_untied tied again (K.untied = 0), (b) the split's luma
        term dropped from the Jacobian, (c) the chain's split dropped."""
        src = (HERE / 'native/jfit.c').read_text()
        a = 'K.untied = 1; K.nf = knee ? JF2_NFK : JF2_NFU;'
        b = '0.299f * (d1[0][i] - d2[0][i]) + 0.587f * (d1[1][i] - d2[1][i]) + 0.114f * (d1[2][i] - d2[2][i]);'
        c = '    if (jf_split(P)) {'
        for k in (a, b, c): self.assertEqual(src.count(k), 1, k)
        # (a): tied refine -- M1 stays M2
        La = lib_v5(src.replace(a, 'K.untied = 0; K.nf = JF2_NF;'))
        La.jf_host_untied_k.argtypes = La.jf_host_fit.argtypes + [ctypes.c_int]; La.jf_host_untied_k.restype = ctypes.c_float
        jft, old = self.jft, self.jft._LIB
        jft._LIB = La
        try:
            with self.assertRaises(AssertionError):
                self.test_the_untied_refine_frees_m1_and_beats_the_tied_one()
        finally:
            jft._LIB = old
        # (b): the gradient is wrong
        self.assertGreater(self.grad_gap(lib_v5(src.replace(b, '0;'))), 0.05)
        # (c): the chain ignores M1
        L = self.L
        try:
            self.L = lib_v5(src.replace(c, '    if (0) {'))
            with self.assertRaises(AssertionError):
                self.test_split_chain_matches_python()
        finally:
            self.L = L

# ---------------------------------------------------------------- JFIT v6 (2026-11-11): the CKNEE
def py_cost_v6(P, bt, xs, want, w):
    """the untied refine's cost with the CKNEE in float64: jft.chain (joint_fit_eval.chain + the knee after YCMAT) + the
    tail of py_cost_v5 + the YCMAT hinges (3000 x the excess above 4094 / 4096 or below 2 / 4096)"""
    import jft
    r = ((F.lab709(jft.chain(xs, P, bt)) - want) * w[:, None]).ravel()
    q = P[51:123].reshape(3, 24)
    sm = ((q - np.roll(q, -1, 1)) * np.array([0.02, 2.0, 2.0])[:, None]).ravel()
    gap = 15 + np.roll(P[51:75], -1) - P[51:75]
    hinge = np.where(gap < 4.75, (4.75 - gap) * 10.0, 0.0)
    s = P[45] + P[46]
    yg = (s - 4094 / 4096 if s > 4094 / 4096 else s - 2 / 4096 if s < 2 / 4096 else 0.0) * 3000.0
    return float(r @ r + sm @ sm + (P[18:45] * 2.0) @ (P[18:45] * 2.0) + hinge @ hinge + yg * yg)


KNEE = [0.08, 0.7, 0.1, 1.3, 0.12, 0.5, 0.06, 1.4]           # (knee, slope) +Cb, -Cb, +Cr, -Cr: every half bends somewhere


class KneeTests(unittest.TestCase):
    """JFIT v6 (camera 2026-11-11, validation/20261111-cknee-cal): the ISP's CKNEE (after YCMAT, before CEQ; Cb and Cr
    each on its own, a half-axis above its knee at its slope) in the chain, the untied refine's exact Jacobian, the
    knee's start, its codes (knee x 1024, 9 bits; slope x 16, 5 bits, at most 24) in the .JFT, and the choice."""

    @classmethod
    def setUpClass(cls):
        import jft
        cls.jft = jft
        cls.L = lib_v5()
        U = UntiedTests
        if not hasattr(U, 'P'):
            U.setUpClass()
        cls.U = U
        cls.bt, cls.target = U.bt, staticmethod(U.target)
        cls.Pk = jft.knee_off(U.Pu); cls.Pk[140:148] = KNEE

    def test_the_chain_bends_each_half_axis_as_the_python_twin(self):
        """jf_chain_t with the CKNEE = jft.chain (float64); off = the v5 chain exactly; slope 1 = no knee"""
        jft, xs = self.jft, E.lvb_samples()
        d = np.abs(c_lab(self.L, self.Pk, self.bt, xs) - F.lab709(jft.chain(xs, self.Pk, self.bt))).max()
        print(f'\n  CKNEE chain: native vs Python max dLab {d:.4f}')
        self.assertLess(d, 0.05)
        self.assertGreater(np.abs(c_lab(self.L, self.Pk, self.bt, xs) - c_lab(self.L, self.U.Pu, self.bt, xs)).max(), 5)
        self.assertTrue((c_lab(self.L, jft.knee_off(self.U.Pu), self.bt, xs) == c_lab(self.L, self.U.Pu, self.bt, xs)).all())
        one = self.Pk.copy(); one[141::2] = 1.0
        self.assertLess(np.abs(c_lab(self.L, one, self.bt, xs) - c_lab(self.L, self.U.Pu, self.bt, xs)).max(), 1e-3)
        # each half alone: a knee at 0 with slope 0 takes that half's chroma to 0, the other half untouched
        lab0 = c_lab(self.L, self.U.Pu, self.bt, xs)
        for h in range(4):
            Q = jft.knee_off(self.U.Pu); Q[140 + 2 * h], Q[141 + 2 * h] = 0.0, 0.0
            moved = np.abs(c_lab(self.L, Q, self.bt, xs) - lab0).max(1) > 1e-3
            self.assertTrue(moved.any() and not moved.all(), h)

    def normal(self, P, xs, want, w, untied=2):
        nf = {0: 131, 1: 140, 2: 148}[untied]
        g = np.zeros(nf); co = ctypes.c_double()
        c = self.L.jf_host_normal(ptr(f32(P)), untied, ptr(f32(self.bt / F.TONE_MAX)), len(xs), ptr(f32(xs)), ptr(f32(want)),
                                  ptr(f32(w)), g.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), ctypes.byref(co))
        return c, co.value, g

    def knee_grad_gap(self, L=None):
        """jf2_normal's gradient (untied + CKNEE) against central differences of py_cost_v6, on the 8 knee parameters
        and on M2, M1, YCMAT, a knot, a CEQ anchor, a YGAM node: max relative error"""
        if L is not None:
            keep, self.L = self.L, L
        try:
            xs = E.lvb_samples()[::3]
            want = F.lab709(self.target(xs, 100)); w = np.sqrt((1 - 2.5 * F.saturation(self.target(xs, 0)) / 8) ** 8)
            P = self.Pk.copy()
            c, co, g = self.normal(P, xs, want, w)
            self.assertAlmostEqual(c / co, 1, delta=1e-6)
            self.assertAlmostEqual(c / py_cost_v6(P, self.bt, xs, want, w), 1, delta=2e-3)
            worst = 0
            for group in (range(140, 148), range(9), range(9, 18), [45, 47, 50, 18 + 13, 51 + 7, 75 + 3, 123 + 9]):
                num = np.array([(py_cost_v6(np.r_[P[:k], P[k] + 1e-4, P[k + 1:]], self.bt, xs, want, w) -
                                 py_cost_v6(np.r_[P[:k], P[k] - 1e-4, P[k + 1:]], self.bt, xs, want, w)) / 4e-4 for k in group])
                worst = max(worst, np.linalg.norm(g[list(group)] - num) / np.linalg.norm(num))
            return worst
        finally:
            if L is not None:
                self.L = keep

    def test_the_knee_gradient_is_exact(self):
        gap = self.knee_grad_gap()
        print(f'\n  CKNEE gradient vs central differences: max rel err {gap:.2e}')
        self.assertLess(gap, 0.01)

    def test_the_ycmat_floor_hinge(self):
        """yr + yb below 2 / 4096 (yg 4096: no 12-bit word -- ARRI 709 with the CKNEE free drove it there) costs
        (3000 x the shortfall)^2 in the untied refine, as py_cost_v6: the cost and d / d yr, yb at yr = yb = 0"""
        xs = E.lvb_samples()[::50]
        want = F.lab709(self.target(xs, 100)); w = np.sqrt((1 - 2.5 * F.saturation(self.target(xs, 0)) / 8) ** 8)
        P = self.Pk.copy(); P[45] = P[46] = 0.0
        c, _co, g = self.normal(P, xs, want, w)
        self.assertAlmostEqual(c / py_cost_v6(P, self.bt, xs, want, w), 1, delta=2e-3)
        for k in (45, 46):
            hi, lo = P.copy(), P.copy(); hi[k] += 1e-5; lo[k] = max(lo[k] - 1e-5, 0.0)
            num = (py_cost_v6(hi, self.bt, xs, want, w) - py_cost_v6(lo, self.bt, xs, want, w)) / (2 * (hi[k] - lo[k]))
            self.assertLess(abs(g[k] - num) / abs(num), 0.02, k)
        self.assertLess(g[45], -2000)                                      # the hinge pulls yr + yb up

    def test_the_start_is_the_knee_less_chain_with_a_gradient(self):
        """jf_knee_start (0 LM steps): each knee at the 70th percentile of its half's chroma after YCMAT (a 1/512 bin),
        slope 1 -- the cost is the knee-less start's, and the slopes have a gradient there"""
        jft = self.jft
        xs, want, w, bt, T, _hw = self.U.kodak()
        Pk, ck = jft.native_untied(xs, want, w, bt, T, 0, knee=True)
        Pn, cn = jft.native_untied(xs, want, w, bt, T, 0, knee=False)
        self.assertTrue(jft.knee_on(Pk)); self.assertFalse(jft.knee_on(jft.knee_off(Pn)))
        self.assertTrue((Pk[141::2] == 1).all())
        self.assertAlmostEqual(ck / cn, 1, delta=1e-5)
        import lv_fit
        rgb = np.clip(lv_fit.luma_preserve(*[np.stack([np.interp(np.clip(xs @ T[o:o + 9].reshape(3, 3).T * F.WHITE_INDEX, 0, 2047)[:, k],
                                            np.arange(2048), np.clip(np.maximum.accumulate(bt[k] + np.interp(np.arange(2048), np.linspace(0, 2047, 9), T[18:45].reshape(3, 9)[k])), 0, 1))
                                            for k in range(3)], -1) for o in (9, 0)]), 0, 1)
        q = T[45:]; rg, bg = rgb[:, 0] - rgb[:, 1], rgb[:, 2] - rgb[:, 1]
        for h, v in enumerate((q[2] * rg + q[3] * bg, q[4] * rg + q[5] * bg)):
            for side, m in ((0, v > 0), (1, v < 0)):
                ref = max(np.percentile(np.abs(v[m]), 70), 0.02)
                self.assertLess(abs(Pk[140 + 4 * h + 2 * side] - min(ref, 511 / 1024)), 2 / 512, (h, side))
        _c, _co, g = self.normal(Pk, xs[::5], want[::5], w[::5])
        self.assertGreater(np.abs(g[141::2]).max(), 1.0)

    def test_the_codes_round_trip_and_the_packed_chain_reads_them(self):
        """quantise: knee x 1024 (9 bits), slope x 16 (5 bits, at most 24), rounded half up as conv_pack, clamped; the .JFT's block
        (on, the PQ record's +4 .. +15 in the 10C0 / 10D0 / 10C8 / 10D8 halves); jf_unpack + the chain = the Python twin
        on the codes; packed_cost on the quantised knee; a v5 file (no block) reads with knee None"""
        jft = self.jft
        bt = self.bt / F.TONE_MAX
        P = self.Pk.copy(); P[140:148] = [0.6, 2.0, 0.1, 1.3, 300.4 / 1024, 18.5 / 16, 0.0, -0.1]
        hw = jft.quantise(P, bt)
        self.assertEqual(hw['knee'], [511, 24, 102, 21, 300, 19, 0, 0])
        data = jft.pack((b'\1' * 8, 0, 0, 100, 0), hw, (1.0, 2.0, 3.0))
        self.assertEqual((len(data), jft.PAYLOAD), (64 + 12580, 12580))
        blk = data[64 + 12564:64 + 12580]
        self.assertEqual(blk, struct.pack('<I2H2B2H2B', 1, 511, 102, 24, 21, 300, 0, 19, 0))
        self.assertEqual(jft.knee_record(hw), b'\0' * 4 + blk[4:])
        u = jft.unpack(data)['hw']
        self.assertEqual(u['knee'], hw['knee'])
        xs = E.lvb_samples()
        d = np.abs(jft.packed_lab(data, xs) - hw_lab_py(u, xs)).max()
        print(f'\n  packed CKNEE: jf_unpack chain vs Python twin max dLab {d:.4f}')
        self.assertLess(d, 0.05)
        want = F.lab709(self.target(xs, 100)); w = np.ones(len(xs))
        twin = float((((hw_lab_py(u, xs) - want) * w[:, None]) ** 2).sum())
        self.assertAlmostEqual(jft.packed_cost(data, xs, want, w) / twin, 1, delta=2e-3)
        off = jft.pack((b'\1' * 8, 0, 0, 100, 0), jft.quantise(jft.knee_off(P), bt), (1.0, 2.0, 3.0))
        self.assertEqual(off[64 + 12564:64 + 12580], bytes(16))
        self.assertIsNone(jft.unpack(off)['hw']['knee'])
        self.assertNotEqual(jft.packed_cost(off, xs, want, w), jft.packed_cost(data, xs, want, w))
        v5 = bytearray(data[:64 + jft.PAYLOAD_V5]); struct.pack_into('<I', v5, 12, len(v5))
        struct.pack_into('<I', v5, 56, jft.fnv(bytes(v5[64:])))
        self.assertIsNone(jft.unpack(bytes(v5))['hw']['knee'])
        bad = bytearray(data); struct.pack_into('<I', bad, 64 + 12564, 2); struct.pack_into('<I', bad, 56, jft.fnv(bytes(bad[64:])))
        with self.assertRaises(ValueError):
            jft.unpack(bytes(bad))

    def test_the_knee_is_kept_only_when_it_lowers_the_packed_cost(self):
        """Kodak 2383 (the v4 result, 15 steps): the refine with the CKNEE packs below both the same tables without it
        and the v4 one -- kept; a knee that costs more (k 0, slope 0: that half's chroma gone) -- the tables without it;
        one that does not pack -- the v4 one"""
        jft = self.jft
        xs, want, w, bt, T, hw = self.U.kodak()
        P, hw2, info = jft.untie(T, hw, xs, want, w, bt, 15)
        print(f"\n  Kodak packed cost: v4 {info['cost_tied']:.1f}  untied (knee off) {info['cost_untied']:.1f}  "
              f"with the CKNEE {info['cost_knee']:.1f}  codes {hw2['knee']}")
        self.assertTrue(info['knee']); self.assertEqual(info['kept'], 'untied')
        self.assertLess(info['cost_knee'], min(info['cost_tied'], info['cost_untied']))
        self.assertEqual(hw2['knee'], jft.knee_codes(P)); self.assertEqual(info['cost_knee'], jft.packed_cost(jft.payload(hw2), xs, want, w))
        nu = jft.native_untied
        try:
            good = P.copy()
            v5 = jft.knee_off(nu(xs, want, w, bt, T, 15, knee=False)[0])            # v5's refine: it beats the v4 one
            bad = v5.copy(); bad[140:148] = [0.0, 0.0] * 4                        # every chroma to 0: dearer than without
            jft.native_untied = lambda *a, **k: (bad, 0.0)
            P3, hw3, info3 = jft.untie(T, hw, xs, want, w, bt)
            self.assertFalse(info3['knee']); self.assertEqual(info3['kept'], 'untied'); self.assertIsNone(hw3['knee'])
            self.assertGreater(info3['cost_knee'], info3['cost_untied'])
            self.assertTrue((P3 == v5).all())
            jft.native_untied = lambda *a, **k: (np.r_[good[:45], 2.0, 2.0, good[47:]], 0.0)   # YCMAT beyond 12 bits
            P4, hw4, info4 = jft.untie(T, hw, xs, want, w, bt)
            self.assertEqual((info4['kept'], info4['knee']), ('tied', False)); self.assertIs(hw4, hw)
        finally:
            jft.native_untied = nu

    def test_mutants_are_caught(self):
        """(a) the knee's own derivative terms dropped, (b) its chain factor (m d in) dropped, (c) the chain without
        it, (d) jf_unpack reading the slope as / 19 (the renderer calibration's wrong unit), (e) no YCMAT floor hinge, (f) jft.untie keeping any knee that packs"""
        src = (HERE / 'native/jfit.c').read_text()
        muts = dict(a=('if (s0 >= 0) { dv[s0] += sg * (1 - p[1]); dv[s0 + 1] += sg * (x - p[0]); }', ''),
                    b=('for (int i = 0; i < nm; i++) dv[i] *= p[1];', ''),
                    c=('{ int sd; cb = jf_knee(cb, P + JF_NK, &sd); cr = jf_knee(cr, P + JF_NK + 4, &sd); }', ''),
                    d=('P[JF_NK + i] = (float)kc[i] / (i & 1 ? 16.0f : 1024.0f);', 'P[JF_NK + i] = (float)kc[i] / (i & 1 ? 19.0f : 1024.0f);'),
                    e=(': s < JF_YG_MIN ? (s - JF_YG_MIN) * K->w_yg : 0.0f;', ': 0.0f;'))
        for k, (a, b) in muts.items():
            self.assertEqual(src.count(a), 1, k)
        for k in 'ab':
            self.assertGreater(self.knee_grad_gap(lib_v5(src.replace(*muts[k]))), 0.05, k)
        keep = self.L
        try:
            self.L = lib_v5(src.replace(*muts['c']))
            with self.assertRaises(AssertionError):
                self.test_the_chain_bends_each_half_axis_as_the_python_twin()
            self.L = lib_v5(src.replace(*muts['e']))
            with self.assertRaises(AssertionError):
                self.test_the_ycmat_floor_hinge()
        finally:
            self.L = keep
        jft, old = self.jft, self.jft._LIB
        try:
            jft._LIB = lib_v5(src.replace(*muts['d']))
            with self.assertRaises(AssertionError):
                self.test_the_codes_round_trip_and_the_packed_chain_reads_them()
        finally:
            jft._LIB = old
        rule = "    if k and k[0] < c0 and (u is None or k[0] < u[0]):"
        jsrc = (HERE / 'jft.py').read_text(); self.assertEqual(jsrc.count(rule), 1)
        ns = dict(jft.__dict__)
        exec(compile(jsrc.replace(rule, "    if k:"), str(HERE / 'jft.py'), 'exec'), ns)
        keep_untie = jft.untie
        try:
            jft.untie = ns['untie']; ns['native_untied'] = jft.native_untied
            with self.assertRaises(AssertionError):
                self.test_the_knee_is_kept_only_when_it_lowers_the_packed_cost()
        finally:
            jft.untie = keep_untie


if __name__ == '__main__':
    unittest.main(verbosity=2)
