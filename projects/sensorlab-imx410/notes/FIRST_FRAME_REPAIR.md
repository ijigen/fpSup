# First-frame +1 row: detect, then drop (v0.7.26test, 2026-11-04, offline)

> **Superseded by v0.7.27test (2026-11-04).** Bei dropped both the drop and the repair ("丟幀面臨問題太多").
> v0.7.27test keeps only the arm-time sentinel and adds a read-only trace: see
> `validation/20261104-first-frame-trace/README.md`. The RE below (hook sites, the release pair, the "no frame"
> branch, numbering, the audio consequence) stays valid as reference.

Status: implemented in `apply/ap.c` and tested under unicorn against `out/MAIN_c0000000.bin`. **Not run on the camera.**
[C] = shown by code or emulation (the image's own instructions ran). [I] = inference.
The cause is not re-investigated here; see `FIRST_FRAME_PURPLE.md`, `FIRST_FRAME_DMA_START_RE.md` and
`validation/20261103-first-frame-*`. Evidence and test runs: `validation/20261104-first-frame-repair/README.md`.

## What it does

The first CinemaDNG frame of a take is sometimes shifted down one raster row: BUFA1 never writes row 0, and
`frame1[y+1] == frame2[y]`. The repair runs on the first frame only, and only while a SensorLab slot is live.

1. **Arm, at REC start, before the DMA starts.** ap.c writes 16 words (64 B) of a per-take xorshift32 sequence into
   the **last** 64 bytes of raster row 0.
   - The last bytes are used because a shifted row 0 can still get a 12–48 px fragment at its start.
   - The write goes through the uncached alias, after one full D-cache clean+invalidate (`C000E91C`) and before a
     `dsb`.
2. **Check, when the frame arrives and before anything reads it.**
   - Sentinel overwritten means a normal frame. It is not touched.
   - Sentinel intact means BUFA1 never wrote the end of row 0, so the frame is shifted. **It is dropped**
     (Bei, 11-04: no incomplete frame in the clip). See "The drop" below.
   - **Fallback, when dropping is not a no-op for the firmware** (a stop or flag 2 is pending, or the creator is
     already past its first frame): the rows are moved up one instead, as in the first version of this build.
     - Move rows 1..N-1 up to rows 0..N-2, then copy row N-2 into row N-1, which is outside DefaultCrop.
     - The move goes through the cached alias, with a full `C000E91C` clean+invalidate before and after it.
3. The state is one-shot. The first arrival after an arm ends it, whether or not it was the armed frame. A REC start
   re-arms it, and every commit clears it.

It never allocates, never waits on anything, and arms nothing for a stock mode.

## The drop [C unless marked]

The firmware has **no "skip one frame and continue" path**.

- `FUN_c038bd98`'s error branch (message +0xe4 ≠ 0) releases the frame, then ends the take with `cDevt_stop`.
  `test_the_drop_is_the_firmwares_own_release_pair` runs this branch.

The drop therefore combines two pieces of native behaviour:

1. **The release pair**, the same calls with the same arguments as that error branch (C038BECC–C038BEF4) and as the
   completion `FUN_c038c058`:
   - `FUN_c0377730(FUN_c0377348(), id)` frees the RAW allocations through `C03777B8` and refills.
   - `FUN_c0375030(FUN_c0374220(), id)` deletes the frame-table entry.
   - `id` is frame +0x10FC.
2. **The lookup answers NULL.** `FUN_c038bd98` then takes its own "no such frame" branch.
   - That branch logs, clears flag bytes 2 and 3 of `*param_1`, and stops only if `param_1[5] != 0x80000000`.
   - `param_1[5] == 0x80000000` means "before the first frame". It is set at take start, and only the non-NULL path
     sets it to 0 (C038BE48–C038BE74).
   - So on the first frame the branch neither stops nor enqueues. It returns `param_1[3]` unchanged, exactly as the
     normal path does.
3. **The drop is taken only when the branch's side effects are no-ops:** `param_1[5] == 0x80000000`, flag 2 clear and
   flag 3 clear.
   - Flag 3 is "stop pressed before the first frame". It is set by v28 and v37 only while `+0x14 == 0x80000000`.
   - Otherwise the fallback move is used, and the native stop still follows the enqueue (tested).

Downstream effects:

- **Frame 2 becomes the take's first.** It runs the first-frame step (`FUN_c0396000(…, 2)`, `param_1[5] = 0`), the
  header DMA and the enqueue. [C, tested]
  - Lossless counts arrivals at C038BFF0, so frame 2 is its uncompressed first file. [C, source]
  - The writer's first-file hook (`XC_StillCreateFile` v4, `+0x20 == 0` → `FUN_c0396658(frame + 0x1030)`) sees frame
    2's name. [C]
- **The dropped frame's number is skipped.**
  - The DNG name is fixed per frame when the frame is set up: `FUN_c0376b98` copies `_%06d.DNG` from the path info into
    frame +0x1030, and the writer uses +0x1030.
  - In the archived takes the first file is `_000001.DNG` (t34: 000001, 000002). A dropped take therefore starts at
    **`_000002.DNG`** and has no gaps after that. [C copy, I counter]
  - Image-sequence readers (Resolve) start at the first existing number. [I]
- **The frame count, rec log and XMP** count what the writer writes, so one fewer frame. [I] The stop scans the frame
  table (`C0376300`), from which the dropped entry is deleted. [C]
- **Audio:** CinemaDNG carries no TimeCode (memory: audio-video-sync-by-construction). Audio and video line up only
  because they start together. A dropped take's video starts **one frame period after the audio**, and nothing
  compensates:
  - 33.4 ms at 29.97 fps;
  - 41.7 ms at 23.976 fps;
  - 16.7 ms at 59.94 fps.
  - The editor sees it as video late by one frame. Fixing it means slipping the audio one frame, or keeping the frame
    (repair) instead. [C no TimeCode / I effect]
- **Gyro2:** if its anchor is the first raw-buffer latch (`FPGYRO_FRAME_ANCHOR`, `0xC343943C`), that latch belongs to
  the dropped frame, so the gyro start is one frame earlier than the first DNG. That is within Gyroflow's per-clip
  sync, but it is a constant +1 frame for dropped takes. [I, Gyro2 not re-read]
- **Cost:** about 220 instructions plus the two native calls. No raster access beyond the 64-byte check, and no cache
  pass.

## Sentinel choice

The sentinel is 16 words of xorshift32, seeded by `tick_us ^ 0x5346F11E ^ arms·0x9E3779B9` with bit 0 forced on. The
sequence is never zero, and the seed changes on every take.

- **A false "shifted" call** would need BUFA1 to write those exact 512 bits from the sensor.
  - Real RAW12 or RAW14 content is either noisy or structured (a flat field, a clipped 0xFFF run). It does not
    follow a xorshift sequence whose seed changes per take. The chance is about 2⁻⁵¹² for any content that does not
    depend on the seed. [I]
  - A sentinel left from an earlier take cannot match either, because the seed differs. [C]
    `test_only_the_armed_frame_is_looked_at` and its fixed-seed mutant cover this.
- **A false "normal" call is the safe failure: no repair.** It happens if BUFA1 writes something over row 0's last
  64 bytes in a shifted frame. No archived bad frame shows that. In every archived bad frame, row 0 beyond 12–48 px is
  stale DRAM, as listed in the review README and the dark-frame audit. [D, I]

## Hook points [C]

| id | site | stock word | context | what |
|---|---|---|---|---|
| `H_FFARM` | `C031C948` in `ContSet_Adr1` (BUFA1 branch) | `FA0C5492` `blx FUN_c0631b98` | REC-start task (caller of `FUN_c0378a50` → `FUN_c030cf98`) | r0 is the destination (`ldr r0,[r6,#0x38]` at C031C944). r6 is desc − 8: +0x1C is the mode, +0x20 the format. Runs before the start at C031CAE0 (`FUN_c0631c08(1)`). |
| `H_FFFIX` | `C038BDB4` in `FUN_c038bd98` | `EBFFA581` `bl FUN_c03753c0` | SRecRaw (prio 15) | Gets the frame back, then checks; answers NULL when it drops (r4 = `param_1`, the creator state). Runs before `cineCapture` (C038BFB0), the header DMA `FUN_c038c5f8` (C038BFD0) and the creator enqueue C038BFF0 (Lossless's arrival hook). |

The two sites are new; no other sup claims them. The count goes to 46 apply hooks, 47 claims with the clock gate.

### Why the first frame's raster is `frame + 0x4C`

`FUN_c0378a50` copies the REC-start descriptor and puts the first frame's `param_2 + 0x4C` at descriptor +0x30.
`FUN_c030cf98` turns that into ContSet_Adr1's `param_2 + 0x38`. That value is what `FUN_c0631b98` writes into
`0x30182280` (phys >> 2). [C]

At the arrival, ap.c compares the frame's `+0x4C`, alias-normalised, with the armed address. Anything else is a
"miss" and is left untouched.

### Why the check runs at FUN_c038bd98 and not at the completion

The completion path runs in interrupt context [C]:

- `FUN_c0630d60` (BUFA1 IRQ, 0x30182048 bit4) reads the destination register and calls `FUN_c031bca0`.
- `FUN_c031bca0` calls `FUN_c031d7a0`, which calls the observer's vtable +0xC = `XC_StillCreateImgObs` v1
  `C037F778`.
- For type 1 that is `FUN_c037a590`. It finds the frame by address, `FUN_c03754d0`, and posts it with
  `FUN_c0377210`.

None of these functions reads the raster. They handle metadata and messages only. [C, decomp]

A 9 MB CPU move does not belong in an IRQ. It would stall the 2500 Hz gyro, USB, and the next BUFA1 completion.

The first task that sees the frame is the CinemaDNG creator state:

- `MovRecFuncStateCinemaDng` v38 dispatches type 5 to `FUN_c038bd98`. [C]
- That runs on SRecRaw, which Lossless's live notes record as the task where frames arrive. [I, strong]
- Its first action is the hooked lookup.

Lossless also observes at C038BD08 (v38, metadata only, `fpl_card_event`) and takes the frame at C038BFF0. Both
leave the first frame uncompressed and natively enqueued. So Lossless, the native writer and the header DMA all see
the repaired rows. [C, source]

## Cost (fallback move only; a drop costs about 220 instructions)

Unicorn instruction counts, from `validation/20261104-first-frame-repair/measure.py`. The D-cache routine and the tick
are stubbed and not counted. [C]

| case | arm | arrival, normal frame | arrival, shifted frame | later frames |
|---|---|---|---|---|
| 12v2 3024×2010 RAW12 (4536 B/row) | 259 insns, 64 B | 220 insns, 64 B uncached read | 1,424,951 insns; 9.12 MB read + 9.12 MB written | 72 insns |
| 1×1 14-bit 3024×2020 RAW14 (5292 B/row) | 259 | 220 | 1,670,624 insns; 10.69 MB + 10.69 MB | 72 |

The move is 32 bytes per pass with LDM/STM (5 instructions), the same shape as the firmware's `memcpy` C001510C.

Time estimate [I]: the move is memory-bound.

- No cached CPU copy rate has been measured on the fp. Typical Cortex-A9 cached LDM/STM copies run at 300–800 MB/s,
  which gives **about 11–30 ms** for 12v2.
- Upper bound: the only measured CPU copy rate is Lossless G4a, an uncached copy of 3.2 MB in 44.9 ms (≈ 72 MB/s).
  At that rate, 9.12 MB takes about **127 ms**.
- Add two full `C000E91C` passes. Each runs with IRQs off for "tens to hundreds of µs" (CPU_GLOBAL_CONFIG.md, not
  measured).
- `first_us` in the status reports the real figure on the camera.

Who waits, by the master task table (TASK_PRIORITY_MAP.md §2b) [C table, I effect]:

- **Not delayed**, because they run at a higher priority than SRecRaw (15):
  - ImgCtrl (7), which programs the next BUFA1 destination;
  - SRecFile (6);
  - audio;
  - the Lossless codec task (12).
- **Delayed once per take, for the duration of the move**: MRecMgr / CamSch (15), Level / DrawMgr (16–17) and
  GyroData (20).
  - The gyro ring holds 240 ms.
  - Frame 2's arrival message waits in SRecRaw's queue for 1–4 frame periods.
- IRQs stay on during the move.

## Not verified

- **Nothing here has run on the camera.** The cache maintenance is checked only for its order: in the emulator both
  aliases are one RAM. Real L1/L2 behaviour, for example a dirty line written back over the sentinel, is reasoned
  about, not observed. [I]
- That SRecRaw's message queue and AcqInThr tolerate a 30–130 ms stall of the first arrival. No overflow, no dropped
  frame and no `raw_trans_null` must appear. [I] This is the main live risk.
- The real duration (`first_us`), and that `first_repairs` / `first_ok` match the archived rates: ~100 % for 1×2, ~21 %
  for 1×1, 0 for 2×2.
- The arm site was proven under emulation for 12v2 and 1×1 (written before `0x30182004 = 4`; geometry = BUFA1's line
  words × 4 and lines) and for stock UHD (site reached, nothing armed). Recording paths that are not CinemaDNG, and
  stills, were not traced. ap.c arms only when the descriptor's mode is the live slot's virtual id.
- Format 1 (14-bit DMA lines) for true-14 slots: the descriptor's +0x20 value is assumed to be the DMA format, as
  `FUN_c0630e90` uses it. A true-14 take has not been traced end to end.
- The drop: the release pair and the NULL branch are executed from the image, with the callees stubbed and their calls
  recorded. The real `FUN_c0377730` / `FUN_c0375030` bodies, AcqInThr's refill (vtable +0x14) and the writer, XMP and
  rec-log counts are not executed. The `_000002` start, and that Resolve / Gyroflow accept it, need a camera take.
- (Fallback only) The repaired last row duplicates row N-2, as asked. That is the opposite CFA colour to row N-1. It lies outside
  DefaultCrop (5+ rows of margin), but a demosaicer that reads past the crop sees the wrong colour there. If that
  matters, copy row N-3 (same CFA phase) instead; it is a one-word change, and a mutant shows the tests pin it.
