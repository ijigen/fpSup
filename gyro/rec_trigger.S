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
.equ COUNT_WORD,  STREAM_R1_N
.equ LATCH_WORD,  STREAM_R1_GC
#else
.equ SITE,        0xC01FBA28
.equ SITE_ORIG,   0xE5940008          /* ldr r0, [r4, #8] */
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

#ifdef REC_STOP
    /* Drain BEFORE the gate closes.
     *
     * The producers stop the moment T_WANT goes to zero, so whatever the
     * coprocessor wrote since the last accelerometer sample would simply be
     * left in its ring -- up to one accelerometer interval off the end of every
     * take.  Audio does not lose that: its capture is torn down, and the
     * teardown hands over what is in flight.  This is the same idea, and it is
     * also what makes the stop job honestly last: it goes into the queue behind
     * ALL of the take's data, not just the part that had already been moved. */
    movw    ip, #:lower16:STREAM_DRAINFN
    movt    ip, #:upper16:STREAM_DRAINFN
    ldr     ip, [ip]
    cmp     ip, #0
    blxne   ip

    movw    r0, #:lower16:T_WANT
    movt    r0, #:upper16:T_WANT
    mov     r1, #0
    str     r1, [r0]
#else
    movw    r0, #:lower16:T_WANT
    movt    r0, #:upper16:T_WANT
    mov     r1, #1
    str     r1, [r0]

    /* Where the coprocessor's ring is, to 400 us. */
    gyro_head r0, r1
    movw    r1, #:lower16:STREAM_R0_HEAD
    movt    r1, #:upper16:STREAM_R0_HEAD
    str     r0, [r1]

    /* Anchor the gyro cursor to THIS instant.  The producers do not drain
     * while the camera is idle, so the cursor is stale by however long it has
     * been sitting -- and a stale cursor is a WRAPPED one, indistinguishable
     * from an ordinary wrap.  Latching the write pointer here is what makes the
     * take's first record the sample that existed when the recorder committed.
     *
     * GHEAD holds the ABSOLUTE pointer, not the offset gyro_head returns. */
    movw    r0, #:lower16:GYRO_DESC_PTR
    movt    r0, #:upper16:GYRO_DESC_PTR
    ldr     r0, [r0]
    cmp     r0, #0
    beq     3f
    ldr     r0, [r0, #0x60]
    cmp     r0, #0
    beq     3f
    ldr     r0, [r0]
    movw    r1, #:lower16:STREAM_GHEAD
    movt    r1, #:upper16:STREAM_GHEAD
    str     r0, [r1]
3:
#endif

    /* Build the take, or tear it down.  XC_AudioRecorder::Start and ::Stop do
     * this, in the recorder's own task; both hooks run in that task. */
#ifdef REC_STOP
    movw    ip, #:lower16:T_CLOSEFN
    movt    ip, #:upper16:T_CLOSEFN
#else
    movw    ip, #:lower16:T_OPENFN
    movt    ip, #:upper16:T_OPENFN
#endif
    ldr     ip, [ip]
    cmp     ip, #0
    blxne   ip

    pop     {r0, r1, r2, r3, ip, lr}
#ifdef REC_STOP
    mov     r0, r4                      @ the displaced instruction
#else
    ldr     r0, [r4, #8]                @ the displaced instruction
#endif
    bx      lr
