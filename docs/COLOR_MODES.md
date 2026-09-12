# The colour-mode look tables

The fp's colour modes are three static tables in the firmware, one entry per
mode. This is where the looks live. It is not the XC container — that is menu
artwork, see [XC_CONTAINER.md](XC_CONTAINER.md).

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
`0xC02D73E8`. The tone curve is entry 4 of the same list. The matrix table has
no pointer to it anywhere in the image, so the code must reach it by an offset
from a nearby base.

## 1. The hue table — 580 bytes per mode

```
u32          mode id
float[24][2][3]   24 hue bins x 2 variants x (hue, sat, val)
```

The three floats are a hue rotation in degrees, a saturation multiplier and a
value multiplier. Two entries prove that. Monochrome is saturation 0.000 in
every bin. OFF is hue 0.0, saturation 1.000 and value 1.000 in every bin.

The two variants hold the same hue and almost always the same saturation. Only
the value multiplier differs, in 54 of 408 bins in Ver 5.02. What selects the
variant is not known.

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

**Standard has no block.** Id 0 is absent from all 61, the same way id 9 is
absent from the middle of the gamma map. The ids that are present are 1 to 36
except 0 and 4, plus 39 and 100.

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

**A second matrix builder at `0xC02C55A0` is the best remaining candidate.**
It builds a YCbCr-domain 3x3 at run time from two per-mode records: a stride-20
record giving a Q12 luma row and two zero-sum Q9 chroma rows — cross-terms in a
chroma matrix are exactly a global hue rotation — composed with
`diag(1, 1+a/512, 1+b/512)` per-channel chroma gains from a stride-8 record.
The records are looked up by mode id in RAM tables hung off the parameter
struct `0xC2F1A064` (offsets +0x28 and +0), with all-zero neutral defaults
(id 100) in descriptor entries 31 and 24. **The per-mode records are not in
the firmware image as static arrays** — they are built or uploaded at run
time, and finding their writer is the next step of this campaign.

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

**The `CUVAREA` care maps are found.** Parameter-list entries 1 and 2 (at
`0xC0B42730` and `0xC0B42748`) are id-to-pointer tables selecting among three
blocks each, ids 0 to 2. The entry-2 blocks are 32x32 grids over the chroma
plane holding the **distance from a target colour** — a radial bowl whose zero
sits just off neutral, a different target per id. The entry-1 blocks are the
same idea as 21x31 tables in a (position, level) form with a triangular depth
envelope. Three targets, per-plane distance maps: this is the machinery behind
the register name `PST_TOP CUVAREA CARE_SEL` — chroma processing weighted by
the distance to protected memory colours (three of them, presumably skin, sky
and foliage).

Why it matters: corrections weighted by distance to specific chroma-plane
targets produce exactly the localized, sign-flipping rotation lobes measured
in the missing field — strong near a target, reversing across it, absent far
away. The consumer code and the per-mode strengths are the open ends; the
complete 24-bin field from a colour-rich frame would show three lobes centred
on the targets if this is the stage, which makes the shoot a direct test of
it.

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
| 5 | `0xC0B43CF0` | 22 | **unread**: 11 mode ids x 2 variants, each a RAM pointer and a count |
| 6 | `0xC0B43E50` | 22 | **unread**: the same shape, a second class |

Entries 5 and 6 hold `(mode id, variant, pointer, count)` records whose pointers
run from `0xC2F1B3B8` to `0xC2F1CC28` — 6.2 KB of per-mode parameter RAM,
bracketed by two more getters of the `0xC02D5DE0` family at `0xC02D6BCC` and
`0xC02D8720`. The data is uploaded there at run time; its static source has not
been found.

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
a 33-step strength ladder at `0xC0B386E0`, and further RAM parameter structs at
`0xC2F1BCD8` and `0xC3424DC0`.

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

With the field measurable in 9 of 24 bins (binning by the decode's hue rather
than the OFF image's unlocked five more bins from the same frame), the residual
between render and camera is read directly as per-mode tables: a rotation and a
gain per bin of the decode hue, plus **a per-mode luma row** — the camera's
chroma stages preserve a per-mode luma, not Rec.601, and the difference appears
as a luma shift linear in Cb and Cr. Teal and Orange carries the largest
weights (its cb coefficient is -1.6), which was most of its long-standing luma
error; the runtime matrix builder at `0xC02C55A0` holds the same concept as a
Q12 per-mode luma row, confirming the mechanism class in code.

All of it is measured as medians of camera-vs-camera differentials on the left
half of the sample frame and validated on the right half, where every mode
improves. It ships as a distinct layer in the render, documented as measured
rather than derived.

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

- **Parameter list entries 5 and 6**, `0xC0B43CF0` and `0xC0B43E50`, 22 records
  each: 11 mode ids by 2 variants of `(id, variant, pointer, count)`, addressing
  `0xC2F1B3B8` to `0xC2F1CC28` — 6.2 KB of per-mode parameter RAM. The static
  source that fills it has not been found. Two getters of the `0xC02D5DE0`
  family bracket the region, at `0xC02D6BCC` and `0xC02D8720`.
- **The second 36-entry map** in the 72-entry table, present for Standard and
  OFF. Unlike the DNG's copy its two saturation divisions differ, so the camera
  holds a saturation-dependent hue and saturation map and flattens it for
  export. Applying it as a shared stage does not fit (3.08 to 3.55 dE), so its
  role is open.
- **The `CEQ` and `PST_TOP` chroma stages**: `CEQ_YGAM`, `CEQ_KNEE`, `CEQ_CLIP`,
  `CEQ_CORING`, `CEQ_OFFSET`, `CEQ_COMPATI`, `CUVCONT`, `CSUP`, `ECSUP`,
  `C_SAT_C`. The firmware names them and this file has not found their data.
  Best candidate for the strong looks' missing saturation.
- **The words after the luma triple** in the YCMAT block at `0xC0B39118`:
  `-6, 256, 256, -56, 0, 100, ...`. Likeliest path to the rotation shortfall.
- **The coarse `CEQ_ORG` / `CEQ_TGT` pair**, named beside the 24-bin ones and
  never located.
- **Arrays A and C** of a `CEQ24` block are identified as the two value columns,
  but nothing reads them: their effect on the render is untested.
- **The `CUVAREA` consumer**, and the per-mode strengths that drive it. The
  three care maps are decoded; the code that applies them is not.

## Open questions

Interpretation, not missing data. These do not gate anything.

- Which of the two variants in the hue table is used, and when.
- Why the camera's output shows only 0.6 to 0.7 of the table's rotation, and
  what the per-hue base shift is. Both are measured and both lack a mechanism.
  Tested and rejected against held-out data: the equaliser working in symmetric
  `(B-Y, R-Y)` axes rather than Cb/Cr (4.05 against 2.84), a fixed 512
  denominator for the saturation array (overshoots the two `B=1024` modes), and
  a chroma-dependent gain (the fit collapses to flat).
- Why Standard has no register block.
- What Cinematic and Powder Blue do that the other twelve do not. Both render at
  about 0.8 of the reference's chroma under the same trim that puts every other
  mode within a few percent.
- The settings enum to internal id conversion. It is inline code, not a table.
- What ids 34, 35 and 37 are. None has a menu entry. Id 35 has existed since
  Ver 1.02, carries Standard's matrix, and is the blend base for the effect
  strength system. Id 37 arrived in Ver 2.00 next to OFF.
- The last five name assignments, above.
