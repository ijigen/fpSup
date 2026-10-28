.syntax unified
.arm
.text
.global entry
.global blob
/* ============================================================================
 * pc_launch — 預錄 P1 開機 launcher（destination 0：在 staging 原地執行，裝好後返回）
 * ============================================================================
 *
 * 照 rawview rv_launch.S（非 V3 路徑）的形狀，依 SUP_BUILD_RULES §4：
 *   1. 兩個掛點必須是 5.02 原廠字 `blx r3`，否則什麼都不裝
 *   2. USER heap 配置 ALLOC bytes（描述子在堆疊上，不釋放）
 *   3. 把常駐（本檔尾端的 blob，RES_LEN bytes）整塊複製過去：初值隨程式走
 *   4. 兩個 8-byte veneer 取自 CAVE_BUMP，檢查在 arena 內；只要求 4-byte 對齊
 *      （stage2 每次開機重設成 CAVE_ARENA = 0xC072E064，本身就不是 8 的倍數）
 *   5. D/I cache → 寫 `bl veneer` → 再 D/I cache
 * 任何一步不過就直接返回；之前配置的記憶體留著，下次開機釋放。
 * 掛點已由 builder 宣告成「內容 = 原廠字」的區段：stage2 先記 journal，關機時寫回。
 *
 * builder 以 -D 傳入：RES_LEN、STUB_A、STUB_B（常駐內偏移）。
 * ========================================================================== */

.equ H_GET,          0xC001D740     /* (desc, class, size, 0) */
.equ H_ADDR,         0xC001D7F0     /* (desc) -> address */
.equ F_DCACHE,       0xC000E91C
.equ F_ICACHE,       0xC000EABC
.equ CAVE_BUMP,      0xC072E060
.equ CAVE_ARENA,     0xC072E064
.equ CAVE_ARENA_END, 0xC072EFB4
.equ VENEER_LDR,     0xE51FF004     /* ldr pc, [pc, #-4] */
.equ ALLOC,          0x1000

.equ SITE_A,         0xC038F0E8
.equ SITE_B,         0xC038F174
.equ ORIG_BLX_R3,    0xE12FFF33

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

/* site 寫成 bl <veneer n>；r5 = veneer 起點。(dest − site − 8) asr 2 */
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

entry:
    push    {r4-r11, ip, lr}        @ 十個：stack 保持 8-byte 對齊
    sub     sp, sp, #16             @ allocator descriptor

    /* 1. 原廠字 */
    GUARD   SITE_A, ORIG_BLX_R3
    GUARD   SITE_B, ORIG_BLX_R3

    /* 2. 配置 */
    mov     r0, sp
    mov     r1, #0                  @ USER
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
    bic     r4, r4, #7              @ r4 = 常駐

    /* 3. 複製常駐 */
    ldr     r1, blob_rel
1:  add     r1, pc, r1
    mov     r0, r4
    LDA     r2, RES_LEN
2:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #4
    bne     2b

    /* 4. veneer */
    LDA     r7, CAVE_BUMP
    ldr     r5, [r7]
    LDA     r2, CAVE_ARENA
    cmp     r5, r2
    blo     9f
    tst     r5, #3
    bne     9f
    add     r1, r5, #16
    LDA     r2, CAVE_ARENA_END
    cmp     r1, r2
    bhi     9f
    str     r1, [r7]
    LDA     r2, VENEER_LDR
    LDA     r0, STUB_A
    add     r0, r4, r0
    str     r2, [r5]
    str     r0, [r5, #4]
    LDA     r0, STUB_B
    add     r0, r4, r0
    str     r2, [r5, #8]
    str     r0, [r5, #12]

    /* 5. publish → arm → publish */
    LDA     ip, F_DCACHE
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip
    ARM     SITE_A, 0
    ARM     SITE_B, 1
    LDA     ip, F_DCACHE
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip

9:  add     sp, sp, #16
    pop     {r4-r11, ip, pc}

blob_rel: .word blob - (1b + 8)
.align 2
blob:
