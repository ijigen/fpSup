#!/usr/bin/env python3
"""Offline model of exact-base packed RAW14 horizontal contraction.

No USB, camera, firmware imports, ARM execution or deployment. This proves
sample arithmetic, native BUFA word order and forward in-place scheduling in
a scalar model. It is not an optimized implementation or a speed measurement.
The existing h2_neon_offline u16 routine keeps its disjoint-buffer contract.

Run: python3 -B projects/sensorlab-imx410/tools/rwzm14/prove_packed_h14_inplace.py

Native source: imx410-lab/decode14.py / FUN_c031e800: MSB-first samples
inside little-endian 32-bit words, NOT MIPI RAW14. msb_bytes is the separate
byte stream used by the RMIX endian1 fixtures. Both formats are checked.
"""

import json
import random
import struct


def ref_pack(values, layout):
    """Independent reference: concatenate bits; reverse each physical word."""
    bits = ''.join(format(v, '014b') for v in values)
    assert len(bits) % 32 == 0
    raw = int(bits, 2).to_bytes(len(bits) // 8, 'big')
    if layout == 'native_words':
        raw = b''.join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    return raw


def ref_unpack(raw, layout):
    if layout == 'native_words':
        raw = b''.join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    bits = ''.join(format(b, '08b') for b in raw)
    assert len(bits) % 14 == 0
    return [int(bits[i:i + 14], 2) for i in range(0, len(bits), 14)]


def tile_unpack(raw, layout):
    """Word-based implementation, independent of the reference bit string."""
    order = '<' if layout == 'native_words' else '>'
    words = struct.unpack(order + str(len(raw) // 4) + 'I', raw)
    out = []
    for pixel in range(len(raw) * 8 // 14):
        word, used = divmod(pixel * 14, 32)
        if used <= 18:
            value = words[word] >> (18 - used)
        else:
            tail = used - 18
            value = (words[word] << tail) | (words[word + 1] >> (32 - tail))
        out.append(value & 16383)
    return out


def tile_pack(values, layout):
    words = [0] * (len(values) * 14 // 32)
    for pixel, value in enumerate(values):
        word, used = divmod(pixel * 14, 32)
        if used <= 18:
            words[word] |= value << (18 - used)
        else:
            tail = used - 18
            words[word] |= value >> tail
            words[word + 1] |= (value << (32 - tail)) & 0xffffffff
    order = '<' if layout == 'native_words' else '>'
    return struct.pack(order + str(len(words)) + 'I', *words)


def contract(buf, base, width, height, factor, src_stride, dst_stride,
             src_layout, dst_layout, quantize_mutant=False):
    """Exact same base only; a tile is fully loaded before its first store.

    Assumes a completed, exclusively owned frame. This function models
    neither a concurrent producer/consumer nor DMA/cache ownership.
    """
    tile_pixels = factor * 16
    tile_in, tile_out = tile_pixels * 7 // 4, 28
    assert factor in (2, 3) and width % tile_pixels == 0
    assert width * 7 // (4 * factor) <= dst_stride <= src_stride
    assert src_stride >= width * 7 // 4
    for row in range(height):
        for offset in range(0, width, tile_pixels):
            source = base + row * src_stride + offset * 7 // 4
            dest = base + row * dst_stride + offset * 7 // (4 * factor)
            assert dest <= source and dest + tile_out <= source + tile_in
            values = tile_unpack(bytes(buf[source:source + tile_in]), src_layout)
            means = []
            for first in range(0, tile_pixels, 2 * factor):
                for phase in (0, 1):
                    samples = values[first + phase:first + 2 * factor:2]
                    if quantize_mutant:
                        samples = [v & ~3 for v in samples]
                    if factor == 2:
                        mean = (samples[0] + samples[1] + 1) >> 1
                    else:
                        mean = ((sum(samples) + 1) * 43691) >> 17
                    means.append(mean)
            buf[dest:dest + tile_out] = tile_pack(means, dst_layout)


def run_case(width, height, factor, pattern, src_layout, dst_layout, padded):
    rng = random.Random(140230 + width + height)
    n = width * height
    if pattern == 'flat0':
        data = [0] * n
    elif pattern == 'flat16383':
        data = [16383] * n
    elif pattern == 'flat101':
        data = [101] * n
    elif pattern == 'impulse':
        data = [16383 if i % width == (i // width * 17) % width else 0
                for i in range(n)]
    elif pattern == 'ceiling':
        data = [16380 + i % 4 for i in range(n)]
    elif pattern == 'cfa':
        data = [(1024, 4097, 8194, 12291)[((i // width) % 2) * 2 + i % 2]
                for i in range(n)]
    elif pattern == 'ramp':
        data = [(i * 37 + 3) % 16384 for i in range(n)]
    else:
        data = [rng.randrange(16384) for _ in range(n)]
    src_stride = width * 7 // 4 + (12 if padded else 0)
    out_bytes = width * 7 // (4 * factor)
    # Test dense cross-row compaction and preservation of the original pitch.
    for dst_stride in (out_bytes, src_stride):
        raw = bytearray([0xa5] * (64 + src_stride * height + 64))
        expected = []
        for y in range(height):
            row = data[y * width:(y + 1) * width]
            packed = ref_pack(row, src_layout)
            raw[64 + y * src_stride:64 + y * src_stride + len(packed)] = packed
            means = []
            for x in range(0, width, factor * 2):
                for phase in (0, 1):
                    means.append((sum(row[x + phase:x + factor * 2:2])
                                  + factor // 2) // factor)
            expected.append(means)
        before = bytes(raw)
        contract(raw, 64, width, height, factor, src_stride, dst_stride,
                 src_layout, dst_layout)
        written = set()
        for y in range(height):
            start = 64 + y * dst_stride
            assert ref_unpack(raw[start:start + out_bytes], dst_layout) == expected[y]
            written.update(range(start, start + out_bytes))
        assert all(a == b for i, (a, b) in enumerate(zip(raw, before)) if i not in written)


def main():
    # Every possible 3-sample RAW14 sum, including 16383+16383+16383.
    assert all(((s + 1) * 43691) >> 17 == (s + 1) // 3 for s in range(49150))
    cases = 0
    for factor, widths in ((2, (32, 64, 96, 192, 6048)),
                           (3, (48, 96, 144, 192, 6048))):
        for width in widths:
            for height in (1, 2, 7):
                for pattern in ('flat0', 'flat101', 'flat16383', 'impulse',
                                'ceiling', 'cfa', 'ramp', 'random'):
                    for src in ('native_words', 'msb_bytes'):
                        for dst in ('native_words', 'msb_bytes'):
                            for padded in (False, True):
                                run_case(width, height, factor, pattern, src, dst, padded)
                                cases += 2
    # Deliberately drop the low bits: the controlled input must detect it.
    mutation_caught = []
    for factor in (2, 3):
        values = [101] * (16 * factor)
        packed = ref_pack(values, 'native_words')
        buf = bytearray(packed)
        contract(buf, 0, len(values), 1, factor, len(buf), 28,
                 'native_words', 'native_words', quantize_mutant=True)
        mutation_caught.append(ref_unpack(buf[:28], 'native_words') != [101] * 16)
    assert all(mutation_caught)
    print(json.dumps({
        'status': 'PASS_SCALAR_MODEL_ONLY', 'frame_cases': cases,
        'h3_sum_values_checked': 49150, 'drop_low2_mutants_caught': len(mutation_caught),
        'source_layouts': ['BUFA_MSB_in_LE32', 'RMIX_endian1_MSB_bytes'],
        'camera_operations': 0, 'arm_execution': False, 'throughput_measured': False,
        'limits': 'Exclusive completed frame; exact-base forward contraction only; '
                  'not an optimized kernel, firmware integration or DMA/cache proof.'
    }, indent=2))


if __name__ == '__main__':
    main()
