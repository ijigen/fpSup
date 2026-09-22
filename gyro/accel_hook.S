.syntax unified
.arm

#include "imu_stream.inc.S"

/* The MMA8452Q driver writes its three remapped axes into 0xC377790C and then
 * publishes them:
 *
 *     0xC050D47C  strh  r2, [r4]        x
 *     0xC050D488  strh  r2, [r4, #2]    y
 *     0xC050D490  strh  r2, [r4, #4]    z
 *     0xC050D498  ldrsh r1, [r4]        every axis mode lands here
 *     0xC050D4A0  bl    0xC050C5D0        publish x, y, z
 *     0xC050D4C4  bl    0xC00102D0        <- the driver RELEASES ITS LOCK
 *     0xC050D4C8  mov   r2, #0            <- displaced; we run outside it
 *
 * The hook used to be at 0xC050D498, and that was inside the lock the driver
 * takes on its way in (FUN_c0010298 at the top, FUN_c00102D0 at the bottom).
 * Everything this hook does -- drain fifty records, claim, commit, send a job,
 * and let a priority 6 task preempt and possibly write to the card -- was
 * happening with that lock held, and anything else waiting on it waited for all
 * of it.  Audio's producer is a DSP completion callback and holds nothing.
 *
 * 0xC050D4C8 is the first instruction after the release on the SUCCESS path --
 * the failure path rejoins later -- so we fire exactly when there is a new
 * sample, r4 still points at the cache, and lr is already dead because the
 * function returns through its own pop.
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

.equ ACCEL_SITE,      0xC050D4C8
.equ ACCEL_SITE_ORIG, 0xE3A02000    /* mov r2, #0 -- the success return code */

    .global accel_hook
accel_hook:
    push    {r0, r1, r2, r3, ip, lr}

/* The ACC_MEASURE block stood here.  It counted how many gyro samples the
 * coprocessor's ring had gained between two visits of this hook, to answer one
 * question: could the drain live here instead of in the 20 ms callback, without
 * the ring lapping us?  It could, it does, and the measurement cannot be
 * compiled in any more -- the body is a section of the writer's blob and the
 * define does not reach it.  A diagnostic that cannot be switched on is not a
 * diagnostic, so it is gone rather than kept as something that looks available.
 */

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
/* Called directly.  These used to go through a word in the cave -- the hook
 * was in the cave, the body was somewhere the build could not name, and a
 * pointer was the only way across.  Both are sections of the same blob now, so
 * the assembler resolves the branch and there is nothing to fill in, nothing to
 * read, and nothing to guard against being zero. */
    bl      gyro_drain

    /* Ask for one, write it, say done.  No index, no mask, no slot arithmetic:
     * this hook does not know the ring is divided into anything. */
    mov     r0, #1
    bl      stream_claim                @ r0 = where, r1 = how many
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
    bl      stream_commit

3:  pop     {r0, r1, r2, r3, ip, lr}
    mov     r2, #0                      @ the displaced instruction
    bx      lr
