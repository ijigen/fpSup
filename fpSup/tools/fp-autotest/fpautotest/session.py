# SPDX-License-Identifier: GPL-3.0-or-later
"""Transport backends for the fpSup hardware-in-the-loop harness.

There are two ways to reach the camera's shell, and both expose the same tiny
surface used by the runner::

    session.sh(line) -> str
    session.mem_get(addr, size=4) -> int
    session.version() -> str
    session.status(name="") -> str

``DaemonSession`` is the upstream path and the default on macOS and Linux.  It
talks to ``fpshd`` through ``fp_usb_shell/putfile.sh``; this module deliberately
does not reimplement the AF_UNIX protocol.

``DirectSession`` speaks FPSH v1 over pyusb (interface 0, bulk endpoints
``0x01``/``0x82``) for hosts without the daemon, notably Windows.  pyusb is
imported only when a direct session is opened, so the daemon backend and the
rest of the harness work without it.

Neither backend can write memory by itself.  ``sh()`` will send whatever line a
suite author writes, so suites are the safety boundary: this tool is meant for
read-only probes and operator prompts.
"""

from __future__ import annotations

import errno
import os
import random
import re
import struct
import sys
import time
import zlib
from pathlib import Path

BACKENDS = ("daemon", "direct")

DEFAULT_TIMEOUT_MS = 1000
DEFAULT_RETRIES = 3

# Matches one memory reply line: "get : A:0xC007F324, D:0xE309C6FC".
_MEM_RE = re.compile(r"A:\s*0x([0-9a-fA-F]+)\s*,\s*D:\s*0x([0-9a-fA-F]+)")


class ShellError(RuntimeError):
    """Transport or shell failure."""


def default_backend() -> str:
    """The backend used when ``--backend`` is not given.

    The daemon is the upstream, camera-free path and exists on Unix hosts.  On
    Windows the harness falls back to the direct pyusb client.
    """
    if sys.platform.startswith(("linux", "darwin")):
        return "daemon"
    return "direct"


def _check_line(line: str) -> None:
    if not isinstance(line, str) or not line.strip():
        raise ShellError("shell line must be a non-empty string")
    if any(ch in line for ch in "\r\n\0"):
        raise ShellError("shell line must be a single line")


def _parse_mem_reply(reply: str, addr: int) -> int:
    matches = _MEM_RE.findall(reply)
    if not matches:
        raise ShellError(f"cannot parse memory reply: {reply.strip()!r}")
    # Prefer the requested address; a wider read still reports its first word.
    for found, data in matches:
        if int(found, 16) == addr:
            return int(data, 16)
    return int(matches[0][1], 16)


# -- daemon backend ------------------------------------------------------


def _locate_shell_dir() -> Path:
    """Find ``fp_usb_shell`` relative to this package.

    The checkout layout is ``fpSup/tools/fp-autotest/fpautotest/session.py``;
    searching ancestors avoids hard-coding a repository root and keeps the tool
    usable if the package is vendored elsewhere under the same tree.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "fp_usb_shell"
        if (candidate / "putfile.py").is_file():
            return candidate
    raise ShellError(
        "cannot locate fpSup/fp_usb_shell/putfile.py relative to this package; "
        "run from a full fpSup checkout or use --backend direct"
    )


def _load_putfile(socket_path: str | os.PathLike[str] | None):
    """Import upstream ``putfile`` without duplicating its socket protocol."""
    shell_dir = str(_locate_shell_dir())
    if shell_dir not in sys.path:
        sys.path.insert(0, shell_dir)
    try:
        import putfile  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on checkout layout
        raise ShellError(f"cannot import fp_usb_shell/putfile.py: {exc}") from exc
    if socket_path is not None:
        putfile.SOCK = os.fspath(socket_path)
    return putfile


class DaemonSession:
    """Shell access through the upstream ``fpshd`` AF_UNIX daemon.

    ``putfile.sh`` opens one socket connection per command and retries replies
    that do not arrive, which is the behaviour the upstream tools rely on.
    ``socket_path`` overrides ``putfile.SOCK``; otherwise the daemon honours the
    ``FPSHD_SOCKET`` environment variable and its ``/tmp/fpshd.sock`` default.
    """

    def __init__(
        self,
        timeout_ms: int | None = None,
        retries: int = DEFAULT_RETRIES,
        socket_path: str | os.PathLike[str] | None = None,
    ):
        if timeout_ms is not None and int(timeout_ms) <= 0:
            raise ValueError("timeout_ms must be greater than zero")
        self.timeout_ms = timeout_ms
        self.retries = max(1, int(retries))
        self._putfile = _load_putfile(socket_path)

    def __enter__(self) -> "DaemonSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """The daemon opens one connection per command; nothing is held."""

    def sh(self, line: str) -> str:
        _check_line(line)
        kwargs = {"retries": self.retries}
        if self.timeout_ms is not None:
            kwargs["timeout_ms"] = int(self.timeout_ms)
        try:
            reply = self._putfile.sh(line, **kwargs)
        except OSError as exc:
            raise ShellError(
                f"fpshd daemon unavailable at {self._putfile.SOCK}: {exc}; "
                "start fpshd or use --backend direct"
            ) from exc
        if reply is None:
            reply = ""
        if reply.lstrip().startswith("ERR"):
            raise ShellError(f"daemon error: {reply.strip()}")
        return reply

    def mem_get(self, addr: int, size: int = 4) -> int:
        if int(size) <= 0:
            raise ShellError(f"invalid size {size}")
        address = int(addr)
        reply = self.sh(f"mem get 0x{address:08X},,{int(size)}")
        return _parse_mem_reply(reply, address)

    def version(self) -> str:
        return self.sh("version").strip()

    def status(self, name: str = "") -> str:
        line = "status get" + (f" {name}" if name else "")
        return self.sh(line).strip()


# -- direct pyusb backend ------------------------------------------------

VID = 0x1003
PID = 0xC432

IFACE = 0
EP_OUT = 0x01
EP_IN = 0x82

FRAME = 64
PAYLOAD = 44
HEADER = 20  # magic .. checksum

CMD_PING = 1
CMD_SHL = 3

MAX_BLOCK = 16 * 1024 * 1024
MAX_SKIPPED = 32

LIBUSB_ERROR_NO_DEVICE = -4
LIBUSB_ERROR_TIMEOUT = -7
LIBUSB_ERROR_OVERFLOW = -8
LIBUSB_ERROR_PIPE = -9

_LIBUSB_ERRNO = {
    LIBUSB_ERROR_NO_DEVICE: getattr(errno, "ENODEV", None),
    LIBUSB_ERROR_TIMEOUT: getattr(errno, "ETIMEDOUT", None),
    LIBUSB_ERROR_OVERFLOW: getattr(errno, "EOVERFLOW", None),
    LIBUSB_ERROR_PIPE: getattr(errno, "EPIPE", None),
}

FMT = "<4sBBHIHHI"  # 20 bytes


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _zero_checksum(frame: bytes) -> bytes:
    buf = bytearray(frame[:FRAME])
    buf[16:20] = b"\x00\x00\x00\x00"
    return bytes(buf)


def build_frame(sequence: int, command: int, payload: bytes, flags: int = 0) -> bytes:
    """Build one FPSH command transfer, CRC over the first 64 bytes.

    Commands longer than the 44-byte payload slot spill past byte 64 in the
    same OUT transfer, which is what the upstream daemon does.
    """
    if len(payload) > 0xFFFF:
        raise ShellError("command too long")
    txlen = max(FRAME, (HEADER + len(payload) + 1 + 3) & ~3)
    buf = bytearray(txlen)
    struct.pack_into(
        FMT, buf, 0, b"FPSH", 1, command, flags, sequence, len(payload), 0, 0
    )
    buf[HEADER:HEADER + len(payload)] = payload
    # The checksum field is still zero here, as the camera expects.
    struct.pack_into("<I", buf, 16, crc32(bytes(buf[:FRAME])))
    return bytes(buf)


def parse_frame(raw: bytes) -> dict:
    """Parse and validate one 64-byte FPSH reply frame."""
    if len(raw) != FRAME:
        raise ShellError(f"short frame: {len(raw)} bytes")
    magic, version, command, flags, sequence, plen, status, checksum = (
        struct.unpack_from(FMT, raw, 0)
    )
    if magic != b"FPSH" or version != 1:
        raise ShellError(f"bad frame magic={magic!r} version={version}")
    if crc32(_zero_checksum(raw)) != checksum:
        raise ShellError("bad frame CRC")
    return {
        "command": command,
        "flags": flags,
        "sequence": sequence,
        "payload_length": plen,
        "status": status,
        "payload": raw[HEADER:HEADER + min(plen, PAYLOAD)],
    }


def _load_usb():
    try:
        import usb.core  # type: ignore[import-not-found]
        import usb.util  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ShellError(
            "pyusb is required for --backend direct; install it with "
            "`python -m pip install pyusb` and make sure libusb-1.0 is "
            "discoverable by the platform loader"
        ) from exc
    return usb.core, usb.util


class DirectSession:
    """Direct FPSH v1 client over pyusb, for hosts without ``fpshd``.

    Interface 0, bulk OUT ``0x01``, bulk IN ``0x82``; replies are matched by
    sequence number and stale frames are skipped.  Only the shell command path
    is exposed.
    """

    def __init__(self, timeout_ms: int = DEFAULT_TIMEOUT_MS, retries: int = DEFAULT_RETRIES):
        if int(timeout_ms) <= 0:
            raise ValueError("timeout_ms must be greater than zero")
        self.timeout_ms = int(timeout_ms)
        self.retries = max(1, int(retries))
        self._core, self._util = _load_usb()
        self._usb_error = self._core.USBError
        self.dev = self._core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise ShellError(f"camera {VID:04x}:{PID:04x} not found")
        self._claimed = False
        try:
            cfg = self.dev.get_active_configuration()
            if cfg is None or cfg.bConfigurationValue != 1:
                self.dev.set_configuration()
        except self._usb_error:
            try:
                self.dev.set_configuration()
            except self._usb_error:
                pass
        try:
            self._util.claim_interface(self.dev, IFACE)
            self._claimed = True
        except self._usb_error as exc:
            raise ShellError(f"claim interface {IFACE} failed: {exc}") from exc
        # Start at a random sequence so a stale reply from an earlier run
        # cannot be mistaken for ours.
        self.sequence = random.randrange(0x10000000, 0x7FFFFFF0)

    def __enter__(self) -> "DirectSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._claimed:
            try:
                self._util.release_interface(self.dev, IFACE)
            except self._usb_error:
                pass
            self._claimed = False

    # -- framing ---------------------------------------------------------

    def _next_sequence(self) -> int:
        self.sequence = (self.sequence + 1) & 0xFFFFFFFF
        if self.sequence == 0xFFFFFFFF:
            self.sequence = 1
        return self.sequence

    def _clear_halt(self, endpoint: int) -> None:
        try:
            self.dev.clear_halt(endpoint)
        except (AttributeError, self._usb_error):
            try:
                self._util.clear_halt(self.dev, endpoint)
            except Exception:
                pass

    def _read_exact(self, length: int, timeout: int) -> bytes:
        return bytes(self.dev.read(EP_IN, length, timeout=timeout))

    def _is_libusb_error(self, exc: Exception, code: int) -> bool:
        if getattr(exc, "errno", None) == code:
            return True
        if getattr(exc, "backend_error_code", None) == code:
            return True
        mapped = _LIBUSB_ERRNO.get(code)
        return mapped is not None and getattr(exc, "errno", None) == mapped

    def drain_in(self) -> None:
        """Best-effort clear of leftover IN data."""
        for _ in range(8):
            try:
                moved = len(self._read_exact(16384, 20))
            except self._usb_error as exc:
                if self._is_libusb_error(exc, LIBUSB_ERROR_PIPE):
                    self._clear_halt(EP_IN)
                    continue
                if self._is_libusb_error(exc, LIBUSB_ERROR_OVERFLOW):
                    continue
                break
            if moved == 0:
                break

    def _collect(self, sequence: int, expect_cmd: int) -> tuple[bytes, int]:
        out = bytearray()
        skipped = 0
        while True:
            frame = parse_frame(self._read_exact(FRAME, self.timeout_ms))
            if frame["sequence"] != sequence:
                if frame["flags"] & 2:
                    n = frame["payload_length"]
                    if n > MAX_BLOCK:
                        raise ShellError(f"stale block too large: {n}")
                    self._read_exact(n, self.timeout_ms)  # discard block
                skipped += 1
                if skipped > MAX_SKIPPED:
                    raise ShellError(
                        f"{skipped} stale frames, last seq "
                        f"{frame['sequence']} wanted {sequence}"
                    )
                continue

            if frame["command"] != expect_cmd:
                raise ShellError(
                    f"reply command {frame['command']} != {expect_cmd}"
                )

            if frame["flags"] & 2:
                n = frame["payload_length"]
                if n > MAX_BLOCK:
                    raise ShellError(f"reply block too large: {n}")
                want_crc = struct.unpack_from("<I", frame["payload"], 0)[0]
                block = self._read_exact(n, self.timeout_ms)
                if len(block) != n:
                    raise ShellError(f"short block: {len(block)}/{n}")
                if crc32(block) != want_crc:
                    raise ShellError("reply block CRC mismatch")
                return block, frame["status"]

            out.extend(frame["payload"][: min(frame["payload_length"], PAYLOAD)])
            if not (frame["flags"] & 1):
                return bytes(out), frame["status"]

    def _exchange_once(
        self, command: int, payload: bytes, expect_cmd: int
    ) -> tuple[bytes, int]:
        sequence = self._next_sequence()
        tx = build_frame(sequence, command, payload)
        sent = self.dev.write(EP_OUT, tx, timeout=self.timeout_ms)
        if sent != len(tx):
            raise ShellError(f"OUT short: {sent}/{len(tx)}")
        data, status = self._collect(sequence, expect_cmd)
        if status != 0:
            raise ShellError(f"camera status {status}")
        return data, status

    def exchange(self, command: int, payload: bytes, expect_cmd: int) -> bytes:
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                data, _ = self._exchange_once(command, payload, expect_cmd)
                return data
            except self._usb_error as exc:
                last = exc
                if self._is_libusb_error(exc, LIBUSB_ERROR_NO_DEVICE):
                    raise ShellError("camera disappeared (NO_DEVICE)") from exc
                if self._is_libusb_error(exc, LIBUSB_ERROR_PIPE):
                    self._clear_halt(EP_IN)
                    self._clear_halt(EP_OUT)
                else:
                    self.drain_in()
                if attempt < self.retries:
                    time.sleep(0.05)
            except ShellError as exc:
                last = exc
                self.drain_in()
                if attempt < self.retries:
                    time.sleep(0.05)
        raise ShellError(f"failed after {self.retries} attempts: {last}") from last

    # -- public shell helpers -------------------------------------------

    def sh(self, line: str) -> str:
        _check_line(line)
        payload = b"shl " + line.encode("latin-1")
        data = self.exchange(CMD_SHL, payload, CMD_SHL)
        return data.decode("latin-1").rstrip("\x00")

    def mem_get(self, addr: int, size: int = 4) -> int:
        if int(size) <= 0:
            raise ShellError(f"invalid size {size}")
        address = int(addr)
        reply = self.sh(f"mem get 0x{address:08X},,{int(size)}")
        return _parse_mem_reply(reply, address)

    def version(self) -> str:
        return self.sh("version").strip()

    def status(self, name: str = "") -> str:
        line = "status get" + (f" {name}" if name else "")
        return self.sh(line).strip()


# -- factory -------------------------------------------------------------


def open_session(backend: str | None = None, timeout_ms: int | None = None):
    """Open a session for ``backend`` (or the platform default).

    ``backend`` is one of :data:`BACKENDS`.  Unknown names raise ``ValueError``
    so the CLI can turn them into a usage error.
    """
    name = (backend or default_backend()).lower()
    if name == "daemon":
        return DaemonSession(timeout_ms=timeout_ms)
    if name == "direct":
        return DirectSession(
            timeout_ms=int(timeout_ms or DEFAULT_TIMEOUT_MS)
        )
    allowed = ", ".join(BACKENDS)
    raise ValueError(f"unknown backend {backend!r} (choose from: {allowed})")
