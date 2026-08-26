#!/usr/bin/env python3
"""Extract the 70 IMX410 mode records from SIGMA fp 5.02 firmware."""

from __future__ import annotations

import csv
import re
import struct
from pathlib import Path

ROOT = Path("/Users/dido/Developer.localized/SIGMAfp_re")
FIRMWARE = ROOT / "out/MAIN_c0000000.bin"
DECOMP = ROOT / "out/decomp/full/blk_c03.c"
OUT = Path(__file__).resolve().parent / "analysis_imx410"
TABLE_VA = 0xC0B5FDAC
GEOMETRY_VA = 0xC0B59DC0
TIMING_VA = 0xC0B59500
IMAGE_VA = 0xC0000000
RECORD_SIZE = 0x288
GEOMETRY_SIZE = 0x64
TIMING_SIZE = 0x20
SENSOR_CLOCK_HZ = 72_000_000
MODE_COUNT = 0x46
RAW_BIT_DEPTH = {0: 12, 1: 14, 2: 16, 3: 10, 4: 8}


def parse_writer_map(text: str) -> list[tuple[int, int]]:
    start = text.index("void FUN_c03258c8")
    end = text.index("/* ==== FUN_c0326d88", start)
    body = text[start:end]
    pat = re.compile(
        r"FUN_c0322c70\((0x[0-9a-f]+|\d+),\*\(undefined4 \*\)"
        r"\(\*\(int \*\)\*param_1 \+ iVar1 \* 0x288 \+ (0x[0-9a-f]+|\d+)\)\);"
    )
    pairs = [(int(reg, 0), int(off, 0)) for reg, off in pat.findall(body)]
    if len(pairs) < 100:
        raise RuntimeError(f"writer map unexpectedly short: {len(pairs)}")
    return pairs


def main() -> None:
    OUT.mkdir(exist_ok=True)
    pairs = parse_writer_map(DECOMP.read_text(errors="replace"))
    blob = FIRMWARE.read_bytes()
    base = TABLE_VA - IMAGE_VA
    rows = []
    for index in range(MODE_COUNT):
        rec = blob[base + index * RECORD_SIZE : base + (index + 1) * RECORD_SIZE]
        mode_id = struct.unpack_from("<I", rec, 0)[0]
        values = {reg: struct.unpack_from("<I", rec, off)[0] for reg, off in pairs}
        rows.append((index, mode_id, values))

    geometry = []
    gbase = GEOMETRY_VA - IMAGE_VA
    for index in range(MODE_COUNT):
        g = struct.unpack_from("<25I", blob, gbase + index * GEOMETRY_SIZE)
        geometry.append(g)
        if g[0] != rows[index][1]:
            raise RuntimeError(f"geometry/register mode mismatch at {index}: {g[0]} != {rows[index][1]}")

    timing = []
    tbase = TIMING_VA - IMAGE_VA
    for index in range(MODE_COUNT):
        mode_id, hmax, tail_cycles, vmax = struct.unpack_from("<IHHH", blob, tbase + index * TIMING_SIZE)
        if mode_id != rows[index][1]:
            raise RuntimeError(f"timing/register mode mismatch at {index}: {mode_id} != {rows[index][1]}")
        frame_cycles = hmax * (vmax - 1) + tail_cycles
        fps = SENSOR_CLOCK_HZ / frame_cycles
        width, height = geometry[index][1], geometry[index][2]
        rolling_ms = hmax * height / SENSOR_CLOCK_HZ * 1000
        bit_enum = geometry[index][15]  # metadata +0x3c; returned by FUN_c032c898
        bit_depth = RAW_BIT_DEPTH.get(bit_enum, 0)
        raw_gbps = width * height * fps * bit_depth / 1e9
        timing.append((index, mode_id, hmax, tail_cycles, vmax, frame_cycles, fps,
                       rolling_ms, bit_enum, bit_depth, raw_gbps))

    with (OUT / "imx410_timing.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "mode_id", "hmax_cycles", "tail_cycles", "vmax_lines", "frame_cycles",
                    "exact_fps", "active_readout_ms_est", "raw_bit_enum", "raw_bit_depth", "raw_gbps"])
        w.writerows(timing)

    with (OUT / "imx410_mode_geometry.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "mode_id", *[f"field_0x{x:02x}" for x in range(4, 0x64, 4)]])
        for index, g in enumerate(geometry):
            w.writerow([index, *g])

    regs = [reg for reg, _ in pairs]
    with (OUT / "imx410_modes.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "mode_id", *[f"reg_0x{r:04x}" for r in regs]])
        for index, mode_id, values in rows:
            w.writerow([index, mode_id, *[values[r] for r in regs]])

    varying = []
    for reg in regs:
        vals = [r[2][reg] for r in rows]
        uniq = sorted(set(vals))
        if len(uniq) > 1:
            varying.append((len(uniq), reg, uniq))
    varying.sort(reverse=True)

    with (OUT / "summary.txt").open("w") as f:
        f.write(f"records={len(rows)} record_size=0x{RECORD_SIZE:x} mapped_registers={len(regs)}\n")
        f.write("mode_ids=" + ",".join(str(r[1]) for r in rows) + "\n")
        f.write(f"unique_mode_ids={len(set(r[1] for r in rows))}\n")
        f.write(f"varying_registers={len(varying)} constant_registers={len(regs)-len(varying)}\n\n")
        f.write(f"timing_clock_hz={SENSOR_CLOCK_HZ}\n")
        families = {}
        for g in geometry:
            # Three width/height pairs are stored at +04/+08, +14/+18 and +24/+28.
            # The final crop and its margins follow at +2c..+38.
            key = (g[1], g[2], g[5], g[6], g[9], g[10], g[11], g[12], g[13], g[14])
            families.setdefault(key, []).append(g[0])
        f.write(f"geometry_families={len(families)}\n")
        for key, ids in families.items():
            f.write(
                "geometry "
                f"sensor={key[0]}x{key[1]} stage2={key[2]}x{key[3]} "
                f"output={key[4]}x{key[5]} crop={key[6]}x{key[7]} "
                f"margin={key[8]},{key[9]} modes=" + ",".join(map(str, ids)) + "\n"
            )
        f.write("\n")
        f.write("registers ranked by number of distinct values:\n")
        for count, reg, uniq in varying:
            shown = ",".join(f"0x{x:x}" for x in uniq[:16])
            if len(uniq) > 16:
                shown += ",..."
            f.write(f"reg 0x{reg:04x}: {count:2d} values [{shown}]\n")

        f.write("\nmode fingerprints (varying registers only):\n")
        for index, mode_id, values in rows:
            fp = " ".join(f"{reg:04x}={values[reg]:x}" for _, reg, _ in varying)
            f.write(f"index={index:02d} id={mode_id:3d} {fp}\n")

    print((OUT / "summary.txt").read_text())


if __name__ == "__main__":
    main()
