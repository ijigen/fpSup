# The colour-mode look tables

The fp's colour modes are three static tables in the firmware, one entry per
mode. This is where the looks live. It is not the XC container — that is menu
artwork, see [XC_CONTAINER.md](XC_CONTAINER.md). For where these findings sit in
the whole pipeline, and what is still unread, see
[PIPELINE_COVERAGE.md](PIPELINE_COVERAGE.md).

**The register names in this file are inferences.** The firmware carries a pool
of ISP stage names at `0xC07D366C`, and nothing in the image refers to any string
in it — no `movw`/`movt` pair, no 32-bit word anywhere, no PC-relative `ADR`, and
no pointer to the pool base. So there is no name-to-address table. Wherever this
file calls a block `YCMAT`, `CUVAREA` or `CEQ24`, that name was matched to the
data by its shape, not read from the firmware.

Derived 2026-09-09 against all six unpacked firmwares, from Ver 1.02 to
Ver 5.02.

Tool: [`firmware/colormode_extract.py`](../firmware/colormode_extract.py). It
needs no third-party modules and finds the tables by signature, so it works on
every version.

```
colormode_extract.py report MAIN_dec.bin
colormode_extract.py json   MAIN_dec.bin looks.json
```

---

## Where the tables are

Three tables, each an array of records with a `u32` mode id first.

| table | record | Ver 2.03 | Ver 5.02 |
|---|---|---|---|
| hue table | 580 bytes | `0xC08A9E38` | `0xC0B400AC` |
| colour matrix | 24 bytes | `0xC08A6AF8` | `0xC0B3A340` |
| tone curve | 1028 bytes | `0xC08ADB6C` | `0xC0B434E8` |

The hue table is entry 0 of the parameter list at `0xC0B40074` (Ver 5.02), which
the `PictureQuality` constructor `0xC02C40B8` reads through the getter
`0xC02D73E8`. The tone curve is entry 4 of the same list.

**The matrix table has no pointer to it anywhere in the image.** An earlier
version of this file guessed the code reaches it by an offset from a nearby base.
That guess is now testable and it fails: the offsets from the descriptor table
base to the matrix table, the `CEQ24` run and the gamma map never appear as `add`
immediates, and no literal-pool word holds any of the three addresses. The real
answer is in PIPELINE_COVERAGE.md — the mode-matrix loader takes its records from
a mode-keyed table in RAM at `0xC2F1A064 + 0x08`, and whatever installs that
pointer is not statically visible.

## 1. The hue table — 580 bytes per mode

```
u32          mode id
float[24][2][3]   24 hue bins x 2 variants x (hue, sat, val)
```

The three floats are a hue rotation in degrees, a saturation multiplier and a
value multiplier. Two entries prove that. Monochrome is saturation 0.000 in
every bin. OFF is hue 0.0, saturation 1.000 and value 1.000 in every bin.

**For every menu mode the two variants differ only in the value multiplier.**
Counted over all 408 bins of Ver 5.02: the hue column is identical in 408, the
saturation column in 391, and the value column in 354. All 17 saturation
differences belong to id 37, which has no menu entry. So for the 15 modes a user
can pick, the variants are one table with two value columns.

Variant 0's value column is **1.000 in every bin of every mode**. So choosing
variant 0 is the same as having no value stage at all. Variant 1's column is
non-1 in 54 bins. The section on the value columns tests both against the
camera.

Bin `i` covers 15 degrees. **Bin 0 is not at red.** An earlier version of this
file inferred that it was, and a later one said it was red half a turn away.
Both were wrong. The answer is in the firmware, in the register blocks described
below: bin 0 of this float table is at **285 degrees** of `atan2(Cr, Cb)`. That
it comes within 3.65 degrees of red-plus-half-a-turn is a coincidence.

Two independent things agree on 285.

From the firmware: the `CEQ24` blocks hold an even 24-bin grid, so hardware bin
`j` is at `15 * j` degrees of the hardware's own hue. Matching each float record
against its block lines them up with a **five-bin offset** — float bin `i` is
hardware bin `i - 5`, which puts float bin 0 at `-75` degrees of hardware hue.

From the camera: one frame processed in camera by every mode gives JPEGs that
differ only by the look. Comparing each against Standard's, per bin of the Cb/Cr
angle, recovers the rotation and the chroma gain the camera really applied.
Cross-correlating those against the table peaks at 285 for both, separately —
rotation at +0.58, gain at +0.60 — and the mild looks agree on their own: Vivid
0.94, Landscape 0.85, Neutral 0.75.

Put together, hardware hue zero is at `285 + 75 = 360`, the `+Cb` axis. **The
camera measures hue as a plain `atan2(Cr, Cb)`**, and this float table is the
same wheel rotated by five bins.

## 2. The colour matrix — 24 bytes per mode

```
u32       mode id
int16[9]  matrix, Q9 fixed point (512 = 1.0)
int16     zero
```

Each row stores its own channel first, then the other two in R, G, B order:

```
row R = (RR, RG, RB)
row G = (GG, GR, GB)
row B = (BB, BR, BG)
```

The DuoTone entries prove this layout. Their three rows decode to the same
weights `(0.279, 0.574, 0.146)`, which is a luma matrix — exactly what a duotone
needs.

Rows usually sum to 512, so the matrix keeps white neutral. Three modes break
that by more than 2 percent and shift the white balance: Warm Gold (red gain
1.188, blue 0.846), Sunset Red (red 1.127) and Cinematic (blue 0.748).

**There is one matrix table, not several.** An earlier version of this file said
parallel tables sat next to each other, one per output path. That was wrong.
Searching the whole image for Standard's own 18 bytes finds exactly two
occurrences, `0xC0B3A344` and `0xC0B3A464`, and the second is the same table
further on: its records are ids 35, 1, 16, 22, 2, 17, which is the Monochrome
and DuoTone section. Standard simply carries the same matrix as id 35.

Every matrix here desaturates. They are written for the camera's own sensor
RGB, not for a signal that a raw converter has already brought to Rec.709. A
converter that applies them as they stand desaturates twice. Applying each mode
as its difference from Standard instead — `M_mode * inverse(M_Standard)` — makes
Standard the identity and cancels the shared part.

**With an OFF frame, the whole linear front end is measurable — see the
section on the OFF shot below, which supersedes the fitted matrix that follows.**

**The space these matrices act in matters, and it is measurable.** A
channel-mixing matrix turns hue by an amount that depends on the primaries it
acts between. Applied in Rec.709, each mode's render came out turned a
different way — FOV Classic Blue 11 degrees toward green, Warm Gold 10 toward
red. Different directions cannot come from one shared upstream error directly,
but one wrong *space* produces them exactly, through each mode's own matrix. A
single 3x3 `G` was fitted so that every matrix is applied as
`inverse(G) * M * G`, on half of a fourteen-mode sample frame, and validated on
the other half. It collapses the divergence, it converges to nearly the same
matrix from two unrelated starting points, and it lands close to the
sRGB-to-camera matrix in Sigma's own DNG profile — which is what it physically
is: the mode matrices act in sensor RGB, and the DNG's ColorMatrix is the
per-body calibration this repository said could not be read from the firmware.
It cannot; it can be fitted from the camera's own JPEGs.

```
G = [ 0.5264  0.3159  0.1577 ]      sRGB -> camera, rows sum to 1
    [-0.0813  1.0886 -0.0073 ]
    [-0.0577  0.3132  0.7446 ]
```

## The OFF shot — the measurement that unlocks the rest

OFF is the identity look: the identity tone curve, zero rotations, gain 1.000 in
every bin, value 1.000. So a JPEG taken in OFF, inverted through the identity
curve, **is the camera's linear output**. Nothing else in this project gives a
direct view of the linear front end; every look shot filters it through a curve
and a chroma stage.

What one OFF frame settles:

**The front end is one measured matrix.** Regressing the inverted OFF JPEG
against a linear decode of the same DNG gives the 3x3 between them — least
squares over 708,000 pixels, mean residual 2.3 percent of signal. Composed with
`inverse(M_OFF)` and any mode's own firmware matrix, this replaces the fitted
working-space matrix above, the fitted per-hue base correction, and any exposure
trim. A render of OFF through it scores **0.9 dE** against the camera's own OFF
JPEG — below the JPEG's noise floor, on data no fit ever saw.

**The camera applies its curve hue-preserving, not per channel.** Re-fitting the
front end with the OFF JPEG inverted both ways decides it: read as a
hue-preserving encode (largest and smallest channel through the curve, the
middle in proportion) the correction comes out as the identity to 0.9 percent;
read per channel it needs a green row skewed by 9 percent to fit. A per-channel
curve also turns saturated colours toward yellow-green by several degrees in
render tests, and the camera's output shows no such turn.

**The 285-degree anchor holds** re-derived under this chain: a sweep over
anchors peaks at 285 again.

**What it does not settle**: comparing standard.JPG against off.JPG measures
Standard's whole look at once — matrix, curve and equaliser together. The
matrix and curve dominate (chroma gains of 2 to 4, rotations to 22 degrees), so
the equaliser's rotation column cannot be isolated from that comparison; its
effect is a minor term inside a much larger transform.

## 3. The tone curve — 1028 bytes per mode

```
u32          mode id
float[128][2]   128 (x, y) control points, both in 0.0 to 1.0
```

Only two modes carry one: Standard and OFF. OFF is the exact identity, point for
point. Standard is a strong lift:

```
0.0123 -> 0.0047      0.4553 -> 0.7238
0.0989 -> 0.1403      0.6398 -> 0.8872
0.2921 -> 0.5044      0.8732 -> 0.9902
```

The x spacing is not uniform. It starts at 1/81 and gets finer near 1.0.

## 4. The CEQ24 register blocks — what the hardware actually reads

The float table above is not what the colour equaliser reads. The camera also
holds every look as a block of hardware register values, and those are the ones
that reach the chip.

There are **61 blocks of 292 bytes** (`0x124`), the largest run starting at
`0xC0B3AB1C`. A block is a two-word head and six arrays of 24 `u16`:

| offset | what it is |
|---|---|
| 0 | the mode id, in the same enum as every other table here |
| 2 | zero |
| 4 | array A — the value multiplier of the float table's variant 0, in Q9. All 1.0 |
| 52 | array B — the saturation scale, 683 for most modes, 1024 for Cinematic and Teal and Orange |
| 100 | `CEQ24_ORG` — the even hue grid, `round(i * 65536 / 24)` |
| 148 | array C — the value multiplier of variant 1, in Q9. Monochrome's 576, 672 and 704 are the float table's 1.12, 1.31 and 1.38 exactly |
| 196 | array D — saturation |
| 244 | `CEQ24_TGT` — the hue grid rotated, u16 full-circle |

Find them by searching for the `ORG` grid, which is the same in every block —
`0, 2731, 5461, 8192, 10923, 13653, ...` — and then step back 100 bytes to read
the id. Do not guess a block's mode from its position in the run: `0xC0B3AB1C`
looks like it should be Standard and its id says 35.

**Read as `D / B`, the saturation array is the float table's saturation column,
value for value.** Their means line up exactly — Vivid 1.826, Powder Blue 1.790,
Forest Green 1.676, Cinematic 1.001, Monochrome 0.000. So array B is what
normalises array D, and the two forms of the table hold the same numbers.

**Standard's block is the class default, keyed 100.** An earlier version of this
file said Standard had no block, because id 0 is absent from the run. Id 0 is
absent, but the look is not. The block at `0xC0B3924C`, which carries id 100,
decodes to Standard exactly: its saturation column matches Standard's float
record to 0.00000, its value column to 0.00000, and its rotation column to 0.0063
degrees. Its mean saturation is 1.495 and its largest rotation 11.25 degrees,
which are Standard's own figures.

That block is **descriptor entry 37** of the ISP table at `0xC0B38ACC`, so it is
the id-100 neutral default of the `CEQ24` parameter class. Standard is the
camera's default look, so the class default holds Standard's numbers and id 0
never needs a keyed record. A signature search over the whole image finds no
other id-100 block. The ids present are 1 to 36 except 0 and 4, plus 39 and 100,
and id 9 is absent from the middle of the gamma map in the same way.

This confirms the five-bin offset a third time, through a column no earlier
derivation used. Array C is non-512 in exactly two bins, 10 and 22, at 1.125 and
0.750. Standard's float value column is non-1 in exactly two bins, 15 and 3, at
the same two numbers, and `15 - 5 = 10`, `3 - 5 = 22` modulo 24.

Id 35 is a different look, despite carrying Standard's matrix. Its block at
`0xC0B3AB1C` matches the float record for id 35, not Standard's.

**`TGT - ORG` is the float table's hue column.** Converted to degrees with
`360 / 65536`, and matched to each float record, the regression slope is
**1.000** with a residual of **0.003 degrees**. So the float column is in
degrees, and those degrees are the hardware's degrees. There is no scale factor
and no unit puzzle. Searching the whole image for a degrees-to-u16 constant —
`65536 / 360` and its relatives — finds nothing, which fits: the two forms are
built together, not converted at run time.

The blocks for the menu modes, by the id in each head:

| mode | block | mode | block |
|---|---|---|---|
| Monochrome | `0xC0B3B8CC` | Sunset Red | `0xC0B3B318` |
| Vivid | `0xC0B3AC40` | Forest Green | `0xC0B3B43C` |
| Neutral | `0xC0B3AD64` | Powder Blue | `0xC0B3B560` |
| Portrait | `0xC0B3AE88` | FOV Classic Blue | `0xC0B3B684` |
| Landscape | `0xC0B3AFAC` | FOV Classic Yellow | `0xC0B3B7A8` |
| Cinematic | `0xC0B3B0D0` | Warm Gold | `0xC0B3CF9C` |
| Teal and Orange | `0xC0B3B1F4` | OFF | `0xC0B3D308` |

Warm Gold and OFF sit outside the main run, the same way Warm Gold sits at the
end of the gamma map. Standard has none.

**What this rules out.** The register blocks are the camera's own copy of the
look, and they agree with the float table on every number: rotation to 0.003
degrees, saturation exactly. So the look tables in this file are right, and the
difference that remains between a render made from them and the camera's own
JPEG is **not** in these tables. It is in the rest of the chain — the sensor
matrix, which is per-body calibration and not in the image at all, and the CEQ's
other stages, which the firmware names but this file has not decoded:
`CEQ_YGAM`, `CEQ_KNEE`, `CEQ_CLIP`, `CEQ_CORING`, `CEQ_OFFSET`, `CEQ_COMPATI`.

One thing about the rest of the chain is measurable. The look matrix changes
saturation by an amount that depends on the primaries it acts between, and the
camera applies it to its own sensor RGB. Applying it in a wide space rather than
in Rec.709 is worth 0.3 dE over all modes and much more on the four with the
strongest matrices — Powder Blue 10.6 to 8.6, Cinematic 10.4 to 9.0. Going
further out, to ProPhoto or Rec.2020, is far worse, so the camera's own space is
wide but not that wide.

## 5. The gamma curves — one per mode, eleven per contrast step

The tone curve in section 3 is not what renders a JPEG. The camera has a large
bank of gamma curves at `0xC096CF34`, each `0x1000` bytes, each 2048 `u16`
samples with 8190 as full scale. They take linear in and give display-referred
out, so a curve is the mode's base gamma and its tone rendering in one step.

Which curve a mode uses is a table of `(mode id, group)` pairs at `0xC0B3D670`,
36 pairs long. A group is the first of a run of 11 curves, one per contrast
step, and `group + 5` is the `contrast 0` step in the middle:

| mode | group | mode | group |
|---|---|---|---|
| Standard | 5 | Powder Blue | 49 |
| Vivid, Landscape, Cinematic, Teal and Orange, Sunset Red, Forest Green, FOV Classic Blue, FOV Classic Yellow | 16 | Monochrome and its filter variants | 71 |
| Neutral | 27 | OFF | 82 |
| Portrait | 38 | Warm Gold | 433 |

The eight modes that share group 16 really do share it — the map says so.

Two entries are worth care. **Warm Gold is 433, near the end of the map**, not
60: group 60 belongs to id 35, which has no menu entry. And the bank is much
larger than the 88 curves that the first eight groups cover, because each
DuoTone id takes 33: ids 24 to 33 run 103, 136, 169, 202, 235, 268, 301, 334,
367, 400, and id 34 is at 451.

Only OFF's curve is a plain sRGB encode. Every other one is the camera's own
rendering.

## The looks are also a DNG camera profile

The 72-bin table below is not a 72-bin table. **Its first 36 entries are the DNG
`ProfileHueSatMap` that the camera writes into every DNG it takes**, float for
float, hue and saturation alike, with no offset and no resampling. The 128-point
tone curve in section 3 is that same DNG's `ProfileToneCurve`, point for point.

That settles what those two blocks mean, because the DNG specification defines
them: 36 hue divisions of 10 degrees, division 0 at HSV hue 0, applied in linear
ProPhoto RGB converted to HSV. No inference needed.

It does **not** settle the 24-bin table. Applying the 24-bin table as a DNG
`HueSatMap` in ProPhoto HSV makes every mode worse, and its saturation column
runs 1.2 to 2.0 where the DNG map's runs 0.92 to 1.30. The two blocks are for
two different engines: the 36-bin one is what Sigma exports for a raw converter,
and the 24-bin one is what the camera's own hardware reads.

## The internal mode enum

The settings enum that the menu uses is 0 to 15. The tables use a different,
wider enum. There is no translation table in the image, so the conversion is
inline code.

Ver 5.02:

| id | mode | id | mode |
|---|---|---|---|
| 0 | Standard | 12 | Forest Green |
| 1, 2, 16-23 | Monochrome and its filter variants | 13 | Powder Blue |
| 3 | Vivid | 14 | FOV Classic Blue |
| 5 | Neutral | 15 | FOV Classic Yellow |
| 6 | Portrait | 24-33 | DuoTone, one per colour |
| 7 | Landscape | 34 | equal-weight greyscale, no menu entry |
| 8 | Cinematic | 35 | unmapped A, no menu entry |
| 9 | Warm Gold | 36 | OFF |
| 10 | Teal and Orange | 37 | unmapped B, no menu entry |
| 11 | Sunset Red | | |

Id 4 is not used.

### How the ids were fixed

The enum grew over time and every id above an insertion point moved up by one,
so the numbers differ per version. Matching record contents between consecutive
firmwares gives the renaming exactly:

| step | what happened |
|---|---|
| 1.02 -> 2.00 | new id 23 = OFF. Everything from 23 up moved by 1 |
| 2.00 -> 2.03 | no change |
| 2.03 -> 3.00 | new id 12 = Powder Blue, and 10 DuoTone ids |
| 3.00 -> 4.00 | one more DuoTone id. No look changed |
| 4.00 -> 5.02 | new id 9 = Warm Gold. Powder Blue was re-tuned |

That fixes Standard, Monochrome, Vivid, OFF, Powder Blue and Warm Gold.

The other nine looks held ids 5 to 13 in Ver 1.02, in one run. Their order is
the settings enum plus 3. Four of the nine confirm that from their data alone:

- id 8 Cinematic — saturation is 1.00 in every bin, the flat look
- id 10 Teal and Orange — saturation 1.00, and the hue rotations pull warm
  colours one way and cool colours the other, the two-attractor shape
- id 11 Sunset Red — red gain 1.127, the only look besides Warm Gold that
  shifts white balance toward red
- id 12 Forest Green — its largest saturation boost over Standard is at 120 to
  135 degrees, which is green

Neutral, Portrait, Landscape, FOV Classic Blue and FOV Classic Yellow follow
from the same rule but have no independent confirmation. Of those, the FOV
Classic pair is the one to re-check first.

## What each look does

Ver 5.02, matrix rows in R, G, B order. Channel gain is the row sum: 1.000 keeps
white neutral.

| id | mode | R' | G' | B' | gains R/G/B |
|---|---|---|---|---|---|
| 0 | Standard | +0.883 +0.230 -0.113 | +0.000 +1.262 -0.262 | +0.000 -0.049 +1.049 | 1.000 1.000 1.000 |
| 3 | Vivid | +0.812 +0.229 -0.043 | -0.014 +1.137 -0.123 | -0.010 -0.035 +1.045 | 0.998 1.000 1.000 |
| 5 | Neutral | +0.717 +0.285 -0.002 | -0.002 +1.004 -0.002 | -0.002 +0.039 +0.963 | 1.000 1.000 1.000 |
| 6 | Portrait | +0.834 +0.270 -0.102 | -0.010 +1.232 -0.223 | -0.008 -0.109 +1.119 | 1.002 1.000 1.002 |
| 7 | Landscape | +0.852 +0.254 -0.105 | -0.062 +1.322 -0.260 | -0.010 -0.020 +1.029 | 1.000 1.000 1.000 |
| 8 | Cinematic | +0.812 +0.236 -0.008 | +0.201 +0.848 -0.025 | +0.027 +0.320 +0.400 | 1.041 1.023 0.748 |
| 9 | Warm Gold | +1.352 -0.051 -0.113 | -0.014 +1.129 -0.115 | +0.043 -0.203 +1.006 | 1.188 1.000 0.846 |
| 10 | Teal and Orange | +1.035 -0.002 -0.033 | -0.129 +0.641 +0.488 | -0.316 -0.113 +1.430 | 1.000 1.000 1.000 |
| 11 | Sunset Red | +0.934 +0.250 -0.057 | +0.000 +1.082 -0.080 | +0.000 +0.014 +0.967 | 1.127 1.002 0.980 |
| 12 | Forest Green | +0.902 +0.162 -0.064 | -0.016 +1.182 -0.166 | -0.010 +0.000 +1.010 | 1.000 1.000 1.000 |
| 13 | Powder Blue | +0.783 +0.168 -0.010 | +0.277 +0.592 +0.131 | +0.238 -0.262 +0.994 | 0.941 1.000 0.971 |
| 14 | FOV Classic Blue | +0.738 +0.379 -0.117 | +0.000 +1.332 -0.332 | +0.000 -0.068 +1.068 | 1.000 1.000 1.000 |
| 15 | FOV Classic Yellow | +0.799 +0.191 +0.000 | -0.025 +1.025 +0.000 | -0.002 +0.000 +1.002 | 0.990 1.000 1.000 |
| 1 | Monochrome | +0.715 +0.285 +0.000 | +0.000 +1.000 +0.000 | +0.000 +0.041 +0.959 | 1.000 1.000 1.000 |
| 36 | OFF | +0.715 +0.285 +0.000 | +0.000 +1.000 +0.000 | +0.000 +0.041 +0.959 | 1.000 1.000 1.000 |

**OFF is not a full bypass.** Its hue table and its tone curve are the exact
identity, but its matrix is not. Monochrome carries the same matrix, so this
matrix is probably a fixed step that runs whatever the mode is.

Hue table, same version:

| id | mode | mean sat | sat range | largest rotation | hue of peak sat |
|---|---|---|---|---|---|
| 0 | Standard | 1.495 | 1.22 - 2.01 | 11.2 deg | 240 deg |
| 3 | Vivid | 1.826 | 1.24 - 2.30 | 12.7 deg | 240 deg |
| 5 | Neutral | 1.608 | 1.12 - 2.23 | 11.2 deg | 240 deg |
| 6 | Portrait | 1.622 | 1.27 - 2.16 | 8.4 deg | 240 deg |
| 7 | Landscape | 1.612 | 1.12 - 2.04 | 12.7 deg | 240 deg |
| 8 | Cinematic | 1.001 | 0.91 - 1.09 | 9.8 deg | 270 deg |
| 9 | Warm Gold | 1.407 | 1.10 - 1.76 | 20.0 deg | 30 deg |
| 10 | Teal and Orange | 1.003 | 0.84 - 1.06 | 11.2 deg | 0 deg |
| 11 | Sunset Red | 1.650 | 1.34 - 2.18 | 12.7 deg | 240 deg |
| 12 | Forest Green | 1.676 | 1.17 - 2.16 | 14.1 deg | 255 deg |
| 13 | Powder Blue | 1.790 | 1.31 - 2.25 | 30.9 deg | 60 deg |
| 14 | FOV Classic Blue | 1.663 | 1.31 - 1.97 | 11.2 deg | 30 deg |
| 15 | FOV Classic Yellow | 1.707 | 1.22 - 2.16 | 12.7 deg | 240 deg |
| 1 | Monochrome | 0.000 | 0.00 - 0.00 | 0.0 deg | - |
| 36 | OFF | 1.000 | 1.00 - 1.00 | 0.0 deg | - |

Two looks stand apart. Cinematic and Teal and Orange leave saturation at 1.00
and work only through hue rotation and the matrix. Every other look raises
saturation by about 1.4 to 1.8 on average.

## Also in the same blob

- A 72-bin version of the hue table, 1732 bytes per record, at `0xC0B42760`
  (Ver 5.02). Only Standard and OFF have one. Its first 36 entries are the DNG
  `ProfileHueSatMap`, as above.
- Per-mode entries for the Monochrome variants (ids 1, 2, 16-23) and for the ten
  DuoTone colours (ids 24-33). All ten DuoTone matrices are luma matrices with
  slightly different weights.

## The develop code path, as read so far

The JPEG engine's colour code is now partly mapped. Everything below is read
from Ver 5.02 disassembly, with addresses so it can be picked up cold.

**The data plane has exactly two doors.** No code in the image holds a direct
pointer to any look table. Everything goes through two getter functions:
`0xC02D73E8` returns the look-parameter list `0xC0B40074`, and `0xC02D5DE0`
returns the ISP descriptor table `0xC0B38ACC`. Every consumer calls one of
these, so the callers enumerate the whole colour path.

**The matrix loader is `0xC02C5440`**, and it settles two questions in code:

- It reassembles the record as `row0=(h0,h1,h2), row1=(h4,h3,h5), row2=(h7,h8,h6)`
  — the own-channel-first layout this file derived from the DuoTone records,
  now confirmed by the instructions that consume it.
- It divides all nine coefficients by `h0+h1+h2` — the red row's sum — in
  double precision. For most modes that is 512 and changes nothing. For the
  white-shifting modes it rescales the whole matrix: Warm Gold by 0.842,
  Sunset Red by 0.888, Cinematic by 0.961. Renders got worse with this applied,
  so the consumer of these floats has its exposure compensated elsewhere; the
  fact is recorded, not adopted.

A driver at `0xC02C57C0` preloads a float matrix for every mode id in the order
35, 1, 0, 3, 5, 6, 7, 14, 11, 12, 15, ... into an array of 36-byte records.

**The colour-effect slider engine is fully decoded.** The
`PictureQualityFuncTh` thread object (name in ROM at `0xC0B35F74`, constructor
`0xC02CF310`, two real methods `0xC02D4510` and `0xC02D4570`) owns two 4 KB
scratch buffers and builds a two-plane 32x32 chroma LUT of Q9 gains:

- `0xC02D4510` converts the +/-5 slider to Q9: `512 + slider * 512 / 10`.
- `0xC02D4570` blends two source LUTs per plane by the slider in Q10 —
  `(g*A + (1024-g)*B) >> 10` — then scales the result's offset from 512 by a
  per-family strength, `512 + s*delta/256`.
- The source LUTs live at **`0xC0B46A70`: twelve 32x32 grids of 2 KB each**,
  selected by a pointer table at `0xC0B468AC` — a count of 8, then 8 records of
  a tag and 13 pointers. Eight records for the eight look families, the same
  partition as the gamma groups. LUT 0 is the identity (512 everywhere); the
  production grids are mirrored plus/minus radial bowls (saturation-dependent
  gain, up to +/-10 percent); LUTs 1, 8, 10 and 11 are test patterns —
  registration crosses at the corners, quadrant centres and centre.

At slider 0 the blend is the midpoint of a mirrored pair, which is the
identity. So this stage does nothing in the sample frames, and it is ruled out
as the source of the missing hue field.

**A second matrix builder at `0xC02C55A0`, now decoded.** It builds a
YCbCr-domain 3x3 at run time from two per-mode records: a stride-20 record
giving a Q12 luma row and two zero-sum Q9 chroma rows, composed with
`diag(1, 1+a/512, 1+b/512)` per-channel chroma gains from a stride-8 record.
The records are looked up by mode id in RAM tables hung off the parameter
struct `0xC2F1A064` (offsets +0x28 and +0). **The per-mode records are not in
the firmware image as static arrays** — they are built or uploaded at run time,
and finding their writer is still open. The static defaults are in descriptor
entries 24 and 31, and the section on the YC matrix reads them out.

**The effect slider is one system across all tables.** A composer at
`0xC02CFF00`-ish fetches each parameter class's mode record and extrapolates it
away from the id-35 record by a percentage: `out = mode + (mode - base) * pct
/ 100`, via the blender at `0xC02CF758` (the divide-by-100 constant
`0x51EB851F` names the unit). Id 35 — present since Ver 1.02 with Standard's
matrix and no menu entry — is the **blend base for the strength system**. At
effect 0 every path returns the plain tables.

**The leading mechanism for the missing hue field, validated held-out:** a
shared rotation proportional to chroma magnitude. Measured as `degrees per
unit chroma` per hue bin from five Standard-family modes' left halves and
applied to all modes' right halves, it improves eight modes (Standard 3.03 to
2.79 dE, Vivid 2.93 to 2.62, Landscape 2.75 to 2.47, Forest Green 2.31 to
2.13) and moves none of the measurements it was built from. It also explains
the long-standing 0.6 rotation shortfall: a negative-slope shared stage
partially undoes the equaliser's rotations exactly where pixels are saturated.
Two modes regress (Warm Gold, Teal and Orange) because their content sits in
hue bins the sample frame cannot measure — the same four-of-24-bins limit as
before. The field is not shipped; the mechanism is recorded, and one
colour-rich frame per mode completes it.

**The `CUVAREA` care maps are found, and they are not memory colours.**
Parameter-list entries 1 and 2 (at `0xC0B42730` and `0xC0B42748`) are
id-to-pointer tables selecting among three blocks each, ids 0 to 2. The entry-2
blocks are 32x32 grids over the chroma plane. The entry-1 blocks are the same
idea as 21x31 tables, 651 cells.

An earlier version of this file said each grid holds the distance from a target
colour, a bowl whose zero sits just off neutral, with a different target per id,
and read that as protection for three memory colours. **Every part of that was
wrong.** All three grids put their zero on the four centre cells — at neutral
exactly, not off it. The three are one shape at three strengths: `id1 / id0` is
0.942 and `id2 / id0` is 0.754, each with a spread of about 0.04.

The shape is an elliptical distance from neutral. Fitting
`sqrt((a*dCb)^2 + (b*dCr)^2)` gives an axis ratio of 1.481 and a residual of
1.0 percent of full scale, where the best circle leaves 6.9 percent. The value
runs 0 at neutral to 1024 at the corners, and it is linear in distance, not
squared.

**So `CUVAREA` cannot be the mechanism behind the residual field.** The earlier
reading made it the leading candidate, because a correction weighted by the
distance to specific chroma targets gives localized, sign-flipping lobes. A
single monotone bowl centred on neutral cannot. It is a chroma-magnitude weight
with a mild twice-per-turn hue term, so it has no way to act at one hue and
reverse at another. The shoot it was going to be tested by would have found
nothing, because there are no three lobes to look for.

**The `CUVAREA` consumer is decoded.** It exists twice, once per orchestrator:
the entry-2 copy at `0xC02CE260` and the entry-1 copy at `0xC02CDCF0`. Both run
the same steps.

- A base struct comes from `0xC02C1CF0`, which holds it in RAM at `0xC3414470`.
  `0xC02D3A90` is not a fetcher. It adds `0x1c` or `0x110` to that pointer,
  chosen by a byte flag, and returns it.
- Two 9-entry `int` arrays at `+0x90` and `+0xb4` of that struct become floats.
  These are the per-mode strengths, one pair per level.
- If every `+0xb4` entry is zero, the whole stage is skipped.
- A settings flag at `+0x33d` picks the care map: id 1 through `[table + 0xc]`,
  or id 2 through `[table + 0x14]`. The id is a constant offset in the code, not
  a computed index.
- For each cell — 1024 of them for entry 2, 651 for entry 1 — the cell's `u16`
  is bracketed in a ladder of `level * 128`, which is 0, 128, up to 1024 over
  nine levels. The two strengths are then interpolated across that bracket.
- The result is written as two planes of 2048 bytes, at `[obj + 0x190]` and
  `0x800` after it. That is the same two-plane 32x32 shape as the effect-slider
  LUT, so both stages feed the same kind of chroma table.

**The per-mode strengths are not in the image.** They sit in the RAM struct
above, so this stage cannot gate a fit: there is nothing here left to read.

**The parameter space is enumerated.** Two near-identical orchestrators (the
vtable methods at `0xC02C6870` and `0xC02C7448`) call about 55 loader functions
in a fixed sequence — one per parameter class — through a small family of
per-id fetchers (`0xC02C41F8` the generic one, `0xC02C6540` the 580-stride
hue-table find, `0xC02D3A90` and `0xC02D5B50` for the heavyweight classes).
Three of the loaders are per-mode preloaders that fill arrays for every mode id
in the order 35, 1, 0, 3, 5, 6, 7, 14, 11, 12, 15, ...: the mode matrices
(36-byte float records via `0xC02C5440`), the runtime YCbCr matrices
(`0xC02C55A0`), and the float hue tables themselves (576 bytes per mode via
`0xC02C6540`). The rest of the classes — noise, sharpening, exposure — are
scoped but not read.

**The parameter list is seven entries, not five.** An earlier reading stopped at
the tone curve. The full list at `0xC0B40074`:

| entry | data | count | what |
|---|---|---|---|
| 0 | `0xC0B400AC` | 17 | the 24-bin hue tables |
| 1 | `0xC0B42730` | 3 | `CUVAREA` care-map selector |
| 2 | `0xC0B42748` | 3 | `CUVAREA` care-map selector |
| 3 | `0xC0B42760` | 2 | the 72-entry tables, Standard and OFF only |
| 4 | `0xC0B434E8` | 2 | the 128-point tone curves |
| 5 | `0xC0B43CF0` | 22 | ISO ladders: 11 capture ids x a low/high split |
| 6 | `0xC0B43E50` | 22 | ISO ladders, a second class, the same shape |

**The 72-entry table is two maps, and only one of them is the DNG's.** Its 432
floats are `36 hue x 2 sat x 3` twice over. The first map matches the DNG's
`ProfileHueSatMap` exactly, both saturation divisions. The second map is
different data and **has never been used by anything in this project**. Its two
saturation divisions differ from each other, where the DNG's are identical —
so the camera holds a saturation-dependent hue and saturation map, and
deliberately flattens it for the DNG export. That is direct evidence that the
internal pipeline has exactly the chroma-dependent hue behaviour that the
measured residual layer models. Applying the second map as a shared stage,
before or after the mode matrix, does not fit (3.08 to 3.55 dE), and it exists
only for Standard and OFF, so its role is still open.

Also catalogued and not yet decoded: a parameter zone around `0xC0B35F90`
holding Q9 knee-point ladders, a full-scale tone curve ending at `0xC0B35F32`,
a 33-step strength ladder at `0xC0B386E0`, and a further RAM parameter struct
at `0xC3424DC0`. The struct once listed at `0xC2F1BCD8` is not a separate
object: it is one block of the ISO ladders, decoded in the section that follows.

## Entries 5 and 6 are ISO ladders, not colour-mode data

An earlier version of this file read these two entries as "11 mode ids by 2
variants" and said their static source was missing. Both parts were wrong.

Each record is 16 bytes, and field `+4` holds an ISO value. The initialiser
writes that field through the converter at `0xC04D01F8`, which takes an integer
ISO and returns a log form. The 415 records hold the fp's own ISO ladder, from
the extended low of 6 to the extended high of 102400.

The `variant` column is an ISO split. Variant 0 is the low ladder and variant 1
is the high one. The two meet at a shared boundary ISO, so the last key of
variant 0 repeats as the first key of variant 1.

The 11 ids resolve to three ladder shapes. Entry 5, by id group:

| ids | variant 0 (count) | variant 1 (count) |
|---|---|---|
| 0, 1, 2 | 6, 200, 250, 320, 400, 500, 640 (7) | 640 to 102400 (23) |
| 3, 5, 7, 9 | 100, 800, 1000, 1250, 1600, 2000, 2500, 3200 (8) | 3200 to 102400 (16) |
| 4, 6, 8, 10 | 100, 125, 160, 200, 250, 320, 400, 500, 640 (9) | 640 to 102400 (23) |

Entry 6 repeats the last two rows value for value. Its first row is finer: ids
0, 1 and 2 get all 21 steps from 6 to 640. In entry 6 the three groups share
their pointers outright, so its 22 records address only six distinct blocks.

**One function writes the whole region.** The initialiser at `0xC02D73F8` sits
directly after the getter `0xC02D73E8` and runs `0x1248` bytes of unrolled
stores. It holds the base `0xC2F1BCD8` in `r4` and reaches the region with
signed offsets. Past the 4095-byte offset limit it reloads `r8` with
`0xC2F1CC28`, and that reload is what `0xC02D8720` is. That address is not a
getter. `0xC02D6BCC` is not one either: it copies 176 bytes out of
`0xC2F1B060`, which is below the region. Neither address brackets anything.

All 415 stores write field `+4`. No other code in the image forms an address
into the region. A sweep for `movw`/`movt` pairs and for literal-pool words in
`0xC2F1B3B8` to `0xC2F1CD98` finds only this initialiser and the two parameter
tables themselves. So the ISO keys are in the image, and the payload fields
`+0`, `+8` and `+12` are not.

The region ends at `0xC2F1CD98`. An earlier reading gave `0xC2F1CC28`, which is
the start of the last block, not the end of the data.

**Why this does not bear on the colour error.** Four things settle it:

- The key column is ISO. All 415 records are keyed by an ISO value.
- The id column runs 0 to 10 with no gaps. Every colour-mode table in this file
  uses the wide internal enum, which skips id 4 and reaches 37.
- Two of the three id groups alternate odd and even. Colour modes do not
  alternate, and 11 ids collapsing to three parameter sets is not 15 looks.
- The payload has no source in the image, so no per-mode value can be read here.

A search that cannot fail has not been run, so here is what would have found
colour data: an id column in the internal enum, a record count of 15, 17 or 36
to match the other look tables, or a ROM writer for the payload fields. None of
the three is present.

What the 11 ids select is still open. The ladder shapes point at capture modes,
because one group covers extended-low ISO, one covers the native range, and one
varies only above ISO 800. This file does not name them.

## The value columns, tested and rejected

Arrays A and C of a `CEQ24` block are the value multipliers of the float table's
two variants. Nothing in this project had ever rendered with either. Both are
now tested.

**Array A cannot do anything.** It is 1.000 in all 408 bins of all 17 modes. A
render with it applied comes out bit-identical to a render without it, which is
also a check that the test harness applies the column where it says it does.

**Array C makes the render worse.** It is non-1 in 54 bins, held by nine of the
15 menu modes. Applied as a per-bin multiplier at the equaliser, over the
shipped chain, measured on the left half and validated on the right:

| set of modes | baseline L | baseline R | array C, L | array C, R |
|---|---|---|---|---|
| all 14 | 5.340 | 3.239 | 5.453 | 3.754 |
| the nine with a non-1 bin | 5.337 | 2.990 | 5.513 | 3.792 |

Scaling luma alone rather than Y, Cb and Cr together is worse again, at 3.769 on
the held-out half. The six modes with no non-1 bin do not move, as they cannot.
The worst hits are FOV Classic Blue at 2.65 to 4.94, Powder Blue at 4.55 to
6.51, and Monochrome at 1.48 to 2.62.

Monochrome is the sharpest probe of the three. Its output has no chroma, so a
hue-indexed luma column can only show up as lightness differences between
objects of different colour. Monochrome renders at 0.9 dE full frame with no
value stage, and array C moves it the wrong way on data the test never saw. The
camera is not applying that column.

**So the variant question has an answer for the value stage.** Because the two
variants are otherwise one table, and variant 0's value column is all 1.000, the
render says variant 0 — which is the same as saying the fp has no value stage in
this path.

This tests the column at the equaliser, indexed by the hue of the pixel after
the curve. It does not rule out the same numbers being used at another point in
the chain, or against another index. It does rule out the obvious reading.

The script is `xc/valcol.py`.

## The YC matrix, and the camera's own chroma plane

The builder at `0xC02C55A0` copies 16 bytes from `record + 4` and reads them as
eight `s16`. It assembles a 3x3 in double precision:

```
row 0 = (v0, v1, v2)        / 4096      the luma row, Q12
row 1 = (v3, -(v3+v4), v4)  /  512      Cb, Q9
row 2 = (v5, -(v5+v6), v6)  /  512      Cr, Q9
```

Only two coefficients of each chroma row are in the record. The middle one is
the negative of their sum, so both chroma rows are zero-sum by construction.
The two scale constants are exact: `0xC02C5934` holds 1/4096, and `0xC02C593C`
holds 1/512.

The ISP descriptor table at `0xC0B38ACC` is `(pointer, count)` pairs, the same
shape as the look parameter list. Entry 31 is `0xC0B39118`, count 1, stride 20.
Its record is `(100, 0, 1224, 2403, 469, -6, 256, 256, -56, 0)`, which decodes
to:

```
Y  = ( 1224, 2403,  469) / 4096 = ( 0.2988,  0.5867,  0.1145)
Cb = (   -6, -250,  256) /  512 = (-0.0117, -0.4883,  0.5000)
Cr = (  256, -200,  -56) /  512 = ( 0.5000, -0.3906, -0.1094)
```

An earlier version of this file called entries 31 and 24 all-zero neutral
defaults. That is true of entry 24 (`0xC0B39088`, the record `(100, 0, 0, 0)`,
so the chroma gains are the identity). It is not true of entry 31, which holds
a real matrix.

**The luma row is Rec.601 and the chroma rows are not.** The luma weights are
Rec.601 to four decimals, and the three of them sum to exactly 4096. Rec.601 Cb
is `(-0.1687, -0.3313, 0.5)`, where this Cb has almost no red term and sits
close to `0.5 * (B - G)`. Both row pairs span the same zero-sum plane of RGB, so
an exact 2x2 map `T` takes Rec.601 chroma to this chroma, with a residual of
1e-16:

```
T = [ 1.05404  0.33227 ]
    [-0.05939  0.97996 ]
```

In Rec.601 terms the camera's `+Cb` axis is at 3.5 degrees and its `+Cr` axis is
at 107.5 degrees. The two axes are 104 degrees apart, not 90.

**What this predicts, and what it does not.** A rotation applied in this plane
and read back in Rec.601 is `inverse(T) * R * T`. That is a rotation of mean
gain 1.038, with a hue-dependent term of plus or minus 0.278, so the local gain
runs 0.78 to 1.27. The mean is more than 1. The measured rotation shortfall runs
the other way, at 0.6 to 0.7, so this stage cannot be its cause.

**Tested and rejected: the equaliser working in this plane.** The rig applied
the rotation and the gain in the decoded plane instead of in Rec.601, over a
sweep of anchor and rotation scale. Measured on the left half of the frame and
validated on the right:

| plane | best anchor | best rotation scale | left dE | right dE |
|---|---|---|---|---|
| Rec.601 | 300 | 0.6 | 5.301 | 3.416 |
| camera | 285 | 0.7 | 5.352 | 3.386 |

The two are the same render to within 0.03 dE on both halves, and the rotation
scale stays fitted and stays well below 1. So the plane is real and decoded, and
moving the equaliser into it buys nothing. The script is `xc/ycplane.py`.

The test does confirm one thing. The two planes prefer anchors 15 degrees apart,
and `T` maps Rec.601 300 degrees to camera 285.2 degrees. The two forms describe
the same render, which is why the score does not move.

This sweep is not the instrument that fixed the 285-degree anchor, and it does
not bear on it. It runs a stripped chain with no residual layer, on a 15-degree
grid, and it sweeps the anchor together with the rotation scale. The anchor
stands on the register blocks and on the cross-correlation, not on this.

## The differential method, and what is still missing

With the front end measured, a second differential becomes meaningful: compare
**mode-vs-OFF in the camera** against **mode-vs-OFF in the render**. Geometry
cancels, the front end cancels, and what remains is exactly what the model
misses, per hue.

Measured this way, the missing transform is precise and repeatable. Per bin of
`atan2(Cr, Cb)` hue, `camera rotation minus render rotation`, on the one sample
frame (only bins with enough saturated content resolve):

| mode | 90° (red) | 120° | 240° (yellow-green) | 300° (cyan) |
|---|---|---|---|---|
| Standard | **−21.8** | −11.5 | −15.9 | −1.4 |
| Vivid | **−21.0** | −7.7 | −10.5 | −3.9 |
| Cinematic | −3.3 | −7.2 | **−56.3** | **−58.8** |
| Warm Gold | +6.2 | +4.1 | −7.4 | −0.4 |
| Teal and Orange | −0.9 | +0.2 | −13.3 | +0.1 |
| Powder Blue | −15.7 | −15.7 | +11.8 | −3.5 |

The field is per mode and large — and none of the tables in this file produce
it. The rotation column at those bins is 0 to 3 degrees for Standard, and
Cinematic's never exceeds 10.

Mechanisms tested against this field and rejected, so they are not tried again:

- **A shared post-CEQ stage.** The field differs per mode.
- **The equaliser before the curve rather than after.** Both orders render the
  differential almost identically under a hue-preserving curve.
- **The equaliser first with a per-channel curve.** Fixes Warm Gold's warm bins
  exactly, does not produce Standard's −21 or Cinematic's −56.
- **The matrix applied in a companded domain** (`MAT_TOP IGAMMA` suggests one).
  Right direction for Cinematic and Warm Gold, but no single exponent fits: the
  one Cinematic wants overshoots Warm Gold four-fold and turns Powder Blue the
  wrong way by 150 degrees. Standard never moves, its matrix being too mild.
- **The curve before the matrix.** Turns Powder Blue +141 degrees at red.
- **The 72-bin table as a shared in-camera stage.** Its OFF record being the
  exact identity makes this reading attractive, and it does land several bins —
  Cinematic at 120 degrees to within a degree, Teal and Orange's long-standing
  +17 at 240 down to +6 — but it worsens the whole (3.1 to 3.5 dE right-half),
  so as a straight extra stage it is wrong too.

What would settle it: a frame with saturated content in every hue bin — this
scene resolves only four to five of the 24 — so the missing field can be read
completely instead of extrapolated from four points per mode. The differential
needs only one such frame shot in each mode plus OFF.

## The measured residual layer, and the luma row

**What the sample frame actually covers**, measured rather than asserted. Per
hue bin of `atan2(Cr, Cb)`, counting camera-JPEG pixels above the chroma
threshold of 0.12 that `metric2` itself uses, a bin counts as resolved at 300
pixels:

| mode | bins resolved | mode | bins resolved |
|---|---|---|---|
| Vivid | 10 of 24 | Warm Gold | 5 of 24 |
| Powder Blue | 9 of 24 | Cinematic | 4 of 24 |
| Standard | 7 of 24 | Teal and Orange | 4 of 24 |

The frame is not short of saturated pixels. Each mode has 61,000 to 96,000 of
them. The content is concentrated: bins 8 and 9 hold about 130,000 pixels each
across six modes, where bins 16 to 23 hold a few thousand between them, and bins
0 to 3 hold none at all. So the limit is the spread of hues, not the amount of
colour, and it falls hardest on the modes whose content sits in the thin bins.

With the field measurable in 9 of 24 bins (binning by the decode's hue rather
than the OFF image's unlocked five more bins from the same frame), the residual
between render and camera is read directly as per-mode tables: a rotation and a
gain per bin of the decode hue, plus **a per-mode luma row** — the camera's
chroma stages preserve a per-mode luma, not Rec.601, and the difference appears
as a luma shift linear in Cb and Cr. Teal and Orange carries the largest
weights (its cb coefficient is -1.6), which was most of its long-standing luma
error; the runtime matrix builder at `0xC02C55A0` holds the same concept as a
Q12 per-mode luma row, confirming the mechanism class in code.

**The luma row's mechanism is now read out of the register-write path.** The
function at `0xC02D5E18` fetches descriptor entry 31 — the YC matrix record — 142
times and writes fields into a register block. The structure is regular: 57
groups at a stride of 20 bytes, spanning register offsets `0xA88` to `0xEEA`,
cycling with a period of four groups. **Only the luma fields are written.** The
three offsets used are `+4`, `+6` and `+8`, which are the Q12 luma row. The
chroma fields `+10` to `+16` are never written by this path.

So the camera broadcasts one per-mode luma row to 57 register slots across the
pipeline. That is why every chroma stage preserves the same per-mode luma rather
than Rec.601, and it raises the earlier note from "the mechanism class exists in
code" to "the mechanism is this, and here is where it is written". The values
stay undecoded, because the per-mode records are built in RAM and only the id-100
default is static.

All of the residual layer is measured as medians of camera-vs-camera
differentials on the left half of the sample frame and validated on the right
half, where every mode improves. It ships as a distinct layer in the render,
documented as measured rather than derived.

Also settled while reading the code: the two double-precision constants at
`0xC0970044` and `0xC097008C` are the standard XYZ-to-sRGB matrix with
per-channel white-balance diagonals baked in — `diag(0.492, 1.000, 0.649)` and
`diag(0.480, 1.210, 1.569)` — the camera's two calibration illuminants,
consumed by the double-precision 3x3 inverter at `0xC02C6CD8`. An earlier note
read this region as garbage floats; they are doubles.

## How close this gets

One frame, processed in the camera by all fifteen looks, against the same frame
rendered from its DNG. Warp fitted and undone, full frame, mean CIE Lab dE,
against a median 8.2 dE between one camera mode and the next:

| mode | dE | mode | dE |
|---|---|---|---|
| OFF | 0.9 | Teal and Orange | 3.1 |
| Monochrome | 0.9 | Sunset Red | 3.5 |
| FOV Classic Yellow | 2.0 | Warm Gold | 3.8 |
| Neutral | 2.4 | Cinematic | 4.4 |
| Forest Green | 2.5 | Powder Blue | 4.5 |
| Landscape | 2.5 | | |
| Portrait | 2.5 | | |
| Standard | 2.6 | | |
| Vivid | 2.8 | | |
| FOV Classic Blue | 3.0 | | |

Mean 2.7 with one flat residual band; **2.46 with two** — the residual layer
split into two chroma bands of the decode (below and above 0.08, blended over
0.03), because the field is chroma-dependent within a bin: Powder Blue's pastel
blues need 1.7x chroma where its saturated blues need none. Each round was
measured on the left half and validated on the right (2.30 to 2.22 to 2.03 on
the increments' own metric). Final per-mode, full frame: OFF and Monochrome
0.9, ten modes between 2.0 and 3.1, Warm Gold 3.5, Powder Blue 3.9, Cinematic
4.2 — against a median 8.2 dE between one camera mode and the next.

What remains sits in hue variance inside bins the frame measures thinly, and in
Cinematic's chroma at 0.92. The next measurable gain needs hue coverage this
frame does not have.

## Unread data

Firmware objects this file knows exist and has not decoded. **This list is the
gate on fitting** — see `CLAUDE.md`. Each entry is a place where real per-mode
data sits, so a fitted constant added while any of these stands is a fit on top
of a fact.

- **The second 36-entry map** in the 72-entry table, present for Standard and
  OFF. Unlike the DNG's copy its two saturation divisions differ, so the camera
  holds a saturation-dependent hue and saturation map and flattens it for
  export. Applying it as a shared stage does not fit (3.08 to 3.55 dE), so its
  role is open.
- **The `CEQ` and `PST_TOP` chroma stages**: `CEQ_YGAM`, `CEQ_KNEE`, `CEQ_CLIP`,
  `CEQ_CORING`, `CEQ_OFFSET`, `CEQ_COMPATI`, `CUVCONT`, `CSUP`, `ECSUP`,
  `C_SAT_C`. The firmware names them and this file has not found their data.
  Best candidate for the strong looks' missing saturation.
- **The per-mode YC matrix records**, the stride-20 class that `0xC02C55A0`
  reads. Only the id-100 default is static, at descriptor entry 31. The per-mode
  records live in RAM off `0xC2F1A064 + 0x28`, and nothing in the image writes
  them. The words after the luma triple are decoded — they are the two chroma
  rows — so what is left here is the per-mode data, not the format.
- **Descriptor entry 30**, `0xC0B39100`, one 24-byte record
  `(100, 0, 632, -92, -28, 646, 0, -134, 566, 0, -54, 0)`. Three Q9 rows that
  each sum to 512. Read in the own-channel-first layout, its green row is
  `(0.000, 1.262, -0.262)`, which is Standard's green row exactly. Its other two
  rows are not Standard's. No consumer found yet.
- **The coarse `CEQ_ORG` / `CEQ_TGT` pair**, named beside the 24-bin ones and
  never located.
Arrays A and C used to stand here. Both are tested against the camera now, and
neither belongs in the render. The section on the value columns has the numbers.
The `CUVAREA` consumer used to stand here. It is decoded, and its per-mode
strengths live in RAM rather than in the image, so nothing about it is readable
and it gates nothing. The section on the care maps has the algorithm.

## Open questions

Interpretation, not missing data. These do not gate anything.

- What selects the hue table's variant, and when. For the 15 menu modes it can
  only ever change the value column, and the render rejects variant 1's, so the
  question bears on nothing this file measures.
- Why the camera's output shows only 0.6 to 0.7 of the table's rotation, and
  what the per-hue base shift is. Both are measured and both lack a mechanism.
  Tested and rejected against held-out data: the equaliser working in symmetric
  `(B-Y, R-Y)` axes rather than Cb/Cr (4.05 against 2.84), a fixed 512
  denominator for the saturation array (overshoots the two `B=1024` modes), a
  chroma-dependent gain (the fit collapses to flat), and the equaliser working
  in the camera's own decoded chroma plane, which moves the render by 0.03 dE
  and predicts a mean gain of 1.038, the wrong way.
- What Cinematic and Powder Blue do that the other twelve do not. Both render at
  about 0.8 of the reference's chroma under the same trim that puts every other
  mode within a few percent.
- The settings enum to internal id conversion. It is inline code, not a table.
- What the 11 ids of parameter list entries 5 and 6 select. They are not colour
  modes. Their ladder shapes point at capture modes, and nothing names them.
- What ids 34, 35 and 37 are. None has a menu entry. Id 35 has existed since
  Ver 1.02, carries Standard's matrix, and is the blend base for the effect
  strength system. Id 37 arrived in Ver 2.00 next to OFF.
- The last five name assignments, above.
