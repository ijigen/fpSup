"""Execute the actual reservation arithmetic; no camera, allocator or DMA.

Host C execution and ARM compilation validate arithmetic only. Output capacity
is a benefit-only budget, not a JPEG expansion bound or a codec safety proof.
"""
import ctypes as ct
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
OK, INVALID, UNSUPPORTED = 0, 1, 3
ALIGN = 1024
SPAN_NAMES = ('source', 'output', 'codec_sizes', 'codec_scratch', 'metadata',
              'tile_offsets', 'tile_counts')


class Span(ct.Structure):
    _fields_ = [('offset', ct.c_uint32), ('capacity', ct.c_uint32)]


class Layout(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in
                ('width', 'height', 'bits', 'tile_cols', 'tile_rows',
                 'tile_count', 'raster_bytes', 'total_bytes')]
    _fields_ += [(name, Span) for name in SPAN_NAMES]


class Context(ct.Structure):
    _fields_ = [(name, ct.c_uint32) for name in
                ('firmware', 'cine', 'compression', 'bits', 'width', 'height',
                 'fps_num', 'fps_den', 'media', 'ready')]


def aligned(n):
    return ((n + ALIGN - 1) // ALIGN) * ALIGN


class WorkspaceLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('clang')
        if not cls.compiler:
            raise RuntimeError('clang is required; implementation checks cannot be skipped')
        cls.temp = tempfile.TemporaryDirectory(prefix='fpl-workspace-layout-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.lib = cls.compile(HERE / 'workspace_layout.c', 'baseline')

    @classmethod
    def compile(cls, source, name):
        target = Path(cls.temp.name) / (name + '.dylib')
        subprocess.run([cls.compiler, '-std=c11', '-O2', '-Wall', '-Wextra',
                        '-Werror', '-shared', '-fPIC', '-I', str(HERE),
                        str(source), str(HERE.parent / 'control.c'),
                        '-o', str(target)], check=True, capture_output=True,
                       text=True, timeout=30)
        lib = ct.CDLL(str(target))
        lib.fpl_workspace_plan.argtypes = [ct.POINTER(Layout)] + [ct.c_uint32] * 5
        lib.fpl_workspace_plan.restype = ct.c_uint32
        lib.fpl_can_enable.argtypes = [ct.POINTER(Context)]
        lib.fpl_can_enable.restype = ct.c_uint32
        return lib

    def plan(self, width=1936, height=1090, bits=12, copy=1, metadata=0x15400,
             lib=None):
        layout = Layout()
        result = (lib or self.lib).fpl_workspace_plan(
            ct.byref(layout), width, height, bits, copy, metadata)
        self.assertEqual(result, OK)
        return layout

    def check_layout(self, width, height, bits, copy, metadata, lib=None):
        layout = self.plan(width, height, bits, copy, metadata, lib)
        cols, rows = (width + 511) // 512, (height + 367) // 368
        tiles, raster = cols * rows, width * height * bits // 8
        self.assertEqual((layout.width, layout.height, layout.bits),
                         (width, height, bits))
        self.assertEqual((layout.tile_cols, layout.tile_rows, layout.tile_count),
                         (cols, rows, tiles))
        self.assertLessEqual(tiles, 160)
        self.assertEqual(layout.raster_bytes, raster)
        capacities = (aligned(raster) * copy, aligned(raster),
                      aligned(tiles * 4), aligned(tiles * 4), aligned(metadata),
                      aligned(tiles * 4), aligned(tiles * 4))
        end = 0
        for name, capacity in zip(SPAN_NAMES, capacities):
            span = getattr(layout, name)
            self.assertEqual((span.offset, span.capacity), (end, capacity), name)
            self.assertEqual(span.offset % ALIGN, 0)
            self.assertEqual(span.capacity % ALIGN, 0)
            self.assertLessEqual(span.offset + span.capacity, layout.total_bytes)
            end += capacity
        self.assertEqual(layout.total_bytes, end)
        self.assertEqual(layout.total_bytes % ALIGN, 0)
        self.assertEqual(layout.codec_scratch.offset,
                         layout.codec_sizes.offset + aligned(tiles * 4))
        return layout

    def test_layout_abi_has_no_readiness_or_pointer_fields(self):
        self.assertEqual(ct.sizeof(Layout), 88)
        self.assertEqual(Layout.source.offset, 32)
        self.assertEqual(Layout.tile_counts.offset, 80)

    def test_format_matrix_and_optional_source_copy(self):
        for width, height in ((8, 2), (1024, 576), (1936, 1090), (3840, 2160),
                              (4096, 2160), (6064, 4042)):
            for bits in (10, 12, 14):
                for copy in (0, 1):
                    with self.subTest(width=width, height=height, bits=bits, copy=copy):
                        self.check_layout(width, height, bits, copy, 0x15400)

    def test_six_k_14bit_is_not_limited_to_16_mib(self):
        layout = self.check_layout(6064, 4042, 14, 1, 0x15400)
        self.assertEqual(layout.raster_bytes, 42893704)
        self.assertEqual(layout.tile_count, 132)
        self.assertEqual(layout.source.capacity, 42894336)
        self.assertEqual(layout.output.capacity, 42894336)
        self.assertEqual(layout.total_bytes, 85879808)
        self.assertGreater(layout.output.capacity, 16 * 1024 * 1024)
        self.assertGreater(layout.total_bytes, 81 * 1024 * 1024)

    def test_fhd_copy_covers_native_length_rounding_tail(self):
        layout = self.check_layout(1936, 1090, 12, 1, 0x15400)
        self.assertEqual(layout.raster_bytes, 3165360)
        self.assertEqual(layout.source.capacity, 3166208)
        self.assertEqual(layout.source.capacity - layout.raster_bytes, 848)

    def test_tile_edge_geometry_does_not_claim_native_request_eligibility(self):
        # Exact tile-height multiples are valid reservation geometries, but the
        # unmodified native F_ENC has a separate zero-height final-band defect.
        for width in (504, 512, 520, 1536):
            for height in (366, 368, 370, 736):
                self.check_layout(width, height, 14, 1, 1)

    def test_zero_metadata_and_borrowed_source_are_explicit_empty_spans(self):
        layout = self.check_layout(1936, 1090, 10, 0, 0)
        self.assertEqual((layout.source.offset, layout.source.capacity), (0, 0))
        self.assertEqual(layout.metadata.capacity, 0)

    def test_metadata_is_caller_sized_not_a_fixed_header(self):
        for metadata in (1, 1023, 1024, 1025, 0x13400, 0x15400, 0x20000):
            self.check_layout(1936, 1090, 12, 1, metadata)

    def refused(self, args, expected, lib=None):
        layout = Layout()
        ct.memset(ct.byref(layout), 0xA7, ct.sizeof(layout))
        before = bytes(layout)
        result = (lib or self.lib).fpl_workspace_plan(ct.byref(layout), *args)
        self.assertEqual(result, expected)
        self.assertEqual(bytes(layout), before, 'failed planner published partial/stale geometry')

    def test_bad_geometry_and_depth_are_refused_without_output_changes(self):
        for width, height, bits in ((0, 2, 12), (4, 2, 12), (7, 2, 12), (9, 2, 12),
                                   (1936, 0, 12), (1936, 1, 12), (1936, 1091, 12),
                                   (6072, 4042, 14), (6064, 4044, 14),
                                   (0xFFFFFFFF, 2, 12), (8, 0xFFFFFFFE, 12),
                                   (1936, 1090, 0), (1936, 1090, 8),
                                   (1936, 1090, 16), (1936, 1090, 0xFFFFFFFF)):
            with self.subTest(width=width, height=height, bits=bits):
                self.refused((width, height, bits, 1, 0x15400), UNSUPPORTED)

    def test_null_output_and_noncanonical_copy_flag(self):
        self.assertEqual(self.lib.fpl_workspace_plan(None, 1936, 1090, 12, 1, 0), INVALID)
        for copy in (2, 3, 0xFFFFFFFF):
            self.refused((1936, 1090, 12, copy, 0), INVALID)

    def test_metadata_rounding_and_total_overflow_are_refused(self, lib=None):
        for metadata in (0xFFFFFFFF, 0xFFFFFC01, 0xFFFFFC00, 0xFFF00000):
            self.refused((6064, 4042, 14, 1, metadata), INVALID, lib)

    def test_largest_arithmetic_plan_fits_without_address_space_wrap_claim(self):
        fixed = self.plan(8, 2, 10, 0, 0).total_bytes
        metadata = 0xFFFFFC00 - fixed
        layout = self.check_layout(8, 2, 10, 0, metadata)
        self.assertEqual(layout.total_bytes, 0xFFFFFC00)
        # This is arithmetic only; a native allocator/address-range check must
        # still reject infeasible memory sizes and base+size wrapping.
        self.refused((8, 2, 10, 0, metadata + 1), INVALID)

    def test_planning_14bit_does_not_enable_the_existing_control(self):
        self.plan(6064, 4042, 14)
        context = Context(502, 1, 1, 14, 6064, 4042, 24, 1, 1, 127)
        self.assertEqual(self.lib.fpl_can_enable(ct.byref(context)), UNSUPPORTED)

    def test_arm_freestanding_compilation_has_no_runtime_helpers(self):
        obj = Path(self.temp.name) / 'layout.arm.o'
        asm = Path(self.temp.name) / 'layout.arm.s'
        args = [self.compiler, '--target=armv7-none-eabi', '-mcpu=cortex-a9',
                '-marm', '-mfloat-abi=soft', '-mfpu=none', '-std=c11', '-Os',
                '-ffreestanding', '-fno-builtin', '-Wall', '-Wextra', '-Werror']
        for flag, target in (('-c', obj), ('-S', asm)):
            subprocess.run(args + [flag, str(HERE / 'workspace_layout.c'), '-o', str(target)],
                           check=True, capture_output=True, text=True, timeout=30)
        binary = obj.read_bytes()
        self.assertEqual(binary[:4], b'\x7fELF')
        self.assertEqual(int.from_bytes(binary[18:20], 'little'), 40)
        for helper in ('__aeabi_', 'memcpy', 'memset', 'malloc'):
            self.assertNotIn(helper, asm.read_text())

    def test_mutations_are_caught(self):
        source = (HERE / 'workspace_layout.c').read_text()
        mutations = (
            ('drop-source-tail', 'packed_capacity = align1024(raster);',
             'packed_capacity = raster & ~1023u;',
             lambda lib: self.check_layout(1936, 1090, 12, 1, 0x15400, lib)),
            ('old-16m-cap', 'packed_capacity = align1024(raster);',
             'packed_capacity = 16u * 1024u * 1024u;',
             lambda lib: self.check_layout(6064, 4042, 14, 1, 0x15400, lib)),
            ('overlap-codec-tables', 'span(&out->codec_scratch, at, table_capacity)',
             'span(&out->codec_scratch, out->codec_sizes.offset, table_capacity)',
             lambda lib: self.check_layout(1936, 1090, 12, 1, 0x15400, lib)),
            ('metadata-round-wrap',
             'if (metadata_bytes > UINT32_MAX - (FPL_WORKSPACE_ALIGNMENT - 1u))',
             'if (0)', self.test_metadata_rounding_and_total_overflow_are_refused),
        )
        for name, old, new, scenario in mutations:
            with self.subTest(mutation=name):
                self.assertEqual(source.count(old), 1)
                path = Path(self.temp.name) / (name + '.c')
                path.write_text(source.replace(old, new))
                mutant = self.compile(path, name)
                with self.assertRaises(AssertionError):
                    scenario(mutant)


if __name__ == '__main__':
    unittest.main()
