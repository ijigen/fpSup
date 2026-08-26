.syntax unified
.arm
.text
/* ============================================================================
 * park — somewhere for a resident task to wait while its code is replaced.
 * ============================================================================
 *
 * A task started from the injection region runs from the injection region, and
 * nothing can stop it: `tkos task` offers chgpri and nothing else, and
 * tk_ext_tsk's stub is not linked into this firmware.  Unhooking the callback
 * stops new entries and does nothing about the loop already running, so the
 * code underneath cannot be rewritten -- which put a battery pull in front of
 * every iteration until this existed.
 *
 * Place this where the loader never writes and leave it there.  Your loop
 * checks the flag at the top and branches here; the loader waits for the
 * acknowledgement, rewrites the body, points the resume word at the new loop
 * and clears the flag.
 *
 *     your_loop:
 *         ldr     r0, [rSTATE, #PARK]
 *         cmp     r0, #0
 *         beq     1f
 *         movw    ip, #:lower16:PARK_ADDR
 *         movt    ip, #:upper16:PARK_ADDR
 *         bx      ip
 *     1:  ...
 *
 * The state address is not baked in.  It sits at park+12, reached by pc
 * arithmetic rather than a literal load so that this assembles with no
 * relocation at all, and the loader writes it there -- the same stub serves
 * whatever happens to be loaded beside it.
 *
 *      state+0x00  PARK      set by the host, cleared when the body is ready
 *      state+0x04  PARKED    set here, so the host knows it is safe to write
 *      state+0x08  RESUME    where to carry on
 *
 * Swap implementations, not protocols.  This is built for replacing the body
 * of a loop that keeps talking to the same state block in the same way; change
 * where the state lives, or which registers the resume point expects, and the
 * thread waiting in here has no way to know.  Reboot for those.
 *
 * On resume r10 holds the address of those three words and nothing else is
 * promised.  Point RESUME at a label that sets up its own registers -- resuming
 * straight into a loop that expects r10 to be something else costs whatever
 * that loop was in the middle of.
 * ========================================================================== */

.equ FN_SLEEP, 0xC03705D8      /* sleep(ms) */

.global park
park:
    sub     r10, pc, #8                 @ r10 = park
    ldr     r10, [r10, #12]             @ the state address, written by the loader
    b       waiting

.global park_state
park_state:
    .word   0

waiting:
    mov     r0, #1
    str     r0, [r10, #4]               @ PARKED
    mov     r0, #5
    movw    ip, #:lower16:FN_SLEEP
    movt    ip, #:upper16:FN_SLEEP
    blx     ip
    ldr     r0, [r10]                   @ PARK
    cmp     r0, #0
    bne     waiting

    /* Do not resume into zero.  The resume word is cleared along with the rest
     * of the state block, so a park requested before the loader has filled it
     * in would otherwise branch to address 0. */
    ldr     r0, [r10, #8]               @ RESUME
    cmp     r0, #0
    beq     waiting
    mov     r1, #0
    str     r1, [r10, #4]
    bx      r0
