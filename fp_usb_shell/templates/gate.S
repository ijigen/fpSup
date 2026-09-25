.syntax unified
.arm
.text
.global gate
/* ============================================================================
 * gate -- warm-boot minimal test (2026-09-25).  NOT a product.
 * ============================================================================
 *
 * The power switch is a warm restart: the firmware image and the cave survive
 * it (fpSup/HOOKS_AT_POWER_OFF.md, "What survives a restart").  So a word the
 * AutoRun patches into the image is still there on the next boot -- including
 * the one place the firmware starts the AutoRun:
 *
 *     0xC03DA420  bl 0xC03DA758        ; ("\AutoRun.txt", 1), word 0xEB0000CC
 *
 * warm_gate_card.py points that call here.  On the next warm boot:
 *
 *   1. (only with ONE_SHOT) put the original word back first, so the boot
 *      after this one is stock whatever happens below,
 *   2. call the loader that is still sitting at CAVE_LOW, the same way the
 *      AutoRun's `echo` does,
 *   3. if stage2 ran (it stamps LOAD_DONE_US, which is cleared first), return
 *      without starting the AutoRun at all; otherwise start it as normal.
 *
 * Immediates only -- no literal pool, no pc-relative loads -- so the words mean
 * the same thing wherever they are copied.
 *
 * Marker block at MARK, for the host to read afterwards:
 *   +0x0  times the gate ran since the card installed it
 *   +0x4  TICK_US at gate entry
 *   +0x8  TICK_US after the loader returned
 *   +0xC  1 = loaded, AutoRun skipped;  2 = loader failed, AutoRun started
 * ========================================================================== */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.equ SITE,       0xC03DA420
.equ SITE_ORIG,  0xEB0000CC
.equ AUTORUN,    0xC03DA758
.equ F_DCACHE,   0xC000E91C
.equ F_ICACHE,   0xC000EABC
.equ F_TICK_US,  0xC002B6E0
/* LOADER, LOAD_DONE and MARK are passed in by warm_gate_card.py */

gate:
    push    {r0, r1, r4, r5, r6, lr}    @ r0/r1 are the AutoRun's arguments
    mov     r6, sp                      @ r6 is callee-saved: survives every call
    bic     sp, sp, #7

#ifdef ONE_SHOT
    /* 1. disarm, before anything that could fail.  Off by default since
     *    2026-09-25: a one-shot gate makes every other warm boot slow, and a
     *    slow boot then cannot be told apart from a cold one. */
    LDA     r4, SITE
    LDA     r5, SITE_ORIG
    str     r5, [r4]
    LDA     ip, F_DCACHE
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip
#endif

    LDA     r4, MARK
    ldr     r0, [r4]
    add     r0, r0, #1
    str     r0, [r4]
    LDA     ip, F_TICK_US
    blx     ip
    str     r0, [r4, #4]

    /* 2. the loader.  LOAD_DONE survives the restart too, so clear it: only a
     *    stage2 that runs on THIS boot may set it. */
    LDA     r5, LOAD_DONE
    mov     r0, #0
    str     r0, [r5]
    mov     r1, #0
    mov     r2, #0
    LDA     ip, LOADER
    blx     ip

    LDA     ip, F_TICK_US
    blx     ip
    str     r0, [r4, #8]

    /* 3. decide */
    ldr     r0, [r5]
    cmp     r0, #0
    moveq   r1, #2
    movne   r1, #1
    str     r1, [r4, #12]
    mov     sp, r6                      @ flags untouched
    pop     {r0, r1, r4, r5, r6, lr}
    movne   r0, #0
    bxne    lr                          @ loaded: the AutoRun never starts
    LDA     ip, AUTORUN
    bx      ip                          @ tail call, lr = 0xC03DA424
