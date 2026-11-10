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
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_UNMAPPED, UC_MEM_WRITE  # noqa: E402
from unicorn.arm_const import *                             # noqa: E402,F403

IMAGE = ROOT / 'out' / 'MAIN_c0000000.bin'
PROFILES = ROOT / 'research/other/external/FP3K-technical-handoff-2026-09-10/analysis/firmware/raw-profiles.json'
SRC = HERE / 'src_override'                                 # unused unless a mutant run sets AP_SRC
CLK = 72_000_000
AP_MEM = int(re.search(r'#define AP_MEM_BYTES (0x[0-9A-Fa-f]+)u', (HERE / 'ap.h').read_text()).group(1), 16)
AP_ABI = int(re.search(r'#define AP_ABI +(\d+)u', (HERE / 'ap.h').read_text()).group(1))

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
          ICACHE=0xC000EABC, CINE=0xC0058340, TK_CRE=0xC0016A58, TK_STA=0xC0016BC0)
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
AP_E = dict(ABI=-1, HOOKS=-2, NOTREADY=-3, RECIPE=-4, CORE=-5, ISP=-6, RATE=-7, FORMAT=-8, BUSY=-9, STANDBY=-11, CPU2=-12)


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
               'canvases recrates standby_picks carrier carrier_sets fast commit_us gated blacks '
               'defc defc_builds defc_skips defc_loads defc_last '
               'first_arms first_skips first_checks first_intact first_ok first_miss trace_n trace_lost '
               'resync_calls resync_skips resync_us resync_seen resync_ours').split()


def sel_bytes(sel, valid=1, fmt=0, kh=1, kv=1, km=0, standby=1, abi=None, **over):
    d = dict(sel, valid=valid, fmt=fmt, kh=kh, kv=kv, km=km, standby=standby)
    d.update(over)
    return struct.pack('<19I', 19 * 4, AP_ABI if abi is None else abi, *[d[k] & 0xFFFFFFFF for k in SEL_FIELDS])


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
        self.cine = 1                                   # CinemaMode (0 = STILL): v0.7.37test ap_boot_ready
        self.refuse_claim = refuse_claim
        self.on_stop = None
        self.fr_refuse = False
        self.clk_writes = []
        self.native = (30000, 1001)
        self.tk_id, self.tk_sta_rc, self.tk, self.sleeps, self.sleep_stop = 9, 0, [], [], False   # CPU x2's worker
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
            if name == 'CINE':
                assert r0 == 0x1234
                return self.ret(self.cine)
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
            if name == 'TK_CRE':
                self.tk.append(('cre', [self.w(r0 + 4 * i) for i in range(8)]))
                return self.ret(self.tk_id)
            if name == 'TK_STA':
                self.tk.append(('sta', r0, r1))
                return self.ret(self.tk_sta_rc)
            if name == 'TK_DLY':
                self.sleeps.append(r0)
                self.ret(0)
                if self.sleep_stop:
                    mu.emu_stop()
                return
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
        self.put(WORK + 0x3004, AP_ABI)
        self.fn('ap_status_get', MEM, WORK + 0x3000)
        d = dict(zip(STATUS_KEYS, struct.unpack(f'<{n}I', self.mu.mem_read(WORK + 0x3000, 4 * n))))
        d['result'] = ctypes.c_int32(d['result']).value
        d['defc_last'] = ctypes.c_int32(d['defc_last']).value
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
        self.assertEqual(len(sites), 53)
        for a, w, kind in sites:
            a, w = int(a, 16), int(w, 16)
            self.assertEqual(iw(a), w, f'{a:#x}')
            branch = (w & 0x0E000000) == 0x0A000000
            self.assertEqual(branch, a in (0xC031B660, 0xC032DDF0, 0xC032DE70, 0xC02CA1C0, 0xC02CA21C, 0xC05BDE80,
                                           0xC05BDFE8, 0xC05BDC9C, 0xC05C2DE8, DEFC_SITE, FF_ARM, FF_FIX, RS_SITE, RS_SITE2, H2_SITE, H2_DEST1, H2_DEST), f'{a:#x}')
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
            if a == 0xC01CE450:
                import capstone
                cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
                instruction, = cs.disasm(struct.pack('<I', w), a)
                self.assertEqual(instruction.mnemonic, 'blx')
                cave = int(instruction.op_str.lstrip('#'), 0)
                self.assertEqual(cam.w(cave), 0xE51FF004)
                self.assertTrue(MEM <= cam.w(cave + 4) < MEM + 0x8000)
                continue
            self.assertIn(w >> 24, (0xEA, 0xEB), f'{a:#x}')
            self.assertEqual(w >> 24 == 0xEB, a in (0xC031B660, 0xC032DDF0, 0xC032DE70, 0xC043A18C, 0xC043A19C, 0xC02CA1C0,
                                                    0xC02CA21C, 0xC05BDE80, 0xC05BDFE8, 0xC05BDC9C, 0xC05C2DE8, DEFC_SITE,
                                                    FF_ARM, FF_FIX, RS_SITE, RS_SITE2, H2_SITE, H2_DEST1, H2_DEST))
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


def cpu2_twin(dc, rs, c):
    """D11: the RWZM twin of CPU x2 case c in the core's own list (same readout, hbin 1 x vbin 1, same record)"""
    tw = [t for t in Q.qualities(*dc, *rs, None, 0.02) if t['hbin'] == 1 and t['vbin'] == 1 and
          t['readout'] == c['readout'] and t['rec'] == c['rec']]
    assert len(tw) == 1, (dc, rs, c['quality'])
    return tw[0]


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


class CpuX2Tests(unittest.TestCase):
    """CPU x2 (hbin 2, notes/CPU_X2_DESIGN.md): apc_build treats it as the ISP's 1:1 path (no binfilt, RWZM off, true 14
    for a 14-bit AD), hands the firmware the native half-width record and carries the hardware line hw_w = 2 x rec_w;
    the DNG DefaultScale counts 2 sensor px per recorded px horizontally."""

    def build(self, dc, rs, c):
        lib = host()
        hm = Q.hmax_of(c)
        v = Q.vmax_range(c)[0]
        key = lib.core_key_index(c['readout'][0].encode())
        args = (ctypes.c_uint32 * 14)(*dc, *rs, key, c['hbin'], c['vbin'], hm, max(v, 3000), 30000, 1001, 2, 3, 1)
        w = ctypes.create_string_buffer(lib.apc_sizes(0))
        o = ctypes.create_string_buffer(lib.apc_sizes(1))
        rc = lib.apc_build_host(args, w, o)
        at = 25 * 4 + 0x20 + 100 + 0x28 + 0x38 + 0x14 + 0x68 + 0x288 + 8
        base = (at + 3) & ~3
        tail = struct.unpack_from('<8I6s2x65I3I14I', o.raw, base)
        more = struct.unpack_from('<24I', o.raw, base + struct.calcsize('<8I6s2x65I3I14I'))
        attrs = struct.unpack_from('<25i', o.raw, 0)
        return rc, dict(isp=tail[9:74], rec=tail[77:79], binfilt=tail[89], rec14=more[11], ds_on=more[12],
                        ds=more[13:17], hw_w=more[23], tim_w=attrs[12] - attrs[11], width=attrs[5])

    def test_cpu2_recipes_build_as_native_half_width(self):
        import readout_cfg as RCF
        n = 0
        for dc, rs in (((6048, 4040), (3024, 2020)), ((4192, 2358), (2096, 1178)), ((6048, 4040), (3024, 4040)),
                       ((6048, 3402), (3024, 1700))):
            for c in Q.qualities(*dc, *rs, None, 0.02):
                rc, t = self.build(dc, rs, c)
                self.assertEqual(rc, 0, c['quality'])
                hw = 2 * t['rec'][0] if c['hbin'] == 2 else t['rec'][0]
                self.assertEqual(t['hw_w'], hw, c['quality'])
                if c['hbin'] != 2:
                    continue
                n += 1
                mv = RCF.BY_KEY[c['readout'][0]]['mv']
                self.assertEqual(list(t['rec']), c['rec'], c['quality'])           # the firmware's raster: half width
                self.assertEqual(t['rec'][0], rs[0])
                self.assertEqual(t['binfilt'], 0)
                # the receiver window (TIM x1 - x0, mode width) is the full raster: it holds the 2 x rec_w line
                self.assertEqual((t['tim_w'], t['width']), (c['window'][0], c['window'][0]), c['quality'])
                self.assertTrue(t['hw_w'] <= t['tim_w'] and t['tim_w'] * 1024 // t['hw_w'] < 1026, c['quality'])
                self.assertEqual(t['isp'][0xF4 // 4], c['window'][0])               # profile window: full width too
                # D11 (4), Bei 11-05 choice B: the record skips RWZM, so a 14-bit AD records true 14 (the twin: 12)
                self.assertEqual(t['rec14'], 1 if c['bits'] == 14 else 0, c['quality'])
                self.assertEqual(t['isp'][0x84 // 4], 8 if c['bits'] == 14 else 7, c['quality'])
                self.assertEqual((t['isp'][0x5C // 4], t['isp'][0x64 // 4], t['isp'][0xD4 // 4]), (0, 1023, 1023))
                # DNG pixel = 2 sensor px wide, mv tall: square for v2, else DefaultScale stretches the short axis
                px = Fraction(2 * t['rec'][1] * 1, t['rec'][1] * mv)
                if px == 1:
                    self.assertEqual(t['ds_on'], 0, c['quality'])
                else:
                    self.assertEqual(t['ds_on'], 1, c['quality'])
                    got = Fraction(t['ds'][0], t['ds'][1]) / Fraction(t['ds'][2], t['ds'][3])
                    self.assertEqual(got, px, c['quality'])
        self.assertGreaterEqual(n, 8)


class CpuX2GuardTests(unittest.TestCase):
    """Core / apply agreement (notes/CPU_X2_DESIGN.md "Display rules (single source)" brief, item 3): every hbin-2 recipe
    the recipe core offers -- the six DC presets x every RES of res_list, plus the custom RES a user can dial at half
    width (H, H/2, H/3 rows, where sensor 1x3 readouts exist) -- builds (apc_build rc 0), may run standby (rok) and
    passes the commit guard's geometry / merge check (apc_cpu2_check, the code ap_h2_guard runs): none is refused with
    AP_E_CPU2 GEOM / MV.  The CPU-only parts of the guard (D-cache line, the worker task) are not recipe properties."""

    def cells(self):
        sys.path.insert(0, str(HERE.parent / 'qs'))
        import slqs_ref as R
        out = []
        for _, W, H in R.DCS:
            out += [(W, H, it['w'], it['h']) for it in R.res_list(W, H)]
            out += [(W, H, W // 2 // 16 * 16, H // k // 2 * 2) for k in (1, 2, 3)]
        return list(dict.fromkeys(out))

    def test_every_cpu2_recipe_passes_the_commit_guard(self):
        import readout_cfg as RCF
        lib = host()
        lib.apc_cpu2_host.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        n, bad, mv3 = 0, [], 0
        for W, H, w, h in self.cells():
            for c in Q.qualities(W, H, w, h, None, 0.02):
                r = RCF.BY_KEY[c['readout'][0]]
                mv3 += c['hbin'] == 1 and r['mh'] == 1 and r['mv'] == 3 and w == W // 2 // 16 * 16
                if c['hbin'] != Q.CPU2:
                    continue
                n += 1
                hm = Q.hmax_of(c)
                v = Q.vmax_range(c)[0]
                key = lib.core_key_index(c['readout'][0].encode())
                args = (ctypes.c_uint32 * 14)(W, H, w, h, key, c['hbin'], c['vbin'], hm, v, 30000, 1001, 2, 3, 1)
                wk = ctypes.create_string_buffer(lib.apc_sizes(0))
                o = ctypes.create_string_buffer(lib.apc_sizes(1))
                rc = lib.apc_build_host(args, wk, o)
                if rc:
                    bad.append((W, H, w, h, c['quality'], 'apc_build', rc))
                    continue
                at = 25 * 4 + 0x20 + 100 + 0x28 + 0x38 + 0x14 + 0x68 + 0x288 + 8
                base = (at + 3) & ~3
                more = struct.unpack_from('<24I', o.raw, base + struct.calcsize('<8I6s2x65I3I14I'))
                if not more[22]:
                    bad.append((W, H, w, h, c['quality'], 'rok 0 (AP_E_STANDBY)'))
                why = lib.apc_cpu2_host(ctypes.addressof(wk), ctypes.addressof(o))
                if why:
                    bad.append((W, H, w, h, c['quality'], 'AP_E_CPU2', {1: 'GEOM', 2: 'MV'}.get(why, why)))
        self.assertGreaterEqual(n, 12)
        self.assertGreater(mv3, 0, 'the cells reach half-width 1x3 readouts (where CPU x2 must be withheld)')
        self.assertEqual(bad, [], f'{len(bad)} of {n} CPU x2 recipes the core offers are refused by apply')


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
        cs = cpu2_twin(dc, rs, c) if c['hbin'] == Q.CPU2 else c        # D11: the CPU x2 slot is the twin's
        plan, spec = Q.settings(cs, CLK / (hm * v))
        spec = rec_spec(spec)
        if cs is not c:                                   # D11 (4): the record bits are the CPU x2 case's own (true 14)
            spec = dataclasses.replace(spec, bits=rec_spec(Q.settings(c, CLK / (hm * v))[1]).bits)
        spec = dataclasses.replace(spec, hirate=carrier_of(fps) in (6, 7),
                                   record_preview=fps > Fraction(120000, 1001) and CLK / (hm * v) > 99)
        _, rows, _ = smc.create(plan)
        ob = o.raw
        mode = ob[:25 * 4 + 0x20 + 100 + 0x28 + 0x38 + 0x14 + 0x68 + 0x288 + 8]
        at = 25 * 4
        for t, n in (('TIM', 0x20), ('META', 100), ('R28', 0x28), ('R38', 0x38), ('R14', 0x14), ('R68', 0x68), ('REG', 0x288), ('R10', 8)):
            self.assertEqual(mode[at:at + n], bytes(rows[t]), (c['readout_id'], t))
            at += n
        tail = struct.unpack_from('<8I6s2x65I3I14I', ob, (at + 3) & ~3)
        p = F.plan(spec)
        if cs is not c:
            p.words[0x64] = 1023                          # D11 allowed difference (1): the record RWZM H at unity
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
                size = {1: 1, 3: 2, 4: 4, 5: 8, 7: 1}[ty & 0xFFFF] * cnt
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
        res = lambda: [x for x in cam.vars if x[0] == 'PB_Resolution']      # v0.7.21: v92 also sets PB_OwnModel
        self.assertEqual(res(), [('PB_Resolution', 1), ('PB_Resolution', 0)], 'stock')
        cam.vars = []
        self.assertEqual(cam.fn('ap_pb_ctl', MEM, 2, 3) & 0xFFFFFFFF, 0xFFFFFFFF)
        cam.call(PBRES, 0x1234, 2000, 1320)
        cam.call(PBRES, 0x1234, 1920, 1080)
        cam.call(PBRES, 0x1234, 3840, 2160)
        cam.call(PBRES, 0x1234, 4096, 2160)
        cam.call(PBRES, 0x1234, 1280, 720)
        self.assertEqual(res(), [('PB_Resolution', 3), ('PB_Resolution', 1), ('PB_Resolution', 0),
                                 ('PB_Resolution', 1), ('PB_Resolution', 1)])

    def test_own_model_text_row_for_sizes_without_tiles(self):
        """v0.7.21test: a clip whose size is not a stock movie size gets PB_OwnModel 1 -- the pixel-size row of
        PB_PixelSizeString (per-digit font_S glyphs) instead of font_S_imageSize_<N> images it lacks.  v92 (size)
        and v153 (own model) may come in either order; a stock clip after ours gets v153's value back."""
        PBOWN = 0xC05A2440
        own = lambda c: [v for n, v in c.vars if n == 'PB_OwnModel']
        cam = self.cam()
        cam.call(PBRES, 0x1234, 1920, 1080); cam.call(PBOWN, 0x1234, 1)
        self.assertEqual(own(cam), [0], 'stock clip from this camera: the stock value')
        cam.vars = []
        cam.call(PBRES, 0x1234, 2000, 1320); cam.call(PBOWN, 0x1234, 1)
        self.assertEqual(own(cam), [1, 1], 'size first: ours, and v153 does not undo it')
        cam.vars = []
        cam.call(PBOWN, 0x1234, 1); cam.call(PBRES, 0x1234, 3008, 2004)
        self.assertEqual(own(cam), [1, 1], 'model first: still ours')
        cam.vars = []
        cam.call(PBOWN, 0x1234, 1); cam.call(PBRES, 0x1234, 3840, 2160)
        self.assertEqual(own(cam)[-1], 0, 'a stock clip after ours: v153\'s value put back')
        cam.vars = []
        cam.call(PBRES, 0x1234, 4096, 2160); cam.call(PBOWN, 0x1234, 0)
        self.assertEqual(own(cam), [1], 'stock size, another camera: the stock value (0 ^ 1)')
        for w, h in ((3840, 2160), (1920, 1080), (4096, 2160), (1280, 720)):
            cam.vars = []
            cam.call(PBRES, 0x1234, w, h); cam.call(PBOWN, 0x1234, 1)
            self.assertEqual(own(cam), [0], (w, h))

    def test_sizes_without_tiles_keep_their_numbers_for_the_text_row(self):
        """v0.7.22test (Bei 11-03: the text row read "0x0"): with the HUD tile experiment off (the product), v5/v6
        pass a size that has no font_S_imageSize tile unchanged -- the text row needs the real numbers."""
        cam = self.cam()
        cam.fn('ap_pb_ctl', MEM, 1, 0)                       # the product: ap_init's glyph_on 0, nothing turns it on
        cam.vars = []
        cam.call(PBW, 0x1234, 3008)
        cam.call(PBH, 0x1234, 2004)
        self.assertEqual([v for n, v in cam.vars if n in ('PB_PixelSizeWidth', 'PB_PixelSizeHeight')], [3008, 2004])


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


class BootReadyTests(unittest.TestCase):
    """v0.7.35test: ap_boot_ready, what the boot apply's poller and callback ask before the first commit"""
    def test_only_after_a_standby_lv_start_and_never_while_recording_in_playback_or_off_format(self):
        cam = PbCam()
        self.assertEqual(cam.init(), AP_OK)
        ready = lambda: cam.fn('ap_boot_ready', MEM)
        cam.lv_on = False
        self.assertEqual(ready(), 0, 'no LV start seen yet, no live view running')
        cam.lv_on = True
        self.assertEqual(ready(), 1, 'v0.7.37test: a CINE live view running counts (the boot LV never reaches the picker)')
        cam.cine = 0
        self.assertEqual(ready(), 0, 'STILL')
        cam.cine = 1
        cam.lv_on = False
        cam.call(PICKER, 0, TABS, cam.key('MAG4'))
        self.assertEqual(ready(), 0, 'the magnifier is not a standby LV start')
        cam.call(PICKER, 0, TABS, cam.key('MOV'))
        self.assertEqual(ready(), 1)
        cam.lv_on = True
        cam.mu.mem_write(MOV_ACTIVE, b'\x01')
        self.assertEqual(ready(), 0, 'recording')
        cam.mu.mem_write(MOV_ACTIVE, b'\x00')
        cam.fmt = 1
        self.assertEqual(ready(), 0, 'not CinemaDNG')
        cam.fmt = 0
        desc = cam.w(IMAGER)
        cam.put(IMAGER, 0)
        self.assertEqual(ready(), 0, 'no mode descriptor')
        cam.put(IMAGER, desc)
        self.assertEqual(ready(), 1)
        cam.open_clip(dng_tags(DNG_DIR / 'A001_261_000001.DNG'))
        self.assertEqual(ready(), 0, 'a playback hook ran after the LV start')
        cam.call(PICKER, 0, TABS, cam.key('MOV'))
        self.assertEqual(ready(), 1, 'back in standby')
        # the commit itself agrees: ready -> the request commits (no AP_E_NOTREADY)
        self.assertEqual(cam.apply(recipe(*V1_ARGS)[0]), AP_OK)


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

    def test_a_raster_past_stock_dci4k_is_refused_in_any_mode(self):
        """v0.7.24test (6K froze the camera, Bei 11-03): with the admission guard off, a raster above 4112 x 2170
        is still refused before FUN_c05be080 -- its FieldAngle work area would not fit the LVIEW pool."""
        for ras, crop, refused in (((6048, 4040), (6032, 4030), True), ((6064, 4050), (6048, 4040), True),
                                   ((4112, 2172), (4096, 2162), True), ((4112, 2170), (4096, 2160), False),
                                   ((3024, 2014), (3008, 2004), False)):
            with self.subTest(ras=ras):
                cam = self.cam(True)
                cam.fn('ap_pb_ctl', MEM, 3, 0)                         # no selection guard: only the size rule
                cam.info(clip(ras, crop, bits=12))
                self.assertEqual(cam.call(PREP_DFA0, OBJ, 0x1D, 1), 0 if refused else 1)   # one frame (selection)
                if refused:
                    self.assertEqual(cam.call(PREP_DE28, OBJ, 1), 0)                     # stream
                    self.assertEqual(cam.decoded(), [], 'FUN_c05be080 never entered')
                else:
                    self.assertEqual(cam.decoded()[0][1], OBJ)

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


# ---- v0.7.25test: defect (hot pixel) tables for our ids (notes/DEFECT_VIRTUAL_MODES.md) ----
# What runs for real: ap.c's commit and H_DEFC, the firmware's converter FUN_c0310740 (and its sort / stream / flag
# helpers), the whole ImagerDefect loader FUN_c030e2a0 with v33, the Thumb wrapper FUN_c0635d80 and the register
# writer FUN_c0633778 (into mapped MMIO).  Stubbed: the allocator (C001CF78 / C001D038 / C001D2B8, recorded), the
# sensor object getter C0322E48(0) = 0xC343B588 (MODE_TABLES_CONSUMERS: FUN_c03255f8's singleton), the directory
# getter C051E208 (*0xC343A71C, no flash read) and C051F4D8 (small format: 0).  Source: the camera's own flash defect
# buffer, dumped 2026-10-22 (imx410-lab captures/defect/flashbuf.bin) at the address it had (0x44EAFD80).
import defect_tables as DT                                  # noqa: E402  (imx410-lab offline: the Python port)

DEFC_SITE = 0xC030F624
DEFC_CTX, DEFC_BUFP, DEFC_CONV, DEFC_LOAD = 0xC343A66C, 0xC343A71C, 0xC0310740, 0xC030E2A0
FBUF, ARENA = 0x44EAFD80, 0x4A000000
FLASHBUF = IMXL / 'captures' / 'defect' / 'flashbuf.bin'
DEFC_FW = dict(ALLOC_H=0xC001CF78, ALLOC=0xC001D038, FREE=0xC001D2B8, IMGR=0xC0322E48, SADJ=0xC051F4D8,
               DIRGET=0xC051E208)
D84, D00, D80, D380, PTS = 0x300F0D84, 0x300F0D00, 0x300F0D80, 0x300F0380, 0x300F0E00
R12V2 = (6048, 4040, 3024, 2014, '1x2', 12)                 # first-frame-purple t03-t05 (mode 231 live)
R14_1X1 = (6048, 4040, 3024, 2020, '1x1', 14)               # A001_014: key 0, RWZM /2 both axes
R14V2 = (6048, 4040, 3024, 2014, '1x2', 14)                 # A001_012
DEFC_RECIPES = (R12V2, R14_1X1, R14V2, V1_ARGS, ALT_ARGS)


def defc_dir(buf):
    """{id: (table offset, words, list offset)} of the directory (DEFECT_CORRECTION.md §3)"""
    d = DT.parse(buf)
    return {t: (at, nb // 4, lst) for t, (at, nb, lst) in d['tables'].items()}


class DefectCam(Cam):
    def __init__(self, src=None, flash=None, alloc_fail=False, **kw):
        super().__init__(src, **kw)
        mu = self.mu
        mu.mem_map(0x44E00000, 0x100000)
        mu.mem_map(ARENA, 0x400000)
        mu.mem_map(0x30000000, 0x100000)                       # DEFC / 0x300020EC (FUN_c0633778's registers)
        self.flash = FLASHBUF.read_bytes() if flash is None else flash
        if self.flash:
            mu.mem_write(FBUF, self.flash)
            self.put(DEFC_BUFP, FBUF)
        self.put(IMAGER + 0xD0, 0xC0B5FCC0)                    # XC_ImageSensorIMX410 vtable (+0x8c = v33)
        self.allocs, self.frees, self.convs, self.order = [], [], 0, []
        self.alloc_fail, self.bump, self.on_fmt = alloc_fail, ARENA, None
        for n, a in DEFC_FW.items():
            self.stub(a, n)
        mu.hook_add(UC_HOOK_CODE, self._conv, begin=DEFC_CONV, end=DEFC_CONV)

    def _conv(self, mu, addr, size, data):
        self.convs += 1
        self.order.append('CONV')

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name == 'DCACHE':
            self.order.append('DCACHE')
        if name == 'GET_FMT' and self.on_fmt:
            self.on_fmt(self)
        if name not in DEFC_FW:
            return super()._hook(mu, addr, size, data)
        try:
            r0, r1 = self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_R1)
            if name == 'IMGR':
                return self.ret(IMAGER if r0 == 0 else 0)
            if name == 'SADJ':
                return self.ret(0)
            if name == 'DIRGET':
                self.put(r0, self.w(DEFC_BUFP))
                return self.ret(r0)
            if name == 'ALLOC_H':
                return self.ret(0xA1100000 | r0)
            if name == 'ALLOC':
                self.allocs.append((r0 & 0xFF, r1))
                if self.alloc_fail:
                    return self.ret(0)
                p = (self.bump + 31) & ~31
                self.bump = p + r1
                return self.ret(p)
            if name == 'FREE':
                self.frees.append((r0 & 0xFF, r1))
                return self.ret(0)
        except Exception as e:                              # pragma: no cover
            self.error = e
            mu.emu_stop()

    def load(self, mode, enable=1, xlate=0):
        """the mode set's ImagerDefect load, FUN_c030e2a0(ctx, mode, enable, 0, xlate): the DEFC registers after it"""
        self.put(IMAGER + 4, mode)
        for a in (D84, D00, D80, D380):
            self.put(a, 0xDEADBEEF)
        sp = STACK - 0x2008
        self.put(sp, xlate)                                    # the fifth argument
        self.call(DEFC_LOAD, DEFC_CTX, mode, enable, 0, sp=sp)
        return dict(d84=self.w(D84), d00=self.w(D00), d80=self.w(D80), d380=self.w(D380),
                    pts=list(struct.unpack('<128I', self.mu.mem_read(PTS, 512))))

    def defc(self, n):
        """slot n's {tbl, list[128]} and its table buffer (u16)"""
        at = self.off(15) + n * self.fn('ap_sizes_t', 18)
        tbl = self.w(at)
        lst = list(struct.unpack('<128I', self.mu.mem_read(at + 4, 512)))
        buf = self.off(16) + n * 4 * 0x4000
        u16 = list(struct.unpack('<32768H', self.mu.mem_read(buf, 0x10000)))
        return tbl, lst, buf, u16


def stream_until_end(u16):
    out, ff = [], 0
    for w in u16:
        out.append(w)
        ff = ff + 1 if w == 0xFFFF else 0
        if ff == 4:
            return out
    raise AssertionError('no end mark')


def r68_of(rows):
    R = bytes(rows['R68'])
    u = lambda o: struct.unpack_from('<I', R, o)[0]          # noqa: E731
    m = bytes(rows['META'])
    return dict(tid=u(4), flag=u(8), src=u(0xC), win=(u(0x10), u(0x14), u(0x18), u(0x1C)), types=(u(0x20), u(0x24)),
                offs=(u(0x28), u(0x2C)), W=struct.unpack_from('<I', m, 4)[0], H=struct.unpack_from('<I', m, 8)[0])


class DefectTests(unittest.TestCase):
    def live(self, args, cam=None, **kw):
        cam = cam or DefectCam(**kw)
        self.assertEqual(cam.init(), AP_OK)
        self.assertEqual(cam.apply(recipe(*args)[0]), AP_OK, cam.status())
        return cam

    def test_the_rows_carry_the_conversion_fields(self):
        """step 1: core's R68 (mode_rules) already has +08 = 1, +0C = 97 (0x61) and the window / types / offsets"""
        for args in DEFC_RECIPES:
            r = r68_of(recipe(*args)[3])
            self.assertEqual((r['flag'], r['src']), (1, 0x61), args)
        r = r68_of(recipe(*R12V2)[3])
        self.assertEqual((r['win'], r['types'], r['offs']), ((8, 8, 6048, 4042), (0, 7), (0, 2)))
        r = r68_of(recipe(*R14_1X1)[3])
        self.assertEqual((r['win'], r['types'], r['offs']), ((8, 0, 6048, 4040), (0, 0), (0, 0)))

    def test_the_firmware_converter_equals_the_python_port_for_every_recipe(self):
        buf = FLASHBUF.read_bytes()
        at, words, _ = defc_dir(buf)[0x61]
        src, _ = DT.table(buf, 0x61)
        for args in DEFC_RECIPES:
            cam = self.live(args)
            st = cam.status()
            n = st['cur']
            self.assertEqual((st['defc'], st['defc_last'], st['defc_builds']), (1, 1, 1), args)
            r = r68_of(recipe(*args)[3])
            want, wl = DT.translate(src, r['win'], r['types'], r['offs'], r['W'], r['H'], size_words=words)
            tbl, lst, tb, u16 = cam.defc(n)
            got = stream_until_end(u16)
            self.assertEqual(got, want[:len(got)], args)
            self.assertEqual(len(got), len(want), args)
            self.assertEqual(lst, wl, args)
            self.assertEqual(tbl, tb, 'uncached alias (the emulated block is already 0x4...)')
            pts = DT.points(got)
            self.assertGreater(len(pts), 9000, args)
            self.assertTrue(all(x < r['W'] and y < r['H'] for x, y in pts), args)
            # class-10 scratch only (the source-size point buffer + the sort's), all freed in the same call
            self.assertTrue(cam.allocs and all(c == 10 for c, _ in cam.allocs), args)
            self.assertIn((10, 4 * words), cam.allocs, args)
            self.assertEqual(len(cam.frees), len(cam.allocs), args)
            self.assertTrue(all(c == 10 for c, _ in cam.frees), args)
            self.assertEqual(cam.order[-2:], ['CONV', 'DCACHE'], 'the D-clean follows the table (DEFC reads it by DMA)')

    def test_the_firmwares_own_translating_path_computes_the_same_table(self):
        """FUN_c030e2a0 with xlate = 1 (its >0.5 s still path) converts our id itself into its class-0 buffer: it must
        equal ours byte for byte -- the converter is called the way the firmware calls it"""
        for args in (R12V2, R14_1X1):
            cam = self.live(args)
            n = cam.status()['cur']
            mode = cam.status()['mode_id']
            cam.allocs.clear()
            cam.load(mode, xlate=1)
            fw = cam.w(0xC343A648)
            self.assertTrue(ARENA <= fw < ARENA + 0x400000)
            ours = stream_until_end(cam.defc(n)[3])
            theirs = list(struct.unpack(f'<{len(ours)}H', cam.mu.mem_read(fw, 2 * len(ours))))
            self.assertEqual(theirs, ours, args)

    def test_our_id_loads_our_table_stock_ids_and_off_pass_through(self):
        buf = FLASHBUF.read_bytes()
        d = defc_dir(buf)
        ref = DefectCam()
        self.assertEqual(ref.init(), AP_OK)
        cam = self.live(R12V2)
        st = cam.status()
        tbl, lst, tb, _ = cam.defc(st['cur'])
        got = cam.load(st['mode_id'])
        self.assertEqual(got['d84'], ((tb + 0xC0000000) & 0xFFFFFFFF) >> 2, 'DEFC reads our table')
        self.assertEqual((got['d00'], got['d80'], got['d380']), (1, 0x101, 1))
        self.assertEqual(got['pts'], lst)
        self.assertEqual(cam.status()['defc_loads'], 1)
        for mode in (97, 98, 106, 8, 10):                       # stock: R68 +04's flash table, as with no hook
            a, b = cam.load(mode), ref.load(mode)
            self.assertEqual(a, b, mode)
            tid = struct.unpack_from('<H', bytes(cam.row_via_lookup(5, mode)), 4)[0]
            self.assertEqual(a['d84'], ((FBUF + d[tid][0] + 0xC0000000) & 0xFFFFFFFF) >> 2, mode)
        self.assertEqual(cam.status()['defc_loads'], 1, 'stock ids never substituted')
        off = cam.load(st['mode_id'], enable=0)                 # SetImgMode_s step 10: (0, 0, 0) -> DEFC off
        self.assertEqual((off['d00'], off['d80']), (0, 0))
        self.assertEqual(cam.status()['defc_loads'], 1)

    def test_negative_control_the_pre_change_unit_loads_table_97_untranslated(self):
        """the v0.7.24test sources (validation/20261103-defect-virtual/pre-change): our id gets flash table 97 as it
        is -- mode 97's raster coordinates on ours -- which is the bug this change removes"""
        pre = ROOT / 'projects/sensorlab-imx410/validation/20261103-defect-virtual/pre-change'
        cam = DefectCam(src=str(pre))
        self.assertEqual(cam.fn('ap_init', MEM, AP_MEM, SVC), AP_OK)
        pre_abi = int(re.search(r'#define AP_ABI +(\d+)u', (pre / 'ap.h').read_text()).group(1))   # 2 (v0.7.24test)
        self.assertEqual(cam.request(recipe(*R12V2)[0], abi=pre_abi), AP_OK)
        t97 = ((FBUF + defc_dir(FLASHBUF.read_bytes())[0x61][0] + 0xC0000000) & 0xFFFFFFFF) >> 2
        loads = {m: cam.load(m)['d84'] for m in (230, 231)}
        self.assertIn(t97, loads.values())
        self.assertEqual(cam.convs, 0)

    def test_the_old_slot_is_never_rewritten_and_the_new_one_loads(self):
        cam = self.live(R12V2)
        a = cam.status()
        live_tab = bytes(cam.mu.mem_read(cam.defc(a['cur'])[2], 0x10000))
        self.assertEqual(cam.apply(recipe(*R14_1X1)[0]), AP_OK)
        b = cam.status()
        self.assertNotEqual(a['cur'], b['cur'])
        self.assertEqual(bytes(cam.mu.mem_read(cam.defc(a['cur'])[2], 0x10000)), live_tab, 'the slot DEFC may still read')
        self.assertEqual(cam.load(b['mode_id'])['d84'], ((cam.defc(b['cur'])[2] + 0xC0000000) & 0xFFFFFFFF) >> 2)
        self.assertEqual(cam.load(a['mode_id'])['d84'], ((cam.defc(a['cur'])[2] + 0xC0000000) & 0xFFFFFFFF) >> 2)

    def test_stock_behaviour_when_no_table_can_be_made(self):
        buf = bytearray(FLASHBUF.read_bytes())
        i = DT.parse(bytes(buf))['tables']
        big = bytearray(buf)
        k = list(struct.unpack_from('<11H', buf, 0x16008)).index(0x61)
        struct.pack_into('<H', big, 0x16088 + 2 * k, 0x4001)   # larger than a slot's buffer
        bad = bytearray(buf)
        struct.pack_into('<I', bad, 0x16000, 0)                # directory not valid
        nolist = bytearray(buf)
        struct.pack_into('<H', nolist, 0x16008 + 2 * k, 0x7F)  # no source table 0x61
        over = bytearray(buf)                                  # 0x61 second, after a table claiming 0xA000 words:
        struct.pack_into('<2H', over, 0x16008, 0x62, 0x61)     # it would run into the point lists
        struct.pack_into('<2H', over, 0x16088, 0xA000, 0x3000)
        for what, kw, want in (('not loaded', dict(flash=b''), -1), ('no directory', dict(flash=bytes(bad)), -2),
                               ('no 0x61', dict(flash=bytes(nolist)), -3), ('too big', dict(flash=bytes(big)), -3),
                               ('overruns the lists', dict(flash=bytes(over)), -3),
                               ('scratch refused', dict(alloc_fail=True), -5)):
            cam = self.live(R12V2, **kw)
            st = cam.status()
            self.assertEqual((st['active'], st['defc'], st['defc_last'], st['defc_skips']), (1, 0, want, 1), what)
            if kw.get('flash') != b'':
                got = cam.load(st['mode_id'])
                # stock: c030e2a0's own choice -- flash table 97 as it is; no valid directory / no table 97: DEFC is
                # switched off (its "off" call) or left as the mode set's step 10 left it (off)
                at = FBUF + (0x16400 + 4 * 0xA000 if what == 'overruns the lists' else i[97][0])
                want_d84 = 0xDEADBEEF if what in ('no directory', 'no 0x61') else ((at + 0xC0000000) & 0xFFFFFFFF) >> 2
                self.assertEqual(got['d84'], want_d84, what)
            self.assertEqual(cam.status()['defc_loads'], 0, what)
        del i

    def test_recording_safety(self):
        # a commit owed while recording: no conversion, no allocation
        cam = DefectCam()
        cam.init()
        cam.put(MOVREC_DEFAULT & ~3, 1 << (8 * (MOVREC_DEFAULT & 3)))
        self.assertEqual(cam.apply(recipe(*R12V2)[0]), AP_PENDING)
        self.assertEqual((cam.convs, cam.allocs), (0, []))
        # recording starts inside the commit, before the table: the converter (class 10 scratch) is never called
        cam = DefectCam()
        cam.init()
        cam.on_fmt = lambda c: c.put(XMP_FOBJ, 0x1234)
        self.assertEqual(cam.apply(recipe(*R12V2)[0]), AP_E['BUSY'])
        st = cam.status()
        self.assertEqual((cam.convs, cam.allocs, st['defc_last'], st['owed']), (0, [], -4, 1))
        # the REC-start mode set (busy) with a live slot: a pointer swap only -- no allocation, no conversion
        cam = self.live(R12V2)
        n0, a0 = cam.convs, len(cam.allocs)
        cam.put(MOVREC_DEFAULT & ~3, 1 << (8 * (MOVREC_DEFAULT & 3)))
        got = cam.load(cam.status()['mode_id'])
        self.assertEqual(got['d84'], ((cam.defc(cam.status()['cur'])[2] + 0xC0000000) & 0xFFFFFFFF) >> 2)
        self.assertEqual((cam.convs, len(cam.allocs)), (n0, a0))

    def test_a_cached_block_hands_dfec_the_uncached_alias(self):
        """the sup runs from the cached alias (0xC... = 0x4... + 0x80000000): DEFC must get the 0x4... address"""
        from unicorn import UC_PROT_ALL
        cam = DefectCam()
        host = ctypes.create_string_buffer(0x100000)
        cam.mu.mem_unmap(MEM, 0x100000)
        cam.mu.mem_map_ptr(MEM, 0x100000, UC_PROT_ALL, ctypes.addressof(host))
        CMEM = MEM + 0x80000000
        cam.mu.mem_map_ptr(CMEM, 0x100000, UC_PROT_ALL, ctypes.addressof(host))
        self.assertEqual(cam.fn('ap_init', CMEM, AP_MEM, SVC), AP_OK)
        cam.mu.mem_write(WORK + 0x2000, sel_bytes(recipe(*R12V2)[0]))
        self.assertEqual(cam.fn('ap_request', CMEM, WORK + 0x2000), AP_OK)
        n = cam.w(CMEM + cam.fn('ap_sizes_t', 10)) & 1
        at = CMEM + cam.fn('ap_sizes_t', 15) + n * cam.fn('ap_sizes_t', 18)
        tb = CMEM + cam.fn('ap_sizes_t', 16) + n * 0x10000
        self.assertEqual(cam.w(at), tb - 0x80000000)
        self.assertEqual(bytes(cam.mu.mem_read(tb - 0x80000000, 64)), bytes(cam.mu.mem_read(tb, 64)))
        cam.put(IMAGER + 4, 230 + n)
        got = cam.load(230 + n)
        self.assertEqual(got['d84'], ((tb - 0x80000000 + 0xC0000000) & 0xFFFFFFFF) >> 2)

    def test_the_converted_tables_cover_the_measured_hot_pixels(self):
        """G7 dark frames (BUFA0, before DEFC; validation/20261103-defect-virtual/hot_g7.json, receiver coordinates):
        the converted table must cover them; table 97 as DEFC got it before (untranslated) must not"""
        hot = json.loads((ROOT / 'projects/sensorlab-imx410/validation/20261103-defect-virtual/hot_g7.json').read_text())
        buf = FLASHBUF.read_bytes()
        raw = DT.points(DT.table(buf, 0x61)[0])
        for args, cls in ((R12V2, 'gen_12v2'), (R14V2, 'gen_14v2'), (R14_1X1, 'stock_97')):
            cam = self.live(args)
            plan = recipe(*args)[2]
            x0, y0 = smc.attrs_from_plan(plan)['x0'], smc.attrs_from_plan(plan)['y0']
            P = set(DT.points(stream_until_end(cam.defc(cam.status()['cur'])[3])))
            meas = [(x - x0, y - y0) for x, y in hot[cls]['receiver']]
            near = lambda S: sum(any((x + dx, y + dy) in S for dx in (-1, 0, 1) for dy in (-1, 0, 1)) for x, y in meas) / len(meas)   # noqa: E731
            cov, old = near(P), near(set(raw))
            self.assertGreater(cov, 0.95, (cls, cov))
            self.assertLess(old, 0.2 if cls != 'stock_97' else 0.2, (cls, old))


# ---- v0.7.26test: the first recorded frame's +1 row (notes/FIRST_FRAME_REPAIR.md) ----
FF_ARM, FF_FIX = 0xC031C948, 0xC038BDB4                 # ContSet_Adr1 blx FUN_c0631b98; FUN_c038bd98 bl FUN_c03753c0
FF_DONE = 0xC031BCA0                                      # FUN_c031bca0 (BUFA1 completion callback) entry
TR_HDR, TR_WORDS, TR_N = 16, 56, 12
TR_KEYS = 'kind seq epoch raw us tg_frame tg_line tg_flags ras x0 x1 x2 x3 ok'.split()
TMR = 0x30110000                                          # the emulated timer block (*0xC30337F0)
FF_U, FF_SIZE, FF_HDR = 0x4C000000, 0x04000000, 0x15400   # one DRAM window: uncached 0x4C.., cached 0xCC..
FF_DEST = FF_U + FF_HDR                                   # the raster = file + header (frame_hold.c)
FF_12V2 = (6048, 4020, 3024, 2010, '1x2', 12)             # the live t28-t35 recipe: 3024 x 2010 (mmio_diff '12v2')
FF_DESC, FF_TAB, FF_MSG, FF_FRAME = WORK + 0xA000, WORK + 0xB000, WORK + 0xB400, WORK + 0xC000
FF_ST, FF_CTL, FF_CAP, FF_ENQO, FF_HOBJ = WORK + 0xD000, WORK + 0xD100, WORK + 0xD200, WORK + 0xD300, WORK + 0xD400
FF_FRAMES = WORK + 0xE000                                 # frame objects 0x1200 apart (they reach +0x1118)
# FUN_c038bd98's callees, stubbed (recorded); FUN_c03753c0 (the lookup), FUN_c03a92b0/f0 (flag bytes) run for real
FF_STUBS = dict(FF_TABLE=0xC0374220, FF_LOG0=0xC0019DC0, FF_LOG=0xC001A048, FF_C800=0xC038C800, FF_E18=0xC0395E18,
                FF_FIRSTSTATE=0xC0396000, FF_A0F8=0xC038A0F8, FF_HDR=0xC038C5F8, FF_ENQGET=0xC037DD08,
                FF_ENQ=STUB + 0x200, FF_TRACE=0xC03A5938, FF_STOP=0xC038C3C0, FF_CAPMGR=0xC0377348,
                FF_RELBUF=0xC0377730, FF_DELETE=0xC0375030, FF_DRAIN=0xC037DEE0, FF_GUARD=0xC0013090)


def ff_window(cam):
    """a 64 MiB DRAM window seen at both aliases (the hardware's 0x4... / 0xC... pair), for the frame's file buffer"""
    from unicorn import UC_PROT_ALL
    cam._ffram = ctypes.create_string_buffer(FF_SIZE)
    cam.mu.mem_map_ptr(FF_U, FF_SIZE, UC_PROT_ALL, ctypes.addressof(cam._ffram))
    cam.mu.mem_map_ptr(FF_U + 0x80000000, FF_SIZE, UC_PROT_ALL, ctypes.addressof(cam._ffram))
    cam.fflog = []

    def acc(uc, access, a, size, value, data):
        k = ('W' if access == UC_MEM_WRITE else 'R') + ('c' if a >= 0x80000000 else 'u')
        if not cam.fflog or cam.fflog[-1] != k:
            cam.fflog.append(k)
    from unicorn import UC_HOOK_MEM_READ
    cam._ffhooks = [cam.mu.hook_add(UC_HOOK_MEM_WRITE | UC_HOOK_MEM_READ, acc, begin=base, end=base + FF_SIZE - 1)
                    for base in (FF_U, FF_U + 0x80000000)]
    return cam


class FFCam(DefectCam):
    """DefectCam + the DRAM window + BUFA1's registers (FUN_c0631b98 runs for real below the arm hook)"""
    def __init__(self, **kw):
        super().__init__(**kw)
        self.mu.mem_map(0x30100000, 0x100000)
        ff_window(self)
        self.native = []                                      # (name, r0, r1) of FUN_c038bd98's stubbed callees
        for n, a in FF_STUBS.items():
            self.stub(a, n)
        self.put(FF_ENQO, FF_ENQO + 0x40)                     # the creator: vtable +0x10 = the enqueue
        self.put(FF_ENQO + 0x40 + 0x10, FF_STUBS['FF_ENQ'])
        self.put(FF_HOBJ + 0xC, FF_HDR)                       # FUN_c038a0f8()+0xc: the header bytes (-> frame +0x14C)
        self.put(0xC30337F0, TMR)                             # the timer block pointer; timer 5's count at +0x54
        self.put(TMR + 0x54, 0x00ABCDEF)
        self.put(0xC30781A4, 4321)                            # the tick's epoch
        for a, v in ((0x30100588, 0x123), (0x30100590, 0x7770000), (0x3010058C, 0x1000), (0x30182210, 2010),
                     (0x30182214, 1134), (0x30182218, 568), (0x301821E8, 0x31), (0x30182048, 0x10)):
            self.put(a, v)

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name == 'DCACHE':
            self.fflog.append('DCACHE')
        if name in FF_STUBS:
            r0, r1 = self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_R1)
            self.native.append((name, r0, r1))
            if name == 'FF_TABLE':
                return self.ret(FF_TAB)
            if name == 'FF_CAPMGR':
                return self.ret(FF_CAP)
            if name == 'FF_A0F8':
                return self.ret(FF_HOBJ)
            if name == 'FF_ENQGET':
                return self.ret(FF_ENQO)
            if name == 'FF_E18':
                return self.ret(0x1234)
            if name == 'FF_STOP':
                return self.ret(0x55)
            return self.ret(0)
        return super()._hook(mu, addr, size, data)

    def take(self):
        """a new take: the creator state before its first frame (+0x14 = 0x80000000, no stop / flag 2 pending)"""
        self.mu.mem_write(FF_ST, b'\0' * 0x40)
        self.mu.mem_write(FF_CTL, b'\0' * 0x10)
        self.put(FF_ST, FF_CTL)
        self.put(FF_ST + 0xC, 0x77)                           # param_1[3]: the state FUN_c038bd98 returns
        self.put(FF_ST + 0x14, 0x80000000)

    def ff(self):
        """the armed state {state, ras, row, rows, seed, id}"""
        return dict(zip('state ras row rows seed id'.split(),
                        struct.unpack('<6I', self.mu.mem_read(MEM + self.fn('ap_sizes_t', 19), 24))))

    def arm(self, mode, fmt=0, dest=FF_DEST):
        """ContSet_Adr1 C031C944..C031C94C: ldr r0, [r6, #0x38]; blx FUN_c0631b98 (hooked) -- r6 = desc - 8"""
        self.fflog.clear()
        self.mu.mem_write(FF_DESC, b'\0' * 0x1C0)
        self.put(FF_DESC + 0x1C, mode); self.put(FF_DESC + 0x20, fmt); self.put(FF_DESC + 0x38, dest)
        self.mu.reg_write(UC_ARM_REG_R6, FF_DESC)
        self.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
        self.mu.emu_start(0xC031C944, 0xC031C94C, **emu_cap(5_000_000))
        if self.error:
            raise self.error
        return self.r(UC_ARM_REG_R0)

    def arrive(self, raster, ident=7, error=0, keep=False):
        """the whole FUN_c038bd98(state, message type 5, fp) for frame `ident` (its raster at +0x4C): returns
        (value, the lookup's answer at C038BDB8, the native calls it made).  keep: the frame object as it is
        (CPU x2: its allocation record, filled by C037A990), else zeroed"""
        fr = FF_FRAMES + 0x1200 * (ident & 7)
        if not keep:
            self.mu.mem_write(fr, b'\0' * 0x1200)
        self.put(fr + 0x4C, raster)
        self.put(fr + 0x10FC, ident)
        self.put(fr + 0x1118, 0xFFFFFFFF)
        self.put(FF_TAB + 4 + 4 * ident, fr)
        self.mu.mem_write(FF_MSG, b'\0' * 0x100)
        self.put(FF_MSG + 0xC, 5)
        self.put(FF_MSG + 0xE4, error)
        self.put(FF_MSG + 0xE8, ident)
        self.native = []
        seen = []
        h = self.mu.hook_add(UC_HOOK_CODE, lambda uc, a, sz, d: seen.append(uc.reg_read(UC_ARM_REG_R0)),
                             begin=0xC038BDB8, end=0xC038BDB8)
        v = self.call(0xC038BD98, FF_ST, FF_MSG, 0x99, sp=STACK - 0x2004)
        self.mu.hook_del(h)
        return v, seen[0], [(n, a, b) for n, a, b in self.native if n not in ('FF_LOG0', 'FF_LOG', 'FF_TRACE')], fr

    def ram(self, a, n):
        return bytes(self.mu.mem_read(a, n))

    def done(self, ras, guard=None):
        """BUFA1's completion: FUN_c031bca0(ras) entry, through the hook, until the replayed push returns to C031BCA4"""
        hs = []
        if guard is not None:
            img = len(self.img)
            ok_code = lambda a: (BLOB <= a < BLOB + img or MEM <= a < MEM + AP_MEM or CAVE_ARENA <= a < CAVE_ARENA + 0x10000
                                 or a == FF_DONE)                                          # noqa: E731
            hs.append(self.mu.hook_add(UC_HOOK_CODE, lambda uc, a, sz, d: None if ok_code(a) else guard.append(('code', a))))
            ok_w = lambda a: MEM <= a < MEM + AP_MEM or STACK - 0x40000 <= a < STACK                 # noqa: E731
            hs.append(self.mu.hook_add(UC_HOOK_MEM_WRITE,
                                       lambda uc, acc, a, sz, v, d: None if ok_w(a) else guard.append(('write', a))))
        self.mu.reg_write(UC_ARM_REG_R0, ras)
        self.mu.reg_write(UC_ARM_REG_LR, DONE)
        self.mu.reg_write(UC_ARM_REG_SP, STACK - 0x3004)
        self.mu.emu_start(FF_DONE, FF_DONE + 4, **emu_cap(5_000_000))
        for h in hs:
            self.mu.hook_del(h)
        if self.error:
            raise self.error
        self.assertpc = self.r(UC_ARM_REG_PC)

    def trace(self):
        """(header words, [record dicts]) of the take's trace (ap_trace_info, the sq_test 33 pointer)"""
        t = self.fn('ap_trace_info', MEM) & 0xFFFFFFFF
        w = struct.unpack(f'<{TR_HDR + TR_N * TR_WORDS}I', self.mu.mem_read(t, 4 * (TR_HDR + TR_N * TR_WORDS)))
        hdr = dict(zip('magic ver rec_words nmax n lost take live seed row rows id done writes'.split(), w[:14]))
        recs = []
        for i in range(hdr['n']):
            r = w[TR_HDR + i * TR_WORDS:TR_HDR + (i + 1) * TR_WORDS]
            d = dict(zip(TR_KEYS, r[:14]))
            d['head0'], d['tail0'], d['head1'], d['tailn'] = list(r[14:22]), list(r[22:38]), list(r[38:46]), list(r[46:54])
            recs.append(d)
        return hdr, recs


def ff_mmio():
    """validation/20261103-first-frame-mmio-diff/mmio_diff.py on THIS module (a mutant run's own ap.c)"""
    sys.modules.setdefault('test_apply', sys.modules[__name__])
    d = str(ROOT / 'projects/sensorlab-imx410/validation/20261103-first-frame-mmio-diff')
    if d not in sys.path:
        sys.path.insert(0, d)
    argv = list(sys.argv)
    import mmio_diff
    sys.argv[:] = argv
    return mmio_diff


class FirstFrameTests(unittest.TestCase):
    """v0.7.27test: the sentinel at ContSet_Adr1 and the read-only trace at BUFA1's completion and FUN_c038bd98's lookup,
    the real sites of the real image"""
    def live(self, args=FF_12V2):
        cam = FFCam()
        self.assertEqual(cam.init(), AP_OK)
        self.assertEqual(cam.apply(recipe(*args)[0]), AP_OK, cam.status())
        return cam

    def frame(self, cam, row, rows, seed=1):
        """the take's real frame (what the second frame shows one row up), the file header and the guard after it"""
        import random
        rnd = random.Random(seed)
        ref = rnd.randbytes(row * rows)
        cam.mu.mem_write(FF_U, b'H' * FF_HDR)
        cam.mu.mem_write(FF_DEST, rnd.randbytes(row * rows))           # stale DRAM: an older frame / JPEG tiles
        cam.mu.mem_write(FF_DEST + row * rows, b'T' * 0x1000)
        return ref

    def test_the_sites(self):
        self.assertEqual((iw(FF_ARM), iw(FF_FIX)), (0xFA0C5492, 0xEBFFA581))
        self.assertEqual(iw(FF_ARM - 4), 0xE5960038, 'ldr r0, [r6, #0x38]: the destination of frame 1')
        self.assertEqual(iw(0xC031CAE0), 0xE3A00001, 'the BUFA1 start (mov r0, #1; blx FUN_c0631c08) follows the arm')
        self.assertEqual(iw(FF_FIX - 4), 0xE59610E8, 'ldr r1, [r6, #0xe8]: the arriving frame id')
        self.assertEqual(iw(0xC038BFD0), 0xEB000188, 'bl FUN_c038c5f8 (header DMA) after the lookup')
        self.assertEqual(iw(0xC038BFF0), 0xE12FFF33, 'the creator enqueue (Lossless arrival) after it')

    def sentinel(self, seed):
        x, out = seed, []
        for _ in range(16):
            x ^= (x << 13) & 0xFFFFFFFF; x ^= x >> 17; x ^= (x << 5) & 0xFFFFFFFF
            out.append(x)
        return out

    def digest(self, cam, ras, row, rows):
        u = ras - 0x80000000 if ras >= 0xC0000000 else ras
        rd = lambda a, n: list(struct.unpack(f'<{n}I', cam.ram(a, 4 * n)))   # noqa: E731
        return rd(u, 8), rd(u + row - 64, 16), rd(u + row, 8), rd(u + row * rows - 32, 8)

    RAS = [FF_DEST + k * 0x01000000 for k in range(4)]   # BUFA1's four buffers in the window

    def take_with_frames(self, shifted=True, guard=None):
        """a SensorLab 12v2 take: arm, then frame k's completion and writer arrival in turn, k = 1..5"""
        cam = self.live()
        cam.take()
        row, h = 4536, 2010
        ref = self.frame(cam, row, h)
        for k in range(1, 4):
            cam.mu.mem_write(self.RAS[k], bytes([k]) * (row * h))
        st = cam.status()
        cam.arm(st['mode_id'])
        after_arm = cam.ram(FF_DEST, row * h)
        if shifted:
            cam.mu.mem_write(FF_DEST + row, ref[:row * (h - 1)])          # BUFA1 shifted: row 0 never written
        else:
            cam.mu.mem_write(FF_DEST, ref)
        images = [cam.ram(r, row * h) for r in self.RAS]
        reads = []
        from unicorn import UC_HOOK_MEM_READ
        hr = cam.mu.hook_add(UC_HOOK_MEM_READ, lambda uc, acc, a, sz, v, d: reads.append((a, sz)),
                             begin=FF_U, end=FF_U + FF_SIZE - 1)
        hc = cam.mu.hook_add(UC_HOOK_MEM_READ, lambda uc, acc, a, sz, v, d: reads.append(('cached', a)),
                             begin=FF_U + 0x80000000, end=FF_U + 0x80000000 + FF_SIZE - 1)
        frames = []
        for k in range(5):
            ras = self.RAS[k % 4]
            cam.done(ras, guard)
            frames.append(cam.arrive(ras, ident=7 + k))
        cam.mu.hook_del(hr)
        cam.mu.hook_del(hc)
        return cam, row, h, ref, after_arm, images, reads, frames

    def test_the_sites(self):
        self.assertEqual((iw(FF_ARM), iw(FF_FIX), iw(FF_DONE)), (0xFA0C5492, 0xEBFFA581, 0xE92D4070))
        self.assertEqual(iw(FF_ARM - 4), 0xE5960038, 'ldr r0, [r6, #0x38]: the destination of frame 1')
        self.assertEqual(iw(0xC031CAE0), 0xE3A00001, 'the BUFA1 start (mov r0, #1; blx FUN_c0631c08) follows the arm')
        self.assertEqual(iw(FF_FIX - 4), 0xE59610E8, 'ldr r1, [r6, #0xe8]: the arriving frame id')
        self.assertEqual(iw(0xC038BFD0), 0xEB000188, 'bl FUN_c038c5f8 (header DMA) after the lookup')
        self.assertEqual(iw(0xC038BFF0), 0xE12FFF33, 'the creator enqueue (Lossless arrival) after it')
        # ContSet_Adr1's BUFA1 branch sets FUN_c031bca0 as BUFA1's callback (local_b4 -> FUN_c0630d30 -> _DAT_c37cf8fc),
        # which the IRQ handler FUN_c0630d60 calls with the completed raster
        self.assertEqual([iw(a) for a in (0xC031C884, 0xC031C888, 0xC031C88C)], [0xE30B1CA0, 0xE34C1031, 0xE58D1084],
                         'movw r1, #0xbca0; movt r1, #0xc031; str r1, [sp, #0x84]')

    def test_a_take_is_traced_arm_then_completion_and_writer_for_frames_1_to_4(self):
        cam, row, h, ref, after_arm, images, reads, frames = self.take_with_frames()
        hdr, recs = cam.trace()
        self.assertEqual((hdr['magic'], hdr['ver'], hdr['rec_words'], hdr['nmax']), (0x52544653, 1, 56, 12))
        self.assertEqual([r['kind'] for r in recs], [1] + [2, 3] * 4, 'arm, then completion / writer of frames 1..4')
        self.assertEqual([r['seq'] for r in recs], list(range(9)))
        self.assertEqual((hdr['n'], hdr['lost'], hdr['take'], hdr['live'], hdr['done'], hdr['writes']), (9, 0, 1, 0, 4, 4))
        self.assertEqual((hdr['row'], hdr['rows'], hdr['id']), (row, h, cam.status()['mode_id']))
        arm = recs[0]
        self.assertEqual((arm['ras'], arm['x0'], arm['x1'], arm['x2'], arm['x3']),
                         (FF_DEST, cam.status()['mode_id'], 2010, 1134, 568))
        self.assertEqual(arm['tail0'], self.sentinel(hdr['seed']), 'the arm record shows the sentinel in place')
        for r in recs:
            self.assertEqual((r['epoch'], r['raw'], r['tg_frame'], r['tg_line'], r['tg_flags'], r['ok']),
                             (4321, 0xABCDEF, 0x123, 0x7770000, 0x1000, 1))
        for k in range(4):
            d, wr = recs[1 + 2 * k], recs[2 + 2 * k]
            self.assertEqual((d['ras'], d['x0'], d['x1'], d['x2'], d['x3'], d['us']), (self.RAS[k], 0x31, cam.w(0x30182280), k + 1, 0x10, 0))
            self.assertEqual((wr['ras'], wr['x0'], wr['x1'], wr['x2']), (self.RAS[k], 7 + k, frames[k][3], k + 1))
            want = self.digest(cam, self.RAS[k], row, h)
            for r in (d, wr):
                self.assertEqual((r['head0'], r['tail0'], r['head1'], r['tailn']), want, k)
        # frame 1 was shifted: its row-0 tail still holds the sentinel at the completion and at the writer
        self.assertEqual(recs[1]['tail0'], self.sentinel(hdr['seed']))
        self.assertEqual(recs[1]['head1'], list(struct.unpack('<8I', ref[:32])), 'row 1 = the real line 0')
        st = cam.status()
        self.assertEqual((st['first_checks'], st['first_intact'], st['first_ok'], st['trace_n'], st['trace_lost']),
                         (1, 1, 0, 9, 0))
        # read-only: nothing dropped or moved, every frame enqueued, rasters as BUFA1 left them
        for k in range(5):
            self.assertNotEqual(frames[k][1], 0)
            self.assertIn('FF_ENQ', [c[0] for c in frames[k][2]])
        for k in range(4):
            self.assertEqual(cam.ram(self.RAS[k], row * h), images[k], k)
        self.assertNotIn('DCACHE', cam.fflog[2:], 'no cache pass after the arm')

    def test_the_digest_reads_exactly_its_addresses_uncached(self):
        cam, row, h, ref, after_arm, images, reads, frames = self.take_with_frames()
        self.assertFalse([r for r in reads if r[0] == 'cached'], 'never through the cached alias')
        want = set()
        for k in range(4):
            u = self.RAS[k]
            for a, n in ((u, 32), (u + row - 64, 64), (u + row, 32), (u + row * h - 32, 32)):
                want |= set(range(a, a + n, 4))
        got = {a for a, sz in reads}
        sent = set(range(FF_DEST + row - 64, FF_DEST + row, 4))           # the writer-side sentinel check (frame 1)
        self.assertEqual(got - sent, want - sent)
        self.assertTrue(sent <= got)
        self.assertTrue(all(sz == 4 for a, sz in reads))

    def test_a_normal_first_frame_traces_the_overwritten_sentinel(self):
        cam, row, h, ref, *_ = self.take_with_frames(shifted=False)
        hdr, recs = cam.trace()
        self.assertNotEqual(recs[1]['tail0'], self.sentinel(hdr['seed']))
        self.assertEqual(recs[1]['tail0'], list(struct.unpack('<16I', ref[row - 64:row])), 'BUFA1 overwrote it')
        st = cam.status()
        self.assertEqual((st['first_checks'], st['first_intact'], st['first_ok']), (1, 0, 1))
        self.assertEqual(cam.ram(FF_DEST, row * h), ref)

    def test_the_irq_site_calls_nothing_and_writes_only_the_trace(self):
        guard = []
        cam, *_ = self.take_with_frames(guard=guard)
        self.assertEqual(guard, [], 'FUN_c031bca0 hook: no firmware code, no write outside struct ap and its stack')
        self.assertEqual(cam.assertpc, FF_DONE + 4, 'back at the replayed push')
        hdr, recs = cam.trace()
        self.assertEqual(sum(r['kind'] == 2 for r in recs), 4)

    def test_the_trace_resets_per_take_and_stops_after_four_frames(self):
        cam, row, h, *_ = self.take_with_frames()
        self.assertEqual(cam.trace()[0]['n'], 9)
        for k in range(3):                                       # more frames of the same take: not recorded
            cam.done(self.RAS[k])
            cam.arrive(self.RAS[k], ident=20 + k)
        self.assertEqual(cam.trace()[0]['n'], 9)
        cam.now = 777                                            # the next take
        cam.take()
        cam.arm(cam.status()['mode_id'])
        hdr, recs = cam.trace()
        self.assertEqual((hdr['n'], hdr['take'], hdr['live'], [r['kind'] for r in recs]), (1, 2, 1, [1]))
        cam.done(self.RAS[0])
        self.assertEqual([r['kind'] for r in cam.trace()[1]], [1, 2])
        # a commit (never while recording) ends any trace
        self.assertEqual(cam.apply(recipe(*ALT_ARGS)[0]), AP_OK)
        cam.done(self.RAS[1])
        self.assertEqual(cam.trace()[0]['n'], 2)

    def test_completions_ahead_of_the_writer_are_capped_at_four_each(self):
        cam = self.live()
        cam.take()
        row, h = 4536, 2010
        self.frame(cam, row, h)
        cam.arm(cam.status()['mode_id'])
        for k in range(6):
            cam.done(self.RAS[k % 4])
        for k in range(6):
            cam.arrive(self.RAS[k % 4], ident=7 + k)
        hdr, recs = cam.trace()
        self.assertEqual([r['kind'] for r in recs], [1, 2, 2, 2, 2, 3, 3, 3, 3])
        self.assertEqual((hdr['done'], hdr['writes'], hdr['live'], hdr['lost']), (4, 4, 0, 0))

    def test_an_unfinished_trace_never_spills_into_a_stock_take(self):
        cam = self.live()
        cam.take()
        row, h = 4536, 2010
        self.frame(cam, row, h)
        cam.arm(cam.status()['mode_id'])
        s1 = cam.trace()[0]['seed']
        cam.done(self.RAS[0])
        cam.arrive(self.RAS[0])                                  # stopped after one frame: the trace is still live
        self.assertEqual(cam.trace()[0]['live'], 1)
        cam.take()
        cam.arm(106)                                             # a stock-mode take through the same BUFA1 site
        for k in range(3):
            cam.done(self.RAS[k])
            cam.arrive(self.RAS[k], ident=9 + k)
        hdr, recs = cam.trace()
        self.assertEqual(([r['kind'] for r in recs], hdr['live']), ([1, 2, 3], 0))
        cam.now = 999
        cam.take()
        cam.arm(cam.status()['mode_id'])
        hdr = cam.trace()[0]
        self.assertNotEqual(hdr['seed'], s1, 'a new seed per take')
        self.assertEqual(cam.ram(FF_DEST + row - 64, 64), struct.pack('<16I', *self.sentinel(hdr['seed'])))

    def test_true_14_bit_lines(self):
        cam = self.live(R14_1X1)
        cam.take()
        self.frame(cam, 5292, 2020)
        cam.arm(cam.status()['mode_id'], fmt=1)
        hdr, recs = cam.trace()
        self.assertEqual((hdr['row'], hdr['rows']), (3024 * 14 // 8, 2020))
        self.assertEqual(recs[0]['tail0'], self.sentinel(hdr['seed']))

    def test_stock_modes_are_never_traced_or_touched(self):
        row, h = 4536, 2010
        for live in (False, True):
            cam = self.live() if live else FFCam()
            if not live:
                self.assertEqual(cam.init(), AP_OK)
            ref = self.frame(cam, row, h)
            before = cam.ram(FF_U, FF_HDR + row * h)
            cam.fflog.clear()
            modes = (106, 97, cam.status()['mode_id'] ^ 1) if live else (106, 97, 230, 231)
            for mode in modes:
                cam.take()
                cam.arm(mode)
                cam.done(FF_DEST)
                _, seen, calls, fr = cam.arrive(FF_DEST)
                self.assertEqual(seen, fr)
                self.assertIn('FF_ENQ', [c[0] for c in calls])
            self.assertEqual(cam.ram(FF_U, FF_HDR + row * h), before)
            self.assertEqual(cam.fflog, [], 'the raster is neither read nor written')
            st = cam.status()
            self.assertEqual((st['first_arms'], st['first_checks'], st['trace_n']), (0, 0, 0))
            self.assertEqual(cam.trace()[0]['n'], 0)
        cam.arm(cam.status()['mode_id'], dest=0x30000000)         # outside DRAM's aliases: skipped, never written
        self.assertEqual((cam.status()['first_skips'], cam.ff()['state'], cam.trace()[0]['live']), (1, 0, 0))

    def test_record_start_arms_frame_1_before_the_bufa1_start(self):
        """the whole REC start (mmio_diff.py: SetImgMode_s + ContSet_Adr1 of the real image, ap.c's hooks live): the
        sentinel lands in the destination's row 0 after a D-clean and before 0x30182004 = 4; the geometry ap.c armed is
        the one the firmware programs into BUFA1 (line words x 4, lines); stock UHD (BUFA1, same site) is not armed"""
        MD = ff_mmio()
        self.assertEqual(MD.DEST, FF_U)
        for case in ('12v2', '1x1_12', 'stockUHD30', 'stock106'):
            cam = MD.setup(case)
            if cam.sel is None:                               # stock: the sup is loaded, nothing selected
                self.assertEqual(cam.init(), AP_OK)
            ff_window(cam)
            hits = []
            cam.mu.hook_add(UC_HOOK_CODE, lambda uc, a, sz, d: hits.append(1), begin=FF_ARM, end=FF_ARM)
            marks = []
            cam.mu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, a, sz, v, d: marks.append(len(cam.mmio)),
                            begin=FF_U, end=FF_U + FF_SIZE - 1)
            for g in MD.GUARDS_DONE:
                cam.put(g, 1)
            cam.put(MD.CUR_MODE, 0)
            cam.run(0xC031A0F8)
            cam.put(0xC343A78C, 2)
            cam.run(0xC0313400, MD.CUR_MODE, MD.STANDBY_MODE)
            cam.order.clear()
            MD.record_start(cam)
            fin = MD.final_values(cam)
            start = [i for i, (_, pc, a, sz, v, _c) in enumerate(cam.mmio) if a == 0x30182004 and v == 4]
            if case == 'stock106':
                self.assertEqual((hits, marks), ([], []), 'BUFA7: the site is not on its path')
                continue
            self.assertTrue(hits and start, case)
            if case == 'stockUHD30':
                self.assertEqual(marks, [], 'stock BUFA1: never armed')
                self.assertEqual(cam.status()['active'], 0)
                continue
            ff = cam.ff() if hasattr(cam, 'ff') else dict(zip('state ras row rows seed id'.split(), struct.unpack(
                '<6I', cam.mu.mem_read(MEM + cam.fn('ap_sizes_t', 19), 24))))
            self.assertEqual((ff['state'], ff['ras'], ff['id']), (1, FF_U, cam.mode), case)
            self.assertEqual((ff['row'], ff['rows']), (fin[0x30182214][0] * 4, fin[0x30182210][0]), case)
            self.assertTrue(marks and max(marks) < start[0], (case, marks[:3], start))
            self.assertIn('DCACHE', cam.order, case)
            words = struct.unpack('<16I', cam.mu.mem_read(FF_U + ff['row'] - 64, 64))
            self.assertNotIn(0, words)
            self.assertEqual(cam.mu.mem_read(FF_U, ff['row'] - 64), b'\0' * (ff['row'] - 64), 'only the 64 bytes')


# ---- v0.7.28test: the native sensor pause / resume + link resync at REC start ----
RS_SITE = 0xC031BF88                                      # ContSet_Adr1: bl SetImgMode_s
RS_SITE2 = 0xC030D168                                     # the image controller task's message 1: bl SetImgMode_s


class _Log(list):
    """cam.sensor / cam.events that also feed one ordered log"""
    def __init__(self, log, tag):
        super().__init__()
        self.log, self.tag = log, tag

    def append(self, x):
        super().append(x)
        self.log.append((self.tag,) + tuple(x))


class ResyncTests(unittest.TestCase):
    """the whole REC start (mmio_diff.py: SetImgMode_s + ContSet_Adr1 of the real image, the apply hooks live); the
    GPIO driver calls, sleeps and VD waits are stubs, recorded in order with every sensor write"""
    def rec(self, case, period=None, slot=False, contset_switch=False):
        """the REC start as the camera does it (v0.7.28test live: C031BF88 never reached): the image controller
        task switches the mode (message 1, C030D160..C030D16C), then ContSet_Adr1 runs with that mode already current
        and skips its own switch.  contset_switch=True: mmio_diff's old order (ContSet_Adr1 switches itself)"""
        MD = ff_mmio()
        cam = MD.setup(case)
        if cam.sel is None:
            self.assertEqual(cam.init(), AP_OK)
            if slot:                                          # a SensorLab slot live, but the take records stock's mode
                self.assertEqual(cam.apply(recipe(*FF_12V2)[0]), AP_OK)
                self.assertNotEqual(cam.status()['mode_id'], cam.mode)
        ff_window(cam)
        for n, a in (('GPIO_CFG', 0xC00FDCF0), ('GPIO_SET', 0xC00FE3A8)):
            cam.stubs[n] = (a, 'ret0')
            cam.stub(a, n)
        if period is not None:
            cam.stubs['PERIOD'] = (0xC0125CA8, lambda c: c.ret(period))
            cam.stub(0xC0125CA8, 'PERIOD')
        log = []
        for nm, a in (('ARM', FF_ARM), ('START', 0xC031CAE0), ('V21', 0xC0325078), ('SITE_CONTSET', RS_SITE),
                      ('SITE_IMGCTRL', RS_SITE2)):                                     # before any code runs: unicorn
            cam.mu.hook_add(UC_HOOK_CODE, (lambda nm: lambda uc, a, sz, d: log.append((nm,)))(nm), begin=a, end=a)   # keeps
        for g in MD.GUARDS_DONE:                                                       # translated blocks
            cam.put(g, 1)
        cam.put(MD.CUR_MODE, 0)
        cam.run(0xC031A0F8)
        cam.put(0xC343A78C, 2)
        cam.run(0xC0313400, MD.CUR_MODE, MD.STANDBY_MODE)
        log.clear()
        cam.sensor, cam.events = _Log(log, 'S'), _Log(log, 'E')
        cam.put(0xC343B688, 0)                                # the 0000 shadow as init leaves it (C03233D8)
        if contset_switch:
            MD.record_start(cam)
        else:
            msg = WORK + 0xF000                               # FUN_c030d0c0's message: +0x1BC = the mode (FUN_c030ce00)
            cam.mu.mem_write(msg, b'\0' * 0x1C4)
            cam.put(msg + 0x1BC, cam.mode)
            cam.mu.reg_write(UC_ARM_REG_R4, msg)
            cam.mu.reg_write(UC_ARM_REG_SP, STACK - 0x8000)
            cam.mu.emu_start(0xC030D160, 0xC030D16C, **emu_cap(200_000_000))
            if cam.error:
                raise cam.error
            self.assertEqual(cam.w(MD.CUR_MODE), cam.mode, 'the image controller switched the mode')
            d = MD.DESCBUF                                    # FUN_c030cf98's ContSet_Adr1 call, the mode NOT forced back
            cam.mu.mem_write(d, b'\0' * 0x1C0)
            cam.put(d + 0x1C, cam.mode); cam.put(d + 0x20, 0); cam.put(d + 0x28, 0); cam.put(d + 0x38, MD.DEST)
            cam.mmio.clear()
            cam.run(MD.CONTSET, MD.CONT_CTX, d)
        ev = [e for e in log if e[0] != 'E' or e[1] in ('SLEEP_MS', 'VD_WAIT', 'GPIO_CFG', 'GPIO_SET')]
        ev = [('S', e[1], e[2]) if e[0] == 'S' else (e[1], int(e[2], 16), int(e[3], 16)) if e[0] == 'E' and e[1] == 'GPIO_SET' else
              (e[1], int(e[2], 16)) if e[0] == 'E' else e for e in ev]
        return cam, ev

    NATIVE = [('S', 0xCA, 0), ('SLEEP_MS', 1), ('S', 0x00, 2), ('S', 0xC6, 1), ('S', 0xC5, 0x11),
              ('GPIO_CFG', 0x544), ('GPIO_SET', 0x544, 1), ('VD_WAIT', 0),
              ('S', 0x00, 0), ('GPIO_CFG', 0x544), ('GPIO_SET', 0x544, 0), ('SLEEP_MS', 12), ('S', 0xC6, 0),
              ('S', 0xC5, 0), ('S', 0xCA, 1), ('SLEEP_MS', 1), ('V21',)]

    def test_the_site(self):
        self.assertEqual((iw(RS_SITE), iw(RS_SITE2)), (0xEBFFDD1C, 0xEB0018A4))
        self.assertEqual(iw(RS_SITE2 - 4), 0xE59411BC, 'ldr r1, [r4, #0x1bc]: the message mode')
        self.assertEqual(iw(RS_SITE2 - 8), 0xEB00188E, 'bl FUN_c03133a0: the image-mode object')
        self.assertEqual(iw(RS_SITE - 8), 0xE596101C, 'ldr r1, [r6, #0x1c]: the record mode')
        self.assertEqual(iw(RS_SITE - 4), 0xE59D0030, 'ldr r0, [sp, #0x30]: the image-mode object')
        self.assertEqual(iw(0xC0325110), 0xE92D4030, 'v27')
        self.assertEqual(struct.unpack_from('<I', image(), 0xC0B5FCC0 + 0x74 - 0xC0000000)[0], 0xC0325110,
                         'the IMX410 vtable (+0xD0) slot +0x74 is v27')

    def test_our_record_start_runs_the_native_pause_resume_once_before_the_bufa1_arm(self):
        for case in ('12v2', '1x1_12'):
            cam, ev = self.rec(case)
            i11 = max(i for i, e in enumerate(ev) if e[:2] == ('S', 0x11))
            self.assertEqual(ev[i11], ('S', 0x11, 1), 'the mode switch restarted the sensor first')
            i0 = next(i for i, e in enumerate(ev) if i > i11 and e == ('S', 0xCA, 0))
            got = [('VD_WAIT',) if e[0] == 'VD_WAIT' else e for e in ev[i0:i0 + len(self.NATIVE)]]
            want = [('VD_WAIT',) if e[0] == 'VD_WAIT' else e for e in self.NATIVE]
            self.assertEqual(got, want, case)
            gpio = [e for e in ev[i0:] if e[0] == 'GPIO_SET'][:2]
            rest = ev[i0 + len(self.NATIVE):]
            self.assertEqual(rest[0][0], 'VD_WAIT', 'a VD after the resume, as the native loops do')
            self.assertLess(i0, ev.index(('ARM',)), 'before the BUFA1 arm')
            self.assertLess(ev.index(('ARM',)), ev.index(('START',)))
            self.assertEqual(sum(1 for e in ev if e == ('S', 0xC5, 0x11)), 1, 'once')
            self.assertIn(('SITE_IMGCTRL',), ev)
            self.assertNotIn(('SITE_CONTSET',), ev, 'ContSet_Adr1 finds the mode current: its switch is skipped')
            self.assertLess(ev.index(('SITE_IMGCTRL',)), i0)
            st = cam.status()
            self.assertEqual((st['resync_calls'], st['resync_skips'], st['first_arms'], st['resync_seen'],
                              st['resync_ours']), (1, 0, 1, 1, 1), case)
            self.assertEqual(cam.w(0xC343B688) & 0xFF, 0, 'v27 kept the 0000 shadow (2 during the pause, 0 after)')
            self.assertEqual(len(gpio), 2)


    def test_stock_record_starts_are_untouched(self):
        for case, slot in (('stockUHD30', False), ('stock106', False), ('stockUHD30', True)):
            cam, ev = self.rec(case, slot=slot)
            self.assertNotIn(('S', 0xC5, 0x11), ev, case)
            self.assertFalse([e for e in ev if e[0] in ('GPIO_CFG', 'GPIO_SET')], case)
            st = cam.status()
            self.assertEqual((st['resync_calls'], st['resync_skips'], st['first_arms'], st['resync_seen'],
                              st['resync_ours']), (0, 0, 0, 1, 0), case)

    def test_a_contset_switch_gets_it_too(self):
        """if ContSet_Adr1 ever switches itself (mode not yet current), the same sequence runs there, once"""
        cam, ev = self.rec('12v2', contset_switch=True)
        self.assertIn(('SITE_CONTSET',), ev)
        self.assertEqual(sum(1 for e in ev if e == ('S', 0xC5, 0x11)), 1)
        self.assertLess(ev.index(('S', 0xC5, 0x11)), ev.index(('ARM',)))
        st = cam.status()
        self.assertEqual((st['resync_calls'], st['resync_seen'], st['resync_ours']), (1, 1, 1))

    def test_frame_periods_v27_ignores_are_skipped_without_a_call(self):
        cam, ev = self.rec('12v2', period=15000)              # <= 15 ms: v27's own guard would do nothing
        self.assertNotIn(('S', 0xC5, 0x11), ev)
        self.assertFalse([e for e in ev if e[0] in ('GPIO_CFG', 'GPIO_SET')])
        st = cam.status()
        self.assertEqual((st['resync_calls'], st['resync_skips'], st['first_arms'], st['resync_seen'], st['resync_ours']),
                         (0, 1, 1, 1, 1), 'the trace still arms')
        cam, ev = self.rec('12v2', period=15001)
        self.assertEqual(cam.status()['resync_calls'], 1)


# ---- mutation: each must make the named test class fail ----
# Not listed (equivalent on every reachable input): the fast threshold 99.0 -> 100.0 (engines are <= 60 stock or the
# real rate > 119.88), the busy() guard inside ap_commit that ap_run's callers also cover only through it (kept).
# ---- CPU x2: the streaming ISP-stage pass (notes/CPU_X2_DESIGN.md "Per-frame pass (streaming)") ----
H2_SITE = 0xC037ACDC                                       # FUN_c037a990: bl FUN_c02da770(frame + 0x10), r4 = frame
H2_DEST1, H2_DEST, H2_DONE = 0xC031C550, 0xC031CCF4, 0xC031BB50
H2_SLICE = (0xC037ACD8, 0xC037AD2C)                        # add r0, r4, #0x10 .. the C001CFD8 allocation returned
H2_SIZE_FN, H2_ALLOC = 0xC02DA770, 0xC001CFD8
H2_S35 = (4192, 2358, 2096, 1178, '1x2')                   # S35 12v2-cpu2 / 14v2-cpu2: rec 2096 x 1178 (the smallest)
H2_RESERVE = 0x15400
H2_CURSOR, H2_FLAGS = 0x30182184, 0x30182120
H2_PRI, H2_STACK, H2_TAG = 16, 0x1000, 0xFD58
H2_LWORDS, H2_LINES = 0x30182114, 0x30182110               # BUFA0 words per line / lines (FUN_c06306e0)
H2_V3 = 'period_us wait_ms need_mbps line_words lines line_bad entry run_pc run_sp ras_c'.split()
CLEAN_APPLY = ROOT / 'projects/sensorlab-imx410/validation/20261105-clean-v0.7.37test/source/sensorlab-imx410/apply'
H2_KEYS = ('magic ver armed task n bits row rows line mv take failed refused alloc_bad doubled queued binned stops strips '
           'waits wait_max last_us max_us total_us nsamp').split()
H2_OPS = {0x0F36: 'inval', 0x0F3A: 'clean', 0x0F3E: 'cinval'}   # Thumb-2 mcr p15, 0, rt, c7, c6/c10/c14, 1
W = dict(ALLOC=1, FLIP=2, QFULL=3, KIND=4, CAP=5, NOQ=6, LATE=7, KERNEL=8, LINE=9)


@functools.lru_cache(None)
def h2_ref_module():
    """tools/cpu_h2/test_h2_packed.py: its independent Python reference (pack / unpack / h2_ref)"""
    d = str(ROOT / 'projects/sensorlab-imx410/tools/cpu_h2')
    if d not in sys.path:
        sys.path.insert(0, d)
    import test_h2_packed
    return test_h2_packed


def h2_reference(data, bits):
    """the whole raster as one stream, the reference applied per kernel step (pairs never cross 4 px)"""
    R = h2_ref_module()
    step = {12: 48, 14: 28}[bits]
    assert len(data) % step == 0
    return b''.join(R.pack(R.h2_ref(R.unpack(data[i:i + step], bits)), bits) for i in range(0, len(data), step))


class H2Cam(FFCam):
    """FFCam (the real FUN_c038bd98, BUFA0's real destination setter FUN_c0631640) + the real FUN_c037a990 kind-1
    allocation slice, NEON on, the D-cache ops and the strips recorded at the unit's own instructions; the DRAM
    window's per-access hooks removed (the kernel streams megabytes)"""
    def __init__(self, **kw):
        super().__init__(**kw)
        for h in self._ffhooks:
            self.mu.hook_del(h)
        self.mu.reg_write(UC_ARM_REG_C1_C0_2, 0x00F00000)
        self.mu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        # the sup's block (code + state) at both aliases, one memory (sloader4.h: 0x4... uncached, +0x80000000 cached)
        from unicorn import UC_PROT_ALL
        self._alias_mem = ctypes.create_string_buffer(0x00300000)
        self.mu.mem_unmap(BLOB, 0x00200000)
        self.mu.mem_unmap(MEM, 0x00100000)
        for base in (BLOB, BLOB + 0x80000000):
            self.mu.mem_map_ptr(base, 0x00300000, UC_PROT_ALL, ctypes.addressof(self._alias_mem))
        self.mu.mem_write(BLOB, self.img)
        self.size_native, self.alloc_req = 0, []
        self.stub(H2_SIZE_FN, 'H2_SIZE')
        self.stub(H2_ALLOC, 'H2_ALLOC')
        self.stub(0xC03705D8, 'TK_DLY')                    # tk_dly_tsk (the base Cam leaves it to the resync tests)
        self.ops, self.strips = [], []
        sites = set()
        for fn in ('ap_h2_inval', 'ap_h2_clean'):
            if fn not in self.funcs:                       # the pre-CPU-x2 unit (CLEAN_APPLY)
                continue
            at = self.funcs[fn] & ~1
            for o in range(at, at + 0x80, 2):
                hw1, hw2 = struct.unpack_from('<HH', self.img, o)
                if hw1 == 0xEE07 and hw2 & 0x0FFF in H2_OPS and o not in sites:
                    sites.add(o)
                    op, rt = H2_OPS[hw2 & 0x0FFF], hw2 >> 12
                    self.mu.hook_add(UC_HOOK_CODE, lambda uc, a, sz, d, op=op, rt=rt:
                                     self.ops.append((op, uc.reg_read(UC_ARM_REG_R0 + rt))), begin=BLOB + o, end=BLOB + o)
        if 'ap_h2_strip' in self.funcs:
            at = BLOB + (self.funcs['ap_h2_strip'] & ~1)
            self.mu.hook_add(UC_HOOK_CODE, lambda uc, a, sz, d: self.strips.append(
                tuple(uc.reg_read(r) for r in (UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))), begin=at, end=at)
        self.mcr_sites = sum(1 for o in range(0, len(self.img) - 4, 2)
                             if struct.unpack_from('<HH', self.img, o)[0] == 0xEE07 and
                             struct.unpack_from('<HH', self.img, o)[1] & 0x0FFF in H2_OPS)

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name == 'H2_SIZE':
            self.calls.append((name, self.r(UC_ARM_REG_R0), 0))
            return self.ret(self.size_native)
        if name == 'H2_ALLOC':
            r0, r1, r2, r3 = (self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))
            self.alloc_req.append((r0, r1, r2, r3))
            self.put(r1, FF_U); self.put(r1 + 4, r2); self.put(r1 + 8, 10)      # {handle, capacity = asked, class}
            return self.ret(0)
        return super()._hook(mu, addr, size, data)

    def frame_at(self, ident):
        return FF_FRAMES + 0x1200 * (ident & 7)

    def allocate(self, ident, n, kind=1):
        """FUN_c037a990's kind-1 tail for frame `ident` (C037ACD8..C037AD2C, real code): the size it asks C001CFD8"""
        fr = self.frame_at(ident)
        self.mu.mem_write(fr, b'\0' * 0x1200)
        self.put(fr + 4, kind); self.put(fr + 0x128, H2_RESERVE)
        self.size_native, self.alloc_req = n, []
        self.mu.reg_write(UC_ARM_REG_R4, fr)
        self.mu.reg_write(UC_ARM_REG_R11, WORK + 0x9000)
        self.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
        self.mu.emu_start(H2_SLICE[0], H2_SLICE[1], **emu_cap(5_000_000))
        if self.error:
            raise self.error
        (cls, rec, size, align), = self.alloc_req
        self.assertpc = self.r(UC_ARM_REG_PC)
        return size, rec, cls, align

    def run(self, start, stop, **regs):
        self.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
        names = dict(r0=UC_ARM_REG_R0, r4=UC_ARM_REG_R4, r6=UC_ARM_REG_R6)
        for k, v in regs.items():
            self.mu.reg_write(names[k], v)
        self.mu.emu_start(start, stop, **emu_cap(5_000_000))
        if self.error:
            raise self.error
        return self.r(UC_ARM_REG_PC)

    def dest(self, ras, first):
        """ContSet_Adr1 C031C54C..C031C554 (ldr r0, [r6, #0x38]; blx FUN_c0631640) / ContSet_Mem0 C031CCF0..C031CCF8
        (mov r0, r4; blx FUN_c0631640): the real destination setter below the hook; returns 0x30182180"""
        if first:
            self.mu.mem_write(FF_DESC, b'\0' * 0x100)
            self.put(FF_DESC + 0x38, ras)
            self.run(0xC031C54C, 0xC031C554, r6=FF_DESC)
        else:
            self.run(0xC031CCF0, 0xC031CCF8, r4=ras)
        return self.w(0x30182180)

    def done(self, ras, guard=None):
        """BUFA0's completion: FUN_c031bb50(ras) entry through the hook, until the replayed push returns to C031BB54"""
        self.mu.reg_write(UC_ARM_REG_LR, DONE)
        return self.run(H2_DONE, H2_DONE + 4, r0=ras)

    def cursor(self, ras, off):
        """BUFA0's write cursor at byte `off` of the raster: word address of the physical byte"""
        self.put(H2_CURSOR, (ras - 0x40000000 + off) >> 2)

    def step(self):
        return self.fn('ap_h2_step', MEM)

    def drain(self):
        n = 0
        while self.step():
            n += 1
        return n

    def picked(self, key='UHD30'):
        return self.call(PICKER, 0, TAB3, self.key(key))

    def h2(self):
        p = self.fn('ap_h2_info', MEM) & 0xFFFFFFFF
        n = len(H2_KEYS)
        d = dict(zip(H2_KEYS, struct.unpack(f'<{n}I', self.mu.mem_read(p, 4 * n))))
        d['samp'] = [struct.unpack('<2I', self.mu.mem_read(p + 4 * n + 8 * i, 8)) for i in range(16)]
        v3 = p + self.fn('ap_sizes_t', 22)
        d.update(zip(H2_V3, struct.unpack(f'<{len(H2_V3)}I', self.mu.mem_read(v3, 4 * len(H2_V3)))))
        d['bench'] = list(struct.unpack('<8I', self.mu.mem_read(v3 + 4 * len(H2_V3), 32)))
        return d


class CpuX2StreamTests(unittest.TestCase):
    """CPU x2 per D1-D7: the allocation doubled for a guaranteed take, the frame queued at BUFA0's destination, binned
    in place strip by strip as the write cursor advances (byte-exact against tools/cpu_h2's reference), finished after
    BUFA0's completion, and at SRecRaw either passed on binned or dropped with the take stopped by the firmware's own
    message +0xE4 path; nothing for any other slot"""

    def same(self, got, want, msg=''):
        """big buffers / op lists: no difflib (a failing assertEqual on megabytes never finishes)"""
        if got != want:
            k = next((k for k in range(min(len(got), len(want))) if got[k] != want[k]), min(len(got), len(want)))
            self.fail(f'{msg}: differ at {k} (len {len(got)} vs {len(want)}): {got[k:k + 4]!r} vs {want[k:k + 4]!r}')

    def live(self, bits=12, cam=None):
        cam = cam or H2Cam()
        self.assertEqual(cam.init(), AP_OK)
        self.assertEqual(cam.apply(recipe(*(H2_S35 + (bits,)), hbin=2)[0]), AP_OK, cam.status())
        cam.picked()
        n, row, rows = self.geom(bits)                       # D11 (4): a 14-bit AD records true 14
        cam.put(H2_LWORDS, row // 4); cam.put(H2_LINES, rows)   # BUFA0 as FUN_c06306e0 programs it for the take
        return cam

    @staticmethod
    def geom(bits, w=2096, h=1178):
        return w * h * bits // 8, 2 * w * bits // 8, h     # native bytes n, hardware row bytes, rows

    def queued(self, bits=12, seed=7, fill=None, ad=None):
        """a take whose frame 1 is allocated and handed to BUFA0; the raster holds `fill` (the DMA has not written).
        ad: the recipe's AD when it differs from the recorded bits (none since D11 (4): a 14-bit AD records 14)"""
        import random
        cam = self.live(ad or bits)
        n, row, rows = self.geom(bits)
        cam.allocate(1, n)
        cam.mu.mem_write(FF_U, b'H' * H2_RESERVE)
        cam.mu.mem_write(FF_DEST, (fill or b'\xEE') * (2 * n))
        cam.mu.mem_write(FF_DEST + 2 * n, b'T' * 0x1000)
        cam.cursor(FF_DEST, 0)
        cam.take()
        cam.dest(FF_DEST, first=True)
        return cam, n, row, rows, random.Random(seed).randbytes(2 * n)

    def expected_ops(self, cam, strips, n, row):
        L = cam.h2()['line']
        c, end = FF_DEST + 0x80000000, FF_DEST + 0x80000000 + 2 * n
        want = []
        for ras, r0, r1 in strips:
            self.assertEqual(ras, FF_DEST)
            lo, hi = c + r0 * row, c + r1 * row
            want += [('cinval' if a + L > end else 'inval', a) for a in range(lo & ~(L - 1), hi, L)]
            lo, hi = c + (r0 * row >> 1), c + (r1 * row >> 1)
            want += [('clean', a) for a in range(lo & ~(L - 1), hi, L)]
        return want

    # ---- the sites, the commit ----
    def test_the_sites(self):
        self.assertEqual(iw(H2_SITE), 0xEBFD7EA3, 'bl FUN_c02da770')
        self.assertEqual(iw(H2_SITE - 4), 0xE2840010, 'add r0, r4, #0x10: the frame descriptor')
        self.assertEqual(iw(0xC037A99C), 0xE1A04001, 'mov r4, r1: r4 = the frame throughout')
        self.assertEqual([iw(a) for a in (0xC037AD14, 0xC037AD18, 0xC037AD1C)], [0xE5942128, 0xE082200C, 0xE2841068],
                         'size = frame[0x128] + round512(C02DA770), into frame + 0x68')
        self.assertEqual((iw(H2_DEST1 - 4), iw(H2_DEST1)), (0xE5960038, 0xFA0C543A), 'ldr r0, [r6, #0x38]; blx C0631640')
        self.assertEqual((iw(H2_DEST - 4), iw(H2_DEST)), (0xE1A00004, 0xFA0C5251), 'mov r0, r4; blx C0631640')
        self.assertEqual(ap_target_of(H2_DEST1), 0xC0631641)
        self.assertEqual(ap_target_of(H2_DEST), 0xC0631641)
        self.assertEqual(iw(H2_DONE), 0xE92D40F0, 'FUN_c031bb50 push {r4-r7, lr}: BUFA0 completion callback')
        self.assertEqual(iw(FF_FIX), 0xEBFFA581, 'bl FUN_c03753c0: the arrival lookup (H_FFFIX)')
        self.assertEqual(iw(0xC038BE78), 0xE59630E4, 'ldr r3, [r6, #0xe4]: the drop test after the lookup')
        self.assertEqual(iw(0xC038BFF0), 0xE12FFF33, 'the creator enqueue (Lossless) after the header DMA')

    def test_the_commit_starts_the_worker_once_and_refuses_without_it(self):
        cam = H2Cam()
        self.assertEqual(cam.init(), AP_OK)
        cam.tk_id = -1                                       # tk_cre_tsk refuses
        rc = cam.apply(recipe(*(H2_S35 + (12,)), hbin=2)[0])
        st = cam.status()
        self.assertEqual((rc, st['result'], st['detail'], st['active']), (AP_E['CPU2'], AP_E['CPU2'], 4, 0))
        self.assertEqual((cam.h2()['armed'], cam.h2()['refused']), (0, 1))
        cam.tk_id, cam.tk_sta_rc = 9, 1                      # created, but tk_sta_tsk refuses
        self.assertEqual(cam.apply(recipe(*(H2_S35 + (14,)), hbin=2)[0]), AP_E['CPU2'])
        cam.tk_sta_rc = 0
        cam.tk = []
        self.assertEqual(cam.apply(recipe(*(H2_S35 + (12,)), hbin=2)[0]), AP_OK)
        h = cam.h2()
        n, row, rows = self.geom(12)
        self.assertEqual([h[k] for k in ('armed', 'task', 'n', 'bits', 'row', 'rows', 'mv')], [1, 9, n, 12, row, rows, 2])
        self.assertIn(h['line'], (32, 64))
        cre = [c[1] for c in cam.tk if c[0] == 'cre']
        self.assertEqual(len(cre), 1)
        d = cre[0]
        self.assertEqual([c for c in cam.tk if c[0] == 'sta'], [('sta', 9, 0)])
        self.assertEqual((d[1], d[3], d[4]), (0x41, H2_PRI, H2_STACK), 'attr, priority 16, 4 KiB stack')
        tramp = d[2]
        self.assertEqual(tramp >> 28, 0xC, 'the trampoline handed over at its cached alias')
        self.assertEqual([cam.w(tramp + 4 * i) for i in range(3)], [0xE59F0000, 0xE59FF000, MEM])
        ent = cam.w(tramp + 12)
        self.assertTrue(ent & 1, 'Thumb')
        self.assertEqual(ent >> 28, 0xC, 'the task\'s code at its cached alias (the commit ran at 0x4...)')
        self.assertEqual(ap_thumb_bw_target(cam, ent & ~1), BLOB + 0x80000000 + (cam.funcs['ap_h2_task'] & ~1),
                         'b.w ap_h2_task')
        self.assertEqual(cam.h2()['entry'], ent)
        # a second CPU x2 commit and a stock one: no second task; the stock one disarms
        self.assertEqual(cam.apply(recipe(*(H2_S35 + (14,)), hbin=2)[0]), AP_OK)
        self.assertEqual(cam.apply(recipe(*FF_12V2)[0]), AP_OK)
        self.assertEqual([c[0] for c in cam.tk], ['cre', 'sta'])
        self.assertEqual(cam.h2()['armed'], 0)
        # the task's entry: the trampoline reaches the body with r0 = the state, which finds nothing and sleeps 1 ms
        cam.sleep_stop = True
        cam.sleeps = []
        cam.mu.reg_write(UC_ARM_REG_SP, STACK - 0x3000)
        cam.mu.emu_start(tramp, DONE, **emu_cap(5_000_000))
        cam.sleep_stop = False
        if cam.error:
            raise cam.error
        self.assertEqual(cam.sleeps, [1])
        h = cam.h2()
        self.assertEqual(h['run_pc'], ent, 'the worker executes at the cached alias (its own PC-relative address)')
        self.assertTrue(STACK - 0x3100 < h['run_sp'] <= STACK - 0x3000)

    def test_the_allocation_is_doubled_only_for_a_live_hbin_2_take(self):
        for bits in (12, 14):
            n = self.geom(bits)[0]                           # D11 (4): a 14-bit AD records true 14
            cam = self.live(bits)
            size, rec, cls, align = cam.allocate(1, n)
            self.assertEqual(size, H2_RESERVE + (((2 * n) + 0x1FF) & ~0x1FF), bits)
            self.assertEqual((rec, cls & 0xFF, align, cam.assertpc), (cam.frame_at(1) + 0x68, 10, 0x400, H2_SLICE[1]))
            self.assertEqual((cam.h2()['doubled'], cam.h2()['alloc_bad']), (1, 0))
            self.assertEqual(cam.allocate(2, n, kind=5)[0], H2_RESERVE + ((n + 0x1FF) & ~0x1FF), 'kind 5: stock')
            # not the guaranteed raster: never smaller than ours x 2, and the take is condemned (see the stop tests)
            self.assertEqual(cam.allocate(3, n + 512)[0], H2_RESERVE + (((2 * n) + 0x1FF) & ~0x1FF))
            self.assertEqual(cam.allocate(4, 3 * n)[0], H2_RESERVE + (((3 * n) + 0x1FF) & ~0x1FF), 'larger: as asked')
            self.assertEqual(cam.h2()['alloc_bad'], 2)
        cam = self.live(12)
        cam.picked('UHD24')                                  # the picker answered stock: not our take
        self.assertEqual(cam.allocate(1, self.geom(12)[0])[0], H2_RESERVE + ((self.geom(12)[0] + 0x1FF) & ~0x1FF))

    # ---- streaming ----
    def stream(self, bits, chunks=(1, 37, 200, 411, 640, 1000, 1177), ad=None):
        """the DMA writes rows in steps (a moving 0x30182184 after each): the worker bins nothing before BUFA0's
        completion (D2 has no progress source, v3), then the whole frame in 32-row strips through the cached alias"""
        from unicorn import UC_HOOK_MEM_READ
        cam, n, row, rows, data = self.queued(bits, ad=ad)
        self.assertEqual(cam.h2()['queued'], 1)
        c = FF_DEST + 0x80000000
        acc = {'r': 0, 'w': 0, 'u': 0}

        def rd(uc, a_, addr, size, v, d):
            if addr + size > acc['r']:
                acc['r'] = addr + size

        def wr(uc, a_, addr, size, v, d):
            if addr + size > acc['w']:
                acc['w'] = addr + size

        def unc(uc, a_, addr, size, v, d):
            acc['u'] += 1
        hr = cam.mu.hook_add(UC_HOOK_MEM_READ, rd, begin=c, end=c + 2 * n + 0x1000)
        hw = cam.mu.hook_add(UC_HOOK_MEM_WRITE, wr, begin=c, end=c + 2 * n + 0x1000)
        hu = cam.mu.hook_add(UC_HOOK_MEM_WRITE | UC_HOOK_MEM_READ, unc, begin=FF_DEST, end=FF_DEST + 2 * n + 0x1000)
        written = 0
        for r in chunks:
            new = r * row
            cam.mu.mem_write(FF_DEST + written, data[written:new])
            written = new
            cam.cursor(FF_DEST, written)
            self.assertEqual(cam.drain(), 0, f'nothing before the completion ({r} rows written)')
        self.assertEqual((cam.strips, acc['r'], acc['w']), ([], 0, 0), 'the raster untouched before the completion')
        cam.mu.mem_write(FF_DEST + written, data[written:])
        dc = len([x for x in cam.calls if x[0] == 'DCACHE'])
        cam.done(FF_DEST)
        cam.drain()
        cam.mu.hook_del(hr)
        cam.mu.hook_del(hw)
        cam.mu.hook_del(hu)
        self.assertEqual(acc['u'], 0, 'the pass never touches the uncached alias of the raster')
        self.assertEqual(len([x for x in cam.calls if x[0] == 'DCACHE']), dc, 'no set / way clean (FUN_c000e91c)')
        strips = cam.strips
        self.assertEqual([s[1] for s in strips], [0] + [s[2] for s in strips[:-1]], 'contiguous strips')
        self.assertEqual(strips[-1][2], rows)
        self.assertTrue(all(s[2] - s[1] <= 32 for s in strips))
        self.same(cam.ram(FF_DEST, n), h2_reference(data, bits), f'{bits}-bit: binned in place')
        self.same(cam.ram(FF_DEST + n, n), data[n:], 'the second half is the input as the DMA left it')
        self.same(cam.ram(FF_DEST + 2 * n, 0x1000), b'T' * 0x1000, 'nothing past the hardware raster')
        self.same(cam.ram(FF_U, H2_RESERVE), b'H' * H2_RESERVE, 'the header reserve untouched')
        self.same(cam.ops, self.expected_ops(cam, strips, n, row), f'{bits}-bit cache ops')
        self.assertTrue(all(a >= 0xC0000000 for _, a in cam.ops), 'MVA ops on the cached alias only')
        h = cam.h2()
        self.assertEqual(h['nsamp'], len(chunks), 'the cursor is sampled (for the record), never used')
        self.assertTrue(all(s[1] == FF_DEST for s in h['samp'][:h['nsamp']]))
        self.assertEqual(h['ras_c'], c)
        self.assertEqual((h['line_words'] * 4, h['lines'], h['line_bad']), (row, rows, 0))
        # SRecRaw: nothing to wait for, passed on once
        sleeps = len(cam.sleeps)
        v, fr, calls, _ = cam.arrive(FF_DEST, ident=1, keep=True)
        names = [x[0] for x in calls]
        self.assertEqual((names.count('FF_ENQ'), 'FF_DELETE' in names, 'FF_STOP' in names), (1, False, False))
        self.assertEqual(len(cam.sleeps), sleeps)
        h = cam.h2()
        self.assertEqual([h[k] for k in ('binned', 'stops', 'failed')], [1, 0, 0])
        self.assertEqual(cam.w(FF_MSG + 0xE4), 0)
        return cam

    def test_a_12_bit_frame_is_binned_after_its_completion(self):
        self.stream(12)

    def test_a_14_bit_ad_take_records_true_14_through_h2_p14(self):
        """D11 (4) (Bei 11-05, choice B): a 14-bit AD records true 14 bit -- the record skips RWZM -- so the 14-bit
        kernel h2_p14 bins it (byte-exact against the 14-bit reference), on the 14-bit line (2 rec_w x 14 / 8 bytes),
        with the 14-bit plane code, the 14-bit DNG black level and the 14-bit data rate"""
        cam = self.stream(14)
        n, row, rows = self.geom(14)
        h = cam.h2()
        self.assertEqual([h[k] for k in ('bits', 'row', 'rows', 'n')], [14, 2 * 2096 * 14 // 8, 1178, 2096 * 1178 * 14 // 8])
        self.assertEqual((row, n), (7336, 4320904))
        self.assertEqual(h['need_mbps'], -(-row * rows // h['period_us']), 'the 14-bit hardware bytes per period')
        g = cam.canvas(cam.status()['pid'])
        self.assertEqual((g[0x80 // 4], g[0x84 // 4], g[0x64 // 4]), (7, 8, 1023), 'the 14-bit plane, record RWZM unity')
        obj = 0xC3E09000
        for site_from, field in ((0xC02CA1BC, 0x24), (0xC02CA218, 0x08)):   # the DNG BlackLevel's bits (H_BLK6 / H_BLK)
            cam.put(obj + field, 0)
            cam.mu.reg_write(UC_ARM_REG_R0, obj)
            cam.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
            cam.mu.emu_start(site_from, site_from + 8, count=10000)
            self.assertEqual(cam.r(UC_ARM_REG_R0), 14, hex(site_from))

    def test_a_14_bit_take_on_a_12_bit_line_stops(self):
        """the fail-closed line check at the 14-bit depth: BUFA0 programmed for the 12-bit line (0x30182114 x 4 !=
        2 rec_w x 14 / 8) stops the take"""
        n, row, rows = self.geom(14)
        cam2 = self.live(14)
        cam2.put(H2_LWORDS, self.geom(12)[1] // 4)
        cam2.allocate(1, n)
        cam2.mu.mem_write(FF_DEST, b'\xEE' * (2 * n))
        cam2.cursor(FF_DEST, 0)
        cam2.take()
        cam2.dest(FF_DEST, first=True)
        h = cam2.h2()
        self.assertEqual((h['failed'], h['line_bad'], h['line_words'] * 4, h['row'], h['queued']),
                         (W['LINE'], 1, self.geom(12)[1], row, 0))

    def test_a_cursor_that_never_moves_is_never_trusted(self):
        """any value of 0x30182184 (live 11-05: always 0) gives nothing before the completion; the frame is then binned
        after it, whole"""
        cam, n, row, rows, data = self.queued(12)
        cam.mu.mem_write(FF_DEST, data)
        cam.cursor(FF_DEST, 600 * row)
        for _ in range(3):
            self.assertEqual(cam.drain(), 0)
        self.assertEqual(cam.strips, [])
        cam.done(FF_DEST)
        cam.drain()
        self.assertEqual(cam.strips[-1][2], rows)
        self.same(cam.ram(FF_DEST, n), h2_reference(data, 12), 'binned after the completion')

    # ---- fail closed (D3) ----
    def stopped(self, cam, why, ident=1):
        v, fr, calls, _ = cam.arrive(FF_DEST, ident=ident, keep=True)
        names = [x[0] for x in calls]
        self.assertNotIn('FF_ENQ', names, 'never written')
        self.assertIn('FF_DELETE', names, 'the firmware drops it (release, delete)')
        self.assertIn('FF_STOP', names, 'and stops the take (cDevt_stop)')
        self.assertEqual(cam.w(FF_MSG + 0xE4), 1)
        self.assertEqual(cam.h2()['failed'], why)
        return names

    def test_late_is_a_stop(self):
        cam, n, row, rows, data = self.queued(12)
        cam.mu.mem_write(FF_DEST, data)
        self.stopped(cam, W['LATE'])
        sel = recipe(*(H2_S35 + (12,)), hbin=2)[0]
        period = sel['hm'] * sel['vmax'] // 72                # us at 72 MHz
        wait = max(10, min(250, -(-2 * period // 1000)))
        h = cam.h2()
        self.assertEqual((h['period_us'], h['wait_ms']), (period, wait), 'two frame periods, in ms')
        self.assertEqual(h['need_mbps'], -(-(2 * 2096 * 12 // 8) * 1178 // period), 'hardware bytes per period')
        self.assertEqual(cam.sleeps, [1] * wait, 'a bounded wait of tk_dly_tsk(1) polls')
        self.same(cam.ram(FF_DEST, 2 * n), data, 'nothing binned')
        self.assertEqual(cam.h2()['stops'], 1)
        # a later frame of the same take, even binned in time, is dropped too: the take is over
        cam.allocate(2, n)
        cam.dest(FF_DEST, first=False)
        cam.done(FF_DEST)
        cam.drain()
        cam.take()
        self.stopped(cam, W['LATE'], ident=2)
        # the next take (BUFA0 frame 1) starts clean
        cam.allocate(3, n)
        cam.mu.mem_write(FF_DEST, data)
        cam.dest(FF_DEST, first=True)
        cam.done(FF_DEST)
        cam.drain()
        cam.take()
        v, fr, calls, _ = cam.arrive(FF_DEST, ident=3, keep=True)
        self.assertEqual([x[0] for x in calls].count('FF_ENQ'), 1)
        self.same(cam.ram(FF_DEST, n), h2_reference(data, 12), 'take 2: binned')
        self.assertEqual((cam.h2()['take'], cam.h2()['failed'], cam.h2()['binned']), (2, 0, 1))

    def test_every_unguaranteed_frame_stops_the_take(self):
        import random
        data = random.Random(2).randbytes(2 * self.geom(12)[0])
        n, row, rows = self.geom(12)
        # never handed to BUFA0 through our destination hook (e.g. BUFA7): no queue entry
        cam = self.live(12)
        cam.allocate(1, n)
        cam.mu.mem_write(FF_DEST, data)
        cam.take()
        self.stopped(cam, W['NOQ'])
        self.assertEqual(cam.sleeps, [], 'no wait for a frame nobody bins')
        # the allocation is not the doubled one
        cam, *_ = self.queued(12)
        cam.done(FF_DEST); cam.drain()
        cam.put(cam.frame_at(1) + 0x6C, H2_RESERVE + 2 * n - 4)
        self.stopped(cam, W['CAP'])
        # C02DA770 was not the guaranteed raster for some frame of this slot
        cam, *_ = self.queued(12)
        cam.allocate(5, n + 512)
        cam.done(FF_DEST); cam.drain()
        self.stopped(cam, W['ALLOC'])
        # BUFA0 is not written top-down from row 0 (FUN_c0631640's flag bits): refused at the destination
        cam = self.live(12)
        cam.allocate(1, n)
        cam.put(H2_FLAGS, cam.w(H2_FLAGS) | 0x10)
        cam.take()
        cam.dest(FF_DEST, first=True)
        self.assertEqual(cam.h2()['queued'], 0)
        self.stopped(cam, W['FLIP'])
        # BUFA0 programmed for another line or line count (D11 (2): the line must be hw_w x rec_h, the raster 2n)
        for reg, bad in ((H2_LWORDS, row // 4 // 2), (H2_LINES, rows + 2)):
            cam = self.live(12)
            cam.allocate(1, n)
            cam.put(reg, bad)
            cam.take()
            cam.dest(FF_DEST, first=True)
            self.assertEqual((cam.h2()['queued'], cam.h2()['line_bad']), (0, 1), hex(reg))
            self.stopped(cam, W['LINE'])
        # a frame the firmware drops itself (+0xE4 already set): left alone, its entry freed
        cam, *_ = self.queued(12)
        v, fr, calls, _ = cam.arrive(FF_DEST, ident=1, error=2, keep=True)
        self.assertEqual((cam.w(FF_MSG + 0xE4), cam.h2()['stops'], cam.h2()['failed']), (2, 0, 0))
        self.assertEqual(cam.drain(), 0, 'the entry is gone: the worker has nothing')

    def test_frames_after_frames_reuse_the_queue(self):
        """nine frames in turn (the queue holds 8): each queued, completed, binned, passed on, its entry freed"""
        import random
        cam = self.live(12)
        n, row, rows = self.geom(12)
        cam.take()
        for k in range(9):
            cam.allocate(k, n)
            data = random.Random(k).randbytes(2 * n)
            cam.mu.mem_write(FF_DEST, data)
            cam.dest(FF_DEST, first=k == 0)
            cam.done(FF_DEST)
            cam.drain()
            v, fr, calls, _ = cam.arrive(FF_DEST, ident=k, keep=True)
            self.assertEqual([x[0] for x in calls].count('FF_ENQ'), 1, k)
            if k in (0, 8):
                self.same(cam.ram(FF_DEST, n), h2_reference(data, 12), f'frame {k}')
        h = cam.h2()
        self.assertEqual([h[k] for k in ('queued', 'binned', 'stops', 'failed', 'take')], [9, 9, 0, 0, 1])

    # ---- nothing for any other slot ----
    def test_stock_and_non_cpu2_slots_pass_through_untouched(self):
        """no slot / a 1x2 CRCT recipe (hbin 1) / a refused pick: the size is C02DA770's, BUFA0's destination register is
        the pre-CPU-x2 unit's, the completion and the arrival do nothing, no D-cache op, no state, no task"""
        import random
        n = 4536 * 2010
        data = random.Random(5).randbytes(n)
        for case in ('none', 'hbin1', 'stockpick'):
            units = []
            for src in (None, str(CLEAN_APPLY)):
                cam = H2Cam(src=src)
                self.assertEqual(cam.init(), AP_OK)
                if case == 'hbin1':
                    self.assertEqual(cam.apply(recipe(*FF_12V2)[0]), AP_OK)
                    cam.picked()
                if case == 'stockpick' and src is None:
                    self.assertEqual(cam.apply(recipe(*(H2_S35 + (12,)), hbin=2)[0]), AP_OK)
                    cam.picked('UHD24')
                size = cam.allocate(1, n)[0]
                cam.take()
                reg1 = cam.dest(FF_DEST, first=True)
                reg2 = cam.dest(FF_DEST, first=False)
                cam.mu.mem_write(FF_DEST, data)
                cam.done(FF_DEST)
                v, fr, calls, _ = cam.arrive(FF_DEST, ident=1, keep=True)
                units.append((size, reg1, reg2, calls, cam.ram(FF_DEST, n), cam))
            new, old = units
            self.assertEqual(new[:4], old[:4], case)
            self.same(new[4], data, case)
            cam = new[5]
            self.assertEqual((cam.ops, cam.strips, cam.drain()), ([], [], 0), case)
            h = cam.h2()
            self.assertEqual([h[k] for k in ('armed', 'doubled', 'queued', 'binned', 'stops', 'take')],
                             [int(case == 'stockpick'), 0, 0, 0, 0, 0], case)
            self.assertEqual([c for c in cam.tk if case != 'stockpick'], [], case)
        self.assertEqual(cam.mcr_sites, 3, 'the only D-cache ops of the unit are the pass\'s three')


def ap_thumb_bw_target(cam, at):
    """the target of the Thumb-2 b.w at `at` (emulated memory)"""
    h1, h2 = struct.unpack('<HH', cam.mu.mem_read(at, 4))
    assert h1 & 0xF800 == 0xF000 and h2 & 0xD000 == 0x9000, (hex(h1), hex(h2))
    s_ = (h1 >> 10) & 1
    i1, i2 = 1 ^ (((h2 >> 13) & 1) ^ s_), 1 ^ (((h2 >> 11) & 1) ^ s_)
    off = (s_ << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    off -= (1 << 25) if s_ else 0
    return (at + 4 + off) & 0xFFFFFFFF


def ap_target_of(site):
    w = iw(site)
    off = ((w & 0xFFFFFF) ^ 0x800000) - 0x800000
    t = (site + 8 + (off << 2)) & 0xFFFFFFFF
    if w >> 28 == 0xF:
        t |= ((w >> 23) & 2) | 1
    return t


class CpuX2TagTests(unittest.TestCase):
    """D7: the private DNG tag 0xFD58 on IFD 0 of a CPU x2 take, through the IFD writer's own setter"""

    def test_the_tag_names_the_merge_and_the_cfa_offsets(self):
        for bits in (12, 14):
            cam = PbCam()
            self.assertEqual(cam.init(), AP_OK)
            self.assertEqual(cam.apply(recipe(*(H2_S35 + (bits,)), hbin=2)[0]), AP_OK)
            info = 0x48170700
            cam.put(info + 0x134, 2096); cam.put(info + 0x138, 1178); cam.put(info + 0x13C, 8); cam.put(info + 0x140, 5)
            cam.call(DSCALE, 0, TIFF, 0, info)
            self.assertNotIn(H2_TAG, [t[1] for t in cam.tagset], 'not picked for a take: none')
            cam.mu.mem_write(MOVREC_DEFAULT, b'\x01')
            cam.call(PICKER, 0, TAB3, cam.key('UHD30'))
            cam.tagset = []
            cam.call(DSCALE, 0, TIFF, 0, info)
            tags = {t[1]: t for t in cam.tagset}
            self.assertIn(H2_TAG, tags)
            _, tag, ty, cnt, b = tags[H2_TAG]
            self.assertEqual((ty, cnt, len(b)), (7, 32, 32))
            self.assertEqual(b[:4], b'SLC2')
            self.assertEqual(tuple(b[4:12]), (1, 1, 2, 1, 2, 4, bits, 0), 'v1; H CPU x2 equal 2:1; V sensor 2:1; 1/4 px; '
                             'the recorded bits (D11 (4): a 14-bit AD records true 14)')
            offs = struct.unpack('<8b', b[12:20])
            # independent: the pair (2k + p, 2k + p + 2) centres at 2k + p + 1; output px j = k * 2 + p spans input
            # [2j, 2j + 2), centre 2j + 1 - 0.5 = 2j + 0.5 ... offset (in output px) = (0.5 - p) / 2 -> quarter units
            q = lambda p: int((Fraction(1, 2) - p) / 2 * 4)   # noqa: E731
            want = []
            for y in (0, 1):
                for x in (0, 1):
                    want += [q(x), q(y)]
            self.assertEqual(list(offs), want)
            self.assertEqual(struct.unpack('<3H', b[20:26]), (4192, 2096, 1178))
            self.assertEqual(b[26:], bytes(6))
            cam.tagset = []
            cam.call(DSCALE, 0, TIFF, 6, info)
            self.assertNotIn(H2_TAG, [t[1] for t in cam.tagset], 'only IFD 0')
        # a stock-geometry (hbin 1) take: no tag
        cam = PbCam()
        cam.init()
        self.assertEqual(cam.apply(recipe(*FF_12V2)[0]), AP_OK)
        cam.mu.mem_write(MOVREC_DEFAULT, b'\x01')
        cam.call(PICKER, 0, TAB3, cam.key('UHD30'))
        cam.call(DSCALE, 0, TIFF, 0, 0x48170700)
        self.assertNotIn(H2_TAG, [t[1] for t in cam.tagset])

    def test_the_tag_number_is_used_by_nothing_else(self):
        hits, me = [], pathlib.Path(__file__).resolve()
        skip = {'validation', 'worktrees', '.venv', 'node_modules', 'captures', '.git', '__pycache__', 'build', 'out'}
        for base in (ROOT / 'fpSup', ROOT / 'projects'):
            for d, dirs, files in os.walk(base):
                dirs[:] = [x for x in dirs if x not in skip]
                for f in files:
                    q = pathlib.Path(d) / f
                    if q.suffix not in ('.c', '.h', '.S', '.py', '.inc') or q.resolve() == me or f == 'ap.c':
                        continue
                    if re.search(r'0x[fF][dD]58\b', q.read_text(errors='ignore')):
                        hits.append(str(q))
        self.assertEqual(hits, [], 'another private tag 0xFD58 (Lossless 0xFD4C, Gyro2 0x4653)')




class CpuX2BenchTests(unittest.TestCase):
    """the throughput probe (ap_h2_bench, sq_test 50): the worker's own bin routine over a caller's buffer through its
    cached alias, without recording; microseconds per MB of input"""

    def cam(self):
        cam = H2Cam()
        self.assertEqual(cam.init(), AP_OK)
        ticks = iter(range(0, 10 ** 9, 997))
        orig = cam._hook

        def hook(mu, addr, size, data):
            if cam.by_addr.get(addr) == 'TICK':
                cam.now = next(ticks)
            return orig(mu, addr, size, data)
        cam._hook = hook
        cam.mu.hook_add(UC_HOOK_CODE, hook, begin=FW['TICK'], end=FW['TICK'])
        return cam

    def bench(self, cam, buf, nbytes, mode):
        return ctypes.c_int32(cam.fn('ap_h2_bench', MEM, buf, nbytes, mode)).value

    def test_the_bench_runs_the_real_bin_on_the_cached_alias(self):
        import random
        for bits, flag in ((12, 0), (14, 0x10000)):
            cam = self.cam()
            w = 4192
            row = w * bits // 8
            rows = 40
            data = random.Random(bits).randbytes(rows * row)
            cam.mu.mem_write(FF_U, data)
            cam.ops = []
            r = self.bench(cam, FF_U, rows * row + 5, w | flag)
            self.assertGreaterEqual(r, 0, bits)
            h = cam.h2()
            us, nb, c, mode, rc, cpacr, nrows, per = h['bench']
            self.assertEqual((nb, c, mode, rc, nrows), (rows * row, FF_U + 0x80000000, w | flag, 0, rows))
            self.assertEqual(per, r)
            self.assertEqual(r, us * 10 ** 6 // nb)
            self.assertGreater(us, 0)
            self.same(cam.ram(FF_U, rows * row // 2), h2_reference(data, bits), f'{bits}: the worker\'s kernel')
            self.assertTrue(cam.ops and all(a >= 0xC0000000 for _, a in cam.ops), 'MVA ops, cached alias')
            self.assertEqual([x for x in cam.calls if x[0] == 'DCACHE'][1:], [], 'no set / way op')
        cam = self.cam()
        cam.ops = []
        self.assertGreaterEqual(self.bench(cam, FF_U, 40 * 6288, 4192 | 0x20000), 0)
        self.assertEqual(cam.ops, [], 'NOMAINT: no cache maintenance')
        self.assertGreaterEqual(self.bench(cam, FF_U, 40 * 6288, 4192 | 0x40000), 0)
        self.assertEqual(cam.h2()['bench'][2], FF_U, 'ASIS: the uncached address as given')

    def same(self, got, want, msg=''):
        CpuX2StreamTests.same(self, got, want, msg)

    def test_the_bench_refuses(self):
        cam = self.cam()
        self.assertEqual(self.bench(cam, FF_U, 100, 2096), -2, 'fewer than two rows')
        self.assertEqual(self.bench(cam, FF_U, 1 << 20, 2090), -2, 'line not a multiple of 32 px')
        self.assertEqual(self.bench(cam, 0x10000000, 1 << 20, 4192), -2, 'not DRAM')
        cam.mu.mem_write(MOV_ACTIVE, b'\x01')
        self.assertEqual(self.bench(cam, FF_U, 1 << 20, 4192), -1, 'never while recording')
        cam.mu.mem_write(MOV_ACTIVE, b'\x00')


SELECTOR = 0xC0325228                                     # XC_ImageSensorIMX410::v37, the CRCT path selector
TWIN_FPS = (Fraction(30000, 1001), Fraction(25), Fraction(24000, 1001))
TWIN_VIEW = (('OG3K 14v2', (6048, 4040, 3024, 2020), '14v2'), ('HD3K 12v2', (6048, 3402, 3024, 1700), '12v2'),
             ('S35 f12v2w18', (4192, 2358, 2096, 1178), 'f12v2w18'), ('OG 1x1', (6048, 4040, 3024, 4040), '12'),
             ('SQ 14v2', (4032, 4032, 2016, 2016), '14v2'))


def taps(e):
    return {0: 1, 1: 3, 2: 5}[e]                          # FUN_c022ee10 / ee90: the CRCT enum -> taps


class CpuX2TwinTests(unittest.TestCase):
    """D11 (Bei 11-05, notes/CPU_X2_DESIGN.md): a CPU x2 recipe IS its RWZM twin -- the same sensor merge / readout, ISP
    hbin 1 with RWZM 2:1 horizontally to the same record.  Every field the firmware sees comes from the twin; the only
    differences allowed: (1) the record RWZM's H ratio at unity (profile +0x64), (2) the BUFA0 hardware line hw_w =
    2 rec_w, (3) the allocation x 2 + the CPU pass (runtime, ap.c: CpuX2StreamTests), (4) (Bei 11-05, choice B) the
    record bits: a 14-bit AD records true 14 -- apc_out's plane code +0x84 (8, the twin 7) and rec14 (1, the twin 0),
    exactly what a native 1:1 14-bit recipe differs in from its 12-bit container (test_bits_set_is_the_native_one);
    a 12-bit AD differs in (1) and (2) only.  Live 11-05 (v0.7.38test) broke
    it: the CPU x2 slot carried its own path-D preview (RWZM /3 of a 1:1 record) -> the LV showed the centre half."""

    ALLOWED = {('isp', 0x64 // 4), ('hw_w', 0)}
    BITS = {('isp', 0x84 // 4): (8, 7), ('rec14', 0): (1, 0)}           # (4): only for a 14-bit AD

    @classmethod
    def allowed(cls, c):
        return cls.ALLOWED | (set(cls.BITS) if c['bits'] == 14 else set())

    @staticmethod
    @functools.lru_cache(None)
    def fields():
        lib = host()
        lib.apc_field.restype = ctypes.c_char_p
        out, i = [], 0
        while True:
            off, size = ctypes.c_uint(), ctypes.c_uint()
            n = lib.apc_field(i, ctypes.byref(off), ctypes.byref(size))
            if not n:
                return out
            out.append((n.decode(), off.value, size.value))
            i += 1

    @staticmethod
    def pairs():
        """(cell, CPU x2 case, its twin from the core's own list) for every hbin-2 recipe of the QS cells"""
        out = []
        for W, H, w, h in CpuX2GuardTests().cells():
            cs = Q.qualities(W, H, w, h, None, 0.02)
            for c in cs:
                if c['hbin'] != Q.CPU2:
                    continue
                tw = [t for t in cs if t['hbin'] == 1 and t['vbin'] == 1 and t['readout'] == c['readout'] and
                      t['rec'] == c['rec']]
                out.append(((W, H, w, h), c, tw[0] if tw else None))
        return out

    def build(self, cell, c, fps, lib=None):
        lib = lib or host()
        hm = Q.hmax_of(c)
        lo = Q.vmax_range(c)[0]
        v = max(lo, -(-CLK * fps.denominator // (hm * fps.numerator)))
        if v > 16384:
            return None, None
        key = lib.core_key_index(c['readout'][0].encode())
        args = (ctypes.c_uint32 * 14)(*cell, key, c['hbin'], c['vbin'], hm, v, fps.numerator, fps.denominator, 2, 3, 1)
        wk = ctypes.create_string_buffer(lib.apc_sizes(0))
        o = ctypes.create_string_buffer(lib.apc_sizes(1))
        rc = lib.apc_build_host(args, wk, o)
        return rc, o.raw

    def diff(self, a, b):
        d = []
        for name, off, size in self.fields():
            if size % 4:
                if a[off:off + size] != b[off:off + size]:
                    d.append((name, 0, a[off:off + size], b[off:off + size]))
                continue
            for i in range(size // 4):
                x, y = struct.unpack_from('<I', a, off + 4 * i)[0], struct.unpack_from('<I', b, off + 4 * i)[0]
                if x != y:
                    d.append((name, i, x, y))
        return d

    def test_the_field_table_covers_apc_out(self):
        size = host().apc_sizes(1)
        cover = bytearray(size)
        for name, off, n in self.fields():
            for k in range(off, off + n):
                self.assertEqual(cover[k], 0, name)
                cover[k] = 1
        gaps = [k for k in range(size) if not cover[k]]
        self.assertLessEqual(len(gaps), 8, f'apc_out bytes no field names (padding only): {gaps}')

    def test_every_cpu2_slot_is_its_twin_but_the_allowed_words(self):
        n, seen, ad14 = 0, set(), 0
        for cell, c, t in self.pairs():
            self.assertIsNotNone(t, f'{cell} {c["quality"]}: the core lists no RWZM twin')
            self.assertEqual(t['zoom'], [2048, 1024], f'{cell} {c["quality"]}: the twin is RWZM 2:1 x 1:1 exactly')
            for fps in TWIN_FPS:
                rc_c, oc = self.build(cell, c, fps)
                rc_t, ot = self.build(cell, t, fps)
                if rc_c is None:
                    continue
                self.assertEqual((rc_c, rc_t), (0, 0), (cell, c['quality'], fps))
                d = self.diff(oc, ot)
                where = {(x[0], x[1]) for x in d}
                self.assertEqual(where, self.allowed(c), (cell, c['quality'], fps, d))
                got = {(x[0], x[1]): (x[2], x[3]) for x in d}
                for k, v in self.BITS.items():
                    if c['bits'] == 14:
                        self.assertEqual(got[k], v, f'(4): {k} true 14, the twin\'s 12-bit container')
                        ad14 += 1
                rec_w = struct.unpack_from('<I', ot, [f for f in self.fields() if f[0] == 'rec_w'][0][1])[0]
                self.assertEqual(got[('isp', 0x64 // 4)], (1023, 2048), '(1): record RWZM H at unity, the twin 2:1')
                self.assertEqual(got[('hw_w', 0)], (2 * rec_w, rec_w), '(2): the BUFA0 line')
                n += 1
                seen.add((cell, c['quality']))
        self.assertGreaterEqual(len(seen), 24)
        self.assertGreaterEqual(n, 60)
        self.assertGreaterEqual(ad14, 2 * 20, 'both ADs covered')
        self.assertLess(ad14, 2 * n)

    def test_bits_set_is_the_native_one(self):
        """(4) is derived, not guessed: a native 1:1 14-bit recipe and the same recipe forced into the 12-bit container
        (the only change: apc_build's container rule always taken) differ in exactly BITS's fields and values"""
        src = (HERE / 'ap_calc.c').read_text()
        rule = 'if (w->spec.bits == 14 && !(rec_zh == 1024u && w->spec.zv == 1024 && w->spec.hbin == 1 && w->spec.vbin == 1))'
        self.assertEqual(src.count(rule), 1)
        d = pathlib.Path(tempfile.mkdtemp(prefix='slap-bits-'))
        try:
            for f in ('ap_calc.c', 'ap.c', 'ap.h', 'pb_glyph.h', 'pb_page.h'):
                if (HERE / f).exists():
                    shutil.copy(HERE / f, d / f)
            (d / 'ap_calc.c').write_text(src.replace(rule, '(void)rec_zh;\n    if (w->spec.bits == 14)'))
            forced = BA.host(src_dir=d, out_dir=d / 'b', name='forced12')
            forced.core_key_index.argtypes = [ctypes.c_char_p]
            n, diffs = 0, set()
            for cell in CpuX2GuardTests().cells():
                for c in Q.qualities(*cell, None, 0.02):
                    if c['bits'] != 14 or c['hbin'] != 1 or c['vbin'] != 1 or tuple(c['zoom']) != (1024, 1024):
                        continue
                    for fps in TWIN_FPS:
                        rc_a, a = self.build(cell, c, fps)
                        if rc_a is None:
                            continue
                        rc_b, b = self.build(cell, c, fps, lib=forced)
                        self.assertEqual((rc_a, rc_b), (0, 0))
                        diffs |= {((x[0], x[1]), (x[2], x[3])) for x in self.diff(a, b)}
                        n += 1
            self.assertGreaterEqual(n, 6)
            self.assertEqual(diffs, set(self.BITS.items()))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_core_twin_is_the_one_the_core_lists(self):
        """core_quality_twin (what apc_build uses) == the twin core_qualities_tol picks for the cell, field by field
        (seq aside: the twin keeps the CPU x2 case's place)"""
        lib = host()
        lib.core_qualities_tol.argtypes = [ctypes.c_int] * 4 + [ctypes.c_uint32] * 4 + [ctypes.c_void_p, ctypes.c_int]
        lib.core_twin_host.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 5 + [ctypes.c_void_p]
        QW = 31
        cells = {cell for cell, _, _ in self.pairs()}
        n = 0
        for cell in cells:
            buf = ctypes.create_string_buffer(4 * QW * 160)
            k = lib.core_qualities_tol(*cell, 0, 1, 1, 50, buf, 160)
            self.assertGreater(k, 0)
            qs = [struct.unpack_from(f'<{QW}i', buf.raw, 4 * QW * i) for i in range(k)]
            for i, q in enumerate(qs):
                if q[3] != 2:
                    continue
                listed = [x for x in qs if x[3] == 1 and x[4] == 1 and x[5] == q[5] and x[23:25] == q[23:25]]
                self.assertEqual(len(listed), 1, (cell, q))
                tw = ctypes.create_string_buffer(4 * QW)
                rc = lib.core_twin_host(ctypes.addressof(buf) + 4 * QW * i, *cell, 1, tw)
                self.assertEqual(rc, 0, (cell, q))
                got = struct.unpack(f'<{QW}i', tw.raw)
                self.assertEqual(got[:26] + got[27:], listed[0][:26] + listed[0][27:], cell)
                self.assertEqual((got[21], got[22], got[3]), (2048, 1024, 1))
                n += 1
        self.assertGreaterEqual(n, 24)

    # ---- the firmware's view, emulated: commit each and read back what the firmware reads ----
    def commit(self, args, merge_key, hbin):
        W, H, w, h = args
        c = [x for x in Q.qualities(W, H, w, h, None, 0.02) if x['readout'][0] == merge_key and x['hbin'] == hbin
             and x['vbin'] == 1][0]
        hm = Q.hmax_of(c)
        v = max(Q.vmax_range(c)[0], -(-CLK * 1001 // (hm * 30000)))
        sel = dict(dcw=W, dch=H, rw=w, rh=h, key=host().core_key_index(merge_key.encode()), hbin=hbin, vbin=1, hm=hm,
                   vmax=v, fps_n=30000, fps_d=1001)
        cam = H2Cam()
        self.assertEqual(cam.init(), AP_OK)
        self.assertEqual(cam.apply(sel), AP_OK, (args, merge_key, hbin, cam.status()))
        return cam

    def fw_view(self, cam):
        st = cam.status()
        mode, pid = st['mode_id'], st['pid']
        v = {}
        for k, (name, _, _) in enumerate(TABLES):
            v[name] = cam.row_via_lookup(k, mode)
        v['REG'] = cam.reg_via_lookup(mode)
        v['R10'] = cam.call(LK_R10, IMAGER, mode)
        v['profile'] = cam.canvas(pid)
        for sp in (5, 210, 227, 257, 258, 259):
            v[f'standby{sp}'] = cam.canvas(sp)
        pairs = 0xC3E05000
        for idx, (w_, h_) in ((0, (1620, 911)), (1, (1620, 911)), (2, (320, 180))):
            d = 0xC3E05100 + 0x40 * idx
            cam.mu.mem_write(d, struct.pack('<11I', w_, h_, 0, 0, w_, h_, 7, 4, 0x3FC000, 1, 1))
            cam.put(pairs + 8 * idx, d)
            got = cam.call(OUT, pairs, idx)
            v[f'lv{idx}'] = bytes(cam.mu.mem_read(got, 44))
        cam.mu.reg_write(UC_ARM_REG_SP, STACK - 0x2004)
        cam.mu.emu_start(0xC0306EA0, 0xC0306EA8, count=100000)
        v['aspect'] = bytes(cam.mu.mem_read(cam.r(UC_ARM_REG_R0), 8))
        e = cam.picked()
        v['entry'] = [cam.w(e + 4 * i) for i in range(3)] + [bytes(cam.mu.mem_read(cam.w(e + 12), 8))]
        so = cam.off(6) + cam.fn('ap_sizes_t', 3) * st['cur']
        v['slot'] = bytes(cam.mu.mem_read(so, cam.fn('ap_sizes_t', 3)))
        return v

    def selector(self, cam, words, recording=True, kind=1):
        """the real XC_ImageSensorIMX410::v37 on the profile's words (CRCT_PATH_SELECTOR_SOLVED.md section 3): the RWZM
        inputs clamped to >= 1024 (DAT_c0b57144), the CRCT enums as taps"""
        z = lambda x: max(x, 1024)                          # noqa: E731
        inp = [words[0] if recording else 0, words[1] if recording else 0, z(words[0x64 // 4]), z(words[0xD4 // 4]),
               taps(words[0x5C // 4]), taps(words[0xC8 // 4]), kind, 0, 0, z(words[0x60 // 4]), z(words[0xD0 // 4]),
               taps(words[0x58 // 4]), taps(words[0xC4 // 4]), 0]
        a, b = WORK + 0xF000, WORK + 0xF100
        cam.mu.mem_write(a, struct.pack('<14I', *inp))
        cam.mu.mem_write(b, b'\0' * 0x4C)                  # FUN_c031d988 clears local_a4 first
        cam.call(SELECTOR, 0, a, b)
        o = bytes(cam.mu.mem_read(b, 0x4C))
        return dict(en=tuple(o[0:3]), a0=struct.unpack_from('<I', o, 4)[0], a7=struct.unpack_from('<I', o, 8)[0],
                    taps=struct.unpack_from('<2I', o, 0x24), rwzm=struct.unpack_from('<2I', o, 0x34), rec=o[0x48], raw=o)

    @staticmethod
    def lv(sel, words):
        """what the LV / preview sees: the main pipeline's bins, and RWZM where the LV tap follows it -- B / C / D (a1
        off: the main RWZM carries the preview ratio); in E (a1, record index 1) the main RWZM is the record's and the
        LV taps before it (isp_formula R9 / E1-E3, live-validated: the preview is window / (preview zoom x taps))"""
        rw = (max(words[0x60 // 4], 1024), max(words[0xD0 // 4], 1024)) if sel['en'][2] else sel['rwzm']
        return sel['taps'], rw

    def test_the_firmware_view_of_cpu2_is_the_twins(self):
        for name, args, key in TWIN_VIEW:
            c2, tw = self.commit(args, key, 2), self.commit(args, key, 1)
            a, b = self.fw_view(c2), self.fw_view(tw)
            for k in a:
                if k in ('profile', 'slot'):
                    continue
                self.assertEqual(a[k], b[k], f'{name}: {k}')
            ad14 = key.startswith('14')
            pd = [(i, x, y) for i, (x, y) in enumerate(zip(a['profile'], b['profile'])) if x != y]
            self.assertEqual(pd, [(0x64 // 4, 1023, 2048)] + ([(0x84 // 4, 8, 7)] if ad14 else []),
                             f'{name}: the record profile differs only in RWZM H (and (4) the 14-bit plane)')
            isp, hw, r14 = c2.fn('ap_sizes_t', 20), c2.fn('ap_sizes_t', 21), c2.fn('ap_sizes_t', 23)
            sd = [i for i in range(0, len(a['slot']), 4) if a['slot'][i:i + 4] != b['slot'][i:i + 4]]
            self.assertEqual(sd, sorted([isp + 0x64, hw] + ([isp + 0x84, r14] if ad14 else [])), f'{name}: slot words')
            self.assertEqual(c2.h2()['bits'], 14 if ad14 else 12, name)
            # the path selector, run for real: CPU x2 records through a0 Crmf (the pre-RWZM line), the twin through a1
            # RWZM; the LV sees the same bins and RWZM either way, and standby (no record) is byte-identical
            pa, pb = a['profile'], b['profile']
            sa, sb = self.selector(c2, pa), self.selector(c2, pb)
            self.assertEqual((sa['en'], sa['a0'], sa['rec']), ((1, 0, 0), 1, 0), f'{name}: CPU x2 -> a0 Crmf')
            self.assertEqual((sb['en'], sb['rec']), ((0, 0, 1), 1), f'{name}: the twin -> branch E, a1 RWZM')
            self.assertEqual(self.lv(sa, pa), self.lv(sb, pb), f'{name}: the LV sees the twin\'s bins / RWZM')
            self.assertEqual(self.selector(c2, pa, False)['raw'], self.selector(c2, pb, False)['raw'], f'{name}: standby')
            self.assertEqual(self.selector(c2, pa, kind=4)['en'], (0, 1, 0), 'kind 4 would take a7 (BUFA7): NOQ stop')


MUTANTS = [
    ('ap_calc.c', 'o->hw_w = cpu2 ? 2u * o->rec_w : o->rec_w;', 'o->hw_w = o->rec_w;', 'CpuX2TwinTests'),
    ('ap_calc.c', 'u64 an = (u64)o->rec_w * zh', 'u64 an = (u64)o->hw_w * zh', 'CpuX2TwinTests'),
    ('ap_calc.c', 'if (!o->rec_w || (o->rec_w & 15u) ||', 'if (!o->rec_w || (o->rec_w & 31u) ||', 'CpuX2GuardTests'),
    ('ap_calc.c', '(w->plan.mv != 1 && w->plan.mv != 2)) return AP_E_CPU2_MV;', '(w->plan.mv != 1)) return AP_E_CPU2_MV;', 'CpuX2GuardTests'),
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
    ('ap_calc.c', 'if (w->spec.bits == 14 && !(rec_zh == 1024u && w->spec.zv == 1024 && w->spec.hbin == 1 && w->spec.vbin == 1))', 'if (w->spec.bits == 14 && !(0u * rec_zh == 0u && w->spec.hbin == 1 && w->spec.vbin == 1))', 'CalcTests'),
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
    ('ap.c', 'if (!s || s->is169 || A->pb.pbc) return 0;                  /* a stock playback canvas', 'if (!s || s->is169) return 0;                  /* a stock playback canvas', 'PlaybackV1Tests'),
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
    ('ap.c', "if (f[1] == AP_TABS && m && m[0] == 'M' && m[1] == 'O' && m[2] == 'V') { A->lv_seen++; A->pb_since = 0; }", "if (f[1] == AP_TABS && m) { A->lv_seen++; A->pb_since = 0; }", 'BootReadyTests'),
    ('ap.c', "if (f[1] == AP_TABS && m && m[0] == 'M' && m[1] == 'O' && m[2] == 'V') { A->lv_seen++; A->pb_since = 0; }", "if (f[1] == AP_TABS && m && m[0] == 'M' && m[1] == 'O' && m[2] == 'V') { A->lv_seen++; }", 'BootReadyTests'),
    ('ap.c', '        A->pb_since = 1;                                             /* v0.7.35test: playback since the last LV */\n', '', 'BootReadyTests'),
    ('ap.c', '    if (!A || A->magic != AP_MAGIC || !A->armed || A->in_commit || !A->lv_seen || A->pb_since || A->pb.active ||\n        ap_busy()) return 0;', '    if (!A || A->magic != AP_MAGIC || !A->armed || A->in_commit || !A->lv_seen || A->pb_since || A->pb.active) return 0;', 'BootReadyTests'),
    ('ap.c', '    if (((ap_fw1)AP_GET_FMT)(((ap_fw0)AP_GET_OBJ)())) return 0;\n    u32 desc = AP_W(AP_IMAGER), regdesc = AP_W(AP_HOLDER);\n    return desc', '    u32 desc = AP_W(AP_IMAGER), regdesc = AP_W(AP_HOLDER);\n    return desc', 'BootReadyTests'),
    ('ap.c', '    return desc && regdesc && AP_W(regdesc) ? 1 : 0;\n}\n\nint ap_flush', '    return (desc || 1) && regdesc && AP_W(regdesc) ? 1 : 0;\n}\n\nint ap_flush', 'BootReadyTests'),
    ('ap.c', '            if (!ap_busy()) A->standby_picks++;\n            A->picked = (A->cur & 1u) + 1u; A->picks++;',
     '            if (!ap_busy() && !s->sby) { A->picked = 0; A->gated++; return 0; }\n            if (!ap_busy()) A->standby_picks++;\n            A->picked = (A->cur & 1u) + 1u; A->picks++;', 'CommitTests'),
    ('ap.c', '            if (!ap_busy()) A->standby_picks++;\n            A->picked = (A->cur & 1u) + 1u;',
     '            A->standby_picks++;\n            A->picked = (A->cur & 1u) + 1u;', 'CommitTests'),
    ('ap_calc.c', 'o->rok = apc_route_ok(o->src_w, o->src_h, o->sv_w, o->sv_h, o->sr_w, o->sr_h);', 'o->rok = o->sok;', 'CommitTests'),
    ('ap_calc.c', 'vw <= APC_VIS_MAX_W && rw <= sw && rh <= sh && vw && vh;', 'rw <= sw && rh <= sh && vw && vh;', 'CalcTests'),
    # v0.7.21test: PB_OwnModel -> the text pixel-size row for sizes without tiles
    ('ap.c', 'P->own_text = !stock;', 'P->own_text = 0;', 'PlaybackTests'),
    ('ap.c', 'else if (P->own_forced) {', 'else if (0) {', 'PlaybackTests'),
    ('ap.c', 'if (!P->own_text) { P->own_forced = 0; return 0; }', 'if (1) { P->own_forced = 0; return 0; }', 'PlaybackTests'),
    # v0.7.24test: rasters past stock DCI4K refused before the player's buffers
    ('ap.c', '* AP_W(obj + 0x9Cu) > AP_PB_MAX_AREA) {', '* AP_W(obj + 0x9Cu) > 0xFFFFFFFFu) {', 'PlaybackV1Tests'),
    # v0.7.25test: defect tables for our ids.  Not listed (equivalent on every reachable input, kept as guards): R68 +08
    # = 0 (an exact stock-geometry raster with its own table: DC < 6064 never is one), the missing end mark, the r0 == 2
    # test (the hooked site always passes 2: c030e2a0's "off" calls are the other sites), the point-list prefill
    # (c0310740 writes all 128 words).
    ('ap.c', 'if (f[0] != 2u || !s || !s->defc) return 0;', 'if (f[0] != 2u || !s) return 0;', 'DefectTests'),
    ('ap.c', 'f[1] = (u32)(uintptr_t)&A->defc[s - A->slot];', 'f[1] = (u32)(uintptr_t)&A->defc[0];', 'DefectTests'),
    ('ap.c', 'struct ap_slot *s = ap_slot_id(A, f[5]);\n        if (f[0] != 2u', 'struct ap_slot *s = ap_slot_id(A, AP_W(AP_IMAGER + 4u) + 1u);\n        if (f[0] != 2u', 'DefectTests'),
    ('ap.c', 'return p >= SL_ALIAS ? p - SL_ALIAS : p; }', 'return p; }', 'DefectTests'),
    ('ap.c', '    if (ap_busy()) return -4;', '', 'DefectTests'),
    ('ap.c', 'if (!words || words > AP_DEFC_WORDS ||', 'if (!words ||', 'DefectTests'),
    ('ap.c', ' || src + 4u * words > buf + AP_DEFC_BYTES - 0x100u * nt) return -3;', ') return -3;', 'DefectTests'),
    ('ap.c', 'if (AP_W(dir) != 1u || !nt || nt > 64u) return -2;', 'if (!nt || nt > 64u) return -2;', 'DefectTests'),
    ('ap.c', '    s->defc = A->defc_last > 0;', '    s->defc = 1;', 'DefectTests'),
    ('ap.c', '(AP_DEFC_CTX, s->id, words,', '(AP_DEFC_CTX, s->id ^ 1u, words,', 'DefectTests'),
    ('ap.c', '{0xC030F624u, 0xFA0C99D5u, K_BL},', '{0xC030EC94u, 0xFA0C9C39u, K_BL},', 'DefectTests'),
    # v0.7.27test: the first-frame sentinel and the read-only trace.  Not listed (equivalent on every reachable input,
    # kept as guards): the slot-id recheck at the arrival / completion, the commit's disarm, AP_TR_N's room (4 + 4 + 1)
    ('ap.c', 'if (!s || !d || (d & 3u) || AP_W(d + 0x1Cu) != s->id) return;', 'if (!s || !d || (d & 3u)) return;', 'FirstFrameTests'),
    ('ap.c', '#define AP_FF_AT(ras, row) ((ras) + (row) - 4u * AP_FF_WORDS)', '#define AP_FF_AT(ras, row) (ras)', 'FirstFrameTests'),
    ('ap.c', 'fmt == 1u ? 14u : 0u;', 'fmt == 1u ? 12u : 0u;', 'FirstFrameTests'),
    ('ap.c', '    ((ap_fw0)AP_DCACHE)();                                   /* no dirty line left', '    /* */                                   /* no dirty line left', 'FirstFrameTests'),
    ('ap.c', 'volatile u32 *p = (volatile u32 *)(uintptr_t)AP_FF_AT(ras, row);', 'volatile u32 *p = (volatile u32 *)(uintptr_t)AP_FF_AT(ras + SL_ALIAS, row);', 'FirstFrameTests'),
    ('ap.c', 'u32 seed = (ap_now_us() ^ 0x5346F11Eu ^ (A->ff_arms * 0x9E3779B9u)) | 1u;', 'u32 seed = 0x5346F11Fu;', 'FirstFrameTests'),
    ('ap.c', 'if (intact) A->ff_intact++; else A->ff_ok++;', 'if (!intact) A->ff_intact++; else A->ff_ok++;', 'FirstFrameTests'),
    ('ap.c', '{0xC038BDB4u, 0xEBFFA581u, K_BL},', '{0xC038BFD0u, 0xEB000188u, K_BL},', 'FirstFrameTests'),
    # the trace
    ('ap.c', '    r->us = 0;                                               /* no tick call here', '    r->us = ap_now_us();                                               /* no tick call here', 'FirstFrameTests'),
    ('ap.c', 'if (!T->live || T->done >= AP_TR_FRAMES || !s', 'if (!T->live || T->done > AP_TR_FRAMES || !s', 'FirstFrameTests'),
    ('ap.c', 'if (!T->live || T->writes >= AP_TR_FRAMES || !s', 'if (T->writes >= AP_TR_FRAMES || !s', 'FirstFrameTests'),
    ('ap.c', '    T->n = 0; T->lost = 0; T->done = 0; T->writes = 0; T->take++;', '    T->lost = 0; T->done = 0; T->writes = 0; T->take++;', 'FirstFrameTests'),
    ('ap.c', '        ap_tr_words(r->tail0, AP_FF_AT(u, row), 16u);', '        ap_tr_words(r->tail0, AP_FF_AT(u, row) + SL_ALIAS, 16u);', 'FirstFrameTests'),
    ('ap.c', '        ap_tr_words(r->head1, u + row, 8u);', '        ap_tr_words(r->head1, u + row + 4u, 8u);', 'FirstFrameTests'),
    ('ap.c', '        ap_tr_words(r->tailn, u + row * rows - 32u, 8u);', '        ap_tr_words(r->tailn, u + row * rows - 64u, 8u);', 'FirstFrameTests'),
    ('ap.c', '    for (u32 i = 0; i < n; i++) d[i] = s[i];', '    for (u32 i = 0; i < n; i++) { d[i] = s[i]; ((volatile u32 *)(uintptr_t)a)[i] = s[i] + 1u; }', 'FirstFrameTests'),
    ('ap.c', '    case H_FFDONE:                                                   /* FUN_c031bca0(raster) entry, IRQ */\n        ap_tr_done(A, f[0]);', '    case H_FFDONE:                                                   /* FUN_c031bca0(raster) entry, IRQ */\n        ap_tr_done(A, f[1]);', 'FirstFrameTests'),
    ('ap.c', 'r->x[0] = AP_W(0x301821E8u); r->x[1] = AP_W(0x30182280u);', 'r->x[0] = AP_W(0x301821ECu); r->x[1] = AP_W(0x30182280u);', 'FirstFrameTests'),
    ('ap.c', '    A->tr.live = 0;\n    ap_dmb();\n    struct ap_slot *s = ap_live(A);', '    ap_dmb();\n    struct ap_slot *s = ap_live(A);', 'FirstFrameTests'),
    ('ap.c', '    if (T->done >= AP_TR_FRAMES && T->writes >= AP_TR_FRAMES) T->live = 0;\n', '', 'FirstFrameTests'),
    # v0.7.28test: the REC-start resync.  Not listed (equivalent here: the emulated imager is the IMX410): the vtable
    # identity check
    ('ap.c', '        if (s && f[1] == s->id) { A->rs_ours++; ap_resync(A); }', '        if (s) { A->rs_ours++; ap_resync(A); }', 'ResyncTests'),
    ('ap.c', 'if (((ap_fw0)AP_RS_PERIOD)() <= AP_RS_MIN_US)', 'if (((ap_fw0)AP_RS_PERIOD)() < AP_RS_MIN_US)', 'ResyncTests'),
    ('ap.c', '    ((ap_fw2)AP_RS_V27)(obj, 1u);\n    ((ap_fw0)AP_RS_VD)();\n    ((ap_fw2)AP_RS_V27)(obj, 0u);',
     '    ((ap_fw2)AP_RS_V27)(obj, 0u);\n    ((ap_fw0)AP_RS_VD)();\n    ((ap_fw2)AP_RS_V27)(obj, 1u);', 'ResyncTests'),
    ('ap.c', '    ((ap_fw2)AP_RS_V27)(obj, 1u);\n    ((ap_fw0)AP_RS_VD)();\n', '    ((ap_fw2)AP_RS_V27)(obj, 1u);\n', 'ResyncTests'),
    ('ap.c', '    ((ap_fw2)AP_RS_V27)(obj, 0u);\n    ((ap_fw0)AP_RS_VD)();\n', '    ((ap_fw2)AP_RS_V27)(obj, 0u);\n', 'ResyncTests'),
    ('ap.c', '        u32 r = ((ap_fw4)A->ven[id][V_DOWN])(f[0], f[1], f[2], f[3]);\n        struct ap_slot *s = ap_live(A);\n        A->rs_seen++;',
     '        struct ap_slot *s = ap_live(A);\n        A->rs_seen++;\n        if (s && f[1] == s->id) { A->rs_ours++; ap_resync(A); }\n        u32 r = ((ap_fw4)A->ven[id][V_DOWN])(f[0], f[1], f[2], f[3]);\n        if (0)', 'ResyncTests'),
    # v0.7.29test: the image controller's switch, the reach counters
    ('ap.c', '    {0xC030D168u, 0xEB0018A4u, K_BL},', '    {0xC030D174u, 0xEB018177u, K_BL},', 'ResyncTests'),
    ('ap.c', '        A->rs_seen++;                                                /* every mode switch', '        /* */                                                /* every mode switch', 'ResyncTests'),
    ('ap.c', '{ A->rs_ours++; ap_resync(A); }', '{ ap_resync(A); }', 'ResyncTests'),
    ('ap.c', '    A->rs_calls++; A->rs_last = 0u;', '    A->rs_last = 0u;', 'ResyncTests'),

    # CPU x2, the streaming pass (CpuX2StreamTests / CpuX2TagTests): every way a frame could go out unbinned (D3) must be
    # caught.  Not listed (guards, equivalent on every emulated input): the GIVEUP bound, the strip-size cap, the IRQ-off
    # claim (no concurrency under unicorn), the CTR / mh / mv refusals (no recipe reaches them), the kernel rc path
    ('ap.c', '    H->doubled++;\n    return 2u * n;', '    H->doubled++;\n    return n;', 'CpuX2StreamTests'),
    ('ap.c', '        H->alloc_bad++;                                      /* and every arrival', '        /* */                                      /* and every arrival', 'CpuX2StreamTests'),
    ('ap.c', 'u32 why = H->failed ? H->failed : H->alloc_bad ? (u32)AP_H2_W_ALLOC :', 'u32 why = H->failed ? H->failed : 0 ? (u32)AP_H2_W_ALLOC :', 'CpuX2StreamTests'),
    ('ap.c', '(ras != AP_W(fr + AP_FR_HANDLE) + res || AP_W(fr + AP_FR_CAP) < res + 2u * H->n)', '(ras != AP_W(fr + AP_FR_HANDLE) + res)', 'CpuX2StreamTests'),
    ('ap.c', '    AP_W(msg + AP_MSG_DROP) = AP_H2_DROP;                    /* release', '    /* */                    /* release', 'CpuX2StreamTests'),
    ('ap.c', '        if (e->state != AP_H2_BINNED) why = AP_H2_W_LATE;', '', 'CpuX2StreamTests'),
    ('ap.c', '    ap_h2_fail(A, why);\n    H->stops++;', '    H->stops++;', 'CpuX2StreamTests'),
    ('ap.c', '        H->take++; H->failed = 0; H->nsamp = 0;', '        H->take++; H->nsamp = 0;', 'CpuX2StreamTests'),
    ('ap.c', '    if (AP_W(AP_H2_FLAGS) & 0x11u) { ap_h2_fail(A, AP_H2_W_FLIP); return; }', '', 'CpuX2StreamTests'),
    ('ap.c', '        if (m && AP_W(m + AP_FR_HANDLE) + AP_W(m + AP_FR_RESERVE) == ras) { fr = m; break; }', '        if (m && AP_W(m + AP_FR_HANDLE) == ras) { fr = m; break; }', 'CpuX2StreamTests'),
    ('ap.c', '        if (e->cur_last && cur > e->cur_last) e->trusted = 1u;', '        e->trusted = 1u;', 'CpuX2StreamTests'),
    ('ap.c', 'e->ras + (e->avail + 2u) * H->row <= e->cur_last', 'e->ras + (e->avail + 1u) * H->row <= e->cur_last', 'CpuX2StreamTests'),
    ('ap.c', '    if (cur > e->ras && cur < e->ras + 2u * H->n) {', '    if (cur > e->ras) {', 'CpuX2StreamTests'),
    ('ap.c', '        if (H->q[i].state == AP_H2_QUEUED && H->q[i].ras == ras) H->q[i].complete = 1u;', '        if (H->q[i].state == AP_H2_QUEUED && H->q[i].ras == ras) H->q[i].complete = 0u;', 'CpuX2StreamTests'),
    ('ap.c', '    ap_h2_inval(in0, in1, c + 2u * H->n, line);', '', 'CpuX2StreamTests'),
    ('ap.c', '    ap_h2_inval(in0, in1, c + 2u * H->n, line);', '    ap_h2_inval(in0 + line, in1, c + 2u * H->n, line);', 'CpuX2StreamTests'),
    ('ap.c', '    ap_h2_clean(out0, out1, line);', '', 'CpuX2StreamTests'),
    ('ap.c', '    ap_h2_clean(out0, out1, line);', '    ap_h2_clean(out0, out1 - line, line);', 'CpuX2StreamTests'),
    ('ap.c', '    u32 c = ras + SL_ALIAS, row = H->row, line = H->line;', '    u32 c = ras, row = H->row, line = H->line;', 'CpuX2StreamTests'),
    ('ap.c', '        rc = ap_h2_k12(out0, in0, in1 - in0);', '        rc = ap_h2_k12(in0, in0, in1 - in0);', 'CpuX2StreamTests'),
    ('ap.c', '        for (u32 k = 0; k < 14u; k++) d[k] = ((const uint8_t *)out)[k];', '        for (u32 k = 0; k < 13u; k++) d[k] = ((const uint8_t *)out)[k];', 'CpuX2StreamTests'),
    ('ap.c', '    } else if (r1 < H->rows) {', '    } else if (1) {', 'CpuX2StreamTests'),
    ('ap.c', '    e->state = AP_H2_FREE;\n}', '}', 'CpuX2StreamTests'),
    ('ap.c', '            if (r1 == H->rows) { ap_dmb(); e->state = AP_H2_BINNED; }', '            ap_dmb(); e->state = AP_H2_BINNED;', 'CpuX2StreamTests'),
    ('ap.c', '    if (!ap_h2_task_start(A)) return AP_E_CPU2_TASK;', '    ap_h2_task_start(A);', 'CpuX2StreamTests'),
    ('ap.c', '    if (id < 1 || ((s32 (*)(s32, u32))AP_TK_STA)(id, 0)) return 0;', '    if (id < 1) return 0;\n    ((s32 (*)(s32, u32))AP_TK_STA)(id, 0);', 'CpuX2StreamTests'),
    ('ap.c', '    H->tramp[2] = (u32)(uintptr_t)A;', '    H->tramp[2] = (u32)(uintptr_t)A + 4u;', 'CpuX2StreamTests'),
    ('ap.c', '    A->h2.armed = cpu2;                                      /* the live slot', '    A->h2.armed = 0;                                      /* the live slot', 'CpuX2StreamTests'),
    ('ap.c', 'return A->h2.armed && s && s->rec_w && s->hw_w == 2u * s->rec_w && ap_rec_picked(A);', 'return A->h2.armed && s && s->rec_w && s->hw_w == 2u * s->rec_w;', 'CpuX2StreamTests'),
    ('ap.c', '    {0xC031CCF4u, 0xFA0C5251u, K_BL},', '    {0xC031CD0Cu, 0xFA0C524Bu, K_BL},', 'CpuX2StreamTests'),
    ('ap.c', '        b[12u + 2u * i] = (i & 1u) ? 0xFFu : 0x01u;', '        b[12u + 2u * i] = (i & 1u) ? 0x01u : 0xFFu;', 'CpuX2TagTests'),
    ('ap.c', '        b[13u + 2u * i] = H->mv == 2u ? ((i & 2u) ? 0xFFu : 0x01u) : 0u;', '        b[13u + 2u * i] = 0u;', 'CpuX2TagTests'),
    ('ap.c', '        if (s && ap_h2_take(A) && f[1] && f[2] == 0u) {', '        if (s && ap_h2_take(A) && f[1]) {', 'CpuX2TagTests'),
    # D11 twin (CpuX2TwinTests): CPU x2 built from its own (pre-11-05) spec / no unity override / both RWZM words
    ('ap_calc.c', '        q = &w->twin; hbin = 1; vbin = 1;\n', '', 'CpuX2TwinTests'),
    ('ap_calc.c', '    if (cpu2) o->isp[0x64u / 4u] = APC_RWZM_UNITY;', '', 'CpuX2TwinTests'),
    ('ap_calc.c', '    if (cpu2) o->isp[0x64u / 4u] = APC_RWZM_UNITY;', '    if (cpu2) { o->isp[0x64u / 4u] = APC_RWZM_UNITY; o->isp[0x60u / 4u] = APC_RWZM_UNITY; }', 'CpuX2TwinTests'),
    ('ap_calc.c', '        q = &w->twin; hbin = 1; vbin = 1;\n', '        q = &w->twin; vbin = 1;\n', 'CpuX2TwinTests'),
    # v3 pass: cursor trusted again / fixed 40 ms wait / no BUFA0 line check / uncached raster / uncached entry
    ('ap.c', '    if (e->complete) return H->rows;\n    if (H->nsamp', '    if (e->complete || AP_W(AP_H2_CURSOR)) return H->rows;\n    if (H->nsamp', 'CpuX2StreamTests'),
    ('ap.c', 'k < H->wait_ms) { ap_h2_sleep(1u); k++; }', 'k < 40u) { ap_h2_sleep(1u); k++; }', 'CpuX2StreamTests'),
    ('ap.c', 'if (H->line_words * 4u != H->row || H->lines != H->rows)', 'if (H->lines != H->rows)', 'CpuX2StreamTests'),
    ('ap.c', '    u32 c = ap_h2_cached(ras);\n', '    u32 c = ras;\n', 'CpuX2StreamTests'),
    ('ap.c', '    H->entry = ec ? ec | 1u : ent;', '    H->entry = ent + 0u * ec;', 'CpuX2StreamTests'),
    ('ap.c', '    u32 c = (mode & AP_H2_B_ASIS) ? buf : ap_h2_cached(buf);', '    u32 c = buf;', 'CpuX2BenchTests'),
    ('ap.c', '    u32 maint = !(mode & AP_H2_B_NOMAINT), n2', '    u32 maint = 1u, n2', 'CpuX2BenchTests'),
    # D11 (4) (Bei 11-05, choice B): a 14-bit AD CPU x2 records true 14 -- the bits are the record's, nothing else moves
    ('ap_calc.c', 'u32 rec_zh = cpu2 ? 1024u : (u32)w->spec.zh;', 'u32 rec_zh = (u32)w->spec.zh;', 'CpuX2TwinTests'),
    ('ap_calc.c', 'u32 rec_zh = cpu2 ? 1024u : (u32)w->spec.zh;', 'u32 rec_zh = (u32)w->spec.zh;', 'CpuX2Tests'),
    ('ap_calc.c', 'u32 rec_zh = cpu2 ? 1024u : (u32)w->spec.zh;', 'u32 rec_zh = 1024u + 0u * cpu2;', 'CalcTests'),
    ('ap_calc.c', '    if (cpu2) o->isp[0x64u / 4u] = APC_RWZM_UNITY;', '    if (cpu2) o->isp[0x64u / 4u] = APC_RWZM_UNITY;\n    if (cpu2 && o->rec14) o->isp[0x80u / 4u] = 8u;', 'CpuX2TwinTests'),
    ('ap.c', 'u32 bits = o->rec14 ? 14u : 12u, line = ap_h2_dline();', 'u32 bits = 12u, line = ap_h2_dline();', 'CpuX2StreamTests'),
    ('ap.c', '    if (bits == 12u) {\n        rc = ap_h2_k12', '    if (bits == 12u || bits == 14u) {\n        rc = ap_h2_k12', 'CpuX2StreamTests'),
    ('ap.c', 'H->bits = bits; H->row = (o->hw_w * bits) >> 3;', 'H->bits = bits; H->row = (o->hw_w * 12u) >> 3;', 'CpuX2StreamTests'),
    ('ap.c', 'H->n = (o->rec_w * o->rec_h * bits) >> 3;', 'H->n = (o->rec_w * o->rec_h * 12u) >> 3;', 'CpuX2StreamTests'),
    ('ap.c', 'b[10] = (uint8_t)H->bits;', 'b[10] = 12u;', 'CpuX2TagTests'),
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
