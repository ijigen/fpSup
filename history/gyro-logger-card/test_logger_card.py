#!/usr/bin/env python3
"""The logger card's own safety checks, kept with the code they check.

These came out of gyro/test_safety.py, gyro/test_lifecycle.py and
gyro/test_decode_v5.py when the logger generation was retired on 2026-09-23.
They are here rather than deleted because most of them are the only written
record of a property that cost a freeze to find -- the stop publication has to
be followed by a READY rescan; the orientation stub has to be placed before the
word that branches to it; the accelerometer text unroll has to stay bytewise.
The blob generation solves the same problems in different code, so a test here
that still says something true about it belongs in gyro/, re-pointed.

HERE is this directory, which is where the logger sources are now.  The three
layout tests that assemble logger.S fail: the logger outgrew its window in the
cave, which is the thing that retired it.  They are left failing rather than
adjusted, because the number they fail by is the size of the problem.
"""
from __future__ import annotations

import itertools
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent          # the logger sources live here
ROOT = HERE.parents[1]                          # fpSup/
sys.path.insert(0, str(ROOT / "fp_usb_shell"))
sys.path.insert(0, str(ROOT / "gyro"))

from armasm import assemble, symbols             # noqa: E402
import decode                                    # noqa: E402
from test_decode_v5 import capture_bytes         # noqa: E402

class StopRaceTests(unittest.TestCase):
    """From gyro/test_safety.py."""
    def test_successful_take_transactions_drain_without_outer_delay(self):
        """Each take's GCSV and JSON finish before the next take."""

        flags = [0b00, 0b00, 0b00]
        calls = []
        while flags:
            if not flags[0] & 1:
                calls.append(("gcsv", 0))
                flags[0] |= 1
                continue
            calls.append(("json", 0))
            flags[0] |= 2
            if flags[0] == 3:
                flags.pop(0)

        self.assertEqual(
            calls,
            [
                ("gcsv", 0),
                ("json", 0),
                ("gcsv", 0),
                ("json", 0),
                ("gcsv", 0),
                ("json", 0),
            ],
        )

        source = (HERE / "profilegen.S").read_text()
        self.assertIn("pg_post_next:", source)
        self.assertGreaterEqual(source.count("b       pg_post_next"), 3)
        self.assertIn("ldr     r0, [r10, #S_FILE]", source)
        self.assertNotIn("pg_post_find_gcsv", source)
        logger = (HERE / "logger.S").read_text()
        close = logger.index("bl      writer_close")
        self.assertIn("b       writer_idle", logger[close:close + 500])

    def test_native_movie_saving_lock_spans_the_whole_post_queue(self):
        """Every post-process exit releases the camera's real native gate."""

        source = (HERE / "profilegen.S").read_text()
        scheduler = source[source.index("pg_post_process:"):
                           source.index("#ifndef FPGYRO_NATIVE_LIFECYCLE")]
        acquire = scheduler.index("bl      pg_native_movie_saving_set")
        release = scheduler.rindex("bl      pg_native_movie_saving_set")

        self.assertLess(acquire, scheduler.index("pg_post_gcsv:"))
        self.assertLess(acquire, scheduler.index("pg_post_json_head:"))
        self.assertGreater(release, scheduler.index("pg_post_dequeue:"))
        self.assertEqual(scheduler.count("pop     {r4, r5, r6, r7, r8, pc}"), 1)
        self.assertNotIn("pop     {r4, r5, r6, pc}", scheduler)
        self.assertIn("b       pg_post_next", scheduler)

    def test_native_movie_saving_update_is_snapshot_based_and_owned(self):
        """The inhibitor uses the official notifier without raw global writes."""

        source = (HERE / "profilegen.S").read_text()
        helper = source[source.index("pg_native_movie_saving_set:"):
                        source.index("/* Queue scheduler entry")]

        self.assertIn(".equ F_SYS_STATUS_UPDATE80, 0xC0017CA0", source)
        self.assertIn(".equ SYS80_MOVIE_SAVING,    2", source)
        self.assertIn("mov     r3, #SYS80_WORDS", helper)
        self.assertIn("ldr_addr ip, F_SYS_STATUS_UPDATE80", helper)
        self.assertGreaterEqual(helper.count("ldr_addr ip, F_SYS_STATUS_SNAPSHOT"), 2)
        self.assertIn("cmp     r0, #0", helper)  # acquire only when unowned
        self.assertIn("cmp     r0, #1", helper)  # release only our value
        self.assertEqual(helper.count("strb    r0, [sp, #SYS80_MOVIE_SAVING]"), 2)
        self.assertNotIn("strb    r0, [sp, #SYS80_STILL_PROCESSING]", helper)
        self.assertNotIn("0xC3033834", helper)   # never write manager storage

    def test_native_movie_saving_does_not_depend_on_wait_encoding(self):
        """The core movie gate replaces r10/r11's UI event-state experiment."""

        source = (HERE / "profilegen.S").read_text()
        helper = source[source.index("pg_native_movie_saving_set:"):
                        source.index("/* Queue scheduler entry")]
        publish = helper.index("ldr_addr ip, F_SYS_STATUS_UPDATE80")
        owned = helper.index("strb    r0, [sp, #SYS80_MOVIE_SAVING]")

        self.assertLess(owned, publish)
        self.assertNotIn("F_WAIT_ENC", source)
        self.assertNotIn("F_SET_WAIT_ENC", source)
        self.assertNotIn("F_DO_WAIT_ENC", source)
        self.assertNotIn("F_EVENT_MSG_MGR", source)
        self.assertNotIn("EVENT_STATE_WAKE", source)

    def test_gcsv_card_pacing_survives_formatter_optimisation(self):
        """CPU formatting may change; v1.1's proven media pacing may not."""

        source = (HERE / "gcsvgen.S").read_text()
        flush_defs = source[source.index("#ifdef FPGYRO_GCSV_STREAM\n.equ TEXT_FLUSH"):
                            source.index(".equ ACC_VARS")]
        self.assertIn("#ifdef FPGYRO_GCSV_STREAM\n.equ TEXT_FLUSH,      0x10000",
                      flush_defs)
        self.assertIn("#else\n.equ TEXT_FLUSH,      0x10000", flush_defs)
        self.assertIn("#endif", flush_defs)
        flush = source[source.index("gcsv_flush:"):source.index("gcsv_get_head1:")]
        self.assertIn("mov     r0, #5", flush)

    def test_gcsv_only_stream_has_one_card_output_and_json_only_post_job(self):
        """The experiment replaces GYR; it must never silently become dual-write."""

        gcsv = (HERE / "gcsvgen.S").read_text()
        begin = gcsv.index("#ifdef FPGYRO_GCSV_STREAM\n/* Streaming command ABI")
        end = gcsv.index("#else\ngcsv_build:", begin)
        stream = gcsv[begin:end]
        self.assertIn("ldr_addr ip, F_WRITE", stream)
        self.assertNotIn("ldr_addr ip, F_READ", stream)
        self.assertNotIn("ldr_addr ip, F_SEEK", stream)
        self.assertIn("r0=2, r1=one sealed logger block", stream)

        logger = (HERE / "logger.S").read_text()
        enqueue = logger[logger.index("post_enqueue:"):
                         logger.index("hook_stand_down:")]
        self.assertIn("orr     r0, r0, #1", enqueue)
        self.assertIn("GCSV was closed before this job existed", enqueue)

    def test_streaming_formatter_is_bounded_and_off_the_callback(self):
        """Only the writer calls the pool formatter; RAM use is recording-length invariant."""

        logger = (HERE / "logger.S").read_text()
        callback = logger[logger.index("gyro_hook:"):logger.index("return_original:")]
        writer = logger[logger.index("writer_write_block:"):
                        logger.index("writer_sleep:")]
        self.assertNotIn("bl      gcsv_build", callback)
        self.assertIn("mov     r0, #2", writer)
        self.assertIn("bl      gcsv_build", writer)

        gcsv = (HERE / "gcsvgen.S").read_text()
        self.assertIn(".equ TEXT_FLUSH,      0x10000", gcsv)
        self.assertIn(".equ O_STREAM_STATE,  0x01A0", gcsv)
        self.assertIn(".equ ST_TEXT_N,       0x04", gcsv)

    def test_streaming_hot_path_caches_accel_and_skips_ephemeral_crc(self):
        """47 Hz accel text and a non-persisted block must not tax every row."""

        gcsv = (HERE / "gcsvgen.S").read_text()
        sample = gcsv[gcsv.index("gcsv_stream_sample:"):
                      gcsv.index("gcsv_stream_acc_tail:")]
        refresh = gcsv[gcsv.index("gcsv_stream_acc_refresh:"):
                       gcsv.index("gcsv_stream_block_done:")]
        self.assertEqual(sample.count("bl      put_i16"), 0)
        self.assertEqual(sample.count("bl      put_gyro3"), 1)
        self.assertEqual(refresh.count("bl      put_i16"), 3)
        self.assertIn("ST_ACC_TEXT", sample)
        self.assertIn("ST_ACC_DIRTY", sample)
        self.assertNotIn("sub     ip, ip, r11", sample)
        self.assertIn("normalising its private accel zone in place", gcsv)
        seeded = gcsv[gcsv.index("gcsv_stream_seeded:"):
                      gcsv.index("gcsv_stream_sample:")]
        self.assertLess(seeded.index("add     r7, r4, #BLOCK_HEADER"),
                        seeded.index("mov     r4, r3"))

        logger = (HERE / "logger.S").read_text()
        writer = logger[logger.index("writer_write_block:"):
                        logger.index("writer_block_out:")]
        stream_skip = writer[writer.index("#ifdef FPGYRO_GCSV_STREAM"):
                             writer.index("#endif", writer.index("#ifdef FPGYRO_GCSV_STREAM"))]
        self.assertIn("ldr     r7, [r5, #4]", stream_skip)   # seal-time drop count rides in the CRC word
        self.assertNotIn("bl      crc32", stream_skip.split("#else")[0])

    def test_fused_gyro_lookup_uses_native_x_y_pad_z_layout_safely(self):
        """The hot formatter may share its table, but never reinterpret the pad."""

        source = (HERE / "gcsvgen.S").read_text()
        fused = source[source.index("put_gyro3:"):source.index("put_i16:")]
        self.assertIn("push    {r4, r5, r6, r7, r8, lr}", fused)
        self.assertIn("adr     r6, dec_quads", fused)
        self.assertEqual(fused.count("adr     r6, dec_quads"), 1)
        self.assertNotIn("umull", fused)
        self.assertNotIn("mls", fused)
        self.assertNotIn("bl ", fused)
        self.assertIn("addeq   r4, r4, #2", fused)
        self.assertIn("strb    ip, [r5], #1", fused)

        # Mirror the pointer advance after each completed axis.  The second
        # advance skips the record pad, producing native byte offsets 0, 2, 6.
        offset = 0
        left = 3
        seen = []
        while left:
            seen.append(offset)
            left -= 1
            if not left:
                break
            offset += 2
            if left == 1:
                offset += 2
        self.assertEqual(seen, [0, 2, 6])

    def test_accel_text_unroll_keeps_destination_bytewise_and_tail_exact(self):
        """Four-byte source reads never become unsafe unaligned word stores."""

        source = (HERE / "gcsvgen.S").read_text()
        copy = source[source.index("gcsv_stream_acc_ready:"):
                      source.index("gcsv_stream_acc_tail:")]
        self.assertIn("ldr     r0, [r1], #4", copy)
        self.assertNotIn("str     r0, [r5]", copy)
        self.assertIn("cmp     r2, #4", copy)
        self.assertIn("cmp     r2, #0", copy)
        self.assertIn("gcsv_stream_acc_text_copy1:", copy)

        # O_STREAM_STATE + ST_ACC_TEXT is aligned for the only word access.
        self.assertEqual((0x01A0 + 0x1C) % 4, 0)

        # Model every possible cached-fragment length, including a defensive
        # zero and the 19-byte signed triple maximum.
        cached = bytes(range(24))
        for length in range(20):
            src = 0
            left = length
            output = bytearray()
            while left >= 4:
                output.extend(cached[src:src + 4])
                src += 4
                left -= 4
            while left:
                output.append(cached[src])
                src += 1
                left -= 1
            self.assertEqual(output, cached[:length], length)

    def test_native_movie_saving_gate_refuses_other_capture_owners(self):
        """Acquire refuses every native state used by the power-off waiter."""

        source = (HERE / "profilegen.S").read_text()
        helper = source[source.index("pg_native_movie_saving_set:"):
                        source.index("/* Queue scheduler entry")]
        for field in (
            "SYS80_STILL_EXPOSING",
            "SYS80_STILL_SAVING",
            "SYS80_MOVIE_SAVING",
            "SYS80_STILL_PROCESSING",
            "SYS80_CAPTURE_AUX",
            "SYS80_MOVIE_RECORDING",
        ):
            self.assertIn(f"[sp, #{field}]", helper)

class ImageLayoutTests(unittest.TestCase):
    """From gyro/test_safety.py."""
    def _cave_base(self):
        return self._load_const("CAVE_BASE")

    def _payload_base(self):
        """Where an image placed over USB starts, which is above the loader."""
        return self._load_const("CAVE_BASE") + 0x200

    def _load_const(self, name):
        import re
        source = (ROOT / "fp_usb_shell" / "load.py").read_text()
        m = re.search(rf"^{name} = (0x[0-9A-Fa-f]+)", source, re.M)
        if not m:
            raise AssertionError(f"load.py has no {name}")
        return int(m.group(1), 0)

    def test_logger_ends_before_parking_stub(self):
        logger = assemble(HERE / "logger.S")
        park = assemble(ROOT / "fp_usb_shell" / "templates" / "park.S")
        park_at = 0xC072EFB4
        cave_end = 0xC072F000
        self.assertLessEqual(self._payload_base() + len(logger), park_at)
        self.assertLessEqual(park_at + len(park), cave_end)

    def test_stream_logger_ends_before_parking_stub(self):
        logger = assemble(HERE / "logger_stream.S")
        conservative_end = 0xC072EF00
        park_at = 0xC072EFB4
        self.assertLessEqual(self._payload_base() + len(logger), conservative_end)
        self.assertLessEqual(self._payload_base() + len(logger), park_at)

    def test_the_autorun_arms_the_loader_only_after_writing_it(self):
        """The order the AutoRun writes things in, which has no second chance.

        The loader is spelled out one `mem set` per word and then called by
        pointing the `echo` handler at it and saying `echo`.  Two orderings
        brick the boot with nothing printed: arming before the last word is
        written calls a half-written routine, and any `mem set` after `echo`
        races the loader, which by then is placing sections and may already
        have branched into what it placed.

        This replaced a bootstrap in the gyro callback, where the ordering was
        genuinely unenforceable -- the callback fired whenever it liked, which
        is why that path needed a run-once word and an early restore.  Called
        from `echo` the order is the AutoRun's own, so it can be checked here.
        """
        import subprocess, tempfile, re as _re
        shell = ROOT / "fp_usb_shell"
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "AutoRun.txt"
            r = subprocess.run([sys.executable, "build_autorun.py", "--loader",
                                "--out", str(out)],
                               cwd=shell, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            cmds = [l.strip() for l in out.read_text().splitlines()
                    if l.strip() and not l.startswith("#")]

        src = (shell / "build_autorun.py").read_text()
        def const(name):
            m = _re.search(r"^%s\s*= (0x[0-9A-Fa-f]+)" % name, src, _re.M)
            self.assertIsNotNone(m, "%s is gone from build_autorun.py" % name)
            return int(m.group(1), 0)
        slot, orig, hook = const("ECHO_SLOT"), const("ECHO_ORIG"), const("HOOK")

        sets = [(i, int(m.group(1), 16), int(m.group(2), 16))
                for i, l in enumerate(cmds)
                for m in [_re.match(r"mem set (0x[0-9A-Fa-f]+) (0x[0-9A-Fa-f]+)$", l)]
                if m]
        echoes = [i for i, l in enumerate(cmds) if l == "echo"]
        self.assertEqual(len(echoes), 1, "the loader is called exactly once")
        e = echoes[0]

        arm = [(i, v) for i, a, v in sets if a == slot and v != orig]
        self.assertEqual(len(arm), 1, "the handler is armed exactly once")
        self.assertLess(arm[0][0], e, "armed before `echo`")

        boot = arm[0][1]
        body = [i for i, a, v in sets if boot <= a < boot + 0x400]
        self.assertTrue(body, "no loader words written at the armed address")
        self.assertLess(max(body), arm[0][0],
                        "a loader word is written after the handler is armed")

        after = [(a, v) for i, a, v in sets if i > e]
        self.assertTrue(all(a == slot for a, v in after),
                        "a `mem set` after `echo` races the loader: %r" % (after,))
        self.assertTrue(all(v == orig for a, v in after), "restores put the shell back")
        self.assertGreaterEqual(len(after), 3, "`mem set` drops; restore more than once")

        self.assertFalse([1 for i, a, v in sets if a == hook],
                         "the shell writes the gyro callback again -- it is the "
                         "logger's alone since the bootstrap moved to `echo`")

    def test_stream_probe_logger_ends_before_parking_stub(self):
        logger = assemble(HERE / "logger_stream_probe.S")
        park_at = 0xC072EFB4
        self.assertLessEqual(self._payload_base() + len(logger), park_at)

    def test_stream_pgen_fits_the_loader_window(self):
        defines = ("FPGYRO_NATIVE_LIFECYCLE", "FPGYRO_GCSV_STREAM")
        profile = assemble(HERE / "profilegen.S", defines)
        profile += b"\0" * (-len(profile) % 4)
        gcsv = assemble(HERE / "gcsvgen.S", defines)
        self.assertLessEqual(len(profile) + len(gcsv), 0x10000)

        probe_defines = defines + ("FPGYRO_BACKPRESSURE_PROBE",)
        profile = assemble(HERE / "profilegen.S", probe_defines)
        profile += b"\0" * (-len(profile) % 4)
        gcsv = assemble(HERE / "gcsvgen.S", probe_defines)
        self.assertLessEqual(len(profile) + len(gcsv), 0x10000)

    def test_the_streaming_slots_are_read_from_the_source_not_recited(self):
        """The slot layout, taken from gcsvgen.S rather than copied here.

        This test used to spell the geometry out as its own arithmetic --
        0x1000 / 0x30000 / 0x38000, 32 KiB each -- and check that those numbers
        agreed with each other.  They did, for two weeks after the source had
        moved to 0x81000 / 0xA1000 / 0xC1000 at 128 KiB, because nothing tied
        the two together: the test was consistent with itself and describing a
        layout that no longer existed.  Reading the values out of the source is
        the only version of this test that cannot drift.

        The overlap and bounds checks are gcsvgen.S's own .error directives now
        (a bad layout fails to assemble, which is stronger than failing here),
        so what is left for this test is that those guards are present and that
        the capacities still cover a slot's worth of time.
        """
        gcsv = (HERE / "gcsvgen.S").read_text()

        def equ(name):
            m = re.search(r"^\.equ %s,\s*(0x[0-9A-Fa-f]+|\d+)" % name,
                          gcsv, re.M)
            self.assertIsNotNone(m, "%s is gone from gcsvgen.S" % name)
            return int(m.group(1), 0)

        buf_size = equ("BUF_SIZE")
        gyro_cap = equ("GYRO_CAP")
        sample_cap = equ("GYRO_SAMPLE_CAP")
        accel_zone = equ("ACCEL_ZONE")
        accel_base = equ("ACCEL_BASE")
        accel_cap = equ("ACCEL_REC_CAP")
        accel_rec = equ("ACCEL_REC")

        self.assertEqual(gyro_cap // 8, sample_cap)
        self.assertEqual(accel_base + accel_zone, buf_size)
        self.assertLessEqual(accel_cap * accel_rec, accel_zone)

        seconds_per_slot = sample_cap / 2500.0
        self.assertGreater(seconds_per_slot, 3.0)
        self.assertGreaterEqual(accel_cap, seconds_per_slot * 100)

        for guard in (".if O_BUF_A < 0x81000",
                      ".if (O_BUF_C + BUF_SIZE) > 0xF8800",
                      ".if (O_BUF_A + BUF_SIZE) > O_BUF_B",
                      ".if (O_BUF_B + BUF_SIZE) > O_BUF_C",
                      ".if (ACCEL_BASE + ACCEL_ZONE) != BUF_SIZE"):
            self.assertIn(guard, gcsv)

    def test_streaming_source_uses_three_slot_ordered_queue(self):
        source = (HERE / "logger.S").read_text()
        producer = source[source.index("drain_ring:"):
                          source.index("recording_stopped:")]
        writer = source[source.index("writer_check_blocks:"):
                        source.index("writer_no_blocks:")]

        self.assertIn("producer_slot_buffer_offsets:", source)
        self.assertIn("writer_slot_buffer_offsets:", source)
        self.assertIn(".word   O_BUF_A, O_BUF_B, O_BUF_C", source)
        self.assertIn(".word   S_A_STATE, S_B_STATE, S_C_STATE", source)
        self.assertIn("ldr     r2, [r10, #S_INDEX]", producer)
        self.assertIn("cmp     ip, #SLOT_COUNT", producer)
        self.assertIn("cmp     ip, r2", producer)
        self.assertIn("b       drop_batch", producer)

        self.assertIn("ldr     r0, [r5, #16]", writer)
        self.assertIn("cmp     r6, #SLOT_COUNT", writer)
        self.assertIn("cmp     r0, r7", writer)

    def test_backpressure_probe_stays_ram_only_until_existing_json(self):
        logger = (HERE / "logger.S").read_text()
        gcsv = (HERE / "gcsvgen.S").read_text()
        profile = (HERE / "profilegen.S").read_text()

        self.assertIn(".equ O_BP_DIAG,       0x40000", logger)
        self.assertIn("BP_DROP_WRITE", logger)
        self.assertIn("#ifdef FPGYRO_BACKPRESSURE_PROBE", logger)
        self.assertIn("bp_drop_offsets:", logger)
        self.assertIn("logger_stream_probe.S", (HERE / "build_card.py").read_text())
        self.assertIn("backpressure_probe", (HERE / "build_pgen.py").read_text())
        probe = profile[profile.index("#ifdef FPGYRO_BACKPRESSURE_PROBE"):
                        profile.index("#endif", profile.index(
                            "#ifdef FPGYRO_BACKPRESSURE_PROBE"))]
        self.assertIn("fpgyrosup_backpressure", probe)
        self.assertNotIn("open_file", probe)
        self.assertIn("BP_FLUSH_CUR", gcsv)
        self.assertIn("BP_PHASE", gcsv)

    def test_pgen_header_points_to_both_valid_entries(self):
        profile = assemble(HERE / "profilegen.S")
        profile += b"\0" * (-len(profile) % 4)
        gcsv = assemble(HERE / "gcsvgen.S")
        post = symbols(HERE / "profilegen.S")["pg_post_process"]
        gcsv_entry = len(profile) + symbols(HERE / "gcsvgen.S")["gcsv_build"]
        code = profile + gcsv
        blob = struct.pack("<4sIII", b"PGEN", post, gcsv_entry, len(code)) + code

        magic, post_off, gcsv_off, size = struct.unpack_from("<4sIII", blob)
        self.assertEqual(magic, b"PGEN")
        self.assertEqual(size, len(blob) - 16)
        self.assertLess(post_off, size)
        self.assertLess(gcsv_off, size)
        self.assertLessEqual(size, 0x10000)

class LifecycleStateTests(unittest.TestCase):
    """From gyro/test_lifecycle.py."""
    def test_assembly_adapter_is_ram_only_except_volume_lookup(self):
        source = (HERE / "lifecycle.inc.S").read_text()
        self.assertIn("XMP_FOBJ_PTR", source)
        self.assertIn("MOV_ACTIVE_PTR", source)
        self.assertIn("MOV_PATHINFO_PTR", source)
        self.assertIn("pg_cdng_committed", source)
        self.assertNotIn("F_OPEN", source)
        self.assertNotIn("F_WRITE", source)
        self.assertNotIn("F_DIR_", source)
        self.assertEqual(source.count("bl      pg_current_volume"), 4)
        self.assertEqual(source.count("bl      pg_lc_mov_still_same"), 2)
        self.assertIn("cmp     r0, r8", source)
        self.assertIn("cmp     r0, r7", source)
        cdng = source.index("pg_lc_publish_cdng:")
        mov = source.index("pg_lc_publish_mov:")
        self.assertLess(
            source.index("mov     r0, #6", cdng),
            source.index("bl      pg_current_volume", cdng),
        )
        self.assertLess(
            source.index("mov     r0, #6", mov),
            source.index("bl      pg_current_volume", mov),
        )

    def test_logger_connects_all_native_states_to_the_writer(self):
        source = (HERE / "logger.S").read_text()
        self.assertIn("cmp     r7, #1", source)
        self.assertTrue("cmp     r7, #4" in source or "cmpne   r7, #4" in source)  # phase 4 accepted (r38e folds it into cmpne)
        self.assertIn("recording_attach_claim:", source)
        self.assertIn("O_LC_GEN", source)
        self.assertIn("O_LC_ATTACH", source)
        acquire = source.index("recording_attach_valid:")
        recheck = source.index("ldr     r0, [r10, #O_LC_GEN]", acquire)
        self.assertIn("dmb     ish", source[acquire:recheck])
        self.assertNotRegex(source.lower(), r"(?m)^\s*(?:ldrex|strex|clrex)\s")
        self.assertIn("cmp     r0, #4                  @ never create", source)
        self.assertIn("cmp     r0, #1                  @ pending CDNG", source)
        self.assertIn("cmp     r2, #0x200", source)
        # Native events publish the descriptor, but the proven recording flag
        # remains the start gate. XMP allocation alone must not open a GYR.
        native = source.index("native_clip_checked:")
        inactive = source.index("recording_not_active:", native)
        file_check = source.index("ldr     r0, [r10, #S_FILE]", inactive)
        self.assertIn("cmp     r1, #0x21", source[native:inactive])
        self.assertIn("ldrb    r5, [r0]", source[native:inactive])
        self.assertIn("cmp     r5, #0", source[inactive:file_check])
        self.assertIn("beq     return_original", source[inactive:file_check])
        adapter = (HERE / "lifecycle.inc.S").read_text()
        self.assertIn("mov     r0, #6", adapter)
        self.assertIn("pg_lc_publish_cancel:", adapter)
        self.assertIn("O_LC_GEN", adapter)
        self.assertNotRegex(adapter.lower(), r"(?m)^\s*(?:ldrex|strex|clrex)\s")

class DecodeHeaderVersions(unittest.TestCase):
    """From gyro/test_decode_v5.py."""

    def read(self, payload: bytes):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.GYR"
            path.write_bytes(payload)
            return decode.read_capture(path)
    def test_phase_probe_decodes_first_four_and_ordered_rolling_tail(self):
        # Ten writes leave #1..#4 in slots 0..3.  The rolling tail #7..#10 is
        # in slots 6,7,4,5 respectively.
        slots = [(0, 0)] * 8
        for zero_based in range(10):
            slot = zero_based if zero_based < 4 else 4 + ((zero_based - 4) & 3)
            busy = zero_based in (2, 7)
            slots[slot] = ((zero_based + 1) | (0x80000000 if busy else 0),
                           1000 + zero_based)
        record = bytearray(struct.pack("<4sI", b"GFT6", 10))
        for pair in slots:
            record += struct.pack("<II", *pair)
        capture = self.read(capture_bytes(5, phase_record=bytes(record)))
        self.assertEqual(capture.phase_write_count, 10)
        self.assertEqual([sample.write_number for sample in capture.phase_trace],
                         [1, 2, 3, 4, 7, 8, 9, 10])
        self.assertTrue(capture.phase_trace[2].dng_busy)
        self.assertTrue(capture.phase_trace[5].dng_busy)
        self.assertEqual(capture.phase_trace[-1].duration_us, 1009)


class ProfilegenSource(unittest.TestCase):
    """From gyro/test_distfit.py.  pg_dist_prepare is the PGEN
    generator's camera-matrix emitter; the blob writes its json in
    gcsv_json.S instead, and has no test of this shape."""

    def source(self):
        import pathlib
        return (HERE / 'profilegen.S').read_text()

    def test_both_camera_matrix_focals_come_from_r8(self):
        src = self.source()
        i = src.index('bl      pg_dist_prepare')
        after = src[i:src.index('"], [0.0, 0.0, 1.0]],', i)]
        # every pg_em that emits a focal must be fed from r8
        emits = [m for m in after.split('bl      pg_em')[:-1]]
        self.assertGreaterEqual(len(emits), 2)
        for n, chunk in enumerate((emits[0], emits[2] if len(emits) > 2 else emits[1])):
            self.assertIn('mov     r0, r8', chunk,
                          f'camera_matrix focal {n} is not fed from r8')

    def test_distortion_coefficients_are_not_hardcoded(self):
        self.assertNotIn('"distortion_coeffs\\": [0.0, 0.0, 0.0, 0.0]', self.source())
        self.assertIn('bl      pg_dist_emit', self.source())


if __name__ == "__main__":
    unittest.main()
