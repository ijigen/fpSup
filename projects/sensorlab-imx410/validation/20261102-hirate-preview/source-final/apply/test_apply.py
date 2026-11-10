#!/usr/bin/env python3
"""SensorLab-IMX410 apply (stage V1) under unicorn against the real firmware image, and its pure half on the host.

    cd projects/sensorlab-imx410/apply
    python3 -B -m unittest test_apply          # all
    python3 -B test_apply.py --mutate          # every mutant in MUTANTS must make a test fail

What runs for real (emulated, not on the camera): the ARM/Thumb unit (core.c + ap.c, built as the sup builds it),
ap_init's claims and site writes, the veneers, the hook handler, and -- through the hooked sites -- the firmware's own
lookups, register-record writer and mode readers, the picker, the profile gather (FUN_c0439d18 between the vpro and
canvas sites), the LV descriptor getter, the aspect fit and its ratio getter.  Stubbed (Python): the loader service
(claim / cave_alloc / publish), the settings getters, the LV stop / start and camera-schedule calls, the D-cache clean,
the tick, the sensor register writer (recorded), and the layer below recrate / binpath (a fixed native result).
The mode descriptor is boot-built on the camera, so it is built here as res-custom's tests build it (real tables,
a synthetic magnifier table).

Ground truth is the Python: imx410-lab readout_cfg + smc.create (the rows isp-lab's vmode path installs), isp-lab
quality.py / isp_formula.row over profile 171's row, isp_custom lv_box / lvout_rules / display_diffs / binfilt_cfg,
aspect.dng_aspect.
"""
import ctypes, dataclasses, functools, json, os, pathlib, re, shutil, struct, subprocess, sys, tempfile, unittest
from fractions import Fraction

HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(os.environ.get('SL_ROOT', HERE.parents[2]))
IMXL = ROOT / 'projects' / 'imx410-lab'
ISPH = ROOT / 'projects' / 'isp-lab' / 'host'
sys.path[:0] = [str(HERE), str(IMXL), str(IMXL / 'offline'), str(ISPH)]
import build_apply as BA                                    # noqa: E402
import quality as Q                                         # noqa: E402
import isp_formula as F                                     # noqa: E402
import smc                                                  # noqa: E402
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_UNMAPPED  # noqa: E402
from unicorn.arm_const import *                             # noqa: E402,F403

IMAGE = ROOT / 'out' / 'MAIN_c0000000.bin'
PROFILES = ROOT / 'research/other/external/FP3K-technical-handoff-2026-09-10/analysis/firmware/raw-profiles.json'
SRC = HERE / 'src_override'                                 # unused unless a mutant run sets AP_SRC
CLK = 72_000_000
AP_MEM = int(re.search(r'#define AP_MEM_BYTES (0x[0-9A-Fa-f]+)u', (HERE / 'ap.h').read_text()).group(1), 16)

# ---- emulated memory ----
BLOB, MEM, STACK, DONE, WORK, SVC, STUB = 0x46000000, 0x46200000, 0x47040000, 0x48000000, 0x48100000, 0x48200000, 0x48300000
DESC, SYN = 0xC3F00000, 0xC3F10000
IMAGER, HOLDER, MAPPING, LV_MGR = 0xC343B588, 0xC343B67C, 0xC0BD05D4, 0xC375D840
REGDESC = 0xC0B5FDA4
TAB1, TAB2, TAB3 = 0xC0BE5810, 0xC0BE59B0, 0xC0BE5B50
MOV_SELECTOR, MOVREC_DEFAULT, XMP_FOBJ, MOV_ACTIVE = 0xC347D1D4, 0xC347E08F, 0xC358E140, 0xC35A952C
CAVE_BUMP, CAVE_ARENA = 0xC072E060, 0xC072E064
FW = dict(GET_OBJ=0xC0057AE8, GET_FMT=0xC005BE90, FR_GET=0xC005C0F0, CAMSCH1=0xC0207188, CS_GET=0xC0207440,
          CS_SET=0xC02073B8, LV_HOLDER=0xC0423C48, LV_STOP=0xC0423D28, LV_START=0xC0423C88, DCACHE=0xC000E91C,
          TICK=0xC002B6E0, SENSOR_W=0xC0322C70, FR_SET=0xC005C0B8, EXCL_MGR=0xC049EC58, EXCL_RECOMPUTE=0xC049EE78,
          ICACHE=0xC000EABC)
TABS = 0xC0BE4990
CLK_SITE, CLK_STOCK, CLK_OPEN = 0xC0189440, 0x2C49F241, 0x7CFFF64F
SVC_FN = ['claim', 'claim_res', 'chain_next', 'cave_alloc', 'publish', 'log']   # sl_svc +8 ..
TABLES = [('TIM', 0x00, 0x20), ('META', 0x08, 100), ('R28', 0x24, 0x28), ('R38', 0x40, 0x38), ('R14', 0x48, 0x14),
          ('R68', 0xF4, 0x68)]
LOOKUPS = [0xC0320BA0, 0xC0320B38, 0xC0320E90, 0xC0320F60, 0xC0320EF8, 0xC0320C00]
LK_REG, LK_R10 = 0xC0326DB8, 0xC031FFA0
PICKER, OUT, RATIO = 0xC043CCF8, 0xC0437E98, 0xC02DAFA0
CARRIER = {1: 2398, 12: 2400, 2: 2500, 3: 2997, 13: 4800, 4: 5000, 5: 5994, 6: 10000, 7: 11988}
ENGINE = {1: 24.0, 12: 24.0, 2: 25.0, 3: 30.0, 13: 48.0, 4: 50.0, 5: 60.0, 6: 50.0, 7: 60.0}
SUFFIX = {1: '23_98', 12: '24', 2: '25', 3: '30', 13: '48', 4: '50', 5: '60', 6: '100', 7: '120'}
AP_OK, AP_IDLE, AP_PENDING = 0, 1, 2
AP_E = dict(ABI=-1, HOOKS=-2, NOTREADY=-3, RECIPE=-4, CORE=-5, ISP=-6, RATE=-7, FORMAT=-8, BUSY=-9, STANDBY=-11)


def emu_cap(count):
    """emu_start kwargs for an instruction cap: by default a wall-clock cap (count / 10 M instructions per second)
    instead of unicorn's counter, which instruments every instruction (4-5x slower); SL_EMU_COUNT=1 restores the
    counter exactly (qs-container/testcache.emu_start; README "Testing")"""
    return dict(count=count) if os.environ.get('SL_EMU_COUNT') == '1' else dict(timeout=max(1, count // 10))


def f32(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


@functools.lru_cache(None)
def image():
    return IMAGE.read_bytes()


def iw(a):
    return struct.unpack_from('<I', image(), a - 0xC0000000)[0]


def rec_spec(spec):
    """Bei 10-30 (notes/RWZM_14BIT_CHECK.md): a 14-bit-AD recipe that scales records in a 12-bit container"""
    import dataclasses
    if spec.bits == 14 and not (tuple(spec.zoom) == (1024, 1024) and spec.hbin == 1 and spec.vbin == 1):
        return dataclasses.replace(spec, bits=12)
    return spec


@functools.lru_cache(None)
def built(src=None):
    return BA.arm(pathlib.Path(src) if src else HERE)


@functools.lru_cache(None)
def host():
    # a private build dir per process: parallel runs (tools/test.py) must never rewrite a dylib another process loaded
    import atexit
    d = pathlib.Path(tempfile.mkdtemp(prefix='slap-host-'))
    atexit.register(shutil.rmtree, d, True)
    lib = BA.host(out_dir=d)
    lib.core_key_index.argtypes = [ctypes.c_char_p]
    return lib


@functools.lru_cache(None)
def profile_rows():
    j = json.loads(PROFILES.read_text())
    return {pid: rr['words'] for rr in j['rows'] for pid in rr['profile_ids']}


# ---- the recipes (Python ground truth) ----
@functools.lru_cache(None)
def recipe(dcw, dch, rw, rh, merge, ad_bits, fps=Fraction(2997, 100), hbin=1, vbin=1):
    """(sel words, Python case, plan, rows, isp spec) for the quality `merge` at AD `ad_bits`, at the VMAX step of fps."""
    cs = Q.qualities(dcw, dch, rw, rh, None, 0.02)
    hit = [c for c in cs if c['merge'] == merge and c['hbin'] == hbin and c['vbin'] == vbin and
           Q.ad_of(c['readout'][0], c['bits']) == str(ad_bits)]
    assert hit, f'{dcw}x{dch}>{rw}x{rh} has no {ad_bits}b {merge}'
    c = hit[0]
    hm = Q.hmax_of(c)
    lo, _, vmx = Q.vmax_range(c)
    v = max(lo, -(-CLK * fps.denominator // (hm * fps.numerator)))
    plan, spec = Q.settings(c, CLK / (hm * v))
    spec = rec_spec(spec)
    assert plan['soc']['vmax'] == v and plan['soc']['hmax'] == hm, (plan['soc'], v, hm)
    _, rows, _ = smc.create(plan)
    key = host().core_key_index(c['readout'][0].encode())
    assert key >= 0
    sel = dict(dcw=dcw, dch=dch, rw=rw, rh=rh, key=key, hbin=hbin, vbin=vbin, hm=hm, vmax=v,
               fps_n=fps.numerator, fps_d=fps.denominator)
    return sel, c, plan, rows, spec


V1 = (2016, 1346)                         # OG 2K: the RES list's 6048/3 entry (see APPLY_DESIGN §11.1)
V1_ARGS = (6048, 4040) + V1 + ('2x3', 12)
ALT_ARGS = (6048, 4040, 3024, 2020, '2x2', 12)              # OG 3K 12b 2x2 (OG 3K has no 2x3)
SEL_FIELDS = 'valid fmt dcw dch rw rh key hbin vbin hm vmax fps_n fps_d kh kv km standby'.split()
STATUS_KEYS = ('bytes abi armed active cur mode_id pid result detail commits refusals lv_reloads owed picks lookups '
               'canvases recrates standby_picks carrier carrier_sets fast commit_us gated blacks').split()


def sel_bytes(sel, valid=1, fmt=0, kh=1, kv=1, km=0, standby=1, **over):
    d = dict(sel, valid=valid, fmt=fmt, kh=kh, kv=kv, km=km, standby=standby)
    d.update(over)
    return struct.pack('<19I', 19 * 4, 2, *[d[k] & 0xFFFFFFFF for k in SEL_FIELDS])


def carrier_of(fps):
    stock = [(1, Fraction(24000, 1001)), (12, Fraction(24)), (2, Fraction(25)), (3, Fraction(30000, 1001)), (13, Fraction(48)),
             (4, Fraction(50)), (5, Fraction(60000, 1001)), (6, Fraction(100)), (7, Fraction(120000, 1001))]
    return next((e for e, r in stock if r >= fps * (1 - Fraction(1, 20000))), 7)


# ---- the emulated camera ----
class Cam:
    def __init__(self, src=None, refuse_claim=None, build_desc=True):
        self.img, self.funcs = built(src)
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        mu.mem_map(0xC0000000, 0x03000000)
        mu.mem_write(0xC0000000, image()[:0x03000000])
        mu.mem_map(0xC3000000, 0x01000000)
        mu.mem_map(BLOB, 0x00200000)
        mu.mem_write(BLOB, self.img)
        mu.mem_map(MEM, 0x00100000)
        mu.mem_map(STACK - 0x40000, 0x40000)
        mu.mem_map(DONE, 0x1000)
        mu.mem_map(WORK, 0x00400000)
        self.calls, self.claims, self.sensor, self.error = [], [], [], None
        self.fmt, self.fr, self.cs, self.now = 0, 3, 1, 0
        self.lv_on = True
        self.refuse_claim = refuse_claim
        self.on_stop = None
        self.fr_refuse = False
        self.clk_writes = []
        self.native = (30000, 1001)
        self.by_addr = {}
        for n, a in FW.items():
            self.stub(a, n)
        for i, n in enumerate(SVC_FN):
            self.stub(STUB + 8 * i, 'svc_' + n)
            self.put(SVC + 8 + 4 * i, STUB + 8 * i)
        self.put(SVC, 7)
        self.put(CAVE_BUMP, CAVE_ARENA)
        self.lvholder = WORK
        self.put(WORK, WORK + 0x100)
        self.put(WORK + 0x104, 1)
        mu.hook_add(UC_HOOK_CODE, self._hook, begin=DONE, end=DONE)
        if build_desc:
            self.build_descriptor()

    def stub(self, a, name):
        self.mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
        self.by_addr[a] = name
        self.mu.hook_add(UC_HOOK_CODE, self._hook, begin=a, end=a)

    # plumbing
    def r(self, reg):
        return self.mu.reg_read(reg)

    def w(self, a):
        return struct.unpack('<I', self.mu.mem_read(a, 4))[0]

    def put(self, a, v):
        self.mu.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def ret(self, v=None):
        if v is not None:
            self.mu.reg_write(UC_ARM_REG_R0, v & 0xFFFFFFFF)
        self.mu.reg_write(UC_ARM_REG_PC, self.r(UC_ARM_REG_LR))

    def _hook(self, mu, addr, size, data):
        try:
            if addr == DONE:
                mu.emu_stop()
                return
            name = self.by_addr.get(addr)
            if not name:
                return
            r0, r1, r2, r3 = (self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))
            sp = self.r(UC_ARM_REG_SP)
            if sp & 7 and name not in ('SENSOR_W',):
                self.calls.append(('MISALIGNED', name))
            if name == 'SENSOR_W':
                self.sensor.append((r0, r1))
                return self.ret(0)
            self.calls.append((name, r0, r1))
            if name == 'svc_claim':
                kind = self.w(sp)
                self.claims.append((r1, r2, self.w(r3), kind))
                if self.refuse_claim is not None and len(self.claims) == self.refuse_claim:
                    return self.ret(-1)
                return self.ret(0)
            if name == 'svc_cave_alloc':
                p = (self.w(CAVE_BUMP) + 7) & ~7
                self.put(CAVE_BUMP, p + ((r1 + 7) & ~7))
                return self.ret(p)
            if name in ('svc_publish', 'DCACHE', 'CS_SET', 'svc_log', 'ICACHE', 'EXCL_RECOMPUTE'):
                return self.ret(0)
            if name == 'EXCL_MGR':
                return self.ret(0xC3766AEC)
            if name == 'FR_SET':
                if not self.fr_refuse:
                    self.fr = r1
                return self.ret(0)
            if name == 'GET_OBJ':
                return self.ret(0x1234)
            if name == 'GET_FMT':
                return self.ret(self.fmt)
            if name == 'FR_GET':
                return self.ret(self.fr)
            if name == 'CAMSCH1':
                return self.ret(0xCAFE0)
            if name == 'CS_GET':
                return self.ret(self.cs)
            if name == 'LV_HOLDER':
                return self.ret(self.lvholder if self.lv_on else 0)
            if name == 'LV_STOP':
                if self.on_stop:
                    self.on_stop(self)
                return self.ret(0)
            if name == 'LV_START':
                return self.ret(0)
            if name == 'TICK':
                return self.ret(self.now)
            if name == 'NATIVE_RATE':
                self.put(r0, self.native[0])
                self.put(r0 + 4, self.native[1])
                return self.ret(0x77)
            raise RuntimeError(f'unhandled stub {name}')
        except Exception as e:                              # pragma: no cover
            self.error = e
            mu.emu_stop()

    def call(self, pc, *args, thumb=False, sp=STACK - 0x1004, **regs):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, sp)
        for i, v in enumerate(args):
            mu.reg_write([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3][i], v & 0xFFFFFFFF)
        names = dict(r4=UC_ARM_REG_R4, r5=UC_ARM_REG_R5, r6=UC_ARM_REG_R6, ip=UC_ARM_REG_R12)
        for k, v in regs.items():
            mu.reg_write(names[k], v & 0xFFFFFFFF)
        mu.reg_write(UC_ARM_REG_LR, DONE)
        mu.emu_start(pc | (1 if thumb else 0), DONE, **emu_cap(50_000_000))
        if self.error:
            raise self.error
        if mu.reg_read(UC_ARM_REG_PC) != DONE:
            raise RuntimeError(f'{pc:#x} did not return (pc {mu.reg_read(UC_ARM_REG_PC):#x})')
        return self.r(UC_ARM_REG_R0)

    def fn(self, name, *args, sp=STACK - 0x1000):
        return ctypes.c_int32(self.call(BLOB + self.funcs[name], *args, sp=sp)).value

    # the boot-built descriptor (as res-custom's test_v3_rescustom builds it)
    def build_descriptor(self):
        modes = [iw(0xC0B59500 + 0x20 * i) for i in range(70)]
        for i, m in enumerate(modes):
            row = [m] + [(m << 16) | (0x128 << 4) | k for k in range(1, 0x5C // 4)]
            self.mu.mem_write(SYN + i * 0x5C, struct.pack('<23I', *row))
        desc = {0x00: 0xC0B59500, 0x04: 70, 0x08: 0xC0B59DC0, 0x0C: 70, 0x10: 0xC0B5B918, 0x14: 70,
                0x24: 0xC0B5BB48, 0x28: 70, 0x40: 0xC0B5C638, 0x44: 70, 0x48: 0xC0B5D588, 0x4C: 70,
                0xF4: 0xC0B5DB00, 0xF8: 70, 0x128: SYN, 0x12C: 70}
        for off, v in desc.items():
            self.put(DESC + off, v)
        self.put(IMAGER, DESC)
        self.put(HOLDER, REGDESC)

    # the apply API
    def init(self):
        return self.fn('ap_init', MEM, AP_MEM, SVC)

    def request(self, sel, **kw):
        self.mu.mem_write(WORK + 0x2000, sel_bytes(sel, **kw))
        return self.fn('ap_request', MEM, WORK + 0x2000)

    def flush(self):
        return self.fn('ap_flush', MEM)

    def status(self):
        n = len(STATUS_KEYS)
        self.put(WORK + 0x3000, 4 * n)
        self.put(WORK + 0x3004, 2)
        self.fn('ap_status_get', MEM, WORK + 0x3000)
        d = dict(zip(STATUS_KEYS, struct.unpack(f'<{n}I', self.mu.mem_read(WORK + 0x3000, 4 * n))))
        d['result'] = ctypes.c_int32(d['result']).value
        return d

    def off(self, i):
        return MEM + self.fn('ap_sizes_t', i)

    def apply(self, sel, **kw):
        return self.request(sel, **kw)

    def names(self):
        return [c[0] for c in self.calls]

    def key(self, s, at=WORK + 0x4000):
        self.mu.mem_write(at, s.encode().ljust(16, b'\0'))
        return at

    def row_via_lookup(self, k, mode):
        name, field, stride = TABLES[k]
        idx = self.call(LOOKUPS[k], IMAGER, mode)
        return bytes(self.mu.mem_read((self.w(DESC + field) + idx * stride) & 0xFFFFFFFF, stride))

    def reg_via_lookup(self, mode):
        idx = self.call(LK_REG, HOLDER, mode)
        return bytes(self.mu.mem_read((iw(REGDESC) + idx * 0x288) & 0xFFFFFFFF, 0x288))

    def canvas(self, pid):
        """the firmware's gather between the vpro and canvas sites (FUN_c043a158 from C043A184 to C043A1A0)"""
        holder = WORK + 0x8000
        self.mu.mem_write(holder, b'\x11' * 0x200)
        self.mu.reg_write(UC_ARM_REG_R0, 0)
        self.mu.reg_write(UC_ARM_REG_R4, holder)
        self.mu.reg_write(UC_ARM_REG_R5, pid)
        self.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
        self.mu.emu_start(0xC043A184, 0xC043A1A0, **emu_cap(5_000_000))
        if self.error:
            raise self.error
        return list(struct.unpack('<67I', self.mu.mem_read(holder + 0x5C, 67 * 4)))


def with_id(b, mode):
    return struct.pack('<I', mode) + bytes(b[4:])


class SourceTests(unittest.TestCase):
    def test_sites_are_the_images_words_and_kinds_fit(self):
        src = (HERE / 'ap.c').read_text()
        sites = re.findall(r'\{0x([0-9A-F]{8})u, 0x([0-9A-F]{8})u, (K_\w+)\}', src)
        self.assertEqual(len(sites), 40)
        for a, w, kind in sites:
            a, w = int(a, 16), int(w, 16)
            self.assertEqual(iw(a), w, f'{a:#x}')
            branch = (w & 0x0E000000) == 0x0A000000
            self.assertEqual(branch, a in (0xC031B660, 0xC032DDF0, 0xC032DE70, 0xC02CA1C0, 0xC02CA21C, 0xC05BDE80,
                                           0xC05BDFE8, 0xC05BDC9C), f'{a:#x}')
            if kind == 'K_MID':
                self.assertIn(w, (0xE3A00002, 0xE3A00003, 0xE1A01004, 0xE1A00001, 0xE300EE04, 0xE28D102C))

    def test_link_flat_is_the_sup_builders_copy(self):
        """build_apply.link_flat must stay the logic of qs/build_slqs.py's (read, not imported)."""
        a = (HERE / 'build_apply.py').read_text()
        b = (ROOT / 'projects/sensorlab-imx410/qs/build_slqs.py').read_text()
        core = lambda t: [ln.strip() for ln in t[t.index('def link_flat'):t.index('return TextImage' if 'TextImage(' in t[t.index('def link_flat'):] else 'return bytes(out), funcs')].splitlines()
                          if ln.strip() and not ln.strip().startswith(('#', '"""', 'raise', 'load.', 'load =', 'if not flags & 2', 'if kind == 8', 'continue'))]  # noqa: E731
        ka = [x for x in core(a) if 'load' not in x and 'symtab' not in x and 'sname' not in x]
        kb = [x for x in core(b) if 'load' not in x and 'symtab' not in x and 'sname' not in x]
        self.assertGreater(len(set(ka) & set(kb)), 0.8 * len(kb))

    def test_the_unit_has_no_writable_data_and_fits(self):
        img, funcs = built()
        for f in ('ap_init', 'ap_request', 'ap_flush', 'ap_status_get', 'ap_now_us'):
            self.assertTrue(funcs[f] & 1, f)
        cam = Cam()
        self.assertLessEqual(cam.fn('ap_sizes_t', 0), AP_MEM)
        self.assertEqual(cam.fn('ap_sizes_t', 4), 19 * 4)
        self.assertEqual(cam.fn('ap_sizes_t', 7) % 8, 0)


class InstallTests(unittest.TestCase):
    def test_init_claims_every_site_and_arms_through_cave_veneers(self):
        cam = Cam()
        writes = []
        sites = {a for a, *_ in re.findall(r'\{0x([0-9A-F]{8})u, 0x([0-9A-F]{8})u, (K_\w+)\}', (HERE / 'ap.c').read_text())}
        sites = {int(a, 16) for a in sites}
        cam.mu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, a, sz, v, d: writes.append((a, len(cam.calls))),
                        begin=0xC0000000, end=0xC0700000)
        self.assertEqual(cam.init(), AP_OK)
        self.assertEqual(sorted(c[0] for c in cam.claims), sorted(sites | {CLK_SITE}))
        self.assertEqual(cam.w(CLK_SITE), CLK_STOCK, 'the clock gate is only claimed at init')
        for a, n, stock, kind in cam.claims:
            self.assertEqual((n, stock, kind), (4, iw(a), 2), f'{a:#x}: 4 bytes, stock, SL_EXCL')
        pub = [i for i, c in enumerate(cam.calls) if c[0] == 'svc_publish']
        self.assertEqual(len(pub), 2)
        self.assertTrue(writes and all(i > pub[0] for a, i in writes), 'sites written only after the veneers are published')
        for a in sites:
            w = cam.w(a)
            self.assertIn(w >> 24, (0xEA, 0xEB), f'{a:#x}')
            self.assertEqual(w >> 24 == 0xEB, a in (0xC031B660, 0xC032DDF0, 0xC032DE70, 0xC043A18C, 0xC043A19C, 0xC02CA1C0,
                                                    0xC02CA21C, 0xC05BDE80, 0xC05BDFE8, 0xC05BDC9C))
            cave = (a + 8 + ((w & 0xFFFFFF) << 8 >> 6 if not w & 0x800000 else ((w & 0xFFFFFF) | ~0xFFFFFF) << 2)) & 0xFFFFFFFF
            self.assertEqual(cam.w(cave), 0xE51FF004)
            self.assertTrue(MEM <= cam.w(cave + 4) < MEM + 0x8000)

    def test_a_refused_claim_arms_nothing(self):
        cam = Cam(refuse_claim=5)
        self.assertEqual(cam.init(), AP_E['HOOKS'])
        for a in (0xC0320BA0, 0xC043CCF8, 0xC02DAFA0):
            self.assertEqual(cam.w(a), iw(a))
        self.assertEqual(cam.request(recipe(*V1_ARGS)[0]), AP_E['HOOKS'])

    def test_armed_but_nothing_applied_everything_goes_down(self):
        ref, cam = Cam(), Cam()
        cam.init()
        for k in range(6):
            for mode in (98, 106, 230):
                self.assertEqual(cam.call(LOOKUPS[k], IMAGER, mode), ref.call(LOOKUPS[k], IMAGER, mode), (k, mode))
        self.assertEqual(cam.call(LK_REG, HOLDER, 106), ref.call(LK_REG, HOLDER, 106))
        self.assertEqual(cam.call(LK_R10, IMAGER, 106), ref.call(LK_R10, IMAGER, 106))
        self.assertEqual(cam.call(PICKER, 0, TAB3, cam.key('UHD30')), ref.call(PICKER, 0, TAB3, ref.key('UHD30')))
        self.assertEqual(cam.canvas(175), ref.canvas(175))
        self.assertEqual(cam.canvas(5), ref.canvas(5))


class CommitTests(unittest.TestCase):
    def live(self, args=V1_ARGS, **kw):
        cam = Cam()
        self.assertEqual(cam.init(), AP_OK)
        sel = recipe(*args)[0]
        self.assertEqual(cam.apply(sel, **kw), AP_OK, cam.status())
        return cam

    def test_v1_tables_and_r10_are_smc_create_through_the_firmwares_lookups(self):
        cam = self.live()
        sel, c, plan, rows, spec = recipe(*V1_ARGS)
        st = cam.status()
        mode = st['mode_id']
        self.assertIn(mode, (230, 231))
        for k, (name, _, _) in enumerate(TABLES):
            self.assertEqual(cam.row_via_lookup(k, mode), with_id(rows[name], mode), name)
        self.assertEqual(cam.reg_via_lookup(mode), with_id(rows['REG'], mode), 'REG')
        self.assertEqual(cam.call(LK_R10, IMAGER, mode), struct.unpack_from('<I', rows['R10'])[0], 'R10')
        # stock ids still go to their own rows; no firmware table changed
        for k, (name, field, stride) in enumerate(TABLES):
            idx = cam.call(LOOKUPS[k], IMAGER, 106)
            self.assertEqual(cam.w(iw_base(cam, field) + idx * stride), 106, name)
        for base, n in ((0xC0B59500, 70 * 0x20), (0xC0B59DC0, 70 * 100), (0xC0B5FDAC, 70 * 0x288), (MAPPING, 500 * 4),
                        (TAB3, 0x200), (0xC0BD4704, 306 * 4)):
            self.assertEqual(bytes(cam.mu.mem_read(base, n)), image()[base - 0xC0000000:base - 0xC0000000 + n], hex(base))

    def test_the_mode_set_programs_what_the_vmode_path_programs(self):
        """Our virtual id through the hooks == the same rows written into the stock tables under the donor's id
        (isp-lab vmode.apply, the live-proven path; KEEP_WINDOW: the magnifier window is not written)."""
        sel, c, plan, rows, spec = recipe(*V1_ARGS)
        donor = plan['donor']
        ours = self.live()
        mode = ours.status()['mode_id']
        ref = Cam()
        for k, (name, field, stride) in enumerate(TABLES):
            base = ref.w(DESC + field)
            i = [ref.w(base + stride * j) for j in range(70)].index(donor)
            ref.mu.mem_write(base + stride * i, with_id(rows[name], donor))
        rbase = iw(REGDESC)
        i = [iw(rbase + 0x288 * j) for j in range(70)].index(donor)
        ref.mu.mem_write(rbase + 0x288 * i, with_id(rows['REG'], donor))
        r10 = 0xC0B5B918
        i = [iw(r10 + 8 * j + 4) for j in range(70)].index(donor)
        ref.mu.mem_write(r10 + 8 * i, bytes(rows['R10'])[:4])
        ref.put(DESC + 0x11C, 0)                           # NOZOOM: vmode KEEP_WINDOW
        a, b = programming(ours, mode), programming(ref, donor)
        self.assertGreater(len(a[1]), 150, 'the register record was really written')
        self.assertEqual(a[1], b[1], 'sensor register writes')
        self.assertEqual([(f, donor if v == mode else v) for f, v in a[0]], b[0], 'mode readers')

    def test_the_picker_hands_out_our_entry_on_the_carrier_only(self):
        cam = self.live()
        st = cam.status()
        e = cam.call(PICKER, 0, TAB3, cam.key('UHD30'))
        self.assertTrue(MEM <= e < MEM + 0x8000)
        self.assertEqual([cam.w(e + 4 * i) for i in range(3)], [5, st['pid'], st['mode_id']])
        self.assertEqual(bytes(cam.mu.mem_read(cam.w(e + 12), 5)), b'SL30\0')
        self.assertEqual(cam.call(PICKER, 0, TAB3, cam.key('FHD30CROP')), e)
        for key, tab in (('UHD24', TAB3), ('FHD60', TAB3), ('FHD120', TAB3), ('UHD30', TAB2), ('UHD30', TAB1)):
            s = cam.call(PICKER, 0, tab, cam.key(key))
            self.assertTrue(tab <= s < tab + 0x1A0, f'{key} on {tab:#x}: stock')
        cam.fr = 1                                           # 23.98 carrier
        cam.apply(recipe(*V1_ARGS, fps=Fraction(23976, 1000))[0])
        self.assertTrue(MEM <= cam.call(PICKER, 0, TAB3, cam.key('UHD23_98')) < MEM + 0x8000)
        self.assertFalse(MEM <= cam.call(PICKER, 0, TAB3, cam.key('FHD23_98X')) < MEM + 0x8000)

    def test_the_virtual_profile_is_isp_formula_row_over_profile_171(self):
        cam = self.live()
        sel, c, plan, rows, spec = recipe(*V1_ARGS)
        want = F.row(spec, profile_rows()[171])
        want[0x30 // 4] = f32(30.0)
        got = cam.canvas(cam.status()['pid'])
        self.assertEqual(got[:65], want)
        self.assertEqual(got[65:], [0x17B0, 0xFCA])
        ref = Cam()
        self.assertEqual(cam.canvas(175), ref.canvas(175), 'a stock profile untouched')
        sb = F.plan(spec).standby
        for pid in (5, 210, 227, 257, 258, 259):
            g, r = cam.canvas(pid), ref.canvas(pid)
            self.assertEqual((g[8], g[10]), tuple(sb), pid)
            self.assertEqual(g[:8] + [g[9]] + g[11:], r[:8] + [r[9]] + r[11:], pid)
        self.assertEqual(cam.canvas(83), ref.canvas(83), 'stills p83 untouched')

    def test_lv_descriptors_aspect_and_ratio_follow_the_record(self):
        import isp_custom as IC
        cam = self.live()
        sel, c, plan, rows, spec = recipe(*V1_ARGS)
        p = F.plan(spec)
        a = float(Fraction(*p.rec))
        rules = IC.lvout_rules(a)
        disp = IC.display_diffs(a)
        self.assertTrue(rules and disp)
        pairs = 0xC3E05000
        for idx, (w, h), (nw, nh) in ((0, (1620, 911), rules[0][4:]), (2, (320, 180), rules[2][4:] if len(rules) > 2 else None)):
            d = 0xC3E05100 + 0x40 * idx
            stockd = [w, h, 0, 0, w, h, 7, 4, 0x3FC000, 1, 1]
            cam.mu.mem_write(d, struct.pack('<11I', *stockd))
            cam.put(pairs + 8 * idx, d)
            got = cam.call(OUT, pairs, idx)
            if nw is None:
                self.assertEqual(got, d)
                continue
            self.assertNotEqual(got, d)
            self.assertEqual(list(struct.unpack('<11I', cam.mu.mem_read(got, 44))), [nw, nh, 0, 0, nw, nh] + stockd[6:])
            self.assertEqual(list(struct.unpack('<11I', cam.mu.mem_read(d, 44))), stockd, 'the stock descriptor untouched')
        # the aspect fit: mov r0, #3; bl c02dafa0 -> our pair
        cam.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
        cam.mu.emu_start(0xC0306EA0, 0xC0306EA8, count=100000)
        pr = cam.r(UC_ARM_REG_R0)
        self.assertEqual(list(struct.unpack('<2I', cam.mu.mem_read(pr, 8))), [disp[0][2], disp[1][2]])
        self.assertEqual(struct.unpack('<2I', cam.mu.mem_read(cam.call(RATIO, 3), 8)), (16, 9), 'enum 3 stays stock')

    def test_v32_writes_no_window_for_our_ids_and_vpro_gives_row_171(self):
        cam = self.live()
        st = cam.status()
        entered = []
        h = cam.mu.hook_add(UC_HOOK_CODE, lambda uc, a, z, d: entered.append(a), begin=0xC03249A4, end=0xC03249A4)
        cam.put(IMAGER + 4, st['mode_id'])
        cam.sensor = []
        cam.call(0xC03249A0, IMAGER, 1)
        cam.mu.hook_del(h)
        self.assertEqual((cam.sensor, entered), ([], []), 'our id: the stock v32 body never runs, no window write')
        # zg: `bl c03212f8` (the current mode, [r0 + 4]) in FUN_c031b3a0 -> the donor for our ids
        sel, c, plan, rows, spec = recipe(*V1_ARGS)
        for mode, want in ((st['mode_id'], plan['donor']), (106, 106)):
            cam.put(IMAGER + 4, mode)
            cam.mu.reg_write(UC_ARM_REG_R0, IMAGER)
            cam.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
            cam.mu.emu_start(0xC031B660, 0xC031B664, count=10000)
            self.assertEqual(cam.r(UC_ARM_REG_R0), want, mode)
        for pid, want in ((st['pid'], iw(MAPPING + 4 * 171)), (175, iw(MAPPING + 4 * 175))):
            cam.mu.reg_write(UC_ARM_REG_R5, pid)
            cam.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
            cam.mu.emu_start(0xC043A184, 0xC043A190, count=10000)
            self.assertEqual(cam.r(UC_ARM_REG_R1), want, pid)

    def test_a_tall_record_gets_a_narrow_lv_box(self):
        import isp_custom as IC
        args = (4032, 4032, 2016, 2016, '2x2', 12)
        cam = self.live(args)
        sel, c, plan, rows, spec = recipe(*args)
        p = F.plan(spec)
        a = float(Fraction(*p.rec))
        nw, nh = IC.lvout_rules(a)[0][4:]
        self.assertLess(nw, 1620)
        d, pairs = 0xC3E05100, 0xC3E05000
        stockd = [1620, 911, 0, 0, 1620, 911, 7, 4, 0x3FC000, 1, 1]
        cam.mu.mem_write(d, struct.pack('<11I', *stockd))
        cam.put(pairs, d)
        got = cam.call(OUT, pairs, 0)
        self.assertEqual(list(struct.unpack('<11I', cam.mu.mem_read(got, 44))), [nw, nh, 0, 0, nw, nh] + stockd[6:])

    def test_standby_runs_our_mode_on_profile_5_with_the_preview_words(self):
        cam = self.live()
        sel, c, plan, rows, spec = recipe(*V1_ARGS)
        st = cam.status()
        spid = st['pid'] + 2
        for key in ('MOV', 'MOVAF60', 'MOVAF30CROP', 'MOVEIS'):
            e = cam.call(PICKER, 0, TABS, cam.key(key))
            self.assertTrue(MEM <= e < MEM + 0x8000, key)
            self.assertEqual([cam.w(e + 4 * i) for i in range(3)], [1, spid, st['mode_id']], key)
        self.assertEqual(bytes(cam.mu.mem_read(cam.w(e + 12), 6)), b'SLMOV\0')
        ref0 = Cam()
        for key in ('MAG4', 'MAG8CROP'):
            self.assertEqual(cam.call(PICKER, 0, TABS, cam.key(key)), ref0.call(PICKER, 0, TABS, ref0.key(key)),
                             f'{key}: the magnifier keeps the stock answer')
        self.assertEqual(cam.status()['standby_picks'], 4)
        want = list(profile_rows()[5])
        words = F.plan(spec).words
        for off in (0x0C, 0x10, 0x1C, 0x20, 0x28, 0x38, 0x58, 0x60, 0xC4, 0xD0, 0xF4, 0xF8, 0xFC, 0x100):
            if off in words:
                want[off // 4] = words[off]
        want[0x30 // 4] = f32(30.0)
        got = cam.canvas(spid)
        self.assertEqual(got[:65], want)
        self.assertEqual(got[65:], [0x17B0, 0xFCA])
        self.assertEqual((got[0], got[1], got[0x80 // 4], got[0x90 // 4]), (0, 0, 10, 0), 'no record, LV planes')
        # the standby profile is not "raw movie" (gs answers only the record pid)
        cam.put(LV_MGR + 8, 0xC3E07000)
        cam.put(0xC3E07000, st['pid'])
        self.assertEqual(cam.call(0xC03A6DD8), 1)
        cam.put(0xC3E07000, spid)
        down = []
        h = cam.mu.hook_add(UC_HOOK_CODE, lambda uc, a_, z, d: (down.append(a_), uc.emu_stop()), begin=0xC03A6DDC, end=0xC03A6DDC)
        cam.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
        cam.mu.reg_write(UC_ARM_REG_LR, DONE)
        cam.mu.emu_start(0xC03A6DD8, DONE, count=100000)
        cam.mu.hook_del(h)
        self.assertEqual(down, [0xC03A6DDC], 'the standby pid goes to the stock gain class')
        # standby 0 (v0.7.2test): refused -- a stock standby would switch readout at REC start; everything stock
        ref = Cam()
        self.assertEqual(cam.apply(sel, standby=0), AP_E['STANDBY'])
        e = cam.call(PICKER, 0, TABS, cam.key('MOV'))
        self.assertTrue(TABS <= e < TABS + 0x300)
        self.assertEqual(cam.canvas(5), ref.canvas(5), 'stock standby profile, stock framing')

    def test_a_fast_recipe_rides_119_88_with_the_real_engine_rate_and_the_clock_open(self):
        fast = recipe(6048, 4040, 2016, 1346, '2x3', 11, fps=Fraction(144))
        cam = Cam()
        cam.init()
        self.assertEqual(cam.apply(fast[0]), AP_OK)
        st = cam.status()
        self.assertEqual((cam.fr, st['carrier'], st['carrier_sets'], st['fast']), (7, 7, 1, 1))
        self.assertEqual(cam.w(CLK_SITE), CLK_OPEN)
        self.assertIn('ICACHE', cam.names())
        real = CLK / (fast[0]['hm'] * fast[0]['vmax'])
        self.assertEqual(cam.canvas(st['pid'])[0x30 // 4], f32(real))
        self.assertTrue(MEM <= cam.call(PICKER, 0, TAB3, cam.key('FHD120')) < MEM + 0x8000)
        names = cam.names()
        i_set, i_start = len(names) - 1 - names[::-1].index('FR_SET'), len(names) - 1 - names[::-1].index('LV_START')
        self.assertLess(names.index('LV_STOP'), i_set)
        self.assertLess(i_set, i_start, 'the carrier is set while the LV is down')
        self.assertIn('EXCL_RECOMPUTE', names[i_set:])
        self.assertEqual(cam.apply(recipe(*V1_ARGS)[0]), AP_OK)
        self.assertEqual((cam.fr, cam.w(CLK_SITE), cam.status()['fast']), (3, CLK_STOCK, 0))
        cam.apply(fast[0])
        self.assertEqual(cam.w(CLK_SITE), CLK_OPEN)
        cam.apply(fast[0], valid=0)
        self.assertEqual(cam.w(CLK_SITE), CLK_STOCK, 'stock: the gate back')

    def rec_start(self, cam, key='UHD30'):
        """the TAB3 answer in standby, then with the recording flag up (REC start: no commit, no LV stop / start)"""
        rec = MOVREC_DEFAULT & ~3, 1 << (8 * (MOVREC_DEFAULT & 3))
        before = cam.call(PICKER, 0, TAB3, cam.key(key))
        cam.put(*rec)
        during = cam.call(PICKER, 0, TAB3, cam.key(key))
        cam.put(rec[0], 0)
        after = cam.call(PICKER, 0, TAB3, cam.key(key))
        return before, during, after

    def test_rec_start_never_changes_the_route(self):
        """v0.7.2test (live2 item 14: HD 2K 11b 3x2, standby gated to the stock route, REC start froze the camera): the
        TAB3 answer is the same before, during and after a recording -- REC start never switches readout outside a
        commit.  standby, AP_E_STANDBY (stock before and after) and the HD 3x2 family (ours before and after)."""
        cam = self.live()
        b, d, a = self.rec_start(cam)
        self.assertTrue(MEM <= b < MEM + 0x8000)
        self.assertEqual((d, a), (b, b))
        st = cam.status()
        self.assertEqual((st['standby_picks'], st['picks'], st['gated']), (2, 3, 0), 'standby picks: not while recording')
        ref = Cam()
        stock = ref.call(PICKER, 0, TAB3, ref.key('UHD30'))
        self.assertEqual(cam.apply(recipe(*V1_ARGS)[0], standby=0), AP_E['STANDBY'])
        self.assertEqual(self.rec_start(cam), (stock, stock, stock), 'refused: stock all through')
        st = cam.status()
        self.assertEqual((st['active'], st['gated'], st['result']), (0, 1, AP_E['STANDBY']))
        for bits in (12, 11):
            off = recipe(6048, 3402, 2016, 1134, '3x2', bits)
            p = F.plan(off[4])
            self.assertEqual((p.visible[1], p.source[1]), (1686, 1702), 'the live2 family: over 1334, inside R12')
            cam2 = Cam()
            cam2.init()
            self.assertEqual(cam2.apply(off[0]), AP_OK, bits)
            b, d, a = self.rec_start(cam2)
            self.assertTrue(MEM <= b < MEM + 0x8000, 'standby runs our readout (isp-lab p5: 1686 ran)')
            self.assertEqual((d, a), (b, b), bits)
            self.assertEqual(cam2.status()['gated'], 0)
            g = cam2.canvas(cam2.status()['pid'])
            self.assertEqual((g[0x28 // 4], g[0x10 // 4]), (p.visible[1], p.raster[1]), 'standby = the record words')

    def test_a_refused_selection_keeps_the_stock_lv_shape_through_rec_start(self):
        """v0.7.1test squeezed a stock readout under our LV box; v0.7.2test refuses the selection, so the LV box and the
        aspect stay stock in standby and while recording."""
        rec = MOVREC_DEFAULT & ~3, 1 << (8 * (MOVREC_DEFAULT & 3))
        cam = Cam()
        cam.init()
        self.assertEqual(cam.apply(recipe(*V1_ARGS)[0], standby=0), AP_E['STANDBY'])
        pairs, d = 0xC3E05000, 0xC3E05100
        stockd = [1620, 911, 0, 0, 1620, 911, 7, 4, 0x3FC000, 1, 1]
        cam.mu.mem_write(d, struct.pack('<11I', *stockd))
        cam.put(pairs, d)
        def shape(c):
            c.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
            c.mu.emu_start(0xC0306EA0, 0xC0306EA8, count=100000)
            pr = c.r(UC_ARM_REG_R0)
            return c.call(OUT, pairs, 0), tuple(struct.unpack('<2I', c.mu.mem_read(pr, 8)))
        self.assertEqual(shape(cam), (d, (16, 9)), 'standby: the stock LV box and fit')
        cam.put(*rec)
        self.assertEqual(shape(cam), (d, (16, 9)), 'recording: still stock')
        cam.put(rec[0], 0)
        self.assertEqual(cam.apply(recipe(*V1_ARGS)[0]), AP_OK)
        got, pair = shape(cam)
        self.assertNotEqual(got, d, 'ours: our LV box')
        self.assertNotEqual(pair, (16, 9))

    def test_a_visible_one_row_past_the_cap_runs_standby_cut_to_it(self):
        """v0.7.1test: OG 6016 x 4040 1:1 14-bit previews 1984 x 1335; the stock standby cap is 1334.  Standby runs our
        readout with the visible (and raster) one row shorter; recording keeps the formula's words."""
        rec = MOVREC_DEFAULT & ~3, 1 << (8 * (MOVREC_DEFAULT & 3))
        sel, c, plan, rows, spec = recipe(6016, 4040, 6016, 4040, '1x1', 14)
        p = F.plan(spec)
        self.assertEqual(p.visible[1], 1335)
        cam = Cam()
        cam.init()
        self.assertEqual(cam.apply(sel), AP_OK)
        self.assertTrue(MEM <= cam.call(PICKER, 0, TAB3, cam.key('UHD30')) < MEM + 0x8000, 'standby: ours (not gated)')
        self.assertEqual(cam.status()['gated'], 0)
        pid = cam.status()['pid']
        g = cam.canvas(pid)
        self.assertEqual((g[0x20 // 4], g[0x28 // 4], g[0x0C // 4], g[0x10 // 4]),
                         (p.visible[0], 1334, p.raster[0], p.raster[1] - 1))
        self.assertEqual(g[0x00 // 4:0x08 // 4], list(p.rec), 'the record words are the formula\'s')
        cam.put(*rec)
        g = cam.canvas(pid)
        self.assertEqual((g[0x28 // 4], g[0x10 // 4]), (p.visible[1], p.raster[1]), 'recording: the formula\'s words')

    def test_true_14_bit_gets_the_14_bit_black_level_and_scaled_14_a_12_bit_container(self):
        def blk_bits(c, site_from, field):
            obj = 0xC3E09000
            c.put(obj + field, 0)                            # the RAW descriptor's plane enum 0 -> 12 bits stock
            c.mu.reg_write(UC_ARM_REG_R0, obj)
            c.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
            c.mu.emu_start(site_from, site_from + 8, count=10000)
            return c.r(UC_ARM_REG_R0)
        true14 = recipe(6048, 4040, 6048, 4040, '1x1', 14, fps=Fraction(15))
        cam = Cam()
        cam.init()
        self.assertEqual(cam.apply(true14[0]), AP_OK)
        g = cam.canvas(cam.status()['pid'])
        self.assertEqual((g[0x80 // 4], g[0x84 // 4]), (7, 8), 'true 14: the 14-bit plane')
        self.assertEqual((blk_bits(cam, 0xC02CA1BC, 0x24), blk_bits(cam, 0xC02CA218, 0x08)), (12, 12), 'not picked: stock')
        cam.call(PICKER, 0, TAB3, cam.key('UHD24'))       # 15 fps rides the 23.98 carrier ("23_98")
        cam.call(PICKER, 0, TAB3, cam.key('UHD23_98'))
        self.assertEqual((blk_bits(cam, 0xC02CA1BC, 0x24), blk_bits(cam, 0xC02CA218, 0x08)), (14, 14))
        self.assertGreaterEqual(cam.status()['blacks'], 2)
        scaled = recipe(6048, 4040, 3024, 2020, '1x1', 14, fps=Fraction(15))
        self.assertEqual(cam.apply(scaled[0]), AP_OK)
        g = cam.canvas(cam.status()['pid'])
        self.assertEqual((g[0x80 // 4], g[0x84 // 4]), (7, 7), 'scaled 14-bit AD: the 12-bit plane (container)')
        cam.call(PICKER, 0, TAB3, cam.key('UHD23_98'))
        self.assertEqual(blk_bits(cam, 0xC02CA218, 0x08), 12, 'a 12-bit container keeps the 12-bit black')
        # the sensor side is still the 14-bit AD readout
        self.assertEqual(cam.row_via_lookup(0, cam.status()['mode_id']), with_id(scaled[3]['TIM'], cam.status()['mode_id']))

    def test_frame_rate_gates_widen_only_for_the_live_carrier(self):
        def frmax(c, v):
            c.mu.reg_write(UC_ARM_REG_R4, v)
            c.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
            c.mu.emu_start(0xC00A87E4, 0xC00A87E8, count=1000)
            return c.r(UC_ARM_REG_R1)

        def frclass(c, v):
            c.mu.reg_write(UC_ARM_REG_R1, v)
            c.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
            c.mu.emu_start(0xC04A121C, 0xC04A1220, count=1000)
            return c.r(UC_ARM_REG_R0)
        rank = {0: 1500, 1: 2398, 12: 2400, 2: 2500, 3: 2997, 13: 4800, 4: 5000, 5: 5994, 6: 10000, 7: 11988}
        cmax = {0: 7, 5: 6, 3: 5, 1: 3, 4: 2, 2: 1}
        cam = Cam()
        cam.init()
        for v in (1, 3, 5, 7):
            self.assertEqual(frmax(cam, v), v, 'nothing live: stock')
        for v in range(6):
            self.assertEqual(frclass(cam, v), v)
        fast = recipe(6048, 4040, 2016, 1346, '2x3', 11, fps=Fraction(144))
        for sel, car in ((fast[0], 7), (recipe(*V1_ARGS)[0], 3)):
            self.assertEqual(cam.apply(sel), AP_OK)
            for v in (0, 1, 3, 5, 6, 7):
                self.assertEqual(frmax(cam, v), car if rank[v] < rank[car] else v, (car, v))
            for v in range(6):
                got = frclass(cam, v)
                if rank[cmax[v]] >= rank[car]:
                    self.assertEqual(got, v, (car, v))
                else:
                    ok = [c for c in cmax if rank[cmax[c]] >= rank[car]]
                    self.assertEqual(got, min(ok, key=lambda c: rank[cmax[c]]), (car, v))
        cam.apply(fast[0], valid=0)
        self.assertEqual((frmax(cam, 3), frclass(cam, 1)), (3, 1), 'stock again')

    def test_dng_rate_and_binfilt(self):
        import isp_custom as IC
        cam = Cam()
        cam.init()
        native = WORK + 0x6000                               # the layer below: writes the carrier's rational
        cam.stub(native, 'NATIVE_RATE')
        ven = MEM + cam.fn('ap_sizes_t', 7)
        cam.put(ven + 16 * 88 + 17 * 4, native)              # H_RECRATE's down
        out = WORK + 0x6100
        self.assertEqual(cam.call(0xC00C9BD0, out), 0x77)
        self.assertEqual(struct.unpack('<2I', cam.mu.mem_read(out, 8)), (30000, 1001), 'not live: native')
        sel = recipe(*V1_ARGS, fps=Fraction(48713, 1000))[0]
        cam.native = (50, 1)                                 # 48.713 rides the 50 carrier
        self.assertEqual(cam.apply(sel), AP_OK)
        self.assertEqual(cam.fr, 4, 'the native setter put the carrier in')
        cam.call(PICKER, 0, TAB3, cam.key('UHD50'))
        cam.put(ven + 16 * 88 + 17 * 4, native)
        self.assertEqual(cam.call(0xC00C9BD0, out), 0x77)
        got = struct.unpack('<2I', cam.mu.mem_read(out, 8))
        real = Fraction(CLK, sel['hm'] * sel['vmax'])
        self.assertEqual(Fraction(*got), real if abs(real / Fraction(48713, 1000) - 1) > Fraction(1, 20000) else Fraction(48713, 1000))
        # binfilt: an H-bin recipe; the kernel writers' driver bytes (res-custom ogc_binkernel)
        args = (6048, 4040, 2016, 1346, '2x2', 12)
        cs = [c for c in Q.qualities(6048, 4040, 2016, 1346, None, 0.02) if c['hbin'] == 3]
        if cs:
            c = cs[0]
            self.assertEqual(IC.binfilt_cfg((c['hbin'], c['vbin']), {'h': 2, 'v': 1, 'm': 1}) & 0xFFF,
                             0x800 | 0x200 | (0x400 if c['vbin'] == 3 else 0) | 1 << 8 | 2 | 1 << 4)
        del args


def iw_base(cam, field):
    return cam.w(DESC + field)


READERS = [(0xC0320740, 'i'), (0xC03208B0, 'i', 1000000, 0), (0xC03208B0, 'i', 10, 1), (0xC0320818, 'i', 1000000, 0),
           (0xC03258C8, 'h', 'm'), (0xC0321160, 'i', 'm'), (0xC031FFA0, 'i', 'm')]


def automap(uc, access, addr, size, value, data):
    try:
        uc.mem_map(addr & ~0xFFFF, 0x10000)
        return True
    except Exception:
        return False


def programming(cam, mode):
    """res-custom ProgrammingTests.programming: the mode set (C0321290) and the readers, every sensor write."""
    def unmapped(uc, access, addr, size, value, data):
        try:
            uc.mem_map(addr & ~0xFFFF, 0x10000)
            return True
        except Exception:
            return False
    h = cam.mu.hook_add(UC_HOOK_MEM_UNMAPPED, unmapped)
    out = []
    cam.sensor = []
    try:
        cam.put(IMAGER + 4, mode)
        cam.call(0xC0321290, IMAGER, mode)
        for f, *args in READERS:
            vals = [{'i': IMAGER, 'h': HOLDER, 'm': mode}.get(x, x) for x in args]
            out.append((hex(f), cam.call(f, *vals)))
    finally:
        cam.mu.hook_del(h)
    return out, list(cam.sensor)


class TransactionTests(unittest.TestCase):
    def armed(self):
        cam = Cam()
        self.assertEqual(cam.init(), AP_OK)
        return cam

    def test_the_change_event_commits_at_once_and_identical_is_idle(self):
        cam = self.armed()
        sel = recipe(*V1_ARGS)[0]
        self.assertEqual(cam.request(sel), AP_OK)
        self.assertEqual([x for x in cam.names() if x in ('CS_GET', 'CS_SET', 'LV_STOP', 'LV_START')],
                         ['CS_GET', 'CS_SET', 'LV_STOP', 'LV_START', 'CS_SET'])
        self.assertEqual(cam.request(sel), AP_IDLE)
        self.assertEqual(cam.flush(), AP_IDLE)
        self.assertEqual(cam.names().count('LV_STOP'), 1, 'no LV flash for the same selection')
        self.assertEqual(cam.request(sel, km=1), AP_OK)
        self.assertEqual(cam.status()['commits'], 2)
        self.assertNotIn(('MISALIGNED',), [c[:1] for c in cam.calls])

    def test_a_request_during_a_commit_is_committed_once_more_after_it(self):
        """Rapid dialing: a newer selection arriving while a commit runs (simulated at LV_STOP: what ap_request does
        when in_commit is set -- replace `want`, bump seq) is committed once, right after, and only the latest."""
        cam = self.armed()
        a, b = recipe(*V1_ARGS)[0], recipe(*ALT_ARGS)[0]
        c = dict(a, vmax=a['vmax'] + 7)                    # a third, different selection (the latest)
        want, seq = cam.off(12), cam.off(13)
        steps = [b, c]

        def nested(cm):
            if steps:
                x = steps.pop(0)
                cm.mu.mem_write(want, sel_bytes(x))
                cm.put(seq, cm.w(seq) + 1)
        cam.on_stop = nested
        self.assertEqual(cam.request(a), AP_OK)
        st = cam.status()
        self.assertEqual(st['commits'], 3, 'a, then b, then the latest (c)')
        self.assertEqual(struct.unpack_from('<H', cam.row_via_lookup(0, st['mode_id']), 8)[0], c['vmax'], 'c is live')
        self.assertEqual(cam.names().count('LV_STOP'), 3)
        self.assertEqual((st['owed'], cam.w(cam.off(14))), (0, 0), 'in_commit released')
        # a request while a commit is marked running only stores it
        cam.put(cam.off(14), 1)
        n = cam.names().count('LV_STOP')
        self.assertEqual(cam.request(b), AP_PENDING)
        self.assertEqual(cam.names().count('LV_STOP'), n)
        cam.put(cam.off(14), 0)
        self.assertEqual(cam.flush(), AP_OK)
        self.assertEqual(cam.row_via_lookup(0, cam.status()['mode_id']), with_id(recipe(*ALT_ARGS)[3]['TIM'], cam.status()['mode_id']))

    def test_never_while_recording_owed_until_flush(self):
        cam = self.armed()
        cam.put(MOVREC_DEFAULT & ~3, 1 << (8 * (MOVREC_DEFAULT & 3)))
        sel = recipe(*V1_ARGS)[0]
        self.assertEqual(cam.request(sel), AP_PENDING)
        self.assertEqual(cam.flush(), AP_PENDING)
        self.assertNotIn('LV_STOP', cam.names())
        self.assertEqual(cam.status()['active'], 0)
        cam.put(MOVREC_DEFAULT & ~3, 0)
        self.assertEqual(cam.flush(), AP_OK)
        self.assertEqual(cam.status()['active'], 1)

    def test_recording_starting_inside_the_commit_leaves_stock_and_owes(self):
        cam = self.armed()
        cam.on_stop = lambda c: c.put(XMP_FOBJ, 0x1234)
        self.assertEqual(cam.apply(recipe(*V1_ARGS)[0]), AP_E['BUSY'])
        st = cam.status()
        self.assertEqual((st['active'], st['owed']), (0, 1))
        self.assertEqual(cam.names().count('LV_START'), 1, 'the LV comes back')
        self.assertFalse(MEM <= cam.call(PICKER, 0, TAB3, cam.key('UHD30')) < MEM + 0x8000)

    def test_any_failure_restores_stock(self):
        sel = recipe(*V1_ARGS)[0]
        for what, setup, want in (
                ('recipe', lambda c: None, dict(key=0x7FFF)),
                ('hmax', lambda c: None, dict(hm=sel['hm'] + 1)),
                ('vmax', lambda c: None, dict(vmax=99999)),
                ('rate', lambda c: (setattr(c, 'fr', 1), setattr(c, 'fr_refuse', True)), dict(km=1)),
                ('format', lambda c: setattr(c, 'fmt', 1), dict(km=1)),
                ('mov', lambda c: None, dict(fmt=1)),
                ('notready', lambda c: c.put(IMAGER, 0), dict(km=1)),
                ('invalid', lambda c: None, dict(valid=0))):
            cam = self.armed()
            self.assertEqual(cam.apply(sel), AP_OK)
            stops = cam.names().count('LV_STOP')
            setup(cam)
            rc = cam.apply(sel, **want)
            expect = {'recipe': AP_E['RECIPE'], 'hmax': AP_E['RECIPE'], 'vmax': AP_E['RECIPE'], 'rate': AP_E['RATE'],
                      'format': AP_E['FORMAT'], 'mov': AP_E['FORMAT'], 'notready': AP_E['NOTREADY'], 'invalid': AP_OK}[what]
            self.assertEqual(rc, expect, what)
            st = cam.status()
            self.assertEqual(st['active'], 0, what)
            self.assertEqual(cam.names().count('LV_STOP'), stops + 1, f'{what}: LV reloaded onto stock')
            cam.put(IMAGER, DESC)
            self.assertFalse(MEM <= cam.call(PICKER, 0, TAB3, cam.key('UHD30')) < MEM + 0x8000, what)

    def test_two_ids_rotate_and_the_old_slot_survives_one_commit(self):
        cam = self.armed()
        a = recipe(*V1_ARGS)
        b = recipe(*ALT_ARGS)
        cam.apply(a[0])
        m1 = cam.status()['mode_id']
        cam.apply(b[0])
        m2 = cam.status()['mode_id']
        self.assertEqual({m1, m2}, {230, 231})
        self.assertEqual(cam.row_via_lookup(0, m1), with_id(a[3]['TIM'], m1), 'old slot intact')
        self.assertEqual(cam.row_via_lookup(0, m2), with_id(b[3]['TIM'], m2))
        cam.apply(a[0], km=1)
        self.assertEqual(cam.status()['mode_id'], m1)
        self.assertEqual(cam.row_via_lookup(0, m2), with_id(b[3]['TIM'], m2), 'previous slot intact')

    def test_lv_not_running_flips_without_reload(self):
        cam = self.armed()
        cam.lv_on = False
        self.assertEqual(cam.apply(recipe(*V1_ARGS)[0]), AP_OK)
        self.assertNotIn('LV_STOP', cam.names())
        self.assertEqual(cam.status()['active'], 1)


def default_pick(cs, dcw, dch, rw, rh):
    """slqs.c defaultPick over the presets (1x1 CRCT): |DC_h - mv RES_h|, recorded bits desc, |DC_w - mh RES_w|, RS desc"""
    import readout_cfg as RCF
    def rbits(c):
        return 14 if c['bits'] == 14 and tuple(c['zoom']) == (1024, 1024) and c['hbin'] == c['vbin'] == 1 else 12
    def key(c):
        r = RCF.BY_KEY[c['readout'][0]]
        rs = Q.hmax_of(c) * Q._replay(c)['receiver_lines']
        return (abs(dch - r['mv'] * rh), -rbits(c), abs(dcw - r['mh'] * rw), -rs)
    pre = [c for c in cs if c['hbin'] == c['vbin'] == 1] or cs
    return min(pre, key=key)


def apc_run(lib, dc, rs, c, fps=Fraction(2997, 100)):
    """apc_build on the host for case c: (attrs[25], tail dict) or None when the rate is out of the case's range"""
    hm = Q.hmax_of(c)
    lo, _, _ = Q.vmax_range(c)
    v = max(lo, -(-CLK * fps.denominator // (hm * fps.numerator)))
    if v > 16384:
        return None
    key = lib.core_key_index(c['readout'][0].encode())
    args = (ctypes.c_uint32 * 14)(*dc, *rs, key, c["hbin"], c["vbin"], hm, v, fps.numerator, fps.denominator, 2, 3, 1)
    w = ctypes.create_string_buffer(lib.apc_sizes(0))
    o = ctypes.create_string_buffer(lib.apc_sizes(1))
    rc = lib.apc_build_host(args, w, o)
    assert rc == 0, (dc, rs, c['readout_id'], rc)
    ob = o.raw
    attrs = struct.unpack_from('<25i', ob, 0)
    at = 25 * 4 + 0x20 + 100 + 0x28 + 0x38 + 0x14 + 0x68 + 0x288 + 8
    base = (at + 3) & ~3
    tail = struct.unpack_from('<8I6s2x65I3I14I', ob, base)
    rec_w, rec_h, sb_w, sb_h, asp_n, asp_d, is169 = tail[77:84]
    more = struct.unpack_from('<23I', ob, base + struct.calcsize('<8I6s2x65I3I14I'))
    fast, sok, rok = more[0], more[1], more[22]
    src, vis, ras = more[5:7], more[7:9], more[9:11]
    sv, sr, sclamp = more[17:19], more[19:21], more[21]
    return attrs, dict(rec=(rec_w, rec_h), asp=(asp_n, asp_d), is169=is169, sok=sok, rok=rok, src=src, vis=vis, ras=ras,
                       sv=sv, sr=sr, sclamp=sclamp)


class DcSweepTests(unittest.TestCase):
    """v0.7.1test (Bei 10-30 live: OG width 6048 -> 5008 and heights 4040 -> 3030 in standby squeezed the picture
    instead of cropping it).  For every OG DC width 6048..4000 (16 px) and height 4040..3000 (2 px), at RES = DC,
    DC / 1.5 and DC / 3, the recipe the QS picks by default: the readout's source window (TIM raster x merge) is the
    DC (one raster quantum wide, the 2 % visible tolerance tall), centred, the display aspect is the source's, and
    the standby runs our readout (the gate is on) unless a hard rule refuses it."""

    def sweep(self):
        import readout_cfg as RCF
        lib = host()
        cells = [(w, 4040) for w in range(6048, 3999, -16)] + [(6048, h) for h in range(4040, 2999, -2)]
        n = 0
        bad = []
        for dcw, dch in cells:
            for div in (1, 1.5, 3):
                rw = int(dcw / div / 16 + 0.5) * 16
                rh = int(dch / div / 2 + 0.5) * 2
                cs = Q.qualities(dcw, dch, rw, rh, None, 0.02)
                if not cs:
                    continue
                c = default_pick(cs, dcw, dch, rw, rh)
                got = apc_run(lib, (dcw, dch), (rw, rh), c)
                if got is None:
                    continue
                attrs, t = got
                r = RCF.BY_KEY[c['readout'][0]]
                plan = Q._replay(c)
                fov_w = (attrs[12] - attrs[11]) * r['mh']           # TIM x1 - x0: the raster the ISP gets
                fov_h = attrs[6] * r['mv']
                n += 1
                why = []
                if attrs[12] - attrs[11] != plan['raster_w'] or attrs[5] != plan['raster_w']:
                    why.append('TIM width is not the raster')
                if not (0 <= fov_w - dcw < 16 * r['mh'] + 16 or abs(fov_w - dcw) <= 16):
                    why.append(f'width {fov_w} for DC {dcw}')
                if not (-0.021 * dch <= fov_h - dch <= 2 * r['mv'] + 2):
                    why.append(f'height {fov_h} for DC {dch}')
                a = Fraction(t['asp'][0], t['asp'][1])
                if not t['is169'] and abs(a / Fraction(fov_w, fov_h) - 1) > Fraction(1, 50):
                    why.append(f'display aspect {float(a):.4f} vs source {fov_w / fov_h:.4f}')
                hard = (t['src'][0] > 2100 or t['src'][1] > 1710 or t['sr'][0] > t['src'][0] or
                        t['sr'][1] > t['src'][1] or t['vis'][0] > 2008 or t['vis'][1] > 1342)
                if not t['rok'] and not hard:
                    why.append(f'standby gated: vis {t["vis"]} sv {t["sv"]}')
                if not t['rok']:
                    why.append('refused (AP_E_STANDBY): the QS offers it')
                if bool(t['sok']) != bool(t['rok'] and t['sv'][0] <= 2000 and t['sv'][1] <= 1334):
                    why.append(f'MOV standby gate {t["sok"]} for sv {t["sv"]}')
                if 1334 < t['vis'][1] <= 1342 and t['sv'][1] != 1334:
                    why.append(f'visible {t["vis"]} not cut to 1334 in standby: sv {t["sv"]}')
                if t['sok'] and (t['sv'][0] > 2000 or t['sv'][1] > 1334):
                    why.append('standby visible past the cap')
                if why:
                    bad.append((dcw, dch, rw, rh, c['readout_id'], why))
        return n, bad

    def test_every_og_width_and_height_crops_the_source_and_keeps_standby(self):
        n, bad = self.sweep()
        self.assertGreater(n, 1500)
        self.assertEqual(bad[:10], [], f'{len(bad)} of {n} cells')


class RouteSweepTests(unittest.TestCase):
    """v0.7.2test (live2 item 14): every recipe the QS lists -- the six DC presets x every RES of res_list x every
    quality -- passes the route gate (rok), so no QS selection is refused with AP_E_STANDBY and no standby runs the
    stock route under a SensorLab record.  The HD 3x2 family (visible 1671..1686) is in it."""

    def test_every_qs_recipe_can_run_standby(self):
        sys.path.insert(0, str(HERE.parent / 'qs'))
        import slqs_ref as R
        lib = BA.host()
        lib.core_key_index.argtypes = [ctypes.c_char_p]
        n, tall, bad = 0, 0, []
        for _, W, H in R.DCS:
            for it in R.res_list(W, H):
                for c in Q.qualities(W, H, it['w'], it['h'], None, 0.02):
                    got = apc_run(lib, (W, H), (it['w'], it['h']), c)
                    if got is None:
                        got = apc_run(lib, (W, H), (it['w'], it['h']), c, fps=Fraction(15))
                    if got is None:
                        continue
                    t = got[1]
                    n += 1
                    tall += t['vis'][1] > 1334
                    if not t['rok']:
                        bad.append((W, H, it['w'], it['h'], c['readout_id'], c['hbin'], c['vbin'], t['vis'], t['src']))
        self.assertGreater(n, 700)
        self.assertGreater(tall, 0, 'the sweep reaches visibles past 1334 (the HD 3x2 family)')
        self.assertEqual(bad[:5], [], f'{len(bad)} of {n}')


def standby_visible(p):
    """v0.7.1test: the standby copy of the preview visible / raster: a visible at most 8 past the stock standby cap
    2000 x 1334 is cut to it (the raster by as much); the record keeps the formula's"""
    sv, sr = list(p.visible), list(p.raster)
    for i, cap in ((0, 2000), (1, 1334)):
        if cap < sv[i] <= cap + 8:
            sr[i] -= sv[i] - cap
            sv[i] = cap
    return sv, sr


class CalcTests(unittest.TestCase):
    """The pure half on the host: every recipe of a few DC x RES, field by field against the Python."""
    CASES = [(6048, 4040, 2016, 1346), (6048, 4040, 3024, 2020), (6048, 3402, 3840, 2160), (4192, 2358, 2096, 1178),
             (2096, 1240, 2096, 1240), (4032, 4032, 2016, 2016),
             (6048, 4040, 2016, 1200), (6048, 4040, 2016, 1000),
             (6048, 4040, 2016, 800), (6048, 4040, 1600, 1346)]

    def run_case(self, lib, dc, rs, c, fps=Fraction(2997, 100)):
        import isp_custom as IC
        hm = Q.hmax_of(c)
        lo, _, _ = Q.vmax_range(c)
        v = max(lo, -(-CLK * fps.denominator // (hm * fps.numerator)))
        if v > 16384:
            return 0
        key = lib.core_key_index(c['readout'][0].encode())
        args = (ctypes.c_uint32 * 14)(*dc, *rs, key, c["hbin"], c["vbin"], hm, v, fps.numerator, fps.denominator, 2, 3, 1)
        w = ctypes.create_string_buffer(lib.apc_sizes(0))
        o = ctypes.create_string_buffer(lib.apc_sizes(1))
        rc = lib.apc_build_host(args, w, o)
        self.assertEqual(rc, 0, (dc, rs, c['readout_id']))
        plan, spec = Q.settings(c, CLK / (hm * v))
        spec = rec_spec(spec)
        spec = dataclasses.replace(spec, hirate=carrier_of(fps) in (6, 7))
        _, rows, _ = smc.create(plan)
        ob = o.raw
        mode = ob[:25 * 4 + 0x20 + 100 + 0x28 + 0x38 + 0x14 + 0x68 + 0x288 + 8]
        at = 25 * 4
        for t, n in (('TIM', 0x20), ('META', 100), ('R28', 0x28), ('R38', 0x38), ('R14', 0x14), ('R68', 0x68), ('REG', 0x288), ('R10', 8)):
            self.assertEqual(mode[at:at + n], bytes(rows[t]), (c['readout_id'], t))
            at += n
        tail = struct.unpack_from('<8I6s2x65I3I14I', ob, (at + 3) & ~3)
        p = F.plan(spec)
        isp, mask = list(tail[9:74]), tail[74:77]
        for off, val in p.words.items():
            self.assertTrue(mask[off // 128] >> ((off // 4) & 31) & 1, off)
            self.assertEqual(isp[off // 4], val, (c['readout_id'], hex(off)))
        self.assertEqual(sum(bin(m).count('1') for m in mask), len(p.words))
        rec_w, rec_h, sb_w, sb_h, asp_n, asp_d, is169, box_w, box_h, det_h, dng_n, dng_d, binf = tail[77:90]
        self.assertEqual((rec_w, rec_h), tuple(p.rec))
        self.assertEqual((sb_w, sb_h), tuple(p.standby))
        a = float(Fraction(*p.rec))
        self.assertEqual(Fraction(asp_n, asp_d), Fraction(*p.rec).limit_denominator(1000))
        rules = IC.lvout_rules(a)
        self.assertEqual(bool(is169), not rules, c['readout_id'])
        if rules:
            self.assertEqual((box_w, box_h), rules[0][4:])
            self.assertEqual(det_h, rules[2][5] if len(rules) > 2 else 0)
            d = IC.display_diffs(a)
            self.assertEqual((asp_n, asp_d), (d[0][2], d[1][2]), c['readout_id'])
        self.assertEqual(binf, IC.binfilt_cfg((c['hbin'], c['vbin']), {'h': 2, 'v': 3, 'm': 1}) if c['hbin'] == 3 or c['vbin'] == 3 else 0)
        real = Fraction(CLK, hm * v)
        bc = {Fraction(2997, 100): Fraction(30000, 1001)}.get(fps, fps)
        exp = real if abs(real / fps - 1) > Fraction(1, 20000) else bc
        self.assertEqual(Fraction(dng_n, dng_d), exp)
        head = struct.unpack_from('<8I', ob, (at + 3) & ~3)
        carrier, engine = head[4], head[6]
        self.assertEqual(carrier, carrier_of(fps))
        self.assertEqual(engine, f32(ENGINE[carrier]) if fps <= Fraction(120000, 1001) else f32(float(real)))
        fast, sok, *smask = struct.unpack_from('<5I', ob, ((at + 3) & ~3) + struct.calcsize('<8I6s2x65I3I14I'))
        rok, = struct.unpack_from('<I', ob, ((at + 3) & ~3) + struct.calcsize('<8I6s2x65I3I14I') + 22 * 4)
        sv, sr = standby_visible(p)
        gate = (p.source[0] <= 2100 and p.source[1] <= 1710 and sv[0] <= 2000 and sv[1] <= 1334 and
                sr[0] <= p.source[0] and sr[1] <= p.source[1])
        self.assertEqual(bool(sok), gate, c['readout_id'])
        route = (p.source[0] <= 2100 and p.source[1] <= 1710 and sv[0] <= 2000 and sr[0] <= p.source[0] and
                 sr[1] <= p.source[1])
        self.assertEqual(bool(rok), route, c['readout_id'])
        self.assertTrue(rok, ('v0.7.2test: every QS recipe can run standby', c['readout_id']))
        self.assertEqual(bool(fast), engine > f32(99.0))
        sw = {0x0C, 0x10, 0x1C, 0x20, 0x28, 0x38, 0x58, 0x60, 0xC4, 0xD0, 0xF4, 0xF8, 0xFC, 0x100} & set(p.words)
        self.assertEqual({4 * i for i in range(65) if smask[i >> 5] >> (i & 31) & 1}, sw)
        return 1

    def test_every_recipe_of_dc_res_cases_against_the_python(self):
        lib = BA.host()
        lib.core_key_index.argtypes = [ctypes.c_char_p]
        n = 0
        for dcw, dch, rw, rh in self.CASES:
            for c in Q.qualities(dcw, dch, rw, rh, None, 0.02):
                n += self.run_case(lib, (dcw, dch), (rw, rh), c)
        self.assertGreater(n, 60)

    def test_near_16_9_and_boxes_against_isp_custom(self):
        import isp_custom as IC
        lib = BA.host()
        o = ctypes.create_string_buffer(lib.apc_sizes(1))
        off = 1108 + 32 + 8 + 260 + 12
        for k in range(-160, 161):
            if abs(k) == 50:
                continue                                     # exactly 0.5 % off: Python's float decides by rounding error
            an, ad = 16 * 100000 + k * 160, 9 * 100000
            lib.apc_display_host(ctypes.c_uint64(an), ctypes.c_uint64(ad), o)
            _, _, _, _, asp_n, asp_d, is169, bw, bh, det = struct.unpack_from('<10I', o.raw, off)
            rules = IC.lvout_rules(an / ad)
            self.assertEqual(bool(is169), not rules, k)
            if rules:
                self.assertEqual((bw, bh), rules[0][4:], k)

    def test_carrier_and_f32(self):
        lib = BA.host()
        lib.apc_f32_host.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        import random
        rnd = random.Random(3)
        for _ in range(5000):
            n, d = rnd.randrange(1, 10 ** 9), rnd.randrange(1, 10 ** 9)
            self.assertEqual(lib.apc_f32_host(n, d), f32(n / d), (n, d))
        for n, d in ((2 ** 24 + 1, 1), (2 ** 24 + 3, 1), (2 ** 25 + 2, 1), (2 ** 25 + 6, 1), (3 * 2 ** 24 + 1, 2)):
            self.assertEqual(lib.apc_f32_host(n, d), f32(n / d), ('tie', n, d))
        std = [(23976, 1000), (24, 1), (25, 1), (2997, 100), (30, 1), (47952, 1000), (48, 1), (50, 1), (5994, 100), (60, 1),
               (72, 1), (90, 1), (100, 1), (11988, 100), (120, 1), (144, 1), (240, 1), (1000, 1), (48713, 1000), (17, 1),
               (2997093, 100000), (2997200, 100000), (2400100, 100000), (2400200, 100000), (11988710, 100000)]
        for n, d in std:
            self.assertEqual(lib.apc_carrier_host(n, d), carrier_of(Fraction(n, d)), (n, d))
        for _ in range(3000):
            n, d = rnd.randrange(1, 200000), rnd.randrange(1, 1001)
            self.assertEqual(lib.apc_carrier_host(n, d), carrier_of(Fraction(n, d)), (n, d))

    def test_the_standby_gate_against_its_rules(self):
        lib = BA.host()
        import random
        rnd = random.Random(5)
        edges = [(2100, 1710, 2000, 1334, 2100, 1710), (2101, 1710, 2000, 1334, 2016, 1344), (2016, 1711, 2000, 1334, 2016, 1344),
                 (2016, 1346, 2001, 1334, 2016, 1344), (2016, 1346, 2000, 1335, 2016, 1344), (2016, 1346, 2000, 1334, 2017, 1344),
                 (2016, 1346, 2000, 1334, 2016, 1347), (2016, 1346, 0, 1334, 2016, 1344)]
        for _ in range(4000):
            edges.append(tuple(rnd.randrange(0, 2300) for _ in range(6)))
        for sw, sh, vw, vh, rw, rh in edges:
            want = sw <= 2100 and sh <= 1710 and vw <= 2000 and vh <= 1334 and rw <= sw and rh <= sh and vw > 0 and vh > 0
            self.assertEqual(bool(lib.apc_gate_host(sw, sh, vw, vh, rw, rh)), want, (sw, sh, vw, vh, rw, rh))
            route = sw <= 2100 and sh <= 1710 and vw <= 2000 and rw <= sw and rh <= sh and vw > 0 and vh > 0
            self.assertEqual(bool(lib.apc_route_host(sw, sh, vw, vh, rw, rh)), route, ('route', sw, sh, vw, vh, rw, rh))

    def test_every_recipe_also_at_144_fps(self):
        lib = BA.host()
        lib.core_key_index.argtypes = [ctypes.c_char_p]
        n = 0
        for dcw, dch, rw, rh in self.CASES[:2]:
            for c in Q.qualities(dcw, dch, rw, rh, None, 0.02):
                if c['fps'] >= 144:
                    n += self.run_case(lib, (dcw, dch), (rw, rh), c, fps=Fraction(144))
        self.assertGreaterEqual(n, 2)

    def test_limit_denominator_ties(self):
        lib = BA.host()
        on, od = ctypes.c_uint32(), ctypes.c_uint32()
        ties = 0
        for d in range(2, 400):
            for n in range(1, d):
                x = Fraction(n, d)
                for lim in (3, 5, 7):
                    if x.denominator <= lim:
                        continue
                    lib.apc_limit_host(ctypes.c_uint64(n), ctypes.c_uint64(d), ctypes.c_uint64(lim), ctypes.byref(on), ctypes.byref(od))
                    self.assertEqual(Fraction(on.value, od.value), x.limit_denominator(lim), (n, d, lim))
                    ties += 1
        self.assertGreater(ties, 1000)

    def test_limit_denominator_and_dng_rate_rules(self):
        lib = BA.host()
        on, od = ctypes.c_uint32(), ctypes.c_uint32()
        import random
        rnd = random.Random(7)
        for _ in range(3000):
            n, d = rnd.randrange(1, 10 ** 8), rnd.randrange(1, 10 ** 8)
            lib.apc_limit_host(ctypes.c_uint64(n), ctypes.c_uint64(d), ctypes.c_uint64(1000), ctypes.byref(on), ctypes.byref(od))
            self.assertEqual(Fraction(on.value, od.value), Fraction(n, d).limit_denominator(1000), (n, d))
        for hm, v, sn, sd, want in ((1000, 2402, 2997, 100, Fraction(30000, 1001)),     # 29.9750: 83 ppm -> real
                                    (1001, 2400, 2997, 100, Fraction(30000, 1001)),     # exactly 30000/1001
                                    (1000, 72, 1000, 1, Fraction(1000)), (1000, 3000, 24, 1, Fraction(24)),
                                    (1000, 1502, 47952, 1000, Fraction(48000, 1001))):
            lib.apc_dng_host(hm, v, sn, sd, ctypes.byref(on), ctypes.byref(od))
            real = Fraction(CLK, hm * v)
            exp = want if abs(real / Fraction(sn, sd) - 1) <= Fraction(1, 20000) else real
            self.assertEqual(Fraction(on.value, od.value), exp, (hm, v, sn, sd))


# ---- playback (v0.6.0, notes/PLAYBACK_DESIGN.md) ----
DNG_DIR = ROOT / 'projects/qs-container/validation/2026-10-30-apply1/dng'
PB = dict(TAG_E40=0xC05C1E40, TAG_DB8=0xC05C1DB8, TAG_ED0=0xC05C1ED0, TAG_458=0xC00BA458, TAG_4D8=0xC00BA4D8,
          TAG_SET=0xC00BA310, VAR_INT=0xC059F618, VAR_FLAG=0xC059F718, VAR_SET=0xC059F5C8, LOG0=0xC0019DC0,
          LOG1=0xC001A0D8)
NBR_LOAD, GUI_OBJECT, KEYBLD_FN, EMITTER = 0xC05E84D8, 0xC37B7048, 0xC043BC68, 0xC0437B48
PBTAG, DSCALE, PBW, PBH, PBRES = 0xC05C1A58, 0xC02C43C0, 0xC059F8B8, 0xC059F8F8, 0xC05A1500
TIFF, P_CROP, P_RAS, KOBJ, KVT, KPAR, APP = 0x48170000, 0x48170100, 0x48170200, 0x48170300, 0x48170400, 0x48170500, 0x48170600
PB_KEYS = ('magic mode glyph_on res_val cw ch en seq active ras_w ras_h bits is169 asp_n asp_d box_w box_h det_h '
           'latches patches skips tags fix14 dscale_w hud_hidden res_sets glyphs gfail outs').split()


def dng_tags(path):
    """IFD0 of a DNG: {tag: [values]} (rationals as (num, den))"""
    d = pathlib.Path(path).read_bytes()[:200000]
    off = struct.unpack_from('<I', d, 4)[0]
    out = {}
    for i in range(struct.unpack_from('<H', d, off)[0]):
        t, ty, c, v = struct.unpack_from('<HHII', d, off + 2 + 12 * i)
        size = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 10: 8, 11: 4, 12: 8}[ty] * c
        raw = d[off + 10 + 12 * i:off + 14 + 12 * i] if size <= 4 else d[v:v + size]
        if ty == 3:
            out[t] = list(struct.unpack_from(f'<{c}H', raw))
        elif ty == 4:
            out[t] = list(struct.unpack_from(f'<{c}I', raw))
        elif ty in (5, 10):
            w = struct.unpack_from(f'<{2 * c}{"I" if ty == 5 else "i"}', raw)
            out[t] = [(w[2 * k], w[2 * k + 1]) for k in range(c)]
    return out


def clip(raster, crop, bits=12, rate=(30000, 1001), dscale=None):
    t = {0x100: [raster[0]], 0x101: [raster[1]], 0x102: [bits], 0xC620: list(crop), 0xC764: [rate]}
    if dscale:
        t[0xC61E] = list(dscale)
    return t


class PbCam(Cam):
    """Cam + the playback side: the DNG tag readers fed from a tag dict (the parser object is boot-built on the camera),
    the HUD notifier's variable setters recorded, the NBR loader recorded."""
    def __init__(self, **kw):
        super().__init__(**kw)
        self.tags, self.vars, self.packs, self.tagset = {}, [], [], []
        for n, a in PB.items():
            self.stub(a, n)
        self.mu.mem_write(NBR_LOAD, struct.pack('<H', 0x4770))          # Thumb bx lr
        self.by_addr[NBR_LOAD] = 'NBR_LOAD'
        self.mu.hook_add(UC_HOOK_CODE, self._hook, begin=NBR_LOAD, end=NBR_LOAD)
        # P_CROP/P_RAS/KPAR already lie in Cam's WORK mapping.
        self.put(GUI_OBJECT, APP)
        self.put(KOBJ + 8, KVT)
        self.put(KVT + 0xC, EMITTER)

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name not in PB and name != 'NBR_LOAD':
            return Cam._hook(self, mu, addr, size, data)
        try:
            r0, r1, r2, r3 = (self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))
            sp = self.r(UC_ARM_REG_SP)
            self.calls.append((name, r0, r1))
            if name == 'NBR_LOAD':
                self.packs.append((r0, r1, r2, bytes(self.mu.mem_read(r1, r2))))
                self.mu.reg_write(UC_ARM_REG_R0, 0)
                self.mu.reg_write(UC_ARM_REG_PC, self.r(UC_ARM_REG_LR))
                return
            v = self.tags.get(r2)
            if name == 'TAG_E40':                                    # (h, 0, tag, out[2], 0) -> != 0 found
                if v:
                    self.put(r3, v[0]); self.put(r3 + 4, v[1])
                return self.ret(1 if v else 0)
            if name == 'TAG_DB8':
                if v:
                    self.put(r3, v[0])
                return self.ret(1 if v else 0)
            if name == 'TAG_ED0':                                    # a SHORT
                if v:
                    self.mu.mem_write(r3, struct.pack('<H', v[0]))
                return self.ret(1 if v else 0)
            if name == 'TAG_458':                                    # (h, 5, 0, tag, out, &n) -> 0 found
                v = self.tags.get(r3)
                if v:
                    self.mu.mem_write(self.w(sp), bytes([v[0]]))
                return self.ret(0 if v else 100)
            if name == 'TAG_4D8':                                    # (h, ifd, tag, out, n rationals) -> 0 found
                n = self.w(sp)
                if v and len(v) >= n:
                    for k in range(n):
                        self.put(r3 + 8 * k, v[k][0]); self.put(r3 + 8 * k + 4, v[k][1])
                return self.ret(0 if v and len(v) >= n else 100)
            if name == 'TAG_SET':                                    # (tiff, ifd, 0, tag, type, count, data)
                ty, cnt, data_p = self.w(sp), self.w(sp + 4), self.w(sp + 8)
                size = {3: 2, 4: 4, 5: 8}[ty & 0xFFFF] * cnt
                self.tagset.append((r1, r3, ty & 0xFFFF, cnt, bytes(self.mu.mem_read(data_p, size))))
                return self.ret(0)
            if name in ('VAR_INT', 'VAR_FLAG', 'VAR_SET'):
                nm = bytes(self.mu.mem_read(r1, 24)).split(b'\0')[0].decode()
                self.vars.append((nm, r2))
                return self.ret(0)
            if name in ('LOG0', 'LOG1'):
                return self.ret(0)
        except Exception as e:                              # pragma: no cover
            self.error = e
            mu.emu_stop()

    def pb(self):
        a = self.fn('ap_pb_info', MEM) & 0xFFFFFFFF
        return dict(zip(PB_KEYS, struct.unpack(f'<{len(PB_KEYS)}I', self.mu.mem_read(a, 4 * len(PB_KEYS)))))

    def open_clip(self, tags):
        """what playback does to show a clip: its tags (the real FUN_c05c1a58, our hook after it), the real key
        build FUN_c043bc68 (mode 5's param block as FUN_c0436b80 fills it), then the profile's real gather + canvas"""
        self.tags = tags
        self.mu.mem_write(P_CROP, b'\0' * 0x20)
        self.mu.mem_write(P_RAS, b'\0' * 0x20)
        self.call(PBTAG, 0, TIFF, P_CROP, P_RAS)
        en = self.w(P_RAS + 0x10)
        self.mu.mem_write(KPAR, b'\0' * 0x40)
        self.put(KPAR + 8, self.w(P_CROP)); self.put(KPAR + 0xC, self.w(P_CROP + 4)); self.put(KPAR + 0x20, en)
        e = self.call(KEYBLD_FN, KOBJ, KPAR)
        pid = self.w(e + 4)
        return pid, en, self.canvas(pid)

    def out(self, idx):
        pairs, d = 0xC3E05000, 0xC3E05100 + 0x40 * idx
        w, h = (1620, 911) if idx == 0 else (320, 180)
        stockd = [w, h, 0, 0, w, h, 7, 4, 0x3FC000, 1, 1]
        self.mu.mem_write(d, struct.pack('<11I', *stockd))
        self.put(pairs + 8 * idx, d)
        got = self.call(OUT, pairs, idx)
        return None if got == d else list(struct.unpack('<11I', self.mu.mem_read(got, 44)))[:2]


PB_PAIRS = (0x0C, 0x10, 0xD8, 0xE0, 0xF4, 0xF8, 0x20, 0x28, 0x60, 0xD0, 0x64, 0xD4, 0x1C)


class PlaybackTests(unittest.TestCase):
    """the v2 playback machinery (canvas patch, RAW14, DefaultScale, HUD tiles): off in v1 (v0.7.0test), switched on
    here with ap_pb_ctl (0:1, 1:1, 3:0) so it stays tested for v2"""
    def cam(self, live=False):
        cam = PbCam()
        self.assertEqual(cam.init(), AP_OK)
        cam.fn('ap_pb_ctl', MEM, 0, 1); cam.fn('ap_pb_ctl', MEM, 1, 1); cam.fn('ap_pb_ctl', MEM, 3, 0)
        if live:
            self.assertEqual(cam.apply(recipe(*V1_ARGS)[0]), AP_OK)
        return cam

    def test_a001_261_gets_its_own_raster_and_nothing_else_moves(self):
        tags = dng_tags(DNG_DIR / 'A001_261_000001.DNG')
        self.assertEqual((tags[0x100][0], tags[0x101][0], tags[0xC620]), (2016, 1330, [2000, 1320]))
        for live in (False, True):
            cam, ref = self.cam(live), PbCam()
            pid, en, got = cam.open_clip(tags)
            rpid, ren, want = ref.open_clip(tags)
            self.assertEqual((pid, en), (73, 0), 'FHD key (no stock name for 2000x1320), 12-bit table')
            self.assertEqual((rpid, ren), (73, 0))
            exp = dict(zip(PB_PAIRS, (2016, 1330, 2016, 1330, 2016, 1330, 2000, 1320, 1024, 1024, 1024, 1024, 2)))
            for k in range(67):
                self.assertEqual(got[k], exp.get(4 * k, want[k]), f'+{4 * k:#x}')
            self.assertEqual(want[0x0C // 4], 1936, 'the stock p73 raster: the 80-pixel row mismatch')
            st = cam.pb()
            self.assertEqual((st['active'], st['patches'], st['cw'], st['ch'], st['ras_w'], st['ras_h']),
                             (1, 1, 2000, 1320, 2016, 1330))
            # the LCD shape follows the clip (isp_custom lvout_rules on 2000 / 1320)
            import isp_custom as IC
            rules = IC.lvout_rules(2000 / 1320)
            self.assertEqual(cam.out(0), list(rules[0][4:]))
            # back in live view: a non-playback canvas ends it
            cam.canvas(175)
            self.assertEqual(cam.pb()['active'], 0)
            if not live:
                self.assertIsNone(cam.out(0), 'no slot, no playback: the stock descriptor')

    def test_stock_clips_are_not_touched(self):
        cam, ref = self.cam(True), PbCam()
        clips = [dng_tags(DNG_DIR / 'A001_262_000001_stock.DNG'),
                 clip((3856, 2170), (3840, 2160)), clip((1936, 1090), (1920, 1080), bits=10),
                 clip((3856, 2170), (3840, 2160), bits=8)]
        for t in clips:
            a, b = cam.open_clip(t), ref.open_clip(t)
            self.assertEqual(a, b, t)
            self.assertEqual(cam.pb()['active'], 0)
        self.assertEqual(cam.pb()['patches'], 0)
        self.assertEqual(cam.pb()['skips'], len(clips))
        self.assertEqual([x[0] for x in (cam.open_clip(clips[0]),)], [73])
        self.assertEqual(ref.open_clip(clips[2])[0], 63)

    def test_14_bit_rides_the_12_bit_profile_with_the_14_bit_code(self):
        cam, ref = self.cam(), PbCam()
        t = clip((6064, 4050), (6048, 4040), bits=14)
        pid, en, got = cam.open_clip(t)
        rpid, ren, want = ref.open_clip(t)
        self.assertEqual((rpid, ren), (53, 4), 'stock: BitsPerSample 14 -> 4 = the 8-bit table')
        self.assertEqual((pid, en), (73, 0), 'ours: the 12-bit table')
        self.assertEqual(got[0x80 // 4], 0x10008)
        self.assertEqual((got[0x0C // 4], got[0x10 // 4], got[0x20 // 4], got[0x28 // 4]), (6064, 4050, 6048, 4040))
        self.assertEqual(cam.pb()['fix14'], 1)
        # an 8-bit clip of a non-stock size keeps its own (8-bit) class code
        pid, en, got = cam.open_clip(clip((2016, 1330), (2000, 1320), bits=8))
        self.assertEqual((pid, en, got[0x80 // 4]), (53, 4, 0x1000A))
        self.assertEqual((got[0x0C // 4], got[0x10 // 4]), (2016, 1330))

    def test_the_index_view_reads_many_clips_the_one_built_wins(self):
        cam = self.cam()
        odd = clip((2024, 1341), (2000, 1334))                        # a raster that is not crop + 16 / + 10
        cam.tags = odd
        cam.call(PBTAG, 0, TIFF, P_CROP, P_RAS)
        for t in (dng_tags(DNG_DIR / 'A001_261_000001.DNG'), dng_tags(DNG_DIR / 'A001_262_000001_stock.DNG')):
            cam.tags = t
            cam.call(PBTAG, 0, TIFF, P_CROP, P_RAS)
        cam.put(KPAR + 8, 2000); cam.put(KPAR + 0xC, 1334); cam.put(KPAR + 0x20, 0)
        pid = cam.w(cam.call(KEYBLD_FN, KOBJ, KPAR) + 4)
        got = cam.canvas(pid)
        self.assertEqual((got[0x0C // 4], got[0x10 // 4], got[0x20 // 4], got[0x28 // 4]), (2024, 1341, 2000, 1334))

    def test_the_mode_switch(self):
        cam, ref = self.cam(), PbCam()
        t = dng_tags(DNG_DIR / 'A001_261_000001.DNG')
        self.assertEqual(cam.fn('ap_pb_ctl', MEM, 0, 0), 1, 'v2: every non-stock clip')
        self.assertEqual(cam.open_clip(t), ref.open_clip(t), 'off')
        cam.fn('ap_pb_ctl', MEM, 0, 2)
        self.assertEqual(cam.open_clip(t), ref.open_clip(t), '2: only while a slot is live')
        raw14 = clip((6064, 4050), (6048, 4040), bits=14)
        self.assertEqual(cam.open_clip(raw14), ref.open_clip(raw14), 'mode 2 inactive must not reclassify RAW14')
        self.assertEqual(cam.apply(recipe(*V1_ARGS)[0]), AP_OK)
        self.assertNotEqual(cam.open_clip(t)[2], ref.open_clip(t)[2])
        self.assertEqual(cam.fn('ap_pb_ctl', MEM, 0, 3), -1)

    def test_default_scale_also_applies_when_the_raster_matches_stock(self):
        cam = self.cam()
        cam.open_clip(clip((1936, 1090), (1920, 1080), dscale=[(1, 1), (2, 1)]))
        self.assertEqual(cam.pb()['active'], 1)
        import isp_custom as IC
        self.assertEqual(cam.out(0), list(IC.lvout_rules(1920 / 2160)[0][4:]))

    def test_default_scale_is_written_for_anamorphic_recipes_and_read_back(self):
        import aspect as AS
        found, square = None, None
        for dc, rs in (((6048, 4040), (2000, 1320)), ((6048, 4040), (2016, 1346)), ((6048, 3402), (2016, 1134))):
            for c in Q.qualities(*dc, *rs, None, 0.02):
                ad = int(Q.ad_of(c['readout'][0], c['bits']))
                try:
                    sel, cc, plan, rows, spec = recipe(*dc, *rs, c['merge'], ad, hbin=c['hbin'], vbin=c['vbin'])
                except AssertionError:
                    continue
                p = F.plan(spec)
                a = Fraction(AS.dng_aspect(dict(rec=p.rec, zoom=[1023 if z == 1024 else z for z in spec.zoom],
                                                bin=(spec.hbin, spec.vbin), scale=spec.scale)))
                pa = a * p.rec[1] / p.rec[0]
                if abs(pa - 1) > Fraction(1, 200) and not found:
                    found = (sel, pa, p)
                if abs(pa - 1) < Fraction(1, 400) and not square:
                    square = sel
        self.assertTrue(found and square)
        sel, pa, p = found
        cam = self.cam()
        self.assertEqual(cam.apply(sel), AP_OK)
        info = 0x48170700
        cam.put(info + 0x134, p.rec[0]); cam.put(info + 0x138, p.rec[1]); cam.put(info + 0x13C, 8); cam.put(info + 0x140, 5)
        cam.call(DSCALE, 0, TIFF, 0, info)
        self.assertEqual([t[1] for t in cam.tagset], [0xC620], 'not picked for a take: stock only')
        cam.mu.mem_write(MOVREC_DEFAULT, b'\x01')                     # recording: the picker hands out our entry
        cam.call(PICKER, 0, TAB3, cam.key('UHD30'))
        cam.tagset = []
        cam.call(DSCALE, 0, TIFF, 0, info)
        self.assertEqual([t[1] for t in cam.tagset], [0xC61E, 0xC620])
        _, tag, ty, cnt, data = cam.tagset[0]
        hn, hd, vn, vd = struct.unpack('<4I', data)
        self.assertEqual((ty, cnt), (5, 2))
        want = pa.limit_denominator(1000) if pa > 1 else 1
        self.assertEqual((Fraction(hn, hd), Fraction(vn, vd)),
                         (want, 1) if pa > 1 else (Fraction(1), (1 / pa).limit_denominator(1000)))
        self.assertEqual(struct.unpack('<2I', cam.tagset[1][4]), (p.rec[0] - 16, p.rec[1] - 10), 'the stock tag still')
        cam.tagset = []
        cam.call(DSCALE, 0, TIFF, 6, info)
        self.assertEqual([t[1] for t in cam.tagset], [0xC620], 'IFD 6 (not the CinemaDNG IFD): stock')
        # a square recipe writes none
        sq = self.cam()
        self.assertEqual(sq.apply(square), AP_OK)
        sq.mu.mem_write(MOVREC_DEFAULT, b'\x01')
        sq.call(PICKER, 0, TAB3, sq.key('UHD30'))
        sq.call(DSCALE, 0, TIFF, 0, info)
        self.assertEqual([t[1] for t in sq.tagset], [0xC620])
        # playback reads it: the LCD box is the stretched shape
        import isp_custom as IC
        pb = self.cam()
        crop = (p.rec[0] - 16, p.rec[1] - 10)
        pb.open_clip(clip(p.rec, crop, dscale=[(hn, hd), (vn, vd)]))
        shape = Fraction(crop[0] * hn * vd, crop[1] * vn * hd)
        rules = IC.lvout_rules(float(shape))
        self.assertEqual(pb.out(0), list(rules[0][4:]) if rules else None)

    def test_hud_size_tiles(self):
        import pb_glyph as G                 # also exposes the maintained NBR/XCI readers on sys.path
        import nbr
        import xci
        self.assertEqual((HERE / 'pb_glyph.h').read_text(), G.header(), 'pb_glyph.h is current')
        cam = self.cam()
        cam.open_clip(dng_tags(DNG_DIR / 'A001_261_000001.DNG'))
        cam.vars = []
        cam.call(PBW, 0x1234, 2000)
        cam.call(PBH, 0x1234, 1320)
        self.assertEqual(cam.vars, [('PB_PixelSizeDisp', 0), ('PB_PixelSizeWidth', 0),
                                    ('PB_PixelSizeDisp', 0), ('PB_PixelSizeHeight', 0)], '1320 has no tile: no size line')
        cam.vars = []
        cam.call(PBW, 0x1234, 1920)
        cam.call(PBH, 0x1234, 1080)
        self.assertEqual(cam.vars, [('PB_PixelSizeDisp', 1), ('PB_PixelSizeWidth', 1920),
                                    ('PB_PixelSizeDisp', 1), ('PB_PixelSizeHeight', 1080)], 'stock: untouched')
        # a commit queues the take's numbers; ap_idle registers one pack each (UI thread, not in the commit)
        live = self.cam(True)
        st = live.status()
        self.assertEqual(live.packs, [], 'never inside the commit')
        self.assertEqual(live.fn('ap_idle', MEM), AP_OK)
        sel, c, plan, rows, spec = recipe(*V1_ARGS)
        p = F.plan(spec)
        nums = [n for n in (p.rec[0] - 16, p.rec[1] - 10) if n not in G.stock_numbers()]
        self.assertTrue(nums)
        self.assertEqual(sorted(int(re.search(rb'font_S_imageSize_(\d+)\0', pk).group(1)) for *_, pk in live.packs),
                         sorted(nums))
        for app, at, n, pk in live.packs:
            self.assertEqual((app, n), (APP, len(G.template()[0])))
            inv = nbr.inspect(pk)
            f = inv['files'][0]
            self.assertEqual(struct.unpack_from('>I', pk, G.template()[3])[0], nbr.fnv1a(f['filename']))
            v = int(re.search(rb'font_S_imageSize_(\d+)\0', pk).group(1))
            self.assertEqual(f['filename'], f'slpb{v:04d}.xci')
            W, H, L, A = xci.decode(pk, f['offset'])
            import numpy as np
            self.assertEqual((W, H), (88, 38))
            self.assertTrue((A == G.compose(v)).all() and (L == A).all(), v)
            self.assertEqual(bytes(live.mu.mem_read(at, n)), pk, 'the pack stays as handed over')
        self.assertEqual(live.fn('ap_idle', MEM), AP_IDLE, 'nothing queued twice')
        live.open_clip(clip(p.rec, (p.rec[0] - 16, p.rec[1] - 10)))
        live.vars = []
        live.call(PBW, 0x1234, p.rec[0] - 16)
        live.call(PBH, 0x1234, p.rec[1] - 10)
        self.assertEqual([v for _, v in live.vars], [1, p.rec[0] - 16, 1, p.rec[1] - 10], 'now it has its tiles')
        del st

    def test_pb_resolution_override_is_off_by_default(self):
        cam = self.cam()
        cam.call(PBRES, 0x1234, 2000, 1320)
        cam.call(PBRES, 0x1234, 3840, 2160)
        self.assertEqual(cam.vars, [('PB_Resolution', 1), ('PB_Resolution', 0)], 'stock')
        cam.vars = []
        self.assertEqual(cam.fn('ap_pb_ctl', MEM, 2, 3) & 0xFFFFFFFF, 0xFFFFFFFF)
        cam.call(PBRES, 0x1234, 2000, 1320)
        cam.call(PBRES, 0x1234, 1920, 1080)
        cam.call(PBRES, 0x1234, 3840, 2160)
        cam.call(PBRES, 0x1234, 4096, 2160)
        cam.call(PBRES, 0x1234, 1280, 720)
        self.assertEqual(cam.vars, [('PB_Resolution', 3), ('PB_Resolution', 1), ('PB_Resolution', 0),
                                    ('PB_Resolution', 1), ('PB_Resolution', 1)])


# ---- v1 playback safety (v0.7.0test, notes/PLAYBACK_DESIGN.md §15) ----
PB_V1_AT = 4 * 176                      # struct ap_pb: block, refused, pbc, preps (appended after tpl[4])
OBJ = 0x48180000                        # an XC_CinemaDngPlay: +4 vptr, +0x30 state, +0x98 / +0x9C the clip's raster
OBJ_VT = OBJ + 0x1000
PREP_DE28, PREP_DFA0, V12 = 0xC05BDE28, 0xC05BDFA0, 0xC05BE848
V1FW = dict(BE080=0xC05BE080, BE5B0=0xC05BE5B0, C09F8=0xC05C09F8, D7E0=0xC036D7E0, DC8=0xC0423DC8, DE8=0xC0423DE8,
            D818=0xC036D818, VT2C=OBJ + 0x2000)


class V1Cam(PbCam):
    """PbCam + the CinemaDNG player's object and the firmware it calls around FUN_c05be080 (Python stubs, recorded);
    FUN_c05bde28 / FUN_c05bdfa0 / XC_CinemaDngPlay::v12 themselves run from the image"""
    def __init__(self, **kw):
        super().__init__(**kw)
        for n, a in V1FW.items():
            self.stub(a, n)
        self.mu.mem_write(OBJ, b'\0' * 0x800)
        self.put(OBJ + 4, OBJ_VT)
        self.put(OBJ_VT + 0x2C, V1FW['VT2C'])

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name not in V1FW:
            return PbCam._hook(self, mu, addr, size, data)
        try:
            self.calls.append((name, self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_R1)))
            return self.ret({'BE080': 1, 'BE5B0': WORK + 0x7000, 'VT2C': 7, 'D818': 0}.get(name, 0))
        except Exception as e:                              # pragma: no cover
            self.error = e
            mu.emu_stop()

    def v1(self):
        return dict(zip(('block', 'refused', 'pbc', 'preps'),
                        struct.unpack('<4I', self.mu.mem_read((self.fn('ap_pb_info', MEM) & 0xFFFFFFFF) + PB_V1_AT, 16))))

    def info(self, tags):
        """XC_CinemaDngPlay::v11's tag read: FUN_c05c1a58(obj + 0x1ac, tiff, crop out, obj + 0x98) through our hook"""
        self.tags = tags
        self.call(PBTAG, OBJ + 0x1AC, TIFF, P_CROP, OBJ + 0x98)

    def decoded(self):
        return [c for c in self.calls if c[0] == 'BE080']


class PlaybackV1Tests(unittest.TestCase):
    CASES = [  # (raster, crop, bits) -> refused: the stock profile cannot read it
        ((2016, 1330), (2000, 1320), 12, True), ((6064, 4050), (6048, 4040), 14, True), ((3040, 2020), (3024, 2010), 12, True),
        ((2024, 1341), (2000, 1334), 12, True), ((3856, 2170), (3840, 2160), 14, True),
        ((3856, 2170), (3840, 2160), 12, False), ((1936, 1090), (1920, 1080), 10, False), ((4112, 2170), (4096, 2160), 8, False),
        ((1296, 730), (1280, 720), 12, False)]

    def cam(self, live=False):
        cam = V1Cam()
        self.assertEqual(cam.init(), AP_OK)
        cam.fn('ap_pb_ctl', MEM, 0, 0)  # explicitly retain/test the v1 stock-only fallback policy
        if live:
            self.assertEqual(cam.apply(recipe(*V1_ARGS)[0]), AP_OK)
        return cam

    def test_v1_fallback_is_stock_playback(self):
        cam, ref = self.cam(True), PbCam()
        st, v1 = cam.pb(), cam.v1()
        self.assertEqual((st['mode'], st['glyph_on'], st['res_val'], v1['block']), (0, 0, 0xFFFFFFFF, 1))
        self.assertEqual(cam.fn('ap_pb_ctl', MEM, 3, 2) & 0xFFFFFFFF, 0xFFFFFFFF)
        for t in (dng_tags(DNG_DIR / 'A001_261_000001.DNG'), clip((6064, 4050), (6048, 4040), bits=14)):
            self.assertEqual(cam.open_clip(t), ref.open_clip(t), 'no canvas patch, no RAW14 reclass')
        self.assertEqual((cam.pb()['patches'], cam.pb()['fix14'], cam.pb()['active']), (0, 0, 0))
        self.assertEqual(cam.fn('ap_idle', MEM), AP_IDLE, 'no HUD tiles registered: nothing queued')
        self.assertEqual(cam.packs, [])

    def test_a_clip_the_stock_profile_cannot_read_never_reaches_the_decoder(self):
        for ras, crop, bits, refused in self.CASES:
            with self.subTest(ras=ras, bits=bits):
                cam = self.cam(True)
                cam.info(clip(ras, crop, bits=bits))
                self.assertEqual((cam.w(OBJ + 0x98), cam.w(OBJ + 0x9C)), ras, "v11's raster is where the hook reads it")
                got = cam.call(PREP_DFA0, OBJ, 0x1D, 1)               # one frame (v12's path)
                self.assertEqual((got, len(cam.decoded())), (0, 0) if refused else (1, 1))
                if refused:
                    self.assertEqual(cam.call(PREP_DE28, OBJ, 1), 0)    # multi-frame / stream
                    self.assertEqual(cam.decoded(), [], 'FUN_c05be080 (buffers, RAW engine) never entered')
                    self.assertEqual(cam.v1()['refused'], 2)
                else:
                    self.assertEqual(cam.decoded()[0][1], OBJ)
                    self.assertEqual(cam.v1()['refused'], 0)
        cam = self.cam()
        cam.fn('ap_pb_ctl', MEM, 3, 0)                                 # v2 switch: the decode goes on
        cam.info(clip((2016, 1330), (2000, 1320)))
        self.assertEqual(cam.call(PREP_DFA0, OBJ, 0x1D, 1), 1)

    def test_the_one_frame_decode_fails_without_its_infinite_wait(self):
        """XC_CinemaDngPlay::v12 (from the image): a refused prepare is its own false return -- the FEVR event wait
        (FUN_c036d818, -1) that a decode which never completes would hang in is not reached"""
        cam = self.cam(True)
        cam.info(clip((2016, 1330), (2000, 1320)))
        self.assertEqual(cam.call(V12, OBJ, 0, 0, 0), 0)
        names = [c[0] for c in cam.calls]
        self.assertNotIn('D818', names)
        self.assertNotIn('BE080', names)
        self.assertIn('DE8', names, 'its own cleanup ran')

    def test_a_stock_clip_keeps_the_stock_lcd_shape_under_a_live_non_16_9_recipe(self):
        """the 10-30 review's defect: a stock clip's canvas is not patched (active 0), and the LV descriptor and aspect
        hooks fell back to the live 3:2 recipe on the playback screen"""
        cam = self.cam(True)
        self.assertIsNotNone(cam.out(0), 'live view: the recipe shape')
        cam.open_clip(dng_tags(DNG_DIR / 'A001_262_000001_stock.DNG'))
        self.assertEqual((cam.pb()['active'], cam.v1()['pbc']), (0, 1))
        self.assertIsNone(cam.out(0), 'playback: the stock 1620 x 911 descriptor')
        self.assertIsNone(cam.out(2))
        cam.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
        cam.mu.emu_start(0xC0306EA0, 0xC0306EA8, count=100000)
        self.assertEqual(struct.unpack('<2I', cam.mu.mem_read(cam.r(UC_ARM_REG_R0), 8)), (16, 9), 'aspect: stock')
        cam.canvas(175)                                                # back in live view
        self.assertEqual(cam.v1()['pbc'], 0)
        self.assertIsNotNone(cam.out(0))


class PoolTests(unittest.TestCase):
    """The playback pool check: the firmware's own FieldAngle sizing (C0435428 / C0435588, executed by
    open-gate/build/og4k_offline NativeSizing) over our playback canvases, against the stock ones it already serves."""
    def test_sizes(self):
        sys.path.insert(0, str(ROOT / 'projects/open-gate/build/og4k_offline'))
        import og4k_sizes as O
        img = O.load_firmware()
        model = O.load_model()
        em = O.NativeSizing(img)
        cam = PbCam()
        cam.init()
        cam.fn('ap_pb_ctl', MEM, 0, 1)
        cam.fn('ap_pb_ctl', MEM, 3, 0)  # size the custom canvas directly; selected-player admission is tested separately
        rows = {}
        for label, t in (('p51 UHD8 stock', None), ('p71 UHD12 stock', None),
                         ('A001_261 2000x1320', clip((2016, 1330), (2000, 1320))),
                         ('OG3K 3008x2000 (live-proven)', clip((3024, 2010), (3008, 2000))),
                         ('DC 6048x3402 1:1', clip((6064, 3412), (6048, 3402))),
                         ('DC 6048x4040 1:1', clip((6064, 4050), (6048, 4040))),
                         ('DC 6048x4040 1:1 14-bit', clip((6064, 4050), (6048, 4040), bits=14))):
            if t is None:
                c = O.profile_canvas(img, model, int(label[1:3]))
            else:
                c = cam.open_clip(t)[2]
                self.assertEqual((c[3], c[4]), (t[0x100][0], t[0x101][0]), 'must size the custom canvas, not its stock fallback')
            r = em.fieldangle(c, (1620, 1080))
            rows[label] = r['total_bytes']
            self.assertEqual(r['total_bytes'], model.total(c, 1620, 1080), label)
        print('\n  playback FieldAngle bytes (firmware arithmetic):')
        for k, v in rows.items():
            print(f'    {k:32s} {v:>11,d}  {v / rows["p51 UHD8 stock"]:.2f} x p51')
        self.assertLess(rows['A001_261 2000x1320'], rows['p51 UHD8 stock'])
        self.assertLess(rows['OG3K 3008x2000 (live-proven)'], rows['p51 UHD8 stock'])


# ---- mutation: each must make the named test class fail ----
# Not listed (equivalent on every reachable input): the fast threshold 99.0 -> 100.0 (engines are <= 60 stock or the
# real rate > 119.88), the busy() guard inside ap_commit that ap_run's callers also cover only through it (kept).
MUTANTS = [
    ('ap.c', 'if (id == H_LK_R10) { f[0] = s->r10;', 'if (id == H_LK_R10) { f[0] = s->r10 + 1u;', 'CommitTests'),
    ('ap.c', '    AP_W(row) = id;\n', '    AP_W(row) = id + 1u;\n', 'CommitTests'),
    ('ap.c', 'f[0] = s ? s->donor : r;', 'f[0] = s ? s->id : r;', 'CommitTests'),
    ('ap.c', 'return ap_slot_id(A, AP_W(f[0] + 4)) ? 1u : 0u;', 'return 0;', 'CommitTests'),
    ('ap.c', 'AP_W(c + 0x30u) = s->engine;', 'AP_W(c + 0x30u) = s->engine + 1u;', 'CommitTests'),
    ('ap.c', 'if (pid == AP_STANDBY_PIDS[i]) { AP_W(c + 0x20u) = s->sb_w;', 'if (pid == AP_STANDBY_PIDS[i]) { AP_W(c + 0x24u) = s->sb_w;', 'CommitTests'),
    ('ap.c', 'f[1] = sb ? s->sbase_row : s->base_row;', 'f[1] = sb ? s->sbase_row : s->base_row + 1u;', 'CommitTests'),
    ('ap.c', 'f[1] = sb ? s->sbase_row : s->base_row;', 'f[1] = s->base_row;', 'CommitTests'),
    ('ap.c', 'const u32 *m = sb ? s->smask : s->mask;', 'const u32 *m = s->mask;', 'CommitTests'),
    ('ap.c', "k[0] == 'M' && k[1] == 'O' && k[2] == 'V'", "k[0] == 'M'", 'CommitTests'),
    ('ap.c', 'if (!c || !ap_slot_pid(A, AP_W(c), &sb) || sb) return 0;', 'if (!c || !ap_slot_pid(A, AP_W(c), &sb)) return 0;', 'CommitTests'),
    ('ap.c', 'key_rate(const char *key, const struct ap_slot *s)\n{', 'key_rate(const char *key, const struct ap_slot *s)\n{\n    return 1;', 'CommitTests'),
    ('ap.c', 'if (s && f[1] == AP_TAB3 &&', 'if (s &&', 'CommitTests'),
    ('ap.c', 't->words[0] = nw; t->words[4] = nw;', 't->words[0] = nw;', 'CommitTests'),
    ('ap.c', 'f[0] = AP_ASPECT_ENUM;\n        return 1;', 'return 0;', 'CommitTests'),
    ('ap.c', '{ AP_W(out) = s->dng_n; AP_W(out + 4u) = s->dng_d;', '{ AP_W(out) = s->dng_d; AP_W(out + 4u) = s->dng_n;', 'CommitTests'),
    ('ap.c', '        ((ap_fw3)AP_FR_SET)(obj, s->carrier, 0);', '        ((ap_fw3)AP_FR_SET)(obj, s->carrier ^ 1u, 0);', 'CommitTests'),
    ('ap.c', '    ap_clock(A, s->fast);\n', '    ap_clock(A, 0);\n', 'CommitTests'),
    ('ap.c', '    ap_clock(A, 0);\n    if (run) ap_lv_start(A, holder, cs, was);\n}', '    if (run) ap_lv_start(A, holder, cs, was);\n}', 'CommitTests'),
    ('ap.c', '    ((ap_fw0)AP_ICACHE)();\n', '', 'CommitTests'),
    ('ap.c', '    if (ap_busy()) {                                         /* recording began meanwhile', '    if (ap_busy() == 99) {                                         /* recording began meanwhile', 'TransactionTests'),
    ('ap.c', 'if (kind == H_FRMAX) return ap_rank(v) < want ? s->carrier : v;', 'if (kind == H_FRMAX) return v;', 'CommitTests'),
    ('ap.c', 'if (r >= want && r < br) { best = c; br = r; }', 'if (r >= want && (br == 0xFFFFFFFFu || r > br)) { best = c; br = r; }', 'CommitTests'),
    ('ap.c', 'if (v < 6u && ap_rank(AP_CLASS_MAX[v]) >= want) return v;', '', 'CommitTests'),
    ('ap.c', 'static const uint8_t AP_CLASS_MAX[6] = {7, 3, 1, 5, 2, 6};', 'static const uint8_t AP_CLASS_MAX[6] = {7, 3, 1, 5, 6, 2};', 'CommitTests'),
    ('ap.c', 'if (s && s->rec14 && ap_rec_picked(A)) { r = 14u; A->blacks++; }', 'if (s && ap_rec_picked(A)) { r = 14u; A->blacks++; }', 'CommitTests'),
    ('ap.c', 'if (s && s->rec14 && ap_rec_picked(A)) { r = 14u; A->blacks++; }', 'if (s && s->rec14 && ap_rec_picked(A) && 0) { r = 14u; A->blacks++; }', 'CommitTests'),
    ('ap_calc.c', '        w->spec.bits = 12;\n', '', 'CalcTests'),
    ('ap_calc.c', 'if (w->spec.bits == 14 && !(w->spec.zh == 1024 && w->spec.zv == 1024 && w->spec.hbin == 1 && w->spec.vbin == 1))', 'if (w->spec.bits == 14 && !(w->spec.hbin == 1 && w->spec.vbin == 1))', 'CalcTests'),
    ('ap.c', 'u32 n = (A->cur & 1u) ^ 1u;', 'u32 n = 0;', 'TransactionTests'),
    ('ap.c', 'if (rc) { ap_to_stock(A); return ap_finish(A, rc, o->detail); }', 'if (rc) return ap_finish(A, rc, o->detail);', 'TransactionTests'),
    ('ap.c', 'A->owed = !ap_same(&A->want, &A->have) ||', 'A->owed = 1 ||', 'TransactionTests'),
    ('ap.c', 'u32 again = A->seq != seq && !ap_same(&A->want, &A->have) && rc != AP_PENDING;', 'u32 again = 0u * seq;', 'TransactionTests'),
    ('ap.c', 'u32 mine = A->owed && !A->in_commit;\n    if (mine) A->in_commit = 1;\n    u32 owed', 'u32 mine = A->owed;\n    if (mine) A->in_commit = 1;\n    u32 owed', 'TransactionTests'),
    ('ap.c', '        if (((ap_fw1)AP_FR_GET)(obj) != s->carrier) {        /* the setter refused', '        if (0) {        /* the setter refused', 'TransactionTests'),
    ('ap.c', '    if (ap_busy()) { A->owed = 1; return ap_finish(A, AP_PENDING, 0); }', '', 'TransactionTests'),
    ('ap.c', '    svc->publish(svc);                                     /* veneers', '    /* */                                     /* veneers', 'InstallTests'),
    ('ap.c', 'if (svc->claim(svc, h->site, 4u, &h->stock, SL_EXCL) != SL_OK) return AP_E_HOOKS;', 'svc->claim(svc, h->site, 4u, &h->stock, SL_EXCL);', 'InstallTests'),
    ('ap.c', 'if (svc->claim(svc, AP_CLK_SITE, 4u, &clk_stock, SL_EXCL) != SL_OK) return AP_E_HOOKS;', 'if (svc->claim(svc, AP_CLK_SITE + 4u, 4u, &clk_stock, SL_EXCL) != SL_OK) return AP_E_HOOKS;', 'InstallTests'),
    ('ap_calc.c', 'b[4] = (u32)apc_div(apc_round(APC_LCD_W * ad, an), 2u) * 2u;', 'b[4] = (u32)apc_round(APC_LCD_W * ad, an);', 'CalcTests'),
    ('ap_calc.c', 'if (e2 * bd <= e1 * q1)', 'if (e2 * bd < e1 * q1)', 'CalcTests'),
    ('ap_calc.c', 'if (diff > apc_div(y, APC_PPM_TOL)) return;', 'if (diff > apc_div(y, 2000u)) return;', 'CalcTests'),
    ('ap_calc.c', 'b[0] = 200u * dd < 16u * ad;', 'b[0] = 100u * dd < 16u * ad;', 'CalcTests'),
    ('ap_calc.c', '0x800u | (hbin == 3 ? 0x200u : 0u) | (vbin == 3 ? 0x400u : 0u) | km << 8 | kh | kv << 4', '0x800u | (hbin == 3 ? 0x200u : 0u) | (vbin == 3 ? 0x400u : 0u) | km << 8 | kh | kh << 4', 'CalcTests'),
    ('ap_calc.c', 'if (20000u * (u64)r->num * sd >= 19999u * (u64)sn * r->den) return r;', 'if ((u64)r->num * sd >= (u64)sn * r->den) return r;', 'CalcTests'),
    ('ap_calc.c', 'if (2u * r > d || (2u * r == d && (m & 1u))) m++;', 'if (2u * r > d) m++;', 'CalcTests'),
    ('ap_calc.c', 'sh <= APC_SRC_MAX_H &&', 'sh <= APC_SRC_MAX_H + 1u &&', 'CalcTests'),
    ('ap_calc.c', '0x0C / 4, 0x10 / 4,', '0x0C / 4, 0x14 / 4,', 'CalcTests'),
    ('ap.c', 'P->mode && (P->mode != 2u || ap_live(A))', 'P->mode', 'PlaybackTests'),
    ('ap.c', ' && (u64)ds[0] * ds[3] == (u64)ds[2] * ds[1]', '', 'PlaybackTests'),
    ('ap.c', 'AP_W(c + 0x0Cu) = rw; AP_W(c + 0x10u) = rh;', 'AP_W(c + 0x0Cu) = rw + 1u; AP_W(c + 0x10u) = rh;', 'PlaybackTests'),
    ('ap.c', 'code = bits == 14u ? 8u :', 'code = bits == 14u ? 7u :', 'PlaybackTests'),
    ('ap.c', 'A->pb.active = 0; A->pb.pbc = 0;                             /* any other canvas', 'A->pb.active = 1; A->pb.pbc = 0;                             /* any other canvas', 'PlaybackTests'),
    ('ap.c', '0xC61Eu, 5u, 2u,', '0xC61Eu, 4u, 2u,', 'PlaybackTests'),
    ('ap.c', 'if (v && (!ap_tile_ok(A, v) || (o && !ap_tile_ok(A, o))))', 'if (v && (!ap_tile_ok(A, v) || (o && !ap_tile_ok(A, o))) && P->mode == 99u)', 'PlaybackTests'),
    ('ap.c', '(w == 4096u && h == 2160u) || (w == 1280u && h == 720u)', '0', 'PlaybackTests'),
    # v0.7.0test: the v1 playback policy
    ('ap.c', 'if (P->block && obj && !(obj & 3u)', 'if (0 && P->block && obj && !(obj & 3u)', 'PlaybackV1Tests'),
    ('ap.c', '{1936u, 1090u}', '{1936u, 1091u}', 'PlaybackV1Tests'),
    ('ap.c', 'return !(t->bits == 0u || t->bits == 8u || t->bits == 10u || t->bits == 12u);', 'return 0;', 'PlaybackV1Tests'),
    ('ap.c', 'if (!s || s->is169 || P->pbc) return 0;', 'if (!s || s->is169) return 0;', 'PlaybackV1Tests'),
    ('ap.c', 'if (!s || s->is169 || A->pb.active || A->pb.pbc) return 0;', 'if (!s || s->is169 || A->pb.active) return 0;', 'PlaybackV1Tests'),
    ('ap.c', 'A->pb.mode = 0u; A->pb.glyph_on = 0u;', 'A->pb.mode = 1u; A->pb.glyph_on = 0u;', 'PlaybackV1Tests'),
    ('ap.c', 'A->pb.res_val = AP_PB_RES_STOCK; A->pb.block = 1u;', 'A->pb.res_val = AP_PB_RES_STOCK; A->pb.block = 0u;', 'PlaybackV1Tests'),
    ('ap.c', 'A->pb.active = 0; A->pb.pbc = 0;', 'A->pb.active = 0;', 'PlaybackV1Tests'),
    # v0.7.1test: the standby visible cut to the cap
    ('ap.c', 'if (s->sclamp && (sb || !ap_busy())) {', 'if (s->sclamp && sb) {', 'CommitTests'),
    ('ap.c', 'if (s->sclamp && (sb || !ap_busy())) {', 'if (s->sclamp) {', 'CommitTests'),
    ('ap_calc.c', '#define APC_VIS_CUT 8u ', '#define APC_VIS_CUT 0u ', 'DcSweepTests'),
    ('ap_calc.c', 'o->sok = apc_standby_ok(o->src_w, o->src_h, o->sv_w, o->sv_h, o->sr_w, o->sr_h);',
     'o->sok = apc_standby_ok(o->src_w, o->src_h, o->vis_w, o->vis_h, o->ras_w, o->ras_h);', 'DcSweepTests'),
    ('ap_calc.c', ' && vh <= APC_VIS_MAX_H;', ';', 'CalcTests'),
    # v0.7.2test: the route never answers by busy(); a selection standby cannot run is refused at the commit
    ('ap.c', 'if (!sel->standby || !o->rok) { ap_to_stock(A); A->gated++; return ap_finish(A, AP_E_STANDBY, 0); }', '',
     'CommitTests'),
    ('ap.c', 'if (!sel->standby || !o->rok) {', 'if (!o->rok) {', 'CommitTests'),
    ('ap.c', 'if (!sel->standby || !o->rok) {', 'if (!sel->standby || !o->sok) {', 'CommitTests'),
    ('ap.c', '            if (!ap_busy()) A->standby_picks++;\n            A->picked = (A->cur & 1u) + 1u; A->picks++;',
     '            if (!ap_busy() && !s->sby) { A->picked = 0; A->gated++; return 0; }\n            if (!ap_busy()) A->standby_picks++;\n            A->picked = (A->cur & 1u) + 1u; A->picks++;', 'CommitTests'),
    ('ap.c', '            if (!ap_busy()) A->standby_picks++;\n            A->picked = (A->cur & 1u) + 1u;',
     '            A->standby_picks++;\n            A->picked = (A->cur & 1u) + 1u;', 'CommitTests'),
    ('ap_calc.c', 'o->rok = apc_route_ok(o->src_w, o->src_h, o->sv_w, o->sv_h, o->sr_w, o->sr_h);', 'o->rok = o->sok;', 'CommitTests'),
    ('ap_calc.c', 'vw <= APC_VIS_MAX_W && rw <= sw && rh <= sh && vw && vh;', 'rw <= sw && rh <= sh && vw && vh;', 'CalcTests'),
]


def mutate():
    import time
    bad = []
    only = [int(a.split('=')[1]) for a in sys.argv if a.startswith('--only=')]
    for i, (fname, old, new, cls) in enumerate(MUTANTS):
        if only and i not in only:
            continue
        t = pathlib.Path(tempfile.mkdtemp(prefix='slap-mut-'))
        for f in ('ap.c', 'ap_calc.c', 'ap.h', 'pb_glyph.h', 'pb_glyph.py', 'build_apply.py', 'test_apply.py'):
            shutil.copy(HERE / f, t / f)
        src = (t / fname).read_text()
        old_m = old
        if src.count(old_m) != 1:
            bad.append((i, 'mutant text not found once'))
            continue
        (t / fname).write_text(src.replace(old_m, new))
        env = dict(os.environ, SL_ROOT=str(ROOT))
        b = subprocess.run([sys.executable, '-B', '-c', 'import build_apply as B; B.arm(); B.host()'], cwd=t, env=env,
                           capture_output=True, text=True)
        if b.returncode:
            print(f'mutant {i:2d} does not compile: not a test of the tests', b.stderr[-300:])
            bad.append((i, 'does not compile'))
            continue
        t0 = time.time()
        r = subprocess.run([sys.executable, '-B', str(t / 'test_apply.py'), cls], cwd=t, capture_output=True,
                           text=True, env=env)
        ok = r.returncode != 0
        print(f'mutant {i:2d} {cls:17s} {"caught" if ok else "SURVIVED"} ({time.time() - t0:.0f} s)')
        if not ok:
            bad.append((i, new[:60]))
        shutil.rmtree(t, ignore_errors=True)
    print('all caught' if not bad else f'survived: {bad}')
    return not bad


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(0 if mutate() else 1)
    unittest.main()
