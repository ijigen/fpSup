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
.equ F_TICK_US, 0xC002B6E0           /* () -> microseconds since power-on   */

#ifdef LH_RESTORE
/* The power-off restore (LH_RESTORE, every --loader card) and the loader hook
 * (LOADER_HOOK, only the merge page's Fast Start 2).  See LOADER_V2.md.
 *
 * Every firmware word this file overwrites is copied first into a journal in
 * memory from the allocator, and a power-off callback writes the journal back.
 * So a warm boot finds the image stock again -- except 0xC03DA420, the call
 * that starts the AutoRun, which is pointed at the loader's +4 entry and is the
 * one patch meant to outlive the boot.
 *
 * Not journaled: the cave (0xC072D000..0xC0735000).  It holds hook BODIES and
 * the loader, not hook sites; writing it back at power-off while the firmware
 * may still branch into it is the wrong order, and nothing reaches it once the
 * sites are stock.
 *
 * Non-cache routines are called through r3/r7, not ip: verify_stage2_cache_
 * publish reads every movw/movt/blx ip as a cache call. */
.equ LH_SITE,   0xC03DA420           /* bl 0xC03DA758: starts the AutoRun   */
.equ MEM_HEAP,  0xC001CF78           /* (class) -> channel                  */
.equ MEM_GET,   0xC001D038           /* (channel, size, 0, 0, [sp] 0)       */
.equ POFF_MGR,  0xC0023A98           /* () -> XC_PowerOffMgr                */
.equ POFF_ADD,  0xC0024118           /* (mgr, obj, forced) -> 1 registered  */
.equ CAVE_LO,   0xC072D000
.equ CAVE_HI,   0xC0735000
/* LH_ENTRY_AT / LH_ENTRY_WORD: the loader's +4 and the `b lhook` it must hold.
 * LH_BL: `bl LH_ENTRY_AT` encoded at LH_SITE.  Passed in by build_autorun. */
#endif

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
    push    {r4, r5, r6, r7, r8, r9, r10, lr}   @ an even count: the firmware LDRDs need 8-byte alignment
    mov     r6, r0

    /* Hand the cave's allocator a fresh start, before anybody can ask.
     *
     * One word holds the next free cave address and a payload takes what it
     * needs by adding to it -- no free list, because nothing gives cave space
     * back within a boot, and no lock, because entries are called one after
     * another from here.  What it buys is that a card nobody selected costs no
     * addresses at all, instead of holding a reserved range for a feature the
     * user may not want.
     *
     * RESET EVERY BOOT, and that is the part that bites.  The cave outlives a
     * soft power cycle, so a pointer left from the last boot would climb a
     * little further each time until it walked off the end -- the same shape as
     * the stale B_PTR that had the logger writing into buffers the recorder had
     * been given.  Here is the only honest moment: after the file is in memory
     * and before any entry has run. */
    movw    r0, #:lower16:CAVE_ARENA
    movt    r0, #:upper16:CAVE_ARENA
    movw    r1, #:lower16:CAVE_BUMP
    movt    r1, #:upper16:CAVE_BUMP
    str     r0, [r1]
#ifdef LH_RESTORE
    /* The journal and the power-off callback, BEFORE anything is placed: a
     * patch must never exist without its way back.  r9 = the block (0: none,
     * and then the hook is not armed), r10 = the journal's write cursor. */
    mov     r9, #0
    mov     r10, #0
    bl      lh_setup
#endif
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
     * Only on a card that has a fast path.  This was unconditional, and that
     * meant every gyro and open-gate release placed the abort in the cave and
     * pointed the echo slot at it, on a card with nothing to stop early for --
     * the script restored the slot three commands later and the abort never
     * ran.  Harmless there only because of how that AutoRun happens to be laid
     * out: a script with an `echo` after the loader would have been cut off.
     * Safety that depends on the caller's line order is not safety.
     *
     * So a plain card places sections, calls the entry and returns, and that
     * is all it does; the fast path -- writing the loader into flash and
     * stopping the script that has just been made redundant -- belongs to the
     * build that asked for one.
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
#ifdef ARM_ABORT
    /* Only when an AutoRun is actually running.  The loader hook path starts
     * no script: arming there would leave `echo` pointing at the abort, and the
     * next `echo` anyone sends would pop a registration that does not exist.
     * Same test abort.S uses to find the script: a table entry whose per-line
     * callback is the interpreter's (0xC03DA7A8). */
    movw    r0, #:lower16:0xC2F20FC0    @ registration table, depth at +0x21C
    movt    r0, #:upper16:0xC2F20FC0
    movw    r2, #:lower16:0xC03DA7A8
    movt    r2, #:upper16:0xC03DA7A8
    ldr     r1, [r0, #0x21C]
    cmp     r1, #15                     @ the firmware's own limit; anything
    bhi     .Larm_done                  @ bigger is not a live table
.Larm_scan:
    cmp     r1, #1
    blt     .Larm_done                  @ no script: nothing to stop
    add     r3, r0, r1, lsl #5          @ entry = table + depth * 36
    add     r3, r3, r1, lsl #2
    ldr     r3, [r3, #4]
    cmp     r3, r2
    beq     .Larm_do
    subs    r1, r1, #1
    b       .Larm_scan
.Larm_do:
    movw    r0, #:lower16:ABORT_AT
    movt    r0, #:upper16:ABORT_AT
    movw    r1, #:lower16:ECHO_SLOT
    movt    r1, #:upper16:ECHO_SLOT
    str     r0, [r1]
.Larm_done:
#endif

    /* When the load finished, in the camera's own microseconds.
     *
     * Every section is placed, the entry has been and returned, the store is
     * provisioned and the stop is armed -- there is nothing left of the load
     * after this line, so this is the moment worth stamping.
     *
     * It is here rather than in the host's stopwatch because the host cannot
     * see power-on: the best it can do is poll for the worker to answer, which
     * carries USB enumeration and the polling interval with it (measured
     * 165-627 ms of spread).  TICK_US is the camera's own counter and it
     * restarts at power-on (measured: 12,722,392 ms before a reboot, 304,362
     * after), so this word is the load time with nothing else in it.
     *
     * Free: this code travels in the file.  The word is LOAD_DONE_US, which was
     * the store handshake until the magic replaced it -- reserved and dead
     * since.  Read it with `mem get 0xC072F6F8,,4`.
     *
     * SP is 8-aligned here (the loader pushed eight registers, this pushed
     * six), but recprobe.S aligns before the same call and a leaf that is wrong
     * about this is the freeze our own notes warn about, so it is aligned
     * anyway -- three instructions, in the file, free.
     *
     * Called through r4, not ip, on purpose: verify_stage2_cache_publish
     * decodes every `movw ip / movt ip / blx ip` in the emitted machine code
     * and requires the list to be exactly the two cache routines.  That check
     * is the reason a renamed constant cannot make a build look safe, so this
     * routine stays out of its way instead of being accommodated by it.  r4 and
     * r5 are ours -- both are in the push above and about to be popped. */
    mov     r5, sp
    bic     sp, sp, #7
    movw    r4, #:lower16:F_TICK_US
    movt    r4, #:upper16:F_TICK_US
    blx     r4
    mov     sp, r5
    movw    r1, #:lower16:LOAD_DONE_US
    movt    r1, #:upper16:LOAD_DONE_US
    str     r0, [r1]

#ifdef LH_BANNER
    /* On a warm boot the AutoRun never runs, so nothing else tells the user
     * the load is done.  After LOAD_DONE_US, so the wait below is not load
     * time. */
    bl      lh_banner
#endif

#ifdef LH_SPLASH
    /* The four-box splash on the loader hook path.  splash_finish assumes the
     * AutoRun already paused the GUI redraw and painted frame 0; on a warm boot
     * no AutoRun ran, so do those two things first.  Does nothing when the
     * redraw is already paused, i.e. on the AutoRun path. */
    bl      lh_splash_pre
#endif

#ifdef SPLASH_FINISH
    /* Completion artwork stays in the staging buffer until this call returns.
     * Keep it after LOAD_DONE_US so the display hold is not load time. */
    bl      .Ls2_splash_finish
#endif

#ifdef LOADER_HOOK
    /* Arm the loader hook -- only with the callback registered, and only if
     * the loader in the cave is the one whose +4 is the hook entry this build
     * expects.  A loader left by another card's cold boot fails that check and
     * the next boot simply runs the AutoRun. */
    cmp     r9, #0
    beq     1f
    movw    r0, #:lower16:LH_ENTRY_AT
    movt    r0, #:upper16:LH_ENTRY_AT
    ldr     r1, [r0]
    movw    r2, #:lower16:LH_ENTRY_WORD
    movt    r2, #:upper16:LH_ENTRY_WORD
    cmp     r1, r2
    bne     1f
    movw    r0, #:lower16:LH_SITE
    movt    r0, #:upper16:LH_SITE
    movw    r1, #:lower16:LH_BL
    movt    r1, #:upper16:LH_BL
    str     r1, [r0]
    bl      s2_publish
1:
#endif
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, r9, r10, pc}

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
#ifdef LH_RESTORE
    bl      lh_record                   @ the original words, before they go
#endif

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

#ifdef SPLASH_FINISH
.Ls2_splash_finish:
#include "splash_finish.S"
#endif

#ifdef LH_RESTORE
/* --- is this destination journaled? ---------------------------------------
 * r0 = destination.  r3 = 1 if it is a firmware word outside the cave, else 0.
 * Clobbers ip only. */
lh_want:
    mov     r3, #0
    movw    ip, #0
    movt    ip, #0x4000
    cmp     r0, ip
    bxlo    lr                          @ a pool offset
    movw    ip, #:lower16:CAVE_LO
    movt    ip, #:upper16:CAVE_LO
    cmp     r0, ip
    blo     1f
    movw    ip, #:lower16:CAVE_HI
    movt    ip, #:upper16:CAVE_HI
    cmp     r0, ip
    bxlo    lr                          @ the cave
1:  mov     r3, #1
    bx      lr

/* --- block, journal, registration -----------------------------------------
 * Block X from the allocator (class 0, never freed):
 *     X+0   X-8        vtable pointer: the manager calls [vtbl+0xC] = [X+4]
 *     X+4   X+12       the routine
 *     X+8   journal    where the entries start
 *     X+12  lh_unhook, copied
 *     ...   journal:   { address, bytes, the original words }..., 0
 * The size is counted from the section table with the same test lh_record
 * uses, so the journal cannot outgrow the block. */
lh_setup:
    push    {r4, r5, r7, lr}
    ldr     r7, [r6, #4]                @ section count
    add     r5, r6, #16                 @ the table
    adr     r1, lh_unhook
    adr     r2, lh_unhook_end
    sub     r4, r2, r1
    add     r4, r4, #16                 @ the 12-byte header and the terminator
#ifdef LH_SPLASH
    add     r4, r4, #12                 @ one more entry: the paused DRAW word
#endif
1:  cmp     r7, #0
    beq     2f
    ldr     r0, [r5], #4
    ldr     r1, [r5], #4
    sub     r7, r7, #1
    bl      lh_want
    cmp     r3, #0
    beq     1b
    add     r1, r1, #3
    bic     r1, r1, #3
    add     r4, r4, r1
    add     r4, r4, #8
    b       1b

2:  mov     r5, sp
    bic     sp, sp, #7
    mov     r0, #0                      @ class 0, USER
    movw    r3, #:lower16:MEM_HEAP
    movt    r3, #:upper16:MEM_HEAP
    blx     r3
    cmp     r0, #0
    beq     9f
    mov     r1, r4
    mov     r2, #0
    mov     r3, #0
    mov     ip, #0
    push    {ip, lr}                    @ the fifth argument, and the alignment
    movw    r7, #:lower16:MEM_GET
    movt    r7, #:upper16:MEM_GET
    blx     r7
    add     sp, sp, #8
    cmp     r0, #0
    beq     9f                          @ refused: no journal, no hook

    mov     r4, r0                      @ X
    sub     r1, r4, #8
    str     r1, [r4]
    add     r1, r4, #12
    str     r1, [r4, #4]
    adr     r0, lh_unhook
    adr     r2, lh_unhook_end
3:  ldr     r3, [r0], #4
    str     r3, [r1], #4
    cmp     r0, r2
    blo     3b
    str     r1, [r4, #8]                @ the journal starts after the code
    mov     r3, #0
    str     r3, [r1]                    @ and is empty
    mov     r10, r1
#ifdef LH_MARK
    movw    r0, #:lower16:LH_MARK
    movt    r0, #:upper16:LH_MARK
    str     r4, [r0, #8]                @ debug: where the block is
#endif
    bl      s2_publish                  @ the routine is code now

    movw    r3, #:lower16:POFF_MGR
    movt    r3, #:upper16:POFF_MGR
    blx     r3
    mov     r1, r4
    mov     r2, #0                      @ the ordinary list
    movw    r3, #:lower16:POFF_ADD
    movt    r3, #:upper16:POFF_ADD
    blx     r3
    cmp     r0, #0
    moveq   r10, #0                     @ no slot: journal nothing, arm nothing
    beq     9f
    /* The forced list too: the manager runs it instead of the ordinary one on
     * its fast path.  Same as the USB gadget and gyro's s_poff. */
    movw    r3, #:lower16:POFF_MGR
    movt    r3, #:upper16:POFF_MGR
    blx     r3
    mov     r1, r4
    mov     r2, #1
    movw    r3, #:lower16:POFF_ADD
    movt    r3, #:upper16:POFF_ADD
    blx     r3
    mov     r9, r4                      @ registered: the hook may be armed

9:  mov     sp, r5
    pop     {r4, r5, r7, pc}

/* --- copy one section's original words into the journal -------------------
 * r0 = destination, r2 = bytes rounded up to a word.  Called from s2_place
 * just before the copy; r0-r2 come back as they went in.  The terminator is
 * written first and the address last, so a power-off in the middle of this
 * sees either the old journal or the new one, never half an entry. */
lh_record:
    cmp     r10, #0
    bxeq    lr
    push    {r0, r1, r2, lr}
    bl      lh_want
    cmp     r3, #0
    beq     2f
    add     ip, r10, #8
    mov     r1, #0
1:  cmp     r1, r2
    bhs     3f
    ldr     r3, [r0, r1]
    str     r3, [ip, r1]
    add     r1, r1, #4
    b       1b
3:  add     ip, ip, r2
    mov     r3, #0
    str     r3, [ip]
    str     r2, [r10, #4]
    str     r0, [r10]
    mov     r10, ip
2:  pop     {r0, r1, r2, pc}

/* --- the power-off routine: copied into the block, runs from there ---------
 * Called as vtbl[+0xC](obj, reason), from both lists, so possibly twice:
 * writing an original word back twice is harmless.  Position-independent: no
 * literal pool, every address a movw/movt. */
lh_unhook:
    push    {r4, r5, r6, lr}
    mov     r6, sp
    bic     sp, sp, #7
    ldr     r4, [r0, #8]                @ the journal
1:  ldr     r0, [r4]
    cmp     r0, #0
    beq     3f
    ldr     r2, [r4, #4]
    add     r4, r4, #8
2:  cmp     r2, #0
    beq     1b
    ldr     r3, [r4], #4
    str     r3, [r0], #4
    sub     r2, r2, #4
    b       2b
3:
#ifdef LH_MARK
    movw    r4, #:lower16:LH_MARK
    movt    r4, #:upper16:LH_MARK
    ldr     r1, [r4]
    add     r1, r1, #1
    str     r1, [r4]                    @ debug: times run
    movw    r3, #:lower16:F_TICK_US
    movt    r3, #:upper16:F_TICK_US
    blx     r3
    str     r0, [r4, #4]                @ debug: when
#endif
    movw    r3, #:lower16:F_DCACHE
    movt    r3, #:upper16:F_DCACHE
    blx     r3
    movw    r3, #:lower16:F_ICACHE
    movt    r3, #:upper16:F_ICACHE
    blx     r3
    mov     sp, r6
    pop     {r4, r5, r6, pc}
lh_unhook_end:

#ifdef LH_SPLASH
/* --- frame 0 and the redraw pause, for the loader hook path ---------------
 * Same as the AutoRun's FourBoxBar.start + first frame: pause the GUI redraw
 * (0xC0528700 = bx lr), publish, then paint FPSUPUI\0.BIN (1024x56, the whole
 * top row) into all three buffers.  The DRAW word goes through lh_record first,
 * so a power-off during the hold still puts the redraw back.  splash_finish
 * restores it itself when the hold ends. */
.equ S_DRAW,        0xC0528700
.equ S_PAUSED,      0xE12FFF1E           /* bx lr                               */
.equ S_OSDFILE,     0xC03E4270           /* display osdfile handler             */
lh_splash_pre:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r7, sp
    bic     sp, sp, #7
    movw    r5, #:lower16:S_DRAW
    movt    r5, #:upper16:S_DRAW
    ldr     r0, [r5]
    movw    r1, #:lower16:S_PAUSED
    movt    r1, #:upper16:S_PAUSED
    cmp     r0, r1
    beq     9f                          @ the AutoRun paused it: its path
0:  movw    r8, #:lower16:F_TICK_US     @ not before LH_BANNER_AT_US
    movt    r8, #:upper16:F_TICK_US
    blx     r8
    movw    r1, #:lower16:LH_BANNER_AT_US
    movt    r1, #:upper16:LH_BANNER_AT_US
    cmp     r0, r1
    bhs     1f
    mov     r0, #50
    movw    r8, #:lower16:0xC03705D8     @ native sleep(ms), yields
    movt    r8, #:upper16:0xC03705D8
    blx     r8
    b       0b
1:  mov     r0, r5
    mov     r2, #4
    bl      lh_record                   @ the stock word, for power-off (the
                                        @ block has room: see lh_setup)
    movw    r1, #:lower16:S_PAUSED
    movt    r1, #:upper16:S_PAUSED
    str     r1, [r5]
    bl      s2_publish
    sub     sp, sp, #32                 @ ctx + six argv, 8-aligned
    adr     r0, lsp_quiet
    str     r0, [sp]
    mov     r4, sp
    adr     r0, lsp_path
    str     r0, [sp, #4]
    adr     r0, lsp_zero
    str     r0, [sp, #8]
    str     r0, [sp, #12]
    adr     r0, lsp_w
    str     r0, [sp, #16]
    adr     r0, lsp_h
    str     r0, [sp, #20]
    adr     r0, lsp_zero
    str     r0, [sp, #24]
    mov     r6, #3
2:  mov     r0, r4
    mov     r1, #6
    add     r2, sp, #4
    movw    r8, #:lower16:S_OSDFILE
    movt    r8, #:upper16:S_OSDFILE
    blx     r8
    subs    r6, r6, #1
    bne     2b
9:  mov     sp, r7
    pop     {r4, r5, r6, r7, r8, pc}
lsp_quiet:
    mov     r0, #0
    bx      lr
lsp_path:   .asciz  "\\FPSUPUI\\0.BIN"
lsp_zero:   .asciz  "0"
lsp_w:      .asciz  "1024"
lsp_h:      .asciz  "56"
.balign 4

#endif

#ifdef LH_BANNER
/* --- the banner, drawn by calling the display handlers directly -----------
 * Not through the shell dispatcher: a command run from inside another does
 * not reach the screen (2026-09-19), but splash_finish.S calls a subcommand
 * handler directly and that does.  A handler is (ctx, argc, argv) with argv
 * starting after the subcommand name, and [ctx] is its printf.  Same sequence
 * as the AutoRun minus its clear: text + layer on, three times (three
 * buffers).  Calls go through r8, not ip (see the note at the
 * top of this block). */
.equ D_TEXT,    0xC03E4620           /* display text <string>               */
.equ D_OSD,     0xC03E3D00           /* display osd <on> [colour]           */
.equ D_SLEEP,   0xC03705D8           /* (ms): native sleep, yields          */
lh_banner:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r7, sp
    bic     sp, sp, #7
    /* Not before LH_BANNER_AT_US after power-on.  Drawn at 1.35 s it was wiped:
     * the display switches to the normal OSD at 1.56 s and the UI redraws after
     * that (measured 2026-09-25).  On the AutoRun path this is ~15 s already
     * and the loop does not run.  Sleeping yields; it holds up only the task
     * that called the loader hook. */
0:  movw    r8, #:lower16:F_TICK_US
    movt    r8, #:upper16:F_TICK_US
    blx     r8
    movw    r1, #:lower16:LH_BANNER_AT_US
    movt    r1, #:upper16:LH_BANNER_AT_US
    cmp     r0, r1
    bhs     3f
    mov     r0, #50
    movw    r8, #:lower16:D_SLEEP
    movt    r8, #:upper16:D_SLEEP
    blx     r8
    b       0b
3:
    sub     sp, sp, #16                 @ ctx, then two argv slots
    adr     r0, lb_quiet
    str     r0, [sp]
    mov     r4, sp
    /* No clear.  The AutoRun clears the layer (osd 1 0x00000000) to wipe its
     * progress bar; there is no bar here, and the clear took the camera's own
     * UI icons with it (seen 2026-09-25). */
    mov     r6, #3
2:  adr     r0, lb_text
    str     r0, [sp, #4]
    mov     r0, r4
    mov     r1, #1
    add     r2, sp, #4
    movw    r8, #:lower16:D_TEXT
    movt    r8, #:upper16:D_TEXT
    blx     r8
    adr     r0, lb_one
    str     r0, [sp, #4]
    mov     r0, r4
    mov     r1, #1
    add     r2, sp, #4
    movw    r8, #:lower16:D_OSD
    movt    r8, #:upper16:D_OSD
    blx     r8
    subs    r6, r6, #1
    bne     2b
#ifdef LH_MARK
    movw    r8, #:lower16:F_TICK_US
    movt    r8, #:upper16:F_TICK_US
    blx     r8
    movw    r1, #:lower16:LH_MARK
    movt    r1, #:upper16:LH_MARK
    str     r0, [r1, #12]               @ debug: the banner calls returned
#endif
    mov     sp, r7
    pop     {r4, r5, r6, r7, r8, pc}
lb_quiet:
    mov     r0, #0
    bx      lr
lb_one:     .asciz  "1"
lb_text:    .asciz  LH_BANNER_TEXT
.balign 4
#endif
#endif
