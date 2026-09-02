#!/usr/bin/env python3
"""Exact-output tests for the on-camera decimal fast path."""
import random
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "fp_usb_shell"))

from armasm import assemble, symbols  # noqa: E402


MAGIC_100 = 0x51EB851F
PAIRS = tuple(f"{n:02d}" for n in range(100))
QUADS = tuple(f"{n:04d}" for n in range(10_000))


def div100_magic(value: int) -> tuple[int, int]:
    quotient = (value * MAGIC_100) >> 37
    return quotient, value - quotient * 100


def camera_uint(value: int) -> str:
    assert 0 <= value <= 0xFFFFFFFF
    if value < 10:
        return chr(ord("0") + value)
    if value < 100:
        return PAIRS[value]
    tail = []
    while value >= 100:
        value, remainder = div100_magic(value)
        tail.append(PAIRS[remainder])
    head = chr(ord("0") + value) if value < 10 else PAIRS[value]
    return head + "".join(reversed(tail))


def camera_i16(value: int) -> str:
    """Model the exact 0000..9999 table path used by put_i16."""

    assert -32768 <= value <= 32768
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value < 10:
        return sign + chr(ord("0") + value)
    if value < 100:
        return sign + QUADS[value][2:]
    if value < 1000:
        return sign + QUADS[value][1:]
    if value < 10_000:
        return sign + QUADS[value]

    lead = 0
    while value >= 10_000:
        lead += 1
        value -= 10_000
    return sign + chr(ord("0") + lead) + QUADS[value]


def camera_gyro3(record_words: tuple[int, int, int, int]) -> str:
    """The fused native record path uses words X, Y, pad, Z."""

    return "".join(camera_i16(record_words[index]) + ","
                   for index in (0, 1, 3))


def camera_accel_fragment(native_x: int, native_y: int, native_z: int) -> str:
    """The cached GCSV axis mapping used by the streaming assembly."""
    return ",".join((camera_i16(native_y), camera_i16(-native_x),
                     camera_i16(native_z)))


class DecimalFastPathTests(unittest.TestCase):
    def test_every_sensor_value_is_identical_to_decimal(self):
        for value in range(-32768, 32769):
            self.assertEqual(camera_i16(value), str(value), value)

    def test_unsigned_timestamp_boundaries_and_random_values(self):
        values = {
            0, 1, 9, 10, 11, 99, 100, 101, 999, 1000, 9999, 10000,
            0x7FFFFFFF, 0x80000000, 3_600_000_000, 0xFFFFFFFF,
        }
        rng = random.Random(0xF502)
        values.update(rng.randrange(0x100000000) for _ in range(100_000))
        for value in values:
            self.assertEqual(camera_uint(value), str(value), value)

    def test_one_hour_is_not_formatted_as_a_negative_timestamp(self):
        self.assertEqual(camera_uint(3_600_000_000), "3600000000")

    def test_cached_accel_fragment_preserves_axis_mapping_and_extremes(self):
        cases = (
            (0, 0, 0),
            (-32768, -32768, -32768),
            (32767, 32767, 32767),
            (-1001, -40, -71),
        )
        for native_x, native_y, native_z in cases:
            expected = f"{native_y},{-native_x},{native_z}"
            self.assertEqual(
                camera_accel_fragment(native_x, native_y, native_z), expected
            )

    def test_fused_gyro_formatter_preserves_offsets_and_trailing_commas(self):
        cases = (
            (0, 0, 12345, 0),
            (-32768, 32767, -22222, 32767),
            (9, 10, 11111, 99),
            (100, 999, -11111, 1000),
        )
        rng = random.Random(0xA023)
        cases += tuple(tuple(rng.randrange(-32768, 32768) for _ in range(4))
                       for _ in range(10_000))
        for record in cases:
            expected = f"{record[0]},{record[1]},{record[3]},"
            self.assertEqual(camera_gyro3(record), expected, record)

    def test_assembled_quad_table_contains_every_exact_entry(self):
        defines = ("FPGYRO_NATIVE_LIFECYCLE", "FPGYRO_GCSV_STREAM")
        code = assemble(HERE / "gcsvgen.S", defines)
        start = symbols(HERE / "gcsvgen.S", defines)["dec_quads"]
        expected = "".join(QUADS).encode("ascii")
        self.assertEqual(len(expected), 40_000)
        self.assertEqual(code[start:start + len(expected)], expected)

    def test_assembly_uses_the_bounded_specialised_entries(self):
        source = (HERE / "gcsvgen.S").read_text()
        # Streaming fuses only the three 2500 Hz gyro columns.  The low-rate
        # accel refresh and post-read path retain the bounded single-value entry.
        self.assertEqual(source.count("bl      put_uint"), 2)
        self.assertEqual(source.count("bl      put_i16"), 9)
        self.assertEqual(source.count("bl      put_gyro3"), 1)
        self.assertNotIn("bl      put_int", source)
        i16 = source[source.index("put_i16:"):source.index("dec_pairs:")]
        self.assertNotIn("push", i16)
        self.assertNotIn("pop", i16)
        self.assertNotIn("umull", i16)
        self.assertNotIn("mls", i16)
        self.assertIn("dec_quads", i16)
        self.assertIn(".rept   10000", source)


def model_stream_rows(block_first, samples, accels):
    """Mirror the on-camera gcsv_stream_sample loop exactly (2-tap decimation to
    1250 Hz + sparse accel).  samples: [(x,y,pad,z)...]; accels: [(t,ax,ay,az)...]
    already take-relative and sorted.  Returns list of formatted GCSV rows."""
    rows = []
    r9 = block_first
    i = 0
    ai = 0
    dirty = False
    held = None
    n = len(samples)
    while i < n:
        if n - i >= 2:
            s0, s1 = samples[i], samples[i + 1]
            avg = ((s0[0] + s1[0]) >> 1, (s0[1] + s1[1]) >> 1,
                   None, (s0[3] + s1[3]) >> 1)
            t = r9 + 200
            rec = avg
            step = 2
        else:
            s0 = samples[i]
            t = r9
            rec = s0
            step = 1
        # accel catchup up to r9 (loop bound is r9, matching the assembly)
        while ai < len(accels) and accels[ai][0] <= r9:
            held = accels[ai][1:]
            dirty = True
            ai += 1
        gy = camera_gyro3(rec)                  # 'gx,gy,gz,'  (trailing comma)
        if dirty and held is not None:
            frag = camera_accel_fragment(*held)  # 'ax,ay,az'
            row = f"{t}," + gy + frag
            dirty = False
        else:
            row = f"{t}," + gy[:-1]              # drop trailing comma -> gyro-only
        rows.append(row)
        r9 += 400 * step
        i += step
    return rows


class DecimationSparseTests(unittest.TestCase):
    def test_pair_average_midpoint_and_step(self):
        # Two samples 400us apart -> one row at midpoint, 2-tap average.
        samples = [(100, -200, 0, 300), (102, -198, 0, 306)]
        rows = model_stream_rows(0, samples, [])
        self.assertEqual(len(rows), 1)
        # midpoint timestamp 200, averaged x=101,y=-199,z=303, gyro-only (no accel)
        self.assertEqual(rows[0], "200,101,-199,303")

    def test_odd_tail_sample_emitted_unaveraged(self):
        samples = [(10, 20, 0, 30), (12, 22, 0, 32), (99, -99, 0, 50)]
        rows = model_stream_rows(0, samples, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], "200,11,21,31")   # pair midpoint
        self.assertEqual(rows[1], "800,99,-99,50")  # lone tail at r9 (0+800)

    def test_asr_rounds_toward_negative_infinity_like_the_asm(self):
        # (-1 + 0) >> 1 == -1, matching ARM asr, not truncation toward zero.
        samples = [(-1, -1, 0, -1), (0, 0, 0, 0)]
        rows = model_stream_rows(0, samples, [])
        self.assertEqual(rows[0], "200,-1,-1,-1")

    def test_sparse_accel_only_on_rows_with_a_new_sample(self):
        # Accel at t=0 seeds the first row (7 cols); later rows are gyro-only
        # until the next accel record arrives.
        samples = [(1, 2, 0, 3)] * 8   # 4 downsampled rows
        accels = [(0, 10, -20, 30), (900, 11, -21, 31)]
        rows = model_stream_rows(0, samples, accels)
        self.assertEqual(len(rows), 4)
        # row0 t=200: accel t=0<=r9(0) consumed -> 7 cols, mapping ay,-ax,az
        self.assertEqual(rows[0], "200,1,2,3,-20,-10,30")
        # row1 t=1000 (r9=800): accel t=900<=800? no -> gyro-only
        self.assertEqual(rows[1], "1000,1,2,3")
        # row2 t=1800 (r9=1600): accel t=900<=1600 consumed -> 7 cols
        self.assertEqual(rows[2], "1800,1,2,3,-21,-11,31")
        # row3 gyro-only again
        self.assertEqual(rows[3], "2600,1,2,3")

    def test_four_column_rows_never_have_a_trailing_comma(self):
        samples = [(5, 6, 0, 7)] * 6
        rows = model_stream_rows(0, samples, [])   # no accel -> all gyro-only
        for r in rows:
            self.assertFalse(r.endswith(","), r)
            self.assertEqual(r.count(","), 3, r)   # t,gx,gy,gz


def model_seam_blocks(blocks):
    """Mirror the seam rule: blocks = [(anchor_first_us, samples[, dropped_since_prev])].
    Continue the grid when no drop was counted since the previous block and the
    anchor is within the 10 ms guard; otherwise keep the anchor."""
    rows = []; expect = None
    for blk in blocks:
        anchor, samples = blk[0], blk[1]; dropped = blk[2] if len(blk) > 2 else False
        n = len(samples)
        first_row = anchor + 200 if n >= 2 else anchor
        r9 = anchor
        if expect is not None and not dropped and abs(first_row - expect) <= 65536:
            r9 = anchor - first_row + expect
        rs = model_stream_rows(r9, samples, [])
        rows += rs
        last_t = int(rs[-1].split(",")[0])
        expect = last_t + (800 if n % 2 == 0 else 600)
    return rows


class SeamContinuityTests(unittest.TestCase):
    S = (1, 1, 0, 1)
    def times(self, rows): return [int(r.split(",")[0]) for r in rows]
    def test_jittered_anchor_snaps_onto_the_grid(self):
        # even block of 4 -> rows 200,1000; next expected 1800; second anchor 500us late
        rows = model_seam_blocks([(0, [self.S]*4), (1600 + 500, [self.S]*4)])
        self.assertEqual(self.times(rows), [200, 1000, 1800, 2600])
    def test_odd_tail_makes_next_row_600_not_800(self):
        rows = model_seam_blocks([(0, [self.S]*3), (1200, [self.S]*4)])
        self.assertEqual(self.times(rows), [200, 800, 1400, 2200])
    def test_late_anchor_1200us_snaps(self):
        rows = model_seam_blocks([(0, [self.S]*4), (1600 + 1200, [self.S]*4)])
        self.assertEqual(self.times(rows), [200, 1000, 1800, 2600])
    def test_late_anchor_1800us_snaps(self):
        rows = model_seam_blocks([(0, [self.S]*4), (1600 + 1800, [self.S]*4)])
        self.assertEqual(self.times(rows), [200, 1000, 1800, 2600])
    def test_late_anchor_4900us_snaps(self):
        rows = model_seam_blocks([(0, [self.S]*4), (1600 + 4900, [self.S]*4)])
        self.assertEqual(self.times(rows), [200, 1000, 1800, 2600])
    def test_counted_drop_keeps_anchor_even_when_close(self):
        rows = model_seam_blocks([(0, [self.S]*4), (1600 + 300, [self.S]*4, True)])
        self.assertEqual(self.times(rows), [200, 1000, 2100, 2900])
    def test_late_anchor_11ms_snaps_when_no_drop(self):
        rows = model_seam_blocks([(0, [self.S]*4), (1600 + 11000, [self.S]*4)])
        self.assertEqual(self.times(rows), [200, 1000, 1800, 2600])
    def test_real_gap_is_preserved(self):
        rows = model_seam_blocks([(0, [self.S]*4), (1600 + 20000, [self.S]*4, True)])
        t = self.times(rows)
        self.assertEqual(t[:2], [200, 1000]); self.assertEqual(t[2] - t[1], 20800)
    def test_first_block_keeps_its_anchor(self):
        rows = model_seam_blocks([(5000, [self.S]*2)])
        self.assertEqual(self.times(rows), [5200])


if __name__ == "__main__":
    unittest.main()