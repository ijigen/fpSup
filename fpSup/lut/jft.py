"""The joint-fit file (.JFT): one cube's LV hardware tables, converted once (user 2026-11-04: "在 LUT Manager
中做轉檔、轉完之前不能選"; this host side converts the same way, with the same native/jfit.c).

    \\fpSup\\LUTDATA\\<sha[:16]>.JFT      little-endian (the sup's own folder; \\fpSup\\LUT\\ is the user's
                                        cubes alone since 2026-11-06 -- files under LUT\\JFIT\\ are not read)
    header 64 B:  'JFT1', version, header_len, total, sha[8], color, gamma, amount, matrix, jfit_version,
                  dE_mean x100, dE_p95 x100, dE_max x100, fnv1a(payload), reserved
    payload:      shift u32, m2 9 x i16 (+ 2 pad), tone 3 x 2048 u16, ycmat 7 x i16 (+ 2 pad),
                  ceq_tgt 72 u16 (TGT L, S, H x 24), ygam 18 u32 (the YGAM shadow words),
                  m1 9 x i16 (+ 2 pad) (JFIT v5, 2026-11-11: RGBLMAT set 1, root+0x10, the luma; m2 is set 2,
                  root+0x08, the chroma; one shift for both -- the firmware halves all 18 together),
                  cknee 16 B (JFIT v6, 2026-11-11: the ISP's CKNEE, projects/lut-sup/validation/20261111-cknee-cal):
                  u32 on (0 / 1), then the PQ table record's +4 .. +15 as native/lvb.c hands it to the ISP --
                  u16 knee A (+Cb, 10C0), u16 knee C (-Cb, 10D0), u8 slope A, u8 slope C, u16 knee B (+Cr, 10C8),
                  u16 knee D (-Cr, 10D8), u8 slope B, u8 slope D; knee = 9-bit code / 1024 in the chain's chroma
                  (YCMAT / 512), slope = 5-bit code / 16 (JFIT 7; at most 24)
    chart block (Bei 2026-11-07, after the payload; the header's total counts the core only, so a v2 file without
                  it stays valid and the camera's ISP read never sees it): 'JFC1', 212, match %, the core's fnv
                  (header +56), 48 x 0xRRGGBBAA (the 0 EV ColorChecker as the conversion overlay leaves it:
                  patch p's target then its fit, LC_P00..47), fnv1a of the 208 before

The fidelity numbers ("還原度") are the hardware chain against the cube's target on the ColorChecker 24 at
-1 / 0 / +1 EV (lut_batch_eval.sample_sets), mean / p95 / max dE76.  Any matrix: the
host target is lv_fit.make_target, which equals the camera's render (test_lvb_native); the matrix is key only."""
import ctypes
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MAGIC = 0x3154464A                   # 'JFT1'
VERSION = 1
JFIT_VERSION = 7                     # bump when the conversion's fit changes: old files are stale (native/lvb.c JFT_JFIT;
                                     # 2 = jf_fit_direct "direct10+144"; 3 = "xlm10+144": jf_fit 2 x 20 on the ordinary
                                     # samples, then jf_fit_direct 10 from the cheaper on + the 144 HSV, Bei 2026-11-07;
                                     # 4 = 3 + the CEQ hue order (11-10: a v3 file could hold a decreasing hue pair, which
                                     # the ISP takes the long way round -- magenta in Fuji 3513DI / Kodak 2383 greens);
                                     # 5 = 4 + the untied refine (Bei 2026-11-11: M1 apart from M2, ~5000 samples x 40
                                     # LM steps from the packed v4 result, the cheaper packed one kept) + m1 in the
                                     # payload (a v4 file is shorter: its size check fails too); 6 = 5 + the CKNEE
                                     # (2026-11-11: freed in the untied refine, kept when it lowers the packed cost;
                                     # its 16-byte block after m1 -- a v5 file is shorter too); 7 = 6 with the slope code / 16 (11-11, camera-read;
                                     # a v6 file's codes meant / 19: same size, stale by this number)
HEADER = 64
NTONE = 2048
ORG_H = [0, 2731, 5461, 8192, 10923, 13653, 16384, 19115, 21845, 24576, 27307, 30037,
         32768, 35499, 38229, 40960, 43691, 46421, 49152, 51883, 54613, 57344, 60075, 62805]
# CEQ hue order (native/jfit.c JF_HUE_*): every forward step between neighbouring destinations >= HUE_GAP deg
HUE_GAP, HUE_SAFE, HUE_WORDS = 3.75, 3.8, 683
PAYLOAD_V4 = 4 + 20 + 3 * NTONE * 2 + 16 + 72 * 2 + 18 * 4   # JFIT <= 4: no m1 (read here for studies; stale on camera)
PAYLOAD_V5 = PAYLOAD_V4 + 20                                 # JFIT 5: + m1
PAYLOAD = PAYLOAD_V5 + 16                                    # JFIT 6: + the CKNEE block
# the CKNEE (native/jfit.c JF_NK ..): P[NK:NK + 8] = (knee, slope) for +Cb, -Cb, +Cr, -Cr; KNEE_OFF = none (identity)
NP, NK, KNEE_OFF = 148, 140, 8.0
KNEE_DIV, SLOPE_DIV, KNEE_CODES, SLOPE_CODES = 1024, 16, 511, 24   # slope / 16, at most 1.5 (11-11)
CHART_MAGIC = 0x3143464A             # 'JFC1' (native/lvb.c JFC_MAGIC)
CHART_BYTES = 212                    # native/lvb.c JFC_BYTES
CHART_PATCHES = 48


def _probes():
    p = str(ROOT / 'projects/lut-sup/probes')
    if p not in sys.path:
        sys.path.insert(0, p)


def fnv(data):
    h = 2166136261
    for b in data:
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


# ---------------------------------------------------------------- YGAM words (FUN_c0109768 + FUN_c010a160)
def _cdiv(a, b):
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def ygam_words(p):
    """17 Y outputs (12-bit, x = 0, 256 .. 4096) -> the 18 shadow words (camera-checked 2026-11-04, lut-joint-05)."""
    clamp = lambda v, lo, hi: max(lo, min(hi, v))
    y0 = min(p[0], 0xfff)
    sl = [clamp(_cdiv((p[1] - p[0]) * 0x80 + 0x80, 256), 0, 0x3ff), clamp(_cdiv((p[2] - p[0]) * 0x80 + 0x100, 512), 0, 0x3ff)]
    for i in range(3, 17):
        sl.append(clamp(_cdiv((p[i] - p[i - 2]) * 0x80 + 0x100, 512), 0, 0x3ff))
    knots, prev = [], y0
    for i in range(15):
        prev = clamp(prev + sl[i] + sl[i + 1], 0, 0xfff); knots.append(prev)
    last = clamp(p[16] - (knots[-1] + sl[15]) + 1, 0, 0x3ff)
    w = [1 | y0 << 16]
    seq = knots + [0x1000]
    for i in range(0, 16, 2):
        w.append(seq[i] | seq[i + 1] << 16)
    for i in range(0, 16, 2):
        w.append(sl[i] | sl[i + 1] << 16)
    w.append(last)
    return w


# ---------------------------------------------------------------- the native fit, host build
_LIB = None


def _lib():
    global _LIB
    if _LIB is None:
        out = Path(tempfile.mkdtemp()) / 'jfit.dylib'
        subprocess.run(['clang', '-O2', '-shared', '-fPIC', '-o', str(out), str(HERE / 'native/host/jfit_host.c')], check=True)
        L = ctypes.CDLL(str(out))
        FP = ctypes.POINTER(ctypes.c_float)
        L.jf_host_fit.argtypes = [FP, FP, ctypes.c_uint32, FP, FP, FP, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        L.jf_host_fit.restype = ctypes.c_float
        L.jf_host_dense.argtypes = [ctypes.c_int]
        L.jf_host_direct.argtypes = L.jf_host_fit.argtypes
        L.jf_host_direct.restype = ctypes.c_float
        L.jf_host_hsv.argtypes = [FP]
        L.jf_host_untied.argtypes = L.jf_host_fit.argtypes
        L.jf_host_untied.restype = ctypes.c_float
        L.jf_host_untied_k.argtypes = L.jf_host_fit.argtypes + [ctypes.c_int]
        L.jf_host_untied_k.restype = ctypes.c_float
        L.jf_host_dense_samples.argtypes = [FP]
        L.jf_host_ndx.restype = ctypes.c_uint32
        L.jf_host_packed_cost.argtypes = [ctypes.c_char_p, ctypes.c_uint32, FP, FP, FP]
        L.jf_host_packed_cost.restype = ctypes.c_double
        L.jf_host_packed_lab.argtypes = [ctypes.c_char_p, ctypes.c_uint32, FP, FP]
        _LIB = L
    return _LIB


def _f32(a):
    return np.ascontiguousarray(a, np.float32)


def knee_on(P):
    """P carries a CKNEE (native/jfit.c jf_knee_on)"""
    return len(P) > NK and P[NK] < KNEE_OFF / 2


def knee_off(P):
    """P (140 or 148) -> 148 with the CKNEE off (native/jfit.c jf_knee_off)"""
    out = np.r_[np.asarray(P, float)[:NK], np.zeros(8)]
    out[NK::2], out[NK + 1::2] = KNEE_OFF, 1.0
    return out


def _p148(P):
    """the native P: a 140 one (no CKNEE) padded with the CKNEE off"""
    return _f32(P if len(P) == NP else knee_off(P))


def _back(P, P0):
    """native P out, as long as P0 was (a 140 in: no CKNEE out, its 140)"""
    out = P.astype(float)
    return out if len(P0) == NP or knee_on(out) else out[:len(P0)]


def native_fit(xs, want, w, base_tone, P0, iters=10):
    L = _lib(); FP = ctypes.POINTER(ctypes.c_float)
    P = _p148(P0); es = (ctypes.c_uint32 * 2)()
    xs, want, w, bt = _f32(xs), _f32(want), _f32(w), _f32(base_tone)
    cost = L.jf_host_fit(P.ctypes.data_as(FP), bt.ctypes.data_as(FP), len(xs), xs.ctypes.data_as(FP),
                         want.ctypes.data_as(FP), w.ctypes.data_as(FP), iters, es)
    return _back(P, P0), float(cost)


def native_direct(xs, want, w, base_tone, P0, iters=None):
    """native/jfit.c jf_fit_direct (JFIT v2): the exact-Jacobian LM from P0, iters steps at most."""
    L = _lib(); FP = ctypes.POINTER(ctypes.c_float)
    P = _p148(P0); es = (ctypes.c_uint32 * 2)()
    xs, want, w, bt = _f32(xs), _f32(want), _f32(w), _f32(base_tone)
    cost = L.jf_host_direct(P.ctypes.data_as(FP), bt.ctypes.data_as(FP), len(xs), xs.ctypes.data_as(FP),
                            want.ctypes.data_as(FP), w.ctypes.data_as(FP), CONV_DIRECT_ITERS if iters is None else iters, es)
    return _back(P, P0), float(cost)


def native_untied(xs, want, w, base_tone, P0, iters=None, knee=True):
    """native/jfit.c jf_fit_untied (JFIT v5): the LM from P0 with M1 (P[9:18]) free, luma_preserve, iters steps at most;
    JFIT v6 (knee): the CKNEE free too, from jf_knee_start -> P of 148."""
    L = _lib(); FP = ctypes.POINTER(ctypes.c_float)
    P = _p148(P0); es = (ctypes.c_uint32 * 2)()
    xs, want, w, bt = _f32(xs), _f32(want), _f32(w), _f32(base_tone)
    cost = L.jf_host_untied_k(P.ctypes.data_as(FP), bt.ctypes.data_as(FP), len(xs), xs.ctypes.data_as(FP),
                              want.ctypes.data_as(FP), w.ctypes.data_as(FP), CONV_UNTIE_ITERS if iters is None else iters, es,
                              1 if knee else 0)
    return _back(P, P0), float(cost)


def dense_samples():
    """native/jfit.c jf_dense_samples: the untied refine's JF_NDX extra samples (camera RGB, Q20-exact float32):
    -> (xs, n_weighted) -- the first n_weighted take the stock-look weight, the rest (HSV) weight 1."""
    L = _lib(); n = L.jf_host_ndx(); out = np.zeros(3 * n, np.float32)
    L.jf_host_dense_samples(out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
    return out.reshape(n, 3).astype(float), n - NDX_HSV


def packed_cost(core, xs, want, w):
    """native/jfit.c jf_packed_cost: sum (w (Lab - want))^2 through a .JFT's packed tables (core: the file's first
    HEADER + PAYLOAD bytes, or the payload alone)."""
    L = _lib(); FP = ctypes.POINTER(ctypes.c_float)
    pay = bytes(core[HEADER:HEADER + PAYLOAD]) if len(core) >= HEADER + PAYLOAD else bytes(core)
    assert len(pay) == PAYLOAD
    xs, want, w = _f32(xs), _f32(want), _f32(w)
    return float(L.jf_host_packed_cost(pay, len(xs), xs.ctypes.data_as(FP), want.ctypes.data_as(FP), w.ctypes.data_as(FP)))


def packed_lab(core, xs):
    """native/jfit.c jf_unpack + jf_sample: Lab through a .JFT's packed tables"""
    L = _lib(); FP = ctypes.POINTER(ctypes.c_float)
    pay = bytes(core[HEADER:HEADER + PAYLOAD]) if len(core) >= HEADER + PAYLOAD else bytes(core)
    xs = _f32(xs); out = np.zeros(xs.shape, np.float32)
    L.jf_host_packed_lab(pay, len(xs), xs.ctypes.data_as(FP), out.ctypes.data_as(FP))
    return out.astype(float)


def hsv_samples():
    """native/jfit.c jf_hsv_samples: the 144 HSV samples (camera RGB, float32 as the camera computes them)."""
    L = _lib(); out = np.zeros(3 * NHSV, np.float32)
    L.jf_host_hsv(out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
    return out.reshape(NHSV, 3).astype(float)


# ---------------------------------------------------------------- quantise to the hardware
def hue_safe(dh):
    """native/jfit.c jf_hue_safe: the 24 CEQ hue shifts (deg) scaled by the one factor that brings every forward gap
    15 + dh[a+1] - dh[a] up to HUE_SAFE (a no-op on a table in order) -> a new array."""
    dh = np.asarray(dh, float).copy()
    d = dh - np.roll(dh, -1)
    bad = 15 - d < HUE_SAFE
    if bad.any():
        dh *= min(1.0, float(((15 - HUE_SAFE) / d[bad]).min()))
    return dh


def hue_steps(words):
    """the 24 forward steps (mod 65536) between neighbouring CEQ hue destination words"""
    return [(words[(k + 1) % 24] - words[k]) % 65536 for k in range(24)]


def hue_in_order(words, floor=HUE_WORDS):
    """the ISP interpolates each destination pair forward mod 65536: in order = every step >= floor and one turn"""
    st = hue_steps(words)
    return min(st) >= floor and sum(st) == 65536


def quantise(P, base_tone):
    """P (140, joint_fit_eval layout: M2 = P[:9], M1 = P[9:18]) + base tone (3 x 2048, 0..1) -> hardware values.
    Plain rounding of the matrices: the joint fit leaves row sums free (camera 2026-11-04, lut-joint-04/05); one shift,
    the first that fits both (native/conv.c conv_pack)."""
    _probes()
    import lv_fit as F
    M = P[:9].reshape(3, 3); M1 = P[9:18].reshape(3, 3)
    KX = np.linspace(0, NTONE - 1, 9); AX = np.arange(NTONE, dtype=float)
    d = P[18:45].reshape(3, 9)
    curve = np.stack([np.clip(np.maximum.accumulate(base_tone[k] + np.interp(AX, KX, d[k])), 0, 1) for k in range(3)])
    for shift in range(3):
        q = np.round(M / 2 ** shift * F.Q9).astype(int); q1 = np.round(M1 / 2 ** shift * F.Q9).astype(int)
        if F.in_q9_range(F.table_order(q)) and F.in_q9_range(F.table_order(q1)):
            break
    else:
        raise ValueError('matrix beyond the hardware range')
    tone = np.stack([np.round(F.TONE_MAX * curve[k][np.minimum(np.arange(NTONE) << shift, NTONE - 1)]) for k in range(3)]).astype(int)
    post = P[45:]
    yr, yb = int(round(post[0] * 4096)), int(round(post[1] * 4096)); yg = 4096 - yr - yb
    if not all(0 <= v <= 4095 for v in (yr, yg, yb)):
        raise ValueError(f'YCMAT Y beyond 12 bits: {yr},{yg},{yb}')
    cbr, cbb, crr, crb = (int(round(v * 512)) for v in post[2:6])
    ycmat = [yr, yg, yb, max(-511, min(511, cbr)), max(0, min(1023, cbb)), max(0, min(1023, crr)), max(-511, min(511, crb))]
    dh, gs, gl = hue_safe(post[6:30]), post[30:54], post[54:78]
    ceq = [[int(round(512 * g)) for g in gl], [int(round(683 * g)) for g in gs],
           [int(round(h + v * 65536 / 360)) % 65536 for h, v in zip(ORG_H, dh)]]
    if not hue_in_order(ceq[2]):                     # never: hue_safe (native/conv.c conv_pack: CVE_HUE)
        raise ValueError('CEQ hue destinations out of order')
    yg_out = [int(round(4095 * v)) for v in np.maximum.accumulate(np.clip(post[78:95], 0, 1))]
    return dict(shift=shift, m2=[int(x) for x in F.table_order(q)], tone=tone, ycmat=ycmat, ceq=ceq,
                ygam=ygam_words(yg_out[:17]), m1=[int(x) for x in F.table_order(q1)], knee=knee_codes(P))


def knee_codes(P):
    """JFIT v6: P's CKNEE as the 8 hardware codes in P's order (knee, slope for +Cb, -Cb, +Cr, -Cr; native/conv.c
    conv_pack: rounded half up, clamped to 9 / 5 bits), None when P has none"""
    if not knee_on(P):
        return None
    out = []
    for i, v in enumerate(np.asarray(P, float)[NK:NK + 8]):
        div, top = (SLOPE_DIV, SLOPE_CODES) if i & 1 else (KNEE_DIV, KNEE_CODES)
        out.append(int(min(top, max(0, np.floor(float(np.float32(v) * np.float32(div)) + 0.5)))))
    return out


def knee_record(hw):
    """the 16-byte PQ table record native/lvb.c points the ISP at (thr 0, then the file's +4 .. +15), None without"""
    k = hw.get('knee')
    if not k:
        return None
    return struct.pack('<I2H2B2H2B', 0, k[0], k[2], k[1], k[3], k[4], k[6], k[5], k[7])


def knee_values(codes):
    """the 8 codes -> the chain's (knee, slope) x 4 (native/jfit.c jf_unpack)"""
    return [c / (SLOPE_DIV if i & 1 else KNEE_DIV) for i, c in enumerate(codes)]


def chart_block(core, chart):
    """The block after the core: chart = dict(match=%, patches=48 x 0xRRGGBBAA) (native/conv.c conv_seal)."""
    patches = [int(v) & 0xFFFFFFFF for v in chart['patches']]
    if len(patches) != CHART_PATCHES or not 0 <= int(chart['match']) <= 100:
        raise ValueError('a chart is 48 halves and a match 0..100')
    b = struct.pack('<4I48I', CHART_MAGIC, CHART_BYTES, int(chart['match']), struct.unpack_from('<I', core, 56)[0], *patches)
    return b + struct.pack('<I', fnv(b))


def read_chart(data, core=HEADER + PAYLOAD):
    """-> dict(match, patches) from a file's chart block, None when the file has none (a v2 file before 11-07)."""
    if len(data) == core:
        return None
    if len(data) != core + CHART_BYTES:
        raise ValueError('JFT length')
    b = data[core:]
    m, n, match, core_fnv = struct.unpack_from('<4I', b)
    if m != CHART_MAGIC or n != CHART_BYTES or match > 100 or core_fnv != struct.unpack_from('<I', data, 56)[0] or \
            fnv(b[:-4]) != struct.unpack_from('<I', b, CHART_BYTES - 4)[0]:
        raise ValueError('JFT chart block')
    return dict(match=match, patches=list(struct.unpack_from('<48I', b, 16)))


def rgba(rgb):
    """native/conv.c conv_rgba: 0..1 per channel, rounded half up, alpha FF."""
    q = np.floor(np.clip(np.asarray(rgb, float), 0, 1) * 255 + 0.5).astype(int)
    return [int(r) << 24 | int(g) << 16 | int(b) << 8 | 0xFF for r, g, b in q]


def chart_values(target_rgb, fit_rgb, mean_de):
    """The 0 EV checker's 24 targets and fits (display RGB 0..1) and the mean dE76 over the 72 -> chart_block's dict."""
    t, f = rgba(target_rgb), rgba(fit_rgb)
    return dict(match=match_percent(mean_de), patches=[v for p in zip(t, f) for v in p])


def payload(hw):
    """the payload bytes (m1 = m2 when hw has none: tied)"""
    pay = struct.pack('<I9h2x', hw['shift'], *hw['m2'])
    pay += np.asarray(hw['tone'], '<u2').tobytes()
    pay += struct.pack('<7h2x', *hw['ycmat'])
    pay += struct.pack('<72H', *(v for plane in hw['ceq'] for v in plane))
    pay += struct.pack('<18I', *hw['ygam'])
    pay += struct.pack('<9h2x', *hw.get('m1', hw['m2']))
    rec = knee_record(hw)                                     # JFIT v6: the CKNEE block (on, the record's +4 .. +15)
    pay += struct.pack('<I', 1) + rec[4:] if rec else bytes(16)
    assert len(pay) == PAYLOAD
    return pay


def pack(key, hw, stats, chart=None):
    pay = payload(hw)
    sha, color, gamma, amount, matrix = key
    head = struct.pack('<4I8s5I3I2I', MAGIC, VERSION, HEADER, HEADER + PAYLOAD, sha[:8], color, gamma, amount, matrix,
                       JFIT_VERSION, *(int(round(100 * v)) for v in stats), fnv(pay), 0)
    assert len(head) == HEADER
    core = head + pay
    return core + chart_block(core, chart) if chart is not None else core


def unpack(data):
    """-> dict(key, jfit_version, stats, chart, hw).  A file made before JFIT v5 (no m1: m1 = m2, tied) or v6 (no CKNEE:
    knee None) is read too."""
    m, v, hl, total = struct.unpack_from('<4I', data)
    if m != MAGIC or v != VERSION or hl != HEADER or total not in (HEADER + PAYLOAD, HEADER + PAYLOAD_V5, HEADER + PAYLOAD_V4) or \
            len(data) not in (total, total + CHART_BYTES):
        raise ValueError('not a JFT1 file')
    chart = read_chart(data, total)
    data = data[:total]
    sha, color, gamma, amount, matrix, jv, e0, e1, e2, h, _ = struct.unpack_from('<8s5I3I2I', data, 16)
    pay = data[HEADER:]
    if fnv(pay) != h:
        raise ValueError('JFT payload checksum')
    shift, *m2 = struct.unpack_from('<I9h', pay)
    tone = np.frombuffer(pay[24:24 + 3 * NTONE * 2], '<u2').reshape(3, NTONE)
    o = 24 + 3 * NTONE * 2
    ycmat = list(struct.unpack_from('<7h', pay, o)); o += 16
    ceq = list(struct.unpack_from('<72H', pay, o)); o += 144
    ygam = list(struct.unpack_from('<18I', pay, o)); o += 72
    m1 = list(struct.unpack_from('<9h', pay, o)) if len(pay) >= PAYLOAD_V5 else list(m2); o += 20
    knee = None
    if len(pay) == PAYLOAD:
        on, ka, kc, sa, sc, kb, kd, sb, sd = struct.unpack_from('<I2H2B2H2B', pay, o)
        if on > 1:
            raise ValueError('JFT CKNEE block')
        knee = [ka, sa, kc, sc, kb, sb, kd, sd] if on else None
    return dict(key=(sha, color, gamma, amount, matrix), jfit_version=jv, stats=(e0 / 100, e1 / 100, e2 / 100), chart=chart,
                hw=dict(shift=shift, m2=m2, tone=tone, ycmat=ycmat, ceq=[ceq[:24], ceq[24:48], ceq[48:]], ygam=ygam, m1=m1,
                        knee=knee))


# ---------------------------------------------------------------- convert one cube
CONV_ITERS = 20                 # jf_fit's steps per start (JFIT v1, and v3's first stage; native/conv.c CONV_ITERS): ~20 to settle (11-05)
CONV_DIRECT_ITERS = 10          # jf_fit_direct's steps (v3: the refine from the seed; native/conv.c CONV_DIRECT_ITERS)
CONV_UNTIE_ITERS = 40           # jf_fit_untied's steps (v5: the untied refine from the packed v4 result; conv.c CONV_UNTIE_ITERS)
NDX_HSV = 297                   # native/jfit.c JF_NDX_HSV: the dense extras' last (weight 1)
NHSV = 144                      # native/jfit.c JF_NHSV
GREY_LEVELS, GREY_TINT = 24, 0.03


def grey_samples():
    """The grey axis the 11^3 grid lacks (11-05: its diagonal has 4 mid greys, 2.6 % of the weight -> casts on
    the ColorChecker's greys): 24 levels geometric 0.01..1 (equal camera RGB), each with 6 tints of 3 %.
    Q20-rounded: build_sup puts these very values after the ColorChecker (native/conv.c CONV_GREY)."""
    lv = np.geomspace(0.01, 1.0, GREY_LEVELS)
    dirs = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [-1, 0, 0], [0, -1, 0], [0, 0, -1]], float)
    near = np.array([v * (1 + GREY_TINT * d) for v in lv for d in dirs])
    g = np.clip(np.r_[np.repeat(lv[:, None], 3, 1), near], 0, 1)
    return np.round(g * (1 << 20)) / (1 << 20)


def choose(candidates, bt):
    """native/conv.c conv_choose: the candidates P in the order given (v3: refined, the seed, the other v1 start), the
    first that quantises -> (P, hw).  A YCMAT / matrix overflow of one does not fail the conversion
    (FITTER_OPTIMIZATION.md); none -> ValueError."""
    err = None
    for P in candidates:
        dh = hue_safe(P[51:75])                                  # conv_choose: scored as packed (11-10);
        if not np.array_equal(dh, np.asarray(P[51:75], float)):  # a table in order: P itself, untouched
            P = np.array(P, float); P[51:75] = dh
        try:
            return P, quantise(P, bt)
        except ValueError as e:
            err = e
    raise err


def seed_order(v1):
    """native/conv.c: the two v1 (P, cost) by cost, the cheaper first (a NaN last; a tie keeps the identity's)"""
    a, b = v1
    return [b, a] if b[1] == b[1] and not a[1] <= b[1] else [a, b]


def route(xs, want, w, bt, starts, n, iters=None):
    """JFIT v3 "xlm10+144" (native/conv.c conv_compute): jf_fit (CONV_ITERS) from each start on the first n samples
    (the ordinary ones, their weights), the cheaper the seed of jf_fit_direct (CONV_DIRECT_ITERS) on all of them
    (+ the 144 HSV).  iters, when given, replaces both counts (conv.iters).  -> (candidates in packing order:
    refined, seed, other v1; their costs)"""
    v1 = [native_fit(xs[:n], want[:n], w[:n], bt, P0, CONV_ITERS if iters is None else iters) for P0 in starts]
    (seed, cs), (other, co) = seed_order(v1)
    P, cost = native_direct(xs, want, w, bt, seed, CONV_DIRECT_ITERS if iters is None else iters)
    return [P, seed, other], [cost, cs, co]


def dense_set(xs, want, w, target, amount):
    """JFIT v5's training set: the conversion's own samples (xs, want, w: lvb's + greys + 144 HSV) + jf_dense_samples
    (native/conv.c conv_inputs: their target the cube's render, the camera RGB and near-grey ones the stock-look weight)."""
    _probes()
    import lv_fit as F
    xd, nw = dense_samples()
    wd = np.r_[np.sqrt((1 - 2.5 * F.saturation(target(xd[:nw], 0)) / 8) ** 8), np.ones(len(xd) - nw)]
    return np.r_[xs, xd], np.r_[want, F.lab709(target(xd, amount))], np.r_[w, wd]


def untie(P, hw, xs, want, w, bt, iters=None, knee=True):
    """JFIT v5 (native/conv.c conv_untie): jf_fit_untied from the packed v4 result P (its hue order as packed) on the dense
    set; the refined one when it packs and its packed tables cost less on that set (jf_packed_cost) -> (P, hw, info).
    JFIT v6 (knee): the refine frees the CKNEE too; its result is offered with the knee and with the CKNEE off (the same
    other tables) -- the knee kept only when its packed tables cost less than the knee-less ones and the v4 ones
    (conv_untie: knee = packs and ck < c0 and (the other does not pack or ck < cn))."""
    Pu, cu = native_untied(xs, want, w, bt, P, CONV_UNTIE_ITERS if iters is None else iters, knee=knee)
    dh = hue_safe(Pu[51:75])
    if not np.array_equal(dh, Pu[51:75]):
        Pu = Pu.copy(); Pu[51:75] = dh
    c0 = packed_cost(payload(hw), xs, want, w)
    info = dict(cost_tied=c0, cost_untied=None, cost_knee=None, fit_cost=cu, kept='tied', knee=False)
    got = {}
    for tag, Pc in (('knee', Pu if knee_on(Pu) else None), ('untied', knee_off(Pu) if knee_on(Pu) else Pu)):
        if Pc is None:
            continue
        try:
            hwc = quantise(Pc, bt)
        except ValueError as e:
            info['why' if tag == 'untied' else 'why_knee'] = str(e); continue
        info[f'cost_{tag}'] = c = packed_cost(payload(hwc), xs, want, w)
        got[tag] = (c, Pc, hwc)
    k, u = got.get('knee'), got.get('untied')
    if k and k[0] < c0 and (u is None or k[0] < u[0]):
        info['kept'], info['knee'] = 'untied', True
        return k[1], k[2], info
    if u and u[0] < c0:
        info['kept'] = 'untied'
        return u[1], u[2], info
    return P, hw, info


def convert(cube_path, color, gamma, amount=100, sha=b'\0' * 8, matrix=0, iters=None, untied=True):
    """-> (JFT bytes, stats (mean, p95, max dE76 on the ColorChecker at -1/0/+1 EV)).  JFIT v3 (Bei 2026-11-07):
    native/conv.c's route (route()) -- jf_fit from the identity and from lvb's matrix on lvb's samples + the grey
    axis, the cheaper refined by jf_fit_direct on those + the 144 HSV samples (weight 1); refined, seed, other: the
    first that packs.  JFIT v5 (Bei 2026-11-11): then untie() -- the untied refine on the dense set, kept when its
    packed tables cost less there.  untied=False: the v4 result (studies only; its file would say v5)."""
    _probes()
    import lv_fit as F
    import lut_batch_eval as E
    import joint_fit_eval as J
    from cube import Cube
    from cinemadng import COLOR_SPACES, COMMON_GAMMAS, BLACKMAGIC_GAMMAS
    if matrix not in (0, 1, 2):
        raise ValueError('matrix must be standard / off / custom (library.MATRICES)')
    # the matrix is part of the key only: the camera's render (lvb_render, the asset) does not read it -- it goes to
    # the DNG (dng.c) -- so the host target is the same for all three (11-05: default Off, user)
    space = list(COLOR_SPACES)[color]
    gname = (BLACKMAGIC_GAMMAS if space == 'blackmagic-design' else COMMON_GAMMAS)[gamma]
    target = F.make_target(Cube.read(cube_path), space=space, gamma=gname)
    fit = E.fit_lvb(target, amount)
    base = np.r_[E.lvb_samples(), grey_samples()]
    xs = np.r_[base, hsv_samples()]; want = F.lab709(target(xs, amount))
    w = np.r_[np.sqrt((1 - 2.5 * F.saturation(target(base, 0)) / 8) ** 8), np.ones(NHSV)]
    bt = fit['tone'].astype(float) / F.TONE_MAX
    if fit['shift']:
        bt = np.stack([np.interp(np.arange(NTONE) / 2 ** fit['shift'], np.arange(NTONE), bt[k]) for k in range(3)])
    M_lvb = np.asarray(fit['q'], float) / F.Q9 * 2 ** fit['shift']
    starts = [np.r_[M0.ravel(), M0.ravel(), np.zeros(27), E.POST_ID]   # the identity (YCMAT takes the chroma), lvb's
              for M0 in (np.eye(3), M_lvb)]
    candidates, _costs = route(xs, want, w, bt, starts, len(base), iters)
    P, hw = choose(candidates, bt)
    if untied:
        P, hw, _info = untie(P, hw, *dense_set(xs, want, w, lambda x, s: target(x, s), amount), bt, iters)
    chk = E.sample_sets()['色卡']
    fit_rgb = chain(chk, P, (bt * F.TONE_MAX))
    dE = E.score_set(target(chk, amount), fit_rgb)
    stats = (float(dE.mean()), float(np.percentile(dE, 95)), float(dE.max()))
    chart = chart_values(target(chk[24:48], amount), fit_rgb[24:48], stats[0])   # the 0 EV set, as conv.c's chart
    return pack((sha, color, gamma, amount, matrix), hw, stats, chart), stats


def chain(xs, P, bt, split=True):
    """joint_fit_eval.chain (bt: the base tone in code, as there) with JFIT v6's CKNEE after YCMAT (native/jfit.c
    jf_chain_t) when P has one -- exactly joint_fit_eval.chain when it has none."""
    _probes()
    import joint_fit_eval as J
    if not knee_on(P):
        return J.chain(xs, np.asarray(P, float)[:NK], bt, split)
    import lv_fit as F
    import lut_batch_eval as E
    P = np.asarray(P, float)
    d = P[18:45].reshape(3, J.KN)
    tone = np.stack([np.clip(np.maximum.accumulate(bt[k] / F.TONE_MAX + np.interp(J.AX, J.KX, d[k])), 0, 1) for k in range(3)])

    def through(M):
        idx = np.clip(np.asarray(xs, float) @ M.T * F.WHITE_INDEX, 0, F.N_TONE - 1)
        return np.stack([np.interp(idx[:, k], J.AX, tone[k]) for k in range(3)], -1)
    ch = through(P[:9].reshape(3, 3))
    rgb = np.clip(F.luma_preserve(through(P[9:18].reshape(3, 3)), ch) if split else ch, 0, 1)
    p = P[45:NK]
    yr, yb, cbr, cbb, crr, crb = p[:6]                         # lut_batch_eval.post_apply, the CKNEE after YCMAT
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = yr * r + (1 - yr - yb) * g + yb * b
    cb = cbr * (r - g) + cbb * (b - g); cr = crr * (r - g) + crb * (b - g)
    kn = P[NK:NK + 8]

    def bend(v, k):
        x = np.abs(v); kk, mm = np.where(v < 0, k[2], k[0]), np.where(v < 0, k[3], k[1])
        return np.where(x > kk, np.sign(v) * (kk + (x - kk) * mm), v)
    cb, cr = bend(cb, kn[:4]), bend(cr, kn[4:])
    th = np.degrees(np.arctan2(cr, cb)) % 360; c = np.hypot(cb, cr)
    x = np.arange(25) * 15.
    lerp = lambda t: np.interp(th, x, np.r_[t, t[0]])
    q = p[6:78]
    c2 = c * lerp(q[24:48]); th2 = np.radians(th + E.hue_lerp(th, q[:24])); y2 = y + (lerp(q[48:]) - 1) * c
    y2 = np.interp(y2, np.linspace(0, 1, 17), np.maximum.accumulate(p[78:95]))
    cb2, cr2 = c2 * np.cos(th2), c2 * np.sin(th2)
    kr, kb = E.K601; kg = 1 - kr - kb
    R = y2 + 2 * (1 - kr) * cr2; B = y2 + 2 * (1 - kb) * cb2; G = (y2 - kr * R - kb * B) / kg
    return np.clip(np.stack([R, G, B], -1), 0, 1)


def match_percent(mean_de):
    """還原度 as the manager shows it (native/conv.c conv_pct; user 2026-11-04: a percentage): 100 - 10 x mean dE76,
    from the header's dE x 100 as the camera computes it."""
    m100 = int(round(100 * mean_de))
    tenth = (m100 * 6554 + 32768) >> 16
    return 0 if tenth >= 100 else 100 - tenth


def path_for(sha_hex):
    """native/lvb.c lvb_jpath: sha[0..7]; a camera identity ('CAM1' + size .. +20 the name's fnv, import.c
    imp_identity) by sha[4..7] + sha[20..23] -- size and name (2026-11-10: same-size cubes shared a file).
    `sha_hex` the whole identity (64 hex digits) for a camera one."""
    if sha_hex[:8] == '43414d31':
        if len(sha_hex) < 48:
            raise ValueError('a camera identity needs its bytes 20..23 (the name): pass the whole identity')
        return f'fpSup/LUTDATA/{sha_hex[8:16]}{sha_hex[40:48]}.JFT'
    return f'fpSup/LUTDATA/{sha_hex[:16]}.JFT'


# ---------------------------------------------------------------- a whole library (the card's LUTDATA folder)
def library_files(document, log=print):
    """-> ({card path: JFT bytes}, {id: stats or reason}).  One file per entry, keyed as native lvb_refresh keys
    the row (sha[0..7], colour, gamma within its family, strength, matrix); an entry left out falls back to the
    camera's own fit (lvb.c), so skipping is always safe.  The key is the record build_sup writes (library.binary:
    the file's name and size, zero dates); a real card's dates re-key it on the first scan, so for a card use
    bin_files on its saved LUT.BIN instead."""
    import library as LB
    from cinemadng import COLOR_SPACES, COMMON_GAMMAS, BLACKMAGIC_GAMMAS
    document = LB.refresh(document)
    files, report = {}, {}
    for entry in document['luts']:
        v = LB.resolved(entry)
        if not v['configured']:
            report[entry['id']] = 'input not set'; continue
        color = list(COLOR_SPACES).index(v['input_space'])
        gamma = (BLACKMAGIC_GAMMAS if color == 2 else COMMON_GAMMAS).index(v['input_gamma'])
        source = Path(entry['source']).read_bytes()
        key = LB.camera_identity(LB.camera_name(entry['filename']), len(source))
        data, stats = convert(Path(entry['source']), color, gamma, v['strength_percent'], key[:8], LB.MATRICES.index(v['color_matrix']))
        files[path_for(key.hex())] = data
        report[entry['id']] = stats
        log(f'{entry["filename"]}: {match_percent(stats[0])}% match  (dE mean {stats[0]:.2f}  p95 {stats[1]:.2f}  max {stats[2]:.2f})')
    return files, report


def bin_files(bin_data, sources, log=print):
    """The camera's own records (a saved LUT.BIN) + the card's fpSup/LUT folder -> {card path: JFT}.
    Keys straight from the record, so they are what lvb_refresh compares.  A record's cube is the folder's
    file of its name (origin camera); a hidden record (its file gone) is skipped."""
    import library as LB
    off = struct.unpack_from('<I', bin_data, 76)[0]
    magic, version, header, record, count = struct.unpack_from('<5I', bin_data, off)
    if magic != LB.MAGIC or version != 3 or record != LB.RECORD:
        raise ValueError('need a v3 library record')
    files = {}
    for i in range(count):
        p = off + header + record * i
        ident = bin_data[p:p + 32].hex(); name = bin_data[p + 32:p + 96].split(b'\0')[0].decode('utf-8', 'replace')
        flags, color, gamma, amount = struct.unpack_from('<4I', bin_data, p + 96)
        matrix = struct.unpack_from('<I', bin_data, p + 128)[0]
        origin = struct.unpack_from('<I', bin_data, p + 124)[0]
        if (flags & 15) != 15 or matrix > 2 or origin != LB.ORIGIN_CAMERA:   # enabled + set up (LIB_ALL), its file there
            log(f'{name}: skipped (flags {flags:#x}, matrix {matrix}, origin {origin})'); continue
        src = Path(sources) / name
        data, st = convert(src, color, gamma, amount, bytes.fromhex(ident)[:8], matrix)
        files[path_for(ident)] = data
        log(f'{name}: {match_percent(st[0])}% match  (dE mean {st[0]:.2f}  p95 {st[1]:.2f}  max {st[2]:.2f})')
    return files


if __name__ == '__main__':
    import argparse, json
    ap = argparse.ArgumentParser(description='convert a LUT library to .JFT files (card layout under OUT)')
    ap.add_argument('library', help='library json (fplut.py lib), or a saved LUT4 BIN with --sources')
    ap.add_argument('out', help='output root: files land at OUT/fpSup/LUTDATA/')
    ap.add_argument('--sources', help="the card's fpSup/LUT folder, its .cube files (BIN input)")
    a = ap.parse_args()
    if a.sources:
        files = bin_files(Path(a.library).read_bytes(), a.sources)
    else:
        files, _ = library_files(json.loads(Path(a.library).read_text()))
    for name, data in files.items():
        p = Path(a.out) / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    print(f'{len(files)} files')
