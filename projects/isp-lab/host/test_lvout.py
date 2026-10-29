"""lvout.S under unicorn against the real C0437E98 body, the firmware facts it rests on, isp_custom's install /
restore around it; mutants.  Offline: putfile / callfn / cave are stubbed before isp_custom is imported, so nothing
here can reach USB.  python3 -B -m unittest test_lvout   (from this directory)"""
import importlib.util, io, json, os, pathlib, struct, sys, tempfile, types, unittest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_SP,
                               UC_ARM_REG_LR)

HERE = pathlib.Path(__file__).resolve().parent
HOST = HERE.parent / 'host'
ROOT = HERE.parents[2]
for _m in ('putfile', 'callfn', 'cave'):             # no USB: every camera module is a stub
    sys.modules[_m] = types.ModuleType(_m)
sys.path[:0] = [str(HERE), str(HOST), str(ROOT / 'fpSup' / 'fp_usb_shell')]
import armasm                                        # noqa: E402
import isp_custom as C                               # noqa: E402

C.MATRIX = HOST / 'matrix.json'
SRC = HERE / 'asm' / 'lvout.S'
IMG = (ROOT / 'out' / 'MAIN_c0000000.bin').read_bytes()
SEG1 = (ROOT / 'out' / 'seg1_c2ef6e00.bin').read_bytes()
BASE, OBJ, STACK, STOP = 0x45000000, 0x46000000, 0x47000000, 0x48000000
DESC = 0xC3001000                                                   # inside ogc_out's 0xC0000000..0xC3FFFFFF
CINE = [1620, 911, 0, 0, 1620, 911, 0, 4, 0x3FC000, 1, 1]          # LIVE_VIEW_DISPLAY_CHAIN §2, measured live
DET = [320, 180, 0, 0, 320, 180, 3, 4, 76800, 1, 0]                 # 0xC2F21620 (seg1 + FUN_c0438338)


def img_w(a, n=1):
    return list(struct.unpack_from(f'<{n}I', IMG, a - 0xC0000000))


def seg1_w(a, n=1):
    return list(struct.unpack_from(f'<{n}I', SEG1, a - 0xC2EF6E00))


class Firmware(unittest.TestCase):
    """What the hook's constants are, read from the 5.02 image (the rest of the chain is in isp_custom's notes)."""

    def test_site_is_dispparam_v5(self):
        site, w0, w1 = C.LVOUT_SITE
        self.assertEqual(img_w(site, 2), [w0, w1])
        self.assertEqual(img_w(0xC0BD0318 + 8 + 4 * 5), [site])     # XC_LiveViewDispParam vtable slot v5

    def test_rec_descriptor_is_the_movie_params_idx0(self):
        # ctor FUN_c043a2d8: movw/movt r1, 0xC2F21494; add r0, r4, #0x460; bl FUN_c043cc98 (pairs[0] = r1)
        self.assertEqual(img_w(0xC043A8C0, 3), [0xE3011494, 0xE34C12F2, 0xE2840E46])
        # the image's words 6..10 (FUN_c0438338 writes only 0..5, W/H = 1920x1080)
        self.assertEqual(seg1_w(C.LVOUT_REC + 24, 5), C.LVOUT_REC_STOCK[6:])
        self.assertEqual(seg1_w(0xC2F21620 + 24, 5), DET[6:])

    def test_route_tables_pick_0x460_and_no_table_0x268(self):
        for at in (0xC043C5CC, 0xC043C5F4, 0xC043C61C):              # after the 5810 / 59B0 / 5B50 range checks
            self.assertEqual(img_w(at), [0xE2842E46])                # add r2, r4, #0x460
        self.assertEqual(img_w(0xC043C74C), [0xE3003511])            # movw r3, #0x511: no table matched ...
        self.assertEqual(img_w(0xC043C764), [0xE2842F9A])            # ... add r2, r4, #0x268 (the still param)


def rules_for(a):
    return C.lvout_rules(a)


class Hook(unittest.TestCase):
    src = SRC

    def _emu(self, rules, desc, idx, at=DESC, calls=1, change=None):
        """C0437E98 entered through the hook with pairs[idx] = at -> desc; returns (r0, r4, r5, sp delta, emu, sym)."""
        code = bytearray(armasm.assemble(self.src))
        sym = armasm.symbols(self.src)
        for i, r in enumerate(rules):
            struct.pack_into('<6I', code, sym['rules'] + C.LVOUT_RULE * i, *r)
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for a in (BASE, OBJ, STACK, STOP, 0xC0437000):
            u.mem_map(a, 0x10000)
        if at >> 16 not in (BASE >> 16, OBJ >> 16, STACK >> 16, STOP >> 16, 0xC043):
            u.mem_map(at & ~0xFFFF, 0x10000)
        u.mem_write(BASE, bytes(code))
        u.mem_write(0xC0437E98, IMG[0x437E98:0x437ED8])              # the real function: the replay runs into it
        u.mem_write(OBJ, struct.pack('<8I', at, 3, 0, 0, at, 0x20, 0, 0))
        u.mem_write(at, struct.pack('<11I', *desc))
        out = []
        for k in range(calls):
            if change and k:
                u.mem_write(at, struct.pack('<11I', *change))
            u.reg_write(UC_ARM_REG_R0, OBJ)
            u.reg_write(UC_ARM_REG_R1, idx)
            u.reg_write(UC_ARM_REG_R4, 0x4444)
            u.reg_write(UC_ARM_REG_R5, 0x5555)
            u.reg_write(UC_ARM_REG_SP, STACK + 0x8000)
            u.reg_write(UC_ARM_REG_LR, STOP)
            u.emu_start(BASE + sym['out'], STOP, count=500)
            out.append((u.reg_read(UC_ARM_REG_R0), u.reg_read(UC_ARM_REG_R4), u.reg_read(UC_ARM_REG_R5),
                        u.reg_read(UC_ARM_REG_SP) - (STACK + 0x8000)))
        return out, u, sym

    def _words(self, u, a, n=11):
        return list(struct.unpack('<%dI' % n, u.mem_read(a, 4 * n)))

    def _hits(self, u, sym, i):
        return self._words(u, BASE + sym['rules'] + C.LVOUT_RULE * i + C.LVOUT_HITS, 1)[0]

    def test_standby_1620x911_becomes_the_record_box(self):
        rules = rules_for(6048 / 4040)
        out, u, sym = self._emu(rules, CINE, 0)
        (r0, r4, r5, dsp), = out
        tpl = BASE + sym['rules'] + C.LVOUT_RULE * 0 + 28
        self.assertEqual(r0, tpl)
        self.assertEqual(self._words(u, tpl), [1616, 1080, 0, 0, 1616, 1080, 0, 4, 0x3FC000, 1, 1])
        self.assertEqual(self._words(u, DESC), CINE)                    # the firmware's descriptor is never written
        self.assertEqual((r4, r5, dsp), (0x4444, 0x5555, 0))
        self.assertEqual([self._hits(u, sym, i) for i in range(3)], [1, 0, 0])

    def test_rec_1920x1080_by_address(self):
        rec = C.LVOUT_REC_STOCK
        for a, box in ((6048 / 4040, (1616, 1080)), (1.51, (1620, 1072)), (4032 / 4032, (1072, 1080))):
            rules = rules_for(a)
            out, u, sym = self._emu(rules, rec, 0, at=C.LVOUT_REC)
            tpl = BASE + sym['rules'] + C.LVOUT_RULE * 1 + 28
            self.assertEqual(out[0][0], tpl, a)
            self.assertEqual(self._words(u, tpl), [*box, 0, 0, *box, 0, 4, 0x3FC000, 1, 1], a)
            self.assertEqual(self._hits(u, sym, 1), 1)

    def test_idx2_320x180(self):
        rules = rules_for(1.5)
        out, u, sym = self._emu(rules, DET, 2)
        tpl = BASE + sym['rules'] + C.LVOUT_RULE * 2 + 28
        self.assertEqual(out[0][0], tpl)
        self.assertEqual(self._words(u, tpl), [320, 213, 0, 0, 320, 213, 3, 4, 76800, 1, 0])   # = the still's 320x213
        self.assertEqual(len(rules_for(1.0)), 2)                         # 1:1 keeps the stock one (cap 320x240)

    def test_untouched_answers_the_stock_descriptor(self):
        rules = rules_for(1.5)
        cases = [(CINE, 1, DESC), (CINE, 3, DESC),                      # other idx
                 ([1280, 720, 0, 0, 1280, 720, 0, 4, 0x3FC000, 1, 1], 0, DESC),
                 (C.LVOUT_REC_STOCK, 0, DESC),                           # 1920x1080 elsewhere: HDMI / MAG params
                 ([1620, 1080, 0, 0, 1620, 1080, 0, 4, 0x3FC000, 1, 0], 0, DESC),   # the still's own 1620x1080
                 (DET, 0, DESC),                                         # 320x180 as idx 0
                 (CINE, 0, 0x40000000)]                                  # outside ogc_out's address guard
        for desc, idx, at in cases:
            out, u, sym = self._emu(rules, desc, idx, at=at)
            self.assertEqual(out[0], (at if idx in (0, 2) else 0, 0x4444, 0x5555, 0), (desc[:2], idx, hex(at)))
            self.assertEqual([self._hits(u, sym, i) for i in range(3)], [0, 0, 0])
        out, u, sym = self._emu([], CINE, 0)                             # no rules: stock
        self.assertEqual(out[0], (DESC, 0x4444, 0x5555, 0))

    def test_template_is_filled_once(self):
        rules = rules_for(1.5)
        moved = [1620, 911, 0, 0, 1620, 911, 9, 9, 9, 9, 9]
        out, u, sym = self._emu(rules, CINE, 0, calls=3, change=moved)
        tpl = BASE + sym['rules'] + 28
        self.assertEqual({o[0] for o in out}, {tpl})
        self.assertEqual(self._words(u, tpl), [1620, 1080, 0, 0, 1620, 1080, 0, 4, 0x3FC000, 1, 1])
        self.assertEqual(self._hits(u, sym, 0), 3)


MUTANTS = {
    'REC rule ignores the address': ('    cmp     ip, r2\n    bne     2f\n', ''),
    'second W not replaced': ('    str     ip, [r3, #(R_TPL + 0x10)]\n', ''),
    'second H not replaced': ('    str     ip, [r3, #(R_TPL + 0x14)]\n', ''),
    'refilled every hit': ('    cmp     ip, #0\n    bne     6f\n', ''),
    'replay drops mov r5, r0': ('    mov     r5, r0                      @ stock 0xC0437E9C\n', ''),
    'idx 2 not taken': ('    cmpne   r1, #2\n', '    cmpne   r1, #1\n'),
    'H not compared': ('    ldr     ip, [r3, #R_H]\n    ldr     r5, [r2, #4]\n    cmp     ip, r5\n    beq     4f\n',
                       '    b       4f\n'),
    'hits not counted': ('    add     ip, ip, #1\n    str     ip, [r3, #R_HITS]\n', '    str     ip, [r3, #R_HITS]\n'),
    'replay pushes without lr': ('    push    {r4, r5, lr}                @ stock 0xC0437E98\n',
                                 '    push    {r4, r5}\n'),
}


# ---- isp_custom: apply / restore around the hook ------------------------------------------------------------------
class FakeShell:
    def __init__(self, mem):
        self.mem, self.writes = dict(mem), []

    def sh(self, line):
        return 'is_recording -> 0'

    def mem_get(self, a, n=1):
        return [self.mem.get(a + 4 * i, 0) for i in range(n)]

    def mem_set(self, a, v):
        self.writes.append((a, v))
        self.mem[a] = v


CLAIM = 0xC072E400


def stock_mem(p):
    m = {a: o for a, o, n, off in p['diffs']}
    site, w0, w1 = C.LVOUT_SITE
    m[site], m[site + 4] = w0, w1
    for i, v in enumerate(C.LVOUT_REC_STOCK):
        m[C.LVOUT_REC + 4 * i] = v
    return m


class Install(unittest.TestCase):
    mod = C
    exp = 'M0'                                                         # OG 6048x4040, 1.497

    def setUp(self):
        M = self.mod
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.saved = {k: getattr(M, k) for k in ('STATE', '_shell', '_flush', 'vmode_install', 'vmode_restore',
                                                  'lv_reload', 'MATRIX')}
        self.env = os.environ.get('ISPC_LVOUT')
        M.STATE, M._flush, M.MATRIX = self.tmp / 'state.json', (lambda: None), HOST / 'matrix.json'
        M.vmode_install = M.vmode_restore = M.lv_reload = (lambda *a: None)
        self.put = {}
        sys.modules['cave'].claim = lambda name, size: CLAIM
        sys.modules['putfile'].put = lambda at, data, what: self.put.__setitem__(at, bytes(data))
        sys.modules['putfile'].mem_get = lambda a, n=1: self.sh.mem_get(a, n)
        self.p = M.plan(self.exp)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(self.mod, k, v)
        if self.env is None:
            os.environ.pop('ISPC_LVOUT', None)
        else:
            os.environ['ISPC_LVOUT'] = self.env

    def _run(self, mem):
        self.sh = FakeShell(mem)
        self.mod._shell = lambda: self.sh
        return self.sh

    def test_apply_hooks_then_restore_puts_everything_back(self):
        M = self.mod
        stock = stock_mem(self.p)
        sh = self._run(stock)
        M.apply(self.exp)
        site, w0, w1 = M.LVOUT_SITE
        code, sym = M.lvout_code(self.p['lvout'])
        self.assertEqual(self.put, {CLAIM: bytes(code)})
        self.assertEqual(sh.mem_get(site, 2), [M.LDR_PC_M4, CLAIM + sym['out']])
        self.assertLess(sh.writes.index((site + 4, CLAIM + sym['out'])), sh.writes.index((site, M.LDR_PC_M4)))
        rules = [list(struct.unpack_from('<6I', code, sym['rules'] + M.LVOUT_RULE * i)) for i in range(3)]
        self.assertEqual(rules, [[0, 0, 1620, 911, 1616, 1080], [0, M.LVOUT_REC, 1920, 1080, 1616, 1080],
                                 [2, 0, 320, 180, 320, 214]])
        self.assertNotIn(0xC375E934, sh.mem.keys() - stock.keys())     # the heap descriptor is no longer a RAM word
        self.assertFalse({a for a, v in sh.writes} & {0xC375E934, 0xC375EA68, M.LVOUT_REC})
        self.assertEqual(json.loads(M.STATE.read_text())['lvout_hook']['at'], CLAIM)
        M.restore()
        self.assertEqual({a: sh.mem[a] for a in stock}, stock)
        self.assertFalse(M.STATE.exists())

    def test_square_and_apsc_install_their_box(self):
        M = self.mod
        for exp, box, n in (('M554', (1072, 1080), 2), ('M341', (1620, 1072), 3)):
            p = M.plan(exp)
            self.assertEqual(len(p['lvout']), n, exp)
            self.assertEqual({tuple(r[4:]) for r in p['lvout'][:2]}, {box}, exp)

    def test_16_9_installs_nothing(self):
        M = self.mod
        p = M.plan('E2')
        self.assertEqual(p['lvout'], [])
        sh = self._run(stock_mem(p))
        M.apply('E2')
        self.assertEqual(self.put, {})
        self.assertFalse({a for a, v in sh.writes} & {M.LVOUT_SITE[0], M.LVOUT_SITE[0] + 4})
        M.restore()
        self.assertFalse({a for a, v in sh.writes} & {M.LVOUT_SITE[0], M.LVOUT_SITE[0] + 4})

    def test_site_not_stock_refuses_before_any_write(self):
        M = self.mod
        for where in (M.LVOUT_SITE[0], M.LVOUT_SITE[0] + 4, M.LVOUT_REC, M.LVOUT_REC + 32):
            mem = stock_mem(self.p)
            mem[where] ^= 1
            sh = self._run(mem)
            with self.assertRaises(SystemExit):
                M.apply(self.exp)
            self.assertEqual(sh.writes, [], hex(where))
            self.assertEqual(self.put, {})
            self.assertFalse(M.STATE.exists())

    def test_control_without_the_hook(self):
        M = self.mod
        os.environ['ISPC_LVOUT'] = '0'
        mem = stock_mem(self.p)
        mem[M.LVOUT_SITE[0]] ^= 1                                       # not even looked at
        sh = self._run(mem)
        M.apply(self.exp)
        self.assertEqual(self.put, {})
        self.assertFalse({a for a, v in sh.writes} & {M.LVOUT_SITE[0], M.LVOUT_SITE[0] + 4})
        M.restore()
        self.assertFalse({a for a, v in sh.writes} & {M.LVOUT_SITE[0], M.LVOUT_SITE[0] + 4})


PY_MUTANTS = {
    'apply skips the check': ("    if plan_.get('lvout'):\n        lvout_check(p, plan_['lvout'])\n", ''),
    'restore leaves the hook': ("    if plan_.get('lvout'):                        # the same\n        lvout_restore()\n", ''),
    'restore puts one word back': ("    _set(p, site, w0)\n    _set(p, site + 4, w1)\n", "    _set(p, site, w0)\n"),
    'ldr before its address': ("    _set(p, site + 4, at + sym['out'])\n    _set(p, site, LDR_PC_M4)\n",
                               "    _set(p, site, LDR_PC_M4)\n    _set(p, site + 4, at + sym['out'])\n"),
    'REC rule by size only': ("(0, LVOUT_REC, 1920, 1080, tw, th)", "(0, 0, 1920, 1080, tw, th)"),
    'heap descriptor written again': ("    out += [(site, MOV_R0 | 3, MOV_R0 | ASPECT_SLOT, 0x2010 + i) for i, site in enumerate(ASPECT_SITES)]\n",
                                      "    out += [(site, MOV_R0 | 3, MOV_R0 | ASPECT_SLOT, 0x2010 + i) for i, site in enumerate(ASPECT_SITES)]\n"
                                      "    out.append((0xC375E934, 1620, lv_box(a)[0], 0x2020))\n"),
}


class Mutation(unittest.TestCase):
    def _killed(self, cls):
        r = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestLoader().loadTestsFromTestCase(cls))
        return not r.wasSuccessful()

    def test_every_asm_mutant_is_caught(self):
        src = SRC.read_text()
        for name, (old, new) in MUTANTS.items():
            self.assertEqual(src.count(old), 1, name)
            with tempfile.TemporaryDirectory() as t:
                p = pathlib.Path(t) / 'm.S'
                p.write_text(src.replace(old, new))
                self.assertTrue(self._killed(type('M', (Hook,), {'src': p})), f'mutant survived: {name}')

    def test_every_install_mutant_is_caught(self):
        src = (HERE / 'isp_custom.py').read_text()
        for name, (old, new) in PY_MUTANTS.items():
            self.assertEqual(src.count(old), 1, name)
            path = HERE / '_mutant_isp_custom.py'              # beside the real one: HERE-relative paths hold
            try:
                path.write_text(src.replace(old, new))
                spec = importlib.util.spec_from_file_location('_mutant_isp_custom', path)
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                m.LVOUT_SRC = SRC
                cls = type('M', (Install,), {'mod': m})
                self.assertTrue(self._killed(cls), f'mutant survived: {name}')
            finally:
                path.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
