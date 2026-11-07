"""Extract firmware segment 1 (load 0xC2EF6E00) from FP__V502.BIN.0.

FP__V502.BIN.0 is the DFI part already split out of FP__V502.BIN; in it the
compressed data is relative to 0x200 (verified: seg0 then reproduces
MAIN_c0000000.bin). Classic Okumura LZSS (N=4096, F=18, r=0xFEE, LSB-first
flags, 1=literal).
"""
import sys

SEG1_OFFSET = 0x200 + 0x1740E00
SEG1_PACKED = 0x1D400
SEG1_SIZE = 0x39A00


def lzss_decompress(packed, out_size):
    ring = bytearray(4096)
    r = 0xFEE
    out = bytearray()
    pos = 0
    flags = 0
    while len(out) < out_size and pos < len(packed):
        flags >>= 1
        if not flags & 0x100:
            flags = packed[pos] | 0xFF00
            pos += 1
            if pos >= len(packed):
                break
        if flags & 1:
            byte = packed[pos]
            pos += 1
            out.append(byte)
            ring[r] = byte
            r = (r + 1) & 0xFFF
        else:
            if pos + 1 >= len(packed):
                break
            b0, b1 = packed[pos], packed[pos + 1]
            pos += 2
            offset = b0 | ((b1 & 0xF0) << 4)
            for k in range((b1 & 0x0F) + 3):
                byte = ring[(offset + k) & 0xFFF]
                out.append(byte)
                ring[r] = byte
                r = (r + 1) & 0xFFF
    return bytes(out[:out_size])


def main(src, dst):
    with open(src, "rb") as fh:
        fh.seek(SEG1_OFFSET)
        packed = fh.read(SEG1_PACKED)
    data = lzss_decompress(packed, SEG1_SIZE)
    if len(data) != SEG1_SIZE:
        raise SystemExit(f"short output: {len(data):#x} of {SEG1_SIZE:#x}")
    with open(dst, "wb") as fh:
        fh.write(data)
    print(f"wrote {dst} ({len(data):#x} bytes)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
