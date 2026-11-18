"""Playback of a compressed clip: frames decoded back into the stock layout.

play_decode.c + play_decode_fixture.c on the host. A small frame in OUR
layout (IFD0 at 8 describing the uncompressed strip, the root moved to a
trailing IFD with Compression 7 and a contiguous tile table) is built here;
its header is the clip's first frame at clip open, and the whole file is
"read" into the player's buffer -- not 1 KiB aligned, as on the camera. A fake
engine decodes whole tiles the way the real one does. Checked: clip open asks
for the stock frame size and takes the scratch; each frame's strip ends up as
the stock pixels, decoded bottom up so no row is written over a stream not yet
read; nothing is written past the buffer's capacity or anywhere else; the root
goes back to IFD0; and every frame that is not ours, or cannot be done safely,
is left exactly as it was read.

No camera, USB or card.
"""
import ctypes as ct
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
(R_SLOT, R_TIFF, R_ROOT, R_FORMAT, R_TILES, R_IFD0, R_ROOM, R_ORDER, R_SCRATCH, R_ENGINE,
 R_COPY, R_BUSY) = range(12)
STOCK, DECODED = 0xFE, 0xFF
SEEN, N_STOCK, N_DECODED, OOB, BAD_WRITES, OPENS, CLOSES, ALLOCS, RELEASES, DMAS, \
    SUBMITS, MISALIGNED, SCRATCH_BYTES, CLIPS_OURS, SYNCS, SCRATCH_FAILED, CLIP_FAILED = range(17)
(FAST, ROWS, SLOTS_ALIGNED, RESTORED, NO_SPARE, NO_ALIGN, NO_ROOM, SPARE, ROWS_TOLD, TILE_VAR, PUTS,
 SPARE_LOST, NOT_OURS, SPARE_FAILED, AHEAD_READ, AHEAD_USED, AHEAD_MISSED, AHEAD_NONE, FILE_READS,
 READS_WHILE_ENGINE, AHEAD, AHEAD_GOT, AHEAD_FAILED) = range(17, 40)


def build(directory, replace=None, name='play.dylib'):
    source = HERE / 'play_decode.c'
    if replace:
        old, new = replace
        text = source.read_text()
        if text.count(old) != 1:
            raise AssertionError('mutation seam not found once: ' + old[:60])
        source = Path(directory) / (name + '.c')
        source.write_text(text.replace(old, new))
    out = Path(directory) / name
    subprocess.run([shutil.which('clang') or 'clang', '-shared', '-fPIC', '-O2', '-std=c11',
                    '-Wall', '-Wextra', '-Werror', '-DFPL_PLAY_DECODE_HOST_TEST', '-I', str(HERE),
                    str(source), str(HERE / 'play_decode_fixture.c'), '-o', str(out)],
                   check=True, capture_output=True, text=True, timeout=60)
    lib = ct.CDLL(str(out))
    lib.fpl_fixture_load.argtypes = [ct.c_char_p, ct.c_uint32, ct.c_uint32]
    lib.fpl_fixture_load.restype = None
    for fn in ('clip', 'open'):
        getattr(lib, 'fpl_fixture_' + fn).argtypes = [ct.c_char_p, ct.c_uint32, ct.c_uint32,
                                                     ct.c_uint32]
        getattr(lib, 'fpl_fixture_' + fn).restype = ct.c_uint32
    for fn, n, ret in (('knob', 2, False), ('run', 1, True), ('byte', 1, True), ('get', 1, True),
                       ('reset', 0, False), ('end', 0, False), ('pool', 0, False),
                       ('free_pool', 0, True), ('live', 0, True), ('slot', 2, True),
                       ('slot_byte', 2, True), ('remake', 1, False), ('gate', 4, True),
                       ('slot_last', 2, False), ('big_pool', 1, False)):
        f = getattr(lib, 'fpl_fixture_' + fn)
        f.argtypes = [ct.c_uint32] * n
        f.restype = ct.c_uint32 if ret else None
    lib.fpl_fixture_open_pool.argtypes = [ct.c_char_p, ct.c_uint32, ct.c_uint32, ct.c_uint32,
                                          ct.c_uint32]
    lib.fpl_fixture_open_pool.restype = ct.c_uint32
    lib.fpl_fixture_play.argtypes = [ct.c_uint32, ct.c_char_p, ct.c_uint32]
    lib.fpl_fixture_play.restype = ct.c_uint32
    lib.fpl_fixture_disk.argtypes = [ct.c_char_p, ct.c_char_p, ct.c_uint32]
    lib.fpl_fixture_disk.restype = None
    lib.fpl_fixture_play_path.argtypes = [ct.c_uint32, ct.c_char_p]
    lib.fpl_fixture_play_path.restype = ct.c_uint32
    return lib


def ifd(entries, at, extra_at):
    """entries: (tag, type, count, value-or-bytes). Out-of-line bytes go at
    extra_at. Returns (ifd bytes, extra bytes)."""
    body, extra = b'', b''
    for tag, typ, count, val in sorted(entries):
        if isinstance(val, bytes):
            body += struct.pack('<HHII', tag, typ, count, extra_at + len(extra))
            extra += val + b'\0' * (-len(val) % 4)
        elif typ == 3:
            body += struct.pack('<HHIHH', tag, typ, count, val, 0)
        else:
            body += struct.pack('<HHII', tag, typ, count, val)
    return struct.pack('<H', len(entries)) + body + b'\0\0\0\0', extra


def default_grid(w, h):
    """tile_grid.h's default (no force): the engine's soonest legal grid."""
    best, pick = None, (512, 368)
    for tw in range(32, 513, 32):
        if w == 2 * tw:
            continue
        across = -(-w // tw)
        for th in range(16, 513, 16):
            down = -(-h // th)
            if across * down > 160:
                continue
            cost = across * tw * down * th + across * down * 32250
            if best is None or cost < best:
                best, pick = cost, (tw, th)
    return pick


def clip_size(w=96, h=74, bits=12, strip=0x400, **_):
    """What clip open asks the player's buffers to be for: the stock frame
    file, and whole default tiles below the last row."""
    pitch = ((w * bits // 8) + 3) & ~3
    th = default_grid(w, h)[1]
    stock = strip + ((raster_len(w, h, bits) + 0x1FF) & ~0x1FF)
    return max(stock, strip + pitch * (-(-h // th) * th))


def raster_len(w=96, h=74, bits=12, **_):
    pitch = ((w * bits // 8) + 3) & ~3
    return (h - 1) * pitch + ((-(-w // 12) * 12 * bits // 8 + 3) & ~3)


def frame(w=96, h=74, bits=12, tw=32, th=32, strip=0x400, ours=True, comp=7,
          ifd0_w=None, gap_at=None, tiles_n=None, cut=0, tile_len=None, rate=None):
    """A file in our layout; returns (bytes, expected strip bytes, pitch)."""
    across, down = -(-w // tw), -(-h // th)
    tiles = []
    for t in range(across * down):
        n = tile_len or 16 + 4 * ((t * 13) % 11)
        tiles.append(struct.pack('<II', n, t) + b'\x5a' * (n - 8))
    pitch = ((w * bits // 8) + 3) & ~3
    # as the recorder lays it out (C0135D40): the last row rounded to 12 px
    raster = (h - 1) * pitch + ((-(-w // 12) * 12 * bits // 8 + 3) & ~3)
    head = bytearray(b'II*\0' + b'\0\0\0\0')
    e0 = [(256, 4, 1, ifd0_w or w), (257, 4, 1, h), (258, 3, 1, bits), (259, 3, 1, 1),
          (273, 4, 1, strip), (279, 4, 1, raster)]
    if rate:
        e0.append((51044, 10, 1, struct.pack('<ii', *rate)))
    blk, extra = ifd(e0, 8, 8 + 2 + 12 * len(e0) + 4)
    head += blk + extra
    head += b'\0' * (strip - len(head))
    stream = b''.join(tiles)
    offs, at = [], strip
    for t in tiles:
        offs.append(at)
        at += len(t)
    if gap_at is not None:
        offs[gap_at] += 4
    counts = [len(t) for t in tiles]
    count_n = tiles_n or len(tiles)
    trailer_at = strip + len(stream)
    e1 = [(256, 4, 1, w), (257, 4, 1, h), (258, 3, 1, bits), (259, 3, 1, comp),
          (322, 4, 1, tw), (323, 4, 1, th),
          (324, 4, count_n, struct.pack(f'<{len(offs)}I', *offs)[:4 * count_n]),
          (325, 4, count_n, struct.pack(f'<{len(counts)}I', *counts)[:4 * count_n])]
    blk, extra = ifd(e1, trailer_at, trailer_at + 2 + 12 * len(e1) + 4)
    data = bytes(head) + stream + blk + extra
    data = bytearray(data[:len(data) - cut] if cut else data)
    struct.pack_into('<I', data, 4, trailer_at if ours else 8)
    expected = bytearray(pitch * h)     # what is decoded; the raster's last-row
                                        # padding past it is not written
    for y in range(h):
        ty, yi = divmod(y, th)
        for tx in range(across):
            x0, x1 = tx * tw, min(w, tx * tw + tw)
            for b in range(x0 * bits // 8, x1 * bits // 8):
                expected[y * pitch + b] = ((ty * across + tx) * 7 + yi + b) & 0xFF
    return bytes(data), bytes(expected), pitch


class PlayDecodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-play-')
        cls.lib = build(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def get(self, f): return self.lib.fpl_fixture_get(f)

    def setUp(self):
        self.lib.fpl_fixture_reset()

    def open_clip(self, data, size=None, busy=0):
        """Clip open, the old pool freed, the pool made: the camera's order."""
        return self.lib.fpl_fixture_open(data, len(data), size or len(data), busy)

    def load(self, data, cap):
        self.data = data
        self.lib.fpl_fixture_load(data, len(data), cap)

    def strip(self, at, n):
        return bytes(self.lib.fpl_fixture_byte(at + i) for i in range(n))

    def untouched(self):
        self.assertEqual(self.strip(0, len(self.data)), self.data, 'the frame was changed')
        self.assertEqual((self.get(OOB), self.get(BAD_WRITES)), (0, 0))
        self.assertEqual(self.get(OPENS), self.get(CLOSES))

    def decode(self, **kw):
        data, expected, pitch = frame(**kw)
        strip = kw.get('strip', 0x400)
        self.open_clip(data)
        cap = max(strip + max(len(expected), raster_len(**kw)), len(data))  # the stock size
        self.load(data, cap)
        return data, expected, cap, strip

    # ---- clip open --------------------------------------------------------
    def test_a_clip_of_ours_asks_for_the_stock_frame_and_the_pool_takes_the_scratch(self):
        data, expected, pitch = frame()
        stock = 0x400 + ((len(expected) + 0x1FF) & ~0x1FF)
        self.assertGreater(clip_size(), stock, 'this frame has no padded tile rows')
        self.assertEqual(self.lib.fpl_fixture_clip(data, len(data), len(data), 0), clip_size())
        self.assertEqual((self.get(CLIPS_OURS), self.get(ALLOCS)), (1, 0), 'taken at clip open')
        self.lib.fpl_fixture_end()                       # the player's old pool freed
        self.lib.fpl_fixture_pool()                      # and made
        self.assertEqual(self.get(ALLOCS), 1)
        self.assertEqual(len(expected), raster_len())
        self.assertGreaterEqual(self.get(SCRATCH_BYTES), 2 * pitch * 32)
        self.lib.fpl_fixture_pool()
        self.assertEqual(self.get(ALLOCS), 1, 'the scratch was taken twice')
        self.lib.fpl_fixture_end()
        self.assertEqual((self.get(RELEASES), self.get(SCRATCH_BYTES)), (1, 0))
        self.lib.fpl_fixture_end()
        self.assertEqual(self.get(RELEASES), 1, 'freed twice')

    def test_the_old_pool_freed_between_clip_open_and_the_new_pool_keeps_the_scratch(self):
        # 2026-10-02, 48p: the scratch taken at clip open went with the old pool
        data, expected, pitch = frame()
        self.lib.fpl_fixture_clip(data, len(data), len(data), 0)
        self.lib.fpl_fixture_end()
        self.lib.fpl_fixture_pool()
        self.load(data, 0x400 + raster_len())
        self.assertEqual(self.lib.fpl_fixture_run(0), DECODED)

    def test_a_clip_we_do_not_decode_after_ours_takes_no_scratch(self):
        self.open_clip(frame()[0])
        self.open_clip(frame(ours=False, bits=8)[0])
        self.assertEqual(self.get(SCRATCH_BYTES), 0)

    def test_a_clip_opening_on_a_stock_frame_keeps_its_size_and_gets_the_scratch(self):
        # the take's first frame is left uncompressed (for DaVinci): the
        # first frame cannot tell, so any clip we can decode gets the scratch
        data, expected, pitch = frame(ours=False)
        self.assertEqual(self.open_clip(data, 123456), 123456)
        self.assertEqual((self.get(CLIPS_OURS), self.get(ALLOCS)), (0, 1))

    def test_a_clip_opening_on_a_stock_frame_gets_room_for_whole_tiles(self):
        data, expected, pitch = frame(ours=False)
        self.assertEqual(self.open_clip(data, len(data)), clip_size())

    def test_a_compressed_frame_after_a_stock_first_frame_is_decoded(self):
        self.open_clip(frame(ours=False)[0])
        data, expected, pitch = frame()
        self.load(data, 0x400 + raster_len())
        self.assertEqual(self.lib.fpl_fixture_run(0), DECODED)
        self.assertEqual(self.strip(0x400, len(expected)), expected)

    def test_a_format_we_do_not_decode_takes_no_scratch(self):
        data, expected, pitch = frame(ours=False, bits=8)
        self.assertEqual(self.open_clip(data, 4321), 4321)
        self.assertEqual(self.get(ALLOCS), 0)

    def test_no_clip_change_while_a_take_is_live(self):
        data, expected, pitch = frame()
        self.assertEqual(self.open_clip(data, 777, busy=1), 777)
        self.assertEqual(self.get(ALLOCS), 0)

    def test_a_first_frame_that_cannot_be_read_changes_nothing(self):
        data, expected, pitch = frame()
        self.lib.fpl_fixture_knob(4, 1)
        self.assertEqual(self.open_clip(data, 999), 999)
        self.assertEqual((self.get(CLIP_FAILED), self.get(ALLOCS)), (1, 0))

    def test_a_clip_whose_ifd0_is_not_a_stock_strip_changes_nothing(self):
        data, expected, pitch = frame(bits=8)
        self.assertEqual(self.open_clip(data, 999), 999)
        self.assertEqual(self.get(ALLOCS), 0)

    def test_no_scratch_at_clip_open_still_gives_the_stock_size(self):
        data, expected, pitch = frame()
        self.lib.fpl_fixture_knob(2, 1)
        self.assertEqual(self.open_clip(data), clip_size())
        self.assertEqual(self.get(SCRATCH_FAILED), 1)

    # ---- frames of ours, decoded -------------------------------------------
    def check_decoded(self, data, expected, strip):
        self.assertEqual(self.lib.fpl_fixture_run(0), DECODED)
        self.assertEqual(self.strip(strip, len(expected)), expected)
        self.assertEqual(struct.unpack('<I', self.strip(4, 4))[0], 8, 'root not back on IFD0')
        self.assertEqual(self.strip(8, strip - 8), data[8:strip], 'IFD0 changed')
        self.assertEqual((self.get(OOB), self.get(BAD_WRITES)), (0, 0), 'wrote out of bounds')
        self.assertEqual(self.get(OPENS), self.get(CLOSES))
        self.assertEqual(self.get(MISALIGNED), 0)
        self.assertEqual(self.get(SYNCS), 1)

    def test_a_frame_of_ours_becomes_the_stock_frame(self):
        data, expected, cap, strip = self.decode()
        self.check_decoded(data, expected, strip)
        self.assertEqual(self.get(OPENS), 3, 'one decode per tile row')

    def test_a_frame_that_compresses_badly_is_still_decoded_bottom_up(self):
        # every tile row's stream almost as long as its raw rows: a row
        # written top down would land on the next row's stream
        data, expected, cap, strip = self.decode(h=64, tile_len=1480)
        self.check_decoded(data, expected, strip)

    def test_whole_tile_rows(self):
        data, expected, cap, strip = self.decode(h=64)
        self.check_decoded(data, expected, strip)

    def test_a_frame_shorter_than_one_tile_row(self):
        data, expected, cap, strip = self.decode(h=20)
        self.check_decoded(data, expected, strip)

    def test_a_partial_last_column(self):
        data, expected, cap, strip = self.decode(w=88)
        self.check_decoded(data, expected, strip)

    def test_a_width_whose_last_raster_row_is_padded_to_12_pixels(self):
        # FHD is 1936 wide: the recorder's last row is 1944 px, 12 B more
        data, expected, pitch = frame(w=88)
        raster = raster_len(w=88)
        self.assertGreater(raster, pitch * 74)
        self.assertEqual(self.open_clip(data), clip_size(w=88))
        self.assertEqual(self.get(CLIPS_OURS), 1, 'not taken for ours')
        # a height that is whole tiles: exactly the stock file, the 12 B included
        data, expected, pitch = frame(w=88, h=64)
        self.assertEqual(default_grid(88, 64)[1], 64)
        self.assertEqual(self.open_clip(data), 0x400 + ((raster_len(w=88, h=64) + 0x1FF) & ~0x1FF))

    def test_nothing_is_written_past_an_exact_capacity(self):
        data, expected, cap, strip = self.decode()
        self.lib.fpl_fixture_run(0)
        self.assertEqual(self.lib.fpl_fixture_byte(cap), 0xA5)
        self.assertEqual(self.get(BAD_WRITES), 0)

    # ---- not ours, or not safe: left exactly as read ----------------------
    def refused(self, why, busy=0, cap_delta=0, **kw):
        data, expected, pitch = frame(**kw)
        strip = kw.get('strip', 0x400)
        self.open_clip(frame()[0])
        cap = strip + max(len(expected), raster_len(**kw)) + cap_delta
        self.load(data, cap if why == R_ROOM else max(cap, len(data)))
        self.assertEqual(self.lib.fpl_fixture_run(busy), why)
        self.untouched()
        if why < 12:
            self.assertEqual(self.get(100 + why), 1)

    def test_a_stock_frame_is_left_alone(self):
        self.refused(STOCK, ours=False)
        self.assertEqual(self.get(N_STOCK), 1)

    def test_while_a_take_is_live(self):
        self.refused(R_BUSY, busy=1)

    def test_a_trailer_that_is_not_compression_7(self):
        self.refused(R_FORMAT, comp=1)

    def test_a_tile_table_with_a_gap(self):
        self.refused(R_TILES, gap_at=4)

    def test_a_tile_table_of_the_wrong_length(self):
        self.refused(R_TILES, tiles_n=8)

    def test_a_file_read_short_of_its_tile_table(self):
        self.refused(R_TILES, cut=40)

    def test_a_file_read_short_of_its_trailer(self):
        self.refused(R_ROOT, cut=150)

    def test_an_ifd0_that_is_not_this_frame(self):
        self.refused(R_IFD0, ifd0_w=88)

    def test_a_buffer_one_byte_too_small(self):
        self.refused(R_ROOM, cap_delta=-1)

    def test_an_unsupported_depth(self):
        self.refused(R_FORMAT, bits=8)

    def test_a_tile_row_worse_than_raw(self):
        self.refused(R_ORDER, h=64, tile_len=2000)

    def test_no_scratch(self):
        data, expected, pitch = frame()
        self.open_clip(data)
        self.lib.fpl_fixture_end()
        self.load(data, 0x400 + len(expected))
        self.assertEqual(self.lib.fpl_fixture_run(0), R_SCRATCH)
        self.untouched()

    def test_not_a_tiff(self):
        data, expected, pitch = frame()
        self.open_clip(data)
        self.load(b'MM' + data[2:], 0x400 + len(expected))
        self.assertEqual(self.lib.fpl_fixture_run(0), R_TIFF)

    def test_no_buffer(self):
        data, expected, pitch = frame()
        self.load(data, 0x400 + len(expected))
        self.lib.fpl_fixture_knob(3, 0)
        self.assertEqual(self.lib.fpl_fixture_run(0), R_SLOT)

    # ---- failures on the way ----------------------------------------------
    def test_a_failed_first_copy_changes_nothing(self):
        data, expected, cap, strip = self.decode()
        self.lib.fpl_fixture_knob(0, 1)
        self.assertEqual(self.lib.fpl_fixture_run(0), R_COPY)
        self.untouched()

    def test_an_engine_failure_closes_and_keeps_the_root(self):
        data, expected, cap, strip = self.decode()
        self.lib.fpl_fixture_knob(1, 1)
        self.assertEqual(self.lib.fpl_fixture_run(0), R_ENGINE)
        self.assertEqual(self.get(OPENS), self.get(CLOSES))
        self.assertEqual(self.strip(4, 4), data[4:8], 'root moved for a frame not decoded')
        self.assertEqual(self.get(BAD_WRITES), 0)


class OneJobTests(unittest.TestCase):
    """The whole frame in one engine job, no bulk copy (2026-11-18): the
    player's buffers moved up to 1 KiB when its pool is made, the stream read
    where the player put it, the pixels decoded into a spare buffer that then
    takes the frame's place in the slot."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-play-one-')
        cls.lib = build(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def get(self, f): return self.lib.fpl_fixture_get(f)

    def setUp(self):
        self.lib.fpl_fixture_reset()

    def pool(self, slots=3, step=0x780, **kw):
        self.kw = kw
        first = frame(ours=False, **{k: v for k, v in kw.items() if k in ('w', 'h', 'bits', 'strip')})[0]
        self.want = self.lib.fpl_fixture_open_pool(first, len(first), len(first), slots, step)
        return self.want

    def play(self, k, **over):
        data, expected, pitch = frame(**{**self.kw, **over})
        self.data, self.expected = data, expected
        return self.lib.fpl_fixture_play(k, data, len(data))

    def slot_bytes(self, k, at, n):
        return bytes(self.lib.fpl_fixture_slot_byte(k, at + i) for i in range(n))

    def check(self, k, strip=0x400):
        self.assertEqual(self.slot_bytes(k, strip, len(self.expected)), self.expected)
        self.assertEqual(struct.unpack('<I', self.slot_bytes(k, 4, 4))[0], 8, 'root not on IFD0')
        self.assertEqual(self.slot_bytes(k, 8, strip - 8), self.data[8:strip], 'header changed')
        self.assertEqual((self.get(OOB), self.get(BAD_WRITES), self.get(MISALIGNED)), (0, 0, 0))
        self.assertEqual(self.get(OPENS), self.get(CLOSES))

    def test_the_pool_made_aligns_every_buffer_and_keeps_its_room(self):
        self.pool(slots=3)
        self.assertEqual(self.get(SLOTS_ALIGNED), 3)
        cap = (self.want + 0x1FFF) & ~0xFFF
        for k in range(3):
            self.assertEqual(self.lib.fpl_fixture_slot(k, 0x14) & 0x3FF, 0)
            self.assertEqual(self.lib.fpl_fixture_slot(k, 0x18), cap - (0x400 - 0x380))
            self.assertGreaterEqual(self.lib.fpl_fixture_slot(k, 0x18), self.want)
        self.assertEqual(self.get(SPARE) & 0x3FF, 0)
        self.assertEqual(self.lib.fpl_fixture_live(), 5, 'three of the player, the spare, the one read ahead into')
        self.assertEqual(self.get(AHEAD) & 0x3FF, 0)

    def test_a_frame_is_decoded_in_one_job_and_the_buffers_change_places(self):
        self.pool()
        was, spare = self.lib.fpl_fixture_slot(1, 0x14), self.get(SPARE)
        self.assertEqual(self.play(1), DECODED)
        self.check(1)
        self.assertEqual((self.get(FAST), self.get(ROWS)), (1, 0))
        self.assertEqual((self.get(OPENS), self.get(SUBMITS), self.get(DMAS)), (1, 1, 0),
                         'one job, no bulk copy')
        self.assertEqual(self.get(SYNCS), 1)
        self.assertEqual(self.lib.fpl_fixture_slot(1, 0x14), spare, 'the slot did not take the spare')
        self.assertEqual(self.get(SPARE), was, 'the old buffer is not the spare')
        # the engine was told the tile-padded height and every tile
        tw, th = 32, 32
        self.assertEqual(self.get(ROWS_TOLD), -(-74 // th) * th)
        self.assertEqual(self.get(TILE_VAR), -(-96 // tw) * -(-74 // th))

    def test_frame_after_frame_in_every_slot(self):
        self.pool(slots=3)
        for n in range(7):
            k = n % 3
            self.assertEqual(self.play(k, tile_len=24 + 4 * n), DECODED, n)
            self.check(k)
        self.assertEqual((self.get(FAST), self.get(ROWS)), (7, 0))

    def test_an_allocator_that_gives_aligned_blocks(self):
        self.pool(step=0)
        self.assertEqual(self.play(0), DECODED)
        self.check(0)
        self.assertEqual(self.get(FAST), 1)
        self.assertEqual(self.lib.fpl_fixture_free_pool(), 0)
        self.assertEqual(self.lib.fpl_fixture_live(), 0)

    def test_the_pool_freed_gets_every_address_the_allocator_gave(self):
        self.pool(slots=3)
        for k in (0, 2, 0, 1):
            self.assertEqual(self.play(k), DECODED)
        self.assertEqual(self.lib.fpl_fixture_free_pool(), 0, 'a moved address was freed')
        self.assertEqual(self.lib.fpl_fixture_live(), 0, 'a buffer was not given back')
        self.assertEqual((self.get(RESTORED), self.get(NOT_OURS), self.get(SPARE_LOST)), (3, 0, 0))
        self.assertEqual(self.get(PUTS), 5)
        self.assertEqual(self.get(SPARE), 0)

    def test_the_end_puts_addresses_and_capacities_back_in_place(self):
        # a REC start while the pool lives: each slot keeps ITS buffer
        self.pool(slots=2)
        self.assertEqual(self.play(0), DECODED)
        now = [self.lib.fpl_fixture_slot(k, 0x14) for k in range(2)]
        self.lib.fpl_fixture_end()
        cap = (self.want + 0x1FFF) & ~0xFFF
        for k in range(2):
            self.assertEqual(self.lib.fpl_fixture_slot(k, 0x14), now[k] - 0x80)
            self.assertEqual(self.lib.fpl_fixture_slot(k, 0x18), cap)
        self.assertEqual(self.slot_bytes(0, 0x80 + 0x400, len(self.expected)), self.expected)
        # and a frame after that goes the row way, into the buffer as it is
        self.lib.fpl_fixture_end()
        self.assertEqual(self.get(PUTS), 2, 'the spares freed twice')

    def test_a_pool_already_made_is_not_moved_again(self):
        # after a REC start gave everything back, the player's pool still made
        self.pool(slots=2)
        self.lib.fpl_fixture_end()
        now = [self.lib.fpl_fixture_slot(k, 0x14) for k in range(2)]
        live = self.lib.fpl_fixture_live()
        self.lib.fpl_fixture_remake(self.want)
        self.assertEqual([self.lib.fpl_fixture_slot(k, 0x14) for k in range(2)], now)
        self.assertEqual((self.lib.fpl_fixture_live(), self.get(SPARE)), (live, 0))
        self.assertEqual(self.play(0), DECODED)          # the row way
        self.assertEqual((self.get(FAST), self.get(ROWS)), (0, 1))
        self.assertEqual(self.lib.fpl_fixture_free_pool(), 0)

    def test_a_stock_frame_is_left_and_nothing_changes_places(self):
        self.pool()
        was = self.lib.fpl_fixture_slot(0, 0x14)
        self.assertEqual(self.play(0, ours=False), STOCK)
        self.assertEqual(self.lib.fpl_fixture_slot(0, 0x14), was)
        self.assertEqual(self.slot_bytes(0, 0, len(self.data)), self.data)

    def test_no_spare_goes_the_row_way(self):
        self.lib.fpl_fixture_knob(5, 1)
        first = frame(ours=False)[0]
        self.lib.fpl_fixture_open_pool(first, len(first), len(first), 0, 0x780)
        self.assertEqual((self.get(SPARE), self.get(SPARE_FAILED), self.get(SLOTS_ALIGNED)), (0, 1, 0))

    def test_a_strip_that_is_not_1_kib_aligned_goes_the_row_way(self):
        self.pool(strip=0x600)
        self.assertEqual(self.play(0), DECODED)
        self.check(0, strip=0x600)
        self.assertEqual((self.get(FAST), self.get(ROWS), self.get(NO_ALIGN)), (0, 1, 1))

    def test_a_grid_whose_padded_height_does_not_fit_goes_the_row_way(self):
        self.pool(w=96, h=66)                    # default grid: no padding to speak of
        was = self.lib.fpl_fixture_slot(0, 0x14)
        cap = self.lib.fpl_fixture_slot(0, 0x18)
        th = 48
        pitch = 144
        while 0x400 + pitch * (-(-66 // th) * th) <= cap:
            th += 16
        self.assertEqual(self.play(0, th=th), DECODED)
        self.check(0)
        self.assertEqual((self.get(FAST), self.get(ROWS), self.get(NO_ROOM)), (0, 1, 1))
        self.assertEqual(self.lib.fpl_fixture_slot(0, 0x14), was)

    def test_an_engine_failure_leaves_the_frame_and_the_buffers(self):
        self.pool()
        was, spare = self.lib.fpl_fixture_slot(0, 0x14), self.get(SPARE)
        self.lib.fpl_fixture_knob(1, 1)
        self.assertEqual(self.play(0), R_ENGINE)
        self.lib.fpl_fixture_knob(1, 0)
        self.assertEqual((self.lib.fpl_fixture_slot(0, 0x14), self.get(SPARE)), (was, spare))
        self.assertEqual(self.slot_bytes(0, 0, len(self.data)), self.data, 'the frame was changed')
        self.assertEqual(self.get(OPENS), self.get(CLOSES))
        self.assertEqual(self.play(0), DECODED)
        self.check(0)

    def test_a_pool_the_player_could_not_make_keeps_nothing_moved(self):
        first = frame(ours=False)[0]
        self.lib.fpl_fixture_open_pool(first, len(first), len(first), 0, 0x780)
        self.assertEqual(self.get(SLOTS_ALIGNED), 0)
        self.assertEqual(self.lib.fpl_fixture_free_pool(), 0)
        self.assertEqual(self.lib.fpl_fixture_live(), 0, 'the spare was kept')

    def test_14_bit_and_a_wide_frame(self):
        self.pool(w=480, h=130, bits=14, tw=64, th=48)
        self.assertEqual(self.play(2), DECODED)
        self.check(2)
        self.assertEqual(self.get(FAST), 1)


def path(n):
    return (r'\CINEMA\A001_398\A001_398_20261118_%06d.DNG' % n).encode()


class ReadAheadTests(unittest.TestCase):
    """While the engine decodes frame N the next frame file is read into a
    second spare; the player's read of exactly that file is then skipped."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-play-ahead-')
        cls.lib = build(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def get(self, f): return self.lib.fpl_fixture_get(f)

    def setUp(self):
        self.lib.fpl_fixture_reset()
        self.files = {}

    def clip(self, numbers, slots=3, stock=()):
        first = frame(ours=False)[0]
        self.lib.fpl_fixture_open_pool(first, len(first), len(first), slots, 0x780)
        for n in numbers:
            data, expected, pitch = frame(ours=n not in stock, tile_len=24 + 4 * (n % 5))
            self.files[n] = (data, expected)
            self.lib.fpl_fixture_disk(path(n), data, len(data))

    def play(self, k, n):
        return self.lib.fpl_fixture_play_path(k, path(n))

    def check(self, k, n):
        data, expected = self.files[n]
        got = bytes(self.lib.fpl_fixture_slot_byte(k, 0x400 + i) for i in range(len(expected)))
        self.assertEqual(got, expected, f'frame {n} in slot {k}')
        self.assertEqual((self.get(OOB), self.get(BAD_WRITES), self.get(MISALIGNED)), (0, 0, 0))

    def test_the_next_file_is_read_while_the_engine_runs_and_the_read_is_skipped(self):
        self.clip([5, 6, 7])
        self.assertEqual(self.play(0, 5), DECODED)
        self.check(0, 5)
        self.assertEqual((self.get(AHEAD_READ), self.get(FILE_READS), self.get(READS_WHILE_ENGINE)),
                         (1, 1, 1), 'frame 6 was not read during frame 5\'s decode')
        self.assertEqual(self.get(AHEAD_GOT), len(self.files[6][0]))
        self.assertEqual(self.play(1, 6), DECODED)
        self.check(1, 6)
        self.assertEqual(self.get(AHEAD_USED), 1, 'the player read frame 6 again')
        self.assertEqual(self.lib.fpl_fixture_slot(1, 0x1c), len(self.files[6][0]))
        self.assertEqual(self.play(2, 7), DECODED)
        self.check(2, 7)
        self.assertEqual((self.get(AHEAD_USED), self.get(AHEAD_READ)), (2, 2))
        self.assertEqual(self.get(AHEAD_GOT), 0, 'a file after the last one')
        for k, n in ((0, 5), (1, 6)):
            self.check(k, n)                          # earlier frames still whole

    def test_a_long_run_through_few_slots(self):
        self.clip(list(range(98, 102)), slots=2)      # 000099 -> 000100: a carry
        for i, n in enumerate(range(98, 102)):
            self.assertEqual(self.play(i % 2, n), DECODED, n)
            self.check(i % 2, n)
        self.assertEqual((self.get(AHEAD_USED), self.get(AHEAD_MISSED)), (3, 0))
        self.assertEqual(self.lib.fpl_fixture_free_pool(), 0)
        self.assertEqual(self.lib.fpl_fixture_live(), 0)

    def test_another_frame_than_the_one_read_ahead_is_read_by_the_player(self):
        self.clip([5, 6, 9])
        self.assertEqual(self.play(0, 5), DECODED)     # 6 read ahead
        self.assertEqual(self.play(1, 9), DECODED)     # the player jumps to 9
        self.check(1, 9)
        self.assertEqual((self.get(AHEAD_USED), self.get(AHEAD_MISSED)), (0, 1))
        self.assertEqual(self.play(2, 6), DECODED)     # and back: read as stock, right
        self.check(2, 6)

    def test_the_same_frame_again_is_not_served_from_a_stale_read(self):
        self.clip([5, 6])
        self.assertEqual(self.play(0, 5), DECODED)
        self.assertEqual(self.play(1, 5), DECODED)     # 5 again, not 6
        self.check(1, 5)
        self.assertEqual(self.get(AHEAD_USED), 0)

    def test_a_stock_frame_read_ahead_is_handed_over_whole(self):
        self.clip([5, 6, 7], stock=(6,))
        self.assertEqual(self.play(0, 5), DECODED)
        self.assertEqual(self.play(1, 6), STOCK)
        data = self.files[6][0]
        self.assertEqual(bytes(self.lib.fpl_fixture_slot_byte(1, i) for i in range(len(data))), data)
        self.assertEqual(self.get(AHEAD_USED), 1)
        self.assertEqual(self.play(2, 6), STOCK)       # the same file again: read, not served twice
        self.assertEqual(bytes(self.lib.fpl_fixture_slot_byte(2, i) for i in range(len(data))), data)
        self.assertEqual(self.get(AHEAD_USED), 1)
        self.assertEqual(self.play(2, 7), DECODED)     # nothing was read ahead of a stock frame
        self.check(2, 7)
        self.assertEqual(self.get(AHEAD_USED), 1)

    def test_a_new_clip_forgets_what_was_read_ahead(self):
        self.clip([5, 6])
        self.assertEqual(self.play(0, 5), DECODED)
        self.assertGreater(self.get(AHEAD_GOT), 0)
        first = frame(ours=False)[0]
        self.lib.fpl_fixture_clip(first, len(first), len(first), 0)
        self.assertEqual(self.get(AHEAD_GOT), 0)

    def test_no_second_spare_still_decodes_in_one_job(self):
        self.lib.fpl_fixture_knob(6, 2)                # the allocator's second block refused
        self.clip([5, 6])
        self.assertEqual((self.get(AHEAD), self.get(AHEAD_FAILED)), (0, 1))
        self.assertEqual(self.play(0, 5), DECODED)
        self.check(0, 5)
        self.assertEqual((self.get(FAST), self.get(AHEAD_READ), self.get(FILE_READS)), (1, 0, 0))
        self.assertEqual(self.play(1, 6), DECODED)
        self.check(1, 6)
        self.assertEqual(self.lib.fpl_fixture_free_pool(), 0)
        self.assertEqual(self.lib.fpl_fixture_live(), 0)

    def test_a_file_as_long_as_the_buffer_is_not_served(self):
        self.clip([5])
        cap = self.lib.fpl_fixture_slot(0, 0x18)
        self.lib.fpl_fixture_disk(path(6), b'\x11' * cap, cap)
        self.assertEqual(self.play(0, 5), DECODED)
        self.assertEqual((self.get(AHEAD_GOT), self.get(AHEAD_NONE)), (0, 1))


AHEAD_MUTATIONS = {
    'reads the same file again': ("        if (c != '9') { p->ahead_path[k] = (char)(c + 1); break; }",
                                  "        if (c != '9') { break; }"),
    'no carry': ("        p->ahead_path[k] = '0';\n", ''),
    'serves any path': ('rd8(reader + READER_PATH + n, 0) == (uint8_t)p->ahead_path[n]; ++n) {}',
                        '1; ++n) {}\n    n = 0; while (p->ahead_path[n]) ++n;\n    if (rd8(reader + READER_PATH + n, 0)) n = 0;'),
    'serves it twice': ('    p->ahead_got = 0;\n    saturate(&p->ahead_used);', '    saturate(&p->ahead_used);'),
    'the slot keeps its buffer': ('    poke(slot + SLOT_BUFFER, (uint32_t)p->ahead);\n', ''),
    'the bytes read not told': ('    poke(slot + SLOT_READ, p->ahead_got);\n', ''),
    'the old buffer lost': ('    p->ahead = buf;\n', ''),
    'read after the engine': ('''    read_ahead(p, reader);                           /* the next file, while the engine runs */
    t3 = now_us();
    if (band_finish((uint32_t)flag, BAND_TICKS) != 0) {''', '''    t3 = now_us();
    if (band_finish((uint32_t)flag, BAND_TICKS) != 0 || (read_ahead(p, reader), 0)) {'''),
    'kept across clips': ('    p->hook_end_us = 0;\n    p->ahead_got = 0;\n    p->sums_stale = 1;',
                          '    p->hook_end_us = 0;\n    p->sums_stale = 1;'),
    'a full buffer served': ('|| !got || got >= p->ahead_cap) {', '|| !got) {'),
}


GATE_HELD, GATE_LET, RATE_NUM, RATE_DEN, PACE_N = 40, 41, 42, 43, 44
BUFFERING = 1


class StartGateTests(unittest.TestCase):
    """A clip of ours whose frames arrive slower than its frame rate starts
    when the player's pool is full, not at the player's own five frames."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-play-gate-')
        cls.lib = build(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def get(self, f): return self.lib.fpl_fixture_get(f)

    def setUp(self):
        self.lib.fpl_fixture_reset()
        self.now = 5000

    def clip(self, rate=(24, 1), slots=6):
        self.rate = rate
        first = frame(ours=False, rate=rate)[0]
        self.lib.fpl_fixture_open_pool(first, len(first), len(first), slots, 0x780)

    def arrive(self, frames, period_us, ours=True):
        """`frames` frame files reach our hook, one every period_us."""
        for n in range(frames):
            data = frame(ours=ours and n > 0, rate=self.rate)[0]
            self.lib.fpl_fixture_knob(7, self.now)
            self.assertIn(self.lib.fpl_fixture_play(n % 2, data, len(data)), (STOCK, DECODED))
            self.now += period_us

    def gate(self, free, state=BUFFERING, stock=1, busy=0):
        return self.lib.fpl_fixture_gate(state, free, stock, busy)

    def test_a_slow_clip_waits_until_one_slot_is_left_free(self):
        self.clip()
        self.arrive(6, 48000)                        # 24 fps is 41667 us
        self.assertEqual([self.gate(free) for free in (5, 3, 2, 1, 0)], [0, 0, 0, 1, 1])
        self.assertEqual((self.get(GATE_HELD), self.get(GATE_LET)), (3, 2))

    def test_a_clip_arriving_at_its_frame_rate_starts_as_the_player_says(self):
        self.clip()
        self.arrive(6, 41000)
        self.assertEqual(self.gate(4), 1)
        self.assertEqual(self.get(GATE_HELD), 0)

    def test_half_a_percent_over_is_not_slow_and_two_percent_is(self):
        self.clip()
        self.arrive(8, 41900)
        self.assertEqual(self.gate(4), 1)
        self.setUp()
        self.clip()
        self.arrive(8, 42500)
        self.assertEqual(self.gate(4), 0)

    def test_a_start_once_held_waits_for_the_pool_whatever_the_pace_becomes(self):
        self.clip()
        self.arrive(6, 48000)
        self.assertEqual(self.gate(4), 0)
        self.arrive(12, 30000)                       # the average falls under the frame period
        self.assertEqual([self.gate(free) for free in (3, 2, 1)], [0, 0, 1])
        self.assertEqual(self.gate(4), 1, 'the next start is judged again')

    def test_a_held_start_that_played_on_is_forgotten(self):
        self.clip()
        self.arrive(6, 48000)
        self.assertEqual(self.gate(4), 0)
        self.assertEqual(self.gate(4, state=3), 1)   # playing: the player started another way
        self.arrive(12, 30000)
        self.assertEqual(self.gate(4), 1)

    def test_a_no_from_the_player_stays_a_no(self):
        self.clip()
        self.arrive(6, 48000)
        self.assertEqual(self.gate(0, stock=0), 0)
        self.assertEqual(self.gate(1, stock=0), 0)

    def test_only_a_buffering_player_is_held(self):
        self.clip()
        self.arrive(6, 48000)
        self.assertEqual([self.gate(4, state=s) for s in (0, 2, 3, 4)], [1, 1, 1, 1])

    def test_three_intervals_say_nothing(self):
        self.clip()
        self.arrive(4, 48000)
        self.assertEqual(self.gate(4), 1)
        self.arrive(1, 48000)
        self.assertEqual(self.gate(4), 0)

    def test_a_clip_without_a_frame_rate_is_left_alone(self):
        self.clip(rate=None)
        self.arrive(6, 48000)
        self.assertEqual(self.gate(4), 1)
        self.assertEqual(self.get(RATE_NUM), 0)

    def test_a_fractional_frame_rate(self):
        self.clip(rate=(24000, 1001))                # 41708 us a frame
        self.arrive(6, 46000)
        self.assertEqual((self.get(RATE_NUM), self.get(RATE_DEN)), (24000, 1001))
        self.assertEqual(self.gate(4), 0)

    def test_a_frame_rate_with_a_long_denominator(self):
        self.clip(rate=(14400000, 600661))           # Sensor Lab's 23.974: 41712 us a frame
        self.arrive(6, 43890)                        # as measured, OG 4K from an SD card
        self.assertEqual(self.gate(4), 0)
        self.setUp()
        self.clip(rate=(14400000, 600661))
        self.arrive(6, 41900)
        self.assertEqual(self.gate(4), 1)

    def test_a_frame_rate_that_is_no_rate_is_not_used(self):
        for rate in ((0, 1), (1, 0), (241, 1)):
            with self.subTest(rate=rate):
                self.setUp()
                self.clip(rate=rate)
                self.arrive(6, 5_000 if rate == (241, 1) else 480_000)
                self.assertEqual(self.gate(4), 1)

    def test_a_reader_that_has_ended_is_not_waited_for(self):
        self.clip()
        self.arrive(6, 48000)
        self.assertEqual(self.gate(4), 0)
        self.lib.fpl_fixture_slot_last(3, 1)
        self.assertEqual(self.gate(4), 1)

    def test_sixty_four_frames_waiting_are_enough(self):
        self.clip()
        self.arrive(6, 48000)
        self.lib.fpl_fixture_big_pool(70)
        self.assertEqual([self.gate(free) for free in (7, 6)], [0, 1])

    def test_a_pause_is_not_the_pace(self):
        self.clip()
        self.arrive(3, 41000)
        self.now += 2_000_000                        # paused on a frame
        self.arrive(4, 41000)
        self.assertEqual(self.gate(4), 1)

    def test_while_a_take_is_live_the_player_is_left_alone(self):
        self.clip()
        self.arrive(6, 48000)
        self.assertEqual(self.gate(4, busy=1), 1)

    def test_a_new_clip_starts_its_pace_again(self):
        self.clip()
        self.arrive(6, 48000)
        self.assertEqual(self.gate(4), 0)
        self.lib.fpl_fixture_free_pool()
        self.clip()
        self.assertEqual(self.get(PACE_N), 0)
        self.arrive(2, 48000)
        self.assertEqual(self.gate(4), 1)

    def test_stock_frames_count_for_the_pace_too(self):
        self.clip()
        self.arrive(6, 48000, ours=False)
        self.assertEqual(self.gate(4), 0)


GATE_MUTATIONS = {
    'held in every state': ('    if (p->gate_state != PLAYER_BUFFERING) { saturate(&p->gate_other); p->gate_waiting = 0; return stock; }\n', ''),
    'held when not slow': ('    if (!p->gate_slow && !p->gate_waiting) { saturate(&p->gate_fast); return stock; }\n', ''),
    'a full pool still held': ('    if (free_n > 1u && total - free_n < GATE_FRAMES) {',
                               '    if (free_n > 0u && total - free_n < GATE_FRAMES) {'),
    'never held': ('        if (!ended) { saturate(&p->gate_held); p->gate_waiting = 1; return 0; }',
                   '        if (!ended) { saturate(&p->gate_held); p->gate_waiting = 1; }'),
    'a held start not remembered': ('        if (!ended) { saturate(&p->gate_held); p->gate_waiting = 1; return 0; }',
                                    '        if (!ended) { saturate(&p->gate_held); return 0; }'),
    'the reader\'s end not looked at': ('            ended = rd8(p->slots_base + n * POOL_STRIDE + SLOT_LAST, 0);',
                                        '            ended = 0;'),
    'no cap on the frames waiting': ('    if (free_n > 1u && total - free_n < GATE_FRAMES) {', '    if (free_n > 1u) {'),
    'no margin': ('#define PACE_MARGIN     1010000u', '#define PACE_MARGIN     1000000u'),
    'a wide margin': ('#define PACE_MARGIN     1010000u', '#define PACE_MARGIN     1030000u'),
    'a held start judged again': ('    if (!p->gate_slow && !p->gate_waiting) {', '    if (!p->gate_slow) {'),
    'held for ever once held': ('    p->gate_waiting = 0;\n    saturate(&p->gate_let);', '    saturate(&p->gate_let);'),
    'held over a start that played': ('saturate(&p->gate_other); p->gate_waiting = 0; return stock; }', 'saturate(&p->gate_other); return stock; }'),
    'pauses counted': ('        if (d < PACE_BREAK_US) {', '        if (d < 0xffffffffu) {'),
    'the pace kept across clips': ('    p->pace_last_us = p->pace_sum_us = p->pace_n = 0;\n', ''),
    'one interval is enough': ('#define PACE_MIN        4u', '#define PACE_MIN        1u'),
    'a take ignored': ('    if (busy || !pool || !player || p->pool != pool || !p->slots) return stock;',
                       '    if (busy > 1u || !pool || !player || p->pool != pool || !p->slots) return stock;'),
    'the rate upside down': ('                p->rate_num = n; p->rate_den = d;', '                p->rate_num = d; p->rate_den = n;'),
    'a long denominator refused': ('d <= 0x1000000u && n <= 240u * d', 'd <= 0x10000u && n <= 240u * d'),
    'a long denominator cut off': ('                while (d > 0xffffu) { n >>= 1; d >>= 1; }', '                d &= 0xffffu;'),
    'stock frames not timed': ('    pace(p, buf, got);\n    if (root == ROOT_STOCK) { saturate(&p->stock); return FPL_PLAY_STOCK; }',
                               '    if (root == ROOT_STOCK) { saturate(&p->stock); return FPL_PLAY_STOCK; }\n    pace(p, buf, got);'),
    'a rate read as an integer': ('        case 51044: if (type == 10 && count == 1) f->rate = v; break;',
                                  '        case 51044: f->rate = 0; break;'),
}


class StartGateMutationTests(unittest.TestCase):
    def test_every_mutation_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='fpl-play-gate-mut-') as tmp:
            for index, (name, seam) in enumerate(GATE_MUTATIONS.items()):
                with self.subTest(mutation=name):
                    lib = build(tmp, seam, f'g{index}.dylib')

                    class Against(StartGateTests):
                        @classmethod
                        def setUpClass(cls):
                            cls.lib = lib

                        @classmethod
                        def tearDownClass(cls):
                            pass
                    result = unittest.TestResult()
                    unittest.defaultTestLoader.loadTestsFromTestCase(Against).run(result)
                    self.assertFalse(result.wasSuccessful(), f'{name} was not caught')


class ReadAheadMutationTests(unittest.TestCase):
    def test_every_mutation_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='fpl-play-ahead-mut-') as tmp:
            for index, (name, seam) in enumerate(AHEAD_MUTATIONS.items()):
                with self.subTest(mutation=name):
                    lib = build(tmp, seam, f'a{index}.dylib')

                    class Against(ReadAheadTests):
                        @classmethod
                        def setUpClass(cls):
                            cls.lib = lib

                        @classmethod
                        def tearDownClass(cls):
                            pass
                    result = unittest.TestResult()
                    unittest.defaultTestLoader.loadTestsFromTestCase(Against).run(result)
                    self.assertFalse(result.wasSuccessful(), f'{name} was not caught')


ONE_JOB_MUTATIONS = {
    'the real height, not the padded one': ('tiles, down * f.th,\n', 'tiles, f.h,\n'),
    'one tile row of tiles': ('fast_frame(p, slot, buf, cap, &f, f0.soff, row_at[0], tiles,',
                              'fast_frame(p, slot, buf, cap, &f, f0.soff, row_at[0], across,'),
    'no room check': ('p->spare_cap - soff < pitch_of(f->w, f->bits) * padded_rows',
                      'p->spare_cap - soff < 1u'),
    'no alignment check': ('(soff & (ALIGN - 1u)) || (stream_at & (ALIGN - 1u))', '0'),
    'decodes over the stream': ('p->spare + soff, buf + stream_at);',
                                'buf + soff, buf + stream_at);'),
    'a short header': ('    head_copy(p->spare, buf, soff);', '    head_copy(p->spare, buf, soff - 0x100u);'),
    'root left on the trailer': ('    poke(p->spare + 4, ROOT_STOCK);', ''),
    'the slot keeps its buffer': ('    poke(slot + SLOT_BUFFER, (uint32_t)p->spare);\n', ''),
    'the spare stays the spare': ('    p->spare = buf;\n', ''),
    'no cache sync': ('    cache_sync();\n    p->last_engine_us', '    p->last_engine_us'),
    'capacity not cut at alignment': ('        poke(slot + SLOT_CAPACITY, cap - (uint32_t)(a - raw));\n', ''),
    'capacity not put back': (
        '            poke(slot + SLOT_CAPACITY, peek(slot + SLOT_CAPACITY) + (uint32_t)(a - raw));\n', ''),
    'addresses not put back': ('            poke(slot + SLOT_BUFFER, (uint32_t)raw);\n', ''),
    'the spare freed by its moved address': ('        if (raw) buffer_put(raw); else', '        if (raw) buffer_put(*held); else'),
    'the spare never freed': ('        if (raw) buffer_put(raw); else saturate(&p->spare_lost);',
                              '        if (!raw) saturate(&p->spare_lost);'),
    'the spare kept after the end': ('        *held = 0;\n', ''),
    'only the spare given back': ('    for (uint32_t k = 0; k < 2; ++k) {               /* the spare,',
                                  '    for (uint32_t k = 0; k < 1; ++k) {               /* the spare,'),
    'aligned blocks left where they are': ('raw + ALIGN - (raw & (ALIGN - 1u));    /* 4..0x400 B up */',
                                           '(raw + ALIGN - 1u) & ~(uintptr_t)(ALIGN - 1u);'),
    'a spare for a pool already made': ('rd8(pool + POOL_MADE, 0) || peek(pool + POOL_COUNT) ||', ''),
    'engine failure counted as decoded': (
        '''    if (band_finish((uint32_t)flag, BAND_TICKS) != 0) {
        p->hook_end_us = 0;
        return refuse(p, FPL_PLAY_R_ENGINE);         /* the frame as it was read */''',
        '''    if (band_finish((uint32_t)flag, BAND_TICKS) != 0) {
        p->hook_end_us = 0;'''),
    'no size for whole tiles': ('        if (padded > stock) stock = padded;', '        if (padded > stock + 0x100000u) stock = padded;'),
}


class OneJobMutationTests(unittest.TestCase):
    def test_every_mutation_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='fpl-play-one-mut-') as tmp:
            for index, (name, seam) in enumerate(ONE_JOB_MUTATIONS.items()):
                with self.subTest(mutation=name):
                    lib = build(tmp, seam, f'o{index}.dylib')
                    failed = False
                    for case in (OneJobTests, PlayDecodeTests):
                        class Against(case):
                            @classmethod
                            def setUpClass(cls):
                                cls.lib = lib

                            @classmethod
                            def tearDownClass(cls):
                                pass
                        result = unittest.TestResult()
                        unittest.defaultTestLoader.loadTestsFromTestCase(Against).run(result)
                        failed = failed or not result.wasSuccessful()
                    self.assertTrue(failed, f'{name} was not caught')


class PlayDecodeMutationTests(unittest.TestCase):
    MUTATIONS = {
        'top down': ('    for (uint32_t r = down; r-- > 0;) {',
                     '    for (uint32_t r = 0; r < down; ++r) {'),
        'no order check': ('            return refuse(p, FPL_PLAY_R_ORDER);', '            (void)0;'),
        'leaves the root on the trailer': ('    poke(buf + 4, ROOT_STOCK);\n', ''),
        'no cache sync': ('    cache_sync();\n    p->last_us', '    p->last_us'),
        'trusts the capacity': ('cap - f0.soff < strip_bytes(&f0)',
                                'cap - f0.soff < strip_bytes(&f0) - strip_bytes(&f0)'),
        'no slack for the padded last row': ('f0->scnt <= pitch_of(f0->w, f0->bits) * f0->h + LAST_ROW_SLACK',
                                             'f0->scnt <= pitch_of(f0->w, f0->bits) * f0->h'),
        'ignores a gap in the tiles': ('        if (o != end || !n', '        if (!n'),
        'decodes while recording': ('    if (busy) return refuse(p, FPL_PLAY_R_BUSY);\n',
                                    '    (void)busy;\n'),
        'decodes straight into the strip': ('        if (decode_band(&f, f.th, across, o_at, s_at, WAIT_TICKS) != 0)',
                                            '        if (decode_band(&f, f.th, across, strip + r * raw_row, s_at, WAIT_TICKS) != 0)'),
        'copies whole tile rows in': ('(r == down - 1u ? rem : f.th) * pitch',
                                      '(r == down - 1u ? rem + 2u : f.th) * pitch'),
        'no scratch for a clip opening on a stock frame': (
            '    p->scratch_want = need;\n',
            '    p->scratch_want = rd32(h + 4, 1) == ROOT_STOCK ? 0 : need;\n'),
        'takes a second scratch': ('    if (!p->scratch) {\n        p->scratch = scratch_get',
                                   '    {\n        p->scratch = scratch_get'),
        'keeps a stale want across clips': ('    p->scratch_want = 0;\n    p->hook_end_us = 0;',
                                            '    p->hook_end_us = 0;'),
        'no clip check while recording': ('    if (busy || !desc) return size;',
                                          '    (void)busy;\n    if (!desc) return size;'),
    }

    def test_every_mutation_is_caught(self):
        with tempfile.TemporaryDirectory(prefix='fpl-play-mut-') as tmp:
            for index, (name, seam) in enumerate(self.MUTATIONS.items()):
                with self.subTest(mutation=name):
                    lib = build(tmp, seam, f'm{index}.dylib')

                    class Against(PlayDecodeTests):
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
        with tempfile.TemporaryDirectory(prefix='fpl-play-arm-') as tmp:
            out = Path(tmp) / 'play.o'
            subprocess.run([clang, '--target=armv7a-none-eabi', '-mcpu=cortex-a9', '-mthumb',
                            '-mfloat-abi=soft', '-mfpu=none', '-ffreestanding', '-fno-builtin',
                            '-nostdlib', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-Wpedantic', '-c', '-I', str(HERE), str(HERE / 'play_decode.c'),
                            '-o', str(out)], check=True, capture_output=True, text=True,
                           timeout=30)
            undefined = subprocess.run([nm, '-u', str(out)], capture_output=True,
                                       text=True).stdout
            for forbidden in ('memcpy', 'memset', '__aeabi', '_test_natives'):
                self.assertNotIn(forbidden, undefined, undefined)


if __name__ == '__main__':
    unittest.main()
