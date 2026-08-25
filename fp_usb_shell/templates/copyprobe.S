.syntax unified
.arm
.text
/* ============================================================================
 * copyprobe — copy out of the gyro ring, and nothing else.
 * ============================================================================
 *
 * The last untested thing the logger does. Everything read-side has now been
 * cleared during a real recording: the hook framework, the recording-state
 * query, the descriptor chain, the ring head, the clock, the path manager. The
 * pool has been checked too -- 160 KiB of markers survived three seconds
 * untouched apart from the two words the shell itself owns.
 *
 * What is left is the bulk copy. The ring lives at 0x2E00644C, which is not in
 * any region this work has touched before -- not firmware at 0xC0......, not
 * the DRAM pool at 0x44....... Reading one word from it is proven; reading four
 * hundred bytes out of it fifty times a second while the sensor is filling it
 * is not the same thing.
 *
 *      0xC072E800  +0x00 calls   +0x04 copies   +0x08 bytes copied, total
 *                  +0x0C last head   +0x10 last span   +0x14 first word copied
 * Destination is the pool at +0x7000, where the logger's buffer A sits.
 * ========================================================================== */

.equ HOOK_TARGET,   0xC01EC6F9
.equ SCRATCH,       0xC072E800
.equ REC_STATE,     0xC035B2D0
.equ GYRO_DESC_PTR, 0xC31E3FCC
.equ POOL_PTR,      0xC3757A7C
.equ RING_SIZE,     0x12C4

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global probe
probe:
    push    {r3, r4, r5, r6, r7, r8, r9, r10, r11, lr}
    LDA     ip, HOOK_TARGET
    blx     ip
    mov     r11, r0

    LDA     r4, SCRATCH
    ldr     r0, [r4]
    add     r0, r0, #1
    str     r0, [r4]

    LDA     ip, REC_STATE
    blx     ip
    ldrb    r0, [r0, #0x157]
    cmp     r0, #0
    beq     out                      @ only while recording

    LDA     r0, GYRO_DESC_PTR
    ldr     r0, [r0]
    ldr     r8, [r0, #0x60]          @ ring base
    ldr     r5, [r8]                 @ head now
    ldr     r6, [r4, #0x0C]          @ head last time
    cmp     r6, #0
    beq     remember                 @ first call: just take the head
    cmp     r5, r6
    beq     out

    /* Byte count, wrapping the same way the logger computes it. */
    cmp     r5, r6
    subhi   r3, r5, r6
    bhi     have
    movw    r3, #RING_SIZE
    add     r3, r3, r5
    sub     r3, r3, r6
have:
    str     r3, [r4, #0x10]

    /* Destination: pool + 0x7000, the logger's buffer A. */
    LDA     r0, POOL_PTR
    ldr     r7, [r0]
    add     r7, r7, #0x7000

    cmp     r5, r6
    bhi     one_span
    add     r0, r6, #4
    movw    r12, #RING_SIZE
    add     r1, r8, r12
    bl      span
    add     r0, r8, #4
    add     r1, r5, #4
    bl      span
    b       copied
one_span:
    add     r0, r6, #4
    add     r1, r5, #4
    bl      span
copied:
    ldr     r0, [r4, #4]
    add     r0, r0, #1
    str     r0, [r4, #4]
    ldr     r0, [r4, #8]
    add     r0, r0, r3
    str     r0, [r4, #8]
    LDA     r0, POOL_PTR
    ldr     r0, [r0]
    ldr     r0, [r0, #0x7000]
    str     r0, [r4, #0x14]
remember:
    str     r5, [r4, #0x0C]

out:
    mov     r0, r11
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}

span:
1:  cmp     r0, r1
    bhs     2f
    ldrb    r12, [r0], #1
    strb    r12, [r7], #1
    b       1b
2:  bx      lr
