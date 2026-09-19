.syntax unified
.arm
.text
.global stage2

/* Not "the pool" any more -- there is no such thing.  This word holds whatever
 * the file's own entry published into it, which is how a section can name an
 * offset into memory the allocator only chooses at run time.  The gyro logger
 * publishes it and has one such section; a card whose entry publishes nothing
 * leaves it zero, and the placement below is skipped rather than writing to a
 * low address.  The loader does NOT publish it: its staging buffer is handed
 * back, and pointing anything at a freed block is worse than pointing at zero. */
.equ FRAMEBUF, 0xC3757A7C
.equ F_DCACHE,  0xC000E91C           /* D-cache clean/invalidate + barriers */
.equ F_ICACHE,  0xC000EABC           /* whole I-cache invalidate + barriers */

/* The second half of the loader, carried in \fpSup.BIN instead of spelled out.
 *
 * Everything the AutoRun writes costs a `mem set` and about sixty milliseconds,
 * so the first half is kept to what has to exist before the file is in memory:
 * restore the callback, open, read, close, check the magic, and branch here.
 * Placing the sections and the cache maintenance do not need to be spelled out,
 * because by the time they run the file is already in RAM -- so they live here,
 * where they are free.
 *
 * Runs from the read buffer, which is the camera's DMA pool; the first half
 * cleans the cache before branching, so these instructions are really there.
 *
 *   r0 = the buffer, which is also the file:
 *        +0x00 "VBIN"   +0x04 count   +0x08 entry   +0x0C data bytes
 *        +0x10 the table: { destination, length } per section, then the data
 *
 * The first section is this code, and it is marked with destination zero so the
 * loop leaves it where it is instead of copying it over something.
 *
 * TWO PASSES, and the entry is called between them.
 *
 * A destination below 0x40000000 is an offset into a pool -- and nobody owns a
 * pool at boot any more.  The loader's buffer is a staging buffer it frees on
 * its way out; what a payload needs, the payload asks the allocator for itself,
 * in its entry.  So the order has to be: place everything that lives at a
 * firmware address, call the entry (which allocates and publishes), then place
 * the sections that are offsets into what it just published.
 *
 * Which means the entry is CALLED, not tail-branched to, and it has to come
 * back.  `spawn` does; a payload whose entry never returns gets its firmware
 * sections and nothing else, and no diagnosis -- there is no one left to give
 * one.  The gyro logger is the only card with a pool section today (its
 * profile generator, 10,640 bytes at pool+0x44000) and its entry returns.
 *
 * Returns to the first half in every case. */
stage2:
    push    {r4, r5, r6, r7, r8, lr}   @ an even count: the firmware LDRDs need 8-byte alignment
    mov     r6, r0
    mov     r8, #1                      @ pass 1: firmware destinations
    bl      s2_pass
    bl      s2_publish                  @ before anything placed is allowed to run
    /* The entry.  Below 0x40000000 it is an offset into this buffer rather
     * than an address -- which is how a payload names its own bootstrap when
     * that bootstrap is meant to run where the file landed, out of memory the
     * allocator chose this boot.  The worker's does: it asks for a pool of its
     * own and copies the rest of itself into it, so that nothing of it is left
     * in the cave and nothing of it is left here when the loader hands this
     * buffer back. */
    ldr     r0, [r6, #8]                @ entry, or zero
    cmp     r0, #0
    beq     1f
    movw    r3, #0
    movt    r3, #0x4000                 @ 0x40000000
    cmp     r0, r3
    addlo   r0, r0, r6
    mov     ip, r0
    blx     ip
1:  mov     r8, #0                      @ pass 2: offsets into the entry's pool
    bl      s2_pass
    bl      s2_publish                  @ the pool code just landed; publish it too
    /* Put the loader in the settings block, if what is there is not already
     * this one.
     *
     * The loader used to do this to itself, on its way out, and it needed a
     * handshake word to know whether to: store_boot set a flag before it
     * branched, and a set flag meant "you came out of the store, do not write
     * flash again".  An indirect answer to a question that can be asked
     * directly -- so it is asked directly here.  The magic in the store is
     * compared with the one this build baked in, and those are equal exactly
     * when the store already holds this loader.  The handshake word is gone.
     *
     * Here rather than in the loader for the same reason the abort is: the
     * loader has to fit in 468 bytes of settings block, and this was 72 of
     * them.  Out here it costs nothing.  It is also a better moment -- the
     * loader has not just been read, it has been used: the file opened, every
     * section is placed, the entry has returned.  What gets written to flash
     * is a loader that has demonstrated it works.
     *
     * Compiled in only for a card that has a store.  The copy is a
     * `subs`/`bne` countdown, and a length of zero counts down from -4 for
     * about a billion iterations before it comes round to zero -- a card with
     * nothing to publish must not carry this code at all rather than carry it
     * with a harmless-looking constant.
     *
     * The magic goes LAST.  A store half written by a power cut must not look
     * valid to the next boot, and the magic is the only thing that boot
     * checks. */
#ifdef STORE_PROVISION
    movw    r4, #:lower16:STORE
    movt    r4, #:upper16:STORE
    movw    r0, #:lower16:STORE_MAGIC
    movt    r0, #:upper16:STORE_MAGIC
    ldr     r1, [r4]
    cmp     r1, r0
    beq     2f                          @ already this loader: leave flash alone

    movw    r2, #:lower16:LOADER_BASE
    movt    r2, #:upper16:LOADER_BASE
    movw    r3, #:lower16:STORE_LEN
    add     r5, r4, #4                  @ the body starts past the magic
1:  ldr     ip, [r2], #4
    str     ip, [r5], #4
    subs    r3, r3, #4
    bne     1b
    str     r0, [r4]                    @ magic last
2:
#endif
    /* Arm the stop, now that there is something to stop for.
     *
     * The loader used to do this on its way out, which is one call too early:
     * at that point the file has been read but nothing is placed.  Here every
     * section is down and the payload's entry has been and returned, so the
     * script really has nothing left worth reading -- and the `echo` two lines
     * further on ends it.
     *
     * The loader needed a handshake word to know whether to arm at all (arming
     * on a boot that had not come from the store would stop the script before
     * the loader had been written out).  This needs none: stage2 runs only
     * after a read that worked, on either path, and on the slow path the
     * script restores this slot a few lines later anyway.
     *
     * ABORT_AT is a section of this same file, placed in the cave -- somewhere
     * that outlives the staging buffer, which the loader hands back. */
    movw    r0, #:lower16:ABORT_AT
    movt    r0, #:upper16:ABORT_AT
    movw    r1, #:lower16:ECHO_SLOT
    movt    r1, #:upper16:ECHO_SLOT
    str     r0, [r1]

    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

/* --- one pass over the section table --------------------------------------
 * r6 = the buffer, r8 = 1 to place firmware destinations, 0 to place pool
 * offsets.  Rebuilds its own cursors, so the two passes cannot share state. */
s2_pass:
    push    {r9, lr}
    ldr     r7, [r6, #4]                @ section count
    add     r5, r6, #16                 @ the table
    add     r4, r5, r7, lsl #3          @ the data begins past it
s2_place:
    cmp     r7, #0
    beq     s2_pass_done
    ldr     r0, [r5], #4                @ destination
    ldr     r1, [r5], #4                @ length
    add     r2, r1, #3
    bic     r2, r2, #3                  @ each section starts on a word
    cmp     r0, #0
    beq     s2_next                     @ destination zero: this code itself

    /* Firmware destinations are all 0xC0000000 and above, so a destination
     * below 0x40000000 can only be a pool offset -- a build cannot name a pool
     * address, because the allocator decides it, but it can name an offset. */
    movw    r3, #0
    movt    r3, #0x4000                 @ 0x40000000
    cmp     r0, r3
    bhs     2f

    cmp     r8, #0
    bne     s2_next                     @ pass 1 leaves pool sections alone
    movw    r3, #:lower16:FRAMEBUF
    movt    r3, #:upper16:FRAMEBUF
    ldr     r3, [r3]
    cmp     r3, #0
    beq     s2_next                     @ the entry published no pool: place
    add     r0, r0, r3                  @ nothing rather than write to a low
    b       3f                          @ address

2:  cmp     r8, #0
    beq     s2_next                     @ pass 2: these are already in place

3:  subs    r1, r1, #4
    ldrge   r3, [r4, r1]
    strge   r3, [r0, r1]
    bgt     3b
s2_next:
    add     r4, r4, r2
    sub     r7, r7, #1
    b       s2_place
s2_pass_done:
    pop     {r9, pc}

/* --- make written words executable ----------------------------------------
 * The loader runs after live view has already exercised some firmware
 * callsites.  Publishing the new RAM words is not enough: those sites can still
 * execute their stock instructions from I-cache.  Clean data first, then
 * invalidate instruction cache.  This also makes a hook in an early or
 * continuous AE path reliable.
 *
 * 0xC000E91C pushes r4-r7 and pops them again, so the cursors above survive. */
s2_publish:
    push    {r4, lr}
    movw    ip, #:lower16:F_DCACHE
    movt    ip, #:upper16:F_DCACHE
    blx     ip
    movw    ip, #:lower16:F_ICACHE
    movt    ip, #:upper16:F_ICACHE
    blx     ip
    pop     {r4, pc}
