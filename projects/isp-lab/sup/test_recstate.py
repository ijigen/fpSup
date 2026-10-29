#!/usr/bin/env python3
"""Repeated takes with the real fp 5.02 observer lifecycle ARM instructions.

Only manager registration and movie events are supplied by the harness. The
ena/disa/init/event callback execute ROM, unlike the older per-press flag fake.
"""
import struct
import unittest
from unittest import mock

import test_card as T
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1


class ObserverCamera(T.Cam):
    BOUNDARIES = {0xC0407828: 'object', 0xC0370CF8: 'manager',
                  0xC0371598: 'register', 0xC03715C8: 'unregister'}
    EVENT = 0x438FE000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observers, self.observer_calls = set(), []
        self.recording = False
        for at in self.BOUNDARIES:
            self.mu.mem_write(at, struct.pack('<I', 0xE12FFF1E))
        self.mu.mem_write(T.RECSTATE, bytes(8))

    def native(self, fn, obj=T.RECSTATE, event=None):
        self.mu.reg_write(UC_ARM_REG_R0, obj)
        if event is not None:
            self.mu.reg_write(UC_ARM_REG_R1, event)
        self.mu.reg_write(UC_ARM_REG_PC, fn)

    def _hook(self, mu, at, size, user):
        kind = self.BOUNDARIES.get(at)
        if kind:
            if kind == 'object':
                return self._ret(T.RECSTATE)
            if kind == 'manager':
                return self._ret(0xC3758000)
            obj = self.r(UC_ARM_REG_R1)
            assert obj == T.RECSTATE
            self.observer_calls.append(kind)
            if kind == 'register':
                assert obj not in self.observers, 'duplicate observer registration'
                self.observers.add(obj)
            else:
                self.observers.discard(obj)
            return self._ret(0)
        if at == T.STUBS['SHELL_EXEC']:
            line = self.cstr(self.r(UC_ARM_REG_R1))
            self.shell.append((line, self.now))
            fn = {'recstate ena': 0xC0407908, 'recstate disa': 0xC0407948,
                  'recstate init': 0xC0407980}.get(line)
            if fn:
                return self.native(fn)
            if line == 'key MOVON':
                self.recording = not self.recording
                if T.RECSTATE in self.observers:
                    code = 0xF if self.recording else 0x13
                    mu.mem_write(self.EVENT, struct.pack('<4I', 0, 0, 1, code))
                    return self.native(0xC0407868, event=self.EVENT)
            # Wait boundaries return; only a registered native callback above
            # can set started/saved. Unknown waits cannot manufacture success.
            return self._ret(0)
        return super()._hook(mu, at, size, user)


class NativeRecstateTests(unittest.TestCase):
    def take(self):
        with mock.patch.object(T, 'Cam', ObserverCamera):
            return T.Take(0, frames=1, ctl_only=True)

    def test_native_disable_leaves_stale_registration_flag(self):
        t = self.take()
        c = t.cam
        c.call(0xC0407908, r0=T.RECSTATE)
        self.assertIn(T.RECSTATE, c.observers)
        c.call(0xC0407948, r0=T.RECSTATE)
        self.assertNotIn(T.RECSTATE, c.observers)
        self.assertEqual(bytes(c.mu.mem_read(T.RECSTATE+4, 1)), b'\1')
        c.call(0xC0407908, r0=T.RECSTATE)
        self.assertNotIn(T.RECSTATE, c.observers)
        self.assertEqual(c.observer_calls, ['register', 'unregister'])

    def test_two_takes_rearm_native_observer_and_stop(self):
        t = self.take()
        c = t.cam
        for cycle in range(2):
            t.arm('sd')
            for key, val in [('start_ms', 100), ('rec_ms', 100), ('ctl', T.R.CTL['armed'])]:
                c.put(t.cap_at+T.R.OFF[key], val)
            base = 1_000_000+cycle*3_000_000
            T.ControlTests.step(self, t, base)
            cap = T.ControlTests.step(self, t, base+200_000)
            self.assertEqual(cap['ctl'], T.R.CTL['starting'])        # layout 10: +6 is polled from the next step
            cap = T.ControlTests.step(self, t, base+220_000)
            self.assertEqual(cap['ctl'], T.R.CTL['rec'], f'cycle {cycle}: no native start callback')
            cap = T.ControlTests.step(self, t, base+1_000_000)
            self.assertEqual((cap['ctl'], cap['n_press'], cap['rs_started'], cap['rs_saved']),
                             (T.R.CTL['done'], 2, 1, 1))
            self.assertFalse(c.recording)
            self.assertNotIn(T.RECSTATE, c.observers)
        self.assertEqual(c.observer_calls, ['register', 'unregister']*2)


if __name__ == '__main__':
    unittest.main()
