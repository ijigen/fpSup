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
     * It can branch straight to the exit now.  The stop job used to be posted
     * from a tail down here, which is why this used to have to fall through it;
     * take_close posts it from the record hook, so there is nothing left in
     * this hook that a stopped take still needs. */
    movw    ip, #:lower16:T_WANT
    movt    ip, #:upper16:T_WANT
    ldr     ip, [ip]
    cmp     ip, #0
    beq     9f

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

    /* Gyro records only, so this is a ruler for the sensor's own rate: the
     * shared index counts both sensors and cannot be one.  Only this task
     * writes it, so it needs no exclusive. */
    movw    r2, #:lower16:STREAM_GCOUNT
    movt    r2, #:upper16:STREAM_GCOUNT
    ldr     r1, [r2]
    add     r1, r1, r4
    str     r1, [r2]

    add     r6, r6, #GYRO_DATA_OFF      @ source cursor
    add     r5, r8, #GYRO_DATA_OFF      @ first record of the firmware ring
    movw    r9, #GYRO_SPAN
    add     r9, r5, r9                  @ one past its last

    /* Ask, copy, say done.  That is the whole of it.
     *
     * This hook does not know that buffers exist, how big they are, when one
     * fills, or that anything is ever posted.  It asks for room, is given as
     * much as there is, writes it, says how much it wrote, and asks again if it
     * still has records left.  Every judgement that used to live here -- the
     * ring mask, the chunk threshold, whether a file was open, whether the stop
     * had gone -- is in stream_space.S now, which is the only thing in the
     * system that has any business making it.
     *
     * The audio producer is a DMA engine and tests nothing at all.  This is as
     * close to that as software gets. */
10: mov     r0, r4
    movw    ip, #:lower16:STREAM_CLAIMFN
    movt    ip, #:upper16:STREAM_CLAIMFN
    ldr     ip, [ip]
    cmp     ip, #0
    beq     9f
    blx     ip                          @ r0 = where, r1 = how many
    cmp     r1, #0
    beq     9f
    mov     r7, r0
    mov     r8, r1                      @ keep the count for the commit
    sub     r4, r4, r1

4:  cmp     r6, r9
    movhs   r6, r5                      @ round the firmware ring

    ldrsh   r3, [r6]
    strh    r3, [r7]
    ldrsh   r3, [r6, #2]
    strh    r3, [r7, #2]
    ldrsh   r3, [r6, #6]
    strh    r3, [r7, #6]
    mov     r3, #TAG_GYRO
    strh    r3, [r7, #4]                @ last: the tag publishes the record

    ldrsh   r3, [r6, #4]                @ the pad this format spends
    cmp     r3, #0
    bne     5f

6:  add     r6, r6, #8
    add     r7, r7, #8
    subs    r1, r1, #1
    bne     4b

    mov     r0, r8
    movw    ip, #:lower16:STREAM_COMMITFN
    movt    ip, #:upper16:STREAM_COMMITFN
    ldr     ip, [ip]
    cmp     ip, #0
    blxne   ip                          @ and it decides whether a buffer filled

    cmp     r4, #0
    bne     10b

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
