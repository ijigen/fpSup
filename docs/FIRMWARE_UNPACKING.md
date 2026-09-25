# Unpacking the firmware update file

The distributed `FP__V502.bin` is a container and its main payload is compressed,
so grepping the download finds nothing — not even a string as common as
`AutoRun`. This is how to get the image the camera actually runs.

Derived 2026-09-08 against `FP__V502.bin`,
sha256 `c9fa76f32f523bb2dc9a3fbda39418c31573cab6a1aa5c56d28c371862066ed8`.

---

## Container layout

```
0x00000000  0x100 bytes of ASCII header
            "LENGTH=24503296 w71c1 VER=V91 DVR=5.02 SUM=2768501654 IPL PTBL DAT1"
0x00000100  @DFI partition table
0x00000300  MAIN, LZSS-compressed
0x0175E500  IPL   131072 bytes, plaintext ARM -- the loader
0x0177E600  PTBL    4096 bytes
0x0177F700  DAT1  1052672 bytes
```

`DVR=5.02` in the header is the firmware version. Each trailing section carries
its own `NAME LENGTH=... VER=... SUM=...` header in the same ASCII form.

The IPL is not compressed. It is ARM code with its build string intact —
`PureNAND IPL xz01-v0.7.r255715 (Misato) [DEBUG BUILD] (Jun 19 2019 15:29:49)` —
and it holds the loader messages (`LoadData[ %2d ] addr = 0x%08x`,
`Invalid Firmware?`). It is the natural place to read how MAIN is loaded.

## MAIN is Okumura LZSS

Classic LZSS, no header of its own:

```
ring buffer     4096 bytes
F               18
THRESHOLD       2
initial r       N - F = 0xFEE
control byte    one per 8 items, LSB first, 1 = literal, 0 = match
match           two bytes -> offset = b1 | ((b2 & 0xF0) << 4)
                             length = (b2 & 0x0F) + 3
```

It is recognisable by eye from the ARM reset vector table leaking through as
literals at `0x300`: `ff 18 f0 9f e5 18 f0 9f e5 ef ...` is a control byte of
`0xff` (eight literals) followed by `E59FF018` twice — `ldr pc, [pc, #0x18]`.
The first match is offset `0xFEE`, length 8, which back-references the ring
start to emit two more vector entries.

Decompressed size is **49,483,317 bytes** (`0x2F30E35`).

## Where MAIN ends — get this right

**Do not decompress up to the next section header.** There is zero padding
between the end of the LZSS stream and the `IPL` header, and the decoder happily
expands it into about **237 KB of ring-buffer ghost data past the end of the
image**. That garbage is not obviously garbage: it contains mangled but
recognisable strings (a garbled newlib `strerror` table, `test data test data`)
and plausible-looking words. It will send you chasing addresses that do not
exist — it cost a wrong conclusion here, see [color sup](../projects/color-sup.md).

The `@DFI` partition table at `0x100` gives the exact geometry:

```
+0x120  uncompressed size            0x02EF6E00 for V502
+0x128  load address                 0xC0000000
+0x12C  checksum: plain sum of the compressed bytes
+0x134  compressed size              0x01740E00
+0x138  zero-init (BSS) size         0x00039A00
+0x140  BSS start = load + uncompressed size
```

So for V502 the real image is **`0xC0000000 .. 0xC2EF6E00`**, 49,245,696 bytes,
and anything at or above `0xC2EF6E00` is either BSS (not in the file at all) or
decoder overrun. The checksum is verifiable before you trust anything:

```
sum(data[0x300 : 0x300 + comp]) & 0xFFFFFFFF == checksum
```

`fw_unpack.py` reads the geometry, checks the sum, and truncates to the declared
size. A second section table at `0xC0725D40` corroborates it — 12-byte records
of `{addr, addr + 0x58000200, size}` giving `.text` at `0xC0000400`, data at
`0xC0725DE0`, and BSS at `0xC2EF6E00`.

## The address mapping, and how to check it

```
address = file_offset + 0xC0000000
```

Do not take this on trust — it is checkable. The firmware shell's command table
sits at `0xC0BAC14C` as 77 entries of `{ char name[0x14]; void *handler; }` at
stride `0x18`. Parse it and compare against [SHELL_COMMANDS.md](SHELL_COMMANDS.md):

```
adc     -> 0xC03DBA40
adj     -> 0xC03DC1A0
mem     -> 0xC03FA2A8
menu    -> 0xC0402F98
pic     -> 0xC0404E98
setting -> 0xC041E330
```

All 77 resolve. If they do not, the mapping is wrong and nothing built on it can
be trusted.

The mapping is verified as far as `0xC0CF3740` (the USB descriptors patched by
[fp USB Shell](../fp_usb_shell/)). Beyond roughly `0xC0D00000` the image
continues into data — vtables and initialised data appear around `0xC2E3xxxx` —
but code analysis should stay below `0xC0D00000` unless separately confirmed.

## Tooling

The unpacker is [`firmware/fw_unpack.py`](../firmware/fw_unpack.py). It
decompresses and then runs the command-table check, and exits non-zero if the
check fails:

```sh
./firmware/fw_unpack.py FP__V502.bin MAIN_dec.bin
```

The check knows Ver 5.02's command table. On an older container the
decompressed image is still written, but the check reports a mismatch and the
exit code is 1.

For analysis, radare2 needs the map or it disassembles garbage:

```sh
r2 -a arm -b 32 -m 0xC0000000 MAIN_dec.bin
```

`-B 0xC0000000` does **not** work for a raw image; use `-m`.

Parts of the firmware are Thumb, reached by `BLX` with an immediate. A
call-graph index that only decodes `BL` will silently miss them — over the code
region there are 183,444 `BL` edges and 12,901 `BLX` edges.

## Keep the blob out of the repository

`.gitignore` does not cover `*.BIN`, and eight `.BIN` files are tracked here.
This repository is public. Keep `FP__V502.bin` and the decompressed image
outside the working tree.
