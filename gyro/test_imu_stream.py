#!/usr/bin/env python3
"""The format is only worth what both producers agree on.

Half of these read the assembly rather than run it.  The bugs this file exists
to catch -- a record shape that drifts between the two hooks, a producer that
keeps its own copy of the index, an odd push -- are all things that assemble
cleanly and are found on the camera or not at all.
"""
import pathlib
import re
import struct
import tempfile
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

    def test_the_block_state_is_locked(self):
        """B_CUR, B_FILL and B_DONE are read and written together, and two
        different tasks reach them: the accelerometer driver, and the recorder
        when it commits a stop and the tail of the take has to come out before
        the file closes.  A task switch in between hands the same space out
        twice.

        Audio needs none of this -- its producer is one DSP callback.  The old
        design got away with none of it because it claimed a single monotonic
        word with LDREX; three words need a lock, and masking is what
        MPoolFixed::v1 uses on its own free list."""
        for name in ('stream_claim', 'stream_commit'):
            body = SPACE[SPACE.index(f'{name}:'):]
            body = body[:body.index('\n    bx      lr')]
            self.assertIn('st_lock', body, f'{name} touches the state unlocked')
            self.assertIn('st_unlock', body, f'{name} never lets interrupts back')

    def test_the_post_happens_outside_the_lock(self):
        """Taking a descriptor and sending a message do not belong in a critical
        section -- and by then the block is marked busy and B_CUR is cleared, so
        the state is already consistent."""
        commit = SPACE[SPACE.index('stream_commit:'):]
        post = commit.index('STREAM_SIGFN')
        # the release that precedes the call, not the one on the early exit
        self.assertLess(commit.index('B_BUSY'), commit.rindex('st_unlock', 0, post))
        self.assertLess(commit.rindex('st_unlock', 0, post), post)

    def test_full_is_the_block_running_out(self):
        """Audio's blocks are separate allocations and "full" is not a number
        anyone computes -- it is that block being used up.  Ours are separate
        allocations too now, so the same subtraction that decides how much of
        the current one to hand out is what discovers there is none left.  No
        mask, no modulo, no index into a tiled ring."""
        body = SPACE[SPACE.index('stream_claim:'):]
        for gone in ('BUF_MASK', 'RING_MASK', 'ring_slot', 'STREAM_INDEX'):
            self.assertNotIn(gone, body, f'{gone} is arithmetic on a tiled ring')
        self.assertIn('B_PTR', body)
        self.assertIn('BUF_RECORDS', body)

    def test_a_block_is_handed_over_when_it_is_used_up(self):
        commit = SPACE[SPACE.index('stream_commit:'):]
        self.assertIn('BUF_RECORDS', commit)
        self.assertIn('blo     9f', commit, 'the test is not against capacity')
        self.assertIn('B_BUSY', commit, 'the block is not marked as gone')
        self.assertIn('STREAM_SIGFN', commit)

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

    def test_records_are_eight_bytes_apart(self):
        """The stride lives in the space provider now, and only there: it is the
        only thing that turns a record count into an address."""
        body = SPACE[SPACE.index('stream_claim:'):]
        self.assertRegex(body, r'lsl #3')
        for name, src in WRITERS:
            self.assertNotRegex(src[src.index('push'):], r'lsl\s+#3',
                                f'{name} is doing address arithmetic')
class Header(unittest.TestCase):
    """The .GYR v7 header.  The camera writes it; gyr7.py reads it; the two
    have to agree field for field, and nothing else checks that."""

    def setUp(self):
        self.inc = (HERE / 'ring_task.inc.S').read_text()
        self.task = (HERE / 'ring_task.S').read_text()

    def equ(self, name):
        m = re.search(rf'^\.equ {name},\s*(\S+?)\s*(?:/\*|$)',
                      self.inc, re.M)
        self.assertIsNotNone(m, f'{name} is not defined')
        return int(m.group(1), 0)

    def test_the_two_sides_lay_the_header_out_the_same(self):
        import gyr7
        self.assertEqual(self.equ('HDR_BYTES'), gyr7.HDR_BYTES)
        self.assertEqual(gyr7.HEADER.size, gyr7.HDR_BYTES)
        # Field by field, camera offset against host offset.
        for name, want in (('H_MAGIC', 0), ('H_VERSION', 4), ('H_PERIOD_PS', 8),
                           ('H_GSCALE', 0x0C), ('H_ORIENT', 0x10),
                           ('H_CLIP', 0x14), ('H_VOLUME', 0x1C),
                           ('H_PAYLOAD', 0x20), ('H_DROPPED', 0x24),
                           ('H_MODE', 0x28), ('H_EXPOSURE', 0x2C),
                           ('H_WIDTH', 0x30), ('H_HEIGHT', 0x34)):
            self.assertEqual(self.equ(name), want, name)

    def test_the_period_is_the_measured_one(self):
        """400 us flat is 0.085 us fast on every sample.  The figure two
        independent rulers agreed on is 400.0854 us."""
        self.assertEqual(self.equ('GYR_PERIOD_PS'), 400085400)

    def test_the_payload_starts_after_the_header(self):
        """B_OFF is where the first block says it belongs.  Starting it at zero
        would put records under the header; carrying the last take's value over
        would layer two takes into one file."""
        c = '\n'.join(l for l in self.task.splitlines()
                       if 'B_OFF' in l or 'HDR_BYTES' in l)
        self.assertIn('HDR_BYTES', c)

    def test_the_header_is_written_twice(self):
        """Once at open so the file always has a magic, once at close for the
        counts that only exist then."""
        self.assertIn('bl      take_header', self.task)
        self.assertEqual(self.task.count('bl      put_header'), 2)

    def test_the_reader_rejects_the_old_container(self):
        import gyr7
        bad = pathlib.Path(tempfile.mkdtemp()) / 'x.GYR'
        bad.write_bytes(b'GFS6' + b'\0' * 60)
        with self.assertRaises(ValueError):
            gyr7.read_capture(bad)


class BlockComments(unittest.TestCase):
    """A block comment that is never closed swallows the code after it, and the
    assembler says nothing.  One of these ate take_close's own `9:` return
    label: every teardown short of the last branched to the NEXT function's
    `9:` -- whose pop happened to match, so they looked like passes -- and the
    full teardown fell straight through into writer_openfile, re-opening the
    file at record stop.  Three camera freezes and a battery each.

    The house style is that every continuation line of a block comment starts
    with `*`, so a comment that has swallowed code is one whose interior lines
    do not.  That is checkable, and eyes are not.
    """

    CODE = re.compile(
        r'^[A-Za-z_0-9]+:|'
        r'^\s+(?:mov[wt]?|ldr|str|add|sub|rsb|cmp|cmn|tst|teq|and|orr|eor|bic'
        r'|lsl|lsr|asr|mul|mla|adr|nop|push|pop|b|bl|blx|bx|msr|mrs|ldm|stm)'
        r'(?:eq|ne|cs|cc|hs|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?s?\s+'
        r'(?:r\d|ip\b|sp\b|lr\b|pc\b|#|\{|\d+[fb]\b'
        r"|[A-Za-z_]\w*\s*(?:@.*)?$)")

    def test_no_block_comment_swallows_code(self):
        for f in sorted(HERE.parent.rglob('*.S')):
            inside = False
            for n, line in enumerate(f.read_text().splitlines(), 1):
                body = line
                if inside:
                    self.assertFalse(
                        self.CODE.match(line),
                        f'{f.name}:{n} is inside a block comment but is code '
                        f'-- an unterminated /* above it is eating this '
                        f'line: {line!r}')
                    if '*/' not in line:
                        continue
                    body = line.split('*/', 1)[1]
                    inside = False
                while True:
                    o = body.find('/*')
                    if o < 0:
                        break
                    c = body.find('*/', o + 2)
                    if c < 0:
                        inside = True
                        break
                    body = body[c + 2:]


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

    CALL = re.compile(r'^\s*(?:blx?)\s+(?:ip|r\d+|(\w+))\s*$|'
                      r'^\s*mov[wt]\s+ip,\s*#:(?:lower|upper)16:(\w+)\s*$', re.M)

    def calls(self, text):
        """The names a routine actually calls, with comments -- which may
        mention the very name we are asserting is gone -- stripped out."""
        code = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        code = re.sub(r'@.*', '', code)
        return {a or b for a, b in self.CALL.findall(code)}

    def whole(self, name):
        """The whole routine, not just up to the first return: a function with
        an early exit (DRY_RUN) has more than one bx lr."""
        i = self.task.index(f'\n{name}:')
        m = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*:', re.M).search(self.task, i + 2 + len(name))
        return self.task[i:m.start() if m else len(self.task)]

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
        commit = SPACE[SPACE.index('stream_commit:'):]
        self.assertIn('B_OFF', commit, 'the offset is not carried at all')

    def test_attach_passes_the_body_objects_address(self):
        """FUN_c036efe8 calls (**(code **)(**(int **)(holder + 8) + 0xc))(): B is
        the stored pointer, *B the body's vtable, vtable+0xC the function.
        W_BODYOBJ is the body -- one word holding &W_VT -- so attach must pass
        &W_BODYOBJ.  Passing its VALUE (&W_VT) hands the worker W_VT[0] as a
        vtable, which nothing writes, and it died the instant it was woken."""
        t = self.body('take_open')
        att = t.index('XT_ATTACH')
        window = t[att - 400:att]
        self.assertIn('W_BODYOBJ', window)
        self.assertNotRegex(window, r'W_BODYOBJ\n\s+ldr\s+r1, \[r1\]',
                            'attach dereferences the body object')
        self.assertNotIn('ldr     r1, [r1]', window[window.rindex('W_BODYOBJ'):])

    def test_every_take_names_its_own_file(self):
        """A fixed name layers every take's writes into one file.  The camera
        names clips from RecordFilePathMgrCinema and so must we, or the log
        cannot be matched to the clip it belongs to."""
        c = self.whole('take_path')
        for field in ('#0x10', '#0x2C', '#8', '#0x0C'):
            self.assertIn(field, c, f'take_path must read the manager\'s {field}')
        self.assertIn('O_AUTORSTFLG', c,
                      'the saved maximum only counts when AutoRstFlg is clear')
        self.assertIn("mov     r0, #'G'", c)
        self.assertIn("mov     r0, #'Y'", c)
        self.assertIn("mov     r0, #'R'", c)
        self.assertIn('bl      take_path', self.whole('writer_openfile'))

    def test_no_fixed_path_is_left_in_the_blob(self):
        """The deployer used to patch a name into the blob.  If a literal comes
        back, two takes share a file again and the second overwrites the first
        from byte zero."""
        literals = [l for l in self.task.splitlines() if '.asciz' in l]
        self.assertFalse([l for l in literals if 'GYRO' in l],
                         f'no path literal belongs in the blob: {literals}')
        self.assertNotIn('RINGTEST',
                         (HERE / 'ring_task_deploy.py').read_text())

    def test_the_tail_goes_before_the_marker(self):
        """FUN_c01fbc80 copies four words into the stop message and audio's are
        DAT_c07e3dc8 = four zeros, so AudioFileWriter::v1 breaks on J_STOP
        without writing anything.  The last part-filled block therefore has to
        be posted as an ordinary job BEFORE the marker, or the tail of every
        take is lost."""
        c = self.whole('take_close')
        flush = c.index('STREAM_FLUSHFN')
        stop = c.index('bl      writer_make_job')
        self.assertLess(flush, stop,
                        'the tail must be posted before the stop marker')

    def test_the_stop_message_carries_no_data(self):
        """Audio's marker is four zero words and a flag.  Ours must be too:
        a stop job with a length would be written by a body that never looks
        at it."""
        c = self.whole('take_close')
        stop = c.index('mov     r0, #1                      @ J_STOP')
        args = c[stop:c.index('bl      writer_make_job', stop)]
        for r in ('r1', 'r2', 'r3'):
            self.assertIn(f'mov     {r}, #0', args)

    def test_the_flush_writes_only_what_was_committed(self):
        """B_FILL counts records handed out; B_DONE counts records written.
        A claim that has not committed is a producer mid-write, so flushing
        B_FILL would write records that do not exist yet."""
        f = (HERE / 'stream_space.S').read_text()
        body = f[f.index('\nstream_flush:'):]
        self.assertIn('B_DONE', body)
        self.assertNotIn('B_FILL', body,
                         'the flush must not trust the claim count')

    def test_the_file_is_closed_by_its_destructor_alone(self):
        """AudioFileWriter::v0 calls XC_MediaFile::v0 and never F_CLOSE: the
        destructor's first act is FUN_c0366020, which is F_CLOSE.  Calling it
        ourselves first sent us through that path twice."""
        called = self.calls(self.whole('writer_closefile'))
        self.assertIn('F_DTOR', called)
        self.assertNotIn('F_CLOSE', called,
                         'closing twice is not what audio does')

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
        b = self.body('blocks_open')
        self.assertIn('MEM_HEAP', b)
        self.assertIn('MEM_GET', b)
        self.assertIn('MEM_FREE', self.task)
        self.assertEqual(int(equ('MEM_CLASS', self.inc), 0), 0)
        # and NOT in the record hook's path: the movie takes its memory at
        # record start, so ours has to be older than that
        t = self.body('take_open')
        self.assertNotIn('MEM_GET', t, 'take_open still asks the allocator')
        c = self.body('take_close')
        self.assertNotIn('free_blocks', c, 'take_close still gives them back')

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
        # AudioFileWriter::v0's order: mailbox, thread, and the file LAST
        self.assertLess(t.index('XT_JOIN'), t.index('MBX_DELETE'))
        self.assertLess(t.index('MBX_DELETE'), t.index('XT_DESTROY'))
        self.assertLess(t.index('XT_DESTROY'), t.index('bl      writer_closefile'))

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
