.syntax unified
.arm
.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm
.equ PARM, 0xC072F740
    .global _start
_start:                                 /* runs as the echo handler */
    push    {r4, r5, r6, r7, r8, lr}
    ldr_addr r4, PARM
    ldr     r5, [r4, #16]               /* &kr, four doubles  */
    ldr     r6, [r4, #20]               /* &fit, three doubles */
    mov     r0, r5
    bl      pg_dist_kr
    str     r0, [r4, #24]               /* did the lens have data? */
    cmp     r0, #0
    beq     1f
    vldr    d7, [r4, #32]               /* s, handed in as a double */
    mov     r0, r5
    mov     r1, r6
    add     r2, r6, #24                 /* the working matrix, so the host can see it */
    bl      pg_dist_fit
    str     r0, [r4, #28]               /* did the solve succeed? */
    ldr     r0, [r4, #44]               /* the focal the mount reports */
    bl      pg_dist_focal
    str     r0, [r4, #48]               /* the one the optics measured */
1:  ldr_addr r0, 0xD09E0000
    str     r0, [r4, #40]
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

#include "distfit.inc.S"
