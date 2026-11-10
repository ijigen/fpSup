"""The compressed IFD prepared inside the firmware's header template.

On a REAL stock FHD frame from this camera: its header is turned into the
template the firmware would serialize with the card's private tag added
(the root IFD rebuilt with one more entry, the tag's value after it), then
header_tag.c prepares the compressed IFD in the template, the "DMA" copies the
template into a frame, and the completion writes only the tile entries, the
tables and the root pointer. LibRaw must decode the result to exactly the
stock samples, and a RAW frame of the same take must still decode as stock.

No camera, USB or card.
"""
import ctypes as ct
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STOCK = ROOT / 'projects/open-gate/captures/opengate_ev_bug_20260914/dng/A001_083_FHD_f01.DNG'
sys.path.insert(0, str(ROOT / 'research/slimRAW'))
sys.path.insert(0, str(ROOT / 'projects/lossless-sup/tools'))

OK, INVALID, BUSY, UNSUPPORTED, NOT_READY, FAULT = range(6)
PIXELS = 0x13400
TAG = 0xFD4C


def tag_bytes(tiles):
    """header_tag.h FPL_HEADER_TAG_BYTES"""
    return ((3 + 2 + 12 * 80 + 4 + 3) + 8 * tiles + 3) & ~3


TAG_BYTES = tag_bytes(12)               # the FHD take's twelve tiles


def build(directory, source=None, name='header_tag.dylib'):
    out = Path(directory) / name
    subprocess.run([shutil.which('clang') or 'clang', '-shared', '-fPIC', '-O2', '-std=c11',
                    '-Wall', '-Wextra', '-Werror', '-I', str(HERE),
                    str(source or HERE / 'header_tag.c'), str(HERE / 'header_tag_fixture.c'),
                    '-o', str(out)], check=True, capture_output=True, text=True, timeout=60)
    lib = ct.CDLL(str(out))
    lib.fpl_fixture_prepare.argtypes = [ct.c_void_p, ct.c_uint32, ct.c_uint32, ct.c_void_p]
    lib.fpl_fixture_prepare.restype = ct.c_uint32
    lib.fpl_fixture_complete.argtypes = [ct.c_void_p, ct.c_uint32, ct.c_uint32, ct.c_void_p,
                                         ct.c_uint32, ct.c_uint32, ct.c_uint32, ct.c_uint32,
                                         ct.c_void_p]
    lib.fpl_fixture_complete.restype = ct.c_uint32
    return lib


def encode_stock():
    """The stock frame's twelve tiles, padded as the firmware pads them."""
    import numpy as np
    import ljenc
    import mkcompressed as mk
    data = STOCK.read_bytes()
    _, _, _, ifds = mk.parse(str(STOCK))
    t = ifds[0]
    w, h, off = t[256][2][0], t[257][2][0], t[273][2][0]
    b = np.frombuffer(data, np.uint8, count=w * h * 3 // 2, offset=off).reshape(-1, 3)
    b = b.astype(np.uint16)
    px = np.empty(w * h, np.uint16)
    px[0::2] = (b[:, 0] << 4) | (b[:, 1] >> 4)
    px[1::2] = ((b[:, 1] & 0xF) << 8) | b[:, 2]
    pad, _, _ = mk.pad_image(px.reshape(h, w), 512, 368)
    blobs = [ljenc.encode_tile(pad[y:y + 368, x:x + 512], 12, 1)
             for y in range(0, pad.shape[0], 368) for x in range(0, pad.shape[1], 512)]
    counts = [len(x) for x in blobs]
    payload = b''.join(blobs)
    fill = (-len(payload)) % 1024           # C062F95C..C062F98C
    payload += bytes(fill)
    counts[-1] += fill
    return data, payload, counts


def entries_of(buf, root):
    n, = struct.unpack_from('<H', buf, root)
    return [bytes(buf[root + 2 + 12 * i: root + 14 + 12 * i]) for i in range(n)]


def make_template(stock, size=TAG_BYTES):
    """The stock header as the firmware would serialize it with our tag: the
    root IFD moved past the old header with one more entry, the tag's value
    after it at an offset that is 2 mod 4, the length aligned to 1 KiB."""
    header = bytearray(stock[:PIXELS])
    root, = struct.unpack_from('<I', header, 4)
    old = entries_of(header, root)
    new_root = PIXELS
    value = new_root + 2 + 12 * (len(old) + 1) + 4
    assert value % 4 == 2
    head = (value + size + 0x3FF) & ~0x3FF
    ours = struct.pack('<HHII', TAG, 7, size, value)
    entries = sorted(old + [ours], key=lambda e: struct.unpack_from('<H', e)[0])
    out = bytearray(head)
    out[:PIXELS] = header
    struct.pack_into('<H', out, new_root, len(entries))
    for i, e in enumerate(entries):
        out[new_root + 2 + 12 * i: new_root + 14 + 12 * i] = e
    struct.pack_into('<I', out, new_root + 2 + 12 * len(entries), 0)
    struct.pack_into('<I', out, 4, new_root)
    for i, e in enumerate(entries):                  # the strip moves with the header
        if struct.unpack_from('<H', e)[0] == 273:
            struct.pack_into('<I', out, new_root + 2 + 12 * i + 8, head)
    return out, head


def entry_at(buf, root, tag):
    n, = struct.unpack_from('<H', buf, root)
    for i in range(n):
        if struct.unpack_from('<H', buf, root + 2 + 12 * i)[0] == tag:
            return root + 2 + 12 * i
    raise AssertionError(tag)


class HeaderTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-htag-')
        cls.lib = build(cls.tmp.name)
        cls.stock, cls.payload, cls.counts = SHARED
        cls.template, cls.head = make_template(cls.stock)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def call(self, fn, buf, *args, n=12):
        raw = (ct.c_uint8 * len(buf)).from_buffer(buf)
        out = (ct.c_uint32 * n)()
        r = fn(ct.addressof(raw), len(buf), *args, ct.addressof(out))
        del raw
        return r, list(out)

    def prepare(self, tmpl=None):
        tmpl = bytearray(self.template) if tmpl is None else tmpl
        r, out = self.call(self.lib.fpl_fixture_prepare, tmpl, self.head)
        return r, out, tmpl

    def frame(self, tmpl, payload=True):
        """The DMA'd template, then our payload over the start of the old
        raster (or the stock raster itself for a RAW frame)."""
        raster = bytearray(self.stock[PIXELS:])
        if payload:
            raster[:len(self.payload)] = self.payload
        return bytearray(tmpl) + raster

    def complete(self, buf, payload=None, counts=None, capacity=None, tw=512, th=368):
        counts = self.counts if counts is None else counts
        arr = (ct.c_uint32 * len(counts))(*counts)
        return self.call(self.lib.fpl_fixture_complete, buf,
                         len(self.payload) if payload is None else payload,
                         ct.addressof(arr), len(counts), tw, th,
                         len(buf) if capacity is None else capacity)

    def decode_equals_stock(self, data):
        import rawpy
        path = Path(self.tmp.name) / 'f.DNG'
        path.write_bytes(bytes(data))
        with rawpy.imread(str(STOCK)) as a, rawpy.imread(str(path)) as b:
            self.assertEqual(a.raw_image.shape, b.raw_image.shape)
            self.assertTrue((a.raw_image == b.raw_image).all(), 'samples differ')

    # ---- the whole path ----------------------------------------------------
    def test_a_raw_frame_of_the_take_still_decodes_as_stock(self):
        r, _, tmpl = self.prepare()
        self.assertEqual(r, OK)
        raw_len = self.head + len(self.stock) - PIXELS
        self.decode_equals_stock(self.frame(tmpl, payload=False)[:raw_len])

    def test_the_completed_frame_decodes_to_exactly_the_stock_samples(self):
        r, out, tmpl = self.prepare()
        self.assertEqual(r, OK)
        buf = self.frame(tmpl)
        r, res = self.complete(buf)
        self.assertEqual(r, OK)
        self.assertEqual(res[6], self.head + len(self.payload))
        self.decode_equals_stock(buf[:res[6]])
        self.assertLess(res[6], len(self.stock), 'no smaller than stock')

    def test_the_compressed_ifd_is_the_root_ifd_with_tiles_instead_of_strips(self):
        r, out, tmpl = self.prepare()
        buf = self.frame(tmpl)
        r, res = self.complete(buf)
        self.assertEqual(r, OK)
        ifd_at, = struct.unpack_from('<I', buf, 4)
        self.assertEqual(ifd_at, out[6])
        self.assertEqual(ifd_at % 4, 0)
        old_root = PIXELS
        old = {struct.unpack_from('<H', e)[0]: e for e in entries_of(buf, old_root)}
        new = {struct.unpack_from('<H', e)[0]: e for e in entries_of(buf, ifd_at)}
        self.assertEqual(set(old) - {273, 278, 279} | {322, 323, 324, 325}, set(new))
        for tag in set(old) - {259, 273, 278, 279}:
            self.assertEqual(old[tag], new[tag], hex(tag))
        self.assertEqual(struct.unpack_from('<HHIH', new[259]), (259, 3, 1, 7))
        self.assertEqual(struct.unpack_from('<HHII', new[322]), (322, 4, 1, 512))
        self.assertEqual(struct.unpack_from('<HHII', new[323]), (323, 4, 1, 368))
        _, _, n, offs = struct.unpack_from('<HHII', new[324])
        _, _, m, cnts = struct.unpack_from('<HHII', new[325])
        self.assertEqual((n, m), (len(self.counts), len(self.counts)))
        got_off = struct.unpack_from(f'<{n}I', buf, offs)
        got_cnt = struct.unpack_from(f'<{n}I', buf, cnts)
        self.assertEqual(list(got_cnt), self.counts)
        pos = [self.head]
        for c in self.counts[:-1]:
            pos.append(pos[-1] + c)
        self.assertEqual(list(got_off), pos)
        # all of it inside the tag's value
        value = struct.unpack_from('<I', old[TAG], 8)[0]
        self.assertGreaterEqual(ifd_at, value)
        self.assertLessEqual(cnts + 4 * out[10], value + TAG_BYTES)

    def test_completion_writes_only_the_tile_fields_the_tables_and_last_the_root(self):
        r, out, tmpl = self.prepare()
        buf = self.frame(tmpl)
        before = bytes(buf)
        r, res = self.complete(buf)
        self.assertEqual(r, OK)
        self.assertEqual(res[0], 0, 'unaligned access')
        self.assertEqual(res[1], 0, 'access outside the buffer')
        self.assertEqual(res[4], 4, 'the root pointer was not the last write')
        self.assertEqual(res[5], res[3], 'the root pointer was written before the end')
        # few writes: tile fields and two tables, not an IFD
        self.assertLessEqual(res[3], 12 + 2 * len(self.counts) + 1)
        tables_end = out[9] + 4 * out[10]
        changed = [i for i in range(len(buf)) if buf[i] != before[i]]
        for i in changed:
            self.assertTrue(4 <= i < 8 or out[6] <= i < tables_end, hex(i))

    def test_the_tag_is_sized_for_the_take(self):
        """A take with fewer tiles gets a smaller tag, and still decodes."""
        self.assertLess(TAG_BYTES, 1200)
        tmpl, head = make_template(self.stock, tag_bytes(len(self.counts)))
        r, out = self.call(self.lib.fpl_fixture_prepare, tmpl, head)
        self.assertEqual(r, OK)
        self.assertGreaterEqual(out[10], len(self.counts), 'no room for this take')
        # with the root IFD at 8, as the firmware serializes it, the stock
        # header's 100 B of padding plus this tag stay inside 0x13800
        self.assertLessEqual(0x13400 - 100 + 12 + TAG_BYTES, 0x13800)

    def test_one_tile_is_kept_in_the_entries(self):
        r, out, tmpl = self.prepare()
        buf = self.frame(tmpl)
        r, res = self.complete(buf, counts=[len(self.payload)])
        self.assertEqual(r, OK)
        ifd_at, = struct.unpack_from('<I', buf, 4)
        e = entry_at(buf, ifd_at, 324)
        self.assertEqual(struct.unpack_from('<II', buf, e + 4), (1, self.head))
        e = entry_at(buf, ifd_at, 325)
        self.assertEqual(struct.unpack_from('<II', buf, e + 4), (1, len(self.payload)))

    # ---- refusals: nothing written ----------------------------------------
    def refused_prepare(self, tmpl, head=None):
        before = bytes(tmpl)
        raw = (ct.c_uint8 * len(tmpl)).from_buffer(tmpl)
        out = (ct.c_uint32 * 12)()
        r = self.lib.fpl_fixture_prepare(ct.addressof(raw), len(tmpl),
                                         self.head if head is None else head, ct.addressof(out))
        del raw
        self.assertEqual(r, UNSUPPORTED)
        self.assertEqual(bytes(tmpl), before, 'a refused prepare wrote something')
        self.assertEqual(out[3], 0)

    def test_a_template_without_our_tag_is_refused(self):
        stock = bytearray(self.stock[:PIXELS])
        self.refused_prepare(stock, PIXELS)

    def test_a_tag_of_another_type_or_outside_the_sizes_is_refused(self):
        for field, value in ((2, 4), (4, tag_bytes(2) - 4), (4, tag_bytes(160) + 4)):
            with self.subTest(field=field):
                t = bytearray(self.template)
                e = entry_at(t, PIXELS, TAG)
                struct.pack_into('<H' if field == 2 else '<I', t, e + field, value)
                self.refused_prepare(t)

    def test_a_tag_value_past_the_template_is_refused(self):
        t = bytearray(self.template)
        e = entry_at(t, PIXELS, TAG)
        struct.pack_into('<I', t, e + 8, self.head - TAG_BYTES + 2)
        self.refused_prepare(t)

    def test_an_unrecognised_root_ifd_is_refused(self):
        cases = []
        t = bytearray(self.template); struct.pack_into('<H', t, entry_at(t, PIXELS, 259) + 8, 7)
        cases.append(t)
        t = bytearray(self.template); struct.pack_into('<H', t, entry_at(t, PIXELS, 278), 277)
        cases.append(t)
        t = bytearray(self.template); t[0:4] = b'MM\x00*'
        cases.append(t)
        for i, t in enumerate(cases):
            with self.subTest(case=i):
                self.refused_prepare(t)

    def refused_complete(self, buf, expect=UNSUPPORTED, **kw):
        before = bytes(buf)
        r, res = self.complete(buf, **kw)
        self.assertEqual(r, expect)
        self.assertEqual(bytes(buf), before, 'a refused completion wrote something')
        self.assertEqual(res[3], 0)

    def test_a_frame_whose_header_is_not_the_prepared_template_is_refused(self):
        r, out, tmpl = self.prepare()
        buf = self.frame(tmpl)
        struct.pack_into('<H', buf, out[6], 3)              # another IFD there
        self.refused_complete(buf)
        stock = bytearray(self.stock)                        # a frame from before
        stock[PIXELS:PIXELS + len(self.payload)] = self.payload
        self.refused_complete(stock)

    def test_tiles_that_do_not_add_up_or_do_not_fit_are_refused(self):
        r, out, tmpl = self.prepare()
        for counts in (self.counts[:-1] + [self.counts[-1] - 1], [0] + self.counts[1:]):
            with self.subTest():
                self.refused_complete(self.frame(tmpl), INVALID, counts=counts)
        self.refused_complete(self.frame(tmpl),
                              capacity=self.head + len(self.payload) - 1)
        many = [1] * (out[10] + 1)
        self.refused_complete(self.frame(tmpl), payload=len(many), counts=many)


class HeaderTagMutationTests(unittest.TestCase):
    MUTATIONS = {
        'root pointer first': (
            '    wr32(read, write, file + t->width_at + 8u, tile_width);',
            '    write(file + 4, t->ifd_at);\n    wr32(read, write, file + t->width_at + 8u, tile_width);'),
        'tables swapped': ('            write(file + t->tables_at + 4u * n, position);',
                           '            write(file + t->counts_at + 4u * n, position);'),
        'offsets from the old header': ('        position = t->head;', '        position = 0x13400u;'),
        'leaves Compression at 1': ('put_entry(read, write, at, tag, TYPE_SHORT, 1, LOSSLESS_JPEG)',
                                    'put_entry(read, write, at, tag, TYPE_SHORT, 1, 1)'),
        'keeps the strips': ('        if (tag == TAG_STRIP_OFFSETS || tag == TAG_ROWS_PER_STRIP || tag == TAG_STRIP_COUNTS)\n            continue;',
                             ''),
        'unaligned IFD': ('    ifd_at = (value + 3u) & ~3u;', '    ifd_at = value;'),
        'trusts the frame': ('    if (read(file) != TIFF_LE_MAGIC || rd16(read, file + t->ifd_at) != t->entries ||',
                             '    if (read(file) != TIFF_LE_MAGIC || 0 ||'),
        'trusts the tile sum': ('    if (sum != payload) return FPL_INVALID;', ''),
        'one tile through a table': ('    if (tiles == 1u) {', '    if (0) {'),
    }

    def test_every_mutation_is_caught(self):
        text = (HERE / 'header_tag.c').read_text()
        with tempfile.TemporaryDirectory(prefix='fpl-htag-mut-') as tmp:
            for i, (name, (old, new)) in enumerate(self.MUTATIONS.items()):
                with self.subTest(mutation=name):
                    self.assertEqual(text.count(old), 1, name)
                    src = Path(tmp) / f'm{i}.c'
                    src.write_text(text.replace(old, new))
                    lib = build(tmp, src, f'm{i}.dylib')

                    class Against(HeaderTagTests):
                        @classmethod
                        def setUpClass(cls):
                            cls.tmp = tempfile.TemporaryDirectory(prefix='fpl-htag-m-')
                            cls.lib = lib
                            cls.stock, cls.payload, cls.counts = SHARED
                            cls.template, cls.head = make_template(cls.stock)
                    result = unittest.TestResult()
                    unittest.defaultTestLoader.loadTestsFromTestCase(Against).run(result)
                    self.assertFalse(result.wasSuccessful(), f'{name} was not caught')


class ArmCompileTests(unittest.TestCase):
    def test_it_builds_freestanding_for_the_camera(self):
        clang = shutil.which('clang') or 'clang'
        nm = shutil.which('llvm-nm') or shutil.which('nm') or 'nm'
        with tempfile.TemporaryDirectory(prefix='fpl-htag-arm-') as tmp:
            out = Path(tmp) / 'header_tag.o'
            subprocess.run([clang, '--target=armv7a-none-eabi', '-mcpu=cortex-a9', '-mthumb',
                            '-mfloat-abi=soft', '-mfpu=none', '-ffreestanding', '-fno-builtin',
                            '-nostdlib', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror', '-c',
                            '-I', str(HERE), str(HERE / 'header_tag.c'), '-o', str(out)],
                           check=True, capture_output=True, text=True, timeout=30)
            undefined = subprocess.run([nm, '-u', str(out)], capture_output=True,
                                       text=True).stdout
            for forbidden in ('memcpy', 'memset', '__aeabi'):
                self.assertNotIn(forbidden, undefined, undefined)


SHARED = None


def setUpModule():
    global SHARED
    SHARED = encode_stock()


if __name__ == '__main__':
    unittest.main()
