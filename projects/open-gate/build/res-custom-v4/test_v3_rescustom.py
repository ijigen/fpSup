"""res-custom, the multi-format OpenGate core (32RESCUS.BIN) and its format data
files (\fpSup\RESCUS\*.RCD), loaded by the real 加載器 in Unicorn against the
reference image.

    cd projects/open-gate/build/res-custom && python3 -B -m unittest test_v3_rescustom

What runs for real: loader.S, LOADER.BIN, the core's entry (reading the data
files through the firmware's directory and file calls, as the harness models
them), the claims, the veneers, every hook site, the shims and the C logic, the
Quick Set record layer on every recipe record, and -- for an id that is not
ours -- the firmware's own lookup functions.  Stubbed, and said so: uishare's
uia_apply inside the core (no GUI objects in the image's RAM: the stub checks
the block it is given, hands out the CSV slot and the STRBASE ids), the
resource cache's v2/v3, the layer below each Quick Set site, and the firmware
routines the restore and the C code call (settings getters, the live-view
stop/start, the string emitter, the sensor register writer).

The mode descriptor is built by the firmware at boot (the image holds
compressed data there), so the tests build one: the real timing (0xC0B59500),
metadata (0xC0B59DC0) and receiver (0xC0B5C638) tables, and synthetic tables
for the three whose base the image does not show (+0x24, +0x48, +0xF4) and for
the magnifier's (+0x128).  The register descriptor 0xC0B5FDA4 is the image's.

The rows are in data-file name order: OG2K.RCD before OG3K.RCD.

Emulated, not on the camera.
"""
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
BUILD = HERE.parent
ROOT = BUILD.parent.parent.parent
V3 = ROOT / 'fpSup' / 'fp_usb_shell' / 'v3'
UISHARE = ROOT / 'fpSup' / 'uishare'
sys.path.insert(0, str(V3))
sys.path.insert(0, str(V3.parent))
sys.path.insert(0, str(BUILD))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(UISHARE))

import test_v3 as T                                       # noqa: E402
import ogc_layout as L                                    # noqa: E402
import rcd                                                # noqa: E402
from ui import fpui, qs as QS                             # noqa: E402
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,   # noqa: E402
                               UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R11,
                               UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)

TAB1, TAB2, TAB3 = 0xC0BE5810, 0xC0BE59B0, 0xC0BE5B50
PICKER, SETTER, FMTSET = 0xC043CCF8, 0xC005C020, 0xC005BE58
OGSAVE = 0xC30754CC                # no longer used by res-custom (§12): asserted untouched
CMT_SET, CMT_QS, SAVE_SITE = 0xC057A6A0, 0xC05824D0, 0xC0088C60
QS_REC, QS_LAY, QS_LOAD = 0xC05E6400, 0xC05D90F0, 0xC05E84D8
RCACHE, RCACHE_V2, RCACHE_V3 = 0xC37B7254, 0xC05663E8, 0xC0566498
NBU_BASE, QS_STOCK_NBR = 0xC18C0460, 0xC0D22400
CINEMADNG, MOV = 0, 1
KEYBUF = T.STACK - 0x8000
STUBS = T.DONE + 0x100             # the layers below the Quick Set sites (Python)
DESC = 0xC3F00000                  # our stand-in for the boot-built descriptor
SYN = 0xC3F10000                   # synthetic tables
HOLDER = 0xC343B67C                # the register-record holder (+0 = 0xC0B5FDA4)
CANVAS_IN = 0xC3E00000             # a canvas holder: canvas at +0x5C
FW = dict(GET_OBJ=0xC0057AE8, GET_FMT=0xC005BE90, CAMSCH1=0xC0207188, CS_GET=0xC0207440,
          CS_SET=0xC02073B8, LV_HOLDER=0xC0423C48, LV_STOP=0xC0423D28, LV_START=0xC0423C88,
          EMIT=0xC01F578C, SENSOR_W=0xC0322C70, GET_RES=0xC005C058, F_SEEK=0xC03661E0,
          V2=RCACHE_V2, V3=RCACHE_V3, QSNEXT=STUBS, LAYNEXT=STUBS + 0x10, LOADNEXT=STUBS + 0x20,
          CROP_GET=0xC005BB98, EXCL_MGR=0xC049EC58, EXCL_RECOMPUTE=0xC049EE78, FR_GET=0xC005C0F0)
POP4567 = 0xE8BD80F0               # pop {r4, r5, r6, r7, pc}: the commit callbacks' bodies, here
POP456 = 0xE8BD8070                # pop {r4, r5, r6, pc}: the setters' bodies, here
PREV_PIDS = (5, 210, 227, 257, 258, 259)
STRID0 = 0x40000100                # the stub's first STRBASE id
GUI_OBJECT = 0xC37B7048            # uishare ui_pool.c: app -> screens -> screen -> reader
VR_RAM = 0xC3F40000                # our stand-in GUI app, reader, entry table, FV table
FV_SITE, FV_VENEER = 0xC05E5BEC, 0xC0780000
VR_CSV_ADDRS = {a for a, _, _ in rcd.VR_CSV}
BIT_CSV_ADDRS = {a for a, _, _ in rcd.BIT_CSV}
_BUILT = {}
# test layers (OG_MULTIFORMAT_CORE_DESIGN.md "測試分層"): the full per-format / per-entry
# equivalence runs and the large damaged-file sweep only with RC_SLOW=1; by default a
# representative set
SLOW = os.environ.get('RC_SLOW') == '1'


def some(seq, n):
    """all of seq with RC_SLOW=1, else its first n"""
    seq = list(seq)
    return seq if SLOW else seq[:n]


def built():
    if 'b' not in _BUILT:
        t = tempfile.mkdtemp(prefix='ogct-')
        out = pathlib.Path(t) / 'o'
        r = subprocess.run([sys.executable, '-B', str(HERE / 'build_v3_rescustom.py'), '--out', str(out)],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr[-4000:])
        meta = json.loads((out / 'build.json').read_text())['files']
        _BUILT['b'] = {n: ((out / n).read_bytes(), m['facts']) for n, m in meta.items()}
    return _BUILT['b']


def h(s):
    return int(s, 16)


def thumb_bw(site, to):
    off = to - (site + 4)
    s, i1, i2 = off >> 31 & 1, (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (1 ^ i1) ^ s, (1 ^ i2) ^ s
    hw1 = 0xF000 | s << 10 | ((off >> 12) & 0x3FF)
    hw2 = 0x9000 | j1 << 13 | j2 << 11 | ((off >> 1) & 0x7FF)
    return hw1 | hw2 << 16


# og3k_plan reads the stock per-mode profile table from a private file that is not in
# every checkout (a worktree has none): those tests are skipped there, not failed.
needs_raw_profiles = unittest.skipUnless(
    (pathlib.Path(__file__).resolve().parents[4] / 'research/other/external/FP3K-technical-handoff-2026-09-10'
     / 'analysis/firmware/raw-profiles.json').exists(), 'needs the private raw-profiles.json')


class Cam(T.Camera):
    def __init__(self, files, dirs, core_facts, fmt=CINEMADNG, res=2, csv_rows=2, uia_fail=(),
                 vr=False, b25_off=0x19C130, fr=1, **kw):
        super().__init__(files, dirs, **kw)
        self.fr = fr
        self.vr_ids, self.lv_ids, self.fv = [], [], []
        self.fv_next = VR_RAM + 0x10000
        if vr:
            self.gui(b25_off)
        self.cf = core_facts
        self.core_block, self.pending, self.uia = None, [], []
        self.fmt, self.res, self.sensor, self.emitted = fmt, res, [], []
        self.seek_ok = True
        self.corrupt_write = False
        self.csv_rows, self.uia_fail, self.next_id = csv_rows, set(uia_fail), STRID0
        self.qs_seen, self.lay_calls, self.load_calls, self.v_calls = [], [], [], []
        self.load_ret = 0
        self.crop = 0                      # Crop Mode as the settings hold it
        self.recomputes = []               # (manager, class list) the exclusion manager was asked
        for n, a in FW.items():
            self.mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
            self.by_addr[a] = n
        for a in (0xC005C024, 0xC005BE5C):
            self.mu.mem_write(a, struct.pack('<I', POP456))
        for a in (CMT_SET + 4, CMT_QS + 4, 0xC057A6FC, 0xC05821BC):
            self.mu.mem_write(a, struct.pack('<I', POP4567))
        self.build_descriptor()

    def gui(self, b25_off):
        """uishare's runtime GUI (ui_pool.c uis_reader): the app, one screen, the NBU
        reader and its file table -- B2_5 the second of three entries (44 bytes each)."""
        app, arr, screen, reader, table, names = (VR_RAM + o for o in
                                                  (0, 0x100, 0x200, 0x300, 0x400, 0x800))
        self.put(GUI_OBJECT, app)
        self.put(app + 0x80, 1)
        self.put(app + 0x8C, arr)
        self.put(arr, screen)
        self.put(screen + 0x24, reader)
        self.put(reader + 0x24, NBU_BASE)
        self.put(reader + 0xA8, 3)
        self.put(reader + 0xAC, table)
        for i, (nm, off) in enumerate(((b'B2_4', 0x180000), (b'B2_5', b25_off), (b'B2_6', 0x1C0000))):
            self.mu.mem_write(names + 16 * i, nm + b'\0')
            self.put(table + 44 * i + 4, names + 16 * i)
            self.put(table + 44 * i + 8, off)
        self.b25_entry = table + 44
        if not self.fv:
            self.fv_next = VR_RAM + 0x10000

    def fv_add(self, stock, copy, size):
        """uishare's file-redirect handler, as it keeps it: a B.W at the site to a
        Thumb veneer, the handler's head (FSHK), its table (FSFV) of {stock, copy, size}"""
        head, table = VR_RAM + 0x1000, VR_RAM + 0x1100
        if not self.fv:
            self.put(FV_VENEER, 0xF000F8DF)
            self.put(FV_VENEER + 4, head + 16)
            self.put(head, 0x4B485346)
            self.put(head + 8, table)
            self.put(FV_SITE, thumb_bw(FV_SITE, FV_VENEER))
        self.fv.append((stock, copy, size))
        self.put(table + 8, len(self.fv))
        i = len(self.fv) - 1
        for k, v in enumerate((stock, copy, size)):
            self.put(table + 16 + 12 * i + 4 * k, v)

    def fake_vr(self, ops, strings, out, frag=b''):
        """the virtual rates' block: each CSV gets a copy with the rows added (the
        FV table), each STRBASE its id"""
        files = []
        for c, a in ops:
            if c == fpui.OP_FILE:
                files.append([a[0], a[1], [], None])
            elif c == fpui.OP_CSV_ADD:
                files[-1][2].append(strings[a[0]][0])
            elif c == fpui.OP_FILE_SET:
                files[-1][3] = frag[a[0]:a[0] + a[1]]
        for addr, size, adds, replacement in files:
            text = self.img[addr - 0xC0000000:addr - 0xC0000000 + size]
            n = text.count(b'\n') - 1
            for i, row in enumerate(adds):
                text += row.replace('{N}', str(n + 1 + i)).encode() + b'\r\n'
            if replacement is not None:
                text = replacement
            copy = self.fv_next
            self.fv_next += (len(text) + 64) & ~63
            self.mu.mem_write(copy, text)
            self.fv_add(addr, copy, len(text))
        for c, a in ops:
            if c == fpui.OP_STRBASE:
                self.put(a[1], self.next_id)
                first = next(args[1] for code, args in ops if code == fpui.OP_STRBASE)
                ids = self.vr_ids if a[1] < first + 4 * L.VR_K else self.lv_ids
                ids.append(self.next_id)
                self.next_id += 1
        self.put(out, 0)
        return self._ret(0)

    def build_descriptor(self):
        img = self.img
        w = lambda a: struct.unpack_from('<I', img, a - 0xC0000000)[0]   # noqa: E731
        self.modes = [w(0xC0B59500 + 0x20 * i) for i in range(70)]
        p = SYN
        tabs = {}
        # The camera's own descriptor, as read on the camera (research/imx410/notes/
        # FRAME_RATE_IS_VMAX.md: +0x00 0xC0B59500, +0x08 0xC0B59DC0, +0x10 0xC0B5B918,
        # +0x24 0xC0B5BB48, +0x40 0xC0B5C638, +0x48 0xC0B5D588); +0xF4 is the next
        # table in the image (0xC0B5DB00, stride 0x68, the same 70 ids in the same
        # order); only the magnifier's +0x128 is synthetic (not located statically).
        for field, stride in ((0x128, 0x5C),):
            tabs[field] = p
            for i, m in enumerate(self.modes):
                row = [m] + [(m << 16) | (field << 4) | k for k in range(1, stride // 4)]
                self.mu.mem_write(p + i * stride, struct.pack(f'<{stride // 4}I', *row))
            p += (70 * stride + 0x100) & ~0xFF
        tabs.update({0x10: 0xC0B5B918, 0x24: 0xC0B5BB48, 0x48: 0xC0B5D588, 0xF4: 0xC0B5DB00})
        desc = {0x00: 0xC0B59500, 0x04: 70, 0x08: 0xC0B59DC0, 0x0C: 70, 0x10: 0xC0B5B918, 0x14: 70,
                0x24: 0xC0B5BB48, 0x28: 70, 0x40: 0xC0B5C638, 0x44: 70, 0x48: 0xC0B5D588, 0x4C: 70,
                0xF4: 0xC0B5DB00, 0xF8: 70, 0x128: tabs[0x128], 0x12C: 70}
        for off, v in desc.items():
            self.put(DESC + off, v)
        self.put(L.IMAGER, DESC)
        self.put(HOLDER, L.REGDESC)
        self.tabs = tabs

    def _alloc(self, n, align=8):
        p = super()._alloc(n, align)
        if n == self.cf['block'] and self.core_block is None:
            self.core_block = p
            uia = p + (self.cf['uia_apply_off'] & ~1)
            self.by_addr[uia] = 'UIA'
            self.pending.append((uia, struct.pack('<H', 0x4770)))      # bx lr (Thumb)
        return p

    def fake_uia(self, mu):
        """uishare's uia_apply, stubbed: the block must decode; the CSV row gets
        the next slot, each STRBASE its id at its address."""
        blk = bytes(mu.mem_read(self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_R1)))
        out = self.r(UC_ARM_REG_R2)
        strings, ops, frag = fpui.decode(blk)
        if any(c == fpui.OP_FILE and a[0] in BIT_CSV_ADDRS for c, a in ops):
            if 'BIT' in self.uia_fail:
                self.put(out, 4)
                return self._ret(4)
            return self.fake_vr(ops, strings, out, frag)
        if any(c == fpui.OP_FILE and a[0] in VR_CSV_ADDRS for c, a in ops):
            self.uia.append(('VR', blk, None))
            if 'VR' in self.uia_fail:
                self.put(out, 4)
                return self._ret(4)
            return self.fake_vr(ops, strings, out, frag)
        csv = next(strings[a[0]][0] for c, a in ops if c == fpui.OP_CSV_ADD)
        sb = [a for c, a in ops if c == fpui.OP_STRBASE]
        label = strings[sb[0][0]][0].rsplit('_', 1)[0]
        self.uia.append((label, blk, csv))
        if label in self.uia_fail:
            self.put(out, 4)
            return self._ret(4)                     # UIA_GUARD
        for c, a in ops:
            if c == fpui.OP_STRBASE:
                self.put(a[1], self.next_id)
                self.next_id += 1
        self.put(out, 0)
        self.put(out + 12, self.csv_rows)
        self.put(out + 44, 1)
        self.csv_rows += 1
        return self._ret(0)

    def _hook(self, mu, addr, size, data):
        name = self.by_addr.get(addr)
        if name == 'DCACHE' and self.pending:
            for at, code in self.pending:
                mu.mem_write(at, code)
            self.pending = []
        if name == 'UIA':
            return self.fake_uia(mu)
        r = lambda x: self.r(x)                                          # noqa: E731
        if name == 'QSNEXT':
            reader = r(UC_ARM_REG_R0)
            at = self.w(reader + 36) + self.w(reader + 4)
            n = struct.unpack('>I', bytes(mu.mem_read(at + 4, 4)))[0]
            self.qs_seen.append(bytes(mu.mem_read(at, n)))
            self.put(reader + 4, self.w(reader + 4) + n)         # the parser moves past it
            return self._ret(0x55)
        if name == 'LAYNEXT':
            self.lay_calls.append(r(UC_ARM_REG_R0))
            return self._ret(0x66)
        if name == 'LOADNEXT':
            self.load_calls.append(tuple(r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1,
                                                        UC_ARM_REG_R2, UC_ARM_REG_R3)))
            return self._ret(self.load_ret if r(UC_ARM_REG_R1) != QS_STOCK_NBR else 0)
        if name in ('V2', 'V3'):
            self.v_calls.append((name, r(UC_ARM_REG_R0), len(self.lay_calls)))
            return self._ret(0)
        if name == 'GET_FMT':
            self.calls.append(name)
            return self._ret(self.fmt)
        if name == 'GET_RES':
            self.calls.append(name)
            return self._ret(self.res)
        if name == 'EXCL_MGR':
            return self._ret(0xC3766AEC)
        if name == 'EXCL_RECOMPUTE':
            lst, a = [], r(UC_ARM_REG_R1)
            while len(lst) < 8:
                lst.append(self.w(a + 4 * len(lst)))
                if lst[-1] == 0xFFFFFFFF:
                    break
            self.recomputes.append((r(UC_ARM_REG_R0), lst))
            self.calls.append(name)
            return self._ret(0)
        if name == 'FR_GET':
            self.calls.append(name)
            return self._ret(self.fr)
        if name == 'CROP_GET':
            self.calls.append(name)
            return self._ret(self.crop)
        if name == 'F_OPEN' and r(UC_ARM_REG_R2) == 7:      # overwrite in place: keep the file
            path = self.cstr(r(UC_ARM_REG_R1))
            self.calls.append(name)
            self.written.setdefault(path, self.files.get(path, b''))
            self.fobj[r(UC_ARM_REG_R0)] = [path, 0]
            return self._ret(1)
        if name == 'F_WRITE' and self.corrupt_write:          # the card took other bytes
            path, pos = self.fobj[r(UC_ARM_REG_R0)]
            data = bytearray(mu.mem_read(r(UC_ARM_REG_R1), r(UC_ARM_REG_R2)))
            data[0x10] ^= 0xFF
            old = self.written[path]
            self.written[path] = old[:pos] + bytes(data) + old[pos + len(data):]
            self.fobj[r(UC_ARM_REG_R0)][1] += len(data)
            return self._ret(1)
        if name == 'F_SEEK':
            self.calls.append(name)
            if not self.seek_ok:
                return self._ret(0)
            self.fobj[r(UC_ARM_REG_R0)][1] = r(UC_ARM_REG_R1)
            return self._ret(1)
        if name == 'F_READ' and self.fobj.get(r(UC_ARM_REG_R0)) and \
                self.fobj[r(UC_ARM_REG_R0)][0] in self.written:
            self.calls.append(name)
            path, pos = self.fobj[r(UC_ARM_REG_R0)]
            n = r(UC_ARM_REG_R2)
            data = self.written[path][pos:pos + n]
            mu.mem_write(r(UC_ARM_REG_R1), data)
            self.fobj[r(UC_ARM_REG_R0)][1] += len(data)
            if r(UC_ARM_REG_R3):
                self.put(r(UC_ARM_REG_R3), len(data))
            return self._ret(len(data))
        if name == 'LV_HOLDER':
            self.calls.append(name)
            return self._ret(0xC3E80000)              # +0 = 0: MovSigProcess not running
        if name == 'SENSOR_W':
            self.calls.append(name)
            self.sensor.append((r(UC_ARM_REG_R0), r(UC_ARM_REG_R1)))
            return self._ret(0)
        if name == 'EMIT':
            self.calls.append(name)
            self.emitted.append(self.cstr(r(UC_ARM_REG_R1)))
            return self._ret(0)
        return super()._hook(mu, addr, size, data)

    def callr(self, pc, **regs):
        """call with any registers (names r0..r12)."""
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, regs.pop('sp', T.STACK - 0x1004))
        mu.reg_write(UC_ARM_REG_LR, T.DONE)
        ids = dict(r0=UC_ARM_REG_R0, r1=UC_ARM_REG_R1, r2=UC_ARM_REG_R2, r3=UC_ARM_REG_R3,
                   r4=UC_ARM_REG_R4, r5=UC_ARM_REG_R5, r6=UC_ARM_REG_R6, fp=UC_ARM_REG_R11,
                   ip=UC_ARM_REG_R12)
        for k, v in regs.items():
            mu.reg_write(ids[k], v & 0xFFFFFFFF)
        try:
            mu.emu_start(pc, T.DONE, count=20_000_000)
        finally:
            if self.error:
                raise self.error
        return {k: self.r(v) for k, v in ids.items()}


def rcd_card(core_name, core, rcds, order=None, extra=()):
    """The card: the loader, the core, \\fpSup\\RESCUS (a directory entry the loader
    skips) and the data files in it (directory order: `order` or as given)."""
    files, dirs = T.card((core_name, core), extra=[('RESCUS', 0x10, 0)])
    if rcds is not None:
        names = order or list(rcds)
        ents = [(n, 0x20, len(rcds[n])) for n in names] + list(extra)
        dirs['\\fpSup\\RESCUS'] = ents
        for n, d in rcds.items():
            files['\\fpSup\\RESCUS\\' + n] = d
    return files, dirs


@unittest.skipIf(T.Uc is None or not T.IMAGE.exists(), 'needs unicorn and the image')
class CoreTests(unittest.TestCase):
    NAME, HL = '32RESCUS.BIN', 32           # the file and its header (test_v4_rescustom: v4's)

    @classmethod
    def setUpClass(cls):
        cls.b = built()
        cls.core, cls.f = cls.b[cls.NAME]
        cls.all_rcds = {n.split('/')[1]: d for n, (d, _) in cls.b.items() if n.startswith('RESCUS/')}
        # the baseline card: OG2K + OG3K (milestones 3/4); the five-format card is all_rcds
        cls.rcds = {n: cls.all_rcds[n] for n in ('OG2K.RCD', 'OG3K.RCD')}
        cls.img = T.IMAGE.read_bytes()
        cls.stock_ids = {struct.unpack_from('<I', cls.img, 0xB59500 + 0x20 * i)[0] for i in range(70)}
        cls.rows = cls.decoded(cls.rcds)                     # as the core sees them: name order
        for r in cls.rows:
            r['target'] = r['label'].lower()

    @classmethod
    def decoded(cls, rcds):
        return [rcd.decode(rcds[n], cls.img, cls.stock_ids) for n in sorted(rcds)]

    def stock(self, a, n=4):
        return self.img[a - 0xC0000000:a - 0xC0000000 + n]

    def sw(self, a):
        return struct.unpack('<I', self.stock(a))[0]

    def record(self, label, stock=2, magic=L.CFG_MAGIC, version=L.CFG_VERSION, bad_sum=False,
               enable=(), vrate=0):
        rec = bytearray(L.CFG['BYTES'])
        struct.pack_into('<3I', rec, 0, magic, version, L.CFG_FLAG_VRATE | vrate << 8 if vrate else 0)
        rec[L.CFG['SEL']:L.CFG['SEL'] + len(label)] = label.encode()
        struct.pack_into('<I', rec, L.CFG['SEL_STOCK'], stock)
        struct.pack_into('<I', rec, L.CFG['NEN'], len(enable))
        for i, e in enumerate(enable):
            rec[L.CFG['EN'] + 8 * i:L.CFG['EN'] + 8 * i + len(e)] = e.encode()
        hsh = 0x811C9DC5
        for b in rec[:L.CFG['SUM']]:
            hsh = ((hsh ^ b) * 0x01000193) & 0xFFFFFFFF
        struct.pack_into('<I', rec, L.CFG['SUM'], hsh ^ (1 if bad_sum else 0))
        return bytes(rec)

    def core_with(self, rec):
        return self.core[:self.HL] + rec + self.core[self.HL + len(rec):]

    def boot(self, rcds='default', fmt=CINEMADNG, res=2, record=None, core_name=None,
             stale=None, order=None, extra=(), **kw):
        core_name = core_name or self.NAME
        core = self.core_with(record) if record else self.core
        rcds = self.rcds if rcds == 'default' else rcds
        cardfiles, dirs = rcd_card(core_name, core, rcds, order, extra)
        st = dict(stale or {})
        st.setdefault(OGSAVE, 0x5A5A5A5A)                 # a canary: res-custom never writes it
        cam = Cam(cardfiles, dirs, self.f, fmt=fmt, res=res, stale=st, **kw)
        cam.boot()
        self.assertEqual(cam.misaligned, [])
        self.assertEqual(cam.w(OGSAVE), 0x5A5A5A5A, 'OGSAVE untouched')
        cam.S = self.s_addr(cam, core_name)
        cam.core_path = '\\fpSup\\' + core_name
        return cam

    def outcome(self, cam, name):
        return {t: c for c, _, _, t in cam.log() if c in ('LOADED', 'RELEASED')}.get(name)

    def s_addr(self, cam, name):
        """S where the core landed: from the picker veneer's target."""
        site = PICKER
        w = cam.w(site)
        if w == self.sw(site):
            return None
        d = w & 0xFFFFFF
        d -= 0x1000000 if d & 0x800000 else 0
        ven = site + 8 + 4 * d
        to = cam.w(ven + 4)
        return to - (L.LAYOUT0 + self.f['shims']['picker']) + L.S_COORD

    def S(self, cam, off):
        return cam.w(cam.S + off)

    def rowa(self, cam, r):
        return cam.S + self.S(cam, L.S['ROWS']) + L.ROW['SIZE'] * r

    def row(self, cam, r, off):
        return cam.w(self.rowa(cam, r) + off)

    def vm(self, cam, v):
        return cam.S + self.S(cam, L.S['VMS']) + L.VM['SIZE'] * v

    def ref(self, rows=None):
        return L.state_blob(rows or self.rows)

    def vid(self, target, donor):
        r = [x['target'] for x in self.rows].index(target)
        for v in self.ref()[1]['vms']:
            if v['row'] == r and v['donor'] == donor:
                return v['id']
        raise KeyError((target, donor))

    def entry_pid(self, r, i, rows=None):
        """The virtual profile entry i of row r names: its own variant's, or the row's."""
        rows = rows or self.rows
        vi, first = len(rows), {}
        for rr, row in enumerate(rows):
            first[rr] = vi
            vi += len(row.get('rate_canvas', []))
        e = rows[r]['entries'][i]
        for k, rc in enumerate(rows[r].get('rate_canvas', [])):
            if rc['rank'] in (0, e['rank']) and rc['crop'] == e['crop']:
                return L.VPID_POOL[first[r] + k]
        return L.VPID_POOL[r]

    def pick(self, cam, key, table=TAB3):
        cam.mu.mem_write(KEYBUF, key.encode().ljust(16, b'\0'))
        r0, _ = cam.call(PICKER, r0=0, r1=table, r2=KEYBUF)
        return r0

    def row_of_enum(self, enum):
        return next(i for i, r in enumerate(self.rows) if r['enum'] == enum)

    def commit(self, cam, mrow, site=CMT_SET):
        """The menu commits row `mrow` (as FUN_c057a6a0 / FUN_c05824d0 see it)."""
        var = KEYBUF + 0x900
        cam.put(var + 8, mrow)
        cam.call(site, r0=var)

    def choose(self, cam, enum, site=CMT_SET):
        """Pick the format with this (legacy) enum, as the menu does: commit its
        row, then the firmware's setter with the stock value the pairs give."""
        r = self.row_of_enum(enum)
        self.commit(cam, self.row(cam, r, L.ROW['MROW']), site)
        cam.call(SETTER, r0=0, r1=self.rows[r]['stock_value'], r2=1)

    def live(self, cam, enum):
        cam.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
        self.choose(cam, enum)

    def site_of(self, name):
        return next(h(x['site']) for x in self.f['hooks'] if self.f['hook_names'][x['site']] == name)

    def hooks_stock(self, cam):
        for hk in self.f['hooks']:
            self.assertEqual(cam.w(h(hk['site'])), self.sw(h(hk['site'])), hk['site'])
        for a in self.f['ui_sites']:
            self.assertEqual(cam.w(h(a)), self.sw(h(a)), a)

    # ---- loading ------------------------------------------------------------
    def test_the_core_loads_and_every_format_is_a_row(self):
        cam = self.boot()
        self.assertEqual(self.outcome(cam, self.NAME), 'LOADED')
        self.assertEqual([lab for lab, _, _ in cam.uia], ['OG2K', 'OG3K'])
        for r in range(len(self.rows)):
            self.assertEqual(self.row(cam, r, L.ROW['ON']), 1)
            self.assertEqual(self.row(cam, r, L.ROW['MROW']), 2 + r)
        self.assertEqual(self.S(cam, L.S['RCD_FOUND']), 2)
        self.assertEqual(self.S(cam, L.S['RCD_OK']), 2)
        self.assertEqual(self.S(cam, L.S['UI_OK']), 3)

    def test_without_data_files_the_core_writes_nothing(self):
        for rcds in (None, {}):
            cam = self.boot(rcds=rcds)
            self.assertEqual(self.outcome(cam, self.NAME), 'RELEASED')
            self.hooks_stock(cam)
            for a in (0xC06BDA3C, 0xC06BDA40, 0xC06BDA48):
                self.assertEqual(cam.w(a), self.sw(a))
            self.assertEqual(cam.uia, [])

    def test_one_data_file_one_row(self):
        cam = self.boot(rcds={'OG3K.RCD': self.rcds['OG3K.RCD']})
        self.assertEqual(self.outcome(cam, self.NAME), 'LOADED')
        self.assertEqual(self.S(cam, L.S['NROWS']), 1)
        self.assertEqual(cam.mu.mem_read(self.rowa(cam, 0) + L.ROW['LABEL'], 5), b'OG3K\0')
        cam.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
        self.commit(cam, 3)                                      # no fourth row on this card
        cam.call(SETTER, r0=0, r1=2, r2=1)
        self.assertEqual((self.S(cam, L.S['FLAG']), self.S(cam, L.S['SEL'])), (0, 0))
        self.assertEqual(self.S(cam, L.S['PAIRN']), 3)

    def test_claims_are_the_hooks_the_menu_sites_the_converter_and_the_donors(self):
        sites = {h(x['site']) for x in self.f['hooks']}
        rest = {h(c['address']) for c in self.f['claims']} - sites
        conv = {0xC06BDA3C, 0xC06BDA48, 0xC06BDB0C, 0xC06BDB18, 0xC06CB6DC, 0xC06CB6E8}
        clock = {0xC0189440}  # v21 default clock claim, introduced before this UI change
        self.assertEqual(rest, {h(a) for a in self.f['ui_sites']} | conv | clock)
        for c in self.f['claims']:
            a = h(c['address'])
            want = 3 if c['address'] in self.f['ui_sites'] else 2 if a in conv | clock else 1
            self.assertEqual(c['kind'], want, c)
        # the donors' timing records (98, 117, 139 +4) are claimed at the entry, from the data
        cam = self.boot()
        got = {a for a, n, _ in cam.journal() if 0xC0B59500 <= a < 0xC0B59500 + 70 * 0x20}
        self.assertEqual(got, {0xC0B59544, 0xC0B59A24, 0xC0B599A4})

    def test_power_off_puts_every_site_back(self):
        cam = self.boot()
        self.live(cam, 4)
        cam.power_off()
        self.hooks_stock(cam)

    # ---- §14: the data files ------------------------------------------------------
    def body(self, cam):
        """S as filled, the run-time words masked (ROW runtime fields, key pointers)."""
        end = self.S(cam, L.S['S_END'])
        b = bytearray(cam.mu.mem_read(cam.S, end))
        rows, ents = self.S(cam, L.S['ROWS']), self.S(cam, L.S['ENTS'])
        for r in range(self.S(cam, L.S['NROWS'])):
            for f in L.RUNTIME_ROW:
                n = 12 if f == 'QSID' else 4
                o = rows + L.ROW['SIZE'] * r + L.ROW[f]
                b[o:o + n] = bytes(n)
        for i in range(self.S(cam, L.S['NENT'])):
            o = ents + L.ENT['SIZE'] * i + L.ENT['KEYPTR']
            b[o:o + 4] = bytes(4)
        return bytes(b)

    def header_words(self, buf):
        keys = ['MAGIC', 'VERSION', 'NROWS', 'ROWS', 'NENT', 'ENTS', 'NVM', 'VMS', 'VPID0',
                'VMID0', 'S_END']
        out = {k: struct.unpack_from('<I', buf, L.S[k])[0] for k in keys}
        out['BASEROW'] = buf[L.S['BASEROW']:L.S['BASEROW'] + 32]
        out['VMDONOR'] = buf[L.S['VMDONOR']:L.S['VMDONOR'] + 64]
        return out

    def assertS(self, cam, rows):
        ref, _ = self.ref(rows)
        got = self.body(cam)
        self.assertEqual(self.header_words(got), self.header_words(ref))
        self.assertEqual(len(got), len(ref))
        for o in range(L.S['BODY'], len(ref), 4):
            self.assertEqual(got[o:o + 4], ref[o:o + 4], f'S+0x{o:X}')

    def variant(self, name, **change):
        """A data file made from a built one, with fields changed (re-encoded)."""
        data = self.rcds[name]
        d = rcd.decode(data, self.img, self.stock_ids)
        off, ln = d['pack']
        d.update(change)
        return rcd.encode(d, data[off:off + ln])

    def test_s_from_the_files_is_the_reference_byte_for_byte(self):
        cam = self.boot()
        self.assertS(cam, self.rows)

    def test_six_formats_with_overrides_fill_s_as_the_reference(self):
        og3k = rcd.decode(self.rcds['OG3K.RCD'])
        rcds = {}
        for i, lab in enumerate(('A1', 'B2', 'C3', 'D4', 'E5', 'F6')):
            base = 'OG3K.RCD' if i % 2 else 'OG2K.RCD'
            ents = rcd.decode(self.rcds[base])['entries']
            ovr = [(ents[0]['donor'], 0, 0x0C, 0x1000 + i), (ents[0]['donor'], 5, 0x10, 0x2000 + i),
                   (ents[0]['donor'], 7, 0, 0x3000 + i), (ents[0]['donor'], 8, 0x1C, 0x4000 + i)]
            rcds[lab + '.RCD'] = self.variant(base, label=lab, overrides=ovr if i < 3 else [],
                                              entries=[dict(e, key=lab + e['key'][4:]) for e in ents])
        del og3k
        cam = self.boot(rcds=rcds, order=list(reversed(list(rcds))))
        self.assertEqual(self.outcome(cam, self.NAME), 'LOADED')
        rows = self.decoded(rcds)
        self.assertEqual(self.S(cam, L.S['NROWS']), 6)
        self.assertS(cam, rows)
        # the overrides land on the cloned rows (and nowhere else)
        cam.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
        self.commit(cam, 2)
        cam.call(SETTER, r0=0, r1=2, r2=1)
        e = self.pick(cam, 'A1' + rows[0]['entries'][0]['key'][2:])
        vid = cam.w(e + 8)
        vm = next(self.vm(cam, v) for v in range(16) if cam.w(self.vm(cam, v)) == vid)
        idx, _ = cam.call(self.site_of('lk_tim'), r0=L.IMAGER, r1=vid)
        tim = (0xC0B59500 + idx * 0x20) & 0xFFFFFFFF
        self.assertEqual(cam.w(tim + 0x0C), 0x1000)
        idx, _ = cam.call(self.site_of('lk_r68'), r0=L.IMAGER, r1=vid)
        self.assertEqual(cam.w((0xC0B5DB00 + idx * 0x68 + 0x10) & 0xFFFFFFFF), 0x2000)
        r10, _ = cam.call(self.site_of('lk_r10'), r0=L.IMAGER, r1=vid)
        self.assertEqual(r10, 0x3000)
        dst = KEYBUF + 0x400
        cam.callr(0xC031AC38, r0=dst, r1=0, r2=vid)
        self.assertEqual(cam.w(dst + 0x1C), 0x4000)
        self.assertEqual(cam.w(vm + L.VM['NOVR']), 4)

    def test_bad_files_are_left_out_and_said_why(self):
        good = self.rcds['OG3K.RCD']
        b = bytearray(good)
        b[200] ^= 1
        nw = self.variant('OG3K.RCD', label='NW')                # a label of its own: not a duplicate
        newer = rcd.reseal(nw[:4] + struct.pack('<I', L.RCD_VERSION + 1) + nw[8:])
        mincore = rcd.reseal(good[:0x2C] + struct.pack('<I', 9) + good[0x30:])
        unknown_req = self.variant('OG3K.RCD', label='UR')
        cases = {
            'BADSUM.RCD': (bytes(b), 'SUM'),
            'NEWER.RCD': (newer, 'VERSION'),
            'MINCORE.RCD': (mincore, 'NEWER'),
            'SHORT.RCD': (good[:40], 'SIZE'),
            'NOTRCD.RCD': (b'X' * 128, 'MAGIC'),
        }
        sys.path.insert(0, str(HERE))
        d = rcd.decode(good)
        pack = good[d['pack'][0]:d['pack'][0] + d['pack'][1]]
        row = dict(d, label='UQ')
        cases['UQ.RCD'] = (rcd.encode(row, pack, extra=[(99, 1, b'\0' * 8)]), 'UNKNOWN')
        cases['UO.RCD'] = (rcd.encode(dict(d, label='UO'), pack, extra=[(99, 0, b'\0' * 8)]), None)
        cases['DUP.RCD'] = (good, 'DUPLICATE')                # OG3K again, sorts first ...
        cases['ZZ.RCD'] = (self.variant('OG3K.RCD', profile=75), 'PROFILE')
        bad_donor = self.variant('OG3K.RCD', label='BD', modes=[(231,) + tuple(m[1:]) for m in d['modes']])
        cases['BD.RCD'] = (bad_donor, 'ENTRY')
        del unknown_req
        for name, (data, want) in cases.items():
            if want and want != 'DUPLICATE':
                with self.assertRaises(rcd.RcdError) as cm:
                    rcd.decode(data, self.img, self.stock_ids)
                self.assertEqual(cm.exception.why, want, name)
        rcds = {n: d for n, (d, _) in cases.items()}
        rcds['OG3K.RCD'] = good
        names = sorted(rcds)
        cam = self.boot(rcds=rcds, extra=[('._OG3K.RCD', 0x20, 4096), ('NOTE.TXT', 0x20, 10),
                                          ('SUB.RCD', 0x10, 0), ('HID.RCD', 0x22, 4)])
        self.assertEqual(self.outcome(cam, self.NAME), 'LOADED')
        self.assertEqual(self.S(cam, L.S['RCD_FOUND']), len(rcds))
        bad = self.S(cam, L.S['RCD_BAD'])
        for i, n in enumerate(names):
            want = cases.get(n, (None, None))[1]
            # DUP.RCD sorts before OG3K.RCD: DUP is the OG3K row, OG3K.RCD the duplicate
            if n == 'DUP.RCD':
                want = None
            if n == 'OG3K.RCD':
                want = 'DUPLICATE'
            self.assertEqual(bool(bad >> i & 1), want is not None, (n, want))
        first = names.index('BADSUM.RCD')
        self.assertEqual(self.S(cam, L.S['RCD_WHY']), first << 16 | L.RCD_WHY['SUM'])
        labels = [bytes(cam.mu.mem_read(self.rowa(cam, r) + L.ROW['LABEL'], 8)).rstrip(b'\0').decode()
                  for r in range(self.S(cam, L.S['NROWS']))]
        self.assertEqual(labels, ['OG3K', 'UO'])

    def test_the_core_and_rcd_decode_agree_on_damaged_files(self):
        """Differential: every field of a data file damaged (and the file sealed
        again), the core's verdict for each against rcd.decode's."""
        good = self.rcds['OG2K.RCD']
        d = rcd.decode(good)
        n = len(good)
        sec = L.RCD_HDR
        cuts = []
        for o in list(range(0, L.RCD_HDR, 4)) + list(range(sec, sec + 16 * 5, 4)):
            for v in (0, 1, 0xFFFFFFFF, 0x41, 0x80):
                cuts.append((o, v))
        ents = struct.unpack_from('<4I', good, sec)[1]
        for o in (ents, ents + 4, ents + 4 + 15, ents + 4 + 16, ents + 4 + 36):
            for v in (0, 0x20, 300):
                cuts.append((o, v))
        canv = struct.unpack_from('<4I', good, sec + 16)[1]
        ui = struct.unpack_from('<4I', good, sec + 32)[1]
        for o in (canv, canv + 12, canv + 20, canv + 32, canv + 36, ui, ui + 4, ui + 31, ui + 32,
                  ui + 47, d['pack'][0]):
            for v in (0, 0x2C, 0x108, 0xFFFF):
                cuts.append((o, v))
        files = []
        for o, v in cuts:
            b = bytearray(good)
            if o + 4 <= n:
                struct.pack_into('<I', b, o, v & 0xFFFFFFFF) if o % 4 == 0 else b.__setitem__(o, v & 0xFF)
            if o not in (L.RCD['SUM'],):
                b = bytearray(rcd.reseal(bytes(b)))
            files.append(bytes(b))
        dn = d['entries'][0]['donor']
        for o in ((dn, 9, 4, 1), (dn, 0, 2, 1), (dn, 0, 0x20, 1), (dn, 7, 4, 1), (dn, 8, 0x5C, 1),
                  (98, 0, 4, 1), (dn, 6, 0x284, 1), (dn, 3, 0x34, 1)):
            files.append(self.variant('OG2K.RCD', label='OV', overrides=[o]))
        # v2: the standby groups and the entries' own canvases (S16's file has both)
        s16 = self.all_rcds['S16.RCD']
        nsec = struct.unpack_from('<I', s16, L.RCD['NSEC'])[0]
        for k in range(nsec):
            typ, off, ln, _ = struct.unpack_from('<4I', s16, sec + 16 * k)
            if typ not in (L.SEC_STANDBY, L.SEC_ENTCANVAS):
                continue
            for o in (off, off + 4, off + 8, off + 12, off + 16, off + 20, off + ln - 8, off + ln - 4):
                for v in (0, 1, 7, 0x10C, 0xD1, 74, 0x300, 40, 0x2000B, 0x3000B):
                    b = bytearray(s16)
                    struct.pack_into('<I', b, o, v)
                    files.append(rcd.reseal(bytes(b)))
            b = bytearray(s16)
            struct.pack_into('<I', b, sec + 16 * k + 8, ln - 4)          # one word short
            files.append(rcd.reseal(bytes(b)))
        files = list(dict.fromkeys(f for f in files if f != good and f != s16))
        if not SLOW:                     # representative: every 6th damage (all kinds stay in)
            files = files[::6]
        for i in range(0, len(files), 15):
            batch = {f'M{j:02d}.RCD': f for j, f in enumerate(files[i:i + 15])}
            want, label = {}, {}
            for name, f in batch.items():
                try:
                    label[name] = rcd.decode(f, self.img, self.stock_ids)['label']
                    want[name] = 0
                except rcd.RcdError as e:
                    want[name] = L.RCD_WHY[e.why]
            cam = self.boot(rcds=batch)
            names = sorted(batch)
            got = {nm: cam.mu.mem_read(cam.S + L.S['RCD_WHYS'] + k, 1)[0] if cam.S else None
                   for k, nm in enumerate(names)}
            if cam.S is None:                                   # every one refused: released
                self.assertTrue(all(want.values()), want)
                continue
            # a good one may be a duplicate of an earlier good one, or past the sixth
            seen = []
            for nm in names:
                w = want[nm]
                if w == 0:
                    if label[nm] in seen:
                        w = L.RCD_WHY['DUPLICATE']
                    else:
                        seen.append(label[nm])
                        if len(seen) > L.MAX_ROWS:
                            w = L.RCD_WHY['EXCESS']
                self.assertEqual(got[nm], w, nm)
            self.checked = getattr(self, 'checked', 0) + len(names)
        self.assertGreater(self.checked, 100 if SLOW else 30)

    def test_more_than_six_formats_the_first_six_by_name(self):
        rcds = {f'F{i}.RCD': self.variant('OG2K.RCD', label=f'F{i}', row_text=f'F{i} 2000x1334')
                for i in range(8)}
        cam = self.boot(rcds=rcds, order=[f'F{i}.RCD' for i in (7, 3, 0, 5, 1, 6, 2, 4)])
        self.assertEqual(self.S(cam, L.S['NROWS']), 6)
        self.assertEqual(self.S(cam, L.S['NAVAIL']), 8)
        labels = [bytes(cam.mu.mem_read(self.rowa(cam, r) + L.ROW['LABEL'], 8)).rstrip(b'\0').decode()
                  for r in range(6)]
        self.assertEqual(labels, [f'F{i}' for i in range(6)])
        self.assertEqual(self.S(cam, L.S['RCD_BAD']), 0, 'left out, not bad')
        self.assertEqual([m for _, _, m in cam.uia][-1], '{N},F5 2000x1334,Popup,,1,2')

    def test_the_enable_list_in_the_bin_chooses(self):
        rcds = dict(self.rcds)
        rcds['S16.RCD'] = self.variant('OG2K.RCD', label='S16')
        cam = self.boot(rcds=rcds, record=self.record('', enable=('S16', 'OG3K')))
        labels = [bytes(cam.mu.mem_read(self.rowa(cam, r) + L.ROW['LABEL'], 8)).rstrip(b'\0').decode()
                  for r in range(self.S(cam, L.S['NROWS']))]
        self.assertEqual(labels, ['OG3K', 'S16'], 'enabled ones, in name order')
        avail = [bytes(cam.mu.mem_read(cam.S + L.S['AVAIL'] + 8 * i, 8)).rstrip(b'\0').decode()
                 for i in range(self.S(cam, L.S['NAVAIL']))]
        self.assertEqual(avail, ['OG2K', 'OG3K', 'S16'])
        # a damaged record: the default (all, up to six)
        cam = self.boot(rcds=rcds, record=self.record('', enable=('S16',), bad_sum=True))
        self.assertEqual(self.S(cam, L.S['NROWS']), 3)

    def test_the_future_sixth_page_sets_the_enable_list(self):
        cam = self.boot()
        fn = self.S(cam, L.S['ENABLE_FN'])
        labels = KEYBUF + 0xC00
        cam.mu.mem_write(labels, b'OG3K\0\0\0\0')
        out = cam.callr(fn | 1, r0=cam.S, r1=1, r2=labels)
        self.assertEqual(out['r0'], 1)
        self.save(cam)
        rec = cam.written[cam.core_path][self.HL:self.HL + L.CFG['BYTES']]
        self.assertEqual(rec, self.record('', stock=0, enable=('OG3K',)))
        cam2 = self.boot(record=rec)
        self.assertEqual(self.S(cam2, L.S['NROWS']), 1)

    # ---- milestone 5: Jose's S16 / OG3.5K / OG4K ----------------------------------------
    def test_jose_literals_are_his_words(self):
        import jose_extract
        import jose_formats as J
        if not jose_extract.available():
            self.skipTest('Jose packages not in the tree')
        for name, row in J.ROWS.items():
            x = jose_extract.extract(name)
            for k in ('label', 'profile', 'aspect', 'prev_h'):
                self.assertEqual(row[k], x[k], (name, k))
            self.assertEqual(list(row['act']), list(x['act']))
            self.assertEqual([tuple(p) for p in row['canvas_rec']], [tuple(p) for p in x['canvas_rec']])
            self.assertEqual([tuple(p) for p in row['canvas_pb']], [tuple(p) for p in x['canvas_pb']])
            self.assertEqual([tuple(o) for o in row['overrides']], [tuple(o) for o in x['overrides']])
            plain = [e for e in row['entries'] if not e['key'].endswith('CROP')]
            for e, h_ in zip(plain, x['entries']):
                self.assertEqual((e['key'], e['donor'], e['w0'], e['w1'], e['nominal']),
                                 (h_['key'], h_['donor'], h_['w0'], h_['w1'], h_['nominal']))
            self.assertEqual(len(plain), J.RATES_KEPT[name])
            self.assertEqual([tuple(p) for p in J.STANDBY.get(name, [])], [tuple(p) for p in x['standby']])
            crop = [e for e in row['entries'] if e['key'].endswith('CROP')]
            self.assertEqual([(e['key'], e['donor'], e['w0'], e['w1']) for e in crop],
                             [(e['key'] + 'CROP', e['donor'], e['w0'], e['w1']) for e in plain] if x['crop'] else [])
            groups = row.get('standby', [])
            if x['crop']:
                self.assertEqual(row['flags'] & L.RFLAG_CROP, L.RFLAG_CROP)
                for ec in row['ent_canvas']:
                    self.assertEqual([tuple(p) for p in ec['pairs']], [tuple(p) for p in x['crop']['canvas']])
                on = [g for g in groups if g[2] == L.SBY_COND['crop_on']]
                self.assertEqual([tuple(p) for p in on[0][1]], [tuple(p) for p in x['crop']['standby']])
            off = [g for g in groups if g[2] != L.SBY_COND['crop_on']]
            self.assertEqual([tuple(p) for g in off for p in g[1]], [tuple(p) for p in x['standby']])
            self.assertEqual(bool(row['flags'] & L.RFLAG_MAG8), x['mag8'])
            if name == 's16':
                self.assertEqual([tuple(p) for p in row['ent_canvas'][0]['pairs']],
                                 [tuple(p) for p in x['hirate_100p']])
                self.assertEqual([tuple(p) for p in x['hirate_100p']], J_S16100)

    @needs_raw_profiles

    def test_jose_formats_declare_the_stock_engine_frame_rate(self):
        """layer 2 (data): every S16 / OG3.5K / OG4K entry's engfps (canvas +0x30, the
        ISP cadence) is what the stock firmware declares on the same picker slot --
        FHD for S16, UHD for OG3.5K / OG4K -- read from the image, not computed"""
        import jose_formats as J
        os.environ.pop('OG_V3', None)
        os.environ.pop('OG_CHAIN', None)
        import og3k_plan as P
        plan = P.Plan()
        slots = {}
        for i in range(26):
            key = self.img[struct.unpack_from('<I', self.img, TAB3 - 0xC0000000 + 16 * i + 12)[0]
                           - 0xC0000000:][:16].split(b'\0')[0].decode()
            slots[key] = i
        for name, row in J.ROWS.items():
            stock = 'FHD' if name == 's16' else 'UHD'
            for e in row['entries']:
                key = stock + e['key'][len(row['label']):]
                self.assertEqual(e['engfps'], plan.engine_fps(slots[key]), (name, e['key'], key))
        # and the built files carry it
        for name in ('S16.RCD', 'OG35K.RCD', 'OG4K.RCD'):
            d = rcd.decode(self.all_rcds[name], self.img, self.stock_ids)
            want = {e['key']: e['engfps'] for r in J.ROWS.values() for e in r['entries']}
            for e in [e for e in d['entries'] if not e['vrate']]:
                self.assertEqual(e['engfps'], want[e['key']], (name, e['key']))
                self.assertNotEqual(e['engfps'], 0)

    def test_five_formats_rows_menu_and_s(self):
        cam = self.boot(rcds=self.all_rcds)
        self.assertEqual(self.outcome(cam, self.NAME), 'LOADED')
        rows = self.decoded(self.all_rcds)
        self.assertEqual([r['label'] for r in rows], ['OG2K', 'OG35K', 'OG3K', 'OG4K', 'S16'])
        self.assertEqual([self.row(cam, r, L.ROW['MROW']) for r in range(5)], [2, 3, 4, 5, 6])
        self.assertEqual([csv for _, _, csv in cam.uia],
                         ['{N},%s,Popup,,1,2' % r['row_text'] for r in rows])
        self.assertS(cam, rows)
        # pairs: UHD, FHD, then each format's stock value (FHD for S16/OG2K/OG3K, UHD for OG3.5K/OG4K)
        self.assertEqual(self.pairs(cam), [(3, 0), (2, 1), (2, 2), (3, 3), (2, 4), (3, 5), (2, 6)])
        self.assertEqual(self.S(cam, L.S['NVM']), 6)

    def test_quick_set_for_five_formats_n7(self):
        img = QS.image()
        cam = self.boot(rcds=self.all_rcds)
        got = self.run_recipe(cam, 7)
        ids = self.qs_ids(cam)
        self.assertEqual(sorted(ids), [2, 3, 4, 5, 6])
        for row in QS.recipe()['records']:
            old = QS.stock(row, img)
            want = rcd.qs_target(row, old, 7, ids)
            self.assertEqual(got[row['address']], old if want is None else want, row['address'])

    def test_uhd_formats_choose_and_go_live_on_the_uhd_value(self):
        cam = self.boot(rcds=self.all_rcds)
        cam.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
        self.commit(cam, 5)                                     # OG4K
        cam.call(SETTER, r0=0, r1=3, r2=1)                      # its value: UHD
        self.assertEqual((self.S(cam, L.S['FLAG']), self.S(cam, L.S['CUR'])), (1, 4))
        self.assertEqual(self.pairs(cam)[0], (3, 5), 'the cursor lands on OG4K')
        self.assertEqual(self.S(cam, L.S['ASPECT']), 2)
        e = self.pick(cam, 'OG4K30')
        self.assertNotEqual(e, 0)
        self.assertEqual(self.pick(cam, 'OG4K60'), 0, 'greyed in his table: no entry -> stock')
        self.assertEqual(self.S(cam, L.S['PICKOK']), 0)
        self.commit(cam, 1)                                     # FHD
        cam.call(SETTER, r0=0, r1=2, r2=1)
        self.assertEqual(self.S(cam, L.S['FLAG']), 0)
        self.commit(cam, 6)                                     # S16, an FHD-valued format
        cam.call(SETTER, r0=0, r1=2, r2=1)
        self.assertEqual((self.S(cam, L.S['FLAG']), self.S(cam, L.S['CUR']), self.S(cam, L.S['ASPECT'])),
                         (1, 5, 0), 'S16 is 16:9: the aspect sites stay stock')
        e = self.pick(cam, 'S16100')
        self.assertNotEqual(e, 0, 'S16 100p: its own virtual profile (the virtual table)')
        self.assertNotEqual(cam.w(e + 4), self.row(cam, 4, L.ROW['PID']))

    # ---- the virtual table, standby ------------------------------------------------------
    def test_entries_with_their_own_canvas_get_their_own_profile(self):
        cam = self.boot(rcds=self.all_rcds)
        rows = self.decoded(self.all_rcds)
        vpro = self.shim_base(cam) + self.f['shims']['vpro']
        for label, key, extra in (('OG3K', 'OG3K100', {0xB0: 1}),
                                  ('S16', 'S16100', dict(J_S16100))):
            r = [x['label'] for x in rows].index(label)
            cam.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
            self.commit(cam, self.row(cam, r, L.ROW['MROW']))
            cam.call(SETTER, r0=0, r1=rows[r]['stock_value'], r2=1)
            e = self.pick(cam, key)
            pid = cam.w(e + 4)
            self.assertIn(pid, L.VPID_POOL[len(rows):], key)
            out = cam.callr(vpro, r5=pid, ip=L.MAPPING, r0=0x1234)
            self.assertEqual(out['r1'], rows[r]['base_row'], 'its base row')
            c = self.canvas(cam, pid)
            want = {off: v for off, v in rows[r]['canvas_rec']}
            want.update(extra)
            for off, v in want.items():
                self.assertEqual(struct.unpack_from('<I', c, off)[0], v, f'{key} +0x{off:X}')
            # a sibling rate: the row's profile, without the extra fields
            sib = next(x['key'] for x in rows[r]['entries'] if x['key'] != key)
            p2 = cam.w(self.pick(cam, sib) + 4)
            self.assertEqual(p2, self.row(cam, r, L.ROW['PID']))
            c2 = self.canvas(cam, p2)
            for off in extra:
                if off not in {o for o, _ in rows[r]['canvas_rec']}:
                    self.assertEqual(struct.unpack_from('<I', c2, off)[0], 0x11111111, f'{sib} +0x{off:X}')
            # not live: nothing
            cam.call(SETTER, r0=0, r1=3 if rows[r]['stock_value'] == 2 else 2, r2=1)
            self.assertEqual(self.canvas(cam, pid), bytes([0x11]) * 0x108)

    def test_standby_framing_while_live(self):
        import jose_formats as J
        cam = self.boot(rcds=self.all_rcds)
        rows = self.decoded(self.all_rcds)
        for label in ('S16', 'OG4K', 'OG35K'):
            r = [x['label'] for x in rows].index(label)
            for pid in (0xD2, 0xD1, 5, 7, 24, 0xD3, 13, 171):
                c = self.canvas(cam, pid)
                self.assertEqual(c, bytes([0x11]) * 0x108, f'not live {label} p{pid}')
            cam.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
            self.commit(cam, self.row(cam, r, L.ROW['MROW']))
            cam.call(SETTER, r0=0, r1=rows[r]['stock_value'], r2=1)
            groups = J.ROWS[label.lower()].get('standby', [])
            for crop in (0, 2):
                cam.crop = crop
                for pid in (0xD2, 0xD1, 0xD5, 5, 7, 24, 0xD3, 13, 171, 210):
                    c = self.canvas(cam, pid)
                    want = {}
                    if rows[r]['aspect'] == 2 and pid in L.PREV_GROUP_PIDS:
                        want[0x28] = rows[r]['prev_h']
                    for pids, pairs, cond in groups:
                        if pid in pids and (cond == 0 or (cond == 2) == bool(crop)):
                            want.update(dict(pairs))
                    for off in range(0, 0x108, 4):
                        self.assertEqual(struct.unpack_from('<I', c, off)[0], want.get(off, 0x11111111),
                                         f'{label} crop{crop} p{pid} +0x{off:X}')
            cam.crop = 0
            if label == 'S16':
                self.assertNotEqual(self.canvas(cam, 0xD1), bytes([0x11]) * 0x108)
            if label == 'OG4K':
                self.assertEqual(self.canvas(cam, 0xD1), bytes([0x11]) * 0x108, 'D1 only for S16')
            cam.call(SETTER, r0=0, r1=3 if rows[r]['stock_value'] == 2 else 2, r2=1)

    # ---- Crop Mode, frame-rate greying, the live-view reload -------------------------------
    def go(self, cam, rows, label):
        r = [x['label'] for x in rows].index(label)
        cam.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
        self.commit(cam, self.row(cam, r, L.ROW['MROW']))
        cam.call(SETTER, r0=0, r1=rows[r]['stock_value'], r2=1)
        return r

    def test_crop_keys_pick_the_crop_entries(self):
        import jose_formats as J
        cam = self.boot(rcds=self.all_rcds)
        rows = self.decoded(self.all_rcds)
        for label in ('OG4K', 'OG35K'):
            r = self.go(cam, rows, label)
            plain = self.pick(cam, label + '23_98')
            crop = self.pick(cam, label + '23_98CROP')
            self.assertNotEqual(plain, 0)
            self.assertNotEqual(crop, 0)
            self.assertNotEqual(plain, crop, 'the full key decides (not its first 8 bytes)')
            self.assertEqual(cam.w(crop + 8), cam.w(plain + 8), 'the same mode')
            self.assertNotEqual(cam.w(crop + 4), cam.w(plain + 4), 'its own profile')
            c = self.canvas(cam, cam.w(crop + 4))
            want = dict(rows[r]['canvas_rec'])
            want.update(dict(J.ROWS[label.lower()]['ent_canvas'][0]['pairs']))
            for off, v in want.items():
                self.assertEqual(struct.unpack_from('<I', c, off)[0], v, f'{label} crop +0x{off:X}')
            self.assertEqual(self.pick(cam, label + '60CROP'), 0)
            self.assertEqual(self.pick(cam, label + '2'), 0, 'a prefix of a key is not the key')
        for label in ('OG3K', 'S16'):
            self.go(cam, rows, label)
            self.assertEqual(self.pick(cam, label + '10'), 0, 'not the 100p entry')
            self.assertEqual(self.pick(cam, label + '30CROP'), self.pick(cam, label + '30'),
                             'no Crop Mode: a CROP key records the plain entry')

    def stub_gates(self, cam):
        put = lambda a, *w: cam.mu.mem_write(a, struct.pack(f'<{len(w)}I', *w))   # noqa: E731
        put(0xC04A1790, 0xE3A00077, 0xE8BD8010)      # mov r0, #0x77; pop {r4, pc}
        put(0xC00A87E8, 0xE1A00001, 0xE12FFF1E)      # mov r0, r1; bx lr
        put(0xC043B6AC, 0xE1A00001, 0xE12FFF1E)      # (movt r1 stays) mov r0, r1; bx lr

    def gates(self, cam):
        frame = KEYBUF + 0x1000
        out = {}
        out['cropst'] = cam.callr(0xC04A1788, r0=0x1234)['r0']
        cam.mu.mem_write(frame, struct.pack('<6I', 4, 5, 6, 7, 8, T.DONE))
        out['cropeff'] = cam.callr(0xC00A93BC, r3=2, sp=frame)['r0']
        out['frmax'] = {v: cam.callr(0xC00A87E4, r4=v)['r0'] for v in (7, 6, 5, 3, 2)}
        cl = {}
        for v in (0, 5, 3, 1, 4, 2):
            cam.mu.mem_write(frame, struct.pack('<4I', 4, 5, 6, T.DONE))
            cl[v] = cam.callr(0xC04A121C, r1=v, sp=frame)['r0']
        out['frclass'] = cl
        out['mag'] = cam.callr(0xC043B6A4)['r0']
        return out

    def test_crop_and_frame_rate_gates(self):
        cam = self.boot(rcds=self.all_rcds)
        self.stub_gates(cam)
        rows = self.decoded(self.all_rcds)
        stock = {'cropst': 0x77, 'cropeff': 2, 'frmax': {7: 7, 6: 6, 5: 5, 3: 3, 2: 2},
                 'frclass': {0: 0, 5: 5, 3: 3, 1: 1, 4: 4, 2: 2}, 'mag': 0xC0BE46F0}
        self.assertEqual(self.gates(cam), stock, 'nothing of ours live: the firmware decides')
        want = {
            'OG3K': dict(cropst=0, cropeff=0, frmax=dict.fromkeys((7, 6, 5, 3, 2), 6),
                         frclass=dict.fromkeys((0, 5, 3, 1, 4, 2), 5), mag=0xC0BE46F0),
            'S16': dict(cropst=0, cropeff=0, frmax=dict.fromkeys((7, 6, 5, 3, 2), 6),
                        frclass=dict.fromkeys((0, 5, 3, 1, 4, 2), 5), mag=0xC0BE46F8),
            'OG4K': dict(cropst=0x77, cropeff=2, frmax=dict.fromkeys((7, 6, 5, 3, 2), 3),
                         frclass=dict.fromkeys((0, 5, 3, 1, 4, 2), 1), mag=0xC0BE46F0),
        }
        for label, w in want.items():
            self.go(cam, rows, label)
            self.assertEqual(self.gates(cam), w, label)
        cam.call(FMTSET, r0=0, r1=MOV, r2=1)                    # MOV: not live, stock again
        self.assertEqual(self.gates(cam), stock)

    def test_the_frame_rate_class_is_recomputed_when_our_row_changes(self):
        """Settings picks its frame-rate list variant from the exclusion manager's
        cached class 0x19, recomputed by the camera only when its own value changes:
        the core asks for it after the setter whenever our live row changed."""
        from unicorn import UC_HOOK_CODE
        cam = self.boot(rcds=self.all_rcds)
        rows = self.decoded(self.all_rcds)
        cam.mu.hook_add(UC_HOOK_CODE, lambda uc, a, n, d: cam.calls.append('SETBODY'),
                        begin=0xC005C024, end=0xC005C024)
        ask = [(0xC3766AEC, [0x19, 0x1E, 0xFFFFFFFF])]
        self.go(cam, rows, 'OG4K')                              # FHD (2) -> OG4K (3)
        self.assertEqual(cam.recomputes, ask)
        self.commit(cam, 0)                                     # OG4K (3) -> UHD (3): same value
        cam.call(SETTER, r0=0, r1=3, r2=1)
        self.assertEqual(cam.recomputes, ask * 2)
        self.commit(cam, 0)                                     # UHD again: nothing changed
        cam.call(SETTER, r0=0, r1=3, r2=1)
        self.assertEqual(cam.recomputes, ask * 2)
        self.go(cam, rows, 'OG3K')
        self.go(cam, rows, 'S16')                               # 2 -> 2
        self.assertEqual(cam.recomputes, ask * 4)
        self.assertEqual(self.S(cam, L.S['EXCL_RECOMPUTES']), 4)
        # after the firmware's setter (its body at C005C024), never before it
        seq = [c for c in cam.calls if c in ('EXCL_RECOMPUTE', 'SETBODY')]
        self.assertEqual(seq.count('EXCL_RECOMPUTE'), 4)
        for i, c in enumerate(seq):
            if c == 'EXCL_RECOMPUTE':
                self.assertEqual(seq[i - 1], 'SETBODY')

    def test_the_live_view_is_reloaded_when_the_value_stays(self):
        cam = self.boot(rcds=self.all_rcds)
        rows = self.decoded(self.all_rcds)
        cam.put(0xC3E80000, 0xC3E80100)                         # MovSigProcess running
        cam.put(0xC3E80104, 1)
        stops = lambda: cam.calls.count('LV_STOP')               # noqa: E731
        self.go(cam, rows, 'OG3K')                              # FHD (2) -> OG3K (2)
        n = stops()
        self.assertGreaterEqual(n, 1)
        self.go(cam, rows, 'S16')                               # OG3K (2) -> S16 (2)
        self.assertEqual(stops(), n + 1)
        self.go(cam, rows, 'S16')                               # the same row again: no
        self.assertEqual(stops(), n + 1)
        self.go(cam, rows, 'OG4K')                              # 2 -> 3: the camera rebuilds itself
        self.assertEqual(stops(), n + 1)
        self.commit(cam, 0)                                     # OG4K (3) -> UHD (3)
        cam.call(SETTER, r0=0, r1=3, r2=1)
        self.assertEqual(stops(), n + 2)
        self.assertEqual(self.S(cam, L.S['LV_RELOADS']), n + 2)

    # ---- §13: the menu -----------------------------------------------------------------
    def test_each_rows_menu_block_is_the_template_with_its_texts(self):
        cam = self.boot()
        tpl = self.core[self.f['tpl_off']:self.f['tpl_off'] + 0x8000]
        tpl = tpl[:struct.unpack_from('<I', tpl, 8)[0]]
        for r, (label, blk, csv) in enumerate(cam.uia):
            row = self.rows[r]
            self.assertEqual(blk, rcd.ui_block(tpl, row, self.rowa(cam, r)), label)
            self.assertEqual(csv, '{N},%s,Popup,,1,2' % row['row_text'])
            strings = [t for t, _ in fpui.decode(blk)[0]]
            self.assertIn(row['summary'], strings)
            for i, sfx in enumerate(('QS', 'SET', 'FONT')):
                self.assertIn(f'{label}_{sfx}', strings)
                self.assertEqual(self.row(cam, r, L.ROW['QSID'] + 4 * i), STRID0 + 3 * r + i)
            self.assertNotIn('@', ''.join(strings))

    def test_a_row_whose_menu_fails_is_off_and_all_failing_releases(self):
        cam = self.boot(uia_fail={'OG2K'})
        self.assertEqual(self.outcome(cam, self.NAME), 'LOADED')
        self.assertEqual([self.row(cam, r, L.ROW['ON']) for r in range(2)], [0, 1])
        self.assertEqual(self.row(cam, 0, L.ROW['UIRES']), 5)
        self.assertEqual(self.pairs(cam), [(3, 0), (2, 1), (2, 2)])
        cam = self.boot(uia_fail={'OG2K', 'OG3K'})
        self.assertEqual(self.outcome(cam, self.NAME), 'RELEASED')
        self.hooks_stock(cam)

    # ---- §13: the Quick Set, scheme B ---------------------------------------------------
    def reader(self, cam, rec, ctx=0xC3E90000):
        rd = KEYBUF + 0xD00
        cam.mu.mem_write(rd, bytes(64))
        cam.put(rd + 4, rec - NBU_BASE)
        cam.put(rd + 8, ctx)
        cam.put(rd + 36, NBU_BASE)
        return rd

    def qs_stubs(self, cam):
        for n, stub in (('qsrec', FW['QSNEXT']), ('qslay', FW['LAYNEXT']), ('qsload', FW['LOADNEXT'])):
            cam.put(cam.S + L.S['NEXT'] + 4 * L.HOOK_INDEX[n], stub)

    def run_recipe(self, cam, n):
        """Every recipe record through C05E6400: what the parser below is given."""
        self.qs_stubs(cam)
        cam.put(cam.S + L.S['QS_N'], n)
        out = {}
        for row in QS.recipe()['records']:
            a = int(row['address'], 16)
            cam.qs_seen = []
            rd = self.reader(cam, a)
            r0, _ = cam.call(QS_REC, r0=rd, thumb=True)
            self.assertEqual(r0, 0x55)
            self.assertEqual(cam.w(rd + 36), NBU_BASE, 'base back')
            self.assertEqual(cam.w(rd + 4), a - NBU_BASE + row['length'], 'past the stock record')
            out[row['address']] = cam.qs_seen[0]
        self.assertEqual(self.S(cam, L.S['QS_DEPTH']), 0)
        return out

    def qs_ids(self, cam):
        return {self.row(cam, r, L.ROW['MROW']): tuple(self.row(cam, r, L.ROW['QSID'] + 4 * i)
                                                        for i in range(3))
                for r in range(self.S(cam, L.S['NROWS'])) if self.row(cam, r, L.ROW['ON'])}

    def test_quick_set_n3_is_the_proven_recipe(self):
        """One format (N = 3): every record exactly as uishare's reference layer
        (ui/qs.py, the FP3K/OG recipe proven on the camera) makes it, its three
        images in the shared slots."""
        cam = self.boot(rcds={'OG3K.RCD': self.rcds['OG3K.RCD']})
        got = self.run_recipe(cam, 3)
        (k, ids), = self.qs_ids(cam).items()
        self.assertEqual(k, 2)
        img = QS.image()
        for row in QS.recipe()['records']:
            want, what = QS.layer(QS.stock(row, img), row, 3, 2, [ids[0], ids[1], ids[2], ids[1]], img)
            self.assertEqual(got[row['address']], want, (row['address'], row['rule'], what))

    def test_quick_set_scheme_b_for_two_and_six_formats(self):
        img = QS.image()
        six = {f'F{i}.RCD': self.variant('OG2K.RCD', label=f'F{i}') for i in range(6)}
        for rcds, n in ((self.rcds, 4), (six, 8)):
            cam = self.boot(rcds=rcds)
            got = self.run_recipe(cam, n)
            ids = self.qs_ids(cam)
            self.assertEqual(sorted(ids), list(range(2, n)))
            for row in QS.recipe()['records']:
                old = QS.stock(row, img)
                want = rcd.qs_target(row, old, n, ids)
                self.assertEqual(got[row['address']], old if want is None else want,
                                 (n, row['address'], row['rule']))
            # each row's state sits at its own time, sorted, with its own image
            clone = next(r for r in QS.recipe()['records'] if r['rule'] == 'clone' and r['marker'] == 0)
            b = got[clone['address']]
            keys = struct.unpack('>I', b[28:32])[0]
            times = [struct.unpack('>I', b[28 + 20 + 10 * i + 2:28 + 20 + 10 * i + 6])[0] for i in range(keys)]
            self.assertEqual(times[-(n - 2):], [100 * k // 3 for k in range(2, n)])

    def test_quick_set_passes_what_is_not_its_own(self):
        cam = self.boot()
        self.qs_stubs(cam)
        cam.put(cam.S + L.S['QS_N'], 4)
        rd = self.reader(cam, 0xC1900000)                      # not a recipe record
        cam.mu.mem_write(0xC1900000, bytes(8))
        cam.call(QS_REC, r0=rd, thumb=True)
        self.assertEqual(cam.w(rd + 36), NBU_BASE)
        rec = QS.recipe()['records'][0]
        rd = self.reader(cam, int(rec['address'], 16))
        other = 0xC3E95000 - (int(rec['address'], 16) - NBU_BASE)
        cam.put(rd + 36, other)                                 # someone else's copy
        cam.mu.mem_write(0xC3E95000, QS.stock(rec))
        cam.qs_seen = []
        cam.call(QS_REC, r0=rd, thumb=True)
        self.assertEqual(self.S(cam, L.S['QS_HITS']), 0)
        cam.put(cam.S + L.S['QS_N'], 0)                         # N read from the list: 2 (stock FV)
        rd = self.reader(cam, int(rec['address'], 16))
        cam.call(QS_REC, r0=rd, thumb=True)
        self.assertEqual(self.S(cam, L.S['QS_READY']), 2, 'N = 2: not a supported row count')

    def test_n_is_the_resolution_lists_rows(self):
        cam = self.boot()
        self.qs_stubs(cam)
        # the file-redirect table as uishare's handler keeps it: a B.W at the site
        # to a veneer, the handler's head (FSHK), its table (FSFV), the CSV's copy
        ven, head, table, csv = 0xC0780000, KEYBUF + 0xE40, KEYBUF + 0xE80, KEYBUF + 0xF00
        text = b'id,name\r\n0,a\r\n1,b\r\n2,c\r\n3,d\r\n'
        cam.mu.mem_write(csv, text + b'9,z\r\n')                # past the copy's length: not a row
        cam.put(ven, 0xF000F8DF)
        cam.put(ven + 4, head + 16)
        cam.put(head, 0x4B485346)
        cam.put(head + 8, table)
        cam.put(table + 8, 1)
        cam.put(table + 16, 0xC0F8E7EC)
        cam.put(table + 20, csv)
        cam.put(table + 24, len(text))
        off = ven - (0xC05E5BEC + 4)
        s, i1, i2 = off >> 31 & 1, (off >> 23) & 1, (off >> 22) & 1
        j1, j2 = (1 ^ i1) ^ s, (1 ^ i2) ^ s
        hw1 = 0xF000 | s << 10 | ((off >> 12) & 0x3FF)
        hw2 = 0x9000 | j1 << 13 | j2 << 11 | ((off >> 1) & 0x7FF)
        cam.put(0xC05E5BEC, hw1 | hw2 << 16)
        cam.put(cam.S + L.S['QS_N'], 0)
        rec = QS.recipe()['records'][0]
        cam.call(QS_REC, r0=self.reader(cam, int(rec['address'], 16)), thumb=True)
        self.assertEqual(self.S(cam, L.S['QS_N']), 4)
        self.assertEqual(self.S(cam, L.S['QS_READY']), 1)

    def test_packs_are_registered_once_per_context_and_a_failed_one_drops_its_row(self):
        cam = self.boot()
        self.qs_stubs(cam)
        cam.callr(QS_LOAD | 1, r0=0xC3E91000, r1=QS_STOCK_NBR, r2=100, r3=0)
        packs = [(self.row(cam, r, L.ROW['PACK']), self.row(cam, r, L.ROW['PACKLEN'])) for r in range(2)]
        self.assertEqual(cam.load_calls, [(0xC3E91000, QS_STOCK_NBR, 100, 0)] +
                         [(0xC3E91000, p, n, 0) for p, n in packs])
        for p, n in packs:
            self.assertEqual(p % 64, 0)
            self.assertEqual(cam.mu.mem_read(p, 4), b'NBR\0')
        cam.callr(QS_LOAD | 1, r0=0xC3E91000, r1=QS_STOCK_NBR, r2=100, r3=0)
        self.assertEqual(len(cam.load_calls), 4, 'once per context')
        cam.load_ret = 7                                        # a new context; the packs fail
        cam.callr(QS_LOAD | 1, r0=0xC3E92000, r1=QS_STOCK_NBR, r2=100, r3=0)
        self.assertEqual([self.row(cam, r, L.ROW['PACKST']) for r in range(2)], [3, 3])
        cam.put(cam.S + L.S['QS_N'], 4)
        rec = next(r for r in QS.recipe()['records'] if r['rule'] == 'qs_max')
        cam.qs_seen = []
        cam.call(QS_REC, r0=self.reader(cam, int(rec['address'], 16), 0xC3E92000), thumb=True)
        self.assertEqual(cam.qs_seen[0], QS.stock(rec), 'no row with a pack: nothing changes')

    def test_the_boot_reparse_happens_once_after_another_layout(self):
        held, tree, ctx = 0xC3E93000, 0xC3E93100, 0xC3E93200
        cam = self.boot(stale={RCACHE + 4: held})
        self.qs_stubs(cam)
        self.assertEqual(self.S(cam, L.S['QS_PRE']), held)
        cam.put(held + 0xC, tree)
        cam.put(held + 4, ctx)
        cam.put(tree + 0xC, 2)                                  # held elsewhere too: not yet
        cam.call(QS_LAY, r0=0xC3E94000, thumb=True)
        self.assertEqual(cam.v_calls, [])
        cam.put(tree + 0xC, 1)
        cam.call(QS_LAY, r0=held, thumb=True)                   # the held one itself: never
        self.assertEqual(cam.v_calls, [])
        cam.call(QS_LAY, r0=0xC3E94000, thumb=True)
        self.assertEqual(cam.v_calls, [('V3', RCACHE, 3), ('V2', RCACHE, 3)],
                         'v3 then v2, on the cache, after the layout below loaded')
        cam.call(QS_LAY, r0=0xC3E94000, thumb=True)
        self.assertEqual(len(cam.v_calls), 2, 'once')
        self.assertEqual(self.S(cam, L.S['QS_RELOADS']), 1)
        cam = self.boot()                                       # nothing cached before us
        self.qs_stubs(cam)
        cam.call(QS_LAY, r0=0xC3E94000, thumb=True)
        self.assertEqual((cam.v_calls, self.S(cam, L.S['QS_BOOT'])), ([], 1))

    # ---- nothing in the firmware's tables is written ------------------------
    def test_no_firmware_table_changes(self):
        cam = self.boot()
        watch = [(0xC0B59500, 70 * 0x20), (0xC0B59DC0, 70 * 100), (0xC0B5C638, 70 * 0x38),
                 (0xC0B5FDAC, 70 * 0x288), (0xC0BD05D4, 500 * 4), (0xC0BDB9C0, 0x400),
                 (0xC074222C, 8)]
        before = [bytes(cam.mu.mem_read(a, n)) for a, n in watch]
        for enum, keys in ((4, ('OG3K24', 'OG3K100')), (7, ('OG2K60',))):
            self.live(cam, enum)
            for k in keys:
                e = self.pick(cam, k)
                self.assertNotEqual(e, 0, k)
                vid = cam.w(e + 8)
                for lk in L.LOOKUPS[:-1]:
                    cam.call(h(next(x['site'] for x in self.f['hooks']
                                    if self.f['hook_names'][x['site']] == lk)), r0=L.IMAGER, r1=vid)
                cam.call(0xC0326DB8, r0=HOLDER, r1=vid)
        cam.call(SETTER, r0=0, r1=3, r2=1)
        after = [bytes(cam.mu.mem_read(a, n)) for a, n in watch]
        for (a, n), x, y in zip(watch, before, after):
            self.assertEqual(x, y, f'0x{a:08X}')
            self.assertEqual(x, self.stock(a, n), f'0x{a:08X} stock')

    # ---- the picker ------------------------------------------------------------
    def test_the_picker_answers_our_keys_with_virtual_ids(self):
        cam = self.boot()
        for r, rf in enumerate(self.rows):
            for i, e in enumerate(rf['entries']):
                for table, bd in ((TAB3, 0), (TAB2, 3), (TAB1, 4)):
                    ent = self.pick(cam, e['key'], table)
                    self.assertNotEqual(ent, 0, e['key'])
                    self.assertEqual(cam.w(ent), 5)
                    self.assertEqual(cam.w(ent + 4), self.entry_pid(r, i))
                    self.assertEqual(cam.w(ent + 8), self.vid(rf['target'], e['donor']))
                    self.assertEqual(cam.w(ent + 0xC), ent + 0x14)
                    self.assertEqual(cam.cstr(ent + 0x14), e['key'])
                    self.assertEqual(self.S(cam, L.S['BITLATCH']), bd)
        stock_entry = self.pick(cam, 'UHD30')          # down to the firmware's own table
        self.assertTrue(0xC0BE5B50 <= stock_entry < 0xC0BE5B50 + 0x1A0, hex(stock_entry))

    def test_a_label_key_without_an_entry_takes_the_display_back(self):
        cam = self.boot()
        self.live(cam, 4)
        self.pick(cam, 'OG3K30')
        self.assertEqual(self.S(cam, L.S['ASPECT']), 2)
        self.assertEqual(self.pick(cam, 'OG3K120'), 0)
        self.assertEqual(self.S(cam, L.S['PICKOK']), 0)
        self.assertEqual(self.S(cam, L.S['ASPECT']), 0, 'MATCH: the display follows the picker')
        self.pick(cam, 'OG3K30')
        self.assertEqual(self.S(cam, L.S['ASPECT']), 2)

    # ---- virtual mode ---------------------------------------------------------------
    def site_of(self, name):
        return next(h(x['site']) for x in self.f['hooks'] if self.f['hook_names'][x['site']] == name)

    def test_lookups_land_on_our_rows_and_stock_ids_go_down(self):
        cam = self.boot()
        self.live(cam, 4)
        for key, donor, nominal in (('OG3K25', 98, 25), ('OG3K100', 117, 100)):
            e = self.pick(cam, key)
            vid = cam.w(e + 8)
            ent = next(x for x in self.rows[self.row_of_enum(4)]['entries'] if x['key'] == key)
            for (name, field, cnt, stride), lk in zip(L.TABLES[:-1], L.LOOKUPS[:-1]):
                idx, _ = cam.call(self.site_of(lk), r0=L.IMAGER, r1=vid)
                base = cam.w(DESC + field)
                row = (base + idx * stride) & 0xFFFFFFFF
                vm = next(self.vm(cam, v) for v in range(4) if cam.w(self.vm(cam, v)) == vid)
                self.assertEqual(row, cam.w(vm + L.VM['PTR'] + 4 * L.TABLES.index((name, field, cnt, stride))), name)
                self.assertEqual(cam.w(row), vid, name)
                # the donor's row, word for word, but for what we change
                drow = None
                for i in range(70):
                    if cam.w(base + i * stride) == donor:
                        drow = base + i * stride
                for k in range(1, stride // 4):
                    got, want = cam.w(row + 4 * k), cam.w(drow + 4 * k)
                    if name == 'TIM' and k in (1, 2):
                        want = (ent['w0'], ent['w1'])[k - 1]
                    if name == 'R38' and 4 * k == 0x04:
                        want |= 0x8
                    if name == 'R38' and 4 * k == 0x18:
                        want |= 0xC000
                    self.assertEqual(got, want, f'{key} {name} +0x{4 * k:X}')
                # a stock id: the firmware's own function, the stock index
                sidx, _ = cam.call(self.site_of(lk), r0=L.IMAGER, r1=98)
                self.assertEqual(cam.w(base + sidx * stride), 98, name)
            # the register record
            idx, _ = cam.call(0xC0326DB8, r0=HOLDER, r1=vid)
            rbase = self.sw(0xC0B5FDA4)
            row = (rbase + idx * 0x288) & 0xFFFFFFFF
            d = rbase + 0x288 * [self.sw(rbase + 0x288 * i) for i in range(70)].index(donor)
            self.assertEqual(cam.w(row), vid)
            self.assertEqual(bytes(cam.mu.mem_read(row + 4, 0x284)), self.stock(d + 4, 0x284))

    def test_the_shutter_angle_sites_get_the_nominal_fps_while_live(self):
        cam = self.boot()
        stub = KEYBUF + 0x700
        cam.mu.mem_write(stub, struct.pack('<2I', 0xE3A0004E, 0xE12FFF1E))    # mov r0, #78; bx lr
        for n in ('fps1', 'fps2', 'fps3', 'fps4'):
            cam.put(cam.S + L.S['NEXT'] + 4 * L.HOOK_INDEX[n], stub)
        self.live(cam, 4)
        # v3: every entry's nominal is its rate's (OG3K100 too -- mode 117's own +0x40 is 100)
        for key, want in (('OG3K25', 25), ('OG3K60', 60), ('OG3K100', 100), ('OG3K23_98', 24)):
            vid = cam.w(self.pick(cam, key) + 8)
            for n in ('fps1', 'fps2', 'fps3', 'fps4'):
                out = cam.callr(self.shim_base(cam) + self.f['shims'][n], r0=vid)
                self.assertEqual(out['r0'], want, f'{key} {n}')
            out = cam.callr(self.shim_base(cam) + self.f['shims']['fps1'], r0=98)
            self.assertEqual(out['r0'], 78, 'a stock mode: the getter')
        cam.call(SETTER, r0=0, r1=3, r2=1)
        out = cam.callr(self.shim_base(cam) + self.f['shims']['fps1'], r0=vid)
        self.assertEqual(out['r0'], 78, 'not live: the getter')

    def test_the_timing_follows_every_pick(self):
        cam = self.boot()
        self.live(cam, 4)
        e = self.pick(cam, 'OG3K24')
        vid = cam.w(e + 8)
        idx, _ = cam.call(self.site_of('lk_tim'), r0=L.IMAGER, r1=vid)
        row = (0xC0B59500 + idx * 0x20) & 0xFFFFFFFF
        for key in ('OG3K23_98', 'OG3K50', 'OG3K60'):
            self.pick(cam, key)
            ent = next(x for x in self.rows[self.row_of_enum(4)]['entries'] if x['key'] == key)
            self.assertEqual((cam.w(row + 4), cam.w(row + 8)), (ent['w0'], ent['w1']), key)

    # ---- the transaction, the MOV guard ------------------------------------------
    def test_the_setters_publish_and_take_down(self):
        cam = self.boot()
        og3k, og2k = self.row_of_enum(4) + 1, self.row_of_enum(7) + 1
        cam.put(cam.S + L.S['FMTLATCH'], 0xFFFFFFFF)            # as before the restore ran
        self.choose(cam, 4)                                    # OG3K, format unknown: not live
        self.assertEqual((self.S(cam, L.S['FLAG']), self.S(cam, L.S['SEL'])), (0, og3k))
        cam.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
        self.assertEqual((self.S(cam, L.S['FLAG']), self.S(cam, L.S['CUR'])), (1, og3k))
        self.assertEqual(self.S(cam, L.S['ASPECT']), 2)
        cam.call(FMTSET, r0=0, r1=MOV, r2=1)                  # MOV: down (the freeze)
        self.assertEqual((self.S(cam, L.S['FLAG']), self.S(cam, L.S['ASPECT'])), (0, 0))
        cam.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
        self.assertEqual(self.S(cam, L.S['FLAG']), 1)
        self.choose(cam, 7, CMT_QS)                           # OG2K, from Quick Set
        self.assertEqual((self.S(cam, L.S['CUR']), self.S(cam, L.S['SEL'])), (og2k, og2k))
        # the stock FHD row: the same value 2 as OG3K/OG2K -- only the commit tells
        self.commit(cam, 1)
        cam.call(SETTER, r0=0, r1=2, r2=1)
        self.assertEqual((self.S(cam, L.S['FLAG']), self.S(cam, L.S['CUR']), self.S(cam, L.S['SEL'])),
                         (0, 0, 0))
        self.choose(cam, 4)
        self.assertEqual(self.S(cam, L.S['FLAG']), 1)
        cam.call(SETTER, r0=0, r1=3, r2=1)                    # the setting moved (UHD) by any path
        self.assertEqual((self.S(cam, L.S['FLAG']), self.S(cam, L.S['SEL'])), (0, 0))

    def pairs(self, cam):
        n = self.S(cam, L.S['PAIRN'])
        return [(cam.w(cam.S + L.S['PAIRS'] + 8 * i), cam.w(cam.S + L.S['PAIRS'] + 8 * i + 4))
                for i in range(n)]

    def test_the_converter_reads_our_pairs_the_chosen_row_first(self):
        cam = self.boot()
        # MenuValueConverterBase::v21 itself, patched: (table, count)
        out = cam.callr(0xC06BDA30, r0=0, r1=KEYBUF + 0xA00)
        self.assertEqual((cam.w(KEYBUF + 0xA00), out['r0']), (cam.S + L.S['PAIRS'], 4))
        self.assertEqual(self.pairs(cam), [(3, 0), (2, 1), (2, 2), (2, 3)])
        self.commit(cam, 3)                                     # OG2K
        self.assertEqual(self.pairs(cam), [(2, 3), (3, 0), (2, 1), (2, 2)])
        self.assertEqual(self.S(cam, L.S['DIRTY']), 1)
        self.commit(cam, 0)                                     # UHD
        self.assertEqual(self.pairs(cam), [(3, 0), (2, 1), (2, 2), (2, 3)])
        cam.power_off()
        for a in (0xC06BDA3C, 0xC06BDA40, 0xC06BDA48):
            self.assertEqual(cam.w(a), self.sw(a), hex(a))

    def test_the_gain_site_and_the_aspect_sites(self):
        cam = self.boot()
        self.live(cam, 4)
        self.pick(cam, 'OG3K30')
        r0, _ = cam.call(0xC03A6DD8, r0=0x77)
        self.assertEqual(r0, 1, 'raw movie while live')
        for site, back in ((0xC0306EA0, 0xC0306EA4), (0xC0306EEC, 0xC0306EF0)):
            cam.mu.mem_write(back, struct.pack('<I', 0xE12FFF1E))
            r0, _ = cam.call(site, r0=0x99)
            self.assertEqual(r0, 2, hex(site))
        cam.call(SETTER, r0=0, r1=3, r2=1)
        self.assertEqual(self.S(cam, L.S['ASPECT']), 0)
        for site in (0xC0306EA0, 0xC0306EEC):
            r0, _ = cam.call(site, r0=0x99)
            self.assertEqual(r0, 3, 'stock 16:9 replayed')

    # ---- the canvas -------------------------------------------------------------
    def canvas(self, cam, pid, pattern=0x11):
        cam.mu.mem_write(CANVAS_IN, bytes([pattern]) * 0x200)
        out = cam.callr(L.LAYOUT0 + self.f['shims']['canvas'] - L.LAYOUT0 + self.shim_base(cam),
                        r4=CANVAS_IN, r5=pid)
        self.assertEqual(out['r0'], CANVAS_IN, 'mov r0, r4 replayed')
        return bytes(cam.mu.mem_read(CANVAS_IN + 0x5C, 0x108))

    def shim_base(self, cam):
        return cam.S - L.S_COORD + L.LAYOUT0

    def test_the_canvas_declares_our_profile(self):
        cam = self.boot()
        for r, rf in enumerate(self.rows):
            self.live(cam, rf['enum'])
            for table, bd, planes in ((TAB3, 0, (7, 7)), (TAB2, 3, (10, 9)), (TAB1, 4, (10, 10))):
                e = self.pick(cam, rf['entries'][3]['key'], table)
                c = self.canvas(cam, L.VPID0 + r)
                want = {off: v for off, v in rf['canvas_rec']}
                want[0x30] = rf['entries'][3]['engfps']
                want[0x80], want[0x84] = planes
                for off in range(0, 0x108, 4):
                    got = struct.unpack_from('<I', c, off)[0]
                    self.assertEqual(got, want.get(off, 0x11111111), f'{rf["label"]} bd{bd} +0x{off:X}')
                del e

    def test_preview_heights_only_while_live(self):
        cam = self.boot()
        for pid in PREV_PIDS:
            c = self.canvas(cam, pid)
            self.assertEqual(struct.unpack_from('<I', c, 0x28)[0], 0x11111111)
        self.live(cam, 4)
        for pid in PREV_PIDS:
            c = self.canvas(cam, pid)
            self.assertEqual(struct.unpack_from('<I', c, 0x28)[0], 1334)
            self.assertEqual(c[:0x28] + c[0x2C:], bytes([0x11]) * (0x108 - 4))
        c = self.canvas(cam, 83)
        self.assertEqual(c, bytes([0x11]) * 0x108, 'p83 (stills) is never touched')

    def test_playback_of_our_clip(self):
        cam = self.boot()
        sizes = KEYBUF + 0x100
        for r, rf in enumerate(self.rows):
            cam.put(sizes + 8, rf['act'][0])
            cam.put(sizes + 0xC, rf['act'][1])
            cam.call(0xC0437B48, r0=0, r1=KEYBUF + 0x200, r2=sizes)
            self.assertEqual(cam.emitted[-1], rf['label'])
            cam.mu.mem_write(CANVAS_IN, bytes([0x11]) * 0x200)
            cam.put(CANVAS_IN + 0x5C + 0x80, 0x10007)
            cam.callr(self.shim_base(cam) + self.f['shims']['canvas'], r4=CANVAS_IN, r5=51)
            c = bytes(cam.mu.mem_read(CANVAS_IN + 0x5C, 0x108))
            for off, v in rf['canvas_pb']:
                self.assertEqual(struct.unpack_from('<I', c, off)[0], v, f'{rf["label"]} +0x{off:X}')

    # ---- the virtual profile at C043A18C -------------------------------------------
    def test_the_gather_gets_a_base_row_for_a_virtual_profile(self):
        cam = self.boot()
        vpro = self.shim_base(cam) + self.f['shims']['vpro']
        for r, rf in enumerate(self.rows):
            out = cam.callr(vpro, r5=L.VPID0 + r, ip=L.MAPPING, r0=0x1234)
            self.assertEqual((out['r1'], out['r0'], out['ip']), (rf['base_row'], 0x1234, L.MAPPING))
        out = cam.callr(vpro, r5=83, ip=L.MAPPING, r0=0x1234)
        self.assertEqual(out['r1'], self.sw(L.MAPPING + 83 * 4))
        out = cam.callr(vpro, r5=L.VPID0 + 7, ip=L.MAPPING)
        self.assertEqual(out['r1'], self.sw(L.MAPPING + (L.VPID0 + 7) * 4))

    # ---- the magnifier ------------------------------------------------------------
    def test_the_magnifier_rows(self):
        cam = self.boot()
        self.live(cam, 4)
        e = self.pick(cam, 'OG3K30')
        vid = cam.w(e + 8)
        zbase = cam.tabs[0x128]
        drow = zbase + 0x5C * cam.modes.index(98)
        dst = KEYBUF + 0x400
        cam.callr(0xC031AC38, r0=dst, r1=0, r2=vid)
        got = bytes(cam.mu.mem_read(dst, 0x5C))
        want = struct.pack('<I', vid) + bytes(cam.mu.mem_read(drow + 4, 0x58))
        self.assertEqual(got, want)
        # v32 with the imager on our mode: the donor row's arithmetic, ours
        cam.put(L.IMAGER + 4, vid)
        cam.sensor = []
        cam.callr(0xC03249A0, r0=L.IMAGER, r1=1)
        a = cam.w(drow + 0x1C) + cam.w(drow + 0x38 + 4)
        b = cam.w(drow + 0x44 + 4) >> 1
        self.assertEqual(cam.sensor, [(3, 1), (0x22, a & 0xFF), (0x23, (a & 0xFFFF) >> 8),
                                      (0x24, b & 0xFF), (0x25, (b & 0xFFFF) >> 8)])
        # the getter call site in FUN_c031b3a0 and FUN_c031acd8 see the donor
        zg = self.shim_base(cam) + self.f['shims']['zg']
        out = cam.callr(zg, r0=L.IMAGER)
        self.assertEqual(out['r0'], 98)
        stub = KEYBUF + 0x600
        cam.mu.mem_write(stub, struct.pack('<2I', 0xE1A00003, 0xE12FFF1E))    # mov r0, r3; bx lr
        nx = cam.S + L.S['NEXT'] + 4 * L.HOOK_INDEX['acd8']
        keep = cam.w(nx)
        cam.put(nx, stub)
        out = cam.callr(self.shim_base(cam) + self.f['shims']['acd8'], r3=vid)
        self.assertEqual(out['r0'], 98)
        out = cam.callr(self.shim_base(cam) + self.f['shims']['acd8'], r3=139)
        self.assertEqual(out['r0'], 139)
        cam.put(nx, keep)

    # ---- the boot restore ------------------------------------------------------------
    def test_restore_brings_the_saved_format_back(self):
        cam = self.boot(record=self.record('OG2K'))
        r = self.row_of_enum(7)
        self.assertEqual((self.S(cam, L.S['FLAG']), self.S(cam, L.S['CUR']), self.S(cam, L.S['SEL'])),
                         (1, r + 1, r + 1))
        self.assertEqual(self.S(cam, L.S['RLOG'] + 0xC), 1)
        self.assertEqual(self.S(cam, L.S['DIRTY']), 0, 'the record already says it')
        self.assertEqual(self.pairs(cam)[0], (2, 2 + r), 'the cursor lands on OG2K')
        self.assertNotIn('SETTER', cam.calls)
        for kw, code in ((dict(record=self.record('OG2K'), res=3), 7),         # setting moved: no
                         (dict(record=self.record('OG2K'), fmt=MOV), 3),
                         (dict(record=self.record('S16')), 2),                  # not on this card
                         (dict(record=self.record('OG2K', bad_sum=True)), 2),
                         (dict(record=self.record('OG2K', version=9)), 2),
                         (dict(), 2)):
            cam = self.boot(**kw)
            self.assertEqual((self.S(cam, L.S['FLAG']), self.S(cam, L.S['SEL'])), (0, 0), kw)
            self.assertEqual(self.S(cam, L.S['RLOG'] + 0xC), code, kw)

    # ---- the BIN record (§12.4) --------------------------------------------------------
    def save(self, cam):
        stub = KEYBUF + 0xB00
        cam.mu.mem_write(stub, struct.pack('<2I', 0xE3A00077, 0xE12FFF1E))    # mov r0, #0x77
        cam.put(cam.S + L.S['NEXT'] + 4 * L.HOOK_INDEX['save'], stub)
        out = cam.callr(self.shim_base(cam) + self.f['shims']['save'])
        self.assertEqual(out['r0'], 0x77, "the firmware's save's result passes through")

    def test_the_choice_is_written_to_our_own_file(self):
        cam = self.boot()
        self.save(cam)
        self.assertNotIn(cam.core_path, cam.written, 'nothing owed: nothing written')
        self.live(cam, 4)
        self.save(cam)
        f = cam.written[cam.core_path]
        self.assertEqual(f[self.HL:self.HL + L.CFG['BYTES']], self.record('OG3K'))
        self.assertEqual(f[:self.HL] + f[self.HL + L.CFG['BYTES']:],
                         self.core[:self.HL] + self.core[self.HL + L.CFG['BYTES']:])
        self.assertEqual((self.S(cam, L.S['DIRTY']), self.S(cam, L.S['SAVES'])), (0, 1))
        self.save(cam)
        self.assertEqual(self.S(cam, L.S['SAVES']), 1, 'unchanged: not written again')
        self.commit(cam, 1)                                     # FHD: the record is cleared
        cam.seek_ok = False
        self.save(cam)
        self.assertEqual((self.S(cam, L.S['DIRTY']), self.S(cam, L.S['SAVE_FAILS'])), (1, 1))
        self.assertEqual(cam.written[cam.core_path][self.HL:self.HL + L.CFG['BYTES']], self.record('OG3K'))
        cam.seek_ok = True
        cam.corrupt_write = True                                # written, but reads back wrong
        self.save(cam)
        self.assertEqual((self.S(cam, L.S['DIRTY']), self.S(cam, L.S['SAVE_FAILS'])), (1, 2))
        cam.corrupt_write = False
        cam.put(0xC35A952C, 1)                                  # MOV writing: not now
        self.save(cam)
        self.assertEqual(self.S(cam, L.S['DIRTY']), 1)
        cam.put(0xC35A952C, 0)
        self.save(cam)
        self.assertEqual(cam.written[cam.core_path][self.HL:self.HL + L.CFG['BYTES']], self.record('', 0))
        # and the next boot reads it back
        cam2 = self.boot(record=self.record('OG3K'))
        self.assertEqual(self.S(cam2, L.S['SEL']), self.row_of_enum(4) + 1)

    def test_the_bin_write_never_creates_or_overwrites_a_stranger(self):
        """2026-10-08: the card's 32RESCUS.BIN was renamed while the core ran; at
        power-off the write (mode 7) created a 128-byte stub under the old name.
        Now the file must still be this sup (its 32-byte header) before anything
        is written; otherwise nothing, and the record stays owed."""
        cam = self.boot()
        self.live(cam, 4)
        del cam.files[cam.core_path]                            # renamed / deleted
        self.save(cam)
        self.assertNotIn(cam.core_path, cam.written, 'no file is created')
        self.assertEqual((self.S(cam, L.S['DIRTY']), self.S(cam, L.S['SAVE_WHY'])), (1, 1))
        other = bytearray(self.core)
        other[20:24] = b'XXXX'                                  # another sup's header
        cam.files[cam.core_path] = bytes(other)
        self.save(cam)
        self.assertNotIn(cam.core_path, cam.written, 'a different file is not written')
        self.assertEqual(self.S(cam, L.S['SAVE_WHY']), 2)
        cam.files[cam.core_path] = self.core[:20]               # truncated
        self.save(cam)
        self.assertNotIn(cam.core_path, cam.written)
        self.assertEqual(self.S(cam, L.S['SAVE_WHY']), 2)
        cam.files[cam.core_path] = self.core                    # back: written
        self.save(cam)
        self.assertEqual(cam.written[cam.core_path][self.HL:self.HL + L.CFG['BYTES']], self.record('OG3K'))
        self.assertEqual((self.S(cam, L.S['DIRTY']), self.S(cam, L.S['SAVE_WHY'])), (0, 0))

    def test_the_template_leaves_the_frame_rate_list_variants_alone(self):
        """2026-10-08: uishare's RES_EXCL pointed B2_5_5's six variants all at the
        open one, so FHD/UHD lost their Settings frame-rate greying."""
        tpl = self.core[self.f['tpl_off']:self.f['tpl_off'] + 0x8000]
        tpl = tpl[:struct.unpack_from('<I', tpl, 8)[0]]
        _, ops, _ = fpui.decode(tpl)
        from ui import options as O
        a, _, _ = O.resource_set('B2_5')
        base, offs, _ = O.RES_EXCL
        bad = {base + o - a for o in offs}
        for code, args in ops:
            if code in (fpui.OP_ADD32, fpui.OP_ADDF, fpui.OP_GUARD):
                self.assertNotIn(args[0], bad, (code, args))

    def test_first_rule_no_settings_word_is_ever_written(self):
        """§12.7: res-custom writes nothing into the settings (XC_UserSetting,
        XC_CommonSaveData), calls no setter of its own, claims nothing there."""
        from unicorn import UC_HOOK_MEM_WRITE
        for c in self.f['claims']:
            a = h(c['address'])
            self.assertFalse(0xC3074BE8 <= a < 0xC3075650, c)
        cam = self.boot(record=self.record('OG3K'))
        hits = []
        lo, hi = cam.S - 0x20000, cam.S + 0x40000

        def write(uc, access, addr, size, value, data):
            if 0xC3074BE8 <= addr < 0xC3075650:
                hits.append((hex(addr), value, hex(uc.reg_read(UC_ARM_REG_PC))))
        cam.mu.hook_add(UC_HOOK_MEM_WRITE, write)
        self.live(cam, 4)
        self.choose(cam, 7, CMT_QS)
        cam.call(FMTSET, r0=0, r1=MOV, r2=1)
        self.commit(cam, 1)
        cam.call(SETTER, r0=0, r1=2, r2=1)
        self.save(cam)
        cam.power_off()
        self.assertEqual(hits, [])
        del lo, hi

    # ---- equivalence with today's OpenGate (30OG3K / 30OG2K) ------------------------
    # ---- v3 timing (2026-10-08): the core solves it; today's words are the reference
    def ent_by_key(self, cam, key, vrate=0):
        for i in range(self.S(cam, L.S['NENT'])):
            e = cam.S + self.S(cam, L.S['ENTS']) + L.ENT['SIZE'] * i
            k = bytes(cam.mu.mem_read(e + L.ENT['KEY'], 16)).split(b'\0')[0].decode()
            if k == key and cam.w(e + L.ENT['VRATE']) == vrate:
                return e
        raise KeyError(key)

    def force_timing(self, cam, key, w0, w1):
        """today's timing words into our entry, so everything else can be compared exactly"""
        e = self.ent_by_key(cam, key)
        cam.put(e + L.ENT['W0'], w0)
        cam.put(e + L.ENT['W1'], w1)

    def modes_index(self, mode):
        return [struct.unpack_from('<I', self.img, 0xB59500 + 0x20 * i)[0] for i in range(70)].index(mode)

    @staticmethod
    def cycles_of(key, label):
        suf = key[len(label):].replace('CROP', '')
        return next(r[3] for r in L.RATES if r[1] == suf)

    def assertTiming(self, old, new, cyc, what):
        """same hmax and x as today; the solver's vmax/tail: the real period hmax x vmax
        within hmax / 2 of the rate's (hmax when the tail floor moved it), the
        firmware's own count exact -- and never further off than today's"""
        hm, tail, vm, x = new[0] & 0xFFFF, new[0] >> 16, new[1] & 0xFFFF, new[1] >> 16
        self.assertEqual((hm, x), (old[0] & 0xFFFF, old[1] >> 16), what)
        self.assertEqual(hm * (vm - 1) + tail, cyc, what)
        self.assertEqual((vm, tail), L.solve(hm, cyc), what)
        self.assertGreaterEqual(tail, L.MIN_TAIL, what)
        bound = hm if tail - hm < L.MIN_TAIL else hm // 2 + 1
        self.assertLessEqual(abs(hm * vm - cyc), bound, what)
        self.assertLessEqual(abs(hm * vm - cyc), abs(hm * (old[1] & 0xFFFF) - cyc), what + ' worse than today')

    @needs_raw_profiles

    def test_same_timing_and_canvas_as_todays_opengate(self):
        sys.path.insert(0, str(BUILD))
        import test_v3_og as O
        for r, rf in enumerate(self.rows):
            old_bin, old_f, old_name = O.built(rf['target'])
            files, dirs = T.card((old_name, old_bin))
            old = O.OGCamera(files, dirs, {old_f['block']: old_f})
            old.boot()
            old.put(old.at(old_f, old_f['fmtlatch']), 0)
            old.call(SETTER, r0=0, r1=rf['enum'], r2=1)
            new = self.boot()
            self.live(new, rf['enum'])
            for e in some(rf['entries'], 1) + [x for x in rf['entries'] if x['key'].endswith('100')]:
                for table in some((TAB3, TAB2, TAB1), 1):
                    old.mu.mem_write(KEYBUF, e['key'].encode().ljust(16, b'\0'))
                    oe, _ = old.call(PICKER, r0=0, r1=table, r2=KEYBUF)
                    ne = self.pick(new, e['key'], table)
                    donor_rec = old.w(oe + 0x10)
                    self.assertTiming((old.w(donor_rec + 4), old.w(donor_rec + 8)),
                                      (new.w(ne + 0x24), new.w(ne + 0x28)),
                                      self.cycles_of(e['key'], rf['label']), e['key'])
                    self.assertEqual(old.w(oe + 0x2C), new.w(ne + 0x2C), 'engine fps')
                    old.mu.mem_write(CANVAS_IN, bytes([0x11]) * 0x200)
                    old.mu.reg_write(UC_ARM_REG_R4, CANVAS_IN)
                    old.mu.reg_write(UC_ARM_REG_R5, rf_profile(rf))
                    oc = run_old_canvas(old, old_f)
                    nc = self.canvas(new, new.w(ne + 4))
                    if e['key'] in ('OG3K100', 'OG2K100'):   # the intended difference (user 2026-10-07)
                        oc = bytearray(oc)
                        struct.pack_into('<I', oc, 0xB0, 1)
                        oc = bytes(oc)
                    self.assertEqual(oc, nc, f'{e["key"]} {table:#x}')

    # ---- the virtual frame rates (design §15: K = 4, core-defined) --------------------
    RANKS = [r for r, _, _ in L.VRATES]

    def vr_rcds(self):
        """OG3K as built (23.98..100, 17.98) and HS: OG2K's data on mode 12 (2016x672,
        hmax 330, 302 fps) -- every stock rate, 239.76, 279.72, 17.98"""
        return {'OG3K.RCD': self.rcds['OG3K.RCD'],
                'HS.RCD': self.variant('OG2K.RCD', label='HS', enum=10, modes=[(12, 30219, 330, 0, 6)])}

    def vr_boot(self, **kw):
        cam = self.boot(rcds=self.vr_rcds(), vr=True, **kw)
        cam.vr_rows = self.decoded(self.vr_rcds())
        return cam

    def vr_live(self, cam, enum):
        cam.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
        r = next(i for i, x in enumerate(cam.vr_rows) if x['enum'] == enum)
        self.commit(cam, self.row(cam, r, L.ROW['MROW']))
        cam.call(SETTER, r0=0, r1=cam.vr_rows[r]['stock_value'], r2=1)

    def rcommit(self, cam, mrow, name='rcmt2'):
        var = KEYBUF + 0x900
        cam.put(var + 8, mrow)
        cam.call(self.site_of(name), r0=var)

    def rpairs(self, cam):
        n = self.S(cam, L.S['RPAIRN'])
        return [(cam.w(cam.S + L.S['RPAIRS'] + 8 * i), cam.w(cam.S + L.S['RPAIRS'] + 8 * i + 4))
                for i in range(n)]

    def spairs(self, cam):
        n = self.S(cam, L.S['SPAIRN'])
        return [(cam.w(cam.S + L.S['SPAIRS'] + 8 * i), cam.w(cam.S + L.S['SPAIRS'] + 8 * i + 4))
                for i in range(n)]

    def stock_pairs(self, a, n):
        return [struct.unpack_from('<2I', self.img, a - 0xC0000000 + 8 * i) for i in range(n)]

    def csv_ab(self, cam):
        """each copy's last 9 + K rows' "a,b", as the menu reads them"""
        out = []
        for stock, copy, size in cam.fv:
            if stock not in VR_CSV_ADDRS:
                continue
            lines = bytes(cam.mu.mem_read(copy, size)).decode('latin1').split('\r\n')
            out.append([ln.rsplit(',', 2)[-2] + ',' + ln.rsplit(',', 1)[-1] for ln in lines if ln][-L.VR_ROWS:])
        return out

    def test_the_virtual_rates_menu_goes_in(self):
        import vr_ui
        cam = self.vr_boot()
        self.assertEqual((self.S(cam, L.S['VR_WHY']), self.S(cam, L.S['VR_UI'])), (1, 1))
        ids = cam.vr_ids
        self.assertEqual(len(ids), L.VR_K)
        self.assertEqual([self.S(cam, L.S['VR_LABEL'] + 4 * k) for k in range(L.VR_K)], ids)
        # the page: vr_ui's bytes, the K label ids in its marks, an FSPG copy the entry names
        page, marks = vr_ui.b25(self.img)
        page = bytearray(page)
        for k, m in enumerate(marks):
            struct.pack_into('>I', page, m, ids[k])
        at = (NBU_BASE + cam.w(cam.b25_entry + 8)) & 0xFFFFFFFF
        self.assertEqual(bytes(cam.mu.mem_read(at, len(page))), bytes(page))
        self.assertEqual([cam.w(at - 128 + 4 * i) for i in range(2, 6)],
                         [len(page), len(page), 0x1CD6B, 1])
        self.assertTrue(cam.S + L.S['BODY'] < at, 'in the core block')
        # the LV layouts: every run, then the label keys
        runs, lmarks = vr_ui.lv(self.img)
        want = {}
        for a, _, new in runs:
            for i, b in enumerate(new):
                want[a + i] = b
        for i, m in enumerate(lmarks):
            for j, b in enumerate(struct.pack('>I', ids[i % L.VR_K])):
                want[m + j] = b
        got = {a: cam.mu.mem_read(a, 1)[0] for a in want}
        self.assertEqual(got, want)
        self.assertEqual(len(cam.lv_ids), 29)
        self.assertEqual([self.S(cam, L.S['LV_LABEL'] + 4*k) for k in range(29)], cam.lv_ids)
        self.qs_stubs(cam)
        for row in vr_ui.lv_records(self.img):
            data = bytearray(row['data'])
            for offset, label in row['marks']:
                struct.pack_into('>I', data, offset, cam.lv_ids[label])
            cam.qs_seen = []
            rd = self.reader(cam, row['address'])
            r0, _ = cam.call(QS_REC, r0=rd, thumb=True)
            self.assertEqual(r0, 0x55)
            self.assertEqual(b''.join(cam.qs_seen), bytes(data))
            self.assertEqual(len(cam.qs_seen), row['records'])
            self.assertEqual(cam.w(rd + 36), NBU_BASE)
            self.assertEqual(cam.w(rd + 4), row['address'] - NBU_BASE + len(row['stock']))
        # the six variants got K rows each, "0,0" while nothing of ours is live; the
        # stock nine as the firmware has them
        self.assertEqual([s for s, _, _ in cam.fv if s in VR_CSV_ADDRS], [a for a, _, _ in rcd.VR_CSV])
        self.assertEqual(self.csv_ab(cam), self.csv_want(set(range(9))))
        # the rate converter: the stock nine, the K virtual rows, the hidden 15 fps last
        stock = self.stock_pairs(0xC2E40224, 10)
        self.assertEqual(self.rpairs(cam), [p for p in stock if p[1] != 9] +
                         [(b, 9 + k) for k, (_, b, _) in enumerate(L.VRATES)] + [(0, 13)])
        self.assertEqual(self.spairs(cam), self.stock_pairs(0xC2E44EE4, 9) + [(0, 13)])
        cam.power_off()
        for a, st, _ in runs:
            self.assertEqual(bytes(cam.mu.mem_read(a, len(st))), st, f'LV 0x{a:08X} put back')

    def test_styled_lv_record_guard_and_disabled_layer_control(self):
        import vr_ui
        cam = self.vr_boot()
        self.qs_stubs(cam)
        row = next(r for r in vr_ui.lv_records(self.img) if r['records'] == 51)
        table = self.S(cam, L.S['LV_RECORDS'])
        cam.put(cam.S + L.S['LV_RECORDS'], 0)
        rd = self.reader(cam, row['address'])
        cam.qs_seen = []
        cam.call(QS_REC, r0=rd, thumb=True)
        self.assertEqual(cam.qs_seen, [row['stock']])
        # Negative control: the new three-text assertion detects a disabled layer.
        with self.assertRaises(AssertionError):
            self.assertEqual(len(cam.qs_seen), row['records'])
        cam.put(cam.S + L.S['LV_RECORDS'], table)
        changed = bytearray(row['stock']); changed[-1] ^= 1
        cam.mu.mem_write(row['address'], bytes(changed))
        rd = self.reader(cam, row['address'])
        cam.qs_seen = []
        cam.call(QS_REC, r0=rd, thumb=True)
        self.assertEqual(cam.qs_seen, [bytes(changed)], 'unknown bytes pass through untouched')
        self.assertEqual(cam.w(rd + 36), NBU_BASE)
        self.assertEqual(cam.w(rd + 4), row['address'] - NBU_BASE + len(row['stock']))

    def test_styled_lv_keeps_parsing_when_resources_were_registered(self):
        """Reader +1c records new resources, not a fatal record-parse error.

        Native C05E69AE/C05E69B4 sets it after successfully registering a new
        resource. A booted reader may already have this flag before LV loads.
        """
        import vr_ui
        cam = self.vr_boot()
        self.qs_stubs(cam)
        row = next(r for r in vr_ui.lv_records(self.img) if r['records'] == 51)
        data = bytearray(row['data'])
        for offset, label in row['marks']:
            struct.pack_into('>I', data, offset, cam.lv_ids[label])
        rd = self.reader(cam, row['address'])
        cam.put(rd + 0x1c, 1)
        cam.qs_seen = []
        cam.call(QS_REC, r0=rd, thumb=True)
        self.assertEqual(b''.join(cam.qs_seen), bytes(data))
        self.assertEqual(len(cam.qs_seen), 51)
        self.assertEqual(cam.w(rd + 0x1c), 1, 'preserve native resource registration state')
        self.assertEqual(cam.w(rd + 36), NBU_BASE)
        self.assertEqual(cam.w(rd + 4), row['address'] - NBU_BASE + len(row['stock']))

    def test_styled_lv_install_refuses_an_unknown_header(self):
        import imx410_rate_lv as V
        a = V.SETS[0]['start'] + 10  # unclaimed object budget bytes, same header size
        a &= ~3
        cam = self.vr_boot(stale={a: self.sw(a) ^ 0x00010000})
        self.assertEqual(self.S(cam, L.S['VR_WHY']), 7)
        self.assertEqual(self.S(cam, L.S['VR_UI']), 0)
        self.assertEqual(self.S(cam, L.S['LV_RECORDS']), 0)
        for spec in V.SETS:
            self.assertEqual(bytes(cam.mu.mem_read(spec['group'], 65)),
                             self.img[spec['group']-0xC0000000:spec['group']-0xC0000000+65])

    def test_qs_records_do_not_walk_the_lv_substitution_table(self):
        from unicorn import UC_HOOK_MEM_READ
        cam = self.vr_boot()
        self.qs_stubs(cam)
        tab = self.S(cam, L.S['LV_RECORDS'])
        size = cam.w(tab + 4)
        def unexpected(mu, access, address, length, value, user):
            raise AssertionError('QS must not read the resident LV record list')
        hook = cam.mu.hook_add(UC_HOOK_MEM_READ, unexpected, begin=tab, end=tab+size-1)
        try:
            got = self.run_recipe(cam, 4)
            self.assertEqual(len(got), len(QS.recipe()['records']))
        finally:
            cam.mu.hook_del(hook)

    def csv_want(self, on, declared=False):
        """each variant's 13 rows: its stock "a,b" for the rows in `on`, else 0,0"""
        return [[('1,2' if declared else rcd._csv_row(self.img, addr, size, j + 1 if j < 9 else (9 if L.VRATES[j - 9][1] == 7 else 1)))
                 if j in on else '0,0' for j in range(L.VR_ROWS)] for addr, size, _ in rcd.VR_CSV]

    def test_every_frame_rate_row_follows_the_live_format(self):
        """2026-10-08 (user): no row the user can choose falls back to a stock mode --
        a stock rate without a plain entry is greyed, a virtual one with entries is not"""
        cam = self.vr_boot()
        self.assertEqual(self.csv_ab(cam), self.csv_want(set(range(9))))
        self.vr_live(cam, 4)                                    # OG3K: 23.98..100, 17.98
        self.assertEqual(self.csv_ab(cam), self.csv_want(set(range(8)) | {11}, declared=True))
        self.vr_live(cam, 10)                                   # HS: all, 239.76, 279.72, 17.98
        self.assertEqual(self.csv_ab(cam), self.csv_want(set(range(12)), declared=True))
        self.vr_live(cam, 4)
        self.commit(cam, 0)                                     # a stock resolution: the firmware's
        cam.call(SETTER, r0=0, r1=3, r2=1)
        self.assertEqual(self.S(cam, L.S['FLAG']), 0)
        self.assertEqual(self.csv_ab(cam), self.csv_want(set(range(9))))

    def test_the_core_times_every_rate_as_the_reference(self):
        """v3: the entries the core makes from the modes (ogc.c gen_entry) are the
        reference's (ogc_layout.gen_entries) byte for byte in S -- PAL hmax, two modes,
        a rate exactly at a mode's limit, Crop Mode twins, mode 12's virtual rates"""
        cases = [
            dict(modes=[(12, 30219, 560, 0, 6)]),        # a synthetic hmax: an exact quotient (udiv)
            dict(modes=[(98, 2997, 445, 450, 4), (117, 10000, 330, 0, 4)]),       # 48..60 on none
            dict(modes=[(98, 11988, 445, 450, 4)]),                              # 119.88 exactly
            dict(modes=[(12, 30219, 330, 0, 6)], flags=1 | L.RFLAG_CROP),         # all + virtual, CROP
            dict(modes=[(139, 2398, 445, 0, 6)]),                                # 23.98 and 17.98 only
            dict(modes=[(139, 1798, 445, 0, 6)]),                                # 17.98 only
        ]
        for change in some(cases, 3):
            rcds = dict(self.rcds, **{'OG2K.RCD': self.variant('OG2K.RCD', **change)})
            cam = self.boot(rcds=rcds)
            self.assertS(cam, [dict(r, target=r['label'].lower()) for r in self.decoded(rcds)])

    def test_every_made_timing_is_within_the_formula_bound(self):
        """layer 2 for the five formats: every entry the core makes keeps the format's
        hmax and x, solves to the rate's 72 MHz count (real period hmax x vmax within
        hmax / 2, hmax when the tail floor moved it), fits the mode's rows plus its stock
        vblank (imx410_full.Registry; S16's window is Jose's, so not there), and 8.99 is
        not made (user: the camera first)"""
        sys.path.insert(0, str(BUILD))
        import imx410_full as X
        reg = X.Registry()
        for name, data in self.all_rcds.items():
            d = rcd.decode(data, self.img, self.stock_ids)
            for e in d['entries']:
                hm, tail, vm, x = e['w0'] & 0xFFFF, e['w0'] >> 16, e['w1'] & 0xFFFF, e['w1'] >> 16
                cyc = (next(v[0] for k, v in enumerate(L.VR_TIME) if L.VRATES[k][0] == e['vrate'])
                       if e['vrate'] else self.cycles_of(e['key'], d['label']))
                m = next(m for m in d['modes'] if m[0] == e['donor'])
                self.assertIn(hm, (m[2], m[3]), e['key'])
                self.assertEqual(x, m[4], e['key'])
                self.assertEqual((vm, tail), L.solve(hm, cyc), e['key'])
                self.assertLessEqual(abs(hm * vm - cyc), hm if tail - hm < L.MIN_TAIL else hm // 2 + 1, e['key'])
                self.assertNotEqual(e['vrate'], 899)
                if d['label'] != 'S16':
                    mode = reg.by_id[e['donor']]
                    self.assertGreaterEqual(vm - mode.raw[1], mode.vblank, e['key'])
            for m in d['modes']:
                if d['label'] != 'S16':
                    mode = reg.by_id[m[0]]
                    self.assertLessEqual(m[1], int(100 * L.CLOCK / (m[2] * (mode.raw[1] + mode.vblank))),
                                         (name, m))

    def test_the_rows_above_the_fastest_rate_are_grey(self):
        """v3: a format is its modes and their fastest rate -- every rate up to it is
        timed by the core (CROP twins too), every one above it greyed"""
        d = rcd.decode(self.rcds['OG3K.RCD'], self.img, self.stock_ids)
        rcds = dict(self.rcds, **{'OG3K.RCD': self.variant('OG3K.RCD', modes=[(98, 3000, 445, 450, 4)],
                                                           flags=d['flags'] | L.RFLAG_CROP)})
        cam = self.boot(rcds=rcds, vr=True)
        cam.vr_rows = self.decoded(rcds)
        self.vr_live(cam, 4)
        self.assertEqual(self.csv_ab(cam), self.csv_want({0, 1, 2, 3, 11}, declared=True))
        for key, there in (('OG3K30', 1), ('OG3K30CROP', 1), ('OG3K48', 0), ('OG3K48CROP', 0)):
            self.assertEqual(bool(self.pick(cam, key)), bool(there), key)
        long7 = self.variant('OG3K.RCD', label='LONGER7', flags=d['flags'] | L.RFLAG_CROP)
        with self.assertRaises(rcd.RcdError) as cm:             # label + "23_98CROP" must fit 15
            rcd.decode(long7)
        self.assertEqual(cm.exception.why, 'FIELD')
        cam = self.boot(rcds=dict(self.rcds, **{'LONGER7.RCD': long7}))
        names = sorted(dict(self.rcds, **{'LONGER7.RCD': long7}))
        self.assertEqual(cam.mu.mem_read(cam.S + L.S['RCD_WHYS'] + names.index('LONGER7.RCD'), 1)[0],
                         L.RCD_WHY['FIELD'], 'the core refuses it too')

    def test_the_rate_limit_is_the_fastest_mode(self):
        cam = self.vr_boot()
        self.stub_gates(cam)
        frmax = lambda v: cam.callr(0xC00A87E4, r4=v)['r0']     # noqa: E731
        self.vr_live(cam, 4)                                    # OG3K: 104.79
        self.assertEqual(frmax(7), 6, '119.88 normalises to 100')
        self.vr_live(cam, 10)                                   # HS: 302.19
        self.assertEqual(frmax(7), 7)

    def test_the_virtual_rates_menu_stays_out_when_it_cannot_go_in(self):
        for kw, why in ((dict(b25_off=0x19C134), 2), (dict(uia_fail={'VR'}), 0x14)):
            cam = self.vr_boot(**kw)
            self.assertEqual((self.S(cam, L.S['VR_WHY']), self.S(cam, L.S['VR_UI'])), (why, 0), kw)
            self.assertEqual(cam.w(cam.b25_entry + 8), kw.get('b25_off', 0x19C130), kw)
            self.assertEqual(self.rpairs(cam), self.stock_pairs(0xC2E40224, 10), kw)
            self.assertEqual(self.outcome(cam, self.NAME), 'LOADED', 'the formats still go in')
            self.vr_live(cam, 4)
            self.rcommit(cam, 9)
            self.assertEqual(self.S(cam, L.S['VRATE']), 0, kw)
        cam = self.boot(rcds=self.vr_rcds())                    # no GUI at all
        self.assertEqual((self.S(cam, L.S['VR_WHY']), self.S(cam, L.S['VR_UI'])), (2, 0))

    def test_a_virtual_row_commits_its_rate_and_the_pairs_follow(self):
        cam = self.vr_boot()
        self.vr_live(cam, 10)
        stock = [p for p in self.stock_pairs(0xC2E40224, 10) if p[1] != 9]
        virt = [(b, 9 + k) for k, (_, b, _) in enumerate(L.VRATES)]
        ssum = self.stock_pairs(0xC2E44EE4, 9)
        for name in ('rcmt1', 'rcmt2'):
            for row, rank in ((9, 23976), (12, 0), (11, 1798), (10, 27972), (3, 0), (9, 23976)):
                self.rcommit(cam, row, name)
                self.assertEqual(self.S(cam, L.S['VRATE']), rank, (name, row))
                k = row - 9 if rank else None
                if rank:
                    self.assertEqual(self.rpairs(cam), [virt[k]] + stock + virt[:k] + virt[k + 1:] + [(0, 13)])
                    self.assertEqual(self.spairs(cam), [(L.VRATES[k][2], row)] + ssum + [(0, 13)])
                else:
                    self.assertEqual(self.rpairs(cam), stock + virt + [(0, 13)])
                    self.assertEqual(self.spairs(cam), ssum + [(0, 13)])
            self.rcommit(cam, 0, name)
        self.assertEqual(self.S(cam, L.S['VR_COMMITS']), 14)
        self.rcommit(cam, 9)
        self.assertEqual(self.S(cam, L.S['DIRTY']), 1)
        self.vr_live(cam, 4)                                    # OG3K has no 239.76: the rate goes
        self.assertEqual(self.S(cam, L.S['VRATE']), 0)
        self.assertEqual(self.rpairs(cam), stock + virt + [(0, 13)])

    def test_the_picker_takes_the_virtual_rates_entries(self):
        cam = self.vr_boot()
        self.vr_live(cam, 10)
        e = self.pick(cam, 'HS120')
        self.assertEqual((cam.w(e + L.ENT['VRATE']), cam.w(e + L.ENT['NOMINAL'])), (0, 120))
        self.rcommit(cam, 9)
        e = self.pick(cam, 'HS120')
        self.assertEqual((cam.w(e + L.ENT['VRATE']), cam.w(e + L.ENT['NOMINAL'])), (23976, 240))
        self.assertEqual(cam.w(e + L.ENT['ENGFPS']), L._f32(240000/1001),
                         'accepted virtual cadence; the withdrawn engine60 trial is not used')
        self.assertEqual(cam.w(e + L.ENT['W1']) & 0xFFFF, 910, 'mode 12 at 239.76: its own vmax')
        e = self.pick(cam, 'HS23_98')
        self.assertEqual(cam.w(e + L.ENT['VRATE']), 0, '23.98 keeps its plain entry')
        self.rcommit(cam, 11)
        e = self.pick(cam, 'HS23_98')
        self.assertEqual((cam.w(e + L.ENT['VRATE']), cam.w(e + L.ENT['NOMINAL'])), (1798, 18))
        self.rcommit(cam, 1)
        e = self.pick(cam, 'HS23_98')
        self.assertEqual(cam.w(e + L.ENT['VRATE']), 0)

    def shim(self, cam, name):
        return self.shim_base(cam) + self.f['shims'][name]

    def vtv(self, cam):
        """(slowest Tv of both copies, display clamp, angle-list enum, angle fps x 100)"""
        a, b = KEYBUF + 0xC00, KEYBUF + 0xC08
        out = []
        for name in ('tvmin', 'tvmin2'):
            cam.mu.mem_write(a, struct.pack('<4I', 30, 1, 1, 120))
            r = cam.callr(self.shim(cam, name), r0=a, r1=b)
            out.append((struct.unpack('<2I', bytes(cam.mu.mem_read(b, 8))), r['r0']))
        nx = lambda n: cam.S + L.S['NEXT'] + 4 * L.HOOK_INDEX[n]   # noqa: E731
        old = cam.w(nx('tvdisp')), cam.w(nx('angtv'))
        cam.put(nx('tvdisp'), T.DONE)
        cam.put(nx('angtv'), T.DONE)
        sp = T.STACK - 0x1004 - 0x100
        cam.mu.mem_write(sp + 0x28, struct.pack('<2I', 1, 125))
        cam.callr(self.shim(cam, 'tvdisp'), sp=sp, fp=cam.fr)
        out.append(struct.unpack('<2I', bytes(cam.mu.mem_read(sp + 0x28, 8))))
        out.append(cam.callr(self.shim(cam, 'anglist'))['r0'])
        cam.put(sp, cam.fr)
        out.append(cam.callr(self.shim(cam, 'angtv'), sp=sp, r6=5000)['r6'])
        cam.put(nx('tvdisp'), old[0])
        cam.put(nx('angtv'), old[1])
        return out

    def test_the_shutter_range_and_angle_follow_the_virtual_rate(self):
        cam = self.vr_boot()
        cam.fr = 7
        stock = [((1, 120), 1), ((1, 120), 1), (1, 125), 7, 5000]
        self.assertEqual(self.vtv(cam), stock, 'nothing of ours live')
        self.vr_live(cam, 10)
        self.assertEqual(self.vtv(cam), stock, 'ours live, no virtual rate')
        self.rcommit(cam, 9)
        self.assertEqual(self.vtv(cam), [((1, 240), 1), ((1, 240), 1), (1, 240), 0, 23976])
        cam.fr = 6                                              # the camera moved to 100p
        self.assertEqual(self.vtv(cam), [((1, 120), 1), ((1, 120), 1), (1, 125), 6, 5000])
        cam.fr = 1
        self.rcommit(cam, 11)
        self.assertEqual(self.vtv(cam), [((1, 18), 1), ((1, 18), 1), (1, 18), 0, 1798])
        cam.fr = 7
        self.rcommit(cam, 10)
        self.assertEqual(self.vtv(cam), [((1, 280), 1), ((1, 280), 1), (1, 280), 0, 27972])
        self.vr_live(cam, 4)                                    # OG3K: no 279.72
        self.assertEqual(self.vtv(cam)[2:], [(1, 125), 7, 5000])
        self.assertGreater(self.S(cam, L.S['VTV_HITS']), 0)

    def test_the_virtual_rate_is_saved_and_restored(self):
        cam = self.vr_boot()
        self.vr_live(cam, 10)
        self.rcommit(cam, 9)
        self.save(cam)
        self.assertEqual(cam.written[cam.core_path][self.HL:self.HL + L.CFG['BYTES']],
                         self.record('HS', vrate=23976))
        self.rcommit(cam, 3)
        self.save(cam)
        self.assertEqual(cam.written[cam.core_path][self.HL:self.HL + L.CFG['BYTES']], self.record('HS'))
        for fr, rank, got in ((7, 23976, 23976), (6, 23976, 0), (1, 1798, 1798), (7, 27972, 27972),
                              (1, 899, 0), (7, 12345, 0)):
            cam = self.vr_boot(record=self.record('HS', vrate=rank), fr=fr)
            self.assertEqual(self.S(cam, L.S['RLOG'] + 0xC), 1)
            self.assertEqual(self.S(cam, L.S['VRATE']), got, (fr, rank))
            if got:
                self.assertEqual(self.rpairs(cam)[0][1], 9 + self.RANKS.index(got))


class ProgrammingTests(CoreTests):
    """What the firmware programs the sensor and the receiver with, for our
    virtual mode against the stock mode (2026-10-07: the camera's first take was
    garbage -- FUN_c031ffa0, the descriptor's +0x10 {value, mode} table, was not
    intercepted, so the readout took mode 0's value instead of the donor's).

    Every per-mode reader of the mode-set path that runs to completion here, for
    real, in a fresh camera: the eight lookups (rows / value), the cached-index
    readers (FUN_c0320740, FUN_c03208b0, FUN_c0320818), the register-record
    writer FUN_c03258c8 (every sensor register it writes), the frame-period
    getter -- and every firmware memory write they make (hardware pages are
    mapped on demand).  The descriptor is the camera's (live-read addresses)."""

    READERS = [(0xC0320740, 'i'), (0xC03208B0, 'i', 1000000, 0), (0xC03208B0, 'i', 10, 1),
               (0xC0320818, 'i', 1000000, 0), (0xC03258C8, 'h', 'm'), (0xC0321160, 'i', 'm'),
               (0xC031FFA0, 'i', 'm')]
    ROWS = [(0xC0320FC8, 0x20), (0xC0321028, 100), (0xC0320700, 0x28), (0xC0321088, 0x14),
            (0xC0321100, 0x68)]

    def programming(self, cam, mode, donor):
        from unicorn import UC_HOOK_MEM_WRITE, UC_HOOK_MEM_UNMAPPED
        mu = cam.mu
        writes = []
        blo, bhi = (cam.S or 0) - 0x20000, (cam.S or 0) + 0x20000

        def unmapped(uc, access, addr, size, value, data):
            try:
                uc.mem_map(addr & ~0xFFFF, 0x10000)
                return True
            except Exception:
                return False

        def write(uc, access, addr, size, value, data):
            if T.STACK - 0x20000 <= addr < T.STACK or blo <= addr < bhi:
                return
            if addr in (L.IMAGER + 4, L.IMAGER + 0xC, L.IMAGER + 0x10, L.IMAGER + 0x14):
                return                     # the mode id and the cached indices: ours by design
            writes.append((addr, size, donor if value == mode else value))

        h1 = mu.hook_add(UC_HOOK_MEM_UNMAPPED, unmapped)
        h2 = mu.hook_add(UC_HOOK_MEM_WRITE, write)
        out = []
        cam.sensor = []
        try:
            cam.put(L.IMAGER + 4, mode)
            cam.callr(0xC0321290, r0=L.IMAGER, r1=mode)
            for f, *args in self.READERS:
                regs = {f'r{i}': {'i': L.IMAGER, 'h': HOLDER, 'm': mode}.get(a, a)
                        for i, a in enumerate(args)}
                r = cam.callr(f, **regs)
                self.assertEqual(cam.mu.reg_read(UC_ARM_REG_PC), T.DONE, f'{f:#x} returned')
                out.append((hex(f), donor if r['r0'] == mode else r['r0']))
            for f, n in self.ROWS:
                p = cam.callr(f, r0=L.IMAGER, r1=mode)['r0']
                row = bytes(cam.mu.mem_read(p, n))
                out.append((hex(f), struct.unpack_from('<I', row)[0] in (mode, donor), row[4:]))
            # the receiver row: FUN_c0320f60's index on the descriptor's +0x40, as FUN_c032d5e0 reads it
            i = cam.callr(0xC0320F60, r0=L.IMAGER, r1=mode)['r0']
            row = bytes(cam.mu.mem_read((0xC0B5C638 + i * 0x38) & 0xFFFFFFFF, 0x38))
            out.append(('receiver', struct.unpack_from('<I', row)[0] in (mode, donor), row[4:]))
            i = cam.callr(0xC0326DB8, r0=HOLDER, r1=mode)['r0']
            base = cam.w(L.REGDESC)
            row = bytes(cam.mu.mem_read((base + i * 0x288) & 0xFFFFFFFF, 0x288))
            out.append(('registers', struct.unpack_from('<I', row)[0] in (mode, donor), row[4:]))
        finally:
            mu.hook_del(h1)
            mu.hook_del(h2)
        return out, writes, list(cam.sensor)

    def assertSameProgramming(self, a, b, what):
        (oa, wa, sa), (ob, wb, sb) = a, b
        self.assertEqual(len(oa), len(ob))
        for x, y in zip(oa, ob):
            self.assertEqual(x, y, f'{what}: {x[0]}')
        self.assertEqual(sa, sb, f'{what}: sensor register writes')
        self.assertEqual(wa, wb, f'{what}: firmware memory writes')
        self.assertGreater(len(sa), 150, 'the register record was really written')

    def test_core_self_proof_a_stock_copy_programs_exactly_the_stock_mode(self):
        """A row that asks for nothing (no clamp, no pick) must give the donor,
        word for word: the core itself adds no difference."""
        for target, donor in some((('og3k', 98), ('og3k', 117), ('og2k', 139)), 1):
            vid = self.vid(target, donor)
            cam = self.boot()
            for v in range(len(self.ref()[1]['vms'])):
                cam.put(self.vm(cam, v) + L.VM['CLAMP'], 0)
            ours = self.programming(cam, vid, donor)
            stock = self.programming(self.boot(), donor, donor)
            self.assertSameProgramming(ours, stock, f'{target} vm of {donor}')

    def test_og3k_and_og2k_program_what_todays_core_programs(self):
        """Today's 30OG3K / 30OG2K (v3, with the video clamp) against the new core,
        for the same pick: identical, clamp included."""
        sys.path.insert(0, str(BUILD))
        import test_v3_og as O
        for target, key, donor in some((('og3k', 'OG3K30', 98), ('og2k', 'OG2K60', 139),
                                        ('og3k', 'OG3K100', 117), ('og3k', 'OG3K24', 98)), 2):
            rf = next(x for x in self.rows if x['target'] == target)
            old_bin, old_f, old_name = O.built(target)
            files, dirs = T.card((old_name, old_bin))
            old = old_camera(O, files, dirs, {old_f['block']: old_f})
            old.boot()
            old.build_descriptor()
            old.S = None
            old.put(old.at(old_f, old_f['fmtlatch']), 0)
            old.call(SETTER, r0=0, r1=rf['enum'], r2=1)
            old.mu.mem_write(KEYBUF, key.encode().ljust(16, b'\0'))
            old.call(PICKER, r0=0, r1=TAB3, r2=KEYBUF)
            new = self.boot()
            self.live(new, rf['enum'])
            dr = 0xC0B59500 + 0x20 * self.modes_index(donor)
            self.force_timing(new, key, old.w(dr + 4), old.w(dr + 8))   # today's words (assertTiming: the solver)
            vid = new.w(self.pick(new, key) + 8)
            self.assertSameProgramming(self.programming(new, vid, donor),
                                       self.programming(old, donor, donor), key)


J_S16100 = [(144, 1), (176, 1), (192, 0), (220, 2112), (228, 1250), (252, 0x40000000),
            (256, 0x40000000)]       # Jose's S16 record list after its 100p mark


def _jose_programming(self):
    """S16 (mode 121 + 29 table overrides + the window) and OG4K / OG3.5K (mode 3 +
    the window): our virtual mode programs exactly what Jose's patched STOCK
    mode programs -- his patches written into the firmware's tables, his picker's
    timing words and clamp -- while the stock tables stay untouched on our side."""
    import jose_formats as J
    tabs = [0xC0B59500, 0xC0B59DC0, 0xC0B5BB48, 0xC0B5C638, 0xC0B5D588, 0xC0B5DB00, 0xC0B5FDAC]
    for name, key in [x for i, x in enumerate((('s16', 'S1630'), ('og4k', 'OG4K24'), ('s16', 'S1624'),
                                                ('og35k', 'OG35K30'))) if SLOW or i < 2]:
        row = J.ROWS[name]
        ent = next(e for e in row['entries'] if e['key'] == key)
        donor = ent['donor']
        new = self.boot(rcds=self.all_rcds)
        cam_rows = self.decoded(self.all_rcds)
        r = [x['label'] for x in cam_rows].index(row['label'])
        new.call(FMTSET, r0=0, r1=CINEMADNG, r2=1)
        self.commit(new, self.row(new, r, L.ROW['MROW']))
        new.call(SETTER, r0=0, r1=row['stock_value'], r2=1)
        mine = self.ent_by_key(new, key)
        self.assertTiming((ent['w0'], ent['w1']), (new.w(mine + L.ENT['W0']), new.w(mine + L.ENT['W1'])),
                          self.cycles_of(key, row['label']), key)
        self.force_timing(new, key, ent['w0'], ent['w1'])    # his words: the rest compared exactly
        vid = new.w(self.pick(new, key) + 8)
        self.assertGreaterEqual(vid, L.VMID0)
        old = self.boot(rcds=None)                       # the core not loaded: stock tables
        for _, kind, off, val in row['overrides']:
            stride = L.TABLES[kind][3]
            base = tabs[kind]
            i = [old.w(base + stride * k) for k in range(70)].index(donor)
            old.put(base + stride * i + off, val)
        i = [old.w(tabs[0] + 0x20 * k) for k in range(70)].index(donor)
        old.put(tabs[0] + 0x20 * i + 4, ent['w0'])
        old.put(tabs[0] + 0x20 * i + 8, ent['w1'])
        r38 = tabs[3] + 0x38 * [old.w(tabs[3] + 0x38 * k) for k in range(70)].index(donor)
        old.put(r38 + 4, old.w(r38 + 4) | 0x8)
        old.put(r38 + 0x18, old.w(r38 + 0x18) | 0xC000)
        # Unicorn drops a store when a memory-write hook is installed while our
        # override loop runs (seen 2026-10-07: the second TIM override, +0x10, lost
        # only with programming()'s hook in place; without it the row is right).
        # So the mode is set once, unhooked, first -- the same on both sides.
        for cam, m in ((new, vid), (old, donor)):
            cam.put(L.IMAGER + 4, m)
            cam.callr(0xC0321290, r0=L.IMAGER, r1=m)
            # The register clone is lazy and isn't read by mode-set. Warm it
            # through its real lookup before installing the write observer,
            # for the same Unicorn dropped-store issue described above.
            # Its bytes and every sensor write are still compared below.
            cam.callr(0xC0326DB8, r0=HOLDER, r1=m)
        idx, _ = new.call(self.site_of('lk_tim'), r0=L.IMAGER, r1=vid)
        tim = (0xC0B59500 + idx * 0x20) & 0xFFFFFFFF
        want = {o: v for _, k, o, v in row['overrides'] if k == 0}
        self.assertEqual((new.w(tim + 0xC), new.w(tim + 0x10)), (want[0xC], want[0x10]), key)
        self.assertSameProgramming(self.programming(new, vid, donor),
                                   self.programming(old, donor, donor), key)
        # and the stock tables on our side are the image's
        for base, stride in ((tabs[1], 100), (tabs[3], 0x38), (tabs[6], 0x288)):
            self.assertEqual(bytes(new.mu.mem_read(base, 70 * stride)), self.stock(base, 70 * stride))


# ProgrammingTests borrows CoreTests' boot and helpers, not its tests.
for _n in [n for n in vars(CoreTests) if n.startswith('test_')]:
    setattr(ProgrammingTests, _n, None)
ProgrammingTests.test_jose_formats_program_what_his_patched_stock_modes_program = _jose_programming


def old_camera(O, files, dirs, sups):
    """test_v3_og's camera for today's core, recording the sensor register writes."""
    class OldCam(O.OGCamera):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.sensor = []
            self.by_addr[FW['SENSOR_W']] = 'SENSOR_W'
            self.mu.mem_write(FW['SENSOR_W'], struct.pack('<I', 0xE12FFF1E))

        def _hook(self, mu, addr, size, data):
            if self.by_addr.get(addr) == 'SENSOR_W':
                self.sensor.append((self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_R1)))
                return self._ret(0)
            return super()._hook(mu, addr, size, data)

        callr = Cam.callr
        build_descriptor = Cam.build_descriptor
    return OldCam(files, dirs, sups)


def rf_profile(rf):
    return {'OG3K': 83, 'OG2K': 13}[rf['label']]


def run_old_canvas(cam, f):
    """today's og3kcanvas, through the hooked site's veneer: call C043A19C."""
    mu = cam.mu
    mu.reg_write(UC_ARM_REG_SP, T.STACK - 0x1004)
    mu.reg_write(UC_ARM_REG_LR, T.DONE)
    site = 0xC043A19C
    w = cam.w(site)
    d = w & 0xFFFFFF
    d -= 0x1000000 if d & 0x800000 else 0
    ven = site + 8 + 4 * d
    mu.emu_start(ven, T.DONE, count=2_000_000)
    return bytes(mu.mem_read(CANVAS_IN + 0x5C, 0x108))


if __name__ == '__main__':
    unittest.main()
