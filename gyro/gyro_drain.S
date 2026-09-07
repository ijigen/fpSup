.syntax unified
.arm

#include "imu_stream.inc.S"

/* Move whatever the coprocessor has written since last time into the stream.
 *
 * This used to be a hook on the firmware's 20 ms gyro callback, and that
 * callback was the last timer in the system: everything else is now driven by
 * something happening.  It is a plain routine now, and the things that happen
 * call it --
 *
 *     the accelerometer driver publishing a sample, which is a real hardware
 *     event and the only one this data has;
 *     the recorder committing a stop, so the tail of the take is not left in
 *     the coprocessor's ring.
 *
 * Draining BEFORE the accelerometer record is appended is what makes that
 * record land in the right place: every gyro sample that preceded it is already
 * in the stream, so its position is its time to 400 us.  That is the whole
 * reason the drain moved here.  It is also why nothing else may append.
 *
 * It does not gate on anything.  Whether a take is running is the caller's
 * question, and the caller is the one who knows.
 */
.equ GYRO_DESC_RING, 0x60           /* -> the ring object                     */
.equ GYRO_DATA_OFF,  4              /* records start at base+4                */
.equ GYRO_SPAN,      0x12C0         /* 600 records of eight bytes             */

    .global gyro_drain
gyro_drain:
    push    {r0-r9, ip, lr}

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
10: lsl     r0, r4, #3                  @ what is left to move, in bytes
    movw    ip, #:lower16:STREAM_CLAIMFN
    movt    ip, #:upper16:STREAM_CLAIMFN
    ldr     ip, [ip]
    cmp     ip, #0
    beq     9f
    blx     ip                          @ r0 = where, r1 = how many BYTES
    cmp     r1, #8
    blo     9f                          @ not even one whole record
    bic     r1, r1, #7                  @ whole records only: the space provider
    mov     r7, r0                      @ counts bytes and does not know ours
    mov     r8, r1                      @ keep the byte count for the commit
    lsr     r1, r1, #3                  @ and the record count for the loop
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
 * routine writes the counter, so it needs no exclusive. */
5:  movw    r3, #:lower16:STREAM_PADBAD
    movt    r3, #:upper16:STREAM_PADBAD
    ldr     ip, [r3]
    add     ip, ip, #1
    str     ip, [r3]
    b       6b
