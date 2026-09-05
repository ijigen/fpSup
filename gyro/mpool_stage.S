.syntax unified
.arm

#include "mpool.inc.S"

/* The same probe, cut into stages, so what wedged the camera is found rather
 * than guessed at.  Each stage does everything the one below it does and one
 * thing more; whichever stage stops answering is the one that did it.
 *
 *   1  write a marker and return            -- is the vehicle itself sound?
 *   2  + mpool_init                          -- does building the list work?
 *   3  + drain the pool with mpool_alloc     -- does the interrupt mask work?
 *   4  + mpool_free and the failure cases    -- the whole thing
 *
 * Stage 1 has no push and no call at all: if that does not come back, the
 * problem is the handler or the placement, not the pool.
 */

.equ MP_ARG_POOL,    0xC072E0F0
.equ MP_ARG_RESULT,  0xC072E0F4
.equ N_BLOCKS,       4
.equ PAYLOAD,        24

    .global mpool_stage
mpool_stage:
    movw    r0, #:lower16:MP_ARG_RESULT
    movt    r0, #:upper16:MP_ARG_RESULT
    ldr     r0, [r0]
    movw    r1, #:lower16:0xAAAA1111
    movt    r1, #:upper16:0xAAAA1111
    str     r1, [r0, #0x3C]             @ [15] "stage 1 got here"

#if STAGE >= 2
    push    {r4, r5, r6, r7, r8, lr}
    movw    r4, #:lower16:MP_ARG_POOL
    movt    r4, #:upper16:MP_ARG_POOL
    mov     r5, r0
    ldr     r4, [r4]
    mov     r0, r4
    mov     r1, #PAYLOAD
    mov     r2, #N_BLOCKS
    bl      mpool_init
    str     r0, [r5, #0x00]
    ldr     r0, [r4, #MP_COUNT]
    str     r0, [r5, #0x04]
    movw    r0, #:lower16:0xAAAA2222
    movt    r0, #:upper16:0xAAAA2222
    str     r0, [r5, #0x3C]
#endif

#if STAGE >= 3
    mov     r6, #0
    mov     r7, #0x10
1:  mov     r0, r4
    bl      mpool_alloc
    str     r0, [r5, r7]
    add     r7, r7, #4
    cmp     r0, #0
    strne   r0, [r5, #0x30]
    add     r6, r6, #1
    cmp     r6, #N_BLOCKS
    blo     1b
    ldr     r0, [r4, #MP_COUNT]
    str     r0, [r5, #0x08]
    ldr     r0, [r4, #MP_HIWATER]
    str     r0, [r5, #0x0C]
    mov     r0, r4
    bl      mpool_alloc
    str     r0, [r5, #0x20]
    ldr     r0, [r4, #MP_FAILED]
    str     r0, [r5, #0x24]
    movw    r0, #:lower16:0xAAAA3333
    movt    r0, #:upper16:0xAAAA3333
    str     r0, [r5, #0x3C]
#endif

#if STAGE >= 4
    mov     r0, r4
    ldr     r1, [r5, #0x30]
    bl      mpool_free
    str     r0, [r5, #0x28]
    mov     r0, r4
    ldr     r1, [r5, #0x30]
    bl      mpool_free
    str     r0, [r5, #0x2C]
    mov     r0, r4
    movw    r1, #:lower16:0xC0000100
    movt    r1, #:upper16:0xC0000100
    bl      mpool_free
    str     r0, [r5, #0x34]
    ldr     r0, [r4, #MP_COUNT]
    str     r0, [r5, #0x38]
    movw    r0, #:lower16:0xAAAA4444
    movt    r0, #:upper16:0xAAAA4444
    str     r0, [r5, #0x3C]
#endif

#if STAGE >= 2
    pop     {r4, r5, r6, r7, r8, lr}
#endif
    mov     r0, #0
    bx      lr

#if STAGE >= 2
#include "mpool.S"
#endif
