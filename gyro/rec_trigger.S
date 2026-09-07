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
 *   START  FUN_c0378a50, the recorder's start step, the instruction right
 *          after it has built the audio recorder -- file, mailbox, thread,
 *          and woken it:
 *
 *              c0379080  bl   F_MGR
 *              c0379090  bl   F_VOL
 *              c03790b4  bl   XC_AudioRecorder::Start   <- AudF_W is built here
 *              c03790b8  ldrb r2, [r11, #0x5ce]        <- displaced
 *
 *          The hook used to sit at 0xC01FBA28, inside FUN_c01fb918 -- movRec
 *          tearing the monitor audio down, several steps EARLIER in the start
 *          sequence.  Building a priority 6 thread there froze the camera on
 *          the spot; opening a file there did not.  Audio builds its thread
 *          here, so we build ours here, right behind it.  (This branch is the
 *          one taken when an audio file is recorded, which CinemaDNG does.)
 *
 *   STOP   cDevt_stop @0xC038C3C0, at the point where the two paths rejoin --
 *          which is AFTER audio has torn its own writer down:
 *
 *              c038c45c  ldrb r3, [r0, #0xe0]
 *              c038c464  beq  ---------------+   no audio file
 *              c038c46c  bl   XC_AudioRecorder::Stop   join, del mbx,
 *              c038c470  b    --------------+|   destroy thread, close
 *              c038c478  bl   FUN_c01fb2f8  ||
 *              c038c47c  bl   FUN_c01fb918  ||   restart the monitor
 *              c038c480  bl   FUN_c0399150 <++   both paths arrive here
 *              c038c484  cmp  r0, #0        <- displaced
 *
 *          The hook sat at 0xC038C45C, which is BEFORE that call: our whole
 *          teardown -- join, delete the mailbox, destroy the thread, take the
 *          card lock and close -- ran ahead of audio's, in the one task
 *          SRecFile is waiting on.  Teardowns that only sent a message and
 *          waited on a flag were fine there; every one that went further froze
 *          the camera, whatever order the further steps were in.
 *
 *          Here, audio has already collected its writer and closed its file,
 *          and we do the same thing to ours behind it.
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
.equ SITE,        0xC038C484
.equ SITE_ORIG,   0xE3500000          /* cmp r0, #0 */
.equ COUNT_WORD,  STREAM_R1_N
.equ LATCH_WORD,  STREAM_R1_GC
#else
.equ SITE,        0xC03790B8
.equ SITE_ORIG,   0xE5DB25CE          /* ldrb r2, [r11, #0x5ce] */
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
    cmp     r0, #0                      @ the displaced instruction.  It only
                                        @ sets the flags for the beq that
                                        @ follows, and r0 -- FUN_c0399150's
                                        @ result -- is restored by the pop, so
                                        @ the flags this leaves are the right
                                        @ ones even though the hook clobbered
                                        @ them in between.
#else
    ldrb    r2, [r11, #0x5ce]           @ the displaced instruction; r11 is the
                                        @ recorder's state and is never touched
#endif
    bx      lr
