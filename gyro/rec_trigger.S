.syntax unified
.arm

#include "imu_stream.inc.S"

/* Start where the movie recorder starts, stop where it stops.
 *
 * Both sites were read out of the firmware rather than guessed at.  The movie
 * path does NOT go through XC_AudioRecorder::Start (FUN_c01fb338) -- that one
 * has two callers, a debug command with a "/test_wav" string and one path that
 * starts and stops immediately.  The movie path is:
 *
 * Which of the two is the start was settled on the camera, not from the call
 * sites -- reading those the other way round is the obvious mistake, and it is
 * the one I made.  Two takes: an eleven second take put 11.38 s between them,
 * a three second take 4.40 s, and c01fba28 fired first both times.  So:
 *
 *   START  movRec  ->  FUN_c01fb918(recorder), past the "am I recording"
 *          check, immediately before the call that tears the running monitor
 *          audio down:
 *
 *              c01fba28  ldr r0, [r4, #8]    <- displaced
 *              c01fba2c  ldr r1, [r0, #0xc]
 *              c01fba30  add r1, r1, #0x20
 *              c01fba34  ldr r1, [r1]
 *              c01fba38  blx r1              vtable +0x20
 *
 *   STOP   MovRecFuncStateREC__v36 case 1  ->  FUN_c01fb640(recorder, 0),
 *          which takes the class 6 heap -- MOVAUDIO -- checks it has room, and
 *          past every early return commits at
 *
 *              c01fb880  mov r0, r4          <- displaced
 *              c01fb884  mov r1, #1
 *              c01fb888  bl  FUN_c01fbad0    (mark the recorder running)
 *                        ... vtable +0x1c, the capture starts again
 *
 *          Case 1 is the state being LEFT, not entered.
 *
 * Neither site is a function entry, and that is deliberate: both functions save
 * lr in their first instruction, and both have early returns in front of the
 * commit.  At these two addresses lr has already been clobbered by earlier
 * calls and the function returns through its own pop, so a bl costs nothing --
 * and anything that reaches here is a take that really begins or really ends.
 *
 * What each one records: the gyro count at that instant.  Beside the frame
 * hook's latch, the gap between them is how far our start point sits from the
 * take's first exposure, in gyro samples of 400 us.  The 470-570 ms figure has
 * only ever been inferred from where Gyroflow's auto-sync landed; this makes it
 * a measurement.
 */

#ifdef REC_STOP
.equ SITE,        0xC01FB880
.equ SITE_ORIG,   0xE1A00004          /* mov r0, r4 */
.equ TAG_THIS,    TAG_STOP
.equ COUNT_WORD,  STREAM_R1_N
.equ LATCH_WORD,  STREAM_R1_GC
#else
.equ SITE,        0xC01FBA28
.equ SITE_ORIG,   0xE5940008          /* ldr r0, [r4, #8] */
.equ TAG_THIS,    TAG_START
.equ COUNT_WORD,  STREAM_R0_N
.equ LATCH_WORD,  STREAM_R0_GC
#endif

    .global rec_trigger
rec_trigger:
    push    {r0, r1, r2, r3, ip, lr}

    movw    ip, #:lower16:COUNT_WORD
    movt    ip, #:upper16:COUNT_WORD
    ldr     r2, [ip]
    add     r3, r2, #1
    str     r3, [ip]                    @ only this hook writes it

    /* The first one since arming latches the gyro count beside it.  Later ones
     * do not overwrite it: a take is bounded by the first start and the first
     * stop, and a second take should not quietly redefine the first. */
    cmp     r2, #0
    bne     2f
    movw    r0, #:lower16:STREAM_GCOUNT
    movt    r0, #:upper16:STREAM_GCOUNT
    ldr     r0, [r0]
    movw    r1, #:lower16:LATCH_WORD
    movt    r1, #:upper16:LATCH_WORD
    str     r0, [r1]
2:
    movw    ip, #:lower16:STREAM_INDEX
    movt    ip, #:upper16:STREAM_INDEX
1:  ldrex   r0, [ip]
    add     r1, r0, #1
    strex   r3, r1, [ip]
    cmp     r3, #0
    bne     1b

    and     r0, r0, #STREAM_MASK
    movw    r1, #:lower16:STREAM_BASE
    movt    r1, #:upper16:STREAM_BASE
    add     r1, r1, r0, lsl #3

    strh    r2, [r1]                    @ x = which one this is
    mov     r0, #0
    strh    r0, [r1, #2]
    strh    r0, [r1, #6]
    mov     r0, #TAG_THIS
    strh    r0, [r1, #4]                @ last: the tag publishes the record

    pop     {r0, r1, r2, r3, ip, lr}
#ifdef REC_STOP
    mov     r0, r4                      @ the displaced instruction
#else
    ldr     r0, [r4, #8]                @ the displaced instruction
#endif
    bx      lr
