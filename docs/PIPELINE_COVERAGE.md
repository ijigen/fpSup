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
Every entry's first record begins `100, 0`, the id-100 neutral default, so all 49
are per-mode parameter classes with a static default in ROM.

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
| 30 | `0xC0B39100` | 1 | 24 | 4 | a Q9 3x3, rows sum to 512, unread |
| 24 | `0xC0B39088` | 1 | 8 | 3 | the chroma gains, all zero |
| 29 | `0xC0B390E8` | 1 | 24 | 3 | three rows of 512, unread |
| 37 | `0xC0B3924C` | 1 | 292 | 3 | **identified**: Standard's own `CEQ24` block |

Entry 37 is now read. It is a full `CEQ24` block carrying id 100, and it decodes
to Standard's look exactly. That answers a standing question — Standard does have
a register block, as the class default rather than as a keyed record — and it
confirms the five-bin hue offset through the value column, which no earlier
derivation used. See COLOR_MODES.md, section 4.

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
2. ~~Entry 37.~~ Done on 2026-09-12: it is Standard's `CEQ24` block.
3. **Then entries 30 and 29.** Both are 24-byte records of Q9 rows that sum to
   512, both have real consumers, and entry 30's green row is Standard's green
   row exactly.
4. **The second 36-entry map** in the 72-entry table. Present for Standard and
   OFF, its two saturation divisions differ where the DNG's are identical, and
   its role is open.
5. **The `PST_TOP` chroma stages**, through the same descriptor walk rather than
   by name. `CUVCONT`, `CSUP`, `ECSUP` and `CKNEE` are the best candidates for
   the strong looks' missing saturation.
6. **`SIG1 SHADING`** if the renderer ever needs to match corner falloff. It is
   not on the path the current measurements use.

Items 1 to 3 are bounded work with a known method. Items 5 and 6 are searches.
