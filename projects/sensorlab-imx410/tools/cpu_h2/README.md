# CPU ×2: in-place NEON horizontal 2:1 for packed DNG rasters (2026-11-05, offline)

This is the kernel behind RECIPE > ISP HBIN "CPU ×2". It does same-colour, equal-weight, rounded binning: `(a+b+1)>>1`. Bei chose equal weight only.

## Files

- `h2_packed.S` holds the two kernels:
  - `h2_p12`: packed 12-bit, 48 B (32 px) per step.
  - `h2_p14`: packed 14-bit, 28 B (16 px) per step.
- Both are MSB first, like the DNG packing, and work in place.
- `test_h2_packed.py` runs the clang-assembled bytes under unicorn (Cortex-A9) against an independent Python reference.

## Key facts

- **The whole raster is one stream.** Row widths are multiples of 4 px, so a same-colour pair never crosses a row and there is no row loop.
- **In place is safe.** The output cursor is at most half the input cursor, and each step loads before it stores.
- **Registers.** Only q0–q7 (d0–d15) are used, because TK-OS saves only d0–d15 + FPSCR. d8–d15 are pushed (AAPCS).
- **`h2_p14` touches a little past its range:**
  - It reads 4 B past each 28-byte step, which on the last step is past the input end.
  - It writes 1 B past each 7-byte output group; the next group overwrites it.
  - The frame wrapper must run the last step from a 32-byte copy.

## Results (unicorn instruction counts, not time)

| Kernel | Instructions / input px |
|---|---|
| p12 | 1.005 |
| p14 | 4.08 |

## Validation

- **Suite:** 6 tests OK:
  - edge pairs;
  - random streams, in place and separate;
  - a 6048×3 raster against row-by-row processing;
  - guards on the exact read/write extent;
  - AAPCS preservation (r4–r11, sp, d8–d15);
  - bad sizes.
- **Mutation check:** `--mutate` 9/9 caught (truncating mean, nibble mask, pair split, shift, mask, pack shift, d8 save).

## Not done

- Real camera throughput: cached alias plus MVA-range cache maintenance.
- The frame hold, worker task, header template and writer length, which follow the Lossless mechanism.
