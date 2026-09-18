"""Assemble the experimental OG4K core for offline inspection only.

No transport, hook patch list, AutoRun, VSHL, or camera install action exists.
The firmware binding and pipeline quiescence adapter are still outstanding.
"""
from __future__ import annotations

import hashlib
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parents[1]
ROOT = FPSUP.parent
sys.path.insert(0, str(FPSUP / "fp_usb_shell"))
import armasm

SOURCE = HERE / "core.S"
FIRMWARE = ROOT / "out" / "MAIN_c0000000.bin"
FIRMWARE_SHA256 = "92a8ee993f6c3d66c251e88d45a2ccd5135c6cf7342717784321c2ed506e2fb4"
MAGIC = 0x4B34474F
BASE = 0xC0000000
RECORD_REQUEST = (MAGIC, 1, 429, 151, 24, 1, 12, 0, 1)
PLAYBACK_FRAME = (MAGIC, 1, 12, 4016, 2676, 8, 5, 4000, 2666, 16_120_232)


def build():
    blob = armasm.assemble(SOURCE)
    symbols = armasm.symbols(SOURCE)
    if len(blob) > 4096:
        raise ValueError("experimental core exceeds its emulator code page")
    for name in ("transition", "record_canvas", "playback_canvas"):
        if name not in symbols or symbols[name] % 4:
            raise ValueError(f"missing or misaligned entry: {name}")
    return blob, symbols


def load_firmware():
    image = FIRMWARE.read_bytes()
    if hashlib.sha256(image).hexdigest() != FIRMWARE_SHA256:
        raise ValueError("firmware is not the pinned V5.02 image")
    return image


def table(blob, symbols, name, count, fields):
    words = struct.unpack_from(f"<{count * fields}I", blob, symbols[name])
    return tuple(tuple(words[i:i + fields]) for i in range(0, len(words), fields))


def main():
    image = load_firmware()
    blob, symbols = build()
    frontend = table(blob, symbols, "frontend", 10, 3)
    for address, stock, _ in frontend:
        if struct.unpack_from("<I", image, address - BASE)[0] != stock:
            raise ValueError(f"frontend stock mismatch at {address:#x}")
    print(f"OG4K offline core: {len(blob)} bytes, sha256 {hashlib.sha256(blob).hexdigest()}")
    for name in ("transition", "record_canvas", "playback_canvas"):
        print(f"  {name}: +0x{symbols[name]:04x}")
    print("Camera deployment: unavailable; firmware adapter and recording allocation proof pending.")


if __name__ == "__main__":
    main()
