"""Execute the exact no-menu control entry as ARM, never camera firmware.

Fresh producer facts below are explicit test fixtures, not hardware proofs. The
context mapping is read-only during execution, so the core cannot fabricate UI
readiness. The maintained ELF extractor rejects text relocations and undefined
symbols; no linker, installer, native capture adapter or USB access is provided.
The actual JIT workload runs in a child and must pass without skipped cases.
"""
import hashlib
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parents[1]
HELPER = HERE.parents[1] / 'research/ui/tools/arm_text/elf_text.py'
OK, INVALID, BUSY, UNSUPPORTED, NOT_READY, FAULT = range(6)
IDLE, RAW, LOSSLESS, STOPPED = range(4)
CODE, RAM, CONTEXT, STACK, RETURN = (
    0x30000000, 0x45000000, 0x45002000, 0x46010000, 0x47000000)
STATE = RAM + 0x100
CAPTURE, ALL, BLOCK_REC = 126, 127, 1 << 31
STATE_SIZE, CONTEXT_SIZE, CASES = 32, 40, 11


def compile_text(directory, *, mutation=False):
    compiler = shutil.which('clang')
    if compiler is None:
        raise RuntimeError('clang required: ARM compilation was not performed')
    spec = importlib.util.spec_from_file_location('direct_control_checked_elf', HELPER)
    elf = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = elf
    spec.loader.exec_module(elf)
    source = (HERE / 'control.c').read_text()
    if mutation:
        original = ('if ((c->ready & FPL_READY_CAPTURE) != FPL_READY_CAPTURE) '
                    'return FPL_NOT_READY;')
        if source.count(original) != 1:
            raise AssertionError('direct writer-proof mutation requires one exact guard')
        source = source.replace(
            original,
            'if ((c->ready & (FPL_READY_CAPTURE & ~FPL_READY_WRITER)) != '
            '(FPL_READY_CAPTURE & ~FPL_READY_WRITER)) return FPL_NOT_READY;')
    source += '''
#include <stddef.h>
_Static_assert(sizeof(uintptr_t) == 4, "ARM32 pointers");
_Static_assert(sizeof(struct fpl_state) == 32, "control state ABI");
_Static_assert(offsetof(struct fpl_state, requested) == 8, "requested ABI");
_Static_assert(offsetof(struct fpl_state, clip) == 12, "clip ABI");
_Static_assert(offsetof(struct fpl_state, fault) == 20, "fault ABI");
_Static_assert(sizeof(struct fpl_context) == 40, "context ABI");
_Static_assert(offsetof(struct fpl_context, ready) == 36, "readiness ABI");
_Static_assert(FPL_READY_CAPTURE == 126, "direct omits UI only");
'''
    obj = Path(directory) / ('missing-writer-proof.o' if mutation else 'control.o')
    # -O2 retains calls from the menu APIs to fpl_can_enable, requiring text
    # relocations which this strict extractor correctly rejects. At -O3 clang
    # inlines those calls in the unchanged complete C translation unit. Keep
    # the extractor as the authority: compiler changes must fail, not fall back
    # to stripping relocations or dropping the existing menu APIs.
    subprocess.run(
        [compiler, '--target=armv7-none-eabi', '-mcpu=cortex-a9', '-marm',
         '-mfloat-abi=soft', '-mfpu=none', '-std=c11', '-O3', '-ffreestanding',
         '-fno-builtin', '-fno-addrsig', '-fno-unwind-tables',
         '-fno-asynchronous-unwind-tables', '-Wall', '-Wextra', '-Werror',
         '-I', str(HERE), '-x', 'c', '-c', '-', '-o', str(obj)],
        input=source, text=True, capture_output=True, check=True, timeout=30)
    return elf.load_text(obj)  # Never strip/apply a relocation to make this pass.


class ArmControl:
    def __init__(self, text):
        from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
        from unicorn import UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC, arm_const
        self.text, self.reg = text, arm_const
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        extent = (len(text.code) + 4095) & ~4095
        self.uc.mem_map(CODE, extent, UC_PROT_READ | UC_PROT_WRITE)
        self.uc.mem_write(CODE, text.code)
        self.uc.mem_protect(CODE, extent, UC_PROT_READ | UC_PROT_EXEC)
        self.uc.mem_map(RAM, 0x1000, UC_PROT_READ | UC_PROT_WRITE)
        self.uc.mem_map(CONTEXT, 0x1000, UC_PROT_READ)
        self.uc.mem_map(STACK - 0x10000, 0x10000, UC_PROT_READ | UC_PROT_WRITE)
        self.uc.mem_map(RETURN, 0x1000, UC_PROT_READ | UC_PROT_EXEC)
        self.uc.hook_add(UC_HOOK_CODE, self.instruction)
        self.calls = 0
        self.context()
        self.boot()

    def r(self, name):
        return self.uc.reg_read(getattr(self.reg, 'UC_ARM_REG_' + name.upper()))

    def setr(self, name, value):
        self.uc.reg_write(getattr(self.reg, 'UC_ARM_REG_' + name.upper()), value)

    def write(self, address, *words):
        self.uc.mem_write(address, struct.pack('<' + 'I' * len(words), *words))

    def words(self, address, count):
        return struct.unpack('<' + 'I' * count, self.uc.mem_read(address, count * 4))

    def state(self):
        return self.words(STATE, 8)

    def context(self, ready=CAPTURE, **changes):
        # Host initialization is deliberately explicit. No firmware/native
        # producer path is stubbed to pretend these synthetic facts were read.
        fields = dict(firmware=502, cine=1, compression=1, bits=12,
                      width=1936, height=1090, fps_num=24000, fps_den=1001,
                      media=1, ready=ready)
        unknown = set(changes) - set(fields)
        if unknown:
            raise AssertionError('unknown context fields: ' + repr(unknown))
        fields.update(changes)
        self.write(CONTEXT, *fields.values())  # Host writes bypass guest protection.
        return self.words(CONTEXT, 10)

    def boot(self):
        self.call('boot', STATE)

    def instruction(self, _uc, pc, size, _data):
        if CODE <= pc and pc + size <= CODE + len(self.text.code):
            return
        if pc == RETURN:
            self.returned = True
            self.uc.emu_stop()
            return
        raise AssertionError(f'unapproved external PC: {pc:#010x}')

    def call(self, name, *arguments):
        saved = {f'r{i}': 0xD1EC0000 + i for i in range(4, 12)}
        for register, value in saved.items():
            self.setr(register, value)
        sp = STACK - 0x100
        self.setr('sp', sp)
        self.setr('lr', RETURN)
        for n in range(4):
            self.setr(f'r{n}', arguments[n] if n < len(arguments) else 0xBAD00000 + n)
        if len(arguments) > 4:
            raise AssertionError('control ABI requires at most four register arguments')
        context_before = bytes(self.uc.mem_read(CONTEXT, 0x1000))
        self.returned = False
        entry = CODE + self.text.functions['fpl_' + name]
        self.uc.emu_start(entry, 0, timeout=250000, count=20000)
        if not self.returned:
            raise AssertionError('bounded ARM control call did not return')
        if self.r('sp') != sp or any(self.r(k) != v for k, v in saved.items()):
            raise AssertionError('ARM control clobbered SP or r4-r11')
        if bytes(self.uc.mem_read(CONTEXT, 0x1000)) != context_before:
            raise AssertionError('control changed supplied producer facts')
        self.calls += 1
        return self.r('r0')


def worker_suite(text, mutant):
    class ExecutedDirectControlTests(unittest.TestCase):
        def unchanged_rejection(self, h, result, function='begin_direct', *args):
            before = h.state()
            context = h.words(CONTEXT, 10)
            self.assertEqual(h.call(function, STATE, *(args or (CONTEXT,))), result)
            self.assertEqual(h.state(), before)
            self.assertEqual(h.words(CONTEXT, 10), context)

        def test_all_128_direct_readiness_combinations(self):
            h = ArmControl(text)
            for ready in range(128):
                with self.subTest(ready=ready):
                    h.boot()
                    h.context(ready)
                    if (ready & CAPTURE) == CAPTURE:
                        self.assertEqual(h.call('begin_direct', STATE, CONTEXT), OK)
                        self.assertEqual(h.state(), (0x46504C53, 1, 1, LOSSLESS, 0, 0, 0, 0))
                    else:
                        self.unchanged_rejection(h, NOT_READY)
                    self.assertEqual(h.words(CONTEXT + 36, 1), (ready,))

        def test_menu_still_requires_ui_for_all_128_combinations(self):
            h = ArmControl(text)
            for ready in range(128):
                with self.subTest(ready=ready):
                    h.boot()
                    h.context(ready)
                    expected = OK if ready == ALL else NOT_READY
                    self.assertEqual(h.call('can_enable', CONTEXT), expected)
                    self.assertEqual(h.call('set', STATE, 1, CONTEXT), expected)
                    self.assertEqual(h.state()[2], int(ready == ALL))
                    # Establish ON legitimately with full readiness, then
                    # recheck fresh downgraded facts at the normal REC entry.
                    h.context(ALL)
                    self.assertEqual(h.call('set', STATE, 1, CONTEXT), OK)
                    h.context(ready)
                    before = h.state()
                    self.assertEqual(h.call('begin', STATE, CONTEXT), expected)
                    if expected != OK:
                        self.assertEqual(h.state(), before)

        def test_read_only_context_has_no_ui_forgery(self):
            from unicorn import UC_PROT_READ
            h = ArmControl(text)
            self.assertIn((CONTEXT, CONTEXT + 0xFFF, UC_PROT_READ), list(h.uc.mem_regions()))
            facts = h.context(CAPTURE)
            self.assertEqual(h.call('begin_direct', STATE, CONTEXT), OK)
            self.assertEqual(h.words(CONTEXT, 10), facts)
            self.assertEqual(h.words(CONTEXT + 36, 1), (CAPTURE,))
            self.assertEqual(h.call('can_enable', CONTEXT), NOT_READY)

        def test_raw_lossless_and_stopped_clips_reject_reentry(self):
            for clip in (RAW, LOSSLESS, STOPPED):
                with self.subTest(clip=clip):
                    h = ArmControl(text)
                    if clip == RAW:
                        self.assertEqual(h.call('begin', STATE, CONTEXT), OK)
                    else:
                        self.assertEqual(h.call('begin_direct', STATE, CONTEXT), OK)
                        if clip == STOPPED:
                            self.assertEqual(h.call('fail', STATE, 37), FAULT)
                    self.assertEqual(h.state()[3], clip)
                    self.unchanged_rejection(h, BUSY)
                    self.unchanged_rejection(h, BUSY, 'set', 0, CONTEXT)

        def test_stop_fault_cleanup_keeps_fault_sticky(self):
            h = ArmControl(text)
            self.assertEqual(h.call('begin_direct', STATE, CONTEXT), OK)
            self.assertEqual(h.call('frame_done', STATE), OK)
            self.assertEqual(h.call('fail', STATE, 37), FAULT)
            self.assertEqual(h.call('fail', STATE, 99), FAULT)
            self.assertEqual(h.state()[3:6], (STOPPED, 1, 37))
            self.unchanged_rejection(h, FAULT, 'frame_done')
            for cleanup in (0, 2, 0xFFFFFFFF):
                self.unchanged_rejection(h, BUSY, 'end', cleanup)
            self.assertEqual(h.call('end', STATE, 1), OK)
            self.assertEqual(h.state()[3:6], (IDLE, 0, 37))
            self.unchanged_rejection(h, FAULT)
            self.assertEqual(h.call('set', STATE, 0, 0), OK)
            self.assertEqual(h.call('begin', STATE, CONTEXT), OK)
            self.assertEqual(h.state()[3], RAW)

        def test_continuous_take_cleanup_and_saturating_counter(self):
            h = ArmControl(text)
            self.assertEqual(h.call('begin_direct', STATE, CONTEXT), OK)
            for _ in range(1200):
                self.assertEqual(h.call('frame_done', STATE), OK)
            self.assertEqual(h.state()[3:5], (LOSSLESS, 1200))
            self.unchanged_rejection(h, BUSY, 'end', 0)
            self.assertEqual(h.call('end', STATE, 1), OK)
            self.assertEqual(h.call('begin_direct', STATE, CONTEXT), OK)
            self.assertEqual(h.state()[4], 0)
            h.write(STATE + 16, 0xFFFFFFFE)  # Explicit diagnostic counter fixture.
            for _ in range(3):
                self.assertEqual(h.call('frame_done', STATE), OK)
            self.assertEqual(h.state()[3:5], (LOSSLESS, 0xFFFFFFFF))

        def test_block_rec_refuses_direct_and_normal_raw(self):
            h = ArmControl(text)
            for ready in (BLOCK_REC, BLOCK_REC | CAPTURE, BLOCK_REC | ALL):
                h.context(ready)
                self.unchanged_rejection(h, FAULT)
                self.unchanged_rejection(h, FAULT, 'begin')

        def test_format_guards_and_candidate_formats(self):
            h = ArmControl(text)
            rejected = (dict(firmware=501), dict(cine=0), dict(compression=0),
                        dict(bits=8), dict(bits=14), dict(width=0), dict(width=1937),
                        dict(width=0x4008), dict(height=0), dict(height=1091),
                        dict(height=0x4002), dict(width=0x4000, height=0x4000),
                        dict(fps_num=0), dict(fps_den=0), dict(media=0))
            for changes in rejected:
                with self.subTest(changes=changes):
                    h.context(CAPTURE, **changes)
                    self.unchanged_rejection(h, UNSUPPORTED)
            for width, height in ((1280, 720), (1936, 1090), (3840, 2160), (6000, 4000)):
                for bits in (10, 12):
                    with self.subTest(width=width, height=height, bits=bits):
                        h.context(CAPTURE, width=width, height=height, bits=bits)
                        self.assertEqual(h.call('begin_direct', STATE, CONTEXT), OK)
                        self.assertEqual(h.call('end', STATE, 1), OK)

        def test_invalid_state_and_null_context_do_not_mutate(self):
            h = ArmControl(text)
            self.assertEqual(h.call('begin_direct', 0, CONTEXT), INVALID)
            self.unchanged_rejection(h, INVALID, 'begin_direct', 0)
            for field, value in ((0, 0), (1, 2), (2, 2), (3, 4), (6, 1), (7, 1)):
                with self.subTest(field=field):
                    h.boot()
                    h.write(STATE + field * 4, value)
                    self.unchanged_rejection(h, INVALID)

        def test_missing_writer_mutation_enters_lossless_unsafely(self):
            good, bad = ArmControl(text), ArmControl(mutant)
            missing_writer = CAPTURE & ~(1 << 2)
            good.context(missing_writer)
            bad.context(missing_writer)
            self.unchanged_rejection(good, NOT_READY)
            # Establish the exact unsafe effect rather than counting an
            # arbitrary compile/JIT/assertion failure as a caught mutation.
            result = bad.call('begin_direct', STATE, CONTEXT)
            self.assertEqual((result, bad.state()[2:4]), (OK, (1, LOSSLESS)))
            self.assertEqual(bad.words(CONTEXT + 36, 1), (missing_writer,))
            with self.assertRaises(AssertionError):
                self.assertEqual(result, NOT_READY, 'native writer proof is mandatory')

        def test_external_pc_whitelist_is_enforced(self):
            h = ArmControl(text)
            with self.assertRaisesRegex(AssertionError, 'unapproved external PC'):
                h.uc.emu_start(RETURN + 0x100, 0, timeout=100000, count=4)

    return unittest.defaultTestLoader.loadTestsFromTestCase(ExecutedDirectControlTests)


class CompiledArmDirectControlTests(unittest.TestCase):
    def test_actual_arm_direct_control_in_isolated_worker(self):
        optimized = ['-' + 'O' * sys.flags.optimize] if sys.flags.optimize else []
        child = subprocess.run(
            [sys.executable, '-B', *optimized, str(Path(__file__).resolve()), '--worker'],
            capture_output=True, text=True, timeout=90)
        detail = child.stdout + child.stderr
        self.assertEqual(child.returncode, 0,
                         'ARM worker failed (negative exit means host signal/JIT restriction); '
                         'ARM execution is unverified.\n' + detail)
        self.assertIn(f'ARM DIRECT CONTROL VERIFIED: {CASES} tests, 0 skipped', child.stdout)
        print(child.stdout.strip())


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        with tempfile.TemporaryDirectory(prefix='fpl-direct-control-arm-') as directory:
            text = compile_text(directory)
            mutant = compile_text(directory, mutation=True)
            result = unittest.TextTestRunner(verbosity=2).run(worker_suite(text, mutant))
        if result.wasSuccessful() and not result.skipped and result.testsRun == CASES:
            print(f'ARM DIRECT CONTROL VERIFIED: {result.testsRun} tests, 0 skipped; '
                  f'text={len(text.code)} bytes; optimization=-O3; '
                  f'r4-r11/SP checked; context read-only; '
                  f'text_sha256={hashlib.sha256(text.code).hexdigest()}; '
                  f'control_sha256={hashlib.sha256((HERE / "control.c").read_bytes()).hexdigest()}')
            raise SystemExit(0)
        raise SystemExit(1)
    unittest.main()
