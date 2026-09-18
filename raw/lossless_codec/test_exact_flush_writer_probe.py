#!/usr/bin/env python3
"""Offline safety contract for the exact SD-flush observation probe.

The host module and assembly are intentionally imported but never allowed to
construct a camera shell here.  These tests model reads and writes in memory so
the one-shot installer can be reviewed before any USB use.
"""

from __future__ import annotations

import contextlib
import io
import re
import unittest

import exact_flush_writer_probe as probe


EXPECTED_CONTEXT = (
    0xE320F000,  # C03A5484: nop
    0xE1A01004,  # C03A5488: mov r1, r4
    0xE28D0020,  # C03A548C: add r0, sp, #0x20
    0xEB0BD652,  # C03A5490: bl  C069ADE0
    0xE1A06000,  # C03A5494: mov r6, r0
    0xE1A07001,  # C03A5498: mov r7, r1
    0xE5DB300D,  # C03A549C: ldrb r3, [r11, #0xd]
    0xE3530000,  # C03A54A0: cmp r3, #0
)


SHAPE_REQUIRED_INDICES = (
    probe.S_COUNT,
    probe.S_WRITER,
    probe.S_LR,
    probe.S_WRITER_8,
    probe.S_HEAD,
    probe.S_NODE_COUNT,
    probe.S_EXPECTED_NODE,
    probe.S_NODE_NEXT,
    probe.S_NODE_BUFFER,
    probe.S_NODE_LENGTH,
    probe.S_NODE_KIND,
    probe.S_DNG_MAGIC,
    probe.S_SHAPE_FLAGS,
    probe.S_RESTORED,
    probe.S_ENTERED,
    probe.S_DONE,
)


def success_shape_fixture():
    """Return the minimal exact state accepted as a proven observation."""
    values = [0] * probe.STATE_WORDS
    writer = 0x45166000
    values[probe.S_COUNT] = 1
    values[probe.S_WRITER] = writer
    values[probe.S_LR] = probe.EXPECTED_LR
    values[probe.S_WRITER_8] = 1
    values[probe.S_HEAD] = writer + 0x0C
    values[probe.S_NODE_COUNT] = 1
    values[probe.S_EXPECTED_NODE] = writer + 0x0C
    values[probe.S_NODE_NEXT] = 0
    values[probe.S_NODE_BUFFER] = 0x53B16000
    values[probe.S_NODE_LENGTH] = probe.FHD_DNG_LENGTH
    values[probe.S_NODE_KIND] = probe.NODE_KIND
    values[probe.S_DNG_MAGIC] = probe.TIFF_MAGIC
    values[probe.S_SHAPE_FLAGS] = probe.SHAPE_ALL
    values[probe.S_RESTORED] = probe.HOOK_ORIG
    values[probe.S_ENTERED] = probe.ENTERED_MAGIC
    values[probe.S_DONE] = probe.DONE_MAGIC
    return values


class FakeShell:
    """A strict memory-only model of the three regions an install may touch."""

    def __init__(
        self,
        *,
        context=None,
        site=None,
        code_fill=0,
        state_fill=0,
        fire_immediately=False,
    ):
        self.context = list(context or probe.EXPECTED_CONTEXT)
        self.site = probe.HOOK_ORIG if site is None else site
        self.code = [code_fill] * ((probe.STATE - probe.CODE) // 4)
        self.state = [state_fill] * probe.STATE_WORDS
        self.fire_immediately = fire_immediately
        self.writes = []

    def read_word(self, address):
        if address != probe.HOOK_SITE:
            raise AssertionError(f"unexpected word read 0x{address:08X}")
        return self.site

    def read_words(self, address, count):
        if address == probe.CONTEXT_ADDRESS and count == len(probe.EXPECTED_CONTEXT):
            words = list(self.context)
            words[probe.HOOK_CONTEXT_INDEX] = self.site
            return words
        if address == probe.CODE and 0 <= count <= len(self.code):
            return list(self.code[:count])
        if address == probe.STATE and count == probe.STATE_WORDS:
            return list(self.state)
        if address == probe.HOOK_SITE and count == 1:
            return [self.site]
        raise AssertionError(f"unexpected read 0x{address:08X}, {count}")

    def set_word(self, address, value):
        if address != probe.HOOK_SITE:
            raise AssertionError(f"unexpected single-word write 0x{address:08X}")
        self.writes.append(("set", address, (value,)))
        if value == probe.HOOK_ARMED and self.fire_immediately:
            state = success_shape_fixture()
            state[probe.S_COUNT] = 1
            state[probe.S_DONE] = probe.DONE_MAGIC
            state[probe.S_RESTORED] = probe.HOOK_ORIG
            self.state = state
            self.site = probe.HOOK_ORIG
        else:
            self.site = value

    def write_words_verified(self, address, values, attempts=8):
        values = tuple(values)
        self.writes.append(("verified", address, values))
        if address == probe.CODE and len(values) <= len(self.code):
            self.code[: len(values)] = values
            return
        if address == probe.STATE and len(values) == probe.STATE_WORDS:
            self.state = list(values)
            return
        if address == probe.HOOK_SITE and values == (probe.HOOK_ORIG,):
            self.site = probe.HOOK_ORIG
            return
        raise AssertionError(f"unexpected verified write 0x{address:08X}")

    def write_word_verified(self, address, value, attempts=8):
        self.write_words_verified(address, [value], attempts)


class FlushWriterProbeTests(unittest.TestCase):
    def test_exact_branch_and_eight_word_context(self):
        self.assertEqual(probe.HOOK_SITE, 0xC03A5490)
        self.assertEqual(probe.HOOK_ORIG, 0xEB0BD652)
        self.assertEqual(probe.REAL_FLUSH, 0xC069ADE0)
        self.assertEqual(probe.CODE, 0xC0730000)
        self.assertEqual(probe.CODE_LIMIT, 0xC0730600)
        self.assertEqual(probe.STATE, 0xC0730600)
        self.assertEqual(probe.STATE_LIMIT, 0xC0730700)
        self.assertEqual(probe.EXPECTED_LR, 0xC03A5494)
        self.assertEqual(probe.STATE_WORDS, 64)
        self.assertEqual(probe.CONTEXT_ADDRESS, probe.HOOK_SITE - 12)
        self.assertEqual(probe.HOOK_CONTEXT_INDEX, 3)
        self.assertEqual(tuple(probe.EXPECTED_CONTEXT), EXPECTED_CONTEXT)
        self.assertEqual(len(probe.EXPECTED_CONTEXT), 8)
        self.assertEqual(probe.arm_bl(probe.HOOK_SITE, probe.REAL_FLUSH), probe.HOOK_ORIG)
        self.assertEqual(probe.HOOK_ARMED, 0xEB0E2ADA)

    def test_assembly_fits_before_state_and_contains_real_flush(self):
        code = probe.build_probe(probe.DEFAULT_FPSUP)
        words = probe.words_from(code)
        self.assertGreater(len(code), 0)
        self.assertEqual(len(code) & 3, 0)
        self.assertEqual(probe.CODE_LIMIT, probe.STATE)
        self.assertLessEqual(probe.CODE + len(code), probe.CODE_LIMIT)
        self.assertIn(probe.REAL_FLUSH, words)

        # A wrapper must return to EXPECTED_LR after the real flush, rather than
        # jumping into a writer/DNG replacement.  Accept ARM bx-lr or a pop that
        # restores pc; literal pools may follow the executable return.
        has_transparent_return = any(
            word == 0xE12FFF1E
            or (word & 0xFFFF8000) == 0xE8BD8000
            for word in words
        )
        self.assertTrue(has_transparent_return)
        self.assertEqual(words[-2:], [0xE51FF004, probe.REAL_FLUSH])

    def test_source_is_observer_only_and_never_writes_writer_or_dng(self):
        source = probe.SOURCE.read_text()
        code_only = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        code_only = re.sub(r"@.*", "", code_only)
        code_only = re.sub(r"//.*", "", code_only)

        for forbidden in (
            "REAL_WRITE",
            "F_REGISTER",
            "F_CODEC_INIT",
            "F_CODEC_ENCODE",
            "F_MEMCPY",
            "Compression",
            "StripOffsets",
            "TileOffsets",
            "0xC069AC88",
            "0xC05A6890",
            "0xC05A6920",
            "0xC05A6990",
        ):
            self.assertNotIn(forbidden, code_only)

        # Probe state and the one-shot hook word are its only persistent writes.
        # Stack stores are local.  Pin both hook-restoration stores, including
        # the stale-I-cache path, and require every other store to use STATE.
        store_lines = [
            line.strip()
            for line in code_only.splitlines()
            if re.match(r"^str(?:b|h)?\s", line.strip())
        ]
        self.assertTrue(store_lines)
        hook_restores = ("str     r6, [r5]", "str     r12, [r3]")
        for restore in hook_restores:
            self.assertEqual(store_lines.count(restore), 1)
        self.assertIn(
            "LDA     r5, HOOK_SITE\n    LDA     r6, HOOK_ORIG\n    str     r6, [r5]",
            code_only,
        )
        self.assertIn(
            "LDA     r3, HOOK_SITE\n    LDA     r12, HOOK_ORIG\n    str     r12, [r3]",
            code_only,
        )
        for line in store_lines:
            if line in hook_restores:
                continue
            self.assertRegex(line, r"\[r4(?:,|\])", line)

    def test_shape_success_requires_every_declared_proof_word(self):
        values = success_shape_fixture()
        self.assertEqual(len(values), probe.STATE_WORDS)
        self.assertTrue(probe.shape_success(values))

        required = SHAPE_REQUIRED_INDICES
        self.assertTrue(required)
        self.assertEqual(len(required), len(set(required)))
        self.assertTrue(all(0 <= index < probe.STATE_WORDS for index in required))
        self.assertEqual(tuple(probe.SHAPE_REQUIRED_INDICES), required)
        for index in required:
            broken = list(values)
            if index in (probe.S_WRITER, probe.S_WRITER_8, probe.S_NODE_BUFFER):
                broken[index] = 0
            else:
                broken[index] ^= 1
            self.assertFalse(probe.shape_success(broken), index)

        self.assertFalse(probe.shape_success(values[:-1]))
        self.assertFalse(probe.shape_success(values + [0]))

    def test_region_survey_rejects_any_nonzero_code_or_state(self):
        code = probe.build_probe(probe.DEFAULT_FPSUP)
        for region_name in ("code", "state"):
            size = len(getattr(FakeShell(), region_name))
            for index in (0, size // 2, size - 1):
                shell = FakeShell()
                getattr(shell, region_name)[index] = 1
                with self.subTest(region=region_name, index=index):
                    with self.assertRaises(probe.ProbeError):
                        probe.arm_probe(shell, code)
                    self.assertEqual(shell.writes, [])

    def test_context_mismatch_causes_zero_writes(self):
        code = probe.build_probe(probe.DEFAULT_FPSUP)
        for index in range(len(probe.EXPECTED_CONTEXT)):
            if index == probe.HOOK_CONTEXT_INDEX:
                shell = FakeShell(site=probe.HOOK_ORIG ^ 1)
            else:
                context = list(probe.EXPECTED_CONTEXT)
                context[index] ^= 1
                shell = FakeShell(context=context)
            with self.subTest(index=index):
                with self.assertRaises(probe.ProbeError):
                    probe.arm_probe(shell, code)
                self.assertEqual(shell.writes, [])

    def test_install_order_is_code_state_then_hook_as_final_write(self):
        code = probe.build_probe(probe.DEFAULT_FPSUP)
        shell = FakeShell()
        with contextlib.redirect_stdout(io.StringIO()):
            probe.arm_probe(shell, code)
        self.assertEqual(shell.writes[0][0:2], ("verified", probe.CODE))
        self.assertEqual(
            shell.writes[1],
            ("verified", probe.STATE, (0,) * probe.STATE_WORDS),
        )
        self.assertEqual(
            shell.writes[2],
            ("set", probe.HOOK_SITE, (probe.HOOK_ARMED,)),
        )
        self.assertEqual(len(shell.writes), 3)

    def test_immediate_fire_is_never_rearmed(self):
        code = probe.build_probe(probe.DEFAULT_FPSUP)
        shell = FakeShell(fire_immediately=True)
        with contextlib.redirect_stdout(io.StringIO()):
            probe.arm_probe(shell, code)
        arm_writes = [
            write
            for write in shell.writes
            if write == ("set", probe.HOOK_SITE, (probe.HOOK_ARMED,))
        ]
        self.assertEqual(len(arm_writes), 1)
        self.assertEqual(shell.site, probe.HOOK_ORIG)
        self.assertEqual(shell.state[probe.S_COUNT], 1)
        self.assertEqual(shell.state[probe.S_DONE], probe.DONE_MAGIC)
        self.assertEqual(shell.state[probe.S_RESTORED], probe.HOOK_ORIG)


if __name__ == "__main__":
    unittest.main()
