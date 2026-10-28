#!/usr/bin/env python3
"""Offline checks for the pre-capture P3 resident (time-based 4-slot hold).

    python3 -B -m unittest test_precap_p3 -v
"""
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_precap3  # noqa: E402

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE  # noqa: E402
from unicorn import arm_const as REG  # noqa: E402
from cave import CAVE_ARENA  # noqa: E402

H_GET, H_ADDR = 0xC001D740, 0xC001D7F0
F_DCACHE, F_ICACHE, F_TICK_US = 0xC000E91C, 0xC000EABC, 0xC002B6E0
F_KIND, F_KEYMON, F_ENQ, F_DISP = 0xC0397B30, 0xC02DBAF0, 0xC02DBBE8, 0xC02DC138
F_JOBDB, F_JOBGET = 0xC0374220, 0xC03753C0
F_CAP, F_REFUND = 0xC03A4620, 0xC03A46B8
F_RAWOBJ, F_DROPRW, F_DROPJB = 0xC0377348, 0xC0377730, 0xC0375030
F_ENQUEUE = 0xC037AF20
CAVE_BUMP = 0xC072E060
(SITE_A, _, _), (SITE_B, _, _), (SITE_D, _, _) = build_precap3.SITES
VENEER_LDR = 0xE51FF004
KEYMON, JOBDB, CAP, RAWOBJ = 0xC3425684, 0xC351FF44, 0xC359BE2C, 0xC35200E4
JOBS, YUV = 0x51000000, 0xC35201E0
S1ON, S1OFF, S2ON, S2OFF = 4, 5, 6, 7
TIMEOUT_US, INTERVAL = 10_000_000, 167_000
JOB_SIZE = 0x1200

STAGING, STACK, STOP, TARGET, HEAP = 0x42000000, 0x10000000, 0x10100000, 0x10200000, 0x50000000
CAVE_START = CAVE_ARENA
HEAP_RETURN = HEAP + 4
P = dict(count_a=0x08, count_b=0x0C, first_us=0x10, last_us=0x14, seq=0x18, ring_n=0x1C,
         pre=0x20, t0=0x24, tmo=0x28, inj=0x2C, s1c=0x30, tmof=0x34, disp=0x38, gate=0x3C,
         held=0x40, dropped=0x44, evicted=0x48, committed=0x4C, abandoned=0x50,
         origin=0x54, lock=0x58, head=0x5C, n=0x60, keep=0x68)
CALLEE_SAVED = ('r4', 'r5', 'r6', 'r7', 'r8', 'r9', 'r10', 'r11')
SINGLETON_GUARDS = (0xC35A9530, 0xC31F8C90, 0xC358CB48, 0xC3074980, 0xC3075684)
DROP_GUARDS = (0xC35200D8, 0xC35201D4, 0xC359BE44)
SSTACK = 0xC3075670


def live_camera_state():
    words = {guard: 1 for guard in SINGLETON_GUARDS + DROP_GUARDS}
    words.update({SSTACK + 0xC: 1, SSTACK + 0x10: 0, SSTACK: 0xC3100000})
    return words


def job_addr(job_id):
    return JOBS + job_id * JOB_SIZE


def u32(uc, address):
    return struct.unpack('<I', uc.mem_read(address, 4))[0]


def bl_target(site, word):
    if word >> 24 != 0xEB:
        raise AssertionError(f'0x{word:08X} at 0x{site:08X} is not bl')
    offset = word & 0x00FFFFFF
    if offset & 0x00800000:
        offset -= 1 << 24
    return site + 8 + offset * 4


def reg(name):
    return getattr(REG, f'UC_ARM_REG_{name.upper()}')


class Harness:
    def __init__(self, *, site_words=None, heap_return=HEAP_RETURN, cave_start=CAVE_START, kind=9,
                 camera_words=None):
        self.blob, self.info = build_precap3.build_blob()
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        rom = build_precap3.p1.rom_path().read_bytes()
        self.uc.mem_map(0xC0000000, 0x04000000)
        self.uc.mem_write(0xC0000000, rom[:0x04000000])
        for address, size in ((STAGING, 0x10000), (STACK, 0x10000), (STOP, 0x1000),
                              (TARGET, 0x1000), (HEAP, 0x10000), (JOBS, 0x40000)):
            self.uc.mem_map(address, size)
        self.uc.mem_write(STAGING, self.blob)
        self.uc.mem_write(CAVE_BUMP, struct.pack('<I', cave_start))
        for site, word in (site_words or {}).items():
            self.uc.mem_write(site, struct.pack('<I', word))
        for address, word in (live_camera_state() if camera_words is None else camera_words).items():
            self.uc.mem_write(address, struct.pack('<I', word))
        self.alive = {}
        for job_id in range(32):
            addr = job_addr(job_id)
            self.alive[job_id] = True
            self.uc.mem_write(JOBDB + 4 + job_id * 4, struct.pack('<I', addr))
            self.uc.mem_write(addr + 0xFFC, struct.pack('<I', 0x1000 + job_id))
            self.uc.mem_write(addr + 0x10FC, struct.pack('<I', job_id))
        self.heap_return = heap_return
        self.kind = kind
        self.tick = 1000
        self.tick_step = 55_555
        self.calls = []
        self.dispatched = []
        self.posted = []
        self.refunds = []
        self.raw_drops = []
        self.job_drops = []
        self.enqueued = []
        self.site_writes = []
        self.target_hits = []
        intercepted = (H_GET, H_ADDR, F_DCACHE, F_ICACHE, F_TICK_US, F_KIND, F_KEYMON,
                       F_ENQ, F_DISP, F_JOBDB, F_JOBGET, F_CAP, F_REFUND, F_RAWOBJ,
                       F_DROPRW, F_DROPJB, F_ENQUEUE, STOP, TARGET)
        for address in intercepted:
            self.uc.hook_add(UC_HOOK_CODE, self._intercept, begin=address, end=address)
        for site in (SITE_A, SITE_B, SITE_D):
            self.uc.hook_add(UC_HOOK_MEM_WRITE, self._site_write, begin=site, end=site + 3)

    def _return(self, value=None):
        if value is not None:
            self.uc.reg_write(REG.UC_ARM_REG_R0, value)
        self.uc.reg_write(REG.UC_ARM_REG_PC, self.uc.reg_read(REG.UC_ARM_REG_LR))

    def _intercept(self, uc, address, _size, _user):
        if address == STOP:
            uc.emu_stop()
            return
        if address == TARGET:
            self.target_hits.append({name: uc.reg_read(reg(name))
                                     for name in ('r0', 'r1', 'r2', 'r3', 'lr', 'sp')})
            uc.emu_stop()
            return
        r0, r1, r2 = (uc.reg_read(reg(n)) for n in ('r0', 'r1', 'r2'))
        self.calls.append((address, uc.reg_read(REG.UC_ARM_REG_SP), r0, r1))
        if address == H_GET:
            uc.mem_write(r0, struct.pack('<I', self.heap_return))
            self._return(0)
        elif address == H_ADDR:
            self._return(u32(uc, r0))
        elif address == F_TICK_US:
            self.tick += self.tick_step
            self._return(self.tick & 0xFFFFFFFF)
        elif address == F_KIND:
            self._return(self.kind)
        elif address == F_KEYMON:
            self._return(KEYMON)
        elif address == F_ENQ:
            self.posted.append((r0, r1))
            self._return()
        elif address == F_DISP:
            self.dispatched.append((r0, r1))
            for name in ('r0', 'r1', 'r2', 'r3', 'ip'):
                uc.reg_write(reg(name), 0xBAD0BAD0)
            self._return()
        elif address == F_JOBDB:
            self._return(JOBDB)
        elif address == F_JOBGET:
            job_id = r1
            if job_id < 32 and self.alive.get(job_id):
                self._return(job_addr(job_id))
            else:
                self._return(0)
        elif address == F_CAP:
            self._return(CAP)
        elif address == F_REFUND:
            self.refunds.append((r0, r1, r2))
            self._return()
        elif address == F_RAWOBJ:
            self._return(RAWOBJ)
        elif address == F_DROPRW:
            self.raw_drops.append((r0, r1))
            self._return(1)
        elif address == F_DROPJB:
            self.job_drops.append((r0, r1))
            self.alive[r1] = False
            self._return()
        elif address == F_ENQUEUE:
            self.enqueued.append((r0, r1, r2))
            self._return(1)
        else:
            self._return()

    def _site_write(self, _uc, _access, address, _size, value, _user):
        caches = sum(1 for call in self.calls if call[0] in (F_DCACHE, F_ICACHE))
        self.site_writes.append((address, value, caches))

    def run_launcher(self):
        self.uc.reg_write(REG.UC_ARM_REG_SP, STACK + 0xF000)
        self.uc.reg_write(REG.UC_ARM_REG_LR, STOP)
        self.uc.emu_start(STAGING, STOP, count=200_000)
        if self.uc.reg_read(REG.UC_ARM_REG_SP) != STACK + 0xF000:
            raise AssertionError('launcher did not restore SP')

    def resident(self):
        veneer = bl_target(SITE_A, u32(self.uc, SITE_A))
        return u32(self.uc, veneer + 4) - self.info['stub_a']

    def field(self, name):
        return u32(self.uc, self.resident() + P[name])

    def keep_slots(self):
        base = self.resident() + P['keep']
        n, head = self.field('n'), self.field('head')
        rows = []
        for i in range(n):
            off = ((head + i) & 3) * 16
            rows.append(struct.unpack('<4I', self.uc.mem_read(base + off, 16)))
        return rows

    def run_frame(self, site=SITE_B, r0=YUV, r1=1, expect='hold'):
        sp = STACK + 0xE000
        self.target_hits.clear()
        for name, value in (('r0', r0), ('r1', r1), ('r2', 1), ('r3', TARGET),
                            ('sp', sp), ('lr', site + 4)):
            self.uc.reg_write(reg(name), value)
        self.uc.emu_start(site, site + 4, count=50_000)
        if expect == 'pass':
            if len(self.target_hits) != 1:
                raise AssertionError('expected the original enqueue exactly once')
            return self.target_hits[0], sp
        if self.target_hits:
            raise AssertionError('held/dropped frame still reached the original enqueue')
        if self.uc.reg_read(REG.UC_ARM_REG_PC) != site + 4:
            raise AssertionError('hook did not return to the site')
        if self.uc.reg_read(REG.UC_ARM_REG_SP) != sp:
            raise AssertionError('hook did not restore SP')
        return None, sp

    def key(self, code):
        sp = STACK + 0xD000
        saved = {name: 0x40000000 + i for i, name in enumerate(CALLEE_SAVED)}
        for name, value in saved.items():
            self.uc.reg_write(reg(name), value)
        self.uc.reg_write(REG.UC_ARM_REG_R0, KEYMON)
        self.uc.reg_write(REG.UC_ARM_REG_R1, code)
        self.uc.reg_write(REG.UC_ARM_REG_SP, sp)
        self.uc.reg_write(REG.UC_ARM_REG_LR, 0xDEAD0000)
        before = len(self.dispatched)
        self.uc.emu_start(SITE_D, SITE_D + 4, count=80_000)
        if self.uc.reg_read(REG.UC_ARM_REG_PC) != SITE_D + 4:
            raise AssertionError('dispatch hook did not return to the site')
        if self.uc.reg_read(REG.UC_ARM_REG_SP) != sp:
            raise AssertionError('dispatch hook did not restore SP')
        for name, value in saved.items():
            if self.uc.reg_read(reg(name)) != value:
                raise AssertionError(f'dispatch hook clobbered {name}')
        new = self.dispatched[before:]
        if any(keymon != KEYMON for keymon, _ in new):
            raise AssertionError('stock dispatch got a different keymon')
        return [code for _, code in new]


def armed(kind=9, camera_words=None):
    h = Harness(kind=kind, camera_words=camera_words)
    h.run_launcher()
    return h


class LauncherArms(unittest.TestCase):
    def setUp(self):
        self.h = armed()

    def test_three_sites_and_cave_advance_by_24(self):
        resident = self.h.resident()
        stubs = (self.h.info['stub_a'], self.h.info['stub_b'], self.h.info['disp_stub'])
        for index, site in enumerate((SITE_A, SITE_B, SITE_D)):
            veneer = bl_target(site, u32(self.h.uc, site))
            self.assertEqual(veneer, CAVE_START + index * 8)
            self.assertEqual(u32(self.h.uc, veneer + 4) - resident, stubs[index])
        self.assertEqual(u32(self.h.uc, CAVE_BUMP), CAVE_START + 24)
        self.assertEqual(bytes(self.h.uc.mem_read(resident, 8)), b'PCP3' + struct.pack('<I', 3))
        self.assertEqual(self.h.field('ring_n'), 4)


class HalfPressStillStartsTheBurst(unittest.TestCase):
    def test_s1_on_in_high_speed_dispatches_s1_then_s2(self):
        h = armed()
        self.assertEqual(h.key(S1ON), [S1ON, S2ON])
        self.assertEqual((h.field('pre'), h.field('inj'), h.field('n')), (1, 1, 0))

    def test_s1_on_in_any_other_kind_is_left_alone(self):
        h = armed(kind=0)
        self.assertEqual(h.key(S1ON), [S1ON])
        self.assertEqual((h.field('pre'), h.field('gate')), (0, 0x100))

    def test_s1_off_while_pre_sends_s2_off_first(self):
        h = armed()
        h.key(S1ON)
        self.assertEqual(h.key(S1OFF), [S2OFF, S1OFF])
        self.assertEqual(h.field('pre'), 0)


class HoldReplacesAndEvicts(unittest.TestCase):
    def setUp(self):
        self.h = armed()
        self.h.key(S1ON)
        self.h.tick_step = 0
        self.base = self.h.field('t0')

    def hold(self, now, job):
        self.h.tick = self.base + now
        self.h.run_frame(r1=job, expect='hold')

    def test_first_frame_is_held_and_not_enqueued(self):
        self.hold(1000, 1)
        self.assertEqual(self.h.field('n'), 1)
        self.assertEqual(self.h.keep_slots()[0][1], 1)
        self.assertEqual(self.h.enqueued, [])
        self.assertEqual(self.h.job_drops, [])
        self.assertEqual(self.h.field('held'), 1)

    def test_a_frame_inside_the_window_replaces_the_newest(self):
        self.hold(1000, 1)
        self.hold(1000 + INTERVAL - 1, 2)
        self.assertEqual(self.h.field('n'), 1)
        self.assertEqual(self.h.keep_slots()[0][1], 2)
        self.assertEqual(self.h.job_drops, [(JOBDB, 1)])
        self.assertEqual(self.h.refunds, [(CAP, 0x1001, 0)])
        self.assertEqual(self.h.raw_drops, [(RAWOBJ, 1)])
        self.assertEqual(self.h.field('dropped'), 1)

    def test_a_frame_past_the_window_opens_a_new_slot(self):
        self.hold(1000, 1)
        self.hold(1000 + INTERVAL, 2)
        self.assertEqual([row[1] for row in self.h.keep_slots()], [1, 2])
        self.assertEqual(self.h.job_drops, [])

    def test_the_fifth_generation_evicts_the_oldest(self):
        for i in range(5):
            self.hold(1000 + i * INTERVAL, i + 1)
        self.assertEqual([row[1] for row in self.h.keep_slots()], [2, 3, 4, 5])
        self.assertEqual(self.h.job_drops, [(JOBDB, 1)])
        self.assertEqual(self.h.field('evicted'), 1)
        self.assertEqual(self.h.field('n'), 4)

    def test_frames_without_pre_pass_through(self):
        h = armed()
        seen, sp = h.run_frame(r0=0xA0A0A0A0, r1=3, expect='pass')
        self.assertEqual((seen['r0'], seen['r1'], seen['r2'], seen['r3']),
                         (0xA0A0A0A0, 3, 1, TARGET))
        self.assertEqual((seen['lr'], seen['sp']), (SITE_B + 4, sp))
        self.assertEqual(h.field('n'), 0)


class CommitAndAbandon(unittest.TestCase):
    def primed(self, jobs=4):
        h = armed()
        h.key(S1ON)
        h.tick_step = 0
        base = h.field('t0')
        for i in range(jobs):
            h.tick = base + 2000 + i * INTERVAL
            h.run_frame(r1=i + 1, expect='hold')
        return h

    def test_real_s2_commits_in_time_order_then_later_frames_pass(self):
        h = self.primed()
        self.assertEqual(h.key(S2ON), [S2ON])
        self.assertEqual(h.enqueued, [(YUV, 1, 1), (YUV, 2, 1), (YUV, 3, 1), (YUV, 4, 1)])
        self.assertEqual((h.field('pre'), h.field('committed'), h.field('n')), (0, 4, 0))
        seen, _ = h.run_frame(r0=YUV, r1=10, expect='pass')
        self.assertEqual((seen['r0'], seen['r1'], seen['r2']), (YUV, 10, 1))

    def test_s1_off_drops_the_ring_and_saves_nothing(self):
        h = self.primed()
        self.assertEqual(h.key(S1OFF), [S2OFF, S1OFF])
        self.assertEqual(h.enqueued, [])
        self.assertEqual([job for _, job in h.job_drops], [1, 2, 3, 4])
        self.assertEqual((h.field('abandoned'), h.field('n'), h.field('pre')), (4, 0, 0))

    def test_timeout_abandons_then_posts_s2_off(self):
        h = armed()
        h.key(S1ON)
        t0 = h.field('t0')
        h.tick_step = 0
        h.tick = t0 + 1000
        h.run_frame(r1=1, expect='hold')
        h.tick = t0 + TIMEOUT_US
        h.run_frame(r1=2, expect='hold')
        self.assertEqual(h.posted, [(KEYMON, S2OFF)])
        self.assertEqual((h.field('pre'), h.field('tmo'), h.field('n')), (0, 1, 0))
        self.assertEqual(sorted(job for _, job in h.job_drops), [1, 2])
        self.assertEqual(h.key(S2OFF), [S2OFF])

    def test_a_missing_job_is_not_handed_to_the_asserting_drop(self):
        h = armed()
        h.key(S1ON)
        h.tick_step = 0
        h.tick = h.field('t0') + 1000
        h.alive[7] = False
        h.run_frame(r1=7, expect='hold')
        h.key(S1OFF)
        self.assertEqual(h.job_drops, [])
        self.assertEqual(h.raw_drops, [])

    def test_drop_guards_not_ready_means_passthrough(self):
        words = live_camera_state()
        words[DROP_GUARDS[0]] = 0
        h = armed(camera_words=words)
        h.key(S1ON)
        h.run_frame(r1=1, expect='pass')
        self.assertEqual(h.field('n'), 0)


class LauncherRefuses(unittest.TestCase):
    def test_any_site_that_is_not_stock(self):
        h = Harness(site_words={SITE_D: 0xEB000000})
        h.run_launcher()
        self.assertEqual(h.site_writes, [])
        self.assertEqual(u32(h.uc, CAVE_BUMP), CAVE_START)


class CardDeclaresItsSites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = pathlib.Path(cls.tmp.name) / 'card'
        subprocess.run([sys.executable, '-B', str(HERE / 'build_precap3.py'), '--out', str(out)],
                       check=True, capture_output=True, text=True)
        cls.files = sorted(p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file())
        cls.bin = (out / 'fpSup.BIN').read_bytes()
        cls.autorun = (out / 'AutoRun.txt').read_text()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_card_shape(self):
        self.assertEqual(self.files, ['AutoRun.txt', 'fpSup.BIN', 'precap.bin'])
        self.assertIn(build_precap3.BANNER, self.autorun)
        self.assertNotIn('four-box', self.autorun.lower())
        blob, _ = build_precap3.build_blob()
        self.assertEqual(self.bin.count(blob), 1)
        magic, count, _, length = struct.unpack_from('<4sIII', self.bin)
        self.assertEqual(magic, b'VBIN')
        cursor, sections = 16 + 8 * count, {}
        for index in range(count):
            address, size = struct.unpack_from('<II', self.bin, 16 + index * 8)
            sections.setdefault(address, []).append(self.bin[cursor:cursor + size])
            cursor += (size + 3) & ~3
        for site, word, _ in build_precap3.SITES:
            self.assertEqual(sections.get(site), [struct.pack('<I', word)])


if __name__ == '__main__':
    unittest.main()
