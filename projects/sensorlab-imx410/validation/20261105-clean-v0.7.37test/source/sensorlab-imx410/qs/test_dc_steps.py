"""DC dial stops through the actual QS key callbacks and loaded SensorLab ARM.

Only firmware/file/GUI services use the existing test_slqs models. No camera I/O.
--build tests an exact deliverable; --old-counterexample requires the old bug.
"""
import argparse
import hashlib
import json
from pathlib import Path
import unittest

import test_slqs as S

DOWN = [5888, 5728, 5568, 5408, 5248, 5088, 5040, 4880, 4720,
        4560, 4400, 4240, 4144, 3984, 3824]
UP = [3984, 4144, 4304, 4464, 4624, 4784, 4944, 5040, 5200,
      5360, 5520, 5680, 5840, 6000, 6048]


def open_width(*, locked=True, ready=False):
    c = S.boot(descriptor=ready)
    S.press(c, 5, 1)  # DC -> sub-QS
    if not locked:
        S.press(c, 1, 3)  # FREE
    c.guid(S.focus_int(c, 1))
    return c


class DialStops(unittest.TestCase):
    def width(self, c, expected, locked=True):
        self.assertEqual(int(S.tile(c, 1)[1]), expected)
        # HD's saved 16:9 ratio, rounded to an even sensor row, never accumulated.
        height = ((expected * 9 + 16) // 32) * 2 if locked else 3402
        self.assertEqual(int(S.tile(c, 2)[1]), height)
        marked = expected in (6048, 5040, 4144, 3984)
        foot = S.footer(c, S.focus_int(c, 1))
        self.assertEqual((foot['spin'], foot['items'][0][0], foot['items'][0][3]),
                         (1, str(expected), marked))
        # Check the container actually posts the visible dotted marker too.
        self.assertEqual(bool(S.TP.texts(c)['QSC_FM7'].strip()), marked)

    def route(self, locked):
        c = open_width(locked=locked)
        for expected in DOWN:
            S.press(c, 4, 1)
            self.width(c, expected, locked)
        for expected in UP:
            S.press(c, 3, 1)
            self.width(c, expected, locked)
        S.press(c, 3, 1)  # upper bound must still hold
        self.width(c, 6048, locked)

    def test_rear_stops_both_directions_with_ratio_locked(self):
        self.route(True)

    def test_rear_stops_both_directions_without_changing_free_height(self):
        self.route(False)

    def test_front_retains_16_pixel_steps_and_leaves_mark(self):
        c = open_width()
        for _ in range(6):
            S.press(c, 4, 1)
        for expected in (5072, 5056, 5040, 5024):
            S.press(c, 2, 1)
            self.width(c, expected)
        for expected in (5040, 5056):
            S.press(c, 1, 1)
            self.width(c, expected)

    def test_height_and_res_do_not_get_dc_width_stops(self):
        c = open_width(locked=False)
        S.press(c, 4, 2)
        self.assertEqual(int(S.tile(c, 2)[1]), 3382)
        self.assertEqual(int(S.tile(c, 1)[1]), 6048)
        # RES full width, FREE: coarse width crosses 5040 without a sensor mark.
        c = S.boot()
        for _ in range(16):
            S.press(c, 1, 2)  # last RES preset = full width
        S.press(c, 5, 2)
        S.press(c, 1, 3)
        for _ in range(7):
            S.press(c, 4, 1)
        self.assertEqual(S.ap_sel(c)['rw'], 4928)
        foot = S.footer(c, S.focus_int(c, 1))
        self.assertFalse(foot['items'][0][3])

    def test_5040_applies_and_survives_save_and_reload(self):
        c = open_width(ready=True)
        for _ in range(7):
            S.press(c, 4, 1)
        self.width(c, 5040)
        self.assertEqual((S.ap_sel(c)['dcw'], S.ap_sel(c)['dch']), (5040, 2836))
        self.assertEqual(S.ap_status(c)['active'], 1)
        c.layout()  # simulated file write through existing leave/save path
        saved = c.written['\\fpSup\\' + S.BS.file_name()]
        d = S.boot(card=saved, descriptor=True)
        S.press(d, 5, 1)
        d.guid(S.focus_int(d, 1))
        self.width(d, 5040)
        S.press(d, 4, 1)
        self.width(d, 4880)


def exact_build(folder, version):
    info = json.loads((folder / f'build-{version}.json').read_text())
    info['functions'] = {'sq_test': info['sq_test_off'] - info['code_off']}
    S.BS.VERSION = version
    data = (folder / 'fpSup' / S.BS.file_name()).read_bytes()
    assert hashlib.sha256(data).hexdigest() == info['sha256']
    S.PATH = '\\fpSup\\' + S.BS.file_name()
    S._built['b'] = data, info


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path)
    p.add_argument('--version', default=S.BS.VERSION)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--old-counterexample', action='store_true')
    a = p.parse_args()
    if a.build:
        exact_build(a.build, a.version)
    if a.old_counterexample:
        c = open_width()
        actual = []
        for _ in range(7):
            S.press(c, 4, 1)
            actual.append(int(S.tile(c, 1)[1]))
        assert actual == [5888, 5728, 5568, 5408, 5248, 5088, 4928], actual
        assert actual != DOWN[:7]
        result = dict(old_bug_reproduced=True, rear_steps=actual, expected_stop=5040)
    else:
        r = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DialStops))
        result = dict(passed=r.wasSuccessful(), tests=r.testsRun, failures=len(r.failures), errors=len(r.errors),
                      skipped=len(r.skipped))
    result.update(sha256=S.blob()[1]['sha256'], hardware_tested=False, limitations=__doc__)
    a.report.write_text(json.dumps(result, indent=2) + '\n')
    if not a.old_counterexample and not r.wasSuccessful():
        raise SystemExit(1)
