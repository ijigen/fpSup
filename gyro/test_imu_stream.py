#!/usr/bin/env python3
"""The format is only worth what both producers agree on.

Half of these read the assembly rather than run it.  The bugs this file exists
to catch -- a record shape that drifts between the two hooks, a producer that
keeps its own copy of the index, an odd push -- are all things that assemble
cleanly and are found on the camera or not at all.
"""
import re
import struct
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

import imu_stream as S                                         # noqa: E402
from armasm import assemble                                    # noqa: E402

ACCEL = (HERE / 'accel_hook.S').read_text()
GYRO = (HERE / 'gyro_stream_hook.S').read_text()
INC = (HERE / 'imu_stream.inc.S').read_text()


def equ(name, src=INC):
    m = re.search(rf'^\.equ\s+{name},\s*([^\s/@]+)', src, re.M)
    if not m:
        raise AssertionError(f'no .equ {name}')
    return m.group(1).rstrip(',')


class Header(unittest.TestCase):
    def test_tags_are_what_the_reader_expects(self):
        self.assertEqual(int(equ('TAG_GYRO'), 0), S.TAG_GYRO)
        self.assertEqual(int(equ('TAG_ACCEL'), 0), S.TAG_ACCEL)

    def test_stream_is_a_power_of_two_of_eight_byte_records(self):
        n = int(equ('STREAM_COUNT'), 0)
        self.assertEqual(n & (n - 1), 0, 'the mask assumes a power of two')

    def test_both_producers_take_the_header_rather_than_a_copy(self):
        for name, src in (('accel_hook.S', ACCEL), ('gyro_stream_hook.S', GYRO)):
            self.assertIn('#include "imu_stream.inc.S"', src, name)
            # A literal stream address in a producer is a second source of truth.
            for bad in ('0xC072E1F8', '0xC072E200'):
                self.assertNotIn(bad, src.split('*/')[-1], f'{name} hardcodes {bad}')


class RecordShape(unittest.TestCase):
    """x at 0, y at 2, tag at 4, z at 6 -- in both producers, or neither works."""

    def offsets(self, src):
        body = src[src.index('push'):]
        got = {}
        for m in re.finditer(r'strh\s+r\d+,\s*\[r\d+(?:,\s*#(\d+))?\]', body):
            got.setdefault(int(m.group(1) or 0), 0)
            got[int(m.group(1) or 0)] += 1
        return got

    def test_four_halfwords_each(self):
        for name, src in (('accel', ACCEL), ('gyro', GYRO)):
            self.assertEqual(sorted(self.offsets(src)), [0, 2, 4, 6], name)

    def test_tag_is_written_last(self):
        """A reader that catches a half-written record sees the old tag, not a
        new payload under an old one."""
        for name, src in (('accel', ACCEL), ('gyro', GYRO)):
            body = src[src.index('push'):]
            stores = [int(m.group(1) or 0) for m in
                      re.finditer(r'strh\s+r\d+,\s*\[r\d+(?:,\s*#(\d+))?\]', body)]
            self.assertEqual(stores[-1], 4, f'{name} does not publish with the tag')

    def test_records_are_indexed_eight_bytes_apart(self):
        for name, src in (('accel', ACCEL), ('gyro', GYRO)):
            self.assertRegex(src, r'lsl\s+#3', f'{name} does not stride by eight')


class Assembly(unittest.TestCase):
    def words(self, path):
        code = assemble(HERE / path)
        return struct.unpack(f'<{len(code)//4}I', code)

    def test_pushes_are_even(self):
        """An odd push misaligns the stack and the firmware's LDRD takes a data
        abort -- which freezes the camera, not the hook."""
        for path in ('accel_hook.S', 'gyro_stream_hook.S'):
            for w in self.words(path):
                if (w & 0x0FFF0000) == 0x092D0000:              # push {reglist}
                    self.assertEqual(bin(w & 0xFFFF).count('1') % 2, 0,
                                     f'{path} pushes an odd number')

    def test_gyro_runs_the_displaced_call_first(self):
        """The firmware's own blx belongs where the firmware had it, before our
        copy, not tail-branched after it."""
        w = self.words('gyro_stream_hook.S')
        self.assertEqual(w[0] & 0x0FFF0000, 0x092D0000, 'first word is not a push')
        self.assertEqual(w[3], 0xE12FFF3C, 'the second thing done is not blx ip')
        self.assertEqual(w[4], 0xE58D0000, 'its result is not saved over r0')

    def test_accel_ends_with_the_displaced_instruction(self):
        w = self.words('accel_hook.S')
        self.assertEqual(w[-2], 0xE1D410F0, 'ldrsh r1, [r4] is not there')
        self.assertEqual(w[-1], 0xE12FFF1E, 'bx lr is not there')

    def test_both_fit_where_they_are_put(self):
        import imu_stream_deploy as D
        D._check_header()
        D._place()                      # raises on overlap or on leaving the cave


class Reader(unittest.TestCase):
    def blob(self, *recs):
        return b''.join(struct.pack('<hhhh', *r) for r in recs)

    def test_position_is_time(self):
        b = self.blob((1, 2, 0, 3), (4, 5, 0, 6), (7, 8, 0, 9))
        r = S.rows(S.records(b))
        self.assertEqual([t for t, _, _ in r], [0.0, 400.0, 800.0])

    def test_accel_does_not_advance_time(self):
        b = self.blob((1, 1, 0, 1), (9, 9, 1, 9), (2, 2, 0, 2))
        r = S.rows(S.records(b))
        self.assertEqual([t for t, _, _ in r], [0.0, 400.0])
        self.assertIsNone(r[0][2])
        self.assertEqual(r[1][2], (9, 9, 9))

    def test_a_leading_accel_lands_on_the_first_row(self):
        b = self.blob((9, 9, 1, 9), (1, 1, 0, 1))
        r = S.rows(S.records(b))
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0][2], (9, 9, 9))

    def test_a_gyro_sample_and_an_accel_sample_are_the_same_size(self):
        self.assertEqual(len(self.blob((0, 0, 0, 0))),
                         len(self.blob((0, 0, 1, 0))))
        self.assertEqual(S.RECORD, 8)

    def test_an_unknown_tag_is_refused_rather_than_guessed(self):
        with self.assertRaises(ValueError):
            S.rows(S.records(self.blob((0, 0, 7, 0))))

    def test_a_short_buffer_is_refused(self):
        with self.assertRaises(ValueError):
            S.records(b'\0' * 12)

    def test_summary_counts_the_interleave(self):
        recs = S.records(self.blob(*([(0, 0, 0, 0)] * 53 + [(0, 0, 1, 0)])))
        s = S.summary(recs)
        self.assertEqual((s['gyro'], s['accel']), (53, 1))
        self.assertAlmostEqual(s['duration_us'], 53 * 400)


if __name__ == '__main__':
    unittest.main(verbosity=2)
