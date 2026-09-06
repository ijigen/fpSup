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

.equ GYRO_SITE,      0xC00D0794
.equ GYRO_SITE_ORIG, 0xFA046FD7     /* blx 0xC01EC6F8 */

.equ HOOK_RESUME_LO, 0xC6F9         /* 0xC01EC6F9: thumb, so bx not blx          */
.equ HOOK_RESUME_HI, 0xC01E

    .global gyro_stream_hook
gyro_stream_hook:
    push    {r0-r9, ip, lr}         @ twelve: the LDRD in the callee wants 8-byte

    movw    ip, #HOOK_RESUME_LO     @ the displaced instruction, in its own place
    movt    ip, #HOOK_RESUME_HI
    blx     ip
    str     r0, [sp]                @ the caller's r11; the pop returns it

    /* Nothing is recording: do not touch the ring at all.
     *
     * The shipping logger has always worked this way -- its drain sits behind
     * the MovieRecording flag and an idle callback returns without reading a
     * byte.  The rewrite dropped that, and the fix at 013e12f only put back the
     * half the bisect pointed at, the doorbell.  This is the other half: fifty
     * memcpys a second into the pool, for the whole life of the session, for
     * data no file will ever contain.
     *
     * It branches to the TAIL, not to the exit.  The stop job is posted from
     * down there when T_WANT has just gone to zero, and skipping the whole hook
     * would leave the take's file open for ever. */
    movw    ip, #:lower16:T_WANT
    movt    ip, #:upper16:T_WANT
    ldr     ip, [ip]
    cmp     ip, #0
    beq     8f

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
    /* Base and mask once, outside the loop: this is the only producer that
     * appends more than one record per visit. */
    movw    r7, #:lower16:STREAM_RING
    movt    r7, #:upper16:STREAM_RING
    ldr     r7, [r7]
    cmp     r7, #0
    movweq  r8, #STREAM_MASK
    movwne  r8, #:lower16:RING_MASK
    movtne  r8, #:upper16:RING_MASK
    movweq  r7, #:lower16:STREAM_BASE
    movteq  r7, #:upper16:STREAM_BASE

4:  cmp     r6, r9
    movhs   r6, r5                  @ round the firmware ring

    and     r2, r0, r8
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

    /* Ring the doorbell, but only once enough has piled up to be worth a card
     * write.  This runs every 20 ms; waking the writer every time would put
     * fifty small writes a second through the one non-preemptible card lock,
     * which is exactly the shape that starved the old writer.
     *
     * Task context, so a syscall is safe from here.  The Vd hook is an
     * interrupt and must never reach writer_signal. */
8:  movw    ip, #:lower16:STREAM_INDEX
    movt    ip, #:upper16:STREAM_INDEX
    ldr     r0, [ip]
    movw    ip, #:lower16:STREAM_POSTED
    movt    ip, #:upper16:STREAM_POSTED
    ldr     r1, [ip]
    sub     r0, r0, r1
    movw    r1, #RING_CHUNK
    cmp     r0, r1
    bhs     7f
    /* Not enough yet -- but a take may have ended, and the stop has to go
     * through the queue behind whatever is still unposted.  Only the producer
     * can post it: this is task context, where a syscall is safe, and the
     * record hooks are not.
     *
     * Three conditions, not one.  Checking only "not recording" called into
     * the pool fifty times a second for the whole life of the session, with
     * nothing to do every time -- a firmware callback should not be running
     * code it does not need. */
    movw    ip, #:lower16:T_FOPEN
    movt    ip, #:upper16:T_FOPEN
    ldr     ip, [ip]
    cmp     ip, #0
    beq     9f                      @ no file: nothing to post and none to stop
    movw    ip, #:lower16:T_WANT
    movt    ip, #:upper16:T_WANT
    ldr     ip, [ip]
    cmp     ip, #0
    bne     9f                      @ still recording, and not enough yet
    movw    ip, #:lower16:T_STOPSENT
    movt    ip, #:upper16:T_STOPSENT
    ldr     ip, [ip]
    cmp     ip, #0
    bne     9f                      @ the stop has already gone
7:  movw    ip, #:lower16:STREAM_SIGFN
    movt    ip, #:upper16:STREAM_SIGFN
    ldr     ip, [ip]
    cmp     ip, #0
    blxne   ip

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
