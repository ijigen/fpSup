.syntax unified
.arm
.text
.global entry
/* ============================================================================
 * gsup_launch -- the logger's own bootstrap: ask, copy, run.
 * ============================================================================
 *
 * This replaces gsup_entry.S, and the difference is the whole point.
 *
 * gsup_entry READ the pool pointer and expected the writer blob to already be
 * sitting at pool + 0x44000.  That held while the AutoRun ran `memmgr bufmem
 * get` before anything else and stage2 placed every section in one pass.  It
 * stopped holding when the pool stopped being the script's business: nobody
 * publishes a pool any more except the payload that wants one, and a section
 * whose destination is a pool offset can only be placed after somebody has.
 * So the pointer was zero, gsup_entry returned on its first branch, the blob
 * was never placed, and the card logged nothing -- silently, because doing
 * nothing is exactly what it is supposed to do when there is no pool.
 *
 * The fix is not to make stage2 call twice.  It is that a payload drives its
 * own order: ask the allocator, copy its own bytes in, make them runnable, run
 * them.  The USB shell's worker has done this since it left the cave, and this
 * is the same shape -- which is why the blob travels APPENDED TO THIS CODE, as
 * one destination-zero section, rather than as a pool-offset section somebody
 * else has to place at the right moment.
 *
 * Destination zero means stage2 leaves the section where the file landed and
 * runs it there, so `blob` below is reachable with a PC-relative ADR.  The
 * staging buffer is handed back afterwards, which is why the blob is copied
 * rather than used in place.
 *
 * WHERE IT IS COPIED TO is not free: gsup_boot recomputes its own address as
 * POOL_PTR + 0x44000 and the editions carve the rest of the pool up by fixed
 * offsets around it (job pool +0x43000, file object +0x42000).  This puts it
 * where they all already agree it is.
 * ========================================================================== */

.equ H_GET,       0xC001D740    /* (desc, class, size, 0)                     */
.equ H_ADDR,      0xC001D7F0    /* (desc) -> address                          */
.equ POOL_CLASS,  0             /* USER.  NOT class 10, the CinemaDNG frames  */
.equ POOL_BYTES,  0x100000      /* every offset in the editions is measured
                                 * against this megabyte                      */
.equ POOL_PTR,    0xC3757A7C    /* where every gyro source reads the base     */
.equ CODE_OFF,    0x44000       /* ring_task_deploy.py CODE_POOL_OFF          */
.equ O_GSUP_BOOT, 0x18          /* the routine table's seventh word           */
.equ F_DCACHE,    0xC000E91C    /* both take no arguments: whole-cache ops    */
.equ F_ICACHE,    0xC000EABC

/* BLOB_LEN is passed in: only the builder knows how long the edition it
 * appended is, and a constant here would be the same number in two places. */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

entry:
    /* Six registers: an even count, because the firmware's LDRD needs the
     * stack 8-byte aligned and an interrupt will use ours. */
    push    {r4, r5, r6, r7, r8, lr}
    sub     sp, sp, #16                 @ the allocator descriptor.  On the
                                        @ stack because it is never freed --
                                        @ heapalloc.S only wants it kept by a
                                        @ caller that will free later.
    LDA     r4, POOL_PTR
    ldr     r5, [r4]
    cmp     r5, #0
    bne     2f                          @ a pool is already published: it
                                        @ belongs to whoever ran before us on
                                        @ this card and is theirs to keep, so
                                        @ take it rather than ask for a second
    mov     r0, sp
    mov     r1, #POOL_CLASS
    LDA     r2, POOL_BYTES
    mov     r3, #0
    LDA     ip, H_GET
    blx     ip
    mov     r0, sp
    LDA     ip, H_ADDR
    blx     ip
    movs    r5, r0
    beq     9f                          @ refused -- playback takes ten
                                        @ megabytes of its own -- so stand
                                        @ down rather than write to zero
    str     r5, [r4]                    @ published: every gyro source reads
                                        @ the base from here

2:  LDA     r7, CODE_OFF
    add     r7, r5, r7                  @ destination
    adr     r6, blob                    @ source: our own tail, where the file
                                        @ landed
    LDA     r8, BLOB_LEN
3:  ldr     ip, [r6], #4
    str     ip, [r7], #4
    subs    r8, r8, #4
    bne     3b

    /* Freshly written code is data to the caches until this runs, and the
     * I-cache may hold whatever used to be at those addresses. */
    LDA     ip, F_DCACHE
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip

    /* Hand over, exactly as gsup_entry did: r0 is the blob's base and the
     * seventh word of its table is gsup_boot's offset within it. */
    LDA     r0, CODE_OFF
    add     r0, r5, r0
    ldr     r1, [r0, #O_GSUP_BOOT]
    cmp     r1, #0
    beq     9f                          @ an unpatched table: do nothing at all
    add     r1, r0, r1
    blx     r1

9:  add     sp, sp, #16
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

    .align  2
blob:
    /* The edition's blob is appended here by build_base_card.py.  Nothing
     * below may name its own address: it is assembled somewhere else. */
