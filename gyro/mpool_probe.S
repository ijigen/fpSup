.syntax unified
.arm

#include "mpool.inc.S"

/* Exercise the pool once and leave every answer in memory.
 *
 * A pool that looks right and is wrong is the worst outcome here: it would
 * hand the same descriptor to two owners and the corruption would surface
 * somewhere else entirely.  So this checks the things that would hide --
 * exhaustion, double free, a pointer from outside -- not just that alloc
 * returns something.
 *
 * The two addresses come from fixed words rather than registers: the probe is
 * fired through the shell's borrowed command handler, which calls it with
 * whatever happened to be in r0 and r1.
 */
.equ MP_ARG_POOL,    0xC072E0F0
.equ MP_ARG_RESULT,  0xC072E0F4
.equ N_BLOCKS,   4
.equ PAYLOAD,    24

    .global mpool_probe
mpool_probe:
    push    {r4, r5, r6, r7, r8, lr}
    movw    r4, #:lower16:MP_ARG_POOL
    movt    r4, #:upper16:MP_ARG_POOL
    ldr     r5, [r4, #4]                @ results
    ldr     r4, [r4]                    @ the pool object

    mov     r1, #PAYLOAD
    mov     r2, #N_BLOCKS
    bl      mpool_init
    str     r0, [r5, #0x00]             @ [0] the pool's byte size
    ldr     r0, [r4, #MP_COUNT]
    str     r0, [r5, #0x04]             @ [1] free after init: expect 4

    /* Drain it. */
    mov     r6, #0
    mov     r7, #0x10                   @ results[4..7] take the pointers
1:  mov     r0, r4
    bl      mpool_alloc
    str     r0, [r5, r7]
    add     r7, r7, #4
    cmp     r0, #0
    moveq   r8, #0
    movne   r8, r0
    strne   r8, [r5, #0x30]             @ [12] keep the last good one
    add     r6, r6, #1
    cmp     r6, #N_BLOCKS
    blo     1b

    ldr     r0, [r4, #MP_COUNT]
    str     r0, [r5, #0x08]             @ [2] free after draining: expect 0
    ldr     r0, [r4, #MP_HIWATER]
    str     r0, [r5, #0x0C]             @ [3] high water: expect 4

    /* One more than there are.  This must fail, and be counted. */
    mov     r0, r4
    bl      mpool_alloc
    str     r0, [r5, #0x20]             @ [8] expect 0
    ldr     r0, [r4, #MP_FAILED]
    str     r0, [r5, #0x24]             @ [9] expect 1

    /* Give one back, then give the same one back again. */
    mov     r0, r4
    ldr     r1, [r5, #0x30]
    bl      mpool_free
    str     r0, [r5, #0x28]             @ [10] expect 1
    mov     r0, r4
    ldr     r1, [r5, #0x30]
    bl      mpool_free
    str     r0, [r5, #0x2C]             @ [11] expect 0 -- the guard caught it

    /* A pointer that was never ours. */
    mov     r0, r4
    movw    r1, #:lower16:0xC0000100
    movt    r1, #:upper16:0xC0000100
    bl      mpool_free
    str     r0, [r5, #0x34]             @ [13] expect 0

    ldr     r0, [r4, #MP_COUNT]
    str     r0, [r5, #0x38]             @ [14] expect 1: only the one real free

    movw    r0, #:lower16:0x600D0000
    movt    r0, #:upper16:0x600D0000
    str     r0, [r5, #0x3C]             @ [15] the probe ran to the end

    pop     {r4, r5, r6, r7, r8, lr}
    bx      lr

/* The pool itself, so the probe is one blob and the calls resolve without a
 * relocation the loader here cannot apply.  The duplicate .equ definitions are
 * the same values; GAS allows the redefinition. */
#include "mpool.S"
