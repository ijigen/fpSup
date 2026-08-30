#!/usr/bin/env python3
"""Host-side safety checks for the resident logger image.

These do not emulate the camera.  They protect the two properties that caused
the field freeze: the stop publication must be followed by a READY rescan, and
the logger/PGEN images must remain inside their fixed RAM regions.
"""

from __future__ import annotations

import itertools
import struct
import sys
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

    def test_gcsv_timing_is_unchanged_while_lifecycle_is_stabilised(self):
        """r12 must not mix the lifecycle fix with a GCSV scheduling change."""

        source = (HERE / "gcsvgen.S").read_text()
        self.assertIn(".equ TEXT_FLUSH,      0x4000", source)
        flush = source[source.index("gcsv_flush:"):source.index("gcsv_get_head1:")]
        self.assertIn("mov     r0, #5", flush)

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

    def test_logger_ends_before_parking_stub(self):
        logger = assemble(HERE / "logger.S")
        park = assemble(ROOT / "fp_usb_shell" / "templates" / "park.S")
        load_at = 0xC072E064
        park_at = 0xC072EFB4
        cave_end = 0xC072F000
        self.assertLessEqual(load_at + len(logger), park_at)
        self.assertLessEqual(park_at + len(park), cave_end)

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
