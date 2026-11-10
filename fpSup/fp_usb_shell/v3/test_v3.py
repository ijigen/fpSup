#!/usr/bin/env python3
"""Loader v3 under unicorn: the real loader.S (as the AutoRun spells it) and the
real LOADER.BIN, against the real firmware image, with the firmware's file,
directory, allocator and power-off routines done in Python.

    cd fpSup/fp_usb_shell && python3 -B -m unittest v3.test_v3

What this cannot tell: timing, what the real directory API returns on a card
with odd entries (that was checked on the camera, DIR_ENUM_API.md), and
anything a stub does differently from the routine it replaces.
"""
import pathlib, struct, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
IMAGE = HERE.parents[2] / 'out' / 'MAIN_c0000000.bin'

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR,
                                   UC_ARM_REG_PC, UC_ARM_REG_CPSR)
except ImportError:                                        # pragma: no cover
    Uc = None

import build_v3 as B
import cave
from armasm import assemble

CAVE_LOW = cave.CAVE_ARENA - 0x200
HEAP, HEAP_SIZE = 0x45000000, 0x00800000
STACK = 0x46000000
DONE = 0x47000000
STAGING_GARBAGE = 0xDE

F = dict(F_MGR=0xC0444658, F_VOL=0xC0444698, F_CTOR=0xC0365E90, F_OPEN=0xC0365FB0,
         F_READ=0xC0366060, F_CLOSE=0xC0366020, F_DTOR=0xC0365ED0,
         DCACHE=0xC000E91C, ICACHE=0xC000EABC, TICK=0xC002B6E0,
         H_GET=0xC001D740, H_ADDR=0xC001D7F0, H_FREE=0xC001D7A0,
         MEM_HEAP=0xC001CF78, MEM_GET=0xC001D038, MEM_FREE=0xC001D2B8,
         POFF_MGR=0xC0023A98, POFF_ADD=0xC0024118,
         DIR_CTOR=0xC0366918, DIR_OPEN=0xC0366990, DIR_NEXT=0xC03669F8,
         DIR_DTOR=0xC0366940, AR_START=0xC03DA758,
         TK_CRE=0xC0016A58, TK_STA=0xC0016BC0, F_WRITE=0xC03660E8,
         D_FILE=0xC03E4270, D_SLEEP=0xC03705D8, CYC_DRAW=0xC05278F8,
         UI_CLEAR=0xC0527DD8, UI_FORCE=0xC0527E68)
DRAW, DRAW_STOCK, DRAW_PAUSED = 0xC0528700, 0xE92D4BF0, 0xE12FFF1E

# Real firmware words, used as sites: the gyro's accel/start/stop hooks.
SITE_A, SITE_B, SITE_C = 0xC050D4C8, 0xC03790B8, 0xC038C484
NOP = 0xE1A00000

# struct state, mirrored from sloader.c (checked by test_state_layout).
SVC_BYTES = 44                       # version 3: + holder, self, done_at_start
O_POFF, O_HEAP, O_JBASE, O_JCUR = 44, 56, 60, 64
O_NCLAIMS = 72
O_CLAIMS, CLAIM_BYTES, MAX_CLAIMS = 88, 12, 768
O_NSUPS = O_CLAIMS + CLAIM_BYTES * MAX_CLAIMS
O_SUPS, SUP_BYTES, MAX_SUPS = O_NSUPS + 4, 100, 32
O_NLOG = O_SUPS + SUP_BYTES * MAX_SUPS
O_LOG, LOG_BYTES = O_NLOG + 4, 32
L = {1: 'START', 2: 'NO_DIR', 3: 'SKIP_NAME', 4: 'TOO_MANY', 5: 'OPEN_FAIL',
     6: 'BAD_HEADER', 7: 'DUP_ID', 8: 'NO_MEMORY', 9: 'SHORT_READ', 10: 'LOADED',
     11: 'RELEASED', 12: 'REPAIRED', 13: 'SUP', 14: 'DONE', 15: 'NO_POFF', 16: 'CONFLICT'}


def word(img, a):
    return struct.unpack_from('<I', img, a - 0xC0000000)[0]


def test_sup(sup_id, rows, block_size=None):
    """rows: (address, stock, kind, new)."""
    code = assemble(HERE / 'test_sup.S')
    table = struct.pack('<I', len(rows)) + b''.join(struct.pack('<4I', *r) for r in rows)
    return B.make_sup(code + table, B.SL_HEADER_LEN, sup_id, block_size=block_size)


class Camera:
    def __init__(self, files, dirs, stale=None, autorun=None):
        self.files, self.dirs = files, dirs
        self.img = IMAGE.read_bytes()
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        mu.mem_map(0xC0000000, 0x03000000)
        mu.mem_write(0xC0000000, self.img[:0x03000000])
        mu.mem_map(0xC3000000, 0x01000000)
        mu.mem_map(HEAP, HEAP_SIZE)
        mu.mem_map(STACK - 0x20000, 0x20000)
        mu.mem_map(DONE, 0x1000)
        ar = autorun if autorun is not None else B.autorun(pathlib.Path('/tmp'))
        for a, v in B.loader_words(ar).items():
            mu.mem_write(a, struct.pack('<I', v))
        for a, v in (stale or {}).items():
            mu.mem_write(a, struct.pack('<I', v))
        # Every stubbed routine starts with `bx lr` as well as being hooked:
        # unicorn sometimes ignores a PC written from a code hook (seen on the
        # osdfile stub, 2026-10-06) and runs the real routine instead.
        for a in F.values():
            mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
        self.heap_next = HEAP
        self.allocs, self.freed, self.registered, self.calls = {}, [], [], []
        self.dir_iter, self.fobj, self.misaligned, self.opened = {}, {}, [], []
        self.tasks, self.draws, self.slept, self.written = [], [], 0, {}
        self.by_addr = {v: k for k, v in F.items()}
        self.now = 1_400_000
        self.error = None
        mu.hook_add(UC_HOOK_CODE, self._safe_hook)

    # --- plumbing ---------------------------------------------------------
    def r(self, reg):
        return self.mu.reg_read(reg)

    def w(self, a):
        return struct.unpack('<I', self.mu.mem_read(a, 4))[0]

    def put(self, a, v):
        self.mu.mem_write(a, struct.pack('<I', v & 0xFFFFFFFF))

    def cstr(self, a, n=128):
        return bytes(self.mu.mem_read(a, n)).split(b'\0')[0].decode()

    def _ret(self, value=None):
        mu = self.mu
        if value is not None:
            mu.reg_write(UC_ARM_REG_R0, value & 0xFFFFFFFF)
        # unicorn takes the Thumb state from bit 0 of a PC write
        mu.reg_write(UC_ARM_REG_PC, self.r(UC_ARM_REG_LR))

    def _alloc(self, n, align=8):
        p = (self.heap_next + align - 1) & ~(align - 1)
        self.heap_next = p + n
        self.allocs[p] = n
        self.mu.mem_write(p, b'\xA5' * n)        # not zero: the code must clear
        return p

    def _safe_hook(self, mu, addr, size, data):
        # unicorn swallows an exception raised in a hook and carries on running
        # the real firmware routine: stop instead, and let call() raise it.
        try:
            self._hook(mu, addr, size, data)
        except Exception as e:                            # pragma: no cover
            self.error = e
            mu.emu_stop()

    def _hook(self, mu, addr, size, _):
        if addr == DONE:
            mu.emu_stop()
            return
        name = self.by_addr.get(addr)
        if name is None:
            return
        # loader.S is entered 4 off by the echo caller and does not realign
        # (stage2 always did that); only the loader's own calls are exempt.
        if self.r(UC_ARM_REG_SP) & 7 and not CAVE_LOW <= self.r(UC_ARM_REG_LR) < cave.CAVE_ARENA:
            self.misaligned.append(name)
        self.calls.append(name)
        r0, r1, r2, r3 = (self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1,
                                               UC_ARM_REG_R2, UC_ARM_REG_R3))
        if name == 'AR_START':
            self.calls.append('AUTORUN')
            mu.emu_stop()
            return
        if name == 'H_GET':
            self.put(r0, self._alloc(r2))
            return self._ret(1)
        if name == 'H_ADDR':
            return self._ret(self.w(r0))
        if name == 'H_FREE':
            p = self.w(r0)
            self.freed.append(p)
            mu.mem_write(p, bytes([STAGING_GARBAGE]) * self.allocs[p])
            return self._ret(0)
        if name == 'MEM_HEAP':
            return self._ret(0x1234 if r0 == 0 else 0)
        if name == 'MEM_GET':
            return self._ret(self._alloc(r1))
        if name == 'MEM_FREE':
            self.freed.append(r1)
            return self._ret(0)
        if name == 'F_VOL':
            return self._ret(1)
        if name == 'F_CTOR':
            self.fobj[r0] = None
            return self._ret(r0)
        if name == 'F_OPEN':
            path = self.cstr(r1)
            self.opened.append(path)
            if r2 == 7:                               # write: create or overwrite
                self.fobj[r0] = [path, 0]
                self.written.setdefault(path, b'')
                return self._ret(1)
            ok = path in self.files
            self.fobj[r0] = [path, 0] if ok else None
            return self._ret(1 if ok else 0)
        if name == 'F_READ':
            path, pos = self.fobj[r0]
            data = self.files[path][pos:pos + r2]
            mu.mem_write(r1, data)
            self.fobj[r0][1] += len(data)
            if r3:
                self.put(r3, len(data))
            return self._ret(len(data))
        if name == 'DIR_CTOR':
            self.put(r0, 0x5A5A0000)
            return self._ret(r0)
        if name == 'DIR_OPEN':
            path = self.cstr(r1)
            if path not in self.dirs:
                return self._ret(0)
            self.dir_iter[r0] = list(self.dirs[path])
            return self._ret(1)
        if name == 'DIR_NEXT':
            left = self.dir_iter.get(r0) or []
            if not left:
                return self._ret(0)
            nm, attr, size = left.pop(0)
            ent = bytearray(0x238)
            u = nm.encode('utf-16le')
            ent[:len(u)] = u
            struct.pack_into('<QB', ent, 0x210, size, attr)
            mu.mem_write(r1, bytes(ent))
            return self._ret(1)
        if name == 'POFF_MGR':
            return self._ret(0xC3000100)
        if name == 'POFF_ADD':
            self.registered.append((r1, r2))
            return self._ret(1)
        if name == 'F_WRITE':
            path, pos = self.fobj[r0]
            data = bytes(mu.mem_read(r1, r2))
            old = self.written[path]
            self.written[path] = old[:pos] + data + old[pos + len(data):]
            self.fobj[r0][1] += r2
            return self._ret(1)
        if name == 'TK_CRE':
            self.tasks.append(self.w(r0 + 8))
            self.task_stacks = getattr(self, 'task_stacks', []) + [self.w(r0 + 16)]   # stksz
            return self._ret(7)
        if name == 'D_FILE':
            argv = [self.cstr(self.w(r2 + 4 * i)) for i in range(r1)]
            self.draws.append((argv[0], self.w(DRAW)))
            return self._ret(0)
        if name == 'CYC_DRAW':
            return self._ret(0xC3000200)
        if name == 'D_SLEEP':
            self.slept += r0
            return self._ret(0)
        if name == 'TICK':
            self.now += 1000
            return self._ret(self.now)
        return self._ret(0)

    def call(self, pc, r0=0, r1=0, r2=0, lr=DONE, sp=STACK - 0x1004, thumb=False):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, sp)
        for reg, v in ((UC_ARM_REG_R0, r0), (UC_ARM_REG_R1, r1), (UC_ARM_REG_R2, r2)):
            mu.reg_write(reg, v & 0xFFFFFFFF)
        mu.reg_write(UC_ARM_REG_LR, lr)
        try:
            mu.emu_start(pc | (1 if thumb else 0), DONE, count=20_000_000)
        finally:
            if self.error:
                raise self.error
        return self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_SP)

    # --- reading the loader's books ----------------------------------------
    def boot(self):
        return self.call(CAVE_LOW)                 # the echo entry: `b load`

    def state(self):
        objs = {o - size for o, _ in self.registered for size, version in ((SVC_BYTES, 3), (SVC_BYTES + 4, 4))
                if self.w(o - size) == version}
        assert len(objs) == 1, self.registered
        return objs.pop()

    def journal(self):
        st = self.state()
        delta = 4 if self.w(st) == 4 else 0
        e, out = self.w(st + O_JBASE + delta), []
        while self.w(e):
            a, n = self.w(e), self.w(e + 4)
            out.append((a, n, bytes(self.mu.mem_read(e + 8, n))))
            e += 8 + n
        return out

    def log(self):
        st = self.state()
        delta = 4 if self.w(st) == 4 else 0
        out = []
        for i in range(self.w(st + O_NLOG + delta)):
            r = st + O_LOG + delta + LOG_BYTES * i
            code, a, b = struct.unpack('<3I', self.mu.mem_read(r, 12))
            out.append((L.get(code, code), a, b, self.cstr(r + 12, 20)))
        return out

    def power_off(self):
        st = self.state()
        obj = st + O_POFF + (4 if self.w(st) == 4 else 0)
        vtbl = self.w(obj)
        return self.call(self.w(vtbl + 0xC), r0=obj, r1=4)


def card(*sups, extra=(), order=None):
    """{path: bytes} and {dir: [(name, attr, size)]}, in directory order."""
    vbin, _ = B.loader_bin()
    files = {'\\fpSup\\LOADER.BIN': vbin}
    ents = [('LOADER.BIN', 0x20, len(vbin))]
    for name, data in sups:
        files['\\fpSup\\' + name] = data
        ents.append((name, 0x20, len(data)))
    ents += list(extra)
    if order:
        ents = [next(e for e in ents if e[0] == n) for n in order]
    return files, {'\\fpSup': ents}


@unittest.skipIf(Uc is None or not IMAGE.exists(), 'needs unicorn and the image')
class LoaderV3Tests(unittest.TestCase):
    def setUp(self):
        img = IMAGE.read_bytes()
        self.stock = {a: word(img, a) for a in (SITE_A, SITE_B, SITE_C)}

    def rows(self, *spec):
        return [(a, self.stock[a], k, new) for a, k, new in spec]

    def test_loads_in_name_order_skipping_what_is_not_a_sup(self):
        a = test_sup('TSTA', self.rows((SITE_A, 2, NOP)))
        c = test_sup('TSTC', self.rows((SITE_C, 2, NOP)))
        files, dirs = card(('20C.BIN', c), ('10A.BIN', a),
                           extra=[('._10A.BIN', 0x22, 4096), ('._20C.BIN', 0x20, 4096),
                                  ('NOTES.TXT', 0x20, 10),
                                  ('SUB', 0x10, 0), ('HIDDEN.BIN', 0x22, 64)])
        cam = Camera(files, dirs)
        r0, sp = cam.boot()
        self.assertEqual(sp, STACK - 0x1004)
        self.assertEqual(cam.misaligned, [])
        self.assertNotIn('AUTORUN', cam.calls)
        loaded = [t for c, _, _, t in cam.log() if c == 'LOADED']
        self.assertEqual(loaded, ['10A.BIN', '20C.BIN'])
        self.assertEqual([t for c, _, _, t in cam.log() if c == 'SKIP_NAME'], ['LOADER.BIN', 'NOTES.TXT'])
        self.assertFalse([c for c, *_ in cam.log() if c in ('OPEN_FAIL', 'BAD_HEADER')])
        opened = [p for p in cam.opened if 'fpSup\\' in p and p not in cam.written]
        self.assertEqual(sorted(set(opened)), ['\\fpSup\\10A.BIN', '\\fpSup\\20C.BIN',
                                               '\\fpSup\\LOADER.BIN'])
        self.assertEqual(cam.w(SITE_A), NOP)
        self.assertEqual(cam.w(SITE_C), NOP)
        self.assertEqual(cam.w(cave.CAVE_BUMP), cave.CAVE_ARENA)
        self.assertNotEqual(cam.w(cave.LOAD_DONE_US), 0)
        self.assertEqual(sorted(f for _, f in cam.registered), [0, 1])
        self.assertEqual(cam.log()[-1][:2], ('DONE', 2))

    def test_journal_holds_the_declared_stock_and_power_off_restores_it(self):
        a = test_sup('TSTA', self.rows((SITE_A, 2, NOP), (SITE_B, 1, NOP)))
        cam = Camera(*card(('A.BIN', a)))
        cam.boot()
        self.assertEqual(cam.journal(), [(SITE_A, 4, struct.pack('<I', self.stock[SITE_A])),
                                         (SITE_B, 4, struct.pack('<I', self.stock[SITE_B]))])
        cam.power_off()
        self.assertEqual(cam.w(SITE_A), self.stock[SITE_A])
        self.assertEqual(cam.w(SITE_B), self.stock[SITE_B])

    def test_a_patch_left_by_a_missed_power_off_is_repaired_not_journaled(self):
        stale = 0xEB0DEAD0                      # a bl into last boot's heap
        a = test_sup('TSTA', self.rows((SITE_A, 2, NOP)))
        cam = Camera(*card(('A.BIN', a)), stale={SITE_A: stale})
        cam.boot()
        self.assertEqual(cam.journal()[0][2], struct.pack('<I', self.stock[SITE_A]))
        self.assertIn(('REPAIRED', SITE_A), [x[:2] for x in cam.log()])
        cam.power_off()
        self.assertEqual(cam.w(SITE_A), self.stock[SITE_A])

    def test_stale_site_is_stock_before_anyone_writes_it(self):
        """A CHAIN layer reads the site to find the layer below; a stale bl
        there would send it into last boot's heap."""
        a = test_sup('TSTA', self.rows((SITE_A, 1, 0)))       # claim, no write
        cam = Camera(*card(('A.BIN', a)), stale={SITE_A: 0xEB0DEAD0})
        cam.boot()
        self.assertEqual(cam.w(SITE_A), self.stock[SITE_A])

    def test_conflicting_sup_is_released_and_leaves_nothing(self):
        a = test_sup('TSTA', self.rows((SITE_A, 2, NOP)))
        b = test_sup('TSTB', self.rows((SITE_B, 2, 0xE1A01001), (SITE_A, 2, 0xE1A02002)))
        cam = Camera(*card(('1A.BIN', a), ('2B.BIN', b)))
        cam.boot()
        log = cam.log()
        self.assertIn('2B.BIN', [t for c, _, _, t in log if c == 'RELEASED'])
        self.assertIn('CONFLICT', [c for c, *_ in log])
        self.assertEqual(cam.w(SITE_A), NOP)                    # A's, untouched
        self.assertEqual(cam.w(SITE_B), self.stock[SITE_B])     # B wrote nothing
        self.assertEqual([j[0] for j in cam.journal()], [SITE_A])
        self.assertEqual(cam.w(cam.state() + O_NCLAIMS), 1)
        st = cam.state()
        blocks = [cam.w(st + O_SUPS + SUP_BYTES * i + 44) for i in range(2)]
        self.assertEqual(blocks[1], 0)
        self.assertGreater(len(cam.freed), 0)

    def test_chain_claims_stack_and_exclusive_does_not(self):
        a = test_sup('TSTA', self.rows((SITE_A, 1, NOP)))
        b = test_sup('TSTB', self.rows((SITE_A, 1, NOP)))
        c = test_sup('TSTC', self.rows((SITE_A, 2, NOP)))
        cam = Camera(*card(('1.BIN', a), ('2.BIN', b), ('3.BIN', c)))
        cam.boot()
        res = {t: c for c, _, _, t in cam.log() if c in ('LOADED', 'RELEASED')}
        self.assertEqual(res, {'1.BIN': 'LOADED', '2.BIN': 'LOADED', '3.BIN': 'RELEASED'})
        self.assertEqual(len(cam.journal()), 1)                  # stock once

    def test_same_id_loads_once(self):
        a = test_sup('SAME', self.rows((SITE_A, 1, NOP)))
        b = test_sup('SAME', self.rows((SITE_B, 1, NOP)))
        cam = Camera(*card(('1.BIN', a), ('2.BIN', b)))
        cam.boot()
        self.assertIn(('DUP_ID', '2.BIN'), [(c, t) for c, _, _, t in cam.log()])
        self.assertEqual(cam.w(SITE_B), self.stock[SITE_B])

    def test_bad_headers_are_skipped(self):
        good = test_sup('GOOD', self.rows((SITE_A, 1, NOP)))
        short = good[:40]
        badmagic = b'XXXX' + good[4:]
        cam = Camera(*card(('1.BIN', short), ('2.BIN', badmagic), ('3.BIN', good)))
        cam.boot()
        log = cam.log()
        self.assertEqual([t for c, _, _, t in log if c == 'BAD_HEADER'], ['1.BIN', '2.BIN'])
        self.assertEqual([t for c, _, _, t in log if c == 'LOADED'], ['3.BIN'])

    def test_block_size_tail_is_zeroed(self):
        a = test_sup('TSTA', self.rows((SITE_A, 1, NOP)), block_size=0x2000)
        cam = Camera(*card(('A.BIN', a)))
        cam.boot()
        blk = next(x for c, x, _, t in cam.log() if c == 'LOADED')
        self.assertEqual(bytes(cam.mu.mem_read(blk + len(a), 0x2000 - len(a))),
                         b'\0' * (0x2000 - len(a)))

    def test_survives_the_staging_buffer_being_freed(self):
        """Everything that runs after the load -- power-off, services -- is in
        the resident copy: the harness fills the freed staging with 0xDE."""
        a = test_sup('TSTA', self.rows((SITE_A, 2, NOP)))
        cam = Camera(*card(('A.BIN', a)))
        cam.boot()
        self.assertTrue(cam.freed)
        cam.power_off()
        self.assertEqual(cam.w(SITE_A), self.stock[SITE_A])

    def test_no_directory_loads_nothing_and_does_not_start_the_autorun(self):
        files, _ = card()
        cam = Camera(files, {})
        cam.boot()
        self.assertIn('NO_DIR', [c for c, *_ in cam.log()])
        self.assertEqual(cam.log()[-1][:2], ('DONE', 0))

    def test_chain_next_decodes_branches(self):
        cam = Camera(*card())
        cam.boot()
        svc = cam.state()
        fn = cam.w(svc + 16)                                     # chain_next
        site = HEAP + HEAP_SIZE - 0x1000                         # scratch: not the arena
        def ask(word_bytes, thumb):
            cam.mu.mem_write(site, word_bytes)
            return cam.call(fn & ~1, r0=svc, r1=site, r2=thumb, thumb=bool(fn & 1))[0]
        tgt = site - 0x200000                                    # within bl reach
        bl = 0xEB000000 | (((tgt - site - 8) >> 2) & 0xFFFFFF)
        self.assertEqual(ask(struct.pack('<I', bl), 0), tgt)
        self.assertEqual(ask(struct.pack('<I', NOP), 0), 0)
        # Thumb-2 BL forward 0x1000: S=0 J1=1 J2=1
        off = 0x1000
        h1 = 0xF000 | ((off >> 12) & 0x3FF)
        h2 = 0xD000 | 0x2800 | ((off >> 1) & 0x7FF)
        self.assertEqual(ask(struct.pack('<HH', h1, h2), 1), (site + 4 + off) | 1)

    def test_autorun_draws_frames_from_fpSup_UI(self):
        ar = B.autorun(pathlib.Path('/tmp')).decode()
        self.assertIn('display osdfile \\fpSup\\UI\\0.BIN', ar)
        self.assertNotIn('FPSUPUI', ar)

    def test_last_frame_after_the_load_then_redraw_restored(self):
        a = test_sup('TSTA', self.rows((SITE_A, 1, NOP)))
        cam = Camera(*card(('A.BIN', a)), stale={DRAW: DRAW_PAUSED})   # as the AutoRun left it
        cam.boot()
        self.assertEqual(cam.draws, [('\\fpSup\\UI\\4.BIN', DRAW_PAUSED)] * 3)
        self.assertEqual(cam.w(DRAW), DRAW_STOCK)
        self.assertEqual(cam.slept, 0)
        self.assertNotIn('D_SLEEP', cam.calls)
        self.assertIn('UI_FORCE', cam.calls)
        i = len(cam.calls) - cam.calls[::-1].index('TICK') - 1           # LOAD_DONE_US
        self.assertLess(i, cam.calls.index('D_FILE'))

    def test_shell_sup_zeroes_a_stale_claim_patches_the_interface_and_spawns(self):
        import patches
        iface, want, *_ = patches.IFACE[0]
        state = 0xC072F000
        img = IMAGE.read_bytes()
        cam = Camera(*card(('00SHELL.BIN', B.shell_sup())), stale={state: 0x4C485356})
        cam.boot()
        self.assertEqual(len(cam.tasks), 1)                          # spawn ran
        self.assertEqual(cam.w(state), 0x4C485356)                   # and claimed it
        self.assertEqual(cam.w(iface), want)
        ptp, off, *_ = patches.NOPTP[0]
        arm, skip, *_ = patches.NOPTP[1]
        self.assertEqual(word(img, ptp), 0xEB129F0D)                 # BL FUN_c04db778
        self.assertEqual(word(img, arm), 0x4628D01E)                 # beq; mov r0, r5
        self.assertEqual(cam.w(ptp), off)                            # PTP receive off
        self.assertEqual(cam.w(arm), skip)                           # and its auto-arm
        self.assertEqual([j[:2] for j in cam.journal()],
                         [(state, 96), (iface, 4), (ptp, 4), (arm, 4)])
        cam.power_off()
        self.assertEqual(cam.w(iface), word(img, iface))
        self.assertEqual(cam.w(ptp), word(img, ptp))                 # and back on
        self.assertEqual(cam.w(arm), word(img, arm))
        self.assertEqual(cam.w(state), 0)

    def test_shell_sup_can_leave_ptp_alone(self):
        import patches
        ptp, *_ = patches.NOPTP[0]
        cam = Camera(*card(('00SHELL.BIN', B.shell_sup(noptp=False))))
        cam.boot()
        self.assertEqual(len(cam.tasks), 1)
        self.assertEqual(cam.w(ptp), word(IMAGE.read_bytes(), ptp))

    def test_shell_sup_backs_off_when_the_interface_word_is_taken(self):
        import patches
        iface, want, *_ = patches.IFACE[0]
        img = IMAGE.read_bytes()
        other = test_sup('OTHR', [(iface, word(img, iface), 2, 0xDEADBEEF)])
        cam = Camera(*card(('00OTHER.BIN', other), ('10SHELL.BIN', B.shell_sup())))
        cam.boot()
        self.assertEqual(cam.tasks, [])                              # no worker
        self.assertEqual(cam.w(iface), 0xDEADBEEF)                   # the other's
        self.assertEqual(cam.w(0xC072F000), 0)                       # STATE untouched
        self.assertIn('10SHELL.BIN', [t for c, _, _, t in cam.log() if c == 'RELEASED'])

    def test_load_log_is_written_whole(self):
        a = test_sup('TSTA', self.rows((SITE_A, 1, NOP)))
        cam = Camera(*card(('10A.BIN', a)))
        cam.boot()
        log = cam.written['\\fpSup\\LOAD.LOG']
        self.assertEqual(len(log), 4096)
        lines = log.decode().rstrip(' \n').split('\n')
        self.assertTrue(lines[0].startswith('01 '))                     # START
        self.assertIn('0A', [l.split()[0] for l in lines])              # LOADED
        self.assertTrue(any(l.startswith('0A ') and l.endswith('10A.BIN') for l in lines))
        self.assertTrue(lines[-1].startswith('0E 00000001 '))           # DONE, one kept

    def test_padded_shell_sup_still_loads(self):
        """Historical padded sups remain readable; new builders emit real size."""
        sup = bytearray(B.shell_sup()) + bytes(256)
        struct.pack_into('<II', sup, 8, len(sup), len(sup))
        sup = bytes(sup)
        cam = Camera(*card(('00SHELL.BIN', sup)))
        cam.boot()
        self.assertEqual(len(cam.tasks), 1)

    def test_each_sup_is_told_its_own_path(self):
        """Service version 2: r2 = the file it was loaded from, resident (it
        must outlive the staging buffer the harness fills with 0xDE)."""
        from armasm import symbols
        seen = symbols(HERE / 'test_sup.S')['svc_seen'] + B.SL_HEADER_LEN
        a = test_sup('TSTA', self.rows((SITE_A, 1, NOP)))
        c = test_sup('TSTC', self.rows((SITE_C, 1, NOP)))
        cam = Camera(*card(('20RENAMED.BIN', c), ('10A.BIN', a)))
        cam.boot()
        blocks = {t: x for k, x, _, t in cam.log() if k == 'LOADED'}
        for name in ('10A.BIN', '20RENAMED.BIN'):
            path = cam.w(blocks[name] + seen + 8)
            self.assertEqual(cam.cstr(path), '\\fpSup\\' + name)
            st = cam.state()
            self.assertTrue(st <= path < st + O_NLOG, 'not in the resident state')

    def test_version_3_services(self):
        """holder(): who is in the books for a site, in load order, the running
        sup included; self(): the running sup's path; SL_SVC_AT: the table
        while entries run, 0 after; done_at_start = LOAD_DONE_US meanwhile."""
        from armasm import assemble, symbols
        src = HERE / 'test_svc3.S'
        probe = B.make_sup(assemble(src) + struct.pack('<2I', SITE_A, self.stock[SITE_A]),
                           B.SL_HEADER_LEN, 'PRB3')
        seen = symbols(src)['seen'] + B.SL_HEADER_LEN
        a = test_sup('TSTA', self.rows((SITE_A, 3, 0)))
        c = test_sup('TSTC', self.rows((SITE_C, 2, NOP)))
        x = test_sup('TSTX', self.rows((SITE_A, 3, 0), (SITE_B, 2, 0)))
        bad = test_sup('TSTB', self.rows((SITE_A, 3, 0), (SITE_C, 2, NOP)))  # refused
        cam = Camera(*card(('10A.BIN', a), ('20C.BIN', c), ('25B.BIN', bad),
                           ('30X.BIN', x), ('40P.BIN', probe)))
        cam.mu.mem_write(B.SL_SVC_AT - 4, struct.pack('<I', 0x1234))     # LOAD_DONE_US
        cam.boot()
        out = {t: k for k, _, _, t in cam.log() if k in ('LOADED', 'RELEASED')}
        self.assertEqual(out, {'10A.BIN': 'LOADED', '25B.BIN': 'RELEASED', '20C.BIN': 'LOADED',
                               '30X.BIN': 'LOADED', '40P.BIN': 'LOADED'})
        blk = next(x for k, x, _, t in cam.log() if k == 'LOADED' and t == '40P.BIN')
        w = [cam.w(blk + seen + 4 * i) for i in range(9)]
        st = cam.state()
        self.assertEqual(w[0], st, 'SL_SVC_AT during an entry')
        self.assertEqual(w[1], st)
        self.assertEqual(cam.cstr(w[2]), '\\fpSup\\40P.BIN')
        self.assertEqual((w[3], w[4]), (0x1234, 0x1234))
        names = [cam.cstr(p) if p else None for p in w[5:9]]
        self.assertEqual(names, ['\\fpSup\\10A.BIN', '\\fpSup\\30X.BIN',
                                 '\\fpSup\\40P.BIN', None])
        self.assertEqual(cam.w(B.SL_SVC_AT), 0, 'SL_SVC_AT after the load')
        self.assertNotEqual(cam.w(B.SL_SVC_AT - 4), 0x1234, 'LOAD_DONE_US written at the end')

    def test_state_layout(self):
        cam = Camera(*card())
        cam.boot()
        self.assertEqual(cam.log()[0][0], 'START')
        st = cam.state()
        self.assertEqual(cam.w(st), B.SL_SVC_VERSION)
        self.assertEqual(cam.w(st + O_POFF), st + O_POFF - 8)


if __name__ == '__main__':
    unittest.main()
