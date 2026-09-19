.syntax unified
.arm
.text
/* ============================================================================
 * abort -- stop the AutoRun interpreter, as the borrowed `echo` handler.
 * ============================================================================
 *
 * This used to live inside loader.S, and the loader is the one thing that has
 * to fit in the settings block: 468 bytes, of which this was 128.  Out here it
 * is a section of fpSup.BIN placed at a fixed address in the cave, which costs
 * the AutoRun nothing and gives the store back a quarter of its space.
 *
 * WHO ARMS IT.  stage2 does, once every section is placed and the payload's
 * entry has returned -- the first moment anything can honestly say the load
 * finished.  The loader used to arm it on its way out, which was earlier than
 * that and had to be gated on a handshake word to avoid arming on a boot that
 * had not loaded from the store.  stage2 needs no gate: it only ever runs
 * after a successful read.
 *
 * WHAT IT OWES.  The interpreter's teardown at 0xC03DA700 does three things --
 * close the script's file, pop the registration, clear the running byte -- and
 * it does the last two only while that byte is still set.  Clearing the byte
 * is how the script is stopped, so whoever clears it owes all three.  All
 * three are here.  The close was missing for a day, and the symptom was that
 * \AutoRun.txt could not be opened afterwards by anything -- so the card that
 * would have fixed it was the one file that could not be replaced.
 * ========================================================================== */

.equ AR_TABLE,  0xC2F20FC0      /* registration table; depth at +0x21C        */
.equ AR_LINEFN, 0xC03DA7A8      /* the script's per-line callback: how its own
                                 * entry is told apart from anyone else's     */
.equ AR_POP,    0xC0420D90      /* pop the entry, depth -= 1                  */
.equ AR_DEPTH,  0x21C
.equ AR_CTX,    0x0C
.equ AR_RUNNING, 0x90           /* u8: the reader answers EOF once it is zero */
.equ AR_FOBJ,   0x94            /* the script's own file object, or zero      */
.equ F_CLOSE,   0xC0366020      /* close(fileobj) -- the loader's own close   */

/* ECHO_SLOT and ECHO_ORIG are passed in: the same two values build_autorun
 * writes into the script, so they cannot disagree with it. */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

    .global entry
entry:                                  /* (ctx, argc, argv), return ignored */
    /* Put the handler back BEFORE stopping the script: the three commands that
     * would have done it are among the ones about to be skipped.  We are
     * inside that handler, and writing the slot we were reached through is
     * safe -- the return address is already in lr. */
    push    {r4, lr}
    LDA     r0, ECHO_ORIG
    LDA     r1, ECHO_SLOT
    str     r0, [r1]

    /* Find the script's context by walking the registration table for the
     * entry whose per-line callback is the interpreter's.  Taking the top of
     * the stack instead would pick the wrong one under a nested script. */
    LDA     r0, AR_TABLE
    LDA     ip, AR_LINEFN
    ldr     r1, [r0, #AR_DEPTH]
4:  cmp     r1, #1
    blt     5f
    add     r2, r0, r1, lsl #5          @ entry = table + depth * 36
    add     r2, r2, r1, lsl #2
    ldr     r3, [r2, #4]
    cmp     r3, ip
    beq     3f
    subs    r1, r1, #1
    b       4b

3:  ldr     r4, [r2, #AR_CTX]
    cmp     r4, #0
    beq     5f

    /* Close the script's file.
     *
     * The teardown does three things and this routine prevents all three, so
     * it owes all three.  Two of them were obvious because their absence was
     * loud: the pop, without which the registration depth never returns to
     * zero and the USB shell's replies go nowhere.  The close was not, because
     * its symptom is quiet and arrives later -- \AutoRun.txt cannot be opened
     * afterwards, by anything, read or write, until the camera is power
     * cycled.  Every other file on the card opens fine, which is what makes it
     * look like something other than an open handle.
     *
     * It cost a day: the card that would have fixed it was the one file that
     * could not be replaced.
     *
     * The rule, stated properly: whoever stops the teardown owes everything
     * the teardown does, not the part whose absence shouts. */
    ldr     r0, [r4, #AR_FOBJ]
    cmp     r0, #0
    beq     2f
    LDA     r3, F_CLOSE
    blx     r3
    mov     r3, #0
    str     r3, [r4, #AR_FOBJ]          @ as the teardown leaves it.  NOT a
                                        @ destructor: the interpreter allocated
                                        @ the object and still owns it

2:  /* Pop first, clear second.  The teardown pops only while the byte is set,
     * so doing it the other way round loses the pop. */
    LDA     r3, AR_POP
    blx     r3
    mov     r3, #0
    strb    r3, [r4, #AR_RUNNING]

5:  mov     r0, #0
    pop     {r4, pc}
