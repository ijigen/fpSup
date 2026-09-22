#!/usr/bin/env python3
"""Regression tests for GYR file-header versions 3 through 5."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import decode


def float_word(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def capture_bytes(version: int, *, clip_id: bytes = b"A001_037",
                  volume: int = 1, adapter: int = 1,
                  phase_record: bytes = b"") -> bytes:
    fields = [
        version, 2500, 400, 123456,
        ord("B"), 12, 34,
        int.from_bytes(b"XYZ\0", "little"), float_word(0.001),
        0, 77, 106, 8, 10000, 0,
    ]
    header = bytearray(decode.FILE_HEADER.pack(b"GFS6", *fields))
    if version >= 5:
        header[20:28] = clip_id
        header[28] = volume
        header[29] = adapter
        header[30:32] = b"\0\0"
    lens = bytes(decode.LENS_REGION) if version >= 4 else b""
    footer = decode.FOOTER.pack(b"GFE6", 0, 0, 0, 124456, 106, 1936, 1090)
    return bytes(header) + lens + phase_record + footer


class DecodeHeaderVersions(unittest.TestCase):
    def read(self, payload: bytes):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.GYR"
            path.write_bytes(payload)
            return decode.read_capture(path)

    def test_v5_decodes_explicit_clip_and_sd_cdng_adapter(self):
        capture = self.read(capture_bytes(5))
        self.assertEqual(capture.format_version, 5)
        self.assertEqual(capture.clip_name, "A001_037")
        self.assertEqual((capture.camera_id, capture.reel, capture.clip),
                         (ord("A"), 1, 37))
        self.assertEqual(capture.recording_volume, 1)
        self.assertEqual(capture.lifecycle_adapter, 1)

    def test_v5_decodes_ssd_movie_adapter(self):
        capture = self.read(capture_bytes(
            5, clip_id=b"C123_456", volume=5, adapter=2))
        self.assertEqual(capture.clip_name, "C123_456")
        self.assertEqual(capture.recording_volume, 5)
        self.assertEqual(capture.lifecycle_adapter, 2)

    def test_v3_numeric_identity_is_unchanged(self):
        capture = self.read(capture_bytes(3))
        self.assertEqual(capture.format_version, 3)
        self.assertEqual(capture.clip_name, "B012_034")
        self.assertEqual(capture.explicit_clip_id, "")
        self.assertEqual(capture.recording_volume, 0)
        self.assertEqual(capture.lifecycle_adapter, 0)
        self.assertIsNone(capture.lens_table)

    def test_v4_numeric_identity_is_unchanged(self):
        capture = self.read(capture_bytes(4))
        self.assertEqual(capture.format_version, 4)
        self.assertEqual(capture.clip_name, "B012_034")
        self.assertEqual(capture.explicit_clip_id, "")
        self.assertEqual(capture.recording_volume, 0)
        self.assertEqual(capture.lifecycle_adapter, 0)

    def test_v5_rejects_invalid_metadata(self):
        cases = [
            capture_bytes(5, clip_id=b"bad-name"),
            capture_bytes(5, volume=0),
            capture_bytes(5, adapter=0),
        ]
        for payload in cases:
            with self.subTest(payload=payload[20:32]):
                with self.assertRaises(ValueError):
                    self.read(payload)



if __name__ == "__main__":
    unittest.main()
