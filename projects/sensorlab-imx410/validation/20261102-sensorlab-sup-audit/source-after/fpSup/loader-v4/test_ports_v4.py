#!/usr/bin/env python3
"""ports.py's sups under the real v4 core (unicorn).

    python3 -B -m unittest test_ports_v4

ULWR's full take through firmware code runs in its own test under this core:
    cd projects/rec-core/writer && ULWR_V4=1 python3 -B -m unittest test_card
"""
import pathlib, struct, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_v4 as B                                    # noqa: E402
import ports                                            # noqa: E402
import names_v4 as N                                    # noqa: E402
import test_v4 as T                                     # noqa: E402

FCAP_SITE, STOPFX_SITE = 0xC063F824, 0xC0377118
GYR2_SITES = (0xC050D4C8, 0xC0125480)
_built = {}


def built():
    if not _built:
        _built.update(ports.build())
    return _built


def stock(cam, a):
    return struct.unpack_from('<I', cam.img, a - 0xC0000000)[0]


class PortTests(unittest.TestCase):
    def test_body_is_the_v3_body(self):
        for name, (v4, v3) in built().items():
            if name == N.file_name('GYR2'):                 # its own v4 build with the row: test_gyr2_v4
                continue
            h3, h4 = struct.unpack_from('<8I', v3), struct.unpack_from('<12I', v4)
            self.assertEqual(h4[0], B.SL4_MAGIC, name)
            self.assertEqual(v4[48:48 + len(v3) - 32], v3[32:], name)
            self.assertEqual(h4[4], h3[4] + 16, name)                          # entry
            self.assertEqual(h4[3], max(h3[3] + 16, h4[2]), name)               # block (+ the name)
            self.assertEqual((h4[5], h4[6]), (h3[5], h3[6]), name)             # id, version
            self.assertEqual(h4[8], 0 if name == N.file_name('SHEL') else B.SL_F_CACHED_OK, name)

    def test_names(self):
        """names_v4 (the user 2026-10-25): file <base>_v<version>.BIN, header display name."""
        self.assertEqual(sorted(built()), sorted(N.file_name(k) for k in ('FCAP', 'STFX', 'ULWR', 'GYR2', 'SHEL')))
        for sid in ('FCAP', 'STFX', 'ULWR', 'SHEL'):
            v4 = built()[N.file_name(sid)][0]
            at = struct.unpack_from('<I', v4, 44)[0]
            self.assertEqual(v4[at:v4.index(b'\0', at)].decode(), N.display(sid), sid)
        self.assertEqual(N.file_name('FCAP'), 'EarlyFlush_v0.1.0.BIN')

    def test_v3_bytes_are_the_released_ones(self):
        rel = HERE.parent / 'tools' / 'merge-v3' / 'inputs'
        self.assertEqual(built()[N.file_name('FCAP')][1], (rel / 'fcap-20261015' / '30FCAP.BIN').read_bytes())
        self.assertEqual(built()[N.file_name('STFX')][1], (rel / 'stopfx-20261012' / '05STOPFX.BIN').read_bytes())
        self.assertEqual(built()[N.file_name('ULWR')][1], (HERE.parent / 'releases' / 'fpsup-unlocked-writer-v0.1.0test'
                                                  / 'fpSup' / '20ULWR.BIN').read_bytes())
        self.assertEqual(built()[N.file_name('SHEL')][1], (HERE.parent / 'releases' / 'fpsup-usbshell-v3.4.0test'
                                                   / 'fpSup' / '00SHELL.BIN').read_bytes())

    def test_all_on_one_card(self):
        sups = [(n, v4) for n, (v4, _) in built().items() if n != N.file_name('ULWR')]   # ULWR: test_card
        cam = T.boot(*sups)
        self.assertIsNone(cam.error)
        loaded = T.blocks(cam)
        self.assertEqual(sorted(loaded), sorted(n for n, _ in sups))
        for n, at in loaded.items():
            if n == N.file_name('SHEL'):
                self.assertTrue(0x40000000 <= at < 0x80000000, hex(at))
            else:
                self.assertTrue(at >= 0xC0000000 and at % 64 == 0, (n, hex(at)))
        self.assertEqual(cam.w(FCAP_SITE), 0x2A282002)        # cmp r2, #40
        self.assertEqual(cam.w(STOPFX_SITE), 0xEA000160)
        for a in GYR2_SITES:
            self.assertNotEqual(cam.w(a), stock(cam, a), hex(a))
        sites = [FCAP_SITE, STOPFX_SITE, *GYR2_SITES]
        cam.power_off()
        self.assertEqual([cam.w(a) for a in sites], [stock(cam, a) for a in sites])

    def test_from_v3_refuses_a_body_it_cannot_vouch_for(self):
        v3 = built()[N.file_name('GYR2')][1]
        with self.assertRaises(B.BuildError):
            B.from_v3(v3, name='Gyro2')                  # not patch_sup, not marked reviewed
        with self.assertRaises(B.BuildError):
            B.from_v3(built()[N.file_name('FCAP')][0], name='x')  # already v4


if __name__ == '__main__':
    unittest.main()
