#!/usr/bin/env python3

import contextlib
import io
import pathlib
import sys
import unittest
from unittest import mock

import exact_dng_writer_probe as base
import single_frame_codec_probe as probe


class FakeShell:
    def __init__(self, *, context=None, fire_immediately=False, site=None):
        self.site = base.HOOK_ORIG if site is None else site
        self.context = list(context or base.EXPECTED_CONTEXT)
        self.state = [0] * probe.STATE_WORDS
        self.log = [0] * (probe.AGG_OFF // 4 + probe.AGG_WORDS)
        self.fire_immediately = fire_immediately
        self.writes = []

    def read_word(self, address):
        if address != base.HOOK_SITE:
            raise AssertionError(f"unexpected read 0x{address:08X}")
        return self.site

    def read_words(self, address, count):
        if address == base.CONTEXT_ADDRESS and count == len(base.EXPECTED_CONTEXT):
            words = list(self.context)
            words[base.HOOK_CONTEXT_INDEX] = self.site
            return words
        if address == probe.STATE and count in (base.STATE_WORDS, probe.STATE_WORDS):
            return list(self.state[:count])
        if address == probe.LOG and count <= len(self.log):
            return list(self.log[:count])
        if address == probe.LOG + probe.AGG_OFF:
            start = probe.AGG_OFF // 4
            return list(self.log[start:start + count])
        if address == base.HOOK_SITE and count == 1:
            return [self.site]
        raise AssertionError(f"unexpected read 0x{address:08X}, {count}")

    def set_word(self, address, value):
        if address != base.HOOK_SITE:
            raise AssertionError(f"unexpected write 0x{address:08X}")
        self.writes.append(("set", address, (value,)))
        if value == base.HOOK_ARMED and self.fire_immediately:
            self.state[probe.S_COUNT] = 1
            self.state[probe.S_DONE] = base.DONE_MAGIC
            self.state[probe.S_RESTORED] = base.HOOK_ORIG
            self.site = base.HOOK_ORIG
        else:
            self.site = value

    def write_words_verified(self, address, values, attempts=8):
        values = tuple(values)
        self.writes.append(("verified", address, values))
        if address == probe.CODE:
            return
        if address == probe.STATE and len(values) == probe.STATE_WORDS:
            self.state = list(values)
            return
        if address == probe.LOG and len(values) <= len(self.log):
            self.log[:len(values)] = list(values)
            return
        if address == base.HOOK_SITE and values == (base.HOOK_ORIG,):
            self.site = base.HOOK_ORIG
            return
        raise AssertionError(f"unexpected verified write 0x{address:08X}")

    def write_word_verified(self, address, value, attempts=8):
        self.write_words_verified(address, [value], attempts)


class CodecProbeTests(unittest.TestCase):
    @staticmethod
    def successful_preflight_state():
        values = [0] * probe.STATE_WORDS
        values[probe.S_COUNT] = 1
        values[probe.S_DONE] = base.DONE_MAGIC
        values[probe.S_RESTORED] = base.HOOK_ORIG
        values[probe.S_PHASE] = probe.PHASE_PREFLIGHT
        values[probe.S_STAGE] = 7
        values[probe.S_R2] = 2
        values[probe.S_LR] = base.EXPECTED_LR
        values[probe.S_BUFFER] = 0x53B02C00
        values[probe.S_LENGTH] = 0x00318200
        values[probe.S_SOURCE] = 0x53B16000
        values[probe.S_PREFLIGHT] = probe.PREFLIGHT_MAGIC
        return values

    @staticmethod
    def successful_scratch_state(handle=0x45166C00):
        values = [0] * probe.STATE_WORDS
        values[probe.S_COUNT] = 1
        values[probe.S_R2] = 2
        values[probe.S_LR] = base.EXPECTED_LR
        values[probe.S_BUFFER] = 0x53B02C00
        values[probe.S_LENGTH] = 0x00318200
        values[probe.S_DONE] = base.DONE_MAGIC
        values[probe.S_RESTORED] = base.HOOK_ORIG
        values[probe.S_PHASE] = probe.PHASE_SCRATCH
        values[probe.S_STAGE] = 7
        values[probe.S_ALLOCATOR] = 0xC3073A5C
        values[probe.S_HANDLE] = handle
        values[probe.S_ALLOC_END] = handle + probe.ALLOC_SIZE
        values[probe.S_WORK_BASE] = handle
        values[probe.S_WORK_END] = handle + probe.WORK_CAP
        values[probe.S_WORK_GUARD] = handle + probe.WORK_CAP
        values[probe.S_TABLE_BASE] = handle + probe.TABLE_OFFSET
        values[probe.S_TABLE_TEMP] = handle + probe.TABLE_TEMP_OFFSET
        values[probe.S_SCRATCH_SOURCE] = 0x53B16000
        values[probe.S_GUARD_WORK] = probe.GUARD_MAGIC
        values[probe.S_GUARD_TABLE] = probe.GUARD_MAGIC
        values[probe.S_GUARD_TEMP] = probe.GUARD_MAGIC
        values[probe.S_PREFLIGHT] = probe.PREFLIGHT_MAGIC
        values[probe.S_SCRATCH_MAGIC] = probe.SCRATCH_MAGIC
        values[probe.S_END_GUARD] = handle + probe.ALLOC_SIZE - 4
        values[probe.S_GUARD_END] = probe.GUARD_MAGIC
        values[probe.S_TABLE_GUARD] = (
            handle + probe.TABLE_OFFSET + probe.TABLE_BYTES
        )
        values[probe.S_TEMP_GUARD] = (
            handle + probe.TABLE_TEMP_OFFSET + probe.TABLE_BYTES
        )
        return values

    def test_power_preflight_build_is_small_and_transparent(self):
        code = probe.build_image("preflight", base.DEFAULT_FPSUP)
        words = base.words_from(code)
        self.assertGreater(len(code), 0)
        self.assertLessEqual(probe.CODE + len(code), probe.PREFLIGHT_CODE_LIMIT)
        self.assertEqual(words[0], 0xE92D503F)  # push r0-r5,r12,lr
        self.assertEqual(words[-2], 0xE51FF004)
        self.assertEqual(words[-1], base.REAL_WRITE)

    def test_preflight_source_cannot_touch_allocator_codec_or_dng(self):
        source = probe.PREFLIGHT_SOURCE.read_text()
        for forbidden in (
            "F_ALLOC",
            "F_GET",
            "F_INIT",
            "F_ENC",
            "F_SIZE",
            "0xC001CF78",
            "0xC001D038",
            "0xC05A6890",
            "0xC05A6920",
            "0xC05A6990",
        ):
            self.assertNotIn(forbidden, source)
        # The preflight may read the segment/DNG for its exact FHD shape guard,
        # but its only stores are to STATE through r4 and the hook through r1.
        self.assertEqual(source.count("str     r2, [r1]"), 1)
        store_lines = [line.strip() for line in source.splitlines() if line.strip().startswith("str")]
        self.assertTrue(store_lines)
        for line in store_lines:
            self.assertTrue("[r4," in line or line == "str     r2, [r1]", line)

    def test_scratch_build_is_transparent_and_bounded(self):
        code = probe.build_image("scratch", base.DEFAULT_FPSUP)
        words = base.words_from(code)
        self.assertGreater(len(code), 0)
        self.assertLessEqual(probe.CODE + len(code), probe.SCRATCH_CODE_LIMIT)
        self.assertGreater(probe.CODE + len(code), 0xC072FC00)
        self.assertEqual(words[0], 0xE92D55FF)
        self.assertEqual(words[-2:], [0xE51FF004, base.REAL_WRITE])

    def test_scratch_source_only_allocates_and_never_calls_codec_or_power(self):
        source = probe.SCRATCH_SOURCE.read_text()
        self.assertIn("F_ALLOC", source)
        self.assertIn("F_GET", source)
        for forbidden in (
            "F_INIT",
            "F_ENC",
            "F_SIZE",
            "F_PWR",
            "F_CLK",
            "0xC05A6890",
            "0xC05A6920",
            "0xC05A6990",
            "0xC0708C61",
            "0xC07095A9",
            "F_ADDR",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("LDA     r2, 0x400", source)
        self.assertIn("str     r3, [sp]", source)

    def test_scratch_success_requires_exact_retained_layout(self):
        values = self.successful_scratch_state()
        self.assertTrue(probe.scratch_preflight_success(values))
        for index in (
            probe.S_DONE,
            probe.S_RESTORED,
            probe.S_PHASE,
            probe.S_STAGE,
            probe.S_ERROR,
            probe.S_ALLOCATOR,
            probe.S_HANDLE,
            probe.S_ALLOC_END,
            probe.S_WORK_BASE,
            probe.S_WORK_END,
            probe.S_WORK_GUARD,
            probe.S_TABLE_BASE,
            probe.S_TABLE_TEMP,
            probe.S_SCRATCH_SOURCE,
            probe.S_SCRATCH_CODEC_MODE,
            probe.S_GUARD_WORK,
            probe.S_GUARD_TABLE,
            probe.S_GUARD_TEMP,
            probe.S_PREFLIGHT,
            probe.S_SCRATCH_MAGIC,
            probe.S_END_GUARD,
            probe.S_GUARD_END,
            probe.S_TABLE_GUARD,
            probe.S_TEMP_GUARD,
        ):
            broken = list(values)
            if index == probe.S_ALLOCATOR:
                broken[index] = 0
            else:
                broken[index] ^= 1
            self.assertFalse(probe.scratch_preflight_success(broken), index)

    def test_scratch_arm_requires_power_proof_and_preserves_magic_seed(self):
        code = probe.build_image("scratch", base.DEFAULT_FPSUP)
        shell = FakeShell()
        with self.assertRaises(probe.ProbeError):
            probe.arm_scratch_preflight(shell, code)
        self.assertEqual(shell.writes, [])

        shell.state = self.successful_preflight_state()
        with contextlib.redirect_stdout(io.StringIO()):
            probe.arm_scratch_preflight(shell, code)
        self.assertEqual(shell.site, base.HOOK_ARMED)
        self.assertEqual(shell.writes[0][0:2], ("verified", probe.CODE))
        seeded = shell.writes[1]
        self.assertEqual(seeded[0:2], ("verified", probe.STATE))
        self.assertEqual(seeded[2][probe.S_PREFLIGHT], probe.PREFLIGHT_MAGIC)
        self.assertEqual(sum(value != 0 for value in seeded[2]), 1)
        self.assertEqual(shell.writes[2], ("set", base.HOOK_SITE, (base.HOOK_ARMED,)))

    def test_successful_scratch_state_refuses_duplicate_arm(self):
        code = probe.build_image("scratch", base.DEFAULT_FPSUP)
        shell = FakeShell()
        shell.state = self.successful_scratch_state()
        with self.assertRaises(probe.ProbeError):
            probe.arm_scratch_preflight(shell, code)
        self.assertEqual(shell.writes, [])

    def test_retained_scratch_cannot_be_orphaned_by_power_rearm(self):
        code = probe.build_image("preflight", base.DEFAULT_FPSUP)
        shell = FakeShell()
        shell.state = self.successful_scratch_state()
        with self.assertRaises(probe.ProbeError):
            probe.arm_power_preflight(shell, code)
        self.assertEqual(shell.writes, [])

    def test_preflight_has_balanced_order_and_failure_cleanup(self):
        source = probe.PREFLIGHT_SOURCE.read_text()
        power_on = source.index("mov     r0, #1\n    LDA     r12, F_PWR")
        clock_on = source.index("mov     r1, #1\n    LDA     r12, F_CLK")
        clock_off = source.index("mov     r1, #0\n    LDA     r12, F_CLK")
        power_off = source.index("mov     r0, #0\n    LDA     r12, F_PWR", clock_off)
        self.assertLess(power_on, clock_on)
        self.assertLess(clock_on, clock_off)
        self.assertLess(clock_off, power_off)
        cleanup = source[source.index("cleanup_power_after_clock_failure:") :]
        self.assertIn("LDA     r12, F_PWR", cleanup)
        self.assertIn("mov     r0, #ERR_CLK_ON", cleanup)
        # The reviewed firmware-matching policy does not cut power after a
        # failed clock-off; that path goes straight to finish.
        clock_off_failure = source[
            source.index("clock_off_failed:") : source.index("power_off_failed:")
        ]
        self.assertNotIn("F_PWR", clock_off_failure)

    def test_preflight_success_requires_every_proof_field(self):
        values = self.successful_preflight_state()
        self.assertTrue(probe.power_preflight_success(values))

        for index in (
            probe.S_COUNT,
            probe.S_DONE,
            probe.S_RESTORED,
            probe.S_STAGE,
            probe.S_ERROR,
            probe.S_CLEANUP_ERROR,
            probe.S_CODEC_MODE,
            probe.S_R2,
            probe.S_LR,
            probe.S_BUFFER,
            probe.S_LENGTH,
            probe.S_SOURCE,
            probe.S_PWR_ON,
            probe.S_CLK_ON,
            probe.S_CLK_OFF,
            probe.S_PWR_OFF,
            probe.S_PREFLIGHT,
        ):
            broken = list(values)
            broken[index] = 1
            if index == probe.S_COUNT:
                broken[index] = 0
            if index in (
                probe.S_DONE,
                probe.S_RESTORED,
                probe.S_LR,
                probe.S_BUFFER,
                probe.S_LENGTH,
                probe.S_SOURCE,
                probe.S_PREFLIGHT,
            ):
                broken[index] ^= 1
            self.assertFalse(probe.power_preflight_success(broken), index)

    def test_status_reports_proven_preflight(self):
        shell = FakeShell()
        shell.state = self.successful_preflight_state()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            probe.show_status(shell)
        self.assertIn("power_preflight           PASS", output.getvalue())

    def test_preflight_gate_is_read_only_and_rechecks_context(self):
        shell = FakeShell()
        shell.state = self.successful_preflight_state()
        self.assertEqual(probe.require_power_preflight(shell), shell.state)
        self.assertEqual(shell.writes, [])

        shell.context[0] ^= 1
        with self.assertRaises(base.ProbeError):
            probe.require_power_preflight(shell)
        self.assertEqual(shell.writes, [])

    def test_arm_uses_context_guard_and_hook_is_final_write(self):
        code = probe.build_image("preflight", base.DEFAULT_FPSUP)
        shell = FakeShell()
        with contextlib.redirect_stdout(io.StringIO()):
            probe.arm_power_preflight(shell, code)
        self.assertEqual(shell.site, base.HOOK_ARMED)
        self.assertEqual(shell.writes[0][0:2], ("verified", probe.CODE))
        self.assertEqual(
            shell.writes[1],
            ("verified", probe.STATE, (0,) * probe.STATE_WORDS),
        )
        self.assertEqual(shell.writes[2], ("set", base.HOOK_SITE, (base.HOOK_ARMED,)))

    def test_context_mismatch_refuses_before_any_write(self):
        code = probe.build_image("preflight", base.DEFAULT_FPSUP)
        context_words = list(base.EXPECTED_CONTEXT)
        context_words[0] ^= 1
        shell = FakeShell(context=context_words)
        with self.assertRaises(base.ProbeError):
            probe.arm_power_preflight(shell, code)
        self.assertEqual(shell.writes, [])

    def test_immediate_fire_is_not_rearmed(self):
        code = probe.build_image("preflight", base.DEFAULT_FPSUP)
        shell = FakeShell(fire_immediately=True)
        # Model the in-probe completion fields required by base.arm_site.
        original_set = shell.set_word

        def set_and_complete(address, value):
            original_set(address, value)
            if value == base.HOOK_ARMED:
                shell.state[base.S_DONE] = base.DONE_MAGIC
                shell.state[base.S_RESTORED] = base.HOOK_ORIG

        shell.set_word = set_and_complete
        with contextlib.redirect_stdout(io.StringIO()):
            probe.arm_power_preflight(shell, code)
        arm_writes = [entry for entry in shell.writes if entry[0] == "set"]
        self.assertEqual(len(arm_writes), 1)
        self.assertEqual(shell.site, base.HOOK_ORIG)

    def test_guarded_restore_rejects_bad_context(self):
        bad = list(base.EXPECTED_CONTEXT)
        bad[-1] ^= 1
        shell = FakeShell(context=bad, site=base.HOOK_ARMED)
        with self.assertRaises(base.ProbeError):
            base.restore_probe(shell)
        self.assertEqual(shell.site, base.HOOK_ARMED)

    def test_encode_layout_is_aligned_in_bounds_and_disjoint(self):
        layout = probe.encode_layout(0x45166C00)
        self.assertTrue(probe.encode_layout_is_safe(layout))
        self.assertEqual(layout["work"], (0x45166C00, 0x4546BC00))
        self.assertEqual(layout["size_table"][0], 0x4546CC00)
        self.assertEqual(layout["temporary_table"][0], 0x4546D000)
        self.assertLessEqual(
            layout["temporary_table_guard"][1], layout["allocation"][1]
        )
        self.assertFalse(probe.encode_layout_is_safe(probe.encode_layout(1)))

    def test_encode_design_builds_but_live_action_is_refused_before_shell(self):
        code = probe.build_image("encode", base.DEFAULT_FPSUP)
        self.assertLessEqual(probe.CODE + len(code), probe.ENCODE_DESIGN_LIMIT)
        self.assertEqual(base.words_from(code)[-2:], [0xE51FF004, base.REAL_WRITE])

        called = False

        def forbidden_shell(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("CameraShell must not be constructed")

        argv = ["single_frame_codec_probe.py", "encode"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            base, "CameraShell", forbidden_shell
        ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            self.assertEqual(probe.main(), 1)
        self.assertFalse(called)

    def test_encode_struct_uses_init6_for_output_and_init7_for_table(self):
        source = probe.ENCODE_SOURCE.read_text()
        self.assertIn("str     r8, [sp, #0x18]", source)
        self.assertIn("compressed output/work", source)
        self.assertIn("str     r0, [sp, #0x1C]", source)
        self.assertIn("size-table base", source)
        self.assertIn("mov     r2, #TILE_COUNT", source)
        self.assertIn("str     r1, [r4, #S_COMP_SIZE]", source)

    # ---- PHASE=2: consume the retained block, then release it --------------

    @staticmethod
    def lda_pair(register, value):
        """The movw/movt pair the LDA macro emits for an absolute address."""
        low, high = value & 0xFFFF, value >> 16
        return [
            0xE3000000 | ((low >> 12) << 16) | (register << 12) | (low & 0xFFF),
            0xE3400000 | ((high >> 12) << 16) | (register << 12) | (high & 0xFFF),
        ]

    @classmethod
    def calls(cls, words, address):
        pair = cls.lda_pair(12, address)
        return any(words[index:index + 2] == pair for index in range(len(words) - 1))

    def successful_encode_state(self, handle=0x45166C00, *, encode_return=1,
                                entered=1, adopted=1, error=0):
        values = [0] * probe.STATE_WORDS
        values[probe.S_COUNT] = 1
        values[probe.S_DONE] = base.DONE_MAGIC
        values[probe.S_RESTORED] = base.HOOK_ORIG
        values[probe.S_PHASE] = probe.PHASE_ENCODE
        values[probe.S_STAGE] = 8
        values[probe.S_ERROR] = error
        values[probe.S_ALLOCATOR] = 0xC3A00000
        values[probe.S_HANDLE] = handle
        values[probe.S_ADOPTED] = adopted
        values[probe.S_ENCODE_STARTED] = entered
        values[probe.S_INIT_RET] = 1
        values[probe.S_ENC_RET] = encode_return
        values[probe.S_SIZE_RET] = 1
        values[probe.S_T0] = 0xFFFFFF00
        values[probe.S_T1] = (0xFFFFFF00 + 21000) & 0xFFFFFFFF
        values[probe.S_COMPRESSED] = 1_300_000
        for index in range(probe.TILE_COUNT):
            values[probe.S_TILE0 + index] = 1_300_000 // probe.TILE_COUNT
        if encode_return == 1 and not error:
            values[probe.S_FREE_DONE] = probe.FREE_MAGIC
        else:
            values[probe.S_FREE_ERROR] = probe.ERR_RETAINED
        return values

    def test_live_encode_build_is_bounded_and_transparent(self):
        code = probe.build_image("encode-live", base.DEFAULT_FPSUP)
        words = base.words_from(code)
        self.assertLessEqual(probe.CODE + len(code), probe.ENCODE_LIVE_LIMIT)
        self.assertLess(probe.ENCODE_LIVE_LIMIT, 0xC0730000)
        self.assertEqual(words[0], 0xE92D55FF)
        self.assertEqual(words[-2:], [0xE51FF004, base.REAL_WRITE])

    def test_live_encode_allocates_nothing_and_frees(self):
        live = base.words_from(probe.build_image("encode-live", base.DEFAULT_FPSUP))
        design = base.words_from(probe.build_image("encode", base.DEFAULT_FPSUP))
        for allocator_call in (0xC001CF78, 0xC001D038):
            self.assertTrue(self.calls(design, allocator_call))
            self.assertFalse(self.calls(live, allocator_call))
        self.assertTrue(self.calls(live, 0xC001D2B8))
        self.assertFalse(self.calls(design, 0xC001D2B8))
        for shared in (0xC05A6890, 0xC05A6920, 0xC05A6990, 0xC002B6E0):
            self.assertTrue(self.calls(live, shared))

    def test_reviewed_design_image_is_byte_identical(self):
        """PHASE=0/1 must not shift when PHASE=2 is added."""
        code = probe.build_image("encode", base.DEFAULT_FPSUP)
        self.assertEqual(len(code), 1268)
        self.assertEqual(probe.CODE + len(code), 0xC072FCF4)

    def test_live_encode_arm_requires_a_complete_scratch_result(self):
        code = probe.build_image("encode-live", base.DEFAULT_FPSUP)
        shell = FakeShell()
        with self.assertRaises(probe.ProbeError):
            probe.arm_live_encode(shell, code)
        self.assertEqual(shell.writes, [])

        shell.state = self.successful_preflight_state()
        with self.assertRaises(probe.ProbeError):
            probe.arm_live_encode(shell, code)
        self.assertEqual(shell.writes, [])

        broken = self.successful_scratch_state()
        broken[probe.S_GUARD_WORK] ^= 1
        shell.state = broken
        with self.assertRaises(probe.ProbeError):
            probe.arm_live_encode(shell, code)
        self.assertEqual(shell.writes, [])

    def test_live_encode_seeds_only_the_handle_and_both_proofs(self):
        code = probe.build_image("encode-live", base.DEFAULT_FPSUP)
        shell = FakeShell()
        scratch = self.successful_scratch_state()
        shell.state = scratch
        with contextlib.redirect_stdout(io.StringIO()):
            probe.arm_live_encode(shell, code)
        self.assertEqual(shell.writes[0][0:2], ("verified", probe.CODE))
        seeded = shell.writes[1]
        self.assertEqual(seeded[0:2], ("verified", probe.STATE))
        values = seeded[2]
        self.assertEqual(values[probe.S_PREFLIGHT], probe.PREFLIGHT_MAGIC)
        self.assertEqual(values[probe.S_SCRATCH_MAGIC], probe.SCRATCH_MAGIC)
        self.assertEqual(values[probe.S_ALLOCATOR], scratch[probe.S_ALLOCATOR])
        self.assertEqual(values[probe.S_HANDLE], scratch[probe.S_HANDLE])
        self.assertEqual(sum(value != 0 for value in values), 4)
        self.assertEqual(shell.writes[2], ("set", base.HOOK_SITE, (base.HOOK_ARMED,)))

    def test_encode_report_measures_across_a_counter_wrap(self):
        report = probe.encode_report(self.successful_encode_state())
        self.assertEqual(report["elapsed_us"], 21000)
        self.assertEqual(report["mpix_per_second"], round(1936 * 1090 / 21000, 1))
        self.assertLess(report["elapsed_us"], report["frame_budget_24p_us"])
        self.assertEqual(report["ratio"], round(probe.RAW_BYTES / 1_300_000, 3))
        self.assertTrue(report["block_released"])
        self.assertFalse(report["release_refused"])
        self.assertTrue(report["source_unmodified"])

    def test_failed_encode_reports_no_rate_and_keeps_the_block(self):
        values = self.successful_encode_state(encode_return=0, error=18)
        report = probe.encode_report(values)
        self.assertNotIn("elapsed_us", report)
        self.assertNotIn("mpix_per_second", report)
        self.assertTrue(report["release_refused"])
        self.assertFalse(report["block_released"])

    def test_release_policy_is_asymmetric_in_the_source(self):
        source = probe.ENCODE_SOURCE.read_text()
        self.assertIn("ldr     r0, [r4, #S_ADOPTED]", source)
        self.assertIn("ldr     r0, [r4, #S_ENC_STARTED]", source)
        self.assertIn("ERR_RETAINED", source)
        self.assertIn("str     r0, [r4, #S_ENC_STARTED]   /* set BEFORE", source)
        # the marker must precede the timed call, never follow it
        self.assertLess(source.index("S_ENC_STARTED]   /* set BEFORE"),
                        source.index("LDA     r12, F_ENC"))

    # ---- PHASE=3: sustained run ------------------------------------------

    def test_sustained_build_is_bounded_below_its_log(self):
        code = probe.build_image("encode-sustained", base.DEFAULT_FPSUP)
        words = base.words_from(code)
        end = probe.CODE + len(code)
        self.assertLessEqual(end, probe.SUSTAINED_CODE_LIMIT)
        self.assertLessEqual(end, probe.LOG, "code must not reach into the log")
        log_end = probe.LOG + probe.AGG_OFF + probe.AGG_WORDS * 4
        self.assertLessEqual(log_end, 0xC0730000)
        self.assertEqual(words[0], 0xE92D55FF)
        self.assertEqual(words[-2:], [0xE51FF004, base.REAL_WRITE])

    def test_sustained_still_allocates_nothing_and_frees(self):
        live = base.words_from(probe.build_image("encode-sustained", base.DEFAULT_FPSUP))
        for allocator_call in (0xC001CF78, 0xC001D038):
            self.assertFalse(self.calls(live, allocator_call))
        self.assertTrue(self.calls(live, 0xC001D2B8))

    def test_one_shot_images_are_unchanged_by_phase_three(self):
        for kind, size, end in (("encode", 1268, 0xC072FCF4),
                                ("encode-live", 1420, 0xC072FD8C)):
            code = probe.build_image(kind, base.DEFAULT_FPSUP)
            self.assertEqual(len(code), size, kind)
            self.assertEqual(probe.CODE + len(code), end, kind)

    def test_rearm_is_the_last_action_and_is_doubly_bounded(self):
        source = probe.ENCODE_SOURCE.read_text()
        loop = source[source.index("final_frame"):] if False else source
        rearm = loop.index("LDA     r1, HOOK_ARMED")
        # both ceilings are tested before the re-arm store
        self.assertLess(loop.index("cmp     r5, #FRAMES"), rearm)
        self.assertLess(loop.index("cmp     r0, #FRAMES * 2"), rearm)
        # and an error stops the loop before either
        self.assertLess(loop.index("bne     final_frame"), rearm)
        # the site is restored at entry, long before any re-arm
        self.assertLess(loop.index("str     r8, [r7]"), rearm)
        self.assertIn("dsb     sy", loop[rearm:rearm + 400])
        self.assertIn("isb", loop[rearm:rearm + 400])

    def test_sustained_arm_requires_scratch_and_clears_the_log(self):
        code = probe.build_image("encode-sustained", base.DEFAULT_FPSUP)
        shell = FakeShell()
        with self.assertRaises(probe.ProbeError):
            probe.arm_sustained_encode(shell, code)
        self.assertEqual(shell.writes, [])

        shell.state = self.successful_scratch_state()
        with contextlib.redirect_stdout(io.StringIO()):
            probe.arm_sustained_encode(shell, code)
        targets = [(kind, address) for kind, address, _ in shell.writes]
        self.assertEqual(targets[0], ("verified", probe.CODE))
        self.assertEqual(targets[1], ("verified", probe.LOG))
        self.assertEqual(targets[2], ("verified", probe.STATE))
        self.assertEqual(targets[3], ("set", base.HOOK_SITE))
        cleared = shell.writes[1][2]
        self.assertEqual(len(cleared), probe.AGG_OFF // 4 + probe.AGG_WORDS)
        self.assertTrue(all(word == 0 for word in cleared))
        # the rows and every aggregate slot are covered by that clear
        self.assertGreaterEqual(len(cleared) * 4,
                                probe.RING_FRAMES * probe.LOG_WORDS_PER_FRAME * 4)

    def test_log_reader_skips_unwritten_records(self):
        frames = probe.RING_FRAMES
        words = [0] * (frames * probe.LOG_WORDS_PER_FRAME)
        for index, (elapsed, size) in enumerate(((18000, 1200000), (19500, 1310000))):
            words[index * 4:index * 4 + 4] = [elapsed, size, 0x53B02C00 + index * 0x1000,
                                              0x124D3112 + index]

        class LogShell(FakeShell):
            def read_words(self, address, count):
                if address == probe.LOG:
                    return words[:count]
                return super().read_words(address, count)

        records = probe.read_log(LogShell(), frames)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["elapsed_us"], 18000)
        self.assertEqual(records[1]["compressed_bytes"], 1310000)
        self.assertNotEqual(records[0]["buffer"], records[1]["buffer"])
        self.assertIn("first_pixel", records[0])

    def test_rows_ring_and_worst_case_covers_every_frame(self):
        source = probe.ENCODE_SOURCE.read_text()
        # rows are masked into a ring, so a long run cannot walk off the log
        self.assertIn("and     r7, r5, #RING_MASK", source)
        self.assertIn(".equ RING_MASK,       7", source)
        # the worst-case trackers are updated unconditionally, not inside the
        # ring-row path, so they see frames whose rows were overwritten
        agg = source.index("LDA     r6, LOG + AGG_OFF")
        ring = source.index("and     r7, r5, #RING_MASK")
        self.assertLess(ring, agg)
        self.assertIn("strhi   r2, [r6, #AGG_MAX_US]", source)
        self.assertIn("strhi   r3, [r6, #AGG_MAX_BYTES]", source)
        self.assertIn("addhs   r0, r0, #1", source)
        # the ring must fit below the aggregates
        self.assertLessEqual(probe.RING_FRAMES * probe.LOG_WORDS_PER_FRAME * 4,
                             probe.AGG_OFF)

    def test_aggregate_reader(self):
        class AggShell(FakeShell):
            def read_words(self, address, count):
                if address == probe.LOG + probe.AGG_OFF:
                    return [41999, 1400000, 2][:count]
                return super().read_words(address, count)

        aggregates = probe.read_aggregates(AggShell())
        self.assertEqual(aggregates["max_elapsed_us"], 41999)
        self.assertEqual(aggregates["max_compressed_bytes"], 1400000)
        self.assertEqual(aggregates["frames_over_budget"], 2)
        self.assertGreater(aggregates["max_elapsed_us"], probe.BUDGET_US)


if __name__ == "__main__":
    unittest.main()
