# v0.7.26test: first-frame +1 row, detect then drop (offline evidence, 2026-11-04)

> **Update, the same day: drop instead of repair** (Bei: no incomplete frame in the clip). A shifted first frame is now
> **dropped** through `FUN_c038bd98`'s own "no frame" branch, with the firmware's release pair.
> - The move-up repair below is kept only as a fallback, for when a stop or flag 2 is pending.
> - Design, numbering (`_000002.DNG` start), audio (video one frame late) and the Gyro2 note: §"The drop" in
>   `notes/FIRST_FRAME_REPAIR.md`.
>
> Tests now run the **whole `FUN_c038bd98`** from the image. Its callees are stubbed and recorded; the lookup and the
> flag bytes run for real.
> - **dropped:** the lookup answers 0. There is no header DMA, enqueue, stop or first-frame step; the release pair runs
>   for this id; nothing in the buffer is written; the state stays 0x80000000.
> - **frame 2:** it gets the first-frame step, the header and the enqueue.
> - **native comparison:** the error branch issues the same release pair, and then stops the take.
> - **fallback, with flag 2, flag 3, or past the first frame:** a byte-exact move, and the native stop is kept.
> - **unchanged:** normal frames, frames 2+, only-armed, stock.
>
> Results:
> - 8 FirstFrameTests pass. All 21 mutants (#91–111) are caught, including 6 for the drop: each condition, each release
>   call, and the NULL answer.
> - `test_apply` 72/72, `tools/test.py fast` PASS, settings-migration 8/8.
>
> Build: `default-build/fpSup/SensorLab-IMX410_v0.7.26test.BIN`, 187,900 B, sha256
> `26e81702f5def44619753316d84d2360b0212b0761ce74aaa623a438603454cb`, block 568,384 B. It replaces the repair-only build
> `e966ae54…`, and the frozen fixture is updated.
>
> The status gains `first_drops`, for 38 words. The figures and tables below describe the repair-only build of the same
> day and are kept as history.

Status: **offline only**. I did not touch the camera, the USB shell or fpshd. The build is not deployed.
Design, hook points, context and cost: [notes/FIRST_FRAME_REPAIR.md](../../notes/FIRST_FRAME_REPAIR.md).
[C] = code or emulation of the real image. [I] = inference.

## What changed

- `apply/ap.c` gets two hooks.
  - `H_FFARM` at C031C948, ContSet_Adr1's `blx FUN_c0631b98(dest)`, the first frame's BUFA1 destination.
  - `H_FFFIX` at C038BDB4, the frame lookup in `FUN_c038bd98` on SRecRaw, before the header DMA, the enqueue and
    Lossless.
  - Each is a K_BL with a stock-word guard, through the same veneer as the other hooks. That makes 46 apply hooks and
    47 claims with the clock gate.
  - New functions: `ap_ff_arm`, `ap_ff_check`, `ap_ff_move`. New state: `struct ap_ff`, appended to `struct ap`.
  - `struct ap_slot` gains `rec_w` / `rec_h`.
- `apply/ap.h`: AP_ABI 2 → 3. `struct ap_status` gains `first_arms first_skips first_checks first_repairs first_ok
  first_miss first_us`, appended, for 37 words. The `sq_test 17` comment in `qs/slqs.c` is updated to match.
- `qs/build_slqs.py`: VERSION `0.7.26test`. STATE_RESERVE +0x40, because `struct st` holds an `ap_status`.
- Tests:
  - `apply/test_apply.py`: `FirstFrameTests` (6 tests) and 15 mutants. The status and selection ABI now come from
    ap.h. The v0.7.24 negative control packs its own ABI 2.
  - `apply/build_apply.py`: `ap_sizes_t(19)` = offsetof(struct ap, ff).
  - `qs/test_slqs.py`: ABI 3, and the code-size guard +2 KiB for the ~1.4 KiB added. That guard checks growth only;
    the loader's limit is MAX_BLOCK, 16 MiB.

## Tests ([C], emulated against `out/MAIN_c0000000.bin`)

`FirstFrameTests` runs the real hooked sites.

- **Arm.** The unit runs C031C944–C031C94C: `ldr r0,[r6,#0x38]`, our veneer, then the real `FUN_c0631b98`, which
  writes 0x30182280.
- **Arrival.** The unit runs C038BDB0–C038BDB8: `ldr r1,[r6,#0xe8]`, our veneer, then the real `FUN_c03753c0`.
- **Raster.** The frame's file buffer is a 16 MiB window mapped at both the uncached (0x4C…) and the cached (0xCC…)
  alias. The window logs read/write order against the D-cache calls.

| | test | proves |
|---|---|---|
| a | `test_a_shifted_first_frame_is_repaired_byte_exactly` | Covers 12v2 3024×2010 RAW12, with and without a 12-px ×4 fragment at the start of row 0, and true-14 1×1 3024×2020 RAW14 (format 1). Rows 1..N-1 hold the real lines 0..N-2 and row 0 is stale. After the repair, rows 0..N-1 are **byte-exact** to `lines 0..N-2 + line N-2`. The header (0x15400) and 4 KiB after the raster are untouched. Order: D-clean, then the sentinel through the uncached alias. At the arrival: uncached sentinel read, D-clean+inv, cached-alias move only, D-clean last. Counters `1 arm / 1 check / 1 repair`. |
| b, c | `test_a_normal_first_frame_and_frames_2_on_are_untouched` | A fully written first frame is untouched: no D-cache call, `first_ok` 1. Frames 2 and 3 carry the take's sentinel bytes in row 0 and shifted rows, and are still untouched. |
| – | `test_only_the_armed_frame_is_looked_at` | If the first arrival is another buffer, it counts as a miss. The armed buffer arriving later is not looked at. The next take gets a new seed, and the frame can carry the cached alias. |
| d | `test_stock_modes_are_never_armed_or_touched` | With no slot, modes 106/97/230/231 do nothing. With a live slot and a descriptor mode of 106, 97 or the other slot's id, nothing is armed or touched. A destination outside DRAM is skipped and `first_skips` counts it. |
| d | `test_record_start_arms_frame_1_before_the_bufa1_start` | Runs the whole REC start through `../20261103-first-frame-mmio-diff/mmio_diff.py`: `SetImgMode_s` + `ContSet_Adr1`, ap.c hooks live. For 12v2 and 1×1, the 64 sentinel bytes land in the destination's row 0, after a D-clean and before `0x30182004 = 4`. The armed row/rows equal BUFA1's programmed line words ×4 and lines, 0x30182214 and 0x30182210. Stock UHD30 reaches the same site (BUFA1) and is not armed. Stock FHD106 (BUFA7) never reaches the site. |
| – | `test_the_sites` | The stock words, and the instruction order around both sites. |

Mutation (15 new entries in `MUTANTS`, run in isolation with `test_apply.py --mutate --only=N`): **15/15 caught.**

| # | mutant |
|---|---|
| 91 | Mode guard removed |
| 92 | Sentinel test inverted |
| 93 | Duplicate row N-3 instead of N-2 |
| 94 | Move one row short |
| 95 | Not one-shot |
| 96 | Raster match removed |
| 97 | 14-bit treated as 12-bit |
| 98 | Sentinel at the row start |
| 99–101 | Each of the three D-cache calls removed |
| 102 | Sentinel written through the cached alias |
| 103 | Move through the uncached alias |
| 104 | Fixed seed |
| 105 | Repair site moved to C038BFD0 |

Mutant 103 first survived. I added the assertion that the move touches only the cached alias, and it is now caught.

Not listed as mutants, because they are equivalent on every reachable input and kept as guards: the slot-id recheck
at the arrival, and the commit's disarm. A commit never runs while recording, and it already disarms.

Runs on this tree:

- `python3 -B tools/test.py fast`: **PASS**. 13 jobs; the first try failed on the size and STATE_RESERVE guards, fixed
  above.
- `python3 -B tools/test.py full --no-mutants`: 260 jobs.
  - One failure: the v0.7.24 negative control sent an ABI-3 selection to the ABI-2 unit. The test is fixed and
    re-passes on its own.
  - Everything else passed, including `settings-migration` 8/8 against the new frozen fixture and `slqs` 67/67.
- `python3 -B tools/test.py mutants --only apply,slqs` (logs `tools/test-logs/mutants-20261103-214029/`):
  - apply: 102 of 106 caught, all 15 new ones included. Mutants #48, 54, 56 and 61 fail with "mutant text not found
    once": that is the same pre-existing problem as at v0.7.25test, not this change.
  - slqs: 89 of 90 caught. Mutant #81 does not compile (`unused variable 'was'` at slqs.c:1165, outside this change), so
    it tests nothing. I did not check whether it already failed before this change.

## Cost (`measure.py` → `measure.json`, `measure.txt`) [C counts, I time]

| case | arm | arrival, normal | arrival, shifted | later frames |
|---|---|---|---|---|
| 12v2 3024×2010 RAW12 | 259 insns, 64 B | 220 insns, 64 B read | 1,424,951 insns, 9.12 MB read + 9.12 MB written | 72 insns |
| 1×1 3024×2020 RAW14 | 259 | 220 | 1,670,624 insns, 10.69 MB + 10.69 MB | 72 |

Estimated time for the shifted case:

- About 11–30 ms at typical cached A9 copy rates. [I]
- At most about 127 ms if the cached path were no faster than the only measured CPU copy on this camera: Lossless G4a,
  uncached, ≈ 72 MB/s. [I]
- Plus two full `C000E91C` passes.

It runs once per take, on SRecRaw (prio 15), with IRQs on. ImgCtrl (7), SRecFile (6) and the Lossless codec task (12)
are not delayed. See the note for the tasks that are.

## Build

- `default-build/fpSup/SensorLab-IMX410_v0.7.26test.BIN`: 187,796 B, sha256
  `e966ae54484bee90a3d5334ace54de6006feeba43beb6ad672a0710c8c935191`, block 568,320 B.
- It is copied as the frozen settings-migration fixture: `qs/test-fixtures/settings-migration/frozen/`, with a
  README.txt entry.

## Not verified (needs the camera)

- Whether the repair fires at the archived rates. Read `sq_test 17` after takes: `first_repairs` should be about 100 %
  for 1×2, about 21 % for 1×1, and 0 for 2×2. The repaired DNG's row 0 and its last rows should be checked with
  `../20261103-first-frame-purple-review/audit_rows.py`.
- The real `first_us`, and that the first-arrival stall causes no dropped frame, no `raw_trans_null` and no overflow.
- Real cache behaviour. The emulator checks only the order of the cache calls.
- With Lossless ON, and with Gyro and ULWR on the same card.
