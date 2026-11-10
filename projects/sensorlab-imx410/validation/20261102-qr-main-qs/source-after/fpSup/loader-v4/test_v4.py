#!/usr/bin/env python3
"""Loader v4 under unicorn: the real loader.S (as the AutoRun spells it), the
real v4 LOADER.BIN, real sups (test_sup4.c, SUPMGR, SHELL), the real firmware
image; file/dir/allocator/power-off routines are v3/test_v3.py's Python stubs.

    cd fpSup/loader-v4 && python3 -B -m unittest test_v4
    python3 -B test_v4.py --mutate          # each mutant must fail a test

The heap is mapped twice, at 0x45000000 (the allocator's uncached alias) and
0xC5000000 (the cached alias) over the same host memory, so "ran at the
cached alias" is observable.  Caches themselves are not emulated.
"""
import ctypes, pathlib, re, shutil, struct, subprocess, sys, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell' / 'v3'))
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

import build_v4 as B
import build_v3 as V3
import test_v3 as T3
import cave
from armasm import assemble

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_PROT_ALL
    from unicorn.arm_const import UC_ARM_REG_R3
except ImportError:                                         # pragma: no cover
    Uc = None

HEAP, HEAP_SIZE, ALIAS = T3.HEAP, T3.HEAP_SIZE, 0x80000000
SITE_A, SITE_B, SITE_C = T3.SITE_A, T3.SITE_B, T3.SITE_C
NOP = T3.NOP
SVC_FIELDS = ['version', 'boot_id', 'claim', 'claim_res', 'chain_next', 'cave_alloc', 'publish',
              'log', 'holder', 'self', 'done_at_start', 'uncached', 'self_path', 'file_is',
              'provide', 'find', 'page_add', 'page_refresh', 'page_count', 'page_row',
              'sups_list', 'disabled_get', 'disabled_set', 'file_read', 'borrow', 'ui_go']
SVC_BYTES = 4 * len(SVC_FIELDS)
LOADER_SRC = None                                 # the mutation check swaps it


class Camera(T3.Camera):
    """v3's Camera with the heap mapped at both aliases."""
    def __init__(self, files, dirs, stale=None):
        self.files, self.dirs = files, dirs
        self.img = T3.IMAGE.read_bytes()
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        mu.mem_map(0xC0000000, 0x03000000)
        mu.mem_write(0xC0000000, self.img[:0x03000000])
        mu.mem_map(0xC3000000, 0x01000000)
        self._heapbuf = ctypes.create_string_buffer(HEAP_SIZE)
        ptr = ctypes.addressof(self._heapbuf)
        mu.mem_map_ptr(HEAP, HEAP_SIZE, UC_PROT_ALL, ptr)
        mu.mem_map_ptr(HEAP + ALIAS, HEAP_SIZE, UC_PROT_ALL, ptr)
        mu.mem_map(T3.STACK - 0x20000, 0x20000)
        mu.mem_map(T3.DONE, 0x1000)
        for a, v in V3.loader_words(V3.autorun(pathlib.Path('/tmp'))).items():
            mu.mem_write(a, struct.pack('<I', v))
        for a, v in (stale or {}).items():
            mu.mem_write(a, struct.pack('<I', v))
        for a in T3.F.values():
            mu.mem_write(a, struct.pack('<I', 0xE12FFF1E))
        self.heap_next = HEAP
        self.allocs, self.freed, self.registered, self.calls = {}, [], [], []
        self.dir_iter, self.fobj, self.misaligned, self.opened = {}, {}, [], []
        self.tasks, self.draws, self.slept, self.written = [], [], 0, {}
        self.by_addr = {v: k for k, v in T3.F.items()}
        self.now = 1_400_000
        self.error = None
        mu.hook_add(UC_HOOK_CODE, self._safe_hook)

    def _hook(self, mu, addr, size, data):
        if self.by_addr.get(addr) == 'MEM_FREE':        # tolerate either alias
            r1 = self.r(T3.UC_ARM_REG_R1)
            self.freed.append(r1 if r1 < ALIAS else r1 - ALIAS)
            return self._ret(0)
        return super()._hook(mu, addr, size, data)

    def _alloc(self, n, align=8):
        # the firmware allocator promises 8: hand out 8 past a 64-byte line every
        # time, so every piece of code that needs whole lines must align for itself
        p = ((self.heap_next + 63) & ~63) + 8
        self.heap_next = p + n
        self.allocs[p] = n
        self.mu.mem_write(p, b'\xA5' * n)        # not zero: the code must clear
        return p

    def svc(self):
        objs = {o - SVC_BYTES for o, _ in self.registered}
        assert len(objs) == 1, self.registered
        st = objs.pop()
        assert self.w(st) == B.SL4_LOADER_SVC, hex(self.w(st))
        return st

    def fn(self, name):
        return self.w(self.svc() + 4 * SVC_FIELDS.index(name))

    def callsvc(self, name, r1=0, r2=0, r3=0):
        f = self.fn(name)
        self.mu.reg_write(UC_ARM_REG_R3, r3 & 0xFFFFFFFF)
        r0, _ = self.call(f & ~1, r0=self.svc(), r1=r1, r2=r2, thumb=bool(f & 1))
        return r0

    def journal(self):
        obj = self.registered[0][0]
        e, out = self.w(obj + 8), []
        while self.w(e):
            a, n = self.w(e), self.w(e + 4)
            out.append((a, n, bytes(self.mu.mem_read(e + 8, n))))
            e += 8 + n
        return out

    def power_off(self):
        obj = self.registered[0][0]
        return self.call(self.w(self.w(obj) + 0xC), r0=obj, r1=4)

    def loadlog(self):
        text = self.written.get('\\fpSup\\LOAD.LOG', b'').decode('ascii', 'replace')
        out = []
        for line in text.splitlines():
            m = re.match(r'^([0-9A-F]{2}) ([0-9A-F]{8}) ([0-9A-F]{8}) ?(.*)$', line)
            if m:
                out.append((int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16), m.group(4).strip()))
        return out


CODES = {'LOADED': 10, 'RELEASED': 11, 'REPAIRED': 12, 'DISABLED': 19, 'OLD': 20,
         'BAD': 6, 'CLAIM': 18, 'DUP': 7, 'DONE': 14, 'CONFLICT': 16}


def cfg(claims=(), rows=(), provide=(0, 0), find=0, release=0):
    b = struct.pack('<I', len(claims))
    for c in list(claims) + [(0, 0, 0, 0)] * (4 - len(claims)):
        b += struct.pack('<4I', *c)
    b += struct.pack('<I', len(rows))
    for kind, title in list(rows) + [(0, '')] * (6 - len(rows)):
        b += struct.pack('<I', kind) + title.encode().ljust(20, b'\0')
    b += struct.pack('<4I', provide[0], provide[1], find, release)
    assert len(b) == 232
    return b


O_OUT = 48 + 232                                     # out_svc in the block
OUT = ['svc', 'block', 'path', 'self', 'self_path', 'find', 'uncached', 'fileis', 'pc', 'fileis_bad']
O_ROWS, O_OPENED, O_TOGGLED, O_ROWMEM = 48 + 272, 48 + 296, 48 + 320, 48 + 344
O_PROVIDE = 48 + 536


def sid(s):
    return struct.unpack('<I', s.encode().ljust(4, b'\0'))[0]


def card(*sups, extra=(), loader=None):
    vbin = loader if loader is not None else B.loader_bin(src=LOADER_SRC)[0]
    files = {'\\fpSup\\LOADER.BIN': vbin}
    ents = [('LOADER.BIN', 0x20, len(vbin))]
    for name, data in sups:
        files['\\fpSup\\' + name] = data
        ents.append((name, 0x20, len(data)))
    ents += list(extra)
    return files, {'\\fpSup': ents}


def boot(*sups, **kw):
    stale = kw.pop('stale', None)
    cam = Camera(*card(*sups, **kw), stale=stale)
    cam.boot()
    return cam


def blocks(cam):
    """{name: run address} from LOAD.LOG's LOADED lines."""
    return {t: a for c, a, _, t in cam.loadlog() if c == CODES['LOADED']}


def outs(cam, base):
    return dict(zip(OUT, struct.unpack('<10I', cam.mu.mem_read(base + O_OUT, 40))))


@unittest.skipIf(Uc is None or not T3.IMAGE.exists(), 'needs unicorn and the image')
class LoaderV4Tests(unittest.TestCase):
    def setUp(self):
        img = T3.IMAGE.read_bytes()
        self.stock = {a: T3.word(img, a) for a in (SITE_A, SITE_B, SITE_C)}

    def ts(self, sup_id, **kw):
        flags = kw.pop('flags', B.SL_F_CACHED_OK)
        name = kw.pop('name', None)
        dma = kw.pop('dma', (0, 0))
        return B.test_sup(cfg(**kw), sup_id, flags=flags, name=name, dma=dma)

    # --- loading ---------------------------------------------------------
    def test_alphabetical_order_and_old_format_refused(self):
        v3sup = T3.test_sup('OLD3', [(SITE_B, self.stock[SITE_B], 2, NOP)])
        cam = boot(('ZED.BIN', self.ts('ZEDD')), ('ALPHA.BIN', self.ts('ALPH')),
                   ('OLDV3.BIN', v3sup), ('mid.bin', self.ts('MIDD')),
                   extra=[('._ALPHA.BIN', 0x20, 4096), ('NOTE.TXT', 0x20, 3)])
        log = cam.loadlog()
        self.assertEqual([t for c, _, _, t in log if c == CODES['LOADED']],
                         ['ALPHA.BIN', 'mid.bin', 'ZED.BIN'])
        self.assertEqual([t for c, _, _, t in log if c == CODES['OLD']], ['OLDV3.BIN'])
        self.assertEqual(cam.w(SITE_B), self.stock[SITE_B])          # the v3 sup never ran
        self.assertEqual(cam.misaligned, [])

    def test_a_newer_version_of_one_name_wins(self):
        """Gyro2_v0.1.0.BIN beside Gyro2_v0.2.0.BIN (the user 2026-10-25: the
        version rides on the file name): the newer loads, the older is the
        duplicate sup_id -- whatever their alphabetical order."""
        cam = boot(('Gyro2_v0.1.0.BIN', self.ts('GYRO')), ('Gyro2_v0.10.0.BIN', self.ts('GYRO')),
                   ('Gyro2_v0.2.0.BIN', self.ts('GYRO')), ('Gyro2_v0.10.0test.BIN', self.ts('GYRO')),
                   ('Alpha.BIN', self.ts('ALPH')))
        log = cam.loadlog()
        self.assertEqual([t for c, _, _, t in log if c == CODES['LOADED']], ['Alpha.BIN', 'Gyro2_v0.10.0.BIN'])
        self.assertEqual([t for c, _, _, t in log if c == CODES['DUP']],
                         ['Gyro2_v0.10.0test.BIN', 'Gyro2_v0.2.0.BIN', 'Gyro2_v0.1.0.BIN'])

    def test_log_counts_claims_instead_of_listing_them(self):
        cam = boot(('A.BIN', self.ts('AAAA', claims=[(SITE_A, self.stock[SITE_A], 2, NOP),
                                                      (SITE_B, self.stock[SITE_B], 2, NOP)])))
        log = cam.loadlog()
        loaded = [b for c, _, b, t in log if c == CODES['LOADED']]
        self.assertEqual(loaded, [2])
        self.assertFalse([1 for c, *_ in log if c == CODES['CLAIM']])

    def test_bad_dma_range_is_a_bad_header(self):
        bad = self.ts('BADD', dma=(0x7FFFFFF0, 0x100))
        cam = boot(('B.BIN', bad))
        self.assertIn('B.BIN', [t for c, _, _, t in cam.loadlog() if c == CODES['BAD']])

    # --- cached execution --------------------------------------------------
    def test_core_runs_at_the_cached_alias(self):
        cam = boot()
        st = cam.svc()
        self.assertGreaterEqual(st, HEAP + ALIAS)
        self.assertGreaterEqual(cam.fn('claim') & ~1, HEAP + ALIAS)
        self.assertGreaterEqual(cam.registered[0][0], HEAP + ALIAS)

    def test_cached_ok_sup_runs_at_cached_alias_aligned(self):
        cam = boot(('C.BIN', self.ts('CACH')), ('U.BIN', self.ts('UNCA', flags=0)))
        b = blocks(cam)
        c, u = outs(cam, b['C.BIN']), outs(cam, b['U.BIN'])
        self.assertGreaterEqual(c['block'], HEAP + ALIAS)
        self.assertEqual(c['block'] % 64, 0)
        self.assertTrue(c['block'] <= c['pc'] & ~1 < c['block'] + 0x2000)    # code ran there
        self.assertEqual(c['uncached'], c['block'] - ALIAS + B.SL4_HEADER_LEN)
        self.assertLess(u['block'], ALIAS)
        self.assertEqual(u['block'] % 64, 0)
        self.assertEqual(u['uncached'], u['block'] + B.SL4_HEADER_LEN)
        # same memory, both views
        self.assertEqual(bytes(cam.mu.mem_read(c['block'], 48)), bytes(cam.mu.mem_read(c['block'] - ALIAS, 48)))

    def test_bss_is_zero_and_padding_whole_lines(self):
        cam = boot(('C.BIN', self.ts('CACH')))
        b = blocks(cam)['C.BIN']
        data = B.test_sup(cfg(), 'CACH')
        blk = struct.unpack_from('<I', data, 12)[0]
        tail = bytes(cam.mu.mem_read(b + len(data), ((blk + 63) & ~63) - len(data)))
        self.assertEqual(set(tail), {0})

    # --- path, file_is, provide/find ---------------------------------------
    def test_self_path_and_file_is(self):
        cam = boot(('RESCUS.BIN', self.ts('RCUS')))
        o = outs(cam, blocks(cam)['RESCUS.BIN'])
        self.assertEqual(cam.cstr(o['path']), '\\fpSup\\RESCUS.BIN')
        self.assertEqual(cam.cstr(o['self']), '\\fpSup\\RESCUS.BIN')
        self.assertEqual(cam.cstr(o['self_path']), '\\fpSup\\RESCUS.BIN')
        self.assertEqual(o['fileis'], 0)
        self.assertEqual(o['fileis_bad'], 0xFFFFFFFC)                 # SL_NOT_SELF
        # after the boot, from any address in the block (either alias)
        p = cam.callsvc('self_path', o['block'] + 100)
        self.assertEqual(cam.cstr(p), '\\fpSup\\RESCUS.BIN')
        p = cam.callsvc('self_path', o['block'] - ALIAS + 100)
        self.assertEqual(cam.cstr(p), '\\fpSup\\RESCUS.BIN')
        self.assertEqual(cam.callsvc('self_path', 0xC0001000), 0)

    def test_file_is_never_creates(self):
        cam = boot(('A.BIN', self.ts('AAAA')))
        path = 0xC3000400
        cam.mu.mem_write(path, b'\\fpSup\\GONE.BIN\0')
        r = cam.callsvc('file_is', path, 0xC3000500, 16)
        self.assertEqual(r, 0xFFFFFFFC)
        self.assertNotIn('\\fpSup\\GONE.BIN', cam.written)

    def test_provide_and_find_across_sups(self):
        svc_id = 0x56435253                                         # "SRCV"
        cam = boot(('A.BIN', self.ts('AAAA', provide=(svc_id, 0xC043CCF9))),
                   ('B.BIN', self.ts('BBBB', find=svc_id)),
                   ('C.BIN', self.ts('CCCC', provide=(svc_id, 0x1234))))
        b = blocks(cam)
        self.assertEqual(outs(cam, b['B.BIN'])['find'], 0xC043CCF9)
        self.assertEqual(cam.callsvc('find', svc_id), 0xC043CCF9)    # the second provide lost
        self.assertEqual(cam.callsvc('find', 0x11111111), 0)
        prov = lambda n: struct.unpack('<i', cam.mu.mem_read(b[n] + O_PROVIDE, 4))[0]
        self.assertEqual((prov('A.BIN'), prov('C.BIN')), (0, -1))     # SL_OK, SL_CONFLICT

    def test_cave_alloc_unchanged(self):
        cam = boot()
        a = cam.callsvc('cave_alloc', 24)
        b = cam.callsvc('cave_alloc', 24)
        self.assertEqual(a, (cave.CAVE_ARENA + 7) & ~7)                # v3's rule
        self.assertEqual(b, a + 24)
        self.assertEqual(cam.w(cave.CAVE_BUMP), a + 48)

    # --- the fpSup page ------------------------------------------------------
    def test_rows_sorted_by_title_supmanager_first(self):
        cam = boot(('ALPHA.BIN', self.ts('ALPH', rows=[(1, 'zebra'), (2, 'Apple')])),
                   ('SUPMGR.BIN', B.supmgr_sup()),
                   ('ZZ.BIN', self.ts('ZZZZ', rows=[(4, 'mango'), (1, 'banana')])))
        n = cam.callsvc('page_count')
        titles = [cam.cstr(cam.w(cam.callsvc('page_row', i) + 4)) for i in range(n)]
        self.assertEqual(titles, ['SupManager', 'Apple', 'banana', 'mango', 'zebra'])
        self.assertEqual(cam.callsvc('page_row', n), 0)

    def test_paging_slot_mapping(self):
        rows = [(1, f'R{i:02d}') for i in range(6)]
        cam = boot(('A.BIN', self.ts('AAAA', rows=rows)), ('B.BIN', self.ts('BBBB', rows=rows[:5])))
        n = cam.callsvc('page_count')
        self.assertEqual(n, 11)
        pages = (n + B_PAGE_ROWS - 1) // B_PAGE_ROWS
        self.assertEqual(pages, 3)
        t = [cam.cstr(cam.w(cam.callsvc('page_row', p * 5 + k) + 4))
             for p in range(pages) for k in range(5) if p * 5 + k < n]
        self.assertEqual(t, sorted(t, key=str.upper))

    def test_total_limit_64_and_bad_rows(self):
        sups = [(f'S{i:02d}.BIN', self.ts(f'S{i:03d}', rows=[(1, f'r{i}{k}') for k in range(6)])) for i in range(11)]
        cam = boot(*sups)
        self.assertEqual(cam.callsvc('page_count'), 64)
        last = outs(cam, blocks(cam)['S10.BIN'])
        res = struct.unpack('<6i', cam.mu.mem_read(blocks(cam)['S10.BIN'] + O_ROWS, 24))
        self.assertEqual(sum(1 for r in res if r == -2), 2)            # SL_FULL
        bad = boot(('A.BIN', self.ts('AAAA', rows=[(9, 'x'), (1, 'ok')])))
        res = struct.unpack('<6i', bad.mu.mem_read(blocks(bad)['A.BIN'] + O_ROWS, 24))
        self.assertEqual(res[:2], (-3, 0))
        del last

    def test_released_sup_leaves_no_rows_or_service(self):
        cam = boot(('A.BIN', self.ts('AAAA', rows=[(1, 'gone')], provide=(7, 9), release=1)),
                   ('B.BIN', self.ts('BBBB', rows=[(1, 'kept')])))
        self.assertEqual(cam.callsvc('page_count'), 1)
        self.assertEqual(cam.cstr(cam.w(cam.callsvc('page_row', 0) + 4)), 'kept')
        self.assertEqual(cam.callsvc('find', 7), 0)

    def test_row_callbacks_are_resident(self):
        cam = boot(('A.BIN', self.ts('AAAA', rows=[(1, 'jump'), (2, 'toggle')])))
        row = cam.callsvc('page_row', 0)                                   # "jump"
        f = cam.w(row + 24)
        cam.call(f & ~1, r0=cam.w(row + 28), thumb=bool(f & 1))
        base = blocks(cam)['A.BIN']
        self.assertEqual(cam.w(base + O_OPENED), 1)
        row = cam.callsvc('page_row', 1)                                   # "toggle": set(arg, 1)
        f = cam.w(row + 16)
        cam.call(f & ~1, r0=cam.w(row + 28), r1=1, thumb=bool(f & 1))
        self.assertEqual(cam.w(base + O_TOGGLED + 4), 1)

    # --- disabled list -------------------------------------------------------
    def test_list_applies_with_supmanager(self):
        loader = B.with_disabled(B.loader_bin(src=LOADER_SRC)[0], ['BBBB', 'SMGR'])
        cam = boot(('A.BIN', self.ts('AAAA')), ('B.BIN', self.ts('BBBB')),
                   ('SUPMGR.BIN', B.supmgr_sup()), loader=loader)
        log = cam.loadlog()
        self.assertEqual([t for c, _, _, t in log if c == CODES['DISABLED']], ['B.BIN'])
        self.assertIn('SUPMGR.BIN', blocks(cam))                      # never disabled
        self.assertEqual(cam.callsvc('disabled_get', sid('BBBB')), 1)

    def test_list_ignored_without_supmanager(self):
        loader = B.with_disabled(B.loader_bin(src=LOADER_SRC)[0], ['BBBB'])
        cam = boot(('A.BIN', self.ts('AAAA')), ('B.BIN', self.ts('BBBB')), loader=loader)
        self.assertEqual(sorted(blocks(cam)), ['A.BIN', 'B.BIN'])

    def test_disabled_set_writes_loader_back_and_refuses_supmanager(self):
        cam = boot(('A.BIN', self.ts('AAAA')), ('SUPMGR.BIN', B.supmgr_sup()))
        self.assertEqual(cam.callsvc('disabled_set', sid('SMGR'), 1), 0xFFFFFFFD)   # BADARG
        self.assertNotIn('\\fpSup\\LOADER.BIN', cam.written)
        self.assertEqual(cam.callsvc('disabled_set', sid('AAAA'), 1), 0)
        new = cam.written['\\fpSup\\LOADER.BIN']
        orig = cam.files['\\fpSup\\LOADER.BIN']
        self.assertEqual(len(new), len(orig))
        tail = new[-(8 + 4 * B.DS_MAX):]
        self.assertEqual(struct.unpack_from('<3I', tail), (B.DS_MAGIC, 1, sid('AAAA')))
        self.assertEqual(new[:64], orig[:64])
        self.assertEqual(cam.callsvc('disabled_get', sid('AAAA')), 1)
        self.assertEqual(cam.callsvc('disabled_set', sid('AAAA'), 0), 0)
        tail = cam.written['\\fpSup\\LOADER.BIN'][-(8 + 4 * B.DS_MAX):]
        self.assertEqual(struct.unpack_from('<2I', tail), (B.DS_MAGIC, 0))

    def test_disabled_set_refuses_a_replaced_loader_file(self):
        cam = boot(('A.BIN', self.ts('AAAA')), ('SUPMGR.BIN', B.supmgr_sup()))
        cam.files['\\fpSup\\LOADER.BIN'] = b'VBIN' + b'\x99' * 200
        self.assertEqual(cam.callsvc('disabled_set', sid('AAAA'), 1), 0xFFFFFFFC)
        self.assertNotIn('\\fpSup\\LOADER.BIN', cam.written)

    def test_sups_list_for_supmanager(self):
        loader = B.with_disabled(B.loader_bin(src=LOADER_SRC)[0], ['BBBB'])
        v3sup = T3.test_sup('OLD3', [])
        cam = boot(('A.BIN', self.ts('AAAA', name='Alpha Sup')), ('B.BIN', self.ts('BBBB')),
                   ('OLD.BIN', v3sup), ('SUPMGR.BIN', B.supmgr_sup()), loader=loader)
        info, i = [], 0
        out = 0xC3000600
        while cam.callsvc('sups_list', i, out) == 0:
            name, disp, ident, ver, status, nxt = struct.unpack('<6I', cam.mu.mem_read(out, 24))
            info.append((cam.cstr(name), cam.cstr(disp), status, nxt))
            i += 1
        self.assertEqual(info, [('A.BIN', 'Alpha Sup', 1, 1), ('B.BIN', 'B.BIN', 3, 0),
                                ('OLD.BIN', 'OLD.BIN', 4, 0), ('SUPMGR.BIN', 'SupManager', 1, 1)])

    # --- books -----------------------------------------------------------------
    def test_power_off_restores_and_stale_patch_repaired(self):
        cam = boot(('A.BIN', self.ts('AAAA', claims=[(SITE_A, self.stock[SITE_A], 2, NOP)])),
                   stale={SITE_A: 0xEB0DEAD0})
        self.assertEqual(cam.w(SITE_A), NOP)
        self.assertIn(CODES['REPAIRED'], [c for c, *_ in cam.loadlog()])
        self.assertEqual(cam.journal(), [(SITE_A, 4, struct.pack('<I', self.stock[SITE_A]))])
        cam.power_off()
        self.assertEqual(cam.w(SITE_A), self.stock[SITE_A])

    def test_stale_site_is_stock_before_anyone_writes_it(self):
        cam = boot(('A.BIN', self.ts('AAAA', claims=[(SITE_A, self.stock[SITE_A], 1, 0)])),
                   stale={SITE_A: 0xEB0DEAD0})
        self.assertEqual(cam.w(SITE_A), self.stock[SITE_A])

    def test_conflict_releases_and_undoes(self):
        cam = boot(('A.BIN', self.ts('AAAA', claims=[(SITE_A, self.stock[SITE_A], 2, NOP)])),
                   ('B.BIN', self.ts('BBBB', claims=[(SITE_B, self.stock[SITE_B], 2, 0xE1A01001),
                                                     (SITE_A, self.stock[SITE_A], 2, 0xE1A02002)])))
        self.assertIn('B.BIN', [t for c, _, _, t in cam.loadlog() if c == CODES['RELEASED']])
        self.assertEqual(cam.w(SITE_B), self.stock[SITE_B])
        self.assertEqual(cam.w(SITE_A), NOP)

    # --- the real sups ---------------------------------------------------------
    def test_supmanager_registers_and_provides_toggle(self):
        cam = boot(('A.BIN', self.ts('AAAA')), ('SUPMGR.BIN', B.supmgr_sup()))
        b = blocks(cam)['SUPMGR.BIN']
        self.assertGreaterEqual(b, HEAP + ALIAS)
        f = cam.callsvc('find', sid('SMGR'))
        self.assertTrue(b <= (f & ~1) < b + 0x400, hex(f))
        # toggle row 0 (A.BIN) through SupManager's own function
        ctl = b + ((struct.unpack_from('<I', B.supmgr_sup(), 8)[0] + 7) & ~7)
        r0, _ = cam.call(f & ~1, r0=ctl, r1=0, thumb=bool(f & 1))
        self.assertEqual(r0, 0)
        self.assertEqual(cam.callsvc('disabled_get', sid('AAAA')), 1)

    def test_shell_loads_as_v4(self):
        cam = boot(('SHELL.BIN', B.shell_sup()))
        self.assertIn('SHELL.BIN', blocks(cam))
        self.assertLess(blocks(cam)['SHELL.BIN'], ALIAS)               # not SL_F_CACHED_OK
        self.assertTrue(cam.tasks, 'the worker was not spawned')


B_PAGE_ROWS = 5

MUTANTS = [
    ('run cached', 'u32 run = (flags & SL_F_CACHED_OK) ? cached((u32)(uintptr_t)ub) : (u32)(uintptr_t)ub;',
     'u32 run = (u32)(uintptr_t)ub; (void)flags;'),
    ('core cached', 'u8 *res = (u8 *)(uintptr_t)cached((u32)(uintptr_t)ub);', 'u8 *res = ub;'),
    ('align 64', 'u8 *ub = (u8 *)(uintptr_t)(((u32)(uintptr_t)raw + LINE - 1) & ~(LINE - 1));\n    got',
     'u8 *ub = raw;\n    got'),
    ('old format accepted', 'if (got >= 4 && h->magic == SL3_MAGIC) {', 'if (0) {'),
    ('list without smgr', 'if (st->has_smgr && h->sup_id != SL_SMGR_ID && listed(st, h->sup_id)) {',
     'if (h->sup_id != SL_SMGR_ID && listed(st, h->sup_id)) {'),
    ('smgr disables itself', 'if (!id || id == SL_SMGR_ID) return SL_BADARG;', 'if (!id) return SL_BADARG;'),
    ('smgr disabled by list', 'if (st->has_smgr && h->sup_id != SL_SMGR_ID && listed',
     'if (st->has_smgr && listed'),
    ('sort ignores smgr', 'if (sa != sb) return sa > sb;', '(void)sa; (void)sb;'),
    ('sort reversed', 'return ncmp(a->row->title, b->row->title) < 0;', 'return ncmp(a->row->title, b->row->title) > 0;'),
    ('no total cap', 'if (st->nrows >= SL_PAGE_MAX) return SL_FULL;', 'if (st->nrows >= 999) return SL_FULL;'),
    ('released rows kept', 'if (st->rows[i].owner != st->cur) st->rows[k++] = st->rows[i];', 'st->rows[k++] = st->rows[i];'),
    ('file_is lies', 'differs(buf, expect, n)) ? SL_NOT_SELF : SL_OK;', 'differs(buf, expect, 0)) ? SL_NOT_SELF : SL_OK;'),
    ('disabled_set unchecked', 'int r = svc_file_is(svc, path, st->file, 64);', 'int r = SL_OK;'),
    ('provide overwrites', 'if (st->serv[i].id == id) return SL_CONFLICT;', 'if (0) return SL_CONFLICT;'),
    ('self_path uncached view', '(a >= u && a < u + s->size)', '(u && 0)'),
    ('claims listed', 'u32 nc = 0;', 'for (u32 i = st->cmark; i < st->nclaims; i++) logrec(st, L_CLAIM, 0, 0, 0);\n        u32 nc = 0;'),
    ('dma unchecked', '&& (!h->dma_len || (h->dma_off + h->dma_len <= h->block_size && h->dma_off + h->dma_len > h->dma_off))', ''),
    ('no repair', 'copy((void *)(uintptr_t)addr, stock, len);\n            publish();', 'publish();'),
    ('bss not zeroed', 'zero(ub + len, ((size + LINE - 1) & ~(LINE - 1)) - len);', ''),
    ('released services kept', 'st->nserv = smark;', '(void)smark;'),
]


def mutate():
    global LOADER_SRC
    src = (HERE / 'sloader4.c').read_text()
    failed = []
    with tempfile.TemporaryDirectory(prefix='slv4mut-') as t:
        for name, old, new in MUTANTS:
            if src.count(old) != 1:
                failed.append(f'{name}: pattern not found once')
                continue
            p = pathlib.Path(t) / 'sloader4.c'
            p.write_text(src.replace(old, new))
            shutil.copy(HERE / 'sloader4.h', pathlib.Path(t) / 'sloader4.h')
            LOADER_SRC = p
            try:
                B.loader_bin(src=p)
            except Exception as e:
                failed.append(f'{name}: does not build ({e})')
                continue
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(LoaderV4Tests)
            res = unittest.TextTestRunner(stream=open('/dev/null', 'w'), verbosity=0).run(suite)
            killed = bool(res.failures or res.errors)
            print(f'{"caught " if killed else "SURVIVED"} {name}', flush=True)
            if not killed:
                failed.append(name)
    LOADER_SRC = None
    print('mutants:', len(MUTANTS), 'survived/invalid:', failed)
    return not failed


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        sys.exit(0 if mutate() else 1)
    unittest.main()
