.syntax unified
.arm
.text
/* ============================================================================
 * loader — read the code off the card instead of spelling it out.
 * ============================================================================
 *
 * The AutoRun is five hundred commands and four hundred of them are `mem set`,
 * one word each, writing fifteen hundred bytes of worker. The progress bar
 * exists only because that is slow: without it the readout sits at ninety per
 * cent through several hundred silent commands and looks exactly like a stall.
 * Adding the gyro logger to the same file would cost eight hundred more.
 *
 * There is no `mem load` -- the shell can save memory to a file but not the
 * other way -- so the AutoRun cannot ask for this. It can spell out something
 * small that does the asking, and that is this: about ninety commands, and the
 * count no longer grows with what is being loaded.
 *
 * Runs in place of the worker's own bootstrap, called once from the borrowed
 * `echo` handler, and after loading it does not start the worker in a new task -- it becomes
 * the worker, by branching to the entry the file names. One task, and nothing
 * left parked with nowhere to return to.
 *
 *     \fpSup.BIN
 *      +0x00  "VBIN"
 *      +0x04  section count
 *      +0x08  entry, an absolute address to branch to when everything is placed
 *      +0x0C  total bytes of section data that follow the table
 *      +0x10  the table: { destination, length } per section
 *             then the data, in the same order, each section 4-byte aligned
 *
 * The magic is checked before anything is copied and before the branch. A file
 * that is missing or truncated leaves the camera exactly as it was, minus the
 * shell -- which is the failure that matters, because there is no shell left to
 * repair it with. That is the price of two files instead of one.
 * ========================================================================== */

.equ HOOK_SITE,   0xC00D0794

/* The allocator, the way gyro's writer and heapalloc.S use it -- the
 * descriptor form, whose four arguments all fit in registers.  Class 0 is
 * USER, which is where `memmgr bufmem get` was taking this same megabyte from;
 * NOT class 10, which is RAW, the CinemaDNG frame buffer, and the allocation
 * whose failure is what froze movRec for a week. */
.equ H_GET,       0xC001D740    /* (desc, class, size, 0)                   */
.equ H_ADDR,      0xC001D7F0    /* (desc) -> address                        */
.equ H_FREE,      0xC001D7A0    /* (desc, 2)                                */
.equ POOL_CLASS,  0            /* USER                                      */
/* 64 KiB, and it is STAGING, not a pool.
 *
 * This was a megabyte, held for the life of the camera, and every card got one
 * whether it wanted it or not: og3k and og2k never read a byte of it.  What the
 * loader actually needs is somewhere to put a file that is padded to 32 KiB and
 * the file object that reads it -- so it asks for that, and gives it back on the
 * way out.  A payload that needs memory asks the allocator itself, in its entry,
 * and stage2 places the sections that are offsets into it afterwards. */
.equ POOL_BYTES,  0x10000
.equ O_FOBJ,      0x0000        /* the file object, about 3 KiB             */
.equ O_BUF,       0x1000        /* the file: 32 KiB of it, BIN_PAD          */
.equ MAXLEN,      0xF000        /* what is left of the buffer past O_BUF --
                                 * ask for more than the file can be, but
                                 * never for more than there is room for   */

.equ F_MGR,       0xC0444658
.equ F_VOL,       0xC0444698
.equ F_CTOR,      0xC0365E90
.equ F_OPEN,      0xC0365FB0
.equ F_READ,      0xC0366060
.equ F_CLOSE,     0xC0366020
.equ F_DTOR,      0xC0365ED0
.equ F_CACHE,     0xC000E91C

.equ VOL_SD,      1             /* FUN_c0444698: 1 = the card, 5 = an SSD */

.equ MAGIC,       0x4E494256    /* "VBIN" */
/* Pops the AutoRun's registration entry and decrements the depth at
 * 0xC2F20FC0+0x21C.  The interpreter's own teardown calls it -- but ONLY when
 * [ctx+0x90] is non-zero, and zeroing that byte is how the script is stopped.
 * So stopping the script the obvious way also skips the pop, the entry stays
 * registered, the depth never returns to zero, and the camera goes on thinking
 * a script is running.  The USB shell never comes up after that: the worker is
 * alive and its replies go nowhere.  Cost of the fix: one word. */
.equ AR_POP,      0xC0420D90


.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* A call to a firmware routine, in one word instead of three.
 *
 * `bl` reaches anything within 32 MB and every entry point here is about seven
 * away, but the assembler lays this file out at zero and has no idea where it
 * will be copied, so the offset is worked out here from LOADER_BASE (passed in
 * by build_autorun) and the distance from the file's first byte.  A label
 * minus a label is a constant the assembler can fold; the dot on its own is
 * not, which is why the position comes from `9b - _lstart` rather than from
 * `.`.  Sixteen words saved is a second off every boot, because each word the
 * AutoRun has to spell out costs a `mem set` and about sixty milliseconds.
 *
 * ARM targets only: the displaced callback is Thumb and still needs BLX. */
.macro CALL target
9:  .word 0xEB000000 + ((((\target) - (LOADER_BASE + (9b - _lstart)) - 8) >> 2) & 0xFFFFFF)
.endm

/* --- the borrowed echo handler: called once, by the AutoRun ----------------
 *
 * This used to sit in the gyro callback at 0xC00D0794, and everything odd about
 * the block below was that address's doing: the site holds a BLX, so the first
 * thing here had to be a call to the routine it displaced and a place to keep
 * that routine's return value; the callback fires at 50-90 Hz, so a word had to
 * be spent proving this had not already run; and because the file read takes
 * longer than the gap between two callbacks, the firmware's word had to go back
 * before the read rather than after it.  Three mechanisms, all of them paying
 * for the choice of site rather than doing any work.
 *
 * The AutoRun cannot call -- but it can point the `echo` handler at an address,
 * say `echo`, and put the handler back, which is what --boot-call has done for
 * one-shot routines all along.  That gives this: called once because the
 * AutoRun says so, in the shell dispatcher's own task where a file read is an
 * ordinary thing to do, at a point in the boot the AutoRun chooses rather than
 * whenever the IMU next ticks.
 *
 * The gyro callback is the logger's now, and only the logger's.
 *
 * Handler signature is (ctx, argc, argv) and [ctx] is a printf; nothing here
 * uses it, and the return value is ignored, so this returns zero. */
.global boot
_lstart:
boot:
    /* There was a task here.  The shell build used to create one and run `load`
     * inside it, so that `load_stop` could sit still instead of returning --
     * and the reason turned out to be nothing: worker.S's own bootstrap calls
     * tk_cre_tsk itself, from the gyro callback, and always did.  The loader
     * was creating a task for a payload that creates its own.
     *
     * Twenty-four words, and they were the last thing that made a shell card's
     * AutoRun different from a release card's. */
    b       load

load:
    /* r9 carries the descriptor's address all the way to the free at the end.
     * Two registers more in the push costs nothing -- it is one instruction
     * either way -- and it saves the movw/movt pair that reloading the address
     * down there would take.  The loader is 468 bytes and the store holds 468,
     * so a spare word is not a nicety here. */
    push    {r4, r5, r6, r7, r8, r9, r10, lr}


    /* Ask for the staging buffer here instead of having the AutoRun ask.
     *
     * `memmgr bufmem get` was one line of script, but it was the script's line:
     * the AutoRun had to run it, in the right order, before anything that
     * needed it.  The loader needs it, so the loader asks -- and the answer
     * still goes to 0xC3757A7C, because the worker, stage2 and every gyro
     * source read it from there.
     *
     * The descriptor is sixteen bytes of cave scratch that has to outlive the
     * call: the address is read out of it afterwards.  It sits above the worker
     * and below STORE_FROM; build_autorun refuses a worker that reaches it. */
    movw    r9, #:lower16:POOL_DESC
    movt    r9, #:upper16:POOL_DESC
    mov     r0, r9
    mov     r1, #POOL_CLASS
    mov     r2, #POOL_BYTES
    mov     r3, #0
    CALL    H_GET
    mov     r0, r9
    CALL    H_ADDR
    cmp     r0, #0
    beq     load_fail                   @ refused: place nothing rather than
    mov     r4, r0                      @ stage a file at address zero
    /* 0xC3757A7C is NOT written here any more.  It is where everything reads a
     * pool address from, and what it holds now is whatever the payload's entry
     * published -- the worker's, the logger's -- not a buffer that is about to
     * be handed back. */
    add     r5, r4, #O_FOBJ             @ file object scratch
    add     r6, r4, #O_BUF

    /* Keep the firmware's normal media-manager initialisation in the boot path:
     * skipping these calls was the only loader-side change in the first native
     * test that froze at 90%.
     *
     * But F_VOL names the volume the camera is CURRENTLY pointed at, and with
     * an external SSD plugged in that is the SSD -- which does not have
     * \fpSup.BIN on it.  The card boots, the AutoRun runs, the loader opens
     * nothing, and the camera ends up with no logger at all: every take that
     * session is missing its sidecars, with no sign that anything is wrong.
     * With a shell in the build it is worse -- load_stop spins and the progress
     * bar stops at 90.
     *
     * That is the whole of the "intermittent" SSD fault: an SSD attached BEFORE
     * boot, every time; attached after the banner, never.  Reproduced on cold
     * boots repeatedly.
     *
     * So: whatever F_VOL says first, then the card.  The card is where AutoRun
     * was read from, so it is where fpSup.BIN is. */
    CALL    F_MGR
    mov     r1, #0
    CALL    F_VOL
    mov     r7, r0

1:  mov     r1, r7
    mov     r0, r5
    CALL    F_CTOR

    mov     r0, r5
    adr     r1, path
    mov     r2, #1
    CALL    F_OPEN
    cmp     r0, #0
    bne     2f

    /* Give the object back before trying again: a file object left constructed
     * after a failed open makes every later open fail too. */
    mov     r0, r5
    mov     r1, #2
    CALL    F_DTOR
    cmp     r7, #VOL_SD
    beq     load_stop                   @ that was the card: there is no file
    mov     r7, #VOL_SD
    b       1b

2:  mov     r0, r5
    mov     r1, r6
    mov     r2, #MAXLEN                 @ 0x20000 = 2 ror 8, one word not two
    mov     r3, #0
    CALL    F_READ

    mov     r0, r5
    CALL    F_CLOSE

load_shut:
    mov     r0, r5
    mov     r1, #2
    CALL    F_DTOR

    ldr     r0, [r6]                    @ nothing runs until the file says it is
    LDA     r1, MAGIC                   @ the right file
    cmp     r0, r1
    bne     load_stop

    /* The rest of the loading travels in the file, as its first section, and is
     * therefore free: every word spelled out here costs the AutoRun one
     * `mem set` and about sixty milliseconds of boot.  Clean the cache first --
     * the buffer holds instructions now -- then hand it the buffer.  It places
     * every section, cleans the cache again, and comes back, unless the file
     * names an entry, which is how the debug build's worker takes the task. */

    CALL    F_CACHE
    ldr     r1, [r6, #4]                @ section count
    add     r1, r6, r1, lsl #3
    add     r1, r1, #16                 @ past the table: the first section's data
    mov     r0, r6
    blx     r1


/* Nothing was placed: leave the camera exactly as it was, minus the shell.
 * The debug build reaches this from its own task, and returning from a task
 * entry is undefined here -- tk_ext_tsk is not in the syscall table -- so it
 * sits still instead. */
load_stop:
    /* Hand the staging buffer back.  stage2 ran from inside it and has
     * returned, the payload's entry has been called and has returned, and the
     * sections that were offsets into the payload's own pool are placed -- so
     * nothing of ours is left in here.
     *
     * Reached only from below the allocation; `load_fail` is the path for a
     * refusal, because freeing a descriptor that never held anything is not a
     * no-op. */
    mov     r0, r9
    mov     r1, #2
    CALL    H_FREE
load_fail:
    pop     {r4, r5, r6, r7, r8, r9, r10, pc}



path:
    .asciz  "\\fpSup.BIN"
    .align  2


