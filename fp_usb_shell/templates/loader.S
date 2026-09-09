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
 * Runs in place of the worker's own bootstrap, from the same borrowed callback,
 * and after loading it does not start the worker in a new task -- it becomes
 * the worker, by branching to the entry the file names. One task, and nothing
 * left parked with nowhere to return to.
 *
 *     \VSHL.BIN
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

.equ CLAIM,       0x4E49424C    /* "LBIN" */

.equ HOOK_SITE,   0xC00D0794
.equ HOOK_ORIG,   0xFA046FD7
.equ HOOK_TARGET, 0xC01EC6F9

.equ FRAMEBUF,    0xC3757A7C    /* [0] = the DMA pool */
.equ O_FOBJ,      0x7000        /* clear of the frame and capture buffers */
.equ O_BUF,       0x8000
.equ MAXLEN,      0x20000       /* ask for more than the file can be */

.equ F_MGR,       0xC0444658
.equ F_VOL,       0xC0444698
.equ F_CTOR,      0xC0365E90
.equ F_OPEN,      0xC0365FB0
.equ F_READ,      0xC0366060
.equ F_CLOSE,     0xC0366020
.equ F_DTOR,      0xC0365ED0
.equ F_CACHE,     0xC000E91C

.equ FN_CRETSK,   0xC0016A58
.equ FN_STATSK,   0xC0016BC0
.equ VOL_SD,      1             /* FUN_c0444698: 1 = the card, 5 = an SSD */
.equ TASK_PRIO,   28
.equ TASK_STACK,  0x2000

.equ MAGIC,       0x4E494256    /* "VBIN" */

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

/* --- the hook site: run once, make a task, put the callback back ----------- */
.global boot
_lstart:
boot:
    push    {r4, r5, r6, lr}
    LDA     r12, HOOK_TARGET
    blx     r12
    mov     r4, r0                      @ the displaced call's return value

    /* Run once. The word is the loader's own, not a spare one in the worker's
     * state block -- the first attempt borrowed 0xC072F03C, which the worker
     * clears on every successful reply, so the guard was gone within a
     * millisecond of the worker starting and a second callback would have run
     * the whole thing again. */
    adr     r5, claim
    ldr     r0, [r5]
    LDA     r1, CLAIM
    cmp     r0, r1
    beq     boot_done
    str     r1, [r5]

    LDA     r0, HOOK_SITE               @ and put the callback back straight
    LDA     r1, HOOK_ORIG               @ away: the file read below takes long
    str     r1, [r0]                    @ enough for this to fire again

#ifdef NOTASK
    /* No task. The read below happens inside the gyro callback, once, at boot,
     * with nothing recording -- the only cost is that one drain of the sample
     * ring arrives late, and the ring holds 240 ms. A task here would cost 26
     * words of loader, which is 26 `mem set` commands the AutoRun has to spend
     * before the camera is usable. */
    bl      load
    b       boot_done
#else
    sub     sp, sp, #32
    mov     r0, #0
    str     r0, [sp]                    @ exinf
    mov     r0, #0x41
    str     r0, [sp, #4]                @ tskatr
    adr     r0, load
    str     r0, [sp, #8]
    mov     r0, #TASK_PRIO
    str     r0, [sp, #12]
    movw    r0, #TASK_STACK
    str     r0, [sp, #16]
    LDA     r0, 0x4441534C              @ dsname "LSAD" -- loader
    str     r0, [sp, #20]
    movw    r0, #0x0052                 @ "R"
    str     r0, [sp, #24]
    mov     r0, #0
    str     r0, [sp, #28]
    mov     r0, sp
    CALL    FN_CRETSK
    add     sp, sp, #32
    cmp     r0, #0
    ble     boot_done
    mov     r1, #0
    CALL    FN_STATSK
#endif

boot_done:
    mov     r0, r4
    pop     {r4, r5, r6, pc}

/* --- the task: read the file, place what it says, become it ---------------- */
load:
    push    {r4, r5, r6, r7, r8, lr}

    LDA     r0, FRAMEBUF
    ldr     r4, [r0]                    @ pool
    movw    r0, #O_FOBJ
    add     r5, r4, r0                  @ file object scratch
    movw    r0, #O_BUF
    add     r6, r4, r0                  @ where the file lands

    /* Keep the firmware's normal media-manager initialisation in the boot path:
     * skipping these calls was the only loader-side change in the first native
     * test that froze at 90%.
     *
     * But F_VOL names the volume the camera is CURRENTLY pointed at, and with
     * an external SSD plugged in that is the SSD -- which does not have
     * \VSHL.BIN on it.  The card boots, the AutoRun runs, the loader opens
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
     * was read from, so it is where VSHL.BIN is. */
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
    LDA     r2, MAXLEN
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
#ifdef HOOK_RESTORE
    /* Hand the callback to the worker, now that everything is placed.
     *
     * The loader and the USB shell both start themselves from this one word,
     * and for a long time that meant a card could have a logger or a shell but
     * never both -- the loader's branch was the one written, so the worker sat
     * at its address with nothing ever calling it.  A card that records and
     * cannot be asked anything is exactly the card you want when a fault only
     * happens on a card.
     *
     * Here, not at the early restore above: the worker must not start while
     * the file is still being read.  Both exits pass through, so a load that
     * placed nothing still leaves a shell to find out why with. */
    LDA     r0, HOOK_SITE
    LDA     r1, HOOK_RESTORE
    str     r1, [r0]
#endif
#ifdef NOTASK
    pop     {r4, r5, r6, r7, r8, pc}
#else
1:  b       1b
#endif

claim:
    .word   0

path:
    .asciz  "\\VSHL.BIN"
    .align  2
