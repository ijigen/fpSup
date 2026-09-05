#ifndef MPOOL_INC
#define MPOOL_INC 1

/* A fixed-size block pool, copied from the firmware's own MPoolFixed.
 *
 * ---------------------------------------------------------------------------
 * WHY THIS AND NOT A HEAP
 *
 * The audio path posts each chunk of work to its writer as a small descriptor:
 * it takes one from a pool, fills in {offset, pointer, length}, sends the
 * pointer through the mailbox, and the writer releases it when the write is
 * done.  The POOL IS THE QUEUE -- a descriptor is a queue slot, and "the pool
 * is empty" is exactly "the queue is full", which is the back-pressure signal
 * with no bookkeeping of our own.
 *
 * What makes it usable during a recording is what it is NOT.  Reading
 * MPoolFixed<24,32> at 0xC01FCDF8 (alloc) and 0xC01FD0F8 (free):
 *
 *     - it is not a heap channel, so nothing the recording path allocates can
 *       be short because of it.  That matters: holding 64 KiB of channel 10 is
 *       what froze the camera, because movRec -> FUN_c0386198 allocates from
 *       channel 10 and came up short.
 *     - it is not a kernel object, so there is no service call and no context
 *       restriction.
 *     - it is a free list in a static object, guarded by masking interrupts.
 *       O(1), no fragmentation, safe from an interrupt handler.
 *
 * ---------------------------------------------------------------------------
 * THE FIRMWARE'S LAYOUT, for MPoolFixed<24, 32> at DAT_c2f16ee0
 *
 *     +0x00   vtable
 *     +0x04   XC_DList: a doubly linked free list
 *     +0x28   free count            (vtable slot 3 returns it)
 *     +0x2C   storage: 32 blocks of 36 bytes
 *
 *   block:
 *     +0x00   next          +0x04  prev
 *     +0x08   guard   0xFAFAFEFE free / 0xBEBEBABA in use
 *     +0x0C   24 bytes of payload; the pointer handed out is block+0x0C
 *
 *   alloc pops the head and fails by returning 0 when the count is zero; free
 *   range-checks the pointer against the storage array, checks the guard, and
 *   pushes it back.  Both wrap the list work in FUN_c001cce0 / XC_INTR__v0,
 *   which are RAII around
 *
 *     FUN_c000ec14   mrs r0, cpsr / orr r1, r0, #0xC0 / msr cpsr_c, r1
 *     FUN_c000ec24   restore only the I and F bits from the saved cpsr
 *
 * ---------------------------------------------------------------------------
 * WHERE THIS DIFFERS, AND WHY
 *
 * Singly linked, not doubly.  The firmware uses its generic XC_DList because
 * that is the container it has; a pool that only ever pushes and pops one end
 * never removes from the middle, so the prev pointer is dead weight.
 *
 * The interrupt mask is inlined rather than called -- four instructions against
 * a call, and it keeps the critical section visible where it is held.
 *
 * The guard words are kept exactly.  They are not decoration: they turn a
 * double free and a pointer from outside the pool into a fault at the point of
 * the mistake, and the firmware asserts on both.
 *
 * Two counters are added that the firmware does not keep: the high-water mark
 * of blocks in use, and the number of failed allocations.  Those are the two
 * numbers that say whether the depth is right, and guessing that is what this
 * project has spent the most time on.
 */

.equ MP_FREE,        0xFAFAFEFE     /* the firmware's own guard values, kept  */
.equ MP_INUSE,       0xBEBEBABA     /* so a mixed-up pointer faults the same  */

.equ MP_HEAD,        0x00           /* first free block, 0 when empty         */
.equ MP_COUNT,       0x04           /* blocks free now                        */
.equ MP_TOTAL,       0x08           /* blocks the pool was built with         */
.equ MP_HIWATER,     0x0C           /* most ever in use at once               */
.equ MP_FAILED,      0x10           /* allocations that found the pool empty  */
.equ MP_STORAGE,     0x14           /* the blocks start here                  */

.equ MPB_NEXT,       0x00
.equ MPB_GUARD,      0x04
.equ MPB_PAYLOAD,    0x08           /* what alloc hands out                   */
.equ MPB_OVERHEAD,   0x08

/* Mask interrupts, keeping the old state in \saved.  The pool is reached from
 * task context and from the Vd interrupt, so the list has to be touched with
 * interrupts off -- exactly as the firmware does it. */
.macro mp_lock saved
    mrs     \saved, cpsr
    orr     r12, \saved, #0xC0
    msr     cpsr_c, r12
.endm

.macro mp_unlock saved
    mrs     r12, cpsr
    bic     r12, r12, #0xC0
    and     \saved, \saved, #0xC0
    orr     r12, \saved, r12
    msr     cpsr_c, r12
.endm

#endif  /* MPOOL_INC */
