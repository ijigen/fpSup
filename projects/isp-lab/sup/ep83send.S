.syntax unified
.arm
.text
/* ============================================================================
 * ep83send -- push engine milestone 1: one buffer out of EP 0x83, once.
 * ============================================================================
 *
 * pushprobe.S showed StartTransfer on ctx 3 / physical 7 is accepted 100/100;
 * no payload has ever reached the host.  This sends `len` bytes at `addr`
 * (DMA-visible, uncached alias) in one TRB and reports what happened, so the
 * host (fpshd `EP83 <len> echo`) can compare the bytes it read with the ones
 * it wrote there.
 *
 * Borrowed slot: echo (handler 0xC0BAC2F8), as pushprobe/callfn.  Its own
 * cave blocks: code 'ispl.ep83.code', parameters 'ispl.ep83.parm' (IMX410_RULES
 * §71 -- no code or parameter block shared with another echo tool).
 *
 * Parameter block (host fills +0x00..+0x10, reads the rest):
 *      +0x00  addr        source, DMA address = uncached CPU address - 0x40000000
 *      +0x04  len         bytes, 1 .. 16 MiB - 1 KiB
 *      +0x08  ctx         3 = EP 0x83
 *      +0x0C  phys        7 = EP 0x83
 *      +0x10  wait_ms     how long FN_WAIT may block
 *      +0x14  start_rc    FUN_c01e6b80's answer (0 = started)
 *      +0x18  wait_rc     FUN_c01e4e80's answer
 *      +0x1C  trb_ctrl    TRB word 3 after the wait (bit 0 HWO: 1 = not done)
 *      +0x20  trb_size    TRB word 2 after the wait (low 24 bits: bytes left)
 *      +0x24  ended       1 = the transfer was still owned and EndTransfer ran
 *      +0x28  done        0xD09E0083 when this routine got to the end
 * ========================================================================== */

#ifndef P
.equ P,          0xC072F700     /* the host passes its claim; only for a bare assemble */
#endif
.equ TRB_TBL,    0xC31E3264     /* per-context TRB pointers, ctx * 4 (pushprobe) */
.equ TRB_ARMED,  0x813          /* HWO | LST | IOC | type normal (push_green)  */
.equ DONE,       0xD09E0083

.equ FN_STARTX,  0xC01E6B81
.equ FN_WAIT,    0xC01E4E81
.equ FN_ENDX,    0xC01E6D49
.equ FMT_S,      0xC0BABB38

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r8, r0                      @ shell context
    LDA     r4, P
    mov     r0, #0
    str     r0, [r4, #0x14]
    str     r0, [r4, #0x18]
    str     r0, [r4, #0x1C]
    str     r0, [r4, #0x20]
    str     r0, [r4, #0x24]
    str     r0, [r4, #0x28]

    LDA     r0, TRB_TBL
    ldr     r1, [r4, #0x08]             @ ctx
    ldr     r5, [r0, r1, lsl #2]        @ this context's TRB
    ldr     r0, [r4, #0x00]
    str     r0, [r5]                    @ buffer, low
    mov     r0, #0
    str     r0, [r5, #4]                @ buffer, high
    ldr     r0, [r4, #0x04]
    str     r0, [r5, #8]                @ size
    movw    r0, #TRB_ARMED
    str     r0, [r5, #0xC]
    dsb

    ldr     r0, [r4, #0x0C]             @ phys
    LDA     r12, FN_STARTX
    blx     r12
    str     r0, [r4, #0x14]
    cmp     r0, #0
    bne     finish                      @ refused: nothing to wait for or end

    ldr     r0, [r4, #0x08]
    ldr     r1, [r4, #0x10]
    LDA     r12, FN_WAIT
    blx     r12
    str     r0, [r4, #0x18]

    ldr     r0, [r5, #0xC]
    str     r0, [r4, #0x1C]
    ldr     r0, [r5, #8]
    str     r0, [r4, #0x20]
    ldr     r0, [r5, #0xC]
    tst     r0, #1                      @ still owned by the controller?
    beq     finish
    mov     r0, #1
    str     r0, [r4, #0x24]
    ldr     r0, [r4, #0x08]
    LDA     r12, FN_ENDX
    blx     r12

finish:
    LDA     r0, DONE
    str     r0, [r4, #0x28]
    ldr     ip, [r8]
    LDA     r0, FMT_S
    adr     r1, msg
    blx     ip
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

msg:
    .asciz  "ep83send done"
    .align  2
