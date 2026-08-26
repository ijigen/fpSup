.syntax unified
.arm
.text
/* ============================================================================
 * pushprobe — does StartTransfer get refused on the push endpoint too?
 * ============================================================================
 *
 * The shell's own StartTransfer, on EP 0x01 OUT, is refused by the controller
 * between twelve and twenty-seven per cent of the time: FUN_c01e6a48 returns -1
 * when DEPCMD answers with a non-zero status, which on this part means it had
 * no transfer resource to give.
 *
 * push_green.S does the same call on ctx4 and throws the answer away:
 *
 *      blx  FN_STARTX          @ result ignored
 *      mov  r0, #4
 *      movw r1, #50000
 *      blx  FN_WAIT            @ fifty seconds for a transfer that never began
 *
 * If ctx4 refuses at anything like the same rate, that is what "EP84 halts and
 * needs the cable pulled" has been: not a halt, a wait for something that was
 * never started. The fix would be one comparison.
 *
 * Measured without a host to collect the frames: each round starts a transfer,
 * waits briefly for the completion that will not come, and ends it again, so
 * every round begins from the same state. Nothing is pushed anywhere -- the
 * buffer is the raw DMA area and no data leaves.
 *
 * Borrowed slot: echo, handler pointer 0xC0BAC2F8. See shellcmd.S.
 *
 * Parameter block, 0xC072F700:
 *      +0x00  rounds to run     host fills
 *      +0x10  context           host fills: 3 is EP 0x83, 4 is EP 0x84
 *      +0x14  physical endpoint host fills: 7 for EP 0x83, 9 for EP 0x84
 *      +0x04  refused           written here
 *      +0x08  started           written here
 *      +0x0C  last non-zero return from StartTransfer
 * ========================================================================== */

.equ P,          0xC072F700
.equ TRB_TBL,    0xC31E3264     /* the per-context TRB pointers, ctx * 4      */
.equ TRB_ARMED,  0x813
/* Which endpoint to try is read from the parameter block: the old push code
 * was written for a gadget that had EP 0x84, and this one does not -- DALEPENA
 * is 0xA7, so physical 9 is not enabled and every StartTransfer on it is
 * refused instantly. EP 0x83 is enabled, and our own descriptor patches turned
 * it from interrupt into bulk with 1024-byte packets and burst 3, which is a
 * push channel nobody has used. */
.equ BUF,        0x50000000     /* the raw DMA area; nothing reads it here    */
.equ SIZE,       1024

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
    ldr     r7, [r4]                    @ rounds
    mov     r0, #0
    str     r0, [r4, #4]
    str     r0, [r4, #8]
    str     r0, [r4, #0xC]

round:
    cmp     r7, #0
    beq     done

    LDA     r0, TRB_TBL
    ldr     r1, [r4, #0x10]
    ldr     r5, [r0, r1, lsl #2]
    LDA     r0, BUF
    str     r0, [r5]
    mov     r0, #0
    str     r0, [r5, #4]
    movw    r0, #SIZE
    str     r0, [r5, #8]
    movw    r0, #TRB_ARMED
    str     r0, [r5, #0xC]
    dsb

    ldr     r0, [r4, #0x14]
    LDA     r12, FN_STARTX
    blx     r12
    cmp     r0, #0
    beq     started
    ldr     r1, [r4, #4]                @ refused
    add     r1, r1, #1
    str     r1, [r4, #4]
    str     r0, [r4, #0xC]
    b       cleanup

started:
    ldr     r1, [r4, #8]
    add     r1, r1, #1
    str     r1, [r4, #8]
    ldr     r0, [r4, #0x10]             @ briefly, since nobody is collecting
    mov     r1, #20
    LDA     r12, FN_WAIT
    blx     r12

cleanup:
    ldr     r0, [r4, #0x10]             @ leave the endpoint as it was found
    LDA     r12, FN_ENDX
    blx     r12

    sub     r7, r7, #1
    b       round

done:
    ldr     ip, [r8]
    LDA     r0, FMT_S
    adr     r1, msg
    blx     ip
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

msg:
    .asciz  "pushprobe: counts at 0xC072F704"
    .align  2
