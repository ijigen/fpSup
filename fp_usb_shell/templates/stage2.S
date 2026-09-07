.syntax unified
.arm
.text
.global stage2

.equ FRAMEBUF, 0xC3757A7C           /* [0] = the camera's DMA pool */

/* The second half of the loader, carried in \VSHL.BIN instead of spelled out.
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
 * Returns to the first half, or -- when the file names an entry, which is what
 * the debug build's worker does -- branches there and never comes back. */
stage2:
    push    {r4, r5, r6, r7, r8, lr}   @ an even count: the firmware LDRDs need 8-byte alignment
    mov     r6, r0
    ldr     r7, [r6, #4]                @ section count
    add     r5, r6, #16                 @ the table
    add     r4, r5, r7, lsl #3          @ the data begins past it
s2_place:
    cmp     r7, #0
    beq     s2_done
    ldr     r0, [r5], #4                @ destination
    ldr     r1, [r5], #4                @ length
    add     r2, r1, #3
    bic     r2, r2, #3                  @ each section starts on a word
    cmp     r0, #0
    beq     s2_next                     @ destination zero: this code itself

    /* A destination below the firmware's address space is an OFFSET into the
     * camera's DMA pool.  The pool is where code too big for the cave has to
     * live, and its address is decided at boot, so a build cannot name it --
     * but it can name an offset, and this is where the two meet.  Firmware
     * destinations are all 0xC0000000 and above, so the two can never be
     * confused. */
    movw    r3, #0
    movt    r3, #0x4000                 @ 0x40000000
    cmp     r0, r3
    bhs     1f
    movw    r3, #:lower16:FRAMEBUF
    movt    r3, #:upper16:FRAMEBUF
    ldr     r3, [r3]
    cmp     r3, #0
    beq     s2_next                     @ no pool: place nothing rather than
    add     r0, r0, r3                  @ write to a low address

1:  subs    r1, r1, #4
    ldrge   r3, [r4, r1]
    strge   r3, [r0, r1]
    bgt     1b
s2_next:
    add     r4, r4, r2
    sub     r7, r7, #1
    b       s2_place
s2_done:
    movw    ip, #:lower16:0xC000E91C    @ cache maintenance, so the placed code
    movt    ip, #:upper16:0xC000E91C    @ is really at its address
    blx     ip
    ldr     r0, [r6, #8]                @ entry, or zero
    cmp     r0, #0
    popeq   {r4, r5, r6, r7, r8, pc}
    pop     {r4, r5, r6, r7, r8, lr}
    bx      r0
