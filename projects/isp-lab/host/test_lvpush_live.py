"""Standby runner cleanup and result checks; all camera I/O is replaced."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import lvpush_live as L


class Camera:
    def __init__(self):
        self.cap = dict.fromkeys((*L.FIELDS, 'ctl'), 0)
        self.writes = []

    def mem_set(self, addr, value):
        name = next(k for k in L.FIELDS if L.ispl.R.OFF[k] == addr - 0x45001000)
        self.writes.append((name, value))
        self.cap[name] = value

    def mem_get(self, addr):
        name = next(k for k in L.FIELDS if L.ispl.R.OFF[k] == addr - 0x45001000)
        return [self.cap[name]]


class Capture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = pathlib.Path(tmp.name) / 'trial'
        self.cam = Camera()
        patches = mock.patch.multiple(L.ispl, use_ctl_only=mock.Mock(), P=lambda: self.cam,
                                      not_recording=mock.Mock(), build=lambda: {'sha256': 'expected'},
                                      block_addr=lambda: 0x45000000, cap_addr=lambda *a: 0x45001000,
                                      read_cap=lambda *a: dict(self.cam.cap), flush=mock.Mock())
        patches.start()
        self.addCleanup(patches.stop)

    def receive(self, *args, **kw):
        self.assertEqual(self.cam.cap['lv_push'], 1)
        self.cam.cap['lv_n_sent'] += 8
        return ({'reason': 'idle'}, None,
                {'images': 8, 'skipped_bytes': 0, 'resyncs': 0, 'torn': 0, 'seq_gaps': {}, 'leftover': 0})

    def report(self):
        return json.loads((self.out / 'lvpush.json').read_text())

    def test_success_disables_and_saves_verified_counters(self):
        with mock.patch.object(L.push_rx, 'listen', side_effect=self.receive):
            rep = L.capture(self.out)
        self.assertTrue(rep['ok'])
        self.assertTrue(rep['cleanup_ok'])
        self.assertEqual(self.cam.writes[-1], ('lv_push', 0))
        self.assertEqual(rep, self.report())

    def test_disconnect_disables_and_preserves_error(self):
        with mock.patch.object(L.push_rx, 'listen', side_effect=ConnectionError('stream lost')):
            with self.assertRaisesRegex(ConnectionError, 'stream lost'):
                L.capture(self.out)
        self.assertEqual(self.cam.cap['lv_push'], 0)
        self.assertTrue(self.report()['cleanup_ok'])
        self.assertIn('stream lost', self.report()['error'])

    def test_interrupted_arm_still_attempts_disable(self):
        real_set = self.cam.mem_set
        def write(addr, value):
            real_set(addr, value)
            if addr == 0x45001000 + L.ispl.R.OFF['lv_push'] and value == 1:
                raise KeyboardInterrupt('arm reply lost')
        with mock.patch.object(self.cam, 'mem_set', side_effect=write):
            with self.assertRaises(KeyboardInterrupt):
                L.capture(self.out)
        self.assertEqual(self.cam.cap['lv_push'], 0)
        self.assertTrue(self.report()['cleanup_ok'])

    def test_unsettled_listener_does_not_send_camera_cleanup(self):
        with mock.patch.object(L.push_rx, 'listen', side_effect=L.push_rx.ListenerUnsettled('still listening')):
            with self.assertRaises(L.push_rx.ListenerUnsettled):
                L.capture(self.out)
        self.assertEqual(self.cam.writes[-1], ('lv_push', 1))
        self.assertFalse(self.report()['cleanup_ok'])
        self.assertIn('not attempted', self.report()['cleanup_error'])

    def test_incomplete_trial_does_not_report_success(self):
        def incomplete(*args, **kw):
            end, reply, stats = self.receive()
            stats['images'] = 7
            return end, reply, stats
        with mock.patch.object(L.push_rx, 'listen', side_effect=incomplete):
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                L.capture(self.out)
        self.assertTrue(self.report()['cleanup_ok'])
        self.assertFalse(self.report()['ok'])

    def test_cleanup_failure_is_retained_with_original_error(self):
        real_set = self.cam.mem_set
        def write(addr, value):
            if self.cam.cap['lv_push'] == 1 and value == 0:
                raise RuntimeError('disable lost')
            real_set(addr, value)
        with mock.patch.object(self.cam, 'mem_set', side_effect=write), \
             mock.patch.object(L.push_rx, 'listen', side_effect=ConnectionError('stream lost')):
            with self.assertRaisesRegex(ConnectionError, 'stream lost'):
                L.capture(self.out)
        rep = self.report()
        self.assertIn('stream lost', rep['error'])
        self.assertIn('disable lost', rep['cleanup_error'])
        self.assertFalse(rep['cleanup_ok'])

    def test_active_sampler_and_nonempty_output_are_rejected(self):
        self.cam.cap['lv_push'] = 1
        with self.assertRaisesRegex(RuntimeError, 'active'):
            L.capture(self.out)
        self.assertEqual(self.cam.writes, [])
        (self.out / 'existing.bin').write_bytes(b'evidence')
        with self.assertRaisesRegex(ValueError, 'empty'):
            L.capture(self.out)
        self.assertEqual(self.cam.writes, [])


if __name__ == '__main__':
    unittest.main()
