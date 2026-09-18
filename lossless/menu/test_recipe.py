"""Pinned-source unit tests. Run with FPLOSSLESS_SEG0 set to the explicit input."""

import os
from pathlib import Path
import struct
import unittest

import verify_recipe as recipe


class FixedWidthRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get("FPLOSSLESS_SEG0")
        if not path:
            raise unittest.SkipTest("FPLOSSLESS_SEG0 was not provided")
        cls.source = Path(path).read_bytes()
        recipe.check(recipe.sha(cls.source) == recipe.SEG0_SHA, "source fingerprint mismatch")

    def test_explicit_noop_not_omitted_true_default(self):
        records, _ = recipe.fixed_width_recipe(self.source)
        self.assertEqual(records[0xC216CA4D][32:], struct.pack(">III", 0x22, 0, 0))

    def test_original_is_unchanged(self):
        before = recipe.sha(self.source)
        recipe.fixed_width_recipe(self.source)
        self.assertEqual(recipe.sha(self.source), before)

    def test_budget_and_record_count(self):
        records, evidence = recipe.fixed_width_recipe(self.source)
        self.assertEqual(len(records), len(recipe.records(self.source)) - 2)
        self.assertEqual(evidence["component_budget_delta"],
                         {"appVariableChangeEvent": -1, "controlAnimation": -1})

    def test_wrong_source_rejected(self):
        changed = bytearray(self.source)
        changed[recipe.DONOR_START - recipe.BASE + 1] ^= 1
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            recipe.fixed_width_recipe(changed)

    def test_reenabled_sync_rejected(self):
        records, _ = recipe.fixed_width_recipe(self.source)
        changed = bytearray(records[0xC216CA4D])
        struct.pack_into(">I", changed, 36, 1)
        records[0xC216CA4D] = bytes(changed)
        with self.assertRaisesRegex(ValueError, "inert"):
            recipe.verify_isolation(self.source, records)

    def test_shared_width_watcher_rejected(self):
        records, _ = recipe.fixed_width_recipe(self.source)
        records[0xC216CF50] = recipe.records(self.source)[0xC216CF50]
        with self.assertRaisesRegex(ValueError, "watcher"):
            recipe.verify_isolation(self.source, records)

    def test_wrong_geometry_rejected(self):
        records, _ = recipe.fixed_width_recipe(self.source)
        changed = bytearray(records[0xC216D3A7])
        struct.pack_into(">f", changed, 32, 100.0)
        records[0xC216D3A7] = bytes(changed)
        with self.assertRaisesRegex(ValueError, "base geometry"):
            recipe.verify_isolation(self.source, records)

    def test_restoring_animation_rejected(self):
        records, _ = recipe.fixed_width_recipe(self.source)
        changed = bytearray(records[0xC216D565])
        struct.pack_into(">f", changed, 64, 0.0)
        records[0xC216D565] = bytes(changed)
        with self.assertRaisesRegex(ValueError, "nonconstant"):
            recipe.verify_isolation(self.source, records)


if __name__ == "__main__":
    unittest.main()
