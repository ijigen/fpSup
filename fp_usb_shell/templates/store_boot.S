.syntax unified
.arm
.text
/* ============================================================================
 * store_boot -- run the loader out of the settings block instead of spelling
 * it out.
 * ============================================================================
 *
 * The AutoRun's expensive part is seventy-six `mem set` commands writing three
 * hundred and four bytes of loader into the cave, one word each, about sixty-
 * five milliseconds apiece.  The loader exists precisely so the count stops
 * growing with the payload; this is the same trick applied to the loader
 * itself.
 *
 * XC_CommonSaveData at 0xC307523C is 0x410 bytes of settings, flash-backed:
 * written into its free space, a value comes back after a power cycle with no
 * save command given.  Measured 2026-09-17 -- 206 of 207 words survived, the
 * one exception being a u16 field at +0x024 that the firmware owns.  See
 * research/firmware/notes/PERSISTENT_STORE_COMMONSAVE.md.
 *
 * So the loader lives there, and the AutoRun carries only this: check the
 * header, checksum the body, copy it into the cave, publish it to the caches,
 * and branch.  Thirty-odd words instead of seventy-six.
 *
 * WHY IT VERIFIES BEFORE IT BRANCHES.  Those bytes are free today.  They belong
 * to a settings block whose unused fields may stop being unused -- a feature
 * nobody on this camera has triggered, a firmware that ships later.  A wrong
 * word here is not a wrong setting, it is a branch into whatever the bytes
 * happen to spell, at boot, with no shell to recover with.  Magic, length and
 * a sum of the body, and any of them failing means this does nothing at all:
 * it returns, the rest of the AutoRun runs, and the camera loads the slow way.
 * The worst case is the boot time we have today.
 *
 *     store layout, at STORE:
 *       +0x00  magic   'fpLD'
 *       +0x04  body    the loader, verbatim, to be copied to CAVE_LOW
 *
 * There was a sixteen-byte header here -- magic, version, length, sum -- and
 * three of those four fields are gone.
 *
 * LENGTH is now baked in at build time instead of read out of the store.  A
 * length read from the thing being checked is a length that can be garbage,
 * and the copy loop below runs it: a wrong one writes past the cave, through
 * the payload and the worker, for as far as the number says.  The `cmp
 * #STORE_MAX` that used to guard that is not a guard we need if the number
 * cannot be wrong in the first place.
 *
 * SUM and VERSION are gone because the check that matters moved.  A checksum
 * computed HERE, against a value baked into THIS build, is what caught a stale
 * store -- and that job now belongs to the loader, which compares the card's
 * declared version against its own.  Doing it there rather than here is not a
 * saving of five instructions, it is the difference between a check the store
 * can satisfy by being self-consistent and a check whose reference comes from
 * outside.  See loader.S.
 *
 * What is left here is the one question the loader cannot answer, because
 * answering it is what lets the loader run at all: is there anything of ours
 * in this block?  On a camera that has never been seeded those bytes are the
 * camera's own settings, and branching into them is not recoverable at boot.
 * ========================================================================== */

.equ STORE,       0xC3075264    /* 0xC307523C + 0x28 -- past the u16 the       */
                                /* firmware clears at +0x024                   */
/* STORE_LEN is passed in, never written here: build_autorun assembles the
 * loader, measures it, and refuses to emit a card whose loader would not fit.
 * The first card carried a length in this file AND in build_autorun, they
 * disagreed, and every boot failed silently -- the same constant in two
 * places, which is the trap our own notes warn about. */
/* STORE_MAGIC is passed in, and it is a hash of the loader's own bytes.
 *
 * It started as the string 'fpLD', then 'fpL2' when the header shrank -- and
 * that is exactly the trap.  A constant string has to be bumped BY HAND every
 * time the loader changes, and in one night the loader changed four times
 * while the string sat still.  Any of those four builds would have found a
 * store whose magic matched, copied STORE_LEN bytes out of a body that was a
 * different length, and branched into the result.
 *
 * Deriving it from the bytes makes that state unreachable: change the loader by
 * one instruction and the magic changes with it, the store stops matching, and
 * the card falls back to spelling the loader out and republishing.  It is also
 * why nothing downstream needs a version field -- the magic IS the version, and
 * unlike a check inside the loader it is answered BEFORE the branch. */
.equ CAVE_LOW,    0xC072DE64    /* where the loader runs, as build_autorun     */
                                /* assembled it -- its CALL macro is baked to  */
                                /* this address, so it cannot run anywhere else */
/* This code must NOT live at CAVE_LOW: it copies the loader there, and the
 * first draft overwrote itself mid-loop.  0xC072F700 is the cave's scratch,
 * above the payload and above the shell's worker (which ends at 0xC072F698). */
.equ BOOT_AT,     0xC072F700

/* The loader publishes itself into the store on the boot it was spelled out,
 * and must NOT do it again on every boot afterwards -- this is flash.  Setting
 * this word is how it knows: the cave is zeroed at boot, so a one here can only
 * have come from the code below. */
.equ STORE_FROM,  0xC072F6F8

.equ F_DCACHE,    0xC000E91C
.equ F_ICACHE,    0xC000EABC

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

    .global _start
_start:                                 /* runs as the borrowed echo handler:
                                         * (ctx, argc, argv), return ignored */
/* Six constants, and a movw/movt pair each would be twelve words -- twelve
 * `mem set` commands, about sixty-five milliseconds apiece.  A literal pool
 * plus two `ldmia` is eight, and the pool is read on both sides of the cache
 * calls because 0xC000E91C pushes r4-r7 and pops them again, while 0xC000EABC
 * is five instructions that touch only r0.  Both leave lr alone; it is `blx`
 * itself that costs us lr, which is why it is still pushed.
 *
 * `add rX, pc, #(label - label)` rather than `adr`: a label minus a label is a
 * constant the assembler folds, and this assembler resolves only R_ARM_CALL
 * and pc-relative literal loads.  The same idiom the loader's CALL macro uses. */
    push    {r4-r7, lr}
8:  add     r7, pc, #(0f - 8b - 8)
    ldmia   r7!, {r4, r5, r6}           @ STORE, STORE_MAGIC, CAVE_LOW

    ldr     r0, [r4]
    cmp     r0, r5
    bne     9f                          @ not ours: leave everything alone

    /* Copy.  Nothing is verified beyond the magic, and nothing needs to be: a
     * copy that turns out to be the wrong loader is harmless here, because the
     * loader checks its own version against the card's before it places
     * anything, and a copy that turns out to be rubbish is harmless because the
     * rest of the AutoRun writes the real loader straight over it.  Only the
     * BRANCH was ever worth gating, and the magic gates it. */
    add     r1, r4, #4                  @ src
    mov     r2, r6                      @ dst
    movw    r5, #:lower16:STORE_LEN     @ baked, never read from the store
1:  ldr     ip, [r1], #4
    str     ip, [r2], #4
    subs    r5, r5, #4
    bne     1b

    /* Publish before branching: written words are data to the caches until
     * 0xC000E91C runs, and the I-cache may still hold what used to be here.
     * r6 carries CAVE_LOW across both calls -- see the note above. */
    ldmia   r7, {r4, r5, r7}            @ F_DCACHE, F_ICACHE, STORE_FROM
    blx     r4
    blx     r5

    mov     r0, #1                      @ tell the loader the store is current,
    str     r0, [r7]                    @ so it does not rewrite flash

    mov     r0, r6
    pop     {r4-r7, lr}
    bx      r0                          @ tail into the loader, in the echo
                                        @ handler's context, which is what it
                                        @ was built for

9:  mov     r0, #0                      @ "nothing happened" -- the AutoRun
    pop     {r4-r7, pc}                 @ carries on and loads the slow way

    .align  2
0:  .word   STORE
    .word   STORE_MAGIC
    .word   CAVE_LOW
    .word   F_DCACHE
    .word   F_ICACHE
    .word   STORE_FROM
