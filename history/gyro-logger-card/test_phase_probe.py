#!/usr/bin/env python3
"""Static invariants for the release-only RAM media phase probe."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "fp_usb_shell"))

from armasm import assemble  # noqa: E402


class PhaseProbeTests(unittest.TestCase):
    def test_branch_word_reaches_probe_entry(self):
        site = 0xC03660E8
        target = 0xC072F000
        displacement = (target - (site + 8)) >> 2
        expected = 0xEA000000 | (displacement & 0xFFFFFF)
        patch = assemble(HERE / "phase_fwrite_patch.S")
        self.assertEqual(struct.unpack("<I", patch)[0], expected)
        restore = assemble(HERE / "phase_fwrite_restore.S")
        self.assertEqual(struct.unpack("<I", restore)[0], 0xE92D40F0)

    def test_release_layout_has_no_overlap(self):
        logger = assemble(HERE / "logger_phase.S")
        park = assemble(ROOT / "fp_usb_shell" / "templates" / "park.S")
        probe = assemble(HERE / "phase_probe.S")
        self.assertLessEqual(0xC072E064 + len(logger), 0xC072EFB4)
        self.assertLessEqual(0xC072EFB4 + len(park), 0xC072F000)
        self.assertLessEqual(0xC072F000 + len(probe), 0xC072F800)

    def test_probe_has_no_recording_time_media_calls(self):
        source = (HERE / "phase_probe.S").read_text()
        self.assertNotIn("F_OPEN", source)
        self.assertNotIn("F_CLOSE", source)
        self.assertNotIn("F_CTOR", source)
        self.assertNotIn("F_DTOR", source)
        self.assertIn("F_WRITE_BODY", source)
        self.assertIn("S_TRACE", source)
        self.assertIn("STATE_MAGIC", source)
        self.assertIn("O_LC_KIND", source)

    def test_every_normal_card_build_restores_global_write_entry(self):
        source = (HERE / "build_card.py").read_text()
        self.assertIn("phase_fwrite_restore.S", source)
        logger = (HERE / "logger.S").read_text()
        self.assertIn("original push {r4-r7, lr}", logger)

    def test_phase_logger_uses_distinct_record_magic(self):
        normal = assemble(HERE / "logger.S")
        phase = assemble(HERE / "logger_phase.S")
        wrapper = (HERE / "logger_phase.S").read_text()
        source = (HERE / "logger.S").read_text()
        self.assertIn("#define FPGYRO_PHASE_PROBE 1", wrapper)
        self.assertIn("movt    r0, #0x3654", source)
        self.assertIn("movt    r0, #0x364D", source)
        self.assertNotEqual(normal, phase)

    def test_on_camera_gcsv_accepts_phase_tail(self):
        source = (HERE / "gcsvgen.S").read_text()
        self.assertIn("movt    r2, #0x3654", source)
        self.assertIn("GFT6: phase-probe end-of-blocks record", source)


if __name__ == "__main__":
    unittest.main()
