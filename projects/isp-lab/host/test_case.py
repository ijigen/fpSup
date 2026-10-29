"""case.py: the LV decode and the LV colour check, on synthetic frames and on recorded takes."""
import json, pathlib, shutil, subprocess, tempfile, unittest

import numpy as np

import case, evidence_jxl

VAL = pathlib.Path(__file__).resolve().parents[1] / 'validation'


def yvyu(y, cb, cr, w=4, h=2):
    return bytes([y, cr, y, cb] * (w // 2) * h)


class DecodeTests(unittest.TestCase):
    def test_orange_is_orange(self):          # orange: Cb low, Cr high (BT.709 Y 150, Cb 90, Cr 170)
        rgb = case.yuyv_rgb(yvyu(150, 90, 170), 4, 2)[0, 0].astype(int)
        self.assertGreater(rgb[0], rgb[2] + 60)

    def test_stats_read_the_same_order(self):
        self.assertEqual(case.lv_stats(yvyu(100, 120, 140), 4, 2)[2:], (120.0, 140.0))


def build(d):
    """case.build on a recorded take, unpacking push/ from its archive into a temp copy when the raw copy is gone."""
    run = VAL / d
    if (run / 'push').is_dir():
        return case.build(run)
    if not (run / 'evidence.tar.zst').exists() and not (run / 'EVIDENCE.json').exists():
        raise unittest.SkipTest(f'{d} not on disk')
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp) / d
        t.mkdir()
        evidence_jxl.unpack(run, t, ['push', 'applied.json'])
        return case.build(t)


class StandbyPick(unittest.TestCase):
    """10-28: ISPL v8.1's REC-start frames (flag 16) were taken as the standby LV; RWZM H 1:1 shows the top third x3
    there, so every such case failed fov / frames while its LCD and its real standby LV were right."""
    def test_rec_start_frame_is_not_the_standby(self):
        c = build('20261028-p6ab1-FHD60_C7a33b784')
        self.assertEqual(c['checkpoints']['standby_lv']['w'], 1620)
        self.assertGreater(c['checks']['fov_r'], 0.9)


class RecordedTakes(unittest.TestCase):
    """The colour check against takes whose truth is known (10-27): stock, bad-R10 V41 (white LV), fixed V41."""
    def check(self, d):
        return build(d)['checks']['lv_colour']

    def test_stock_passes(self):
        self.assertTrue(self.check('20261027-chk2-FHD60_E0'))

    def test_white_recording_lv_fails(self):
        self.assertFalse(self.check('20261027-vm1-FHD60_V41'))

    def test_h_only_zoom_with_a_seamed_recording_lv_fails(self):     # user 10-27: night1 z2048x1024 passed
        self.assertEqual(build('20261027-night1-z2048x1024')['verdict'], 'fail')

    def test_recording_lv_scale_is_judged_against_act_over_rec(self):     # mx1, 10-27
        self.assertTrue(build('20261027-mx1-FHD60_M134')['checks']['rec_lv'])    # 336 wide: 0.935 for 0.952
        self.assertFalse(build('20261027-mx1-FHD60_M74')['checks']['rec_lv'])    # E1 crops it: 0.945 for 0.977

    def test_a_square_record_stretched_to_16_9_fails(self):          # user 10-27: distorted modes
        c = build('20261027-sby-FHD60_M155')['checks']
        self.assertEqual((c['aspect'], c['aspect_dng']), (False, 1.009))
        self.assertTrue(build('20261027-chk2-FHD60_E0')['checks']['aspect'])

    def test_a_raw_one_row_off_fails(self):                          # g1 10-27: 12fastW greens at (0,0)/(1,1)
        self.assertTrue(build('20261027-g1-FHD60_M116')['checks']['cfa'])     # 12, same geometry
        self.assertFalse(build('20261027-g1-FHD60_M117')['checks']['cfa'])    # 12fastW: 1 of 3 frames
        self.assertFalse(build('20261027-g1-FHD60_M160')['checks']['cfa'])    # f12v3
        self.assertTrue(build('20261027-g1-FHD60_M140')['checks']['cfa'])     # 12v3

    def test_a_noise_frame_fails(self):                               # colour views 10-27: frames of pure noise
        c = build('20261027-smoke-FHD60_M1')['checkpoints']['cdng']       # frame 3 is noise with all four phases equal:
        self.assertEqual((c['cfa_frames'][2], c['frames_ok']), (True, False))   # the CFA test cannot see it
        self.assertTrue(build('20261027-g1-FHD60_M116')['checks']['frames'])

    def test_fixed_v41_passes(self):
        self.assertTrue(self.check('20261027-r10-FHD60_V41'))


if __name__ == '__main__':
    unittest.main()
