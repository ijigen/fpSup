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
# The consume-and-free image is larger than the self-allocating design: it adds
# proof/guard revalidation and the release step while dropping F_ALLOC/F_GET.
# Still 512 bytes below the shell's reserved end at 0xC0730000, and no other
# helper may be loaded while it is armed.
ENCODE_LIVE_LIMIT = 0xC072FE00
# PHASE=3 additionally owns a per-frame log immediately above its code, still
# inside the shell's reserved template region. No other helper may be loaded
# while it is armed, and the log must be read before one is.
SUSTAINED_CODE_LIMIT = 0xC072FF00
LOG = 0xC072FF00
# The run lasts as long as the recording. Rows ring over the last RING_FRAMES
# frames; the worst-case trackers at AGG_OFF cover every frame.
SUSTAINED_FRAMES = 4096
RING_FRAMES = 8
LOG_WORDS_PER_FRAME = 4
AGG_OFF = 0x80
AGG_WORDS = 3
BUDGET_US = 41708

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
PHASE_ENCODE = 2
PHASE_SUSTAINED = 3
FREE_MAGIC = 0x45455246
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
S_FREE_ERROR = 0xEC // 4
S_FREE_DONE = 0xF0 // 4
S_ENCODE_STARTED = 0xF4 // 4
S_ADOPTED = 0xF8 // 4
S_FRAMES_DONE = 0xFC // 4
S_INIT_RET = 0x58 // 4
S_ENC_RET = 0x5C // 4
S_SIZE_RET = 0x60 // 4
S_COMPRESSED = 0x64 // 4
S_TILE_COUNT = 0xA0 // 4
S_HDR_BEFORE = 0x78 // 4
S_HDR_AFTER = 0x7C // 4
S_PIX0_BEFORE = 0x80 // 4
S_PIX0_AFTER = 0x84 // 4
S_PIXN_BEFORE = 0x88 // 4
S_PIXN_AFTER = 0x8C // 4
S_TILE0 = 0xA4 // 4
RAW_BYTES = 0x304CB0
TILE_COUNT = 12
ERR_RETAINED = 25

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
    0xEC: "free_error",
    0xF0: "free_done",
    0xF4: "encode_entered",
    0xF8: "block_adopted",
    0xFC: "frames_done",
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
    elif kind == "encode-live":
        source = ENCODE_SOURCE
        defines = ("PHASE=2",)
        limit = ENCODE_LIVE_LIMIT
    elif kind == "encode-sustained":
        source = ENCODE_SOURCE
        defines = ("PHASE=3", f"FRAMES={SUSTAINED_FRAMES}")
        limit = SUSTAINED_CODE_LIMIT
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
        "encode-live": ENCODE_SOURCE,
        "encode-sustained": ENCODE_SOURCE,
    }[kind]
    live = kind in ("preflight", "scratch", "encode-live", "encode-sustained")
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
    elif kind == "encode-live":
        mode = ("live-capable single encode; consumes the retained block, "
                "requires PPWR + ALOC proof")
    elif kind == "encode-sustained":
        mode = (f"live-capable sustained encode over {SUSTAINED_FRAMES} frames; "
                f"log at 0x{LOG:08X}, re-arms between frames")
    else:
        mode = "DRY-RUN ONLY"
    print(f"mode   : {mode}")
    if kind in ("scratch", "encode", "encode-live", "encode-sustained"):
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


def arm_live_encode(shell: base.CameraShell, code: bytes) -> None:
    """One encode into the block the scratch phase retained, then release it.

    Nothing is allocated. The seeded handle is only the scratch result's own
    handle, and the probe still re-derives the whole layout and re-checks every
    guard before it lets the codec touch the block.
    """
    values = shell.read_words(STATE, STATE_WORDS)
    if not scratch_preflight_success(values):
        raise ProbeError(
            "live encode requires a complete, error-free scratch preflight in "
            "state; run scratch first, or power-cycle and redo both preflights"
        )
    seeded_state = [0] * STATE_WORDS
    seeded_state[S_PREFLIGHT] = PREFLIGHT_MAGIC
    seeded_state[S_SCRATCH_MAGIC] = SCRATCH_MAGIC
    seeded_state[S_ALLOCATOR] = values[S_ALLOCATOR]
    seeded_state[S_HANDLE] = values[S_HANDLE]

    shell.write_words_verified(CODE, base.words_from(code))
    shell.write_words_verified(STATE, seeded_state)
    base.verify_call_context(shell)
    armed = base.arm_site(shell)
    if armed:
        print("live encode armed and verified against the retained block")
        print(f"allocator 0x{values[S_ALLOCATOR]:08X}  handle 0x{values[S_HANDLE]:08X}")
        print("record one short FHD CinemaDNG clip, then run: status")
    else:
        print("live encode fired during arm and already restored; run: status")


def unfired_seed_present(values: list[int] | tuple[int, ...]) -> bool:
    """A seeded, never-fired block from an earlier arm of this same phase.

    Re-arming over it swaps the image without allocating a second 4 MiB block
    and without discarding a result: both proofs must be present, the handle
    must still look like the allocator's, and nothing may have run yet.
    """
    if len(values) < STATE_WORDS:
        return False
    handle = values[S_HANDLE]
    return (
        values[S_PREFLIGHT] == PREFLIGHT_MAGIC
        and values[S_SCRATCH_MAGIC] == SCRATCH_MAGIC
        and values[S_ALLOCATOR] != 0
        and 0x40000000 <= handle < 0x80000000
        and handle & 0x3FF == 0
        and values[S_COUNT] == 0
        and values[S_FRAMES_DONE] == 0
        and values[S_DONE] == 0
    )


def arm_sustained_encode(shell: base.CameraShell, code: bytes,
                         reuse_seed: bool = False) -> None:
    """Encode FRAMES consecutive frames into the retained block, then release.

    The probe re-arms itself between frames, so unlike the one-shot images an
    interrupted run leaves the site armed. Always finish with `status` and, if
    it still reports armed, `restore`.
    """
    values = shell.read_words(STATE, STATE_WORDS)
    if reuse_seed:
        if not unfired_seed_present(values):
            raise ProbeError(
                "--reuse-seed needs an unfired seed from an earlier arm of this "
                "phase: both proofs, a plausible handle, and nothing run yet"
            )
        print("reusing the retained block; no second allocation")
    elif not scratch_preflight_success(values):
        raise ProbeError(
            "sustained encode requires a complete, error-free scratch preflight "
            "in state; run scratch first, or power-cycle and redo both preflights"
        )
    seeded_state = [0] * STATE_WORDS
    seeded_state[S_PREFLIGHT] = PREFLIGHT_MAGIC
    seeded_state[S_SCRATCH_MAGIC] = SCRATCH_MAGIC
    seeded_state[S_ALLOCATOR] = values[S_ALLOCATOR]
    seeded_state[S_HANDLE] = values[S_HANDLE]

    shell.write_words_verified(CODE, base.words_from(code))
    # Stale records must not be readable as results.
    shell.write_words_verified(LOG, [0] * (AGG_OFF // 4 + AGG_WORDS))
    shell.write_words_verified(STATE, seeded_state)
    base.verify_call_context(shell)
    armed = base.arm_site(shell)
    if armed:
        print(f"sustained encode armed; runs until recording stops "
              f"(ceiling {SUSTAINED_FRAMES} frames)")
        print(f"allocator 0x{values[S_ALLOCATOR]:08X}  handle 0x{values[S_HANDLE]:08X}")
        print("record one clip of at least a second, then run: status")
    else:
        print("sustained encode fired during arm; run: status")


def read_aggregates(shell: base.CameraShell) -> dict[str, int]:
    """Worst case over every frame of the run, whatever its length."""
    words = shell.read_words(LOG + AGG_OFF, AGG_WORDS)
    return {"max_elapsed_us": words[0], "max_compressed_bytes": words[1],
            "frames_over_budget": words[2]}


def read_log(shell: base.CameraShell, frames: int) -> list[dict[str, int]]:
    """One 16-byte record per frame: elapsed, compressed, buffer, first pixel.

    The last two identify the frame. Identical compressed sizes across records
    mean nothing unless the buffer or the pixel word differ.
    """
    frames = min(frames, RING_FRAMES)
    words = shell.read_words(LOG, frames * LOG_WORDS_PER_FRAME)
    records = []
    for index in range(frames):
        base_index = index * LOG_WORDS_PER_FRAME
        elapsed, compressed, buffer_address, pixel = words[base_index:base_index + 4]
        if not elapsed and not compressed and not buffer_address:
            continue  # never written
        records.append({"frame": index, "elapsed_us": elapsed,
                        "compressed_bytes": compressed,
                        "buffer": buffer_address, "first_pixel": pixel})
    return records


def print_sustained_report(shell: base.CameraShell,
                           values: list[int] | tuple[int, ...]) -> None:
    done = values[S_FRAMES_DONE]
    print("")
    print(f"sustained encode: {done} frames encoded")
    aggregates = read_aggregates(shell)
    if done:
        worst = aggregates["max_elapsed_us"]
        print(f"  WORST frame            {worst} us  "
              f"({worst / BUDGET_US:.2f} of the 24p budget, "
              f"{'fits' if worst < BUDGET_US else 'OVER'})")
        print(f"  largest compressed     {aggregates['max_compressed_bytes']} bytes")
        print(f"  frames over budget     {aggregates['frames_over_budget']} of {done}")
    if values[S_ERROR]:
        print(f"  run ended on error {values[S_ERROR]} after {done} frames")
    print(f"  last {RING_FRAMES} frames in detail:")
    records = read_log(shell, RING_FRAMES)
    if not records:
        print("  no records written")
        return
    print("  frame  elapsed_us   Mpix/s  compressed   ratio      buffer   pixel0")
    pixels = 1936 * 1090
    times, ratios = [], []
    for record in records:
        elapsed = record["elapsed_us"]
        compressed = record["compressed_bytes"]
        rate = pixels / elapsed if elapsed else 0.0
        ratio = RAW_BYTES / compressed if compressed else 0.0
        if elapsed:
            times.append(elapsed)
            ratios.append(ratio)
        print(f"  {record['frame']:5d}  {elapsed:10d}  {rate:7.1f}  "
              f"{compressed:10d}  {ratio:6.3f}  0x{record['buffer']:08X}  "
              f"0x{record['first_pixel']:08X}")
    distinct_buffers = {record["buffer"] for record in records}
    distinct_pixels = {record["first_pixel"] for record in records}
    if len(records) > 1 and len(distinct_buffers) == 1 and len(distinct_pixels) == 1:
        print("  WARNING: every record has the same buffer AND the same first")
        print("  pixel. These may be re-encodes of one frame, not distinct frames.")
    else:
        print(f"  distinct buffers {len(distinct_buffers)}, "
              f"distinct first pixels {len(distinct_pixels)} of {len(records)}")
    if times:
        print(f"  elapsed us   min {min(times)}  max {max(times)}  "
              f"mean {sum(times) // len(times)}")
        print(f"  ratio        min {min(ratios):.3f}  max {max(ratios):.3f}")
        print(f"  worst frame is {max(times) / 41708:.2f} of the 24p budget "
              f"({'fits' if max(times) < 41708 else 'OVER'})")


def encode_report(values: list[int] | tuple[int, ...]) -> dict[str, object] | None:
    """Decode a finished PHASE=2 result. Returns None if this is not one."""
    if len(values) < STATE_WORDS or values[S_PHASE] != PHASE_ENCODE:
        return None
    if values[S_DONE] != DONE_MAGIC:
        return None
    report: dict[str, object] = {
        "error": values[S_ERROR],
        "stage": values[S_STAGE],
        "adopted": values[S_ADOPTED] == 1,
        "encode_entered": values[S_ENCODE_STARTED] == 1,
        "init_return": values[S_INIT_RET],
        "encode_return": values[S_ENC_RET],
        "size_return": values[S_SIZE_RET],
        "compressed_bytes": values[S_COMPRESSED],
        "tile_sizes": [values[S_TILE0 + n] for n in range(TILE_COUNT)],
        "block_released": values[S_FREE_DONE] == FREE_MAGIC,
        "release_refused": values[S_FREE_ERROR] == ERR_RETAINED,
        "source_unmodified": (
            values[S_HDR_BEFORE] == values[S_HDR_AFTER]
            and values[S_PIX0_BEFORE] == values[S_PIX0_AFTER]
            and values[S_PIXN_BEFORE] == values[S_PIXN_AFTER]
        ),
    }
    if values[S_ENC_RET] == 1 and values[S_ERROR] == 0:
        # The tick is a free-running 1 MHz counter, so a wrap is a plain
        # 32-bit subtraction. One frame only: this is not sustained throughput.
        elapsed = (values[S_T1] - values[S_T0]) & 0xFFFFFFFF
        report["elapsed_us"] = elapsed
        if 0 < elapsed < 10_000_000:
            pixels = 1936 * 1090
            report["mpix_per_second"] = round(pixels / elapsed, 1)
            report["frame_budget_24p_us"] = 41708
        if values[S_COMPRESSED]:
            report["ratio"] = round(RAW_BYTES / values[S_COMPRESSED], 3)
    return report


def print_encode_report(values: list[int] | tuple[int, ...]) -> None:
    report = encode_report(values)
    if report is None:
        return
    print("")
    print("live encode result")
    for key in ("error", "stage", "adopted", "encode_entered", "init_return",
                "encode_return", "size_return", "compressed_bytes", "ratio",
                "elapsed_us", "mpix_per_second", "frame_budget_24p_us",
                "source_unmodified", "block_released", "release_refused"):
        if key in report:
            print(f"  {key:22s} {report[key]}")
    print(f"  tile_sizes             {report['tile_sizes']}")
    if report["release_refused"]:
        print("  NOTE: the encode did not succeed, so the block was deliberately")
        print("        retained. Power-cycle the camera to reclaim it.")


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
        elif name == "free_done":
            note = " RELEASED" if value == FREE_MAGIC else ""
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
    print("hook_state                "
          + ("ARMED — run restore" if site == base.HOOK_ARMED else "restored"))
    if values[S_PHASE] == PHASE_ENCODE:
        print_encode_report(values)
    if values[S_PHASE] == PHASE_SUSTAINED:
        print_sustained_report(shell, values)


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
        ("encode", "build/inspect the self-allocating design; dry-run only"),
        ("encode-live", "consume and free the retained scratch in one encode"),
        ("encode-sustained", f"encode {SUSTAINED_FRAMES} consecutive frames"),
        ("status", "read the common state block"),
        ("restore", "guardedly restore this probe's hook word"),
    ):
        child = actions.add_parser(action, help=help_text)
        if action == "encode-sustained":
            child.add_argument(
                "--reuse-seed",
                action="store_true",
                help="re-arm over an unfired seed instead of allocating again",
            )
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
        if args.action in ("preflight", "scratch", "encode", "encode-live",
                           "encode-sustained"):
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
            elif args.action == "scratch":
                arm_scratch_preflight(shell, code)
            elif args.action == "encode-live":
                arm_live_encode(shell, code)
            else:
                arm_sustained_encode(shell, code,
                                     reuse_seed=getattr(args, "reuse_seed", False))
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
