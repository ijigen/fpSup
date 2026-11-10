"""14-bit Lossless, end to end on a REAL Sensor Lab 1:1 true-14 frame (2026-11-10).

The frame is B_A001_265_000003.DNG: 6048x4040, BitsPerSample 14, one strip of
exactly 6048 x 4040 x 14 / 8 bytes (Sensor Lab, 2026-10-30 live2). Here:

  1. LibRaw's reading of the stock strip IS the MSB-first packed-14 reading
     with a row pitch of 14 x 6048 / 8 -- the layout the engine is programmed
     with (C062FFF8: 300D006C = 14 x width / 16, test_producer_facts).
  2. The frame is cut into the take's grid (tile_grid.h, compiled), each tile
     LJ92-encoded the way the engine encodes (2 components, predictor 1,
     P = 14, per-tile Huffman; research/slimRAW/ljenc, here vectorised and
     checked byte-identical to ljenc), padded to 1 KiB as codec_job does.
  3. header_tag.c (compiled, the camera's source) prepares the compressed IFD
     in the firmware-style template and completes the frame.
  4. LibRaw -- not ours -- decodes the result: every sample equals the stock
     frame's. The repo's own LJ92 decoder (research/slimRAW/ljpeg) decodes one
     tile independently of LibRaw.

What this does NOT prove: that the camera's engine reads a Sigpro format-1
raster MSB-first (the stills path feeds it format 1, StillCr C037E7AC, but no
uncompressed still was compared). That is the live check
(projects/sensorlab-imx410/validation/20261110-lossless-14bit/LIVE_PROTOCOL.md).

No camera, USB or card.
"""
import ctypes as ct
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FRAME14 = ROOT / 'projects/sensorlab-imx410/validation/2026-10-30-v1-live2/dng/B_A001_265_000003.DNG'
sys.path.insert(0, str(ROOT / 'research/slimRAW'))
sys.path.insert(0, str(HERE))

import test_header_tag as T            # noqa: E402  build / make_template / tag_bytes / PIXELS

OK = 0
W, H = 6048, 4040


def unpack14(strip, w, h, msb_first=True):
    """Packed 14 bit, 4 samples in 7 bytes, rows w*14/8 apart."""
    b = np.frombuffer(strip, np.uint8, count=w * h * 14 // 8).reshape(-1, 7).astype(np.uint64)
    if msb_first:
        v = np.zeros(len(b), np.uint64)
        for k in range(7):
            v = (v << np.uint64(8)) | b[:, k]
        out = np.stack([(v >> np.uint64(s)) & np.uint64(0x3FFF) for s in (42, 28, 14, 0)], 1)
    else:
        v = np.zeros(len(b), np.uint64)
        for k in range(7):
            v |= b[:, k] << np.uint64(8 * k)
        out = np.stack([(v >> np.uint64(s)) & np.uint64(0x3FFF) for s in (0, 14, 28, 42)], 1)
    return out.reshape(h, w).astype(np.uint16)


def grid_lib(directory):
    """fpl_tile_grid from tile_grid.h itself."""
    src = Path(directory) / 'grid.c'
    src.write_text('#include "tile_grid.h"\n'
                   'void grid(uint32_t w, uint32_t h, uint32_t *tw, uint32_t *th)'
                   ' { fpl_tile_grid(w, h, 0, tw, th); }\n')
    out = Path(directory) / 'grid.dylib'
    subprocess.run([shutil.which('clang') or 'clang', '-shared', '-fPIC', '-O2', '-std=c11',
                    '-I', str(HERE), '-I', str(HERE.parent), str(src), '-o', str(out)],
                   check=True, capture_output=True, text=True, timeout=60)
    lib = ct.CDLL(str(out))
    lib.grid.argtypes = [ct.c_uint32, ct.c_uint32, ct.POINTER(ct.c_uint32), ct.POINTER(ct.c_uint32)]
    return lib


def grid_of(lib, w, h):
    tw, th = ct.c_uint32(), ct.c_uint32()
    lib.grid(w, h, ct.byref(tw), ct.byref(th))
    return tw.value, th.value


def encode_tile_fast(tile, P):
    """ljenc.encode_tile, the bit writer vectorised (same tables, same bytes)."""
    import ljenc
    th, tw = tile.shape
    comps = [tile[:, c::2] for c in (0, 1)]
    D = [ljenc._diffs(c, P, 1) for c in comps]
    S = [ljenc._ssss(d) for d in D]
    tables = []
    for s in S:
        u, cnt = np.unique(s, return_counts=True)
        tables.append(ljenc._canonical(ljenc._huff_lengths(dict(zip(u.tolist(), cnt.tolist())))))
    out = bytearray(b'\xFF\xD8')
    out += b'\xFF\xC3' + (14).to_bytes(2, 'big') + bytes([P]) + \
        th.to_bytes(2, 'big') + (tw // 2).to_bytes(2, 'big') + b'\x02' + \
        b'\x00\x11\x00' + b'\x01\x11\x00'
    for i, (counts, order, codes) in enumerate(tables):
        body = bytes([i]) + bytes(counts) + bytes(order)
        out += b'\xFF\xC4' + (len(body) + 2).to_bytes(2, 'big') + body
    out += b'\xFF\xDA' + (10).to_bytes(2, 'big') + b'\x02\x00\x00\x01\x10' + bytes([1, 0, 0])
    # one (value, length) per sample, the two components interleaved
    vals, lens = [], []
    for c in (0, 1):
        codes = tables[c][2]
        lut_l = np.zeros(17, np.int64)
        lut_c = np.zeros(17, np.int64)
        for sym, (l, code) in codes.items():
            lut_l[sym], lut_c[sym] = l, code
        d, s = D[c].astype(np.int64), S[c].astype(np.int64)
        extra_n = np.where((s > 0) & (s != 16), s, 0)
        extra_v = np.where(d > 0, d, d + (np.int64(1) << s) - 1) & ((np.int64(1) << extra_n) - 1)
        vals.append((lut_c[s] << extra_n) | extra_v)
        lens.append(lut_l[s] + extra_n)
    v = np.stack(vals, -1).reshape(-1)          # row-major, component 0 then 1
    n = np.stack(lens, -1).reshape(-1)
    starts = np.concatenate(([0], np.cumsum(n)[:-1]))
    total = int(n.sum())
    nbits = total + (-total) % 8
    bits = np.ones(nbits, np.uint8)            # the flush pads with 1 bits
    for k in range(int(n.max())):
        m = n > k
        bits[starts[m] + k] = ((v[m] >> (n[m] - 1 - k)) & 1).astype(np.uint8)
    data = np.packbits(bits)
    ff = np.nonzero(data == 0xFF)[0]
    data = np.insert(data, ff + 1, 0)          # byte stuffing
    return bytes(out) + data.tobytes() + b'\xFF\xD9'


class Lossless14RoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FRAME14.exists():
            # The frame is a camera DNG from the research tree, not published: skip where it is absent
            # (FPL_REQUIRE_FRAME14=1 makes a missing frame a failure).
            if os.environ.get('FPL_REQUIRE_FRAME14') == '1':
                raise AssertionError(f'missing the Sensor Lab 14-bit frame {FRAME14}')
            raise unittest.SkipTest(f'the Sensor Lab 14-bit frame is not in this tree: {FRAME14}')
        import rawpy
        import tilegeom
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-ll14-')
        cls.stock = FRAME14.read_bytes()
        with rawpy.imread(str(FRAME14)) as raw:
            cls.libraw = raw.raw_image.copy()
        cls.pixels = unpack14(cls.stock[T.PIXELS:], W, H)
        cls.grid = grid_of(grid_lib(cls.tmp.name), W, H)
        tw, th = cls.grid
        pad, _, _ = tilegeom.pad_image(cls.pixels, tw, th)
        blobs = [encode_tile_fast(pad[y:y + th, x:x + tw], 14)
                 for y in range(0, pad.shape[0], th) for x in range(0, pad.shape[1], tw)]
        cls.first_tile = pad[:th, :tw].copy()
        cls.blobs = blobs
        counts = [len(b) for b in blobs]
        payload = b''.join(blobs)
        fill = (-len(payload)) % 1024              # C062F95C..C062F98C
        payload += bytes(fill)
        counts[-1] += fill
        cls.payload, cls.counts = payload, counts
        cls.lib = T.build(cls.tmp.name)
        cls.template, cls.head = T.make_template(cls.stock, T.tag_bytes(len(counts)))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_stock_strip_is_tight_msb_first_packed_14(self):
        r, = struct.unpack_from('<I', self.stock, 4)
        tags = {}
        for e in T.entries_of(self.stock, r):
            tag, kind, n, v = struct.unpack('<HHII', e)
            tags[tag] = v & 0xFFFF if kind == 3 else v
        self.assertEqual((tags[256], tags[257], tags[258], tags[259]), (W, H, 14, 1))
        self.assertEqual((tags[273], tags[279]), (T.PIXELS, W * H * 14 // 8))
        self.assertTrue((self.pixels == self.libraw).all())
        # the reading is not vacuous: LSB-first is a different picture
        self.assertFalse((unpack14(self.stock[T.PIXELS:], W, H, msb_first=False) == self.libraw).all())

    def test_the_take_grid_is_what_codec_job_sends(self):
        tw, th = self.grid
        self.assertEqual((tw, th), (512, 512))
        self.assertEqual(len(self.counts), 12 * 8)
        self.assertLessEqual(len(self.counts), 160)

    def test_the_vectorised_encoder_is_ljenc(self):
        import ljenc
        tile = self.first_tile[:64, :128]
        self.assertEqual(encode_tile_fast(tile, 14), ljenc.encode_tile(tile, 14, 1))
        self.assertEqual(self.blobs[0][2:6], b'\xFF\xC3\x00\x0E')
        self.assertEqual(self.blobs[0][6], 14)       # SOF3 precision

    def test_an_independent_ljpeg_decoder_reads_a_tile_back(self):
        import ljpeg
        tw, th = self.grid
        small = self.first_tile[:32, :64]
        P, X, Y, Nf, rows = ljpeg.decode_tile(encode_tile_fast(small, 14))
        self.assertEqual((P, X, Y, Nf), (14, 32, 32, 2))
        self.assertTrue((np.array(rows, np.uint16) == small).all())

    def test_the_completed_14bit_frame_decodes_to_exactly_the_stock_samples(self):
        import rawpy
        tmpl = bytearray(self.template)
        raw = (ct.c_uint8 * len(tmpl)).from_buffer(tmpl)
        out = (ct.c_uint32 * 12)()
        self.assertEqual(self.lib.fpl_fixture_prepare(ct.addressof(raw), len(tmpl), self.head,
                                                      ct.addressof(out)), OK)
        del raw
        raster = bytearray(self.stock[T.PIXELS:])
        raster[:len(self.payload)] = self.payload
        buf = bytearray(tmpl) + raster
        arr = (ct.c_uint32 * len(self.counts))(*self.counts)
        rawbuf = (ct.c_uint8 * len(buf)).from_buffer(buf)
        res = (ct.c_uint32 * 12)()
        tw, th = self.grid
        self.assertEqual(self.lib.fpl_fixture_complete(ct.addressof(rawbuf), len(buf),
                                                       len(self.payload), ct.addressof(arr),
                                                       len(self.counts), tw, th, len(buf),
                                                       ct.addressof(res)), OK)
        del rawbuf
        size = res[6]
        self.assertEqual(size, self.head + len(self.payload))
        frame = bytes(buf[:size])
        # the compressed IFD: BitsPerSample carried over as 14, Compression 7, tiles
        root, = struct.unpack_from('<I', frame, 4)
        tags = {}
        for e in T.entries_of(frame, root):
            tag, kind, n, v = struct.unpack('<HHII', e)
            tags[tag] = (kind, n, v & 0xFFFF if kind == 3 else v)
        self.assertEqual(tags[258][2], 14)
        self.assertEqual(tags[259][2], 7)
        self.assertEqual((tags[322][2], tags[323][2]), (tw, th))
        self.assertEqual((tags[324][1], tags[325][1]), (len(self.counts),) * 2)
        for t in (273, 278, 279):
            self.assertNotIn(t, tags)
        path = Path(self.tmp.name) / 'll14.DNG'
        path.write_bytes(frame)
        with rawpy.imread(str(path)) as b:
            self.assertEqual(b.raw_image.shape, self.libraw.shape)
            self.assertTrue((b.raw_image == self.libraw).all(), 'samples differ')
        ratio = (W * H * 14 / 8) / len(self.payload)
        # informative: this real (dim, ISO?) frame's 14-bit ratio
        print(f'\n  6048x4040 14-bit: payload {len(self.payload):,} B, ratio {ratio:.2f}:1, '
              f'{len(self.payload) * 8 / (W * H):.2f} bpp', file=sys.stderr)
        self.assertGreater(ratio, 1.0)


class RoundTripMutationTests(unittest.TestCase):
    """The 14-bit round trip fails when header_tag.c is broken."""
    MUTATIONS = {
        'offsets from the old header': ('        position = t->head;', '        position = 0x13400u;'),
        'leaves Compression at 1': ('put_entry(read, write, at, tag, TYPE_SHORT, 1, LOSSLESS_JPEG)',
                                    'put_entry(read, write, at, tag, TYPE_SHORT, 1, 1)'),
        'tables swapped': ('            write(file + t->tables_at + 4u * n, position);',
                           '            write(file + t->counts_at + 4u * n, position);'),
    }

    def test_every_mutation_is_caught(self):
        text = (HERE / 'header_tag.c').read_text()
        Lossless14RoundTripTests.setUpClass()
        self.addCleanup(Lossless14RoundTripTests.tearDownClass)
        real = Lossless14RoundTripTests.lib
        with tempfile.TemporaryDirectory(prefix='fpl-ll14-mut-') as tmp:
            try:
                for i, (name, (old, new)) in enumerate(self.MUTATIONS.items()):
                    with self.subTest(mutation=name):
                        self.assertEqual(text.count(old), 1, name)
                        src = Path(tmp) / f'm{i}.c'
                        src.write_text(text.replace(old, new))
                        Lossless14RoundTripTests.lib = T.build(tmp, src, f'm{i}.dylib')
                        result = unittest.TestResult()
                        Lossless14RoundTripTests(
                            'test_the_completed_14bit_frame_decodes_to_exactly_the_stock_samples').run(result)
                        self.assertFalse(result.wasSuccessful(), f'{name} was not caught')
            finally:
                Lossless14RoundTripTests.lib = real


if __name__ == '__main__':
    unittest.main()
