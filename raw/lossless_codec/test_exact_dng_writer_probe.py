#!/usr/bin/env python3

import contextlib
import io
import unittest

import exact_dng_writer_probe as probe


class FakeShell:
    def __init__(self, *, drop_arms=0, fire_immediately=False, site=None):
        self.site = probe.HOOK_ORIG if site is None else site
        self.state = [0] * probe.STATE_WORDS
        self.drop_arms = drop_arms
        self.fire_immediately = fire_immediately
        self.arm_writes = 0

    def read_word(self, address):
        if address != probe.HOOK_SITE:
            raise AssertionError(f"unexpected read 0x{address:08X}")
        return self.site

    def read_words(self, address, count):
        if address == probe.STATE and count == probe.STATE_WORDS:
            return list(self.state)
        if address == probe.HOOK_SITE and count == 1:
            return [self.site]
        raise AssertionError(f"unexpected read 0x{address:08X}, {count}")

    def set_word(self, address, value):
        if address != probe.HOOK_SITE:
            raise AssertionError(f"unexpected write 0x{address:08X}")
        if value == probe.HOOK_ARMED:
            self.arm_writes += 1
            if self.drop_arms:
                self.drop_arms -= 1
                return
            if self.fire_immediately:
                self.state[probe.S_COUNT] = 1
                self.state[probe.S_DONE] = probe.DONE_MAGIC
                self.state[probe.S_RESTORED] = probe.HOOK_ORIG
                self.site = probe.HOOK_ORIG
                return
        self.site = value

    def write_words_verified(self, address, values, attempts=8):
        if address != probe.HOOK_SITE or values != [probe.HOOK_ORIG]:
            raise AssertionError("unexpected verified write")
        self.site = probe.HOOK_ORIG

    def write_word_verified(self, address, value, attempts=8):
        self.write_words_verified(address, [value], attempts)


class FakeInstallShell(FakeShell):
    def __init__(self, *, context=None, **kwargs):
        super().__init__(**kwargs)
        self.context = list(context or probe.EXPECTED_CONTEXT)
        self.writes = []

    def read_words(self, address, count):
        if address == probe.CONTEXT_ADDRESS and count == len(probe.EXPECTED_CONTEXT):
            words = list(self.context)
            words[probe.HOOK_CONTEXT_INDEX] = self.site
            return words
        return super().read_words(address, count)

    def set_word(self, address, value):
        self.writes.append(("set", address, (value,)))
        super().set_word(address, value)

    def write_words_verified(self, address, values, attempts=8):
        values = tuple(values)
        self.writes.append(("verified", address, values))
        if address == probe.CODE:
            return
        if address == probe.STATE and len(values) == probe.STATE_WORDS:
            self.state = list(values)
            return
        if address == probe.HOOK_SITE and values == (probe.HOOK_ORIG,):
            self.site = probe.HOOK_ORIG
            return
        raise AssertionError(f"unexpected verified write 0x{address:08X}")


class ProbeTests(unittest.TestCase):
    def test_default_checkout_contains_the_shared_assembler(self):
        self.assertTrue(
            (probe.DEFAULT_FPSUP / "fp_usb_shell" / "armasm.py").is_file()
        )

    def test_assembled_tail_call_preserves_registers(self):
        code = probe.build_probe(probe.DEFAULT_FPSUP)
        words = probe.words_from(code)
        self.assertEqual(len(code), 124)
        self.assertEqual(words[0], 0xE92D500F)  # push r0-r3,r12,lr
        self.assertEqual(words[-2], 0xE51FF004)  # ldr pc, [pc, #-4]
        self.assertEqual(words[-1], probe.REAL_WRITE)

    def test_branch_encoding(self):
        self.assertEqual(probe.HOOK_SITE, 0xC0722AFC)
        self.assertEqual(probe.HOOK_ORIG, 0xEBFDE061)
        self.assertEqual(probe.EXPECTED_LR, 0xC0722B00)
        self.assertEqual(probe.HOOK_ARMED, 0xEB00333F)
        self.assertEqual(probe.arm_bl(probe.HOOK_SITE, probe.REAL_WRITE), probe.HOOK_ORIG)

    def test_verified_live_call_context(self):
        self.assertEqual(probe.CONTEXT_ADDRESS, 0xC0722AF0)
        self.assertEqual(
            probe.EXPECTED_CONTEXT,
            (
                0xE1A0100D,
                0xE1A0000A,
                0xE3A02002,
                0xEBFDE061,
                0xE28DD008,
                0xE8BD84F0,
            ),
        )

    def test_context_guard_accepts_only_hook_word_variation(self):
        class ContextShell:
            def __init__(self, words):
                self.words = words

            def read_words(self, address, count):
                self.assert_request = (address, count)
                return list(self.words)

        shell = ContextShell(probe.EXPECTED_CONTEXT)
        self.assertEqual(probe.verify_call_context(shell), list(probe.EXPECTED_CONTEXT))
        self.assertEqual(
            shell.assert_request,
            (probe.CONTEXT_ADDRESS, len(probe.EXPECTED_CONTEXT)),
        )

        armed = list(probe.EXPECTED_CONTEXT)
        armed[probe.HOOK_CONTEXT_INDEX] = probe.HOOK_ARMED
        with self.assertRaises(probe.ProbeError):
            probe.verify_call_context(ContextShell(armed))
        probe.verify_call_context(
            ContextShell(armed), (probe.HOOK_ORIG, probe.HOOK_ARMED)
        )

        corrupt = list(probe.EXPECTED_CONTEXT)
        corrupt[0] ^= 1
        with self.assertRaises(probe.ProbeError):
            probe.verify_call_context(ContextShell(corrupt))

    def test_arm_writes_code_then_state_then_hook(self):
        code = probe.build_probe(probe.DEFAULT_FPSUP)
        shell = FakeInstallShell()
        with contextlib.redirect_stdout(io.StringIO()):
            probe.arm_probe(shell, code)
        self.assertEqual(shell.site, probe.HOOK_ARMED)
        self.assertEqual(shell.writes[0][0:2], ("verified", probe.CODE))
        self.assertEqual(shell.writes[1], ("verified", probe.STATE, (0,) * probe.STATE_WORDS))
        self.assertEqual(shell.writes[2], ("set", probe.HOOK_SITE, (probe.HOOK_ARMED,)))

    def test_context_mismatch_prevents_all_install_writes(self):
        context_words = list(probe.EXPECTED_CONTEXT)
        context_words[0] ^= 1
        shell = FakeInstallShell(context=context_words)
        with self.assertRaises(probe.ProbeError):
            probe.arm_probe(shell, b"\0\0\0\0")
        self.assertEqual(shell.writes, [])

    def test_restore_accepts_only_this_armed_hook_with_valid_context(self):
        shell = FakeInstallShell(site=probe.HOOK_ARMED)
        with contextlib.redirect_stdout(io.StringIO()):
            probe.restore_probe(shell)
        self.assertEqual(shell.site, probe.HOOK_ORIG)

        bad_context = list(probe.EXPECTED_CONTEXT)
        bad_context[-1] ^= 1
        shell = FakeInstallShell(site=probe.HOOK_ARMED, context=bad_context)
        with self.assertRaises(probe.ProbeError):
            probe.restore_probe(shell)
        self.assertEqual(shell.site, probe.HOOK_ARMED)

    def test_normal_arm(self):
        shell = FakeShell()
        self.assertTrue(probe.arm_site(shell))
        self.assertEqual(shell.site, probe.HOOK_ARMED)
        self.assertEqual(shell.arm_writes, 1)

    def test_dropped_arm_is_retried(self):
        shell = FakeShell(drop_arms=1)
        self.assertTrue(probe.arm_site(shell))
        self.assertEqual(shell.site, probe.HOOK_ARMED)
        self.assertEqual(shell.arm_writes, 2)

    def test_immediate_fire_is_not_rearmed(self):
        shell = FakeShell(fire_immediately=True)
        self.assertFalse(probe.arm_site(shell))
        self.assertEqual(shell.site, probe.HOOK_ORIG)
        self.assertEqual(shell.arm_writes, 1)

    def test_unknown_hook_is_refused(self):
        shell = FakeShell(site=0x12345678)
        with self.assertRaises(probe.ProbeError):
            probe.arm_site(shell)
        self.assertEqual(shell.arm_writes, 0)


if __name__ == "__main__":
    unittest.main()
