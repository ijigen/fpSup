.syntax unified
.arm
.text
.global entry
.global blob
/* ============================================================================
 * pc3_launch — 預錄 P3 開機 launcher（與 P2 同一三個掛點）
 * ============================================================================
 * builder 以 -D 傳入：RES_LEN、STUB_A、STUB_B、STUB_D。
 * ========================================================================== */

.equ H_GET,          0xC001D740
.equ H_ADDR,         0xC001D7F0
.equ F_DCACHE,       0xC000E91C
.equ F_ICACHE,       0xC000EABC
.equ CAVE_BUMP,      0xC072E060
.equ CAVE_ARENA,     0xC072E064
.equ CAVE_ARENA_END, 0xC072EFB4
.equ VENEER_LDR,     0xE51FF004
.equ ALLOC,          0x1000

.equ SITE_A,         0xC038F0E8
.equ SITE_B,         0xC038F174
.equ SITE_D,         0xC02DC108
.equ ORIG_BLX_R3,    0xE12FFF33
.equ ORIG_BL_DISP,   0xEB00000A

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.macro GUARD addr, word
    LDA     r0, \addr
    ldr     r1, [r0]
    LDA     r2, \word
    cmp     r1, r2
    bne     9f
.endm

.macro ARM site, n
    LDA     r1, \site
    add     r2, r5, #(\n) * 8
    sub     r0, r2, r1
    sub     r0, r0, #8
    asr     r0, r0, #2
    bic     r0, r0, #0xFF000000
    orr     r0, r0, #0xEB000000
    str     r0, [r1]
.endm

.macro VENEER n, stub
    LDA     r0, \stub
    add     r0, r4, r0
    str     r2, [r5, #(\n) * 8]
    str     r0, [r5, #(\n) * 8 + 4]
.endm

entry:
    push    {r4-r11, ip, lr}
    sub     sp, sp, #16

    GUARD   SITE_A, ORIG_BLX_R3
    GUARD   SITE_B, ORIG_BLX_R3
    GUARD   SITE_D, ORIG_BL_DISP

    mov     r0, sp
    mov     r1, #0
    LDA     r2, ALLOC
    mov     r3, #0
    LDA     ip, H_GET
    blx     ip
    mov     r0, sp
    LDA     ip, H_ADDR
    blx     ip
    movs    r4, r0
    beq     9f
    add     r4, r4, #7
    bic     r4, r4, #7

    ldr     r1, blob_rel
1:  add     r1, pc, r1
    mov     r0, r4
    LDA     r2, RES_LEN
2:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #4
    bne     2b

    LDA     r7, CAVE_BUMP
    ldr     r5, [r7]
    LDA     r2, CAVE_ARENA
    cmp     r5, r2
    blo     9f
    tst     r5, #3
    bne     9f
    add     r1, r5, #24
    LDA     r2, CAVE_ARENA_END
    cmp     r1, r2
    bhi     9f
    str     r1, [r7]
    LDA     r2, VENEER_LDR
    VENEER  0, STUB_A
    VENEER  1, STUB_B
    VENEER  2, STUB_D

    LDA     ip, F_DCACHE
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip
    ARM     SITE_A, 0
    ARM     SITE_B, 1
    ARM     SITE_D, 2
    LDA     ip, F_DCACHE
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip

9:  add     sp, sp, #16
    pop     {r4-r11, ip, pc}

blob_rel: .word blob - (1b + 8)
.align 2
blob:
