"""fpRecLimit as a Loader v3 sup, loaded by the real 加載器.

    cd fpSup/rec-limit && python3 -B -m unittest test_v3_reclimit

The real loader.S (as the AutoRun spells it), the real LOADER.BIN and the built
46RECLM.BIN run in Unicorn against the reference image; the firmware's file,
allocator and power-off routines are Python (fp_usb_shell/v3/test_v3.Camera).

Proven here: the sup claims both limit words with SL_EXCL and writes 28800 s over
them; the stock 7200 s is in the journal and the loader puts it back at power-off;
another sup that already holds either word makes this one RELEASE with nothing
written; it creates no task and writes no file.  Not proven here: the camera's
recording behaviour (that is the on-camera record in projects/rec-limit-sup.md).
"""
import pathlib
import struct
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
V3 = HERE.parent / 'fp_usb_shell' / 'v3'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(V3))
sys.path.insert(0, str(V3.parent))

import test_v3 as T                                        # noqa: E402
import build_v3 as B                                       # noqa: E402
import build_v3_reclimit as M                              # noqa: E402

STOCK_BYTES = struct.pack('<I', M.STOCK)


@unittest.skipIf(T.Uc is None or not T.IMAGE.exists(), 'needs unicorn and the image')
class RecLimitTests(unittest.TestCase):
    def setUp(self):
        self.img = T.IMAGE.read_bytes()
        self.data = M.build()[0]

    def boot(self, *sups):
        cam = T.Camera(*T.card(*sups))
        cam.boot()
        return cam

    def results(self, cam):
        return {t: c for c, _, _, t in cam.log() if c in ('LOADED', 'RELEASED')}

    def test_header_is_a_loader_v3_sup(self):
        magic, hlen, flen, block, entry, sid, ver, svc = struct.unpack_from('<8I', self.data)
        self.assertEqual(magic, B.SL_MAGIC)
        self.assertEqual(hlen, B.SL_HEADER_LEN)
        self.assertEqual(flen, len(self.data))
        self.assertGreaterEqual(block, flen)
        self.assertTrue(0 < (entry & ~1) < flen)
        self.assertEqual(struct.pack('<I', sid).rstrip(b'\0'), b'RCLM')
        self.assertEqual(svc, 1)                       # entries only; the base services
        self.assertLessEqual(M.NEW, 0xFFFF)            # both consumers stay exact
        self.assertGreater(M.NEW, M.STOCK)

    def test_both_words_become_the_new_cap(self):
        cam = self.boot((M.NAME, self.data))
        self.assertEqual(self.results(cam), {M.NAME: 'LOADED'})
        for a in M.WORDS:
            self.assertEqual(cam.w(a), M.NEW)

    def test_stock_is_journalled_and_power_off_puts_it_back(self):
        cam = self.boot((M.NAME, self.data))
        self.assertEqual(cam.journal(), [(a, 4, STOCK_BYTES) for a in M.WORDS])
        cam.power_off()
        for a in M.WORDS:
            self.assertEqual(cam.w(a), M.STOCK)

    def test_no_task_no_file_write(self):
        cam = self.boot((M.NAME, self.data))
        self.assertEqual([n for n in cam.calls if n in ('TK_CRE', 'TK_STA')], [])
        self.assertEqual([p for p in cam.written if '46RECLM' in p], [])

    def test_another_sup_holding_a_word_wins(self):
        stock = [T.word(self.img, a) for a in M.WORDS]
        other = T.test_sup('TSTO', [(a, s, 2, s) for a, s in zip(M.WORDS, stock)])
        cam = self.boot(('10TSTO.BIN', other), (M.NAME, self.data))
        self.assertEqual(self.results(cam), {'10TSTO.BIN': 'LOADED', M.NAME: 'RELEASED'})
        for a, s in zip(M.WORDS, stock):
            self.assertEqual(cam.w(a), s)
        self.assertEqual(cam.journal(), [(a, 4, struct.pack('<I', s))
                                         for a, s in zip(M.WORDS, stock)])

    def test_one_word_taken_is_enough_to_release(self):
        stock = [T.word(self.img, a) for a in M.WORDS]
        other = T.test_sup('TSON', [(M.WORDS[1], stock[1], 2, stock[1])])
        cam = self.boot(('10TSON.BIN', other), (M.NAME, self.data))
        self.assertEqual(self.results(cam), {'10TSON.BIN': 'LOADED', M.NAME: 'RELEASED'})
        self.assertEqual(cam.w(M.WORDS[0]), stock[0])   # nothing of ours is written
        self.assertEqual(cam.w(M.WORDS[1]), stock[1])


if __name__ == '__main__':
    unittest.main()
