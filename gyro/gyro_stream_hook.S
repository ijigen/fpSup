.syntax unified
.arm

#include "imu_stream.inc.S"

/* The other producer.  It drains the firmware's gyro ring into the same stream,
 * in the same eight-byte record, with tag 0.
 *
 * The firmware's own record already has this shape --
 *
 *     0  i16 x   2  i16 y   4  i16 pad   6  i16 z
 *
 * -- with the pad always zero, which is what made a tag in that halfword free.
 * The copy writes tag 0 into it rather than trusting that, and counts any source
 * pad that was not zero in STREAM_PADBAD, so the assumption the whole format
 * rests on is a number that can be read back instead of a belief.
 *
 * Hook site 0xC00D0794, the same callback the logger uses, about every 20 ms.
 * The displaced instruction is `blx 0xC01EC6F8` (encoded 0xFA046FD7) and the
 * caller keeps its result in r11, so it is performed first -- at the point in
 * the callback the firmware performs it -- and its r0 is written over the saved
 * r0 on the stack, so the pop hands it back untouched.  Doing it last would
 * have been shorter and would have moved a firmware call across our copy for
 * no reason; the logger does it first and this is not the place to differ.
 *
 * A batch is about fifty samples, so a 256-record stream is a hundred
 * milliseconds and wraps quickly.  That is enough to read the interleave back
 * and see roughly one accelerometer record per fifty; the real buffer replaces
 * it at assembly.
 */

.equ GYRO_DESC_PTR,  0xC31E3FCC
.equ GYRO_DESC_RING, 0x60           /* -> the ring object                       */
.equ GYRO_DATA_OFF,  4              /* records start at base+4, head is base+off */
.equ GYRO_SPAN,      0x12C0         /* 600 records of eight bytes                */

.equ HOOK_RESUME_LO, 0xC6F9         /* 0xC01EC6F9: thumb, so bx not blx          */
.equ HOOK_RESUME_HI, 0xC01E

    .global gyro_stream_hook
gyro_stream_hook:
    push    {r0-r9, ip, lr}         @ twelve: the LDRD in the callee wants 8-byte

    movw    ip, #HOOK_RESUME_LO     @ the displaced instruction, in its own place
    movt    ip, #HOOK_RESUME_HI
    blx     ip
    str     r0, [sp]                @ the caller's r11; the pop returns it

    movw    r0, #:lower16:GYRO_DESC_PTR
    movt    r0, #:upper16:GYRO_DESC_PTR
    ldr     r0, [r0]
    cmp     r0, #0
    beq     9f
    ldr     r8, [r0, #GYRO_DESC_RING]
    cmp     r8, #0
    beq     9f
    ldr     r5, [r8]                @ where the firmware is writing now

    movw    r9, #:lower16:STREAM_GHEAD
    movt    r9, #:upper16:STREAM_GHEAD
    ldr     r6, [r9]                @ where we left off
    cmn     r6, #1                  @ HEAD_UNARMED: first visit, take the head
    streq   r5, [r9]                @ and let the pre-record history go
    beq     9f

    cmp     r5, r6
    beq     9f                      @ nothing new
    str     r5, [r9]                @ consumed, whatever the copy manages
    bhi     1f
    movw    r3, #GYRO_SPAN          @ wrapped: to the end and round again
    add     r3, r3, r5
    sub     r3, r3, r6
    b       2f
1:  sub     r3, r5, r6
2:  lsrs    r4, r3, #3              @ records
    beq     9f

    /* Claim the whole batch in one step.  The accelerometer hook fires from a
     * different task and claims one; either order is fine, each record owns its
     * slot, and the batch stays contiguous. */
    movw    r7, #:lower16:STREAM_INDEX
    movt    r7, #:upper16:STREAM_INDEX
3:  ldrex   r0, [r7]
    add     r1, r0, r4
    strex   r2, r1, [r7]
    cmp     r2, #0
    bne     3b

    /* Gyro records only, so this is a ruler for the sensor's own rate.  The
     * shared index counts both sensors and cannot be one.  Only this task
     * writes it, so it needs no exclusive.
     *
     * It is here to settle a real disagreement in the notes: one place records
     * the gyro at 2500 Hz within 0.02%, another at a hardware-measured 2501.85
     * Hz, which is 0.074% -- and neither says how it was measured.  On a three
     * minute take that is the difference between one frame of drift and four,
     * and it drifts progressively, so it is a candidate for the sync being
     * right at the head of a clip and wrong at the end.  A count against a long
     * baseline settles it. */
    movw    r2, #:lower16:STREAM_GCOUNT
    movt    r2, #:upper16:STREAM_GCOUNT
    ldr     r1, [r2]
    add     r1, r1, r4
    str     r1, [r2]

    add     r6, r6, #GYRO_DATA_OFF  @ source cursor
    add     r5, r8, #GYRO_DATA_OFF  @ first record of the firmware ring
    movw    r9, #GYRO_SPAN
    add     r9, r5, r9              @ one past its last
    movw    r7, #:lower16:STREAM_BASE
    movt    r7, #:upper16:STREAM_BASE

4:  cmp     r6, r9
    movhs   r6, r5                  @ round the firmware ring

    and     r2, r0, #STREAM_MASK
    add     r2, r7, r2, lsl #3

    ldrsh   r3, [r6]
    strh    r3, [r2]
    ldrsh   r3, [r6, #2]
    strh    r3, [r2, #2]
    ldrsh   r3, [r6, #6]
    strh    r3, [r2, #6]
    mov     r3, #TAG_GYRO
    strh    r3, [r2, #4]            @ last: the tag publishes the record

    ldrsh   r3, [r6, #4]            @ the pad this format spends
    cmp     r3, #0
    bne     5f

6:  add     r6, r6, #8
    add     r0, r0, #1
    subs    r4, r4, #1
    bne     4b

9:  pop     {r0-r9, ip, lr}
    bx      lr

/* Out of line: it never runs unless the pad assumption is wrong, and only this
 * task writes the counter, so it needs no exclusive. */
5:  movw    r3, #:lower16:STREAM_PADBAD
    movt    r3, #:upper16:STREAM_PADBAD
    ldr     ip, [r3]
    add     ip, ip, #1
    str     ip, [r3]
    b       6b
