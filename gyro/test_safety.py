#!/usr/bin/env python3
"""Host-side safety checks for the resident logger image.

These do not emulate the camera.  They protect the properties that caused
the field freeze: the stop publication must be followed by a READY rescan, and
the logger/PGEN images must remain inside their fixed RAM regions.
"""

from __future__ import annotations

import itertools
import struct
import sys
import pathlib
import re
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "fp_usb_shell"))

from armasm import assemble, symbols  # noqa: E402


class StopRaceTests(unittest.TestCase):
    def test_stop_rescan_never_closes_over_late_ready(self):
        """Enumerate every ordering of callback publication and writer scan."""

        producer = ("publish_ready", "publish_stop")
        writer = ("scan", "observe_stop_and_rescan")

        for order in itertools.permutations(producer + writer):
            if [x for x in order if x in producer] != list(producer):
                continue
            if [x for x in order if x in writer] != list(writer):
                continue

            ready = stop = scanned_ready = closed = False
            for event in order:
                if event == "publish_ready":
                    ready = True
                elif event == "publish_stop":
                    stop = True
                elif event == "scan":
                    scanned_ready = ready
                    if scanned_ready:
                        ready = False  # writer drains it
                elif stop:
                    # The revised writer acquires STOP and rescans READY here.
                    if ready:
                        ready = False
                    else:
                        closed = True

            self.assertFalse(closed and ready, order)

    def test_three_slot_producer_claims_only_empty_or_drops(self):
        """Exhaust every state combination around the producer's ring walk."""

        empty, filling, ready, writing = range(4)
        for current in range(3):
            others = ((current + 1) % 3, (current + 2) % 3)
            for states_tail in itertools.product(range(4), repeat=2):
                states = [ready, ready, ready]
                states[current] = ready  # the producer has just sealed it
                for slot, state in zip(others, states_tail):
                    states[slot] = state

                claimed = next((slot for slot in others
                                if states[slot] == empty), None)
                dropped = claimed is None

                if dropped:
                    self.assertNotIn(empty, (states[others[0]],
                                             states[others[1]]))
                else:
                    self.assertEqual(states[claimed], empty)
                    states[claimed] = filling
                    self.assertEqual(sum(state == filling for state in states),
                                     states_tail.count(filling) + 1)

    def test_three_slot_writer_always_consumes_lowest_ready_sequence(self):
        """Physical ring position cannot reorder published sample blocks."""

        empty, filling, ready, writing = range(4)
        del empty, filling, writing
        sequences = (11, 7, 19)
        for states in itertools.product(range(4), repeat=3):
            candidates = [i for i, state in enumerate(states)
                          if state == ready]
            chosen = min(candidates, key=sequences.__getitem__) \
                if candidates else None
            if candidates:
                self.assertEqual(sequences[chosen],
                                 min(sequences[i] for i in candidates))
            else:
                self.assertIsNone(chosen)

    def test_head_take_finishes_before_next_take_starts(self):
        """GYR/GCSV/JSON form one transaction in queue order."""

        flags = [0b01, 0b00, 0b00, 0b01]
        # The head already has GCSV, so JSON for that same take is next even
        # though later takes still need their GCSV.
        self.assertEqual("json" if flags[0] & 1 else "gcsv", "json")

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

    def test_json_path_is_rebuilt_from_each_queued_job(self):
        """GCSV-first order must not send an older JSON to a later clip."""

        def json_path(gyro_path: bytes) -> bytes:
            clip = gyro_path[6:14]
            return b"\\CINEMA\\" + clip + b"\\" + clip + b".json"

        self.assertEqual(
            json_path(b"\\GYRO\\A001_021.GYR\0"),
            b"\\CINEMA\\A001_021\\A001_021.json",
        )
        self.assertEqual(
            json_path(b"\\GYRO\\A001_030.GYR\0"),
            b"\\CINEMA\\A001_030\\A001_030.json",
        )

    def test_quick_restart_boundary_is_debounced_and_armed(self):
        """Only a sustained zero after live geometry may split a take."""

        active, counter = 1, 0

        def poll(width):
            nonlocal active, counter
            if active == 2:
                if width:
                    active = 0
                return
            if active != 1:
                return
            if width:
                counter = 1
            elif counter:
                counter += 1
                if counter >= 21:
                    active = 3

        # The geometry may still be zero just after the record flag rises.
        for _ in range(40):
            poll(0)
        self.assertEqual((active, counter), (1, 0))

        poll(1920)
        for _ in range(19):
            poll(0)
        self.assertEqual(active, 1)
        poll(0)
        self.assertEqual(active, 3)

        # The callback seals 3 -> 2; the writer releases it only when the next
        # clip's real geometry appears.
        active = 2
        poll(0)
        self.assertEqual(active, 2)
        poll(1920)
        self.assertEqual(active, 0)

    def test_transient_geometry_zero_does_not_split(self):
        counter = 1
        for width in [0] * 8 + [1920] + [0] * 8:
            counter = 1 if width else counter + 1
        self.assertLess(counter, 21)


class ImageLayoutTests(unittest.TestCase):
    def test_queue_fits_header_tail_exactly(self):
        queue_at = 0x2A0
        metadata = 0x10
        jobs = 7 * 0x30
        file_object_at = 0x400
        self.assertEqual(queue_at + metadata + jobs, file_object_at)

    # These check the images load.sh places over USB, which start at load.py's
    # CAVE_BASE.  They used to spell that base as 0xC072E064 -- which is
    # build_base_card.py's ENTRY_AT, where the VSHL *card* image starts, 512
    # bytes higher.  Two different images, two different bases, one constant
    # copied between them: the tests went red the week logger.S grew past the
    # margin that 512-byte error had eaten, and stayed red reading like a real
    # overrun.  Both bases are read from their own build script now.

    def _cave_base(self):
        source = (ROOT / "fp_usb_shell" / "load.py").read_text()
        m = re.search(r"^CAVE_BASE = (0x[0-9A-Fa-f]+)", source, re.M)
        self.assertIsNotNone(m, "CAVE_BASE is gone from load.py")
        return int(m.group(1), 0)

    def test_logger_ends_before_parking_stub(self):
        logger = assemble(HERE / "logger.S")
        park = assemble(ROOT / "fp_usb_shell" / "templates" / "park.S")
        park_at = 0xC072EFB4
        cave_end = 0xC072F000
        self.assertLessEqual(self._cave_base() + len(logger), park_at)
        self.assertLessEqual(park_at + len(park), cave_end)

    def test_stream_logger_ends_before_parking_stub(self):
        logger = assemble(HERE / "logger_stream.S")
        conservative_end = 0xC072EF00
        park_at = 0xC072EFB4
        self.assertLessEqual(self._cave_base() + len(logger), conservative_end)
        self.assertLessEqual(self._cave_base() + len(logger), park_at)

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

    def test_the_pool_blob_offset_agrees_everywhere_it_is_written(self):
        """0x44000 is written down twice and assembly cannot see across files.

        ring_task_deploy.py tells stage2 where to put the writer blob;
        gsup_entry.S, forty bytes in the cave, adds the same offset to the pool
        base to find it again.  If one moves, gsup_entry reads a word out of
        whatever is at the old offset instead of the routine table -- and its
        only guard is that the word is exactly zero, so anything else becomes
        a blx into garbage.
        """
        deploy = (HERE / "ring_task_deploy.py").read_text()
        entry = (HERE / "gsup_entry.S").read_text()
        m = re.search(r"^CODE_POOL_OFF = (0x[0-9A-Fa-f]+)", deploy, re.M)
        n = re.search(r"^\.equ CODE_POOL_OFF,\s*(0x[0-9A-Fa-f]+)", entry, re.M)
        self.assertIsNotNone(m, "CODE_POOL_OFF is gone from ring_task_deploy.py")
        self.assertIsNotNone(n, "CODE_POOL_OFF is gone from gsup_entry.S")
        self.assertEqual(int(m.group(1), 0), int(n.group(1), 0))

    def test_the_pool_blob_clears_the_loader_read_window(self):
        """stage2 runs from the loader's read buffer and reads the remaining
        sections out of it, so a pool section landing there overwrites itself
        mid-copy -- a boot freeze with nothing printed.  build_base_card.check
        enforces this; that it is enforced at all is what is asserted here."""
        import build_base_card
        lo, hi = build_base_card.loader_window()
        deploy = (HERE / "ring_task_deploy.py").read_text()
        blob = int(re.search(r"^CODE_POOL_OFF = (0x[0-9A-Fa-f]+)",
                             deploy, re.M).group(1), 0)
        self.assertGreaterEqual(blob, hi)

        secs = build_base_card.sections("gcsv")
        pool = [(a, a + len(b), w) for a, b, w in secs if a < 0x40000000]
        self.assertTrue(pool, "no pool-relative section: this test has nothing "
                              "left to guard and should be re-examined")
        for a, b, w in pool:
            self.assertFalse(a < hi and lo < b,
                             "%s at pool+0x%X..0x%X is in the window" % (w, a, b))

        moved = [(lo if a < 0x40000000 else a, b, w) for a, b, w in secs]
        with self.assertRaises(SystemExit):
            build_base_card.check(moved)

    def test_the_card_image_starts_above_the_loader(self):
        """ENTRY_AT is not CAVE_BASE -- what the two tests above got wrong.

        The gap is what the loader needs to not be overwritten by the image it
        just placed.  Asserted as "big enough", not as its present value: 0x200
        is a round number someone chose with margin, and the loader assembles
        to 396 bytes at its largest, so pinning the constant would fail a
        legitimate tightening of it.  What must never happen is the image
        starting inside the running loader.
        """
        card = (HERE / "build_base_card.py").read_text()
        m = re.search(r"^ENTRY_AT = (0x[0-9A-Fa-f]+)", card, re.M)
        self.assertIsNotNone(m)
        entry_at = int(m.group(1), 0)
        loader = assemble(ROOT / "fp_usb_shell" / "templates" / "loader.S",
                          ("LOADER_BASE=0x%X" % self._cave_base(),))
        self.assertGreaterEqual(entry_at - self._cave_base(), len(loader))

    def test_stream_probe_logger_ends_before_parking_stub(self):
        logger = assemble(HERE / "logger_stream_probe.S")
        load_at = 0xC072E064
        park_at = 0xC072EFB4
        self.assertLessEqual(load_at + len(logger), park_at)

    def test_the_shipping_build_guards_the_park_stub_itself(self):
        source = (HERE / "build_base_card.py").read_text()
        self.assertIn("PARK_AT = 0xC072EFB4", source)
        self.assertIn("if hi > PARK_AT:", source)

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

    def test_stream_state_and_32k_text_chunk_have_guard_space(self):
        stream_state = 0x01A0
        stream_state_last_word = 0x40
        header = 0x0200
        text = 0x1A000
        flush = 0x10000
        max_line_slop = 64
        next_region = 0x5B000

        self.assertLessEqual(stream_state + stream_state_last_word + 4, header)
        self.assertLessEqual(text + flush + max_line_slop, next_region)

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


if __name__ == "__main__":
    unittest.main()
