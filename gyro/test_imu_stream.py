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
TRIG = (HERE / 'rec_trigger.S').read_text()
VD = (HERE / 'vd_hook.S').read_text()
INC = (HERE / 'imu_stream.inc.S').read_text()

# Who may append to the stream, and who may not.  Only a hook that lays
# samples down in the order the coprocessor made them can claim a position;
# everything else measures into state words.
WRITERS = (('accel', ACCEL), ('gyro', GYRO))
MARKERS = (('vd', VD), ('trigger', TRIG))


def equ(name, src=INC):
    m = re.search(rf'^\.equ\s+{name},\s*([^\s/@]+)', src, re.M)
    if not m:
        raise AssertionError(f'no .equ {name}')
    return m.group(1).rstrip(',')


class Header(unittest.TestCase):
    def test_tags_are_what_the_reader_expects(self):
        self.assertEqual(int(equ('TAG_GYRO'), 0), S.TAG_GYRO)
        self.assertEqual(int(equ('TAG_ACCEL'), 0), S.TAG_ACCEL)
        self.assertEqual(int(equ('TAG_START'), 0), S.TAG_START)
        self.assertEqual(int(equ('TAG_STOP'), 0), S.TAG_STOP)
        self.assertEqual(int(equ('TAG_VD'), 0), S.TAG_VD)

    def test_stream_is_a_power_of_two_of_eight_byte_records(self):
        n = int(equ('STREAM_COUNT'), 0)
        self.assertEqual(n & (n - 1), 0, 'the mask assumes a power of two')

    def test_both_producers_take_the_header_rather_than_a_copy(self):
        for name, src in (('accel_hook.S', ACCEL), ('gyro_stream_hook.S', GYRO),
                          ('rec_trigger.S', TRIG),
                          ('vd_hook.S', VD)):
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
        for name, src in WRITERS:
            self.assertEqual(sorted(self.offsets(src)), [0, 2, 4, 6], name)

    def test_tag_is_written_last(self):
        """A reader that catches a half-written record sees the old tag, not a
        new payload under an old one."""
        for name, src in WRITERS:
            body = src[src.index('push'):]
            stores = [int(m.group(1) or 0) for m in
                      re.finditer(r'strh\s+r\d+,\s*\[r\d+(?:,\s*#(\d+))?\]', body)]
            self.assertEqual(stores[-1], 4, f'{name} does not publish with the tag')

    def test_neither_producer_touches_the_ring_when_nothing_records(self):
        """The shipping logger's drain sits behind the recording flag and an
        idle callback returns without reading a byte.  The rewrite dropped that
        and 013e12f only restored the doorbell half; this is the other half.
        Both gates must come before the producer claims anything."""
        for name, src in WRITERS:
            body = src[src.index('push'):]
            gate = body.index('T_WANT')
            self.assertLess(gate, body.index('ldrex'),
                            f'{name} claims a slot before checking for a take')

    def test_the_gyro_gate_still_reaches_the_doorbell(self):
        """Skipping the whole hook would leave the take's file open for ever:
        the stop job is posted from the tail, precisely when T_WANT has just
        gone to zero.  The gate must branch INTO the tail, not past it."""
        body = GYRO[GYRO.index('push'):]
        self.assertIn('beq     8f', body, 'the gate does not branch to the tail')
        tail = body.index('\n8:')
        self.assertLess(tail, body.index('STREAM_SIGFN'),
                        'the tail label is not before the doorbell')
        self.assertLess(body.index('T_STOPSENT'), body.index('STREAM_SIGFN'))

    def test_record_start_anchors_the_gyro_cursor(self):
        """With no idle drain the cursor is stale by however long the camera
        sat, and a stale cursor is a WRAPPED one -- indistinguishable from a
        normal wrap.  The start hook has to latch the head itself."""
        # the start half is what #ifndef REC_STOP selects
        start = TRIG.split('#ifndef REC_STOP')[1].split('#endif')[0]
        self.assertIn('STREAM_GHEAD', start, 'the start hook does not anchor it')
        self.assertLess(start.index('STREAM_R0_HEAD'), start.index('STREAM_GHEAD'))
        self.assertNotIn('STREAM_GHEAD',
                         TRIG.split('#ifdef REC_STOP')[1].split('#else')[0],
                         'the stop hook must not move the cursor')

    def test_every_stop_closes_the_exposure_census(self):
        """VPREV is a gate, not a latch.  The take-scoped latches must not be
        redefined by a second take, but leaving this one open after one lets
        liveview Vd -- 59.94 Hz, 42-sample gaps -- pour into the census as
        'doubled interrupts'.  The start side re-arms every take; so must this."""
        body = TRIG[TRIG.index('rec_trigger:'):]
        first_only = body.index('bne     2f')
        rearm = body.index('\n2:')
        self.assertGreater(body.index('STREAM_VPREV'), rearm,
                           'the VPREV freeze is still inside the first-one-only block')
        self.assertLess(first_only, rearm)

    def test_the_job_leaves_the_kernels_word_alone(self):
        """tk_snd_mbx takes a message beginning with T_MSG -- the kernel's queue
        link at offset 0, which it writes while the message is queued.  The
        audio writer's descriptor starts its fields at +4 for exactly this
        reason.  Ours had J_PTR on that word: a ring address in the kernel's
        list pointer, and a list pointer where the writer read its source."""
        self.assertEqual(int(equ('J_MSGQ'), 0), 0)
        for name in ('J_PTR', 'J_LEN', 'J_STOP', 'J_SEQ'):
            self.assertGreaterEqual(int(equ(name), 0), 4,
                                    f'{name} is on the kernel word')
        task = (HERE / 'ring_task.S').read_text()
        self.assertNotIn('J_MSGQ]', task, 'something writes the kernel word')

    def test_the_markers_append_nothing_to_the_stream(self):
        """A marker appended from outside the gyro producer lands where the last
        drain left the index, 0-20 ms before it belongs -- most of a frame, on a
        thing whose whole job is to say which frame.  Both marker hooks measure
        with the coprocessor's head instead, into state words, and claim no
        position.  They may append again when the drain moves into the producers
        and the position becomes true by construction, not before."""
        for name, src in MARKERS:
            body = src[src.index('push'):]
            self.assertNotIn('ring_slot', body, name)
            self.assertNotIn('ldrex', body, f'{name} still claims a stream slot')
            # \b, because strhi and strlo are conditional word stores and the
            # Vd hook is full of them.
            self.assertIsNone(re.search(r'strh\s+r\d+,\s*\[', body),
                              f'{name} still writes a record')
        self.assertIn('gyro_head', VD[VD.index('push'):], 'vd stopped measuring')
        self.assertIn('gyro_head', TRIG[TRIG.index('push'):],
                      'the record trigger stopped measuring')

    def test_records_are_indexed_eight_bytes_apart(self):
        """The stride now lives in the ring_slot macro, so check it there -- and
        check every producer either uses the macro or carries its own stride,
        so a fifth copy of the arithmetic cannot appear unnoticed."""
        macro = INC[INC.index('.macro ring_slot'):INC.index('.endm', INC.index('.macro ring_slot'))]
        self.assertRegex(macro, r'lsl\s+#3', 'ring_slot does not stride by eight')
        for name, src in WRITERS:
            body = src[src.index('push'):]
            self.assertTrue('ring_slot' in body or re.search(r'lsl\s+#3', body),
                            f'{name} indexes the ring by neither route')


class Assembly(unittest.TestCase):
    def words(self, path):
        code = assemble(HERE / path)
        return struct.unpack(f'<{len(code)//4}I', code)

    def test_no_frame_leaves_the_stack_misaligned(self):
        """The stack must stay eight-byte aligned, full stop.

        This was weakened once to "misaligned AND calls something", on the
        reasoning that a leaf function cannot reach a firmware LDRD.  The
        camera disagreed: mpool_free was a leaf, pushed five registers, and
        wedged it; pushing four fixed it and the same probe then ran clean
        through every stage.  The window is the interrupt taken before the
        function masks them -- the context save lands on the interrupted
        task's own stack.  The mutation test had already shown the weakened
        guard could not catch it, and that should have been the end of the
        argument.

        A push may still be odd if a `sub sp` in the same prologue makes the
        total a multiple of eight -- gcsvgen's put_uint_many pushes five and
        subtracts twelve.  And a frame that reproduces a hooked function's own
        prologue is the firmware's alignment, not ours; it says so on the line.
        """
        for path in sorted(HERE.glob('*.S')):
            lines = path.read_text().splitlines()
            for n, line in enumerate(lines):
                m = re.match(r'\s*push\s*\{([^}]*)\}', line)
                if not m or 'displaced' in line:
                    continue
                regs = 0
                for part in m.group(1).split(','):
                    part = part.strip()
                    rng = re.match(r'r(\d+)\s*-\s*r(\d+)$', part)
                    regs += int(rng.group(2)) - int(rng.group(1)) + 1 if rng else 1
                total = regs * 4
                for follow in lines[n + 1:n + 4]:
                    sub = re.match(r'\s*sub\s+sp,\s*sp,\s*#(\d+)', follow)
                    if sub:
                        total += int(sub.group(1))
                        break
                    if follow.strip().startswith(('push', 'pop', 'bl', 'bx', 'b ')):
                        break
                self.assertEqual(total % 8, 0,
                                 f'{path.name}:{n + 1} pushes {regs} registers, '
                                 f'leaving the stack at {total}: {line.strip()}')

    def test_pushes_are_even(self):
        """An odd push misaligns the stack and the firmware's LDRD takes a data
        abort -- which freezes the camera, not the hook."""
        for path in ('accel_hook.S', 'gyro_stream_hook.S', 'rec_trigger.S', 'vd_hook.S'):
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

    def test_the_accel_measurement_is_off_by_default(self):
        """A bisect with two variables in it is not a bisect.  Without the flag
        the hook must be the same bytes it was before the counters existed:
        the flag inserts a block after the push and changes nothing else."""
        self.assertIn('#ifdef ACC_MEASURE', ACCEL)
        plain = assemble(HERE / 'accel_hook.S', ())
        measured = assemble(HERE / 'accel_hook.S', ('ACC_MEASURE',))
        self.assertGreater(len(measured), len(plain))
        self.assertEqual(measured[:4], plain[:4], 'the push moved')
        self.assertEqual(measured[-(len(plain) - 4):], plain[4:],
                         'the flag changed the work, not just added to it')

    def test_only_the_accel_hook_writes_its_own_cursor(self):
        """ACC_GHEAD carries no exclusive, so it is only correct while exactly
        one producer advances it.  The day the drain moves into this hook, that
        stops being true of STREAM_GHEAD too -- this test is the tripwire."""
        for path in ('gyro_stream_hook.S', 'rec_trigger.S', 'vd_hook.S'):
            src = (HERE / path).read_text()
            self.assertNotIn('ACC_', src,
                             f'{path} touches the accel hook\'s private counters')
        self.assertIn('ACC_O_GHEAD', ACCEL)

    def test_the_gap_measurement_cannot_report_a_negative(self):
        """The head is a byte offset that wraps at GYRO_RING_SPAN, so a visit
        that straddles a wrap must add the span back, not produce a huge
        unsigned number."""
        self.assertIn('movwlo', ACCEL)
        self.assertIn('GYRO_RING_SPAN', ACCEL)

    def test_all_of_them_fit_where_they_are_put(self):
        import imu_stream_deploy as D
        D._check_header()
        D._place()                      # raises on overlap or on leaving the cave


class Reader(unittest.TestCase):
    def blob(self, *recs):
        return b''.join(struct.pack('<hhhh', *r) for r in recs)

    def test_position_is_time(self):
        b = self.blob((1, 2, 0, 3), (4, 5, 0, 6), (7, 8, 0, 9))
        r = S.rows(S.records(b))
        self.assertEqual([t for t, _, _, _ in r], [0.0, 400.0, 800.0])

    def test_accel_does_not_advance_time(self):
        b = self.blob((1, 1, 0, 1), (9, 9, 1, 9), (2, 2, 0, 2))
        r = S.rows(S.records(b))
        self.assertEqual([t for t, _, _, _ in r], [0.0, 400.0])
        self.assertIsNone(r[0][2])
        self.assertEqual(r[1][2], (9, 9, 9))

    def test_a_frame_marker_does_not_advance_time_either(self):
        b = self.blob((1, 1, 0, 1), (7, 0, 2, 0), (2, 2, 0, 2), (3, 3, 0, 3))
        r = S.rows(S.records(b))
        self.assertEqual([t for t, _, _, _ in r], [0.0, 400.0, 800.0])
        self.assertIsNone(r[0][3])
        self.assertEqual(r[1][3], ('frame', 7), 'the frame lands on the row after it')
        self.assertIsNone(r[2][3])

    def test_frame_spacing_counts_gyro_between_markers(self):
        recs = S.records(self.blob(
            (0, 0, 2, 0), *([(0, 0, 0, 0)] * 83), (1, 0, 2, 0),
            *([(0, 0, 0, 0)] * 84), (2, 0, 2, 0)))
        gaps, mean = S.frame_spacing(recs)
        self.assertEqual(gaps, [83, 84], 'each gap must be visible, not averaged away')
        self.assertAlmostEqual(mean, 83.5)

    def test_frame_spacing_ignores_accel_records(self):
        recs = S.records(self.blob(
            (0, 0, 2, 0), (0, 0, 0, 0), (9, 9, 1, 9), (0, 0, 0, 0), (1, 0, 2, 0)))
        gaps, _ = S.frame_spacing(recs)
        self.assertEqual(gaps, [2])

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

    def test_no_hook_sits_on_a_function_entry(self):
        """Every one of these functions saves lr in its first instruction, so a
        bl there would put our return address in the function's own frame.  Each
        site must be past the push -- and past the early returns, or a take that
        bails out would look like a take that started."""
        import imu_stream_deploy as D
        entries = {0xC0315C10, 0xC01FB640, 0xC01FB918, 0xC050D250, 0xC01FD380,
                   0xC0125478}
        for name, (_at, _src, _d, site, _orig, _t) in D.PRODUCERS.items():
            self.assertNotIn(site, entries, f'{name} is on a function entry')

    def test_every_hook_declares_the_site_it_is_deployed_to(self):
        import imu_stream_deploy as D
        D._check_header()                # raises if a source and the table drift

    def test_the_thumb_branch_matches_the_firmware_layout(self):
        """A Thumb BLX splits its immediate over two halfwords with J1/J2 derived
        from the sign; getting it wrong branches into the middle of something
        rather than faulting.  So the layout is fixed against a branch the
        camera itself executes -- the bl at 0xC0125494, which the decompilation
        names FUN_c0128e50 -- and the encoder is round-tripped through it."""
        import struct as _s
        import imu_stream_deploy as D
        fw = Path('/Users/dido/Developer/SIGMAfp_re/out/MAIN_c0000000.bin')
        if not fw.exists():
            self.skipTest('no firmware image')
        blob = fw.read_bytes()

        def decode(site, hw1, hw2):
            sgn = (hw1 >> 10) & 1
            j1, x, j2 = (hw2 >> 13) & 1, (hw2 >> 12) & 1, (hw2 >> 11) & 1
            i1, i2 = (~(j1 ^ sgn)) & 1, (~(j2 ^ sgn)) & 1
            off = ((sgn << 24) | (i1 << 23) | (i2 << 22)
                   | ((hw1 & 0x3FF) << 12) | ((hw2 & 0x7FF) << 1))
            if sgn:
                off -= 1 << 25
            return ('bl' if x else 'blx'), (site + 4 if x else (site + 4) & ~3) + off

        anchor = 0xC0125494
        hw1, hw2 = _s.unpack_from('<HH', blob, anchor - 0xC0000000)
        self.assertEqual(decode(anchor, hw1, hw2), ('bl', 0xC0128E50))

        site, target = 0xC0125480, D.PRODUCERS['vd'][0]
        word = D.branch_word(site, target, 1)
        got = decode(site, word & 0xFFFF, word >> 16)
        self.assertEqual(got, ('blx', target))

    def test_the_vd_site_is_what_the_firmware_still_has(self):
        import struct as _s
        import imu_stream_deploy as D
        fw = Path('/Users/dido/Developer/SIGMAfp_re/out/MAIN_c0000000.bin')
        if not fw.exists():
            self.skipTest('no firmware image')
        site, orig = D.PRODUCERS['vd'][3], D.PRODUCERS['vd'][4]
        have = _s.unpack_from('<I', fw.read_bytes(), site - 0xC0000000)[0]
        self.assertEqual(have, orig, 'the Vd site is not the word we expect')

    def test_the_two_triggers_share_one_source(self):
        """Start and stop differ by four lines; two files would drift."""
        import imu_stream_deploy as D
        self.assertEqual(D.PRODUCERS['start'][1], D.PRODUCERS['stop'][1])
        self.assertEqual(D.PRODUCERS['stop'][2], ('REC_STOP',))

    def test_a_short_buffer_is_refused(self):
        with self.assertRaises(ValueError):
            S.records(b'\0' * 12)

    def test_summary_counts_the_interleave(self):
        recs = S.records(self.blob(*([(0, 0, 0, 0)] * 53 + [(0, 0, 1, 0)])))
        s = S.summary(recs)
        self.assertEqual((s['gyro'], s['accel'], s['frame']), (53, 1, 0))
        self.assertEqual((s['start'], s['stop']), (0, 0))
        self.assertAlmostEqual(s['duration_us'], 53 * 400)


if __name__ == '__main__':
    unittest.main(verbosity=2)
