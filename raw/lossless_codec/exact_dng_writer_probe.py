#!/usr/bin/env python3
"""Build, arm, inspect, or restore the exact CinemaDNG writer probe.

The live operations talk only through fpSup-v1/fp_usb_shell/host/fpsh.  Arming
is deliberately ordered so the hook instruction is the final write.  Every
code/state write is read back, and an unexpected hook word is never replaced.

Examples:

    ./exact_dng_writer_probe.py arm --dry-run
    ./exact_dng_writer_probe.py arm
    ./exact_dng_writer_probe.py status
    ./exact_dng_writer_probe.py restore
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import re
import struct
import subprocess
import sys
from collections.abc import Callable


HOOK_SITE = 0xC0722AFC
HOOK_ORIG = 0xEBFDE061
REAL_WRITE = 0xC069AC88
CONTEXT_ADDRESS = HOOK_SITE - 12
HOOK_CONTEXT_INDEX = 3
EXPECTED_CONTEXT = (
    0xE1A0100D,  # C0722AF0: mov r1, sp
    0xE1A0000A,  # C0722AF4: mov r0, r10
    0xE3A02002,  # C0722AF8: mov r2, #2
    HOOK_ORIG,   # C0722AFC: bl  C069AC88
    0xE28DD008,  # C0722B00: add sp, sp, #8
    0xE8BD84F0,  # C0722B04: pop {r4-r7,r10,pc}
)
STATE = 0xC072F700
STATE_WORDS = 9
CODE = 0xC072F800
CODE_LIMIT = 0xC072FA00
DONE_MAGIC = 0x454E4F44
EXPECTED_LR = HOOK_SITE + 4

SOURCE = pathlib.Path(__file__).with_name("exact_dng_writer_probe.S")


def _find_default_fpsup() -> pathlib.Path:
    """Find the checkout that owns this probe, with a legacy-tree fallback."""
    source = pathlib.Path(__file__).resolve()
    for parent in source.parents:
        if (parent / "fp_usb_shell" / "armasm.py").is_file():
            return parent
    return source.parents[2] / "fpSup-v1"


DEFAULT_FPSUP = _find_default_fpsup()
WORD_RE = re.compile(r"A:0x([0-9A-Fa-f]+),\s*D:0x([0-9A-Fa-f]+)")

STATE_FIELDS = (
    "count",
    "first_r0",
    "first_r1",
    "first_r2",
    "first_lr",
    "segment_buffer",
    "segment_length",
    "done",
    "restored_word",
)
S_COUNT = 0
S_DONE = 7
S_RESTORED = 8


class ProbeError(RuntimeError):
    """A refusal or verified transport failure."""


def arm_bl(site: int, target: int) -> int:
    delta = target - site - 8
    if delta & 3:
        raise ProbeError("BL target is not word aligned")
    displacement = delta >> 2
    if not -(1 << 23) <= displacement < (1 << 23):
        raise ProbeError("BL target is outside ARM's 24-bit branch range")
    return 0xEB000000 | (displacement & 0x00FFFFFF)


HOOK_ARMED = arm_bl(HOOK_SITE, CODE)
if HOOK_ARMED != 0xEB00333F:
    raise AssertionError(f"unexpected hook encoding 0x{HOOK_ARMED:08X}")


def load_assembler(fpsup: pathlib.Path) -> tuple[Callable[[pathlib.Path], bytes], Callable]:
    module_path = fpsup / "fp_usb_shell" / "armasm.py"
    if not module_path.is_file():
        raise ProbeError(f"armasm.py not found at {module_path}")
    spec = importlib.util.spec_from_file_location("fpsup_armasm", module_path)
    if spec is None or spec.loader is None:
        raise ProbeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.assemble, module.symbols


def build_probe(fpsup: pathlib.Path) -> bytes:
    assemble, symbols = load_assembler(fpsup)
    code = assemble(SOURCE)
    syms = symbols(SOURCE)
    if syms.get("probe_entry") != 0:
        raise ProbeError(f"probe_entry is not at offset zero: {syms.get('probe_entry')}")
    if len(code) & 3:
        raise ProbeError("assembled probe is not word aligned")
    if CODE + len(code) > CODE_LIMIT:
        raise ProbeError(
            f"probe 0x{CODE:08X}..0x{CODE + len(code):08X} exceeds "
            f"0x{CODE_LIMIT:08X}"
        )
    return code


class CameraShell:
    def __init__(self, fpsh: pathlib.Path):
        if not fpsh.is_file():
            raise ProbeError(f"fpsh not found at {fpsh}")
        self.fpsh = fpsh

    def command(self, *parts: str) -> str:
        try:
            result = subprocess.run(
                [str(self.fpsh), *parts],
                capture_output=True,
                text=True,
                timeout=75,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProbeError(f"fpsh failed: {exc}") from exc
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or "no reply"
            raise ProbeError(f"fpsh {' '.join(parts)}: {detail}")
        return result.stdout

    def read_words(self, address: int, count: int, attempts: int = 4) -> list[int]:
        seen: dict[int, int] = {}
        for _ in range(attempts):
            output = self.command("mem", "get", f"0x{address:08X},,0x{count * 4:X}")
            for addr_text, data_text in WORD_RE.findall(output):
                seen[int(addr_text, 16)] = int(data_text, 16)
            if all(address + index * 4 in seen for index in range(count)):
                return [seen[address + index * 4] for index in range(count)]
        missing = [
            f"0x{address + index * 4:08X}"
            for index in range(count)
            if address + index * 4 not in seen
        ]
        raise ProbeError("mem get omitted " + ", ".join(missing))

    def read_word(self, address: int) -> int:
        return self.read_words(address, 1)[0]

    def set_word(self, address: int, value: int) -> None:
        self.command("mem", "set", f"0x{address:08X}", f"0x{value:08X}")

    def write_words_verified(
        self, address: int, values: list[int], attempts: int = 8
    ) -> None:
        pending = list(range(len(values)))
        for _ in range(attempts):
            for index in pending:
                self.set_word(address + index * 4, values[index])
            observed = self.read_words(address, len(values))
            pending = [
                index for index, value in enumerate(values) if observed[index] != value
            ]
            if not pending:
                return
        locations = ", ".join(f"0x{address + i * 4:08X}" for i in pending)
        raise ProbeError(f"write verification failed at {locations}")

    def write_word_verified(self, address: int, value: int, attempts: int = 8) -> None:
        self.write_words_verified(address, [value], attempts)


def words_from(code: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(code) // 4}I", code))


def describe_build(code: bytes, show_words: bool = False) -> None:
    print(f"source : {SOURCE}")
    print(f"code   : {len(code)} bytes, 0x{CODE:08X}..0x{CODE + len(code):08X}")
    print(f"state  : 0x{STATE:08X}..0x{STATE + STATE_WORDS * 4:08X}")
    print(f"site   : 0x{HOOK_SITE:08X}, require 0x{HOOK_ORIG:08X}")
    print(
        f"guard  : {len(EXPECTED_CONTEXT)} verified words, "
        f"0x{CONTEXT_ADDRESS:08X}.."
        f"0x{CONTEXT_ADDRESS + len(EXPECTED_CONTEXT) * 4:08X}"
    )
    print(f"arm    : 0x{HOOK_ARMED:08X} (BL 0x{CODE:08X})")
    print(f"real   : 0x{REAL_WRITE:08X}")
    if show_words:
        for index, word in enumerate(words_from(code)):
            print(f"  0x{CODE + index * 4:08X}: 0x{word:08X}")


def dry_run_restore() -> None:
    print(f"would read 0x{HOOK_SITE:08X}")
    print(f"would only replace 0x{HOOK_ARMED:08X} with 0x{HOOK_ORIG:08X}")
    print("would read the word back and retry until verified")


def restore_after_failed_arm(shell: CameraShell) -> None:
    """Put back the word we verified immediately before our arm attempt.

    This is intentionally stronger than the public ``restore`` command.  An
    unknown word here arose while this process owned an arm transaction whose
    starting value was verified as HOOK_ORIG, so leaving it in place is less
    safe than restoring the known firmware instruction.
    """
    try:
        shell.write_word_verified(HOOK_SITE, HOOK_ORIG)
    except ProbeError as exc:
        raise ProbeError(
            "could not verify recovery of the hook site; power-cycle the camera"
        ) from exc


def verify_call_context(
    shell: CameraShell, allowed_hook_words: tuple[int, ...] = (HOOK_ORIG,)
) -> list[int]:
    """Refuse a different firmware/call site before writing executable code.

    The BL word alone already encodes both source and destination, but checking
    the three argument-setup words and the two return-path words makes an
    accidental firmware/site mismatch much harder to accept.
    """
    observed = shell.read_words(CONTEXT_ADDRESS, len(EXPECTED_CONTEXT))
    differences: list[str] = []
    for index, (actual, expected) in enumerate(zip(observed, EXPECTED_CONTEXT)):
        address = CONTEXT_ADDRESS + index * 4
        if index == HOOK_CONTEXT_INDEX:
            if actual not in allowed_hook_words:
                allowed = "/".join(f"0x{word:08X}" for word in allowed_hook_words)
                differences.append(f"0x{address:08X}=0x{actual:08X} (want {allowed})")
        elif actual != expected:
            differences.append(
                f"0x{address:08X}=0x{actual:08X} (want 0x{expected:08X})"
            )
    if differences:
        raise ProbeError("call-site context mismatch: " + ", ".join(differences))
    return observed


def arm_site(shell: CameraShell, attempts: int = 8) -> bool:
    """Arm the final word without re-arming a probe that fired during read-back.

    Returns True when the site is observed armed.  False means the call fired
    during this transaction and the probe already restored the original word.
    """
    for _ in range(attempts):
        state = shell.read_words(STATE, STATE_WORDS)
        current = shell.read_word(HOOK_SITE)

        # count is stored before the in-probe restore.  Once it is non-zero, an
        # observed original word is a successful one-shot, not a dropped arm
        # command that should be retried.  If the probe is between count and
        # DONE, keep observing it without writing the site again.
        if state[S_COUNT] != 0:
            if current not in (HOOK_ORIG, HOOK_ARMED):
                restore_after_failed_arm(shell)
                raise ProbeError(
                    f"probe fired but hook became 0x{current:08X}; restored original"
                )
            if state[S_DONE] == DONE_MAGIC and state[S_RESTORED] == HOOK_ORIG:
                if current == HOOK_ARMED:
                    # This can only be a stale/repeated arm. Do not leave it live.
                    restore_after_failed_arm(shell)
                return False
            continue

        if current == HOOK_ARMED:
            return True
        if current != HOOK_ORIG:
            raise ProbeError(
                f"hook changed before arm: 0x{current:08X}; refusing to overwrite it"
            )

        # Close the window between the state read above and the final write. If
        # a previous arm entered the probe in that interval, never re-arm it.
        if shell.read_words(STATE, STATE_WORDS)[S_COUNT] != 0:
            continue
        shell.set_word(HOOK_SITE, HOOK_ARMED)
        try:
            observed = shell.read_word(HOOK_SITE)
        except ProbeError:
            # The next pass first checks both state and site. It can distinguish
            # an armed word, a dropped command, and an already-fired one-shot.
            continue
        if observed == HOOK_ARMED:
            # A probe from an earlier attempt could have entered just before
            # this write. Its count makes this a re-arm, so let the state-aware
            # path above restore it instead of declaring success.
            if shell.read_words(STATE, STATE_WORDS)[S_COUNT] == 0:
                return True
            continue
        if observed != HOOK_ORIG:
            restore_after_failed_arm(shell)
            raise ProbeError(
                f"arm wrote an unexpected 0x{observed:08X}; restored original"
            )
        # It either dropped or fired. The next pass reads state before deciding.

    final_state = shell.read_words(STATE, STATE_WORDS)
    final_site = shell.read_word(HOOK_SITE)
    if (
        final_state[S_COUNT] != 0
        and final_state[S_DONE] == DONE_MAGIC
        and final_state[S_RESTORED] == HOOK_ORIG
        and final_site == HOOK_ORIG
    ):
        return False
    restore_after_failed_arm(shell)
    raise ProbeError("could not verify a stable arm; restored the original word")


def arm_probe(shell: CameraShell, code: bytes) -> None:
    verify_call_context(shell)

    print("writing and verifying probe code")
    shell.write_words_verified(CODE, words_from(code))
    print("clearing and verifying probe state")
    shell.write_words_verified(STATE, [0] * STATE_WORDS)

    verify_call_context(shell)

    print("arming exact call site (final write)")
    armed = arm_site(shell)

    if armed:
        print("armed and verified")
        print("record a 1-2 second FHD CinemaDNG clip, stop, then run: status")
    else:
        print("probe fired during arm and already restored the site; run: status")


def restore_probe(shell: CameraShell) -> None:
    current = shell.read_word(HOOK_SITE)
    if current == HOOK_ORIG:
        print(f"already restored: 0x{HOOK_SITE:08X} = 0x{HOOK_ORIG:08X}")
        return
    if current != HOOK_ARMED:
        raise ProbeError(
            f"refusing to overwrite unknown hook word 0x{current:08X} at "
            f"0x{HOOK_SITE:08X}"
        )
    verify_call_context(shell, (HOOK_ORIG, HOOK_ARMED))
    shell.write_word_verified(HOOK_SITE, HOOK_ORIG)
    print(f"restored and verified: 0x{HOOK_SITE:08X} = 0x{HOOK_ORIG:08X}")


def show_status(shell: CameraShell) -> None:
    site = shell.read_word(HOOK_SITE)
    values = shell.read_words(STATE, STATE_WORDS)
    if site == HOOK_ORIG:
        site_state = "original/restored"
    elif site == HOOK_ARMED:
        site_state = "armed; probe has not restored it yet"
    else:
        site_state = "UNKNOWN -- do not overwrite automatically"
    print(f"hook            0x{site:08X}  {site_state}")
    for name, value in zip(STATE_FIELDS, values):
        note = ""
        if name == "first_lr":
            note = "  expected" if value == EXPECTED_LR else "  UNEXPECTED"
        elif name == "done":
            note = "  DONE" if value == DONE_MAGIC else "  not complete"
        elif name == "restored_word":
            note = "  verified" if value == HOOK_ORIG else "  UNEXPECTED"
        print(f"{name:16s} 0x{value:08X}{note}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the live FHD C0722AFC CinemaDNG writer probe."
    )
    parser.add_argument(
        "--fpsup",
        type=pathlib.Path,
        default=DEFAULT_FPSUP,
        help=f"fpSup-v1 checkout (default: {DEFAULT_FPSUP})",
    )
    parser.add_argument(
        "--fpsh",
        type=pathlib.Path,
        default=None,
        help="host/fpsh path; defaults below --fpsup",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="perform no USB reads or writes",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("arm", "build, load, verify, and arm the one-shot probe"),
        ("status", "read the hook and captured state"),
        ("restore", "restore the original word if this probe is still armed"),
    ):
        child = subparsers.add_parser(action, help=help_text)
        child.add_argument(
            "--dry-run",
            action="store_true",
            default=argparse.SUPPRESS,
            help="perform no USB reads or writes",
        )
    return parser


def main() -> int:
    args = make_parser().parse_args()
    fpsup = args.fpsup.resolve()
    fpsh = (
        args.fpsh.resolve()
        if args.fpsh is not None
        else fpsup / "fp_usb_shell" / "host" / "fpsh"
    )

    try:
        if args.action == "arm":
            code = build_probe(fpsup)
            describe_build(code, show_words=args.dry_run)
            if args.dry_run:
                print("dry-run: no camera reads or writes performed")
                return 0
            arm_probe(CameraShell(fpsh), code)
            return 0

        if args.dry_run:
            if args.action == "status":
                print(f"would read hook 0x{HOOK_SITE:08X} and state 0x{STATE:08X}")
            else:
                dry_run_restore()
            print("dry-run: no camera reads or writes performed")
            return 0

        shell = CameraShell(fpsh)
        if args.action == "status":
            show_status(shell)
        else:
            restore_probe(shell)
        return 0
    except ProbeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
