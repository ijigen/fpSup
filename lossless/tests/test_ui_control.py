import ctypes as ct
import unittest
import test_control as core_tests
from test_control import State, Context, eligible
from test_control import OK, INVALID, BUSY, UNSUPPORTED, NOT_READY, FAULT


class UI(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in ('magic', 'session', 'owner', 'generation', 'attached')]


class View(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in
                ('visible', 'value', 'off_enabled', 'on_enabled', 'reason')]


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse compilation setup, not the control TestCase's test methods.
        core_tests.ControlTests.setUpClass.__func__(cls)
        cls.lib.fpl_ui_boot.argtypes = [ct.POINTER(UI), ct.c_uint32]
        cls.lib.fpl_ui_boot.restype = None
        cls.lib.fpl_ui_attach.argtypes = [ct.POINTER(UI)] + [ct.c_uint32] * 6
        cls.lib.fpl_ui_detach.argtypes = [ct.POINTER(UI)] + [ct.c_uint32] * 3
        cls.lib.fpl_ui_select.argtypes = [ct.POINTER(UI), ct.c_uint32, ct.c_uint32, ct.c_uint32,
                                         ct.POINTER(State), ct.POINTER(Context), ct.c_uint32]
        cls.lib.fpl_ui_view.argtypes = [ct.POINTER(UI), ct.POINTER(State), ct.POINTER(Context), ct.POINTER(View)]
        cls.lib.fpl_ui_view.restype = None

    def setUp(self):
        self.ui, self.s, self.c = UI(), State(), eligible()
        self.session = 1
        self.lib.fpl_ui_boot(ct.byref(self.ui), self.session)
        self.lib.fpl_boot(ct.byref(self.s))

    def attach(self, page=10, owner=1234, generation=1, cine=1, present=1):
        return self.lib.fpl_ui_attach(ct.byref(self.ui), self.session, page, owner, generation, cine, present)

    def select(self, value, owner=1234, generation=1, session=None):
        return self.lib.fpl_ui_select(ct.byref(self.ui), self.session if session is None else session, owner, generation,
                                       ct.byref(self.s), ct.byref(self.c), value)

    def view(self):
        out = View()
        self.lib.fpl_ui_view(ct.byref(self.ui), ct.byref(self.s), ct.byref(self.c), ct.byref(out))
        return out

    def test_cine_mainb2_and_actual_private_widget_are_required(self):
        for args in ({'page': 31}, {'page': 9}, {'cine': 0}, {'present': 0}):
            before = bytes(self.ui)
            self.assertEqual(self.attach(**args), UNSUPPORTED)
            self.assertEqual(bytes(self.ui), before)
        self.assertEqual(self.view().visible, 0)

    def test_attach_once_and_no_owner_replacement(self):
        self.assertEqual(self.attach(), OK)
        before = bytes(self.ui)
        self.assertEqual(self.attach(), OK)
        self.assertEqual(self.attach(owner=4321), BUSY)
        self.assertEqual(self.attach(generation=2), BUSY)
        self.assertEqual(bytes(self.ui), before)

    def test_off_on_changes_only_product_preference(self):
        self.attach()
        view = self.view()
        self.assertEqual((view.visible, view.value, view.off_enabled, view.on_enabled), (1, 0, 1, 1))
        self.assertEqual(self.select(1), OK)
        self.assertEqual(self.view().value, 1)
        self.assertEqual(self.s.clip, 0)  # no recording or codec action
        self.assertEqual(self.select(0), OK)

    def test_wrong_owner_and_stale_generation_are_ignored(self):
        self.attach()
        before = bytes(self.s)
        self.assertEqual(self.select(1, owner=2222), INVALID)
        self.assertEqual(self.select(1, generation=2), INVALID)
        self.assertEqual(bytes(self.s), before)

    def test_detach_and_recreated_owner_invalidates_old_callback(self):
        self.attach()
        self.assertEqual(self.lib.fpl_ui_detach(ct.byref(self.ui), self.session, 1234, 1), OK)
        self.assertEqual(self.select(1), INVALID)
        self.assertEqual(self.view().visible, 0)
        self.assertEqual(self.attach(generation=2), OK)
        self.assertEqual(self.select(1), INVALID)
        self.assertEqual(self.select(1, generation=2), OK)
        self.assertEqual(self.lib.fpl_ui_detach(ct.byref(self.ui), self.session, 1234, 1), INVALID)
        self.assertEqual(self.ui.attached, 1)

    def test_warm_boot_invalidates_old_callback(self):
        self.attach()
        self.select(1)
        self.session = 2
        self.lib.fpl_ui_boot(ct.byref(self.ui), self.session)
        self.lib.fpl_boot(ct.byref(self.s))
        self.assertEqual(self.select(1), INVALID)
        self.assertEqual(self.view().visible, 0)
        self.assertEqual(self.s.requested, 0)
        self.assertEqual(self.attach(), OK)  # same address/generation, new session
        self.assertEqual(self.select(1, session=1), INVALID)
        self.assertEqual(self.lib.fpl_ui_detach(ct.byref(self.ui), 1, 1234, 1), INVALID)
        self.assertEqual(self.select(1), OK)

    def test_zero_session_is_invalid(self):
        self.lib.fpl_ui_boot(ct.byref(self.ui), 0)
        self.assertEqual(self.attach(), INVALID)
        self.assertEqual(self.view().visible, 0)

    def test_recording_locks_both_values(self):
        self.attach()
        self.select(1)
        self.lib.fpl_begin(ct.byref(self.s), ct.byref(self.c))
        view = self.view()
        self.assertEqual((view.off_enabled, view.on_enabled, view.reason), (0, 0, BUSY))
        self.assertEqual(self.select(0), BUSY)

    def test_unready_backend_cannot_appear_usable(self):
        self.attach()
        self.c.ready = 0
        view = self.view()
        self.assertEqual((view.visible, view.value, view.on_enabled, view.reason), (1, 0, 0, NOT_READY))
        self.assertEqual(self.select(1), NOT_READY)

    def test_still_transition_hides_row(self):
        self.attach()
        self.c.cine = 0
        self.assertEqual(self.view().visible, 0)
        self.assertEqual(self.select(1), UNSUPPORTED)
        self.assertEqual(self.select(0), UNSUPPORTED)

    def test_unsupported_geometry_disables_on_but_allows_off(self):
        self.attach()
        self.select(1)
        self.c.width, self.c.height = 2016, 1344
        view = self.view()
        self.assertEqual((view.value, view.off_enabled, view.on_enabled, view.reason), (1, 1, 0, UNSUPPORTED))
        self.assertEqual(self.select(0), OK)


if __name__ == '__main__':
    unittest.main()
