#!/usr/bin/env python3
"""Verify the frozen OG3K v0.2.3a artifact against public v0.2.2a."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct


ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "releases" / "fpsup-og3k-v0.2.2a"
NEW = ROOT / "releases" / "fpsup-og3k-v0.2.3a"
CURRENT = ROOT / "opengate"

EXPECTED_SHA256 = {
    "AutoRun.txt": "1e7f75f3d9197fecae946ab95ebc2aeb3dc93fbe55984019da3208b4f092b745",
    "VSHL.BIN": "da1c94e05828c7fec423fed044856d54ba839532d38a5bd2e446942778062cd7",
}
EXPECTED_DELTAS = {
    0xC0730800: (0xE92D5018, 0xE92D5078),
    0xC0730810: (0x03A01000, 0x03A05000),
    0xC0730824: (0x03A01003, 0x03A05003),
    0xC073083C: (0xE3A01004, 0xE3A05004),
    0xC0730880: (0xE5841000, 0xE5845000),
    0xC07308D4: (0xE8BD5018, 0xE8BD5078),
    0xC07308DC: (0xE8BD5018, 0xE8BD5078),
}
SHIPPING_FILES = {"AutoRun.txt", "MANIFEST.txt", "README.txt", "VSHL.BIN"}
USB_SHELL_SITES = {
    0xC0CF3740, 0xC0CF3758, 0xC0CF375C, 0xC0CF3780,
    0xC0CF3784, 0xC0CF3798, 0xC0CF379C,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_vshl(path: Path) -> dict:
    blob = path.read_bytes()
    require(len(blob) == 32768, f"{path} is not 32,768 bytes")
    magic, count, entry, body_bytes = struct.unpack_from("<4sIII", blob)
    require(magic == b"VBIN", f"{path} has bad magic")
    table_end = 16 + count * 8
    require(table_end <= len(blob), f"{path} has a truncated section table")

    offset = table_end
    sections = []
    words = {}
    for index in range(count):
        address, length = struct.unpack_from("<II", blob, 16 + index * 8)
        require(length % 4 == 0, f"section 0x{address:08X} is unaligned")
        payload = blob[offset:offset + length]
        require(len(payload) == length, f"section 0x{address:08X} is truncated")
        sections.append((address, payload))
        if address >= 0x40000000:
            for inner in range(0, length, 4):
                site = address + inner
                require(site not in words, f"overlapping word at 0x{site:08X}")
                words[site] = struct.unpack_from("<I", payload, inner)[0]
        offset += length

    require(offset == table_end + body_bytes, f"{path} body length disagrees")
    require(not any(blob[offset:]), f"{path} has non-zero padding")
    return {
        "count": count,
        "entry": entry,
        "sections": sections,
        "words": words,
    }


def autorun_commands(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def without_version_banner(commands: list[str]) -> list[str]:
    return [
        line for line in commands
        if not line.startswith("display text fpSup-OG3K-v")
    ]


def main() -> None:
    require(OLD.is_dir(), f"missing {OLD}")
    require(NEW.is_dir(), f"missing {NEW}")
    require({path.name for path in NEW.iterdir()} == SHIPPING_FILES,
            "release directory does not contain exactly the four shipping files")

    for name, expected in EXPECTED_SHA256.items():
        require(sha256(NEW / name) == expected, f"{name} hash differs")

    old = parse_vshl(OLD / "VSHL.BIN")
    new = parse_vshl(NEW / "VSHL.BIN")
    require((old["count"], old["entry"]) == (80, 0),
            "v0.2.2a VSHL shape is unexpected")
    require((new["count"], new["entry"]) == (80, 0),
            "v0.2.3a VSHL is not the 80-section no-shell form")
    require(
        [(address, len(payload)) for address, payload in old["sections"]]
        == [(address, len(payload)) for address, payload in new["sections"]],
        "section address/order/size changed",
    )

    sites = sorted(set(old["words"]) | set(new["words"]))
    deltas = {
        site: (old["words"].get(site), new["words"].get(site))
        for site in sites
        if old["words"].get(site) != new["words"].get(site)
    }
    require(deltas == EXPECTED_DELTAS,
            f"VSHL delta is not the seven-word fmttable allowlist: {deltas}")

    for name in ("AutoRun.txt", "MANIFEST.txt", "VSHL.BIN"):
        require((CURRENT / name).read_bytes() == (NEW / name).read_bytes(),
                f"opengate/{name} differs from the tagged release copy")

    new_text = (NEW / "AutoRun.txt").read_text(encoding="utf-8")
    require(len(new_text.encode()) == 32772, "AutoRun.txt size differs")
    new_commands = autorun_commands(NEW / "AutoRun.txt")
    old_commands = autorun_commands(OLD / "AutoRun.txt")
    require(len(new_commands) == 135, "AutoRun.txt does not have 135 commands")
    require(without_version_banner(new_commands) == without_version_banner(old_commands),
            "AutoRun functional commands changed outside the banner")
    require(
        len(re.findall(r"^display text fpSup-OG3K-v0\.2\.3a!$", new_text, re.M)) == 3,
        "AutoRun does not contain exactly three v0.2.3a completion banners",
    )
    require("v0.2.2b-RC1" not in new_text, "RC banner remains in AutoRun")

    mem_sites = {
        int(fields[2], 0)
        for line in new_commands
        if len(fields := line.split()) >= 4 and fields[:2] == ["mem", "set"]
    }
    require(not mem_sites.intersection(USB_SHELL_SITES),
            "no-shell AutoRun contains USB shell patches")

    manifest = (NEW / "MANIFEST.txt").read_text(encoding="utf-8")
    for expected in EXPECTED_SHA256.values():
        require(expected in manifest, "MANIFEST.txt omits a shipping hash")
    require("100 張 DNG" in manifest, "MANIFEST.txt omits the camera evidence")
    require("Super35/crop" in manifest, "MANIFEST.txt omits the crop limitation")

    print("PASS: OG3K v0.2.3a frozen artifact")
    print("  hashes, no-shell shape, current copies, and AutoRun: exact")
    print("  v0.2.2a delta: seven allowed fmttable words only")


if __name__ == "__main__":
    main()
