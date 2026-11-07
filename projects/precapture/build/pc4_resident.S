.syntax unified
.arm
.text
.global params
.global stub_a
.global stub_b
.global disp_stub
.global mute_stub
.global keep
/* ============================================================================
 * pc4_resident — 預錄 P4 常駐（P3 + pre 期間快門音靜音）
 * ============================================================================
 *
 * 掛點同 P3，另加 SRec 任務放音點 C03817D4（bl FUN_c03818f8）。
 * pre==1 時 H2 不把幀交給 YUV，按 167 ms 開格、最新格永遠是剛到的幀；
 * 實體 S2 ON 按時間提交；S1 OFF／超時把環丟掉；pre==1 時不放快門音。
 * ========================================================================== */

.equ F_TICK_US,  0xC002B6E0
.equ F_KIND,     0xC0397B30
.equ F_KEYMON,   0xC02DBAF0
.equ F_ENQ,      0xC02DBBE8
.equ F_DISP,     0xC02DC138
.equ F_JOBDB,    0xC0374220
.equ F_JOBGET,   0xC03753C0
.equ F_CAP,      0xC03A4620
.equ F_REFUND,   0xC03A46B8
.equ F_RAWOBJ,   0xC0377348
.equ F_DROPRW,   0xC0377730
.equ F_DROPJB,   0xC0375030
.equ F_ENQUEUE,  0xC037AF20
.equ F_SOUND,    0xC03818F8
.equ KEEP_N,     4
.equ TIMEOUT_US, 10000000
.equ INTERVAL,   167000
.equ JOB_RESV,   0xFFC
.equ JOB_ID,     0x10FC
.equ SSTACK,     0xC3075670

.equ P_MAGIC,    0x00
.equ P_LAYOUT,   0x04
.equ P_COUNT_A,  0x08
.equ P_COUNT_B,  0x0C
.equ P_FIRST_US, 0x10
.equ P_LAST_US,  0x14
.equ P_SEQ,      0x18
.equ P_RING_N,   0x1C
.equ P_PRE,      0x20
.equ P_T0,       0x24
.equ P_TMO,      0x28
.equ P_INJ,      0x2C
.equ P_S1C,      0x30
.equ P_TMOF,     0x34
.equ P_DISP,     0x38
.equ P_GATE,     0x3C
.equ P_HELD,     0x40
.equ P_DROPPED,  0x44
.equ P_EVICTED,  0x48
.equ P_COMMITTED,0x4C
.equ P_ABANDONED,0x50
.equ P_ORIGIN,   0x54
.equ P_LOCK,     0x58
.equ P_HEAD,     0x5C
.equ P_N,        0x60
.equ P_MUTED,    0x64
.equ P_PLAYED,   0x68
.equ P_KEEP,     0x70

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

params:
    .word   0x34504350              /* "PCP4" */
    .word   4
    .word   0, 0, 0, 0, 0
    .word   KEEP_N
    .word   0, 0, 0, 0, 0, 0, 0     /* pre..disp */
    .word   0                       /* gate */
    .word   0, 0, 0, 0, 0           /* held dropped evicted committed abandoned */
    .word   0, 0, 0, 0              /* origin lock head n */
    .word   0, 0                    /* muted played */
    .word   0                       /* pad so keep == P_KEEP */
keep:
    .space  KEEP_N * 16

/* ---- 幀掛點 -------------------------------------------------------------- */
stub_a:
    push    {r0-r8, lr}
    mov     r4, #0
    b       frame_common
stub_b:
    push    {r0-r8, lr}
    mov     r4, #1
frame_common:
    ldr     r5, params_rel
1:  add     r5, pc, r5
    mov     r6, r1                  @ 任務 id
    ldr     r7, [sp]                @ Yuv 物件
    LDA     ip, F_TICK_US
    blx     ip
    mov     r8, r0                  @ now

    add     r2, r5, r4, lsl #2
    ldr     r1, [r2, #P_COUNT_A]
    add     r1, r1, #1
    str     r1, [r2, #P_COUNT_A]
    ldr     r1, [r5, #P_SEQ]
    cmp     r1, #0
    streq   r8, [r5, #P_FIRST_US]
    str     r8, [r5, #P_LAST_US]
    add     r1, r1, #1
    str     r1, [r5, #P_SEQ]

    ldr     r1, [r5, #P_PRE]
    cmp     r1, #0
    beq     f_pass

    ldr     r0, drop_guards_rel
9:  add     r0, pc, r0
8:  ldr     r1, [r0], #4
    cmp     r1, #0
    beq     2f
    ldr     r1, [r1]
    cmp     r1, #1
    bne     f_pass
    b       8b
2:
    bl      acquire
    ldr     r1, [r5, #P_PRE]
    cmp     r1, #0
    beq     f_rel_pass

    ldr     r1, [r5, #P_TMO]
    cmp     r1, #0
    bne     3f
    ldr     r2, [r5, #P_T0]
    sub     r2, r8, r2
    LDA     r3, TIMEOUT_US
    cmp     r2, r3
    blo     3f
    mov     r1, #1
    str     r1, [r5, #P_TMO]
    ldr     r1, [r5, #P_TMOF]
    add     r1, r1, #1
    str     r1, [r5, #P_TMOF]
    mov     r0, #0
    str     r0, [r5, #P_PRE]
    mov     r0, r6                  @ 這一幀也要丟掉，否則 RAW 槽會漏
    bl      drop_one
    ldr     r1, [r5, #P_ABANDONED]
    add     r1, r1, #1
    str     r1, [r5, #P_ABANDONED]
    bl      abandon_ring
    bl      release
    LDA     ip, F_KEYMON
    blx     ip
    mov     r1, #7
    LDA     ip, F_ENQ
    blx     ip
    b       f_skip
3:
    bl      keep_or_drop
    bl      release
    b       f_skip

f_rel_pass:
    bl      release
f_pass:
    pop     {r0-r8, lr}
    bx      r3
f_skip:
    pop     {r0-r8, lr}
    bx      lr

/* r5=params r8=now r6=id r7=yuv r4=site */
keep_or_drop:
    push    {r4-r8, lr}
    ldr     r0, [r5, #P_N]
    cmp     r0, #0
    beq     k_add
    ldr     r1, [r5, #P_ORIGIN]
    sub     r1, r8, r1
    LDA     r2, INTERVAL
    cmp     r1, r2
    bhs     k_add
    /* 換掉最新格 */
    ldr     r1, [r5, #P_HEAD]
    add     r1, r1, r0
    sub     r1, r1, #1
    and     r1, r1, #(KEEP_N - 1)
    add     r2, r5, #P_KEEP
    add     r2, r2, r1, lsl #4
    ldr     r0, [r2, #4]
    bl      drop_one
    ldr     r1, [r5, #P_DROPPED]
    add     r1, r1, #1
    str     r1, [r5, #P_DROPPED]
    ldr     r0, [r5, #P_N]
    ldr     r1, [r5, #P_HEAD]
    add     r1, r1, r0
    sub     r1, r1, #1
    and     r1, r1, #(KEEP_N - 1)
    b       k_store
k_add:
    ldr     r0, [r5, #P_N]
    cmp     r0, #KEEP_N
    bne     k_push
    ldr     r1, [r5, #P_HEAD]
    add     r2, r5, #P_KEEP
    add     r2, r2, r1, lsl #4
    ldr     r0, [r2, #4]
    bl      drop_one
    ldr     r1, [r5, #P_EVICTED]
    add     r1, r1, #1
    str     r1, [r5, #P_EVICTED]
    ldr     r1, [r5, #P_HEAD]
    add     r1, r1, #1
    and     r1, r1, #(KEEP_N - 1)
    str     r1, [r5, #P_HEAD]
    ldr     r0, [r5, #P_N]
    sub     r0, r0, #1
    str     r0, [r5, #P_N]
k_push:
    str     r8, [r5, #P_ORIGIN]
    ldr     r0, [r5, #P_N]
    ldr     r1, [r5, #P_HEAD]
    add     r1, r1, r0
    and     r1, r1, #(KEEP_N - 1)
    add     r0, r0, #1
    str     r0, [r5, #P_N]
    ldr     r0, [r5, #P_HELD]
    add     r0, r0, #1
    str     r0, [r5, #P_HELD]
k_store:
    add     r2, r5, #P_KEEP
    add     r2, r2, r1, lsl #4
    str     r8, [r2]
    str     r6, [r2, #4]
    str     r7, [r2, #8]
    str     r4, [r2, #12]
    pop     {r4-r8, pc}

/* ---- 丟掉／提交整環（呼叫前已持鎖；r5=params） ------------------------ */
abandon_ring:
    push    {r4-r8, lr}
    ldr     r4, [r5, #P_N]
    ldr     r6, [r5, #P_HEAD]
    mov     r8, #0
a_loop:
    cmp     r8, r4
    bhs     a_done
    add     r1, r6, r8
    and     r1, r1, #(KEEP_N - 1)
    add     r2, r5, #P_KEEP
    add     r2, r2, r1, lsl #4
    ldr     r0, [r2, #4]
    bl      drop_one
    ldr     r1, [r5, #P_ABANDONED]
    add     r1, r1, #1
    str     r1, [r5, #P_ABANDONED]
    add     r8, r8, #1
    b       a_loop
a_done:
    mov     r0, #0
    str     r0, [r5, #P_N]
    str     r0, [r5, #P_HEAD]
    pop     {r4-r8, pc}

commit_ring:
    push    {r4-r8, lr}
    ldr     r4, [r5, #P_N]
    ldr     r6, [r5, #P_HEAD]
    mov     r8, #0
c_loop:
    cmp     r8, r4
    bhs     c_done
    add     r1, r6, r8
    and     r1, r1, #(KEEP_N - 1)
    add     r2, r5, #P_KEEP
    add     r2, r2, r1, lsl #4
    ldr     r0, [r2, #8]
    ldr     r1, [r2, #4]
    bl      commit_one
    ldr     r1, [r5, #P_COMMITTED]
    add     r1, r1, #1
    str     r1, [r5, #P_COMMITTED]
    add     r8, r8, #1
    b       c_loop
c_done:
    mov     r0, #0
    str     r0, [r5, #P_N]
    str     r0, [r5, #P_HEAD]
    pop     {r4-r8, pc}

/* r0 = 任務 id */
drop_one:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    cmp     r4, #0x60
    bhs     d9
    LDA     ip, F_JOBDB
    blx     ip
    mov     r5, r0
    mov     r1, r4
    LDA     ip, F_JOBGET
    blx     ip
    cmp     r0, #0
    beq     d9
    mov     r6, r0
    LDA     ip, F_CAP
    blx     ip
    movw    r1, #:lower16:JOB_RESV
    ldr     r1, [r6, r1]
    mov     r2, #0
    LDA     ip, F_REFUND
    blx     ip
    LDA     ip, F_RAWOBJ
    blx     ip
    mov     r1, r4
    LDA     ip, F_DROPRW
    blx     ip
    mov     r0, r5
    mov     r1, r4
    mov     r6, #0
    LDA     ip, F_DROPJB
    blx     ip
d9: pop     {r4, r5, r6, pc}

/* r0 = yuv，r1 = 任務 id */
commit_one:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    mov     r5, r1
    cmp     r5, #0x60
    bhs     c9
    LDA     ip, F_JOBDB
    blx     ip
    mov     r1, r5
    LDA     ip, F_JOBGET
    blx     ip
    cmp     r0, #0
    beq     c9
    mov     r0, r4
    mov     r1, r5
    mov     r2, #1
    LDA     ip, F_ENQUEUE
    blx     ip
c9: pop     {r4, r5, r6, pc}

/* 單核：SWP 在執行緒切換之間原子地拿鎖。ldrex/strex 在這套組譯器／unicorn 上不好用。 */
acquire:
    add     r2, r5, #P_LOCK
    mov     r1, #1
0:  swp     r0, r1, [r2]
    cmp     r0, #0
    bne     0b
    bx      lr

release:
    mov     r0, #0
    str     r0, [r5, #P_LOCK]
    bx      lr

/* ---- 快門音（SRec 任務；r0=SRec r1=曝光 us lr=C03817D8） ------------------- */
/* 只用 r2/r3/ip：放音函數只吃 r0/r1，呼叫點之後也不讀 r2/r3。 */
mute_stub:
    ldr     r2, mute_params_rel
3:  add     r2, pc, r2
    ldr     r3, [r2, #P_PRE]
    cmp     r3, #0
    bne     m_mute
    ldr     r3, [r2, #P_PLAYED]
    add     r3, r3, #1
    str     r3, [r2, #P_PLAYED]
    LDA     ip, F_SOUND
    bx      ip
m_mute:
    ldr     r3, [r2, #P_MUTED]
    add     r3, r3, #1
    str     r3, [r2, #P_MUTED]
    bx      lr

/* ---- 按鍵分發 ------------------------------------------------------------ */
disp_stub:
    push    {r4-r8, lr}
    mov     r4, r0
    mov     r5, r1
    ldr     r6, disp_params_rel
2:  add     r6, pc, r6

    ldr     r0, [r6, #P_DISP]
    add     r0, r0, #1
    str     r0, [r6, #P_DISP]

    cmp     r5, #4
    beq     d_s1
    cmp     r5, #5
    beq     d_s1off
    cmp     r5, #6
    beq     d_s2on
    cmp     r5, #7
    beq     d_s2off
    b       d_orig

d_s2on:
    ldr     r0, [r6, #P_PRE]
    cmp     r0, #0
    beq     d_orig
    mov     r0, #0
    str     r0, [r6, #P_PRE]
    mov     r5, r6
    bl      acquire
    bl      commit_ring
    bl      release
    mov     r5, #6
    b       d_orig

d_s2off:
    ldr     r0, [r6, #P_PRE]
    cmp     r0, #0
    beq     d_orig
    mov     r0, #0
    str     r0, [r6, #P_PRE]
    mov     r5, r6
    bl      acquire
    bl      abandon_ring
    bl      release
    mov     r5, #7
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
    mov     r5, r6
    bl      acquire
    bl      abandon_ring
    bl      release
    mov     r0, r4
    mov     r1, #7
    LDA     ip, F_DISP
    blx     ip
    mov     r0, r4
    mov     r1, #5
    LDA     ip, F_DISP
    blx     ip
    b       d_done

d_s1:
    ldr     r0, [r6, #P_PRE]
    cmp     r0, #0
    bne     d_orig

    ldr     r0, guards_rel
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
6:  LDA     r0, SSTACK
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

    mov     r0, #3
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
    mov     r0, r4
    mov     r1, #4
    LDA     ip, F_DISP
    blx     ip
    mov     r5, r6
    bl      acquire
    mov     r0, #0
    str     r0, [r6, #P_N]
    str     r0, [r6, #P_HEAD]
    str     r0, [r6, #P_ORIGIN]
    bl      release
    mov     r0, #1
    str     r0, [r6, #P_PRE]
    LDA     ip, F_TICK_US
    blx     ip
    str     r0, [r6, #P_T0]
    mov     r0, #0
    str     r0, [r6, #P_TMO]
    ldr     r0, [r6, #P_INJ]
    add     r0, r0, #1
    str     r0, [r6, #P_INJ]
    mov     r0, r4
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

params_rel:       .word params - (1b + 8)
disp_params_rel:  .word params - (2b + 8)
guards_rel:       .word guards - (4b + 8)
drop_guards_rel:  .word drop_guards - (9b + 8)
mute_params_rel:  .word params - (3b + 8)
guards:
    .word   0xC35A9530
    .word   0xC31F8C90
    .word   0xC358CB48
    .word   0xC3074980
    .word   0xC3075684
    .word   0
drop_guards:
    .word   0xC35200D8              /* FUN_c0374220 */
    .word   0xC35201D4              /* FUN_c0377348 */
    .word   0xC359BE44              /* FUN_c03a4620 */
    .word   0
