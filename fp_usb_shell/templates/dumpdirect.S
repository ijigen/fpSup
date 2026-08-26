.syntax unified
.arm
.text
/* ============================================================================
 * dumpdirect — say where the bytes are; do not move them.
 * ============================================================================
 *
 * dumpraw copies its answer into the shell's capture buffer, and that buffer is
 * sixteen kilobytes, so a 31 MB file came back in 1995 round trips. The card
 * had nothing to do with it: the camera reads that file into memory in 0.17 s,
 * at 183 MB/s, and then the host spent sixteen seconds asking for it sixteen
 * kilobytes at a time.
 *
 * A TRB carries a 24-bit length -- one transfer can be sixteen megabytes. This
 * writes the source address into CAP_PTR and the length into CAP_LEN, and the
 * worker points the TRB straight at it. Nothing is copied and nothing is
 * staged.
 *
 *      echo <address> <length>     both hex, as dumpraw
 *
 * The address is a CPU address; the worker subtracts 0x40000000 to get what the
 * controller wants. That holds for the pool and for what the firmware's
 * allocator hands out -- which is where files land -- and is not assumed to
 * hold for the firmware's own image at 0xC0000000, which is mapped some other
 * way. Read those with dumpraw.
 *
 * No address tag on the end, either: there is nowhere to put one that is not
 * somebody else's memory. dumpraw appends the source address so a stale reply
 * can be recognised; here the caller gets one transfer instead of two thousand,
 * so there is little for a stale reply to be confused with -- but it is a
 * weaker guarantee, and worth knowing about.
 *
 * Borrowed slot: echo, handler pointer 0xC0BAC2F8. See shellcmd.S.
 * ========================================================================== */

.equ CAP_LEN,  0xC072F040
.equ CAP_PTR,  0xC072F04C

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    push    {r4, r5, r6, lr}
    cmp     r1, #2
    blo     out
    mov     r4, r2
    ldr     r0, [r4]
    bl      parse_hex
    mov     r5, r0                      @ source
    ldr     r0, [r4, #4]
    bl      parse_hex
    mov     r6, r0                      @ length

    LDA     r0, CAP_PTR
    str     r5, [r0]
    LDA     r0, CAP_LEN
    str     r6, [r0]

out:
    mov     r0, #0
    pop     {r4, r5, r6, pc}

/* r0 = NUL-terminated hex -> r0 = value. */
parse_hex:
    mov     r1, #0
1:  ldrb    r2, [r0], #1
    sub     r3, r2, #'0'
    cmp     r3, #9
    bls     2f
    orr     r2, r2, #0x20
    sub     r3, r2, #'a'
    cmp     r3, #5
    bhi     3f
    add     r3, r3, #10
2:  lsl     r1, r1, #4
    add     r1, r1, r3
    b       1b
3:  mov     r0, r1
    bx      lr
