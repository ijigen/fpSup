#!/usr/bin/env python3
"""Manage exact-site power/scratch preflights; inspect encode dry-runs.

The power and scratch preflights are live-capable, but this module never runs
either on import.
The encode-and-discard image is intentionally build/dry-run only.  It does not
yet consume and free the retained scratch allocation, so a non-dry-run
``encode`` request is refused before a CameraShell is constructed.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import struct
import sys

import exact_dng_writer_probe as base


STATE = base.STATE
STATE_WORDS = 0x100 // 4
CODE = base.CODE
PREFLIGHT_CODE_LIMIT = 0xC072FB00
SCRATCH_CODE_LIMIT = 0xC072FD00
ENCODE_DESIGN_LIMIT = 0xC072FD00

PREFLIGHT_SOURCE = pathlib.Path(__file__).with_name("exact_writer_power_preflight.S")
SCRATCH_SOURCE = pathlib.Path(__file__).with_name(
    "exact_writer_scratch_preflight.S"
)
ENCODE_SOURCE = pathlib.Path(__file__).with_name(
    "single_frame_encode_discard_probe.S"
)

PREFLIGHT_MAGIC = 0x52575050
SCRATCH_MAGIC = 0x434F4C41
GUARD_MAGIC = 0xA55AA55A
PHASE_PREFLIGHT = 0
PHASE_SCRATCH = 1
DONE_MAGIC = base.DONE_MAGIC

ALLOC_SIZE = 0x400000
WORK_CAP = 0x305000
TABLE_OFFSET = 0x306000
TABLE_TEMP_OFFSET = 0x306400
TABLE_BYTES = 12 * 4

S_COUNT = 0x00 // 4
S_R2 = 0x0C // 4
S_LR = 0x10 // 4
S_BUFFER = 0x14 // 4
S_LENGTH = 0x18 // 4
S_DONE = 0x1C // 4
S_RESTORED = 0x20 // 4
S_PHASE = 0x24 // 4
S_STAGE = 0x28 // 4
S_ERROR = 0x2C // 4
S_CODEC_MODE = 0x30 // 4          # power-preflight interpretation
S_SOURCE = 0x34 // 4              # power-preflight interpretation
S_CLEANUP_ERROR = 0x38 // 4       # power-preflight interpretation
S_ALLOCATOR = 0x30 // 4           # scratch-preflight interpretation
S_HANDLE = 0x34 // 4
S_ALLOC_END = 0x38 // 4
S_WORK_BASE = 0x3C // 4
S_WORK_END = 0x40 // 4
S_WORK_GUARD = 0x44 // 4
S_TABLE_BASE = 0x48 // 4
S_TABLE_TEMP = 0x4C // 4
S_SCRATCH_SOURCE = 0x50 // 4
S_SCRATCH_CODEC_MODE = 0x54 // 4
S_T0 = 0x50 // 4
S_T1 = 0x54 // 4
S_PWR_ON = 0x68 // 4
S_CLK_ON = 0x6C // 4
S_CLK_OFF = 0x70 // 4
S_PWR_OFF = 0x74 // 4
S_GUARD_WORK = 0x94 // 4
S_GUARD_TABLE = 0x98 // 4
S_GUARD_TEMP = 0x9C // 4
S_PREFLIGHT = 0xD4 // 4
S_SCRATCH_MAGIC = 0xD8 // 4
S_END_GUARD = 0xDC // 4
S_GUARD_END = 0xE0 // 4
S_TABLE_GUARD = 0xE4 // 4
S_TEMP_GUARD = 0xE8 // 4

STATE_FIELDS = {
    0x00: "count",
    0x04: "first_r0",
    0x08: "first_r1",
    0x0C: "first_r2",
    0x10: "first_lr",
    0x14: "buffer",
    0x18: "segment_length",
    0x1C: "done",
    0x20: "restored_word",
    0x24: "phase",
    0x28: "stage",
    0x2C: "error",
    0x30: "codec_mode_or_allocator",
    0x34: "source_or_allocation_handle",
    0x38: "cleanup_error_or_allocation_end",
    0x3C: "work_base",
    0x40: "work_end",
    0x44: "work_guard_address",
    0x48: "size_table_base",
    0x4C: "temporary_table",
    0x50: "source_or_t0",
    0x54: "codec_mode_or_t1",
    0x58: "init_return",
    0x5C: "encode_return",
    0x60: "size_return",
    0x64: "compressed_size_sum",
    0x68: "power_on_return",
    0x6C: "clock_on_return",
    0x70: "clock_off_return",
    0x74: "power_off_return",
    0x78: "header_before",
    0x7C: "header_after",
    0x80: "first_pixel_before",
    0x84: "first_pixel_after",
    0x88: "last_pixel_before",
    0x8C: "last_pixel_after",
    0x90: "segment_length_after",
    0x94: "work_guard_after",
    0x98: "size_table_guard_after",
    0x9C: "temporary_table_guard_after",
    0xA0: "tile_count",
    **{0xA4 + index * 4: f"tile_size_{index}" for index in range(12)},
    0xD4: "power_preflight_magic",
    0xD8: "scratch_preflight_magic",
    0xDC: "allocation_end_guard_address",
    0xE0: "allocation_end_guard_after",
    0xE4: "size_table_guard_address",
    0xE8: "temporary_table_guard_address",
}


class ProbeError(base.ProbeError):
    """A build refusal or inherited verified transport failure."""


def build_image(kind: str, fpsup: pathlib.Path) -> bytes:
    assemble, symbols = base.load_assembler(fpsup)
    if kind == "preflight":
        source = PREFLIGHT_SOURCE
        defines: tuple[str, ...] = ()
        limit = PREFLIGHT_CODE_LIMIT
    elif kind == "scratch":
        source = SCRATCH_SOURCE
        defines = ()
        limit = SCRATCH_CODE_LIMIT
    elif kind == "encode":
        source = ENCODE_SOURCE
        defines = ("PHASE=1",)
        limit = ENCODE_DESIGN_LIMIT
    else:
        raise ProbeError(f"unknown image kind {kind!r}")

    code = assemble(source, defines=defines)
    syms = symbols(source, defines=defines)
    if syms.get("probe_entry") != 0:
        raise ProbeError(f"probe_entry is not at offset zero: {syms.get('probe_entry')}")
    if len(code) & 3:
        raise ProbeError("assembled image is not word aligned")
    if CODE + len(code) > limit:
        raise ProbeError(
            f"{kind} image 0x{CODE:08X}..0x{CODE + len(code):08X} "
            f"exceeds design limit 0x{limit:08X}"
        )
    words = base.words_from(code)
    if words[-2:] != [0xE51FF004, base.REAL_WRITE]:
        raise ProbeError("image does not end in the register-transparent tail-call")
    return code


def describe_image(kind: str, code: bytes, show_words: bool = False) -> None:
    source = {
        "preflight": PREFLIGHT_SOURCE,
        "scratch": SCRATCH_SOURCE,
        "encode": ENCODE_SOURCE,
    }[kind]
    live = kind in ("preflight", "scratch")
    print(f"image  : {kind}")
    print(f"source : {source}")
    print(f"sha256 : {hashlib.sha256(code).hexdigest()}")
    print(f"code   : {len(code)} bytes, 0x{CODE:08X}..0x{CODE + len(code):08X}")
    print(f"state  : 0x{STATE:08X}..0x{STATE + STATE_WORDS * 4:08X}")
    print(f"site   : 0x{base.HOOK_SITE:08X}, require 0x{base.HOOK_ORIG:08X}")
    print(f"arm    : 0x{base.HOOK_ARMED:08X} (final write)")
    if kind == "preflight":
        mode = "live-capable power-only preflight"
    elif kind == "scratch":
        mode = "live-capable scratch-only preflight; requires PPWR proof"
    else:
        mode = "DRY-RUN ONLY"
    print(f"mode   : {mode}")
    if kind in ("scratch", "encode"):
        layout = encode_layout(0)
        print(
            "layout : work [base,+0x305000), table +0x306000, "
            "temporary table +0x306400, allocation 0x400000"
        )
        if not encode_layout_is_safe(layout):
            raise ProbeError("internal encode layout validation failed")
    if not live:
        print("reason : requires reviewed power and retained-scratch preflights")
    if show_words:
        for index, word in enumerate(base.words_from(code)):
            print(f"  0x{CODE + index * 4:08X}: 0x{word:08X}")


def encode_layout(base_address: int) -> dict[str, tuple[int, int]]:
    """Return the half-open ranges used by the dry-run encode design."""
    return {
        "allocation": (base_address, base_address + ALLOC_SIZE),
        "work": (base_address, base_address + WORK_CAP),
        "work_guard": (base_address + WORK_CAP, base_address + WORK_CAP + 4),
        "size_table": (
            base_address + TABLE_OFFSET,
            base_address + TABLE_OFFSET + TABLE_BYTES,
        ),
        "size_table_guard": (
            base_address + TABLE_OFFSET + TABLE_BYTES,
            base_address + TABLE_OFFSET + TABLE_BYTES + 4,
        ),
        "temporary_table": (
            base_address + TABLE_TEMP_OFFSET,
            base_address + TABLE_TEMP_OFFSET + TABLE_BYTES,
        ),
        "temporary_table_guard": (
            base_address + TABLE_TEMP_OFFSET + TABLE_BYTES,
            base_address + TABLE_TEMP_OFFSET + TABLE_BYTES + 4,
        ),
        "allocation_end_guard": (
            base_address + ALLOC_SIZE - 4,
            base_address + ALLOC_SIZE,
        ),
    }


def encode_layout_is_safe(layout: dict[str, tuple[int, int]]) -> bool:
    allocation = layout["allocation"]
    payload_names = tuple(name for name in layout if name != "allocation")
    if allocation[0] & 0x3FF:
        return False
    for name in ("work", "size_table", "temporary_table"):
        if layout[name][0] & 0x3FF:
            return False
    for name in payload_names:
        start, end = layout[name]
        if not allocation[0] <= start < end <= allocation[1]:
            return False
    ordered = sorted((layout[name][0], layout[name][1]) for name in payload_names)
    return all(left_end <= right_start for (_, left_end), (right_start, _) in zip(ordered, ordered[1:]))


def power_preflight_success(values: list[int] | tuple[int, ...]) -> bool:
    return (
        len(values) >= STATE_WORDS
        and values[S_COUNT] >= 1
        and values[S_DONE] == DONE_MAGIC
        and values[S_RESTORED] == base.HOOK_ORIG
        and values[S_PHASE] == PHASE_PREFLIGHT
        and values[S_STAGE] == 7
        and values[S_ERROR] == 0
        and values[S_CLEANUP_ERROR] == 0
        and values[S_CODEC_MODE] == 0
        and values[S_R2] == 2
        and values[S_LR] == base.EXPECTED_LR
        and values[S_BUFFER] != 0
        and values[S_LENGTH] == 0x00318200
        and values[S_SOURCE] != 0
        and values[S_SOURCE] & 0x3FF == 0
        and values[S_PWR_ON] == 0
        and values[S_CLK_ON] == 0
        and values[S_CLK_OFF] == 0
        and values[S_PWR_OFF] == 0
        and values[S_PREFLIGHT] == PREFLIGHT_MAGIC
    )


def require_power_preflight(shell: base.CameraShell) -> list[int]:
    """Read-only proof gate reserved for a future live encode implementation."""
    values = shell.read_words(STATE, STATE_WORDS)
    if not power_preflight_success(values):
        raise ProbeError("no successful exact-writer power preflight in state")
    if shell.read_word(base.HOOK_SITE) != base.HOOK_ORIG:
        raise ProbeError("power preflight hook is not restored")
    base.verify_call_context(shell)
    return values


def retained_scratch_present(values: list[int] | tuple[int, ...]) -> bool:
    """A nonzero retained handle must not be orphaned by clearing this state."""
    return (
        len(values) >= STATE_WORDS
        and values[S_PHASE] == PHASE_SCRATCH
        and (values[S_HANDLE] != 0 or values[S_SCRATCH_MAGIC] == SCRATCH_MAGIC)
    )


def scratch_preflight_success(values: list[int] | tuple[int, ...]) -> bool:
    if len(values) < STATE_WORDS:
        return False
    handle = values[S_HANDLE]
    if not 0x40000000 <= handle < 0x80000000 or handle & 0x3FF:
        return False
    end = handle + ALLOC_SIZE
    if end > 0x80000000:
        return False
    return (
        values[S_COUNT] >= 1
        and values[S_DONE] == DONE_MAGIC
        and values[S_RESTORED] == base.HOOK_ORIG
        and values[S_PHASE] == PHASE_SCRATCH
        and values[S_STAGE] == 7
        and values[S_ERROR] == 0
        and values[S_R2] == 2
        and values[S_LR] == base.EXPECTED_LR
        and values[S_BUFFER] != 0
        and values[S_LENGTH] == 0x00318200
        and values[S_ALLOCATOR] != 0
        and values[S_ALLOC_END] == end
        and values[S_WORK_BASE] == handle
        and values[S_WORK_END] == handle + WORK_CAP
        and values[S_WORK_GUARD] == handle + WORK_CAP
        and values[S_TABLE_BASE] == handle + TABLE_OFFSET
        and values[S_TABLE_TEMP] == handle + TABLE_TEMP_OFFSET
        and values[S_SCRATCH_SOURCE] != 0
        and values[S_SCRATCH_SOURCE] & 0x3FF == 0
        and values[S_SCRATCH_CODEC_MODE] == 0
        and values[S_GUARD_WORK] == GUARD_MAGIC
        and values[S_GUARD_TABLE] == GUARD_MAGIC
        and values[S_GUARD_TEMP] == GUARD_MAGIC
        and values[S_PREFLIGHT] == PREFLIGHT_MAGIC
        and values[S_SCRATCH_MAGIC] == SCRATCH_MAGIC
        and values[S_END_GUARD] == end - 4
        and values[S_GUARD_END] == GUARD_MAGIC
        and values[S_TABLE_GUARD] == handle + TABLE_OFFSET + TABLE_BYTES
        and values[S_TEMP_GUARD] == handle + TABLE_TEMP_OFFSET + TABLE_BYTES
    )


def arm_power_preflight(shell: base.CameraShell, code: bytes) -> None:
    """Use the exact probe's guarded context and final-write transaction."""
    base.verify_call_context(shell)
    current = shell.read_words(STATE, STATE_WORDS)
    if retained_scratch_present(current):
        raise ProbeError(
            "retained scratch is active; encode/free it or power-cycle before "
            "clearing state"
        )
    shell.write_words_verified(CODE, base.words_from(code))
    shell.write_words_verified(STATE, [0] * STATE_WORDS)
    base.verify_call_context(shell)
    armed = base.arm_site(shell)
    if armed:
        print("power-only preflight armed and verified")
        print("record one short FHD CinemaDNG clip, then run: status")
    else:
        print("preflight fired during arm and already restored; run: status")


def arm_scratch_preflight(shell: base.CameraShell, code: bytes) -> None:
    """Chain a retained allocation to a verified PPWR result, once per boot."""
    require_power_preflight(shell)
    seeded_state = [0] * STATE_WORDS
    seeded_state[S_PREFLIGHT] = PREFLIGHT_MAGIC

    shell.write_words_verified(CODE, base.words_from(code))
    shell.write_words_verified(STATE, seeded_state)
    base.verify_call_context(shell)
    armed = base.arm_site(shell)
    if armed:
        print("scratch-only preflight armed and verified")
        print("record one short FHD CinemaDNG clip, then run: status")
    else:
        print("scratch preflight fired during arm and already restored; run: status")


def show_status(shell: base.CameraShell) -> None:
    site = shell.read_word(base.HOOK_SITE)
    values = shell.read_words(STATE, STATE_WORDS)
    if site == base.HOOK_ORIG:
        site_note = "original/restored"
    elif site == base.HOOK_ARMED:
        site_note = "armed"
    else:
        site_note = "UNKNOWN"
    print(f"hook                     0x{site:08X}  {site_note}")
    for offset, name in STATE_FIELDS.items():
        value = values[offset // 4]
        note = ""
        if name == "done":
            note = " DONE" if value == DONE_MAGIC else ""
        elif name == "restored_word":
            note = " verified" if value == base.HOOK_ORIG else ""
        elif name == "power_preflight_magic":
            note = " SUCCESS" if value == PREFLIGHT_MAGIC else ""
        elif name == "scratch_preflight_magic":
            note = " SUCCESS" if value == SCRATCH_MAGIC else ""
        print(f"{name:25s} 0x{value:08X}{note}")
    state_pass = power_preflight_success(values)
    print(
        "power_preflight           "
        + ("PASS" if state_pass and site == base.HOOK_ORIG else "NOT PROVEN")
    )
    scratch_pass = scratch_preflight_success(values)
    print(
        "scratch_preflight         "
        + ("PASS" if scratch_pass and site == base.HOOK_ORIG else "NOT PROVEN")
    )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage exact-writer power/scratch preflights and encode dry-run."
    )
    parser.add_argument("--fpsup", type=pathlib.Path, default=base.DEFAULT_FPSUP)
    parser.add_argument("--fpsh", type=pathlib.Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    actions = parser.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("preflight", "build and arm the power/clock-only one-shot"),
        ("scratch", "reserve and verify the retained 4 MiB codec scratch"),
        ("encode", "build/inspect the encode-and-discard design; dry-run only"),
        ("status", "read the common state block"),
        ("restore", "guardedly restore this probe's hook word"),
    ):
        child = actions.add_parser(action, help=help_text)
        child.add_argument(
            "--dry-run",
            action="store_true",
            default=argparse.SUPPRESS,
            help="perform no camera reads or writes",
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
        if args.action in ("preflight", "scratch", "encode"):
            code = build_image(args.action, fpsup)
            describe_image(args.action, code, show_words=args.dry_run)
            if args.action == "encode" and not args.dry_run:
                raise ProbeError("encode is dry-run only; no camera access attempted")
            if args.dry_run:
                print("dry-run: no camera reads or writes performed")
                return 0
            shell = base.CameraShell(fpsh)
            if args.action == "preflight":
                arm_power_preflight(shell, code)
            else:
                arm_scratch_preflight(shell, code)
            return 0

        if args.dry_run:
            if args.action == "status":
                print(
                    f"would read hook 0x{base.HOOK_SITE:08X} and "
                    f"state 0x{STATE:08X}..0x{STATE + STATE_WORDS * 4:08X}"
                )
            else:
                base.dry_run_restore()
            print("dry-run: no camera reads or writes performed")
            return 0

        shell = base.CameraShell(fpsh)
        if args.action == "status":
            show_status(shell)
        else:
            base.restore_probe(shell)
        return 0
    except (base.ProbeError, ProbeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
