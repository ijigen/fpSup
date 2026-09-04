.syntax unified
.arm
.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm
.equ PARM, 0xC072F740
    .global _start
_start:                                 /* runs as the echo handler */
    push    {r4, r5, r6, r7, r8, r9, r10, r11, ip, lr}
    ldr_addr r4, PARM
    ldr     r5, [r4]                    /* frame width         */
    ldr     r6, [r4, #4]                /* frame height        */
    ldr     r8, [r4, #8]                /* focal_px x 1000     */
    ldr     r9, [r4, #12]               /* where the text goes */
    ldr     r10, [r4, #16]              /* the state base      */
    ldr     r7, [r4, #20]
    blx     r7                          /* pg_dist_prepare */
    ldr_addr r4, PARM
    str     r8, [r4, #24]               /* focal after the breathing term */
    ldr     r7, [r4, #28]
    blx     r7                          /* pg_dist_emit */
    ldr_addr r4, PARM
    str     r9, [r4, #32]               /* where the text ended */
    ldr_addr r0, 0xD09E0000
    str     r0, [r4, #36]
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, r9, r10, r11, ip, pc}
