"""raw-view as a Loader v4 sup (build_v4_rawview.py), loaded by the real v4 core.

    cd projects/rawview/build && python3 -B -m unittest test_v4_rawview

Every test of test_v3_rawview runs again on the v4 build under the v4 core:
claims before anything, release with nothing written, the three CHAIN sites,
power-off, the settings record in its own file -- now at 48, behind
svc->file_is.  uia_apply (fpsup-ui's section here) is answered by the test,
as in v3: the image's RAM has no GUI objects.  Added: the block runs at the
cached alias; the save writes nothing into a file that is no longer this sup;
the file object and the read-back are at the uncached alias.

This is the 0.3.1 build (build(v4=True), no COL-Share); RAW-View 0.4.0test, the COL-Share
client, is test_v4_cols_rawview.py.

Emulated, not on the camera.
"""
import pathlib
import struct
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'fpSup' / 'loader-v4'))

import test_v3_rawview as V3R                             # noqa: E402
import build_v4 as B4                                     # noqa: E402
import test_v4 as T4                                      # noqa: E402

V, T = V3R.V, V3R.T
NAME = V.NAME                                             # any name: the v4 file is RAWV.BIN
LINE = 64
CODE_NAMES = {T4.CODES['LOADED']: 'LOADED', T4.CODES['RELEASED']: 'RELEASED',
              T4.CODES['REPAIRED']: 'REPAIRED'}


class RawCamera4(V3R.RawCamera, T4.Camera):
    """test_v3_rawview's camera on v4's: the block is the 64-aligned line in
    the allocation, run at its cached alias."""
    def _hook(self, mu, addr, size, data):
        before = self.block
        r = super()._hook(mu, addr, size, data)
        if self.block is not None and self.block != before:
            ub = (self.block + LINE - 1) & ~(LINE - 1)
            self.block = ub + 0x80000000 if 0x40000000 <= ub < 0x80000000 else ub
            self.uia_at = (self.block + self.ui_off) & ~1
        return r


class RawViewV4Tests(V3R.RawViewV3Tests):
    HL = B4.SL4_HEADER_LEN

    def log(self, cam):
        return [(CODE_NAMES.get(c, c), a, b, t) for c, a, b, t in cam.loadlog()]

    @classmethod
    def setUpClass(cls):
        cls.sup, cls.facts, cls.rows = V.build(v4=True, name=b'RAW-View\0')
        d = dict(x.split('=') for x in cls.facts['defines'])
        cls.ui_off = cls.facts['blob_off'] + int(d['UI_APPLY'], 0)
        cls.img = T.IMAGE.read_bytes()
        cls.seg1 = V3R.SEG1.read_bytes()
        cls.sites = {a: s for a, s, _ in cls.rows}
        size = cls.facts['block']
        cls.asize = ((size + LINE - 1) & ~(LINE - 1)) + 2 * LINE   # sloader4.c load_one

    def boot(self, *inner, sup=None, stale=None, bank=0, uia=0):
        files, dirs = T4.card(*inner, (NAME, sup or self.sup))
        cam = RawCamera4(files, dirs, stale=stale, bank_color=bank,
                         block_size=self.asize, ui_off=self.ui_off)
        cam.uia_result = uia
        cam.boot()
        self.assertIsNone(cam.error)
        self.assertEqual(cam.misaligned, [])
        return cam

    def other(self, sid, *rows):
        return B4.test_sup(T4.cfg(claims=[(a, struct.unpack('<I', self.sites[a])[0], k, new)
                                          for a, k, new in rows]), sid)

    # ---- what v4 changed ----------------------------------------------------
    def test_header_and_no_string_site(self):
        h = struct.unpack_from('<12I', self.sup)
        self.assertEqual((h[0], h[1], h[8]), (B4.SL4_MAGIC, 48, B4.SL_F_CACHED_OK))
        self.assertEqual(self.sup[h[11]:h[11] + 9], b'RAW-View\0')
        self.assertEqual(struct.unpack_from('<I', self.sup, 48)[0], V.CFG_MAGIC)   # the record at 48
        for a in (0xC05E5B58, 0xC05E61C8, 0xC05E61E0):
            self.assertNotIn(a, self.sites)

    def test_loads_claims_every_site_and_hooks(self):
        cam = self.boot()
        self.assertEqual(self.outcome(cam), 'LOADED')
        self.assertIn('UIA_APPLY', cam.calls)
        self.assertTrue(cam.block >= 0xC0000000 and cam.block % 64 == 0, hex(cam.block))
        self.assertEqual(T4.blocks(cam)[NAME], cam.block)
        self.assertEqual(sorted(a for a, *_ in cam.journal()), sorted(self.sites))
        for a, n, data in cam.journal():
            self.assertEqual(data, self.sites[a], hex(a))
        res = self.resident(cam)
        self.assertEqual(cam.w(res), 0x31575652)                # "RVW1"
        self.assertTrue(cam.block < res < cam.block + self.facts['block'])
        self.assertEqual(cam.w(res + V3R.P_BLOCK), cam.block)
        self.assertEqual(cam.cstr(cam.w(res + V3R.P_PATH)), V3R.PATH)
        rs = self.facts['res_syms']
        self.assertEqual(cam.w(res + rs['sv_next']), V3R.SV_ORIG)
        self.assertEqual(cam.w(res + rs['pq_next']), V3R.PQ_ORIG)
        self.assertEqual(cam.w(res + rs['ai_next']), V3R.AI_ORIG)
        self.assertEqual(cam.w(res + V.build.__globals__['symbols'](
            HERE / 'rv_resident.S', ['V3=1', 'V4=1'])['sv_svc']), cam.svc())
        self.assertEqual(cam.w(V3R.bl_target(V3R.SV, cam.w(V3R.SV)) + 4), res + rs['stub_sv'])

    def test_save_writes_the_record_into_its_own_file(self):
        cam = self.boot()
        got = self.save(cam, 1, 1, 1, 1)
        self.assertEqual(got[:48], self.sup[:48])               # the header unchanged
        self.assertEqual(got[80:], self.sup[80:])               # and the rest
        self.assertEqual(struct.unpack('<8I', got[48:80]), (V.CFG_MAGIC, 1, 1, 1, 1, 0, 0, 0))
        self.assertIn('F_READ', cam.calls)                      # read back
        self.assertEqual(cam.opened, [V3R.PATH, V3R.PATH])      # file_is, then the write
        self.save(cam, 1, 1, 1, 1)                              # unchanged: no card access
        self.assertEqual(cam.opened, [])

    def test_a_replaced_file_is_never_written(self):
        cam = self.boot()
        other = b'\0' * len(self.sup)
        cam.files[V3R.PATH] = other
        cam.written.pop(V3R.PATH, None)
        self.save(cam, 1, 1, 1, 1)
        self.assertNotIn('F_WRITE', cam.calls)
        self.assertEqual(cam.files[V3R.PATH], other)
        cam.files[V3R.PATH] = self.sup                          # ours again: written now
        got = self.save(cam, 1, 1, 1, 1)
        self.assertEqual(struct.unpack('<5I', got[48:68]), (V.CFG_MAGIC, 1, 1, 1, 1))

    def test_the_file_object_is_at_the_uncached_alias(self):
        cam = self.boot()
        self.save(cam, 1, 1, 1, 1)
        objs = [o for o in cam.fobj if o is not None]
        mine = [o for o in objs if cam.block - 0x80000000 <= o < cam.block - 0x80000000 + self.facts['block']]
        self.assertTrue(mine, [hex(o) for o in objs])


if __name__ == '__main__':
    unittest.main()
