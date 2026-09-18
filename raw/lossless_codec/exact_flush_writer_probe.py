#!/usr/bin/env python3
"""Manage the one-shot, read-only CinemaDNG final-flush probe.

The probe wraps only the V5.02 call at ``0xC03A5490``.  It records the fully
built FileSplitWriter, restores the firmware instruction before doing any
dereference, calls the original flush, and returns its 64-bit result unchanged.

No action talks to the camera on import.  ``arm --dry-run`` assembles and
validates the image without constructing a CameraShell.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

import exact_dng_writer_probe as base


DEFAULT_FPSUP = base.DEFAULT_FPSUP
arm_bl = base.arm_bl
words_from = base.words_from

HOOK_SITE = 0xC03A5490
HOOK_ORIG = 0xEB0BD652
REAL_FLUSH = 0xC069ADE0
EXPECTED_LR = HOOK_SITE + 4

CONTEXT_ADDRESS = HOOK_SITE - 12
HOOK_CONTEXT_INDEX = 3
EXPECTED_CONTEXT = (
    0xE320F000,  # C03A5484: nop
    0xE1A01004,  # C03A5488: mov r1, r4
    0xE28D0020,  # C03A548C: add r0, sp, #0x20
    HOOK_ORIG,   # C03A5490: bl  C069ADE0
    0xE1A06000,  # C03A5494: mov r6, r0
    0xE1A07001,  # C03A5498: mov r7, r1
    0xE5DB300D,  # C03A549C: ldrb r3, [fp, #0xd]
    0xE3530000,  # C03A54A0: cmp r3, #0
)

# Keep this outside the shell template, whose exclusive upper bound is
# C0730000.  Current OG3K starts at C0730700, leaving this exact 0x700-byte gap;
# old reqlog/keylog/fmthook experiments did borrow it, so an all-zero survey is
# still a hard arm gate rather than documentation advice.
CODE = 0xC0730000
CODE_LIMIT = 0xC0730600
STATE = 0xC0730600
STATE_WORDS = 0x100 // 4
STATE_LIMIT = STATE + STATE_WORDS * 4

SOURCE = pathlib.Path(__file__).with_name("exact_flush_writer_probe.S")

DONE_MAGIC = 0x454E4F44
ENTERED_MAGIC = 0x52544E45
TIFF_MAGIC = 0x002A4949
FHD_DNG_LENGTH = 0x00318200
NODE_KIND = 2
SHAPE_ALL = 0x1FF

S_COUNT = 0x00 // 4
S_WRITER = 0x04 // 4
S_ARG1 = 0x08 // 4
S_LR = 0x0C // 4
S_WRITER_0 = 0x10 // 4
S_WRITER_4 = 0x14 // 4
S_WRITER_8 = 0x18 // 4
S_HEAD = 0x1C // 4
S_NODE_COUNT = 0x20 // 4
S_EXPECTED_NODE = 0x24 // 4
S_NODE_NEXT = 0x28 // 4
S_NODE_BUFFER = 0x2C // 4
S_NODE_LENGTH = 0x30 // 4
S_NODE_KIND = 0x34 // 4
S_DNG_MAGIC = 0x38 // 4
S_SHAPE_FLAGS = 0x3C // 4
S_RESTORED = 0x40 // 4
S_T0 = 0x44 // 4
S_T1 = 0x48 // 4
S_RETURN_LOW = 0x4C // 4
S_RETURN_HIGH = 0x50 // 4
S_ENTERED = 0x54 // 4
S_DONE = 0x58 // 4

STATE_FIELDS = {
    0x00: "count",
    0x04: "writer",
    0x08: "flush_arg1",
    0x0C: "first_lr",
    0x10: "writer_word_0",
    0x14: "writer_word_4",
    0x18: "writer_word_8",
    0x1C: "head",
    0x20: "node_count",
    0x24: "expected_node",
    0x28: "node_next",
    0x2C: "node_buffer",
    0x30: "node_length",
    0x34: "node_kind",
    0x38: "dng_magic",
    0x3C: "shape_flags",
    0x40: "restored_word",
    0x44: "flush_t0",
    0x48: "flush_t1",
    0x4C: "return_low",
    0x50: "return_high",
    0x54: "entered",
    0x58: "done",
}

SHAPE_REQUIRED_INDICES = (
    S_COUNT,
    S_WRITER,
    S_LR,
    S_WRITER_8,
    S_HEAD,
    S_NODE_COUNT,
    S_EXPECTED_NODE,
    S_NODE_NEXT,
    S_NODE_BUFFER,
    S_NODE_LENGTH,
    S_NODE_KIND,
    S_DNG_MAGIC,
    S_SHAPE_FLAGS,
    S_RESTORED,
    S_ENTERED,
    S_DONE,
)


class ProbeError(base.ProbeError):
    """A build refusal or verified transport failure."""


HOOK_ARMED = base.arm_bl(HOOK_SITE, CODE)
if HOOK_ARMED != 0xEB0E2ADA:
    raise AssertionError(f"unexpected hook encoding 0x{HOOK_ARMED:08X}")
if base.arm_bl(HOOK_SITE, REAL_FLUSH) != HOOK_ORIG:
    raise AssertionError("recorded V5.02 call instruction does not target REAL_FLUSH")


def build_probe(fpsup: pathlib.Path) -> bytes:
    assemble, symbols = base.load_assembler(fpsup)
    code = assemble(SOURCE)
    syms = symbols(SOURCE)
    if syms.get("probe_entry") != 0:
        raise ProbeError(f"probe_entry is not at offset zero: {syms.get('probe_entry')}")
    if not code or len(code) & 3:
        raise ProbeError("assembled probe is empty or not word aligned")
    if CODE + len(code) > CODE_LIMIT:
        raise ProbeError(
            f"probe 0x{CODE:08X}..0x{CODE + len(code):08X} exceeds "
            f"0x{CODE_LIMIT:08X}"
        )
    return code


def verify_call_context(
    shell: base.CameraShell, allowed_hook_words: tuple[int, ...] = (HOOK_ORIG,)
) -> list[int]:
    """Require the exact V5.02 argument setup and return-value consumers."""
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


def _nonzero_words(values: list[int]) -> list[tuple[int, int]]:
    return [(index, value) for index, value in enumerate(values) if value != 0]


def survey_install_regions(shell: base.CameraShell) -> dict[str, list[int]]:
    """Read every reserved word; arming requires both regions to be all zero."""
    code_words = shell.read_words(CODE, (CODE_LIMIT - CODE) // 4)
    state_words = shell.read_words(STATE, STATE_WORDS)
    return {"code": code_words, "state": state_words}


def require_clear_install_regions(shell: base.CameraShell) -> None:
    regions = survey_install_regions(shell)
    occupied: list[str] = []
    for name, address in (("code", CODE), ("state", STATE)):
        nonzero = _nonzero_words(regions[name])
        if nonzero:
            index, value = nonzero[0]
            occupied.append(
                f"{name} first non-zero at 0x{address + index * 4:08X}="
                f"0x{value:08X} ({len(nonzero)} non-zero words)"
            )
    if occupied:
        raise ProbeError(
            "reserved shell-template region is occupied: " + "; ".join(occupied)
        )


def describe_survey(regions: dict[str, list[int]]) -> bool:
    clear = True
    for name, address, limit in (
        ("code", CODE, CODE_LIMIT),
        ("state", STATE, STATE_LIMIT),
    ):
        nonzero = _nonzero_words(regions[name])
        if nonzero:
            clear = False
            index, value = nonzero[0]
            detail = (
                f"OCCUPIED: {len(nonzero)} non-zero; first "
                f"0x{address + index * 4:08X}=0x{value:08X}"
            )
        else:
            detail = "clear"
        print(f"{name:5s}  0x{address:08X}..0x{limit:08X}  {detail}")
    return clear


def restore_after_failed_arm(shell: base.CameraShell) -> None:
    try:
        shell.write_word_verified(HOOK_SITE, HOOK_ORIG)
    except base.ProbeError as exc:
        raise ProbeError(
            "could not verify recovery of the hook site; power-cycle the camera"
        ) from exc


def arm_site(shell: base.CameraShell, attempts: int = 8) -> bool:
    """Make the branch the final write and never re-arm a fired one-shot."""
    for _ in range(attempts):
        state = shell.read_words(STATE, STATE_WORDS)
        current = shell.read_word(HOOK_SITE)

        if state[S_COUNT] != 0:
            if current == HOOK_ARMED:
                restore_after_failed_arm(shell)
            elif current != HOOK_ORIG:
                restore_after_failed_arm(shell)
                raise ProbeError(
                    f"probe fired but hook became 0x{current:08X}; restored original"
                )
            return False

        if current == HOOK_ARMED:
            return True
        if current != HOOK_ORIG:
            raise ProbeError(
                f"hook changed before arm: 0x{current:08X}; refusing to overwrite it"
            )

        if shell.read_words(STATE, STATE_WORDS)[S_COUNT] != 0:
            continue
        shell.set_word(HOOK_SITE, HOOK_ARMED)
        try:
            observed = shell.read_word(HOOK_SITE)
        except base.ProbeError:
            continue
        if observed == HOOK_ARMED:
            if shell.read_words(STATE, STATE_WORDS)[S_COUNT] == 0:
                return True
            restore_after_failed_arm(shell)
            return False
        if observed == HOOK_ORIG:
            if shell.read_words(STATE, STATE_WORDS)[S_COUNT] != 0:
                return False
            continue
        restore_after_failed_arm(shell)
        raise ProbeError(
            f"arm wrote an unexpected 0x{observed:08X}; restored original"
        )

    final_state = shell.read_words(STATE, STATE_WORDS)
    final_site = shell.read_word(HOOK_SITE)
    if final_state[S_COUNT] != 0 and final_site == HOOK_ORIG:
        return False
    restore_after_failed_arm(shell)
    raise ProbeError("could not verify a stable arm; restored the original word")


def arm_probe(shell: base.CameraShell, code: bytes) -> None:
    # All refusal checks precede the first write.
    verify_call_context(shell)
    require_clear_install_regions(shell)

    print("writing and verifying final-flush probe code")
    shell.write_words_verified(CODE, base.words_from(code))
    print("clearing and verifying final-flush state")
    shell.write_words_verified(STATE, [0] * STATE_WORDS)

    verify_call_context(shell)
    print("arming exact final-flush call (final write)")
    armed = arm_site(shell)
    if armed:
        print("armed and verified; the next matching FHD frame will self-restore it")
    else:
        print("probe fired during arm and restored the site; run: status")


def restore_probe(shell: base.CameraShell) -> None:
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


def shape_success(values: list[int] | tuple[int, ...]) -> bool:
    if len(values) != STATE_WORDS:
        return False
    writer = values[S_WRITER]
    return (
        values[S_COUNT] == 1
        and writer != 0
        and values[S_LR] == EXPECTED_LR
        and values[S_WRITER_8] & 0xFF != 0
        and values[S_NODE_COUNT] == 1
        and values[S_EXPECTED_NODE] == writer + 0x0C
        and values[S_HEAD] == writer + 0x0C
        and values[S_NODE_NEXT] == 0
        and values[S_NODE_BUFFER] != 0
        and values[S_NODE_LENGTH] == FHD_DNG_LENGTH
        and values[S_NODE_KIND] == NODE_KIND
        and values[S_DNG_MAGIC] == TIFF_MAGIC
        and values[S_SHAPE_FLAGS] == SHAPE_ALL
        and values[S_RESTORED] == HOOK_ORIG
        and values[S_ENTERED] == ENTERED_MAGIC
        and values[S_DONE] == DONE_MAGIC
    )


def success_shape_fixture(writer: int = 0xC3A6F3BC) -> tuple[int, ...]:
    """Return a synthetic exact-FHD result for host-only tests."""
    values = [0] * STATE_WORDS
    values[S_COUNT] = 1
    values[S_WRITER] = writer
    values[S_ARG1] = 0xC3A6F37C
    values[S_LR] = EXPECTED_LR
    values[S_WRITER_8] = 1
    values[S_HEAD] = writer + 0x0C
    values[S_NODE_COUNT] = 1
    values[S_EXPECTED_NODE] = writer + 0x0C
    values[S_NODE_BUFFER] = 0x53B02C00
    values[S_NODE_LENGTH] = FHD_DNG_LENGTH
    values[S_NODE_KIND] = NODE_KIND
    values[S_DNG_MAGIC] = TIFF_MAGIC
    values[S_SHAPE_FLAGS] = SHAPE_ALL
    values[S_RESTORED] = HOOK_ORIG
    values[S_T0] = 100
    values[S_T1] = 200
    values[S_ENTERED] = ENTERED_MAGIC
    values[S_DONE] = DONE_MAGIC
    return tuple(values)


def describe_build(code: bytes, show_words: bool = False) -> None:
    print(f"source : {SOURCE}")
    print(f"sha256 : {hashlib.sha256(code).hexdigest()}")
    print(f"code   : {len(code)} bytes, 0x{CODE:08X}..0x{CODE + len(code):08X}")
    print(f"reserve: 0x{CODE:08X}..0x{CODE_LIMIT:08X} (must survey all zero)")
    print(f"state  : 0x{STATE:08X}..0x{STATE_LIMIT:08X} (must survey all zero)")
    print(f"site   : 0x{HOOK_SITE:08X}, require 0x{HOOK_ORIG:08X}")
    print(
        f"guard  : {len(EXPECTED_CONTEXT)} verified words, "
        f"0x{CONTEXT_ADDRESS:08X}.."
        f"0x{CONTEXT_ADDRESS + len(EXPECTED_CONTEXT) * 4:08X}"
    )
    print(f"arm    : 0x{HOOK_ARMED:08X} (BL 0x{CODE:08X})")
    print(f"real   : 0x{REAL_FLUSH:08X}; return r1:r0 is preserved")
    print("effect : read-only writer inspection; no encode, allocation, or DNG mutation")
    if show_words:
        for index, word in enumerate(base.words_from(code)):
            print(f"  0x{CODE + index * 4:08X}: 0x{word:08X}")


def show_status(shell: base.CameraShell) -> None:
    site = shell.read_word(HOOK_SITE)
    values = shell.read_words(STATE, STATE_WORDS)
    if site == HOOK_ORIG:
        site_state = "original/restored"
    elif site == HOOK_ARMED:
        site_state = "armed; not yet self-restored"
    else:
        site_state = "UNKNOWN -- do not overwrite automatically"
    print(f"hook             0x{site:08X}  {site_state}")
    for offset in range(0, STATE_WORDS * 4, 4):
        name = STATE_FIELDS.get(offset, f"reserved_{offset:02x}")
        value = values[offset // 4]
        note = ""
        if offset == S_LR * 4:
            note = "  expected" if value == EXPECTED_LR else "  UNEXPECTED"
        elif offset == S_SHAPE_FLAGS * 4:
            note = "  exact FHD shape" if value == SHAPE_ALL else "  incomplete"
        elif offset == S_RESTORED * 4:
            note = "  verified" if value == HOOK_ORIG else "  UNEXPECTED"
        elif offset == S_ENTERED * 4:
            note = "  entered" if value == ENTERED_MAGIC else "  not entered"
        elif offset == S_DONE * 4:
            note = "  DONE" if value == DONE_MAGIC else "  not returned"
        print(f"{name:18s} 0x{value:08X}{note}")
    elapsed = (values[S_T1] - values[S_T0]) & 0xFFFFFFFF
    print(f"flush_elapsed_us   {elapsed}")
    print(f"shape              {'PASS' if shape_success(values) else 'NOT PROVEN'}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the V5.02 C03A5490 one-shot final-flush writer probe."
    )
    parser.add_argument(
        "--fpsup",
        type=pathlib.Path,
        default=base.DEFAULT_FPSUP,
        help=f"fpSup checkout (default: {base.DEFAULT_FPSUP})",
    )
    parser.add_argument(
        "--fpsh", type=pathlib.Path, default=None, help="fpsh path; defaults below --fpsup"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="perform no USB reads or writes"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("arm", "build, survey, load, verify, and arm the one-shot probe"),
        ("survey", "read the hook/context and reserved regions without writing"),
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
                print("dry-run: no camera or USB reads/writes performed")
                return 0
            arm_probe(base.CameraShell(fpsh), code)
            return 0

        if args.dry_run:
            if args.action == "survey":
                print(
                    f"would verify context 0x{CONTEXT_ADDRESS:08X} and survey "
                    f"0x{CODE:08X}..0x{STATE_LIMIT:08X}"
                )
            elif args.action == "status":
                print(f"would read hook 0x{HOOK_SITE:08X} and state 0x{STATE:08X}")
            else:
                print(f"would only restore 0x{HOOK_ARMED:08X} to 0x{HOOK_ORIG:08X}")
            print("dry-run: no camera or USB reads/writes performed")
            return 0

        shell = base.CameraShell(fpsh)
        if args.action == "survey":
            verify_call_context(shell, (HOOK_ORIG, HOOK_ARMED))
            clear = describe_survey(survey_install_regions(shell))
            print(f"hook   0x{HOOK_SITE:08X} = 0x{shell.read_word(HOOK_SITE):08X}")
            return 0 if clear else 1
        if args.action == "status":
            show_status(shell)
        else:
            restore_probe(shell)
        return 0
    except (ProbeError, base.ProbeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
