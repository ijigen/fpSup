#!/usr/bin/env python3
"""The camera's row rules, checked against the shipped reader.

gcsv_rows.S is assembly and cannot be run here, but its rules can be: hold a
row back by one record so a reading lands on the sample it followed, never
leave a trailing comma, carry the held row across a block boundary, and turn
the accelerometer's axes a quarter of the way round.  Each of those is a way to
produce a file that opens in Gyroflow and is quietly wrong -- ",," alone parses
as three zeroes -- so each of them is checked against gyr7.py, which is the
answer the host tools already give.

The transliteration below has to be kept in step with gcsv_rows.S by hand.
That is worth saying out loud: it proves the rules, not the instructions.
"""
import pathlib
import struct
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gyr7                                                     # noqa: E402

TAG_GYRO, TAG_ACCEL = 0, 1
BLOCK_RECORDS = 2048            # 16 KiB of eight-byte records


def camera(records, block_records=BLOCK_RECORDS):
    """gcsv_format's control flow, block by block, with state that survives one."""
    held, t, out = None, 0, []

    def emit(sample, reading):
        nonlocal t
        row = f'{t},{sample[0]},{sample[1]},{sample[2]}'
        if reading is not None:
            # The quarter turn: native Y is gcsv X, native X negated is gcsv Y.
            row += f',{reading[1]},{-reading[0]},{reading[2]}'
        t += 1
        out.append(row)

    for i in range(0, len(records), block_records):     # one writer wake each
        for x, y, tag, z in records[i:i + block_records]:
            if tag == TAG_GYRO:
                if held is not None:
                    emit(held, None)
                held = (x, y, z)
            elif held is not None:
                emit(held, (x, y, z))
                held = None
    if held is not None:                                # gcsv_last, at the stop
        emit(held, None)
    return out


def a_stream(n=5000, every=54):
    """Shaped like the real one, and deliberately arranged so block boundaries
    fall between a sample and the reading that follows it."""
    recs = []
    for i in range(n):
        recs.append((i - 2000, 2 * i - 3000, TAG_GYRO, 900 - i))
        if i % every == every - 1:
            recs.append((1000 - i, i // 3, TAG_ACCEL, i % 257 - 128))
    return recs


class Rows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs = a_stream()
        cls.rows = camera(cls.recs)
        body = b''.join(struct.pack('<hhhh', *r) for r in cls.recs)
        hdr = gyr7.HEADER.pack(b'GFS7', 7, 400085400, 0.000137923, 0x007A7978,
                               b'A001_037', 1, len(body), 0, 106, 16654, 1936, 1090)
        p = pathlib.Path(tempfile.mkdtemp()) / 'A001_037.GYR'
        p.write_bytes(hdr + body)
        cls.capture = gyr7.read_capture(p)

    def test_every_sample_gets_exactly_one_row(self):
        self.assertEqual(len(self.rows), len(self.capture.gyro))

    def test_the_gyro_columns_are_the_readers(self):
        for i, (row, want) in enumerate(zip(self.rows, self.capture.gyro)):
            f = row.split(',')
            self.assertEqual((int(f[0]), int(f[1]), int(f[2]), int(f[3])),
                             (i,) + want, f'row {i}')

    def test_no_row_ends_in_a_comma(self):
        """",," is not three blanks, it is three zeroes, and Gyroflow will use
        them.  A row with no reading has to end after gz."""
        self.assertFalse([r for r in self.rows if r.endswith(',')])
        for r in self.rows:
            self.assertIn(r.count(','), (3, 6), r)

    def test_a_reading_lands_on_the_sample_it_followed(self):
        carrying = [(i, r) for i, r in enumerate(self.rows) if r.count(',') == 6]
        self.assertEqual(len(carrying), len(self.capture.accel))
        for (i, r), (at, ax, ay, az) in zip(carrying, self.capture.accel):
            # The reader indexes a reading by the sample count before it, so the
            # row it belongs on is the one before that.
            self.assertEqual(i, at - 1)
            f = r.split(',')
            self.assertEqual((int(f[4]), int(f[5]), int(f[6])), (ay, -ax, az))

    def test_a_row_held_at_a_block_boundary_survives_it(self):
        """A sample can be the last record of one block and its reading the
        first of the next.  If the held row did not cross, that reading would
        be dropped and the sample would go out plain -- silently."""
        for block in (2048, 53, 54, 55, 7, 1):
            self.assertEqual(camera(self.recs, block), self.rows,
                             f'the rows change when a block holds {block} records')


if __name__ == '__main__':
    unittest.main(verbosity=2)
