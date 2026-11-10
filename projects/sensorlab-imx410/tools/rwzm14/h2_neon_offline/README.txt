Offline RAW14 horizontal 2:1 averaging proof — 2026-10-30

RESULT
The compiled ARMv7 NEON routine passed 526 test calls in Unicorn 2.1.4.
This is a row-kernel proof only. Nothing was deployed or run on a camera.
The proof is stored in projects/sensorlab-imx410/tools/rwzm14/h2_neon_offline/.
No pre-existing repository file was edited. No package was installed.

DATA CONTRACT
Little-endian, right-justified 14-bit samples stored in 16-bit containers.
Input values are 0..16383. The function does not detect or unpack RAW14.
The two input Bayer phases in each row are processed independently:
  [x0, x1, x2, x3] -> [(x0+x2+1)>>1, (x1+x3+1)>>1]
Output retains the row's starting CFA phase and has half the input width.
There is no operation between rows and no image-stride wrapper.
The sensor's preceding vertical mode and CFA phase remain caller concerns.

This is rounded averaging: it retains a 14-bit output range and low-order
precision rather than truncating to 12 bits. It does not retain all 15 bits
of the unscaled sum or make the spatial reduction reversible.

INTERFACE
int h2_raw14_u16_row(uint16_t *dst, const uint16_t *src, uint32_t width)
ARM state, AAPCS. Width is the number of input samples, not bytes.
Width must be a multiple of 16. Invalid widths return -1 without data reads
or writes. Zero width succeeds without data reads or writes. Otherwise,
the caller must supply valid disjoint buffers, each at least 2-byte aligned.
Input occupies width*2 bytes; output occupies width bytes.

COMPILED CORE
  vld2.32   {d0-d3}, [r1]!
  vrhadd.u16 q0, q0, q1
  vst1.16   {d0-d1}, [r0]!
  subs      r2, r2, #16
  bne       loop

Every 16 input samples use three vector instructions and two loop-control
instructions: 5 instructions, not 5 cycles. Actual latency and throughput
are not measured. Per row the total is 6 + 5*(width/16) instructions.
The routine is 52 bytes. Only q0-q1 (d0-d3) are used; d16-d31 are untouched.
Compiled SHA256: 66073162da74bdd73f0a16c58da3ad122558d98f52b5aa6e5eeb2e7c9f439320

VALIDATION
Real clang-assembled ARM bytes executed in Unicorn configured as Cortex-A7.
Python reference is independent of the NEON instruction implementation.
Coverage: edge-value Cartesian pairs, deterministic random rows, all four
CFA phases with seven independent rows each, widths 0 through 6016, even
pointer offsets, source preservation, destination guards, access extents,
invalid-width rejection, and r4-r11/SP/LR/d4-d31/FPSCR preservation.
A bounded mutant replacing rounded averaging with unrounded averaging is
detected, showing the low-bit rounding assertion is active.
Detailed counts and conditions are in results.json.

The first sandboxed run stopped inside Unicorn host initialization before
any ARM code executed. The identical script passed with an approved local
execution outside that sandbox. This was not a kernel failure.

RUN
From the repository root:
  python3 projects/sensorlab-imx410/tools/rwzm14/h2_neon_offline/test_h2_raw14.py

DEPLOYMENT NOT COVERED
Packed RAW14 handling, firmware hook selection, source/destination ownership,
DMA completion, cache maintenance, task scheduling, real memory bandwidth,
end-to-end recording bit depth, frame deadlines, and thermal behavior.
Host execution time is not a camera-performance measurement.
