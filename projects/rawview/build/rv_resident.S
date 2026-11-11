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
 *   +0x10 tab_base   124 張表(rv_tables.SETS:SA/GA × 對比 0/1,各 31),各 0x1000,ISO 低→高;表 k ≥ 62 在 tab_base + (k + 4)·0x1000
 *   +0x14 slots      11 格插槽(每格 8 bytes,+4 是表位址)
 *   +0x18 mode_copy  mode→tone 表的 RAM 副本(OFF 那筆指向插槽)
 *   +0x1C thr[30]    相對增益門檻
 *   +0x94 pend       選單剛經 GUI 轉換:GUI 15 → 16(OFF)、16 → 17(RAW),其他 0;setter 消化後清 0
 *   +0x98 guitab     色彩模式 {enum, gui} × 17(原廠 16 筆 + {0xC, 16});getter C06C07C0 改指這裡。
 *                    index 15/16 都是 enum 0xC,GUI 值排列「目前生效的在前」
 *   +0x120 dbg_idx / +0x124 dbg 環(8 × 16)
 *   +0x1A4 lat       0 = SA(Latitude — Stop Aligned,曲線 A)、1 = GA(Latitude — Gray Aligned,曲線 B);右側上下框
 *   +0x1A8 mat_copy  色彩矩陣表(root+0x08)的 RAM 副本(launcher 填);OFF 那筆由 stub_gs 依飽和度改寫
 *   +0x1AC key_app   已套用的 lat | con << 1 | sat << 2(stub_gs 偵測變更)
 *   +0x1B0 sat       AEL 飽和度 UI 0..SAT_MAX(捲動即時,AJ)→ 矩陣程度(build/rv_color.sat_k:0 = 不套、1 = 100 %)
 *   +0x1B4 sat_fix   已確認(按 OK,FIX)的飽和度;取消時頁面以它重設 AJ
 *   +0x1B8 menu      COLOR 鍵選單開著(stub_mo/stub_mx,ColorButtonMenu vtable v25/v26)
 *   +0x1BC cur       COLOR 選單游標所在 GUI 列(stub_ma/mj 記錄)
 *   +0x1C0(保留)
 *   +0x1C4 con       AEL 對比度 UI 0..1(捲動即時):0 = 12.5 檔鋪到預覽 10.9 檔(index 1 可見)、1 = 原做法(官方 12.5 檔)
 *   +0x1C8 con_fix   已確認(FIX)的對比度
 *   +0x1D0 sat_tab   6 筆 × 24 B:OFF 筆 {0x24, 9 × s16, pad},UI 0..5
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
 * stub_dg 取代 0xC032F728 `ldr r6,[ip]`:eff 開且 bank 0 → RAW_CORR 數位增益 1×(0x400);最後畫質指令是回放時不動。
 * stub_pq 取代 0xC02B8E64 `bl FUN_c02b97a8`(畫質管理器的指令;2026-09-27 研究):RAW 表格裝著時收到 0xB–0xD
 *   (CinemaDNG 回放、DNG 顯影)→ root+0x70、root+0x08 換回原廠,清 tone 快取,eff 設 2;回放依片段記錄的色彩模式
 *   查表(RAW 錄的片段記為 OFF),不換回就會用我們目前 ISO 的表,且 stub_dg 會把片段的 ISO 增益抹掉(使用者 2026-09-27)。
 *   回到即時畫面後 stub_gs 算出 eff 1 ≠ 2 → 重新套用。stub_gs 在最後指令是回放時也不生效。
 *   sp 未對齊 → leaf,只用 r0。
 * 選單(第 17 列 RAW = 原廠 OFF 0xC + flag):
 * stub_ma 取代三個 `bl C06C0718`(GUI→enum;選單 C056D028、COLOR 鍵 C0568950、QS C05818B8):
 *   r1 = GUI 列號;記下 pend(15 → 16、16 → 17、其他 → 0),再尾跳原函式。
 *   QS 路徑(lr = C05818BC)一律 pend 0:QS 列表沒有 RAW 列,切解析度等操作時 QS 以 GUI 15 重新同步色彩項目,
 *   舊版把它當成「選 OFF」而關掉 RAW(2026-09-26 上機 dbg)。QS 選其他模式(值 ≠ 12)仍會由 setter 關掉 RAW。
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
 *   等於目前顯示值(SA = −5、GA = +5;stub_ai 把框的字形換成字母 →「SA」「GA」)→ 不動;大 → GA、小 → SA,並以 FUN_c0593f30(發布 UI 變數,原廠通知同一路)
 *   把 CM_COLAJ_Effect 與 CM_COLFIX_Effect 設回 −5 / +5(框只停在這兩值;FIX 一致 → 下次開選單複製過來不會誤切);回 0。
 * stub_en 取代兩個 `bl C06C0D70`(通知 v87 C0595908 = CM_COLAJ_Effect、v82 C05957B0 = CM_COLFIX_Effect;r7 = 模式):
 *   模式 0xC → 回 −5 / +5。(2026-09-25 上機 fs2-7:少了 v82,每次開選單 FIX 值 0 複製到 AJ → SA/GA 被切換)
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
 * stub_ai 取代 Thumb 0xC05E2200 `bl FUN_c05d6bb8`(FUN_c05e1fa8:animationClip 依時間把關鍵影格的圖名設到節點;
 *   r0 = 節點、r1 = 屬性、r2 = 圖名(字串池指標)、fp = 容器元件:+0x18 記錄 id)。Thumb BL → Thumb veneer → 這裡:
 *   RAW 生效 && 游標在 RAW 列 && 容器 id 為效果框的符號 0x177 / 數字 0x178 → 圖名 kigou_06 → id_S、kigou_07 → id_G、
 *   LB_5 → id_A(原廠字母字形,名稱只有這裡用);再尾跳原函式(lr 不動)。游標每次改變數值都經過這裡 → 即時切換、不影響他列
 *   (2026-09-26 研究:關鍵影格只存圖名,節點依名稱載圖並快取)。可用 r0–r3、ip;r4/r5 自行保存。
 * stub_sv 取代 0xC0088C60 `bl FUN_c0088660`(關機存檔 v2 0xC0088BB0 與 shell `menu save` 才走到;呼叫者 r4 = 存檔物件):
 *   RAW 開著(flag)、目前是第 0 組、第 0 組紀錄的色彩是 OFF(0xC)→ 暫時改成 0x10 | lat | con << 1 | sat << 2,
 *   呼叫原函式(算校驗、複製進儲存緩衝,關機時寫 NAND),再改回 0xC(之後切回第 0 組才不會把 0x1x 載入工作設定)。
 *   0x10–0x17 在原廠韌體是不認得的色彩:查表都有邊界、預設 Standard,不會寫出界(2026-09-27 研究,唯讀)。
 *   開機時 launcher 看到 0x10–0x17 → 還原 lat/con/sat,經 setter 改回 OFF + RAW。r0–r3 原樣傳給原函式。
 * stub_il(診斷,預設不接):圖檔載入紀錄回呼 [0xC37CECF8](name, w, h)。由 host(tools/rv_imglog.py)把指標指來;
 *   名字是 font_menu_LB* 時記 {呼叫者 lr, 名字 16 B, 呼叫者堆疊 64 word} 到 T0 + 0x40C00(= params + 0x2A00,2 筆環)。
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

#if !COLS
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
.equ P_DTLOG, 0x1C0
.equ P_CON,   0x1C4
.equ P_CONF,  0x1C8
.equ P_SATTAB, 0x1D0
.equ ZC_CONV, 0xC06C0EC0             /* 對比 UI → 存值 */
.equ ZS_CONV, 0xC06C0F90             /* 清晰 UI → 存值 */
.equ ZNC_CONV, 0xC06C0F10            /* 對比 存值 → UI */
.equ ZNS_CONV, 0xC06C0FE0            /* 清晰 存值 → UI */
.equ ZC_AJ_RET, 0xC056D54C
.equ ZC_FIX_RET, 0xC056D3EC        /* 對比 FIX 回呼的 bl 之後 */
.equ ZNC_FIX_RET, 0xC0595820       /* v83(COLFIX 對比)的 bl 之後 */
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
.equ AI_ORIG,   0xC05D6BB9          /* FUN_c05d6bb8(Thumb) */
.equ PQ_ORIG,   0xC02B97A8          /* FUN_c02b97a8:畫質管理器執行指令(r1 = 指令;唯一呼叫者 0xC02B8E64) */
.equ PQ_LASTCMD, 0xC3413CF4         /* 管理器記錄的最後指令(通道 0):即時 2/3/4/5/8/9/10,CinemaDNG 回放 0xC,DNG 顯影 0xB/0xD */
.equ SV_ORIG,   0xC0088660          /* FUN_c0088660:設定存檔(校驗 + 複製 0x4F00 到儲存緩衝) */
.equ SV_GROUP,  0x58CC              /* 存檔物件:目前設定組(0 = 一般,1.. = C1–C3 等) */
.equ SV_COLOR,  0x13C               /* 存檔物件:第 0 組紀錄的色彩模式(= 紀錄 +0x130 = bank +0x12C) */
.equ NAME_K06,  0xC18E6BA0          /* font_menu_LB_kigou_06(−) */
.equ NAME_K07,  0xC18E6BB8          /* font_menu_LB_kigou_07(+) */
.equ NAME_LB5,  0xC18E67B0          /* font_menu_LB_5 */
.equ NAME_ID_S, 0xC18E6A80
.equ NAME_ID_G, 0xC18E6990
.equ NAME_ID_A, 0xC18E6918
/* 2026-10-03:名稱是「目前字串池 + 位移」。別的 sup(Lossless 等)經 fpSup/uishare 把 UI 換到
 * 共用字串池副本(FSPL)後,名稱指標就不在原廠池裡了;原廠位移在副本裡不變,所以比位移。
 * 讀 UI 的 reader 取目前池基底;讀不到(GUI 還沒起來)就用原廠池。 */
.equ STOCK_POOL, 0xC18C0474
.equ GUI_OBJECT, 0xC37B7048
.equ EFF_SIGN,  0x177               /* 效果框符號容器記錄 id */
.equ GUI_TO_ENUM, 0xC06C0718
.equ GUI_TO_ENUM_AJ, 0xC06C07E8
.equ QS_RET,      0xC05818BC        /* QS 的 GUI→enum bl(C05818B8)之後 */
.equ ENUM_TO_GUI, 0xC06C0768
.equ COLOR_ITEM,  0xC31ACDC4
#ifndef V3
#define V3 0
#endif
#ifndef COLS
#define COLS 0
#endif
/* COLS = 1(RAW-View 0.4,COL-Share 的客戶;fpSup/colshare/DESIGN.md P3,Bei 2026-11-07 §9.1):
 *   COLOR 清單的列、GUI 表、setter、±框、ColorButtonMenu、AEL 頁上限、root 共用字都歸 COL-Share。
 *   RAW 列的記錄 = {root+0x70 → mode 副本, root+0x08 → 矩陣副本}(兩個指標固定);
 *   「RAW 在顯示」= root+0x70 是我們的 mode 副本(SHOWN)。stub_gs／stub_pq 不再寫 root,只改兩份副本
 *   的 OFF 筆內容(生效:插槽與 sat_tab[sat];不生效／回放:原廠 82 與 sat_tab[0] = 原廠單位矩陣)。
 *   沒有 stub_ma/mb/mc/mj/ml/ef/en/mo/mx/fv/ai/il(±框固定 0,Bei #7:SA/GA 字形不再需要)。
 *   P_FLAG = 客戶記得的選擇(COL-Share on_pick / 開機的設定區),stub_sv 照舊存進自己的檔。 */
.equ MODE_DELTA, 0x3E200 - 0x3E060   /* params(T0 + OFF_RES)− mode 副本(T0 + OFF_MODE);rv_launch.S 同一組 */
.equ P_MODEN, 0x124                  /* COLS:OFF 筆指向插槽的 base(launcher 算) */
.equ P_BOXP,  0x128                  /* COLS:&COL-Share ±框的 live 字(launcher 的 cb_state) */
#if V3
/* Loader v3(projects/usb-shell-sup/notes/LOADER_V3.md):
 *   - stub_pq/stub_ai/stub_sv 的呼叫點是 CHAIN:尾跳/呼叫 pq_next/ai_next/sv_next(launcher 填 chain_next,
 *     沒有下層時就是原函式)。
 *   - 使用者設定(RAW 開關、SA/GA、對比、飽和度)存在 sup 自己的檔:檔頭之後的 32 B 設定區(block + 32)。
 *     stub_sv 不再改原廠設定區的色彩;原函式存完之後,第 0 組且 RAW 狀態有變才把設定區
 *     原地寫回 P_PATH(同 lossless:open 7 → seek 32 → 寫 32 B → seek → 讀回比對;不符就標成沒存,下次關機重寫)。 */
.equ P_PATH,   0x1C0                 /* 本 sup 的檔案路徑(加載器的字串,整個開機有效) */
.equ P_BLOCK,  0x1CC                 /* 塊基底 = 檔案在記憶體的原樣 */
#if V4
.equ CFG_OFF,  48                    /* the FSB4 header, then the record */
.equ SVC_FILE_IS, 52
.equ F_DCACHE_R, 0xC000E91C
#else
.equ CFG_OFF,  32                    /* 設定區:{'RVS1', flag, lat, con, sat, 0, 0, 0} */
#endif
.equ CFG_MAGIC, 0x31535652           /* "RVS1" */
.equ FOBJ_REL, 0x80000 - 0x3E200     /* 檔案物件:T0 + 0x80000(開機時的 LOG 暫存,之後空著) */
.equ F_CTOR,   0xC0365E90
.equ F_OPEN,   0xC0365FB0
.equ F_WRITE,  0xC03660E8
.equ F_READ,   0xC0366060
.equ F_SEEK,   0xC03661E0           /* (obj, 位置, 0):lossless 的設定存檔同一條 */
.equ F_CLOSE,  0xC0366020
.equ F_DTOR,   0xC0365ED0
#endif

/* reg = params(位置無關;adr 在常駐變大後距離不夠) */
.macro PADR reg
    ldr     \reg, 91f
90: add     \reg, pc, \reg
    b       92f
91: .word   params - (90b + 8)
92:
.endm

/* COLS:r3 = params;Z = root 顯示 RAW 列(root+0x70 是我們的 mode 副本);只用 ip */
.macro SHOWN
    ldr     ip, =ROOT_P70
    ldr     ip, [ip]
    add     ip, ip, #MODE_DELTA
    cmp     ip, r3
.endm

/* r3 = params;不是 RAW → 9f(COLS:root 沒顯示 RAW 列;舊版:flag 0) */
.macro NOTRAW_9
#if COLS
    SHOWN
    bne     9f
#else
    ldr     ip, [r3, #P_FLAG]
    cmp     ip, #0
    beq     9f
#endif
.endm

params:
    .ascii  "RVW1"
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
    .word   0, 0, 0, 0              /* +0x1C0(保留)、+0x1C4 con、+0x1C8 con_fix、+0x1CC(保留) */
#include "rv_sat.inc"
.align 3
#include "rv_dngcm.inc"             /* cm_buf(初值 = 第 0 級 = 原廠 OFF 常數)、cm_tab */

#if COLS
stub_gs:
    ldr     r2, [r5, #0xc]          /* 原指令 */
    cmp     r2, #0
    bxne    lr                      /* 不是待機:不動 */
    PADR    r3

    /* eff = root 顯示 RAW 列 && 色彩 OFF && CinemaDNG && 12-bit && 不是回放 */
    mov     r0, #0
    ldr     ip, =ROOT_P70
    ldr     ip, [ip]
    ldr     r1, [r3, #P_MODE]
    cmp     ip, r1
    bne     1f
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
    ldr     ip, =PQ_LASTCMD
    ldr     ip, [ip]
    sub     ip, ip, #0xB
    cmp     ip, #2
    movls   r0, #0
1:  ldr     ip, [r3, #P_BOXP]       /* lat = COL-Share ±框(SA −5 / GA +5,每一步立刻寫) */
    cmp     ip, #0
    beq     3f
    ldr     ip, [ip]
    cmp     ip, #0
    movgt   ip, #1
    movle   ip, #0
    str     ip, [r3, #P_VAR]
3:  ldr     r1, [r3, #P_VAR]        /* key = lat | con << 1 | sat << 2 */
    ldr     ip, [r3, #P_CON]
    add     r1, r1, ip, lsl #1
    ldr     ip, [r3, #P_SAT]
    add     r1, r1, ip, lsl #2
    ldr     ip, [r3, #P_EFF]
    cmp     r0, ip
    ldreq   ip, [r3, #P_VAPP]
    cmpeq   r1, ip
    beq     2f
    str     r0, [r3, #P_EFF]        /* 改變:兩份副本的 OFF 筆(root 指標歸 COL-Share,不動) */
    str     r1, [r3, #P_VAPP]
    push    {r4, r5}
    ldr     r4, [r3, #P_MODE]
    cmp     r0, #0
    ldrne   r1, [r3, #P_MODEN]      /* 生效:插槽 */
    moveq   r1, #82                 /* 原廠 OFF 曲線 */
    str     r1, [r4, #0x11C]
    mov     r4, #0                  /* 矩陣:生效 sat_tab[sat],否則 sat_tab[0](原廠單位矩陣) */
    cmp     r0, #0
    ldrne   r4, [r3, #P_SAT]
    cmp     r4, #SAT_MAX
    movhi   r4, #0
    add     r4, r4, r4, lsl #1
    add     r5, r3, #P_SATTAB
    add     r4, r5, r4, lsl #3
    ldr     r1, [r3, #P_MAT]
    add     r5, r1, #MAT_OFF
    mov     r1, #6
8:  ldr     ip, [r4], #4
    str     ip, [r5], #4
    subs    r1, r1, #1
    bne     8b
    mov     r4, #0                  /* DNG ColorMatrix:cm_buf = cm_tab[生效 ? sat : 0] */
    cmp     r0, #0
    ldrne   r4, [r3, #P_SAT]
    cmp     r4, #SAT_MAX
    movhi   r4, #0
    mov     r5, #144
    mul     r4, r4, r5
    ldr     ip, =cm_tab - params
    add     r4, r4, ip
    add     r4, r4, r3
    ldr     ip, =cm_buf - params
    add     r5, r3, ip
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
    addne   r1, r1, #31             /* GA 組 */
    ldr     ip, [r3, #P_CON]
    cmp     ip, #0
    addne   r1, r1, #62             /* 對比 1:原做法的兩組 */
    cmp     r1, #62
    addhs   r1, r1, #4              /* 表 62 起在常駐區之後 */
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
    ldr     ip, =PQ_LASTCMD         /* 最後指令是回放／顯影(0xB–0xD):不生效,回放照原廠 */
    ldr     ip, [ip]
    sub     ip, ip, #0xB
    cmp     ip, #2
    movls   r0, #0
1:  ldr     r1, [r3, #P_VAR]        /* key = lat | con << 1 | sat << 2 */
    ldr     ip, [r3, #P_CON]
    add     r1, r1, ip, lsl #1
    ldr     ip, [r3, #P_SAT]
    add     r1, r1, ip, lsl #2
    ldr     ip, [r3, #P_EFF]
    cmp     r0, ip
    ldreq   ip, [r3, #P_VAPP]
    cmpeq   r1, ip
    beq     2f
    str     r0, [r3, #P_EFF]        /* 生效狀態、lat、con 或 sat 改變:切 root 指標、矩陣、強制重選表 */
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
    cmp     r4, #SAT_MAX
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
    cmp     r4, #SAT_MAX
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
    addne   r1, r1, #31             /* GA 組 */
    ldr     ip, [r3, #P_CON]
    cmp     ip, #0
    addne   r1, r1, #62             /* 對比 1:原做法的兩組 */
    cmp     r1, #62
    addhs   r1, r1, #4              /* 表 62 起在常駐區之後 */
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

#endif
stub_dg:
    ldr     r6, [ip]                /* 原指令 */
    ldr     r0, params + P_EFF
    cmp     r0, #1
    bxne    lr                      /* 只在 RAW 表格裝著時(stub_pq 回放時設成 2) */
    cmp     r5, #0
    bxne    lr                      /* bank 1(拍照)不動 */
    ldr     r0, =PQ_LASTCMD         /* CinemaDNG 回放也走這裡(bank 0):保留片段自己的 ISO 增益 */
    ldr     r0, [r0]
    sub     r0, r0, #0xB
    cmp     r0, #2
    bxls    lr
    mov     r6, #0x400              /* 1.0× */
    bx      lr

stub_pq:                            /* 取代 0xC02B8E64 `bl FUN_c02b97a8`:r0 = 管理器、r1 = 指令、r2/r3 + [sp] 原樣給原函式 */
    push    {r0-r3, r4, lr}
    PADR    r4
    ldr     ip, [r4, #P_EFF]
    cmp     ip, #1
    bne     8f                      /* RAW 表格沒裝著:不動 */
    sub     ip, r1, #0xB
    cmp     ip, #2
    bhi     8f                      /* 不是回放／顯影 */
#if COLS
    ldr     r0, [r4, #P_MODE]       /* 副本的 OFF 筆換回原廠(root 指標歸 COL-Share);清兩個通道的 tone 快取鍵 */
    mov     r1, #82
    str     r1, [r0, #0x11C]
    ldr     r0, [r4, #P_MAT]
    add     r0, r0, #MAT_OFF
    add     r1, r4, #P_SATTAB       /* sat_tab[0] = 原廠單位矩陣 */
    mov     r2, #6
7:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #1
    bne     7b
#else
    ldr     r0, =ROOT_P70           /* 換回原廠 tone、矩陣表;清兩個通道的 tone 快取鍵 */
    ldr     r1, =ROOT_P70_ORIG
    str     r1, [r0]
    ldr     r0, =ROOT_P08
    ldr     r1, =ROOT_P08_ORIG
    str     r1, [r0]
#endif
    ldr     r0, =KEY_CTX0
    mvn     r1, #0
    str     r1, [r0]
    str     r1, [r0, #4]
    mov     r0, #2                  /* 回到即時畫面時 stub_gs 看到不同 → 重新套用 */
    str     r0, [r4, #P_EFF]
8:  pop     {r0-r3, r4, lr}
#if V3
    ldr     pc, pq_next
pq_next: .word PQ_ORIG
#else
    ldr     pc, =PQ_ORIG
#endif

#if !COLS
stub_mj:
    ldr     ip, =GUI_TO_ENUM_AJ
    b       1f
stub_ma:
    ldr     ip, =GUI_TO_ENUM
1:  push    {ip}                    /* 尾跳目標 */
    PADR    r3
    sub     r2, r1, #15
    cmp     r2, #2
    addlo   r2, r1, #1              /* GUI 15/16 → pend 16/17 */
    movhs   r2, #0
    ldr     ip, =QS_RET
    cmp     lr, ip
    moveq   r2, #0                  /* QS:列表沒有 RAW 列,它送來的 15 是重新同步(例如切解析度),不是選擇 */
    strne   r1, [r3, #P_CUR]        /* 游標所在 GUI 列(只記 COLOR 選單路徑) */
    str     r2, [r3, #P_PEND]
    ldr     ip, [r3, #P_DBGI]       /* dbg:{'M' | (lr − 0xC0000000) << 8, gui, pend, flag};lr = 呼叫點 + 4 */
    and     r2, ip, #7
    add     ip, ip, #1
    str     ip, [r3, #P_DBGI]
    add     r2, r3, r2, lsl #4
    add     r2, r2, #P_DBG
    sub     ip, lr, #0xC0000000
    lsl     ip, ip, #8
    orr     ip, ip, #0x4D
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
    NOTRAW_9
    ldr     r2, [r3, #P_VAR]        /* 目前顯示值:SA = −5、GA = +5 */
    cmp     r2, #0
    mvneq   r2, #4
    movne   r2, #5
    cmp     r1, r2
    beq     5f                      /* 等於顯示值(含我們自己發布的回呼):不動 */
    movgt   ip, #1                  /* 往上 → GA */
    movlt   ip, #0                  /* 往下 → SA */
    str     ip, [r3, #P_VAR]
    push    {r4, lr}
    cmp     ip, #0
    mvneq   r4, #4
    movne   r4, #5                  /* r4 = 新顯示值 */
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
    NOTRAW_9
    cmp     r7, #0xC
    bne     9f
    ldr     r0, [r3, #P_VAR]
    cmp     r0, #0
    mvneq   r0, #4                  /* SA → −5 */
    movne   r0, #5                  /* GA → +5 */
    bx      lr
9:  ldr     pc, =EN_CONV

#endif
/* 調整值 UI → 存值(RAW 時):r1 = UI 值,夾到 0..max 存 slot;lr 是 FIX 回呼 → 也存 fix(確認值);
 * 捲動(AJ)被夾時以 PUBLISH 把 AJ 變數設回夾後的值(刻度停在範圍內;不發布 FIX,以免變成「確認」);回 0 */
.macro ADJ slot, fix, fix_ret, name, max
    mov     r2, r1                  /* r2 = 原值 */
    cmp     r1, #0
    movlt   r1, #0
    cmp     r1, #\max
    movgt   r1, #\max
    str     r1, [r3, #\slot]
    ldr     ip, =\fix_ret
    cmp     lr, ip
    streq   r1, [r3, #\fix]
    beq     5f
    cmp     r1, r2
    beq     5f
    push    {r4, lr}
    mov     r0, #0
    mov     r2, r1
    ldr     r1, =\name
    ldr     ip, =PUBLISH
    blx     ip
    pop     {r4, lr}
5:  mov     r0, #0
    bx      lr
.endm

stub_sa:
    PADR    r3
    NOTRAW_9
    ADJ     P_SAT, P_SATF, SA_FIX_RET, S_COLAJ_SAT, SAT_MAX
9:  ldr     pc, =SA_CONV

stub_sn:
    PADR    r3
    NOTRAW_9
    ldr     ip, =SN_FIX_RET
    cmp     lr, ip
    ldreq   r0, [r3, #P_SATF]       /* CM_COLFIX_Saturation */
    ldrne   r0, [r3, #P_SAT]        /* CM_COLAJ_Saturation */
    bx      lr
9:  ldr     pc, =SN_CONV

/* RAW 時回 0;lr == aj_ret 且 r1 ≠ 0 → 發布 name = 0。否則尾跳 conv */
.macro ZLOCK conv, aj_ret, name
    PADR    r3
    NOTRAW_9
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
    NOTRAW_9
    mov     r0, #0
    bx      lr
9:  ldr     pc, =\conv
.endm

stub_zc:                            /* 對比度 0..1(使用者 2026-09-26):選曲線做法 */
    PADR    r3
    NOTRAW_9
    ADJ     P_CON, P_CONF, ZC_FIX_RET, S_COLAJ_CONTRAST, 1
9:  ldr     pc, =ZC_CONV
stub_zs:
    ZLOCK   ZS_CONV, ZS_AJ_RET, S_COLAJ_SHARP
stub_znc:
    PADR    r3
    NOTRAW_9
    ldr     ip, =ZNC_FIX_RET
    cmp     lr, ip
    ldreq   r0, [r3, #P_CONF]       /* CM_COLFIX_Contrast */
    ldrne   r0, [r3, #P_CON]        /* CM_COLAJ_Contrast */
    bx      lr
9:  ldr     pc, =ZNC_CONV
stub_zns:
    ZSHOW   ZNS_CONV

#if !COLS
stub_ai:
    push    {r4, r5}
    PADR    r3
    ldr     r4, [r3, #P_FLAG]
    cmp     r4, #0
    beq     8f
    ldr     r4, [r3, #P_CUR]
    cmp     r4, #16
    bne     8f
    ldr     r4, [fp, #0x18]         /* 容器記錄 id */
    ldr     r5, =EFF_SIGN
    sub     r4, r4, r5
    cmp     r4, #1                  /* 0x177 符號、0x178 數字 */
    bhi     8f
    ldr     r3, =GUI_OBJECT         /* 目前的字串池:app → 畫面 0 → reader +0x14 */
    ldr     r3, [r3]
    cmp     r3, #0
    beq     7f
    ldr     r3, [r3, #0x8C]
    cmp     r3, #0
    beq     7f
    ldr     r3, [r3]
    cmp     r3, #0
    beq     7f
    ldr     r3, [r3, #0x24]
    cmp     r3, #0
    beq     7f
    ldr     r3, [r3, #0x14]
    cmp     r3, #0
    bne     6f
7:  ldr     r3, =STOCK_POOL
6:  sub     r4, r2, r3              /* 名稱的位移 */
    ldr     r5, =NAME_K06 - STOCK_POOL
    cmp     r4, r5
    ldreq   r2, =NAME_ID_S - STOCK_POOL
    beq     5f
    ldr     r5, =NAME_K07 - STOCK_POOL
    cmp     r4, r5
    ldreq   r2, =NAME_ID_G - STOCK_POOL
    beq     5f
    ldr     r5, =NAME_LB5 - STOCK_POOL
    cmp     r4, r5
    bne     8f
    ldr     r2, =NAME_ID_A - STOCK_POOL
5:  add     r2, r2, r3              /* 同一個池裡的替換名稱 */
8:  pop     {r4, r5}
#if V3
    ldr     pc, ai_next
ai_next: .word AI_ORIG
#else
    ldr     pc, =AI_ORIG
#endif

#endif
#if V3
stub_sv:
    push    {r0-r3, r5-r7, lr}      /* 8 個:stack 對齊不變 */
    ldr     ip, sv_next
    blx     ip                      /* 原廠存檔照舊(原廠設定區不改) */
    str     r0, [sp]                /* 回傳值 */
    ldr     r0, =SV_GROUP
    ldr     r0, [r4, r0]
    cmp     r0, #0
    bne     9f                      /* 自訂模式:這次存的不是第 0 組,設定區不動 */
    PADR    r5
    ldr     r6, [r5, #P_FLAG]       /* flag:RAW 開著且第 0 組紀錄的色彩是 OFF */
    cmp     r6, #0
    movne   r6, #1
    ldr     r0, [r4, #SV_COLOR]
    cmp     r0, #0xC
    movne   r6, #0
    ldr     r7, [r5, #P_BLOCK]
    add     r7, r7, #CFG_OFF        /* r7 = 設定區 */
    ldr     r0, [r7]
    ldr     r1, =CFG_MAGIC
    cmp     r0, r1
    bne     1f
    ldr     r0, [r7, #4]
    cmp     r0, r6
    bne     1f
    ldr     r0, [r7, #8]
    ldr     r1, [r5, #P_VAR]
    and     r1, r1, #1
    cmp     r0, r1
    bne     1f
    ldr     r0, [r7, #12]
    ldr     r1, [r5, #P_CON]
    cmp     r0, r1
    bne     1f
    ldr     r0, [r7, #16]
    ldr     r1, [r5, #P_SAT]
    cmp     r0, r1
    beq     9f                      /* 沒變:不寫卡 */
1:  ldr     r0, =CFG_MAGIC
    str     r0, [r7]
    str     r6, [r7, #4]
    ldr     r0, [r5, #P_VAR]
    and     r0, r0, #1
    str     r0, [r7, #8]
    ldr     r0, [r5, #P_CON]
    str     r0, [r7, #12]
    ldr     r0, [r5, #P_SAT]
    str     r0, [r7, #16]
#if V4
    /* Loader v4: write only into a file that is still this sup -- mode 7
     * creates a missing one (sup-writeback-must-not-create) -- and only once
     * the record is in memory: this block runs at the cached alias. */
    ldr     r0, sv_svc
    cmp     r0, #0
    beq     8f
    ldr     r1, [r5, #P_PATH]
    ldr     r2, [r5, #P_BLOCK]      /* the file as loaded: its 48-byte header */
    mov     r3, #48
    ldr     ip, [r0, #SVC_FILE_IS]
    blx     ip
    cmp     r0, #0
    bne     8f
    ldr     ip, =F_DCACHE_R
    blx     ip
#endif
    ldr     r6, =FOBJ_REL
    add     r6, r5, r6              /* r6 = 檔案物件 */
#if V4
    cmp     r6, #0xC0000000         /* the object and the read-back at the uncached */
    subhs   r6, r6, #0x80000000     /* alias: what the card driver writes is what we read */
#endif
    mov     r0, r6
    mov     r1, #1                  /* SD */
    ldr     ip, =F_CTOR
    blx     ip
    mov     r0, r6
    ldr     r1, [r5, #P_PATH]
    mov     r2, #7                  /* 覆寫、不截斷 */
    ldr     ip, =F_OPEN
    blx     ip
    cmp     r0, #0
    beq     2f
    mov     r5, #0                  /* r5 = 寫入結果,0 = 失敗(params 之後不用) */
    mov     r0, r6
    mov     r1, #CFG_OFF
    mov     r2, #0
    ldr     ip, =F_SEEK
    blx     ip
    cmp     r0, #0
    beq     5f                      /* seek 失敗:不寫(否則會蓋到檔頭) */
    mov     r0, r6
    mov     r1, r7
    mov     r2, #32
    ldr     ip, =F_WRITE
    blx     ip
    mov     r5, r0
    mov     r0, r6
    mov     r1, #CFG_OFF
    mov     r2, #0
    ldr     ip, =F_SEEK
    blx     ip
    cmp     r0, #0
    moveq   r5, #0
    beq     5f
    add     r1, r6, #0xF00          /* 讀回到檔案物件之後(物件 < 0xF00) */
    mov     r0, #0
    str     r0, [r1, #32]
    mov     r0, r6
    mov     r2, #32
    add     r3, r1, #32             /* 實際讀到的長度 */
    ldr     ip, =F_READ
    blx     ip
5:  mov     r0, r6
    ldr     ip, =F_CLOSE
    blx     ip
    cmp     r5, #0
    beq     2f
    add     r0, r6, #0xF00
    ldr     r1, [r0, #32]
    cmp     r1, #32
    bne     2f
    mov     r2, #0
4:  ldr     r1, [r0, r2]
    ldr     r3, [r7, r2]
    cmp     r1, r3
    bne     2f
    add     r2, r2, #4
    cmp     r2, #32
    blo     4b
    b       3f
2:  mov     r0, #0                  /* 沒寫成:下次關機重寫 */
    str     r0, [r7]
3:  mov     r0, r6
    mov     r1, #2
    ldr     ip, =F_DTOR
    blx     ip
#if V4
    b       9f
8:  mov     r0, #0                  /* not ours / not saved: mark it, retry next power-off */
    str     r0, [r7]
#endif
9:  pop     {r0-r3, r5-r7, pc}
sv_next: .word SV_ORIG
#if V4
sv_svc:  .word 0                    /* the service table (launcher: NEXT_SVC) */
#endif

#else
stub_sv:
    push    {r0-r3, r5, lr}         /* 6 個:stack 對齊不變;r5 = 要改回的位址 */
    mov     r5, #0
    PADR    ip
    ldr     r0, [ip, #P_FLAG]
    cmp     r0, #0
    beq     1f
    ldr     r0, =SV_GROUP
    ldr     r0, [r4, r0]
    cmp     r0, #0
    bne     1f                      /* 自訂模式:這次存的不是第 0 組 */
    ldr     r0, [r4, #SV_COLOR]
    cmp     r0, #0xC
    bne     1f
    ldr     r0, [ip, #P_VAR]
    and     r0, r0, #1
    ldr     r1, [ip, #P_CON]
    and     r1, r1, #1
    orr     r0, r0, r1, lsl #1
    ldr     r1, [ip, #P_SAT]
    and     r1, r1, #1
    orr     r0, r0, r1, lsl #2
    orr     r0, r0, #0x10
    str     r0, [r4, #SV_COLOR]
    add     r5, r4, #SV_COLOR
1:  ldm     sp, {r0-r3}
    ldr     ip, =SV_ORIG
    blx     ip
    cmp     r5, #0
    movne   r1, #0xC
    strne   r1, [r5]
    add     sp, sp, #16
    pop     {r5, pc}

#endif
#if !COLS
stub_il:
    push    {r4-r6, lr}
    ldrb    r4, [r0, #5]
    cmp     r4, #'m'
    bne     9f
    ldrb    r4, [r0, #10]
    cmp     r4, #'L'
    bne     9f
    ldrb    r4, [r0, #11]
    cmp     r4, #'B'
    bne     9f
    PADR    r3
    ldr     ip, =0x2A00
    add     r3, r3, ip              /* 紀錄區:次數 + 2 × 276 B */
    ldr     r4, [r3]
    add     r5, r4, #1
    str     r5, [r3]
    and     r4, r4, #1              /* 2 筆環 */
    ldr     r5, =276
    mul     r4, r4, r5
    add     r4, r4, r3
    add     r4, r4, #4              /* 這一筆 */
    ldr     r5, [sp, #12]           /* 呼叫者 lr */
    str     r5, [r4], #4
    mov     r5, #16
1:  ldrb    r6, [r0], #1
    strb    r6, [r4], #1
    subs    r5, r5, #1
    bne     1b
    add     r6, sp, #16
    mov     r5, #64
2:  ldr     ip, [r6], #4
    str     ip, [r4], #4
    subs    r5, r5, #1
    bne     2b
9:  pop     {r4-r6, pc}

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

#endif
.ltorg
#if !COLS
#include "rv_csv.inc"
#endif
res_end:
