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

    movw    ip, #:lower16:STREAM_INDEX
    movt    ip, #:upper16:STREAM_INDEX
1:  ldrex   r0, [ip]
    add     r1, r0, #1
    strex   r2, r1, [ip]
    cmp     r2, #0
    bne     1b

    ring_slot r0, r1, r2          @ eight bytes a record

    ldrsh   r0, [r4]
    strh    r0, [r1]
    ldrsh   r0, [r4, #2]
    strh    r0, [r1, #2]
    ldrsh   r0, [r4, #4]
    strh    r0, [r1, #6]                @ z sits past the tag, as in the gyro ring
    mov     r0, #TAG_ACCEL
    strh    r0, [r1, #4]                @ last: the tag publishes the record

    pop     {r0, r1, r2, r3, ip, lr}
    ldrsh   r1, [r4]                    @ the displaced instruction
    bx      lr
