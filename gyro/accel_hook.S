.syntax unified
.arm

#include "imu_stream.inc.S"

/* The MMA8452Q driver writes its three remapped axes into 0xC377790C and then
 * publishes them:
 *
 *     0xC050D47C  strh  r2, [r4]        x
 *     0xC050D488  strh  r2, [r4, #2]    y
 *     0xC050D490  strh  r2, [r4, #4]    z
 *     0xC050D498  ldrsh r1, [r4]        <- displaced; every axis mode lands here
 *     0xC050D49C  mov   r0, r6
 *     0xC050D4A0  bl    0xC050C5D0
 *
 * At the hook the cache is complete and r4 already points at it, so the sample
 * costs three loads and no search.  lr is dead -- the instruction after next is
 * a bl -- so reaching this with a bl costs the driver nothing.
 *
 * Reading the cache at 50 Hz, which is what the gyro callback used to do, sees
 * about half of what the sensor produces and cannot tell a fresh value from the
 * previous one still sitting there.  From here every sample is seen exactly
 * once, at the moment it becomes true.
 *
 * The record is the stream's record: x, y, tag, z, four halfwords, the same
 * eight bytes a gyro sample occupies.  The tag is what says "do not advance the
 * timestamp"; see imu_stream.inc.S for why nothing here carries a time.
 *
 * The index is a fixed word rather than one of ours because the gyro producer
 * appends to the same stream from a different task, so the LDREX/STREX has to
 * be on an address both of them can name.
 */

.equ ACCEL_SITE,      0xC050D498
.equ ACCEL_SITE_ORIG, 0xE1D410F0    /* ldrsh r1, [r4] */

    .global accel_hook
accel_hook:
    push    {r0, r1, r2, r3, ip, lr}

#ifdef ACC_MEASURE
    /* ---- observation, not behaviour -------------------------------------
     *
     * The question this answers: could the drain live HERE instead of in the
     * 20 ms callback?  Doing it here would place this record exactly, because
     * the ring would be emptied in the same breath as the record is appended.
     * It is only safe if this hook fires often enough that the firmware's 600
     * record (240 ms) ring never laps us -- and a lap is invisible afterwards,
     * because head-minus-cursor reads the same as an ordinary wrap.
     *
     * So count the gap now, while the 20 ms hook is still doing the work and a
     * wrong answer costs nothing.  The gap is measured on the coprocessor's own
     * head, so it is the true number of samples an accel-only drain would have
     * had to move, not a rate multiplied by an assumed period.
     *
     * ACC_GHEAD has exactly one writer -- this hook -- so nothing here needs an
     * exclusive, and none of it touches a word another producer owns.  r4 is
     * the driver's cache pointer and is never written. */
    gyro_head r0, r1                    @ head as a byte offset into the ring
    movw    r2, #:lower16:ACC_STATE
    movt    r2, #:upper16:ACC_STATE
    ldr     r3, [r2, #ACC_O_GHEAD]
    cmp     r0, #0                      @ what gyro_head returns when the
    mvneq   r0, #0                      @ descriptor is not there -- and an
    str     r0, [r2, #ACC_O_GHEAD]      @ offset we can afford to skip.  Unarm
    beq     2f                          @ rather than measure across it: a false
                                        @ maximum on the one number that decides
                                        @ this would be worse than a lost sample
                                        @ of it.  mvn #0 is HEAD_UNARMED, and
                                        @ neither mvn nor str touches the flags.
    cmn     r3, #1                      @ HEAD_UNARMED: nothing to measure yet
    beq     2f
    subs    r1, r0, r3
    movwlo  ip, #GYRO_RING_SPAN         @ the head wrapped between visits
    addlo   r1, r1, ip
    lsr     r1, r1, #3                  @ bytes -> records
    ldr     ip, [r2, #ACC_O_MAX]
    cmp     r1, ip
    strhi   r1, [r2, #ACC_O_MAX]        @ the one number that decides it
    ldr     ip, [r2, #ACC_O_COUNT]
    add     ip, ip, #1
    str     ip, [r2, #ACC_O_COUNT]
    ldr     ip, [r2, #ACC_O_SUM]
    add     ip, ip, r1
    str     ip, [r2, #ACC_O_SUM]
    movw    r3, #ACC_DANGER
    cmp     r1, r3
    ldrhs   ip, [r2, #ACC_O_OVER]
    addhs   ip, ip, #1
    strhs   ip, [r2, #ACC_O_OVER]
2:
#endif

    /* Nothing is recording: append nothing.  Same reason as the gyro producer
     * -- see the note there.  Unlike it, this hook has no tail worth reaching,
     * so the gate goes straight to the exit. */
    movw    ip, #:lower16:T_WANT
    movt    ip, #:upper16:T_WANT
    ldr     ip, [ip]
    cmp     ip, #0
    beq     3f

    /* Drain the coprocessor's ring FIRST, then append this record.
     *
     * This is the whole point of the drain living here.  Once the drain has
     * run, every gyro sample that existed before this instant is already in the
     * stream -- so this record goes in behind them, and its position IS its
     * time, to 400 us.  There is no offset field, no post-processing, and the
     * decoder still reads straight through in order.
     *
     * It is also the last timer gone.  The drain used to hang off the firmware's
     * 20 ms gyro callback; it hangs off a real hardware event now, the one this
     * driver just produced.  Nothing in the path polls anything. */
    movw    ip, #:lower16:STREAM_DRAINFN
    movt    ip, #:upper16:STREAM_DRAINFN
    ldr     ip, [ip]
    cmp     ip, #0
    blxne   ip

    /* Ask for one, write it, say done.  No index, no mask, no slot arithmetic:
     * this hook does not know the ring is divided into anything. */
    mov     r0, #1
    movw    ip, #:lower16:STREAM_CLAIMFN
    movt    ip, #:upper16:STREAM_CLAIMFN
    ldr     ip, [ip]
    cmp     ip, #0
    beq     3f
    blx     ip                          @ r0 = where, r1 = how many
    cmp     r1, #0
    beq     3f
    mov     r1, r0

    ldrsh   r0, [r4]
    strh    r0, [r1]
    ldrsh   r0, [r4, #2]
    strh    r0, [r1, #2]
    ldrsh   r0, [r4, #4]
    strh    r0, [r1, #6]                @ z sits past the tag, as in the gyro ring
    mov     r0, #TAG_ACCEL
    strh    r0, [r1, #4]                @ last: the tag publishes the record

    mov     r0, #1
    movw    ip, #:lower16:STREAM_COMMITFN
    movt    ip, #:upper16:STREAM_COMMITFN
    ldr     ip, [ip]
    cmp     ip, #0
    blxne   ip

3:  pop     {r0, r1, r2, r3, ip, lr}
    ldrsh   r1, [r4]                    @ the displaced instruction
    bx      lr
