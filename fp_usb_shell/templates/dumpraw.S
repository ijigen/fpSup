.syntax unified
.arm
.text
/* ============================================================================
 * dumpraw — put bytes in the reply buffer directly, with no shell in the way.
 * ============================================================================
 *
 * dump.S prints hex through the firmware's printf, which costs about a
 * microsecond a character: a 1500-byte read spends five milliseconds, and
 * almost none of it is the link. Hex doubles the volume before paying that,
 * so the tax is charged twice.
 *
 * The worker clears the capture length, runs the command, then sends whatever
 * many bytes sit at the capture buffer. Nothing says a command has to get there
 * through printf. This copies the bytes in and sets the length itself, so the
 * reply is the data -- no formatting, no expansion, no shell.
 *
 * Borrowed slot: echo, handler pointer 0xC0BAC2F8. See shellcmd.S.
 *
 * Where to read is said on the command line:
 *
 *      echo C0100000 BB8           address and length, both hex
 *
 * The reply is that many bytes followed by the four-byte address they were read
 * from, so the host can tell its own answer from someone else's.
 *
 * That block then took 0.27 ms and the host spent ten more setting up the next
 * one -- three parameter words written one shell command at a time, one of
 * which was never even read here. Four commands to move three thousand bytes,
 * and the three cheap ones cost thirty times the expensive one.
 *
 * A handler is handed its arguments already parsed (r1 count, r2 vector), so
 * the address can simply ride along with the request. Nothing is remembered
 * between calls, which matters more than the speed: when a reply went missing
 * the camera had still advanced, and host and camera disagreed about where we
 * were until the next write put them back.
 *
 * Called with fewer than two arguments it falls back to the parameter block at
 * 0xC072F700 (+0x00 source, +0x04 count) and advances the source itself.
 * ========================================================================== */

.equ P,        0xC072F700
.equ FRAMEBUF, 0xC3757A7C     /* [0] = the DMA pool, where the buffers live   */
.equ CAP_OFF,  0x2000         /* the reply buffer, past the frame             */
.equ CAP_LEN,  0xC072F040     /* how much of it the worker will send          */
.equ CAP_MAX,  0x4000

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    push    {r4, r5, r6, r7, r8, lr}
    cmp     r1, #2                      @ argc counts arguments, not the command,
    blo     from_block                  @ and argv[0] is the first of them

    mov     r4, r2
    ldr     r0, [r4]
    bl      parse_hex
    mov     r5, r0                      @ source
    ldr     r0, [r4, #4]
    bl      parse_hex
    mov     r6, r0                      @ count
    mov     r4, #0                      @ nothing to write back
    b       have_args

from_block:
    LDA     r4, P
    ldr     r5, [r4]
    ldr     r6, [r4, #4]

have_args:
    movw    r0, #CAP_MAX
    cmp     r6, r0
    movhi   r6, r0                      @ silently short is bad, but a wild
                                        @ length would be worse

    LDA     r0, FRAMEBUF
    ldr     r7, [r0]
    movw    r0, #CAP_OFF
    add     r7, r7, r0

    mov     r0, #0
1:  cmp     r0, r6
    bhs     2f
    ldrb    r8, [r5, r0]
    strb    r8, [r7, r0]
    add     r0, r0, #1
    b       1b
2:
    /* Say which address these bytes came from.
     *
     * A raw block is just bytes: nothing in it says which request it answers.
     * When a read times out and the next one is served with the abandoned
     * reply, the host has no way to tell -- five blocks in forty-two came back
     * belonging to a different address, and looked perfectly fine. The framed
     * path carries a sequence number for exactly this, and costs three times
     * the speed.
     *
     * Four bytes are enough. The host knows what it asked for. */
    str     r5, [r7, r6]
    add     r6, r6, #4

    LDA     r0, CAP_LEN
    str     r6, [r0]
    sub     r6, r6, #4                  @ the caller's count, for the advance

    cmp     r4, #0                      @ only the parameter block advances
    addne   r5, r5, r6
    strne   r5, [r4]

    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

/* r0 = NUL-terminated hex -> r0 = value. Stops at the first character that is
 * not a hex digit, so a trailing anything is harmless. */
parse_hex:
    mov     r1, #0
1:  ldrb    r2, [r0], #1
    sub     r3, r2, #'0'
    cmp     r3, #9
    bls     2f
    orr     r2, r2, #0x20               @ fold case
    sub     r3, r2, #'a'
    cmp     r3, #5
    bhi     3f
    add     r3, r3, #10
2:  lsl     r1, r1, #4
    add     r1, r1, r3
    b       1b
3:  mov     r0, r1
    bx      lr
