"""The REC producer-facts provider: host behaviour, mutations, and the two
firmware tables it relies on, executed from the pinned image.

Host tests compile producer_facts.c with its five firmware services
substituted by producer_facts_fixture.c. The substitutes model a refcounted
descriptor that is POISONED on release, so a read after the reference is
returned shows up as wrong facts rather than passing silently.

The firmware tests run the original instructions of C0135D40 (raster size by
Sigpro format) and C00C9BD0 (the FrameRate tag's table) in Unicorn. They are
what makes the format->bits and rate-code decisions in producer_facts.c facts
about THIS firmware rather than readings of a decompiler. C0437140, the
LiveViewState query, needs runtime tables and is not executed here.

No camera, USB or card is touched.
"""
import ctypes as ct
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
IMAGE = ROOT / 'out/seg0_c0000000.bin'
IMAGE_SHA256 = 'aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622'
OK, INVALID, BUSY, UNSUPPORTED, NOT_READY, FAULT = range(6)
READY_UI, READY_CAPTURE = 1, 0x7E
CINE, CDNG, SD, READINESS = range(4)
FHD = (1936, 1090)
FHD_RASTER = 3165372          # StripByteCounts of a stock FHD 12-bit frame
KNOWN_RATES = {1: (24000, 1001), 2: (24000, 1000), 3: (25000, 1000),
               4: (30000, 1001), 6: (48000, 1000), 7: (50000, 1000),
               8: (60000, 1001), 9: (100000, 1000), 10: (120000, 1001)}

# Field indices into fpl_fixture_get.
FIRMWARE, C_CINE, COMPRESSION, BITS, WIDTH, HEIGHT, FPS_NUM, FPS_DEN, MEDIA, READY = range(10)
REFS, QUERIES, RELEASES, READINESS_CALLS, READINESS_RESERVED, READS, LAST = range(10, 17)
SEEN_W, SEEN_H, SEEN_FMT, SEEN_BITS, SEEN_RASTER, SEEN_CODE, SEEN_NUM, SEEN_DEN = range(20, 28)


def compile_host(directory, source=None, name='facts.dylib'):
    source = source or HERE / 'producer_facts.c'
    out = Path(directory) / name
    subprocess.run([shutil.which('clang') or 'clang', '-shared', '-fPIC', '-O2',
                    '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-DFPL_PRODUCER_FACTS_HOST_TEST', '-I', str(HERE),
                    str(source), str(HERE / 'producer_facts_fixture.c'),
                    '-o', str(out)],
                   check=True, capture_output=True, text=True, timeout=30)
    lib = ct.CDLL(str(out))
    for name, count in {'reset': 4, 'read': 1, 'get': 1, 'match': 2,
                        'read_uninitialised': 0, 'reinit': 0}.items():
        fn = getattr(lib, 'fpl_fixture_' + name)
        fn.argtypes = [ct.c_uint32] * count
        fn.restype = ct.c_uint32
    for name, count in {'probe': 2, 'drop_probe': 1, 'readiness': 1,
                        'fail': 1, 'descriptor': 2}.items():
        fn = getattr(lib, 'fpl_fixture_' + name)
        fn.argtypes = [ct.c_uint32] * count
        fn.restype = None
    return lib


def mutant(directory, name, old, new):
    text = (HERE / 'producer_facts.c').read_text()
    if text.count(old) != 1:
        raise AssertionError(f'mutation seam {name!r} not found exactly once')
    source = Path(directory) / f'{name}.c'
    source.write_text(text.replace(old, new))
    return compile_host(directory, source, f'{name}.dylib')


class HostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-facts-')
        cls.lib = compile_host(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def reset(self, width=FHD[0], height=FHD[1], fmt=0, code=1, lib=None):
        self.assertEqual((lib or self.lib).fpl_fixture_reset(width, height, fmt, code), OK)

    def get(self, field, lib=None):
        return (lib or self.lib).fpl_fixture_get(field)

    def released(self, lib=None):
        self.assertEqual(self.get(REFS, lib), 0, 'a descriptor reference was kept')
        self.assertEqual(self.get(QUERIES, lib), self.get(RELEASES, lib))

    def test_fhd_12_bit_reads_what_the_creator_will_allocate_for(self):
        self.reset()
        self.assertEqual(self.lib.fpl_fixture_read(0), OK)
        self.assertEqual((self.get(WIDTH), self.get(HEIGHT), self.get(BITS)),
                         (1936, 1090, 12))
        self.assertEqual(self.get(SEEN_RASTER), FHD_RASTER)
        self.assertEqual((self.get(FPS_NUM), self.get(FPS_DEN)), (24000, 1001))
        self.assertEqual(self.get(FIRMWARE), 502)
        self.released()

    def test_every_packed_format_maps_to_the_codecs_depth_order(self):
        for fmt, bits in ((0, 12), (1, 14), (2, 16), (3, 10), (4, 8)):
            with self.subTest(fmt=fmt):
                self.reset(fmt=fmt)
                self.assertEqual(self.lib.fpl_fixture_read(0), OK)
                self.assertEqual(self.get(BITS), bits)
                self.released()

    def test_sigpro_converted_and_unknown_formats_are_refused(self):
        for fmt in (5, 7, 0x10002, 0x20004, 0x20007):
            with self.subTest(fmt=hex(fmt)):
                self.reset(fmt=fmt)
                self.assertEqual(self.lib.fpl_fixture_read(0), UNSUPPORTED)
                self.assertEqual(self.get(READY), 0)
                self.released()

    def test_known_rate_codes_carry_the_tags_own_rate(self):
        for code, rate in KNOWN_RATES.items():
            with self.subTest(code=code):
                self.reset(code=code)
                self.assertEqual(self.lib.fpl_fixture_read(0), OK)
                self.assertEqual((self.get(FPS_NUM), self.get(FPS_DEN)), rate)

    def test_a_rate_code_that_would_fall_to_the_default_is_refused(self):
        """C00C9BD0 labels any code it does not know 30000/1001. Trusting that
        would write a guessed frame rate into every file."""
        # Every code the firmware test shows falling to the default, plus
        # the extremes: the C set and the firmware's set cannot drift apart.
        for code in [c for c in range(17) if c not in KNOWN_RATES] + [0xFFFF, 0xFFFFFFFF]:
            with self.subTest(code=code):
                self.reset(code=code)
                self.assertEqual(self.lib.fpl_fixture_read(0), UNSUPPORTED)
                self.released()

    def test_zero_dimensions_are_refused(self):
        for w, h in ((0, 1090), (1936, 0)):
            with self.subTest(w=w, h=h):
                self.reset(w, h)
                self.assertEqual(self.lib.fpl_fixture_read(0), UNSUPPORTED)
                self.released()

    def test_a_missing_settings_object_or_descriptor_is_not_ready(self):
        for which in (0, 1):
            with self.subTest(which=which):
                self.reset()
                self.lib.fpl_fixture_fail(which)
                self.assertEqual(self.lib.fpl_fixture_read(0), NOT_READY)
                self.assertEqual(self.get(READY), 0)
                self.released()

    def test_an_unknown_mode_fact_refuses_and_a_known_no_is_passed_on(self):
        """Unknown is not a no. A probe that cannot answer refuses the read; a
        probe that answers 'not SD' is passed through for control to refuse."""
        for which in (CINE, CDNG, SD):
            with self.subTest(which=which, case='missing'):
                self.reset()
                self.lib.fpl_fixture_drop_probe(which)
                self.assertEqual(self.lib.fpl_fixture_read(0), NOT_READY)
            with self.subTest(which=which, case='unanswerable'):
                self.reset()
                self.lib.fpl_fixture_probe(which, 2)
                self.assertEqual(self.lib.fpl_fixture_read(0), NOT_READY)
            with self.subTest(which=which, case='no'):
                self.reset()
                self.lib.fpl_fixture_probe(which, 0)
                self.assertEqual(self.lib.fpl_fixture_read(0), OK)
                self.assertEqual(self.get((C_CINE, COMPRESSION, MEDIA)[which]), 0)

    def test_no_readiness_provider_means_no_readiness(self):
        self.reset()
        self.lib.fpl_fixture_drop_probe(READINESS)
        self.assertEqual(self.lib.fpl_fixture_read(0), OK)
        self.assertEqual(self.get(READY), 0)

    def test_readiness_is_passed_through_never_widened(self):
        for value in (0, READY_UI, 0x02, 0x40, READY_CAPTURE, 0x7F, 1 << 31):
            with self.subTest(value=hex(value)):
                self.reset()
                self.lib.fpl_fixture_readiness(value)
                self.assertEqual(self.lib.fpl_fixture_read(12345), OK)
                self.assertEqual(self.get(READY), value)
                self.assertEqual(self.get(READINESS_RESERVED), 12345)

    def test_readiness_is_not_asked_when_the_facts_already_failed(self):
        self.reset(code=0)
        self.lib.fpl_fixture_readiness(READY_CAPTURE)
        self.assertEqual(self.lib.fpl_fixture_read(0), UNSUPPORTED)
        self.assertEqual(self.get(READINESS_CALLS), 0)
        self.assertEqual(self.get(READY), 0)

    def test_a_failed_read_leaves_the_previous_facts_intact(self):
        self.reset()
        self.assertEqual(self.lib.fpl_fixture_read(0), OK)
        self.lib.fpl_fixture_descriptor(0, 3840)
        self.lib.fpl_fixture_probe(SD, 2)
        self.assertEqual(self.lib.fpl_fixture_read(0), NOT_READY)
        self.assertEqual(self.get(SEEN_W), 1936)
        self.assertEqual(self.get(LAST), NOT_READY)

    def test_a_frames_descriptor_matches_on_its_format_words_only(self):
        """Width, height and format must match; every other word may differ.
        On the camera word 15 of each frame's copy is that frame's own buffer
        address, so demanding all eighteen refused all 133 frames (2026-09-30)."""
        self.reset()
        self.assertEqual(self.lib.fpl_fixture_match(99, 0), 0, 'matched before any read')
        self.assertEqual(self.lib.fpl_fixture_read(0), OK)
        self.assertEqual(self.lib.fpl_fixture_match(99, 0), 1)
        for index in range(18):
            with self.subTest(index=index):
                expected = 0 if index in (0, 1, 8) else 1
                self.assertEqual(self.lib.fpl_fixture_match(index, 0x5A5A5A5A), expected)
        self.assertEqual(self.lib.fpl_fixture_match(15, 0x54136800), 1)

    def test_storage_must_be_fresh_and_initialised(self):
        self.reset()
        self.assertEqual(self.lib.fpl_fixture_reinit(), INVALID)
        self.assertEqual(self.lib.fpl_fixture_read_uninitialised(), INVALID)


class MutationTests(unittest.TestCase):
    """Each defect, applied to an isolated copy, must fail a host check."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-facts-mut-')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def build(self, name, old, new):
        lib = mutant(self.tmp.name, name, old, new)
        self.assertEqual(lib.fpl_fixture_reset(1936, 1090, 0, 1), OK)
        return lib

    def test_releasing_before_copying_is_caught_by_the_poison(self):
        lib = self.build(
            'release-first',
            '    facts_copy(seen.descriptor, descriptor, FPL_FACTS_DESCRIPTOR_WORDS);\n'
            '    /* Nothing below reads the object: its reference is returned first. */\n'
            '    native_release(&obj, RELEASE_REF_ONLY);',
            '    native_release(&obj, RELEASE_REF_ONLY);\n'
            '    facts_copy(seen.descriptor, descriptor, FPL_FACTS_DESCRIPTOR_WORDS);')
        result = lib.fpl_fixture_read(0)
        self.assertTrue(result != OK or lib.fpl_fixture_get(WIDTH) != 1936)

    def test_trusting_every_rate_code_is_caught(self):
        lib = self.build('any-rate', 'if (!rate_code_known(seen.rate_code))',
                         'if (0 && !rate_code_known(seen.rate_code))')
        lib.fpl_fixture_reset(1936, 1090, 0, 0)
        self.assertEqual(lib.fpl_fixture_read(0), OK)   # the defect: it passes

    def test_inventing_readiness_is_caught(self):
        lib = self.build('invented-ready',
                         'f->readiness(f->readiness_context, reserved_bytes) : 0;',
                         'f->readiness(f->readiness_context, reserved_bytes) : 0x7Eu;')
        lib.fpl_fixture_drop_probe(READINESS)
        self.assertEqual(lib.fpl_fixture_read(0), OK)
        self.assertNotEqual(lib.fpl_fixture_get(READY), 0)   # the defect

    def test_skipping_a_mode_probe_is_caught(self):
        lib = self.build(
            'no-sd-probe',
            '(result = probe(f->sd_media, f->probe_context, &out->media)) != FPL_OK)',
            '(out->media = 1, 0))')
        lib.fpl_fixture_drop_probe(SD)
        self.assertEqual(lib.fpl_fixture_read(0), OK)       # the defect

    def test_every_mutation_above_actually_differs_from_the_real_module(self):
        real = compile_host(self.tmp.name, name='real.dylib')
        real.fpl_fixture_reset(1936, 1090, 0, 0)
        self.assertEqual(real.fpl_fixture_read(0), UNSUPPORTED)
        real.fpl_fixture_reset(1936, 1090, 0, 1)
        real.fpl_fixture_drop_probe(READINESS)
        self.assertEqual(real.fpl_fixture_read(0), OK)
        self.assertEqual(real.fpl_fixture_get(READY), 0)
        real.fpl_fixture_reset(1936, 1090, 0, 1)
        real.fpl_fixture_drop_probe(SD)
        self.assertEqual(real.fpl_fixture_read(0), NOT_READY)


class ArmCompileTests(unittest.TestCase):
    def test_it_builds_freestanding_for_the_camera(self):
        with tempfile.TemporaryDirectory(prefix='fpl-facts-arm-') as tmp:
            out = Path(tmp) / 'producer_facts.o'
            subprocess.run([shutil.which('clang') or 'clang', '--target=armv7a-none-eabi',
                            '-mcpu=cortex-a9', '-mthumb', '-mfloat-abi=soft', '-mfpu=none',
                            '-ffreestanding', '-fno-builtin', '-nostdlib', '-O2',
                            '-std=c11', '-Wall', '-Wextra', '-Werror', '-c',
                            '-I', str(HERE), str(HERE / 'producer_facts.c'), '-o', str(out)],
                           check=True, capture_output=True, text=True, timeout=30)
            self.assertGreater(out.stat().st_size, 0)
            symbols = subprocess.run([shutil.which('llvm-nm') or shutil.which('nm') or 'nm',
                                      '-u', str(out)], capture_output=True, text=True).stdout
            # Five firmware services are reached through absolute function
            # pointers, never through a link-time symbol.
            self.assertNotIn('fpl_test_', symbols)
            for forbidden in ('memcpy', 'memset', '__aeabi'):
                self.assertNotIn(forbidden, symbols, symbols)


class FirmwareTableTests(unittest.TestCase):
    """The two tables the provider's decisions rest on, run from the image."""

    @classmethod
    def setUpClass(cls):
        from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
        cls.Uc, cls.UC_ARCH_ARM, cls.UC_MODE_ARM, cls.UC_HOOK_CODE = (
            Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE)
        image = IMAGE.read_bytes()
        if hashlib.sha256(image).hexdigest() != IMAGE_SHA256:
            raise AssertionError('firmware image hash differs; original ARM unverified')
        cls.image = image

    def machine(self):
        from unicorn import UC_PROT_ALL
        uc = self.Uc(self.UC_ARCH_ARM, self.UC_MODE_ARM)
        base, size = 0xC0000000, (len(self.image) + 0xFFF) & ~0xFFF
        uc.mem_map(base, size, UC_PROT_ALL)
        uc.mem_write(base, self.image)
        uc.mem_map(0x46000000, 0x20000, UC_PROT_ALL)     # stack + scratch
        uc.mem_map(0x47000000, 0x1000, UC_PROT_ALL)      # return trap
        return uc

    def execute(self, uc, entry, args, thumb=False, hooks=None, limit=4000):
        from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                       UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR,
                                       UC_ARM_REG_PC)
        stop = 0x47000000
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                               UC_ARM_REG_R3), args):
            uc.reg_write(reg, value)
        uc.reg_write(UC_ARM_REG_SP, 0x46010000)
        uc.reg_write(UC_ARM_REG_LR, stop)

        self.trace = set()

        def code(u, address, size, data):
            self.trace.add(address)
            if hooks and address in hooks:
                u.reg_write(UC_ARM_REG_R0, hooks[address](u))
                u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))
        uc.hook_add(self.UC_HOOK_CODE, code)
        uc.emu_start(entry | (1 if thumb else 0), stop, timeout=500000, count=limit)
        self.assertEqual(uc.reg_read(UC_ARM_REG_PC) & ~1, stop, 'did not return')
        return uc.reg_read(UC_ARM_REG_R0)

    def test_c0135d40_is_packed_12_14_16_10_8_with_a_longer_last_row(self):
        def mine(w, h, bits):
            row = lambda width: (width * bits // 8 + 3) & ~3
            return (h - 1) * row(w) + row((w + 11) // 12 * 12)
        self.assertEqual(self.execute(self.machine(), 0xC0135D40, (1936, 1090, 0), thumb=True),
                         FHD_RASTER)
        for fmt, bits in ((0, 12), (1, 14), (2, 16), (3, 10), (4, 8)):
            for w, h in ((1920, 1080), (1936, 1090), (3840, 2160), (6064, 4042), (512, 368)):
                with self.subTest(fmt=fmt, w=w, h=h):
                    self.assertEqual(
                        self.execute(self.machine(), 0xC0135D40, (w, h, fmt), thumb=True),
                        mine(w, h, bits))

    def rate(self, code):
        mgr, settings, out = 0x46011000, 0x46012000, 0x46013000
        uc = self.machine()
        uc.mem_write(mgr + 0x5C, struct.pack('<I', settings))
        uc.mem_write(settings + 0x14, struct.pack('<I', code))
        # C0021C00's one-time init needs runtime tables: return the singleton
        # directly. C0021C40 and the table itself run as they are.
        self.execute(uc, 0xC00C9BD0, (out,), hooks={0xC0021C00: lambda u: mgr})
        return struct.unpack('<II', uc.mem_read(out, 8)), frozenset(self.trace)

    def test_c00c9bd0_gives_each_accepted_code_its_rate(self):
        for code, expected in KNOWN_RATES.items():
            with self.subTest(code=code):
                self.assertEqual(self.rate(code)[0], expected)

    def test_c00c9bd0_sends_exactly_the_refused_codes_to_its_default(self):
        """Values cannot tell a default from an explicit case here: code 4 is
        explicit and ALSO 30000/1001. So compare the instructions executed.
        The default block is what a plainly unknown code runs and code 4 does
        not; a code is a default iff it runs that block."""
        _, unknown = self.rate(0xFFFF)
        _, four = self.rate(4)
        default_block = unknown - four
        self.assertTrue(default_block, 'code 4 and the default share every instruction')
        for code in range(0, 16):
            with self.subTest(code=code):
                rate, trace = self.rate(code)
                took_default = default_block <= trace
                self.assertEqual(took_default, code not in KNOWN_RATES)
                if took_default:
                    self.assertEqual(rate, (30000, 1001))


if __name__ == '__main__':
    unittest.main()
