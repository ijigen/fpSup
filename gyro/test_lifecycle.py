#!/usr/bin/env python3
"""State-model and source invariants for the native clip adapters."""

from __future__ import annotations

import itertools
import unittest
from dataclasses import dataclass
from pathlib import Path


HERE = Path(__file__).resolve().parent


@dataclass
class Lifecycle:
    state: int = 0
    generation: int = 0
    attached_generation: int = 0
    kind: int = 0
    volume: int = 0
    top_hash: int = 0
    candidate_hash: int = 0
    opening_polls: int = 0
    take: int = 0
    commit_polls: int = 0

    def cdng_open(self, volume: int, take: int, old_top_hash: int) -> None:
        self.kind, self.volume, self.take = 1, volume, take
        self.top_hash = old_top_hash
        self.candidate_hash = self.opening_polls = self.commit_polls = 0
        self.generation += 1
        self.state = 1

    def callback_attach(self) -> None:
        if self.state in (1, 4):
            self.attached_generation = self.generation

    @property
    def writer_ready(self) -> bool:
        return (
            self.state == 4
            and self.attached_generation == self.generation
        )

    def cdng_top_poll(self, value: int, identity_matches: bool = True) -> None:
        if value == self.top_hash:
            self.candidate_hash = 0
            if self.state == 1:
                self.opening_polls += 1
                if self.opening_polls >= 400:
                    self.state = 3
            return
        if self.candidate_hash != value:
            self.candidate_hash = value
            return
        if self.state == 1 and identity_matches:
            self.top_hash = value
            self.state = 4
            self.candidate_hash = self.opening_polls = 0
        else:
            self.state = 3

    def cdng_closed(self, committed_take: int) -> None:
        if self.state == 1:
            self.state = 3
            return
        self.commit_polls += 1
        if committed_take >= self.take and self.commit_polls >= 2:
            self.state = 3
        elif self.commit_polls >= 400:
            self.state = 3

    def mov_open(self, volume: int) -> None:
        self.generation += 1
        self.kind, self.volume, self.state = 2, volume, 4

    def mov_closed(self) -> None:
        self.state = 3


class LifecycleStateTests(unittest.TestCase):
    def test_cdng_file_waits_for_stable_first_dng(self):
        lc = Lifecycle()
        lc.cdng_open(1, 38, 100)
        lc.callback_attach()
        self.assertEqual(lc.state, 1)  # samples may buffer; writer must not open
        self.assertFalse(lc.writer_ready)
        lc.cdng_top_poll(200)
        self.assertEqual(lc.state, 1)
        lc.cdng_top_poll(200)
        self.assertEqual(lc.state, 4)
        self.assertTrue(lc.writer_ready)

    def test_failed_xmp_allocation_is_bounded(self):
        lc = Lifecycle()
        lc.cdng_open(1, 38, 100)
        lc.callback_attach()
        for _ in range(400):
            lc.cdng_top_poll(100)
        self.assertEqual(lc.state, 3)

    def test_cdng_waits_for_catalog_commit_without_one_second_gap(self):
        lc = Lifecycle()
        lc.cdng_open(5, 38, 100)
        lc.callback_attach()
        lc.cdng_top_poll(200)
        lc.cdng_top_poll(200)
        lc.cdng_closed(37)
        self.assertEqual(lc.state, 4)
        lc.cdng_closed(38)
        self.assertEqual(lc.state, 3)  # second 5 ms observation, not a blind delay

    def test_stable_topfile_change_splits_missed_quick_restart(self):
        lc = Lifecycle(
            state=4,
            generation=3,
            attached_generation=3,
            kind=1,
            volume=1,
            top_hash=100,
            take=37,
        )
        lc.cdng_top_poll(200)
        self.assertEqual(lc.state, 4)
        lc.cdng_top_poll(200)
        self.assertEqual(lc.state, 3)

    def test_mov_uses_same_core_states_and_latched_ssd(self):
        lc = Lifecycle()
        lc.mov_open(5)
        lc.callback_attach()
        self.assertEqual((lc.state, lc.kind, lc.volume), (4, 2, 5))
        self.assertTrue(lc.writer_ready)
        lc.mov_closed()
        self.assertEqual(lc.state, 3)

    def test_stale_attachment_cannot_open_a_new_generation(self):
        lc = Lifecycle()
        lc.mov_open(1)
        lc.callback_attach()
        self.assertTrue(lc.writer_ready)
        lc.mov_closed()
        lc.mov_open(5)
        self.assertFalse(lc.writer_ready)
        lc.callback_attach()
        self.assertTrue(lc.writer_ready)

    def test_publish_attach_handshake_has_no_mixed_generation(self):
        """Enumerate the old-final/new-publish race under SC+DMB ordering."""

        callback = (
            "c_read",
            "c_claim",
            "c_gen",
            "c_state",
            "c_gen_recheck",
            "c_commit",
        )
        publisher = ("p_final", "p_check", "p_intent", "p_commit")

        total = len(callback) + len(publisher)
        for callback_slots in itertools.combinations(range(total), len(callback)):
            callback_slots = set(callback_slots)
            ci = pi = 0
            merged = []
            for slot in range(total):
                if slot in callback_slots:
                    merged.append(callback[ci])
                    ci += 1
                else:
                    merged.append(publisher[pi])
                    pi += 1
            order = tuple(merged)

            state, file_state, generation = 4, 0, 1
            candidate = latched_generation = None
            state_valid = generation_valid = False
            publisher_active = published = attached = False

            for event in order:
                if event == "c_read":
                    candidate = state if state in (1, 4) else None
                elif event == "c_claim" and candidate is not None:
                    file_state = 4
                elif event == "c_gen" and candidate is not None:
                    latched_generation = generation
                elif event == "c_state" and candidate is not None:
                    state_valid = state in (1, 4)
                elif event == "c_gen_recheck" and candidate is not None:
                    generation_valid = latched_generation == generation
                elif event == "c_commit" and candidate is not None:
                    if state_valid and generation_valid:
                        attached = True
                        file_state = 1
                    else:
                        file_state = 0
                elif event == "p_final":
                    state = 3
                elif event == "p_check":
                    publisher_active = file_state == 0
                elif event == "p_intent" and publisher_active:
                    state = 6
                elif event == "p_commit" and publisher_active:
                    if file_state:
                        state = 3
                    else:
                        generation += 1
                        state = 4
                        published = True

            if attached and published:
                self.assertEqual(latched_generation, generation, order)

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
        self.assertIn("cmp     r7, #4", source)
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
        self.assertIn("movw    ip, #0xB2D0", source[native:inactive])
        self.assertIn("ldrb    r5, [r0, #0x157]", source[native:inactive])
        self.assertIn("cmp     r5, #0", source[inactive:file_check])
        self.assertIn("beq     return_original", source[inactive:file_check])
        adapter = (HERE / "lifecycle.inc.S").read_text()
        self.assertIn("mov     r0, #6", adapter)
        self.assertIn("pg_lc_publish_cancel:", adapter)
        self.assertIn("O_LC_GEN", adapter)
        self.assertNotRegex(adapter.lower(), r"(?m)^\s*(?:ldrex|strex|clrex)\s")


if __name__ == "__main__":
    unittest.main()
