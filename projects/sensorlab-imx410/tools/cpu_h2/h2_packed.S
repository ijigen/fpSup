/* SensorLab CPU x2 (RECIPE > ISP HBIN "CPU x2"): horizontal 2:1 same-colour EQUAL-WEIGHT binning of a packed
 * CinemaDNG raster, in place.  Offline unit: tools/cpu_h2/test_h2_packed.py (unicorn, real bytes).
 *
 * Data: DNG uncompressed packing, MSB first, rows contiguous (no padding).  A row is R G R G ... (or G B ...).  With a
 * row width that is a multiple of 4 pixels a pair never straddles rows, so the whole raster is ONE stream:
 *   out[2k]   = (in[4k]   + in[4k+2] + 1) >> 1
 *   out[2k+1] = (in[4k+1] + in[4k+3] + 1) >> 1
 * In place is safe: the output cursor is always at most half the input cursor, and each step loads its input
 * before it stores.  Only d0-d15 (q0-q7) are used: TK-OS saves d0-d15 + FPSCR on a task switch / IRQ, not d16-d31.
 * d8-d15 are callee-saved (AAPCS): pushed.
 *
 * int h2_p12(u8 *dst, const u8 *src, u32 nbytes)  12-bit, 2 px / 3 B: 48 B (32 px) per step; nbytes % 48 else -1
 * int h2_p14(u8 *dst, const u8 *src, u32 nbytes)  14-bit, 4 px / 7 B: 28 B (16 px) per step; nbytes % 28 else -1
 *     h2_p14 reads 4 bytes past each step's 28 (so past the input end on the last step) and writes 1 byte past
 *     each 7-byte output group (overwritten by the next group; past the output end on the last one -- inside the
 *     input when in place).  h2_frame (h2_frame.c) runs the last step from a 32-byte copy.
 * nbytes = input bytes; dst == src (in place) or a separate buffer of nbytes / 2 (+ 1 for h2_p14).  0 = done. */
.syntax unified
.arch armv7-a
.fpu neon
.arm
.text
.align 3

/* ---- packed 12: 16 groups (b0 b1 b2) = 32 px in, 8 groups (24 B) out ---------------------------------------- */
.global h2_p12
.type h2_p12, %function
h2_p12:
    vpush   {d8-d15}
    cmp     r2, #0
    beq     .L12done
.L12loop:
    cmp     r2, #48
    blo     .L12bad
    vld3.8  {d0, d2, d4}, [r1]!          /* groups 0..7:  d0 = b0, d2 = b1, d4 = b2 */
    vld3.8  {d1, d3, d5}, [r1]!          /* groups 8..15 -> q0 = b0, q1 = b1, q2 = b2 of 16 groups */
    vuzp.8  d0, d1                       /* d0 = even groups (pair k), d1 = odd groups (pair k + 1) */
    vuzp.8  d2, d3
    vuzp.8  d4, d5
    /* first sample of a group: (b0 << 4) | (b1 >> 4) */
    vshll.u8   q3, d0, #4
    vshr.u8    d14, d2, #4
    vaddw.u8   q3, q3, d14               /* q3 = A of the even groups */
    vshll.u8   q4, d1, #4
    vshr.u8    d15, d3, #4
    vaddw.u8   q4, q4, d15               /* q4 = A of the odd groups */
    vrhadd.u16 q3, q3, q4                /* q3 = (A0 + A1 + 1) >> 1 */
    /* second sample: ((b1 & 15) << 8) | b2 */
    vshl.u8    d14, d2, #4
    vshr.u8    d14, d14, #4
    vshll.u8   q5, d14, #8
    vaddw.u8   q5, q5, d4                /* q5 = B even */
    vshl.u8    d15, d3, #4
    vshr.u8    d15, d15, #4
    vshll.u8   q6, d15, #8
    vaddw.u8   q6, q6, d5                /* q6 = B odd */
    vrhadd.u16 q5, q5, q6                /* q5 = (B0 + B1 + 1) >> 1 */
    /* pack: b0 = A >> 4, b1 = (A & 15) << 4 | B >> 8, b2 = B & 255 */
    vshrn.u16  d0, q3, #4
    vmovn.u16  d1, q3
    vshl.u8    d1, d1, #4
    vshrn.u16  d2, q5, #8
    vorr       d1, d1, d2
    vmovn.u16  d2, q5
    vst3.8  {d0, d1, d2}, [r0]!
    subs    r2, r2, #48
    bne     .L12loop
.L12done:
    mov     r0, #0
    vpop    {d8-d15}
    bx      lr
.L12bad:
    mvn     r0, #0
    vpop    {d8-d15}
    bx      lr
.size h2_p12, .-h2_p12

/* ---- packed 14: 4 groups of 7 B (px0..px3 = A0 B0 A1 B1) = 16 px in, 2 groups (14 B) out --------------------- *
 * One 7-byte group gives one output pair ((A0 + A1 + 1) >> 1, (B0 + B1 + 1) >> 1); two groups -> one 7-byte output
 * group.  A sample is the big-endian 32-bit word at its first byte (vtbl, then vrev32 into a LE lane), shifted right
 * by 18 / 12 / 14 / 16 (vshl by a negative lane count) and masked to 14 bits.  An output group is assembled in a
 * 64-bit lane: v0 << 42 | v1 << 28 | v2 << 14 | v3, byte-reversed, stored as 8 bytes (the 8th is the next group's). */
.global h2_p14
.type h2_p14, %function
h2_p14:
    push    {r4, lr}
    vpush   {d8-d15}
    cmp     r2, #0
    beq     .L14done
    adr     r12, .L14tab
    add     r3, r12, #64
    vld1.32 {d12, d13}, [r3]             /* q6 = -18, -12, -14, -16 */
    vmov.i32 q7, #0x3F00
    vorr.i32 q7, #0xFF                   /* q7 = 0x00003FFF in every lane (0x3FFF is not one immediate) */
.L14loop:
    cmp     r2, #28
    blo     .L14bad
    vld1.8  {d0, d1, d2, d3}, [r1]       /* 32 bytes: 28 of this step + 4 look-ahead */
    add     r1, r1, #28
    mov     r4, #0
.L14half:                                /* r4 = 0: groups 0, 1 -> output group 0; r4 = 32: groups 2, 3 -> 1 */
    add     r3, r12, r4
    vld1.8  {d8, d9, d10, d11}, [r3]     /* gather indices: first group (d8, d9), second (d10, d11) */
    vtbl.8  d4, {d0, d1, d2, d3}, d8
    vtbl.8  d5, {d0, d1, d2, d3}, d9
    vtbl.8  d6, {d0, d1, d2, d3}, d10
    vtbl.8  d7, {d0, d1, d2, d3}, d11
    vrev32.8 q2, q2
    vrev32.8 q3, q3
    vshl.u32 q2, q2, q6
    vshl.u32 q3, q3, q6
    vand    q2, q2, q7                   /* q2 = A0 B0 A1 B1 of the first group */
    vand    q3, q3, q7                   /* q3 = the second group */
    vrhadd.u32 d4, d4, d5                /* d4 = (v0, v1) */
    vrhadd.u32 d6, d6, d7                /* d6 = (v2, v3) */
    vmovl.u32 q4, d4                     /* d8 = v0, d9 = v1 (u64) */
    vmovl.u32 q5, d6                     /* d10 = v2, d11 = v3 */
    vshl.u64 d8, d8, #42
    vshl.u64 d9, d9, #28
    vshl.u64 d10, d10, #14
    vorr    d8, d8, d9
    vorr    d10, d10, d11
    vorr    d8, d8, d10                  /* d8 = the 56-bit output group, LSB-aligned */
    vshl.u64 d8, d8, #8                  /* bits 63..8: so the byte-reversed group starts at byte 0 */
    vrev64.8 d8, d8
    vst1.8  {d8}, [r0]                   /* 7 bytes + 1 (the next group's first byte; overwritten next) */
    add     r0, r0, #7
    add     r4, r4, #32
    cmp     r4, #64
    bne     .L14half
    subs    r2, r2, #28
    bne     .L14loop
.L14done:
    mov     r0, #0
    vpop    {d8-d15}
    pop     {r4, pc}
.L14bad:
    mvn     r0, #0
    vpop    {d8-d15}
    pop     {r4, pc}
.align 3
.L14tab:
    /* group 0 (bytes 0..6): px0 word at byte 0, px1 at 1, px2 at 3, px3 at 5 */
    .byte 0, 1, 2, 3,     1, 2, 3, 4,     3, 4, 5, 6,     5, 6, 7, 8
    /* group 1 (bytes 7..13) */
    .byte 7, 8, 9, 10,    8, 9, 10, 11,   10, 11, 12, 13, 12, 13, 14, 15
    /* group 2 (bytes 14..20) */
    .byte 14, 15, 16, 17, 15, 16, 17, 18, 17, 18, 19, 20, 19, 20, 21, 22
    /* group 3 (bytes 21..27; px3 reads 26..29) */
    .byte 21, 22, 23, 24, 22, 23, 24, 25, 24, 25, 26, 27, 26, 27, 28, 29
    .word -18, -12, -14, -16
.size h2_p14, .-h2_p14
