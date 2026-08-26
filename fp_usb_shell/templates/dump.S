.syntax unified
.arm
.text
/* ============================================================================
 * dump — read memory back densely, instead of one word per line.
 * ============================================================================
 *
 * `mem get` answers "get : A:0xc072f000, D:0x4C485356\n" -- thirty-four
 * characters for four bytes, and a round trip every 128 words. That is 26 KiB/s
 * on a SuperSpeed link, and the limit is the text, not the wire.
 *
 * This prints bare hex, two characters a byte, and fills the reply: about 3900
 * bytes per round trip against 512, so a quarter-megabyte file comes back in
 * sixty-odd exchanges rather than a thousand.
 *
 * Borrowed slot: echo, handler pointer 0xC0BAC2F8. See shellcmd.S.
 *
 * Parameter block, 0xC072F700:
 *      +0x00  source address          host fills
 *      +0x04  byte count              host fills, at most DUMP_MAX
 *      +0x08  scratch for the text     host fills, needs 2*count + 1 bytes
 * ========================================================================== */

.equ P,        0xC072F700
.equ P_SRC,    0x00
.equ P_LEN,    0x04
.equ P_TEXT,   0x08

.equ FMT_S,    0xC0BABB38     /* "%s " */
.equ DUMP_MAX, 3900           /* 2 chars each, comfortably inside the reply cap */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r8, r0                      @ shell context

    LDA     r4, P
    ldr     r5, [r4, #P_SRC]
    ldr     r6, [r4, #P_LEN]
    ldr     r7, [r4, #P_TEXT]
    movw    r0, #DUMP_MAX
    cmp     r6, r0
    movhi   r6, r0

    add     r6, r5, r6                  @ end of the source
1:
    cmp     r5, r6
    bhs     2f
    ldrb    r0, [r5], #1
    mov     r1, r0, lsr #4
    bl      nibble
    strb    r0, [r7], #1
    ldrb    r0, [r5, #-1]
    and     r1, r0, #0x0F
    bl      nibble
    strb    r0, [r7], #1
    b       1b
2:
    mov     r0, #0
    strb    r0, [r7]

    ldr     ip, [r8]
    LDA     r0, FMT_S
    ldr     r1, [r4, #P_TEXT]
    blx     ip

    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

/* r1 = 0..15 -> r0 = '0'..'9','A'..'F' */
nibble:
    cmp     r1, #10
    addlo   r0, r1, #'0'
    addhs   r0, r1, #'A' - 10
    bx      lr
