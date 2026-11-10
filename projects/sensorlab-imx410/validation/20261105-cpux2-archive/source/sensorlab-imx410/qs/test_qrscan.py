"""SensorLab-IMX410 v0.7.32test: the QR scan hooks (notes/QR_SCAN_DESIGN.md §11), on the real SensorLab BIN in the
real v4 core with the real QSContainer (test_slqs.boot), against the REAL firmware functions:

  - FUN_c05c49f0 (the reader thread's decode wrapper) -> the decoder object's vtable word -> sl_qr_dec -> the real
    stock decoder (FUN_c05c5d00), then qrdec.c; a version-20 frame made by the real stock encoder (FUN_c05c5be8);
  - MenuQrCodeReadHandler v62 (messages, with the real stock settings parser FUN_c052bd38), v8 (OK), v12 (back),
    v72 / v73 (page entry / exit) through the vtable words SensorLab installs;
  - the apply / refuse rule: a code restores only when the restored selection gives back all 27 fields.

Only what is not the logic under test is stubbed (heap, timers, GUI objects, the LV executor, the menu base class);
the stubs record their calls.  No camera.

    cd projects/sensorlab-imx410/qs && python3 -B -m unittest test_qrscan
    python3 -B test_qrscan.py --mutate        # every mutant must fail a test
    SLQS_SCAN_ALL=1 ...                         # the round trip over all 837 site recipes (else a sample)
"""
import json
import os
import pathlib
import random
import struct
import sys
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_slqs as S                     # noqa: E402
import test_qrdec as D                    # noqa: E402

Q1 = S.Q1
URL = D.URL
if os.environ.get('SLQS_SCAN_CBUILD'):    # a prebuilt container (dir with build-*.json + fpSup/*.BIN), e.g. while its source moves
    _d = pathlib.Path(os.environ['SLQS_SCAN_CBUILD'])
    _info = json.loads(next(_d.glob('build-*.json')).read_text())
    Q1._built['c'] = (next((_d / 'fpSup').glob('QSContainer_*.BIN')).read_bytes(), _info)
SCAN_NAMES = ('d0 d1 d2 d3 d4 vt_ok vt_why on_page armed arms arm_refused disarms decodes ours ours_ok results '
              'sensorlab invalid accepted refused applied to_qs goes pending last last_at diff unpack_rc').split()
F_OFF = 4 * len(SCAN_NAMES)               # struct scan .f[27]
QRT_OBJ = 0xC3588D44                      # QrReadTh + 0x14: its XC_QrCode
QRT_OBJ_VT, QRT_VT_STOCK = 0xC3588D68, 0xC2DFE860
MQR_VT = 0xC0CD35C4
SLOT = dict(v8=MQR_VT + 0x20, v12=MQR_VT + 0x30, v62=MQR_VT + 0xF8, v72=MQR_VT + 0x120, v73=MQR_VT + 0x124)
STOCK = dict(v8=0xC0476C08, v12=0xC0476C70, v62=0xC0476DF0, v72=0xC0476B38, v73=0xC0476BB0)
DEC_WRAP = 0xC05C49F0                     # FUN_c05c49f0(obj, y8 image, log, timer, yuv)
ENCODE = 0xC05C5BE8                       # the stock encoder (version 20 only)
MOV_ACTIVE = 0xC35A952C                   # one of busy()'s recording flags

PROBES = {0xC052BD38: 'stock_parse'}     # address -> name: recorded on entry, run as is (the stock settings parser)
EXTRA = {}                                # address -> name: per-test stubs for fast()
STOCK_OK = [b'']
BUF = 0xC3F40000                          # test memory (the harness's FAKE page, above its own use)
IMG, HEAP, HEAP_END = BUF + 0x10000, BUF + 0x60000, BUF + 0xC0000   # image <= 256 KiB; heap: the decoder's 0x5C6A0
STUB = BUF + 0x8000                       # fake vtable stubs: STUB + 4 i = slot i of every fake object (0x200 slots)
DONE = BUF + 0x9F00                       # fast(): the return address it stops at
KEYDEV = 0xC3F40EE0                       # the fake key device singleton
GUI, UIOBJ, H_OBJ, HP, HQ, HBUF = BUF + 0x40, BUF + 0x80, BUF + 0x100, BUF + 0x180, BUF + 0x1C0, BUF + 0x400
FVT = BUF + 0x9000                        # the fake vtable: FVT + 4 i -> STUB + 4 i
RET_SLOT = {0x14: None, 0x24: None}       # slot byte offsets returning the UI object (filled below)

# the functions the tests stub (address -> name); everything else runs from the image
STUBS = {
    0xC001CF78: 'heap_of', 0xC001D1E8: 'alloc', 0xC001D2B8: 'free', 0xC0023730: 'timer', 0xC0023768: 'timer',
    0xC0023790: 'timer_text',
    0xC0489FE0: 'menu_buf', 0xC054DD38: 'gui_state', 0xC046C320: 'advance', 0xC0477108: 'req_read',
    0xC03714A8: 'set_read_mode', 0xC03714E0: 'req_read', 0xC0370CF8: 'lv',
    0xC02DBAF0: 'key_dev', 0xC02DBBE8: 'key_post',
    0xC00173E8: 'f173e8', 0xC0057AE8: 'settings', 0xC0057D38: 'session', 0xC0057DA0: 'session_end',
    0xC0059FB0: 'set_dc', 0xC005A078: 'set_e0', 0xC0058128: 'commit',
    # MenuHandlerSubBase (the menu framework under the handler): recorded, not run
    0xC046B3D8: 'base_v72', 0xC046B4C0: 'base_v73', 0xC046B7C8: 'base_v8', 0xC046BA68: 'base_v12', 0xC046C118: 'base_v62',
}


class ScanCam(Q1.Cam):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.scalls = []
        self.heap = HEAP
        self.ret = {}
        self.active = False                                 # the stubs only inside this file's own calls
        self.answer = {}                                    # probe name -> a forced return value

    def _hook(self, mu, addr, size, data):
        if self.active and addr in PROBES:                  # recorded (name, r0), run as is -- or answered
            from unicorn.arm_const import UC_ARM_REG_R0
            self.scalls.append((PROBES[addr], self.r(UC_ARM_REG_R0), 0, 0))
            if PROBES[addr] in self.answer:
                return self._ret(self.answer[PROBES[addr]])
        name = STUBS.get(addr) if self.active else None
        if name is None and STUB <= addr < STUB + 0x800:
            name = 'slot%x' % (addr - STUB)
        if name is None:
            return super()._hook(mu, addr, size, data)
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2
        r0, r1, r2 = (self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
        self.scalls.append((name, r0, r1, r2))
        if name == 'alloc':                                 # (heap, size, align, out)
            a = (self.heap + 63) & ~63
            self.heap = a + r1
            assert self.heap < HEAP_END, 'test heap exhausted'
            mu.mem_write(a, bytes(min(r1, 0x100)))
            return self._ret(a)
        if name == 'timer_text':
            return self._ret(BUF)
        if name == 'gui_state':
            return self._ret(GUI)
        if name == 'lv':
            return self._ret(BUF + 0x20)
        if name == 'key_dev':
            return self._ret(KEYDEV)
        if name.startswith('slot') and int(name[4:], 16) in RET_SLOT:
            return self._ret(UIOBJ)
        return self._ret(self.ret.get(name, 0 if name != 'heap_of' else 1))


def boot(**kw):
    with patch.object(Q1, 'Cam', ScanCam):
        c = S.boot(**kw)
    stub_code(c)
    return c


def stub_code(c):
    """fake objects: every vtable slot i -> STUB + 4 i (bx lr); GUI / UI objects carry FVT"""
    c.mu.mem_write(STUB, struct.pack('<I', 0xE12FFF1E) * 0x200)
    c.mu.mem_write(DONE, struct.pack('<I', 0xE12FFF1E))
    c.mu.mem_write(FVT, b''.join(struct.pack('<I', STUB + 4 * i) for i in range(0x200)))
    for o in (GUI, UIOBJ, HQ):
        c.put(o, FVT)


def scan(c):
    a = S.sqt(c, 40)
    w = struct.unpack('<%dI' % (len(SCAN_NAMES) + 27), bytes(c.mu.mem_read(a, 4 * (len(SCAN_NAMES) + 27))))
    d = dict(zip(SCAN_NAMES, w))
    d['f'] = list(w[len(SCAN_NAMES):])
    d['addr'] = a
    return d


def fields_now(c):
    S.sqt(c, 43, BUF + 0x200)
    return list(struct.unpack('<27I', bytes(c.mu.mem_read(BUF + 0x200, 108))))


def restore(c, f, keep):
    c.mu.mem_write(BUF + 0x300, struct.pack('<27I', *f))
    r = S.sqt(c, 41, BUF + 0x300, keep) & 0xFFFFFFFF
    return r & 1, r >> 1


def pack(f):
    return D.lib().pack(f)


def site_inputs(limit=None, seed=4):
    """(cell, recipe) inputs from the site data: DC, RES, the recipe's own maximum rate, its parameters"""
    import ast
    import re
    site = HERE.parent / 'site'
    sys.path.insert(0, str(site))
    import build_site as BSITE
    html = BSITE.SOURCE.read_text()
    logic = html.split('<script>\n', 1)[1].split('// ---- render', 1)[0]
    data = json.loads((BSITE.PREVIEW / 'fps_data.js').read_text().split('const FPSDATA = ', 1)[1].rstrip(';\n'))
    dcs = {n: (w, h) for n, w, h in ast.literal_eval(re.search(r'const DCS = (\[.*?\]);', logic)[1])}
    out = []
    for cell, recipes in data['cases'].items():
        dc, wh = cell.split(':')
        rw, rh = map(int, wh.split('x'))
        dcw, dch = dcs[dc]
        for hm, lo, _n, r in recipes:
            f = [1, dcw, dch, rw, rh, 30, lo, hm, {11: 0, 12: 1, 14: 2}[r['ad']], r['mh'], r['mv'], r['hbin'],
                 r['vbin'], 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, r['scw'], r['sch'], 0, 0]
            out.append((cell, f))
    if limit:
        out = random.Random(seed).sample(out, limit)
    return out


def stock_v20(c, data):
    """the stock encoder (version 20, byte, ECC L, x1, Y8) in this camera -> a 97 x 97 module image (0 dark)"""
    work, dat, dst, prm = BUF + 0x52000, BUF + 0x5C000, BUF + 0x5D000, BUF + 0x5F800
    enc = bytes((b - i) & 0xFF for i, b in enumerate(data))  # the encoder adds +i: undo it, phones read the text
    c.mu.mem_write(dat, enc)
    c.mu.mem_write(dst, b'\xff' * 97 * 97)
    c.mu.mem_write(prm, struct.pack('<B3xIIIIIIIII', 0x14, 2, 1, work, len(enc), dat, 1, 1, 97, dst))
    fast(c, ENCODE, r0=prm)                                 # (the matrix is checked by decoding it)
    import numpy as np
    return np.frombuffer(bytes(c.mu.mem_read(dst, 97 * 97)), np.uint8).reshape(97, 97)


def y8_frame(c, kind, url, rng):
    """the reader's input: 512 x 512 Y8 (kind 'v5': ours rendered; 'v20': the stock encoder's matrix, 4 px/module)"""
    import numpy as np
    if kind == 'v5':
        mat, _fn, _m = D.lib().encode(url)
        return D.render(mat, rng, scale=5)
    m = stock_v20(c, url.encode())
    img = np.full((512, 512), 255, np.uint8)
    big = np.kron(m, np.ones((5, 5), np.uint8))
    o = (512 - big.shape[0]) // 2
    img[o:o + big.shape[0], o:o + big.shape[1]] = big
    return img


def decode_frame(c, img):
    """FUN_c05c49f0 on the reader thread's decoder object with this Y8 frame -> (result 0/1/2, bytes as delivered)"""
    dst = BUF + 0x50000
    vt = c.w(QRT_OBJ_VT) or QRT_VT_STOCK                   # = QRT_OBJ + 0x24: armed or not, as the test left it
    c.mu.mem_write(QRT_OBJ, bytes(0x28))
    c.put(QRT_OBJ + 0x18, dst)                              # the destination buffer (already allocated)
    c.put(QRT_OBJ + 0x24, vt)
    c.mu.mem_write(dst, bytes(0x100))
    c.mu.mem_write(IMG, img.tobytes())
    desc = BUF + 0x3C0
    c.mu.mem_write(desc, struct.pack('<8I', img.shape[1], img.shape[0], 0, 0, 0, 0, 0, IMG))
    c.heap = HEAP
    fast(c, DEC_WRAP, r0=QRT_OBJ, r1=desc, r2=0, r3=0, stack=(0,))   # 5th arg (yuv desc) 0
    res, n = c.w(QRT_OBJ + 4), c.w(QRT_OBJ + 0x1C)
    return res, bytes(c.mu.mem_read(dst, n)) if n < 0x400 else b''


def handler(c, phase=1, done=0):
    """a fake MenuQrCodeReadHandler object: vptr = the real vtable, +0x10 -> P {Q, _, buf, cap}"""
    c.mu.mem_write(H_OBJ, bytes(0x40))
    c.put(H_OBJ, MQR_VT)
    c.put(H_OBJ + 0x10, HP)
    c.put(HP, HQ)
    c.put(HP + 8, HBUF)
    c.put(HP + 0xC, 0x35A)
    c.put(H_OBJ + 0x30, phase)
    c.mu.mem_write(H_OBJ + 0x2C, bytes([done, 1, 1]))
    return H_OBJ


def result_msg(c, data):
    """the reader's result message (QrCodeReadThread::v1 -> v62): [0] 2, [3] 0, [5] -> {0 ok, rect, data, len}"""
    res, dat, msg = BUF + 0x3000, BUF + 0x3100, BUF + 0x3400
    c.mu.mem_write(dat, data)
    c.mu.mem_write(res, struct.pack('<7I', 0, 10, 20, 100, 100, dat, len(data)))
    c.mu.mem_write(msg, struct.pack('<6I', 2, 0, 0, 0, 7, res))
    return msg


def fast(c, pc, r0=0, r1=0, r2=0, r3=0, stack=()):
    """pc on a copy of the camera with code hooks ONLY on the stubbed addresses (the harness hooks every ROM
    instruction in Python: the stock decoder / encoder, millions of instructions, run natively here), then the
    camera's RAM is copied back (firmware BSS, the sup blocks, the test page)"""
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, \
        UC_ARM_REG_LR, UC_ARM_REG_PC
    src = c.mu
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    from unicorn.arm_const import UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC
    mu.reg_write(UC_ARM_REG_C1_C0_2, mu.reg_read(UC_ARM_REG_C1_C0_2) | (0xF << 20))   # VFP on (the decoder uses it)
    mu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
    regions = [(b, e - b + 1) for b, e, _p in src.mem_regions()]
    for b, n in regions:
        mu.mem_map(b, n)
        mu.mem_write(b, bytes(src.mem_read(b, n)))
    done = DONE                                             # bx lr there; the run stops on reaching it

    def hook(m, addr, size, _d):
        rr = [m.reg_read(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
        if addr in PROBES:                                  # recorded, not stubbed
            c.scalls.append((PROBES[addr], *rr))
            return
        name = STUBS.get(addr) or EXTRA.get(addr) or 'slot%x' % (addr - STUB)
        c.scalls.append((name, *rr))
        v = 0 if name != 'heap_of' else 1
        if name == 'alloc':
            a = (c.heap + 63) & ~63
            c.heap = a + rr[1]
            assert c.heap < HEAP_END, 'test heap exhausted'
            v = a
        elif name == 'gui_state':
            v = GUI
        elif name == 'lv':
            v = BUF + 0x20
        elif name.startswith('slot') and int(name[4:], 16) in RET_SLOT:
            v = UIOBJ
        elif name == 'timer_text':
            v = BUF
        elif name == 'stock_decode_ok':                     # XC_QrCode::v1 as a stock success: bytes in, length set
            p = rr[2]
            data = STOCK_OK[0]
            m.mem_write(struct.unpack('<I', m.mem_read(p + 0x14, 4))[0], data)
            m.mem_write(p + 0x10, struct.pack('<I', len(data)))
            v = 0
        m.reg_write(UC_ARM_REG_R0, v)
        m.reg_write(UC_ARM_REG_PC, m.reg_read(UC_ARM_REG_LR))
    for a in list(STUBS) + list(PROBES) + list(EXTRA) + [STUB + 4 * i for i in range(0x200)]:
        mu.hook_add(UC_HOOK_CODE, hook, begin=a, end=a)
    sp = 0xC3E80000
    mu.mem_write(sp, b''.join(struct.pack('<I', w) for w in stack))
    for reg, v in ((UC_ARM_REG_R0, r0), (UC_ARM_REG_R1, r1), (UC_ARM_REG_R2, r2), (UC_ARM_REG_R3, r3),
                   (UC_ARM_REG_SP, sp), (UC_ARM_REG_LR, done)):
        mu.reg_write(reg, v & 0xFFFFFFFF)
    mu.emu_start(pc, done, count=400_000_000)
    assert mu.reg_read(UC_ARM_REG_PC) == done, hex(mu.reg_read(UC_ARM_REG_PC))
    for b, n in regions:
        if b >= 0xC3000000:
            src.mem_write(b, bytes(mu.mem_read(b, n)))
    return mu.reg_read(UC_ARM_REG_R0)


def fw(c, pc, **regs):
    """a firmware / SensorLab call with the stubs active"""
    c.active = True
    try:
        return c.call(pc, **regs)[0]
    finally:
        c.active = False


def call_slot(c, slot, h, arg=0):
    c.scalls.clear()
    return fw(c, c.w(SLOT[slot]), r0=h, r1=arg)


def gui_states(c):
    """the page states shown: GUI vt + 0xC (obj, name)"""
    return [c.cstr(r1) for n, r0, r1, _r2 in c.scalls if n == 'slot%x' % 0xC and r0 == GUI]


def stock_bytes(data):
    return bytes((b - i) & 0xFF for i, b in enumerate(data))


@S.SKIP
class Install(unittest.TestCase):
    def test_the_three_handler_slots_and_the_qr_tile(self):
        c = boot()
        sc = scan(c)
        self.assertEqual((sc['vt_ok'], sc['vt_why']), (1, 0))
        for k in ('v62', 'v72', 'v73'):
            self.assertEqual(c.w(SLOT[k]), S.fn_addr(c, 'sl_mqr_' + k) | 1, k)
        for k in ('v8', 'v12'):                                                # OK / back stay stock (v0.7.33test)
            self.assertEqual(c.w(SLOT[k]), STOCK[k], k)
        self.assertEqual(sc['d3'], S.fn_addr(c, 'sl_qr_dec') | 1)
        self.assertEqual((sc['d0'], sc['d1'], sc['d2'], sc['d4']), (0, 0xC2DFE88C, 0xC05C4640, 1))
        # the stock vtable these four words came from: the dtor / RTTI / decode words are the image's
        self.assertEqual([c.w(QRT_VT_STOCK + 4 * i) for i in range(5)], [0, 0xC2DFE88C, 0xC05C4640, 0xC05C4E50, 1])

    def test_not_stock_at_entry_installs_nothing(self):
        def prep(cam):
            cam.put(SLOT['v62'], 0xC0001235)
        c = boot(prepare=prep)
        sc = scan(c)
        self.assertEqual((sc['vt_ok'], sc['vt_why']), (0, 1))     # v62 is the first slot
        self.assertEqual(c.w(SLOT['v72']), STOCK['v72'])
        self.assertEqual(c.w(SLOT['v62']), 0xC0001235)


class ResyncOff(unittest.TestCase):
    def test_the_product_build_has_the_rec_start_resync_off(self):
        """v0.7.32test: AP_RESYNC defaults to 0 in ap.c and only the apply tests' build sets it (validation/
        20261104-resync-review); the SensorLab build passes no such define"""
        import build_slqs as BS
        ap = (HERE.parent / 'apply' / 'ap.c').read_text()
        self.assertIn('#ifndef AP_RESYNC\n#define AP_RESYNC 0', ap)
        self.assertIn('if (!AP_RESYNC) { A->rs_skips++; A->rs_last = 3u; return; }', ap)
        src = (HERE / 'build_slqs.py').read_text() + ' '.join(BS.B.CFLAGS)
        self.assertNotIn('AP_RESYNC', src)


@S.SKIP
class Restore(unittest.TestCase):
    """the apply / refuse rule: inputs -> the camera's own code -> restored on a fresh selection = the same 27"""

    def test_round_trip_and_refusals(self):
        c = boot()
        cases = site_inputs(None if os.environ.get('SLQS_SCAN_ALL') else 40)
        base = fields_now(c)
        n = 0
        for cell, f in cases:
            restore(c, base, 2)                                 # a fresh selection first
            restore(c, f, 2)                                    # the inputs (derived fields ignored)
            code = fields_now(c)
            self.assertEqual((code[1:5], code[8:13]), (f[1:5], f[8:13]), cell)   # the inputs were taken
            restore(c, base, 2)
            before = fields_now(c)
            self.assertNotEqual(before, code, cell) if code[1:5] != base[1:5] else None
            ok, diff = restore(c, code, 0)                      # check only: nothing changes
            self.assertEqual((ok, diff), (1, 0), (cell, f, code))
            self.assertEqual(fields_now(c), before)
            ok, diff = restore(c, code, 1)
            self.assertEqual((ok, fields_now(c)), (1, code), cell)
            n += 1
        self.assertGreaterEqual(n, 40)

    def test_each_derived_field_mismatch_is_refused_and_named(self):
        c = boot()
        code = fields_now(c)
        before = list(code)
        for i, d in ((6, 1), (7, 1), (13, 1), (18, 16), (19, 10), (20, 1), (25, 16), (26, 2), (21, 1)):
            f = list(code)
            f[i] += d
            ok, diff = restore(c, f, 1)
            self.assertEqual(ok, 0, i)
            self.assertTrue(diff >> i & 1, (i, bin(diff)))
            self.assertEqual(fields_now(c), before, i)         # the selection is put back
        for _cell, other in site_inputs(6, 21):                 # another DC / RES / recipe, this code's derived fields
            f = list(code)
            f[1:5], f[8:13], f[23:25] = other[1:5], other[8:13], other[23:25]
            ok, diff = restore(c, f, 1)
            if ok:
                continue                                        # (the same derived values by chance)
            self.assertEqual(fields_now(c), before)            # refused: nothing kept


@S.SKIP
class Decoder(unittest.TestCase):
    """FUN_c05c49f0 (real) -> the object's vtable word -> sl_qr_dec -> the real stock decoder, then ours"""

    def arm(self, c):
        c.put(QRT_OBJ_VT, QRT_VT_STOCK)
        call_slot(c, 'v72', handler(c, phase=0))
        self.assertEqual(c.w(QRT_OBJ_VT), scan(c)['addr'])

    def test_v5_ours_after_the_stock_miss_in_the_stock_convention(self):
        c = boot()
        self.arm(c)
        code = pack(D.random_fields(1, 3)[0])
        img = y8_frame(c, 'v5', URL + code, random.Random(3))
        res, data = decode_frame(c, img)
        sc = scan(c)
        self.assertEqual((res, sc['decodes'], sc['ours'], sc['ours_ok']), (0, 1, 1, 1))
        self.assertEqual(data, stock_bytes((URL + code).encode()))   # byte - i, as the stock decoder delivers

    def test_a_stock_success_is_passed_through_and_ours_never_runs(self):
        """the stock decoder (XC_QrCode::v1) does not decode in this emulation even on its own encoder's version-20
        output (finders found, FUN_c05cb960 sampling fails: runtime state the firmware builds is missing here [I]), so a
        stock success is its stub: bytes + length, return 0.  Ours must not run and the stock bytes must arrive."""
        c = boot()
        self.arm(c)
        STOCK_OK[0] = stock_bytes(b'C43 stock settings payload')
        EXTRA[0xC05C4E50] = 'stock_decode_ok'
        try:
            res, data = decode_frame(c, y8_frame(c, 'v5', URL + pack(D.random_fields(1, 4)[0]), random.Random(4)))
        finally:
            EXTRA.clear()
        sc = scan(c)
        self.assertEqual((res, sc['decodes'], sc['ours']), (0, 1, 0))
        self.assertEqual(data, STOCK_OK[0])

    def test_the_stock_encoder_v20_is_not_ours(self):
        """a version-20 symbol (the stock encoder, this image) is never read by our decoder: stock-only result"""
        c = boot()
        self.arm(c)
        url = URL + pack(D.random_fields(1, 4)[0])
        res, _data = decode_frame(c, y8_frame(c, 'v20', url, random.Random(4)))
        sc = scan(c)
        self.assertEqual((res, sc['decodes'], sc['ours'], sc['ours_ok']), (1, 1, 1, 0))

    def test_disarmed_and_recording_are_stock_only(self):
        c = boot()
        code = pack(D.random_fields(1, 5)[0])
        img = y8_frame(c, 'v5', URL + code, random.Random(5))
        c.put(QRT_OBJ_VT, QRT_VT_STOCK)                         # never armed: the stock decoder alone
        self.assertNotEqual(decode_frame(c, img)[0], 0)
        self.arm(c)
        c.mu.mem_write(MOV_ACTIVE, b'\x01')
        self.assertNotEqual(decode_frame(c, img)[0], 0)
        self.assertEqual(scan(c)['ours'], 0)
        c.mu.mem_write(MOV_ACTIVE, b'\x00')
        self.assertEqual(decode_frame(c, img)[0], 0)


@S.SKIP
class Page(unittest.TestCase):
    """the real MenuQrCodeReadHandler slots through SensorLab's words"""

    def test_entry_arms_only_over_the_stock_word_exit_and_leave_restore(self):
        c = boot()
        c.put(QRT_OBJ_VT, QRT_VT_STOCK)
        call_slot(c, 'v72', handler(c, phase=0))
        sc = scan(c)
        self.assertEqual((sc['on_page'], sc['armed'], sc['arms'], c.w(QRT_OBJ_VT)), (1, 1, 1, sc['addr']))
        self.assertIn('session', [n for n, *_ in c.scalls])      # the stock entry ran first
        call_slot(c, 'v73', handler(c, phase=1))
        sc = scan(c)
        self.assertEqual((sc['on_page'], sc['armed'], c.w(QRT_OBJ_VT)), (0, 0, QRT_VT_STOCK))
        self.assertIn(('set_read_mode', BUF + 0x20, 0, 0), [x[:4] for x in c.scalls])   # stock exit: read mode off
        c.put(QRT_OBJ_VT, 0x12345678)                          # someone else's word: never armed, never touched
        call_slot(c, 'v72', handler(c, phase=0))
        self.assertEqual((scan(c)['arm_refused'], c.w(QRT_OBJ_VT)), (1, 0x12345678))
        call_slot(c, 'v73', handler(c, phase=1))
        self.assertEqual(c.w(QRT_OBJ_VT), 0x12345678)
        c.put(QRT_OBJ_VT, QRT_VT_STOCK)                         # armed, then a layout load off the page: put back
        call_slot(c, 'v72', handler(c, phase=0))
        S.sqt(c, 40)
        c.put(scan(c)['addr'] + 4 * SCAN_NAMES.index('on_page'), 0)
        c.layout()
        self.assertEqual(c.w(QRT_OBJ_VT), QRT_VT_STOCK)

    def run_v62(self, c, data, wrapper=True, h=None):
        h = h or handler(c)
        msg = result_msg(c, data)
        c.scalls.clear()
        c.heap = HEAP                                       # the same heap addresses for the stock / wrapper comparison
        fw(c, c.w(SLOT['v62']) if wrapper else STOCK['v62'], r0=h, r1=msg)
        return h, list(c.scalls)

    @staticmethod
    def states(c, calls):
        return [c.cstr(r1) for n, r0, r1, _ in calls if n == 'slot%x' % 0xC and r0 == GUI]

    def test_the_unwrapped_stock_handler_takes_a_sensorlab_url_as_settings(self):
        """the v0.7.32test live bug on the real handler: the stock parser ACCEPTED our URL on the camera (its name line
        showed URL[i] - i).  In emulation the parser (FUN_c052bd38, fake settings object) rejects it, so its answer is
        forced to the live one; the page then goes to "ProcessingComplete" -- whose page data runs a 2 s timer to
        Y5_ReadQR_SaveSettings (Y5_ReadQR object 4262)"""
        c = boot()
        c.answer = {'stock_parse': 1}
        data = stock_bytes((URL + pack(fields_now(c))).encode())
        h, calls = self.run_v62(c, data, wrapper=False)
        self.assertIn('stock_parse', [n for n, *_ in calls])
        self.assertEqual(self.states(c, calls), ['ProcessingComplete'])
        self.assertEqual(c.mu.mem_read(h + 0x2C, 1)[0], 1)

    def test_ours_applies_and_leaves_without_complete_save_or_parse(self):
        c = boot()
        c.answer = {'stock_parse': 1}                            # as on the camera: the parser would take it
        restore(c, site_inputs(1, 9)[0][1], 2)
        code_f = fields_now(c)
        restore(c, site_inputs(1, 10)[0][1], 2)
        self.assertNotEqual(fields_now(c), code_f)
        pushes = S.sqt(c, 20)                                    # change events handed to the apply unit
        h, calls = self.run_v62(c, stock_bytes((URL + pack(code_f)).encode()))
        sc = scan(c)
        self.assertEqual((sc['sensorlab'], sc['accepted'], sc['applied'], sc['last']), (1, 1, 1, 1))
        self.assertEqual(fields_now(c), code_f)
        self.assertEqual(S.sqt(c, 20), pushes + 1)               # one sq_push
        names = [n for n, *_ in calls]
        self.assertNotIn('stock_parse', names)                   # never seen as a settings payload
        self.assertEqual(self.states(c, calls), [])              # no "ProcessingComplete": no timer, no save page
        self.assertEqual(c.mu.mem_read(h + 0x2C, 1)[0], 0)
        self.assertEqual(names.count('base_v62'), 1)             # the base class still sees the message
        self.assertNotIn('advance', names)
        # v0.7.34test: to the QS -- read mode off, done, our word back, one QS press + release; never Down
        self.assertIn(('set_read_mode', BUF + 0x20, 0), [x[:3] for x in calls])
        self.assertEqual(c.w(h + 0x30), 3)
        self.assertEqual([r1 for n, r0, r1, _ in calls if n == 'key_post'], [0x22, 0x23])
        self.assertTrue(all(r0 == KEYDEV for n, r0, *_ in calls if n == 'key_post'))
        self.assertNotIn('base_v12', names)                      # the Down key (-> R_FileSelect) is never sent
        self.assertEqual(scan(c)['to_qs'], 1)
        # the reader's end message that follows (phase 3): the stock handler replays nothing
        end = BUF + 0x3480
        c.mu.mem_write(end, struct.pack('<6I', 2, 0, 0, 3, 8, 0))
        c.scalls.clear()
        fw(c, c.w(SLOT['v62']), r0=h, r1=end)
        self.assertNotIn('base_v12', [n for n, *_ in c.scalls])
        self.assertNotIn('key_post', [n for n, *_ in c.scalls])

    def test_the_v033_exit_replayed_down_into_r_fileselect(self):
        """the live SS3154 path on the real handler: phase 2 + the end message -> MenuHandlerSubBase::v12 (Down)"""
        c = boot()
        h = handler(c, phase=2)
        end = BUF + 0x3480
        c.mu.mem_write(end, struct.pack('<6I', 2, 0, 0, 3, 8, 0))
        c.scalls.clear()
        fw(c, STOCK['v62'], r0=h, r1=end)
        self.assertIn('base_v12', [n for n, *_ in c.scalls])
        self.assertEqual(c.w(h + 0x30), 3)

    def test_accepted_after_entry_restores_the_decoder_word(self):
        c = boot()
        c.put(QRT_OBJ_VT, QRT_VT_STOCK)
        h = handler(c, phase=0)
        call_slot(c, 'v72', h)
        self.assertEqual(c.w(QRT_OBJ_VT), scan(c)['addr'])
        c.answer = {'stock_parse': 1}
        c.put(h + 0x30, 1)
        self.run_v62(c, stock_bytes((URL + pack(fields_now(c))).encode()), h=h)
        self.assertEqual(c.w(QRT_OBJ_VT), QRT_VT_STOCK)
        self.assertEqual(scan(c)['armed'], 0)

    def test_refused_code_is_the_stock_incompatible_unparsed_and_named(self):
        c = boot()
        c.answer = {'stock_parse': 1}
        before = fields_now(c)
        f = list(before)
        f[6] += 1                                               # VMAX
        h, calls = self.run_v62(c, stock_bytes((URL + pack(f)).encode()))
        sc = scan(c)
        self.assertEqual((sc['sensorlab'], sc['refused'], sc['applied'], sc['last']), (1, 1, 0, 2))
        self.assertTrue(sc['diff'] >> 6 & 1)
        self.assertEqual(self.states(c, calls), ['ProcessingErrorNotSupported'])
        self.assertNotIn('stock_parse', [n for n, *_ in calls])  # no settings payload: nothing to save
        self.assertEqual(c.mu.mem_read(h + 0x2C, 1)[0], 0)
        self.assertEqual(c.w(BUF + 0x3000), 0)                  # the reader's result word put back
        self.assertEqual(fields_now(c), before)

    def test_a_non_sensorlab_url_still_completes_as_stock(self):
        """SIGMA's path for anything that parses (here an unrelated URL): "ProcessingComplete" -> its save page"""
        c = boot()
        c.answer = {'stock_parse': 1}                            # an accepted payload (SIGMA's own code, or any URL)
        data = stock_bytes(('https://example.org/settings/' + 'x' * 58).encode())
        h, calls = self.run_v62(c, data)
        self.assertIn('stock_parse', [n for n, *_ in calls])
        self.assertEqual(self.states(c, calls), ['ProcessingComplete'])
        self.assertEqual(scan(c)['sensorlab'], 0)

    def test_anything_else_is_exactly_the_stock_handler(self):
        c = boot()
        for data in (b'C43' + bytes(60), stock_bytes(b'https://example.com/#abc'),
                     stock_bytes((URL + 'A' * 36).encode()), b'\x00' * 87):
            _h, ours = self.run_v62(c, data)
            _h, stock = self.run_v62(c, data, wrapper=False)
            self.assertEqual(ours, stock, data[:12])
        sc = scan(c)
        self.assertEqual((sc['sensorlab'], sc['applied']), (0, 0))

    def test_invalid_sensorlab_code_and_recording(self):
        c = boot()
        code = pack(fields_now(c))
        bad = code[:-1] + D.B64U[D.B64U.index(code[-1]) ^ 2]       # a CRC bit
        self.run_v62(c, stock_bytes((URL + bad).encode()))
        sc = scan(c)
        self.assertEqual((sc['invalid'], sc['last'], sc['pending']), (1, 3, 0))
        c.mu.mem_write(MOV_ACTIVE, b'\x01')
        _h, ours = self.run_v62(c, stock_bytes((URL + code).encode()))
        _h, stock = self.run_v62(c, stock_bytes((URL + code).encode()), wrapper=False)
        self.assertEqual((ours, scan(c)['sensorlab']), (stock, 1))


class Firmware(unittest.TestCase):
    """the data behind scan_to_qs, read from the image (no emulation)"""
    ROOT = S.ROOT

    def test_qs_key_codes_from_the_shell_key_table(self):
        seg1 = (self.ROOT / 'out' / 'seg1_c2ef6e00.bin').read_bytes()   # the initialised data (runtime 0xC2EF6E00)
        img = (self.ROOT / 'out' / 'MAIN_c0000000.bin').read_bytes()
        w = lambda a: struct.unpack_from('<I', seg1, a - 0xC2EF6E00)[0]
        name = lambda a: img[a - 0xC0000000:img.index(b'\0', a - 0xC0000000)].decode()
        table = {name(w(0xC2F205C0 + 12 * i)): w(0xC2F205C0 + 12 * i + 4) for i in range(0x32)}
        self.assertEqual((table['QSON'], table['QSOFF']), (0x22, 0x23))
        gpio = [[w(0xC2F1CE68 + 40 * i + 4 * k) for k in range(10)] for i in range(8)]
        self.assertIn([table['OKON'], table['OKOFF']], [g[3:5] for g in gpio])     # the GPIO keys share the codes

    def test_the_read_page_qs_key_goes_to_qs_and_down_to_file_select(self):
        import importlib.util
        tools = self.ROOT / 'research' / 'ui' / 'tools'
        spec = importlib.util.spec_from_file_location('nbu_components', tools / 'nbu_components.py')
        m = importlib.util.module_from_spec(spec)
        argv, sys.argv = sys.argv, ['x']
        try:
            spec.loader.exec_module(m)
        finally:
            sys.argv = argv
        seg0 = m.SEG0.read_bytes()
        pool = seg0[m.POOL - 0xC0000000:][:m.POOL_LEN]
        objs, comps, _ = m.walk(seg0[0xC2D19243 - 0xC0000000:0xC2D1F67A - 0xC0000000], pool, m.BM.load_property_schemas(seg0))
        seq = [(objs[o][0], comp, f) for _off, o, _t, comp, _i, f in comps]
        def after(obj, args):
            out, on = [], False
            for name, comp, f in seq:
                if name != obj:
                    continue
                if comp == 'keyEvent':
                    on = f.get('args') == args
                    continue
                if on and comp == 'controlAppState' and f.get('sync-request'):
                    out.append(f['sync-request'])
            return out
        self.assertEqual(after('CommonSystemKeyEvent', '00000014'), ['QS'])       # QS key -> "QS"
        self.assertEqual(after('KeyEvent', '00000028'), ['R_FileSelect'])          # Down -> playback-image read


@S.SKIP
class Tile(unittest.TestCase):
    def test_ael_go_needs_api7_and_no_recording(self):
        c = boot()
        go = S.fn_addr(c, 'sq_qr_go')
        api = c.call(S.fn_addr(c, 'sq_test') & ~1, r0=44, thumb=True)[0]
        self.assertTrue(api)
        ver = c.w(api + 4)
        self.assertEqual(ver, 8)                                # the container built from projects/qs-container (v0.3.8)
        c.put(api + 4, 6)
        self.assertEqual(c.call(go & ~1, r0=0, r1=1, thumb=True)[0], 0)
        c.put(api + 4, 7)
        self.assertEqual(c.call(go & ~1, r0=0, r1=1, thumb=True)[0], 1)
        self.assertEqual(c.call(go & ~1, r0=0, r1=0, thumb=True)[0], 0)
        c.mu.mem_write(MOV_ACTIVE, b'\x01')
        self.assertEqual(c.call(go & ~1, r0=0, r1=1, thumb=True)[0], 0)
        c.put(api + 4, ver)

    def test_the_dial_hint_flag_only_where_the_dials_act(self):
        """v0.7.36test: QSC_F_DIAL_HINT (container API 8) on DC, RES, FPS, RECIPE (they adjust); not FORMAT, MB/s, QR"""
        c = boot()
        f0 = S.sqt(c, 45) - 6 * 60                             # st->f[F_QR] - F_QR * sizeof(struct qsc_func)
        flags = [c.w(f0 + 60 * i + 24) for i in range(7)]     # DC RES FPS RECIPE FORMAT MBPS QR
        adjust = [c.w(f0 + 60 * i + 32) for i in range(7)]
        self.assertEqual([bool(x & 0x1000) for x in flags], [True, True, True, True, False, False, False])
        self.assertEqual([bool(a) for a in adjust], [True, True, True, True, False, False, False])

    def test_the_qr_function_asks_for_the_read_page(self):
        c = boot()
        t = S.sqt(c, 45)                                       # the QR function's struct qsc_func
        flags = c.w(t + 24)                                     # qsc_func.flags
        self.assertEqual((flags >> 8) & 0xF, 1)                 # QSC_F_GO(QSC_GO_READQR)
        self.assertEqual(c.w(t + 56), S.fn_addr(c, 'sq_qr_go') | 1)        # qsc_func.fine


MUTANTS = [
    ('qr_restore keeps on a mismatch', 'if ((*diff && keep != 2u) || !keep) {', 'if (!keep) {'),
    ('qr_restore compares nothing', 'for (u32 i = 0; i < N_QF; i++) if (!ok || g[i] != f[i]) *diff |= 1u << i;',
     'for (u32 i = 0; i < N_QF; i++) if (!ok && g[i] != f[i]) *diff |= 1u << i;'),
    ('scan_result: no restore check', 'if (!qr_restore(st, sc->f, &sc->diff, 0)) { sc->refused++; sc->last = 2; return 2; }', ''),
    ('arm over any word', 'if (q->n != QR_N || W(QRT_OBJ_VT) != QRT_VT_STOCK) { sc->arm_refused++; return; }',
     'if (q->n != QR_N) { sc->arm_refused++; return; }'),
    ('exit does not disarm', 'if (st) { scan_disarm(st); st->scan.on_page = 0; st->scan.pending = 0; }',
     'if (st) { st->scan.on_page = 0; st->scan.pending = 0; }'),
    ('leave does not disarm', '    if (!st->scan.on_page) scan_disarm(st);', ''),
    ('ours before the stock decoder', 'if (!r || busy() || st->qr.n != QR_N) return r;', 'if (busy() || st->qr.n != QR_N) return r;'),
    ('plain bytes back', '    qrd_to_stock(dst, len);\n', ''),
    ('decoder ignores recording', 'if (!r || busy() || st->qr.n != QR_N) return r;', 'if (!r || st->qr.n != QR_N) return r;'),
    ('accepted goes to the stock handler', '        ((void (*)(u32, u32))MQR_BASE_V62)(h, msg);       /* what the stock v62 ends with */',
     '        ((void (*)(u32, u32))MQR_S_V62)(h, msg);       /* what the stock v62 ends with */'),
    ('accepted skips the base class', '        ((void (*)(u32, u32))MQR_BASE_V62)(h, msg);       /* what the stock v62 ends with */\n', ''),
    ('refused handed over with its real result', '        W(res) = 2u;\n', ''),
    ('refused result word not put back', '        W(res) = 0u;\n', ''),
    ('refused also applies', 'if (ours == 2u) {                                   /* the stock', 'if (ours == 2u && 0) {                                   /* the stock'),
    ('v62 ignores recording', 'if (st && !busy() && W(msg) == 2u', 'if (st && W(msg) == 2u'),
    ('accepted does not push', 'st->dirty = 1; sq_push(st); }\n        else { sc->refused++;', 'st->dirty = 1; }\n        else { sc->refused++;'),
    ('accepted does not leave', '        scan_to_qs(st, h);\n', ''),
    ('to QS: reader left on', '    ((void (*)(u32, u32))LV_READ_MODE)(((u32 (*)(void))LV_EXE)(), 0);\n', ''),
    ('to QS: phase left stopping', '    W(h + 0x30u) = MQR_PHASE_END;\n', '    W(h + 0x30u) = 2u;\n'),
    ('to QS: word not put back', '    scan_disarm(st);\n    u32 dev', '    u32 dev'),
    ('to QS: another key', '#define KEY_QS_ON     0x22u', '#define KEY_QS_ON     0x24u'),
    ('to QS: no release', '    ((void (*)(u32, u32))KEY_POST)(dev, KEY_QS_OFF);\n', ''),
    ('accepted does not apply', 'if (qr_restore(st, sc->f, &sc->diff, 1)) { sc->applied++;', 'if (qr_restore(st, sc->f, &sc->diff, 0)) { sc->applied++;'),
    ('go ignores the api version', 'api->version < 7u) return 0;', 'api->version < 1u) return 0;'),
    ('go ignores recording', 'if (!on || !st || !st->scan.vt_ok || busy()) return 0;', 'if (!on || !st || !st->scan.vt_ok) return 0;'),
    ('install over any word', 'if (W(SITE[i]) != STOCK[i]) { sc->vt_why = 1u + i; return; }', '(void)STOCK[i];'),
    ('no dial hint', '        if (f->adjust) f->flags |= QSC_F_DIAL_HINT;', '        (void)0;'),
    ('dial hint everywhere', '        if (f->adjust) f->flags |= QSC_F_DIAL_HINT;', '        f->flags |= QSC_F_DIAL_HINT;'),
    ('stock quirk ignored in the check', 'if (!data || !qrd_sensorlab(data, len, 1, sc->code)) return 0;', 'if (!data || !qrd_sensorlab(data, len, 0, sc->code)) return 0;'),
]


def mutate():
    import shutil
    import subprocess
    import tempfile
    src = (HERE / 'slqs.c').read_text()
    survived = []
    tests = ['Install', 'Restore.test_each_derived_field_mismatch_is_refused_and_named', 'Decoder', 'Page', 'Tile']
    import build_slqs as BS
    for name, a, b in MUTANTS:
        assert src.count(a) == 1, name
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        if env.get('SL_TESTCACHE', '1') != '0':
            env['SL_TESTCACHE'] = 'ro'                      # as test_slqs: a mutant's build is a one-off
        with tempfile.TemporaryDirectory(prefix='qrscan-mut-') as t:
            env['PYTHONPYCACHEPREFIX'] = t
            m = pathlib.Path(t) / 'slqs.c'
            m.write_text(src.replace(a, b))
            shutil.copy(HERE / 'qrdec.c', pathlib.Path(t) / 'qrdec.c')   # included relative to the source
            env['SLQS_SRC'] = str(m)
            try:
                BS.compile_text(m)
            except BS.BuildError as e:
                print('BAD (does not build) ' + name + ': ' + str(e)[:200], flush=True)
                survived.append(name)
                continue
            r = subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', *('test_qrscan.' + x for x in tests)],
                               cwd=HERE, env=env, capture_output=True, text=True)
            caught = r.returncode != 0 and ('FAILED' in r.stderr or 'Error' in r.stderr)
        print(('caught   ' if caught else 'SURVIVED ') + name, flush=True)
        if not caught:
            survived.append(name)
    return survived


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        s = mutate()
        print('survived:', s)
        sys.exit(1 if s else 0)
    unittest.main()
