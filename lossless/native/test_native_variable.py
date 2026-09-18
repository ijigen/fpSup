"""Compile the actual ARM C wrapper, then execute it and pinned native code.

Not a camera test: original Lua/allocator/locks/component callbacks are outside
the inherited synthetic-service boundary. No device or transport is imported.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
IMAGE = TEXT = BINDING = None
COVERAGE = set()
CALLS = []
INVALID, COLLISION, STALE, TYPE, NATIVE, FAULT = range(0x100, 0x106)


def probe_class():
    from unicorn import UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC
    from unicorn.arm_const import (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
                                  UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
                                  UC_ARM_REG_R10, UC_ARM_REG_R11)
    saved = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
             UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)

    class PortProbe(BINDING.BindingProbe):
        CODE = 0x30000000  # emulator-only RX mapping; no camera memory reservation
        STATE = BINDING.BindingProbe.RAM + 0x3B00
        OUTPUT = BINDING.BindingProbe.RAM + 0x3C00

        def __init__(self):
            super().__init__(IMAGE)
            size = (len(TEXT.code) + 4095) & ~4095
            self.uc.mem_map(self.CODE, size, UC_PROT_READ | UC_PROT_WRITE)
            self.uc.mem_write(self.CODE, TEXT.code)
            self.uc.mem_protect(self.CODE, size, UC_PROT_READ | UC_PROT_EXEC)
            self.write(self.NAME, b"MV_fpLossless\0")
            self.native_calls = []

        def _instruction(self, uc, address, size, data):
            if self.CODE <= address and address + size <= self.CODE + len(TEXT.code):
                self.instructions += 1
                return
            if address in (BINDING.registry.REGISTER, BINDING.registry.LOOKUP_APP,
                           BINDING.SUBSCRIBE, BINDING.UNSUBSCRIBE, BINDING.SET_SILENT):
                self.native_calls.append({"entry": hex(address),
                                          "args": [uc.reg_read(r) for r in BINDING.registry.REGS]})
            super()._instruction(uc, address, size, data)

        def call(self, name, *args):
            expected = [0xA0001000 + n for n in range(len(saved))]
            for reg, value in zip(saved, expected):
                self.uc.reg_write(reg, value)
            result = self.run(self.CODE + (TEXT.functions["fp_nv_" + name] & ~1), *args)
            if [self.uc.reg_read(reg) for reg in saved] != expected:
                raise BINDING.registry.ProbeError("compiled/native call clobbered callee-saved registers")
            return result

        def initialize(self):
            return self.call("init", self.STATE, self.APP, self.NAME)

        def own(self):
            result = self.call("register_off", self.STATE)
            if result:
                raise AssertionError("registration failed: %d" % result)
            return self.words(self.STATE + 12)[0]

        def subscribe_own(self):
            return self.call("subscribe", self.STATE, self.PRIVATE_CALLBACK | 1, self.CONTEXT)

    return PortProbe


class NativePortTests(unittest.TestCase):
    def setUp(self):
        self.p = probe_class()()
        self.assertEqual(self.p.initialize(), 0)

    def tearDown(self):
        COVERAGE.update(self.p.visited)
        CALLS.extend(self.p.native_calls)
        self.p.close()

    def test_01_exact_private_name_and_fresh_state(self):
        self.assertEqual(self.p.initialize(), INVALID)
        self.p.write(self.p.NAME, b"MV_AudioRecord\0")
        self.assertEqual(self.p.call("init", self.p.STATE + 64, self.p.APP, self.p.NAME), INVALID)
        self.assertEqual(self.p.call("init", 0, self.p.APP, self.p.NAME), INVALID)
        self.assertEqual(self.p.native_calls, [])

    def test_02_absent_lookup_is_not_a_descriptor(self):
        self.assertEqual(self.p.call("inspect", self.p.STATE, self.p.OUTPUT), 0)
        self.assertEqual(self.p.words(self.p.OUTPUT, 4), (0, 0, 0, 0))
        self.assertEqual(self.p.call("read", self.p.STATE, self.p.OUTPUT), STALE)

    def test_03_register_defaults_off_and_borrows_stable_name(self):
        d = self.p.own()
        self.assertEqual(self.p.words(d, 4), (0, self.p.NAME, 0, 0))
        self.assertEqual(self.p.call("inspect", self.p.STATE, self.p.OUTPUT), 0)
        self.assertEqual(self.p.words(self.p.OUTPUT, 4), (d, 0, 0, 0))
        self.assertEqual(self.p.call("read", self.p.STATE, self.p.OUTPUT), 0)
        self.assertEqual(self.p.words(self.p.OUTPUT)[0], 0)

    def test_04_no_duplicate_registration(self):
        self.p.own(); before = self.p.allocation_calls
        self.assertEqual(self.p.call("register_off", self.p.STATE), INVALID)
        self.assertEqual(self.p.allocation_calls, before)

    def test_05_collision_is_never_adopted(self):
        d = self.p.register_private(1); before = self.p.allocation_calls
        self.assertEqual(self.p.call("register_off", self.p.STATE), COLLISION)
        self.assertEqual(self.p.words(self.p.STATE + 12)[0], 0)
        self.assertEqual(self.p.words(d + 8)[0], 1)
        self.assertEqual(self.p.allocation_calls, before)
        self.assertEqual(self.p.call("register_off", self.p.STATE), FAULT)

    def test_06_registration_error_is_sticky(self):
        self.p.fail_allocation = {self.p.allocation_calls + 1}
        self.assertEqual(self.p.call("register_off", self.p.STATE), NATIVE)
        self.assertEqual(self.p.words(self.p.STATE + 32)[0], 1)
        before = self.p.allocation_calls
        self.assertEqual(self.p.call("register_off", self.p.STATE), FAULT)
        self.assertEqual(self.p.allocation_calls, before)

    def test_07_lua_failure_is_not_rolled_back_or_retried(self):
        self.p.lua_result = 3
        self.assertEqual(self.p.call("register_off", self.p.STATE), NATIVE)
        self.assertEqual(self.p.words(self.p.STATE + 32)[0], 3)
        before = self.p.snapshot()
        self.p.lua_result = 0
        self.assertEqual(self.p.call("register_off", self.p.STATE), FAULT)
        self.assertEqual(self.p.snapshot(), before)

    def test_08_nonboolean_value_rejected_before_native_assignment(self):
        d = self.p.own(); self.p.native_calls.clear()
        for value in (2, 7, 0xFFFFFFFF):
            self.assertEqual(self.p.call("set_canonical", self.p.STATE, value), INVALID)
        self.assertEqual(self.p.native_calls, [])
        self.assertEqual(self.p.words(d + 8)[0], 0)

    def test_09_canonical_set_executes_original_silent_array_setter(self):
        d = self.p.own(); self.assertEqual(self.p.subscribe_own(), 0)
        self.p.events.clear(); self.p.visited.clear()
        self.assertEqual(self.p.call("set_canonical", self.p.STATE, 1), 0)
        self.assertEqual(self.p.words(d + 8)[0], 1)
        self.assertEqual(self.p.callback_events(), [])
        self.assertIn("dispatch_bound_components", self.p.visited)
        self.assertIn("set_named_no_callback_wrapper", self.p.visited)
        self.assertNotIn("set_named_notify_wrapper", self.p.visited)
        self.assertEqual(self.p.call("set_canonical", self.p.STATE, 0), 0)

    def test_10_subscription_copies_pair_and_original_user_write_notifies(self):
        d = self.p.own(); self.assertEqual(self.p.subscribe_own(), 0)
        pair = self.p.words(self.p.STATE + 24)[0]
        self.assertEqual(self.p.words(d + 24)[0], pair)
        self.assertEqual(self.p.words(pair, 2), (self.p.PRIVATE_CALLBACK | 1, self.p.CONTEXT))
        self.assertEqual(self.p.set_integer(1), 0)
        self.assertEqual(self.p.callback_events()[-1]["value"], 1)

    def test_11_subscription_cannot_replace_foreign_owner(self):
        d = self.p.own(); self.assertEqual(self.p.subscribe(), 0)
        pair = self.p.words(d + 24)[0]
        self.assertEqual(self.p.subscribe_own(), COLLISION)
        self.assertEqual(self.p.words(d + 24)[0], pair)

    def test_12_duplicate_subscribe_does_not_mutate(self):
        self.p.own(); self.assertEqual(self.p.subscribe_own(), 0)
        before = self.p.allocation_calls
        self.assertEqual(self.p.subscribe_own(), INVALID)
        self.assertEqual(self.p.allocation_calls, before)

    def test_13_unsubscribe_checks_pair_pointer_and_context(self):
        d = self.p.own(); self.assertEqual(self.p.subscribe_own(), 0)
        pair = self.p.words(d + 24)[0]
        self.p.write_words(pair + 4, self.p.CONTEXT + 4)
        self.assertEqual(self.p.call("unsubscribe_locked", self.p.STATE), COLLISION)
        self.assertEqual(self.p.words(d + 24)[0], pair)
        self.assertIn(pair, self.p.blocks)

    def test_14_serial_unsubscribe_does_not_free_descriptor_name_or_context(self):
        d = self.p.own(); self.assertEqual(self.p.subscribe_own(), 0)
        pair = self.p.words(d + 24)[0]
        self.p.write_words(self.p.CONTEXT, 0x12345678)
        self.assertEqual(self.p.call("unsubscribe_locked", self.p.STATE), 0)
        self.assertNotIn(pair, self.p.blocks)
        self.assertIn(d, self.p.blocks)
        self.assertEqual(self.p.string(self.p.NAME), b"MV_fpLossless")
        self.assertEqual(self.p.words(self.p.CONTEXT)[0], 0x12345678)
        self.assertEqual(self.p.words(self.p.STATE + 16, 3), (0, 0, 0))

    def test_15_failed_subscribe_retains_context_until_explicit_cleanup(self):
        self.p.own(); self.p.fail_allocation = {self.p.allocation_calls + 1}
        self.assertEqual(self.p.subscribe_own(), NATIVE)
        self.assertEqual(self.p.words(self.p.STATE + 20)[0], self.p.CONTEXT)
        self.assertEqual(self.p.call("unsubscribe_locked", self.p.STATE), 0)
        self.assertEqual(self.p.words(self.p.STATE + 16, 3), (0, 0, 0))
        self.assertNotEqual(self.p.words(self.p.STATE + 28)[0], 0)

    def test_16_native_set_failure_sticky_but_serial_cancel_still_possible(self):
        d = self.p.own(); self.assertEqual(self.p.subscribe_own(), 0)
        self.p.fail_allocation = {self.p.allocation_calls + 1}
        self.assertEqual(self.p.call("set_canonical", self.p.STATE, 1), NATIVE)
        self.assertEqual(self.p.words(d + 8)[0], 0)
        self.assertEqual(self.p.call("set_canonical", self.p.STATE, 0), FAULT)
        self.assertEqual(self.p.call("unsubscribe_locked", self.p.STATE), 0)

    def test_17_read_checks_type_before_acceptance(self):
        d = self.p.own(); self.p.write_words(d, 1)
        self.assertEqual(self.p.call("read", self.p.STATE, self.p.OUTPUT), TYPE)
        self.assertEqual(self.p.words(self.p.OUTPUT)[0], 0)

    def test_18_descriptor_identity_and_borrowed_name_checked(self):
        d = self.p.own(); self.p.write(self.p.NAME + 0x80, b"MV_fpLossless\0")
        self.p.write_words(d + 4, self.p.NAME + 0x80)
        self.assertEqual(self.p.call("set_canonical", self.p.STATE, 1), STALE)
        self.assertEqual(self.p.words(d + 8)[0], 0)

    def test_19_inactive_registry_status_is_not_success(self):
        self.p.write_words(self.p.REGISTRY + 0x48, 0)
        self.assertEqual(self.p.call("inspect", self.p.STATE, self.p.OUTPUT), NATIVE)
        self.assertEqual(self.p.words(self.p.STATE + 32)[0], 2)
        self.assertEqual(self.p.words(self.p.OUTPUT, 4), (0, 0, 0, 0))

    def test_20_null_outputs_no_native_call(self):
        self.assertEqual(self.p.call("inspect", self.p.STATE, 0), INVALID)
        self.assertEqual(self.p.call("read", self.p.STATE, 0), INVALID)
        self.assertEqual(self.p.native_calls, [])

    def test_21_changed_subscriber_rejected_before_write(self):
        d = self.p.own(); self.assertEqual(self.p.subscribe_own(), 0)
        pair = self.p.words(d + 24)[0]
        self.p.write_words(pair + 4, self.p.CONTEXT + 4)
        self.assertEqual(self.p.call("set_canonical", self.p.STATE, 1), COLLISION)
        self.assertEqual(self.p.words(d + 8)[0], 0)

    def test_22_removed_subscription_rejected_on_read(self):
        d = self.p.own(); self.assertEqual(self.p.subscribe_own(), 0)
        self.assertEqual(self.p.unsubscribe(), 0)
        self.assertEqual(self.p.call("read", self.p.STATE, self.p.OUTPUT), COLLISION)
        self.assertEqual(self.p.words(self.p.OUTPUT)[0], 0)
        self.assertEqual(self.p.words(d + 8)[0], 0)

    def test_23_unowned_subscription_rejected_before_write(self):
        d = self.p.own(); self.assertEqual(self.p.subscribe(), 0)
        self.assertEqual(self.p.call("set_canonical", self.p.STATE, 1), COLLISION)
        self.assertEqual(self.p.words(d + 8)[0], 0)


def main():
    global IMAGE, TEXT, BINDING
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seg0", required=True, type=Path)
    parser.add_argument("--shared-probe", required=True, type=Path,
                        help="research/ui/tools/native_variable_probe/binding_probe.py")
    parser.add_argument("--elf-helper", required=True, type=Path,
                        help="research/ui/tools/arm_text/elf_text.py")
    args = parser.parse_args()
    elf_spec = importlib.util.spec_from_file_location("checked_arm_text", args.elf_helper)
    elf = importlib.util.module_from_spec(elf_spec)
    sys.modules[elf_spec.name] = elf
    elf_spec.loader.exec_module(elf)
    spec = importlib.util.spec_from_file_location("shared_native_binding", args.shared_probe)
    BINDING = importlib.util.module_from_spec(spec); spec.loader.exec_module(BINDING)
    IMAGE = BINDING.registry.load_firmware(args.seg0)
    clang = shutil.which("clang")
    if not clang:
        raise RuntimeError("clang required; no skipped compilation")
    with tempfile.TemporaryDirectory(prefix="fpl-native-port-") as temp:
        obj = Path(temp) / "native_variable.o"
        subprocess.run([clang, "--target=armv7-none-eabi", "-mcpu=cortex-a9", "-mthumb",
                        "-mfloat-abi=soft", "-mfpu=none", "-std=c11", "-O2", "-ffreestanding",
                        "-fno-builtin", "-fno-unwind-tables", "-fno-asynchronous-unwind-tables",
                        "-Wall", "-Wextra", "-Werror", "-c", str(HERE / "native_variable.c"),
                        "-o", str(obj)], check=True, capture_output=True, text=True)
        TEXT = elf.load_text(obj)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(NativePortTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and not result.skipped
    print(json.dumps({"kind": "compiled_arm_c_to_original_native_variable_calls", "passed": passed,
                      "tests_run": result.testsRun, "skipped": len(result.skipped),
                      "camera_accessed": False, "deployable": False, "native_port_complete": False,
                      "seg0_sha256": BINDING.registry.SEG0_SHA256,
                      "text_bytes": len(TEXT.code), "text_sha256": hashlib.sha256(TEXT.code).hexdigest(),
                      "function_offsets": TEXT.functions, "covered_native_intervals": sorted(COVERAGE),
                      "native_entry_calls": CALLS,
                      "source_hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                        (HERE / "native_variable.c", HERE / "native_variable.h",
                                         HERE / "test_native_variable.py", args.elf_helper.resolve(),
                                         args.shared_probe.resolve(), Path(BINDING.registry.__file__))},
                      "bounds": {"instructions_per_call": 20000, "timeout_us": 250000,
                                 "callee_saved_r4_r11_checked": True, "sp_restoration_checked": True},
                      "substitutes": ["Lua registration", "heap", "ASCII strcmp", "lock/unlock",
                                      "private/global callback services", "empty component vectors"],
                      "exclusion": "Only serial emulator tests; caller must implement actual notification exclusion",
                      "remaining": ["native page installation", "actual callback to policy glue", "rendering",
                                    "owner executor and quiescence", "recorder/backend integration"]}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
