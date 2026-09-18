"""Host execution of exact binding/control C; no firmware-port or camera proof."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE = HERE.parent if (HERE.parent / 'control.c').exists() else ROOT / 'fpSup/lossless'

CASES = ['default_off', 'unready_on_restored', 'private_choice_only', 'recording_locked',
         'invalid_integer_restored', 'wrong_page_no_side_effects', 'unknown_variable_not_adopted',
         'register_failure_no_retry', 'postregister_lookup_failure', 'subscribe_failure_retains_ticket',
         'unsubscribe_is_not_quiescence', 'unsubscribe_failure_no_retry', 'publish_echo_reentry',
         'publish_failure_rolls_back', 'initial_publish_failure', 'no_live_session_reset',
         'fresh_producer_context', 'still_preserves_preference', 'read_failure', 'context_failure',
         'generation_exhaustion', 'registry_replaced', 'foreign_subscriber', 'readiness_never_invented',
         'notification_exclusion_before_cancel', 'failed_cancel_releases_exclusion',
         'close_menu_then_record', 'recovery_redraw_failure', 'reap_read_failure']


class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clang = shutil.which('clang')
        if not cls.clang:
            raise RuntimeError('clang required; no skipped execution')
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-binding-')
        cls.addClassCleanup(cls.tmp.cleanup)
        target = Path(cls.tmp.name) / 'binding.dylib'
        sources = [CORE/'control.c', CORE/'ui_control.c', HERE/'binding.c', HERE/'binding_fixture.c']
        subprocess.run([cls.clang, '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        '-I', str(CORE), *map(str,sources), '-o', str(target)],
                       check=True, capture_output=True, text=True)
        cls.lib = ctypes.CDLL(str(target))
        cls.lib.binding_case.argtypes = [ctypes.c_uint32]
        cls.lib.binding_case.restype = ctypes.c_int

    def test_arm_softfloat_compilation(self):
        target = Path(self.tmp.name) / 'binding.arm.o'
        subprocess.run([self.clang, '--target=armv7-none-eabi', '-mcpu=cortex-a9', '-marm',
                        '-mfloat-abi=soft', '-mfpu=none', '-std=c11', '-Os', '-ffreestanding',
                        '-fno-builtin', '-Wall', '-Wextra', '-Werror', '-I', str(CORE),
                        '-c', str(HERE/'binding.c'), '-o', str(target)],
                       check=True, capture_output=True, text=True)
        blob=target.read_bytes()
        self.assertEqual(blob[:4], b'\x7fELF')
        self.assertEqual(int.from_bytes(blob[18:20],'little'),40)


def make_case(index):
    def test(self):
        line = self.lib.binding_case(index)
        self.assertEqual(line, 0, 'failed C assertion line %d' % line)
    return test


for index, name in enumerate(CASES):
    setattr(BindingTests, 'test_' + name, make_case(index))

if __name__ == '__main__':
    unittest.main(verbosity=2)
