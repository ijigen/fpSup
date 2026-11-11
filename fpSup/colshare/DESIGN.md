# COL-Share 設計(草案,2026-11-07,離線、未寫程式、未上機)

Bei 2026-11-07:「把 color 的 UI 共用出來 COL-Share」。

## 白話摘要

- **COL-Share 是一個獨立的 v4 sup**(`COL-Share_v0.0.1test.BIN`,sup_id `COLS`),只做一件事:
  **原生 COLOR 清單的「多出來的列」**:列數、名字、圖示、GUI 對照表、setter 那個點、±強度框、CSV/圖示的檔案重導。
  做法是把今天 `lut/native/clist.c` 搬出來,讓它不再屬於 LUT。
- **LUT、RAW-View 和以後的色彩 sup 都是「客戶」**:各自報上「我有哪幾列、叫什麼、圖示、強度範圍、選到時 ISP 要寫什麼」。
  COL-Share 負責把列放進清單,選到時照客戶給的那份表寫 ISP root,再在選單關閉時告訴客戶。
- **客戶不必管誰先載入**:COL-Share 檔名排在 LUT、RAW-View 前面;比它早載入的客戶由它在入口時去撈,
  比它晚的客戶自己呼叫它。開機時的狀態和今天一樣是確定的,不用另掛 hook。
- **舊卡相容**:卡上有舊 RAW-View(v0.3.1,自己 claim 同一批點)時,COL-Share 自己退出、讓舊 RAW-View 照舊運作,
  LUT 那時就沒有 COLOR 列(和今天 `cl_rawview_here` 的行為相同)。
- **不加每幀工作**:所有程式只在選單、按 COLOR 鍵、setter 被呼叫時跑;常駐目標 ≤ 64 KB(圖示不複製,直接指向客戶的記憶體)。
- **錄影中不存檔**:COL-Share 本身不寫檔;客戶的「選到了／強度改了」回呼在錄影中會延後到停錄之後。
- **有一個需要 Bei 拍板的架構改變**(見 §9 Q1):ISP root 那幾個字改由 COL-Share claim。這和 11-04「LUT 擁有 root 表」不同,
  先講清楚再動工。

## 1. 現況(要拆的東西)

| 東西 | 今天在哪 | COL-Share 之後 |
|---|---|---|
| 16 個 SL_EXCL 點 S_MA1..S_ADV(GUI↔enum ×6、setter `C0075CF4`、Effect ×3、getter movw/movt/count、ColorButtonMenu v25/v26、AEL 頁列數上限 `C1D6ED48`) | `clist.c` `cl_site()` | COL-Share |
| 共用檔案重導 `C05E5BEC`(HOOK_FV,SL_SHARED_UI) | `clist.c`(11-04 補 claim) | COL-Share(仍 SHARED_UI,和 Res-Custom 共用) |
| 3 份 ListColorButtonMenu CSV 複本、donor 圖示、ColorButtonMenu 資源組、頁面浮點／文字、大標籤 placeholder | `clist_ui.py` FPUI 區塊 + `cl_section` | COL-Share 的 BIN |
| GUI 表 `guitab[2×20]`、`active/pend/cur/menu/changed`、`eff[]` | `struct clist` | COL-Share 狀態 |
| setter 選到後寫 root(`lvrec[]` → root+0x10/08/28/50/70/48/4C,再踩三個 PQ 快取鍵) | `clist_stub_mc` + `lvb.c` | COL-Share 寫、客戶給表(§4) |
| root 字的 claim(P08/P10/P28/P48/P50/P70) | `lvb_install` | **建議**移到 COL-Share(§4、Q1) |
| DNG MakerNote 點(S124/S12D/S34/S129)、YGAM hook、DNG 寫矩陣(`dng.c`)、RAW_CORR | LUT | **留在 LUT**(與清單無關) |
| 選單關閉時 `library_pick`/`library_update` | `clist_closed` | LUT 的回呼 |
| RAW-View 的 COLOR 點(`rv_launch.S` 的 MA1-3/MB/MC/MJ/ML/EF/EN/EN_FIX、getter) | RAW-View 自己 | COL-Share |
| RAW-View 的對比/清晰/飽和框(ZC/ZS/ZNC/ZNS/SA/SN)、SV、PQ、AI、增益 SITE_A/B | RAW-View | **留在 RAW-View**(LUT 不碰,不衝突) |

## 2. 載入與註冊(順序無關)

字母序:`COL-Share…` < `LUT…` < `QS-Share…` < `RAW-View…`。所以現有客戶都**晚於**容器載入;但不能假設以後的客戶也是。

- **晚到的客戶(推)**:entry 裡 `api = svc->find(svc, COLS_ID)`;非 0 就 `api->add(api, &client)`(只在 entry 期間有效)。
- **早到的客戶(拉)**:找不到 COLS 就 `svc->provide(svc, COLS_TAG(my_id), &client)`;COL-Share 的 entry 用
  `sups_list` + `find(COLS_TAG(id))` 把已載入的撈進來(QS-Share `qc_collect` 的同一招,只是時間點在 entry,不在第一次版面載入)。
- 兩條路同一個 `struct cols_client`,客戶程式只多一個 `if`。被 RELEASE 的 sup,loader 會撤掉它的 provide,自然不會出現。
- **列的順序** = 註冊順序(= 檔名序),同一客戶內照它給的順序(Q3)。每次開機重新編號,跨開機保存的是客戶自己的 key,不是列號。
- **為什麼不學 QS-Share 等第一次版面載入**:開機後 LV 就要顯示上次選的 LUT(現在 `clist_sync` 在 entry 就做),
  延後收集等於開機頭幾秒畫面不對,還要多 claim 一個 SL_CHAIN 點。entry 收集已經足夠。

## 3. 客戶 API(`colshare.h`,版本 1;草稿)

```c
#define COLS_ID       0x534C4F43u               /* "COLS" */
#define COLS_TAG(id)  ((uint32_t)(id) ^ 0xC0C0C0C0u)   /* 早到客戶的 provide 鍵(與 QSC_TAG 不同) */
struct cols_row {                /* rows() 填;只列「現在可選」的列(= ready) */
    uint32_t key;                /* 客戶內穩定、跨開機不變 */
    const char *name;            /* 大標籤:1..31 可列印 ASCII(clist_label 的規則) */
    const uint8_t *icon; uint32_t icon_len;   /* 86×74 XCI,常駐在客戶塊內,≤ 13312;0 = 共用 donor 原圖 */
    int8_t eff_min, eff_max;     /* ±框範圍,-5..+5 之內;0,0 = 沒有強度(框固定 0) */
    uint16_t flags;              /* COLS_R_LOCK_REC:錄影中不可選 */
};
struct cols_rec {                /* 選到這列時 root 要寫的字,依序寫;回原廠時用原廠值反序寫 */
    uint32_t n;                  /* 1..COLS_REC_MAX(12) */
    struct { uint16_t off; uint16_t _r; uint32_t val; } w[12];   /* off ∈ COL-Share claim 的 root 偏移 */
};
struct cols_client {
    uint32_t magic, api;         /* "CLC1", 1 */
    uint32_t sup_id;
    uint32_t (*rows)(void *arg, struct cols_row *out, uint32_t max);
    uint32_t (*picked)(void *arg);           /* 開機時:客戶記得的選擇(key+1),0 = 無 */
    void     (*on_pick)(void *arg, uint32_t key_or_none);   /* 選單關閉、不在錄影;~0 = 離開這個客戶的列 */
    int      (*strength_get)(void *arg, uint32_t key);
    void     (*strength_set)(void *arg, uint32_t key, int v);  /* 選單關閉、不在錄影 */
    void *arg;
};
struct cols_api {
    uint32_t magic, version;     /* "CLA1", 1 */
    int  (*add)(const struct cols_api *, const struct cols_client *);       /* entry 期間 */
    void (*changed)(const struct cols_api *, uint32_t sup_id);   /* 列/名/圖/ready 變了:重排(選單開著就延到關閉) */
    int  (*set_record)(const struct cols_api *, uint32_t sup_id, uint32_t key, const struct cols_rec *);
    int  (*shown)(const struct cols_api *, uint32_t *sup_id, uint32_t *key);   /* root 現在顯示誰;0 = 原廠 */
    void (*reapply)(const struct cols_api *);    /* 表的內容變了(例如強度改了重擬合):重寫目前那列 */
    const uint32_t *stock_root;  /* entry 時(殘留修復後)的 root 36 字快照:LUT 的 DNG shadow 用它 */
};
```

規則:所有回呼在 UI 執行緒、要快、程式在客戶自己的塊(快取別名);`cols_rec` 一旦交出就不能再改,
要換就準備另一份再 `set_record`(單字指標交換;setter 可能在任何執行緒同時讀)。舊的那份客戶留到下一次 `set_record` 之後。

## 4. setter 寫 root:誰擁有?

setter 點 `C0075CF4`(`cmp sl, r6`)在原廠設定路徑中間,呼叫者可能是 UI、PTP、shell、自訂模式 C1–C3,
今天的 stub 是只用 r0-r3/ip 的葉函式。

| 做法 | 優點 | 缺點 |
|---|---|---|
| A. COL-Share 在 setter 裡呼叫客戶回呼 | 客戶彈性最大 | 客戶 C 程式跑在別人的執行緒、別人的堆疊上;一個客戶寫錯就是全機凍結;回呼成本進設定路徑 |
| **B. 客戶事先交 `cols_rec`,stub 照表寫(建議)** | 和今天 `lvrec[]` 完全同構;setter 裡沒有任何客戶程式;記錄可離線驗證 | 只能寫 root 範圍內的字;順序由記錄決定 |

**選 B。** 延伸:誰寫就由誰 claim,關機 journal 才會還原正確的字 → **root 字(P08/P10/P28/P40/P44/P48+4C/P50/P70)由 COL-Share claim**,
LUT 的 `lvb_show/lvb_stock` 改成 `set_record` + `reapply`;LUT 保留表的內容(副本表、擬合、JFT)、DNG 的四個點和 YGAM。
RAW-View 選 RAW 時要換的 +0x70、+0x40/+0x44 也走同一份記錄(曲線清單 `C097110C` 的 RAM 副本仍歸 RAW-View,它不是 root 字)。
這會改變 11-04「root 表歸 LUT」的決定(rawview-child-of-lut),**動工前先問 Bei(Q1)**;若 Bei 要維持 LUT 擁有 root,
退路是 LUT 用 `provide` 交出一個「寫 root」葉函式指標、COL-Share 的 stub 跳過去(仍是葉函式,但權責分在兩個 sup,測試要兩邊一起跑)。

`set_record` 為 0(還沒擬合好)= 列可以選,active 會移動,root 不動;客戶之後 `set_record` 時若它正被選就立刻寫(今天 `lvrec==0` 的行為)。
寫完一律踩 `C3414D14`、`C2F19D44`、`C2F19D48`(11-05 JPG 那次教訓:ctx1 也要)。

## 5. 選擇、強度、開機恢復

- 每一列在原廠眼中都是 OFF(0xC)+ `active`;選到原廠其他模式 = 沒有我們的列(今天的規則)。全系統同時只有一列 active。
- 選單關閉(v26)時:active 變了 → 舊客戶 `on_pick(~0)`、新客戶 `on_pick(key)`;強度變了 → `strength_set`。錄影中延後(§7)。
- 經 shell/PTP/C1–C3 改了色彩模式(選單沒開):stub 照樣把 root 回原廠、active 清 0;通知延到下一次選單關閉或 `changed()`
  (今天也是如此;畫面立即正確,只有客戶的記錄晚一點)。
- 開機:每個客戶加入時問 `picked()`;原廠 COLOR 仍是 OFF 且還沒有 active 時,第一個回非 0 的客戶得到 active
  (兩個客戶都說自己被選:先註冊的贏,另一個收到 `on_pick(~0)`)。
- ±框:stub_ef 依該列的 `eff_min..eff_max` 夾值(今天寫死 -5..0),stub_en 從 `eff[]` 回值;`eff[]` 在同步時從 `strength_get` 填。
- QS 的色彩清單沒有我們的列,QS 的 15 是重新同步(今天 MA3 的規則,不變)。

## 6. 舊卡、缺件與遷移

| 卡上組合 | 結果 |
|---|---|
| COL-Share + 新 LUT + 新 RAW-View(≥0.4) | 正常;列序 LUT 的在前(檔名序),見 Q3 |
| COL-Share + **舊 RAW-View v0.3.1** | COL-Share 的 entry 讀 `RAW-View_v*.BIN`/`RAWV.BIN` 的 48 B 檔頭(sup_id RAWV、version < 0.4.0、SupManager 沒停用)→ **自己 RELEASE**(LOAD.LOG 記原因)。舊 RAW-View 拿到全部點照舊運作;LUT 找不到 COLS → 沒有 COLOR 列,Manager 顯示原因。不這樣做的話 COL-Share 先 claim、舊 RAW-View 衝突被整個 RELEASE,使用者會默默失去 RAW-View。 |
| LUT 沒有 COL-Share | **建議**:LUT 不裝任何 COLOR/root/DNG 點,Manager 照常(轉檔可用),列上顯示「需要 COL-Share」;merge 頁把 COL-Share 列為 LUT 與新 RAW-View 的相依、自動帶入(Q2)。不在 LUT 裡留一份 clist 備援:兩份同樣的程式 = 兩個擁有者,就是要消除的問題。 |
| 新 RAW-View 沒有 COL-Share | 同上:RAW 列不出現,其他功能(增益、框)也不裝(沒有列就沒有入口) |
| COL-Share + 舊 LUT(內含 clist) | 舊 LUT 的 `clist_install` 在 S_MA1 衝突回 4,LUT 繼續跑但沒列。LUT 尚未正式發布,影響只在開發卡 |
| 兩個版本的 COL-Share | loader 先載新版,舊版衝突被 RELEASE |

RAW-View 的遷移(v0.4):拿掉 COLOR 那批點與 GUI 表,改成客戶(1 列、RAW 圖示 `rv_raw_icon.xci`、`eff 0,0`、`COLS_R_LOCK_REC` 視 Q6);
SV(關機時把 RAW 存成 0x10–0x17)與 `picked()` 重疊,改成 RAW-View 存在自己 BIN、SV 退役(Q5)。框(ZC/ZS/SA/SN)用 `shown()` 判斷是不是 RAW。

## 7. 記憶體、效能、錄影、關機

- **常駐**:程式 ~5 KB、狀態 <1 KB、3 份 CSV 複本(含 COLS_MAX 列成長)~3 KB、ColorButtonMenu 資源組複本、標籤 placeholder。
  圖示**不複製**:重導表 `FSFV {stock, copy, size}` 的 copy 直接指向客戶塊內的圖(LUT 的 `imp_icon_slot` 本來就常駐)→ 省下今天
  4 × 13 KB 的 donor 容量。目標整塊 ≤ 64 KB,build 時斷言;11-07 MOV 凍結的教訓:每個 sup 的 block_size 算進錄影預算,上機必測 MOV。
- **每幀成本 0**:沒有 Vd/幀 hook;只有按鍵、選單、setter 會進來;setter 的額外路徑和今天同樣是十幾個指令。
- **錄影**:COL-Share 自己從不寫檔;`on_pick`/`strength_set` 在錄影中(`0xC347D1C0+0x14==0x21` 選 `0xC34765CC+0x3D`,否則 `+0x157`)
  不呼叫,標記待辦,停錄後的下一次選單關閉或 `changed()` 補送。客戶仍要自己檢查(LUT 的 `library_busy`)。錄影中選單改 COLOR 時
  root 是否跟著換,照原廠准不准改決定(Q6)。
- **關機/暖開機**:所有寫入原廠的字都經 claim:16 個 SL_EXCL 點、`C05E5BEC` SL_SHARED_UI、root 字 SL_EXCL;core 關機寫回、
  暖開機殘留修復(11-04 凍結的教訓:fpui_stock 的 HOOK_FV 不替呼叫者 claim)。P1 要稽核 `fpui_stock_apply` 對這個區塊寫的每一個字
  都有主人;在 `HOOKS_AT_POWER_OFF.md` 登記。stock root 快照在 entry(殘留修復之後)取。暖開機後客戶記錄重建、active 由 `picked()` 恢復。

## 8. 留在 LUT 的

Manager／設定(Y5_1 三列)／色卡頁(將嵌入 LUT.BIN、LZ4 壓縮、entry 解開:另一個工作)、cube 庫、轉檔(聯合擬合、JFT)、
ISP 副本表內容與 `lvb_fit`、DNG(`dng.c`、MakerNote 四點、shadow)、YGAM、RAW_CORR、每列名字圖示的產生(`import.c`)。
LUT 對 COL-Share 只剩:`rows()`(開著且 ready 的 cube,≤ 分配到的列數)、`picked()`(library active)、`on_pick`(=`library_pick`)、
強度 get/set(amount ↔ -5..0)、`set_record`(lvb 算好的表)。

## 9. 給 Bei 的問題（2026-11-07 Bei 已回覆，見 §9.1）

1. **root 字改由 COL-Share claim、客戶交記錄**(§4 B)可以嗎?還是維持 LUT 擁有 root(退路:LUT 交葉函式)?
2. 沒有 COL-Share 時 LUT/RAW-View:**不出列 + 顯示原因 + merge 頁自動帶**(建議),還是要備援?
3. 列的順序與上限:RAW 列放最前(像以前第 17 列)還是照檔名?目前只驗證過 4 列額外列;RAW 1 + LUT 4 = 5,要上機驗 5–8 列(列數浮點、CSV 環、AEL 頁上限)。
4. 舊 RAW-View v0.3.1 在卡上時,COL-Share 自己退出(建議)可以嗎?
5. RAW-View 還是「LUT 的子 sup」嗎?有了 COL-Share 後建議改成 COL-Share 的平行客戶;RAW_CORR 仍歸 LUT(兩者都要用時再談介面)。SV 退役可以嗎?
6. 錄影中能不能從 COLOR 切到 LUT/RAW 列(原廠允許的話,MOV 中途換色)?
7. RAW 列的 ±框:沒有強度(固定 0)可以嗎?
8. COL-Share 自己要不要在 fpSup 頁有一列?(建議:無,只出現在 SupManager;在那裡停用 = 所有色彩列消失)


### 9.1 Bei 的決定（2026-11-07）
1. **共用的 root 指標字由 COL-Share claim、代寫**（§4 B）：各 sup 事先交出記錄（自己決定寫什麼），COL-Share 在選／取消時照記錄寫、切回原廠寫回原值。各 sup **專屬**、別人不會用的點（LUT 的 YGAM 攔截、DNG 寫入點、MakerNote 等）仍各自 claim、各自寫。
2. 沒有 COL-Share：不出列 + 顯示原因 + merge 頁自動帶（照建議）。
3. RAW 列最前，LUT 依清單順序；5–8 列上機驗（照建議）。
4. 舊 RAW-View v0.3.1 在卡上 → COL-Share 自己退出（照建議）。
5. **RAW-View 不再當 LUT 的子 sup**：與 LUT 平行，都是 COL-Share 的客戶（取代 11-04「RAW-View 是 LUT 子 sup」）。
6. 錄影中切換：照原廠（照建議）。
7. ~~RAW 列 ±框固定 0（照建議）。~~ **Bei 2026-11-08 取代**：RAW-View 的 SA/GA 留在原生 COLOR ±框（同 0.3.1）。
   ±框的 hook 仍歸 COL-Share（原廠只有一個框，它只轉發），但每一列由客戶決定框：範圍、每一格顯示的字形、每一步做什麼。
   做法＝API 2（`colshare.h`，版本 1 的客戶照舊）：`cols_row.flags` 可帶 `COLS_R_SNAP`（只停兩端，往上一步＝max、往下＝min）；
   `client->box(arg, key)` 回 `{live, glyphs}`：live＝每一步立刻寫的字（選單開著、stub 裡，只寫資料），
   glyphs＝效果框符號 0x177／數字 0x178 的圖名替換表（字串池位移，游標在這列且它是 active 時換；COL-Share 多 claim 一個
   CHAIN 點 `C05E2200`，即 0.3.1 的 stub_ai）。選定仍走 `strength_set`（選單關閉、不在錄影，和 LUT 強度一樣延後）。
   LUT 留在 v1（−5..0、不 snap）；RAW 列 −5..+5 snap，SA＝−5、GA＝+5，字形 kigou_06→S、kigou_07→G、LB_5→A。
8. COL-Share 不在 fpSup 頁出列，只在 SupManager（照建議）。

## 10. 分階段工作

| 階段 | 內容 | 完成條件 |
|---|---|---|
| P0 | Bei 回覆 §9 | 決定寫回本檔 |
| P1 抽出 | `colshare/{colshare.c,colshare.h,colshare_ui.py,build_colshare.py}`;`clist.c` 搬過來改成讀客戶;LUT 改成客戶(刪 clist、lvb 改 set_record);`names_v4` 加 `'COLS': ('COL-Share','COL-Share','0.0.1test')` | 單一客戶時,所有 `test_clist_native` 斷言在「COL-Share + LUT」上照樣通過;位元組層面 16 點寫入與今天相同 |
| P2 通用 | 多客戶、推/拉兩種註冊、記錄寫入順序、eff 範圍、錄影延後、舊 RAW-View 退出、LUT 單獨時不裝點 | §11 測試全綠 + 突變全抓 |
| P3 RAW-View v0.4 | 改成客戶,刪 COLOR 點與 SV,框改看 `shown()` | `test_v4_rawview` + 與 LUT 同卡測試 |
| P4 列數 | 上機驗 5–8 列 | 截圖每列、選、存 |
| P5 merge | 相依(LUT、RAW-View→COL-Share)、版本說明 | merge-v4 測試 |

## 11. 離線測試(unicorn,真韌體映像 `out/MAIN_c0000000.bin`,沿用 `lut/test_clist_native.py` 的相機模型)

- 安裝:16 點 + FV + root 全 claim,任一被拒什麼都不寫;客戶 0 個時 CSV 複本是原廠列數。
- 順序:客戶在容器前(provide)與後(add)兩種排列,結果的列、GUI 表、active 完全相同。
- setter:選列 → root 依記錄順序寫、三個快取鍵為 ~0;選原廠模式 → 原廠值反序寫;記錄 0 → root 不動、之後 `set_record` 才寫。
- 記錄越界(off 不在 claim 集合、n>12)→ `set_record` 拒絕。
- ±框:每列範圍夾值、夾到時框被拉回;關閉時 `strength_set` 只叫一次。
- 錄影旗標兩個落點各測:回呼不被叫、停錄後補送。
- 舊 RAW-View 檔頭 → COL-Share RELEASE、無任何寫入;SupManager 停用舊 RAW-View → COL-Share 正常。
- LUT 單獨:LUT 不寫任何 COLOR/root/DNG 點,Manager 仍可轉檔。
- 關機 journal:所有點(含 FV、root)寫回原廠;暖開機殘留(只 claim 不寫也要修)。
- 常駐大小斷言 ≤ 64 KB。
- 突變:任一 stock 字、記錄寫入順序反轉、錄影閘拿掉、`on_pick` 不叫、圖示指標指錯、退出判斷版本比較反向 —— 每個都要有測試失敗。

## 12. 上機步驟(先廣播相機使用權,用完廣播 released)

1. 建卡(skill `fp-merged-card`):COL-Share + LUT;讀 `\fpSup\LOAD.LOG` 的 LOADED 與 claim 數(COLS = 18 + root 數,LUT 減少相同數量)。
2. `ui_drive.py`:COLOR 鍵與選單各一輪,截圖列、圖示、大標籤;選 LUT 列 → LV 色、拍 JPG、錄 MOV FHD 29.97 約 10 秒(凍結測試),
   錄前錄後 `memmgr bufuse` 比較;±框改強度、關選單後重開確認保存。
3. `fastreboot.py now` 兩次(LUT 列 active 與 OFF 各一):10 秒內回來、LUT 自動重套;再一次冷開機。
4. 換舊 RAW-View v0.3.1 卡:LOAD.LOG 看到 COL-Share 退出、RAW 列照舊。
5. 只放 LUT:Manager 顯示原因、COLOR 清單是原廠 16 列。
6. P3 後:COL-Share + LUT + RAW-View v0.4,兩邊的列同時存在、互相切換、暖重開。
