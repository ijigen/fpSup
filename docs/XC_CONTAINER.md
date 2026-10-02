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
| 2.03 | `0xC0DA9EB0` | 1507 | 1478 raw (`0x0101`), 29 `0x0102` |
| 3.00 | `0xC119CFDC` | 1977 | packed |
| 4.00 | `0xC11C9D10` | 2001 | packed |
| 5.02 | `0xC1240014` | 2005 | packed |

**There are three version values, not two.** Ver 2.03 carries 29 blocks marked
`0x0102` beside its 1478 `0x0101` blocks. An earlier version of this file listed
only `0x0101` and `0x0202`, and `xc_decode.py` counted anything that was not
`0x0202` as raw, so it reported "0 packed" while labelling those 29 as packed in
the same listing. `0x0102` is not decoded.

Only Ver 2.03 and earlier can be extracted at all. On Ver 3.00 and later every
block is packed, so `dump` writes nothing.

## Block header

```
+0x00  "XC\0\0"
+0x04  u32 payload size    block total = 0x20 + size, rounded up to 4
+0x08  u16 width           bitmap width in pixels
+0x0A  u16 height          bitmap height in pixels
+0x0C  u16 0x0400
+0x10  u16 version         0x0101 raw, 0x0102 raw variant, 0x0202 packed
+0x20  payload
```

The two fields at `+0x08` and `+0x0A` are the width and the height. Blocks of
the same height sit together, because the artwork is grouped by row size.

## Raw payload (version 0x0101)

```
u8   format, always 0x01
     records
u8   final run
```

A record is:

```
u8        run
u8        count - 1
u16[count] little-endian samples
```

Decode a record like this. **First repeat the previous pixel `run - 1` more
times. Then write the `count` samples.** The run extends what came before it; it
does not repeat what follows. The samples are 16-bit greyscale, `0x0000` is black
and `0xFFFF` is white. Rows run from top to bottom and from left to right.

**The run comes before the literals, and getting that backwards is invisible to a
count.** Two earlier versions of this file said the literals come first and the
last sample then repeats. That produces the identical number of pixels, so it
passed every check anyone had written, while putting every run on the wrong side
of its literals. The damage accumulates along the row: each glyph is dragged
right by the length of the run that should have preceded it, which reads as a
horizontal smear that grows down the image.

It was twice mistaken for something else — once for a viewer mishandling 16-bit
PNG, and once for an italic typeface, because the constant leftward creep of the
glyph edges looks like a slant. The lettering is upright.

The test that separates the two orderings is not a pixel count, because they
agree. It is whether the image is as smooth down as it is across. Over 260
blocks, the mean ratio of vertical to horizontal gradient is **1.06** with the
run first, and **2.40** with the literals first. Real artwork sits near 1.

**The last byte is a run length, not a trailer.** An earlier version of this file
called it a trailer, and said to pad the tail with the last sample until the
pixel count reaches `width * height`. That produces the right pixels, because the
byte *is* exactly that padding count, but it described the field wrongly and it
turned any decode error into a silently plausible image. Read it:

```
final run == width * height - (pixels produced by the records)
```

This holds in **1470 of the 1474** Ver 2.03 blocks whose record walk terminates
cleanly. It is the check the earlier verification lacked.

### How this was got wrong, and how to test it properly

The earlier verification was three claims, and none of them could fail in a way
that mattered:

- "The record walk ends exactly one byte before the payload end in 1476 blocks."
  True, and it does establish the record framing. It says nothing about what that
  byte means.
- "The decoded pixel count is never more than `width * height` in 1472 of 1474
  blocks." An upper bound. The decode is systematically **short** — not one block
  of 1476 reaches `width * height` from its records alone, and the median reaches
  0.970 of it — and an upper bound cannot see that.
- "The last two samples of a record are always equal." True for 484,654 of
  484,663 records, and it does support the run reading.

The test that settles it is equality, not a bound: the records plus the final run
byte must come to exactly `width * height`. That is now in `xc_decode.py` as
`decode(..., strict=True)`, and `dump` reports any block that fails it.

One caution for anyone reading the output: the blocks are written as 16-bit
greyscale PNG, which some viewers and libraries mishandle. Converting with a
truncating 16-to-8 path makes clean output look doubled. Shift right by 8
instead.

### Sample values

57.22 percent of samples are a 4-bit level replicated into all four nibbles, such
as `0x3333` or `0xBBBB`, and 667 of the 1475 readable blocks are made only of
those. The rest carry finer values, so the container is genuinely 16-bit and must
not be decoded as 4-bit or 8-bit.

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

## Blocks that do not decode

Eight of the 1478 Ver 2.03 raw blocks fail. They are listed so nobody re-derives
them:

| address | size | what is wrong |
|---|---|---|
| `0xC0EFA790` | 75 x 35 | format byte `0x03`, a layout this file does not describe |
| `0xC0EFB914` | 78 x 35 | the same |
| `0xC0E38E04` | 82 x 45 | walk stops 3 bytes early; final run byte 0 where 256 pixels are missing |
| `0xC0F6F3E4` | 324 x 14 | records overrun by 166 pixels |
| `0xC0F70E98` | 244 x 14 | the same, and the two payloads share a head and a tail |
| `0xC10DB0D4` | 251 x 271 | payload is the six-byte group `01 55 95 55 95 ff` repeated |
| `0xC10E055C` | 251 x 251 | the same shape, group `01 00 f0 00 f0 ff` |
| `0xC11C2044` | 40 x 40 | group `01 ff ff ff ff ff` repeated; the walk produces no pixels and the image comes out blank |

The last three share a six-byte repeating structure that the `(run, count-1)`
framing does not fit, so they are probably a fourth layout rather than corrupt.
