#!/usr/bin/env python3
"""Unpack a SIGMA fp firmware update file into the image the camera runs.

The distributed FP__Vxxx.BIN is a container, not a flat image:

    0x00000000  0x100 bytes of ASCII header
                "LENGTH=24503296 w71c1 VER=V91 DVR=5.02 SUM=... IPL PTBL DAT1"
    0x00000100  @DFI partition table
    0x00000300  MAIN, LZSS-compressed          <- what this script decompresses
    0x0175E500  IPL   (128 KiB, plaintext ARM -- the loader)
    0x0177E600  PTBL  (4 KiB)
    0x0177F700  DAT1  (1028 KiB)

MAIN is Okumura LZSS: 4096-byte ring buffer, F=18, THRESHOLD=2, ring position
starting at N-F (0xFEE), one control byte per 8 items, LSB first, 1=literal and
0=a two-byte match of {12-bit offset, 4-bit length-3}.

The decompressed output loads at 0xC0000000, so

    address = file_offset + 0xC0000000

Verified against the firmware shell's command table: all 77 entries at
0xC0BAC14C resolve to the handler addresses recorded in docs/SHELL_COMMANDS.md
(adc -> 0xC03DBA40, pic -> 0xC0404E98, setting -> 0xC041E330, ...).

Usage:  ./fw_unpack.py FP__V502.bin MAIN_dec.bin
"""
import re
import struct
import sys

BASE = 0xC0000000
MAIN_START = 0x300
N, F, THRESHOLD = 4096, 18, 2


def geometry(data: bytes):
    """MAIN's exact extent, from the @DFI partition table at 0x100.

    Do NOT decompress up to the next section header: there is zero padding
    between the end of the LZSS stream and the IPL header, and the decoder
    happily expands it into ~237 KB of ring-buffer ghost data past the end of
    the image. That garbage looks like real content (mangled strings, plausible
    words) and will send you chasing addresses that do not exist.

        +0x120  uncompressed size
        +0x128  load address
        +0x12C  checksum: plain sum of the compressed bytes
        +0x134  compressed size
        +0x138  zero-init (BSS) size
        +0x140  BSS start == load address + uncompressed size
    """
    unc, load, csum, comp = (struct.unpack_from("<I", data, o)[0]
                             for o in (0x120, 0x128, 0x12C, 0x134))
    return unc, load, csum, comp


def lzss_decompress(src: bytes) -> bytearray:
    ring = bytearray(N)
    r = N - F
    out = bytearray()
    i, n = 0, len(src)
    flags, nbits = 0, 0
    while i < n:
        if nbits == 0:
            flags, nbits = src[i], 8
            i += 1
            if i >= n:
                break
        if flags & 1:
            c = src[i]
            i += 1
            out.append(c)
            ring[r] = c
            r = (r + 1) & (N - 1)
        else:
            if i + 1 >= n:
                break
            b1, b2 = src[i], src[i + 1]
            i += 2
            off = b1 | ((b2 & 0xF0) << 4)
            length = (b2 & 0x0F) + THRESHOLD + 1
            for k in range(length):
                c = ring[(off + k) & (N - 1)]
                out.append(c)
                ring[r] = c
                r = (r + 1) & (N - 1)
        flags >>= 1
        nbits -= 1
    return out


def check(image: bytes) -> bool:
    """The command table must hold 77 {name[0x14], handler} entries."""
    a = 0xC0BAC14C - BASE
    known = {"adc": 0xC03DBA40, "pic": 0xC0404E98, "setting": 0xC041E330}
    count = 0
    for k in range(80):
        e = image[a + k * 0x18 : a + k * 0x18 + 0x18]
        if len(e) < 0x18:
            break
        name = e[:0x14].split(b"\0")[0]
        handler = struct.unpack("<I", e[0x14:])[0]
        if not name or handler == 0:
            break
        want = known.get(name.decode("latin1", "replace"))
        if want and want != handler:
            print("  MISMATCH %s -> 0x%08X, expected 0x%08X" % (name, handler, want))
            return False
        count += 1
    print("  command table: %d entries, known handlers match" % count)
    return count == 77


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    data = open(sys.argv[1], "rb").read()
    if not data.startswith(b"LENGTH="):
        print("not a SIGMA fp update container")
        return 1
    print("header: %s" % data[:68].decode("latin1"))
    unc, load, csum, comp = geometry(data)
    got = sum(data[MAIN_START:MAIN_START + comp]) & 0xFFFFFFFF
    print("DFI: compressed 0x%X, uncompressed 0x%X, load 0x%08X" % (comp, unc, load))
    print("checksum %s (0x%08X)" % ("ok" if got == csum else "MISMATCH", got))
    if got != csum:
        return 1
    image = lzss_decompress(data[MAIN_START:MAIN_START + comp])[:unc]
    print("decompressed %d bytes (0x%X), loads at 0x%08X, ends at 0x%08X"
          % (len(image), len(image), load, load + len(image)))
    ok = check(image)
    open(sys.argv[2], "wb").write(image)
    print("wrote %s" % sys.argv[2])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
