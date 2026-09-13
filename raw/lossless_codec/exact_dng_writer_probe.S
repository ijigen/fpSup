.syntax unified
.arm
.text

/*
 * One-shot probe for the live FHD CinemaDNG writer call at 0xC0722AFC.
 *
 * The replaced instruction is:
 *
 *     0xC0722AFC  0xEBFDE061  bl 0xC069AC88
 *
 * The installer replaces it with a BL to probe_entry.  On the first hit this
 * routine records the incoming call, restores the original instruction, marks
 * the result DONE, and tail-calls the real function.  The tail-call uses an
 * absolute PC load, so r0-r3, r12, and lr reach the real function unchanged.
 *
 * A stale instruction-cache line could theoretically enter the probe again
 * after the restore.  Such entries only increment count and tail-call the real
 * function; the first-call record is never overwritten.
 *
 * State at 0xC072F700 (cleared by the installer before arming):
 *
 *   +0x00  total probe entries
 *   +0x04  first r0                 writer
 *   +0x08  first r1                 segment pointer
 *   +0x0C  first r2                 kind/offset
 *   +0x10  first lr                 expected 0xC0722B00
 *   +0x14  first [r1]               DNG buffer, if r1 != 0
 *   +0x18  first [r1 + 4]           DNG length, if r1 != 0
 *   +0x1C  completion magic         0x454E4F44, "DONE"
 *   +0x20  hook word after restore  expected 0xEBFDE061
 */

.equ HOOK_SITE,  0xC0722AFC
.equ HOOK_ORIG,  0xEBFDE061
.equ REAL_WRITE, 0xC069AC88
.equ STATE,      0xC072F700
.equ DONE_MAGIC, 0x454E4F44

.equ S_COUNT,     0x00
.equ S_R0,        0x04
.equ S_R1,        0x08
.equ S_R2,        0x0C
.equ S_LR,        0x10
.equ S_SEG_BUF,   0x14
.equ S_SEG_LEN,   0x18
.equ S_DONE,      0x1C
.equ S_RESTORED,  0x20

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global probe_entry
probe_entry:
    /* Six registers are 24 bytes, preserving AAPCS eight-byte alignment. */
    push    {r0, r1, r2, r3, r12, lr}

    LDA     r3, STATE
    ldr     r12, [r3, #S_COUNT]
    add     r12, r12, #1
    str     r12, [r3, #S_COUNT]
    cmp     r12, #1
    bne     tail_call

    /* Preserve the first call exactly; later entries cannot overwrite it. */
    str     r0, [r3, #S_R0]
    str     r1, [r3, #S_R1]
    str     r2, [r3, #S_R2]
    str     lr, [r3, #S_LR]

    /* Put the firmware instruction back before dereferencing the segment. */
    LDA     r12, HOOK_SITE
    LDA     r2, HOOK_ORIG
    str     r2, [r12]
    ldr     r2, [r12]
    str     r2, [r3, #S_RESTORED]

    cmp     r1, #0
    beq     record_done
    ldr     r2, [r1]
    str     r2, [r3, #S_SEG_BUF]
    ldr     r2, [r1, #4]
    str     r2, [r3, #S_SEG_LEN]

record_done:
    LDA     r2, DONE_MAGIC
    str     r2, [r3, #S_DONE]

tail_call:
    pop     {r0, r1, r2, r3, r12, lr}
    ldr     pc, real_write_address

.align 2
real_write_address:
    .word   REAL_WRITE
