.syntax unified
.arm
.text
/* ============================================================================
 * bulkload — carry bytes to the camera in the command line, not one at a time.
 * ============================================================================
 *
 * `mem set` moves four bytes per USB round trip, which put 14 KB of AutoRun at
 * 448 seconds.  Reading the same file back took 22, because `mem get` answers
 * sixteen words at once.  The transport was never the problem; the command was.
 *
 * A shell command line holds about 502 characters, so one invocation can carry
 * roughly 245 bytes of hex instead of four of binary.  The destination is kept
 * in the parameter block and advanced here, so the host sends nothing but data.
 *
 *     mem set 0xC072F5F8 <destination>       once
 *     echo <hex><hex><hex>...                repeatedly
 *
 * Verification is still the caller's job.  Writes get dropped -- so do whole
 * commands -- and a chunk that never arrives leaves a 245 byte hole rather than
 * a four byte one.  Read the region back and repair what is missing.
 *
 * State, 0xC072F5F8, its own -- not the parameter block the others use:
 *      +0x00  destination, advanced by each call        host sets it once
 *      +0x04  bytes taken so far, cumulative
 * ========================================================================== */

/* Its own two words, deliberately outside the parameter block the other
 * templates use.  Sharing +0x14 with them cost a silent failure: loading
 * getfile.S through this loader advanced that word past getfile's own buffer,
 * so the read landed somewhere else and every byte came back as poison. */
.equ P,        0xC072F5F8
.equ P_BUF,    0x00           /* destination, advanced here */
.equ P_ACTUAL, 0x04           /* bytes taken, cumulative    */

.equ FMT_S,    0xC0BABB38

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r8, r0                  @ shell context
    LDA     r4, P
    cmp     r1, #1
    blt     bad_args
    ldr     r5, [r2]                @ argv[0], the hex
    ldr     r6, [r4, #P_BUF]
    mov     r7, #0

next_byte:
    ldrb    r0, [r5], #1
    cmp     r0, #0
    beq     stored
    bl      hexval
    cmp     r0, #0
    blt     stored
    mov     r3, r0, lsl #4
    ldrb    r0, [r5], #1
    cmp     r0, #0
    beq     stored                  @ odd number of digits: drop the tail
    bl      hexval
    cmp     r0, #0
    blt     stored
    orr     r3, r3, r0
    strb    r3, [r6], #1
    add     r7, r7, #1
    b       next_byte

stored:
    str     r6, [r4, #P_BUF]        @ advance for the next chunk
    ldr     r0, [r4, #P_ACTUAL]
    add     r0, r0, r7
    str     r0, [r4, #P_ACTUAL]
    adr     r1, msg_ok
    b       say

bad_args:
    adr     r1, msg_bad

say:
    ldr     ip, [r8]
    LDA     r0, FMT_S
    blx     ip
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

/* r0 = ASCII digit -> value, or negative if it is not one. */
hexval:
    sub     r1, r0, #'0'
    cmp     r1, #10
    movlo   r0, r1
    bxlo    lr
    bic     r1, r0, #0x20           @ fold case
    sub     r1, r1, #'A'
    cmp     r1, #6
    addlo   r0, r1, #10
    mvnhs   r0, #0                  @ -1
    bx      lr

msg_ok:
    .asciz  "ok"
    .align  2
msg_bad:
    .asciz  "bulkload: no data"
    .align  2
