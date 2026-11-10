#!/usr/bin/env python3
"""First-frame MMIO diff: the stock movie record-start path (ContSet_Adr1 @C031BE60, incl. SetImgMode_s) under
unicorn against out/MAIN_c0000000.bin, for stock mode 106 and SensorLab's virtual modes (230/231) built through
apply/ap.c's real hooks (test_apply.DefectCam).  Every write to 0x30000000..0x31000000 is recorded (pc, addr, value).

    cd projects/sensorlab-imx410/validation/20261103-first-frame-mmio-diff
    python3 -B mmio_diff.py            # writes mmio-<case>.tsv, diff.txt

Offline only: no camera, no USB, no product code changed (the apply unit is built from its source as the tests do).
"""
import collections, ctypes, pathlib, struct, sys

HERE = pathlib.Path(__file__).resolve().parent
APPLY = HERE.parents[1] / 'apply'
sys.path.insert(0, str(APPLY))
sys.argv = sys.argv[:1] + [a for a in sys.argv[1:] if a.startswith('--')]
import test_apply as T                                       # noqa: E402
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ, UC_HOOK_BLOCK, UC_HOOK_MEM_UNMAPPED  # noqa
from unicorn.arm_const import *                              # noqa: E402,F403

DECOMP = HERE.parents[3] / 'out' / 'decomp' / 'full'


def _funcs():
    import re
    out = {}
    for f in sorted(DECOMP.glob('blk_*.c')):
        for m in re.finditer(r'^/\* ==== (\S+) @ ([0-9a-f]+) ====', f.read_text(errors='replace'), re.M):
            out[int(m.group(2), 16)] = m.group(1)
    return out


FUNCS = _funcs()
MMIO_LO, MMIO_HI = 0x30000000, 0x31000000
HOLDER_AT, LVP_AT, ALLOC_AT = 0x48500000, 0x48510000, 0x48600000
DESCBUF = 0x48520000
DEST = 0x4C000000                                            # the RAW destination handed in desc+0x30 (any value)
STANDBY_MODE = 8                                             # the sensor mode before REC (FIRST_FRAME_PURPLE §已確定 1)

# stubbed firmware: name -> (addr, behaviour).  'ret0' returns 0, 'ret1' 1, 'self' r0 unchanged.
STUBS = {
    # logging / trace
    'LOG_OBJ': (0xC0019DC0, 'logobj'), 'LOG_A450': (0xC001A450, 'ret0'), 'LOG_A0D8': (0xC001A0D8, 'ret0'),
    'LOG_9FD8': (0xC0019FD8, 'ret0'),
    'ASSERT': (0xC0011100, 'assert'), 'ASSERT2': (0xC0011130, 'assert'),
    # RTOS waits / sleeps
    'VD_WAIT': (0xC01269A8, 'ret0'), 'SLEEP_MS': (0xC03705D8, 'ret0'),
    'FRAMECNT_A': (0xC0125870, 'ret0'), 'FRAMECNT_B': (0xC0126010, 'ret0'),
    'SEM_TAKE': (0xC01F8E8C, 'ret0'), 'SEM_GIVE': (0xC01F8CDC, 'ret0'),
    'DELAY_A08': (0xC0000A08, 'ret0'),
    'IMX_BASE_C121D18': (0xC0121D18, 'ret0'),             # tail of the IMX410 base ctor (FUN_c031fe08)
    'IMX_DBGPRINT': (0xC0322B90, 'ret0'),                 # XC_ImageSensorIMX410 debug printf (adjust-data gate)
    # SetImgMode_s > FUN_c03149b0 > FUN_c0313510: the LV-side pipeline sizing (reads the LV manager's route/state
    # objects that the harness does not build).  Stubbed -> 1; see README "stubbed"
    'LV_PIPE_C0313510': (0xC0313510, 'ret1'),
    'GAIN_LOOKUP_C03131E0': (0xC03131E0, 'ret0'),         # gain from the AE settings map (uninitialised): 0 -> 1.00x
    'LENS_C035F560': (0xC035F560, 'ret0'),                # SetImgMode_s's lens-interface branch (LensInt3 ctor)
    # C++ operator new for the LV geometry object (FUN_c04370e8 -> FUN_c0438980 -> *DAT_c2f21664 vtable +0xC)
    'OPNEW': (0xC0438980, 'alloc'),
    'UPTR_DEL_RAWINFO': (0xC022EDB0, 'ret0'),             # unique_ptr<XC_LiveViewStateRawInfo> dtor: leaked
}

# lazy singletons whose constructors create RTOS objects: marked constructed (FUN_c0013090 guard word = 1), the
# object left zeroed (the defect tests call FUN_c030e2a0 on the same zeroed ctx)
GUARDS_DONE = {
    0xC343A684: 'Corr (ImagerDefect ctx 0xC343A66C): mutex/event ctor',
    0xC34393FC: 'ImagCtrl 0xC34393E8 (task/event ctor)',
    0xC375D95C: 'LV manager part 1 (FUN_c0436590)', 0xC375D964: 'LV manager 0xC375D840 (FUN_c0436608): +4/+8 seeded',
}

# out/MAIN_c0000000.bin is the old untruncated file: its bytes from 0xC2EF6E00 are NOT the initialised data segment
# (research/imaging-hw/notes/CRCT_PATH_SELECTOR_SOLVED.md §1).  seg1 is overlaid there; test_apply does not do this.
SEG1 = HERE.parents[3] / 'out' / 'seg1_c2ef6e00.bin'
SEG1_AT = 0xC2EF6E00
REAL_DESC = 0xC2F1E654                                       # the IMX410 mode descriptor (seg1); +0x114 = 0xC0B5F770
DATA_INIT = {}

# status bits a poll waits for: on every read the bit is forced (reads are otherwise the last value written)
READ_FORCE = {
    0x30000000: (0x100, 'FUN_c0127be8 clock-switch done (bit 8)'),
}

CASES = {                    # recipe args (test_apply.recipe), or the stock picker key
    'stock106': 'FHD30',
    '12v2': (6048, 4020, 3024, 2010, '1x2', 12),             # t28-t35 live: 3024x2010, RWZM v 1:1 (matches the DNGs)
    '14v2': (6048, 4020, 3024, 2010, '1x2', 14),
    '1x1_12': (6048, 4040, 3024, 2020, '1x1', 12),           # dark set key 1: 3024x2020
    '12v2_dc4040': T.R12V2,                                  # today's quality pick: 3024x2008, RWZM v 1027 (t02-t19
                                                             # DNGs are 2014 rows -- not what was live then)
    'stockUHD30': 'UHD30',                                   # reference: stock UHD route
}
# what-if variants (emulation only, product untouched): (base case, canvas word patches {offset in canvas: value})
# canvas = holder+0x5C (the profile words): +0x64/+0xD4 rec RWZM h/v, +0x60/+0xD0 LV RWZM h/v (FUN_c0438018)
VARIANTS = {
    '12v2+lvrwzm=rec': ('12v2', {0x60: 2048, 0xD0: 1024}, {}),
    '1x1_12+lvrwzm=rec': ('1x1_12', {0x60: 2048, 0xD0: 2048}, {}),
    # ContSet_Adr1's BUFA1 start site C031CAE0 `mov r0,#1` -> #2: FUN_c0631c08(2) writes 0x30182004 = 8
    '12v2+start8': ('12v2', {}, {0xC031CAE0: 0xE3A00002}),
    # follow-up: avoid an exact vertical 0x400 (rec RWZM v = canvas +0xD4; 1023 is what our rows carry today)
    '12v2+v1023': ('12v2', {0xD4: 1023}, {}),
    '12v2+v1025': ('12v2', {0xD4: 1025}, {}),
}
START_SITE, START_STOCK = 0xC031CAE0, 0xE3A00001


class MCam(T.DefectCam):
    def __init__(self, extra=None, **kw):
        super().__init__(**kw)
        mu = self.mu
        mu.mem_write(SEG1_AT, SEG1.read_bytes())
        # boot's scalar copy into the real descriptor (FUN_c0322ea0; FUN_c0128890 = 0x100), then the synthetic DESC
        # the tests use gets the real scalar fields + the +0x114 reduction table; its table pointers stay the tests'
        self.call(0xC0322EA0)
        keep = {0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x24, 0x28, 0x40, 0x44, 0x48, 0x4C, 0xF4, 0xF8, 0x128, 0x12C}
        for off in range(0, 0x148, 4):
            if off not in keep:
                self.put(T.DESC + off, self.w(REAL_DESC + off))
        for off in sorted(keep):
            if off not in (0x128, 0x12C):
                assert self.w(T.DESC + off) == self.w(REAL_DESC + off), hex(off)
        mu.mem_map(0x30100000, MMIO_HI - 0x30100000)
        mu.mem_map(HOLDER_AT, 0x100000)
        mu.mem_map(ALLOC_AT, 0x100000)
        self.abump = ALLOC_AT
        self.mmio, self.mreads, self.trail, self.events = [], [], collections.deque(maxlen=64), []
        self.stubs = dict(STUBS, **(extra or {}))
        for n, (a, how) in self.stubs.items():
            self.stub(a, n)
        mu.hook_add(UC_HOOK_MEM_WRITE, self._mw, begin=MMIO_LO, end=MMIO_HI - 1)
        mu.hook_add(UC_HOOK_MEM_READ, self._mr, begin=MMIO_LO, end=MMIO_HI - 1)
        mu.hook_add(UC_HOOK_BLOCK, self._blk)
        mu.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        self.recording = True
        self.fcalls = []
        self.cstack = []

    def _blk(self, mu, addr, size, data):
        self.trail.append(addr)
        st = self.cstack
        while st and any((addr | 1) == (l | 1) for _, _, l in st[-4:]):
            # returned to (one of) the latest callers' lr: pop through it
            while st and (st[-1][2] | 1) != (addr | 1):
                st.pop()
            if st:
                st.pop()
        n = FUNCS.get(addr)
        if n:
            lr = self.r(UC_ARM_REG_LR)
            self.fcalls.append((addr, n, lr))
            st.append((addr, n, lr))
            if addr == 0xC0631C08 or addr == 0xC031D988:
                pass

    def _unmapped(self, uc, access, addr, size, value, data):
        self.events.append(('UNMAPPED', hex(access), hex(addr), hex(self.r(UC_ARM_REG_PC))))
        return False

    def _mw(self, uc, access, addr, size, value, data):
        if self.recording:
            self.mmio.append((len(self.mmio), self.r(UC_ARM_REG_PC), addr, size, value & 0xFFFFFFFF, self.ctx))

    def _mr(self, uc, access, addr, size, value, data):
        f = READ_FORCE.get(addr & ~3)
        if f:
            v = struct.unpack('<I', uc.mem_read(addr & ~3, 4))[0] | f[0]
            uc.mem_write(addr & ~3, struct.pack('<I', v))
        if self.recording:
            self.mreads.append((self.r(UC_ARM_REG_PC), addr))

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name in self.stubs:
            try:
                how = self.stubs[name][1]
                r0 = self.r(UC_ARM_REG_R0)
                self.events.append((name, hex(r0), hex(self.r(UC_ARM_REG_R1)), hex(self.r(UC_ARM_REG_LR))))
                if how == 'ret0':
                    return self.ret(0)
                if how == 'ret1':
                    return self.ret(1)
                if how == 'self':
                    return self.ret()
                if how == 'logobj':
                    return self.ret(0xC303448C)
                if how == 'assert':
                    return self.ret(0)
                if how == 'alloc':
                    p = (self.abump + 31) & ~31
                    self.abump = p + max(self.r(UC_ARM_REG_R0) if name != 'OPNEW' else self.r(UC_ARM_REG_R0), 0x40)
                    mu.mem_write(p, b'\0' * 0x100)
                    return self.ret(p)
                if callable(how):
                    return how(self)
                raise RuntimeError(how)
            except Exception as e:                           # pragma: no cover
                self.error = e
                mu.emu_stop()
                return
        return super()._hook(mu, addr, size, data)

    ctx = '-'

    def run(self, pc, *args, thumb=False, sp=T.STACK - 0x8000, cap=200_000_000):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, sp)
        for i, v in enumerate(args):
            mu.reg_write([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3][i], v & 0xFFFFFFFF)
        mu.reg_write(UC_ARM_REG_LR, T.DONE)
        try:
            mu.emu_start(pc | (1 if thumb else 0), T.DONE, **T.emu_cap(cap))
        except Exception as e:
            raise RuntimeError(f'{pc:#x}: {e}; pc={self.r(UC_ARM_REG_PC):#x} lr={self.r(UC_ARM_REG_LR):#x} '
                               f'trail={[hex(x) for x in list(self.trail)[-12:]]} events={self.events[-4:]}\n  calls='
                               + '\n  '.join(f'{n} lr={l:#x}' for a, n, l in self.fcalls[-8:])
                               + '\n  STACK ' + ' > '.join(n for a, n, l in self.cstack))
        if self.error:
            raise self.error
        if mu.reg_read(UC_ARM_REG_PC) != T.DONE:
            raise RuntimeError(f'{pc:#x} did not return (pc {self.r(UC_ARM_REG_PC):#x}) '
                               f'trail={[hex(x) for x in list(self.trail)[-6:]]} reads={[(hex(a),hex(b)) for a,b in self.mreads[-4:]]}\n  calls='
                               + '\n  '.join(f'{n} lr={l:#x}' for a, n, l in self.fcalls[-8:])
                               + '\n  STACK ' + ' > '.join(n for a, n, l in self.cstack))
        return self.r(UC_ARM_REG_R0)


def setup(case):
    cam = MCam()
    patch = {}
    if case in VARIANTS:
        base, patch, code = VARIANTS[case]
        args = CASES[base]
        for a, v in code.items():
            assert cam.w(a) == START_STOCK
            cam.put(a, v)
    else:
        args = CASES[case]
    if isinstance(args, str):
        e = cam.call(T.PICKER, 0, T.TAB3, cam.key(args))
        _, pid, mode = struct.unpack('<3I', cam.mu.mem_read(e, 12))
        sel = None
    else:
        assert cam.init() == T.AP_OK
        sel = T.recipe(*args)[0]
        assert cam.apply(sel) == T.AP_OK, cam.status()
        st = cam.status()
        pid, mode = st['pid'], st['mode_id']
    # the real XC_ImageSensorIMX410 ctor fields (FUN_c03255b0 over FUN_c031fe08); the holder getter's guard is set,
    # so +0xD8 = 0xC343B67C (the register-record holder the tests already fill)
    cam.put(0xC343B680, 1)
    cam.run(0xC03255B0, T.IMAGER, T.DESC)
    assert cam.w(T.IMAGER + 0xD8) == T.HOLDER and cam.w(T.IMAGER) == T.DESC
    cam.case, cam.pid, cam.mode, cam.sel = case, pid, mode, sel
    # the LV canvas the firmware builds for that profile (FUN_c043a158, ap.c's vpro/canvas hooks live for ours)
    holder = HOLDER_AT
    cam.mu.mem_write(holder, b'\0' * 0x400)
    cam.put(LVP_AT, 0); cam.put(LVP_AT + 4, 0)
    cam.run(0xC043A158, holder, pid, LVP_AT)
    assert cam.w(holder + 4) == holder + 0x5C
    for off, v in patch.items():
        cam.put(holder + 0x5C + off, v)
    cam.put(T.LV_MGR + 8, holder)
    cam.put(T.LV_MGR + 4, LVP_AT - 0x48)
    return cam


def geometry(cam):
    out = WORKG = T.WORK + 0x9000
    cam.put(out, 0)
    cam.run(0xC04370E8, T.LV_MGR, out)
    g = cam.w(out)
    return g, list(struct.unpack('<48I', cam.mu.mem_read(g, 0xC0)))


CONTSET, CUR_MODE, CONT_CTX = 0xC031BE60, 0xC343A6D8, 0xC343A964


def record_start(cam, fmt=0, standby=STANDBY_MODE):
    """FUN_c030cf98's call: ContSet_Adr1(ctx, desc - 8) with the CinemaDNG REC-start fills (FUN_c0378a50)"""
    d = DESCBUF
    cam.mu.mem_write(d, b'\0' * 0x1C0)
    cam.put(d + 0x1C, cam.mode)
    cam.put(d + 0x20, fmt)
    cam.put(d + 0x28, fmt)
    cam.put(d + 0x38, DEST)
    cam.put(CUR_MODE, standby)
    cam.put(T.IMAGER + 4, standby)
    for g in GUARDS_DONE:
        cam.put(g, 1)
    for a, (v, _) in DATA_INIT.items():
        cam.put(a, v)
    cam.mmio.clear(); cam.mreads.clear(); cam.events.clear(); cam.cstack.clear(); cam.fcalls.clear()
    return cam.run(CONTSET, CONT_CTX, d)


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == '--geom':
    for c in CASES:
        cam = setup(c)
        g, words = geometry(cam)
        print(c, cam.pid, cam.mode, [(hex(4*i), w) for i, w in enumerate(words) if w])


import bisect
_FA = sorted(FUNCS)


def owner(pc):
    i = bisect.bisect_right(_FA, pc & ~1) - 1
    return FUNCS[_FA[i]] if i >= 0 else '?'


def run_case(case, pre_standby=True):
    cam = setup(case)
    for g in GUARDS_DONE:
        cam.put(g, 1)
    pre = []
    if pre_standby:
        # standby: the sensor mode 8 set the same way (SetImgMode_s), so RMW registers hold a standby value
        cam.put(CUR_MODE, 0)
        cam.run(0xC031A0F8)                                  # imager state object 0xC343A78C
        cam.put(0xC343A78C, 2)                               # powered, LV (ContSet_Adr1 sets 2 itself; 5 = power-on)
        cam.mmio.clear()
        cam.run(0xC0313400, CUR_MODE, STANDBY_MODE)
        pre = list(cam.mmio)
    cam.sensor = []
    rc = record_start(cam)
    cam.sensor_rec = list(cam.sensor)
    return cam, rc, pre


def dump(cam, path):
    with open(path, 'w') as f:
        f.write('seq\tpc\tfunc\taddr\tvalue\n')
        for seq, pc, a, sz, v, _ in cam.mmio:
            f.write(f'{seq}\t{pc:#010x}\t{owner(pc)}\t{a:#010x}\t{v:#010x}\n')


FOCUS = [  # (address, label)
    (0x30182004, 'BUFA1 start/mode'), (0x30182008, 'BUFA7 start/mode'), (0x30182048, 'BUFA IRQ status (W1C)'),
    (0x30002060, 'BUFA clock/enable'), (0x30000804, 'BUFA reset'),
    (0x30182210, 'BUFA1 lines'), (0x30182214, 'BUFA1 line words'), (0x30182218, 'BUFA1 chunk words'),
    (0x3018221C, 'BUFA1 +1C'), (0x30182220, 'BUFA1 flags'), (0x30182224, 'BUFA1 +24'), (0x30182280, 'BUFA1 dest>>2'),
    (0x30182310, 'BUFA7 lines'), (0x30182314, 'BUFA7 line words'), (0x30182318, 'BUFA7 chunk words'),
    (0x3018231C, 'BUFA7 +1C'), (0x30182320, 'BUFA7 flags'), (0x30182324, 'BUFA7 +24 (bit20 = w%12!=0)'),
    (0x30182380, 'BUFA7 dest>>2'),
    (0x300F0004, 'crop/RWZM enables'), (0x300F0680, 'crop A1 x words'), (0x300F0684, 'crop A1 y'),
    (0x300F068C, 'crop A1 x rem'), (0x300F06E0, 'crop A7 x words'), (0x300F06E4, 'crop A7 y'),
    (0x300F06EC, 'crop A7 x rem'), (0x300F06D0, 'A7 route'),
    (0x300F0870, 'main hvbin bypass'), (0x300F0900, 'RWZM main enable'), (0x300F0908, 'RWZM h (phase<<16|ratio)'),
    (0x300F090C, 'RWZM v (phase<<16|ratio)'), (0x300F2900, 'RWZM sub enable'),
    (0x3010000C, 'RX x window (12-px words)'), (0x30100024, 'RX y window'), (0x300F021C, 'RX x pad'),
    (0x30100004, 'TG H'), (0x30100020, 'TG V'), (0x3010008C, 'RX 1/4-frame line IRQ'),
]


def final_values(cam):
    v = {}
    for seq, pc, a, sz, val, _ in cam.mmio:
        v[a] = (val, owner(pc))
    return v


def arm_sequence(cam):
    """the record path's BUFA/crop block: every write from the first BUFA reset/stop to the end"""
    lo = next((i for i, (_, pc, a, *_r) in enumerate(cam.mmio) if a in (0x30000804,) and
               owner(pc) in ('FUN_c0630fa0', 'FUN_c06314a8') and i > 300), 0)
    return [(owner(pc), a, val) for _, pc, a, sz, val, _ in cam.mmio[lo:]]


if __name__ == '__main__' and len(sys.argv) == 1:
    finals, arms, order = {}, {}, list(CASES) + list(VARIANTS)
    for c in order:
        cam, rc, pre = run_case(c)
        finals[c], arms[c] = final_values(cam), arm_sequence(cam)
        print(c, 'mode', cam.mode, 'pid', cam.pid, 'rc', rc, 'writes', len(cam.mmio), 'standby writes', len(pre),
              'sensor writes', len(cam.sensor_rec), 'stub hits', dict(collections.Counter(e[0] for e in cam.events)))
        dump(cam, HERE / f'mmio-{c}.tsv')
        with open(HERE / f'sensor-{c}.tsv', 'w') as f:
            f.write('reg\tvalue\n' + ''.join(f'{a:#06x}\t{v:#04x}\n' for a, v in cam.sensor_rec))
    with open(HERE / 'diff.txt', 'w') as f:
        f.write('# final value written during ContSet_Adr1 (record start), per register; "-" = not written\n')
        f.write('# generated by mmio_diff.py; emulated, not measured on the camera\n\n')
        f.write(f'{"register":<12}{"meaning":<30}' + ''.join(f'{c:>20}' for c in order) + '\n')
        for a, lab in FOCUS:
            row = [finals[c].get(a) for c in order]
            mark = '*' if len({r[0] if r else None for r in row}) > 1 else ' '
            f.write(f'{mark}{a:#010x}  {lab:<30}' + ''.join(f'{(f"{r[0]:#x}" if r else "-"):>20}' for r in row)
                    + '\n')
        for c in order:
            f.write(f'\n## {c}: arm block (writer, register, value) in order\n')
            f.write(''.join(f'{w:<16}{a:#010x}  {v:#010x}\n' for w, a, v in arms[c]))
    print(open(HERE / 'diff.txt').read().split('## ')[0])
