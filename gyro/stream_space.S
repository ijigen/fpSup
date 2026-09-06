.syntax unified
.arm

#include "imu_stream.inc.S"

/* The space provider.
 *
 * Audio's producer is a DMA engine.  It does not test anything: it is pointed
 * at a buffer, it writes until that buffer ends, and the DSP raises the
 * completion.  The judgement -- which buffer, is it full, hand it over -- lives
 * on the other side of the hardware, in one place, and the filler never sees
 * it.
 *
 * These two routines are that other side.  A producer says "room for n
 * records", writes what it is given, and says "done".  It contains no
 * threshold, no boundary test, no posting, and no knowledge that buffers exist
 * at all.  Everything that used to be scattered through the gyro hook's tail --
 * "is INDEX minus POSTED at least a chunk", "is a file open", "has the stop
 * gone" -- is gone from the producers entirely.
 *
 * Buffers are not a second allocation: the ring the deployer already carves out
 * of the pool IS the row of buffers, tiled exactly.  Audio's two come out of
 * the class 6 heap at capture start; ours come out of the block AutoRun asked
 * the allocator for at boot, which is the same memory from the same allocator,
 * taken at a moment that cannot collide with the recorder.
 */

/* stream_claim(r0 = records wanted) -> r0 = where to write, r1 = records given.
 *
 * Never spans a buffer, so a producer that wants more than the current buffer
 * has left is simply given less and comes back.  That is the whole of the
 * flow control, and it is why the producers have no loop condition to get
 * wrong: they ask until they have been given everything.
 */
    .global stream_claim
stream_claim:
    push    {r2, r3, r4, r5, ip, lr}
    mov     r4, r0                      @ wanted
    movw    r5, #BUF_MASK

    movw    r3, #:lower16:STREAM_INDEX
    movt    r3, #:upper16:STREAM_INDEX
1:  ldrex   r0, [r3]
    and     r1, r0, r5                  @ how far into the buffer we are
    movw    r2, #BUF_RECORDS
    sub     r1, r2, r1                  @ room left in it
    cmp     r4, r1
    movlo   r1, r4                      @ r1 = min(wanted, room)
    add     r2, r0, r1
    strex   ip, r2, [r3]
    cmp     ip, #0
    bne     1b

    ring_slot r0, r2, ip                @ r2 = the byte address of record r0
    mov     r0, r2
    pop     {r2, r3, r4, r5, ip, lr}
    bx      lr


/* stream_commit(r0 = records written).
 *
 * Raised AFTER the records are in memory, not when the space was reserved: a
 * buffer that is spoken for is not a buffer that is full.  When the count lands
 * exactly on a buffer's end that buffer is complete and goes over, once, from
 * here.  It is an equality, not a threshold -- there is nothing to tune and
 * nothing to be late about.
 */
    .global stream_commit
stream_commit:
    push    {r1, r2, r3, r4, ip, lr}
    mov     r4, r0                      @ records written

    movw    r3, #:lower16:STREAM_DONE
    movt    r3, #:upper16:STREAM_DONE
1:  ldrex   r0, [r3]
    add     r1, r0, r4
    strex   r2, r1, [r3]
    cmp     r2, #0
    bne     1b

    movw    r2, #BUF_MASK
    ands    r2, r1, r2
    bne     9f

    movw    r2, #BUF_RECORDS
    sub     r0, r1, r2                  @ the first record of the buffer that filled
    movw    ip, #:lower16:STREAM_SIGFN
    movt    ip, #:upper16:STREAM_SIGFN
    ldr     ip, [ip]
    cmp     ip, #0
    blxne   ip                          @ writer_post_buffer(r0)

9:  pop     {r1, r2, r3, r4, ip, lr}
    bx      lr
