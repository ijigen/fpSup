.syntax unified
.arm
.text
/* ============================================================================
 * callfn — call one function on the camera, from the host, and see what it did.
 * ============================================================================
 *
 * Bringing up resident code one routine at a time.  A logger that hooks a
 * 2500 Hz callback gets exactly one chance to be right; calling its pieces
 * individually first, from a shell command, costs nothing when they are wrong.
 *
 * Borrowed slot: echo, handler pointer 0xC0BAC2F8.  See shellcmd.S.  Task
 * context, so the callee may block -- which is the point, since the routines
 * worth testing this way are the ones that open files.
 *
 * r10 is set as well as r0-r3 because code written to live inside a hook tends
 * to keep its state block in a callee-saved register rather than pass it.
 *
 * Parameter block, 0xC072F500:
 *      +0x00  function to call        host fills
 *      +0x04  r0                      +0x08  r1
 *      +0x0C  r2                      +0x10  r3
 *      +0x14  r10                     +0x20  r4        +0x24  r5
 *      +0x18  return value           <- read this
 *      +0x1C  0xD09E0000 when it returned; unchanged if it never did
 *
 * r4 and r5 are here because routines lifted out of a hook pass their working
 * pointers in whatever register the surrounding code had them in, not in r0-r3.
 *
 * Nothing here checks the address.  A wrong one is a jump into whatever is
 * there, which is a freeze and a battery pull.
 * ========================================================================== */

.equ P,        0xC072F500
.equ P_FN,     0x00
.equ P_R0,     0x04
.equ P_R1,     0x08
.equ P_R2,     0x0C
.equ P_R3,     0x10
.equ P_R10,    0x14
.equ P_RET,    0x18
.equ P_DONE,   0x1C
.equ P_R4,     0x20
.equ P_R5,     0x24

.equ FMT_S,    0xC0BABB38

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    /* An even number of registers, deliberately.  AAPCS wants the stack eight
     * byte aligned at a call, and pushing an odd count leaves it four -- which
     * costs nothing until the callee reaches an LDRD, and then it is a data
     * abort with the shell task holding the dispatcher. */
    push    {r3, r4, r5, r6, r7, r8, r9, r10, r11, lr}
    mov     r8, r0                  @ shell context

    LDA     r4, P
    mov     r0, #0
    str     r0, [r4, #P_DONE]

    ldr     r9, [r4, #P_FN]
    ldr     r0, [r4, #P_R0]
    ldr     r1, [r4, #P_R1]
    ldr     r2, [r4, #P_R2]
    ldr     r3, [r4, #P_R3]
    ldr     r10, [r4, #P_R10]
    ldr     r6, [r4, #P_R4]
    ldr     r7, [r4, #P_R5]
    mov     r4, r6
    mov     r5, r7
    blx     r9

    LDA     r4, P
    str     r0, [r4, #P_RET]
    LDA     r0, 0xD09E0000
    str     r0, [r4, #P_DONE]

    ldr     ip, [r8]
    LDA     r0, FMT_S
    adr     r1, msg
    blx     ip

    mov     r0, #0
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}

msg:
    .asciz  "callfn: returned"
    .align  2
