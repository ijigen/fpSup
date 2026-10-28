.syntax unified
.arm
.text
.global params
.global stub_a
.global stub_b
/* ============================================================================
 * pc_resident — 預錄 P1 常駐（只觀察）
 * ============================================================================
 *
 * 兩個掛點都是 HIGHCONT 把一幀交給 XC_StillCreateYuv 入隊的那條 `blx r3`：
 *   A = C038F0E8（RAW 事件 type 5 主路徑）、B = C038F174（子幀路徑）。
 * launcher 把它們改成 `bl veneer`，veneer 跳到這裡的 stub_a / stub_b。
 * 進來時 r0 = Yuv 階段物件、r1 = 任務 id、r2 = 1、r3 = 入隊函式、lr = 掛點 + 4。
 * 記一筆之後還原 r0–r3、lr，`bx r3` 尾呼叫原函式：原廠流程一個字都不變。
 *
 * 這一段由 launcher 整塊複製進自己配置的記憶體，所以初值就是下面的 .word。
 * USB 讀法：掛點的 bl 目標 = veneer，veneer + 4 = stub_a 的位址，params = stub_a − STUB_A。
 * ========================================================================== */

.equ F_TICK_US,  0xC002B6E0         /* () -> 微秒；loader 的 LOAD_DONE_US 用同一個鐘 */
.equ RING_N,     64                 /* 2 的冪 */

.equ P_MAGIC,    0x00
.equ P_LAYOUT,   0x04
.equ P_COUNT_A,  0x08
.equ P_COUNT_B,  0x0C
.equ P_FIRST_US, 0x10
.equ P_LAST_US,  0x14
.equ P_SEQ,      0x18               /* 總筆數，不取模；環的位置 = SEQ & (RING_N − 1) */
.equ P_RING_N,   0x1C
.equ P_RING,     0x20               /* {us, 任務 id, Yuv 物件, 掛點 0/1} × RING_N */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

params:
    .word   0x31504350              /* "PCP1" */
    .word   1
    .word   0
    .word   0
    .word   0
    .word   0
    .word   0
    .word   RING_N
ring:
    .space  RING_N * 16

stub_a:
    push    {r0-r6, lr}             @ 八個：SP 保持 8-byte 對齊
    mov     r4, #0
    b       common
stub_b:
    push    {r0-r6, lr}
    mov     r4, #1
common:
    ldr     r5, params_rel
1:  add     r5, pc, r5              @ r5 = params
    mov     r6, r1                  @ 任務 id
    LDA     ip, F_TICK_US
    blx     ip                      @ r0 = 微秒

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
    ldr     r3, [sp]                @ 進來時的 r0
    str     r0, [r2]
    str     r6, [r2, #4]
    str     r3, [r2, #8]
    str     r4, [r2, #12]
    add     r1, r1, #1
    str     r1, [r5, #P_SEQ]

    pop     {r0-r6, lr}
    bx      r3

params_rel: .word params - (1b + 8)
