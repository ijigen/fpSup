.syntax unified
.arm

#include "imu_stream.inc.S"

/* The third producer: one record per video frame exposure.
 *
 *     FrameExpos_s @ 0xC0315C10
 *         c10  E92D4BF0  push {r4-r9, r11, lr}
 *         c14  E24DDFC7  sub  sp, sp, #0x31C
 *         c18  E58D0080  str  r0, [sp, #0x80]     <- displaced
 *
 * Not the first instruction: it saves lr, and reaching it with a bl would put
 * our return address in the frame instead of the caller's.  By c18 the caller's
 * lr is already on the stack and dead -- the bl at c28 clobbers it anyway -- so
 * a bl here costs the function nothing, and the displaced instruction is
 * sp-relative, which is safe because our push and pop balance before it runs.
 *
 * A marker rather than a record-start hook, and not because the start point is
 * assumed wrong.  Audio stays in sync with video without an accurate start time
 * at all: both begin at the same event, so a common offset is invisible inside
 * the clip.  Which side our 470-570 ms anchor error sits on has never been
 * established, and guessing it again is how this investigation has gone wrong
 * before.  The marker replaces the guess with three readings from one take:
 *
 *     which gyro sample frame zero lands on   (the anchor, measured)
 *     where our flag-poll start sits relative to it   (which side is late)
 *     how many gyro samples per frame   (the rate against the camera's own
 *                                        clock, which is the only one that
 *                                        matters -- not the host's)
 *
 * x carries a running count of markers, so a reader can tell "the ring wrapped
 * and I lost some" from "the camera skipped a frame".
 */

.equ FRAME_SITE,      0xC0315C18
.equ FRAME_SITE_ORIG, 0xE58D0080    /* str r0, [sp, #0x80] */

    .global frame_hook
frame_hook:
    push    {r0, r1, r2, r3, ip, lr}

    movw    ip, #:lower16:STREAM_INDEX
    movt    ip, #:upper16:STREAM_INDEX
1:  ldrex   r0, [ip]
    add     r1, r0, #1
    strex   r2, r1, [ip]
    cmp     r2, #0
    bne     1b

    and     r0, r0, #STREAM_MASK
    movw    r1, #:lower16:STREAM_BASE
    movt    r1, #:upper16:STREAM_BASE
    add     r1, r1, r0, lsl #3          @ eight bytes a record

    movw    ip, #:lower16:STREAM_FCOUNT
    movt    ip, #:upper16:STREAM_FCOUNT
    ldr     r0, [ip]
    add     r2, r0, #1
    str     r2, [ip]                    @ only this hook writes it

    /* The first marker since arming latches the gyro count beside it.  The ring
     * is a hundred milliseconds deep, so by the end of a take the take's first
     * frame has been overwritten many times over; this is the one thing about
     * it that cannot be reconstructed afterwards. */
    cmp     r0, #0
    bne     2f
    movw    r2, #:lower16:STREAM_GCOUNT
    movt    r2, #:upper16:STREAM_GCOUNT
    ldr     r2, [r2]
    movw    r3, #:lower16:STREAM_F0_GC
    movt    r3, #:upper16:STREAM_F0_GC
    str     r2, [r3]
2:
    strh    r0, [r1]                    @ x = which marker this is
    mov     r0, #0
    strh    r0, [r1, #2]
    strh    r0, [r1, #6]
    mov     r0, #TAG_FRAME
    strh    r0, [r1, #4]                @ last: the tag publishes the record

    pop     {r0, r1, r2, r3, ip, lr}
    str     r0, [sp, #0x80]             @ the displaced instruction
    bx      lr
