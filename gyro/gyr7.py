#!/usr/bin/env python3
"""Read a v7 .GYR -- the zero-copy stream -- and turn it into a Gyroflow log.

    ./gyro/gyr7.py A001_037.GYR                  what is in it
    ./gyro/gyr7.py A001_037.GYR --gcsv out.gcsv  the log
    ./gyro/gyr7.py A001_037.GYR --gcsv out.gcsv --accel   with gravity

The camera can still write the .gcsv itself; this is the other half of the
choice, for anyone who would rather keep the raw capture and convert later.

WHY THE FORMAT CHANGED

GFS6 puts a CRC32 and a sample count in front of every block and keeps the two
sensors in separate regions of the payload.  Both of those mean the camera has
to touch the data on its way to the card.  The stream this reads never does:
the accelerometer hook and the gyro drain write records straight into a buffer
the allocator handed over, and that buffer goes to the card exactly as they
left it.  So the container is a header and then nothing but records --

    0x00  "GFS7"        0x04  version = 7
    0x08  period, ps    0x0C  gscale, float
    0x10  orientation   0x14  clip id, 8 ASCII
    0x1C  volume        0x20  payload bytes    0x24  blocks dropped
    0x28  sensor mode   0x2C  exposure, us     0x30  width   0x34  height

    then, from 0x40, 8-byte records:  int16 x, int16 y, int16 tag, int16 z

-- and the two sensors are interleaved in the order they happened, which is the
point: an accelerometer sample sits beside the gyro samples of its own instant
rather than being filed at the end of a batch.

TIME

The gyro runs at 2499.466 Hz -- 400.0854 us.  Two unrelated rulers agreed: a
600 s host-clock count over 21 points gave 2499.520 +/- 0.018 Hz, and 2863
frame intervals measured against the camera's own sensor gave 2499.466.  The
frame ruler is the one in the header, because it is the clock the video runs
on.  The old header carried an integer 400 us, fast by 0.085 us every sample:
3.4 ms across a forty-second take, and it grows.

So the log does not count microseconds.  `tscale` is the sample period itself
and `t` is the sample number, which is exact and cannot drift -- Gyroflow
multiplies the two.  The camera's own gcsv writer keeps microseconds because it
has no floating point to spare; here there is no reason to lose the precision.
"""
from __future__ import annotations

import argparse
import csv
import struct
from dataclasses import dataclass
from pathlib import Path

HEADER = struct.Struct("<4sIIfI8sIIIIIII8x")
RECORD = struct.Struct("<hhhh")
HDR_BYTES = 64
TAG_GYRO, TAG_ACCEL = 0, 1

# MMA8452Q at the two-g range, twelve bits: 1024 counts to a g.  Unchanged from
# decode.py -- the sensor did not move, only the container around it.
ASCALE = 1.0 / 1024


@dataclass
class Capture:
    version: int
    period_s: float
    gscale: float
    orientation: str
    clip: str
    volume: int
    payload: int
    dropped: int
    sensor_mode: int
    exposure_us: int
    width: int
    height: int
    gyro: list[tuple[int, int, int]]
    # (index of the gyro sample it follows, x, y, z) -- an accelerometer reading
    # belongs to a moment, and its moment is where it sits in the stream.
    accel: list[tuple[int, int, int, int]]
    unknown: int

    @property
    def rate_hz(self) -> float:
        return 1.0 / self.period_s

    @property
    def duration_s(self) -> float:
        return len(self.gyro) * self.period_s


def read_capture(path: Path) -> Capture:
    data = path.read_bytes()
    if len(data) < HDR_BYTES:
        raise ValueError("shorter than a header")
    (magic, version, period_ps, gscale, orient_word, clip, volume,
     payload, dropped, mode, exposure, width, height) = HEADER.unpack_from(data)
    if magic != b"GFS7":
        raise ValueError(f"not a v7 capture: {magic!r} -- decode.py reads GFS6")
    if version != 7:
        raise ValueError(f"unsupported version {version}")
    if not period_ps:
        raise ValueError("the header has no sample period")
    orientation = struct.pack("<I", orient_word).split(b"\0", 1)[0].decode("ascii")

    body = data[HDR_BYTES:]
    if payload and payload != len(body):
        # The header is rewritten at close.  A mismatch means the take never
        # closed -- read what is there and say so rather than refusing.
        print(f"warning: header says {payload} payload bytes, file has "
              f"{len(body)}; reading the file")
    if len(body) % RECORD.size:
        print(f"warning: {len(body) % RECORD.size} bytes past the last whole "
              f"record")

    gyro: list[tuple[int, int, int]] = []
    accel: list[tuple[int, int, int, int]] = []
    unknown = 0
    for x, y, tag, z in RECORD.iter_unpack(body[:len(body) - len(body) % RECORD.size]):
        if tag == TAG_GYRO:
            gyro.append((x, y, z))
        elif tag == TAG_ACCEL:
            accel.append((len(gyro), x, y, z))
        else:
            unknown += 1

    return Capture(version, period_ps / 1e12, gscale, orientation,
                   clip.split(b"\0", 1)[0].decode("ascii", "replace"),
                   volume, payload, dropped, mode, exposure, width, height,
                   gyro, accel, unknown)


def report(c: Capture) -> None:
    print(f"clip: {c.clip}")
    print(f"volume: {c.volume}" + {1: " (SD)", 5: " (USB SSD)"}.get(c.volume, ""))
    print(f"rate_hz: {c.rate_hz:.4f}   period_us: {c.period_s * 1e6:.4f}")
    print(f"orientation: {c.orientation}")
    print(f"gscale: {c.gscale:.12g}")
    print(f"gyro: {len(c.gyro)}   accel: {len(c.accel)}"
          + (f"   unknown tags: {c.unknown}" if c.unknown else ""))
    if c.accel and c.gyro:
        print(f"one accel every {len(c.gyro) / len(c.accel):.1f} gyro "
              f"= {len(c.accel) / c.duration_s:.2f} Hz")
    print(f"duration_s: {c.duration_s:.6f}")
    print(f"dropped_blocks: {c.dropped}"
          + ("   <- the writer did not keep up" if c.dropped else ""))
    if c.sensor_mode:
        print(f"sensor_mode: {c.sensor_mode}")
    if c.exposure_us:
        print(f"exposure_us: {c.exposure_us}  (1/{1e6 / c.exposure_us:.0f} s)")
    if c.width:
        print(f"geometry: {c.width} x {c.height}")


def write_gcsv(path: Path, c: Capture, accel: bool = False) -> None:
    """The Gyroflow log.  With `accel`, gravity goes in beside the gyro.

    The accelerometer is in the .GYR either way.  It is out of the log by
    default because in the A/B that settled the axis order it made Gyroflow's
    fusion worse -- but that test was about axis order, and horizon levelling
    cannot be answered without gravity, so the switch is here.
    """
    head = [
        ["GYROFLOW IMU LOG"], ["version", "1.3"],
        ["id", "sigma_fp_v502_internal_icm20321"],
        ["orientation", c.orientation],
        ["note", f"GFS7 {c.clip}; dropped_blocks={c.dropped}"],
        ["fwversion", "SIGMA fp 5.02"], ["videofilename", c.clip],
        # t counts samples, so this is the whole of the clock.
        ["tscale", format(c.period_s, ".12g")],
        ["gscale", format(c.gscale, ".12g")],
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
            for i, (x, y, z) in enumerate(c.gyro):
                writer.writerow([i, x, y, z])
            return
        # Hold the last reading rather than interpolate: at forty-six hertz the
        # error is small, and invented readings between real ones are harder to
        # argue with when the result is wrong.  Seed with the first real one --
        # a row of zero gravity at the head of the file is not a measurement.
        i, last = 0, (c.accel[0][1:] if c.accel else (0, 0, 0))
        for n, (x, y, z) in enumerate(c.gyro):
            while i < len(c.accel) and c.accel[i][0] <= n:
                last = c.accel[i][1:]
                i += 1
            # The accelerometer's axes are not the gyro's, and gcsv carries one
            # orientation string for both.  A quarter turn puts gravity where
            # Gyroflow expects it -- verified on A001_006, 2026-08-30.
            writer.writerow([n, x, y, z, last[1], -last[0], last[2]])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--gcsv", type=Path)
    ap.add_argument("--accel", action="store_true",
                    help="put the accelerometer in the log too, for levelling")
    a = ap.parse_args()
    c = read_capture(a.input)
    report(c)
    if a.gcsv:
        write_gcsv(a.gcsv, c, accel=a.accel)
        print(f"wrote: {a.gcsv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
