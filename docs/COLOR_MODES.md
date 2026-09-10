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

Bin `i` covers hue angle `15 * i` degrees, with bin 0 at red. **Bin 0 is now
measured, not inferred.**

The measurement does not need the firmware. One frame was processed in the
camera by every mode in turn, which gives a set of JPEGs of the same scene with
the same geometry and only the look between them. Comparing each mode's JPEG
against Standard's, per bin of the Cb/Cr angle, gives the rotation and the
chroma gain that the camera really applied. Cross-correlating those gains
against the table, over all 24 possible offsets, has one peak. The mild looks
agree on it on their own: Vivid at 0.94, Landscape at 0.85, Neutral at 0.75.

The peak puts bin 0 at red, as inferred before, but half a turn from where a
Rec.601 `atan2(Cr, Cb)` puts red. **The camera carries Cb and Cr with the
opposite sign.** So a reader that computes the angle as `atan2(Cr, Cb)` must
subtract `288.65` degrees, not `108.65`.

The code that consumes the table still has not been found, so the sign is read
off the camera's behaviour rather than off an instruction.

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

Every matrix here desaturates. They are written for the camera's own internal
RGB, not for a signal that a raw converter has already brought to Rec.709. A
converter that applies them as they stand desaturates twice. Applying each mode
as its difference from Standard instead — `M_mode * inverse(M_Standard)` — scores
about 0.3 dE better against the camera's own JPEGs, and makes Standard the
identity.

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

## 4. The gamma curves — one per mode, eleven per contrast step

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

## How close this gets

One frame, processed in the camera by 14 modes, against the same frame rendered
from its DNG with the tables here. Scored as mean CIE Lab dE, on flat parts of
the picture only: the RAW has no barrel correction and the JPEG does, so the two
frames do not lie on top of each other, and any pixel on an edge is a different
subject in each.

For scale, the camera's own modes sit a median 8.16 dE apart from each other.

| mode | dE | mode | dE |
|---|---|---|---|
| Monochrome | 1.3 | Vivid | 4.6 |
| Neutral | 3.1 | Sunset Red | 6.1 |
| Portrait | 3.1 | Teal and Orange | 6.9 |
| Forest Green | 3.5 | FOV Classic Yellow | 7.5 |
| Standard | 3.7 | Warm Gold | 7.7 |
| FOV Classic Blue | 3.8 | Cinematic | 10.4 |
| Landscape | 4.3 | Powder Blue | 10.7 |

Nine of the 14 are under 4.6, which is well inside the gap between one mode and
the next. The last four are not, and they are the four with the strongest
matrices. Cinematic and Powder Blue come out at about half the reference's
chroma.

Cinematic resists more than a wrong constant would. Fitting a per-hue rotation
and gain straight from the camera's own JPEGs, then testing it on a half of the
frame the fit never saw, still leaves it at 10.8. So its look is not a luma
curve plus a hue transform at all, and something in its chain is still missing.

## Open

- Which of the two variants in the hue table is used, and when.
- What Cinematic, Powder Blue, Warm Gold and FOV Classic Yellow do that the
  other ten do not. All four have the strongest matrices.
- The settings enum to internal id conversion. It is inline code, not a table.
- What ids 34, 35 and 37 are. None has a menu entry. Id 35 has existed since
  Ver 1.02 and carries Standard's matrix. Id 37 arrived in Ver 2.00 next to OFF.
- The last five name assignments, above.
