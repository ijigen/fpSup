#!/usr/bin/env python3
"""native/jfit_two.c(兩輪聯合擬合 A -> B)對 Python 參考的主機對照。

參考:projects/lut-sup/validation/20261107-twopass-constrained-01/fit_constrained.py,kind = hinge、lam = 0、
start = direct(不受約束的聯合二輪;正向模型 / 封裝 / 三段 LM 來自 20261106-isp-compositions-01/fit_visits.py)。
主機建置(clang -O2 -shared),跟相機同一份 C。檢查:
  1. 正向值與解析 Jacobian(連續 / 8-bit 寫回直通)對 fit_visits.forward;
  2. 封裝(兩輪的 JFT payload)逐字對 fit_visits.packets、整數重播對 replay_isp.encoded_stage;
  3. 四支 LUT(Kodak 2383、Fuji 3513DI、BMD Gen5 Film Look、ARRI Classic)同起點、同樣本整個擬合:選解損失與
     色卡平均 dE76(用參考的整數重播打分)在容差內;
  4. 相機建置(build_v4.compile_unit,-Werror、只有 .text);
  5. 變異:幾個故意的錯誤要被 1–2 抓到。
`python3 -B test_jfit_two.py report` 另印對照表、時間比與工作區大小(JSON 到 stdout)。
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

for _k in ("VECLIB_MAXIMUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_k] = "1"

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VAL = ROOT / 'projects/lut-sup/validation'
sys.path.insert(0, str(VAL / '20261107-twopass-constrained-01'))
import fit_constrained as fc          # noqa: E402  (fit_visits, review_sampling, replay_isp ...)

fv, E, F, jft = fc.fv, fc.E, fc.F, fc.jft
FP = ctypes.POINTER(ctypes.c_float)
U32P = ctypes.POINTER(ctypes.c_uint32)
U8P = ctypes.POINTER(ctypes.c_uint8)
LUTS = ('Kodak', 'Fuji', 'BMD', 'ARRI')
PAY = 12544
NZ = 253
SCHEDULE = fc.SCHEDULE                # (750, soft, 55), (1400, soft, 65), (1400, hard, 18):test_first_steps 會暫時改 fc 的


def build(mutant=None):
    """主機 dylib;mutant = jfit_two.c 的替代全文(變異測試)。"""
    td = Path(tempfile.mkdtemp(prefix='jt-'))
    (td / 'native/host').mkdir(parents=True)
    (td / 'native/jfit.c').write_text((HERE / 'native/jfit.c').read_text())
    (td / 'native/jfit_two.c').write_text(mutant if mutant is not None else (HERE / 'native/jfit_two.c').read_text())
    (td / 'native/host/jfit_two_host.c').write_text((HERE / 'native/host/jfit_two_host.c').read_text())
    lib = td / 'jt.dylib'
    subprocess.run(['clang', '-O2', '-shared', '-fPIC', '-o', str(lib), str(td / 'native/host/jfit_two_host.c')], check=True)
    L = ctypes.CDLL(str(lib))
    L.jt_host_forward.argtypes = [FP, FP, ctypes.c_uint32, FP, ctypes.c_int, FP, FP]
    L.jt_host_pack.argtypes = [FP, FP, U8P]
    L.jt_host_replay.argtypes = [FP, FP, ctypes.c_uint32, FP, FP, FP]
    L.jt_host_replay.restype = ctypes.c_float
    L.jt_host_fit.argtypes = [FP, FP, FP, U32P, ctypes.POINTER(FP), ctypes.POINTER(FP), ctypes.POINTER(FP),
                              ctypes.c_uint32, FP, FP, U32P, FP, FP, U8P]
    L.jt_host_fit.restype = ctypes.c_float
    L.jt_host_draw.argtypes = [ctypes.c_uint32, ctypes.c_uint32, FP]
    L.jt_host_draw.restype = ctypes.c_uint32
    L.jt_host_weight.argtypes = [ctypes.c_uint32, FP, FP]
    L.jt_host_work_bytes.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    L.jt_host_work_bytes.restype = ctypes.c_uint32
    L.jt_host_struct_bytes.restype = ctypes.c_uint32
    for f in (L.jt_host_direct, L.jt_host_oldfit):
        f.argtypes = [FP, FP, ctypes.c_uint32, FP, FP, FP, ctypes.c_uint32]
        f.restype = ctypes.c_float
    return L


def f32(a):
    return np.ascontiguousarray(a, dtype=np.float32)


def ptr(a):
    return a.ctypes.data_as(FP)


# ---------------------------------------------------------------- the reference context (one per LUT, cached)
_WORK = Path(tempfile.mkdtemp(prefix='jt-ref-'))
_REF = {}
_TOOLS = {}


def tools():
    if not _TOOLS:
        _TOOLS['refiner'] = fc.rsm.load_refiner(_WORK)
        jft._lib()
        _TOOLS['fn'] = fv.load_stage(_WORK)
        _TOOLS['cases'] = {c[0]: c for c in E.cases(_WORK / 'cubes') + fc.ft.SU.EXTRA}
    return _TOOLS


def context(key):
    """target、direct F(pF, toneF)、三段訓練樣本、選解集 —— 與 fit_constrained.main 相同。"""
    if key in _REF:
        return _REF[key]
    T = tools()
    case = T['cases'][fc.LUTS[key]]
    fc.direct_first_pass(case, T['refiner'])
    target, pF, toneF, t_direct, _ = fc.direct_first_pass(case, T['refiner'])
    pF = fv.unpack_vector(pF[fv.FIRST], [fv.FIRST], [0, len(fv.FIRST)])[0]
    rng = np.random.default_rng(71393)
    stages = []
    for count, hard, iters in SCHEDULE:
        xs = fv.draw(rng, count)
        stages.append((xs, F.lab709(target(xs, 100)), (1 - 2.5 * F.saturation(target(xs, 0)) / 8) ** .7, iters))
    sel_x = fv.draw(np.random.default_rng(80175), 2100)
    ctx = dict(target=target, pF=pF, toneF=toneF, t_direct=t_direct, stages=stages,
               sel=(sel_x, F.lab709(target(sel_x, 100))), chart=E.sample_sets()['色卡'])
    _REF[key] = ctx
    return ctx


def reference_fit(key):
    c = context(key)
    if 'ref' not in c:
        target = c['target']
        fsel_x, fsel_w = fc.f_selection(target)
        fsel_ref = F.lab709(target(fsel_x, 100))
        ref_blob = fv.packets([c['pF']], [c['toneF']])
        fl = fc.loss(np.linalg.norm(F.lab709(fc.replay_blobs(ref_blob, fsel_x)) - fsel_ref, axis=1), fsel_w)
        seed = ([c['pF'], fv.IDENTITY.copy()], [c['toneF'], fv.IDENTITY_TONE])
        t0 = time.process_time()
        (total, l2, l1, blobs), _ = fc.fit_constrained(tools()['fn'], target, seed, (c['pF'], c['toneF']), 'hinge', 0.0,
                                                       c['sel'], (fsel_x, fsel_w, fsel_ref, fl))
        c['ref'] = dict(sel=l2, blobs=blobs, seconds=time.process_time() - t0, chart=chart_stats(c, blobs))
    return c['ref']


def chart_stats(c, blobs):
    lab = F.lab709(fc.replay_blobs(blobs, c['chart']))
    return fc.stats(lab, F.lab709(c['target'](c['chart'], 100)))


def c_fit(L, c, iters=None, stages=None):
    st = stages or c['stages']
    ns = (ctypes.c_uint32 * 3)(*[len(s[0]) for s in st])
    keep = [(f32(s[0]), f32(s[1]), f32(s[2])) for s in st]
    xs = (FP * 3)(*[ptr(k[0]) for k in keep])
    want = (FP * 3)(*[ptr(k[1]) for k in keep])
    wt = (FP * 3)(*[ptr(k[2]) for k in keep])
    sx, sw = f32(c['sel'][0]), f32(c['sel'][1])
    PA, PB = f32(c['pF']), f32(fv.IDENTITY)
    base = f32(c['toneF'])
    it = (ctypes.c_uint32 * 3)(*(iters or [s[3] for s in st]))
    z, stats = np.zeros(NZ, np.float32), np.zeros(8, np.float32)
    pay = np.zeros(2 * PAY, np.uint8)
    t0 = time.process_time()
    cost = L.jt_host_fit(ptr(base), ptr(PA), ptr(PB), ns, xs, want, wt, len(sx), ptr(sx), ptr(sw), it, ptr(z), ptr(stats),
                         pay.ctypes.data_as(U8P))
    secs = time.process_time() - t0
    params = [PA.astype(float), PB.astype(float)]
    blobs = fv.packets(params, [c['toneF'], fv.IDENTITY_TONE])
    return dict(sel=float(cost), z=z, stats=stats, pay=pay, params=params, blobs=blobs, seconds=secs,
                chart=chart_stats(c, blobs))


def z_of(params):
    return np.r_[params[0][fv.FIRST], params[1][fv.LATER]]


def probe_params(c, seed=5):
    """direct F + 一個有編修的第二輪(各欄小擾動),測正向 / 封裝用。"""
    rng = np.random.default_rng(seed)
    pB = fv.IDENTITY.copy()
    pB[18:45] += rng.normal(0, .03, 27)
    pB[45:51] += rng.normal(0, .01, 6)
    pB[51:75] += rng.normal(0, 3, 24)
    pB[75:123] *= 1 + rng.normal(0, .05, 48)
    pB[123:140] = np.clip(pB[123:140] + rng.normal(0, .01, 17), 0, 1)
    pA = c['pF'].copy()
    pA[123:140] = np.clip(pA[123:140] + rng.normal(0, .01, 17), 0, 1)   # 也試 YGAM 不單調(running max 的來源)
    z = np.clip(z_of([pA, pB]), np.r_[fv.MODEL.lo[fv.FIRST], fv.MODEL.lo[fv.LATER]],
                np.r_[fv.MODEL.hi[fv.FIRST], fv.MODEL.hi[fv.LATER]])
    params = fv.unpack_vector(z, [fv.FIRST, fv.LATER], np.cumsum([0, 131, 253]))
    return z_of(params), params


# ---------------------------------------------------------------- unit checks (also the mutation probes)
def check_forward(L, c, z, params, hard):
    xs = c['stages'][0][0][:400]
    lab, jac = np.zeros((len(xs), 3), np.float32), np.zeros((len(xs), 3, NZ), np.float32)
    L.jt_host_forward(ptr(f32(c['toneF'])), ptr(f32(z)), len(xs), ptr(f32(xs)), int(hard), ptr(lab), ptr(jac))
    rv, rj = fv.forward(tools()['fn'], params, [c['toneF'], fv.IDENTITY_TONE], xs, True, hard)
    dv = np.linalg.norm(lab - rv, axis=1)
    scale = np.linalg.norm(rj, axis=(1, 2)) + 1e-3
    dj = np.linalg.norm(jac - rj, axis=(1, 2)) / scale
    return dv, dj


def check_pack(L, c, z, params):
    pay = np.zeros(2 * PAY, np.uint8)
    rc = L.jt_host_pack(ptr(f32(c['toneF'])), ptr(f32(z)), pay.ctypes.data_as(U8P))
    blobs = fv.packets([p.astype(np.float32).astype(float) for p in params], [c['toneF'], fv.IDENTITY_TONE])
    ref = np.r_[blobs[0][64:64 + PAY], blobs[1][64:64 + PAY]]          # (jft.pack's payload ends with m1 since JFIT v5: not this archived format's)
    a, b = pay.view('<u2').astype(int), ref.view('<u2').astype(int)
    diff = np.flatnonzero(a != b)
    # float 的 tone 曲線 vs 參考的 float64:個別 tone 字差 1(第二輪偶數表差 2)是允許的;其他欄要逐字相同
    tone = ((diff >= 12) & (diff < 12 + 3 * 2048)) | ((diff >= PAY // 2 + 12) & (diff < PAY // 2 + 12 + 3 * 2048))
    hard = diff[~tone | (np.abs(a - b)[diff] > 2)]
    return rc, (hard, diff), blobs


def check_replay(L, c, z, blobs):
    xs, want = c['sel']
    out = np.zeros((len(xs), 3), np.float32)
    loss = L.jt_host_replay(ptr(f32(c['toneF'])), ptr(f32(z)), len(xs), ptr(f32(xs)), ptr(f32(want)), ptr(out))
    ref = fc.replay_blobs(blobs, xs)
    ref_loss = fc.loss(np.linalg.norm(F.lab709(ref) - want, axis=1))
    return np.abs(out - ref).max(axis=1), float(loss), ref_loss


def quick_failures(L, c):
    """變異測試用的快速檢查:回傳不通過的項目。"""
    bad = []
    z, params = probe_params(c)
    for hard in (False, True):
        dv, dj = check_forward(L, c, z, params, hard)
        if np.percentile(dv, 99) > 1e-2 or dv.max() > 2e-2 or np.median(dj) > 1e-4 or np.percentile(dj, 95) > 1e-3:
            bad.append(f'forward hard={hard}: dLab p99 {np.percentile(dv, 99):.2e}, jac med {np.median(dj):.2e} p95 {np.percentile(dj, 95):.2e}')
    rc, (hard_diff, diff), blobs = check_pack(L, c, z, params)
    if rc or len(hard_diff) or len(diff) > 12:
        bad.append(f'pack rc {rc}, {len(diff)} words differ ({len(hard_diff)} outside the tone +-2)')
    d, loss, ref_loss = check_replay(L, c, z, blobs)
    if np.mean(d > 1.5 / 255) > .01 or abs(loss - ref_loss) > 2e-3 * ref_loss:
        bad.append(f'replay: {np.mean(d > 1.5 / 255):.3f} off, loss {loss:.5f} vs {ref_loss:.5f}')
    return bad


MUTANTS = [
    ('直通導數換成恆等(忽略第二輪對輸入的導數)',
     'loc[o][k] = DB[o][3 * k + cc] / div;', 'loc[o][k] = o == k ? 1.0f : 0.0f;'),
    ('第二輪表值用 8190 正規化',
     'sc = pass ? 1.0f / 8160.0f : 1.0f / 8190.0f', 'sc = 1.0f / 8190.0f'),
    ('第二輪重播白點用 1918',
     'float white = pass ? 2040.0f : JF_WHITE', 'float white = JF_WHITE'),
    ('YGAM 沒有 H 平滑',
     'Ps[123 + i] = 0.25f * m[i - 1] + 0.5f * m[i] + 0.25f * m[i + 1];', 'Ps[123 + i] = m[i];'),
    ('寫回用 601 係數',
     'const float KR = 0.2126f, KB = 0.0722f', 'const float KR = 0.299f, KB = 0.114f'),
    ('第二輪 tone 沒重取樣到 2040',
     'float x = (float)i * (JF_WHITE / 2040.0f);', 'float x = (float)i;'),
    ('取整改成無條件捨去',
     'if (f > 0.5f || (f == 0.5f && (i & 1))) i++;\n    return (float)i;', 'return (float)i;'),
]


class JfitTwoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.L = build()

    def test_forward_and_jacobian(self):
        for key in ('Kodak', 'BMD'):
            c = context(key)
            z, params = probe_params(c)
            for hard in (False, True):
                dv, dj = check_forward(self.L, c, z, params, hard)
                with self.subTest(key=key, hard=hard):
                    self.assertLess(np.percentile(dv, 99), 1e-2)      # float Lab vs float64
                    self.assertLess(dv.max(), 2e-2)
                    self.assertLess(np.median(dj), 1e-4)
                    self.assertLess(np.percentile(dj, 95), 1e-3)

    def test_pack_and_replay(self):
        for key in LUTS:
            c = context(key)
            z, params = probe_params(c, seed=11)
            rc, (hard_diff, diff), blobs = check_pack(self.L, c, z, params)
            d, loss, ref_loss = check_replay(self.L, c, z, blobs)
            with self.subTest(key=key):
                self.assertEqual(rc, 0)
                self.assertEqual(len(hard_diff), 0, f'payload words differ: {hard_diff}')
                self.assertLessEqual(len(diff), 12, f'{len(diff)} tone words +-1')
                self.assertLess(np.mean(d > 1.5 / 255), .01)
                self.assertLess(abs(loss - ref_loss), 2e-3 * ref_loss)

    def test_first_steps(self):
        # 一到兩步之後還沒被浮點誤差放大(整個擬合對起點 1e-6 的擾動就會差 +-0.1 dE,見 report 的 spread)
        keep = fc.SCHEDULE
        try:
            for key in ('Kodak', 'ARRI'):
                for its in ((1, 0, 0), (2, 0, 0)):
                    fc.SCHEDULE = ((750, False, its[0]),)
                    c = context(key)
                    saved = c.pop('ref', None)
                    ref = reference_fit(key)
                    c['ref'] = saved
                    if saved is None:
                        c.pop('ref')
                    got = c_fit(self.L, c, iters=list(its))
                    with self.subTest(key=key, iters=its[0]):
                        self.assertLess(abs(got['sel'] - ref['sel']), 2e-3 * its[0] * ref['sel'])
                        self.assertLess(abs(got['chart']['mean'] - ref['chart']['mean']), .015)
        finally:
            fc.SCHEDULE = keep

    def test_fit_parity(self):
        rows = []
        for key in LUTS:
            ref, got = reference_fit(key), c_fit(self.L, context(key))
            rows.append((key, ref['sel'], got['sel'], ref['chart']['mean'], got['chart']['mean']))
            with self.subTest(key=key):
                self.assertEqual(got['stats'][6], 0, 'best solution not packable')
                # 容差 = 同一份 C 從起點 x (1 + 1e-6 雜訊) 出發的散佈(sel +-3%、色卡 +-0.1~0.18)
                self.assertLess(abs(got['sel'] - ref['sel']), .04 * ref['sel'])
                self.assertLess(abs(got['chart']['mean'] - ref['chart']['mean']), .15)
                # C 自己的 payload = 參考封裝 C 的參數
                own = np.r_[got['blobs'][0][64:64 + PAY], got['blobs'][1][64:64 + PAY]]
                d = np.abs(got['pay'].view('<u2').astype(int) - own.view('<u2').astype(int))
                self.assertLessEqual(int(d.max()), 2)
                self.assertLessEqual(int(np.sum(d > 0)), 12)
        for r in rows:
            print('%-6s sel %.4f / C %.4f   chart %.3f / C %.3f' % r, file=sys.stderr)

    def test_camera_build(self):
        sys.path.insert(0, str(ROOT / 'fpSup/loader-v4'))
        import build_v4 as B
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'jt_arm.c'
            src.write_text(f'#include "{HERE}/native/jfit.c"\n#include "{HERE}/native/jfit_two.c"\n'
                           '__attribute__((used)) float jt_entry(struct jtwo *T) { return jt_fit(T); }\n'
                           '__attribute__((used)) uint32_t jt_entry2(uint32_t *s, float *x, const float *r, float *w, uint8_t *p, '
                           'struct jtwo *T) { w[0] = jt_weight(r); jt_payload(T->hw, p); jt_identity(x); return jt_draw(s, 10, x); }\n')
            t = B.compile_unit(Path(td), src, 'jt_entry', ['-mno-movt', '-mfloat-abi=softfp', '-mfpu=vfpv3-d16', '-fno-math-errno'])
            self.assertGreater(len(t.code), 1000)

    def test_mutations_caught(self):
        src = (HERE / 'native/jfit_two.c').read_text()
        c = context('Kodak')
        self.assertEqual(quick_failures(self.L, c), [])
        for name, old, new in MUTANTS:
            self.assertEqual(src.count(old), 1, name)
            with self.subTest(mutant=name):
                self.assertTrue(quick_failures(build(src.replace(old, new)), c), f'mutant survived: {name}')


# ---------------------------------------------------------------- report: parity table, timing, work area
def report():
    L = build()
    out = dict(work_bytes=int(L.jt_host_work_bytes(2800, 2800)), struct_bytes=int(L.jt_host_struct_bytes()),
               sample_floats=int(sum(7 * n for n in (1000, 1866, 1866)) + 6 * 2800), luts={})
    for key in LUTS:
        c = context(key)
        ref, got = reference_fit(key), c_fit(L, c)
        # jf_fit_direct,兩個起點 x 10 次(review_sampling.direct10+144 的輸入),同一個 dylib 計時
        fit = E.fit_lvb(c['target'], 100)
        tone = fit['tone'].astype(float)
        if fit['shift']:
            tone = np.stack([np.interp(fc.ft.J.AX / 2 ** fit['shift'], fc.ft.J.AX, ch) for ch in tone])
        matrix = np.asarray(fit['q'], float) * 2 ** fit['shift'] / F.Q9
        pts, w = fc.f_family(c['target'])
        bt, xs, want, wv = f32(tone / F.TONE_MAX), f32(pts), f32(F.lab709(c['target'](pts, 100))), f32(w)
        reps, t0 = 5, time.process_time()
        for _ in range(reps):
            for m in (np.eye(3), matrix):
                P = f32(np.r_[m.ravel(), m.ravel(), np.zeros(27), E.POST_ID])
                L.jt_host_direct(ptr(P), ptr(bt), len(xs), ptr(xs), ptr(want), ptr(wv), 10)
        t_direct = (time.process_time() - t0) / reps
        # 相機版亂數(jt_draw)的樣本:同一分布、不同點
        st = []
        seed = 0x4A54
        for (_, _, _, iters), count in zip(c['stages'], (750, 1400, 1400)):
            x = np.zeros(((count + count // 3), 3), np.float32)
            L.jt_host_draw(seed, count, ptr(x)); seed += 1
            r0 = f32(c['target'](x.astype(float), 0)); wt = np.zeros(len(x), np.float32)
            L.jt_host_weight(len(x), ptr(r0), ptr(wt))
            st.append((x.astype(float), F.lab709(c['target'](x.astype(float), 100)), wt, iters))
        own = c_fit(L, c, stages=st)
        out['luts'][key] = dict(
            ref=dict(sel=ref['sel'], chart=ref['chart'], seconds=ref['seconds']),
            c=dict(sel=got['sel'], chart=got['chart'], seconds=got['seconds'], steps=int(got['stats'][2]),
                   evals=int(got['stats'][3]), gevals=int(got['stats'][4]), checks=int(got['stats'][5]),
                   packable=bool(got['stats'][6] == 0)),
            c_own_draw=dict(sel=own['sel'], chart=own['chart']),
            direct_F_chart=chart_stats(c, fv.packets([c['pF']], [c['toneF']])),
            t_direct_two_starts=t_direct, ratio=got['seconds'] / t_direct)
        print(key, json.dumps(out['luts'][key]['c']['chart']['mean']), file=sys.stderr, flush=True)
    # 舊 jf_fit(數值 Jacobian)1331 點 10 次:相機 4.77 s(validation/20261104-joint-bench-01)
    sys.path.insert(0, str(ROOT / 'projects/lut-sup/probes/bench'))
    import jfit_bench_run as JB
    xs, want, w, bt, P0 = JB.inputs()
    t0 = time.process_time()
    L.jt_host_oldfit(ptr(P0.copy()), ptr(bt), len(xs), ptr(xs), ptr(want), ptr(w), 10)
    out['oldfit_host_10it'] = time.process_time() - t0
    out['camera_over_host'] = 4.77 / out['oldfit_host_10it']
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    if sys.argv[1:] == ['report']:
        report()
    else:
        unittest.main()
