# FHD hardware lossless-JPEG probe suite

This directory keeps the staged SIGMA fp 5.02 experiments for connecting the
live FHD CinemaDNG writer to the camera's fixed-function lossless-JPEG codec.
It is a research probe suite, not a recording patch and not a flashable
firmware image.

| Phase | Camera status | What it establishes |
|---|---|---|
| Exact writer arguments | **Passed, 2026-08-31** | The live writer seam and its FHD segment are identified |
| Power/clock preflight | **Passed, 2026-08-31** | The exact writer task can balance the required domains while the codec is idle |
| Scratch allocation | **Offline-verified; not yet run on camera** | A guarded, aligned 4 MiB DMA layout can be prepared |
| Encode and measure | **Armable, never yet run on camera** | Consumes and frees the retained scratch; reports elapsed microseconds, per-tile sizes and release state |
| Exact final flush | **Offline-verified; not yet run on camera** | One-shot read-only capture of the completed writer list and synchronous flush result |

The hardware codec exists and is reachable, and its stills-path rate is
measured: 169.7 Mpix/s from one real 24.51 Mpix capture on 2026-08-30 (see
`research/imaging-hw/notes/HW_LOSSLESS_JPEG_CODEC.md`). That is 3.4x the
50 Mpix/s FHD 24p needs and short of the 199 Mpix/s UHD 24p needs. One sample,
one busy scene; the spread is unmeasured. What this directory still has to
establish is that the same engine can be driven **from inside the movie writer
context** — never yet done — and sustained there frame after frame.

中文摘要：已實機確認 FHD writer 交接點，以及該 task 能安全開關 codec 所需的
power/clock；4 MiB scratch 與單張 encode 都已可上機安裝，但兩者都還沒真正跑過。
靜態路徑的速度已量到 169.7 Mpix/s（FHD 24p 有 3.4 倍餘裕），錄影路徑則未知。
這組工具只改 RAM，並不是未簽章 `.bin` 或可刷寫韌體。

## Contents

| File | Role |
|---|---|
| `exact_dng_writer_probe.py` / `.S` | Build, arm, inspect, and restore the verified one-shot FHD writer probe |
| `exact_writer_power_preflight.S` | Balance power and clock from the exact live writer context without calling the codec |
| `exact_writer_scratch_preflight.S` | Allocate and guard the proposed 4 MiB DMA layout without calling the codec |
| `single_frame_codec_probe.py` | Enforce the staged preconditions and keep live encode disabled |
| `single_frame_encode_discard_probe.S` | PHASE=0/1 the reviewed offline design; PHASE=2 the armable consume-and-free encode |
| `exact_flush_writer_probe.py` / `.S` | Guarded one-shot probe at the final SD flush; observes the exact writer/list shape without modifying it |
| `test_*.py` | Verify assembly bounds, hook transaction order, proof gates, cleanup policy, and dry-run refusal |

## Playback boundary

Compression is not currently a transparent recording feature.  The still-DNG
develop path has a hardware decoder branch for `Compression=7`, but the V5.02
CinemaDngPlay parser reads strip layout and does not parse the tiled lossless-DNG
tags.  A valid compressed frame therefore does not imply in-camera movie
playback.  Variable compressed sizes have a separate first-frame-derived buffer
capacity constraint, and dynamically dropping source frames would additionally
require explicit timeline semantics.  Until those are solved, this directory
remains a probe suite, not a release path.

## Exact CinemaDNG writer probe

This is a one-shot diagnostic for the live FHD call at `0xC0722AFC` to
`0xC069AC88`. It records the first call, restores the firmware instruction from
inside the probe, and then passes the untouched call to the real writer.

The earlier candidate at `0xC0722A58` belongs to a v18 path that did not run in
the FHD recording test. The actual path was identified at `0xC0722AFC`, whose
original word is `0xEBFDE061` and whose expected return address is
`0xC0722B00`.

The installer also requires the surrounding six-word sequence before it writes
anything: `mov r1,sp; mov r0,r10; mov r2,#2; bl; add sp,#8; pop`. This guards
against applying the probe to a different firmware build or nearby call site.

It deliberately uses the shell template region at `0xC072F800` and state at
`0xC072F700`; it does not overwrite the gyro logger resident at
`0xC072E064..0xC072EFAC`.

Build and inspect without touching the camera:

```sh
./exact_dng_writer_probe.py arm --dry-run
```

Live sequence, after `fpshd` is connected and `fpsh ping` works:

```sh
./exact_dng_writer_probe.py arm
# Record 1-2 seconds of FHD CinemaDNG, then stop recording.
./exact_dng_writer_probe.py status
./exact_dng_writer_probe.py restore
```

The first hit should leave `count` at 1, `first_lr` at `0xC0722B00`, `done` at
`0x454E4F44`, and both the live hook and `restored_word` at `0xEBFDE061`.
`count` above 1 means the already-fetched hook instruction ran again; those
extra entries still tail-call the original function and do not overwrite the
first record.

## Live validation — 2026-08-31

A short 1920x1080, 12-bit CinemaDNG recording produced the expected one-shot
result:

```text
hook            0xEBFDE061  original/restored
count           0x00000001
first_r0        0xC3A6F3BC
first_r1        0xC3A6F37C
first_r2        0x00000002
first_lr        0xC0722B00
segment_buffer  0x53B02C00
segment_length  0x00318200
done            0x454E4F44
restored_word   0xEBFDE061
```

This confirms that `0xC0722AFC` is the live FHD CinemaDNG call which registers
one complete 3,244,544-byte DNG segment with `0xC069AC88`. The probe restored
the original instruction itself; no host-side restore write was needed.

Do not run `putfile.py`, `getfile.py`, or another template helper while the
probe is armed: those tools share `0xC072F700/0xC072F800`. If the camera becomes
unresponsive, pull the battery; all changes are RAM-only.

## Exact-writer codec preflight and encode design

`single_frame_codec_probe.py` shares the same verified live call site and the
same six-word context guard as the exact argument probe. It has five actions:

```sh
./single_frame_codec_probe.py preflight --dry-run
./single_frame_codec_probe.py scratch --dry-run
./single_frame_codec_probe.py encode --dry-run
./single_frame_codec_probe.py status --dry-run
./single_frame_codec_probe.py restore --dry-run
```

The `preflight` image is a power/clock-only one-shot. On its first entry it
restores `0xC0722AFC`, then performs this balanced sequence from the exact
writer task:

```text
power domain 3 on -> clock domain 5 on -> clock domain 5 off -> power domain 3 off
```

Every return value and any cleanup error are recorded. Cleanup follows the reviewed firmware policy: a
failed power-on releases nothing; a failed clock-on releases power; after a
successful clock-on, clock-off is attempted, and a failed clock-off does not cut
power underneath a clock that may still be enabled. Before those calls it reads
the segment and DNG only to enforce the observed FHD shape, verifies the codec
mode is idle, and records the source address. It never modifies the DNG or
segment, allocates memory, calls a codec wrapper, or writes codec globals. A
complete success leaves magic `0x52575050` (`PPWR`) at state offset `+0xD4`.

Live on 2026-08-31, this exact writer context passed: one hit, the original hook
restored, codec mode zero, aligned source `0x53B16000`, and all four power/clock
returns plus cleanup error equal to zero. The resulting `PPWR` magic was read
back successfully.

The `scratch` image is the next isolated phase. Its live installer first reads
and validates the complete `PPWR` state, then carries only that proof magic into
a new state block. On the first FHD frame it requests one 4 MiB non-cache block
with 1 KiB alignment, validates the low DMA handle and all arithmetic/ranges,
checks that it cannot overlap the DNG segment, and writes/reads four guards. It
does not call power, clock, or codec functions and does not modify the DNG or
segment. A complete result leaves `0x434F4C41` (`ALOC`) at `+0xD8`.

If the scratch phase succeeds, the allocation is intentionally retained. The
installer refuses another power or scratch preflight while it is retained,
preventing a second 4 MiB allocation or loss of the only handle. A live
encode/free consumer is **not implemented yet**; after a live scratch test,
record the status and power-cycle the camera to reclaim the allocation. Do not
load another template in between.

The common installer retains the exact probe's safety properties:

- it verifies the six firmware words at `0xC0722AF0..0xC0722B04`;
- code and the 256-byte state block are written and read back before the hook;
- the hook is the final write;
- an immediate first hit is recognized and never re-armed;
- restore accepts only this probe's armed word with a valid surrounding context.

The reviewed preflight images extend into known helper slots (`power` ends at
`0xC072FAAC`; `scratch` ends at `0xC072FC3C`, below its enforced
`0xC072FD00` limit). The shell reserves `0xC072F800..0xC0730000` for one
template routine, but the named helpers reuse sub-slots inside it. Do not run
`putfile`, `getfile`, bulk-loader, dump, or another template helper while either
probe is loaded or armed.

The `encode` action remains deliberately **dry-run only**: it is the reviewed
self-allocating design, kept byte-identical at 1268 bytes ending `0xC072FCF4`
for comparison, and it refuses before opening the camera transport.

`encode-live` (PHASE=2) is the armable one. It allocates **nothing**: the host
reads a complete, error-free scratch result and seeds exactly four words — the
`PPWR` and `ALOC` proofs, the allocator and the retained handle — into a fresh
state block. The probe re-derives the entire layout from that handle, repeats
every alias/alignment/range/overlap check, and additionally requires the three
guard words the scratch phase left behind to still be intact. A trampled guard
means the block is not what we think it is: it is then neither encoded into nor
freed. The image is 1420 bytes, ending `0xC072FD8C`, under its `0xC072FE00`
limit and 512 bytes below the shell's reserved end.

Its release policy is deliberately asymmetric, because the engine is a single
global with no ownership arbitration and a wrong free is how the still path was
killed on 2026-08-30:

| Situation | Action |
|---|---|
| adopted, encode never entered | free |
| adopted, encode returned success | free |
| encode entered and did not succeed | **retain** — the codec may still own the buffer; power-cycle to reclaim |

`S_ENC_STARTED` is written *before* the call, so a hang that never returns is
still visible in the state block afterwards.

Live sequence, one stage per armed recording, after `fpsh ping` works:

```sh
./single_frame_codec_probe.py preflight     # PPWR
# record 1-2 s FHD CinemaDNG, stop
./single_frame_codec_probe.py status
./single_frame_codec_probe.py scratch       # ALOC, retained
# record again, stop
./single_frame_codec_probe.py status
./single_frame_codec_probe.py encode-live   # consume + free
# record again, stop
./single_frame_codec_probe.py status        # prints the encode report
```

`status` decodes a finished PHASE=2 result into elapsed microseconds (the tick
is a free-running 1 MHz counter, so a wrap is a plain 32-bit subtraction),
Mpix/s against the 41,708 us 24p frame budget, the summed compressed size and
ratio, the twelve tile sizes, whether the source DNG was left byte-identical,
and whether the block was released. **One frame is not sustained throughput**,
and a rate derived from a single tile set is not a worst case.

The reviewed 4 MiB encode layout is:

```text
base + 0x000000 .. 0x304FFF   codec compressed output/work (cap 0x305000)
base + 0x305000               overrun guard
base + 0x306000 .. 0x30602F   final 12-word size table (init[7])
base + 0x306030               size-table guard
base + 0x306400 .. 0x30642F   codec temporary size table
base + 0x306430               temporary-table guard
```

`F_GET` requests 1 KiB alignment directly. The codec receives the low allocator
handle, not the cached alias. In the dry-run encode source, `init[6]` is the
compressed output/work base and `init[7]` is the size-table base; the original
DNG is source-only, and neither its header nor `seg[1]` is written.

Offline verification:

```sh
python3 -m unittest -v \
  test_exact_dng_writer_probe.py \
  test_single_frame_codec_probe.py
```
