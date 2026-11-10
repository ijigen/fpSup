"""Execute REC glue + real layout/core/native-allocation wrapper on the host.

Only ROM services and producer facts are synthetic. No camera imports or USB.
Separate raw-workspace ARM tests verify native call ABI. This test does not
claim the future producer-facts provider, installed hook or DMA bound exists.
"""
import ctypes as ct
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
OK, INVALID, BUSY, UNSUPPORTED, NOT_READY, FAULT = range(6)


def build(directory, mutation=False):
    source = HERE / 'rec_workspace.c'
    if mutation:
        text = source.read_text()
        original = ('r->native_result = native_prepare(camera, request);\n'
                    '    if (!r->native_result) return refuse(r, FPL_NOT_READY);')
        if text.count(original) != 1:
            raise AssertionError('missing original-preparation mutation seam')
        # Isolated copy; never mutate the shared source tree.
        source = Path(directory) / 'missing-native-prepare.c'
        source.write_text(text.replace(original, '(void)native_prepare; r->native_result = 1;'))
    destination = Path(directory) / ('mutant.dylib' if mutation else 'rec.dylib')
    command = [shutil.which('clang') or 'clang', '-shared', '-fPIC', '-O2', '-std=c11',
               '-Wall', '-Wextra', '-Werror', '-DFPL_RAW_WORKSPACE_HOST_TEST',
               '-DFPL_REC_WORKSPACE_HOST_TEST', '-I', str(HERE),
               str(source), str(HERE / 'raw_workspace.c'), str(HERE / 'workspace_layout.c'),
               str(HERE.parent / 'control.c'), str(HERE.parent / 'frame_pipeline.c'),
               str(HERE / 'rec_workspace_fixture.c'), '-o', str(destination)]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    lib = ct.CDLL(str(destination))
    for name, count in {'reset': 4, 'flags': 1, 'prepare': 1, 'finish': 2, 'stop': 1,
                        'reinit': 0, 'read': 1, 'missing_provider': 0,
                        'pending': 0, 'abort_pending': 0}.items():
        method = getattr(lib, 'fpl_fixture_' + name)
        method.argtypes = [ct.c_uint32] * count
        method.restype = ct.c_uint32
    return lib


class RecWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='fpl-rec-workspace-')
        cls.lib = build(cls.directory.name)
        cls.mutant = build(cls.directory.name, True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.assertEqual(self.lib.fpl_fixture_reset(1936, 1090, 12, 0), OK)

    def read(self, field):
        return self.lib.fpl_fixture_read(field)

    def prepare(self):
        return self.lib.fpl_fixture_prepare(3)

    def test_native_prepare_then_allocate_then_admit(self):
        self.assertEqual(self.prepare(), 1)
        trace = [self.read(i + 32) for i in range(self.read(12))]
        self.assertEqual(trace[0], 1)
        self.assertLess(trace.index(1), trace.index(5))
        self.assertLess(trace.index(5), trace.index(4))
        self.assertLess(trace.index(4), trace.index(6))
        self.assertEqual((self.read(1), self.read(2), self.read(7), self.read(8)), (1, 0, 1, 2))
        self.assertEqual(self.read(11), 0)

    def test_6k_12bit_is_larger_than_old_16mib_observation(self):
        self.lib.fpl_fixture_reset(6064, 4042, 12, 0)
        self.assertEqual(self.prepare(), 1)
        self.assertGreater(self.read(9), 16 << 20)
        self.assertGreater(self.read(4), self.read(9))
        self.assertEqual(self.read(4) % 1024, 0)

    def test_source_copy_changes_reservation_before_recording(self):
        self.assertEqual(self.prepare(), 1)
        no_copy = self.read(4)
        self.lib.fpl_fixture_reset(1936, 1090, 12, 1)
        self.assertEqual(self.prepare(), 1)
        self.assertEqual(self.read(4) - no_copy, (1936 * 1090 * 12 // 8 + 1023) & ~1023)

    def test_no_output_span_reserves_one_raster_less_and_keeps_the_rest_packed(self):
        self.assertEqual(self.prepare(), 1)
        full = [self.read(i) for i in (4, 14, 22, 23, 21)]
        self.lib.fpl_fixture_reset(3024, 2010, 12, 2)          # no output span
        self.assertEqual(self.prepare(), 1)
        self.assertEqual(self.read(9), 0)
        self.lib.fpl_fixture_reset(3024, 2010, 12, 0)
        self.assertEqual(self.prepare(), 1)
        with_output = self.read(14)
        raster = (3024 * 2010 * 12 // 8 + 1023) & ~1023
        self.lib.fpl_fixture_reset(3024, 2010, 12, 2)
        self.assertEqual(self.prepare(), 1)
        self.assertEqual(with_output - self.read(14), raster)
        self.assertEqual(self.read(4), self.read(14), 'reserved size is not the planned total')
        # the remaining spans follow each other with no gap and no overlap
        spans = [(self.read(16), self.read(22)), (self.read(17), self.read(22)),
                 (self.read(18), self.read(23)), (self.read(19), self.read(21)),
                 (self.read(20), self.read(21))]
        self.assertEqual(spans[0][0], self.read(15))
        for (a, n), (b, _) in zip(spans, spans[1:]):
            self.assertEqual(a + n, b)
        self.assertEqual(spans[-1][0] + spans[-1][1], self.read(14))
        del full

    def test_original_refusal_and_wrong_mode_do_not_allocate(self):
        for flags in (1, 32):
            self.lib.fpl_fixture_reset(1936, 1090, 12, 0)
            self.lib.fpl_fixture_flags(flags)
            self.assertEqual(self.prepare(), 0)
            self.assertEqual((self.read(1), self.read(2), self.read(7)), (0, 0, 0))

    def test_unsupported_event_and_missing_provider_never_call_native(self):
        self.assertEqual(self.lib.fpl_fixture_prepare(0x24), 0)   # the stop
        self.assertEqual(self.read(0), UNSUPPORTED)
        self.assertEqual(self.lib.fpl_fixture_missing_provider(), 0)
        self.assertEqual((self.read(0), self.read(3), self.read(1)), (NOT_READY, 0, 0))

    def test_the_movie_button_event_starts_a_take_like_event_3(self):
        """0x23 is what the movie button sent on the camera (2026-09-30)."""
        self.assertEqual(self.lib.fpl_fixture_prepare(0x23), 1)
        self.assertEqual(self.read(11), 0)

    def test_allocation_refusal_is_not_successful_raw_recording(self):
        self.lib.fpl_fixture_flags(2)
        self.assertEqual(self.prepare(), 0)
        self.assertEqual((self.read(0), self.read(1), self.read(2), self.read(8)), (NOT_READY, 1, 0, 0))

    def test_post_reserve_headroom_or_geometry_failure_rolls_back(self):
        for flags in (4, 8, 16):
            self.lib.fpl_fixture_reset(1936, 1090, 12, 0)
            self.lib.fpl_fixture_flags(flags)
            self.assertEqual(self.prepare(), 0)
            self.assertEqual((self.read(1), self.read(2), self.read(5), self.read(7), self.read(8)),
                             (1, 1, 0, 0, 0))

    def test_stays_reserved_until_quiescent_finish(self):
        self.assertEqual(self.prepare(), 1)
        self.assertEqual(self.lib.fpl_fixture_stop(1), OK)
        self.assertEqual(self.read(2), 0)
        self.assertEqual(self.lib.fpl_fixture_finish(1, 0), BUSY)
        self.assertEqual(self.read(2), 0)
        self.assertEqual(self.lib.fpl_fixture_finish(1, 1), OK)
        self.assertEqual((self.read(2), self.read(5), self.read(7), self.read(8)), (1, 0, 0, 0))
        self.assertEqual(self.lib.fpl_fixture_finish(1, 1), INVALID)
        self.assertEqual(self.read(2), 1)

    def test_same_mode_second_recording_reserves_again_and_rejects_old_finish(self):
        self.assertEqual(self.prepare(), 1)
        self.assertEqual(self.lib.fpl_fixture_finish(1, 1), OK)
        self.assertEqual(self.prepare(), 1)
        self.assertEqual((self.read(1), self.read(6), self.read(3)), (2, 2, 2))
        self.assertEqual(self.read(11), 0)
        self.assertEqual(self.lib.fpl_fixture_finish(1, 1), INVALID)
        self.assertEqual(self.read(2), 1)
        self.assertEqual(self.lib.fpl_fixture_finish(2, 1), OK)

    def test_start_cancel_releases_even_without_frames(self):
        self.assertEqual(self.prepare(), 1)
        self.assertEqual(self.lib.fpl_fixture_finish(1, 1), OK)
        self.assertEqual(self.read(2), 1)

    def test_inflight_source_cannot_release_output_even_with_quiet_claim(self):
        self.assertEqual(self.prepare(), 1)
        self.assertEqual(self.lib.fpl_fixture_pending(), OK)
        self.assertEqual(self.lib.fpl_fixture_finish(1, 1), BUSY)
        self.assertEqual(self.read(2), 0)
        self.assertEqual(self.lib.fpl_fixture_abort_pending(), OK)
        self.assertEqual(self.lib.fpl_fixture_finish(1, 1), OK)
        self.assertEqual(self.prepare(), 0)
        self.assertEqual(self.read(0), FAULT)

    def test_no_duplicate_prepare_or_reset_live_memory(self):
        self.assertEqual(self.prepare(), 1)
        self.assertEqual(self.prepare(), 0)
        self.assertEqual(self.read(0), BUSY)
        self.assertEqual(self.lib.fpl_fixture_reinit(), INVALID)
        self.assertEqual((self.read(1), self.read(3), self.read(2)), (1, 1, 0))

    def test_14bit_budget_does_not_bypass_control_rejection(self):
        self.lib.fpl_fixture_reset(6064, 4042, 14, 0)
        self.assertEqual(self.prepare(), 0)
        self.assertEqual((self.read(0), self.read(1), self.read(7)), (UNSUPPORTED, 0, 0))

    def test_missing_native_prepare_mutation_is_detected(self):
        self.mutant.fpl_fixture_reset(1936, 1090, 12, 0)
        self.assertEqual(self.prepare(), 1)
        # Removing native prepare leaves the fixture's initial map=0, so the
        # real raw wrapper correctly refuses allocation. This directly catches
        # a design that reserves in the wrong map before original preparation.
        self.assertEqual(self.mutant.fpl_fixture_prepare(3), 0)
        self.assertEqual(self.mutant.fpl_fixture_read(3), 0)
        with self.assertRaises(AssertionError):
            self.assertEqual(self.mutant.fpl_fixture_prepare(3), 1)


if __name__ == '__main__':
    unittest.main()
