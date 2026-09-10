.syntax unified
.arm
.text

/*
 * Proven 3032x2012 canvas patch used by the live USB experiment.
 *
 * Hook: 0xC043A19C, reached after FUN_C0439D18 builds the 65-word
 * FieldAngle row and before downstream geometry is derived from it.
 *
 * ABI:
 *   r4 = FieldAngle object
 *   r4+0x5C = geometry row
 *   r5 = selector
 *
 * The displaced instruction is `mov r0,r4`.  The hook site uses BL and this
 * routine returns through LR after replaying that instruction.
 */

.equ LOG, 0xC072FA00
.equ ROW, 0x5C

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.macro PUT off, val
    movw    r3, #\val
    movw    r0, #\off
    str     r3, [r1, r0]
.endm

.global entry
entry:
    push    {r0, r1, r2, r3, ip, lr}
    add     r1, r4, #ROW
    LDA     ip, LOG

    /* Affect only the shipping FHD CinemaDNG row. */
    ldr     r3, [r1]
    movw    r0, #1936
    cmp     r3, r0
    bne     out
    ldr     r3, [r1, #4]
    movw    r0, #1090
    cmp     r3, r0
    bne     out

    /* Preserve the first pre-overwrite producer fields for diagnosis. */
    ldr     r0, [ip]
    cmp     r0, #0
    bne     patch
    str     r5, [ip, #4]
    movw    r0, #0x0D8
    ldr     r3, [r1, r0]
    str     r3, [ip, #8]
    movw    r0, #0x0E0
    ldr     r3, [r1, r0]
    str     r3, [ip, #12]

patch:
    PUT     0x000, 3032       /* base */
    PUT     0x004, 2012
    PUT     0x024, 3008       /* active; yields crop origin (12,6) */
    PUT     0x02C, 2000
    PUT     0x0D8, 3032       /* producer-side width/height pair */
    PUT     0x0E0, 2012
    PUT     0x0DC, 3032       /* size-getter override */
    PUT     0x0E4, 2012
    PUT     0x0F4, 3032       /* input */
    PUT     0x0F8, 2012

    ldr     r3, [ip]
    add     r3, r3, #1
    str     r3, [ip]

out:
    pop     {r0, r1, r2, r3, ip, lr}
    mov     r0, r4
    bx      lr
