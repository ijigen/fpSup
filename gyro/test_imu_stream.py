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
DRAIN = (HERE / 'gyro_drain.S').read_text()
TRIG = (HERE / 'rec_trigger.S').read_text()
INC = (HERE / 'imu_stream.inc.S').read_text()
SPACE = (HERE / 'stream_space.S').read_text()

# Who may append to the stream, and who may not.  Only a hook that lays
# samples down in the order the coprocessor made them can claim a position;
# everything else measures into state words.
# Only the accelerometer hook appends now: it drains the coprocessor's ring
# and then puts its own record behind what it just moved, which is the only
# way that record's position can be its time.
WRITERS = (('accel', ACCEL),)
MARKERS = (('trigger', TRIG),)


def equ(name, src=INC):
    m = re.search(rf'^\.equ\s+{name},\s*([^\s/@]+)', src, re.M)
    if not m:
        raise AssertionError(f'no .equ {name}')
    return m.group(1).rstrip(',')


class Header(unittest.TestCase):
    def test_tags_are_what_the_reader_expects(self):
        self.assertEqual(int(equ('TAG_GYRO'), 0), S.TAG_GYRO)
        self.assertEqual(int(equ('TAG_ACCEL'), 0), S.TAG_ACCEL)
        # TAG_START, TAG_STOP and TAG_VD are gone from the assembly: nothing
        # appends them any more.  The decoder still knows them, for files
        # written before the markers came out.

    def test_stream_is_a_power_of_two_of_eight_byte_records(self):
        n = int(equ('STREAM_COUNT'), 0)
        self.assertEqual(n & (n - 1), 0, 'the mask assumes a power of two')

    def test_both_producers_take_the_header_rather_than_a_copy(self):
        for name, src in (('accel_hook.S', ACCEL), ('gyro_drain.S', DRAIN),
                          ('stream_space.S', SPACE),
                          ('rec_trigger.S', TRIG),):
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

    def test_the_producers_make_no_judgement(self):
        """Audio's producer is a DMA engine: it is pointed at a buffer, it
        writes, and the hardware raises the completion.  It tests nothing.

        Ours ask for room, write what they are given, and say how much.  Every
        judgement -- where the ring is, how it is divided, whether a buffer
        filled, whether anything should be posted -- belongs to the space
        provider, and a producer that grows one back fails here."""
        for name, src in WRITERS:
            body = src[src.index('push'):]
            for forbidden in ('ring_slot', 'RING_MASK', 'BUF_', 'ldrex',
                              'STREAM_POSTED', 'T_FOPEN', 'T_STOPSENT',
                              'STREAM_SIGFN'):
                self.assertNotIn(forbidden, body,
                                 f'{name} is deciding something: {forbidden}')
            self.assertIn('STREAM_CLAIMFN', body)
            self.assertIn('STREAM_COMMITFN', body)

    def test_only_the_space_provider_knows_the_ring_is_divided(self):
        body = SPACE[SPACE.index('stream_claim:'):]
        for needed in ('BUF_RECORDS', 'BUF_MASK', 'ldrex', 'ring_slot',
                       'STREAM_SIGFN'):
            self.assertIn(needed, body, f'the space provider lost {needed}')

    def test_a_buffer_is_posted_on_an_equality_not_a_threshold(self):
        """A threshold is something to tune and something to be late about.  A
        buffer is full at exactly one count, so the test is ==, and it can only
        be true once per buffer."""
        commit = SPACE[SPACE.index('stream_commit:'):]
        self.assertIn('ands    r2, r1, r2', commit)
        self.assertIn('bne     9f', commit)
        self.assertNotIn('bhs', commit)
        self.assertNotIn('bls', commit)

    def test_record_start_anchors_the_gyro_cursor(self):
        """With no idle drain the cursor is stale by however long the camera
        sat, and a stale cursor is a WRAPPED one -- indistinguishable from a
        normal wrap.  The start hook has to latch the head itself."""
        self.assertIn('STREAM_GHEAD', TRIG, 'the start hook does not anchor it')
        self.assertLess(TRIG.index('STREAM_R0_HEAD'), TRIG.index('STREAM_GHEAD'))
        # it is in an #else arm, so the stop build never assembles it
        i = TRIG.index('STREAM_GHEAD')
        opened = TRIG.rindex('#else', 0, i)
        self.assertLess(TRIG.rindex('#ifdef REC_STOP', 0, i), opened)
        self.assertLess(i, TRIG.index('#endif', opened))

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
            body = src[src.index('rec_trigger:'):]
            self.assertNotIn('ring_slot', body, name)
            self.assertNotIn('ldrex', body, f'{name} still claims a stream slot')
            # \b, because strhi and strlo are conditional word stores and the
            # Vd hook is full of them.
            self.assertIsNone(re.search(r'strh\s+r\d+,\s*\[', body),
                              f'{name} still writes a record')
        self.assertIn('gyro_head', TRIG, 'the record trigger stopped measuring')

    def test_records_are_indexed_eight_bytes_apart(self):
        """The stride now lives in the ring_slot macro, so check it there -- and
        check every producer either uses the macro or carries its own stride,
        so a fifth copy of the arithmetic cannot appear unnoticed."""
        macro = INC[INC.index('.macro ring_slot'):INC.index('.endm', INC.index('.macro ring_slot'))]
        self.assertRegex(macro, r'lsl\s+#3', 'ring_slot does not stride by eight')
        body = SPACE[SPACE.index('stream_claim:'):]
        self.assertIn('ring_slot', body,
                      'the space provider indexes the ring by neither route')


class AudioShape(unittest.TestCase):
    """The writer must have the shape AudF_W has, not the shape it grew.

    Each of these is a line from the audio source, not a preference:
    AudioFileWriter::v1 @0xC01FBD40 for the body, AudF_W @0xC01FD380 for the
    build order, AudioFileRecordingObserver::v0 @0xC01FBB18 for the teardown.
    """

    def setUp(self):
        self.task = (HERE / 'ring_task.S').read_text()
        self.inc = (HERE / 'ring_task.inc.S').read_text()

    def body(self, name):
        i = self.task.index(f'\n{name}:')
        j = self.task.index('\n    bx      lr', i)
        return self.task[i:j]

    def test_the_writer_body_returns(self):
        """AudioFileWriter::v1 breaks out of its loop on the stop message and
        returns; FUN_c036efe8 catches that and sets the completion flag.  A body
        that can never return has no one to wait for it."""
        b = self.body('writer_body')
        self.assertIn('bl      writer_release', b)
        self.assertIn('pop     {r4, lr}', b)

    def test_every_job_says_where_it_belongs(self):
        """A job that never gets a descriptor used to vanish, and every record
        after it moved earlier in the file by the length of the hole -- which in
        a format whose claim is that position IS time silently rewrites the
        timeline.  Audio's writer compares the job's offset against its own file
        position and seeks when they disagree."""
        self.assertEqual(int(equ('J_OFF'), 0), 4)
        put = self.body('writer_put')
        self.assertIn('J_OFF', put)
        self.assertIn('F_SEEK', put)
        self.assertIn('T_POS', put)
        post = self.task[self.task.index('\nwriter_post:'):]
        post = post[:post.index('\nwriter_make_job:')]
        self.assertIn('STREAM_TAIL', post, 'the offset is not computed at all')

    def test_the_thread_is_the_firmwares_own(self):
        """XC_Thread.cpp's pool, used rather than reimplemented: the flag, the
        task, the parking and the wup/ter/del all live inside these four calls,
        and the only interface the worker has is slot +0xC of the object it is
        handed."""
        for call in ('XT_CREATE', 'XT_ATTACH', 'XT_JOIN', 'XT_DESTROY'):
            self.assertIn(call, self.task, f'{call} is not used')
        self.assertNotIn('TK_CRE_TSK', self.task, 'still making its own task')
        self.assertNotIn('FLG_CREATE', self.task, 'still making its own flag')
        self.assertIn('W_VT', self.task)

    def test_the_writer_never_touches_the_file_lifecycle(self):
        """The file is open before this task exists and closed after it has
        finished.  Opening it from inside the loop, at priority 6, is what this
        rewrite removes."""
        b = self.body('writer_body')
        for bad in ('writer_openfile', 'writer_closefile', 'writer_reconcile'):
            self.assertNotIn(bad, b, f'writer_body still calls {bad}')
        self.assertNotIn('writer_reconcile', self.task, 'reconcile is still here')

    def test_the_buffers_come_from_the_allocator(self):
        """DspAudioDevice::v5 asks the class 6 heap for its two blocks at
        capture start and gives them back at stop.  Ours does the same, from
        class 0 -- not 6, which is audio's own, and not 10, which is RAW and is
        what movRec could not allocate the day this project froze the camera."""
        t = self.body('take_open')
        self.assertIn('MEM_HEAP', t)
        self.assertIn('MEM_GET', t)
        self.assertLess(t.index('MEM_GET'), t.index('bl      writer_openfile'),
                        'a refusal must cost nothing: ask before opening')
        c = self.body('take_close')
        self.assertIn('MEM_FREE', c, 'the buffers are never given back')
        self.assertEqual(int(equ('MEM_CLASS', self.inc), 0), 0)

    def test_take_open_opens_before_it_starts_anything(self):
        """AudF_W's constructor opens the file, then attaches the body and wakes
        it.  Reversed, the writer can be posted to before there is a file --
        which is what the knock job existed to paper over."""
        t = self.body('take_open')
        self.assertLess(t.index('bl      writer_openfile'),
                        t.index('bl      make_writer'))
        # the knock job is gone from the code; the comment saying why is not
        self.assertNotIn('bl      writer_make_job             @ an empty job',
                         self.task)

    def test_take_close_joins_before_it_closes(self):
        """The observer's destructor posts the stop, waits on the thread's
        completion flag, and only then runs the file's destructor.  Closing
        first would close a file the writer is still writing to."""
        t = self.body('take_close')
        self.assertLess(t.index('writer_make_job'), t.index('XT_JOIN'))
        self.assertLess(t.index('XT_JOIN'), t.index('bl      writer_closefile'))
        self.assertLess(t.index('bl      writer_closefile'), t.index('XT_DESTROY'))

    def test_the_record_hooks_are_what_build_and_tear_down(self):
        """XC_AudioRecorder::Start and ::Stop do this, in the recorder's own
        task.  Both hooks run in that task; that is why the calls live there."""
        tail = TRIG[TRIG.index('T_CLOSEFN'):]
        # one #ifdef, two arms: stop takes T_CLOSEFN, start takes T_OPENFN
        self.assertIn('#ifdef REC_STOP', TRIG[:TRIG.index('T_CLOSEFN')][-200:])
        self.assertIn('T_OPENFN', tail[:tail.index('#endif')])
        self.assertIn('blxne   ip', tail)

    def test_the_stop_still_travels_as_a_job(self):
        """Ordering by construction: the stop comes out of the queue behind
        every write of the take, because it went in behind them."""
        t = self.body('take_close')
        self.assertIn('mov     r0, #1', t.split('writer_make_job')[0][-200:])


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
        for path in ('accel_hook.S', 'gyro_drain.S', 'stream_space.S',
                     'rec_trigger.S'):
            for w in self.words(path):
                if (w & 0x0FFF0000) == 0x092D0000:              # push {reglist}
                    self.assertEqual(bin(w & 0xFFFF).count('1') % 2, 0,
                                     f'{path} pushes an odd number')

    def test_accel_ends_with_the_displaced_instruction(self):
        w = self.words('accel_hook.S')
        self.assertEqual(w[-2], 0xE3A02000, 'mov r2, #0 is not there')
        self.assertEqual(w[-1], 0xE12FFF1E, 'bx lr is not there')

    def test_the_accel_hook_runs_outside_the_drivers_lock(self):
        """IMUDev_ACCEL_MMA8452Q::v7 takes a lock on the way in (FUN_c0010298)
        and releases it at 0xC050D4C4.  Everything this hook does -- a drain, a
        mailbox send, a priority 6 preemption that may write to the card -- used
        to happen with that lock held, and whatever else waits on it waited for
        all of it.  Audio's producer is a DSP completion callback and holds
        nothing."""
        self.assertIn('0xC050D4C8', ACCEL)
        self.assertNotIn('.equ ACCEL_SITE,      0xC050D498', ACCEL)

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
