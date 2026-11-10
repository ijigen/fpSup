#!/usr/bin/env python3
"""Offline tests for dc_probe.py: pure parsing on bytes/values recorded in the 2026-10-30 live2 run.  No camera.

    python3 -B test_dc_probe.py
"""
import json, pathlib, tempfile, unittest
import dc_probe as d

LIVE2 = d.HERE.parents[1] / 'validation/2026-10-30-v1-live2'


def live2_record(tag):
    for line in (LIVE2 / 'results.jsonl').read_text().splitlines():
        r = json.loads(line)
        if r.get('tag') == tag: return r
    raise KeyError(tag)


class T(unittest.TestCase):
    def test_load_log(self):
        text = (LIVE2 / 'LOAD-current.LOG').read_bytes().decode('latin1')
        self.assertEqual(d.parse_load_log(text), (0xC55F9D40, '0.7.1test'))
        with self.assertRaises(SystemExit): d.parse_load_log(text, '0.7.0test')
        with self.assertRaises(SystemExit): d.parse_load_log('0A C55BCC80 00000008 QSContainer_v0.3.1.BIN')

    def test_build_json(self):
        self.assertEqual(d.load_build('0.7.1test')['sq_test_off'], 0x7B61)
        self.assertEqual(d.load_build('0.7.0test')['sq_test_off'], 0x79DF)
        with self.assertRaises(SystemExit): d.load_build('9.9.9nope')
        with tempfile.TemporaryDirectory() as t:              # wrong file / missing key -> loud
            p = pathlib.Path(t) / 'b.json'
            p.write_text(json.dumps({'file': 'SensorLab-IMX410_v0.7.0test.BIN', 'sq_test_off': 1}))
            with self.assertRaises(SystemExit): d.load_build('0.7.1test', p)
            p.write_text(json.dumps({'file': 'SensorLab-IMX410_v0.7.1test.BIN'}))
            with self.assertRaises(SystemExit): d.load_build('0.7.1test', p)

    def test_row_address_wraps(self):
        # REGDESC base implied by the stock row (mode 12, idx 42); the virtual ids' rows wrap into the SL block
        base = (0xC0B667FC - 42 * d.ROW_BYTES) & 0xFFFFFFFF
        self.assertEqual(base, 0xC0B5FDAC)
        for tag, key in (('i14-preRec', 'regs'), ('i12-pre', 'regs'), ('i12-pre', 'regs_rec')):
            g = live2_record(tag)[key]
            self.assertEqual(hex(d.row_addr(base, g['idx'])), g['row'], (tag, key))

    def test_decode_row_i14(self):
        g = live2_record('i14-preRec')['regs']             # HD 2K 11b 3x2: V start 377, V size 851
        w = [g['id'], 0, g['r0003'], 0, 0, 0, g['r0022'], g['r0023'], g['r0024'], g['r0025']]
        out = d.decode_row(g['mode'], g['idx'], int(g['row'], 16), w)
        self.assertEqual(out, g)
        self.assertEqual((out['vstart'], out['vsize']), (377, 851))

    def test_decode_structs(self):
        r = live2_record('i14-preRec')
        for names, key in ((d.AP, 'ap'), (d.SEL, 'sel')):
            words = [v & 0xFFFFFFFF for v in r[key].values()]
            self.assertEqual(d.decode(names, words), r[key])
        self.assertEqual(d.s32(0xFFFFFFF9), -7)


if __name__ == '__main__':
    unittest.main(verbosity=1)
