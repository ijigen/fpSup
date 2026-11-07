#!/usr/bin/env python3
"""P0 offline checks for the pre-capture P1 observer.

Runs the real launcher and the real hook path on the firmware image in
unicorn, with every firmware call intercepted.  Nothing here touches a card or
a camera.

    python3 -B -m unittest test_precap_p1 -v
"""
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_precap  # noqa: E402

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE  # noqa: E402
from unicorn import arm_const as REG  # noqa: E402

H_GET, H_ADDR = 0xC001D740, 0xC001D7F0
F_DCACHE, F_ICACHE, F_TICK_US = 0xC000E91C, 0xC000EABC, 0xC002B6E0
CAVE_BUMP = 0xC072E060
SITE_A, SITE_B = (site for site, _ in build_precap.SITES)
VENEER_LDR = 0xE51FF004

STAGING, STACK, STOP, TARGET, HEAP = 0x42000000, 0x10000000, 0x10100000, 0x10200000, 0x50000000
from cave import CAVE_ARENA  # noqa: E402

CAVE_START = CAVE_ARENA                   # what stage2 resets CAVE_BUMP to every boot
HEAP_RETURN = HEAP + 4                    # deliberately not 8-aligned
P_COUNT_A, P_COUNT_B, P_FIRST_US, P_LAST_US, P_SEQ, P_RING_N, P_RING = (
    0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20)


def u32(uc, address):
    return struct.unpack('<I', uc.mem_read(address, 4))[0]


def bl_target(site, word):
    if word >> 24 != 0xEB:
        raise AssertionError(f'0x{word:08X} at 0x{site:08X} is not bl')
    offset = word & 0x00FFFFFF
    if offset & 0x00800000:
        offset -= 1 << 24
    return site + 8 + offset * 4


class Harness:
    def __init__(self, *, site_words=None, heap_return=HEAP_RETURN, cave_start=CAVE_START):
        self.blob, self.info = build_precap.build_blob()
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        rom = build_precap.rom_path().read_bytes()
        self.uc.mem_map(0xC0000000, 0x04000000)
        self.uc.mem_write(0xC0000000, rom[:0x04000000])
        for address, size in ((STAGING, 0x10000), (STACK, 0x10000), (STOP, 0x1000),
                              (TARGET, 0x1000), (HEAP, 0x10000)):
            self.uc.mem_map(address, size)
        self.uc.mem_write(STAGING, self.blob)
        self.uc.mem_write(CAVE_BUMP, struct.pack('<I', cave_start))
        for site, word in (site_words or {}).items():
            self.uc.mem_write(site, struct.pack('<I', word))
        self.heap_return = heap_return
        self.calls = []
        self.site_writes = []
        self.tick = 1000
        self.target_hits = []
        for address in (H_GET, H_ADDR, F_DCACHE, F_ICACHE, F_TICK_US, STOP, TARGET):
            self.uc.hook_add(UC_HOOK_CODE, self._intercept, begin=address, end=address)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._site_write, begin=SITE_A, end=SITE_B + 3)

    def _return(self):
        self.uc.reg_write(REG.UC_ARM_REG_PC, self.uc.reg_read(REG.UC_ARM_REG_LR))

    def _intercept(self, uc, address, _size, _user):
        if address == STOP:
            uc.emu_stop()
            return
        if address == TARGET:
            self.target_hits.append({name: uc.reg_read(getattr(REG, f'UC_ARM_REG_{name.upper()}'))
                                     for name in ('r0', 'r1', 'r2', 'r3', 'lr', 'sp')})
            uc.emu_stop()
            return
        sp = uc.reg_read(REG.UC_ARM_REG_SP)
        self.calls.append((address, sp))
        if address == H_GET:
            desc = uc.reg_read(REG.UC_ARM_REG_R0)
            uc.mem_write(desc, struct.pack('<I', self.heap_return))
            uc.reg_write(REG.UC_ARM_REG_R0, 0)
        elif address == H_ADDR:
            desc = uc.reg_read(REG.UC_ARM_REG_R0)
            uc.reg_write(REG.UC_ARM_REG_R0, u32(uc, desc))
        elif address == F_TICK_US:
            self.tick += 55_555
            uc.reg_write(REG.UC_ARM_REG_R0, self.tick)
        self._return()

    def _site_write(self, _uc, _access, address, _size, value, _user):
        caches = sum(1 for call, _ in self.calls if call in (F_DCACHE, F_ICACHE))
        self.site_writes.append((address, value, caches))

    def run_launcher(self):
        self.uc.reg_write(REG.UC_ARM_REG_SP, STACK + 0xF000)
        self.uc.reg_write(REG.UC_ARM_REG_LR, STOP)
        self.uc.emu_start(STAGING, STOP, count=200_000)
        if self.uc.reg_read(REG.UC_ARM_REG_SP) != STACK + 0xF000:
            raise AssertionError('launcher did not restore SP')

    def run_site(self, site, r0, r1, r2=1):
        sp = STACK + 0xE000
        self.target_hits.clear()
        for name, value in (('R0', r0), ('R1', r1), ('R2', r2), ('R3', TARGET),
                            ('SP', sp), ('LR', 0xDEAD0000)):
            self.uc.reg_write(getattr(REG, f'UC_ARM_REG_{name}'), value)
        self.uc.emu_start(site, TARGET + 4, count=10_000)
        if len(self.target_hits) != 1:
            raise AssertionError('the original enqueue was not reached exactly once')
        return self.target_hits[0], sp

    def resident(self):
        veneer = bl_target(SITE_A, u32(self.uc, SITE_A))
        return u32(self.uc, veneer + 4) - self.info['stub_a']


class LauncherArms(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.h.run_launcher()

    def test_sites_branch_to_veneers_that_reach_the_stubs(self):
        for index, site in enumerate((SITE_A, SITE_B)):
            veneer = bl_target(site, u32(self.h.uc, site))
            self.assertEqual(veneer, CAVE_START + index * 8)
            self.assertEqual(u32(self.h.uc, veneer), VENEER_LDR)
        resident = self.h.resident()
        self.assertEqual(resident % 8, 0)
        self.assertEqual(resident, (HEAP_RETURN + 7) & ~7)
        self.assertEqual(u32(self.h.uc, CAVE_START + 12) - resident, self.h.info['stub_b'])

    def test_cave_bump_advances_by_the_two_veneers(self):
        self.assertEqual(u32(self.h.uc, CAVE_BUMP), CAVE_START + 16)

    def test_resident_is_copied_with_its_initial_values(self):
        resident = self.h.resident()
        launch_len = self.h.info['launch']
        copied = bytes(self.h.uc.mem_read(resident, self.h.info['resident']))
        self.assertEqual(copied, self.h.blob[launch_len:])
        self.assertEqual(copied[:4], b'PCP1')
        self.assertEqual(struct.unpack_from('<I', copied, P_SEQ)[0], 0)
        self.assertEqual(struct.unpack_from('<I', copied, P_RING_N)[0], 64)

    def test_publish_then_arm_then_publish(self):
        order = [call for call, _ in self.h.calls]
        self.assertEqual(order, [H_GET, H_ADDR, F_DCACHE, F_ICACHE, F_DCACHE, F_ICACHE])
        self.assertEqual({address for address, _, _ in self.h.site_writes}, {SITE_A, SITE_B})
        self.assertTrue(all(caches == 2 for _, _, caches in self.h.site_writes),
                        'a site was written before the first D/I publication')

    def test_every_call_is_made_with_an_aligned_stack(self):
        self.assertTrue(all(sp % 8 == 0 for _, sp in self.h.calls))


class HookPassesThrough(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.h.run_launcher()

    def test_original_enqueue_sees_the_stock_registers(self):
        for site in (SITE_A, SITE_B):
            seen, sp = self.h.run_site(site, r0=0xA0A0A0A0, r1=0x1234, r2=1)
            self.assertEqual((seen['r0'], seen['r1'], seen['r2'], seen['r3']),
                             (0xA0A0A0A0, 0x1234, 1, TARGET))
            self.assertEqual(seen['lr'], site + 4)
            self.assertEqual(seen['sp'], sp)

    def test_each_frame_is_counted_and_stamped(self):
        self.h.run_site(SITE_A, r0=0x11, r1=0x21)
        self.h.run_site(SITE_A, r0=0x12, r1=0x22)
        self.h.run_site(SITE_B, r0=0x13, r1=0x23)
        params = self.h.resident()
        uc = self.h.uc
        self.assertEqual(u32(uc, params + P_COUNT_A), 2)
        self.assertEqual(u32(uc, params + P_COUNT_B), 1)
        self.assertEqual(u32(uc, params + P_SEQ), 3)
        self.assertEqual(u32(uc, params + P_FIRST_US), 1000 + 55_555)
        self.assertEqual(u32(uc, params + P_LAST_US), 1000 + 3 * 55_555)
        rows = [struct.unpack('<4I', uc.mem_read(params + P_RING + 16 * i, 16)) for i in range(3)]
        self.assertEqual(rows, [(1000 + 55_555, 0x21, 0x11, 0),
                                (1000 + 2 * 55_555, 0x22, 0x12, 0),
                                (1000 + 3 * 55_555, 0x23, 0x13, 1)])

    def test_ring_wraps_without_touching_memory_past_it(self):
        params = self.h.resident()
        guard_at = params + self.h.info['resident']
        self.h.uc.mem_write(guard_at, b'\xEE' * 16)
        for frame in range(70):
            self.h.run_site(SITE_A, r0=frame, r1=frame)
        self.assertEqual(u32(self.h.uc, params + P_SEQ), 70)
        self.assertEqual(struct.unpack('<4I', self.h.uc.mem_read(params + P_RING, 16))[1], 64)
        self.assertEqual(bytes(self.h.uc.mem_read(guard_at, 16)), b'\xEE' * 16)


class LauncherRefuses(unittest.TestCase):
    def assert_untouched(self, h, cave_start=CAVE_START):
        self.assertEqual(u32(h.uc, CAVE_BUMP), cave_start)
        self.assertEqual(h.site_writes, [])
        self.assertNotIn(F_ICACHE, [call for call, _ in h.calls])

    def test_a_site_that_is_not_stock(self):
        h = Harness(site_words={SITE_B: 0xEB000000})
        h.run_launcher()
        self.assert_untouched(h)
        self.assertEqual(h.calls, [])

    def test_the_allocator_saying_no(self):
        h = Harness(heap_return=0)
        h.run_launcher()
        self.assert_untouched(h)

    def test_a_full_cave(self):
        full = 0xC072EFA8
        h = Harness(cave_start=full)
        h.run_launcher()
        self.assert_untouched(h, cave_start=full)

    def test_an_unaligned_bump_pointer(self):
        h = Harness(cave_start=CAVE_START + 2)
        h.run_launcher()
        self.assert_untouched(h, cave_start=CAVE_START + 2)

    def test_the_boot_value_is_only_word_aligned(self):
        self.assertEqual(CAVE_START % 8, 4)

    def test_the_last_slot_that_still_fits(self):
        last = 0xC072EFA4
        h = Harness(cave_start=last)
        h.run_launcher()
        self.assertEqual(u32(h.uc, CAVE_BUMP), last + 16)
        self.assertEqual(bl_target(SITE_B, u32(h.uc, SITE_B)), last + 8)

    def test_a_bump_pointer_outside_the_arena(self):
        h = Harness(cave_start=0xC072E000)
        h.run_launcher()
        self.assert_untouched(h, cave_start=0xC072E000)


class ReaderFindsTheObserver(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(HERE.parent / 'tools'))
        import p1_read
        self.p1_read = p1_read
        self.h = Harness()
        self.h.run_launcher()
        self.h.run_site(SITE_A, r0=0x11, r1=0x21)
        self.h.run_site(SITE_B, r0=0x12, r1=0x22)
        self.commands = []

    def fake_sh(self, drop=None):
        def sh(line, retries=3, **_):
            self.commands.append((line, retries))
            address, size = line.split()[2].split(',,')
            address, size = int(address, 16), int(size, 16)
            lines = [f'get : A:0x{address + i:08x}, D:0x{u32(self.h.uc, address + i):08X}'
                     for i in range(0, size, 4) if address + i != drop]
            return '\n'.join(lines)
        return sh

    def test_locates_and_reads_what_the_hooks_wrote(self):
        sh = self.fake_sh()
        params, veneers = self.p1_read.locate(sh)
        self.assertEqual(params, self.h.resident())
        self.assertEqual(veneers, [CAVE_START, CAVE_START + 8])
        header = self.p1_read.read_words(sh, params, 8)
        self.assertEqual(header[0], 0x31504350)
        self.assertEqual(header[2:4], [1, 1])
        self.assertEqual(header[6], 2)
        ring = self.p1_read.read_words(sh, params + P_RING, 8)
        self.assertEqual(ring[1:4] + ring[5:8], [0x21, 0x11, 0, 0x22, 0x12, 1])
        self.assertTrue(all(line.startswith('mem get ') and retries == 0
                            for line, retries in self.commands))

    def test_stops_on_a_missing_word(self):
        params = self.h.resident()
        sh = self.fake_sh(drop=params + 4)
        with self.assertRaises(self.p1_read.ReadStopped):
            self.p1_read.read_words(sh, params, 8)
        self.assertEqual(len(self.commands), 1)

    def test_says_so_when_nothing_is_installed(self):
        h = Harness(site_words={SITE_B: 0xEB000000})
        h.run_launcher()
        self.h = h
        with self.assertRaises(self.p1_read.ReadStopped):
            self.p1_read.locate(self.fake_sh())


class CardDeclaresItsSites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = pathlib.Path(cls.tmp.name) / 'card'
        subprocess.run([sys.executable, '-B', str(HERE / 'build_precap.py'), '--out', str(out)],
                       check=True, capture_output=True, text=True)
        cls.files = sorted(p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file())
        cls.bin = (out / 'fpSup.BIN').read_bytes()
        cls.autorun = (out / 'AutoRun.txt').read_text()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def sections(self):
        magic, count, entry, length = struct.unpack_from('<4sIII', self.bin)
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
        for site in (SITE_A, SITE_B):
            self.assertEqual(sections.get(site), [struct.pack('<I', 0xE12FFF33)])

    def test_the_launcher_is_carried_unchanged(self):
        blob, _ = build_precap.build_blob()
        self.assertEqual(self.bin.count(blob), 1)

    def test_the_card_carries_only_the_text_banner(self):
        self.assertEqual(self.files, ['AutoRun.txt', 'fpSup.BIN', 'precap.bin'])
        self.assertNotIn('four-box', self.autorun.lower())
        self.assertIn(build_precap.BANNER, self.autorun)

    def test_no_persistent_or_fast_start_paths(self):
        lowered = self.autorun.lower()
        for word in ('store', 'commonsave', 'sdcard format', 'menu set', 'setting write'):
            self.assertNotIn(word, lowered)

    def test_sites_in_source_match_the_declared_sites(self):
        source = (HERE / 'pc_launch.S').read_text()
        for site in (SITE_A, SITE_B):
            self.assertIn(f'0x{site:08X}', source)
        self.assertEqual(source.count('ARM     SITE_'), 2)


if __name__ == '__main__':
    unittest.main()
