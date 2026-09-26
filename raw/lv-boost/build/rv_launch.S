.syntax unified
.arm
.text
.global entry
/* ============================================================================
 * rv_launch — rawview 開機 launcher(destination 0:在 staging 原地執行,裝好後返回)
 * ============================================================================
 *
 * 照 gyro gsup_launch.S 的形狀(SUP_BUILD_RULES):自己配置、自己複製、自己裝 hook,
 * 不讀也不發布 0xC3757A7C,不呼叫其他 sup。任何檢查不過就什麼都不裝、直接返回。
 *
 *   1. 兩個 hook 點與 mode 表第 35 筆必須是 5.02 原廠值
 *   2. USER heap 配置 ALLOC bytes,4 KiB 對齊成 T0
 *   3. T0 + k·0x1000:以整數公式產生 31 張 tone 表(build/rv_tables.py 同一公式)
 *   4. T0 + 0x3E004:11 格插槽 → ISO 100 表;T0 + 0x3E060:mode 表副本,OFF 那筆指向插槽
 *   5. T0 + 0x3E200:常駐程式(rv_resident.S),填參數;flag = 0 → 行為與原廠相同
 *      T0 + 0x40800:色彩矩陣表(root+0x08)副本,OFF 那筆換成 fp 校色矩陣(RC1/RC2 用;build/rv_color.py)
 *   6. 五個 8-byte veneer 取自 CAVE_BUMP → D/I cache → 寫 bl 與 getter patch → 再 D/I cache
 *      增益:site A/B;選單:三個 GUI→enum 呼叫點共用一個 veneer、enum→GUI 一個、setter 一個;
 *      getter C06C07C0 的表位址改成常駐區的 17 筆表、筆數 16 → 17(第 17 列 = RAW)。
 *      RAW 列調整:右側上下框(SA/GA)兩個換算呼叫點、AEL 飽和度(矩陣程度)四個換算呼叫點 → stub_ef/en/sa/sn。
 *
 * builder 以 -D 傳入:RES_LEN、TDATA_OFF(blob 內表格資料的位置)、STUB_GS/DG/MA/MB/MC(常駐內偏移)。
 * blob(本檔尾端)= 常駐程式 | 表格資料(LOG[2048] s32 | WQ[62] s32 | B s32 | THR[30] u32 | SAMP[62][146] u16)
 * ========================================================================== */

.equ H_GET,        0xC001D740       /* (desc, class, size, 0) */
.equ H_ADDR,       0xC001D7F0       /* (desc) -> address */
#ifdef LV_BOOST
.equ ALLOC,        0x7000
#else
.equ ALLOC,        0x42000
#endif
.equ F_DCACHE,     0xC000E91C
.equ F_ICACHE,     0xC000EABC
.equ CAVE_BUMP,    0xC072E060
.equ CAVE_ARENA_END, 0xC072EFB4
.equ VENEER_LDR,   0xE51FF004       /* ldr pc, [pc, #-4] */

.equ SITE_A,       0xC0313244
.equ ORIG_A,       0xE595200C
#ifdef LV_BOOST
.equ SITE_B,       0xC02D2E50
.equ ORIG_B,       0xE5901004
#else
.equ SITE_B,       0xC032F728
.equ ORIG_B,       0xE59C6000
#endif
.equ MODE_TAB,     0xC0B3D670       /* {mode, base} × 0x24 */
.equ GUI_TAB,      0xC2E412BC       /* 色彩模式 {enum, gui} × 16 */
.equ GET_MOVW,     0xC06C07CC
.equ GET_MOVT,     0xC06C07D0
.equ GET_COUNT,    0xC06C07D8
.equ SITE_MA1,     0xC0568950       /* COLOR 鍵 */
.equ SITE_MA2,     0xC056D028       /* 選單 */
.equ SITE_MA3,     0xC05818B8       /* QS */
.equ SITE_MB,      0xC0595734       /* CM_COLFIX 通知 */
.equ SITE_MC,      0xC0075CF4       /* setter cmp sl,r6 */
.equ P_GUI,        0x98
.equ NVEN,         16               /* 0–4 ARM、5 Thumb(H1)、6 ARM(LV_ColorMode)、7–10 ARM(ef/en/sa/sn)、11 ARM(mj)、12–15 ARM(zc/zs/znc/zns) */
.equ SITE_ZC_AJ,   0xC056D548       /* 對比 AJ bl C06C0EC0 */
.equ SITE_ZC_FIX,  0xC056D3E8       /* 對比 FIX */
.equ SITE_ZS_AJ,   0xC056D5A0       /* 清晰 AJ bl C06C0F90 */
.equ SITE_ZS_FIX,  0xC056D440       /* 清晰 FIX */
.equ SITE_ZNC_FIX, 0xC059581C       /* v83 bl C06C0F10 */
.equ SITE_ZNC_AJ,  0xC0595974       /* v88 */
.equ SITE_ZNS_FIX, 0xC0595854       /* v84 bl C06C0FE0 */
.equ SITE_ZNS_AJ,  0xC05959AC       /* v89 */
.equ SITE_MJ,      0xC05689A8       /* COLOR 鍵選單預覽 bl C06C07E8 */
.equ SITE_EN_FIX,  0xC05957B0       /* v82 bl C06C0D70(CM_COLFIX_Effect) */
.equ SITE_EF,      0xC0568A3C       /* 上下框回呼 bl C06C0D20 */
.equ SITE_EN,      0xC0595908       /* v87 bl C06C0D70 */
.equ SITE_SA_AJ,   0xC056D5F8       /* 飽和度 AJ bl C06C1060 */
.equ SITE_SA_FIX,  0xC056D498       /* 飽和度 FIX bl C06C1060 */
.equ SITE_SN_FIX,  0xC059588C       /* v85 bl C06C10B0 */
.equ SITE_SN_AJ,   0xC05959E4       /* v90 bl C06C10B0 */
.equ SITE_ML,      0xC059DA1C       /* LV_ColorMode enum→GUI */
.equ H1_SITE,      0xC05E5BEC       /* Thumb:adds r0,r0,r1; str r0,[r5,#4] */
.equ THUMB_VENEER, 0xF000F8DF       /* ldr.w pc, [pc, #0] */
.equ CURVE_ENTRIES, 0xC0971114

#ifdef LV_BOOST
.equ OFF_SLOTS, 0x3004
.equ OFF_MODE,  0x3060
.equ OFF_RES,   0x3200
.equ OFF_MAT,   0x5800
#else
.equ OFF_SLOTS,    0x3E004          /* ≡ 4 mod 8(CURVE_ENTRIES ≡ 4 mod 8) */
.equ OFF_MODE,     0x3E060
.equ OFF_RES,      0x3E200
.equ OFF_MAT,      0x40800          /* 常駐(含 RAW 圖示、DNG CM 表)之後 */
#endif
.equ CBM_VT_V25,   0xC0D119FC       /* ColorButtonMenu vtable:v25 開啟 */
.equ CBM_VT_V26,   0xC0D11A00       /*                        v26 關閉 */
.equ DNG_CM1_MOVW, 0xC02C4BE4       /* FUN_c02c4a50 OFF 分支:movw/movt r2 = OFF CM1 常數 */
.equ DNG_CM1_MOVT, 0xC02C4BE8
.equ DNG_CM2_MOVW, 0xC02C4C98       /* 同上,CM2 */
.equ DNG_CM2_MOVT, 0xC02C4C9C
.equ ROOT_P08,     0xC2F1A06C       /* 色彩矩陣表 {指標, 筆數} */
.equ MAT_TAB,      0xC0B39CC8
.equ MAT_OFF_REC,  0xC0B39FF8       /* 第 34 筆 = OFF(0x24) */
.equ MAT_LEN,      35 * 0x18
.equ P_MAT,        0x1A8
.equ NTAB,         31
.equ NREC,         62               /* 2 組 × 31 */
.equ NS,           146              /* 每張表的取樣點(−8..+6.5 檔,每 0.1) */
.equ NSP,          146
.equ SAMP_OFF,     NREC * 4 + 4 + NTHR * 4   /* WQ 之後:B、THR,再來取樣表 */
.equ NTHR,         30

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* 原廠字不符 → 9f(什麼都不裝) */
.macro GUARD addr, word
    LDA     r0, \addr
    ldr     r1, [r0]
    LDA     r2, \word
    cmp     r1, r2
    bne     9f
.endm

/* site 寫成 bl <veneer n>;r5 = veneer 起點。(dest − site − 8) asr 2 */
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

/* r3 = 值 → 寫 movw/movt r2 到兩個位址(r0–r2 破壞) */
.macro MOVWT_R2 site_w, site_t
    LDA     r1, \site_w
    mov     r0, r3, lsl #16
    lsr     r0, r0, #16             @ lo16
    and     r2, r0, #0xF000
    bic     r0, r0, #0xF000
    orr     r0, r0, r2, lsl #4      @ imm4 → bits 19:16
    LDA     r2, 0xE3002000          @ movw r2, #imm
    orr     r0, r0, r2
    str     r0, [r1]
    LDA     r1, \site_t
    lsr     r0, r3, #16             @ hi16
    and     r2, r0, #0xF000
    bic     r0, r0, #0xF000
    orr     r0, r0, r2, lsl #4
    LDA     r2, 0xE3402000          @ movt r2, #imm
    orr     r0, r0, r2
    str     r0, [r1]
.endm

/* veneer n → 常駐 + off;r9 = 常駐,r5 = veneer 起點,r2 = VENEER_LDR */
.macro VEN n, off
    LDA     r0, \off
    add     r0, r9, r0
    str     r2, [r5, #(\n) * 8]
    str     r0, [r5, #(\n) * 8 + 4]
.endm

entry:
    push    {r4-r11, ip, lr}        @ 十個:stack 保持 8-byte 對齊
    sub     sp, sp, #16             @ allocator descriptor(不釋放)

    /* 1. 原廠值檢查 */
    GUARD   SITE_A, ORIG_A
    GUARD   SITE_B, ORIG_B
    GUARD   GET_MOVW, 0xE30122BC
    GUARD   GET_MOVT, 0xE34C22E4
    GUARD   GET_COUNT, 0xE3A02010
    GUARD   SITE_MA1, 0xEB055F70
    GUARD   SITE_MA2, 0xEB054DBA
    GUARD   SITE_MA3, 0xEB04FB96
    GUARD   SITE_MB, 0xEB04AC0B
    GUARD   SITE_MC, 0xE15A0006
    ldr     r3, page_rel1           @ 頁面表:{位址, 原廠字, 新字}…,0 結尾
13: add     r3, pc, r3
14: ldr     r0, [r3], #12
    cmp     r0, #0
    beq     15f
    ldr     r1, [r0]
    ldr     r2, [r3, #-8]
    cmp     r1, r2
    bne     9f
    b       14b
15:
    GUARD   H1_SITE, 0x60681840
    GUARD   SITE_ML, 0xEB048B51
    GUARD   SITE_EF, 0xEB0560B7
    GUARD   SITE_MJ, 0xEB055F8E
    GUARD   SITE_EN_FIX, 0xEB04AD6E
    GUARD   DNG_CM1_MOVW, 0xE30F2D74
    GUARD   CBM_VT_V25, 0xC05687E0
    GUARD   SITE_ZC_AJ, 0xEB054E5C
    GUARD   SITE_ZC_FIX, 0xEB054EB4
    GUARD   SITE_ZS_AJ, 0xEB054E7A
    GUARD   SITE_ZS_FIX, 0xEB054ED2
    GUARD   SITE_ZNC_FIX, 0xEB04ADBB
    GUARD   SITE_ZNC_AJ, 0xEB04AD65
    GUARD   SITE_ZNS_FIX, 0xEB04ADE1
    GUARD   SITE_ZNS_AJ, 0xEB04AD8B
    GUARD   CBM_VT_V26, 0xC0568888
    GUARD   DNG_CM1_MOVT, 0xE34C2096
    GUARD   DNG_CM2_MOVW, 0xE30F2CE4
    GUARD   DNG_CM2_MOVT, 0xE34C2096
    GUARD   SITE_EN, 0xEB04AD18
    GUARD   SITE_SA_AJ, 0xEB054E98
    GUARD   SITE_SA_FIX, 0xEB054EF0
    GUARD   SITE_SN_FIX, 0xEB04AE07
    GUARD   SITE_SN_AJ, 0xEB04ADB1
    GUARD   ROOT_P08, MAT_TAB
    GUARD   ROOT_P08 + 4, 35
    LDA     r0, MAT_OFF_REC         @ OFF 那筆必須是原廠單位矩陣
    ldr     r1, mat_rel1
22: add     r1, pc, r1              @ r1 = mat_stock
    mov     r2, #6
19: ldr     r3, [r0], #4
    ldr     ip, [r1], #4
    cmp     r3, ip
    bne     9f
    subs    r2, r2, #1
    bne     19b
    LDA     r0, MODE_TAB + 0x118
    ldr     r1, [r0]
    cmp     r1, #0x24
    bne     9f
    ldr     r1, [r0, #4]
    cmp     r1, #82
    bne     9f

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
    beq     9f                      @ 被拒:什麼都不裝
    LDA     r1, 0xFFF
    add     r4, r4, r1
    bic     r4, r4, r1              @ r4 = T0

#ifdef LV_BOOST
    ldr     r5, blob_rel1
11: add     r5, pc, r5
    LDA     r0, TDATA_OFF
    add     r5, r5, r0
    mov     r0, r4
    mov     r2, #0x3000
24: ldr     r3, [r5], #4
    str     r3, [r0], #4
    subs    r2, r2, #4
    bne     24b
#else
    /* 3. 62 張表(SA 每檔等寬 31 + GA 文件 709 LUT 31;rv_tables.py):以相對中灰檔數取樣、線性內插
     *    x = LOG + WQ[k] + 8(Q16,< 0 夾 0);t = x·10;j = t >> 16、f = t & 0xFFFF;
     *    j ≥ NS − 1 → SAMP[NS−1];否則 SAMP[j] + ((SAMP[j+1] − SAMP[j])·f >> 16) */
    ldr     r5, blob_rel1
11: add     r5, pc, r5              @ r5 = blob(adr 距離不夠,用 PC 相對常數)
    LDA     r0, TDATA_OFF
    add     r5, r5, r0              @ r5 = LOG[]
    add     r6, r5, #0x2000         @ r6 = WQ[62]
    ldr     r7, [r6, #NREC * 4]     @ r7 = B
    mov     r8, #0                  @ k
    mov     r9, r4                  @ 目的
1:  LDA     r10, SAMP_OFF
    add     r10, r6, r10
    LDA     r0, NSP * 2
    mla     r10, r8, r0, r10        @ r10 = SAMP[k]
    ldr     r3, [r6, r8, lsl #2]    @ r3 = WQ[k]
    add     r3, r3, #0x80000        @ + 8(− S0)
    mov     r11, #0                 @ i
2:  ldr     r0, [r5, r11, lsl #2]
    adds    r0, r0, r3              @ x
    movmi   r0, #0
    add     r0, r0, r0, lsl #2
    lsl     r0, r0, #1              @ t = x·10
    lsr     r1, r0, #16             @ j
    LDA     ip, NS - 1
    cmp     r1, ip
    movhs   r1, ip
    movhs   r0, #0                  @ j 夾到最後一點、f = 0
    add     r2, r10, r1, lsl #1
    ldrh    ip, [r2]                @ y[j]
    ldrh    r2, [r2, #2]            @ y[j+1]
    sub     r2, r2, ip
    lsl     r0, r0, #16
    lsr     r0, r0, #16             @ f
    mul     r2, r2, r0
    add     r1, ip, r2, asr #16     @ v
    cmp     r1, #0
    movlt   r1, #0
    cmp     r1, r7
    movgt   r1, r7
    strh    r1, [r9], #2
    add     r11, r11, #1
    cmp     r11, #2048
    blo     2b
    add     r8, r8, #1
    cmp     r8, #NREC
    blo     1b

#endif
    /* 4. 插槽:11 × {0, ISO 100 表} */
    LDA     r0, OFF_SLOTS
    add     r10, r4, r0             @ r10 = slots
    mov     r0, r10
    mov     r1, #0
    mov     r2, #11
3:  str     r1, [r0], #4
    str     r4, [r0], #4
    subs    r2, r2, #1
    bne     3b

    /*    mode 表副本,第 35 筆 base = N = ((slots − CURVE_ENTRIES) asr 3) + 5 */
    LDA     r0, OFF_MODE
    add     r11, r4, r0             @ r11 = mode_copy
    LDA     r1, MODE_TAB
    mov     r0, r11
    mov     r2, #0x24 * 2
4:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #1
    bne     4b
    LDA     r1, CURVE_ENTRIES
    sub     r1, r10, r1
    asr     r1, r1, #3
    add     r1, r1, #5
    str     r1, [r11, #0x11C]

    /* 5. 常駐程式與參數 */
    LDA     r0, OFF_RES
    add     r9, r4, r0              @ r9 = 常駐
    ldr     r1, blob_rel2
12: add     r1, pc, r1              @ r1 = blob
    mov     r0, r9
    LDA     r2, RES_LEN
5:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #4
    bne     5b
    str     r4, [r9, #0x10]         @ tab_base
    str     r10, [r9, #0x14]        @ slots
    str     r11, [r9, #0x18]        @ mode_copy
#ifdef FL_DEFAULT
    /* Read preferences before exposing menu hooks. CommonSave +0x210 is
     * outside Fast's +0x028..200 and OpenGate's +0x290 word. Never seed it
     * during installation: native boot callbacks must not erase a choice. */
    mov     r0, #(FL_DEFAULT - 1)
    str     r0, [r9, #0x1A4]
    LDA     r1, LV_SAVE
    ldr     r0, [r1]
    bic     r1, r0, #7
    LDA     r2, LV_MAGIC
    cmp     r1, r2
    bne     lv_loaded
    and     r1, r0, #3
    cmp     r1, #2
    bhi     lv_loaded
    str     r1, [r9, #0x1A4]
    tst     r0, #4
    moveq   r0, #5                 @ saved disabled: leave native color alone
    streq   r0, [r9, #0x50]
lv_loaded:
#endif
#ifndef LV_BOOST
    add     r1, r6, #NREC * 4 + 4   @ THR[]
    add     r0, r9, #0x1C
    mov     r2, #NTHR
6:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #1
    bne     6b

#endif
    /*    色彩模式 {enum, gui}:原廠 16 筆 + {0xC, 16} */
    LDA     r1, GUI_TAB
    add     r0, r9, #P_GUI
    mov     r2, #32
7:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #1
    bne     7b
    mov     r3, #0xC
    mov     r2, #16
8:  str     r3, [r0], #4
    str     r2, [r0], #4
    add     r2, r2, #1
    cmp     r2, #17
    blo     8b

    /*    色彩矩陣表副本(OFF 那筆換成校色矩陣) */
    LDA     r0, OFF_MAT
    add     r0, r4, r0              @ r0 = 副本
    str     r0, [r9, #P_MAT]
    LDA     r1, MAT_TAB
    LDA     r2, MAT_LEN
20: ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #4
    bne     20b
    LDA     r1, MAT_OFF_REC - MAT_TAB
    ldr     r0, [r9, #P_MAT]
    add     r0, r0, r1
    ldr     r1, mat_rel2
23: add     r1, pc, r1              @ r1 = mat_new
    mov     r2, #6
21: ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #1
    bne     21b

    /* 6. veneer(五個,取自 cave 的 bump 配置器) */
    LDA     r7, CAVE_BUMP
    ldr     r5, [r7]                @ r5 = veneer 起點
    add     r1, r5, #NVEN * 8
    LDA     r2, CAVE_ARENA_END
    cmp     r1, r2
    bhi     9f                      @ cave 滿了:不裝(記憶體留著,重開機釋放)
    str     r1, [r7]
    LDA     r2, VENEER_LDR
    VEN     0, STUB_GS
    VEN     1, STUB_DG
    VEN     2, STUB_MA
    VEN     3, STUB_MB
    VEN     4, STUB_MC
    LDA     r0, STUB_FV              @ veneer 5:Thumb,ldr.w pc 跳 ARM stub(bit0 = 0)
    add     r0, r9, r0
    LDA     r1, THUMB_VENEER
    str     r1, [r5, #40]
    str     r0, [r5, #44]
    LDA     r2, VENEER_LDR
    VEN     6, STUB_ML
    VEN     7, STUB_EF
    VEN     8, STUB_EN
    VEN     9, STUB_SA
    VEN     10, STUB_SN
    VEN     11, STUB_MJ
    VEN     12, STUB_ZC
    VEN     13, STUB_ZS
    VEN     14, STUB_ZNC
    VEN     15, STUB_ZNS

    LDA     ip, F_DCACHE            @ 表(DMA 讀)、常駐程式、veneer
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip

    /* getter:表位址 = 常駐 + P_GUI(movw/movt r2),筆數 17 */
    add     r3, r9, #P_GUI
    MOVWT_R2 GET_MOVW, GET_MOVT
    /* ColorButtonMenu 開/關 → stub_mo/stub_mx(記錄選單開著;SA/GA 字形的條件) */
    LDA     r0, STUB_MO
    add     r0, r9, r0
    LDA     r1, CBM_VT_V25
    str     r0, [r1]
    LDA     r0, STUB_MX
    add     r0, r9, r0
    LDA     r1, CBM_VT_V26
    str     r0, [r1]
#ifndef LV_BOOST
    /* DNG writer:OFF 常數位址 → 常駐 cm_buf(CM1)、cm_buf + 72(CM2) */
    LDA     r3, CMBUF
    add     r3, r9, r3
    MOVWT_R2 DNG_CM1_MOVW, DNG_CM1_MOVT
    add     r3, r3, #72
    MOVWT_R2 DNG_CM2_MOVW, DNG_CM2_MOVT
#endif
    LDA     r1, GET_COUNT
    LDA     r0, 0xE3A02011          @ mov r2, #17
    str     r0, [r1]

    ARM     SITE_A, 0
    ARM     SITE_B, 1
    ARM     SITE_MA1, 2
    ARM     SITE_MA2, 2
    ARM     SITE_MA3, 2
    ARM     SITE_MB, 3
    ARM     SITE_MC, 4
    ARM     SITE_ML, 6
    ARM     SITE_EF, 7
    ARM     SITE_EN, 8
    ARM     SITE_SA_AJ, 9
    ARM     SITE_SA_FIX, 9
    ARM     SITE_SN_FIX, 10
    ARM     SITE_SN_AJ, 10
    ARM     SITE_MJ, 11
    ARM     SITE_EN_FIX, 8
    ARM     SITE_ZC_AJ, 12
    ARM     SITE_ZC_FIX, 12
    ARM     SITE_ZS_AJ, 13
    ARM     SITE_ZS_FIX, 13
    ARM     SITE_ZNC_FIX, 14
    ARM     SITE_ZNC_AJ, 14
    ARM     SITE_ZNS_FIX, 15
    ARM     SITE_ZNS_AJ, 15

    /* ColorButtonMenu 頁面(開啟時才解析,開機時改即可) */
    ldr     r3, page_rel2
16: add     r3, pc, r3
17: ldr     r1, [r3], #12
    cmp     r1, #0
    beq     18f
    ldr     r0, [r3, #-4]
    str     r0, [r1]
    b       17b
18:

    /* H1:Thumb B.W H1_SITE → veneer 5。off = veneer − (site + 4)
     * hw1 = 0xF000 | S<<10 | off[21:12]
     * hw2 = 0x9000 | J1<<13 | J2<<11 | off[11:1],J1 = ~I1 ^ S,J2 = ~I2 ^ S(I1 = off[23],I2 = off[22]) */
    LDA     r1, H1_SITE
    add     r0, r5, #40
    sub     r0, r0, r1
    sub     r0, r0, #4              @ r0 = off
    lsr     r2, r0, #31             @ S
    lsr     r3, r0, #12
    LDA     ip, 0x3FF
    and     r3, r3, ip
    orr     r3, r3, r2, lsl #10
    orr     r3, r3, #0xF000         @ hw1
    lsr     ip, r0, #23
    and     ip, ip, #1              @ I1
    eor     ip, ip, #1
    eor     ip, ip, r2              @ J1
    lsr     r4, r0, #22
    and     r4, r4, #1              @ I2
    eor     r4, r4, #1
    eor     r4, r4, r2              @ J2
    lsr     r0, r0, #1
    LDA     r2, 0x7FF
    and     r0, r0, r2              @ imm11
    orr     r0, r0, ip, lsl #13
    orr     r0, r0, r4, lsl #11
    orr     r0, r0, #0x9000         @ hw2
    orr     r0, r3, r0, lsl #16     @ 小端:hw1 在低位
    str     r0, [r1]

    LDA     ip, F_DCACHE
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip

#ifdef FL_DEFAULT
    /* Same task descriptor ABI as the shared USB worker. The entry and all
     * state live in our allocation, never in staging. Do not wait here. */
    sub     sp, sp, #32
    mov     r0, #0
    str     r0, [sp]
    str     r0, [sp, #24]
    str     r0, [sp, #28]
    mov     r0, #0x41
    str     r0, [sp, #4]
    LDA     r0, FL_START
    add     r0, r9, r0
    str     r0, [sp, #8]
    mov     r0, #28
    str     r0, [sp, #12]
    mov     r0, #0x2000
    str     r0, [sp, #16]
    LDA     r0, 0x4F544146          @ FATO (Focus Auto)
    str     r0, [sp, #20]
    mov     r0, sp
    LDA     ip, 0xC0016A58
    blx     ip
    add     sp, sp, #32
    str     r0, [r9, #0x54]        @ task id / creation error
    cmp     r0, #0
    ble     9f
    mov     r1, #0
    LDA     ip, 0xC0016BC0
    blx     ip
    str     r0, [r9, #0x58]        @ task start result
#endif

9:  add     sp, sp, #16
    mov     r0, #0
    pop     {r4-r11, ip, pc}

    .align  2
page_rel1:  .word page_tab - (13b + 8)
page_rel2:  .word page_tab - (16b + 8)
#include "rv_page.inc"
mat_rel1:   .word mat_stock - (22b + 8)
mat_rel2:   .word mat_new - (23b + 8)
#include "rv_mat.inc"
blob_rel1:  .word blob - (11b + 8)
blob_rel2:  .word blob - (12b + 8)
blob:
    /* build_rawview.py 在這裡接上:常駐程式 | 表格資料 */
