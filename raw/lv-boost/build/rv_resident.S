.syntax unified
.arm
.text
/* ============================================================================
 * rv_resident — rawview 常駐程式(位置無關;launcher 複製到自己配置的記憶體)
 * ============================================================================
 *
 * 參數區(launcher 填,host／選單 hook 改 flag):
 *   +0x00 magic      'RVW1'(host 經 site A → veneer → 本區找到)
 *   +0x04 flag       RAW 模式要求(選單 hook／host 寫)
 *   +0x08 eff        實際生效(stub_gs 算):flag && 色彩模式 OFF && CinemaDNG && 12-bit
 *   +0x0C last_rel   上次選表的相對增益
 *   +0x10 tab_base   62 張表(A 31 + B 31),各 0x1000,ISO 低→高
 *   +0x14 slots      11 格插槽(每格 8 bytes,+4 是表位址)
 *   +0x18 mode_copy  mode→tone 表的 RAM 副本(OFF 那筆指向插槽)
 *   +0x1C thr[30]    相對增益門檻
 *   +0x94 pend       選單剛經 GUI 轉換:GUI 15 → 16(OFF)、16 → 17(RAW),其他 0;setter 消化後清 0
 *   +0x98 guitab     色彩模式 {enum, gui} × 17(原廠 16 筆 + {0xC, 16});getter C06C07C0 改指這裡。
 *                    index 15/16 都是 enum 0xC,GUI 值排列「目前生效的在前」
 *   +0x120 dbg_idx / +0x124 dbg 環(8 × 16)
 *   +0x1A4 lat       0 = SA(Latitude — Stop Aligned,曲線 A)、1 = GA(Latitude — Gray Aligned,曲線 B);右側上下框
 *   +0x1A8 mat_copy  色彩矩陣表(root+0x08)的 RAM 副本(launcher 填);OFF 那筆由 stub_gs 依飽和度改寫
 *   +0x1AC key_app   已套用的 lat | sat << 1(stub_gs 偵測變更)
 *   +0x1B0 sat       AEL 飽和度 UI 0..5(捲動即時,AJ)→ 矩陣程度(build/rv_color.sat_k:0 = 不套、5 = 100 %)
 *   +0x1B4 sat_fix   已確認(按 OK,FIX)的飽和度;取消時頁面以它重設 AJ
 *   +0x1B8 menu      COLOR 鍵選單開著(stub_mo/stub_mx,ColorButtonMenu vtable v25/v26)
 *   +0x1BC cur       COLOR 選單游標所在 GUI 列(stub_ma/mj 記錄)
 *   +0x1C0 sat_tab   6 筆 × 24 B:OFF 筆 {0x24, 9 × s16, pad},UI 0..5
 *   cm_buf           2 × 9 double(CM1、CM2 的 C;8-byte 對齊):DNG writer FUN_c02c4a50 的 OFF 分支經 movw/movt 改讀這裡
 *   cm_tab           6 級 × 144 B(build/rv_dngcm.py;第 0 級 = 原廠 OFF 常數、第 5 級 = 原廠非 OFF 常數)
 *
 * stub_gs 取代 0xC0313244 `ldr r2,[r5,#0xc]`(FUN_c03131e0;r5 = helper,r6 = 這次的相對增益,r4 使用中)
 *   只在待機(gain_state 0)做事:
 *   1. 算 eff;eff、lat 或 sat 改變時:切換 root+0x70(副本 ↔ 原廠);生效時把 sat_tab[sat] 抄進矩陣副本的 OFF 筆、
 *      root+0x08 指副本,否則原廠;cm_buf = cm_tab[生效 ? sat : 0](錄下的 CDNG ColorMatrix1/2 與 LCD 同程度;
 *      只在待機時改 → 錄影中不變);清 ctx0 快取鍵、強制重選表。原廠每次 PQ 更新都從 root+0x08 重查矩陣
 *      (2026-09-25 上機:換指標 1 s 內硬體即更新)。
 *   2. eff 開:相對增益變了就把插槽指到對應的表(GA → B 組 +31)並清快取鍵;r2 = 7(12-bit 錄影的增益規則)。
 *   只寫資料、不呼叫函式;sp 8-byte 對齊;r4/r5 自行保存。
 * stub_dg 取代 0xC032F728 `ldr r6,[ip]`:eff 開且 bank 0 → RAW_CORR 數位增益 1×(0x400)。
 *   sp 未對齊 → leaf,只用 r0。
 * 選單(第 17 列 RAW = 原廠 OFF 0xC + flag):
 * stub_ma 取代三個 `bl C06C0718`(GUI→enum;選單 C056D028、COLOR 鍵 C0568950、QS C05818B8):
 *   r1 = GUI 列號;記下 pend(15 → 16、16 → 17、其他 → 0),再尾跳原函式。
 * stub_mj 同上,取代 COLOR 鍵選單「預覽」回呼(CM_COLAJ_ColorMode,FUN_c0568988)的 `bl C06C07E8`(C05689A8)。
 *   游標移動即時套用、退出即選定走這條(2026-09-25 上機:少了它,第 17 列只有按 OK 才選定、退出不會)。
 * stub_mb 取代 `bl C06C0768`(enum→GUI;CM_COLFIX_ColorMode 通知 C0595734):結果 15 且 flag → 16。
 * stub_mc 取代 C0075CF4 `cmp sl,r6`(所有選單 enum 共用的 setter FUN_c0075be8;r4 = item,sl = 舊值,r6 = 新值):
 *   item 是色彩模式(C31ACDC4)時:新值 ≠ OFF → flag 0;pend 16 → flag 0;pend 17 → flag 1;
 *   其餘(沒經 GUI、值仍是 OFF 的重複寫入,例如按 OK／離開選單時韌體再寫一次)→ 不變。
 *   消化 pend;生效列(flag ? 16 : 15)改變時:guitab index 15/16 的 GUI 值改成「生效列在前」,
 *   讓任何 enum→GUI 路徑(第一個符合)都得到生效列,GUI 15/16 → OFF 不變;並強制「不相等」讓原廠發通知。
 *   (2026-09-25 上機:RAW 一開,韌體經未知的 enum→GUI 路徑以 15 重新同步游標 → 又觸發選 OFF)
 * stub_ml 取代 `bl C06C0768`(LV_ColorMode C059DA1C):結果 16 → 15(16–25 是單色調色圖示)。
 * RAW 列的調整(flag 開時;原廠對 OFF(0xC)的寫入本來就擋掉,這裡只換「UI 值 ↔ 存值」的換算,原廠寫入照走):
 * stub_ef 取代 `bl C06C0D20`(C0568A3C,右側上下框回呼 FUN_c0568a00;r1 = 框上的 UI 值):
 *   等於目前顯示值(SA = 0、GA = 1;使用者 2026-09-25)→ 不動;大 → GA、小 → SA,並以 FUN_c0593f30(發布 UI 變數,原廠通知同一路)
 *   把 CM_COLAJ_Effect 與 CM_COLFIX_Effect 設回 0 / 1(框只停在 0、1;FIX 一致 → 下次開選單複製過來不會誤切);回 0。
 * stub_en 取代兩個 `bl C06C0D70`(通知 v87 C0595908 = CM_COLAJ_Effect、v82 C05957B0 = CM_COLFIX_Effect;r7 = 模式):
 *   模式 0xC → 回 0 / 1。(2026-09-25 上機 fs2-7:少了 v82,每次開選單 FIX 值 0 複製到 AJ → SA/GA 被切換)
 * stub_sa 取代兩個 `bl C06C1060`(飽和度回呼:AJ C056D5F8 捲動、FIX C056D498 按 OK;r1 = UI 值):
 *   夾到 0..5 存 sat;lr 是 FIX(C056D49C)時也存 sat_fix;捲動(AJ)被夾時以 FUN_c0593f30 把 CM_COLAJ_Saturation
 *   設回夾後的值(刻度停在 0..5;不發布 FIX,以免變成「確認」);回 0。
 * stub_sn 取代兩個 `bl C06C10B0`(通知 v85 C059588C = COLFIX、v90 C05959E4 = COLAJ):回 sat_fix / sat。
 *   四個都在呼叫邊界:r0–r3、ip 可用,不用 stack;flag 關時尾跳原換算函式(lr 不動)。
 *   事件紀錄:dbg 環(8 筆 × {tag, a, b, flag})供 host 讀。
 *   該處 sp 未對齊 → leaf;r0–r3、ip 可用;回傳時旗標要等同原本的比較結果。
 * 以上都經 veneer(`ldr pc,[pc,#-4]`)以 `bl` 進入,原指令在 stub 裡重做。
 *
 * UI(ColorButtonMenu 第 17 列):
 * 對比度/清晰度鎖 0(使用者 2026-09-25;RAW 下原廠本來就不套用 OFF 的調整值,鎖住避免誤會):
 * stub_zc/stub_zs 取代 AEL 頁對比/清晰度回呼的 `bl C06C0EC0` / `bl C06C0F90`(AJ C056D548/C056D5A0、FIX C056D3E8/C056D440):
 *   RAW 時回 0;捲動(AJ)到非 0 時發布 CM_COLAJ_Contrast/Sharpness = 0 拉回刻度。
 * stub_znc/stub_zns 取代通知 v83/v88(C059581C/C0595974,`bl C06C0F10`)與 v84/v89(C0595854/C05959AC,`bl C06C0FE0`):RAW 時回 0。
 * stub_mo/stub_mx:ColorButtonMenu vtable v25/v26(0xC0D119FC/0xC0D11A00)改指這裡:記下選單開/關,再尾跳原函式。
 * stub_fv 取代 Thumb C05E5BEC `adds r0,r0,r1; str r0,[r5,#4]`(FUN_c05e5bb8 取檔位置;r0 = offset,r1 = base,
 *   r5 = view,[sp] = 檔案大小)。位址是三個 ListColorButtonMenu CSV 或 set_flash_1.xci(第 17 列借用的圖示名)的
 *   原廠位址時換成本區的新版(CSV／RAW 圖示,build/rv_raw_icon.xci)並改 [sp];
 *   條件成立(RAW 生效、COLOR 選單開著、游標在 RAW 列)時另查 gltab:右側框的 font_menu_LB ± / 0 / + / 1
 *   換成 S / A / G / A(框顯示 0 = SA、1 = GA;字形每次重畫都重新載入,2026-09-25 上機 gui image log)。
 *   font_menu_LB 是通用選單字型 → 只在上述條件下換。
 *   寫回 view+4,再跳回 Thumb C05E5BF1。由 Thumb veneer(ldr.w pc,[pc,#0])以 B.W 進入(lr 不動);
 *   可用 r1–r3、ip,旗標無用。
 * ========================================================================== */

.equ ROOT_P70,      0xC2F1A0D4
.equ ROOT_P70_ORIG, 0xC0B3D670
.equ ROOT_P08,      0xC2F1A06C      /* 色彩矩陣表 {指標, 筆數} */
.equ ROOT_P08_ORIG, 0xC0B39CC8
.equ KEY_CTX0,      0xC2F19D44
.equ SET_SEL,       0xC31B954C      /* byte:0 → bank A,否則 bank B */
.equ SET_BANK_A,    0xC31B32BC
.equ SET_BANK_B,    0xC31B8B84
.equ OFF_COLOR,     0x12C           /* 色彩模式(選單 enum,OFF = 0xC) */
.equ OFF_FMT,       0x784           /* 錄影格式(0 = CinemaDNG) */
.equ OFF_QUAL,      0x788           /* CinemaDNG 位深(0 = 12-bit) */
.equ NTHR,          30

#ifdef LV_BOOST
#include "fl_fv.inc"
#else
#include "rv_fv.inc"
#endif
.equ P_MAGIC, 0x00
.equ P_FLAG,  0x04
.equ P_EFF,   0x08
.equ P_LAST,  0x0C
.equ P_TAB,   0x10
.equ P_SLOTS, 0x14
.equ P_MODE,  0x18
.equ P_THR,   0x1C
.equ P_PEND,  0x94
.equ P_GUI,   0x98
.equ NGUI,    17
.equ P_DBGI,  0x120
.equ P_DBG,   0x124
.equ P_VAR,   0x1A4
.equ P_MAT,   0x1A8
.equ P_VAPP,  0x1AC
.equ P_SAT,   0x1B0
.equ P_SATF,  0x1B4
.equ P_MENU,  0x1B8
.equ P_CUR,   0x1BC
.equ P_SATTAB, 0x1C0
.equ ZC_CONV, 0xC06C0EC0             /* 對比 UI → 存值 */
.equ ZS_CONV, 0xC06C0F90             /* 清晰 UI → 存值 */
.equ ZNC_CONV, 0xC06C0F10            /* 對比 存值 → UI */
.equ ZNS_CONV, 0xC06C0FE0            /* 清晰 存值 → UI */
.equ ZC_AJ_RET, 0xC056D54C
.equ ZS_AJ_RET, 0xC056D5A4
.equ S_COLAJ_CONTRAST, 0xC2DF0238
.equ S_COLAJ_SHARP,    0xC2DF024C
.equ CBM_V25, 0xC05687E0            /* UicGuiMenuColorButtonMenu v25:開啟(註冊回呼) */
.equ CBM_V26, 0xC0568888            /*                             v26:關閉 */
.equ MAT_OFF, 34 * 24               /* 矩陣表第 34 筆 = OFF */
.equ EF_CONV, 0xC06C0D20            /* Effect UI → 存值 */
.equ EN_CONV, 0xC06C0D70            /* Effect 存值 → UI */
.equ SA_CONV, 0xC06C1060            /* 飽和度 UI → 存值 */
.equ SN_CONV, 0xC06C10B0            /* 飽和度 存值 → UI */
.equ SA_FIX_RET, 0xC056D49C         /* FIX 回呼的 bl 之後 */
.equ SN_FIX_RET, 0xC0595890         /* v85(COLFIX)的 bl 之後 */
.equ PUBLISH,    0xC0593F30         /* (未用, 名稱, 值):發布 UI 變數 */
.equ S_COLAJ_EFFECT,  0xC2DF0210
.equ S_COLFIX_EFFECT, 0xC2DF01A8
.equ S_COLAJ_SAT,     0xC2DF0260
.equ GUI_TO_ENUM, 0xC06C0718
.equ GUI_TO_ENUM_AJ, 0xC06C07E8
.equ ENUM_TO_GUI, 0xC06C0768
.equ COLOR_ITEM,  0xC31ACDC4

/* reg = params(位置無關;adr 在常駐變大後距離不夠) */
.macro PADR reg
    ldr     \reg, 91f
90: add     \reg, pc, \reg
    b       92f
91: .word   params - (90b + 8)
92:
.endm

params:
#ifdef LV_BOOST
    .ascii  "FLF1"
#else
    .ascii  "RVW1"
#endif
    .word   0, 0, 0, 0, 0, 0
    .space  NTHR * 4
    .word   0                       /* pend */
    .space  NGUI * 8                /* guitab(launcher 填) */
dbg_idx:
    .word   0                       /* +0x120 事件計數 */
dbg:
    .space  8 * 16                  /* +0x124 8 筆 × {tag, a, b, c} */
    .word   0                       /* +0x1A4 lat(0 = SA) */
    .word   0                       /* +0x1A8 mat_copy */
    .word   0                       /* +0x1AC key_app */
    .word   0                       /* +0x1B0 sat(UI 0 = 100 %) */
    .word   0                       /* +0x1B4 sat_fix */
    .word   0                       /* +0x1B8 menu */
    .word   0                       /* +0x1BC cur */
#include "rv_sat.inc"
.align 3
#include "rv_dngcm.inc"             /* cm_buf(初值 = 第 0 級 = 原廠 OFF 常數)、cm_tab */

#ifdef LV_BOOST
/* LV Boost does not alter gain_state, RAW_CORR, matrices or DNG metadata.
 * Site A is used only to invalidate the native preview tone cache on changes.
 * Application status: native status/get app_current reads C303384C+1F8.
 * Stable STILL live view reports app 2, attribute 1 (SetRecMode=0,
 * MONIT1_60). App 5 also occurs around the UI/USB session. CINE attribute
 * is 2. Attribute 0 observed during transition is NOT an active STILL view.
 * Both accepted applications must pass the attribute-1 check.
 * Hardware validation of context/AE/JPEG isolation remains required. */
.macro FL_STILL reg
    ldr     \reg, =0xC3033A44
    ldr     \reg, [\reg]
    cmp     \reg, #2
    beq     .Lfl_attribute\@
    cmp     \reg, #5
    bne     .Lfl_still\@
.Lfl_attribute\@:
    ldr     \reg, =0xC3033A54
    ldr     \reg, [\reg]
    cmp     \reg, #1
.Lfl_still\@:
.endm
stub_gs:
    ldr     r2, [r5, #0xc]
    push    {r0, r1, r3, ip}
    mrs     r0, cpsr
    push    {r0}
    PADR    r3
    /* Focus-only diagnostics occupy unused threshold storage (+1C..48).
     * No firmware globals or image data are used as scratch. */
    ldr     r0, [r3, #0x1c]
    add     r0, r0, #1
    str     r0, [r3, #0x1c]
    ldr     r0, [r3, #P_FLAG]
    ldr     r1, =0xC3033A44
    ldr     r1, [r1]
    str     r1, [r3, #0x20]
    FL_STILL r1
    movne   r0, #0
    ldr     r1, [r3, #P_VAR]
    add     r1, r0, r1, lsl #1
    ldr     ip, [r3, #P_VAPP]
    cmp     ip, r1
    beq     1f
    str     r1, [r3, #P_VAPP]
    str     r0, [r3, #P_EFF]
    ldr     ip, =KEY_CTX0
    mvn     r1, #0
    str     r1, [ip]
1:  pop     {r0}
    msr     APSR_nzcvq, r0
    pop     {r0, r1, r3, ip}
    bx      lr

/* C02D2E50: native single-table path, after lookup and before descriptor
 * construction. Keep the original condition flags: the next two loads are NE.
 * r5 = context, fp = PQ color enum; only replace stock OFF in context 0. */
stub_dg:
    ldr     r1, [r0, #4]
    push    {r0, r2, r3, ip}
    mrs     r3, cpsr
    push    {r3}
    PADR    r3
    ldr     ip, [r3, #0x24]
    add     ip, ip, #1
    str     ip, [r3, #0x24]
    str     r5, [r3, #0x28]
    str     fp, [r3, #0x2c]
    str     r2, [r3, #0x30]
    str     r1, [r3, #0x34]
    ldr     ip, =0xC3033A44
    ldr     ip, [ip]
    str     ip, [r3, #0x38]
    ldr     ip, [r3, #P_FLAG]
    str     ip, [r3, #0x3c]
    ldr     ip, [r3, #P_VAR]
    str     ip, [r3, #0x40]
    ldr     ip, =0xC3033A54
    ldr     ip, [ip]
    str     ip, [r3, #0x4c]
    cmp     r5, #0
    bne     1f
    cmp     fp, #0x24
    bne     1f
    cmp     r2, #0
    bne     1f
    ldr     r3, =0xC09C3F34
    cmp     r1, r3
    bne     1f
    FL_STILL r3
    bne     1f
    PADR    r3
    ldr     ip, [r3, #P_FLAG]
    cmp     ip, #1
    bne     1f
    ldr     ip, [r3, #P_VAR]
    cmp     ip, #2
    bhi     1f
    ldr     r1, [r3, #P_TAB]
    add     r1, r1, ip, lsl #12
    ldr     ip, [r3, #0x44]
    add     ip, ip, #1
    str     ip, [r3, #0x44]
    str     r1, [r3, #0x48]
1:  pop     {r3}
    msr     APSR_nzcvq, r3
    pop     {r0, r2, r3, ip}
    bx      lr
#else
stub_gs:
    ldr     r2, [r5, #0xc]          /* 原指令 */
    cmp     r2, #0
    bxne    lr                      /* 不是待機:不動 */
    PADR    r3

    /* eff = flag && 色彩 OFF && CinemaDNG && 12-bit */
    mov     r0, #0
    ldr     ip, [r3, #P_FLAG]
    cmp     ip, #0
    beq     1f
    ldr     ip, =SET_SEL
    ldrb    ip, [ip]
    cmp     ip, #0
    ldreq   r1, =SET_BANK_A
    ldrne   r1, =SET_BANK_B
    ldr     ip, [r1, #OFF_COLOR]
    cmp     ip, #0xC
    bne     1f
    ldr     ip, [r1, #OFF_FMT]
    cmp     ip, #0
    bne     1f
    ldr     ip, [r1, #OFF_QUAL]
    cmp     ip, #0
    moveq   r0, #1
1:  ldr     r1, [r3, #P_VAR]        /* key = lat | sat << 1 */
    ldr     ip, [r3, #P_SAT]
    add     r1, r1, ip, lsl #1
    ldr     ip, [r3, #P_EFF]
    cmp     r0, ip
    ldreq   ip, [r3, #P_VAPP]
    cmpeq   r1, ip
    beq     2f
    str     r0, [r3, #P_EFF]        /* 生效狀態、lat 或 sat 改變:切 root 指標、矩陣、強制重選表 */
    str     r1, [r3, #P_VAPP]
    cmp     r0, #0
    ldrne   r1, [r3, #P_MODE]
    ldreq   r1, =ROOT_P70_ORIG
    ldr     ip, =ROOT_P70
    str     r1, [ip]
    ldr     r1, =ROOT_P08_ORIG
    cmp     r0, #0
    beq     7f
    push    {r4, r5}                /* 生效:sat_tab[sat] → 副本的 OFF 筆,root+0x08 → 副本 */
    ldr     r4, [r3, #P_SAT]
    cmp     r4, #5
    movhi   r4, #0                  /* 超出範圍(不該發生):不套 */
    add     r4, r4, r4, lsl #1      /* × 3 */
    add     r5, r3, #P_SATTAB
    add     r4, r5, r4, lsl #3      /* × 24 */
    ldr     r1, [r3, #P_MAT]
    add     r5, r1, #MAT_OFF
    mov     r0, #6
8:  ldr     ip, [r4], #4
    str     ip, [r5], #4
    subs    r0, r0, #1
    bne     8b
    pop     {r4, r5}
    mov     r0, #1
7:  ldr     ip, =ROOT_P08
    str     r1, [ip]
    push    {r4, r5}                /* DNG ColorMatrix:cm_buf = cm_tab[生效 ? sat : 0] */
    mov     r4, #0
    cmp     r0, #0
    ldrne   r4, [r3, #P_SAT]
    cmp     r4, #5
    movhi   r4, #0
    mov     r5, #144
    mul     r4, r4, r5
    ldr     ip, =cm_tab - params
    add     r4, r4, ip
    add     r4, r4, r3              /* 來源 */
    ldr     ip, =cm_buf - params
    add     r5, r3, ip              /* 目的 */
    mov     r1, #36
10: ldr     ip, [r4], #4
    str     ip, [r5], #4
    subs    r1, r1, #1
    bne     10b
    pop     {r4, r5}
    mov     r1, #0
    str     r1, [r3, #P_LAST]
    ldr     ip, =KEY_CTX0
    mvn     r1, #0
    str     r1, [ip]
2:  cmp     r0, #0
    bxeq    lr                      /* 不生效:原廠增益(r2 = 0) */

    ldr     r0, [r3, #P_LAST]
    cmp     r0, r6
    beq     5f
    str     r6, [r3, #P_LAST]
    push    {r4, r5}
    add     r4, r3, #P_THR
    mov     r1, #0
3:  ldr     ip, [r4, r1, lsl #2]
    cmp     r6, ip
    blo     4f
    add     r1, r1, #1
    cmp     r1, #NTHR
    blo     3b
4:  ldr     ip, [r3, #P_VAR]
    tst     ip, #1
    addne   r1, r1, #31             /* B 組 */
    ldr     r0, [r3, #P_TAB]
    add     r0, r0, r1, lsl #12     /* 表 k */
    ldr     r4, [r3, #P_SLOTS]
    mov     r1, #11
6:  str     r0, [r4, #4]
    add     r4, r4, #8
    subs    r1, r1, #1
    bne     6b
    ldr     r4, =KEY_CTX0
    mvn     r0, #0
    str     r0, [r4]
    pop     {r4, r5}
5:  mov     r2, #7                  /* movie_raw_12bit */
    bx      lr

stub_dg:
    ldr     r6, [ip]                /* 原指令 */
    ldr     r0, params + P_EFF
    cmp     r0, #0
    bxeq    lr
    cmp     r5, #0
    bxne    lr                      /* bank 1(拍照)不動 */
    mov     r6, #0x400              /* 1.0× */
    bx      lr

#endif

#ifdef FL_DEFAULT
/* One aligned word: versioned magic | enabled<<2 | level_index.
 * This is a settings RAM mirror, automatically saved by normal shutdown,
 * not a firmware patch to undo in the shared journal. No flash API here.
 * Skip native boot/apply callbacks until restore succeeds or the user acts. */
.macro LV_SAVE_SETTINGS
    push    {r0, r1, ip}
    ldr     r0, [r3, #0x50]
    cmp     r0, #1
    beq     .Lsave\@
    cmp     r0, #2
    bne     .Lsaved\@
.Lsave\@:
    ldr     r0, [r3, #P_VAR]
    cmp     r0, #2
    bhi     .Lsaved\@
    ldr     r1, [r3, #P_FLAG]
    and     r1, r1, #1
    orr     r0, r0, r1, lsl #2
    ldr     ip, =LV_MAGIC
    orr     r0, r0, ip
    ldr     ip, =LV_SAVE
    str     r0, [ip]
.Lsaved\@:
    pop     {r0, r1, ip}
.endm
#endif

stub_mj:
    ldr     ip, =GUI_TO_ENUM_AJ
    b       1f
stub_ma:
    ldr     ip, =GUI_TO_ENUM
1:  push    {ip}                    /* 尾跳目標 */
    PADR    r3
    str     r1, [r3, #P_CUR]        /* 游標所在 GUI 列(SA/GA 字形替換的條件之一) */
#ifdef FL_DEFAULT
    /* An explicit menu selection wins over the pending startup default. */
    mov     r2, #2
    str     r2, [r3, #0x50]
#endif
    sub     r2, r1, #15
    cmp     r2, #2
    addlo   r2, r1, #1              /* GUI 15/16 → pend 16/17 */
    movhs   r2, #0
    str     r2, [r3, #P_PEND]
    ldr     ip, [r3, #P_DBGI]       /* dbg:{'M', gui, pend, flag} */
    and     r2, ip, #7
    add     ip, ip, #1
    str     ip, [r3, #P_DBGI]
    add     r2, r3, r2, lsl #4
    add     r2, r2, #P_DBG
    mov     ip, #0x4D
    str     ip, [r2]
    str     r1, [r2, #4]
    ldr     ip, [r3, #P_PEND]
    str     ip, [r2, #8]
    ldr     ip, [r3, #P_FLAG]
    str     ip, [r2, #12]
    pop     {pc}                    /* 尾跳:lr 仍指回呼叫者;r0/r1 未動 */

stub_mb:
    push    {r4, lr}
    ldr     ip, =ENUM_TO_GUI
    blx     ip
    cmp     r0, #15
    bne     1f
    ldr     r1, params + P_FLAG
    cmp     r1, #0
    movne   r0, #16
1:  pop     {r4, pc}

stub_mc:
    ldr     ip, =COLOR_ITEM
    cmp     r4, ip
    bne     9f
    PADR    r3
    ldr     r1, [r3, #P_PEND]
    mov     r2, #0
    str     r2, [r3, #P_PEND]
    ldr     r0, [r3, #P_FLAG]       /* r0 = 舊生效列 */
    cmp     r0, #0
    movne   r0, #16
    moveq   r0, #15
    cmp     r1, #16                 /* pend 16 = 選 OFF */
    moveq   r2, #0
    streq   r2, [r3, #P_FLAG]
    cmp     r1, #17                 /* pend 17 = 選 RAW */
    moveq   r2, #1
    streq   r2, [r3, #P_FLAG]
    cmp     r6, #0xC
    movne   r2, #0                  /* 新值不是 OFF:一律清 */
    strne   r2, [r3, #P_FLAG]
#ifdef FL_DEFAULT
    LV_SAVE_SETTINGS
#endif
    ldr     r2, [r3, #P_FLAG]       /* r2 = 新生效列 */
    cmp     r2, #0
    movne   r2, #16
    moveq   r2, #15
    ldr     ip, [r3, #P_DBGI]       /* dbg:{'C'|old<<8, new, 舊生效列, 新生效列} */
    and     r1, ip, #7              /* r1(pend)已用完,拿來當紀錄位置 */
    add     ip, ip, #1
    str     ip, [r3, #P_DBGI]
    add     r1, r3, r1, lsl #4
    add     r1, r1, #P_DBG
    mov     ip, #0x43
    orr     ip, ip, sl, lsl #8
    str     ip, [r1]
    str     r6, [r1, #4]
    str     r0, [r1, #8]
    str     r2, [r1, #12]
    cmp     r0, r2
    beq     9f
    add     r1, r3, #P_GUI + 15 * 8 + 4 /* 生效列改變:guitab index 15/16 的 GUI = 生效列在前 */
    str     r2, [r1], #8
    mov     ip, #15
5:  cmp     ip, r2
    strne   ip, [r1], #8
    add     ip, ip, #1
    cmp     ip, #NGUI
    blo     5b
#ifdef LV_BOOST
    ldr     r1, =KEY_CTX0
    mvn     ip, #0
    str     ip, [r1]
#endif
    movs    r0, #1                  /* Z = 0 → 原廠走「值改變」路徑、發通知 */
    bx      lr
9:  cmp     sl, r6                  /* 原指令 */
    bx      lr

stub_ml:
    push    {r4, lr}
    ldr     ip, =ENUM_TO_GUI
    blx     ip
    cmp     r0, #16
    moveq   r0, #15                 /* LV_ColorMode:16–25 是單色調色圖示 */
    pop     {r4, pc}

stub_ef:
    PADR    r3
    ldr     ip, [r3, #P_FLAG]
    cmp     ip, #0
    beq     9f
    ldr     r2, [r3, #P_VAR]        /* 目前顯示值 = lat:SA = 0、GA = 1 */
#ifdef LV_BOOST
    add     r2, r2, #1             /* displayed values +1 / +2 / +3 */
#endif
    cmp     r1, r2
    beq     5f                      /* 等於顯示值(含我們自己發布的回呼):不動 */
#ifdef LV_BOOST
    sub     ip, r1, #1
    cmp     ip, #0
    movlt   ip, #0
    cmp     ip, #2
    movgt   ip, #2
#else
    movgt   ip, #1                  /* 往上 → GA */
    movlt   ip, #0                  /* 往下 → SA */
#endif
    str     ip, [r3, #P_VAR]
#ifdef FL_DEFAULT
    LV_SAVE_SETTINGS
#endif
#ifdef LV_BOOST
    ldr     r0, =KEY_CTX0
    mvn     r1, #0
    str     r1, [r0]
#endif
    push    {r4, lr}
    mov     r4, ip                  /* r4 = 新顯示值 */
#ifdef LV_BOOST
    add     r4, r4, #1
#endif
    mov     r0, #0
    ldr     r1, =S_COLAJ_EFFECT
    mov     r2, r4
    ldr     ip, =PUBLISH
    blx     ip
    mov     r0, #0
    ldr     r1, =S_COLFIX_EFFECT
    mov     r2, r4
    ldr     ip, =PUBLISH
    blx     ip
    pop     {r4, lr}
5:  mov     r0, #0
    bx      lr
9:  ldr     pc, =EF_CONV

stub_en:
    PADR    r3
    ldr     ip, [r3, #P_FLAG]
    cmp     ip, #0
    beq     9f
    cmp     r7, #0xC
    bne     9f
    ldr     r0, [r3, #P_VAR]        /* SA → 0、GA → 1 */
#ifdef LV_BOOST
    add     r0, r0, #1
#endif
    bx      lr
9:  ldr     pc, =EN_CONV

stub_sa:
    PADR    r3
    ldr     ip, [r3, #P_FLAG]
    cmp     ip, #0
    beq     9f
    mov     r2, r1                  /* r2 = 原值 */
    cmp     r1, #0
    movlt   r1, #0                  /* 夾到 0..5 */
#ifdef LV_BOOST
    mov     r1, #0
#else
    cmp     r1, #5
    movgt   r1, #5
#endif
    str     r1, [r3, #P_SAT]
    ldr     ip, =SA_FIX_RET
    cmp     lr, ip
    streq   r1, [r3, #P_SATF]       /* 按 OK:確認值 */
    beq     5f
    cmp     r1, r2
    beq     5f
    push    {r4, lr}                /* 捲動超出 0..5:刻度拉回 */
    mov     r0, #0
    mov     r2, r1
    ldr     r1, =S_COLAJ_SAT
    ldr     ip, =PUBLISH
    blx     ip
    pop     {r4, lr}
5:  mov     r0, #0
    bx      lr
9:  ldr     pc, =SA_CONV

stub_sn:
    PADR    r3
    ldr     ip, [r3, #P_FLAG]
    cmp     ip, #0
    beq     9f
    ldr     ip, =SN_FIX_RET
    cmp     lr, ip
    ldreq   r0, [r3, #P_SATF]       /* CM_COLFIX_Saturation */
    ldrne   r0, [r3, #P_SAT]        /* CM_COLAJ_Saturation */
    bx      lr
9:  ldr     pc, =SN_CONV

/* RAW 時回 0;lr == aj_ret 且 r1 ≠ 0 → 發布 name = 0。否則尾跳 conv */
.macro ZLOCK conv, aj_ret, name
    PADR    r3
    ldr     ip, [r3, #P_FLAG]
    cmp     ip, #0
    beq     9f
    ldr     ip, =\aj_ret
    cmp     lr, ip
    bne     5f
    cmp     r1, #0
    beq     5f
    push    {r4, lr}
    mov     r0, #0
    ldr     r1, =\name
    mov     r2, #0
    ldr     ip, =PUBLISH
    blx     ip
    pop     {r4, lr}
5:  mov     r0, #0
    bx      lr
9:  ldr     pc, =\conv
.endm

.macro ZSHOW conv
    PADR    r3
    ldr     ip, [r3, #P_FLAG]
    cmp     ip, #0
    beq     9f
    mov     r0, #0
    bx      lr
9:  ldr     pc, =\conv
.endm

stub_zc:
    ZLOCK   ZC_CONV, ZC_AJ_RET, S_COLAJ_CONTRAST
stub_zs:
    ZLOCK   ZS_CONV, ZS_AJ_RET, S_COLAJ_SHARP
stub_znc:
    ZSHOW   ZNC_CONV
stub_zns:
    ZSHOW   ZNS_CONV

stub_mo:
    PADR    r3
    mov     ip, #1
    str     ip, [r3, #P_MENU]
    ldr     pc, =CBM_V25
stub_mx:
    PADR    r3
    mov     ip, #0
    str     ip, [r3, #P_MENU]
    ldr     pc, =CBM_V26

stub_fv:
    add     r0, r0, r1              /* 原指令 adds r0,r0,r1 */
    PADR    r2
    adr     r3, fvtab
    mov     ip, #NFV
1:  ldr     r1, [r3], #12           /* {原廠位址, 新版相對 params, 大小} */
    cmp     r0, r1
    beq     2f
    subs    ip, ip, #1
    bne     1b
.if NGL
    ldr     r1, [r2, #P_FLAG]       /* 右側框 SA/GA:RAW 生效、COLOR 選單開著、游標在 RAW 列 → 換字形 */
    cmp     r1, #0
    beq     3f
    ldr     r1, [r2, #P_MENU]
    cmp     r1, #0
    beq     3f
    ldr     r1, [r2, #P_CUR]
    cmp     r1, #16
    bne     3f
    adr     r3, gltab
    mov     ip, #NGL
4:  ldr     r1, [r3], #12
    cmp     r0, r1
    beq     2f
    subs    ip, ip, #1
    bne     4b
.endif
    b       3f
2:  ldr     r1, [r3, #-8]
    add     r0, r2, r1
    ldr     r1, [r3, #-4]
    str     r1, [sp]                /* 檔案大小 */
3:  str     r0, [r5, #4]            /* 原指令 str r0,[r5,#4] */
    ldr     pc, =0xC05E5BF1         /* 回 Thumb */

.ltorg
#ifdef LV_BOOST
#ifdef FL_DEFAULT
#include "fl_startup.inc.S"
#endif
#include "fl_csv.inc"
#else
#include "rv_csv.inc"
#endif
res_end:
