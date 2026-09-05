.syntax unified
.arm

#include "mpool.inc.S"

/* ------------------------------------------------------------------- init */

/* mpool_init(r0 = pool, r1 = payload size, r2 = block count)
 *
 * Threads every block onto the free list and stamps it free.  Blocks are
 * payload + MPB_OVERHEAD, rounded up to four so the links stay aligned.
 * Returns the byte size of the whole pool in r0, so a caller can check what it
 * reserved rather than recompute it.
 */
    .global mpool_init
mpool_init:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r4, r0                      @ pool
    add     r5, r1, #MPB_OVERHEAD
    add     r5, r5, #3
    bic     r5, r5, #3                  @ stride
    mov     r6, r2                      @ count

    mov     r0, #0
    str     r0, [r4, #MP_HEAD]
    str     r6, [r4, #MP_COUNT]
    str     r6, [r4, #MP_TOTAL]
    str     r0, [r4, #MP_HIWATER]
    str     r0, [r4, #MP_FAILED]

    /* Build the list backwards so block 0 ends up at the head: allocations
     * then come out in address order, which makes a dump readable. */
    add     r7, r4, #MP_STORAGE
    mla     r8, r5, r6, r7              @ one past the last block
    mov     r0, #0                      @ next
    movw    r1, #:lower16:MP_FREE
    movt    r1, #:upper16:MP_FREE
1:  cmp     r8, r7
    bls     2f
    sub     r8, r8, r5
    str     r0, [r8, #MPB_NEXT]
    str     r1, [r8, #MPB_GUARD]
    mov     r0, r8
    b       1b
2:  str     r0, [r4, #MP_HEAD]

    mul     r0, r6, r5                  @ the pool's whole size, for the caller
    add     r0, r0, #MP_STORAGE
    pop     {r4, r5, r6, r7, r8, lr}
    bx      lr

/* ------------------------------------------------------------------ alloc */

/* mpool_alloc(r0 = pool) -> r0 = payload, or 0 when the pool is empty.
 *
 * Zero is not an error to be logged and forgotten: it is the queue being full,
 * which is the one thing the depth exists to prevent.  MP_FAILED counts them.
 */
    .global mpool_alloc
mpool_alloc:
    push    {r1, r2, r3, lr}
    mp_lock r3

    ldr     r1, [r0, #MP_HEAD]
    cmp     r1, #0
    beq     8f

    ldr     r2, [r1, #MPB_NEXT]
    str     r2, [r0, #MP_HEAD]
    ldr     r2, [r0, #MP_COUNT]
    sub     r2, r2, #1
    str     r2, [r0, #MP_COUNT]

    /* In use = total - free; keep the largest it ever reached. */
    ldr     r12, [r0, #MP_TOTAL]
    sub     r12, r12, r2
    ldr     r2, [r0, #MP_HIWATER]
    cmp     r12, r2
    strhi   r12, [r0, #MP_HIWATER]

    movw    r2, #:lower16:MP_INUSE
    movt    r2, #:upper16:MP_INUSE
    str     r2, [r1, #MPB_GUARD]
    add     r1, r1, #MPB_PAYLOAD
    b       9f

8:  ldr     r2, [r0, #MP_FAILED]
    add     r2, r2, #1
    str     r2, [r0, #MP_FAILED]

9:  mp_unlock r3
    mov     r0, r1
    pop     {r1, r2, r3, lr}
    bx      lr

/* ------------------------------------------------------------------- free */

/* mpool_free(r0 = pool, r1 = payload) -> r0 = 1 ok, 0 refused.
 *
 * The firmware asserts on a bad pointer or a double free.  We refuse instead
 * and say so in the return: an assert here would take the camera down, and a
 * writer that frees the same descriptor twice is a bug to read about, not to
 * be killed by.
 */
    .global mpool_free
mpool_free:
    /* Four, not five.  r12 is caller-saved and the lock macros clobber it
     * anyway; an odd push misaligns the stack to eight and the next firmware
     * LDRD takes a data abort, which is a frozen camera and a battery pull. */
    push    {r1, r2, r3, lr}
    cmp     r1, #0
    beq     8f
    sub     r1, r1, #MPB_PAYLOAD

    /* The guard is read INSIDE the critical section.  Read outside, two frees
     * of the same block could both see it in use and both push it, which puts
     * one block on the list twice and hands it out to two owners. */
    mp_lock r3
    movw    r2, #:lower16:MP_INUSE
    movt    r2, #:upper16:MP_INUSE
    ldr     r12, [r1, #MPB_GUARD]
    cmp     r12, r2
    bne     7f                          @ not ours, or freed already

    movw    r2, #:lower16:MP_FREE
    movt    r2, #:upper16:MP_FREE
    str     r2, [r1, #MPB_GUARD]
    ldr     r2, [r0, #MP_HEAD]
    str     r2, [r1, #MPB_NEXT]
    str     r1, [r0, #MP_HEAD]
    ldr     r2, [r0, #MP_COUNT]
    add     r2, r2, #1
    str     r2, [r0, #MP_COUNT]
    mp_unlock r3

    mov     r0, #1
    pop     {r1, r2, r3, lr}
    bx      lr

7:  mp_unlock r3
8:  mov     r0, #0
    pop     {r1, r2, r3, lr}
    bx      lr
