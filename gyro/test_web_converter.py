#!/usr/bin/env python3
"""The web converter and the Python tools must answer identically.

    ./gyro/test_web_converter.py

gyro/web/index.html carries a second implementation of everything gyr7.py and
lens_profile.py do -- the header layout, the record layout, the gcsv, the lens
profile.  A second implementation is a second chance to be wrong, and the way
it goes wrong is silently: a file that opens in Gyroflow and is subtly not the
one the other tool would have written.

So this builds a capture, runs the page's own JavaScript over it in node, and
compares byte for byte.  Skipped, loudly, if node is not installed.
"""
import json
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gyr7                                                     # noqa: E402
import lens_profile as L                                        # noqa: E402

HARNESS = """
import fs from 'fs';
const html = fs.readFileSync(process.argv[2], 'utf8');
const src = html.slice(html.indexOf("'use strict';"), html.lastIndexOf('const drop ='));
const modes = fs.readFileSync(process.argv[3], 'utf8');
// The page's script talks to a document; give it just enough of one that the
// pure functions can be reached without a browser.
const shim = `const $=()=>({value:"",focus(){}});const takes={appendChild(){}};`;
const body = modes + shim
  + src.replace("const $ = s => document.querySelector(s);", '')
       .replace("const takes = $('#takes');", '')
  + '\\nexport {readCapture, gcsv, profile, jsonify};';
const tmp = process.argv[7];
fs.writeFileSync(tmp, body);
const {readCapture, gcsv, profile, jsonify} = await import('file://' + tmp);
const buf = fs.readFileSync(process.argv[4]);
const c = readCapture(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length), 'T');
fs.writeFileSync(process.argv[5], gcsv(c, false));
fs.writeFileSync(process.argv[5] + '.accel', gcsv(c, true));
fs.writeFileSync(process.argv[6], jsonify(profile(c, 'SIGMA 45mm F2.8 DG DN', 45)) + '\\n');
console.log(JSON.stringify({n: c.n, accel: c.aAt.length, mode: c.mode,
                            w: c.width, h: c.height, dropped: c.dropped,
                            period: c.periodS, gscale: c.gscale,
                            clip: c.clip, orientation: c.orientation}));
"""


def a_capture(gyro=900, accel_every=54, mode=106, w=1936, h=1090):
    """A .GYR the same shape the camera writes: header, then interleaved records.

    Values that vary per record and are not symmetric, so a reader that mixes up
    x and z, or reads the tag from the wrong halfword, cannot pass by accident.
    """
    body = bytearray()
    n = 0
    for i in range(gyro):
        body += struct.pack('<hhhh', i - 400, 2 * i - 900, gyr7.TAG_GYRO, 700 - i)
        n += 1
        if n % accel_every == 0:
            body += struct.pack('<hhhh', 1000 - i, i // 3, gyr7.TAG_ACCEL, i % 257 - 128)
    head = gyr7.HEADER.pack(b'GFS7', 7, 400085400, 0.000137923, 0x007A7978,
                            b'A001_037', 1, len(body), 0, mode, 16654, w, h)
    return head + bytes(body)


class WebConverter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil_which('node'):
            raise unittest.SkipTest('node is not installed; the web converter '
                                    'cannot be checked against the Python tools')
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        gyr = cls.tmp / 'A001_037.GYR'
        gyr.write_bytes(a_capture())
        harness = cls.tmp / 'h.mjs'
        harness.write_text(HARNESS)
        r = subprocess.run(
            ['node', str(harness), str(HERE / 'web' / 'index.html'),
             str(HERE / 'web' / 'modes.js'), str(gyr),
             str(cls.tmp / 'w.gcsv'), str(cls.tmp / 'w.json'),
             str(cls.tmp / 'page.mjs')],
            capture_output=True, text=True)
        if r.returncode:
            raise AssertionError('the page\'s script would not run:\n'
                                 + r.stdout + r.stderr)
        cls.summary = json.loads(r.stdout)
        cls.capture = gyr7.read_capture(gyr)

    def test_the_header_reads_the_same(self):
        s = self.summary
        c = self.capture
        self.assertEqual(s['clip'], c.clip)
        self.assertEqual(s['orientation'], c.orientation)
        self.assertEqual(s['n'], len(c.gyro))
        self.assertEqual(s['accel'], len(c.accel))
        self.assertEqual(s['mode'], c.sensor_mode)
        self.assertEqual((s['w'], s['h']), (c.width, c.height))
        self.assertEqual(s['dropped'], c.dropped)
        self.assertAlmostEqual(s['period'], c.period_s, places=15)
        self.assertAlmostEqual(s['gscale'], c.gscale, places=12)

    def test_the_gcsv_is_the_same_file(self):
        want = self.tmp / 'p.gcsv'
        gyr7.write_gcsv(want, self.capture)
        self.assertEqual((self.tmp / 'w.gcsv').read_bytes(), want.read_bytes())

    def test_the_gcsv_with_gravity_is_the_same_file(self):
        want = self.tmp / 'p_accel.gcsv'
        gyr7.write_gcsv(want, self.capture, accel=True)
        self.assertEqual((self.tmp / 'w.gcsv.accel').read_bytes(), want.read_bytes())

    def test_the_lens_profile_is_the_same_file(self):
        mode = dict(next(m for m in L.load_modes()
                         if int(m['mode_id']) == self.capture.sensor_mode))
        mode['mode_id'] = int(mode['mode_id'])
        want = json.dumps(L.build_profile(mode, 'SIGMA 45mm F2.8 DG DN',
                                          self.capture.width, self.capture.height,
                                          mode['fps'], 45.0),
                          indent=2, ensure_ascii=False) + '\n'
        self.assertEqual((self.tmp / 'w.json').read_text(), want)

    def test_the_mode_table_is_the_firmwares(self):
        """web/modes.js is generated from lens_profile.load_modes().  If it goes
        stale, every profile the page writes carries the wrong readout time."""
        js = (HERE / 'web' / 'modes.js').read_text()
        web = json.loads(js[js.index('['):js.rindex(']') + 1])
        py = {int(m['mode_id']): m for m in L.load_modes()}
        self.assertEqual(len(web), len(py))
        for m in web:
            p = py[m['mode_id']]
            for k in ('readout_w', 'readout_h', 'bin_h', 'bin_v', 'covered_w',
                      'covered_h', 'fps', 'readout_ms', 'bits'):
                self.assertEqual(m[k], p[k], f'mode {m["mode_id"]} {k}')


def shutil_which(x):
    import shutil
    return shutil.which(x)


if __name__ == '__main__':
    unittest.main(verbosity=2)
