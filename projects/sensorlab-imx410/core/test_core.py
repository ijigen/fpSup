#!/usr/bin/env python3
"""core.c against the CURRENT Python formulas, value for value.

    python3 -B test_core.py              export core_data.h, build (host + ARM), run every comparison
    python3 -B test_core.py --mutants    ... then every mutant of core.c in MUTANTS must fail the comparisons
    python3 -B test_core.py --quick      smaller grids (the mutation run uses these too)

Comparisons (each counts cases and mismatches; any mismatch = exit 1):
  matrix     every case of isp-lab/host/matrix.json AND of matrix.cases() run now: readout plan, smc rows
             (8 tables byte for byte + attrs), isp plan words + the 65-word row
  grid       every readout key x crops x outputs x fps (+ v016 / hmax / hdr variants), rejected ones included:
             same accept/reject and the same reason; smc rows for every distinct accepted plan
  isp        random isp Specs (window, zoom per axis incl. 1024/1025/8191/8192, hbin/vbin 1|3 (+bad), bits)
  quality    isp-lab/host/quality.py: core_line_hmax (R11) for every key x sw 0..10000; core_qualities over every
             preset DC x RES at the 59.94 cap (= matrix.json, case for case) and uncapped, and over random crops / RES /
             caps (flat, tiny, odd, empty, R11 edges, caps at a quality's fps_max); per quality its readout, VMAX range
             and fps key; the Python case's readout args replay its own plan (HMAX, VMAX, 0016, id); then
             core_quality_plan / _spec at VMAX steps (ends, the blanking fallback edge, random; every step on a few)
  proofs     the integer replacements of float expressions, exhaustively: mode_rules._r28 for width / height
             0..65535, fbits for 0..2^20 + random u32, the readout_cfg float predicates for cw / ch 0..40000,
             round(CLK / N, 3)
  arm        clang -target armv7a-none-eabi freestanding compile: no undefined symbols, only PC-relative relocations
"""
import argparse, ctypes, json, os, pathlib, random, re, shutil, struct, subprocess, sys, time
from fractions import Fraction

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
IMXL = ROOT / 'projects' / 'imx410-lab'
ISPH = ROOT / 'projects' / 'isp-lab' / 'host'
BUILD = HERE / 'build'
PROFILES = ROOT / 'research/other/external/FP3K-technical-handoff-2026-09-10/analysis/firmware/raw-profiles.json'
sys.path[:0] = [str(HERE), str(IMXL), str(IMXL / 'offline'), str(ISPH)]
import export_core as EC         # noqa: E402
import readout_cfg as C          # noqa: E402
import smc                       # noqa: E402
import mode_rules as MR          # noqa: E402
import isp_formula as F          # noqa: E402
import quality as Q              # noqa: E402

ARM_FLAGS = ['--target=armv7a-none-eabi', '-mcpu=cortex-a9', '-mthumb', '-mfloat-abi=soft', '-mfpu=none',
             '-mstackrealign', '-ffreestanding', '-fno-builtin', '-nostdlib', '-fno-jump-tables', '-fropi',
             '-fno-addrsig', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-O2', '-std=c11',
             '-Wall', '-Wextra', '-Werror']

# ------------------------------------------------------------------ ctypes mirror of core.h
I32, U32 = ctypes.c_int32, ctypes.c_uint32
A_N = len(EC.attr_enum())
MAX_SENSOR = int(re.search(r'#define CORE_MAX_SENSOR (\d+)', (HERE / 'core.h').read_text()).group(1))


class Plan(ctypes.Structure):
    _fields_ = [(n, I32) for n in (
        'key hdr donor bits mh mv is_new cw ch ow oh fmt_w line_w raster_w out_h y_skip receiver_lines '
        'sw_num sw_den sh_num sh_den fast_set tim_line r38_words hmax vmax vmin rx_width rx_end n_sensor').split()] + \
        [('sensor', (U32 * 2) * MAX_SENSOR)]


class Mode(ctypes.Structure):
    _fields_ = [('attrs', I32 * A_N), ('tim', ctypes.c_uint8 * 0x20), ('meta', ctypes.c_uint8 * 100),
                ('r28', ctypes.c_uint8 * 0x28), ('r38', ctypes.c_uint8 * 0x38), ('r14', ctypes.c_uint8 * 0x14),
                ('r68', ctypes.c_uint8 * 0x68), ('reg', ctypes.c_uint8 * 0x288), ('r10', ctypes.c_uint8 * 8)]


class Spec(ctypes.Structure):
    _fields_ = [(n, I32) for n in 'win_w win_h zh zv sx sy vbin hbin bits hirate has_rec rec_w rec_h'.split()]


class IspRes(ctypes.Structure):
    _fields_ = [('why', I32), ('rec', I32 * 2), ('act', I32 * 2), ('path', I32), ('preview', I32 * 4),
                ('source', I32 * 2), ('visible', I32 * 2), ('raster', I32 * 2), ('standby', I32 * 2),
                ('words', U32 * 65), ('mask', U32 * 3)]


QFIELDS = ('mh mv ad hbin vbin key bits cw ch sw sh hmax rows capped hm vmin_lo vmin vmax fps_milli win_w win_h zh zv '
           'rec_w rec_h path seq lines vis_w vis_h rs_us').split()


class Qual(ctypes.Structure):
    _fields_ = [(n, I32) for n in QFIELDS]


def _errcodes():
    txt = (HERE / 'core.h').read_text()
    return {m.group(1): int(m.group(2)) for m in re.finditer(r'(CORE_E_\w+) = (-\d+)', txt)}


E = _errcodes()
PATHS = {1: 'B', 2: 'C', 3: 'D', 4: 'E1', 5: 'E3'}
TABLE_NAMES = ['TIM', 'META', 'R28', 'R38', 'R14', 'R68', 'REG', 'R10']


# ------------------------------------------------------------------ build
def build_host(src=HERE / 'core.c', name='core_host', werror=True):
    BUILD.mkdir(exist_ok=True)
    out = BUILD / f'{name}.dylib'
    r = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Wextra'] + (['-Werror'] if werror else ['-w']) + ['-shared', '-fPIC',
                        '-I', str(HERE), '-o', str(out), str(src)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError('host compile failed:\n' + r.stderr)
    lib = ctypes.CDLL(str(out))
    lib.core_readout_plan.argtypes = [ctypes.c_int] * 5 + [U32, U32, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                           ctypes.c_int, ctypes.POINTER(Plan)]
    lib.core_smc_create.argtypes = [ctypes.POINTER(Plan), ctypes.POINTER(Mode)]
    lib.core_isp_plan.argtypes = [ctypes.POINTER(Spec), ctypes.POINTER(IspRes)]
    lib.core_isp_row.argtypes = [ctypes.POINTER(Spec), ctypes.POINTER(U32 * 65), ctypes.POINTER(U32 * 65)]
    lib.core_r28.argtypes = [I32, I32, ctypes.POINTER(I32 * 8)]
    lib.core_fbits.argtypes = [U32]; lib.core_fbits.restype = U32
    lib.core_py_vmax.argtypes = [U32, U32, U32]; lib.core_py_vmax.restype = ctypes.c_int64
    lib.core_key_index.argtypes = [ctypes.c_char_p]
    lib.core_line_hmax.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.core_qualities.argtypes = [ctypes.c_int] * 4 + [U32, U32, ctypes.POINTER(Qual), ctypes.c_int]
    lib.core_quality_plan.argtypes = [ctypes.POINTER(Qual), U32, U32, ctypes.POINTER(Plan)]
    lib.core_quality_spec.argtypes = [ctypes.POINTER(Qual), ctypes.POINTER(Spec)]
    lib.core_quality_spec.restype = None
    lib.core_fps_milli.argtypes = [U32]; lib.core_fps_milli.restype = I32
    lib.core_qualities_tol.argtypes = [ctypes.c_int] * 4 + [U32, U32, U32, U32, ctypes.POINTER(Qual), ctypes.c_int]
    lib.core_short_ok.argtypes = [ctypes.c_int] * 4 + [U32, U32]
    lib.core_r16_rows.argtypes = [ctypes.c_int, ctypes.c_int, U32, U32]
    lib.core_js_fixed.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_int]; lib.core_js_fixed.restype = ctypes.c_int64
    return lib


def build_arm():
    BUILD.mkdir(exist_ok=True)
    obj = BUILD / 'core_arm.o'
    r = subprocess.run(['clang', *ARM_FLAGS, '-I', str(HERE), '-c', str(HERE / 'core.c'), '-o', str(obj)],
                       capture_output=True, text=True)
    if r.returncode:
        return False, 'ARM compile failed:\n' + r.stderr
    nm = subprocess.run(['nm', str(obj)], capture_output=True, text=True).stdout
    und = [l for l in nm.splitlines() if re.match(r'\s+U ', l)]
    rel = subprocess.run(['objdump', '-r', str(obj)], capture_output=True, text=True).stdout
    kinds = sorted({l.split()[1] for l in rel.splitlines() if re.match(r'[0-9a-f]{8} R_ARM', l)})
    bad = [k for k in kinds if 'PREL' not in k and k not in ('R_ARM_THM_CALL', 'R_ARM_THM_JUMP24')]
    hdr = subprocess.run(['objdump', '-h', str(obj)], capture_output=True, text=True).stdout
    sizes = {}
    for l in hdr.splitlines():
        m = re.match(r'\s*\d+\s+(\.\S+)\s+([0-9a-f]+)', l)
        if m and m.group(1).startswith(('.text', '.rodata', '.data', '.bss')):
            sizes[m.group(1)] = int(m.group(2), 16)
    ok = not und and not bad and not any(k.startswith(('.data', '.bss')) and v for k, v in sizes.items())
    msg = (f'ARM: .text {sizes.get(".text", 0)} B, rodata {sum(v for k, v in sizes.items() if k.startswith(".rodata"))} B, '
           f'data/bss {sum(v for k, v in sizes.items() if k.startswith((".data", ".bss")))} B; undefined {und or "none"}; '
           f'relocations {kinds}')
    return ok, msg


# ------------------------------------------------------------------ python side
def py_err_plan(e):
    s = str(e)
    if isinstance(e, ZeroDivisionError):
        return E['CORE_E_ZERO']
    if isinstance(e, KeyError):
        return E['CORE_E_KEY']
    for pat, code in (('wider than', 'WIDE'), ('3:1 horizontal', 'H3V1'), ('cannot upscale', 'UPSCALE'),
                      ('vertical window not tested', 'NOWIN'), ('below the floor', 'HMAX'), ('output rows >', 'ROWS'),
                      ('below the tested minimum', 'V016'), ('< minimum', 'VMIN'), ('(14-bit SoC field)', 'VMAX'),
                      ('(V3 margin)', 'MARGIN'), ('(V3 skip)', 'SKIP'), ('outside the readable', 'WINROWS'),
                      ('row crop', 'ROWCROP')):
        if pat in s:
            return E['CORE_E_' + code]
    return ('unmapped', s)


def plan_kw(args):
    """readout_cfg.plan's optional arguments: a dict in args[6] (grid), or positional after fps (matrix.json: v016, hmax;
    R16 cases: hdr, rows)."""
    if len(args) > 6 and isinstance(args[6], dict):
        return args[6]
    return {k: v for k, v in zip(('v016', 'hmax', 'hdr', 'rows'), args[6:]) if v is not None}


def py_plan(args):
    key, cw, ch, ow, oh, fps = args[:6]
    kw = plan_kw(args)
    try:
        return C.plan(key, cw, ch, ow, oh, None if fps is None else float(fps), **kw), 0
    except (ValueError, KeyError, ZeroDivisionError) as e:
        return None, py_err_plan(e)


def fps_frac(fps):
    if fps is None:
        return 0, 1
    f = fps if isinstance(fps, Fraction) else Fraction(str(fps))
    return f.numerator, f.denominator


class Core:
    def __init__(self, lib):
        self.lib = lib
        self.keyidx = {k: i for i, k in enumerate(EC_KEYS)}

    def plan(self, args):
        key, cw, ch, ow, oh, fps = args[:6]
        kw = plan_kw(args)
        n, d = fps_frac(fps)
        p = Plan()
        rc = self.lib.core_readout_plan(self.keyidx.get(key, -1), cw, ch, ow, oh, n, d,
                                        -1 if kw.get('v016') is None else kw['v016'], kw.get('hmax') or 0,
                                        kw.get('hdr', 0), -1 if kw.get('rows') is None else kw['rows'], ctypes.byref(p))
        return p, rc

    def create(self, p):
        m = Mode()
        rc = self.lib.core_smc_create(ctypes.byref(p), ctypes.byref(m))
        return m, rc

    def isp(self, s):
        cs = spec_c(s)
        o = IspRes()
        rc = self.lib.core_isp_plan(ctypes.byref(cs), ctypes.byref(o))
        return o, rc

    def qualities(self, cw, ch, ow, oh, cap, tol=None):
        n, d = fps_frac(cap)
        arr = (Qual * 200)()
        if tol is None:
            rc = self.lib.core_qualities(cw, ch, ow, oh, n, d, arr, 200)
        else:
            t = TOLS[tol]
            rc = self.lib.core_qualities_tol(cw, ch, ow, oh, n, d, t.numerator, t.denominator, arr, 200)
        return (list(arr[:rc]) if rc >= 0 else None), (0 if rc >= 0 else rc)

    def row(self, s, base):
        cs = spec_c(s)
        b = (U32 * 65)(*base); out = (U32 * 65)()
        rc = self.lib.core_isp_row(ctypes.byref(cs), ctypes.byref(b), ctypes.byref(out))
        return list(out), rc


EC_KEYS = [r['key'] for r in C.READOUTS]


def spec_c(s):
    rec = s.rec
    return Spec(s.window[0], s.window[1], s.zoom[0], s.zoom[1], int(s.scale[0]), int(s.scale[1]), s.vbin, s.hbin,
                s.bits, int(bool(s.hirate)), 1 if rec else 0, rec[0] if rec else 0, rec[1] if rec else 0)


def plan_diff(pp, cp):
    """field-by-field: Python plan dict vs C plan; [] when identical"""
    d = []
    def chk(name, a, b):
        if a != b:
            d.append((name, a, b))
    mh, mv = (int(x) for x in pp['merge'].split('x'))
    chk('key', pp['key'], EC_KEYS[cp.key]); chk('hdr', pp['hdr'], cp.hdr); chk('donor', pp['donor'], cp.donor)
    chk('bits', pp['bits'], cp.bits); chk('merge', (mh, mv), (cp.mh, cp.mv)); chk('mv', pp['mv'], cp.mv)
    chk('new', pp['new'], bool(cp.is_new)); chk('crop', pp['crop'], [cp.cw, cp.ch]); chk('out', pp['out'], [cp.ow, cp.oh])
    for f in ('fmt_w', 'line_w', 'raster_w', 'out_h', 'y_skip', 'receiver_lines'):
        chk(f, pp[f], getattr(cp, f))
    sw = cp.sw_num / cp.sw_den if cp.sw_den != 1 else float(cp.sw_num)
    sh = cp.sh_num / cp.sh_den
    chk('rwzm', pp['rwzm'], [sw / cp.ow, sh / cp.oh])
    chk('sensor', [tuple(x) for x in pp['sensor']], [(cp.sensor[i][0], cp.sensor[i][1]) for i in range(cp.n_sensor)])
    chk('fast_set', pp['fast_set'], bool(cp.fast_set))
    chk('rows', pp['rows'], dict(TIM_line=cp.tim_line or None, R38_words=cp.r38_words or None))
    chk('soc', pp['soc'], dict(hmax=cp.hmax, vmax=cp.vmax, rx_width=cp.rx_width, rx_end=cp.rx_end))
    chk('fps', pp['fps'], C.CLK / (cp.hmax * cp.vmax)); chk('fps_max', pp['fps_max'], C.CLK / (cp.hmax * cp.vmin))
    chk('rolling_ms', pp['rolling_ms'], cp.hmax * cp.receiver_lines / C.CLK * 1e3)
    return d


def py_create(pp):
    try:
        a, rows, how = smc.create(pp)
        return (a, {t: bytes(rows[t]) for t in rows}), 0
    except (ValueError, KeyError, ZeroDivisionError, IndexError) as e:
        return None, ('err', type(e).__name__)


def mode_diff(pa, m):
    a, rows = pa
    d = []
    names = EC.attr_enum()
    ca = {n: m.attrs[i] for i, n in enumerate(names)}
    if set(a) != set(ca):
        d.append(('attr names', sorted(set(a) ^ set(ca))))
    for n in a:
        if a[n] != ca.get(n):
            d.append(('attr ' + n, a[n], ca.get(n)))
    for t in TABLE_NAMES:
        cb = bytes(getattr(m, t.lower()))
        if rows.get(t) != cb:
            first = next((i for i in range(len(cb)) if rows[t][i] != cb[i]), None) if t in rows and len(rows[t]) == len(cb) else 'len'
            d.append(('row ' + t, first))
    return d


def isp_diff(s, cr):
    """Python isp_formula.plan vs C, accept/reject + every field"""
    o, rc = cr
    try:
        p = F.plan(s)
    except F.NotPossible as e:
        why = {'outside 1024': 1, 'a CRCT bin is 1 or 3': 2, 'unity record does not bin': 3, '(R8)': 4,
               'needs the preview to equal': 5, 'no preview avoids': 6, 'empty preview': 7}
        w = next((v for k, v in why.items() if k in str(e)), ('unmapped', str(e)))
        return [] if (rc == E['CORE_E_ISP'] and o.why == w) else [('reject', str(e), rc, o.why)]
    except KeyError as e:
        return [] if rc == E['CORE_E_LOOKUP'] else [('keyerror', str(e), rc)]
    if rc:
        return [('accept', 'python accepts', rc, o.why)]
    d = []
    def chk(n, a, b):
        if a != b:
            d.append((n, a, b))
    chk('rec', tuple(p.rec), tuple(o.rec)); chk('act', tuple(p.act), tuple(o.act)); chk('path', p.path, PATHS.get(o.path))
    chk('preview', tuple(p.preview), tuple(o.preview)); chk('source', tuple(p.source), tuple(o.source))
    chk('visible', tuple(p.visible), tuple(o.visible)); chk('raster', tuple(p.raster), tuple(o.raster))
    chk('standby', tuple(p.standby), tuple(o.standby))
    cw = {4 * i: o.words[i] for i in range(65) if (o.mask[i >> 5] >> (i & 31)) & 1}
    chk('words', {k: v & 0xFFFFFFFF for k, v in p.words.items()}, cw)
    return d


# ------------------------------------------------------------------ comparisons
class Tally:
    def __init__(self):
        self.n = {}
        self.bad = {}

    def add(self, name, diff, ctx):
        self.n[name] = self.n.get(name, 0) + 1
        if diff:
            b = self.bad.setdefault(name, [])
            if len(b) < 5:
                b.append((ctx, diff[:4] if isinstance(diff, list) else diff))
            self.bad[name + '#'] = self.bad.get(name + '#', 0) + 1

    def failed(self):
        return sum(v for k, v in self.bad.items() if k.endswith('#'))

    def report(self):
        for k in sorted(self.n):
            print(f'  {k:28s} {self.n[k]:8d} compared, {self.bad.get(k + "#", 0):6d} mismatches')
            for ctx, d in self.bad.get(k, []):
                print(f'      {ctx}: {d}')


def cmp_plan(core, T, name, args):
    pp, pe = py_plan(args)
    cp, ce = core.plan(args)
    if pp is None or ce:
        T.add(name + ' accept/reject', [] if (pp is None and ce == pe) else [('py', pe, 'c', ce)], args)
        return None, None
    T.add(name + ' accept/reject', [], args)
    T.add(name + ' plan fields', plan_diff(pp, cp), args)
    return pp, cp


def cmp_create(core, T, name, pp, cp, ctx):
    pa, pe = py_create(pp)
    m, ce = core.create(cp)
    if pa is None or ce:
        T.add(name + ' smc accept/reject', [] if (pa is None and ce) else [('py', pe, 'c', ce)], ctx)
        return
    T.add(name + ' smc accept/reject', [], ctx)
    T.add(name + ' smc rows+attrs', mode_diff(pa, m), ctx)


def base_row():
    j = json.loads(PROFILES.read_text())
    return next(r['words'] for r in j['rows'] if 171 in r['profile_ids'])


def matrix_cases():
    out = [('json', c) for c in json.loads((ISPH / 'matrix.json').read_text())]
    import importlib.util
    spec = importlib.util.spec_from_file_location('isp_matrix', ISPH / 'matrix.py')
    M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
    out += [('live', c) for c in M.cases()]
    return out


def run_matrix(core, T, base, quick=False):
    cases = matrix_cases()
    if quick:
        cases = cases[::7]
    for src, c in cases:
        args = list(c['readout'])
        pp, cp = cmp_plan(core, T, f'matrix-{src}', args)
        if pp is not None:
            cmp_create(core, T, f'matrix-{src}', pp, cp, c['readout_id'])
        s = F.Spec(window=tuple(c['window']), zoom=tuple(c['zoom']), scale=tuple(int(x) for x in c['merge'].split('x')),
                   vbin=c['vbin'], hbin=c['hbin'], bits=c['bits'], rec=tuple(c['rec']))
        T.add(f'matrix-{src} isp plan', isp_diff(s, core.isp(s)), c['readout_id'])
        try:
            want = F.row(s, base)
        except (F.NotPossible, KeyError):
            want = None
        got, rc = core.row(s, base)
        T.add(f'matrix-{src} isp row', [] if (want is None and rc) or (want == got and not rc) else [('row', rc)],
              c['readout_id'])
        if src == 'live':                       # the case's window is the plan's raster (matrix.isp glue)
            T.add('matrix-live window=plan', [] if cp is not None and [cp.raster_w, cp.out_h] == c['window'] else ['window'],
                  c['readout_id'])


FPS = [None, '1', '4', '23.976', '24', '25', '29.97', '30', '48', '50', '59.94', '60', '100', '119.88', '120',
       '180', '240', '287']


def grid_args(quick=False):
    out = []
    for r in C.READOUTS:
        k, mh, mv = r['key'], r['mh'], r['mv']
        lws = sorted({C.line_width(r, w) for w in r['fmt']})
        cws = {1, 16, 100, 2000, 2016, 2108, 3032, 3958, 4040, 4192, 5073, 6000, 6048, 6064, 6080, 7000}
        for lw in lws:
            t = lw * mh
            cws |= {t - 1, t, t + 1, -(-t * 1000 // 995) - 1, -(-t * 1000 // 995), -(-t * 1000 // 995) + 1}
        chs = {0, 2, 3, 100, 1000, 1248, 2160, 2358, 2628, 3402, 4000, 4040, 4100, 8000,
               C.SENSOR_H - 2 * mv - 1, C.SENSOR_H - 2 * mv, C.SENSOR_H - 2 * mv + 1}
        if quick:
            cws = set(sorted(cws)[::3]); chs = set(sorted(chs)[::3])
        for cw in sorted(cws):
            for ch in sorted(chs):
                sw, sh = cw // mh, ch // mv
                if ch >= C.SENSOR_H:
                    sh = min(sh, C.full_rows(k))
                outs = {(sw, sh), (max(sw // 2, 1), max(sh // 2, 1)), (sw + 1, sh), (sw, sh + 1), (0, sh), (1920, 1080)}
                for ow, oh in sorted(outs):
                    for fps in (FPS[::4] if quick else FPS):
                        out.append([k, cw, ch, ow, oh, fps])
    # the optional knobs
    for r in C.READOUTS:
        k = r['key']
        for kw in (dict(v016=0), dict(v016=2), dict(v016=7), dict(v016=r['v016']), dict(v016=r['v016'] + 5),
                   dict(hmax=r['hmin'] - 1), dict(hmax=r['hmin'] + 100), dict(hdr=0x40), dict(hdr=1, v016=50)):
            for cw, ch, ow, oh in ((6048, 4040, 1920, 1080), (4192, 2358, 4192 // r['mh'], 2358 // r['mv']),
                                   (2108, 1248, 1920 // r['mh'], 1080 // r['mv'])):
                for fps in (None, '23.976', '59.94', '120'):
                    out.append([k, cw, ch, ow, oh, fps, kw])
    # R16 row crops: every key at full height (and on windows, where they must be refused) x rows around the edges
    for r in C.READOUTS:
        k, mh, mv = r['key'], r['mh'], r['mv']
        full = C.full_rows(k)
        for cw, ch in ((6048, 4040), (4192, 4040), (2108, 4040), (6048, 3402), (6048, C.SENSOR_H - 2 * mv)):
            for rows in sorted({0, 1, 2, 208, 392, 566, 567, full - 2, full - 1, full, full + 2}):
                for oh in sorted({max(rows, 1), max(rows - 2, 1), rows + 2, 1080 // mv, 0}):
                    for fps in (None, '59.94', '287'):
                        out.append([k, cw, ch, cw // mh, oh, fps, dict(rows=rows)])
    out.append(['nokey', 6048, 4040, 1920, 1080, None])
    return out


def run_grid(core, T, quick=False, smc_cap=None):
    seen = set()
    nsmc = 0
    for args in grid_args(quick):
        pp, cp = cmp_plan(core, T, 'grid', args)
        if pp is None:
            continue
        sig = (pp['key'], pp['fmt_w'], pp['line_w'], pp['raster_w'], pp['out_h'], pp['y_skip'],
               tuple(map(tuple, pp['sensor'])), pp['soc']['hmax'], pp['soc']['vmax'], pp['fast_set'])
        if sig in seen or (smc_cap and nsmc >= smc_cap):
            continue
        seen.add(sig); nsmc += 1
        cmp_create(core, T, 'grid', pp, cp, args)


def run_fps_sweep(core, T, quick=False):
    """dense fps (k / 1000 and k / 1001) on a few readouts: Python float vs the C rational near round() ties"""
    keys = ['12', '2x2fast', '3x3fast', 'f12v3', '14']
    step = 37 if quick else 3
    for k in keys:
        r = C.BY_KEY[k]
        for num in range(1000, 300000, step):
            for den in (1000, 1001):
                fps = str(Fraction(num, den)) if den == 1001 else f'{num / 1000:g}'
                if den == 1001:
                    # pass the exact rational to C; Python gets the nearest double of it
                    args = [k, 2108, 1248, 2108 // r['mh'], 1248 // r['mv'], None]
                    pp, pe = _py_plan_float(args, num / den)
                    cp, ce = _c_plan_frac(core, args, num, den)
                    T.add('fps-sweep accept/reject', [] if (pp is None and ce == pe) or (pp and not ce) else [(pe, ce)], (k, num, den))
                    if pp and not ce:
                        T.add('fps-sweep vmax', [] if pp['soc']['vmax'] == cp.vmax else [(pp['soc']['vmax'], cp.vmax)], (k, num, den))
                else:
                    cmp_plan(core, T, 'fps-sweep', [k, 2108, 1248, 2108 // r['mh'], 1248 // r['mv'], fps])


def _py_plan_float(args, f):
    try:
        return C.plan(*args[:5], f), 0
    except (ValueError, KeyError, ZeroDivisionError) as e:
        return None, py_err_plan(e)


def _c_plan_frac(core, args, n, d):
    key, cw, ch, ow, oh = args[:5]
    p = Plan()
    rc = core.lib.core_readout_plan(core.keyidx[key], cw, ch, ow, oh, n, d, -1, 0, 0, -1, ctypes.byref(p))
    return p, rc


ZOOMS = [1023, 1024, 1025, 1026, 1536, 2048, 2730, 3072, 4096, 6144, 8190, 8191, 8192, 9000]


# ------------------------------------------------------------------ quality.py
# the visible tolerances compared (quality.py takes a float; C the rational it stands for: proofs below)
TOLS = {0.02: Fraction(1, 50), 0.005: Fraction(1, 200), 0.002: Fraction(1, 500), 0.01: Fraction(1, 100),
        0.03: Fraction(3, 100), 0.0: Fraction(0, 1)}


def py_qualities(cw, ch, ow, oh, cap, tol=None):
    try:
        return Q.qualities(cw, ch, ow, oh, cap, tol=tol), 0
    except ZeroDivisionError:
        return None, E['CORE_E_ZERO']


def py_rs_us(c):
    return round(round(Q.settings(c)[0]['rolling_ms'], 3) * 1000)


def py_qrec(c, cap):
    """what core_quality holds, from a quality.py case"""
    args = c['readout']
    key, cw, ch, sw, sh = args[:5]
    p = Q.readout(key, cw, ch, cap, Q.rows_of(c))       # the case's own plan (its args may name the cap: see below)
    lo, vmin, _ = Q.vmax_range(c)
    m, ad, hb, vb = Q.quality_of(c)
    return dict(mh=int(m.split('x')[0]), mv=int(m.split('x')[1]), ad=int(ad), hbin=hb, vbin=vb, key=key, bits=c['bits'],
                cw=cw, ch=ch, sw=sw, sh=sh, hmax=(args[7] if len(args) > 7 else 0) or 0,
                rows=-1 if Q.rows_of(c) is None else Q.rows_of(c), capped=args[5] is not None,
                hm=p['soc']['hmax'], vmin_lo=lo, vmin=vmin, vmax=p['soc']['vmax'], fps_milli=round(c['fps'] * 1000),
                win_w=c['window'][0], win_h=c['window'][1], zh=c['zoom'][0], zv=c['zoom'][1], rec_w=c['rec'][0],
                rec_h=c['rec'][1], path=c['path'], lines=p['receiver_lines'],
                vis_w=c['rec'][0] - F.MARGIN[0], vis_h=c['rec'][1] - F.MARGIN[1], rs_us=py_rs_us(c))


def v016_of(p):
    return [x for x in p['sensor'] if x[0] == 0x0016]


def c_qrec(q):
    d = {n: getattr(q, n) for n in QFIELDS if n != 'seq'}
    d['key'] = EC_KEYS[q.key]; d['capped'] = bool(q.capped); d['path'] = PATHS.get(q.path)
    return d


def cmp_qualities(core, T, name, cell, cap, steps=0, rnd=None, tol=None):
    """quality.qualities vs core_qualities for one cell; steps > 0: settings at that many VMAX steps per quality.
    cap: a float, or a Fraction (C gets it exactly, Python gets its nearest float).  tol: a TOLS key (core_qualities_tol;
    each case's own visible = vis_w / vis_h, and the Python nominal is the clean RES - 16 x 10)"""
    ccap, cap = cap, (float(cap) if isinstance(cap, Fraction) else cap)
    pq, pe = py_qualities(*cell, cap, tol)
    cq, ce = core.qualities(*cell, ccap, tol)
    if tol is not None and pq:
        T.add(name + ' visible / nominal', [] if all(c['visible'] == [c['rec'][0] - 16, c['rec'][1] - 10] and
              c['nominal'] == [cell[2] - 16, cell[3] - 10] for c in pq) else [('visible', cell)], (cell, cap, tol))
    if pq is None or ce:
        T.add(name + ' accept/reject', [] if (pq is None and pe == ce) else [('py', pe, 'c', ce)], (cell, cap))
        return pq, cq
    T.add(name + ' accept/reject', [], (cell, cap))
    T.add(name + ' count', [] if len(pq) == len(cq) else [(len(pq), len(cq))], (cell, cap))
    for c in pq:                                        # the args replay exactly the plan the case came from
        a = c['readout']
        want = Q.readout(a[0], a[1], a[2], cap, Q.rows_of(c))
        got = C.plan(*a)
        T.add(name + ' args replay', [] if (got['soc'], v016_of(got), got['id']) == (want['soc'], v016_of(want), c['readout_id'])
              else [('replay', a, got['soc'], want['soc'])], (cell, cap, c['quality']))
    for c, q in zip(pq, cq):
        a, b = py_qrec(c, cap), c_qrec(q)
        T.add(name + ' quality', [(k, a[k], b[k]) for k in a if a[k] != b[k]], (cell, cap, c['quality']))
        if steps:
            cmp_settings(core, T, name, c, q, steps, rnd)
    return pq, cq


def cmp_settings(core, T, name, c, q, steps, rnd):
    """core_quality_plan / _spec at VMAX steps vs quality.settings at fps_at(VMAX): same plan, and VMAX is the step"""
    lo, vmin, top = Q.vmax_range(c)
    hm = q.hm
    vs = {lo, lo + 1, vmin - 1, vmin, vmin + 1, top - 1, top, lo - 1, top + 1}
    vs |= {rnd.randint(lo, top) for _ in range(steps)}
    for v in sorted(x for x in vs if x >= 1):
        pp = cp = None
        try:
            pp, ps = Q.settings(c, Q.fps_at(c, v))
            pe = 0
        except ValueError as e:
            pe = py_err_plan(e)
        cp = Plan()
        ce = core.lib.core_quality_plan(ctypes.byref(q), int(C.CLK), hm * v, ctypes.byref(cp))
        inside = lo <= v <= top
        if pp is None or ce:
            T.add(name + ' settings accept/reject', [] if (pp is None and pe == ce and not inside) else [('py', pe, 'c', ce, v)],
                  (c['readout'], v))
            continue
        T.add(name + ' settings accept/reject', [] if inside else [('accepted outside', v)], (c['readout'], v))
        d = plan_diff(pp, cp)
        if pp['soc']['vmax'] != v or cp.vmax != v:
            d.append(('vmax not the step', v, pp['soc']['vmax'], cp.vmax))
        T.add(name + ' settings plan', d, (c['readout'], v))
    cs = Spec()
    core.lib.core_quality_spec(ctypes.byref(q), ctypes.byref(cs))
    want = spec_c(Q.settings(c)[1])
    T.add(name + ' settings spec', [] if bytes(cs) == bytes(want) else [('spec', list(want.__class__._fields_))],
          c['readout'])


def preset_cells():
    import importlib.util
    spec = importlib.util.spec_from_file_location('isp_matrix', ISPH / 'matrix.py')
    M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
    return M, [(dc, (cw, ch) + res) for dc, (cw, ch) in M.DC.items() for res in M.res_list(dc)]


def run_quality(core, T, quick=False, n_random=2000, seed=1029):
    rnd = random.Random(seed)
    # R11
    for k in EC_KEYS:
        for sw in range(0, 10001, 7 if quick else 1):
            want = Q.line_hmax(k, sw) or 0
            T.add('quality R11 line_hmax', [] if core.lib.core_line_hmax(EC_KEYS.index(k), sw) == want else [(k, sw, want)], (k, sw))
    # preset DC x RES: at the host cap the cases are matrix.json's, case for case; uncapped too
    M, cells = preset_cells()
    mj = json.loads((ISPH / 'matrix.json').read_text())
    got = []
    for dc, cell in cells:
        pq, cq = cmp_qualities(core, T, 'quality preset@59.94', cell, M.HOST_FPS, steps=0 if quick else 2, rnd=rnd)
        got += [dict(dc=dc, **c) for c in pq or []]
        cmp_qualities(core, T, 'quality preset uncapped', cell, None, steps=0 if quick else 2, rnd=rnd)
    strip = lambda c: {k: v for k, v in c.items() if k not in ('name', 'id')}
    # R16's cases are held out of matrix.json until their live test (isp-lab/notes/R16_CANDIDATES.md): they only add
    old = [c for c in got if Q.rows_of(c) is None]
    T.add('quality preset = matrix.json', [] if [strip(c) for c in mj] == old else [('cases', len(mj), len(old))], 'matrix')
    T.add('quality preset R16 cases', [] if len(got) - len(old) >= 8 else [('R16 cases', len(got) - len(old))], 'matrix')
    # arbitrary crops / RES / caps
    caps = [None, None, None, 59.94, 29.97, 23.976, 119.88, 120, 30, 240, 1]
    n = 150 if quick else n_random
    for i in range(n):
        cw = rnd.choice([rnd.randint(1, 6100), rnd.randint(1, 380) * 16, rnd.choice([6064, 6065, 6048, 6049, 6032, 4192, 4176,
                         4160, 5073, 5057, 4016, 4000, 3032, 2016, 2108, 3958, 1, 2, 3, 15, 16, 48])])
        ch = rnd.choice([rnd.randint(1, 4100), rnd.randint(2, 300), rnd.randint(1, 60), rnd.choice([4040, 4039, 4041, 4100,
                         4036, 4034, 3402, 2358, 2628, 1248, 2, 3, 6])])
        k = rnd.choice([1, 1, 2, 3, 4, 6, rnd.uniform(1, 8)])
        ow = rnd.choice([int(cw / k) // 16 * 16, int(cw / k) // 16 * 16 - 16, int(cw / k), rnd.randint(0, 6100),
                         -(-cw // 16) * 16 + 16, int(cw / k) // 16 * 16 + 16,       # RES a little wider than the crop
                         rnd.randint(1, 120) * 16, 1920, 3840, 0 if i % 97 == 0 else 16])
        oh = rnd.choice([ow * ch // max(cw, 1) & ~1, (ow * ch // max(cw, 1) & ~1) - 2, ow * ch // max(cw, 1) | 1,
                         int(ch / rnd.choice([1, 2, 3, 6, k])) & ~1, rnd.randint(0, 4100), 1080, 2160, 0 if i % 89 == 0 else 2])
        ow, oh = max(ow, 0), max(oh, 0)
        cmp_qualities(core, T, 'quality random', (cw, ch, ow, oh), rnd.choice(caps), steps=1 if quick else 3, rnd=rnd)
    # caps right at a quality's fps_max (the 0.01 fps window of quality.readout's args): the uncapped fps_max of a
    # random quality, then caps a hair above / below it
    for i in range(40 if quick else 400):
        cw = rnd.choice([6048, 4192, 3958, 2108, rnd.randint(16, 6064)]); ch = rnd.choice([rnd.randint(2, 4100), 4040, 2358])
        k = rnd.choice([1, 2, 3])
        cell = (cw, ch, cw // k // 16 * 16, (cw // k // 16 * 16) * ch // cw & ~1)
        try:
            qs = Q.qualities(*cell)
        except ZeroDivisionError:
            continue
        if qs:
            c = rnd.choice(qs)
            fx = Fraction(int(C.CLK), Q.hmax_of(c) * Q.vmax_range(c)[1])      # its fps_max: the cap exactly at it
            f = float(fx)
            for d in (0, 0.005, 0.0095, 0.0105, 0.05, -0.005, -0.05):
                cmp_qualities(core, T, 'quality near cap', cell, fx if d == 0 else float(f'{f + d:.4f}'), steps=1, rnd=rnd)
    # R11 edges: the raster (ceil16 of sw) crosses a readout's floor while sw does not (12fastW / f12v2 / f12v3 at 400,
    # f12w18 / f12v2w18 at 340)
    for cw in list(range(5780, 5810)) + list(range(4905, 4935)):
        cmp_qualities(core, T, 'quality R11 edge', (cw, 2000, cw // 16 * 16, (cw // 16 * 16) * 2000 // cw & ~1),
                      None, steps=0, rnd=rnd)
    # flat crops aimed at high fps, every VMAX step on a few of their qualities
    # R16 edges: DCs just under full height (the V3 frame shorter than the DC), and the row crop through every DC height
    for ch in (4032, 4034, 4036, 4038, 4039, 3990, 3984, 3402, 2358, 1248, 600, 64):
        for cw, k in ((6048, 6), (4032, 3), (4032, 4), (2108, 6)):
            ow = cw // k // 16 * 16
            cmp_qualities(core, T, 'quality R16 edge', (cw, ch, ow, ow * ch // cw & ~1), rnd.choice([None, 59.94]),
                          steps=1, rnd=rnd)
    run_quality_tol(core, T, rnd, quick, cells)
    flats = [(6048, 64, 2016, 20), (6048, 120, 2016, 40), (3032, 32, 1008, 10), (4192, 48, 4176, 48), (6048, 16, 6048, 16)]
    for cell in flats[:2] if quick else flats:
        pq, cq = cmp_qualities(core, T, 'quality flat', cell, None, steps=2, rnd=rnd)
        for c, q in list(zip(pq or [], cq or []))[:1 if quick else 3]:
            lo, _, top = Q.vmax_range(c)
            for v in range(lo, top + 1, 97 if quick else 1):
                cp = Plan()
                ce = core.lib.core_quality_plan(ctypes.byref(q), int(C.CLK), q.hm * v, ctypes.byref(cp))
                pv = Q.settings(c, Q.fps_at(c, v))[0]['soc']['vmax']
                T.add('quality every VMAX step', [] if (not ce and cp.vmax == v == pv) else [(v, ce, cp.vmax, pv)], (cell, v))


def run_quality_tol(core, T, rnd, quick, cells):
    """the visible tolerance (quality.qualities(..., tol)): every preset DC x RES at 2 % (the QS default, = fps_data.js)
    and at the tolerances the isp-lab tests use; the full-height crops it changes, around their rows; random cells"""
    for dc, cell in cells:
        for tol in ((0.02,) if quick else (0.02, 0.005, 0.0)):
            cmp_qualities(core, T, f'quality tol {tol} preset', cell, None, steps=0 if quick else 1, rnd=rnd, tol=tol)
    full = [(6048, 4040), (4032, 4032), (6048, 4038), (4032, 4034), (4032, 3990), (6032, 4040), (5056, 4040)]
    for cw, ch in full:
        for k in (1, 1.5, 2, 3, 4, 6):
            ow = int(cw / k) // 16 * 16
            for oh in {int(ch / k) & ~1, (int(ch / k) & ~1) - 2, (int(ch / k) & ~1) - 8, int(ow * ch / cw) & ~1}:
                for tol in ((0.02,) if quick else (0.02, 0.01, 0.005, 0.002, 0.03)):
                    cmp_qualities(core, T, 'quality tol full height', (cw, ch, ow, oh), rnd.choice([None, None, 59.94]),
                                  steps=0, rnd=rnd, tol=tol)
    for i in range(40 if quick else 400):
        cw = rnd.choice([6048, 4032, 4192, 3952, 2096, rnd.randint(16, 6064)])
        ch = rnd.choice([4040, 4032, 4038, rnd.randint(2, 4040), 2016, 1346])
        k = rnd.choice([1, 2, 3, 6, rnd.uniform(1, 8)])
        ow = int(cw / k) // 16 * 16
        oh = rnd.choice([int(ch / k) & ~1, ow * ch // max(cw, 1) & ~1, (int(ch / k) & ~1) - rnd.randint(0, 40) * 2])
        cmp_qualities(core, T, 'quality tol random', (cw, ch, ow, max(oh, 0)), rnd.choice([None, None, 59.94, 29.97]),
                      steps=1 if not quick else 0, rnd=rnd, tol=rnd.choice(list(TOLS)))


def run_isp(core, T, base, n=100000, seed=1027):
    rnd = random.Random(seed)
    for i in range(n):
        W = rnd.choice([rnd.randint(1, 7000), rnd.choice([1920, 2016, 2100, 2101, 2112, 3032, 3840, 4176, 6048, 6064, 6300, 6301])])
        H = rnd.choice([rnd.randint(1, 4200), rnd.choice([1080, 1344, 1708, 2014, 2160, 3402, 4040,
                                                          1709, 1710, 1711, 3420, 3421, 5130, 5131])])   # R12 edges
        zh = rnd.choice(ZOOMS + [rnd.randint(1024, 8192)]); zv = rnd.choice([zh, rnd.choice(ZOOMS), rnd.randint(1024, 8192)])
        hb = rnd.choice([1, 1, 3, 3, 2]) if i % 50 == 0 else rnd.choice([1, 3])
        vb = rnd.choice([1, 1, 3, 3, 5]) if i % 50 == 1 else rnd.choice([1, 3])
        bits = rnd.choice([8, 10, 12, 14] * 10 + [11])
        sc = (rnd.choice([1, 2, 3]), rnd.choice([1, 2, 3, 6]))
        rec = None
        if rnd.random() < 0.6:
            try:
                most = ((W // hb) * 1024 // zh & ~15, (H // vb) * 1024 // zv & ~1)
            except ZeroDivisionError:
                most = (0, 0)
            rec = rnd.choice([most, (most[0] - 16 * rnd.randint(0, 20), most[1] - 2 * rnd.randint(0, 50)),
                              (most[0] + 16, most[1]), (most[0] - 8, most[1]), (most[0], most[1] - 1), (16, 10), (32, 12)])
        s = F.Spec(window=(W, H), zoom=(zh, zv), scale=sc, vbin=vb, hbin=hb, bits=bits, hirate=rnd.random() < 0.1, rec=rec)
        T.add('isp-random plan', isp_diff(s, core.isp(s)), s)
        if i % 10 == 0:
            try:
                want = F.row(s, base)
            except (F.NotPossible, KeyError):
                want = None
            got, rc = core.row(s, base)
            T.add('isp-random row', [] if (want is None and rc) or (want == got and not rc) else [('row', rc)], s)


def tie_cases():
    """(hm, num, den) whose exact CLK / (hm * num / den) is k + 1/2: dyadic fps make the float a tie too"""
    out = []
    for hm in (330, 340, 400, 445, 870):
        for t in range(1, 60001, 2):
            f = Fraction(2 * int(C.CLK), hm * t)                # fps of the tie
            if f.numerator < 1 << 32 and f.denominator < 1 << 32:
                out.append((hm, f.numerator, f.denominator))
    return out


def plan_to_c(pp):
    """a (possibly synthetic) Python plan dict -> the C struct core_smc_create reads"""
    p = Plan()
    p.key = EC_KEYS.index(pp['key'])
    for f in ('fmt_w', 'line_w', 'raster_w', 'out_h', 'y_skip'):
        setattr(p, f, pp[f])
    p.hmax, p.vmax = pp['soc']['hmax'], pp['soc']['vmax']
    p.fast_set = int(bool(pp['fast_set']))
    p.n_sensor = len(pp['sensor'])
    for i, (a, v) in enumerate(pp['sensor']):
        p.sensor[i][0], p.sensor[i][1] = a, v
    return p


def run_smc_synthetic(core, T, n=3000, seed=1028):
    """smc.create on plans the planner would never make (odd rasters, short lines, exact 1.7 / 2.0 aspects,
    round() ties in fpsn, sensor writes that overlap the fast set or are not table registers)"""
    import copy
    rnd = random.Random(seed)
    bases = {}
    for r in C.READOUTS:
        for cw, ch in ((6048, 4040), (4192, 2358), (2108, 1248)):
            try:
                bases.setdefault(r['key'], C.plan(r['key'], cw, ch, 1920 // r['mh'], 1080 // r['mv']))
            except ValueError:
                pass
    keys = sorted(bases)
    regs = list(EC.X.REG_ORDER)
    fast_regs = [a for a, _ in __import__('bins').diff('8', '139')]
    for i in range(n):
        pp = copy.deepcopy(bases[rnd.choice(keys)])
        r = C.BY_KEY[pp['key']]
        fmt = pp['fmt_w']
        pp['raster_w'] = rnd.choice([rnd.randint(16, fmt), fmt, fmt - 1, rnd.randint(1, 64) * 16])
        pp['line_w'] = rnd.choice([fmt, fmt - 16, fmt - 3, pp['raster_w'] + rnd.randint(0, 40)])
        pp['out_h'] = rnd.choice([rnd.randint(2, 4100), pp['out_h'], 1080, 2160])
        if i % 7 == 0:                                       # exact aspect boundaries of the 16:9-class flag
            num, den = rnd.choice([(17, 10), (2, 1), (16, 9)])
            h = rnd.randint(100, 2000)
            w = Fraction(num * h * r['mv'], den * r['mh'])
            if w.denominator == 1:
                pp['raster_w'], pp['out_h'] = int(w) + rnd.choice([0, 0, -1, 1]), h
        pp['y_skip'] = rnd.choice([0, 0, 16, 28, 3])
        hm = rnd.choice([pp['soc']['hmax'], rnd.randint(300, 1000)])
        vm = rnd.choice([pp['soc']['vmax'], rnd.randint(100, 16384)])
        if i % 5 == 0:                                       # fpsn = round(CLK / (hm * vm)) at a tie
            hm = rnd.choice([330, 400, 445, 870])
            odd = [t for t in range(1, 4000, 2) if (2 * int(C.CLK)) % (hm * t) == 0 and 2 * int(C.CLK) // (hm * t) <= 16384]
            if odd:
                vm = 2 * int(C.CLK) // (hm * rnd.choice(odd))
        pp['soc'] = dict(pp['soc'], hmax=hm, vmax=vm)
        pp['fps'] = C.CLK / (hm * vm)
        pp['fast_set'] = rnd.random() < 0.5
        extra = []
        for _ in range(rnd.randint(0, 4)):
            extra.append((rnd.choice(fast_regs + regs + [0x0003, 0x0016, 0x0022, 0x0024, 0x0025]), rnd.randint(0, 255)))
        if i % 40 == 0:
            extra.append((0x7FFF, 1))                        # not a table register: ValueError / CORE_E_REG
        pp['sensor'] = list(pp['sensor']) + extra
        cp = plan_to_c(pp)
        pa, pe = py_create(pp)
        m, ce = core.create(cp)
        if pa is None or ce:
            T.add('smc-synthetic accept/reject', [] if (pa is None and ce) else [('py', pe, 'c', ce)], pp['id'])
            continue
        T.add('smc-synthetic accept/reject', [], pp['id'])
        T.add('smc-synthetic rows+attrs', mode_diff(pa, m), (pp['key'], pp['raster_w'], pp['out_h'], pp['line_w'], hm, vm))


def run_proofs(core, T):
    lib = core.lib
    out = (I32 * 8)()
    for v in range(0, 65536):
        p = MR._r28(dict(width=v, height=v))
        lib.core_r28(v, v, ctypes.byref(out))
        got = dict(cw=out[0], ch=out[1], x0=out[2], y0=out[3], aw=out[4], ah=out[5], ax0=out[6], ay0=out[7])
        T.add('proof r28 0..65535', [] if got == p else [(v, p, got)], v)
    rnd = random.Random(5)
    xs = list(range(0, 1 << 20)) + [rnd.getrandbits(32) for _ in range(200000)] + [0xFFFFFFFF, (1 << 24) + 1, (1 << 25) + 3]
    bad = [x for x in xs if lib.core_fbits(x) != F.fbits(x)]
    T.n['proof fbits'] = len(xs)
    if bad:
        T.bad['proof fbits'] = [(bad[:5], 'mismatch')]; T.bad['proof fbits#'] = len(bad)
    # the IEEE double emulation: round(CLK / (hm * (num / den))) for random rationals, NTSC rates and ties
    vs = [(rnd.randint(1, 4000), rnd.randint(1, 1 << 32) - 1 or 1, rnd.randint(1, 1 << 32) - 1 or 1) for _ in range(300000)]
    vs += [(hm, n, d) for hm in (330, 340, 400, 445, 870) for d in (1, 10, 100, 1000, 1001) for n in range(d, 400 * d, max(1, d // 3))][:400000]
    vs += tie_cases()
    vs = [(hm, n, d) for hm, n, d in vs if C.CLK / (hm * (n / d)) < 2 ** 62]
    bad = [(hm, n, d) for hm, n, d in vs if lib.core_py_vmax(hm, n, d) != round(C.CLK / (hm * (n / d)))]
    T.n['proof float emulation (vmax)'] = len(vs)
    if bad:
        T.bad['proof float emulation (vmax)'] = [(bad[:5], 'mismatch')]; T.bad['proof float emulation (vmax)#'] = len(bad)
    # readout_cfg float predicates (the integer forms core.c uses)
    nb = 0; nn = 0
    for r in C.READOUTS:
        lw, mh, mv = C.line_width(r, max(r['fmt'])), r['mh'], r['mv']
        for cw in range(0, 40000):
            sw = cw / mh; nn += 2
            nb += (lw >= sw * 0.995) != (1000 * lw * mh >= 995 * cw)
            nb += (lw >= sw - 1e-6) != (lw * mh >= cw)
        fh = C.SENSOR_H / mv
        for ch in range(0, 40000):
            nn += 2
            nb += (ch / mv < fh - 2) != (ch < C.SENSOR_H - 2 * mv)
            nb += (__import__('math').ceil(ch / mv / 2)) != -(-ch // (2 * mv))
    T.n['proof readout predicates'] = nn
    if nb:
        T.bad['proof readout predicates#'] = nb


def run_quality_proofs(core, T, quick=False):
    """round(CLK / N, 3) (the pick key) on the integer float emulation"""
    rnd = random.Random(7)
    ns = [hm * v for hm in (330, 340, 400, 401, 410, 418, 445, 870) for v in range(1, 16385, 13 if quick else 1)]
    ns += [rnd.randint(1, 1 << 32) - 1 or 1 for _ in range(2000 if quick else 200000)]
    ns += [144000000000 // t for t in range(35, 2000000, 2) if 144000000000 % t == 0]      # exact x.xxx5 ties
    ns = [n for n in ns if n < 1 << 32]
    bad = [n for n in ns if core.lib.core_fps_milli(n) != round(round(C.CLK / n, 3) * 1000)]
    T.n['proof round(fps, 3)'] = len(ns)
    if bad:
        T.bad['proof round(fps, 3)'] = [(bad[:5], 'mismatch')]; T.bad['proof round(fps, 3)#'] = len(bad)


def core_short_ok_ok(core, rec, res, tol, fr):
    return bool(core.lib.core_short_ok(rec[0], rec[1], res[0], res[1], fr.numerator, fr.denominator)) == \
        Q.short_ok(rec, res[0], res[1], tol)


def run_tol_proofs(core, T, quick=False):
    """the float tolerance predicates of quality.py vs the rationals core.c uses, exhaustively over the sizes:
    short_ok's `rw - rec <= tol * rw` and r16_rows' `full >= rows * (1 - tol)`; and core_js_fixed (JS toFixed of a
    rational) against the exact half-up of the nearest double"""
    from decimal import Decimal, ROUND_HALF_UP
    bad = n = 0
    for tol, fr in TOLS.items():
        for rw in range(0, 7001 if not quick else 7001, 1 if not quick else 7):
            lim = int(rw * tol) + 3
            for d in range(0, min(rw, lim) + 1):
                n += 1
                if (d <= tol * rw) != (d * fr.denominator <= fr.numerator * rw):
                    bad += 1
        for rows in range(0, 4101, 1 if not quick else 5):
            for full in range(max(0, int(rows * (1 - tol)) - 3), rows + 1):
                n += 1
                if (full >= rows * (1 - tol)) != (full * fr.denominator >= rows * (fr.denominator - fr.numerator)):
                    bad += 1
    T.n['proof tol predicates'] = n
    if bad:
        T.bad['proof tol predicates'] = [('mismatch', bad)]; T.bad['proof tol predicates#'] = bad
    # the C predicates themselves: core_short_ok on every shortfall around the bound, core_r16_rows per key x DC height
    nb = n = 0
    for tol, fr in TOLS.items():
        for rw in list(range(16, 7000, 1 if not quick else 13)) + [50, 100, 200, 1000, 2020, 2016, 1346, 4040]:
            lim = int(rw * tol)
            for d in sorted({0, 1, lim - 1, lim, lim + 1, lim + 2}):
                if d < 0:
                    continue
                for other in (0, 1):
                    n += 2
                    if core_short_ok_ok(core, (rw - d, rw - other), (rw, rw), tol, fr) is False:
                        nb += 1
                    if core_short_ok_ok(core, (rw - other, rw - d), (rw, rw), tol, fr) is False:
                        nb += 1
        for k, key in enumerate(EC_KEYS):
            for ch in range(0, 4101, 1 if not quick else 3):
                n += 1
                want = Q.r16_rows(key, ch, tol)
                if core.lib.core_r16_rows(k, ch, fr.numerator, fr.denominator) != (-1 if want is None else want):
                    nb += 1
    for k, key in enumerate(EC_KEYS):                                    # tol None
        for ch in range(0, 4101, 1 if not quick else 3):
            n += 1
            want = Q.r16_rows(key, ch)
            if core.lib.core_r16_rows(k, ch, 0, 0) != (-1 if want is None else want):
                nb += 1
    T.n['proof C tol predicates'] = n
    if nb:
        T.bad['proof C tol predicates'] = [('mismatch', nb)]; T.bad['proof C tol predicates#'] = nb
    rnd = random.Random(11)
    cases = [(int(C.CLK), hm * v, 3) for hm in (330, 400, 445, 870) for v in range(1000, 16385, 1 if not quick else 61)]
    cases += [(k, 1000, 2) for k in range(0, 200001, 1 if not quick else 7)]
    cases += [(rnd.randint(1, 1 << 40), rnd.randint(1, 1 << 30), rnd.randint(0, 3)) for _ in range(20000)]
    cases += [(3, 16 * 10 ** p, p) for p in range(4)] + [(375, 16, 3), (1, 8, 2), (5, 2, 0), (1, 16, 3)]   # exact ties
    nb = 0
    for num, den, pl in cases:
        if not den:
            continue
        want = int((Decimal(num / den) * 10 ** pl).quantize(Decimal(1), rounding=ROUND_HALF_UP)) if num else 0
        if core.lib.core_js_fixed(num, den, pl) != want:
            nb += 1
    T.n['proof js toFixed'] = len(cases)
    if nb:
        T.bad['proof js toFixed'] = [('mismatch', nb)]; T.bad['proof js toFixed#'] = nb


def run_ties(core, T):
    vs = tie_cases()
    bad = [v for v in vs if core.lib.core_py_vmax(*v) != round(C.CLK / (v[0] * (v[1] / v[2])))]
    T.n['vmax at round() ties'] = len(vs)
    if bad:
        T.bad['vmax at round() ties'] = [(bad[:5], 'mismatch')]; T.bad['vmax at round() ties#'] = len(bad)


def run_all(lib, quick=False, verbose=True):
    core = Core(lib)
    T = Tally()
    base = base_row()
    t = time.time()
    for name, fn in (('matrix', lambda: run_matrix(core, T, base, quick)),
                     ('grid', lambda: run_grid(core, T, quick, smc_cap=600 if quick else None)),
                     ('fps', lambda: run_fps_sweep(core, T, quick)),
                     ('smc-synthetic', lambda: run_smc_synthetic(core, T, 1500 if quick else 6000)),
                     ('isp', lambda: run_isp(core, T, base, 8000 if quick else 100000)),
                     ('quality', lambda: run_quality(core, T, quick)),
                     ('quality proofs', lambda: run_quality_proofs(core, T, quick)),
                     ('tol proofs', lambda: run_tol_proofs(core, T, quick)),
                     ('vmax ties', lambda: run_ties(core, T)),
                     ('proofs', lambda: None if quick else run_proofs(core, T))):
        fn()
        if verbose:
            print(f'  [{name} done, {time.time() - t:.1f} s]', flush=True)
    return T


# mutants of core.c: each one a real-looking slip; every one must make the comparisons fail
MUTANTS = {
    'R15 dropped (14 bit full width at 870)': ('if (cd_ro[key].bits == 14 && w > CD_WIDE14_W)', 'if (0)'),
    'R14 dropped (E3 clamps the record)': ('if (vw >= aw && vh >= ah) { path = PATH_C;', 'if (0) { path = PATH_C;'),
    'R14 takes a C that clips too': ('if (vw >= aw && vh >= ah) { path = PATH_C;', 'if (1) { path = PATH_C;'),
    'trim tolerance 0.5 % -> 1 %': ('1000 * line_width(r, fmax) * mh >= 995 * (i64)cw', '1000 * line_width(r, fmax) * mh >= 990 * (i64)cw'),
    'window start = 3 mod 4': ('if (pmod(raw - d, 4) == 1) { st = raw - d; break; }\n            if (pmod(raw + d, 4) == 1)',
                               'if (pmod(raw - d, 4) == 3) { st = raw - d; break; }\n            if (pmod(raw + d, 4) == 3)'),
    'round() half up, not half even': ('    if (rem > half || (rem == half && (q & 1u))) q++;\n    return (i64)q;', '    if (rem >= half) q++;\n    return (i64)q;'),
    'vmax by exact rational, not floats': ('vmax = dround(ddiv_int(CD_CLK, dmul(dratio(fps_num, fps_den), (u64)hm)));',
                       'vmax = dround(dratio((u64)CD_CLK * fps_den, (u64)hm * fps_num));'),
    'float division: guard bit dropped': ('if (g && (rest || sticky || (m & 1u))) m++;', 'if (0) m++;'),
    'no smaller tested blanking retry': ('if (vmax < vmin && r->v016_min >= 0 && v016 < 0)', 'if (0)'),
    'V3 margin not in the window': ('    st -= y_skip * mv;\n', '\n'),
    'hd range inclusive': ('d->hd = 17 * den < 10 * num && 10 * num < 20 * den;', 'd->hd = 17 * den <= 10 * num && 10 * num <= 20 * den;'),
    'R28 ch rounds instead of floor': ('i64 ch = 2 * fdiv(H * CD_K_EVAL_H_NUM, 32 * CD_K_EVAL_H_DEN);',
                                       'i64 ch = 2 * tdiv(H * CD_K_EVAL_H_NUM + 16 * CD_K_EVAL_H_DEN, 32 * CD_K_EVAL_H_DEN);'),
    'nearest/cat: k1 ignored': ("(c->k1 == 0xFF || e->k1 == a[c->k1])", "(1)"),
    'smc: fpsn truncated': ('a[A_FPSN] = (int32_t)pyround_div(CD_CLK, (u64)((i64)p->hmax * p->vmax));',
                            'a[A_FPSN] = (int32_t)udiv64(CD_CLK, (u64)((i64)p->hmax * p->vmax), 0);'),
    'fast set after the plan writes': ('    if (p->fast_set)\n        for (int i = 0; i < CD_N_FAST; i++) TRY(reg_write(m, cd_fast[i].reg, cd_fast[i].val));\n    for (int i = 0; i < p->n_sensor; i++) TRY(reg_write(m, p->sensor[i][0], p->sensor[i][1]));',
                                       '    for (int i = 0; i < p->n_sensor; i++) TRY(reg_write(m, p->sensor[i][0], p->sensor[i][1]));\n    if (p->fast_set)\n        for (int i = 0; i < CD_N_FAST; i++) TRY(reg_write(m, cd_fast[i].reg, cd_fast[i].val));'),
    'short-line x0 not kept even': ('x0 = imax(0, fdiv(imin(x0, (i64)p->line_w - p->raster_w), 2) * 2);', 'x0 = imax(0, imin(x0, (i64)p->line_w - p->raster_w));'),
    'isp: D ratio ignores the visible cap': ('imax(cdiv(W, SRC_MAX), cdiv(act0, VIS_MAX_W))', 'cdiv(W, SRC_MAX)'),
    'R12: binned C ignores the source rows': ('fdiv(W * UNITY, fh) > SRC_MAX || fdiv(H * UNITY, fv) > CD_SRC_MAX_H', 'fdiv(W * UNITY, fh) > SRC_MAX'),
    'R12: B ignores the source rows': ('act0 <= VIS_MAX_W && H <= CD_SRC_MAX_H)', 'act0 <= VIS_MAX_W)'),
    'R12: D ratio ignores the source rows': (', cdiv(H, CD_SRC_MAX_H));', ', 1);'),
    'R12: C (fh == fv) ignores the source rows': ('int c_fits = fdiv(W * UNITY, fh) <= SRC_MAX && fdiv(H * UNITY, fv) <= CD_SRC_MAX_H;',
                                                  'int c_fits = fdiv(W * UNITY, fh) <= SRC_MAX;'),
    'R12: E1 ignores the source rows': ('(W <= SRC_MAX && H <= CD_SRC_MAX_H)', '(W <= SRC_MAX)'),
    'R12: source rows inclusive off by one': ('#define SRC_MAX 2100\n', '#define SRC_MAX 2100\n#undef CD_SRC_MAX_H\n#define CD_SRC_MAX_H 1709\n'),
    'isp: RWZM 8192 accepted': ('#define RWZM_MAX 8191', '#define RWZM_MAX 8192'),
    'isp: visible 1334 snap off': ('static const int16_t KNOWN_H[2] = {1125, 1334};', 'static const int16_t KNOWN_H[2] = {1125, 1125};'),
    'isp: 14-bit plane code': ('case 14: pl0 = 7; pl1 = 8; break;', 'case 14: pl0 = 7; pl1 = 7; break;'),
    'fbits: truncates instead of rounding': ('if (rem > half || (rem == half && (mant & 1u))) mant++;', ';'),
    'R11: HMAX at the floor counted as raised': ('return hm > cd_ro[key].hmin ? (int)hm : 0;', 'return hm >= cd_ro[key].hmin ? (int)hm : 0;'),
    'R11: min_line_clk floors': ('i64 hm = cdiv((i64)w * CD_LINE_PX_DEN, CD_LINE_PX_NUM);', 'i64 hm = fdiv((i64)w * CD_LINE_PX_DEN, CD_LINE_PX_NUM);'),
    'quality: no WIDEN retry': ('if ((hbin == 1 && vbin == 1) || (i64)cw + CD_Q_WIDEN > CD_Q_SENSOR_W) continue;', 'continue;'),
    'quality: WIDEN on 1x1 bins too': ('if ((hbin == 1 && vbin == 1) || (i64)cw + CD_Q_WIDEN > CD_Q_SENSOR_W) continue;',
                                       'if ((i64)cw + CD_Q_WIDEN > CD_Q_SENSOR_W) continue;'),
    'quality: tie goes to the later variant': ('if (c->fps_milli > out[i].fps_milli) copy_q(&out[i], c);', 'if (c->fps_milli >= out[i].fps_milli) copy_q(&out[i], c);'),
    'quality: RES within 2 rows': ('if ((o.rec[0] != ow || o.rec[1] != oh) &&', 'if ((o.rec[0] != ow || o.rec[1] + 2 < oh) &&'),
    'R11 on sw, not the raster': ('int hmax = core_line_hmax(key, p->raster_w);', 'int hmax = core_line_hmax(key, (int)sw);'),
    'quality: planned at the cap when fps_max == cap': ('q->capped = cn && dlt(dratio(cn, cd), dratio(CD_CLK, (u64)p->hmax * (u64)p->vmin));',
                                                        'q->capped = cn && !dlt(dratio(CD_CLK, (u64)p->hmax * (u64)p->vmin), dratio(cn, cd));'),
    'quality: float fps key truncated': ('static i64 dround_milli(dbl x) { dbl y = {x.m * 1000u, x.e}; return dround(y); }',
                                         'static i64 dround_milli(dbl x) { return (i64)((x.m * 1000u) >> -x.e); }'),
    'quality: not back in matrix order': ('j > 0 && out[j - 1].seq > out[j].seq', 'j > 0 && 0'),
    'quality: _z 1:1 window 0.1 %': ('return z < UNITY + 2 ? UNITY : z;', 'return z < UNITY + 1 ? UNITY : z;'),
    'quality: no blanking fallback floor': ('q->vmin_lo = r->v016_min >= 0 ?', 'q->vmin_lo = 0 ?'),
    'quality: full-height rows not capped': ('if (ch >= CD_SENSOR_H) sh = imin(sh, full_rows(r));', ';'),
    'R16 dropped': ('            if (ch >= CD_SENSOR_H) continue;\n            /* R16', '            continue;\n            /* R16'),
    'R16 keeps the whole frame': ('i64 rows = fdiv(ch, cd_ro[key].mv) & ~(i64)1, full', 'i64 rows = full_rows(&cd_ro[key]), full'),
    'R16 rows rounded up': ('i64 rows = fdiv(ch, cd_ro[key].mv) & ~(i64)1, full', 'i64 rows = cdiv(ch, cd_ro[key].mv) + 1 & ~(i64)1, full'),
    'R16 on a frame shorter than the DC': ('return rows <= full ? (int)rows : -1;', 'return (int)imin(rows, full);'),
    'R16 crop at the top': ('y_crop = fdiv(rows_out - rows, 4) * 2;', 'y_crop = 0;'),
    'R16 crop off phase': ('y_crop = fdiv(rows_out - rows, 4) * 2;', 'y_crop = fdiv(rows_out - rows, 2);'),
    'R16 crop not in the TIM y0': ('    y_skip += y_crop; ', '    y_skip += 0; '),
    'R16 row crop on a window': ('        if (windowed) return CORE_E_ROWCROP;\n', '\n'),
    'R16 odd rows accepted': ('(rows & 1) || rows > rows_out', 'rows > rows_out'),
    'R16 WIDEN retry forgets the crop': ('q_readout(key, (i64)cw + CD_Q_WIDEN, rch, rows,', 'q_readout(key, (i64)cw + CD_Q_WIDEN, ch, -1,'),
    'R16 replay forgets the crop': ('-1, q->hmax, 0, q->rows, p);', '-1, q->hmax, 0, -1, p);'),
    # visible tolerance (quality.py tol=)
    'tol: pitch from the delivery (stretch)': ('i64 bw = nom ? imax(W, nom[0]) : W, bh = nom ? imax(H, nom[1]) : H;',
                                               'i64 bw = W, bh = H;'),
    'tol: short rows not accepted': ('(!tol || !short_ok(o.rec[0], o.rec[1], ow, oh, tol_num, tol_den))) continue;',
                                     '1) continue;'),
    'tol: any shortfall accepted': ('(u64)(rh - rec_h) * td <= tn * (u64)rh;', '1;'),
    'tol: the bound exclusive': ('(u64)(rw - rec_w) * td <= tn * (u64)rw && (u64)(rh - rec_h) * td <= tn * (u64)rh;',
                                 '(u64)(rw - rec_w) * td <= tn * (u64)rw && (u64)(rh - rec_h) * td < tn * (u64)rh;'),
    'tol: R16 never takes the short frame': ('if (tol && rows > full && (u64)full * td >=', 'if (0 && rows > full && (u64)full * td >='),
    'tol: R16 takes any short frame': ('if (tol && rows > full && (u64)full * td >= (u64)rows * (td - tn)) return (int)full;',
                                       'if (tol && rows > full) return (int)full;'),
    'tol: nominal rows not even': ('fdiv(ch, cd_ro[key].mv) & ~(i64)1};', 'fdiv(ch, cd_ro[key].mv)};'),
    'tol: nominal from the widened crop': ('i64 nom[2] = {fdiv(cw, cd_ro[key].mh),', 'i64 nom[2] = {fdiv(cw + 16, cd_ro[key].mh),'),
    'visible: margin 16 x 8': ('c->vis_h = o.rec[1] - CD_Q_MARGIN_H;', 'c->vis_h = o.rec[1] - 8;'),
    'rs: truncated to the microsecond': ('c->rs_us = (int32_t)dround_milli(dmul(dratio((u64)c->hm * (u64)c->lines, CD_CLK), 1000u));',
                                         'c->rs_us = (int32_t)udiv64((u64)c->hm * (u64)c->lines * 1000000u, CD_CLK, 0);'),
    'js toFixed: half even': ('return (int64_t)(q + (rem >= half));', 'return (int64_t)(q + (rem > half || (rem == half && (q & 1u))));'),
}


def run_mutants():
    src = (HERE / 'core.c').read_text()
    survivors = []
    mdir = BUILD / 'mutants'
    mdir.mkdir(parents=True, exist_ok=True)
    for i, (name, (old, new)) in enumerate(MUTANTS.items()):
        if src.count(old) != 1:
            print(f'  MUTANT {name}: pattern found {src.count(old)} times'); survivors.append(name); continue
        f = mdir / f'm{i}.c'
        f.write_text(src.replace(old, new))
        lib = build_host(f, f'mut{i}_{os.getpid()}', werror=False)
        T = run_all(lib, quick=True, verbose=False)
        n = T.failed()
        if not n and ('fbits' in name or 'float' in name):          # quick mode skips the proofs: run the fbits one directly
            T2 = Tally(); run_proofs(Core(lib), T2); n = T2.failed()
        print(f'  mutant {name:42s} -> {n} mismatches {"(caught)" if n else "SURVIVED"}', flush=True)
        if not n:
            survivors.append(name)
    return survivors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mutants', action='store_true'); ap.add_argument('--quick', action='store_true')
    a = ap.parse_args()
    (HERE / 'core_data.h').write_text(EC.emit(EC.collect()))      # always from the current Python
    lib = build_host()
    ok_arm, msg = build_arm()
    print(msg, '' if ok_arm else '  <-- FAIL')
    T = run_all(lib, quick=a.quick)
    T.report()
    fail = T.failed() + (0 if ok_arm else 1)
    if a.mutants:
        surv = run_mutants()
        print(f'mutants: {len(MUTANTS) - len(surv)}/{len(MUTANTS)} caught' + (f', SURVIVED: {surv}' if surv else ''))
        fail += len(surv)
    print('PASS' if not fail else f'FAIL ({fail})')
    sys.exit(1 if fail else 0)


if __name__ == '__main__':
    main()
