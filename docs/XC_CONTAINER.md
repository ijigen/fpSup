# The XC container

The firmware carries a flat run of `XC` blocks. Each block is one greyscale
bitmap. Together they are the camera's on-screen artwork: every menu label,
every digit, every icon, every bar.

Derived 2026-09-09 against `FP__V203_dec.bin` and `MAIN_dec.bin` (Ver 5.02),
both from [FIRMWARE_UNPACKING.md](FIRMWARE_UNPACKING.md).

Tool: [`firmware/xc_decode.py`](../firmware/xc_decode.py). It needs no
third-party modules.

```
xc_decode.py list FP__V203_dec.bin --group 43
xc_decode.py dump FP__V203_dec.bin out/ --group 43
```

The name matches the card path `\dump.xci` that the firmware already knows.

---

## Where it is

The blocks are concatenated with no index and no directory. To find them,
search for the first 4-byte-aligned `XC\0\0` that has `0x0400` at `+0x0C`.
Then walk block by block.

| version | first block | blocks | payload |
|---|---|---|---|
| 2.03 | `0xC0DA9EB0` | 1507 | raw |
| 3.00 | `0xC119CFDC` | 1977 | packed |
| 4.00 | `0xC11C9D10` | 2001 | packed |
| 5.02 | `0xC1240014` | 2005 | packed |

## Block header

```
+0x00  "XC\0\0"
+0x04  u32 payload size    block total = 0x20 + size, rounded up to 4
+0x08  u16 width           bitmap width in pixels
+0x0A  u16 height          bitmap height in pixels
+0x0C  u16 0x0400
+0x10  u16 version         0x0101 = raw, 0x0202 = packed
+0x20  payload
```

The two fields at `+0x08` and `+0x0A` are the width and the height. Blocks of
the same height sit together, because the artwork is grouped by row size.

## Raw payload (version 0x0101)

```
u8   format, always 0x01
     records
u8   trailer
```

A record is:

```
u8        run
u8        count - 1
u16[count] little-endian samples
```

Decode a record like this. First write the `count` samples. Then write the last
sample `run - 1` more times. The samples are 16-bit greyscale, `0x0000` is
black and `0xFFFF` is white.

The encoder stops as soon as the rest of the image is flat. Pad the tail with
the last sample until the pixel count is `width * height`. Rows run from top to
bottom and from left to right.

Ver 2.03 holds 1478 raw blocks. The proof that this reading is correct:

- The record walk ends exactly one byte before the payload end in 1476 blocks.
  The other 2 blocks carry format byte `0x03`, which is a different layout.
- The decoded pixel count is never more than `width * height` in 1472 of 1474
  blocks. The 2 exceptions are the same pair.
- The last two samples of a record are always equal. This holds for 484,654 of
  484,663 records.

The last-two-equal rule is what makes the format work. A run repeats the final
sample, so the encoder always writes that sample twice.

### Sample precision

Most blocks carry true 16-bit samples. The text labels do not. In every one of
the 22,000 samples of the colour-mode labels, the 16-bit value is an 8-bit
value that was expanded:

```
v16 = (v8 << 8) | (v8 & 0x0F) * 0x11
```

This is a property of that artwork, not a rule of the format. Do not decode on
it. It is useful only as a check that the record framing is right.

## Packed payload (version 0x0202)

Ver 3.00 and later pack every block. This is not decoded yet.

```
+0x00  04 22 4D 18     the LZ4 frame magic
+0x04  u16 0x1088
+0x06  u32 size - 4
+0x0A  five zero bytes
+0x0F  u32 size - 23
+0x13  u16             0x1F in normal blocks, less in very small ones
+0x15  u16 0x0001
+0x17  stream, size - 23 bytes, and it ends with 00 00 00 00
```

The magic is the only LZ4 part. Two results say so:

- A search over the start offset, the token nibble order, the minimum match
  length, the offset width and the offset endianness never reproduced more than
  2 correct bytes.
- The `STD.` label is 100 x 43 pixels in Ver 2.03 and in Ver 5.02, so the
  artwork did not change. But only 163 of the 2401 stream bytes in the Ver 5.02
  block appear anywhere in the Ver 2.03 payload.

A byte-aligned LZ77 over the same bytes would leave far more literals. The
codec is most likely bit-packed.

The smallest packed blocks are the best place to start. A 6 x 1 blank is 27
bytes and its whole stream is `00 00 00 00`. A 12 x 1 blank is 28 bytes and its
stream is `04 00 00 00 00`.
