.syntax unified
.arm
.text
.global entry
.global blob
/* ============================================================================
 * pc2_launch — 預錄 P2 開機 launcher（destination 0：在 staging 原地執行，裝好後返回）
 * ============================================================================
 *
 * 與 pc_launch（P1）同一形狀，多一個掛點：
 *   1. 三個掛點必須是 5.02 原廠字：A、B = `blx r3`，D = `bl FUN_c02dc138`；否則什麼都不裝
 *   2. USER heap 配置 ALLOC bytes
 *   3. 把常駐（本檔尾端的 blob，RES_LEN bytes）整塊複製過去
 *   4. 三個 8-byte veneer 取自 CAVE_BUMP，檢查在 arena 內、4-byte 對齊、放得下
 *   5. D/I cache → 寫三個 `bl veneer` → 再 D/I cache
 * 任何一步不過就直接返回。掛點已由 builder 宣告成「內容 = 原廠字」的區段，關機時寫回。
 *
 * builder 以 -D 傳入：RES_LEN、STUB_A、STUB_B、STUB_D（常駐內偏移）。
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
.equ ORIG_BL_DISP,   0xEB00000A     /* bl FUN_c02dc138（從 C02DC108） */

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

    /* 1. 原廠字 */
    GUARD   SITE_A, ORIG_BLX_R3
    GUARD   SITE_B, ORIG_BLX_R3
    GUARD   SITE_D, ORIG_BL_DISP

    /* 2. 配置 */
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

    /* 3. 複製常駐 */
    ldr     r1, blob_rel
1:  add     r1, pc, r1
    mov     r0, r4
    LDA     r2, RES_LEN
2:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #4
    bne     2b

    /* 4. 三個 veneer（24 bytes） */
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

    /* 5. publish → arm → publish */
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
