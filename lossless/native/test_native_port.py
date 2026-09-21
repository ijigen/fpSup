"""Execute the exact native_port.c binding-ops adapter on the host.

The coordinator, UI policy and control cores are the real sources. Only the
ARM32-only fp_nv_* call layer is substituted, with its checked semantics kept;
that layer is separately executed into original firmware instructions by
test_native_variable.py. Nothing here touches a camera, GUI or transport.
"""
import ctypes
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CORE = HERE.parent
CASES = [
    'default_off_registration', 'ready_ui_never_claimed', 'result_translation_table',
    'name_content_checked', 'register_only_creates_off', 'foreign_descriptor_not_adopted',
    'subscribe_failure_retains_context', 'callback_to_policy_restores_canonical',
    'echo_during_publish_suppressed', 'nested_callback_refused', 'close_without_exclusion_is_busy',
    'quiesce_absent_keeps_ticket', 'unsubscribe_requires_held_exclusion', 'full_retirement',
    'quiesce_provider_not_trusted', 'native_set_failure_sticky', 'facts_absent_blocks_rec',
    'presentation_unapplied_counted', 'foreign_descriptor_rejected_by_read_publish',
    'init_and_bind_validation', 'initial_publish_failure', 'late_event_after_close',
]
SOURCES = ['control.c', 'ui_control.c', 'binding/binding.c', 'native/native_port.c',
           'native/port_fixture.c']
# The adapter calls the native layer and the coordinator; it must pull in no
# libc, floating point or compiler runtime of its own.
ALLOWED_UNDEFINED = {'fp_nv_init', 'fp_nv_inspect', 'fp_nv_register_off', 'fp_nv_read',
                     'fp_nv_subscribe', 'fp_nv_set_canonical', 'fp_nv_unsubscribe_locked',
                     'fpl_binding_notify'}
RESULT = {}


RUNNER = """
extern unsigned port_case(unsigned);
extern int printf(const char *, ...);
int main(void) {
    unsigned n;
    int failures = 0;
    for (n = 0; n < %d; ++n) {
        unsigned line = port_case(n);
        printf("%%u %%u\\n", n, line);
        if (line) ++failures;
    }
    return failures != 0;
}
"""


def build(clang, out, extra, sources):
    subprocess.run([clang, '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wconversion',
                    '-I', str(CORE), '-I', str(CORE / 'binding'),
                    *extra, *sources, '-o', str(out)],
                   check=True, capture_output=True, text=True)
    return out


def sanitized_lines(clang, out):
    """Run every scenario again in one ASan/UBSan executable, not in-process."""
    runner = out.parent / 'port_main.c'
    runner.write_text(RUNNER % len(CASES))
    binary = build(clang, out, ['-O1', '-g', '-fsanitize=address,undefined,integer,local-bounds',
                                '-fno-sanitize-recover=all',
                                '-fno-sanitize=unsigned-integer-overflow'],
                   [str(CORE / s) for s in SOURCES] + [str(runner)])
    done = subprocess.run([str(binary)], capture_output=True, text=True)
    lines = {int(a): int(b) for a, b in
             (row.split() for row in done.stdout.splitlines() if row.strip())}
    if done.returncode and len(lines) == len(CASES) and not any(lines.values()):
        raise RuntimeError('sanitizer reported a fault:\n' + done.stderr)
    if len(lines) != len(CASES):
        raise RuntimeError('sanitized run stopped early:\n%s\n%s' % (done.stdout, done.stderr))
    return lines


class NativePortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clang = shutil.which('clang')
        if not cls.clang:
            raise RuntimeError('clang required; no skipped execution')
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-native-port-')
        cls.addClassCleanup(cls.tmp.cleanup)
        out = Path(cls.tmp.name)
        build(cls.clang, out / 'port.dylib', ['-O2', '-shared', '-fPIC'],
              [str(CORE / s) for s in SOURCES])
        cls.plain = ctypes.CDLL(str(out / 'port.dylib'))
        cls.plain.port_case.argtypes = [ctypes.c_uint32]
        cls.plain.port_case.restype = ctypes.c_int
        cls.checked = sanitized_lines(cls.clang, out / 'port-sanitized')

    def test_arm_thumb_softfloat_object(self):
        """The adapter compiles for the camera CPU with no FP/NEON dependency."""
        obj = Path(self.tmp.name) / 'native_port.arm.o'
        subprocess.run([self.clang, '--target=armv7-none-eabi', '-mcpu=cortex-a9', '-mthumb',
                        '-mfloat-abi=soft', '-mfpu=none', '-std=c11', '-Os', '-ffreestanding',
                        '-fno-builtin', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
                        '-Wall', '-Wextra', '-Werror', '-Wconversion', '-I', str(CORE),
                        '-I', str(CORE / 'binding'), '-c', str(CORE / 'native/native_port.c'),
                        '-o', str(obj)], check=True, capture_output=True, text=True)
        blob = obj.read_bytes()
        self.assertEqual(blob[:4], b'\x7fELF')
        self.assertEqual(int.from_bytes(blob[18:20], 'little'), 40)
        self.assertEqual(int.from_bytes(blob[36:40], 'little') & 0x400, 0, 'hard-float ABI')
        nm = shutil.which('llvm-nm') or shutil.which('nm')
        self.assertTrue(nm, 'nm required to check undefined symbols')
        undefined = {line.split()[-1].lstrip('_') for line in
                     subprocess.run([nm, '-u', str(obj)], check=True, capture_output=True,
                                    text=True).stdout.splitlines() if line.strip()}
        RESULT['undefined_symbols'] = sorted(undefined)
        self.assertEqual(undefined - ALLOWED_UNDEFINED, set())
        # A function-pointer table needs relocated .rodata, unlike the strictly
        # relocation-free native_variable.c text: installing this adapter
        # requires a real loader/link step, not a text-only copy.
        RESULT['requires_relocated_rodata'] = b'.rodata' in blob or b'.data.rel.ro' in blob


def make_case(index, name):
    def test(self):
        line = self.plain.port_case(index)
        self.assertEqual(line, 0, 'host: failed C assertion at port_fixture.c:%d' % line)
        line = self.checked[index]
        self.assertEqual(line, 0, 'sanitized: failed C assertion at port_fixture.c:%d' % line)
    test.__name__ = 'test_%02d_%s' % (index, name)
    return test


for index, name in enumerate(CASES):
    setattr(NativePortTests, 'test_%02d_%s' % (index, name), make_case(index, name))


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NativePortTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and not result.skipped
    print(json.dumps({
        'kind': 'host_executed_native_binding_ops_port',
        'passed': passed, 'tests_run': result.testsRun, 'skipped': len(result.skipped),
        'scenarios': len(CASES), 'each_scenario_runs': ['host -O2 in-process', 'asan+ubsan -O1 executable'],
        'camera_accessed': False, 'deployable': False,
        'native_call_layer': 'substituted on host; separately executed into original '
                             'instructions by test_native_variable.py',
        'rendering_proved': False, 'ready_ui_claimable': False,
        'exclusion_provider_required': True, 'quiescence_provider_required': True,
        'undefined_symbols': RESULT.get('undefined_symbols'),
        'requires_relocated_rodata': RESULT.get('requires_relocated_rodata'),
        'source_hashes': {s: hashlib.sha256((CORE / s).read_bytes()).hexdigest()
                          for s in SOURCES + ['native/native_port.h', 'binding/binding.h',
                                              'native/native_variable.h', 'ui_control.h',
                                              'control.h']},
        'test_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'remaining': ['native page/row installation and rendering', 'choice permission port',
                      'notification exclusion and source-event quiescence providers',
                      'persistent preference', 'REC/codec/writer/header/playback'],
    }, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
