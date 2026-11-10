"""The same-frame adapter: hold at the creator's enqueue, finish, give back.

frame_hold.c + codec_job.c + producer_facts.c + frame_pipeline.c + control.c,
linked together on the host. Only the firmware is substituted
(frame_hold_fixture.c): the frame registry, the creator's enqueue C037DD50,
and a fake engine that writes, as the first word of its output, a marker
carrying the SOURCE frame's id -- 0xC00000id -- while an untouched frame
still reads 0xF00000id. So every file's content is checked against its own
frame directly: that is what "same frame" means, and what the disabled async
probe got wrong.

No camera, USB or card.
"""
import ctypes as ct
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
OK, INVALID, BUSY, UNSUPPORTED, NOT_READY, FAULT = range(6)
FREE, HELD, ENCODING, READY, COMMITTING, RETAINED, READY_RAW = range(7)
MODE_OK, MODE_REFUSE, MODE_WAIT_ERROR, MODE_NEVER, MODE_NEVER_ONCE = range(5)
(ENQ_N, ARRIVALS, HELD_N, PASSED, COMPRESSED, REFUSED, NO_BENEFIT, NOT_ELIGIBLE,
 DRAINED, FAULTS, PHASE, STARTS, CLOSES, OOB, UNCACHED_HITS, BARRIERS, TOLD,
 STARTED_SOURCE, RASTER, ACTIVE, ALLOCATION, BARRIER_N, PUBLISHED, _COPIED, DIRECT,
 LAST_CAPACITY, SOURCE_CAPACITY, SPARE, SWAPPED, SWAP_DECLINED, SWAP_UNDONE,
 SPARE_CAPACITY, OWNERS_DISTINCT, STARTED_DEST, DMAS, DMA_BAD, DMA_FAILED) = range(37)
EXTRA_SPARE = 0xC00000 + 9 * 0x60000   # the fixture's first spare
COMMITS = 16                     # FPL_HOLD_COMMITS
GRANTED_EXTRA = 1024             # the allocator granting a little more than asked
NONE = 0xFFFFFFFF
SOURCES = ['frame_hold.c', 'codec_job.c', 'producer_facts.c', 'frame_hold_fixture.c',
           'flush_site.c', 'header_tag.c']
CORE = ['frame_pipeline.c', 'control.c']
SMALL_PAYLOAD = 40 * 1024        # compresses well: the file gets shorter
HUGE_PAYLOAD = 0x46400           # fits the engine's room (align_kib of the raster)
                                 # but not under the stock file: no saving


def raw(i): return 0xF0000000 | i
def packed(i): return 0xC0000000 | i


def build(directory, replace=None, name='hold.dylib'):
    sources = [HERE / s for s in SOURCES] + [HERE.parent / s for s in CORE]
    if replace:
        target, (old, new) = (replace[0], replace[1:]) if len(replace) == 3 else \
            ('frame_hold.c', replace)
        text = (HERE / target).read_text()
        if text.count(old) != 1:
            raise AssertionError('mutation seam not found once: ' + old[:60])
        mutated = Path(directory) / (name + '.c')
        mutated.write_text(text.replace(old, new))
        sources[SOURCES.index(target)] = mutated
    out = Path(directory) / name
    subprocess.run([shutil.which('clang') or 'clang', '-shared', '-fPIC', '-O2', '-std=c11',
                    '-Wall', '-Wextra', '-Werror', '-DFPL_FRAME_HOLD_HOST_TEST',
                    '-DFPL_CODEC_JOB_HOST_TEST', '-DFPL_PRODUCER_FACTS_HOST_TEST',
                    '-DFPL_FLUSH_SITE_HOST_TEST', '-DFPL_HOLD_COMMITS=16u',
                    '-I', str(HERE)] + [str(s) for s in sources] + ['-o', str(out)],
                   check=True, capture_output=True, text=True, timeout=60)
    lib = ct.CDLL(str(out))
    for fn, count, ret in (('reset', 3, True), ('mode', 1, False), ('open_fails', 1, False),
                           ('close_fails', 1, False), ('enqueue_result', 1, False),
                           ('present', 2, False),
                           ('frame', 2, False), ('frame_field', 3, False),
                           ('arrive', 1, True), ('arrive_arg', 2, True), ('stop', 0, True),
                           ('finish', 0, True), ('break', 0, False), ('flush', 2, True),
                           ('commit_tiles', 2, True), ('tile_force', 1, False), ('get', 1, True),
                           ('header', 1, False), ('writer_flush', 2, True),
                           ('writer_shape', 1, False), ('flush_get', 1, True),
                           ('file_word', 2, True), ('file_poke', 3, False),
                           ('use_spare', 1, False), ('no_output', 1, False),
                           ('lanes', 1, True), ('lane_arrive', 1, True), ('task', 0, True),
                           ('task_wait', 1, True), ('twai', 1, True),
                           ('lane_stop', 0, True), ('lane_abandon', 1, True),
                           ('lane_finish', 1, True), ('lane_get', 2, True),
                           ('kick', 1, True), ('reenter', 1, False),
                           ('dma_fails', 1, False), ('pipeline_phase', 1, False),
                           ('task_in_sleep', 1, False), ('head', 1, False),
                           ('require_head', 1, False)):
        f = getattr(lib, 'fpl_fixture_' + fn)
        f.argtypes = [ct.c_uint32] * count
        f.restype = ct.c_uint32 if ret else None
    return lib


class HoldTests(unittest.TestCase):
    SPARE = 0                    # no spare: every result is copied back

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-hold-')
        cls.lib = build(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def reset(self, latency=0, payload=SMALL_PAYLOAD, lossless=1):
        self.lib.fpl_fixture_use_spare(self.SPARE)
        self.assertEqual(self.lib.fpl_fixture_reset(latency, payload, lossless), OK)

    def setUp(self):
        self.reset()

    def get(self, f): return self.lib.fpl_fixture_get(f)

    def frames(self, *ids, spare=GRANTED_EXTRA):
        for i in ids:
            self.lib.fpl_fixture_frame(i, spare)

    def queued(self):
        """(id, first pixel word when queued, state when queued), in order."""
        n = self.get(ENQ_N)
        return [(self.get(1000 + k), self.get(2000 + k), self.get(3000 + k)) for k in range(n)]

    def ids(self): return [q[0] for q in self.queued()]

    def assert_same_frame(self):
        """Every queued frame carries either its own raw picture or its OWN
        compressed picture -- never another frame's."""
        for frame, word, _ in self.queued():
            self.assertIn(word, (raw(frame), packed(frame)),
                          f'frame {frame} was queued holding {word:#x}')

    # ---- the steady state ---------------------------------------------
    def test_a_fast_engine_compresses_every_frame_into_its_own_file(self):
        self.frames(1, 2, 3, 4, 5)
        for i in (1, 2, 3, 4, 5):
            self.lib.fpl_fixture_arrive(i)
        self.assertEqual(self.ids(), [1, 2, 3, 4])          # 5 is still held
        self.assertEqual(self.get(4000 + 5), 0xB)
        self.lib.fpl_fixture_stop()
        self.assertEqual(self.ids(), [1, 2, 3, 4, 5])
        self.assertEqual([w for _, w, _ in self.queued()], [packed(i) for i in (1, 2, 3, 4, 5)])
        self.assert_same_frame()
        self.assertEqual(self.get(COMPRESSED), 5)
        self.assertEqual(self.get(OOB), 0)

    def test_a_slow_engine_lets_later_frames_through_raw_and_keeps_order_per_file(self):
        self.reset(latency=2)
        self.frames(1, 2, 3, 4, 5, 6)
        for i in (1, 2, 3, 4, 5, 6):
            self.lib.fpl_fixture_arrive(i)
        self.lib.fpl_fixture_stop()
        q = dict((i, w) for i, w, _ in self.queued())
        self.assertEqual(sorted(q), [1, 2, 3, 4, 5, 6], 'a frame was lost or duplicated')
        self.assertEqual(len(self.ids()), 6)
        self.assert_same_frame()
        self.assertEqual(q[1], packed(1))
        self.assertEqual(q[2], raw(2))                      # engine busy with 1
        self.assertGreater(self.get(COMPRESSED), 1)
        self.assertEqual(self.get(PASSED) + self.get(HELD_N), 6)

    def test_a_held_frame_is_marked_pending_before_the_engine_starts(self):
        self.reset(latency=5)
        self.frames(1)
        self.assertEqual(self.lib.fpl_fixture_arrive(1), 1)
        self.assertEqual(self.get(4000 + 1), 0xB)
        self.assertEqual(self.ids(), [])
        self.assertEqual(self.get(STARTED_SOURCE), 0x100000 + 1 * 0x60000 + 0x15400)

    def test_every_frame_is_queued_exactly_once_over_a_long_take(self):
        self.reset(latency=1)
        ids = list(range(1, 8))
        self.frames(*ids)
        sequence = [1 + (n % 7) for n in range(200)]
        for n, i in enumerate(sequence):
            # the slot's previous file is written, then its buffer freed and
            # a new one allocated, as natively
            while self.lib.fpl_fixture_flush(i, 1) != NONE:
                pass
            self.lib.fpl_fixture_frame(i, GRANTED_EXTRA)
            self.lib.fpl_fixture_arrive(i)
            self.assertEqual(self.get(OWNERS_DISTINCT), 1, f'a buffer has two owners at {n}')
        self.lib.fpl_fixture_stop()
        self.assertEqual(len(self.ids()), 200)
        self.assert_same_frame()
        self.assertGreater(self.get(COMPRESSED), 50)
        self.assertEqual(self.get(OOB), 0)

    # ---- what the flush site receives --------------------------------
    def test_each_compressed_frame_publishes_its_promise_for_the_flush(self):
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.lib.fpl_fixture_flush(1, 0), SMALL_PAYLOAD)
        self.assertEqual(self.lib.fpl_fixture_flush(2, 0), NONE)    # still held
        tiles = self.lib.fpl_fixture_commit_tiles(1, 0xFFFF)
        self.assertEqual(tiles, 2)                 # 520x368: two 288x368 tiles across
        self.assertEqual(sum(self.lib.fpl_fixture_commit_tiles(1, t) for t in range(tiles)),
                         SMALL_PAYLOAD)

    def test_the_promise_carries_the_grid_the_frame_was_compressed_with(self):
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_tile_force(256 << 16 | 368)     # from the next frame on
        self.lib.fpl_fixture_arrive(2)
        self.lib.fpl_fixture_stop()
        self.assertEqual(self.lib.fpl_fixture_flush(1, 0), SMALL_PAYLOAD)
        # tile_grid.h's default for 520x368 (test_tile_grid.reference)
        self.assertEqual(self.lib.fpl_fixture_commit_tiles(1, 0xFFFE), 288 << 16 | 368)
        self.assertEqual(self.lib.fpl_fixture_flush(2, 0), SMALL_PAYLOAD)
        self.assertEqual(self.lib.fpl_fixture_commit_tiles(2, 0xFFFE), 256 << 16 | 368)
        self.assertEqual(self.lib.fpl_fixture_commit_tiles(2, 0xFFFF), 3)   # 520 = 3 x 256

    def test_promises_are_independent_of_order(self):
        self.frames(1, 2, 3)
        for i in (1, 2, 3):
            self.lib.fpl_fixture_arrive(i)
        self.lib.fpl_fixture_stop()
        self.assertEqual(self.lib.fpl_fixture_flush(2, 1), SMALL_PAYLOAD)
        self.assertEqual(self.lib.fpl_fixture_flush(2, 0), NONE, 'consumed twice')
        self.assertEqual(self.lib.fpl_fixture_flush(1, 1), SMALL_PAYLOAD)
        self.assertEqual(self.lib.fpl_fixture_flush(3, 1), SMALL_PAYLOAD)

    def test_the_copy_back_goes_through_the_uncached_alias_and_publishes_behind_barriers(self):
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        before = self.get(UNCACHED_HITS), self.get(BARRIERS)
        self.lib.fpl_fixture_arrive(2)
        self.assertGreaterEqual(self.get(UNCACHED_HITS) - before[0], SMALL_PAYLOAD // 4 * 2)
        self.assertGreaterEqual(self.get(BARRIERS) - before[1], 2)

    def test_the_payload_is_fenced_before_the_promise_is_published(self):
        """The flush runs on another task: it must never see a promise whose
        payload and tile sizes are not yet in memory. So the first barrier of
        a handoff happens while that promise is still unpublished."""
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)                  # hands frame 1 off
        log = [self.get(6000 + i) for i in range(self.get(BARRIER_N))]
        self.assertTrue(log, 'no barrier at all')
        self.assertEqual(log[0], 0, f'published before the fence: {log}')
        self.assertIn(1, log, 'never fenced after publishing')

    def test_without_free_promise_slots_nothing_is_held(self):
        """A compressed file without its trailer is garbage: never start one
        that could not be promised a slot."""
        # Nothing is flushed, so the sixteen slots fill and every later frame
        # must go out RAW -- never held, never compressed without a promise.
        ids = list(range(1, 23))
        self.frames(*ids)
        for i in ids:
            self.lib.fpl_fixture_arrive(i)
        self.lib.fpl_fixture_stop()
        self.assertEqual(len(self.ids()), len(ids))
        self.assert_same_frame()
        compressed = [i for i, w, _ in self.queued() if w == packed(i)]
        self.assertEqual(len(compressed), COMMITS)
        for i in compressed:
            self.assertNotEqual(self.lib.fpl_fixture_flush(i, 0), NONE,
                                f'frame {i} compressed without a promise')
        self.assertEqual(self.get(FAULTS), 0)

    # ---- the frame goes out untouched -------------------------------
    def test_an_engine_refusal_sends_the_frame_as_it_was(self):
        self.lib.fpl_fixture_mode(MODE_REFUSE)
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.queued()[0][:2], (1, raw(1)))
        self.assertEqual(self.lib.fpl_fixture_flush(1, 0), NONE)
        self.assertEqual(self.get(REFUSED), 1)
        self.assertEqual(self.get(FAULTS), 0)
        self.assertEqual(self.get(HELD_N), 2, 'a refusal stopped compression')

    def test_a_result_with_no_file_saving_sends_the_frame_as_it_was(self):
        self.reset(payload=HUGE_PAYLOAD)
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.queued()[0][:2], (1, raw(1)))
        self.assertEqual(self.lib.fpl_fixture_flush(1, 0), NONE)
        self.assertEqual(self.get(NO_BENEFIT), 1)

    def test_the_fhd_512_bytes_are_read_in_place_up_to_the_1_kib_boundary(self):
        """Operator decision 2026-09-30: read in place. Measured on the camera,
        the allocation is exactly the native request and the told length ends
        512 B past it -- at the next 1 KiB boundary, since every kind-1
        allocation is 1 KiB aligned. That is the window the engine is given."""
        told, allocation = self.get(TOLD), self.get(ALLOCATION)
        self.assertEqual(0x15400 + told - allocation, 512)
        self.assertEqual((0x15400 + told) % 1024, 0)
        self.frames(1, spare=0)
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual((self.get(STARTS), self.get(DIRECT)), (1, 1))
        self.assertEqual(self.get(STARTED_SOURCE), 0x100000 + 1 * 0x60000 + 0x15400)
        # the window the engine is vouched for ends exactly at that boundary
        self.assertEqual(self.get(SOURCE_CAPACITY), told)

    def test_a_frame_whose_allocation_does_not_hold_its_raster_is_not_held(self):
        self.frames(1, spare=0)
        allocation = self.get(ALLOCATION)
        self.lib.fpl_fixture_frame_field(1, 0x6C, allocation - 1024)
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual(self.queued(), [(1, raw(1), 8)])
        self.assertEqual(self.get(STARTS), 0)

    def test_a_frame_of_another_template_than_the_takes_ifd_is_not_held(self):
        """require_head: only frames whose header is the template the take's
        IFD was prepared in; 0xFFFFFFFF (the card at REC) holds nothing."""
        for require in (0x13800, 0xFFFFFFFF):
            with self.subTest(require=hex(require)):
                self.reset()
                self.lib.fpl_fixture_require_head(require)
                self.frames(1, spare=0)
                self.lib.fpl_fixture_arrive(1)
                self.assertEqual(self.queued(), [(1, raw(1), 8)])
                self.assertEqual(self.get(STARTS), 0)
        self.reset()
        self.lib.fpl_fixture_require_head(0x13400)
        self.frames(1, spare=0)
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual(self.get(STARTS), 1)

    def test_a_frame_whose_header_cannot_be_its_file_is_not_held(self):
        """frame+0x14C past the reserve, unaligned or too short: the file would
        not start inside the allocation (2026-10-14, header_tag.h)."""
        for value in (0x15800, 0x13402, 0x200):
            with self.subTest(head=hex(value)):
                self.reset()
                self.frames(1, spare=0)
                self.lib.fpl_fixture_frame_field(1, 0x14C, value)
                self.lib.fpl_fixture_arrive(1)
                self.assertEqual(self.queued(), [(1, raw(1), 8)])
                self.assertEqual(self.get(STARTS), 0)

    def test_a_frame_with_its_own_buffer_pointer_in_the_descriptor_is_still_held(self):
        """Measured on the camera: descriptor word 15 is per frame."""
        self.frames(1)
        self.lib.fpl_fixture_frame_field(1, 0x10 + 4 * 15, 0x54136800)
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual(self.get(STARTS), 1)

    def test_a_frame_of_another_format_is_not_held(self):
        for field, value in ((0x10, 1920), (0x14, 1080), (0x30, 3)):
            with self.subTest(field=hex(field)):
                self.reset()
                self.frames(1)
                self.lib.fpl_fixture_frame_field(1, field, value)
                self.lib.fpl_fixture_arrive(1)
                self.assertEqual(self.ids(), [1])
                self.assertEqual(self.get(STARTS), 0)

    def test_other_kinds_arguments_and_unknown_ids_pass_straight_through(self):
        self.frames(1, 2)
        self.lib.fpl_fixture_frame_field(1, 0x04, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive_arg(2, 0)
        self.lib.fpl_fixture_arrive(6)                     # not a present frame
        self.assertEqual(self.ids(), [1, 2, 6])
        self.assertEqual(self.get(STARTS), 0)

    def test_with_no_lossless_take_every_frame_passes(self):
        self.reset(lossless=0)
        self.frames(1, 2, 3)
        for i in (1, 2, 3):
            self.lib.fpl_fixture_arrive(i)
        self.assertEqual(self.queued(), [(1, raw(1), 8), (2, raw(2), 8), (3, raw(3), 8)])
        self.assertEqual(self.get(STARTS), 0)

    def test_broken_state_passes_every_frame_to_the_original(self):
        self.lib.fpl_fixture_break()
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.ids(), [1, 2])

    def test_an_engine_that_will_not_open_gives_the_frame_back_at_once(self):
        self.lib.fpl_fixture_open_fails(1)
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual(self.queued(), [(1, raw(1), 0xB)])
        self.assertEqual(self.get(PHASE), FREE, 'slot not freed after a refused start')
        self.lib.fpl_fixture_open_fails(0)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.get(4000 + 2), 0xB)         # the next frame is held

    # ---- stop, and the engine misbehaving ----------------------------
    def test_stop_finishes_the_held_frame_and_the_take_can_end(self):
        self.reset(latency=3)
        self.frames(1)
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual(self.lib.fpl_fixture_stop(), OK)
        self.assertEqual(self.queued()[0][:2], (1, packed(1)))
        self.assertEqual(self.get(PHASE), FREE)
        self.assertEqual(self.get(DRAINED), 1)
        self.assertEqual(self.lib.fpl_fixture_finish(), OK)

    def test_an_engine_that_never_finishes_cannot_hang_stop(self):
        self.lib.fpl_fixture_mode(MODE_NEVER)
        self.frames(1)
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual(self.lib.fpl_fixture_stop(), FAULT)
        self.assertEqual(self.queued()[0][:2], (1, raw(1)))   # given back untouched
        self.assertEqual(self.get(PHASE), ENCODING)
        self.assertEqual(self.lib.fpl_fixture_finish(), BUSY, 'workspace freed under DMA')

    def test_an_unknown_wait_failure_gives_the_frame_back_and_admits_no_more(self):
        self.frames(1, 2, 3)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_mode(MODE_WAIT_ERROR)
        self.lib.fpl_fixture_arrive(2)
        self.lib.fpl_fixture_arrive(3)
        self.assertEqual(self.queued(), [(1, raw(1), 0xB), (2, raw(2), 8), (3, raw(3), 8)])
        self.assertEqual(self.get(FAULTS), 1)
        self.lib.fpl_fixture_stop()
        self.assertEqual(len(self.ids()), 3, 'the frame was given back twice')
        self.assertEqual(self.lib.fpl_fixture_finish(), BUSY)


class SwapHoldTests(HoldTests):
    """Every hold test again, with a spare: the engine writes into the spare
    and the frame is released owning it. Then the swap itself."""
    SPARE = 1

    def handle(self, i): return self.get(8000 + i)

    def test_the_copy_back_goes_through_the_uncached_alias_and_publishes_behind_barriers(self):
        # swapped: no payload copy at all; the header goes by the firmware's
        # DMA, and the promise is still published behind barriers
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        before = self.get(DMAS), self.get(BARRIERS), self.get(UNCACHED_HITS)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.get(DMAS) - before[0], 1)
        self.assertGreaterEqual(self.get(BARRIERS) - before[1], 2)
        self.assertLess(self.get(UNCACHED_HITS) - before[2], 0x400, 'copied by the CPU')

    def test_a_compressed_frame_is_released_owning_the_spare_and_nothing_is_copied(self):
        self.frames(1, 2)
        a1, a2 = self.handle(1), self.handle(2)
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual(self.get(STARTED_SOURCE), a1 + 0x15400)
        self.assertEqual(self.get(STARTED_DEST), EXTRA_SPARE + 0x15400)
        before = self.get(UNCACHED_HITS)
        self.lib.fpl_fixture_arrive(2)
        # the header prefix read and written, and the tile table: no payload
        self.assertLess(self.get(UNCACHED_HITS) - before, 0x15400 // 4 * 2 + 64)
        self.assertEqual(self.handle(1), EXTRA_SPARE)
        self.assertEqual(self.get(SPARE), a1, 'the frame\'s buffer is not the next spare')
        self.assertEqual(self.get(STARTED_DEST), a1 + 0x15400, 'next frame not into A')
        self.assertEqual(self.queued()[0][:2], (1, packed(1)))
        self.assertEqual(self.get(SWAPPED), 1)
        self.lib.fpl_fixture_stop()
        self.assertEqual(self.handle(2), a1)
        self.assertEqual(self.get(SPARE), a2)
        self.assertEqual(self.get(OWNERS_DISTINCT), 1)
        self.assertEqual(self.get(OOB), 0)

    def test_the_record_the_firmware_frees_and_its_raster_pointer_move_together(self):
        self.frames(1, spare=0)
        a1 = self.handle(1)
        spare_capacity = self.get(SPARE_CAPACITY)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_stop()
        # frame+0x68 {handle, capacity, class}, and frame+0x4C
        self.assertEqual((self.handle(1), self.get(10000 + 1), self.get(11000 + 1),
                          self.get(12000 + 1)),
                         (EXTRA_SPARE, spare_capacity, 10, EXTRA_SPARE + 0x15400))
        self.assertEqual((self.get(SPARE), self.get(SPARE_CAPACITY)),
                         (a1, self.get(ALLOCATION)))

    def test_the_header_the_firmware_put_in_the_frame_goes_with_it(self):
        self.frames(3)
        self.lib.fpl_fixture_arrive(3)
        self.lib.fpl_fixture_stop()
        self.assertEqual(self.handle(3), EXTRA_SPARE)
        self.assertEqual(self.get(9000 + 3), 0x48000003)

    def test_the_header_moves_by_the_firmware_dma_on_plain_addresses(self):
        self.frames(1, 2, 3)
        for i in (1, 2, 3):
            self.lib.fpl_fixture_arrive(i)
        self.lib.fpl_fixture_stop()
        self.assertEqual(self.get(DMAS), self.get(SWAPPED))
        self.assertGreater(self.get(DMAS), 0)
        self.assertEqual((self.get(DMA_BAD), self.get(DMA_FAILED)), (0, 0))

    def test_a_refused_dma_falls_back_to_the_cpu_copy(self):
        self.lib.fpl_fixture_dma_fails(1)
        self.frames(3)
        self.lib.fpl_fixture_arrive(3)
        self.lib.fpl_fixture_stop()
        self.assertEqual(self.handle(3), EXTRA_SPARE)
        self.assertEqual(self.get(9000 + 3), 0x48000003)
        self.assertEqual(self.get(DMA_FAILED), 1)

    def test_a_frame_that_shares_its_allocation_is_copied_back_not_swapped(self):
        for field, value in ((0x1114, 1), (0x1118, 5), (0x70, 9)):
            with self.subTest(field=hex(field)):
                self.reset()
                self.frames(1, 2)
                a1 = self.handle(1)
                self.lib.fpl_fixture_frame_field(1, field, value)
                self.lib.fpl_fixture_arrive(1)
                self.lib.fpl_fixture_arrive(2)
                self.assertEqual(self.handle(1), a1)
                self.assertEqual(self.queued()[0][:2], (1, packed(1)))
                self.assertEqual(self.get(SPARE), EXTRA_SPARE)
                self.assertEqual(self.get(SWAP_DECLINED), 1)

    def test_a_clone_made_while_held_undoes_the_swap(self):
        self.frames(1, 2)
        a1 = self.handle(1)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_frame_field(1, 0x1114, 1)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.handle(1), a1)
        self.assertEqual(self.queued()[0][:2], (1, packed(1)))
        self.assertEqual(self.get(SPARE), EXTRA_SPARE)
        self.assertEqual(self.get(SWAP_UNDONE), 1)
        self.assertEqual(self.lib.fpl_fixture_flush(1, 0), SMALL_PAYLOAD)

    def test_a_spare_smaller_than_the_frame_is_not_used(self):
        self.frames(1, spare=4096)                    # larger than the spare
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual(self.get(SWAP_DECLINED), 1)
        self.assertEqual(self.get(STARTED_DEST), 0xA00000)

    def test_a_refused_or_useless_result_keeps_both_buffers_where_they_were(self):
        for mode, payload in ((MODE_REFUSE, SMALL_PAYLOAD), (MODE_OK, HUGE_PAYLOAD)):
            with self.subTest(mode=mode):
                self.reset(payload=payload)
                self.lib.fpl_fixture_mode(mode)
                self.frames(1, 2)
                a1 = self.handle(1)
                self.lib.fpl_fixture_arrive(1)
                self.lib.fpl_fixture_arrive(2)
                self.assertEqual(self.handle(1), a1)
                self.assertEqual(self.get(SPARE), EXTRA_SPARE)
                self.assertEqual(self.queued()[0][:2], (1, raw(1)))
                self.assertEqual(self.get(SWAPPED), 0)

    def test_an_engine_that_never_finishes_keeps_the_spare(self):
        self.lib.fpl_fixture_mode(MODE_NEVER)
        self.frames(1)
        a1 = self.handle(1)
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual(self.lib.fpl_fixture_stop(), FAULT)
        self.assertEqual(self.handle(1), a1)
        self.assertEqual(self.get(SPARE), EXTRA_SPARE)


class NoOutputTests(unittest.TestCase):
    """The card's setting: no output span, only the spare. A frame the swap
    takes is compressed as before; any other frame is never given to the
    engine and goes out as it is."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-hold-noout-')
        cls.lib = build(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.lib.fpl_fixture_no_output(0)
        cls.lib.fpl_fixture_use_spare(0)
        cls.tmp.cleanup()

    def reset(self, spare=1):
        self.lib.fpl_fixture_no_output(1)
        self.lib.fpl_fixture_use_spare(spare)
        return self.lib.fpl_fixture_reset(0, SMALL_PAYLOAD, 1)

    def get(self, f): return self.lib.fpl_fixture_get(f)

    def queued(self):
        n = self.get(ENQ_N)
        return [(self.get(1000 + k), self.get(2000 + k)) for k in range(n)]

    def test_neither_output_nor_spare_is_refused(self):
        self.assertEqual(self.reset(spare=0), INVALID)

    def test_swapped_frames_are_compressed_into_the_spare(self):
        self.assertEqual(self.reset(), OK)
        for i in (1, 2, 3):
            self.lib.fpl_fixture_frame(i, GRANTED_EXTRA)
        for i in (1, 2, 3):
            self.lib.fpl_fixture_arrive(i)
        self.lib.fpl_fixture_stop()
        self.assertEqual(self.queued(), [(i, packed(i)) for i in (1, 2, 3)])
        self.assertEqual(self.get(SWAPPED), 3)
        self.assertEqual(self.get(OOB), 0)

    def test_a_frame_the_swap_cannot_take_never_reaches_the_engine(self):
        self.assertEqual(self.reset(), OK)
        self.lib.fpl_fixture_frame(1, GRANTED_EXTRA)
        self.lib.fpl_fixture_frame_field(1, 0x1114, 1)     # shared with a clone
        self.lib.fpl_fixture_arrive(1)
        self.assertEqual(self.queued(), [(1, raw(1))])
        self.assertEqual((self.get(STARTS), self.get(HELD_N)), (0, 0))

    def test_an_engine_refusal_gives_the_frame_back_as_it_was(self):
        # 2026-10-01 card y: with no output span a refusal faulted and the
        # frame was never given back, so native stop hung
        self.assertEqual(self.reset(), OK)
        self.lib.fpl_fixture_mode(MODE_REFUSE)
        for i in (1, 2):
            self.lib.fpl_fixture_frame(i, GRANTED_EXTRA)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.queued()[0], (1, raw(1)))
        self.assertEqual((self.get(REFUSED), self.get(FAULTS)), (1, 0))
        self.lib.fpl_fixture_stop()
        self.assertEqual(self.queued(), [(1, raw(1)), (2, raw(2))])
        self.assertEqual(self.get(PHASE), FREE)
        self.assertEqual(self.lib.fpl_fixture_finish(), OK)

    def test_a_clone_made_while_held_is_still_copied_back_from_the_spare(self):
        self.assertEqual(self.reset(), OK)
        self.lib.fpl_fixture_frame(1, GRANTED_EXTRA)
        self.lib.fpl_fixture_frame(2, GRANTED_EXTRA)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_frame_field(1, 0x1114, 1)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.queued()[0], (1, packed(1)))
        self.assertEqual(self.get(SWAP_UNDONE), 1)


TAG_IFD_AT = 0x400                 # frame_hold_fixture.c FIXTURE_TAG_AT


class FlushSiteTests(HoldTests):
    """The whole chain: hold, encode, give back, then the writer's flush
    completes the IFD the header already holds and shortens the node -- only
    for the frame that was promised, only at its stock length."""

    def frames(self, *ids, spare=GRANTED_EXTRA):
        super().frames(*ids, spare=spare)
        for i in ids:
            self.lib.fpl_fixture_header(i)

    def fget(self, f): return self.lib.fpl_fixture_flush_get(f)

    def test_a_compressed_frame_gets_its_ifd_and_a_shorter_length(self):
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.lib.fpl_fixture_writer_flush(1, 0), OK)
        self.assertEqual(self.fget(1), 1)
        stock = 0x13400 + ((self.get(RASTER) + 0x1FF) & ~0x1FF)
        length = self.fget(0)
        self.assertLess(length, stock)
        self.assertEqual(length % 1024, 0)
        self.assertEqual(self.lib.fpl_fixture_file_word(1, 4), TAG_IFD_AT,
                         'root pointer not moved to the prepared IFD')
        self.assertEqual(self.lib.fpl_fixture_flush(1, 0), NONE, 'promise not consumed')
        self.assertEqual(self.get(OOB), 0)

    def test_a_longer_header_moves_the_file_and_the_payload_with_it(self):
        """A take whose template carries the card's tag (header_tag.h): the
        file starts 0x15400 - head before the raster, the payload at `head`."""
        head = 0x14000
        self.lib.fpl_fixture_head(head)
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.lib.fpl_fixture_writer_flush(1, 0), OK)
        self.assertEqual(self.fget(1), 1)
        stock = head + ((self.get(RASTER) + 0x1FF) & ~0x1FF)
        self.assertLess(self.fget(0), stock)
        self.assertEqual(self.lib.fpl_fixture_file_word(1, 4), TAG_IFD_AT)
        # the node is the longer header plus the payload, 1 KiB rounded
        self.assertEqual(self.fget(0), (head + SMALL_PAYLOAD + 0x3FF) & ~0x3FF)
        self.assertEqual(self.get(OOB), 0)

    def test_a_raw_frame_is_left_exactly_as_it_was(self):
        self.lib.fpl_fixture_mode(MODE_REFUSE)
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        stock = 0x13400 + ((self.get(RASTER) + 0x1FF) & ~0x1FF)
        self.assertEqual(self.lib.fpl_fixture_writer_flush(1, 0), OK)
        self.assertEqual(self.fget(0), stock)
        self.assertEqual(self.lib.fpl_fixture_file_word(1, 4), 8)
        self.assertEqual(self.fget(2), 1)                     # no promise

    def test_a_different_length_is_left_alone_and_the_promise_kept(self):
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        self.assertEqual(self.lib.fpl_fixture_writer_flush(1, 4096), OK)
        self.assertEqual(self.fget(0), 4096)
        self.assertEqual(self.fget(3), 1)
        self.assertEqual(self.lib.fpl_fixture_file_word(1, 4), 8)
        self.assertNotEqual(self.lib.fpl_fixture_flush(1, 0), NONE)
        self.assertEqual(self.lib.fpl_fixture_writer_flush(1, 0), OK)   # the real one
        self.assertEqual(self.fget(1), 1)

    def test_a_writer_of_another_shape_is_not_touched(self):
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        stock = 0x13400 + ((self.get(RASTER) + 0x1FF) & ~0x1FF)
        for count in (0, 2):
            with self.subTest(count=count):
                self.lib.fpl_fixture_writer_shape(count)
                self.assertEqual(self.lib.fpl_fixture_writer_flush(1, 0), OK)
                self.assertEqual(self.fget(0), stock)
                self.assertEqual(self.lib.fpl_fixture_file_word(1, 4), 8)
                self.assertNotEqual(self.lib.fpl_fixture_flush(1, 0), NONE, 'promise lost')
        self.assertEqual(self.fget(5), 2)
        self.lib.fpl_fixture_writer_shape(1)
        self.assertEqual(self.lib.fpl_fixture_writer_flush(1, 0), OK)
        self.assertEqual(self.fget(1), 1)

    def test_a_header_that_is_not_the_takes_template_is_recorded_and_not_retried(self):
        """The payload is already in the raster: that frame is lost either
        way. It must be counted, its promise consumed, and nothing written."""
        self.frames(1, 2)
        self.lib.fpl_fixture_arrive(1)
        self.lib.fpl_fixture_arrive(2)
        self.lib.fpl_fixture_file_poke(1, 0, 0x2A004D4D)     # big-endian magic
        stock = 0x13400 + ((self.get(RASTER) + 0x1FF) & ~0x1FF)
        self.assertEqual(self.lib.fpl_fixture_writer_flush(1, 0), FAULT)
        self.assertEqual(self.fget(4), 1)
        self.assertEqual(self.fget(0), stock)
        self.assertEqual(self.lib.fpl_fixture_file_word(1, 4), 8)
        self.assertEqual(self.lib.fpl_fixture_flush(1, 0), NONE)


class SwapFlushSiteTests(FlushSiteTests):
    """The flush finds the file where the swap put it."""
    SPARE = 1
    test_the_copy_back_goes_through_the_uncached_alias_and_publishes_behind_barriers = \
        SwapHoldTests.test_the_copy_back_goes_through_the_uncached_alias_and_publishes_behind_barriers


class HoldMutationTests(unittest.TestCase):
    MUTATIONS = {
        'the promise keeps the default grid': (
            '        c->tile_width = h->job.tile_width;', '        c->tile_width = FPL_TILE_WIDTH;'),
        'the force never reaches the engine': (
            '    in->tile_force = h->tile_force;', '    in->tile_force = 0;'),
        'services after the new frame instead of before': (
            '    service(h, 0);\n    if (!admit(h, creator',
            '    if (!admit(h, creator'),
        'does not mark the frame pending': (
            '    poke(frame + FRAME_STATE, STATE_PENDING);', ''),
        'copies into the NEXT frame': (
            '        bulk_copy(uncached(lease->buffer + h->head), uncached(output->bytes),',
            '        bulk_copy(uncached(lease->buffer + 0x60000u + h->head), uncached(output->bytes),'),
        'skips the format check': (
            '    if (!fpl_producer_facts_match(h->facts, descriptor)) {',
            '    if (0 && !fpl_producer_facts_match(h->facts, descriptor)) {'),
        'holds without a promise slot': ('    if (free_slot(h) < 0) {',
                                         '    if (0 && free_slot(h) < 0) {'),
        'publishes before the payload is there': (
            '        barrier();\n        c->file = file;                      /* published */',
            '        c->file = file;\n        barrier();'),
        'keeps the frame when the engine never finishes': (
            '    if (result == FPL_BUSY && h->frame) {', '    if (0) {'),
        'treats a refusal as a fault': (
            '    } else if (result == FPL_UNSUPPORTED) {', '    } else if (0) {'),
        'forgets to give back on a refused start': (
            '    native_enqueue(h->creator, h->native_id, 1);\n    h->frame = 0;\n'
            '    h->swapping = 0;\n    fpl_pipeline_reap(h->pipeline, &h->token, h->job',
            '    h->frame = 0;\n    h->swapping = 0;\n    fpl_pipeline_reap(h->pipeline, &h->token, h->job'),
        'reads past the 1 KiB boundary': (
            '    return ((capacity + 0x3ffu) & ~0x3ffu) - HEADER_RESERVE;',
            '    return ((capacity + 0x7ffu) & ~0x3ffu) - HEADER_RESERVE;'),
        'refuses what the 1 KiB window covers': (
            '    return ((capacity + 0x3ffu) & ~0x3ffu) - HEADER_RESERVE;',
            '    return capacity - HEADER_RESERVE;'),
    }

    SWAP_MUTATIONS = {
        'swaps without the header': (
            '            uint32_t dma_r = header_dma(spare, a, HEADER_RESERVE);',
            '            uint32_t dma_r = 0;'),
        'no CPU copy when the DMA refuses': (
            '                bulk_copy(uncached(spare), uncached(a), HEADER_RESERVE);\n', ''),
        'DMA through the uncached alias': (
            '            uint32_t dma_r = header_dma(spare, a, HEADER_RESERVE);',
            '            uint32_t dma_r = header_dma(uncached(spare), uncached(a), HEADER_RESERVE);'),
        'leaves the raster pointer on A': (
            '            poke(frame + FRAME_RASTER, spare + HEADER_RESERVE);\n', ''),
        'keeps the old record': ('            poke(frame + FRAME_HANDLE, spare);\n', ''),
        'leaves the capacity': (
            '            poke(frame + FRAME_CAPACITY, h->workspace.spare.capacity);\n', ''),
        'ignores clones': ('           peek(frame + FRAME_CLONES) == 0 &&\n', ''),
        'ignores a frame that does not own its allocation': (
            '           peek(frame + FRAME_OWNER) == OWNS_ALLOCATION &&\n', ''),
        'does not look again at the release': (
            '        if (h->swapping && swap_allowed(h, h->frame)) {', '        if (h->swapping) {'),
        'never takes A as the next spare': ('            h->workspace.spare.handle = a;\n', ''),
        'publishes the old file buffer': ('            file = spare + HEADER_RESERVE - h->head;\n', ''),
        'accepts a smaller spare': (
            '           h->workspace.spare.capacity >= peek(frame + FRAME_CAPACITY);',
            '           1;'),
        'encodes into the workspace but swaps': (
            '    in->destination = h->swapping ? h->workspace.spare.handle + HEADER_RESERVE',
            '    in->destination = 0 ? h->workspace.spare.handle + HEADER_RESERVE'),
    }

    @staticmethod
    def against(lib, base=None):
        class Against(base or HoldTests):
            @classmethod
            def setUpClass(cls):
                cls.lib = lib

            @classmethod
            def tearDownClass(cls):
                pass
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(Against).run(result)
        return result

    def test_the_real_module_passes_the_same_harness(self):
        with tempfile.TemporaryDirectory(prefix='fpl-hold-real-') as tmp:
            lib = build(tmp)
            for base in (HoldTests, SwapHoldTests):
                result = self.against(lib, base)
                self.assertTrue(result.wasSuccessful(), result.failures + result.errors)

    def test_every_mutation_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='fpl-hold-mut-') as tmp:
            for index, (name, seam) in enumerate(self.MUTATIONS.items()):
                with self.subTest(mutation=name):
                    result = self.against(build(tmp, seam, f'm{index}.dylib'))
                    self.assertFalse(result.wasSuccessful(), f'{name} was not caught')

    def test_every_swap_mutation_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='fpl-swap-mut-') as tmp:
            for index, (name, seam) in enumerate(self.SWAP_MUTATIONS.items()):
                with self.subTest(mutation=name):
                    result = self.against(build(tmp, seam, f's{index}.dylib'), SwapHoldTests)
                    self.assertFalse(result.wasSuccessful(), f'{name} was not caught')


class FlushMutationTests(unittest.TestCase):
    MUTATIONS = {
        'ignores the stock length': (
            'flush_site.c', '    if (length != c->stock_bytes) {',
            '    if (length != c->stock_bytes && 0) {'),
        'shortens before the IFD is complete': (
            'flush_site.c',
            '    if (!tag || c->head != tag->head ||',
            '    poke(node + NODE_LENGTH, 1024);\n    if (!tag || c->head != tag->head ||'),
        'never consumes the promise': (
            'flush_site.c', '    fpl_hold_consumed(h, c);\n    saturate(&s->applied);',
            '    saturate(&s->applied);'),
        'skips the shape check': (
            'flush_site.c', '    if (!writer || (writer & 3u) || peek(writer + WRITER_COUNT) != 1 ||',
            '    if (!writer || (writer & 3u) ||'),
        'leaves the length stock': (
            'flush_site.c', '    poke(node + NODE_LENGTH, rounded);', '    (void)rounded;'),
    }

    def test_every_mutation_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='fpl-flush-mut-') as tmp:
            for index, (name, seam) in enumerate(self.MUTATIONS.items()):
                with self.subTest(mutation=name):
                    lib = build(tmp, seam, f'f{index}.dylib')

                    class Against(FlushSiteTests):
                        @classmethod
                        def setUpClass(cls):
                            cls.lib = lib

                        @classmethod
                        def tearDownClass(cls):
                            pass
                    result = unittest.TestResult()
                    unittest.defaultTestLoader.loadTestsFromTestCase(Against).run(result)
                    self.assertFalse(result.wasSuccessful(), f'{name} was not caught')


IDLE_L, HELD_L, RUNNING_L, FINISHED_L, FAULT_L = range(5)
L_STALLS = 18
ENQ_CALLS = 19
(L_STATE, L_COMPRESSED, L_HELD, L_CHAINED, L_FAULTS, L_PHASE, L_ORDER, L_FULL,
 IRQ_DEPTH, IRQ_OFFS, IRQ_BAD, SLEEPS, L_DRAINED, L_SWAPPED, ENGINE_RUNNING) = range(15)


class LaneTests(unittest.TestCase):
    """Two lanes, one engine, the codec task (as the card runs them, with no
    output span): the next frame waits already held while the engine works,
    and the task starts it in the same pass that finds the engine done."""
    SECOND = 1

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-lanes-')
        cls.lib = build(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.lib.fpl_fixture_no_output(0)
        cls.lib.fpl_fixture_use_spare(0)
        cls.tmp.cleanup()

    def reset(self, latency=0):
        self.lib.fpl_fixture_no_output(1)
        self.lib.fpl_fixture_use_spare(1)
        self.assertEqual(self.lib.fpl_fixture_reset(latency, SMALL_PAYLOAD, 1), OK)
        self.assertEqual(self.lib.fpl_fixture_lanes(self.SECOND), OK)

    def setUp(self):
        self.reset()

    def get(self, f): return self.lib.fpl_fixture_get(f)
    def lane(self, n, f): return self.lib.fpl_fixture_lane_get(n, f)
    def state(self): return (self.lane(0, L_STATE), self.lane(1, L_STATE))

    def frames(self, *ids):
        for i in ids:
            self.lib.fpl_fixture_frame(i, GRANTED_EXTRA)

    def queued(self):
        n = self.get(ENQ_N)
        return [(self.get(1000 + k), self.get(2000 + k)) for k in range(n)]

    def assert_same_frame(self):
        for frame, word in self.queued():
            self.assertIn(word, (raw(frame), packed(frame)),
                          f'frame {frame} was queued holding {word:#x}')

    def task(self, passes=1):
        for _ in range(passes):
            self.lib.fpl_fixture_task()
            a, b = self.state()
            # one engine, and never idle while a frame waits for it
            self.assertFalse(a == RUNNING_L and b == RUNNING_L)
            if HELD_L in (a, b):
                self.assertIn(RUNNING_L, (a, b), 'a frame waited on an idle engine')

    def assert_clean(self):
        self.assertEqual(self.get(OOB), 0)
        self.assertEqual(self.lane(0, IRQ_DEPTH), 0)
        self.assertEqual(self.lane(0, IRQ_BAD), 0)

    def test_the_next_frame_starts_in_the_same_pass_that_finds_the_engine_done(self):
        self.reset(latency=2)
        self.frames(1, 2, 3)
        self.lib.fpl_fixture_lane_arrive(1)
        self.assertEqual(self.state(), (HELD_L, IDLE_L))
        self.task()
        self.assertEqual(self.state(), (RUNNING_L, IDLE_L))
        self.lib.fpl_fixture_lane_arrive(2)              # engine busy: held, waiting
        self.assertEqual(self.state(), (RUNNING_L, HELD_L))
        self.assertEqual(self.get(4000 + 2), 0xB)
        self.task(2)                                     # still encoding 1
        self.assertEqual(self.state(), (RUNNING_L, HELD_L))
        self.lib.fpl_fixture_task()                      # 1 done -> 2 started
        self.assertEqual(self.state(), (FINISHED_L, RUNNING_L))
        self.assertEqual(self.get(ENQ_N), 0, 'released off the arrival side')
        self.lib.fpl_fixture_lane_arrive(3)              # collects 1, holds 3
        self.assertEqual(self.queued(), [(1, packed(1))])
        self.assertEqual(self.state(), (HELD_L, RUNNING_L))
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)
        self.assertEqual(self.queued(), [(i, packed(i)) for i in (1, 2, 3)])
        self.assert_clean()

    def test_a_waiting_pass_waits_on_the_running_job_and_starts_the_next_at_once(self):
        self.reset(latency=3)
        self.frames(1, 2)
        self.lib.fpl_fixture_lane_arrive(1)
        self.assertEqual(self.lib.fpl_fixture_task_wait(10), 2)        # started; nothing to wait on
        self.assertEqual(self.lib.fpl_fixture_twai(0), 0)
        self.lib.fpl_fixture_lane_arrive(2)
        self.assertEqual(self.lib.fpl_fixture_task_wait(10), 4 | 2 | 1)  # waited, 1 done, 2 started
        self.assertEqual(self.lib.fpl_fixture_twai(0), 1, 'one wait, not a poll loop')
        self.assertEqual(self.lib.fpl_fixture_twai(1), 10)
        self.assertEqual(self.state(), (FINISHED_L, RUNNING_L))
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)
        self.assertEqual(self.queued(), [(1, packed(1)), (2, packed(2))])
        self.assert_clean()

    def test_a_wait_that_ends_before_the_job_says_it_waited_and_finishes_nothing(self):
        self.reset(latency=25)
        self.frames(1)
        self.lib.fpl_fixture_lane_arrive(1)
        self.lib.fpl_fixture_task_wait(10)                             # started
        self.assertEqual(self.lib.fpl_fixture_task_wait(10), 4)        # 10 of 25
        self.assertEqual(self.lib.fpl_fixture_task_wait(10), 4)        # 20 of 25
        self.assertEqual(self.state(), (RUNNING_L, IDLE_L))
        self.assertEqual(self.lib.fpl_fixture_task_wait(10), 4 | 1)
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)
        self.assert_clean()

    def test_with_nothing_running_a_waiting_pass_does_not_wait(self):
        self.assertEqual(self.lib.fpl_fixture_task_wait(10), 0)
        self.assertEqual(self.lib.fpl_fixture_twai(0), 0)

    def test_the_plain_pass_still_polls_one_tick(self):
        self.reset(latency=3)
        self.frames(1)
        self.lib.fpl_fixture_lane_arrive(1)
        self.lib.fpl_fixture_task()
        self.assertEqual(self.lib.fpl_fixture_task() & 4, 0)
        self.assertEqual(self.lib.fpl_fixture_twai(1), 1)
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)

    def test_a_long_take_queues_every_frame_once_and_keeps_the_engine_busy(self):
        self.reset(latency=3)
        ids = list(range(1, 21))
        self.frames(*ids)
        for i in ids:
            self.lib.fpl_fixture_lane_arrive(i)
            self.task(3)                                  # a frame period: 3 passes
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)
        q = self.queued()
        self.assertEqual(sorted(i for i, _ in q), ids, 'a frame was lost or duplicated')
        self.assert_same_frame()
        packed_ids = [i for i, w in q if w == packed(i)]
        self.assertEqual(packed_ids, sorted(packed_ids), 'compressed out of order')
        self.assertGreater(self.lane(0, L_COMPRESSED) + self.lane(1, L_COMPRESSED), 13)
        self.assertEqual(self.get(OWNERS_DISTINCT), 1)
        for n in (0, 1):
            self.assertEqual(self.lib.fpl_fixture_lane_finish(n), OK)
        self.assert_clean()

    def test_stop_lets_the_task_run_what_is_held_and_gives_everything_back(self):
        self.reset(latency=2)
        self.frames(1, 2)
        self.lib.fpl_fixture_lane_arrive(1)
        self.lib.fpl_fixture_lane_arrive(2)
        self.assertEqual(self.state(), (HELD_L, HELD_L))
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)
        self.assertEqual(self.queued(), [(1, packed(1)), (2, packed(2))])
        self.assertGreater(self.lane(0, SLEEPS), 0)
        self.assertEqual((self.lane(0, L_PHASE), self.lane(1, L_PHASE)), (FREE, FREE))
        for n in (0, 1):
            self.assertEqual(self.lib.fpl_fixture_lane_finish(n), OK)
        self.assert_clean()

    def test_a_job_the_engine_never_finishes_is_given_up_and_compression_goes_on(self):
        # 2026-10-02: one job in a long take never signalled; every later
        # frame went out uncompressed and two held frames were lost
        self.lib.fpl_fixture_mode(MODE_NEVER_ONCE)
        self.frames(1, 2, 3)
        self.lib.fpl_fixture_lane_arrive(1)
        self.lib.fpl_fixture_task()
        self.lib.fpl_fixture_lane_arrive(2)              # waits behind the stuck job
        for _ in range(40):                               # 40 ms: under the 50 ms floor
            self.lib.fpl_fixture_task()
        self.assertEqual(self.state(), (RUNNING_L, HELD_L), 'given up too early')
        for _ in range(20):                               # past it: given up, not 0.5 s later
            self.lib.fpl_fixture_task()
        self.assertEqual(self.lane(0, L_STALLS), 1)
        self.lib.fpl_fixture_lane_arrive(3)              # collects 1 (as it was)
        self.assertEqual(self.queued()[0], (1, raw(1)))
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)
        self.assertEqual(sorted(self.queued()), [(1, raw(1)), (2, packed(2)), (3, packed(3))])
        for n in range(1 + self.SECOND):
            self.assertEqual(self.lib.fpl_fixture_lane_finish(n), OK)
        self.assert_clean()

    def test_an_engine_that_never_finishes_cannot_hang_stop_or_queue_twice(self):
        self.lib.fpl_fixture_mode(MODE_NEVER)
        self.frames(1, 2)
        self.lib.fpl_fixture_lane_arrive(1)
        self.task()
        self.lib.fpl_fixture_lane_arrive(2)
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)   # given up inside stop's wait
        self.assertEqual(sorted(self.queued()), [(1, raw(1)), (2, raw(2))])
        self.lib.fpl_fixture_task()
        self.lib.fpl_fixture_lane_stop()
        self.assertEqual(len(self.queued()), 2, 'a frame was queued twice')
        self.assertEqual(self.lane(0, L_STATE), IDLE_L)
        self.assertGreaterEqual(self.lane(0, L_STALLS) + self.lane(1, L_STALLS), 1)
        for n in range(1 + self.SECOND):
            self.assertEqual(self.lib.fpl_fixture_lane_finish(n), OK)

    def test_a_completion_the_pipeline_refuses_still_gives_the_frame_back(self):
        self.frames(1, 2)
        self.lib.fpl_fixture_lane_arrive(1)
        self.task(2)
        self.assertEqual(self.lane(0, L_STATE), FINISHED_L)
        self.lib.fpl_fixture_pipeline_phase(HELD)      # complete() will refuse
        self.lib.fpl_fixture_lane_arrive(2)
        self.assertEqual([i for i, _ in self.queued()].count(1), 1, 'the finished frame was kept')
        self.assertEqual(self.lane(0, L_FAULTS), 1)

    def test_engine_refusals_in_both_lanes_give_every_frame_back(self):
        self.reset(latency=1)
        self.lib.fpl_fixture_mode(MODE_REFUSE)
        ids = list(range(1, 7))
        self.frames(*ids)
        for i in ids:
            self.lib.fpl_fixture_lane_arrive(i)
            self.task(2)
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)
        self.assertEqual(sorted(self.queued()), [(i, raw(i)) for i in ids])
        self.assertEqual(self.lane(0, L_FAULTS) + self.lane(1, L_FAULTS), 0)
        self.assertEqual(self.state(), (IDLE_L, IDLE_L))
        for n in range(1 + self.SECOND):
            self.assertEqual(self.lib.fpl_fixture_lane_finish(n), OK)

    def test_a_job_still_running_when_a_starved_task_lets_stop_give_up(self):
        # stop gives the frame back itself; the job, finished later, must not
        # give it back a second time
        self.lib.fpl_fixture_mode(MODE_NEVER)
        self.frames(1)
        self.lib.fpl_fixture_lane_arrive(1)
        self.lib.fpl_fixture_task()
        self.lib.fpl_fixture_task_in_sleep(0)
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), FAULT)
        self.assertEqual(self.queued(), [(1, raw(1))])
        self.lib.fpl_fixture_task_in_sleep(1)
        for _ in range(300):
            self.lib.fpl_fixture_task()
        self.lib.fpl_fixture_lane_stop()
        self.assertEqual(self.queued(), [(1, raw(1))], 'given back twice')

    def test_a_frame_given_back_at_stop_is_never_started(self):
        self.frames(1)
        self.lib.fpl_fixture_lane_arrive(1)
        self.assertEqual(self.lib.fpl_fixture_lane_abandon(0), OK)
        self.assertEqual(self.queued(), [(1, raw(1))])
        self.lib.fpl_fixture_task()
        self.assertEqual(self.get(STARTS), 0)
        self.assertEqual(self.lane(0, L_STATE), IDLE_L)
        self.assertEqual(self.lane(0, L_PHASE), FREE)
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)
        self.assertEqual(self.lib.fpl_fixture_lane_finish(0), OK)
        self.assertEqual(self.queued(), [(1, raw(1))])
        self.assert_clean()

    def test_starved_worker_stop_cancels_both_never_started_leases(self):
        self.frames(1, 2)
        self.lib.fpl_fixture_lane_arrive(1)
        self.lib.fpl_fixture_lane_arrive(2)
        self.lib.fpl_fixture_task_in_sleep(0)
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), OK)
        self.assertEqual(self.queued(), [(1, raw(1)), (2, raw(2))])
        self.assertEqual(self.state(), (IDLE_L, IDLE_L))
        for n in (0, 1):
            self.assertEqual(self.lane(n, L_PHASE), FREE)
            self.assertEqual(self.lib.fpl_fixture_lane_finish(n), OK)
        self.lib.fpl_fixture_task()
        self.lib.fpl_fixture_lane_stop()
        self.assertEqual(self.get(STARTS), 0)
        self.assertEqual(self.get(ENQ_N), 2)
        self.assert_clean()

    def test_cancel_does_not_claim_transfer_on_a_refused_enqueue(self):
        for native_result in (0, 2):
            with self.subTest(native_result=native_result):
                self.reset()
                self.frames(1)
                self.lib.fpl_fixture_lane_arrive(1)
                self.lib.fpl_fixture_enqueue_result(native_result)
                self.assertEqual(self.lib.fpl_fixture_lane_abandon(0), FAULT)
                self.assertEqual((self.lane(0, L_STATE), self.lane(0, L_PHASE)),
                                 (FAULT_L, HELD))
                self.assertEqual(self.lib.fpl_fixture_lane_finish(0), BUSY)
                self.assertEqual(self.lane(0, ENQ_CALLS), 1)
                self.lib.fpl_fixture_enqueue_result(1)
                self.lib.fpl_fixture_lane_stop()
                self.lib.fpl_fixture_task()
                self.assertEqual(self.lane(0, ENQ_CALLS), 1, 'uncertain enqueue retried')
                self.assertEqual(self.get(ENQ_N), 0)
                self.assertEqual(self.get(STARTS), 0)
                self.assert_clean()

    def test_cancel_requires_the_same_queueable_pending_native_frame(self):
        for field, value in ((0, 0), (4, 9), (0x1104, 0xD), (None, 0)):
            with self.subTest(field=field):
                self.reset()
                self.frames(1)
                self.lib.fpl_fixture_lane_arrive(1)
                if field is None:
                    self.lib.fpl_fixture_present(1, 0)
                else:
                    self.lib.fpl_fixture_frame_field(1, field, value)
                self.assertEqual(self.lib.fpl_fixture_lane_abandon(0), FAULT)
                self.assertEqual(self.lane(0, L_PHASE), HELD)
                self.assertEqual(self.lib.fpl_fixture_lane_finish(0), BUSY)
                self.assertEqual(self.lane(0, ENQ_CALLS), 0)
                self.assert_clean()

    def test_unknown_engine_failure_fences_both_lanes_before_the_next_kick(self):
        for failure in ('wait', 'close'):
            for return_at in ('arrival', 'stop'):
                with self.subTest(failure=failure, return_at=return_at):
                    self.reset()
                    self.frames(1, 2, 3, 4)
                    self.lib.fpl_fixture_lane_arrive(1)
                    self.lib.fpl_fixture_task()
                    self.lib.fpl_fixture_lane_arrive(2)
                    if failure == 'wait':
                        self.lib.fpl_fixture_mode(MODE_WAIT_ERROR)
                    else:
                        self.lib.fpl_fixture_close_fails(1)
                    self.lib.fpl_fixture_task()
                    self.assertEqual(self.state(), (FINISHED_L, HELD_L))
                    self.assertEqual(self.get(STARTS), 1)
                    self.assertEqual(self.get(CLOSES), 0 if failure == 'wait' else 1)
                    self.assertEqual(self.get(ENQ_N), 0, 'worker called native enqueue')
                    self.assert_clean()
                    if return_at == 'arrival':
                        self.lib.fpl_fixture_lane_arrive(3)
                        self.assertEqual(self.queued(), [(i, raw(i)) for i in (1, 2, 3)])
                        self.assertEqual(self.state(), (FAULT_L, IDLE_L))
                        self.lib.fpl_fixture_lane_arrive(4)
                        self.assertEqual(self.lane(1, L_STATE), IDLE_L, 'new work admitted')
                    self.assertEqual(self.lib.fpl_fixture_lane_stop(), FAULT)
                    self.assertEqual(self.lane(0, SLEEPS), 0, 'waited for a fenced HELD job')
                    self.assertEqual(self.lane(0, L_PHASE), ENCODING)
                    self.assertEqual(self.lane(1, L_PHASE), FREE)
                    self.assertEqual(self.lib.fpl_fixture_lane_finish(0), BUSY)
                    self.assertEqual(self.lib.fpl_fixture_lane_finish(1), OK)
                    before = self.queued()
                    self.lib.fpl_fixture_task()
                    self.lib.fpl_fixture_lane_stop()
                    self.assertEqual(self.queued(), before)
                    self.assertEqual([i for i, _ in before].count(1), 1)
                    self.assertEqual([i for i, _ in before].count(2), 1)
                    self.assertEqual(self.get(STARTS), 1)
                    self.assert_clean()

    def test_a_failed_second_lane_also_fences_the_first_lane(self):
        self.frames(1, 2, 3, 4)
        self.lib.fpl_fixture_lane_arrive(1)
        self.lib.fpl_fixture_task()                        # A running
        self.lib.fpl_fixture_lane_arrive(2)
        self.lib.fpl_fixture_task()                        # A finished, B running
        self.lib.fpl_fixture_lane_arrive(3)                 # A holds 3, 1 queued
        self.assertEqual(self.queued(), [(1, packed(1))])
        self.lib.fpl_fixture_mode(MODE_WAIT_ERROR)
        self.lib.fpl_fixture_task()
        self.assertEqual(self.state(), (HELD_L, FINISHED_L))
        self.assertEqual(self.get(STARTS), 2)
        self.assertEqual(self.get(ENQ_N), 1, 'worker performed the transfer')
        self.assert_clean()
        self.lib.fpl_fixture_lane_arrive(4)
        self.assertEqual(self.queued(), [(1, packed(1)), (2, raw(2)), (3, raw(3)), (4, raw(4))])
        self.assertEqual(self.state(), (IDLE_L, FAULT_L))
        self.assertEqual(self.lib.fpl_fixture_lane_stop(), FAULT)
        self.assertEqual(self.lane(0, L_PHASE), FREE)
        self.assertEqual(self.lane(1, L_PHASE), ENCODING)
        self.lib.fpl_fixture_task()
        self.assertEqual(self.get(STARTS), 2)
        self.assert_clean()

    def test_a_start_the_engine_refuses_gives_the_frame_back_at_the_next_arrival(self):
        self.lib.fpl_fixture_open_fails(1)
        self.frames(1, 2)
        self.lib.fpl_fixture_lane_arrive(1)
        self.task()
        self.assertEqual(self.lane(0, L_STATE), FINISHED_L)
        self.lib.fpl_fixture_open_fails(0)
        self.lib.fpl_fixture_lane_arrive(2)
        self.assertEqual(self.queued()[0], (1, raw(1)))
        # given back and the lane free; the pipeline admits no more after a
        # refused start, but that is not an engine fault
        self.assertEqual((self.lane(0, L_STATE), self.lane(0, L_FAULTS)), (IDLE_L, 0))
        self.lib.fpl_fixture_lane_stop()
        self.assertEqual(sorted(i for i, _ in self.queued()), [1, 2])
        self.assert_clean()

    def test_a_finished_lane_is_collected_by_one_side_only(self):
        self.frames(1, 2)
        self.lib.fpl_fixture_lane_arrive(1)
        self.task(2)
        self.assertEqual(self.lane(0, L_STATE), FINISHED_L)
        self.lib.fpl_fixture_reenter(1)                 # stop's wait comes in mid-collect
        self.lib.fpl_fixture_lane_arrive(2)
        self.assertEqual(self.queued()[0], (1, packed(1)))
        self.assertEqual(self.lane(0, L_FAULTS), 0)
        self.lib.fpl_fixture_lane_stop()
        self.assertEqual(sorted(i for i, _ in self.queued()), [1, 2])
        self.assert_same_frame()
        self.assert_clean()

    def test_only_a_held_lane_can_be_started(self):
        self.reset(latency=3)
        self.frames(1)
        self.assertEqual(self.lib.fpl_fixture_kick(0), 0)            # idle
        self.lib.fpl_fixture_lane_arrive(1)
        self.assertEqual(self.lib.fpl_fixture_kick(0), 1)
        self.assertEqual(self.lib.fpl_fixture_kick(0), 0)            # running
        self.assertEqual(self.get(STARTS), 1)
        self.assert_clean()

    def test_the_claim_is_made_with_interrupts_off(self):
        self.frames(1)
        self.lib.fpl_fixture_lane_arrive(1)
        self.task()
        self.assertGreater(self.lane(0, IRQ_OFFS), 0)
        self.assert_clean()

    def test_when_both_lanes_are_busy_a_frame_goes_through_as_it_is(self):
        self.reset(latency=5)
        self.frames(1, 2, 3)
        self.lib.fpl_fixture_lane_arrive(1)
        self.task()
        self.lib.fpl_fixture_lane_arrive(2)
        self.lib.fpl_fixture_lane_arrive(3)
        self.assertEqual(self.queued(), [(3, raw(3))])
        self.assertEqual(self.lane(0, L_FULL), 1)
        self.lib.fpl_fixture_lane_stop()
        self.assert_same_frame()

    def test_the_flush_finds_a_promise_in_either_lane(self):
        self.reset(latency=1)
        self.frames(1, 2, 3)
        for i in (1, 2, 3):
            self.lib.fpl_fixture_header(i)
        self.lib.fpl_fixture_lane_arrive(1)
        self.task()
        self.lib.fpl_fixture_lane_arrive(2)
        self.task(2)
        self.lib.fpl_fixture_lane_arrive(3)
        self.lib.fpl_fixture_lane_stop()
        self.assertGreater(self.lane(1, L_COMPRESSED), 0)
        for i in (1, 2, 3):
            self.assertEqual(self.lib.fpl_fixture_writer_flush(i, 0), OK)
        self.assertEqual(self.lib.fpl_fixture_flush_get(1), 3)


class LaneMutationTests(unittest.TestCase):
    MUTATIONS = {
        'kicks without claiming': (
            '    if (h->lane != FPL_LANE_HELD) { irq_restore(mask); return 0; }\n', ''),
        'claims with interrupts on': (
            '    mask = irq_off();\n    if (h->lane != FPL_LANE_HELD) { irq_restore(mask); return 0; }',
            '    mask = 0;\n    if (h->lane != FPL_LANE_HELD) { return 0; }'),
        'starts while another lane runs': (
            '    if (first->lane == FPL_LANE_RUNNING || (second && second->lane == FPL_LANE_RUNNING))\n'
            '        return moved;                /* one engine */\n', ''),
        'waits a pass before starting the next': (
            '    if (!next) return moved;', '    if (!next || moved) return moved;'),
        'starts the newest held frame first': (
            '    if (first->lane == FPL_LANE_HELD) next = first;\n'
            '    else if (second && second->lane == FPL_LANE_HELD) next = second;',
            '    if (second && second->lane == FPL_LANE_HELD) next = second;\n'
            '    else if (first->lane == FPL_LANE_HELD) next = first;'),
        'forgets the frame stop already gave back': (
            '        h->abandoned = 1;\n', ''),
        'stop does not wait for the task': (
            '        sleep_ms(1);\n', '        break;\n'),
        'abandons a held frame without giving it back': (
            '            native_enqueue(h->creator, h->native_id, 1) != 1)',
            '            0)'),
        'held cancellation uses retained-only reap': (
            'result = fpl_pipeline_cancel_held(h->pipeline, &h->token, 1);',
            'result = fpl_pipeline_reap(h->pipeline, &h->token, 1, 1);'),
        'cancel assumes a refused enqueue succeeded': (
            'native_enqueue(h->creator, h->native_id, 1) != 1)',
            '(native_enqueue(h->creator, h->native_id, 1), 0))'),
        'cancel ignores native queueable flag': (
            '            !(peek(h->frame) & 0xffu) ||\n', ''),
        'cancel ignores native frame identity': (
            'native_frame(h->native_id) != h->frame ||', '0 ||'),
        'restarts unknown shared hardware': (
            '    if (engine_failed(lane)) return moved;  /* unknown hardware is not idle */\n', ''),
        'checks only the first codec job for failure': (
            '        if (hold_valid(lane[n]) && lane[n]->job.phase == FPL_CODEC_FAILED) return 1;',
            '        if (n == 0 && hold_valid(lane[n]) && lane[n]->job.phase == FPL_CODEC_FAILED) return 1;'),
        'stop waits for work the failed engine cannot start': (
            '        if (engine_failed(lane)) {\n'
            '            if (first->lane == FPL_LANE_HELD) fpl_hold_abandon(first);\n'
            '            if (second && second->lane == FPL_LANE_HELD) fpl_hold_abandon(second);\n'
            '        }\n', ''),
        'the task polls instead of waiting': (
            '    result = fpl_codec_job_wait(&h->job, ticks);', '    result = fpl_codec_job_wait(&h->job, 0);'),
        'a wait is not reported': ('waited = ticks ? 4u : 0u;', 'waited = 0u;'),
        'a pass reports a wait it never made': (
            '    if (!hold_valid(h) || h->lane != FPL_LANE_RUNNING) return 0;\n    uint32_t took, polled',
            '    if (!hold_valid(h) || h->lane != FPL_LANE_RUNNING) return ticks ? 4u : 0u;\n    uint32_t took, polled'),
        'checks engine failure only before polling': (
            '    moved |= check(first, ticks);\n'
            '    if (second) moved |= check(second, ticks);\n'
            '    if (engine_failed(lane)) return moved;  /* unknown hardware is not idle */',
            '    if (engine_failed(lane)) return moved;\n'
            '    moved |= check(first, ticks);\n'
            '    if (second) moved |= check(second, ticks);'),
        'collects without claiming': (
            '    if (h->lane != FPL_LANE_FINISHED) { irq_restore(mask); return FPL_BUSY; }\n'
            '    h->lane = FPL_LANE_COLLECTING;\n',
            '    if (h->lane != FPL_LANE_FINISHED && h->lane != FPL_LANE_COLLECTING)'
            ' { irq_restore(mask); return FPL_BUSY; }\n'),
        'a failed start is left held': (
            '        h->lane_failed = 1;\n', ''),
        'refusal points the pipeline at no output': (
            '        out.bytes = h->job.destination;', '        out.bytes = h->workspace.output;'),
        'a failed completion keeps the frame': (
            '        if (h->frame) {\n            native_enqueue(h->creator, h->native_id, 1);\n'
            '            h->frame = 0;\n        }\n        saturate(&h->faults);\n        return result;',
            '        saturate(&h->faults);\n        return result;'),
        'never gives up on a job': ('        if (took < h->stall_limit_us) return waited;',
                                    '        return waited;'),
        'gives up only after the old 250 checks': (
            '        if (took < h->stall_limit_us) return waited;',
            '        if (h->job.polls < 250u) return waited;'),
        'gives up and calls it a fault': (
            '        result = fpl_codec_job_abort(&h->job) == FPL_OK ? FPL_UNSUPPORTED : FPL_FAULT;',
            '        result = fpl_codec_job_abort(&h->job) == FPL_OK ? FPL_FAULT : FPL_FAULT;'),
        'flush looks in one lane only': (
            'flush_site.c', '        h = h2;                          /* the second lane\'s promise */',
            '        (void)h2;'),
    }

    def test_every_mutation_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='fpl-lane-mut-') as tmp:
            for index, (name, seam) in enumerate(self.MUTATIONS.items()):
                with self.subTest(mutation=name):
                    lib = build(tmp, seam, f'l{index}.dylib')

                    class Against(LaneTests):
                        @classmethod
                        def setUpClass(cls):
                            cls.lib = lib

                        @classmethod
                        def tearDownClass(cls):
                            pass
                    result = unittest.TestResult()
                    unittest.defaultTestLoader.loadTestsFromTestCase(Against).run(result)
                    self.assertFalse(result.wasSuccessful(), f'{name} was not caught')


class ArmCompileTests(unittest.TestCase):
    def test_it_builds_freestanding_for_the_camera(self):
        clang = shutil.which('clang') or 'clang'
        nm = shutil.which('llvm-nm') or shutil.which('nm') or 'nm'
        with tempfile.TemporaryDirectory(prefix='fpl-hold-arm-') as tmp:
            for source in ('frame_hold.c', 'flush_site.c'):
                out = Path(tmp) / (source + '.o')
                subprocess.run([clang, '--target=armv7a-none-eabi', '-mcpu=cortex-a9',
                                '-mthumb', '-mfloat-abi=soft', '-mfpu=none', '-ffreestanding',
                                '-fno-builtin', '-nostdlib', '-O2', '-std=c11', '-Wall',
                                '-Wextra', '-Werror', '-c', '-I', str(HERE),
                                str(HERE / source), '-o', str(out)],
                               check=True, capture_output=True, text=True, timeout=30)
                undefined = subprocess.run([nm, '-u', str(out)], capture_output=True,
                                           text=True).stdout
                for forbidden in ('memcpy', 'memset', '__aeabi', '_test_natives'):
                    self.assertNotIn(forbidden, undefined, f'{source}: {undefined}')


if __name__ == '__main__':
    unittest.main()
