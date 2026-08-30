#!/usr/bin/env python3
"""Validate GFS6/GFB6 streamed gyro files and convert them to Gyroflow GCSV."""

from __future__ import annotations

import argparse
import binascii
import csv
import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path

FILE_HEADER = struct.Struct("<4s15I")
LENS_REGION = 96          # v4 onward: the raw region the distortion tables sit in
BLOCK_HEADER = struct.Struct("<4s7I")
FOOTER = struct.Struct("<4s7I")
SAMPLE = struct.Struct("<hhhh")
ACCEL = struct.Struct("<Ihhhh")   # us, x, y, z, pad
V5_CLIP_ID = re.compile(r"^[A-Za-z][0-9]{3}_[0-9]{3}$")


@dataclass
class Block:
    sequence: int
    first_us: int
    last_us: int
    flags: int
    samples: list[tuple[int, int, int]]
    accel: list[tuple[int, int, int, int]]


@dataclass(frozen=True)
class PhaseSample:
    write_number: int
    dng_busy: bool
    phase_us: int
    duration_us: int


@dataclass
class Capture:
    rate_hz: int
    period_us: int
    start_us: int
    camera_id: int
    reel: int
    clip: int
    orientation: str
    gscale: float
    initial_head: int
    sensor_mode: int
    sensor_mode2: int
    exposure_us: int
    lens_table: tuple
    blocks: list[Block]
    footer_blocks: int
    dropped_samples: int
    error_flags: int
    end_us: int
    mode_history: tuple = ()
    format_version: int = 3
    explicit_clip_id: str = ""
    recording_volume: int = 0
    lifecycle_adapter: int = 0
    phase_trace: tuple[PhaseSample, ...] = ()
    phase_write_count: int = 0

    @property
    def clip_name(self) -> str:
        return self.explicit_clip_id or f"{chr(self.camera_id)}{self.reel:03d}_{self.clip:03d}"


def delta32(value: int, origin: int) -> int:
    return (value - origin) & 0xFFFFFFFF


def find_lens_table(region):
    """Pick the lens's distortion support points out of the region.

    Two 17-point tables sit here. One reads as all 32768 -- Q15 for 1.0, the
    identity, which is what correction-off looks like -- and the other is the
    lens. A real table is monotonic and stays within a few percent of the
    identity; without that bound the search runs off the end into whatever
    follows and reports ninety percent distortion.
    """
    words = struct.unpack(f"<{len(region) // 2}H", region)
    best, best_dev = None, 0.0
    for i in range(len(words) - 17):
        t = words[i:i + 17]
        if any(v == 0 for v in t):
            continue
        s = [t[k] * k / 16 / 32768 for k in range(17)]
        if any(s[k] > s[k + 1] + 1e-9 for k in range(16)):
            continue
        dev = max(abs(s[k] - k / 16) for k in range(17))
        if 1e-6 < dev <= 0.05 and dev > best_dev:
            best, best_dev = t, dev
    return best


def read_capture(path: Path) -> Capture:
    data = path.read_bytes()
    if len(data) < FILE_HEADER.size + FOOTER.size:
        raise ValueError("file is shorter than GFS6 header + footer")
    fields = FILE_HEADER.unpack_from(data)
    magic, version, rate, period, start, camera, reel, clip, orient_word, gscale_word = fields[:10]
    initial_head = fields[11]
    sensor_mode, sensor_mode2, exposure_us = fields[12], fields[13], fields[14]
    if magic != b"GFS6" or version not in (3, 4, 5) or not rate or not period:
        raise ValueError(f"unsupported header: {magic!r}, version={version}")
    explicit_clip_id = ""
    recording_volume = 0
    lifecycle_adapter = 0
    if version >= 5:
        try:
            explicit_clip_id = data[20:28].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("v5 header has a non-ASCII clip id") from exc
        if not V5_CLIP_ID.fullmatch(explicit_clip_id):
            raise ValueError(f"v5 header has an invalid clip id: {explicit_clip_id!r}")
        camera = ord(explicit_clip_id[0])
        reel = int(explicit_clip_id[1:4])
        clip = int(explicit_clip_id[5:8])
        recording_volume = data[28]
        lifecycle_adapter = data[29]
        if recording_volume not in (1, 5):
            raise ValueError(f"v5 header has an invalid recording volume: {recording_volume}")
        if lifecycle_adapter not in (1, 2):
            raise ValueError(f"v5 header has an invalid lifecycle adapter: {lifecycle_adapter}")
    orientation = struct.pack("<I", orient_word).split(b"\0", 1)[0].decode("ascii")
    gscale = struct.unpack("<f", struct.pack("<I", gscale_word))[0]
    lens = None
    offset = FILE_HEADER.size
    if version >= 4:
        lens = find_lens_table(data[offset:offset + LENS_REGION])
        offset += LENS_REGION
    blocks = []
    footer_values = None
    mode_history = []
    phase_trace = []
    phase_write_count = 0
    wrap_excess = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError(f"truncated magic at {offset:#x}")
        magic = data[offset:offset + 4]
        if magic == b"GFE6":
            if offset + FOOTER.size != len(data):
                raise ValueError("footer is not the final 32 bytes")
            footer_values = FOOTER.unpack_from(data, offset)
            # The footer carries a second reading of the mode, taken a block or
            # more into the take. Do NOT prefer it: `FUN_c032c720` stops
            # reporting the sensor once recording is under way. A001_016 (59.94
            # fps clip) and A001_017 (29.97 fps clip) both put 8 there, while
            # their headers said 8 and 106 -- each matching its own clip. So the
            # header, sampled the instant the record flag goes up, is the one
            # that tracks the recording; the late value pins to the monitor,
            # which the logger's own notes already describe being raised for the
            # duration of a take. Kept only as a diagnostic.
            late_sensor_mode = footer_values[5]
            offset += FOOTER.size
            break
        if magic == b"GFM6":
            # Every distinct sensor mode the take passed through, sampled on the
            # writer's 5 ms poll. Written because one sample at record start
            # races the mode change: A001_016 and A001_017, shot back to back on
            # the same settings, recorded 8 and 106 there.
            n = struct.unpack_from("<I", data, offset + 4)[0]
            mode_history = [struct.unpack_from("<II", data, offset + 8 + 8 * i)
                            for i in range(min(n, 8))]
            offset += 72
            continue
        if magic == b"GFT6":
            # Phase-probe build: slots 0..3 retain the first four full GYR
            # writes and slots 4..7 are a ring containing the last four.  Each
            # pair is {phase/busy, total F_WRITE duration}; bit 31 says the GYR
            # call arrived while a CinemaDNG write held the shared media path.
            if offset + 72 > len(data):
                raise ValueError("truncated GFT6 phase record")
            phase_write_count = struct.unpack_from("<I", data, offset + 4)[0]
            raw = [struct.unpack_from("<II", data, offset + 8 + 8 * i)
                   for i in range(8)]
            selected = [(i + 1, raw[i])
                        for i in range(min(phase_write_count, 4))]
            if phase_write_count > 4:
                tail_n = min(phase_write_count - 4, 4)
                for zero_based in range(phase_write_count - tail_n,
                                        phase_write_count):
                    slot = 4 + ((zero_based - 4) & 3)
                    selected.append((zero_based + 1, raw[slot]))
            phase_trace = [PhaseSample(number, bool(word & 0x80000000),
                                       word & 0x7FFFFFFF, duration)
                           for number, (word, duration) in selected]
            offset += 72
            continue
        if magic != b"GFB6" or offset + BLOCK_HEADER.size > len(data):
            raise ValueError(f"bad block at {offset:#x}: {magic!r}")
        _, sequence, first, last, count, flags, payload_bytes, expected_crc = BLOCK_HEADER.unpack_from(data, offset)
        # The top half of flags counts the accelerometer records that follow the
        # gyro samples: one per batch, carrying the batch's own timestamp, so the
        # two sensors share a clock. They live in the same payload rather than a
        # second buffer, and the header says how many of each there are.
        accel_count = flags >> 16
        accel_bytes = accel_count * ACCEL.size
        excess = payload_bytes - count * SAMPLE.size - accel_bytes
        if 0 < excess <= 32 and flags & 1:
            # Producer bug, fixed 2026-08-26: the wrap arithmetic used 0x12C4 for
            # the ring length when the ring holds 0x12C0 bytes, so every wrapped
            # block carried four stale bytes past its last whole sample. Files
            # written before the fix are still readable -- the count is right and
            # the extra four are at the end -- so read them, and say so.
            pass
        elif excess:
            raise ValueError(
                f"block {sequence}: payload {payload_bytes} is not "
                f"{count} samples of {SAMPLE.size}")
        begin, end = offset + BLOCK_HEADER.size, offset + BLOCK_HEADER.size + payload_bytes
        if end > len(data):
            raise ValueError(f"block {sequence}: truncated payload")
        actual_crc = binascii.crc32(
            data[begin:offset + BLOCK_HEADER.size + BLOCK_HEADER.unpack_from(data, offset)[6]]
        ) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"block {sequence}: CRC {actual_crc:08x} != {expected_crc:08x}")
        # Gyro samples first, then accel records: the camera keeps them in
        # separate regions of the buffer and brings them together when it writes
        # the block, so the payload is one array of each.
        gyro_end = begin + count * SAMPLE.size
        accel = list(ACCEL.iter_unpack(data[gyro_end:gyro_end + accel_bytes]))
        accel = [(t, x, y, z) for t, x, y, z, _ in accel]
        samples, i, repaired = [], begin, 0
        while i + SAMPLE.size <= gyro_end:
            x, y, pad, z = SAMPLE.unpack_from(data, i)
            if pad == 0:
                samples.append((x, y, z))
                i += SAMPLE.size
                continue
            # Files written before 2026-08-26 carry four stray bytes at every
            # ring wrap: the count treated the ring as 0x12C4 bytes when it holds
            # 0x12C0, so each wrap copied one extra word and shifted everything
            # after it. The padding word is what gives it away, and stepping over
            # four bytes puts the stream back in phase -- verified against a
            # 247 KB capture where the breaks fell exactly 0x12C4 apart and the
            # samples either side were continuous.
            if i + 4 + SAMPLE.size <= end:
                x, y, pad, z = SAMPLE.unpack_from(data, i + 4)
                if pad == 0:
                    samples.append((x, y, z))
                    i += 4 + SAMPLE.size
                    repaired += 1
                    continue
            raise ValueError(f"block {sequence}: lost sample alignment at {i:#x}")
        if repaired:
            wrap_excess += repaired
        blocks.append(Block(sequence, first, last, flags, samples, accel))
        offset = end
    if footer_values is None:
        raise ValueError("missing GFE6 footer (file not cleanly closed)")
    _, footer_blocks, dropped, errors, end_us, _, _, _ = footer_values

    # Which mode the take actually ran in: the one that held longest, not any
    # single sample.
    #
    # A single sample cannot answer it from either end. At record start the
    # switch has not always landed -- A001_016 read 8 there and A001_017 read
    # 106, on identical settings -- and the last sample the writer takes falls
    # after the stop, when the camera is already back in live view, which is why
    # a re-read "later in the take" returned 8 every time. Three takes with the
    # full history show the shape plainly: 106 from the first poll to +12.8 s,
    # then 8 for the last eighty milliseconds. The longest-held entry is the
    # recording mode and the tail is the camera going home.
    if mode_history:
        spans = []
        for i, (us, mode) in enumerate(mode_history):
            stop = mode_history[i + 1][0] if i + 1 < len(mode_history) else end_us
            spans.append((delta32(stop, us), mode))
        held, mode = max(spans)
        if mode != sensor_mode:
            sensor_mode = mode
    sequences = [block.sequence for block in blocks]
    if sequences != list(range(len(sequences))):
        raise ValueError(f"non-contiguous block sequence: {sequences[:8]}...")
    if footer_blocks != len(blocks):
        raise ValueError(f"footer block count {footer_blocks} != parsed {len(blocks)}")
    return Capture(rate, period, start, camera, reel, clip, orientation, gscale,
                   initial_head, sensor_mode, sensor_mode2, exposure_us, lens,
                   blocks, footer_blocks, dropped, errors, end_us,
                   tuple(mode_history), version, explicit_clip_id,
                   recording_volume, lifecycle_adapter,
                   tuple(phase_trace), phase_write_count)


def samples_with_time(capture: Capture):
    previous = -1
    for block in capture.blocks:
        timestamp = delta32(block.first_us, capture.start_us)
        for sample in block.samples:
            timestamp = max(timestamp, previous + 1)
            yield timestamp, sample
            previous = timestamp
            timestamp += capture.period_us


def report(capture: Capture) -> None:
    count = sum(len(block.samples) for block in capture.blocks)
    print(f"clip: {capture.clip_name}")
    if capture.format_version >= 5:
        medium = {1: "SD", 5: "USB SSD"}[capture.recording_volume]
        adapter = {1: "CDNG", 2: "MOV"}[capture.lifecycle_adapter]
        print(f"recording_volume: {capture.recording_volume} ({medium})")
        print(f"lifecycle_adapter: {capture.lifecycle_adapter} ({adapter})")
    print(f"rate_hz: {capture.rate_hz}")
    print(f"period_us: {capture.period_us}")
    print(f"orientation: {capture.orientation}")
    print(f"gscale: {capture.gscale:.12g}")
    print(f"blocks: {len(capture.blocks)}")
    print(f"samples: {count}")
    print(f"duration_s: {count * capture.period_us / 1e6:.6f}")
    print(f"wrap_blocks: {sum(bool(block.flags & 1) for block in capture.blocks)}")
    accel = sum(len(b.accel) for b in capture.blocks)
    print(f"accel_records: {accel}")
    if capture.mode_history:
        first = capture.mode_history[0][0]
        print("mode_history: " + "  ".join(
            f"{delta32(us, first) / 1000:+.1f}ms->{mode}" for us, mode in capture.mode_history))
    if capture.phase_trace:
        print(f"phase_probe_writes: {capture.phase_write_count}")
        for sample in capture.phase_trace:
            edge = "DNG call active" if sample.dng_busy else "between DNG calls"
            print(f"  GYR#{sample.write_number}: phase_us={sample.phase_us} "
                  f"since previous DNG return; {edge}; write_us={sample.duration_us}")
    if capture.sensor_mode:
        # 1080p29.97 matches enum 0106 and enum 0111, both 3032x1708 full width,
        # whose rolling-shutter readouts are 10557 us and 7828 us. `imager
        # mode_list` prints both; the clip says which it was shot in.
        # Enums are decimal in `imager mode_list`; comparing them as hex is how
        # 175 looked unrecognisable for an afternoon.
        # From codex/analysis_imx410, extracted from the firmware's own tables.
        # From the same tables lens_profile.py reads, not a second copy of ten
        # of them. The hardcoded dict had mode 123 -- full sensor, no binning,
        # 21.3 ms -- reported as "not in the extracted table" while the tables
        # had it all along.
        r = None
        try:
            import lens_profile
            for m in lens_profile.load_modes():
                if int(m["mode_id"]) == capture.sensor_mode:
                    r = round(m["readout_ms"] * 1000)
                    break
        except Exception:
            pass
        print(f"sensor_mode: {capture.sensor_mode}" +
              (f"  readout_us: {r}" if r else "  (not in the extracted table)"))
    if capture.lens_table:
        dev = max(abs(capture.lens_table[k] * k / 16 / 32768 - k / 16)
                  for k in range(17))
        print(f"lens_distortion: {dev * 100:.3f}% at most")
        print("  " + ",".join(str(v) for v in capture.lens_table))
    else:
        print("lens_distortion: not in this capture, or only the identity table")
    if capture.exposure_us:
        print(f"exposure_us: {capture.exposure_us}  (1/{1e6/capture.exposure_us:.0f} s)")
    print(f"dropped_samples: {capture.dropped_samples}")
    print(f"error_flags: {capture.error_flags:#x}")
    print(f"capture_span_s: {delta32(capture.end_us, capture.start_us) / 1e6:.6f}")


# MMA8452Q at the two-g range, twelve bits: 1024 counts to a g.  A still camera
# reads about 1005, which is the sensor's own offset and not something to
# calibrate away here -- Gyroflow normalises gravity before it uses it.
ASCALE = 1.0 / 1024


def write_gcsv(path: Path, capture: Capture, accel: bool = False) -> None:
    """The Gyroflow log.  With `accel`, the accelerometer goes in beside the gyro.

    The camera writes the gyro-only form itself.  The accelerometer is recorded
    in the .GYR either way -- a hundred readings a second against the gyro's
    2500 -- but it was left out of the log: in the A/B that settled the axis
    order it made Gyroflow's fusion worse, not better.  That test was about
    which way round the axes go. Horizon levelling is a different question, and
    it cannot be answered without gravity, so this puts it back for anyone who
    wants to try.

    One accelerometer reading covers twenty-five gyro samples, so each row
    carries the most recent one.  Holding the last value rather than
    interpolating: at a hundred hertz the error is small, and inventing readings
    between real ones would be harder to argue with when the result is wrong.
    """
    accels = [a for block in capture.blocks for a in block.accel]
    accels.sort()
    head = [
        ["GYROFLOW IMU LOG"], ["version", "1.3"],
        ["id", "sigma_fp_v502_internal_icm20321"],
        ["orientation", capture.orientation],
        ["note", f"Stage-6 {capture.clip_name}; dropped={capture.dropped_samples}"],
        ["fwversion", "SIGMA fp 5.02"], ["videofilename", capture.clip_name],
        ["tscale", "0.000001"], ["gscale", format(capture.gscale, ".12g")],
    ]
    if accel:
        head.append(["ascale", format(ASCALE, ".12g")])
        head.append(["t", "gx", "gy", "gz", "ax", "ay", "az"])
    else:
        head.append(["t", "gx", "gy", "gz"])

    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(head)
        if not accel:
            for timestamp, (x, y, z) in samples_with_time(capture):
                writer.writerow([timestamp, x, y, z])
            return
        # Seed with the first reading rather than zeros: a row of zero gravity
        # at the head of the file is not a measurement, and the fusion would
        # have to recover from it.
        i, last = 0, (accels[0][1:] if accels else (0, 0, 0))
        for timestamp, (x, y, z) in samples_with_time(capture):
            while i < len(accels) and delta32(accels[i][0], capture.start_us) <= timestamp:
                last = accels[i][1:]
                i += 1
            # The accelerometer's axes are not the gyro's.
            #
            # The gcsv format carries one orientation string and Gyroflow
            # applies it to both sensors, so a sensor that disagrees has to be
            # rotated here instead. With the readings as the firmware hands them
            # over, levelling the horizon needed a roll correction of about -95
            # degrees -- ninety of axis error and five of how the camera was
            # actually held. Rotating a quarter turn the other way puts gravity
            # where Gyroflow expects it: verified on A001_006, 2026-08-30.
            writer.writerow([timestamp, x, y, z, last[1], -last[0], last[2]])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--gcsv", type=Path)
    parser.add_argument("--accel", action="store_true",
                        help="put the accelerometer in the log as well, for horizon levelling")
    args = parser.parse_args()
    capture = read_capture(args.input)
    report(capture)
    if args.gcsv:
        write_gcsv(args.gcsv, capture, accel=args.accel)
        print(f"wrote: {args.gcsv}")


if __name__ == "__main__":
    main()
