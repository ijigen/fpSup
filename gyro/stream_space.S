.syntax unified
.arm

#include "imu_stream.inc.S"

/* The space provider.
 *
 * Audio's producer is a DMA engine.  It is pointed at a block, it writes until
 * that block ends, and the DSP raises the completion.  It tests nothing, and
 * "full" is not a number: it is the block being used up.
 *
 * These two routines are the other side of that hardware.  A producer says
 * "room for n records", writes what it is given, and says "done".  It contains
 * no threshold, no boundary, no posting, and no knowledge that blocks exist.
 *
 * And there is no arithmetic here that decides fullness either.  The same
 * subtraction that works out how much of the current block is left is what
 * discovers there is none: give what there is, and when what there is runs to
 * zero, that block is over.
 */

/* stream_claim(r0 = records wanted) -> r0 = where to write, r1 = records given.
 *
 * Never spans a block, so a producer that wants more than this one has left is
 * given less and comes back.  That is the whole of the flow control.
 */
    .global stream_claim
stream_claim:
    push    {r2, r3, r4, r5, r6, lr}
    mov     r4, r0                      @ wanted
    st_lock r6

    movw    r5, #:lower16:B_CUR
    movt    r5, #:upper16:B_CUR
    ldr     r0, [r5]
    cmn     r0, #1
    bne     2f

    /* No block in hand.  Take a free one -- and if there is none, the writer
     * has not kept up and this data is lost.  Audio cannot reach this state: it
     * has two blocks and 85 ms, and if its writer were ever that late the DSP
     * would simply overwrite.  We would rather count it, because J_OFF then
     * leaves the hole in the right place and every later record keeps its own
     * time. */
    movw    r2, #:lower16:B_BUSY
    movt    r2, #:upper16:B_BUSY
    mov     r0, #0
1:  ldr     r3, [r2, r0, lsl #2]
    cmp     r3, #0
    beq     3f
    add     r0, r0, #1
    cmp     r0, #BUF_N
    blo     1b

    movw    r2, #:lower16:B_DROPS
    movt    r2, #:upper16:B_DROPS
    ldr     r3, [r2]
    add     r3, r3, #1
    str     r3, [r2]
    mov     r0, #0
    mov     r1, #0
    st_unlock r6
    pop     {r2, r3, r4, r5, r6, lr}
    bx      lr

3:  str     r0, [r5]                    @ B_CUR = the block we just took
    movw    r2, #:lower16:B_FILL
    movt    r2, #:upper16:B_FILL
    mov     r3, #0
    str     r3, [r2]
    movw    r2, #:lower16:B_DONE
    movt    r2, #:upper16:B_DONE
    str     r3, [r2]

2:  /* r0 = the block.  How much of it is left, and where in it we are. */
    movw    r2, #:lower16:B_FILL
    movt    r2, #:upper16:B_FILL
    ldr     r3, [r2]
    movw    r1, #:lower16:BUF_RECORDS
    movt    r1, #:upper16:BUF_RECORDS
    sub     r1, r1, r3                  @ room
    cmp     r4, r1
    movlo   r1, r4                      @ r1 = min(wanted, room)
    add     ip, r3, r1
    str     ip, [r2]                    @ B_FILL += given

    movw    r2, #:lower16:B_PTR
    movt    r2, #:upper16:B_PTR
    ldr     r0, [r2, r0, lsl #2]
    cmp     r0, #0
    beq     8f                          @ no allocation behind it: hand out
                                        @ nothing rather than address zero.
                                        @ take_open may never have run -- the
                                        @ layered test switches it off -- and a
                                        @ producer writing to a null block is a
                                        @ data abort, not a lost sample.
    add     r0, r0, r3, lsl #3          @ where in the block

    st_unlock r6
    pop     {r2, r3, r4, r5, r6, lr}
    bx      lr

8:  /* The block has no memory behind it.  Undo the claim and give nothing.
     * r2 is B_PTR by now, so B_FILL has to be addressed again -- r3 still holds
     * what it was before the claim. */
    movw    r2, #:lower16:B_FILL
    movt    r2, #:upper16:B_FILL
    str     r3, [r2]
    mov     r0, #0
    mov     r1, #0
    st_unlock r6
    pop     {r2, r3, r4, r5, r6, lr}
    bx      lr


/* stream_commit(r0 = records written).
 *
 * After the records are in memory, not when the space was reserved: a block
 * that is spoken for is not a block that is full.  When the block is used up it
 * goes to the writer, once, from here.
 */
    .global stream_commit
stream_commit:
    push    {r1, r2, r3, r4, r5, r6, r7, lr}
    mov     r4, r0
    st_lock r7

    movw    r5, #:lower16:B_CUR
    movt    r5, #:upper16:B_CUR
    ldr     r5, [r5]
    cmn     r5, #1
    beq     9f                          @ nothing was given, nothing to commit

    movw    r2, #:lower16:B_DONE
    movt    r2, #:upper16:B_DONE
    ldr     r3, [r2]
    add     r3, r3, r4
    str     r3, [r2]

    movw    r1, #:lower16:BUF_RECORDS
    movt    r1, #:upper16:BUF_RECORDS
    cmp     r3, r1
    blo     9f                          @ this block still has room in it

    /* Used up.  Hand it over. */
    movw    r1, #:lower16:B_BUSY
    movt    r1, #:upper16:B_BUSY
    mov     r2, #1
    str     r2, [r1, r5, lsl #2]

    movw    r1, #:lower16:B_HANDED
    movt    r1, #:upper16:B_HANDED
    ldr     r2, [r1]
    add     r2, r2, #1
    str     r2, [r1]

    movw    r1, #:lower16:B_PTR
    movt    r1, #:upper16:B_PTR
    ldr     r0, [r1, r5, lsl #2]        @ r0 = the block
    movw    r1, #:lower16:BUF_BYTES
    movt    r1, #:upper16:BUF_BYTES     @ r1 = its length
    movw    r2, #:lower16:B_OFF
    movt    r2, #:upper16:B_OFF
    ldr     r3, [r2]                    @ r3 = where it belongs in the file
    add     r4, r3, r1
    str     r4, [r2]                    @ the next block starts after it
    mov     r2, r3
    mov     r3, r5                      @ r3 = which block, so it can be freed

    movw    ip, #:lower16:B_CUR
    movt    ip, #:upper16:B_CUR
    mvn     r4, #0
    str     r4, [ip]                    @ take a fresh one on the next claim

    /* The block is marked busy and B_CUR is already cleared, so the state is
     * consistent and nobody else can touch this block: let interrupts back in
     * before calling out.  Posting takes a descriptor and sends a message, and
     * neither belongs inside a critical section. */
    st_unlock r7
    movw    ip, #:lower16:STREAM_SIGFN
    movt    ip, #:upper16:STREAM_SIGFN
    ldr     ip, [ip]
    cmp     ip, #0
    blxne   ip                          @ writer_post(ptr, len, offset, block)
    pop     {r1, r2, r3, r4, r5, r6, r7, lr}
    bx      lr

9:  st_unlock r7
    pop     {r1, r2, r3, r4, r5, r6, r7, lr}
    bx      lr
