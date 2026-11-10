"""QR scan decoder (qrdec.c), phase 1 of notes/QR_SCAN_DESIGN.md: offline, host build + Thumb build under unicorn.

Codes: the REAL slqs.c encoder (qrdec_unit extracts it), for every preset recipe of the site data (837) and random
payloads.  Images: 512 x 512 Y8 like the stock reader's input (FUN_c05c48a0: the centre 512 x 512 of the display
image), 3..8 px/module, rotation +-10 deg, perspective, blur, noise, contrast loss, partial glare, scene background.

  python3 -B test_qrdec.py              # the suite
  python3 -B test_qrdec.py --rates      # the decode-rate matrix -> validation/20261104-qr-scan-design/rates.json
  python3 -B test_qrdec.py --count      # Thumb instruction counts under unicorn -> .../instructions.json
  python3 -B test_qrdec.py --mutate     # every mutant must be caught
"""
import json
import math
import pathlib
import random
import sys
import unittest

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import qrdec_unit as U          # noqa: E402

VAL = HERE.parent / 'validation' / '20261104-qr-scan-design'
URL = 'https://ijigen.github.io/fpSup/sensor_lab_imx410/#'
B64U = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
WIDTHS = [4, 13, 12, 13, 12, 5, 15, 16, 2, 2, 3, 4, 4, 6, 3, 3, 1, 1, 13, 12, 17, 1, 1, 13, 12, 13, 12]
LIB = None


def lib():
    global LIB
    if LIB is None:
        LIB = U.Lib()
    return LIB


# ------------------------------------------------------------------ payloads
def preset_fields():
    """the 837 preset recipes exactly as site/test_site.py builds them (same data files, same field mapping)"""
    import ast
    import re
    site = HERE.parent / 'site'
    sys.path.insert(0, str(site))
    import build_site as BSITE
    html = BSITE.SOURCE.read_text()
    logic = html.split('<script>\n', 1)[1].split('// ---- render', 1)[0]
    data = json.loads((BSITE.PREVIEW / 'fps_data.js').read_text().split('const FPSDATA = ', 1)[1].rstrip(';\n'))
    dcs = {n: (w, h) for n, w, h in ast.literal_eval(re.search(r'const DCS = (\[.*?\]);', logic)[1])}
    demo = dict(ver=1, fps=8, rs=7370, kh=1, kv=1, km=0, rcustom=0, fmt=0, rescustom=0, key=5)
    out = []
    for cell, recipes in data['cases'].items():
        dc, wh = cell.split(':')
        rw, rh = map(int, wh.split('x'))
        dcw, dch = dcs[dc]
        for hm, lo, _name, r in recipes:
            f = dict(demo, dcw=dcw, dch=dch, rw=rw, rh=rh, vmax=lo, hmax=hm, ad={11: 0, 12: 1, 14: 2}[r['ad']],
                     mh=r['mh'], mv=r['mv'], hbin=r['hbin'], vbin=r['vbin'], visw=r['vis'][0], vish=r['vis'][1],
                     scw=r['scw'], sch=r['sch'], ww=r['win'][0], wh=r['win'][1])
            order = ['ver', 'dcw', 'dch', 'rw', 'rh', 'fps', 'vmax', 'hmax', 'ad', 'mh', 'mv', 'hbin', 'vbin', 'key',
                     'kh', 'kv', 'km', 'rcustom', 'visw', 'vish', 'rs', 'fmt', 'rescustom', 'scw', 'sch', 'ww', 'wh']
            out.append([f[k] for k in order])
    return out


def random_fields(n, seed=410):
    rnd = random.Random(seed)
    return [[1] + [rnd.randrange(1 << w) for w in WIDTHS[1:]] for _ in range(n)]


def codes():
    L = lib()
    return [L.pack(f) for f in preset_fields()] + [L.pack(f) for f in random_fields(300)]


# ------------------------------------------------------------------ rendering (the reader's 512 x 512 Y8)
def _hom(src, dst):
    a = []
    for (x, y), (u, v) in zip(src, dst):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.array(a, float))
    return vt[-1].reshape(3, 3)


def _blur(img, sigma):
    if sigma <= 0:
        return img
    r = int(math.ceil(3 * sigma))
    k = np.exp(-np.arange(-r, r + 1) ** 2 / (2 * sigma * sigma)); k /= k.sum()
    p = np.pad(img, r, mode='edge')
    p = np.apply_along_axis(lambda m: np.convolve(m, k, 'valid'), 1, p)
    return np.apply_along_axis(lambda m: np.convolve(m, k, 'valid'), 0, p)


def render(mat, rng, scale=5.0, rot=0.0, persp=0.0, blur=0.0, noise=0.0, black=20, white=235, glare=0.0, qz=2,
           mirror=False, size=512, scene=True, info=None):
    """mat: 37 x 37, 1 = dark -> uint8 size x size"""
    m = mat.T if mirror else mat
    N = 37 + 2 * qz
    side = N * scale
    cx, cy = size / 2 + rng.uniform(-20, 20), size / 2 + rng.uniform(-20, 20)
    th = math.radians(rot)
    corners = []
    for (u, v) in ((0, 0), (N, 0), (N, N), (0, N)):
        x, y = (u - N / 2) * scale, (v - N / 2) * scale
        x, y = x * math.cos(th) - y * math.sin(th), x * math.sin(th) + y * math.cos(th)
        corners.append((cx + x + rng.uniform(-persp, persp) * side, cy + y + rng.uniform(-persp, persp) * side))
    H = _hom(corners, [(0, 0), (N, 0), (N, N), (0, N)])         # image -> module
    if info is not None:
        info['to_img'] = np.linalg.inv(H); info['qz'] = qz
    ss = 2
    ys, xs = np.mgrid[0:size * ss, 0:size * ss]
    px, py = (xs + 0.5) / ss, (ys + 0.5) / ss
    w = H[2, 0] * px + H[2, 1] * py + H[2, 2]
    u = (H[0, 0] * px + H[0, 1] * py + H[0, 2]) / w - qz
    v = (H[1, 0] * px + H[1, 1] * py + H[1, 2]) / w - qz
    inside = (u >= -qz) & (u < 37 + qz) & (v >= -qz) & (v < 37 + qz)
    mi, mj = np.floor(u).astype(int), np.floor(v).astype(int)
    code = (mi >= 0) & (mi < 37) & (mj >= 0) & (mj < 37)
    dark = np.zeros(u.shape, bool)
    dark[code] = m[mj[code], mi[code]] == 1
    if scene:
        npr = np.random.default_rng(rng.randrange(1 << 30))
        bg = npr.uniform(30, 220, (size // 32 + 2, size // 32 + 2))
        bg = np.kron(bg, np.ones((32 * ss, 32 * ss)))[:size * ss, :size * ss]
        for _ in range(4):                                      # a few hard-edged confusers
            x0, y0 = rng.randrange(0, size * ss), rng.randrange(0, size * ss)
            bg[y0:y0 + rng.randrange(10, 80), x0:x0 + rng.randrange(10, 80)] = rng.uniform(0, 255)
    else:
        bg = np.full(u.shape, float(white))
    img = np.where(inside, np.where(dark, black, white), bg)
    img = img.reshape(size, ss, size, ss).mean(axis=(1, 3))
    img = _blur(img, blur)
    if glare:
        gx, gy = cx + rng.uniform(-0.3, 0.3) * side, cy + rng.uniform(-0.3, 0.3) * side
        yy, xx = np.mgrid[0:size, 0:size]
        img = img + glare * np.exp(-((xx - gx) ** 2 + (yy - gy) ** 2) / (2 * (0.18 * side) ** 2))
    if noise:
        img = img + np.random.default_rng(rng.randrange(1 << 30)).normal(0, noise, img.shape)
    return np.clip(np.rint(img), 0, 255).astype(np.uint8)


CONDITIONS = {        # name: render kwargs (scale is swept separately)
    'clean': {},
    'rot10': dict(rot=10),
    'rot-10': dict(rot=-10),
    'persp': dict(persp=0.06),
    'blur0.8': dict(blur=0.8),
    'blur1.4': dict(blur=1.4),
    'noise10': dict(noise=10),
    'noise20': dict(noise=20),
    'contrast': dict(black=90, white=160),
    'glare': dict(glare=110),
    'combined': dict(rot=7, persp=0.04, blur=0.9, noise=8, black=60, white=200, glare=60),
    # stress (beyond the brief; reported, floors 0)
    'blur2.0': dict(blur=2.0),
    'noise30': dict(noise=30),
    'persp0.10': dict(persp=0.10),
    'glare160': dict(glare=160),
    'lowc40': dict(black=110, white=150),
    'hard': dict(rot=10, persp=0.06, blur=1.4, noise=15, black=80, white=180, glare=100),
}
SCALES = (3, 4, 5, 6, 8)


def trial(L, code, rng, scale, kw, mirror=False):
    url = URL + code
    mat, fn, _mask = L.encode(url)
    img = render(mat, rng, scale=scale, mirror=mirror, **kw)
    r, data, diag = L.decode(img, fn)
    return r, data, diag, url


def rates(n_codes=60, seed=1, out=None):
    L = lib()
    cs = codes()
    rnd = random.Random(seed)
    pick = rnd.sample(cs, n_codes)
    res, wrong = {}, 0
    for name, kw in CONDITIONS.items():
        for s in SCALES:
            ok = 0
            for i, c in enumerate(pick):
                r, data, _d, url = trial(L, c, random.Random(seed * 100003 + i * 31 + s), s, kw)
                if r == 0 and data.decode('latin1') == url:
                    ok += 1
                elif r == 0:
                    wrong += 1
            res[f'{name}@{s}'] = ok / n_codes
    out = out or {}
    out.update(rates=res, wrong_payloads=wrong, n_codes=n_codes)
    return out


# ------------------------------------------------------------------ format modules (slqs.c qr_format's layout)
FMT_A = [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(14 - i, 8) for i in range(9, 15)]
FMT_B = [(36 - i, 8) for i in range(8)] + [(8, 37 - 15 + i) for i in range(8, 15)]


def fmt_word(ecl, mask):
    data = ecl << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return (data << 10 | rem) ^ 0x5412


def set_format(mat, word, copy):
    m = mat.copy()
    for i, (x, y) in enumerate(FMT_A if copy == 'A' else FMT_B):
        m[y, x] = word >> i & 1
    return m


# ------------------------------------------------------------------ the suite
class Unit(unittest.TestCase):
    def test_pack_unpack_round_trip_and_reference(self):
        """qr_unpack (qrdec.c) inverts the C qr_pack; the C qr_pack = test_slqs's Python reference"""
        import test_slqs as Q
        L = lib()
        for f in random_fields(400) + preset_fields()[:200]:
            code = L.pack(f)
            self.assertEqual(code, Q.qr_pack(f))
            r, g = L.unpack(code)
            self.assertEqual((r, g), (0, [v & ((1 << w) - 1) for v, w in zip(f, WIDTHS)]))

    def test_unpack_rejects_crc_pad_version_chars(self):
        L = lib()
        code = L.pack(random_fields(1)[0])
        for bit in range(221):                                   # every single-bit flip is caught
            i, sh = divmod(bit, 6)
            bad = code[:i] + B64U[B64U.index(code[i]) ^ (1 << (5 - sh))] + code[i + 1:]
            self.assertIn(L.unpack(bad)[0], (2, 4), bit)
        pad = code[:-1] + B64U[B64U.index(code[-1]) ^ 1]
        self.assertEqual(L.unpack(pad)[0], 3)
        f = random_fields(1)[0]; f[0] = 2
        self.assertEqual(L.unpack(L.pack(f))[0], 4)
        self.assertEqual(L.unpack(code[:-1] + '=')[0], 1)

    def test_sensorlab_check_plain_and_stock_convention(self):
        """our decoder returns plain bytes; the stock decoder returns byte - i (FUN_c05c5bc0): both recognised"""
        L = lib()
        code = L.pack(random_fields(1)[0])
        plain = (URL + code).encode()
        self.assertEqual(L.sensorlab(plain, 0), code)
        stock = L.to_stock(plain)
        self.assertEqual(stock, bytes((b - i) & 0xFF for i, b in enumerate(plain)))
        self.assertEqual(L.sensorlab(stock, 1), code)
        self.assertIsNone(L.sensorlab(stock, 0))
        self.assertIsNone(L.sensorlab(plain, 1))
        self.assertIsNone(L.sensorlab(plain[:-1], 0))
        self.assertIsNone(L.sensorlab(plain + b'A', 0))
        self.assertIsNone(L.sensorlab(plain.replace(b'ijigen', b'ijigem'), 0))
        self.assertIsNone(L.sensorlab(plain[:-1] + b'=', 0))
        self.assertIsNone(L.sensorlab(b'C43' + bytes(84), 0))   # a stock settings header is not ours

    def test_rs_corrects_up_to_13_and_never_miscorrects_silently(self):
        L = lib()
        rnd = random.Random(5)
        cw = self._codewords(L, URL + L.pack(random_fields(1)[0]))
        for k in range(0, 14):
            for t in range(20):
                c = list(cw)
                for p in rnd.sample(range(134), k):
                    c[p] ^= rnd.randrange(1, 256)
                n, fixed = L.rs(c)
                self.assertEqual((n, fixed), (k, bytes(cw)), (k, t))
        for k in range(14, 30):
            for t in range(20):
                c = list(cw)
                for p in rnd.sample(range(134), k):
                    c[p] ^= rnd.randrange(1, 256)
                n, fixed = L.rs(c)
                if n >= 0:                                       # a miscorrection must at least be a valid codeword
                    self.assertEqual(L.rs(list(fixed))[0], 0)

    @staticmethod
    def _codewords(L, url, mode=4):
        """the 134 codewords as the encoder builds them (independent Python: byte mode, pad, RS remainder)"""
        bits = format(mode, '04b') + format(len(url), '08b') + ''.join(format(b, '08b') for b in url.encode()) + '0000'
        bits += '0' * (-len(bits) % 8)
        data = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
        pad = 0xEC
        while len(data) < 108:
            data.append(pad); pad ^= 0xEC ^ 0x11
        ex, lg = [0] * 512, [0] * 256
        x = 1
        for i in range(255):
            ex[i] = x; lg[x] = i; x <<= 1
            if x & 0x100:
                x ^= 0x11D
        for i in range(255, 512):
            ex[i] = ex[i - 255]
        mul = lambda a, b: 0 if not a or not b else ex[lg[a] + lg[b]]
        g = [1]
        for i in range(26):
            g = [a ^ mul(b, ex[i]) for a, b in zip(g + [0], [0] + g)]
        rem = data + [0] * 26
        for i in range(108):
            f = rem[i]
            if f:
                for j, gj in enumerate(g):            # g: highest power first
                    rem[i + j] ^= mul(gj, f)
        return data + rem[108:]

    def test_every_preset_and_random_code_clean(self):
        """all 837 preset recipes + 300 random payloads, rendered clean at 4 px/module over a scene background"""
        L = lib()
        for i, c in enumerate(codes()):
            r, data, diag, url = trial(L, c, random.Random(i), 4, {})
            self.assertEqual((r, data.decode('latin1')), (0, url), (i, c, diag))

    def test_format_from_either_copy_and_ecc_l_only(self):
        """one format copy destroyed -> the other one reads; an ECC M/Q/H word (same data) is refused"""
        L = lib()
        code = L.pack(random_fields(1, 11)[0])
        mat, fn, mask = L.encode(URL + code)
        self.assertTrue((set_format(mat, fmt_word(1, mask), 'A') == mat).all())   # the layout above = the encoder
        for copy in ('A', 'B'):
            bad = set_format(mat, fmt_word(1, mask) ^ 0x2A5B, copy)              # 8 bits wrong in one copy
            for k, f in enumerate(random_fields(8, 12)):                 # several masks: every format bit matters
                m2, fn2, mask2 = L.encode(URL + L.pack(f))
                bad2 = set_format(m2, fmt_word(1, mask2) ^ 0x2A5B, copy)
                r, data, d = L.decode(render(bad2, random.Random(3 + k), scale=5, scene=False), fn2)
                self.assertEqual((r, data.decode(), d[2]), (0, URL + L.pack(f), 0), (copy, k))
        for ecl in (0, 2, 3):
            m = set_format(set_format(mat, fmt_word(ecl, mask), 'A'), fmt_word(ecl, mask), 'B')
            self.assertNotEqual(L.decode(render(m, random.Random(3), scale=5, scene=False), fn)[0], 0, ecl)

    def test_byte_mode_only(self):
        """the same symbol with an alphanumeric (0010) or numeric (0001) mode header is not returned"""
        L = lib()
        sys.path.insert(0, str(HERE.parent / 'tools' / 'qr'))
        import qr_v5_reference as R
        url = URL + L.pack(random_fields(1, 13)[0])
        mat, fn, mask = L.encode(url)
        cw = Unit._codewords(L, url)
        r, data, _d = L.decode(render(mat, random.Random(4), scale=5, scene=False), fn)
        self.assertEqual((r, data.decode()), (0, url))
        for mode in (2, 1):
            c = Unit._codewords(L, url, mode=mode)
            self.assertEqual(c[0] >> 4, mode)
            m = mat.copy()
            bits = [c[i >> 3] >> (7 - (i & 7)) & 1 for i in range(8 * 134)]
            for i, (x, y) in enumerate(list(R.data_coordinates())[:8 * 134]):
                m[y, x] = bits[i] ^ int(R.mask_at(mask, x, y))
            self.assertNotEqual(L.decode(render(m, random.Random(4), scale=5, scene=False), fn)[0], 0, mode)
        m = mat.copy()                                                    # the control: byte mode re-placed = same
        for i, (x, y) in enumerate(list(R.data_coordinates())[:8 * 134]):
            m[y, x] = (cw[i >> 3] >> (7 - (i & 7)) & 1) ^ int(R.mask_at(mask, x, y))
        self.assertTrue((m == mat).all())

    def test_finder_ratio(self):
        import ctypes
        L = lib()
        f = L.L.qh_dbg_ratio
        f.restype = ctypes.c_uint32
        R5 = ctypes.c_uint32 * 5
        for k in (1, 2, 3, 8):
            self.assertEqual(f(R5(k, k, 3 * k, k, k)), 7 * k)
        for runs in ((1, 1, 1, 1, 1), (1, 1, 8, 1, 1), (2, 2, 16, 2, 2), (1, 2, 3, 1, 1), (4, 1, 3, 1, 1), (2, 2, 6, 2, 0)):
            self.assertEqual(f(R5(*runs)), 0, runs)

    def test_threshold_and_row_scan_white_box(self):
        """the binarisation = 5 x 5 block mean (contrast fallback) recomputed here; the row scan sees exactly that
        binarisation (its 1:1:3:1:1 passes on every 2nd row, counted independently)"""
        import ctypes
        L = lib()
        f = L.L.qh_dbg_scan
        f.restype = ctypes.c_uint32
        for k in range(4):
            mat, _fn, _ = L.encode(URL + L.pack(random_fields(1, 30 + k)[0]))
            img = render(mat, random.Random(30 + k), scale=3 + k, **CONDITIONS['combined' if k & 1 else 'glare'])
            h, w = img.shape
            bin_ = (ctypes.c_uint8 * (w * h))()
            hits = f(L.dbuf, img.ctypes.data_as(ctypes.c_void_p), w, h, bin_)
            b = np.frombuffer(bytes(bin_), np.uint8).reshape(h, w)
            nb = (h + 15) // 16, (w + 15) // 16
            lo = np.zeros(nb, int); hi = np.zeros(nb, int); mn = np.zeros(nb, int)
            for by in range(nb[0]):
                for bx in range(nb[1]):
                    blk = img[16 * by:16 * by + 16, 16 * bx:16 * bx + 16].astype(int)
                    lo[by, bx], hi[by, bx], mn[by, bx] = blk.min(), blk.max(), blk.sum() // blk.size
            g = (lo + hi).sum() // (2 * lo.size)
            thr = np.zeros(nb, int)
            for by in range(nb[0]):
                for bx in range(nb[1]):
                    sl = np.s_[max(0, by - 2):by + 3, max(0, bx - 2):bx + 3]
                    thr[by, bx] = g if hi[sl].max() - lo[sl].min() < 24 else mn[sl].sum() // mn[sl].size
            ref = (img < np.kron(thr, np.ones((16, 16), int))[:h, :w]).astype(np.uint8)
            self.assertTrue((b == ref).all(), k)
            n = 0
            for y in range(0, h, 2):
                row = ref[y]
                edges = np.flatnonzero(np.diff(row)) + 1
                starts = np.r_[0, edges]; lens = np.diff(np.r_[starts, w]); cols = row[starts]
                for i in range(4, len(lens)):
                    if cols[i] != 1:
                        continue
                    r = [int(v) for v in lens[i - 4:i + 1]]
                    t = sum(r)
                    if t >= 7 and all(14 * r[j] >= t and 14 * r[j] <= 3 * t for j in (0, 1, 3, 4)) \
                            and 4 * t <= 14 * r[2] <= 9 * t:
                        n += 1
            self.assertEqual(hits, n, k)

    def test_mirrored_symbol(self):
        L = lib()
        c = L.pack(random_fields(1)[0])
        r, data, diag, url = trial(L, c, random.Random(2), 5, {}, mirror=True)
        self.assertEqual((r, data.decode(), diag[6]), (0, url, 1))

    def test_degradations_meet_the_floor(self):
        """the rate floors (measured in --rates; floors set below the measured values, documented in the notes)"""
        out = rates(n_codes=20, seed=3)['rates']
        floors = json.loads((VAL / 'floors.json').read_text())
        low = {k: v for k, v in out.items() if v < floors.get(k, 0)}
        self.assertEqual(low, {})

    def test_no_false_decodes_on_scenes_and_other_versions(self):
        """background-only frames and other QR versions (the stock V20/V26 and V3/V4 renders) never decode"""
        L = lib()
        _m, fn, _ = L.encode(URL + 'A' * 37)
        for i in range(40):
            rng = random.Random(1000 + i)
            img = render(np.zeros((37, 37), np.uint8), rng, scale=0.01, noise=10)   # no code, only scene
            self.assertNotEqual(L.decode(img, fn)[0], 0)
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('PIL not installed: other-version renders unchecked')
        for v in ('v3', 'v4', 'v20', 'v26'):
            p = HERE.parent / 'tools' / 'qr' / f'{v}.png'
            g = np.asarray(Image.open(p).convert('L'))
            canvas = np.full((512, 512), 255, np.uint8)
            h, w = min(512, g.shape[0]), min(512, g.shape[1])
            canvas[:h, :w] = g[:h, :w]
            self.assertNotEqual(L.decode(canvas, fn)[0], 0, v)

    def test_encoder_extract_is_the_built_sup(self):
        """the extracted encoder = the encoder in the real SensorLab build (unicorn, sq_test 14 matrix)"""
        try:
            import test_slqs as S
            c = S.boot(qr_force=1)
        except Exception as e:            # noqa: BLE001
            self.skipTest(f'unicorn harness unavailable: {e}')
        L = lib()
        S_lcd = S.QRScreen(c); c.guid(S.FMT_ID)
        info = S.qr_info(c)
        url = c.cstr(info['url'], 96)
        mat = np.frombuffer(bytes(c.mu.mem_read(info['mat'], 1369)), np.uint8).reshape(37, 37)
        m2, _fn, _ = L.encode(url)
        self.assertTrue(((mat == 0) == (m2 == 1)).all())
        del S_lcd


# ------------------------------------------------------------------ instruction counts (Thumb, unicorn)
def count(n=6, seed=7):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
    from unicorn import arm_const as A
    img = U.thumb_image()
    L = lib()
    BASE, STK, WRK = 0x100000, 0x800000, 0x1000000
    res = []
    for i in range(n):
        rng = random.Random(seed + i)
        s = SCALES[i % len(SCALES)]
        code = L.pack(random_fields(1, seed + i)[0])
        mat, fn, _ = L.encode(URL + code)
        kw = CONDITIONS['combined'] if i % 2 else {}
        y8 = render(mat, rng, scale=s, **kw)
        mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        mu.mem_map(BASE, 0x100000); mu.mem_write(BASE, bytes(img.code))
        mu.mem_map(STK - 0x10000, 0x10000)
        mu.mem_map(WRK, 0x200000)
        d, im, fna, out, ln, dg = WRK, WRK + 0x10000, WRK + 0x60000, WRK + 0x61000, WRK + 0x61100, WRK + 0x61200
        mu.mem_write(im, y8.tobytes()); mu.mem_write(fna, fn)
        n_ins = [0]
        mu.hook_add(UC_HOOK_CODE, lambda *_: n_ins.__setitem__(0, n_ins[0] + 1))
        mu.reg_write(A.UC_ARM_REG_SP, STK - 16)
        for r_, v in zip((A.UC_ARM_REG_R0, A.UC_ARM_REG_R1, A.UC_ARM_REG_R2, A.UC_ARM_REG_R3), (d, im, 512, 512)):
            mu.reg_write(r_, v)
        sp = STK - 32
        import struct
        mu.mem_write(sp, struct.pack('<5I', 512, fna, out, ln, dg))
        mu.reg_write(A.UC_ARM_REG_SP, sp)
        RET = BASE + 0xFF000
        mu.mem_write(RET, b'\x00\xbf\x00\xbf')
        mu.reg_write(A.UC_ARM_REG_LR, RET | 1)
        mu.emu_start((BASE + img.functions['qh_decode']) | 1, RET, count=400_000_000)
        r = mu.reg_read(A.UC_ARM_REG_R0)
        got = bytes(mu.mem_read(out, struct.unpack('<I', mu.mem_read(ln, 4))[0]))
        hr, hdata, _ = L.decode(y8, fn)
        res.append(dict(scale=s, cond='combined' if i % 2 else 'clean', ok=r == 0 and got == (URL + code).encode(),
                        host_same=(r, got) == (hr, hdata), instructions=n_ins[0]))
    sizes = sorted(((k, v) for k, v in img.functions.items()), key=lambda kv: kv[1] & ~1)
    return dict(runs=res, image_bytes=len(img.code), functions={k: v for k, v in sizes})


# ------------------------------------------------------------------ mutants
MUTANTS = [
    ('no RS correction', 'if (L > QD_T) return -1;', 'if (L > 0u) return -1;'),
    ('Forney without X', 'qd_mul(d, qd_mul(d, X, om), qd_inv(d, dl))', 'qd_mul(d, om, qd_inv(d, dl))'),
    ('format copy A bit order', 'a |= qd_m(d, 8, 7) << 6 | qd_m(d, 8, 8) << 7', 'a |= qd_m(d, 8, 8) << 6 | qd_m(d, 8, 7) << 7'),
    ('format accepts any ECC', 'return be == 1u && bd <= 3u', 'return be != 9u && bd <= 3u'),
    ('global threshold only', 'd->thr[by * nbx + bx] = (u8)(hi - lo < QD_MINC', 'd->thr[by * nbx + bx] = (u8)(1'),
    ('block mean wrong', 's += d->mn[j * nbx + i]; n++;', 's += d->hi[j * nbx + i]; n++;'),
    ('no alignment refinement', 'if (best >= 22u && n)', 'if (0)'),
    ('no mirror retry', 'if (r == QD_FORMAT || r == QD_GEOM) {', 'if (0) {'),
    ('zigzag skips column 6 wrong', 'if (right == 6) right = 5;', 'if (right == 6) right = 4;'),
    ('segment ignores mode', 'if (d->cw[0] >> 4 != 4u) return -1;', ''),
    ('stock quirk ignored', 'u32 c = (b[i] + (stock ? i : 0u)) & 0xFFu;', 'u32 c = (b[i] + (stock ? 0u : 0u)) & 0xFFu;'),
    ('prefix not checked', 'if (c != (u8)P[i]) return 0; continue;', 'continue;'),
    ('pad not checked', 'if (b[(QF_BITS + 8u) >> 3] >> (7u - ((QF_BITS + 8u) & 7u)) & 1u) return QU_PAD;', ''),
    ('pixel test off by a block', 'return row[x] < trow[x >> 4];', 'return row[x] < trow[(x >> 4) + 1u];'),
    ('row scan bypasses the pixel test', 'u32 v = x < d->w ? qd_bit(p, t, (u32)x) : prev ^ 1u;', 'u32 v = x < d->w ? p[x] < d->gthr : prev ^ 1u;'),
    ('merge ignores size', 'if (2 * dm > lim) continue;', 'if (2 * dm > 99 * lim) continue;'),
    ('mirror result dropped', 'if (r2 == QD_OK) { d->mirror = 1; r = QD_OK; }', 'if (r2 == QD_OK) { d->mirror = 1; }'),
    ('finder ratio loose', 'if (14u * r[2] < 4u * t || 14u * r[2] > 9u * t) return 0;', ''),
]


def mutate():
    global LIB
    src = U.QRDEC.read_text()
    survived = []
    quick = ['test_threshold_and_row_scan_white_box', 'test_byte_mode_only', 'test_finder_ratio', 'test_format_from_either_copy_and_ecc_l_only', 'test_rs_corrects_up_to_13_and_never_miscorrects_silently', 'test_sensorlab_check_plain_and_stock_convention',
             'test_unpack_rejects_crc_pad_version_chars', 'test_mirrored_symbol', 'test_degradations_meet_the_floor',
             'test_no_false_decodes_on_scenes_and_other_versions', 'test_every_preset_and_random_code_clean']
    for name, a, b in MUTANTS:
        assert src.count(a) == 1, name
        try:
            LIB = U.Lib(src.replace(a, b))
        except RuntimeError:
            print(f'BUILD-FAIL {name}')                      # not a catch: fix the mutant
            survived.append(name + ' (build)')
            continue
        suite = unittest.TestSuite(Unit(t) for t in quick)
        r = unittest.TextTestRunner(stream=open('/dev/null', 'w'), failfast=True).run(suite)
        caught = not r.wasSuccessful()
        print(f'{"caught  " if caught else "SURVIVED"} {name}')
        if not caught:
            survived.append(name)
    LIB = None
    return survived


if __name__ == '__main__':
    VAL.mkdir(parents=True, exist_ok=True)
    if '--rates' in sys.argv:
        out = rates(n_codes=int(sys.argv[sys.argv.index('--rates') + 1]) if len(sys.argv) > 2 else 60)
        (VAL / 'rates.json').write_text(json.dumps(out, indent=1))
        print(json.dumps(out, indent=1))
    elif '--count' in sys.argv:
        out = count()
        (VAL / 'instructions.json').write_text(json.dumps(out, indent=1))
        print(json.dumps(out['runs'], indent=1), out['image_bytes'])
    elif '--mutate' in sys.argv:
        s = mutate()
        print('survived:', s)
        sys.exit(1 if s else 0)
    else:
        unittest.main()
