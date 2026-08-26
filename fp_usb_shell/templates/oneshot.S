.syntax unified
.arm
.text
/* ============================================================================
 * One-shot — run a piece of code on the camera, once, from the host.
 * ============================================================================
 *
 * The shell can write memory (`mem set`) but nothing can call it.  The way to
 * get code executed is to point an address the firmware already calls at our
 * own routine, let it fire once, and put the original word back.  That is all
 * this file is: the plumbing around a payload, so the payload is the only part
 * that ever needs writing.
 *
 * The borrowed call site is the gyro callback at 0xC00D0794, which fires at
 * 50-90 Hz.  It normally holds `BLX 0xC01EC6F8`; we call that ourselves first
 * and return its value, so the firmware sees no difference.
 *
 * Context: whatever thread the callback runs on — treat it as interrupt-ish.
 * Do not block, do not take a mutex, do not call anything that might.  Anything
 * that needs task context has to be started from here as a task instead.
 *
 * Layout (see README):
 *     0xC072F700  parameters and results, 256 bytes, yours
 *     0xC072F800  this code
 *
 * Use:
 *     ./inject.py oneshot.S            assemble, write, arm, wait for it to fire
 *     ./fpsh mem get 0xC072F700,,0x20  read whatever the payload left
 * ========================================================================== */

.equ HOOK_SITE,   0xC00D0794
.equ HOOK_ORIG,   0xFA046FD7      /* the BLX this site normally holds          */
.equ HOOK_TARGET, 0xC01EC6F9      /* what that BLX calls (thumb)               */
.equ SCRATCH,     0xC072F700      /* +00 'DONE' when finished, +04 result      */

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
    push    {r4, r5, r6, lr}
    LDA     r12, HOOK_TARGET
    blx     r12
    mov     r4, r0                  @ keep the callback's own return value

    LDA     r5, SCRATCH
    ldr     r0, [r5]
    LDA     r1, 0x454E4F44          @ 'DONE'
    cmp     r0, r1
    beq     leave                   @ already ran; the restore below lost a race

    LDA     r0, HOOK_SITE
    LDA     r1, HOOK_ORIG
    str     r1, [r0]                @ put the site back before running anything

    bl      payload
    str     r0, [r5, #4]            @ result
    LDA     r0, 0x454E4F44
    str     r0, [r5]                @ 'DONE' — the host polls this word
leave:
    mov     r0, r4
    pop     {r4, r5, r6, pc}

/* ==========================================================================
 * payload — replace this.  r0-r3 and r12 are free; return a word in r0.
 * Read arguments from SCRATCH+8 upwards, write extra results there too.
 *
 * The version below just proves the mechanism: it returns the tick count so a
 * non-zero, changing result means the code really ran.
 * ========================================================================== */
payload:
    push    {lr}
    LDA     r0, 0xC0BAC478          @ any readable word; replace with real work
    ldr     r0, [r0]
    pop     {pc}
