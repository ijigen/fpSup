#!/usr/bin/env python3
"""Build a mode-gated open-gate AutoRun that does NOT corrupt other modes.

Same data patches as build_test_autorun.py (picker slot 7, mode-117 VMAX, the
four FHD/29.97 RWZM cells), but the live FieldAngle canvas hook is replaced with
rowpatch_gated.S, which additionally requires the FieldAngle build **selector r5
== 175** before it rewrites geometry. r5 was measured on hardware (SIGMA fp
Ver.5.02, over the USB shell): 175 for FHD/29.97 CinemaDNG (open gate) and 180
for FHD/25, both of which build a 1936x1090 row — so the stock rowpatch_v4
(dimensions-only) also fired for FHD/25 and stretched it, corrupting it. Gating
on r5 fixes that: other framerates/modes fall through as a no-op.

Reuses build_test_autorun.py's verified helpers; emits AutoRun.txt with the
gated payload at 0xC072F800, an ARMED flag at 0xC072FA10, and the hook armed last.

  ./build_gated_autorun.py --firmware /path/to/MAIN_c0000000.bin
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
SHELL_DIR = REPO / "fp_usb_shell"
SOURCE = HERE / "rowpatch_gated.S"
sys.path.insert(0, str(SHELL_DIR))
sys.path.insert(0, str(HERE))
from armasm import assemble, words  # noqa: E402
import build_test_autorun as og  # noqa: E402

CODE = 0xC072F800
LOG = 0xC072FA00
ARMED = 0xC072FA10
HOOK = 0xC043A19C
HOOK_STOCK = 0xE1A00004
HOOK_BRANCH = 0xEB000000 | ((((CODE - HOOK - 8) >> 2) & 0xFFFFFF))
BANNER = "fpOGgate!"
FIRMWARE_BASE = 0xC0000000


def firmware_word(image, address):
    return struct.unpack_from("<I", image, address - FIRMWARE_BASE)[0]


def verify_firmware(path, blob):
    image = path.read_bytes()
    if (len(image) != og.FIRMWARE_BYTES
            or hashlib.sha256(image).hexdigest() != og.FIRMWARE_SHA256):
        raise SystemExit("reference firmware is not the verified fp Ver.5.02 image")
    for address, stock, _, _ in og.DATA_PATCHES:
        if firmware_word(image, address) != stock:
            raise SystemExit(f"stock mismatch at 0x{address:08X}")
    if firmware_word(image, HOOK) != HOOK_STOCK:
        raise SystemExit("hook site is not the stock mov r0,r4")
    if any(image[CODE - FIRMWARE_BASE: ARMED + 4 - FIRMWARE_BASE]):
        raise SystemExit("cave 0xC072F800..0xC072FA14 is not empty in firmware")
    if CODE + len(blob) > LOG:
        raise SystemExit("gated payload overlaps the telemetry log")


def gated_section(blob):
    lines = [
        "# --- MODE-GATED 3032x2012 open gate @29.97 -------------------------",
        "# fp Ver.5.02 ONLY. Cold-boot RAM patches; remove AutoRun.txt and",
        "# power-cycle (battery out) to return to stock. Hook no-ops unless the",
        "# FieldAngle selector r5 == 175, so other framerates/modes are untouched.",
        "",
    ]
    for address, stock, value, comment in og.DATA_PATCHES:
        lines.append(f"# {comment}; stock 0x{stock:08X}")
        lines.append(f"mem set 0x{address:08X} 0x{value:08X}")
    lines += ["", f"# clear telemetry words at 0x{LOG:08X}"]
    for offset in range(0, 0x10, 4):
        lines.append(f"mem set 0x{LOG + offset:08X} 0x00000000")
    lines += ["", "# arm the feature (controller flag)",
              f"mem set 0x{ARMED:08X} 0x00000001"]
    lines += ["", f"# mode-gated rowpatch, {len(blob)} bytes"]
    for index, value in enumerate(words(blob)):
        lines.append(f"mem set 0x{CODE + index * 4:08X} 0x{value:08X}")
    lines += [
        "",
        "# Arm last: stock instruction is 0xE1A00004 (mov r0,r4).",
        f"mem set 0x{HOOK:08X} 0x{HOOK_BRANCH:08X}",
        "# --- END gated open gate --------------------------------------------",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--firmware", type=pathlib.Path, default=og.DEFAULT_FIRMWARE)
    parser.add_argument("--out", type=pathlib.Path, default=HERE / "AutoRun.gated.txt")
    args = parser.parse_args()
    blob = assemble(SOURCE)
    if words(blob)[-2:] != (0xE1A00004, 0xE12FFF1E):
        raise SystemExit("payload must end with the displaced mov and bx lr")
    verify_firmware(args.firmware, blob)
    with tempfile.TemporaryDirectory() as tmp:
        base_path = pathlib.Path(tmp) / "AutoRun.base.txt"
        result = subprocess.run(
            (sys.executable, str(SHELL_DIR / "build_autorun.py"), "--out", str(base_path),
             "--banner", BANNER, "--no-ep-patches", "--no-pad"), check=False)
        if result.returncode:
            raise SystemExit("canonical shell builder failed")
        base = og.describe_minimal_usb_shell(base_path.read_text(encoding="utf-8"))
    section = gated_section(blob)
    output = og.insert_before_done(base, section)
    if og.parse_mem_sets(output)[-1] != (HOOK, HOOK_BRANCH):
        raise SystemExit("hook must be the final mem set")
    output_bytes = og.pad_bytes(output)
    args.out.write_bytes(output_bytes)
    print(f"built {args.out} ({len(output_bytes)} bytes)  sha256 {hashlib.sha256(output_bytes).hexdigest()}")
    print(f"payload {len(blob)} bytes at 0x{CODE:08X}; ARMED 0x{ARMED:08X}; hook 0x{HOOK_BRANCH:08X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
