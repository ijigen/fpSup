"""Independent regressions for OG4K transition refusal and rollback semantics.

Runs only emitted ARM against synthetic host RAM. No camera backend is used.
These assertions specify that refusal does not silently unpublish a still-active
full-height front end, and a successful rollback restores the prior state.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_core as existing


class TransitionReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob, cls.symbols = existing.core.build()
        cls.image = existing.core.load_firmware()
        cls.frontend = existing.core.table(cls.blob, cls.symbols, "frontend", 10, 3)

    def setUp(self):
        self.m = existing.Machine(self.blob, self.symbols, self.image)
        self.m.put(existing.STATE, [existing.core.MAGIC, 0, 0, 0])

    def enabled_frontend(self):
        self.assertEqual(self.m.call("transition", existing.STATE, 1), 0)
        for address, _, full in self.frontend:
            self.assertEqual(self.m.word(address), full)

    def test_invalid_action_preserves_active_selection(self):
        self.enabled_frontend()
        self.assertEqual(self.m.call("transition", existing.STATE, 3), 1)
        self.assertEqual(self.m.word(existing.STATE + 4), 1,
                         "refusal left full-height data active but cleared enabled")
        self.assertEqual(self.m.call("transition", existing.STATE, 0), 0,
                         "invalid request must not strand the ordinary OFF path")

    def test_wrong_magic_does_not_write_unowned_state(self):
        original = (0xBAD00BAD, 7, 8, 9)
        self.m.put(existing.STATE, original)
        self.assertEqual(self.m.call("transition", existing.STATE, 1), 1)
        self.assertEqual(self.m.words(existing.STATE, 4), original)

    def test_busy_refusal_keeps_existing_owner_busy(self):
        self.m.put(existing.STATE, [existing.core.MAGIC, 0, 0, 1])
        self.assertEqual(self.m.call("transition", existing.STATE, 1), 1)
        self.assertEqual(self.m.word(existing.STATE + 12), 1,
                         "a rejected call must not release another operation's busy flag")

    def test_successful_disable_rollback_restores_enabled_state(self):
        self.enabled_frontend()
        target = self.frontend[0][0]
        dropped = []

        def inject(address, value, old):
            if address == target and not dropped:
                dropped.append(True)
                return old

        self.m.inject = inject
        self.assertEqual(self.m.call("transition", existing.STATE, 0), 4)
        self.m.inject = None
        for address, _, full in self.frontend:
            self.assertEqual(self.m.word(address), full)
        self.assertEqual(self.m.word(existing.STATE + 4), 1,
                         "successful rollback restored full-height words but lost enabled")
        self.assertEqual(self.m.call("transition", existing.STATE, 0), 0)


if __name__ == "__main__":
    unittest.main()
