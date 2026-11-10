#!/usr/bin/env python3
"""Read-only audit of archived first-frame traces and DNGs; no camera imports.

Run with projects/cdng-image/.venv/bin/python -B <this file>.
Only output is report.json alongside this script. Original artifacts stay unchanged.
"""
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path

import numpy as np
import tifffile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
V = HERE.parent
SETS = ("20261104-first-frame-trace", "20261104-first-frame-resync", "20261104-first-frame-resync2")
REGS = {"0x0000", "0x00C5", "0x00C6", "0x00CA"}
EXPECTED_RESYNC = [("0x00CA", "0x00"), ("0x0000", "0x02"), ("0x00C6", "0x01"),
                   ("0x00C5", "0x11"), ("0x0000", "0x00"), ("0x00C6", "0x00"),
                   ("0x00C5", "0x00"), ("0x00CA", "0x01")]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path):
    return str(path.relative_to(ROOT))


def sentinel(seed):
    x, out = seed, []
    for _ in range(16):
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        out.append(x)
    return out


def sample_bytes(rec):
    return [struct.pack("<8I", *rec[14:22]), struct.pack("<16I", *rec[22:38]),
            struct.pack("<8I", *rec[38:46]), struct.pack("<8I", *rec[46:54])]


def tick(rec):
    return (rec[2] * 1000000 + rec[3] // 12) & 0xFFFFFFFF


def decode_record(rec, sent):
    return dict(kind={1: "arm", 2: "done", 3: "write"}[rec[0]], seq=rec[1],
                epoch=rec[2], raw_timer=rec[3], native_task_us=rec[4], approximate_us=tick(rec),
                tg_588_raw=hex(rec[5]), tg_588_low11=rec[5] & 0x7FF,
                tg_590_raw=hex(rec[6]), tg_line_native=(rec[6] >> 16) & 0x3FFF,
                tg_590_low16=rec[6] & 0xFFFF, tg_58c_raw=hex(rec[7]),
                raster=hex(rec[8]), samples_valid=rec[13] == 1,
                row0_tail64_is_sentinel=rec[13] == 1 and rec[22:38] == sent)


def dng_pair(path):
    files = [next(path.glob("*_000001.DNG")), next(path.glob("*_000002.DNG"))]
    a, b = (tifffile.imread(p)[200:-200, 200:-200].astype(np.float32) for p in files)
    h, w = a.shape
    assert a.shape == b.shape
    errors = {}
    for dy in range(-3, 4):
        for dx in range(-2, 3):
            aa = a[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)]
            bb = b[max(-dy, 0):h - max(dy, 0), max(-dx, 0):w - max(dx, 0)]
            errors[(dy, dx)] = float(np.abs(aa - bb).mean())
    dy, dx = min(errors, key=errors.get)
    old = json.loads((path / "result.json").read_text())
    with tifffile.TiffFile(files[0]) as tf:
        page = tf.pages[0]
        assert len(page.dataoffsets) == len(page.databytecounts) == 1
        offset = int(page.tags["StripOffsets"].value[0])
        strip_bytes = int(page.tags["StripByteCounts"].value[0])
        bits = int(page.tags["BitsPerSample"].value)
        width, height = int(page.imagewidth), int(page.imagelength)
        compression = int(page.tags["Compression"].value)
    assert compression == 1
    row = width * bits // 8
    raw = files[0].read_bytes()
    assert width * bits % 8 == 0 and row >= 64 and height >= 2
    assert strip_bytes >= row * height and offset + strip_bytes <= len(raw)
    assert 0 <= offset < offset + row * height <= len(raw)
    regions = [raw[offset:offset + 32], raw[offset + row - 64:offset + row],
               raw[offset + row:offset + row + 32], raw[offset + row * height - 32:offset + row * height]]
    return dict(take=path.name, clip=old["clip"], files=[dict(path=rel(p), sha256=sha(p)) for p in files],
                width=width, rows=height, bits=bits, compression=compression, strip_offset=offset, row_bytes=row,
                dy=dy, dx=dx, mae=errors[(dy, dx)], mae_zero=errors[(0, 0)],
                matches_saved_shift=(dy == old["dy"] and dx == old["dx"])), regions


def main():
    groups = []
    totals = Counter()
    for name in SETS:
        base = V / name
        trace_path = base / "RUN/trace.jsonl"
        traces = [json.loads(line) for line in trace_path.read_text().splitlines() if line]
        trace_by_take = {t["tag"].split("-")[0]: t for t in traces}
        entries, counts = [], Counter()
        for path in sorted((base / "bus").glob("t*")):
            pair, dng_regions = dng_pair(path)
            counts["dng_pairs"] += 1
            counts["shifted_dng_first_frames"] += pair["dy"] == 1
            counts["saved_dng_labels_match"] += pair["matches_saved_shift"]
            bus_path = path / "bus.json"
            bus = json.loads(bus_path.read_text())
            start = next(i for i, e in enumerate(bus) if e["reg"] == "0x0011" and e["val"] == "0x01")
            restart = bus[start]["t"]
            sequence = [dict(dt_us=(e["t"] - restart) & 0xFFFFFFFF, reg=e["reg"], val=e["val"], lr=e["lr"])
                        for e in bus[start + 1:] if ((e["t"] - restart) & 0xFFFFFFFF) < 300000 and e["reg"] in REGS]
            pair["bus"] = dict(path=rel(bus_path), sha256=sha(bus_path), first_0011_one_us=restart,
                               resync_writes_first_300ms=sequence,
                               exact_resync_sensor_write_sequence=[(e["reg"], e["val"]) for e in sequence] == EXPECTED_RESYNC)
            counts["exact_resync_sensor_sequences"] += pair["bus"]["exact_resync_sensor_write_sequence"]
            if path.name not in trace_by_take:
                pair["trace"] = None
                entries.append(pair)
                continue
            tr = trace_by_take[path.name]
            words = tr["words"]
            assert words[:4] == [0x52544653, 1, 56, 12] and words[5] == 0
            assert words[9] == pair["row_bytes"] and words[10] == pair["rows"]
            recs = [words[16 + i * 56:16 + (i + 1) * 56] for i in range(words[4])]
            arms, done, writes = ([r for r in recs if r[0] == k] for k in (1, 2, 3))
            assert len(arms) == 1 and len(done) == len(writes) == 4
            assert [r[0] for r in recs] == [1, 2, 3, 2, 3, 2, 3, 2, 3]
            sent = sentinel(words[8])
            matches = []
            for d, w in zip(done, writes):
                same_ras = (d[8] & 0x3FFFFFFF) == (w[8] & 0x3FFFFFFF)
                same_bytes = sample_bytes(d) == sample_bytes(w)
                matches.append(dict(same_raster=same_ras, same_160_sample_bytes=same_bytes,
                                    completion_to_writer_us=(tick(w) - tick(d)) & 0xFFFFFFFF))
                counts["done_write_pairs"] += 1
                counts["done_write_raster_equal"] += same_ras
                counts["done_write_samples_equal"] += same_bytes
                counts["done_write_valid_samples"] += d[13] == w[13] == 1
                counts["live_r2280_equals_same_callback"] += ((d[10] << 2) & 0x3FFFFFFF) == (d[8] & 0x3FFFFFFF)
            next_matches = [((a[10] << 2) & 0x3FFFFFFF) == (b[8] & 0x3FFFFFFF) for a, b in zip(done, done[1:])]
            counts["adjacent_done_pairs"] += len(next_matches)
            counts["live_r2280_equals_next_callback"] += sum(next_matches)
            first_sentinel = done[0][22:38] == sent
            sample_match = dng_regions == sample_bytes(done[0])
            pair["trace"] = dict(archived_tag=tr["tag"], header=tr["header"],
                                 records=[decode_record(r, sent) for r in recs], done_write_matches=matches,
                                 first_done_samples_equal_dng_regions=dict(zip(
                                     ["row0_head32", "row0_tail64", "row1_head32", "last_row_tail32"],
                                     [a == b for a, b in zip(dng_regions, sample_bytes(done[0]))])),
                                 first_sentinel_matches_dng_shift=first_sentinel == (pair["dy"] == 1),
                                 first_arm_raster_equals_done=arms[0][8] == done[0][8],
                                 r2280_live_destinations=[hex(((d[10] << 2) + 0x40000000) & 0xFFFFFFFF) for d in done],
                                 live_r2280_equals_next_done_callback=next_matches,
                                 arm_to_first_done_approx_us=(tick(done[0]) - tick(arms[0])) & 0xFFFFFFFF,
                                 first_0011_to_arm_same_native_clock_us=(arms[0][4] - restart) & 0xFFFFFFFF,
                                 arm_native_minus_approx_us=(arms[0][4] - tick(arms[0])) & 0xFFFFFFFF)
            counts["traced_takes"] += 1
            counts["shifted_traced_first_frames"] += first_sentinel
            counts["first_done_four_regions_equal_dng"] += sample_match
            counts["sentinel_matches_dng_shift"] += first_sentinel == (pair["dy"] == 1)
            entries.append(pair)
        totals.update(counts)
        groups.append(dict(dataset=name, trace_file=rel(trace_path), trace_sha256=sha(trace_path),
                           counts=dict(counts), takes=entries))
    report = dict(scope="offline archived trace and DNG audit; no camera access", script_sha256=sha(Path(__file__)),
                  sample_layout_bytes=dict(row0_head=32, row0_tail=64, row1_head=32, last_row_tail=32),
                  shift_method="independent full central raster MAE, dy -3..3 and dx -2..2, 200 pixel border excluded",
                  tg_decode="Native FUN_c0125770 @ C0125770: (raw_30100590 & 0x3fff0000) >> 16",
                  clock_caveat="Bus and arm task us use C002B6E0. First 0011 is selected from each take log. This is a firmware timestamp at sensor-write entry, not a measured sensor-frame boundary. IRQ times derive epoch/raw without pending-bit correction; +/-1 s at epoch wrap remains a general limitation.",
                  counts=dict(totals), datasets=groups)
    (HERE / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["counts"], indent=2))
    for g in groups:
        print(g["dataset"], json.dumps(g["counts"]))


if __name__ == "__main__":
    main()
