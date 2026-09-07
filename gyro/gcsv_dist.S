/* ============================================================================
 * The lens's own distortion, in the profile the camera writes.
 * ============================================================================
 *
 * The arithmetic is distfit.inc.S, included as it stands.  That is a departure
 * from how the rest of this edition was built -- everything else was written
 * fresh against v1.4's source rather than lifted from it -- and the reason is
 * worth stating.
 *
 * What was not reused elsewhere was STRUCTURE: slots, decimation, catch-up, a
 * state machine wired through the old logger's state block.  distfit.inc.S is
 * none of that.  It touches no state block, calls nothing outside itself, and
 * reaches only absolute firmware addresses; its whole interface is three
 * functions and a work area.  And it carries a property that months of
 * reverse engineering bought and that rewriting could only lose: interpolating
 * the firmware's five-node table reproduces a real DNG's WarpRectilinear
 * opcode to nine decimal places.  Re-deriving that is not cheap and getting it
 * subtly wrong would be invisible -- a profile that loads, looks right, and
 * bends the picture slightly.
 *
 * So: the numbers are theirs, the glue is ours.
 *
 *   pg_dist_focal   the focal the correction data was measured at, which is
 *                   not always the one on the barrel
 *   pg_dist_kr      the table, interpolated for where the lens is focused
 *   pg_dist_fit     three collocation radii to four Brown coefficients
 *
 * kr0 is magnification rather than distortion -- the lens breathing, 1.2% on
 * the 40 mm between infinity and its near limit -- so it belongs on the focal
 * length and is folded there before the shape is fitted.
 * ========================================================================== */

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.equ DIST_WORK,      0x1100         /* past the lens name, inside the text
                                     * buffer: 160 bytes of scratch that only
                                     * exists while the profile is built */
.equ DIST_OK,        56             /* the flag distfit sets                  */
.equ DIST_COEFFS,    32             /* the four it fitted                     */
.equ DIST_SCRATCH,   64             /* 96 bytes it wants to work in           */

/* j9 -- r0 = 0..999999999, nine digits at the cursor, zero padded. */
j9: push    {r4, r5, r6, lr}
    mov     r4, r0
    movw    r0, #0x4240
    movt    r0, #0x000F                 @ 1000000
    mov     r1, r4
    bl      udiv32_swap                 @ r0 = r4 / 1e6, r1 = the rest
    mov     r5, r1
    mov     r1, r9
    bl      put_u32_3
    mov     r9, r0
    mov     r0, r5
    bl      udiv_1000
    mov     r5, r1
    mov     r1, r9
    bl      put_u32_3
    mov     r9, r0
    mov     r0, r5
    mov     r1, r9
    bl      put_u32_3
    mov     r9, r0
    pop     {r4, r5, r6, lr}
    bx      lr

/* udiv32_swap -- r1 / r0 -> r0, remainder r1.  udiv32 takes them the other way
 * round and j9 has the divisor to hand first. */
udiv32_swap:
    push    {r4, lr}
    mov     r2, r0
    mov     r0, r1
    mov     r1, r2
    bl      udiv32
    pop     {r4, lr}
    bx      lr

/* jd -- d0 emitted at the cursor, nine places after the point. */
jd: push    {r4, lr}
    vldr    d1, jd_zero
    vcmp.f64 d0, d1
    vmrs    APSR_nzcv, fpscr
    bpl     1f
    mov     r0, #'-'
    strb    r0, [r9], #1
    vneg.f64 d0, d0
1:  vcvt.u32.f64 s2, d0                 @ truncates: the whole part
    vmov    r4, s2
    vcvt.f64.u32 d1, s2
    vsub.f64 d2, d0, d1
    mov     r0, r4
    bl      ji
    mov     r0, #'.'
    strb    r0, [r9], #1
    vldr    d3, jd_1e9
    vmul.f64 d2, d2, d3
    vldr    d3, jd_half
    vadd.f64 d2, d2, d3
    vcvt.u32.f64 s4, d2
    vmov    r0, s4
    movw    r1, #:lower16:999999999     @ a carry would print a tenth digit;
    movt    r1, #:upper16:999999999     @ losing 1e-9 is cheaper than that
    cmp     r0, r1
    movhi   r0, r1
    bl      j9
    pop     {r4, lr}
    bx      lr

    .balign 8
jd_zero: .double 0.0
jd_half: .double 0.5
jd_1e9:  .double 1000000000.0
jd_two:  .double 2.0
jd_thou: .double 1000.0

/* j_dist_prepare -- r4 = the text buffer, r5 = width, r6 = height,
 * r8 = focal_px x 1000.  Returns with r8 corrected and the coefficients ready.
 *
 * The corner radius in focal lengths is what the fit is done against:
 * s = hypot(w, h) / 2 / focal_px.
 */
j_dist_prepare:
    push    {r0, r1, r2, r3, r4, lr}
    add     r4, r4, #DIST_WORK
    mov     r0, #0
    str     r0, [r4, #DIST_OK]
    mov     r0, r4
    bl      pg_dist_kr
    cmp     r0, #0
    beq     9f

    mul     r0, r5, r5
    mla     r0, r6, r6, r0
    vmov    s0, r0
    vcvt.f64.u32 d0, s0
    vsqrt.f64 d0, d0
    vldr    d1, jd_two
    vdiv.f64 d0, d0, d1
    vmov    s2, r8
    vcvt.f64.u32 d1, s2
    vldr    d2, jd_thou
    vdiv.f64 d1, d1, d2
    vdiv.f64 d7, d0, d1

    mov     r0, r4
    add     r1, r4, #DIST_COEFFS
    add     r2, r4, #DIST_SCRATCH
    bl      pg_dist_fit
    cmp     r0, #0
    beq     9f
    mov     r0, #1
    str     r0, [r4, #DIST_OK]

    /* kr0 is magnification, not distortion: it belongs on the focal length. */
    vldr    d0, [r4]
    vmov    s2, r8
    vcvt.f64.u32 d1, s2
    vmul.f64 d0, d0, d1
    vldr    d1, jd_half
    vadd.f64 d0, d0, d1
    vcvt.u32.f64 s0, d0
    vmov    r8, s0
9:  pop     {r0, r1, r2, r3, r4, pc}

/* j_dist_emit -- r4 = the text buffer.  The four numbers, comma separated.
 * Four and not fewer: Gyroflow falls back to its own telemetry path when the
 * list is short. */
j_dist_emit:
    push    {r4, r5, r6, lr}
    add     r4, r4, #DIST_WORK
    ldr     r0, [r4, #DIST_OK]
    cmp     r0, #0
    beq     8f
    add     r4, r4, #DIST_COEFFS
    mov     r5, #0
7:  add     r0, r4, r5, lsl #3
    vldr    d0, [r0]
    bl      jd
    S ", "
    add     r5, r5, #1
    cmp     r5, #3
    blt     7b
    S "0.0"
    pop     {r4, r5, r6, lr}
    bx      lr
8:
    S "0.0, 0.0, 0.0, 0.0"
    pop     {r4, r5, r6, lr}
    bx      lr

#include "distfit.inc.S"
