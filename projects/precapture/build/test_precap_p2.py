#!/usr/bin/env python3
"""Offline checks for the pre-capture P2 resident (half-press starts the burst).

Runs the real launcher and the real hook paths on the firmware image in
unicorn, with every firmware call intercepted.  Nothing here touches a card or
a camera.

    python3 -B -m unittest test_precap_p2 -v
"""
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_precap2  # noqa: E402

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE  # noqa: E402
from unicorn import arm_const as REG  # noqa: E402
from cave import CAVE_ARENA  # noqa: E402

H_GET, H_ADDR = 0xC001D740, 0xC001D7F0
F_DCACHE, F_ICACHE, F_TICK_US = 0xC000E91C, 0xC000EABC, 0xC002B6E0
F_KIND, F_KEYMON, F_ENQ, F_DISP = 0xC0397B30, 0xC02DBAF0, 0xC02DBBE8, 0xC02DC138
CAVE_BUMP = 0xC072E060
(SITE_A, _, _), (SITE_B, _, _), (SITE_D, _, _) = build_precap2.SITES
VENEER_LDR = 0xE51FF004
KEYMON = 0xC3425684
S1ON, S1OFF, S2ON, S2OFF = 4, 5, 6, 7
TIMEOUT_US = 10_000_000

STAGING, STACK, STOP, TARGET, HEAP = 0x42000000, 0x10000000, 0x10100000, 0x10200000, 0x50000000
CAVE_START = CAVE_ARENA
HEAP_RETURN = HEAP + 4
P = dict(count_a=0x08, count_b=0x0C, first_us=0x10, last_us=0x14, seq=0x18, ring_n=0x1C,
         pre=0x20, t0=0x24, tmo=0x28, inj=0x2C, s1c=0x30, tmof=0x34, disp=0x38, gate=0x3C,
         ring=0x40)
CALLEE_SAVED = ('r4', 'r5', 'r6', 'r7', 'r8', 'r9', 'r10', 'r11')
SINGLETON_GUARDS = (0xC35A9530, 0xC31F8C90, 0xC358CB48, 0xC3074980, 0xC3075684)
SSTACK = 0xC3075670


def live_camera_state():
    """What the firmware has built by the time someone half-presses in shooting mode."""
    words = {guard: 1 for guard in SINGLETON_GUARDS}
    words.update({SSTACK + 0xC: 1, SSTACK + 0x10: 0, SSTACK: 0xC3100000})
    return words


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
        self.blob, self.info = build_precap2.build_blob()
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        rom = build_precap2.p1.rom_path().read_bytes()
        self.uc.mem_map(0xC0000000, 0x04000000)
        self.uc.mem_write(0xC0000000, rom[:0x04000000])
        for address, size in ((STAGING, 0x10000), (STACK, 0x10000), (STOP, 0x1000),
                              (TARGET, 0x1000), (HEAP, 0x10000)):
            self.uc.mem_map(address, size)
        self.uc.mem_write(STAGING, self.blob)
        self.uc.mem_write(CAVE_BUMP, struct.pack('<I', cave_start))
        for site, word in (site_words or {}).items():
            self.uc.mem_write(site, struct.pack('<I', word))
        for address, word in (live_camera_state() if camera_words is None else camera_words).items():
            self.uc.mem_write(address, struct.pack('<I', word))
        self.heap_return = heap_return
        self.kind = kind
        self.tick = 1000
        self.tick_step = 55_555
        self.calls = []            # (address, sp, r0, r1)
        self.dispatched = []       # codes handed to the stock dispatch
        self.posted = []           # (keymon, code) posted to the queue
        self.site_writes = []
        self.target_hits = []
        for address in (H_GET, H_ADDR, F_DCACHE, F_ICACHE, F_TICK_US, F_KIND, F_KEYMON,
                        F_ENQ, F_DISP, STOP, TARGET):
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
        r0, r1 = uc.reg_read(REG.UC_ARM_REG_R0), uc.reg_read(REG.UC_ARM_REG_R1)
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
            for name in ('r0', 'r1', 'r2', 'r3', 'ip'):     # a real callee may trash these
                uc.reg_write(reg(name), 0xBAD0BAD0)
            self._return()
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

    def set_field(self, name, value):
        self.uc.mem_write(self.resident() + P[name], struct.pack('<I', value & 0xFFFFFFFF))

    def run_frame(self, site=SITE_A, r0=0x11, r1=0x21):
        sp = STACK + 0xE000
        self.target_hits.clear()
        for name, value in (('r0', r0), ('r1', r1), ('r2', 1), ('r3', TARGET),
                            ('sp', sp), ('lr', 0xDEAD0000)):
            self.uc.reg_write(reg(name), value)
        self.uc.emu_start(site, TARGET + 4, count=20_000)
        if len(self.target_hits) != 1:
            raise AssertionError('the original enqueue was not reached exactly once')
        return self.target_hits[0], sp

    def key(self, code):
        """Run the KeyMon thread's dispatch site with one code; return the codes dispatched."""
        sp = STACK + 0xD000
        saved = {name: 0x40000000 + i for i, name in enumerate(CALLEE_SAVED)}
        for name, value in saved.items():
            self.uc.reg_write(reg(name), value)
        self.uc.reg_write(REG.UC_ARM_REG_R0, KEYMON)
        self.uc.reg_write(REG.UC_ARM_REG_R1, code)
        self.uc.reg_write(REG.UC_ARM_REG_SP, sp)
        self.uc.reg_write(REG.UC_ARM_REG_LR, 0xDEAD0000)
        before = len(self.dispatched)
        self.uc.emu_start(SITE_D, SITE_D + 4, count=20_000)
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

    def test_three_sites_branch_to_veneers_that_reach_the_stubs(self):
        stubs = (self.h.info['stub_a'], self.h.info['stub_b'], self.h.info['disp_stub'])
        resident = self.h.resident()
        for index, site in enumerate((SITE_A, SITE_B, SITE_D)):
            veneer = bl_target(site, u32(self.h.uc, site))
            self.assertEqual(veneer, CAVE_START + index * 8)
            self.assertEqual(u32(self.h.uc, veneer), VENEER_LDR)
            self.assertEqual(u32(self.h.uc, veneer + 4) - resident, stubs[index])
        self.assertEqual(resident, (HEAP_RETURN + 7) & ~7)

    def test_cave_bump_advances_by_the_three_veneers(self):
        self.assertEqual(u32(self.h.uc, CAVE_BUMP), CAVE_START + 24)

    def test_resident_is_copied_with_its_initial_values(self):
        resident = self.h.resident()
        copied = bytes(self.h.uc.mem_read(resident, self.h.info['resident']))
        self.assertEqual(copied, self.h.blob[self.h.info['launch']:])
        self.assertEqual(copied[:8], b'PCP2' + struct.pack('<I', 2))
        for name in ('seq', 'pre', 't0', 'tmo', 'inj', 's1c', 'tmof', 'disp'):
            self.assertEqual(self.h.field(name), 0, name)
        self.assertEqual(self.h.field('ring_n'), 64)

    def test_publish_then_arm_then_publish(self):
        order = [call[0] for call in self.h.calls]
        self.assertEqual(order, [H_GET, H_ADDR, F_DCACHE, F_ICACHE, F_DCACHE, F_ICACHE])
        self.assertEqual({address for address, _, _ in self.h.site_writes}, {SITE_A, SITE_B, SITE_D})
        self.assertTrue(all(caches == 2 for _, _, caches in self.h.site_writes))

    def test_every_call_is_made_with_an_aligned_stack(self):
        self.assertTrue(all(sp % 8 == 0 for _, sp, _, _ in self.h.calls))


class HalfPressStartsTheBurst(unittest.TestCase):
    def test_s1_on_in_high_speed_continuous_dispatches_s1_then_s2(self):
        h = armed(kind=9)
        self.assertEqual(h.key(S1ON), [S1ON, S2ON])
        self.assertEqual((h.field('pre'), h.field('inj'), h.field('tmo')), (1, 1, 0))
        kind_calls = [call for call in h.calls if call[0] == F_KIND]
        self.assertEqual([(r0, r1) for _, _, r0, r1 in kind_calls], [(3, 0)])

    def test_s1_on_in_any_other_shot_kind_is_left_alone(self):
        for kind in (0, 1, 2, 3, 4, 7, 0xD):
            h = armed(kind=kind)
            self.assertEqual(h.key(S1ON), [S1ON], kind)
            self.assertEqual((h.field('pre'), h.field('inj')), (0, 0))
            self.assertEqual(h.field('gate'), 0x100 | kind)

    def test_gate_records_an_injection(self):
        h = armed()
        h.key(S1ON)
        self.assertEqual(h.field('gate'), 1)


class GateRefusesBeforeCallingTheKindSelector(unittest.TestCase):
    def refused(self, camera_words, expect_gate):
        h = armed(camera_words=camera_words)
        self.assertEqual(h.key(S1ON), [S1ON])
        self.assertNotIn(F_KIND, [call[0] for call in h.calls])
        self.assertEqual((h.field('pre'), h.field('inj'), h.field('gate')), (0, 0, expect_gate))
        return h

    def test_each_singleton_not_yet_built(self):
        for index, guard in enumerate(SINGLETON_GUARDS):
            words = live_camera_state()
            words[guard] = 0
            self.refused(words, 0x201 + index)

    def test_settings_stack_not_entered(self):
        words = live_camera_state()
        words[SSTACK + 0xC] = 0
        self.refused(words, 0x300)

    def test_settings_stack_index_out_of_range(self):
        for index in (3, 4, 0x80000000):
            words = live_camera_state()
            words[SSTACK + 0x10] = index
            self.refused(words, 0x300)

    def test_settings_stack_slot_empty(self):
        words = live_camera_state()
        words.update({SSTACK + 0x10: 2, SSTACK + 8: 0})
        self.refused(words, 0x300)

    def test_a_filled_slot_other_than_zero_passes(self):
        words = live_camera_state()
        words.update({SSTACK + 0x10: 2, SSTACK + 8: 0xC3200000, SSTACK: 0})
        h = armed(camera_words=words)
        self.assertEqual(h.key(S1ON), [S1ON, S2ON])

    def test_after_a_refusal_the_next_half_press_can_still_inject(self):
        words = live_camera_state()
        words[SINGLETON_GUARDS[0]] = 0
        h = self.refused(words, 0x201)
        h.key(S1OFF)
        h.uc.mem_write(SINGLETON_GUARDS[0], struct.pack('<I', 1))
        self.assertEqual(h.key(S1ON), [S1ON, S2ON])
        self.assertEqual(h.field('gate'), 1)

    def test_t0_is_taken_after_the_real_s1_went_out(self):
        h = armed()
        h.tick = 5_000_000
        h.key(S1ON)
        self.assertEqual(h.field('t0'), 5_000_000 + h.tick_step)

    def test_a_second_s1_on_while_pre_capturing_is_passed_through(self):
        h = armed()
        h.key(S1ON)
        kind_calls = sum(1 for call in h.calls if call[0] == F_KIND)
        self.assertEqual(h.key(S1ON), [S1ON])
        self.assertEqual(sum(1 for call in h.calls if call[0] == F_KIND), kind_calls)
        self.assertEqual(h.field('inj'), 1)

    def test_every_call_from_the_dispatch_hook_has_an_aligned_stack(self):
        h = armed()
        start = len(h.calls)
        h.key(S1ON)
        h.key(S1OFF)
        self.assertTrue(all(sp % 8 == 0 for _, sp, _, _ in h.calls[start:]))


class ReleasingS1EndsIt(unittest.TestCase):
    def test_s1_off_while_pre_capturing_sends_s2_off_first(self):
        h = armed()
        h.key(S1ON)
        self.assertEqual(h.key(S1OFF), [S2OFF, S1OFF])
        self.assertEqual((h.field('pre'), h.field('s1c')), (0, 1))

    def test_s1_off_when_idle_is_passed_through(self):
        h = armed()
        self.assertEqual(h.key(S1OFF), [S1OFF])
        self.assertEqual(h.field('s1c'), 0)

    def test_a_real_s2_off_clears_pre_and_s1_off_then_goes_alone(self):
        h = armed()
        h.key(S1ON)
        self.assertEqual(h.key(S2ON), [S2ON])            # user presses all the way
        self.assertEqual(h.field('pre'), 1)
        self.assertEqual(h.key(S2OFF), [S2OFF])
        self.assertEqual(h.field('pre'), 0)
        self.assertEqual(h.key(S1OFF), [S1OFF])

    def test_other_codes_are_passed_through_untouched(self):
        h = armed()
        h.key(S1ON)
        for code in (0, 1, 2, 3, 8, 0x11, 0x50, 0x75):
            self.assertEqual(h.key(code), [code])
        self.assertEqual(h.field('pre'), 1)
        self.assertEqual(h.field('disp'), 1 + 8)

    def test_a_full_cycle_can_repeat(self):
        h = armed()
        for _ in range(3):
            self.assertEqual(h.key(S1ON), [S1ON, S2ON])
            self.assertEqual(h.key(S1OFF), [S2OFF, S1OFF])
        self.assertEqual((h.field('inj'), h.field('s1c'), h.field('pre')), (3, 3, 0))


class TimeoutStopsALongBurst(unittest.TestCase):
    def setUp(self):
        self.h = armed()
        self.h.tick = 2_000_000
        self.h.key(S1ON)
        self.t0 = self.h.field('t0')

    def frame_at(self, elapsed, site=SITE_A):
        self.h.tick = self.t0 + elapsed - self.h.tick_step
        return self.h.run_frame(site)

    def test_no_post_before_ten_seconds(self):
        self.frame_at(TIMEOUT_US - 1)
        self.assertEqual(self.h.posted, [])

    def test_one_s2_off_is_posted_at_ten_seconds(self):
        seen, sp = self.frame_at(TIMEOUT_US)
        self.assertEqual(self.h.posted, [(KEYMON, S2OFF)])
        self.assertEqual((self.h.field('tmo'), self.h.field('tmof')), (1, 1))
        self.assertEqual((seen['r0'], seen['r1'], seen['r2'], seen['r3']), (0x11, 0x21, 1, TARGET))
        self.assertEqual((seen['lr'], seen['sp']), (SITE_A + 4, sp))

    def test_only_once_per_half_press(self):
        self.frame_at(TIMEOUT_US)
        self.frame_at(TIMEOUT_US + 55_555, site=SITE_B)
        self.frame_at(TIMEOUT_US + 2 * 55_555)
        self.assertEqual(self.h.posted, [(KEYMON, S2OFF)])

    def test_the_posted_s2_off_clears_pre_and_s1_off_goes_alone(self):
        self.frame_at(TIMEOUT_US)
        self.assertEqual(self.h.key(S2OFF), [S2OFF])
        self.assertEqual(self.h.field('pre'), 0)
        self.assertEqual(self.h.key(S1OFF), [S1OFF])

    def test_the_next_half_press_rearms_the_timeout(self):
        self.frame_at(TIMEOUT_US)
        self.h.key(S2OFF)
        self.h.key(S1OFF)
        self.h.key(S1ON)
        self.assertEqual(self.h.field('tmo'), 0)
        self.t0 = self.h.field('t0')
        self.frame_at(TIMEOUT_US)
        self.assertEqual(self.h.posted, [(KEYMON, S2OFF), (KEYMON, S2OFF)])

    def test_wraparound_of_the_microsecond_clock(self):
        h = armed()
        h.tick = 0xFFFFFFFF - 3_000_000
        h.key(S1ON)
        t0 = h.field('t0')
        h.tick = (t0 + TIMEOUT_US - h.tick_step) & 0xFFFFFFFF
        h.run_frame()
        self.assertEqual(h.posted, [(KEYMON, S2OFF)])


class FramesWithoutPreCaptureAreJustObserved(unittest.TestCase):
    def test_frames_never_post_when_not_pre_capturing(self):
        h = armed()
        h.tick = 50_000_000
        for _ in range(5):
            h.run_frame(SITE_B)
        self.assertEqual(h.posted, [])
        self.assertEqual((h.field('count_b'), h.field('seq')), (5, 5))

    def test_original_enqueue_sees_the_stock_registers(self):
        h = armed()
        h.key(S1ON)
        for site in (SITE_A, SITE_B):
            seen, sp = h.run_frame(site, r0=0xA0A0A0A0, r1=0x1234)
            self.assertEqual((seen['r0'], seen['r1'], seen['r2'], seen['r3']),
                             (0xA0A0A0A0, 0x1234, 1, TARGET))
            self.assertEqual((seen['lr'], seen['sp']), (site + 4, sp))

    def test_ring_wraps_without_touching_memory_past_it(self):
        h = armed()
        resident = h.resident()
        guard_at = resident + h.info['resident']
        h.uc.mem_write(guard_at, b'\xEE' * 16)
        code_at = h.info['stub_a']
        code = h.blob[h.info['launch'] + code_at:]
        for frame in range(70):
            h.run_frame(SITE_A, r0=frame, r1=frame)
        self.assertEqual(h.field('seq'), 70)
        self.assertEqual(bytes(h.uc.mem_read(guard_at, 16)), b'\xEE' * 16)
        self.assertEqual(bytes(h.uc.mem_read(resident + code_at, len(code))), code,
                         'the ring wrote into the code that follows it')


class LauncherRefuses(unittest.TestCase):
    def assert_untouched(self, h, cave_start=CAVE_START):
        self.assertEqual(u32(h.uc, CAVE_BUMP), cave_start)
        self.assertEqual(h.site_writes, [])
        self.assertNotIn(F_ICACHE, [call[0] for call in h.calls])

    def test_any_site_that_is_not_stock(self):
        for site in (SITE_A, SITE_B, SITE_D):
            h = Harness(site_words={site: 0xEB000000})
            h.run_launcher()
            self.assert_untouched(h)
            self.assertEqual(h.calls, [], hex(site))

    def test_the_allocator_saying_no(self):
        h = Harness(heap_return=0)
        h.run_launcher()
        self.assert_untouched(h)

    def test_a_cave_without_room_for_three(self):
        full = 0xC072EFA0
        h = Harness(cave_start=full)
        h.run_launcher()
        self.assert_untouched(h, cave_start=full)

    def test_the_last_slot_that_still_fits(self):
        last = 0xC072EF9C
        h = Harness(cave_start=last)
        h.run_launcher()
        self.assertEqual(u32(h.uc, CAVE_BUMP), last + 24)
        self.assertEqual(bl_target(SITE_D, u32(h.uc, SITE_D)), last + 16)

    def test_an_unaligned_bump_pointer(self):
        h = Harness(cave_start=CAVE_START + 2)
        h.run_launcher()
        self.assert_untouched(h, cave_start=CAVE_START + 2)

    def test_a_bump_pointer_outside_the_arena(self):
        h = Harness(cave_start=0xC072E000)
        h.run_launcher()
        self.assert_untouched(h, cave_start=0xC072E000)


class ReaderFindsTheResident(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(HERE.parent / 'tools'))
        import p2_read
        self.p2_read = p2_read
        self.h = armed()
        self.h.key(S1ON)
        self.h.run_frame(SITE_A, r0=0x11, r1=0x21)
        self.h.run_frame(SITE_B, r0=0x12, r1=0x22)
        self.commands = []

    def fake_sh(self, drop=None):
        def sh(line, retries=3, **_):
            self.commands.append((line, retries))
            address, size = line.split()[2].split(',,')
            address, size = int(address, 16), int(size, 16)
            return '\n'.join(f'get : A:0x{address + i:08x}, D:0x{u32(self.h.uc, address + i):08X}'
                             for i in range(0, size, 4) if address + i != drop)
        return sh

    def test_locates_all_three_sites_and_reads_the_state(self):
        sh = self.fake_sh()
        params, veneers = self.p2_read.locate(sh)
        self.assertEqual(params, self.h.resident())
        self.assertEqual(list(veneers.values()), [CAVE_START, CAVE_START + 8, CAVE_START + 16])
        header = self.p2_read.read_words(sh, params, self.p2_read.HEADER_WORDS)
        fields = dict(zip(self.p2_read.FIELDS, header))
        self.assertEqual((fields['magic'], fields['layout'], fields['ring_n']), (0x32504350, 2, 64))
        self.assertEqual((fields['pre'], fields['inj'], fields['gate'], fields['seq']), (1, 1, 1, 2))
        self.assertTrue(all(line.startswith('mem get ') and retries == 0
                            for line, retries in self.commands))

    def test_stops_on_a_missing_word(self):
        sh = self.fake_sh(drop=self.h.resident() + 4)
        with self.assertRaises(self.p2_read.ReadStopped):
            self.p2_read.read_words(sh, self.h.resident(), 8)
        self.assertEqual(len(self.commands), 1)

    def test_says_so_when_nothing_is_installed(self):
        self.h = Harness(site_words={SITE_D: 0xEB000000})
        self.h.run_launcher()
        with self.assertRaises(self.p2_read.ReadStopped):
            self.p2_read.locate(self.fake_sh())

    def test_gate_values_are_described(self):
        describe = self.p2_read.describe_gate
        self.assertIn('injected', describe(1))
        self.assertIn('kind 0', describe(0x100))
        self.assertIn('FUN_c0022da8', describe(0x205))
        self.assertIn('settings stack', describe(0x300))


class CardDeclaresItsSites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = pathlib.Path(cls.tmp.name) / 'card'
        subprocess.run([sys.executable, '-B', str(HERE / 'build_precap2.py'), '--out', str(out)],
                       check=True, capture_output=True, text=True)
        cls.files = sorted(p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file())
        cls.bin = (out / 'fpSup.BIN').read_bytes()
        cls.autorun = (out / 'AutoRun.txt').read_text()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def sections(self):
        magic, count, _, length = struct.unpack_from('<4sIII', self.bin)
        self.assertEqual(magic, b'VBIN')
        cursor, result = 16 + 8 * count, {}
        for index in range(count):
            address, size = struct.unpack_from('<II', self.bin, 16 + index * 8)
            result.setdefault(address, []).append(self.bin[cursor:cursor + size])
            cursor += (size + 3) & ~3
        self.assertEqual(cursor, 16 + 8 * count + length)
        return result

    def test_each_hook_site_is_a_stock_word_section(self):
        sections = self.sections()
        for site, word, _ in build_precap2.SITES:
            self.assertEqual(sections.get(site), [struct.pack('<I', word)])

    def test_the_launcher_is_carried_unchanged(self):
        blob, _ = build_precap2.build_blob()
        self.assertEqual(self.bin.count(blob), 1)

    def test_the_card_carries_only_the_text_banner(self):
        self.assertEqual(self.files, ['AutoRun.txt', 'fpSup.BIN', 'precap.bin'])
        self.assertNotIn('four-box', self.autorun.lower())
        self.assertIn(build_precap2.BANNER, self.autorun)

    def test_no_persistent_or_fast_start_paths(self):
        lowered = self.autorun.lower()
        for word in ('store', 'commonsave', 'sdcard format', 'menu set', 'setting write'):
            self.assertNotIn(word, lowered)

    def test_sites_in_source_match_the_declared_sites(self):
        source = (HERE / 'pc2_launch.S').read_text()
        for site, word, _ in build_precap2.SITES:
            self.assertIn(f'0x{site:08X}', source)
            self.assertIn(f'0x{word:08X}', source)
        self.assertEqual(source.count('ARM     SITE_'), 3)


if __name__ == '__main__':
    unittest.main()
