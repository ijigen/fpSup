# Coverage of the in-camera pipeline

What the fp's image pipeline contains, how much of each stage has been read out
of the firmware, and what is left. [COLOR_MODES.md](COLOR_MODES.md) holds the
findings themselves; this file is the map of where they sit and what is missing.

Addresses are Ver 5.02.

## Where the stage list comes from

The firmware carries a pool of 133 ISP stage names at `0xC07D366C` to
`0xC07D3E08`, in two fixed-stride runs of 8 and 16 bytes. Indices 6 to 26 are
sequencer operations (`COPY`, `RDMA`, `ROUTE`, `SLEEP`, `WAIT`, `BUF-A`). Indices
27 to 128 are parameter stages, and they are the inventory this file tracks.

**The pool is dead data, and that is a load-bearing fact.** Nothing in the image
refers to any string in it. Four independent checks all return zero: no
`movw`/`movt` pair builds any of those addresses, no 32-bit word anywhere in the
49 MB image equals one, no PC-relative `ADR` computes one, and nothing points at
the pool base. The word check does not depend on the instruction set, so a
second processor sharing this address map would also fail it. Just past the pool
sits the format string `0x%08x = 0x%08x\n`, so this is a register-dump facility
that was compiled in and never linked.

Two consequences follow, and they pull in opposite directions:

- **A name cannot lead to its data.** There is no name-to-address table to walk.
  Searching the image for `CEQ_YGAM` finds the string and stops there. Any stage
  named in this file but not located is in that position.
- **The list is still a complete table of contents.** It names every stage the
  ISP has, in the vendor's own words, so the size of what is unread is known even
  where the data is not. That is why this file can state coverage as a fraction.

**A caution about names already used.** Because no name-to-address link exists,
every place this repository attaches a stage name to an address is an inference
from the shape of the data, not a fact from the firmware. `0xC0B39118` is called
the `YCMAT` block on those grounds. The inference is a good one — the record
really does build a YCbCr matrix — but it is an inference, and the same goes for
`CUVAREA` and the `CEQ24` blocks.

## The route that does work

The ISP descriptor table at `0xC0B38ACC` is 49 entries of `(pointer, count)`.

**The table is keyed by ISO, not by mode.** Every record starts with a `u16` key.
Of the 12 entries with more than one record, 10 hold an ISO ladder — 100, 200,
400, 800, 1600, 3200, 6400, 12800, 25600, 51200, 102400, or a subset of it. The
other two, entries 44 and 48, are keyed by a plain index. All 37 single-record
entries are keyed 100, which is base ISO, not a mode.

A trap for the next reader: **the top step is stored wrapped.** The key is a
`u16`, so ISO 102400 appears as 36864, and read as a signed value it appears as
-28672. ISO 51200 appears as -14336. A reader who takes those at face value will
not recognise the ladder.

An earlier version of this file called these per-mode parameter classes with an
id-100 neutral default. That was wrong on both counts. They are ISO-keyed, and
the 100 is base ISO. The per-mode look data is not here: it is the RAM override
that a handful of these classes accept, which is why `0xC02C55A0` looks up by
mode id in RAM and falls back to the descriptor record when it finds nothing.

The getter is `0xC02D5DE0`. It has 242 call sites, but for most entries the only
two are the bulk copiers at `0xC02D6C08` and `0xC02D7000`, which move each
default into RAM. Consumers then read RAM, not the descriptor. So the working
chain is:

```
descriptor entry  ->  RAM address (from the copier)  ->  consumer (by address scan)
```

28 entries have their RAM address decoded this way. They land in two parallel
structs, `0xC3424DC0` and `0xC3425168`, exactly `0x3A8` apart.

This is the method that produced the two decodes of 2026-09-12. Neither used a
name. The YC matrix came from reading what `0xC02C55A0` does with entry 31, and
the `CUVAREA` consumer came from an address scan on the care-map blocks.

Entries with more than the two copier calls, which marks a real consumer:

| entry | pointer | count | stride | uses | what it is |
|---|---|---|---|---|---|
| 31 | `0xC0B39118` | 1 | 20 | 175 | the YC matrix, decoded |
| 30 | `0xC0B39100` | 1 | 24 | 4 | **identified**: a white-preserving saturating Q9 3x3, the fallback default of a matrix class |
| 24 | `0xC0B39088` | 1 | 8 | 3 | the chroma gains, all zero |
| 29 | `0xC0B390E8` | 1 | 24 | 3 | **identified**: the Q9 identity, the neutral default of a second matrix class |
| 37 | `0xC0B3924C` | 1 | 292 | 3 | **identified**: Standard's own `CEQ24` block |

**Consumers, and a blind spot in how they are counted.** `0xC02D5DE0` is the only
route to table A specifically — nothing else builds `0xC0B38ACC` — but see the
section on the three tables: B and C have their own getters. Of A's 242
call sites, 180 are outside the copiers, and 178 of those index an entry by an
immediate offset in three functions:

| function | entries it reads |
|---|---|
| `0xC02C5440` | 24, 30, 31 — the mode-matrix loader |
| `0xC02CFCF0` | 29, 30, 31, 37 — the effect-strength composer |
| `0xC02D5E18` | 31, 142 times — the register-write path |

The remaining two call sites pass the table pointer on rather than indexing it.
`0xC02BFF9C` hands it to `0xC02D0EC0`, which reads entry 26. `0xC02BF6E8` hands
it to `0xC02BDC20`, which **stores it into an object**.

That last one is the blind spot, and it is worth stating plainly: once the
pointer is in an object, any code holding that object can index the table, and no
scan anchored on the getter will see it. So a count of call sites is a lower
bound on consumers, never a proof that an entry is unused. Do not conclude an
entry is dead from silence here. The reliable route stays the RAM one — the
copier gives the address, and addresses are built with `movw`/`movt`, which is
searchable.

**Entry 30 is decoded and rejected as a render stage.** Its rows each sum to 512,
so it preserves white, but unlike every matrix in the mode table it saturates:
eigenvalues 1.2344, 1.3672 and 1.0, determinant 1.69. Both consumers use it as
the fallback when a mode has no keyed record, and the per-mode records are
stride 40. It matches no mode matrix. Tested in the rig as a shared stage, to see
whether it could stand where the fitted `chroma_trim` of 1.12 does, it is worse
than having no trim at all: 3.581 against 3.239 held out with the trim, and 3.496
with the trim removed and nothing in its place. Applying it before the mode
matrix instead is worse again, at 3.683. The script is `xc/e30.py`.

Entry 37 is now read. It is a full `CEQ24` block carrying id 100, and it decodes
to Standard's look exactly. That answers a standing question — Standard does have
a register block, as the class default rather than as a keyed record — and it
confirms the five-bin hue offset through the value column, which no earlier
derivation used. See COLOR_MODES.md, section 4.

## There are three descriptor tables, not one

An earlier version of this file said `0xC02D5DE0` is the only route to the
descriptor table. That is true of **that** table, and it hid two siblings. There
are three, each 49 entries of `(pointer, count)` in the same layout, each with
its own one-instruction getter:

| table | address | getter | contents |
|---|---|---|---|
| A | `0xC0B38ACC` | `0xC02D5DE0` | 49 ROM entries, single-record defaults |
| B | `0xC0B3EFDC` | `0xC02D6BF8` | 31 RAM + 18 ROM |
| C | `0xC0B3F83C` | `0xC02D6FF0` | 31 RAM + 18 ROM, a second instance |

The two bulk copiers fill the RAM slots of B and C from A's defaults. B's RAM
pointers are exactly the copier destinations, which is how the three line up.

**B and C are what the ISP reads; A is only the fallback set.** The same 18
entries are ROM-resident in both B and C — 0, 1, 6, 8, 9, 10, 14, 15, 16, 17,
20, 21, 22, 26, 34, 39, 44 and 48 — and those are exactly the classes the copiers
skip, because they have no runtime override. For those classes B and C carry
**more data than A**. A's entry 0 is one 16-byte record; B's entry 0 is ten
records on an ISO ladder. So reading table A alone understates the parameter set
by a wide margin.

### The 18 ROM classes of table B

All are ISO-keyed, with the same `u16` wrap as table A.

| entry | records | stride | shape |
|---|---|---|---|
| 0, 1 | 10 | 16 | identical to each other; zero below ISO 800, then a pair rising to 4128 with a second pair that switches on at 12800 |
| 6 | 9 | 16 | a pair falling 16383 to 128 as ISO rises — a strength that decreases with sensitivity |
| 8 | 11 | 12 | three values rising with ISO, 6 to 17 and 24 to 56 |
| 9, 10, 16, 17, 20, 39 | 1 | 8–40 | single records; 39 is a 20-step ramp 0, 256, 512 … 2304 |
| 14 | 1 | 20 | two 4-point ladders, `(0, 200, 1032, 800)` and `(0, 200, 1032, 500)` |
| 15 | 4 | 8 | a strength falling 100, 100, 75, 25 at the top three ISOs |
| 21 | 4 | 16 | 100/180/180/250 against 100, 100 |
| 22 | 1 | 16 | `840, 880, 960, 1027, 5` — an ascending triple, likely knee points |
| 26 | 4 | 8 | 20, 20, 20, 23, 26 |
| 34 | 11 | 20 | rises with ISO on two columns, 0 to 80 and 1032 to 1068 |
| 44 | 2 | 20 | two records both keyed 100 |
| 48 | 79 | 8 | **keyed 0 to 78, not by ISO.** Values are only 0, 1, 256, 257, 258 — a two-byte flag pair. This reads as a per-stage enable table, one row per ISP stage. |

Entry 48 is the most interesting of the set. A 79-row table of small flags keyed
by a plain index is the shape of a stage-enable map, and the pipeline has roughly
that many parameter stages. Nothing yet links row `n` to a stage name, and the
name pool cannot supply the link.

**The `CEQ24` default block is in RAM at `0xC3424F0C`.** The copier reads table A
entry 37 and moves 292 bytes to `0xC3424DC0 + 0x14c`; table C's copy sits at
`0xC34252B4`. Nothing in the image builds either address with `movw`/`movt`, so
the hardware writer reaches them through the table, not directly.

## How an ISO-keyed parameter is actually read

Decompilation settles the mechanism. The generic reader is this, from
`0xC02D0EC0`:

```c
key = *(uint *)(ctx + 0xfc);          // the current ISO
tbl = *(uint **)(table + 0xd0);       // entry 26's records, 0xd0/8 = 26
n   = *(uint *)(table + 0xd4);        // its count
// clamp key into [first key, last key], then walk down for the bracketing pair
v = interp(rec[-2], rec[0], (char)rec[-1], (char)rec[1], key);
```

`interp` is `0xC04D0F80`, a linear interpolation between two `(key, value)`
points. Three things follow, and none was visible from the data alone.

- **The camera interpolates between ISO steps.** It does not snap to the nearest
  rung of the ladder. A parameter is a continuous function of sensitivity, and
  the ladder is its knot set.
- **Only the low byte of each value word is used.** The reader casts with
  `(char)`, so a record's 32-bit value field carries one byte of payload.
- **The entry index is baked into the reader, not passed in.** `0xC02D0EC0` is
  hard-wired to entry 26. So there is one small reader function per parameter
  class, which is why no single call site enumerates the table.

`0xC04D0F80` has 13 callers. Six sit in the ISP parameter code — `0xC02C11A8`,
`0xC02D0618`, `0xC02D0998`, `0xC02D0EC0`, `0xC02D1150`, `0xC02D1A58` and
`0xC02D1AD0` — and the rest are in an unrelated subsystem at `0xC0694000`.
`0xC02D0998` is a generic column reader over 48-byte records, and `0xC02D1150`
interpolates ten columns of one record at once. Those two are the ones to read
next, because between them they cover the wide records.

## Reading the image with a decompiler

The analysis from 2026-09-12 onward uses Ghidra headless over the raw image,
loaded as `ARM:LE:32:v7` at base `0xC0000000`. Auto-analysis finds 39,063
functions in about five minutes.

It is worth saying why this changed the work rather than just speeding it up.
Hand-written scanners anchored on a call site cannot follow a pointer that is
stored into an object, and this firmware does that constantly — the descriptor
tables are wrapped in a class with a vtable and handed to a generic worker. Real
cross-references found 10 distinct callers of table A's getter where a
proximity-clustered scan of the same call sites had found 5, and it found the two
callers each of B's and C's getters immediately.

The decompiler also serves as a check on hand analysis. It reproduced the YC
matrix builder at `0xC02C55A0` independently: the 16-byte copy from `record + 4`,
the luma row scaled by `DAT_c02c5934`, and the two chroma rows as
`v3, -(v3+v4), v4` and `v5, -(v5+v6), v6` scaled by `DAT_c02c593c`.

## Coverage by block

Status words, used strictly:

- **decoded** — the format was read out of the image and confirmed against the
  code that consumes it.
- **located** — the data is found, the format is not read.
- **named only** — the name is in the pool, no data has been found.
- **run time** — the data is built or uploaded while the camera runs, so it is
  not in the image at all.
- **modelled** — the renderer reproduces the effect from measurement, not from
  firmware.

### SIG0 — sensor-side raw

`DELTA DARK`, `DARK SHADING`, `DS_SEL`, `BAYER_NR`, `FPNR`, `RWMEDF`, `SW_DCT`,
`RAWBLT`, `RAWOUT`, `RAW_CORR`, `DLTEXP`, `RAWSHAD_LINEAR`, `VLN_C`, `TBLSD`,
`NLmeans`.

All 15 are **named only**. Nothing here has been touched. The renderer works from
the DNG, which the camera writes after this block, so none of it is on the path
this project measures.

### SIG1 — raw zoom, shading, white balance

`RAW ZOOM`, `SHADING1`, `SHADING2` and its `_R`, `_B`, `_GR`, `_GB` variants,
`RAWOUT`, `3DDNR`, `WHITE BALANCE`, `GRV_C`.

`WHITE BALANCE` is **partly decoded**: the two double-precision calibration
illuminant matrices at `0xC0970044` and `0xC097008C` are read, and they are the
standard XYZ-to-sRGB matrix with `diag(0.492, 1.000, 0.649)` and
`diag(0.480, 1.210, 1.569)` baked in. The rest is **named only**.

### PRE_TOP — demosaic and sharpening

`GAPSUP`, `APKNEE`, `LM`, `HSEP`, `RWAPKNEE`, `CSEP`, `MEDF`, `CORRECT_G`,
`GNR`, `APGEN`, `SHUSA_EXT`.

All 11 **named only**. The renderer uses its own demosaic.

### MAT_TOP — the colour matrix

| stage | status | where |
|---|---|---|
| `RGBLMAT` | decoded | the 24-byte per-mode matrix table at `0xC0B3A340`, loader `0xC02C5440` |
| `IGAMMA` | tested, rejected | a companded domain for the matrix does not fit any single exponent |
| `PSTAPKNEE` | named only | |
| `PSTIGAM` | named only | |

### GAM_TOP — gamma and the YC matrix

| stage | status | where |
|---|---|---|
| `GAMMA TABLE` | decoded | the bank at `0xC096CF34`, 2048 `u16` per curve, 8190 full scale, with the mode-to-group map at `0xC0B3D670` |
| `YCMAT` | decoded | descriptor entry 31, `0xC0B39118`, built by `0xC02C55A0` |
| `GAM_BAS` | named only | |
| `GAMINT` | named only | |
| `SBUS GAMMA` | named only | |
| `GAM_GS GAMDEC` | named only | |
| `RGBMAT_PL` | named only | |

The per-mode `YCMAT` records are **run time**. Only the id-100 default is static.

### CEQ — the colour equaliser

| stage | status | where |
|---|---|---|
| `CEQ24_ORG` | decoded | the even 24-bin hue grid in the 61 register blocks from `0xC0B3AB1C` |
| `CEQ24_TGT` | decoded | the rotated grid; `TGT - ORG` is the float table's hue column to 0.003 degrees |
| arrays A and C | decoded, rejected | the two value columns; A is 1.000 everywhere, C makes the render worse |
| arrays B and D | decoded | `D / B` is the float table's saturation column, value for value |
| `CEQ_ORG` / `CEQ_TGT` | named only | the coarse pair, never located |
| `CEQ_YGAM` | named only | |
| `CEQ_KNEE` | named only | |
| `CEQ_CLIP` | named only | |
| `CEQ_CORING` | named only | |
| `CEQ_CORING2` | named only | |
| `CEQ_OFFSET` | named only | |
| `CEQ_COMPATI` | named only | |
| `CEQ_Y_GAMMA` | named only | |

This is where the unread mass sits. Eight of the equaliser's own stages have no
located data, and the equaliser is the stage the looks act through.

### PST_TOP — post-process chroma

| stage | status | where |
|---|---|---|
| `CUVAREA CARE_SEL` | decoded | maps at `0xC0B44EF8`, `0xC0B456F8`, `0xC0B45EF8`; consumer at `0xC02CE260` |
| `CUVCONT` | named only | |
| `CSUP` | named only | |
| `ECSUP` | named only | |
| `CKNEE` | named only | |
| `Y_GAMMA` | named only | |
| `APSUP` | named only | |
| `SHOOT_G` | named only | |
| `CUVLPF YLPF` | named only | |
| `YUVHMF` | named only | |
| `YUVIIR` | named only | |
| `YSHD_C` | named only | |
| `DITHER` | named only | |

`CUVAREA`'s per-mode strengths are **run time**, in the struct from
`0xC02C1CF0`.

### YMED_TOP, FIR_TOP and the rest

`C_SAT_C`, `CORING`, `YUVFIR`, `PRIVACY_MASK`, `FOCALZM`, `ADD_RND`, `BLT_YUV`,
`BLT_NLM`, `DOPT_MAIN`, `DOPT_ORIGINAL`, `DOPT_SMALL_SLOPEMAX0` and `1`,
`CENH SRAM`, `CENH DEBUG`, `PSF_TOP`, `MT2_TOP`, `HSR_TOP`, `CRCT_TOP`,
`CRCT_3A`, `SRAM_MGR`, `HDR_HIST`, `YUV_PACK`, `SIGSEQ_0` and `1`,
`REG_DEFCADR`, `V LATCH`.

All **named only**. `CONTRAST` is **decoded** in effect if not by name: each
gamma group is a run of 11 curves, one per contrast step, and `group + 5` is the
middle.

## What is decoded outside the ISP stage list

These are not ISP stages, so they carry no name in the pool, but they are the
bulk of what the project has read.

| object | status | where |
|---|---|---|
| the look parameter list | decoded | 7 entries at `0xC0B40074` |
| the 24-bin hue tables | decoded | entry 0, `0xC0B400AC`, 17 modes |
| the 128-point tone curves | decoded | entry 4, `0xC0B434E8`, Standard and OFF only |
| the 72-entry tables | half decoded | entry 3; the first 36 are the DNG's `ProfileHueSatMap`, the second 36 are unread |
| the ISO ladders | decoded | entries 5 and 6, keyed by ISO, not by mode |
| the effect-slider engine | decoded | 12 LUTs at `0xC0B46A70`, selector at `0xC0B468AC`, blender at `0xC02D4570` |
| the internal mode enum | decoded | fixed across six firmware versions |
| the gamma group map | decoded | `0xC0B3D670`, 36 pairs |

## What the renderer uses that is not decoded

This is the debt, quarantined in its own fields. It is listed here so the cost of
each unread stage is visible.

| item | stands in for |
|---|---|
| `T`, the front-end transform | an unread stage between the sensor matrix and the look matrix |
| `residual_lo` / `residual_hi` | undecoded chroma stages, most likely inside `CEQ` or `PST_TOP` |
| `luma_cb` / `luma_cr` | the per-mode `YCMAT` luma row, which is run time |
| `rot_scale`, about 0.6 to 0.7 | no mechanism found; four have been tested and rejected |

## Coverage, counted

Of the 102 named ISP parameter stages, **7 are decoded**: `RGBLMAT`,
`YCMAT`, `GAMMA TABLE`, `CEQ24_ORG`, `CEQ24_TGT`, `CUVAREA CARE_SEL`, and
`WHITE BALANCE` in part. Two more, `IGAMMA` and the `CEQ24` value arrays, are
decoded far enough to be tested and rejected.

That is about 7 percent of the stages by count. It is much more than 7 percent of
the look, because the decoded seven are the matrix, the gamma and the equaliser's
own tables — the stages that carry the mode differences. The render sits at
2.46 dE against the camera, and 4.18 dE with firmware-derived stages alone.

## TODO, in order

1. **Walk the descriptor table.** 49 entries, 28 with a known RAM address, and
   only a handful identified. For each: find the RAM address in the copier, scan
   for consumers of that address, and read what the consumer computes. This is
   the method that worked twice on 2026-09-12 and it needs no names.
2. ~~Entries 37, 30 and 29.~~ Done on 2026-09-12. Entry 37 is Standard's `CEQ24`
   block, entry 30 is a saturating matrix default that the render rejects, and
   entry 29 is the Q9 identity.
3. **The descriptor walk is close to exhausted for colour.** Because the table is
   ISO-keyed, most of its 49 entries are sensor and noise tuning that varies with
   sensitivity, not look data. The look enters only through the classes that take
   a per-mode RAM override, and those are entries 24, 29, 30, 31 and 37 — all now
   identified. Further walking should expect ISO tuning, not looks.
4. **The second 36-entry map** in the 72-entry table. Present for Standard and
   OFF, its two saturation divisions differ where the DNG's are identical, and
   its role is open.
5. **The `PST_TOP` chroma stages**, through the same descriptor walk rather than
   by name. `CUVCONT`, `CSUP`, `ECSUP` and `CKNEE` are the best candidates for
   the strong looks' missing saturation.
6. **`SIG1 SHADING`** if the renderer ever needs to match corner falloff. It is
   not on the path the current measurements use.

Items 1 to 3 are bounded work with a known method. Items 5 and 6 are searches.
