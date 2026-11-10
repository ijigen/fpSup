"""Exercise the exact C core on host, and compile it for the camera CPU.

No camera imports, firmware writes, transport, or optional/skipped checks.
Readiness used below is synthetic and never constitutes hardware approval.
"""
import ctypes as ct
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
OK, INVALID, BUSY, UNSUPPORTED, NOT_READY, FAULT = range(6)
IDLE, RAW, LOSSLESS, STOP = range(4)


class State(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in
                ('magic', 'abi', 'requested', 'clip', 'frames', 'fault',
                 'reserved0', 'reserved1')]


class Context(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in
                ('firmware', 'cine', 'compression', 'bits', 'width', 'height',
                 'fps_num', 'fps_den', 'media', 'ready')]


def eligible():
    return Context(502, 1, 1, 12, 1936, 1090, 24000, 1001, 1, 127)


class ControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('clang')
        if not cls.compiler:
            raise RuntimeError('clang is required; refusing to skip code execution')
        cls.temp = tempfile.TemporaryDirectory(prefix='fpl-control-')
        cls.addClassCleanup(cls.temp.cleanup)
        lib = Path(cls.temp.name) / 'control.dylib'
        subprocess.run([cls.compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-shared', '-fPIC', str(HERE / 'control.c'),
                        str(HERE / 'ui_control.c'), '-o', str(lib)],
                       check=True, capture_output=True, text=True)
        cls.lib = ct.CDLL(str(lib))
        cls.lib.fpl_boot.argtypes = [ct.POINTER(State)]
        cls.lib.fpl_boot.restype = None
        cls.lib.fpl_can_enable.argtypes = [ct.POINTER(Context)]
        cls.lib.fpl_menu_value.argtypes = [ct.POINTER(State)]
        cls.lib.fpl_set.argtypes = [ct.POINTER(State), ct.c_uint32, ct.POINTER(Context)]
        cls.lib.fpl_begin.argtypes = [ct.POINTER(State), ct.POINTER(Context)]
        cls.lib.fpl_begin_direct.argtypes = [ct.POINTER(State), ct.POINTER(Context)]
        cls.lib.fpl_frame_done.argtypes = [ct.POINTER(State)]
        cls.lib.fpl_fail.argtypes = [ct.POINTER(State), ct.c_uint32]
        cls.lib.fpl_end.argtypes = [ct.POINTER(State), ct.c_uint32]
        for name in ('fpl_can_enable', 'fpl_menu_value', 'fpl_set', 'fpl_begin',
                     'fpl_begin_direct', 'fpl_frame_done', 'fpl_fail', 'fpl_end'):
            getattr(cls.lib, name).restype = ct.c_uint32

    def setUp(self):
        self.s, self.c = State(), eligible()
        self.lib.fpl_boot(ct.byref(self.s))

    def set_value(self, enabled):
        return self.lib.fpl_set(ct.byref(self.s), enabled, ct.byref(self.c))

    def begin(self):
        return self.lib.fpl_begin(ct.byref(self.s), ct.byref(self.c))

    def test_struct_abi(self):
        self.assertEqual(ct.sizeof(State), 32)
        self.assertEqual(ct.sizeof(Context), 40)

    def test_camera_arm_cross_compiles(self):
        for source in ('control', 'ui_control'):
            obj = Path(self.temp.name) / (source + '.arm.o')
            subprocess.run([self.compiler, '--target=armv7-none-eabi', '-mcpu=cortex-a9',
                            '-marm', '-mfloat-abi=soft', '-mfpu=none', '-std=c11',
                            '-Os', '-ffreestanding', '-fno-builtin',
                            '-Wall', '-Wextra', '-Werror', '-c', str(HERE / (source + '.c')),
                            '-o', str(obj)], check=True, capture_output=True, text=True)
            data = obj.read_bytes()
            self.assertEqual(data[:4], b'\x7fELF')
            self.assertEqual(int.from_bytes(data[18:20], 'little'), 40)  # EM_ARM

    def test_boot_clears_stale_state_to_off(self):
        ct.memset(ct.byref(self.s), 0xff, ct.sizeof(self.s))
        self.lib.fpl_boot(ct.byref(self.s))
        self.assertEqual((self.s.magic, self.s.abi), (0x46504c53, 1))
        self.assertEqual(bytes(self.s)[8:], bytes(24))

    def test_all_128_readiness_combinations(self):
        for flags in range(128):
            with self.subTest(flags=flags):
                self.c.ready = flags
                expected = OK if flags == 127 else NOT_READY
                self.assertEqual(self.lib.fpl_can_enable(ct.byref(self.c)), expected)

    def test_every_target_predicate_is_required(self):
        wrong = {'firmware': 501, 'cine': 0, 'compression': 7, 'bits': 14,
                 'width': 1937, 'height': 1089, 'fps_num': 0,
                 'fps_den': 0, 'media': 2}
        for field, value in wrong.items():
            with self.subTest(field=field):
                c = eligible()
                setattr(c, field, value)
                self.assertEqual(self.lib.fpl_can_enable(ct.byref(c)), UNSUPPORTED)

    def test_direct_entry_omits_only_ui_for_all_128_combinations(self):
        for flags in range(128):
            with self.subTest(flags=flags):
                self.lib.fpl_boot(ct.byref(self.s))
                self.c.ready = flags
                before, context = bytes(self.s), bytes(self.c)
                result = self.lib.fpl_begin_direct(ct.byref(self.s), ct.byref(self.c))
                self.assertEqual(result, OK if flags in (126, 127) else NOT_READY)
                self.assertEqual(bytes(self.c), context)  # no synthetic UI bit
                if result == OK:
                    self.assertEqual((self.s.requested, self.s.clip, self.s.frames), (1, LOSSLESS, 0))
                else:
                    self.assertEqual(bytes(self.s), before)

    def test_direct_entry_does_not_relax_format_or_explicit_interlock(self):
        wrong = {'firmware': 501, 'cine': 0, 'compression': 7, 'bits': 14,
                 'width': 1937, 'height': 1089, 'fps_num': 0, 'fps_den': 0, 'media': 2}
        for field, value in wrong.items():
            c = eligible()
            c.ready = 126
            setattr(c, field, value)
            before = bytes(self.s)
            self.assertEqual(self.lib.fpl_begin_direct(ct.byref(self.s), ct.byref(c)), UNSUPPORTED)
            self.assertEqual(bytes(self.s), before)
        self.c.ready = 126 | (1 << 31)
        self.assertEqual(self.lib.fpl_begin_direct(ct.byref(self.s), ct.byref(self.c)), FAULT)
        self.assertEqual(self.s.clip, IDLE)

    def test_direct_entry_rechecks_each_take_and_keeps_fault_sticky(self):
        self.c.ready = 126
        self.assertEqual(self.lib.fpl_begin_direct(ct.byref(self.s), ct.byref(self.c)), OK)
        before = bytes(self.s)
        self.assertEqual(self.lib.fpl_begin_direct(ct.byref(self.s), ct.byref(self.c)), BUSY)
        self.assertEqual(bytes(self.s), before)
        self.assertEqual(self.lib.fpl_end(ct.byref(self.s), 0), BUSY)
        self.assertEqual(self.lib.fpl_end(ct.byref(self.s), 1), OK)
        self.c.ready &= ~2
        before = bytes(self.s)
        self.assertEqual(self.lib.fpl_begin_direct(ct.byref(self.s), ct.byref(self.c)), NOT_READY)
        self.assertEqual(bytes(self.s), before)
        self.c.ready = 126
        self.assertEqual(self.lib.fpl_begin_direct(ct.byref(self.s), ct.byref(self.c)), OK)
        self.assertEqual(self.lib.fpl_fail(ct.byref(self.s), 9), FAULT)
        self.assertEqual(self.lib.fpl_end(ct.byref(self.s), 1), OK)
        self.assertEqual(self.lib.fpl_begin_direct(ct.byref(self.s), ct.byref(self.c)), FAULT)
        self.assertEqual(self.s.clip, IDLE)

    def test_direct_entry_does_not_make_menu_on_ready(self):
        self.c.ready = 126
        self.assertEqual(self.set_value(1), NOT_READY)
        self.assertEqual(self.lib.fpl_begin_direct(ct.byref(self.s), ct.byref(self.c)), OK)
        self.assertEqual(self.lib.fpl_can_enable(ct.byref(self.c)), NOT_READY)

    def test_direct_entry_requires_real_state_and_context(self):
        self.assertEqual(self.lib.fpl_begin_direct(None, ct.byref(self.c)), INVALID)
        self.assertEqual(self.lib.fpl_begin_direct(ct.byref(self.s), None), INVALID)
        self.s.reserved0 = 1
        self.assertEqual(self.lib.fpl_begin_direct(ct.byref(self.s), ct.byref(self.c)), INVALID)

    def test_direct_readiness_guard_mutation_is_detected(self):
        source = (HERE / 'control.c').read_text()
        old = 'if ((c->ready & FPL_READY_CAPTURE) != FPL_READY_CAPTURE) return FPL_NOT_READY;'
        self.assertEqual(source.count(old), 1)
        mutant = Path(self.temp.name) / 'direct-mutant.c'
        mutant.write_text(source.replace(old, '/* broken: omitted capture readiness */'))
        target = mutant.with_suffix('.dylib')
        subprocess.run([self.compiler, '-std=c11', '-shared', '-fPIC', '-I', str(HERE),
                        str(mutant), '-o', str(target)], check=True, capture_output=True, text=True)
        lib = ct.CDLL(str(target))
        lib.fpl_begin_direct.argtypes = [ct.POINTER(State), ct.POINTER(Context)]
        lib.fpl_begin_direct.restype = ct.c_uint32
        self.c.ready = 0
        self.assertNotEqual(lib.fpl_begin_direct(ct.byref(self.s), ct.byref(self.c)), NOT_READY)

    def test_requested_format_matrix_requires_its_own_readiness(self):
        # Synthetic candidate facts, NOT camera proof for these formats.
        shapes = ((1024, 576), (1920, 1080), (1936, 1090), (2048, 1152),
                  (3856, 2170), (4096, 2160), (6064, 4042), (6144, 3456))
        for bits in (10, 12):
            for width, height in shapes:
                for num, den in ((24000, 1001), (30000, 1001), (60000, 1001)):
                    with self.subTest(bits=bits, width=width, height=height,
                                      fps=(num, den)):
                        c = Context(502, 1, 1, bits, width, height, num, den, 1, 0)
                        self.assertEqual(self.lib.fpl_can_enable(ct.byref(c)), NOT_READY)
                        c.ready = 127  # explicit synthetic adapter evidence
                        self.assertEqual(self.lib.fpl_can_enable(ct.byref(c)), OK)

    def test_geometry_bounds_and_tile_capacity_are_not_overflowable(self):
        for width, height in ((0, 1090), (7, 1090), (1936, 0), (1936, 1),
                              (0x4008, 2), (8, 0x4002), (0xffffffff, 1090),
                              (1936, 0xffffffff), (0x4000, 0x4000)):
            with self.subTest(width=width, height=height):
                c = eligible()
                c.width, c.height = width, height
                self.assertEqual(self.lib.fpl_can_enable(ct.byref(c)), UNSUPPORTED)
        c = eligible()
        c.width, c.height = 512 * 16, 368 * 10  # exactly 160 tiles
        self.assertEqual(self.lib.fpl_can_enable(ct.byref(c)), OK)
        c.height += 2  # 176 tiles, despite the raster still looking plausible
        self.assertEqual(self.lib.fpl_can_enable(ct.byref(c)), UNSUPPORTED)

    def test_unsupported_depths_do_not_inherit_codec_readiness(self):
        for bits in (0, 8, 11, 14, 16, 32, 0xffffffff):
            c = eligible()
            c.bits = bits
            self.assertEqual(self.lib.fpl_can_enable(ct.byref(c)), UNSUPPORTED)

    def test_format_safety_assertions_detect_isolated_mutations(self):
        # Only temporary source copies are broken; shared runtime is untouched.
        source = (HERE / 'control.c').read_text()
        for index, (before, after, context, expected) in enumerate((
            ('if ((c->ready & FPL_READY_ALL) != FPL_READY_ALL)', 'if (0)',
             Context(502, 1, 1, 10, 6064, 4042, 24000, 1001, 1, 0), NOT_READY),
            ('(c->bits != 10 && c->bits != 12)', '0',
             Context(502, 1, 1, 14, 1936, 1090, 24000, 1001, 1, 127), UNSUPPORTED),
            ('if (columns * rows > FPL_TILE_MAX)', 'if (columns * rows > 0xffffffffu)',
             Context(502, 1, 1, 12, 0x4000, 0x4000, 24000, 1001, 1, 127), UNSUPPORTED),
        )):
            with self.subTest(mutation=index):
                self.assertEqual(source.count(before), 1)
                mutated = Path(self.temp.name) / ('mutation%d.c' % index)
                mutated.write_text(source.replace(before, after))
                output = mutated.with_suffix('.dylib')
                subprocess.run([self.compiler, '-std=c11', '-shared', '-fPIC',
                                '-I', str(HERE), str(mutated), '-o', str(output)],
                               check=True, capture_output=True, text=True)
                lib = ct.CDLL(str(output))
                lib.fpl_can_enable.argtypes = [ct.POINTER(Context)]
                lib.fpl_can_enable.restype = ct.c_uint32
                with self.assertRaises(AssertionError):
                    self.assertEqual(lib.fpl_can_enable(ct.byref(context)), expected)

    def test_menu_changes_only_private_requested_word(self):
        before, context = bytes(self.s), bytes(self.c)
        self.assertEqual(self.set_value(1), OK)
        self.assertEqual(self.lib.fpl_menu_value(ct.byref(self.s)), 1)
        self.assertEqual(bytes(self.s)[:8], before[:8])
        self.assertEqual(bytes(self.s)[12:], before[12:])
        self.assertEqual(bytes(self.c), context)
        self.assertEqual(self.set_value(0), OK)
        self.assertEqual(bytes(self.s), before)

    def test_unready_on_is_rejected_without_mutation(self):
        self.c.ready = 0
        before = bytes(self.s)
        self.assertEqual(self.set_value(1), NOT_READY)
        self.assertEqual(bytes(self.s), before)

    def test_invalid_values_are_not_boolean_coerced(self):
        for value in (2, 255, 0xffffffff):
            before = bytes(self.s)
            self.assertEqual(self.set_value(value), INVALID)
            self.assertEqual(bytes(self.s), before)

    def test_off_requires_no_codec_or_target(self):
        self.assertEqual(self.set_value(1), OK)
        self.assertEqual(self.lib.fpl_set(ct.byref(self.s), 0, None), OK)
        self.assertEqual(self.lib.fpl_begin(ct.byref(self.s), None), OK)
        self.assertEqual(self.s.clip, RAW)

    def test_explicit_binding_interlock_blocks_raw_and_lossless(self):
        for requested in (0, 1):
            self.lib.fpl_boot(ct.byref(self.s))
            self.c = eligible()
            self.assertEqual(self.set_value(requested), OK)
            self.c.ready |= 1 << 31
            before = bytes(self.s)
            self.assertEqual(self.lib.fpl_can_enable(ct.byref(self.c)), FAULT)
            self.assertEqual(self.begin(), FAULT)
            self.assertEqual(bytes(self.s), before)

    def test_changes_locked_for_raw_and_lossless_takes(self):
        for requested, mode in ((0, RAW), (1, LOSSLESS)):
            self.lib.fpl_boot(ct.byref(self.s))
            self.assertEqual(self.set_value(requested), OK)
            self.assertEqual(self.begin(), OK)
            self.assertEqual(self.s.clip, mode)
            before = bytes(self.s)
            for desired in (0, 1):
                self.assertEqual(self.set_value(desired), BUSY)
                self.assertEqual(bytes(self.s), before)
            self.assertEqual(self.begin(), BUSY)

    def test_recheck_at_rec_after_switching_to_unsupported_depth(self):
        self.assertEqual(self.set_value(1), OK)
        self.c.bits = 14
        before = bytes(self.s)
        self.assertEqual(self.begin(), UNSUPPORTED)
        self.assertEqual(bytes(self.s), before)
        self.assertEqual(self.s.clip, IDLE)

    def test_recheck_lost_readiness_at_rec(self):
        self.assertEqual(self.set_value(1), OK)
        self.c.ready &= ~16  # playback adapter unavailable
        self.assertEqual(self.begin(), NOT_READY)
        self.assertEqual(self.s.clip, IDLE)

    def test_two_takes_retain_selection_not_frame_state(self):
        self.assertEqual(self.set_value(1), OK)
        for _ in range(2):
            self.assertEqual(self.begin(), OK)
            self.assertEqual(self.lib.fpl_frame_done(ct.byref(self.s)), OK)
            self.assertEqual(self.s.frames, 1)
            self.assertEqual(self.lib.fpl_end(ct.byref(self.s), 1), OK)
            self.assertEqual((self.s.requested, self.s.clip, self.s.frames), (1, IDLE, 0))

    def test_fault_stops_without_mixing_raw_and_lossless(self):
        self.set_value(1)
        self.begin()
        self.assertEqual(self.lib.fpl_frame_done(ct.byref(self.s)), OK)
        self.assertEqual(self.lib.fpl_fail(ct.byref(self.s), 77), FAULT)
        self.assertEqual((self.s.clip, self.s.frames, self.s.fault), (STOP, 1, 77))
        self.assertEqual(self.lib.fpl_frame_done(ct.byref(self.s)), FAULT)
        self.assertEqual(self.lib.fpl_fail(ct.byref(self.s), 88), FAULT)
        self.assertEqual(self.s.fault, 77)

    def test_no_next_take_before_cleanup(self):
        self.set_value(1)
        self.begin()
        for proof in (0, 2, 0xffffffff):
            before = bytes(self.s)
            self.assertEqual(self.lib.fpl_end(ct.byref(self.s), proof), BUSY)
            self.assertEqual(bytes(self.s), before)

    def test_fault_sticky_but_off_can_restore_stock_recording(self):
        self.set_value(1)
        self.begin()
        self.lib.fpl_fail(ct.byref(self.s), 7)
        self.lib.fpl_end(ct.byref(self.s), 1)
        self.assertEqual(self.begin(), FAULT)
        self.assertEqual(self.set_value(1), FAULT)
        self.assertEqual(self.set_value(0), OK)
        self.assertEqual(self.begin(), OK)
        self.assertEqual(self.s.clip, RAW)

    def test_counter_saturates_without_stopping_a_continuous_take(self):
        self.set_value(1)
        self.begin()
        self.s.frames = 0xffffffff
        for _ in range(3):
            self.assertEqual(self.lib.fpl_frame_done(ct.byref(self.s)), OK)
        self.assertEqual((self.s.clip, self.s.frames, self.s.fault),
                         (LOSSLESS, 0xffffffff, 0))

    def test_continuous_take_has_no_40_frame_limit(self):
        self.assertEqual(self.set_value(1), OK)
        self.assertEqual(self.begin(), OK)
        for n in range(10000):
            self.assertEqual(self.lib.fpl_frame_done(ct.byref(self.s)), OK)
            self.assertEqual((self.s.frames, self.s.clip), (n + 1, LOSSLESS))
        self.assertEqual(self.lib.fpl_end(ct.byref(self.s), 0), BUSY)
        self.assertEqual(self.lib.fpl_end(ct.byref(self.s), 1), OK)

    def test_invalid_state_is_never_written(self):
        for field, value in (('magic', 0), ('abi', 2), ('requested', 2),
                             ('clip', 4), ('reserved0', 1), ('reserved1', 1)):
            self.lib.fpl_boot(ct.byref(self.s))
            setattr(self.s, field, value)
            before = bytes(self.s)
            self.assertEqual(self.set_value(1), INVALID)
            self.assertEqual(self.begin(), INVALID)
            self.assertEqual(self.lib.fpl_menu_value(ct.byref(self.s)), 0)
            self.assertEqual(bytes(self.s), before)

    def test_nulls_and_out_of_take_calls(self):
        self.lib.fpl_boot(None)
        self.assertEqual(self.lib.fpl_can_enable(None), INVALID)
        self.assertEqual(self.lib.fpl_set(None, 1, None), INVALID)
        self.assertEqual(self.lib.fpl_frame_done(ct.byref(self.s)), INVALID)
        self.assertEqual(self.lib.fpl_fail(ct.byref(self.s), 7), INVALID)

    def test_product_is_standalone_and_not_shippable(self):
        manifest = json.loads((HERE / 'manifest.json').read_text())
        self.assertTrue(manifest['standalone'])
        self.assertEqual(manifest['dependencies'], [])
        self.assertFalse(manifest['camera_ready'])
        self.assertEqual(manifest['installed_hooks'], [])
        self.assertEqual(manifest['ui']['default'], 'OFF')
        self.assertFalse(manifest['ui']['native_binding_installed'])
        self.assertFalse((HERE / 'AutoRun.txt').exists())
        self.assertFalse((HERE / 'VSHL.BIN').exists())
        self.assertFalse((HERE / 'fpSup.BIN').exists())

    def test_requested_direct_fast2_build_keeps_usb_shell_without_menu(self):
        # This is a scope regression, not a generated-card or boot test.
        manifest = json.loads((HERE / 'manifest.json').read_text())
        build = manifest['requested_test_build']
        self.assertEqual(build['control_entry'], 'fpl_begin_direct')
        self.assertTrue(build['usb_shell'])
        self.assertEqual(build['usb_shell_source'], 'fp_usb_shell')
        self.assertEqual(build['fast_start'], 2)
        for key in ('menu_included', 'opengate_included', 'gyro_included',
                    'runtime_adapter_installed', 'artifact_produced'):
            self.assertFalse(build[key])
        self.assertTrue(manifest['ui']['deferred_for_current_test_build'])


if __name__ == '__main__':
    unittest.main()
