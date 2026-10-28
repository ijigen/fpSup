.syntax unified
.arm
.text
.global params
.global stub_a
.global stub_b
.global disp_stub
/* ============================================================================
 * pc2_resident — 預錄 P2 常駐（半按自動連拍）
 * ============================================================================
 *
 * 三個掛點（都由 launcher 改成 `bl veneer`，veneer 跳進這裡）：
 *   A = C038F0E8、B = C038F174：HIGHCONT 把一幀交給 XC_StillCreateYuv 的那條
 *       `blx r3`（同 P1）。stub_a / stub_b 記一筆、檢查超時，再尾呼叫原函式。
 *   D = C02DC108：按鍵執行緒裡唯一的 `bl FUN_c02dc138`（把一個鍵碼分發給監聽者）。
 *       disp_stub 看鍵碼決定要不要注入／補 S2，再呼叫原分發函式。
 *
 * 行為（只在 FUN_c0397b30(3)==9，即高速連拍時；呼叫它之前先確認它用到的單例都已建好、
 * 設定堆疊狀態有效，否則不注入、原樣放行，原因記在 P_GATE）：
 *   碼 4 (S1 ON) 且尚未預錄 → 先原樣分發 S1，設 pre=1、記 t0，再分發碼 6 (S2 ON)。
 *                              對焦優先時原廠會把 S2 記成待處理、等合焦才開拍。
 *   碼 5 (S1 OFF) 且 pre     → 清 pre，先分發碼 7 (S2 OFF 收尾) 再分發碼 5。
 *   碼 7 (S2 OFF)            → 清 pre，再原樣分發。
 *   其餘碼                    → 原樣分發。
 *   每幀檢查：pre 且距 t0 超過 10 秒且還沒送過 → 投遞碼 7（跨執行緒，和 shell key 相同）。
 *
 * disp_stub 進來時 r0=keymon、r1=碼、lr=掛點+4；它是一般 AAPCS 呼叫，保存 r4-r8。
 * 整段由 launcher 複製進自己配置的記憶體，初值即下面的 .word。
 * ========================================================================== */

.equ F_TICK_US,  0xC002B6E0         /* () -> 微秒 */
.equ F_KIND,     0xC0397B30         /* (key) -> 拍攝類型；key 3 時 9 = 高速連拍 */
.equ F_KEYMON,   0xC02DBAF0         /* () -> KeyMon 單例（idempotent getter） */
.equ F_ENQ,      0xC02DBBE8         /* (keymon, 碼) 投遞到 KeyMon 佇列 */
.equ F_DISP,     0xC02DC138         /* (keymon, 碼) 原廠分發（掛點 D 原本呼叫的對象） */
.equ RING_N,     64
.equ TIMEOUT_US, 10000000           /* 10 秒 */

.equ P_MAGIC,    0x00
.equ P_LAYOUT,   0x04
.equ P_COUNT_A,  0x08
.equ P_COUNT_B,  0x0C
.equ P_FIRST_US, 0x10
.equ P_LAST_US,  0x14
.equ P_SEQ,      0x18
.equ P_RING_N,   0x1C
.equ P_PRE,      0x20               /* 預錄中 = 1 */
.equ P_T0,       0x24               /* 注入 S2 時的微秒 */
.equ P_TMO,      0x28               /* 已送出超時 S2 OFF = 1 */
.equ P_INJ,      0x2C               /* 注入 S2 次數 */
.equ P_S1C,      0x30               /* 放開 S1 收尾次數 */
.equ P_TMOF,     0x34               /* 超時觸發次數 */
.equ P_DISP,     0x38               /* 經過掛點的鍵碼數 */
.equ P_GATE,     0x3C               /* 最近一次 S1 ON 的判斷：1 = 注入；0x100|kind = 不是高速連拍；
                                       0x200|n = 第 n 個單例還沒建好；0x300 = 設定堆疊狀態不對 */
.equ P_RING,     0x40               /* {us, 任務 id, Yuv 物件, 掛點 0/1} × RING_N */

/* FUN_c0397b30 用到的單例 getter 第一次被呼叫時會建構物件；只在它們都已建好時才呼叫，
 * 免得在按鍵執行緒裡和狀態機任務同時建構。FUN_c0022e08 在設定堆疊狀態不對時會斷言，
 * 所以先照它的條件檢查一遍（[+0xC] == 1、[+0x10] < 3、該格非 0）。 */
.equ SSTACK,     0xC3075670

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

params:
    .word   0x32504350              /* "PCP2" */
    .word   2
    .word   0, 0, 0, 0, 0
    .word   RING_N
    .word   0, 0, 0, 0, 0, 0, 0     /* pre, t0, tmo, inj, s1c, tmof, disp */
    .word   0                       /* gate；builder 檢查 ring == P_RING */
ring:
    .space  RING_N * 16

/* ---- 幀掛點（A/B）：記一筆、檢查超時、尾呼叫原入隊函式 ------------------- */
stub_a:
    push    {r0-r6, lr}             @ 八個：SP 保持 8-byte 對齊
    mov     r4, #0
    b       frame_common
stub_b:
    push    {r0-r6, lr}
    mov     r4, #1
frame_common:
    ldr     r5, params_rel
1:  add     r5, pc, r5              @ r5 = params
    mov     r6, r1                  @ 任務 id
    LDA     ip, F_TICK_US
    blx     ip                      @ r0 = 微秒（之後一直留在 r0）

    add     r2, r5, r4, lsl #2
    ldr     r1, [r2, #P_COUNT_A]
    add     r1, r1, #1
    str     r1, [r2, #P_COUNT_A]

    ldr     r1, [r5, #P_SEQ]
    cmp     r1, #0
    streq   r0, [r5, #P_FIRST_US]
    str     r0, [r5, #P_LAST_US]

    and     r2, r1, #(RING_N - 1)
    add     r3, r5, #P_RING
    add     r2, r3, r2, lsl #4
    ldr     r3, [sp]                @ 進來時的 r0 = Yuv 物件
    str     r0, [r2]
    str     r6, [r2, #4]
    str     r3, [r2, #8]
    str     r4, [r2, #12]
    add     r1, r1, #1
    str     r1, [r5, #P_SEQ]

    /* 超時：pre 且尚未送出且 now - t0 >= 10 s → 投遞 S2 OFF */
    ldr     r1, [r5, #P_PRE]
    cmp     r1, #0
    beq     3f
    ldr     r1, [r5, #P_TMO]
    cmp     r1, #0
    bne     3f
    ldr     r2, [r5, #P_T0]
    sub     r2, r0, r2              @ 經過微秒（無號環繞也沒關係：十秒內單調遞增）
    LDA     r3, TIMEOUT_US
    cmp     r2, r3
    blo     3f
    mov     r1, #1
    str     r1, [r5, #P_TMO]
    ldr     r1, [r5, #P_TMOF]
    add     r1, r1, #1
    str     r1, [r5, #P_TMOF]
    LDA     ip, F_KEYMON
    blx     ip                      @ r0 = keymon
    mov     r1, #7
    LDA     ip, F_ENQ
    blx     ip
3:
    pop     {r0-r6, lr}
    bx      r3

/* ---- 按鍵分發掛點（D）：注入／收尾 S2 ---------------------------------- */
disp_stub:
    push    {r4-r8, lr}             @ 六個：24 bytes，SP 保持 8-byte 對齊
    mov     r4, r0                  @ keymon
    mov     r5, r1                  @ 鍵碼
    ldr     r6, disp_params_rel
2:  add     r6, pc, r6              @ r6 = params

    ldr     r0, [r6, #P_DISP]
    add     r0, r0, #1
    str     r0, [r6, #P_DISP]

    cmp     r5, #4
    beq     d_s1
    cmp     r5, #5
    beq     d_s1off
    cmp     r5, #7
    beq     d_s2off
    b       d_orig

d_s2off:
    mov     r0, #0
    str     r0, [r6, #P_PRE]
    b       d_orig

d_s1off:
    ldr     r0, [r6, #P_PRE]
    cmp     r0, #0
    beq     d_orig
    mov     r0, #0
    str     r0, [r6, #P_PRE]
    ldr     r0, [r6, #P_S1C]
    add     r0, r0, #1
    str     r0, [r6, #P_S1C]
    mov     r0, r4                  @ 先 S2 OFF 收尾
    mov     r1, #7
    LDA     ip, F_DISP
    blx     ip
    mov     r0, r4                  @ 再 S1 OFF
    mov     r1, #5
    LDA     ip, F_DISP
    blx     ip
    b       d_done

d_s1:
    ldr     r0, [r6, #P_PRE]
    cmp     r0, #0
    bne     d_orig                  @ 已在預錄：原樣放行

    ldr     r0, guards_rel          @ 單例都已建好？
4:  add     r0, pc, r0
    mov     r2, #0x200
5:  ldr     r1, [r0], #4
    cmp     r1, #0
    beq     6f
    add     r2, r2, #1
    ldr     r1, [r1]
    cmp     r1, #1
    bne     d_refuse
    b       5b
6:  LDA     r0, SSTACK              @ 設定堆疊狀態有效？
    mov     r2, #0x300
    ldr     r1, [r0, #0xC]
    cmp     r1, #1
    bne     d_refuse
    ldr     r1, [r0, #0x10]
    cmp     r1, #3
    bhs     d_refuse
    ldr     r1, [r0, r1, lsl #2]
    cmp     r1, #0
    beq     d_refuse

    mov     r0, #3                  @ 只在高速連拍時注入
    mov     r1, #0
    LDA     ip, F_KIND
    blx     ip
    cmp     r0, #9
    beq     7f
    and     r2, r0, #0xFF
    orr     r2, r2, #0x100
    b       d_refuse
7:  mov     r0, #1
    str     r0, [r6, #P_GATE]
    mov     r0, r4                  @ 先原樣分發真正的 S1
    mov     r1, #4
    LDA     ip, F_DISP
    blx     ip
    mov     r0, #1                  @ pre = 1
    str     r0, [r6, #P_PRE]
    LDA     ip, F_TICK_US
    blx     ip
    str     r0, [r6, #P_T0]
    mov     r0, #0
    str     r0, [r6, #P_TMO]
    ldr     r0, [r6, #P_INJ]
    add     r0, r0, #1
    str     r0, [r6, #P_INJ]
    mov     r0, r4                  @ 注入 S2 ON
    mov     r1, #6
    LDA     ip, F_DISP
    blx     ip
    b       d_done

d_refuse:
    str     r2, [r6, #P_GATE]
d_orig:
    mov     r0, r4
    mov     r1, r5
    LDA     ip, F_DISP
    blx     ip
d_done:
    pop     {r4-r8, pc}

params_rel:      .word params - (1b + 8)
disp_params_rel: .word params - (2b + 8)
guards_rel:      .word guards - (4b + 8)
guards:
    .word   0xC35A9530              /* FUN_c03a9970 */
    .word   0xC31F8C90              /* FUN_c0206e98 */
    .word   0xC358CB48              /* FUN_c0387e40 */
    .word   0xC3074980              /* FUN_c00213b8 */
    .word   0xC3075684              /* FUN_c0022da8 */
    .word   0
