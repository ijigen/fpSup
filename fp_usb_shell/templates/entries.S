.syntax unified
.arm
.text
.global entry
/* ============================================================================
 * entries -- call every payload's entry, when a card carries more than one.
 * ============================================================================
 *
 * A VBIN header has ONE entry word and stage2 calls it once.  That was enough
 * while a card carried one payload.  It stopped being enough the moment two
 * were combined -- a gyro logger and the USB shell's worker, say -- and the
 * way it stopped was silent: `--vshl-entry` overwrote the worker's entry with
 * the logger's, both sections were still placed, the worker's state words were
 * still written, the endpoint patches were still applied, and then nothing
 * created the task.  A card that looks fully loaded and has no shell.
 *
 * So this goes in as the entry instead, and it calls the real ones in turn.
 *
 * WHY NOT LET EACH PAYLOAD CALL THE NEXT.  Because the payloads are not all
 * ours.  A card is combined from released artifacts -- fpsup-gyro-v1.11b and
 * fpsup-usbshell-v3.1.0 are frozen bytes with no "next" word to patch -- and
 * an author who writes the obvious entry, install yourself and `bx lr`, would
 * end the chain without knowing there was one.  That is the same silent drop
 * this file exists to remove, moved somewhere harder to see.  Out here the
 * rule for a payload is unchanged: install yourself and return.
 *
 * EACH ENTRY IS CALLED EXACTLY AS STAGE2 WOULD CALL IT: r0 holds its own
 * resolved address, and a value below 0x40000000 is an offset into the buffer
 * rather than an address -- the same threshold, because a payload cannot tell
 * which of the two called it and must not have to.
 *
 * The buffer base is not passed to us either, so it is recovered: the first
 * word of the table is this table's own offset in the file, written by the
 * builder, and our runtime address minus that offset is where the file landed.
 * The builder knows that offset already -- it is what it would have put in the
 * header's entry word -- so nothing is computed twice.
 * ========================================================================== */

entry:
    /* Four registers, not three: the firmware's LDRD needs the stack 8-byte
     * aligned and an interrupt will use ours.  r6 is pushed for the count. */
    push    {r4, r5, r6, lr}
    adr     r4, table
    ldr     r5, [r4]                    @ this table's offset in the file
    sub     r5, r4, r5                  @ r5 = the buffer, i.e. the file
    add     r4, r4, #4

1:  ldr     r1, [r4], #4
    cmp     r1, #0
    beq     2f                          @ the list ends with a zero word
    movw    r3, #0
    movt    r3, #0x4000                 @ 0x40000000
    cmp     r1, r3
    addlo   r1, r1, r5                  @ below it: an offset into the file
    mov     r0, r1                      @ as stage2 leaves it
    mov     ip, r1
    blx     ip                          @ install yourself, and come back
    b       1b

2:  pop     {r4, r5, r6, pc}

table:
    .word   0                           @ patched: this word's own file offset
    /* The entry words follow, appended by the builder, terminated by zero. */
