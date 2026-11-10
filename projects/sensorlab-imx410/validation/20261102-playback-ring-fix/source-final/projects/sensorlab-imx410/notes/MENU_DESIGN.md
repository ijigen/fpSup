# SensorLab-IMX410：原廠選單那一側（設計，2026-10-30，離線，未上機）

規格：`../QS_DC_RES_SPEC.md`「選單（非 QS）設定」「生效與選單」「感光元件原生寬度標點」。
離線原型：`../menu/`（清單、CSV、頁面改動的位置表、測試）。**沒碰相機、沒改 `qs/`、`apply/`、`preview/`。**
證據等級：**[實機]** 在相機上看過、**[離線]** 反組譯或模擬、**[推]** 沒驗過。

## 0. 結論

| 原廠列 | 頁 | 做法 | 值存在哪 | 摘要文字 |
|---|---|---|---|---|
| 解析度（B2_5_4） | B2_5 | 這一列在頁面複本裡**改綁私有變數**＋**私有清單**（CSV 資源） | `SLM_Res` = 列號 → `struct sel` | 加一個 drawText 綁字串變數，C 寫 `2K`／`CUSTOM` |
| 每秒幀數（B2_5_5） | B2_5 | 同上；清單最長 50 列，達不到的 `0,0` 反灰 | `SLM_Fps` = 列號 → `sel.fps` | 同上，`59.94`／`57.123` |
| 位元深度（B2_5_2） | B2_5 | **原廠變數不動**；只把清單換成私有清單（8 bit、10 bit 反灰，RAW bit = 原廠 12-bit），12-bit 的摘要字改成 `RAW` | 原廠 `MV_DNGQuality`（12-bit 正是套用要的 TAB3） | 原廠 IconText03 改字面 `RAW` |
| DC 裁剪（B2_1_CINE） | MainB2 | 改綁私有變數；這個 popup **不是 CSV**，是 3 個固定子物件，要用同列的子物件複製到 7 個 | `SLM_Dc` = 列號 → `set_dc` | 同解析度 |

- **原廠設定一律不寫成我們的值**：解析度、DC 裁剪的原廠設定完全不碰；格率由套用單元自動設成載體（`AP_FR_SET`，原廠合法值，已是 Bei 定案）；
  位元深度停在原廠 12-bit。選單上看到的永遠是 `struct sel`。
- **誰擁有**：SensorLab 自己（fpsup-ui 的 `fpui_stock`），不放進 QS 容器。容器只多一個小 API：「下次 QS 開起來時，打開某功能的子 QS／細調」（§4）。理由在 §5。
- **跟 QS 共用同一份選擇**：選單的 watcher 呼叫 slqs.c 裡 QS 選項列用的同一組函式（`set_dc`、`set_res`、`fps`＋`fix_fps`），
  然後 `sq_push` → `ap_request`；記錄照舊在容器的 `leave()` 寫（進出選單本身就是版面載入）。

## 1. 依據（先前做過、這次查過的）

| 事實 | 等級 | 出處 |
|---|---|---|
| B2_5 是「開設定頁才解析」，整頁可換成私有複本（執行期項目 `+08`），退出重進生效 | [實機] | fp-native-ui §1、§8a（2026-10-02 B2_5→B2_6 對照） |
| 舊 Sensor Lab 在 B2_5 複製格率列、改成私有變數（`MV_SLMode`、`EXCL_SLMode`、`SL_ListFocusMode`）＋私有 CSV（私有 NBR 包、`modelCSV` 宣告、`C05E84D8` 註冊），12 列畫得出、選得到、摘要正確 | [實機 r9] | `open-gate/notes/IMX410_FULL_DESIGN.md` §8.12；`open-gate/build/sl_b25_page.py`、`sl_lists.py` |
| 私有清單在選單裡**即時改寫**（`modelCSV` 介面刪列、插列、通知），不退出就是新清單 | [實機 r15] | 同上，`sl_menu/sl_modes.c` |
| kind 16 popup 每一列要一組 `controlValueEvent`＋`controlFocus`，否則游標到得了但畫面不動 | [實機 r5] | fp-native-ui §2 規則 8 |
| 一個清單的上限不只一個：List、MenuItem_Select、IconChange 都要跟著改，漏 IconChange 會被夾回再觸發 setter | [實機] | fp-native-ui §2 規則 9 |
| 字串變數 → drawText（綁定要帶 component-id）即時顯示 | [實機 r43] | fp-native-ui §8b |
| 同一物件裡事件與動畫片段共用本地編號；重複就整機掛掉 | [實機 d5/d6] | fp-native-ui §8b 坑 3 |
| B2_5 自己有 `ChangeScreen`：`CM_TransitionFlag == 2` → `sync-request "QS"`；B2_5、MainB2 的 `CommonSystemKeyEvent` 都有 QS 鍵 → `ClearFlg` + `"QS"`（選單裡按 QS 鍵就是原廠開 QS 的路） | [離線] | 本次 `nbu_components`（B2_5 `0xC1A5E1CF`、`0xC1A5EB7D`；MainB2 `0xC20323A8`） |
| MainB2 沒有 `CM_TransitionFlag == 2` 的事件 | [離線] | 同上 |
| DC 裁剪 popup 的三個選項是固定子物件 `00/01/02`（drawText `0235/0236/0237`），不是 CSV；List 上限 2.0 | [離線] | 本次，MainB2 物件 21878 子樹 |
| 套用單元只答 TAB3（12-bit），key 去掉 `CROP` 尾碼再比載體，所以原廠 DC 裁剪值不影響 picker | [離線] | `apply/ap.c` `ap_key_rate`、H_PICK |
| 套用時原廠選單格率自動變成載體 | [離線，待 V1 上機] | `APPLY_DESIGN.md` §12.4 |
| QS 容器的 `qc_sub_open` 只改 8 個 `MV_QSMENU_QSn` 與焦點變數，**功能不在使用者 8 格裡就直接 return** | [離線] | `qs-container/qsct.c` |

本次量到的數字（`menu/test_menu.py` 釘住）：

| 清單 | 原廠列數 | 我們最多 | 原廠游標事件組 | 要補 |
|---|---|---|---|---|
| RES | 2 | 10（HD 9 個預設＋CUSTOM；任意自訂 DC 最多 8＋1） | 8 | +2 |
| FPS | 9 | 49（預設 DC×RES 的 QS 清單 46–48＋1 個細調值；上限 50，超過就退回 29 個常用格率） | 9 | +41 |
| BIT | 3 | 3 | 4 | 0 |
| DC | 3（固定子物件） | 7 | — | 4 個子物件 |

## 2. 每一列

### 2.1 共同做法

1. **頁面改動用 FPUI 區塊**（`fpSup/fpsup-ui/fpui_stock.c`，原廠座標、FSPG 複本鏈），在 `sup_entry` 套用。
   這樣 MainB2 的改動能跟 Lossless、Desqueeze、TapToZoom 加在 MainB2 的列疊在一起（各自複製「目前的樣子」）。
2. **頁面記錄只放靜態改動**。會變的東西（列數、上限、文字、反灰）一律走變數或私有清單資源，**不在執行期改頁面記錄**：
   後面載入的 sup 可能再複製一次頁面，我們手上的位址就不是畫面用的那份了。
3. 每列的靜態改動（位置表：`menu/b25_plan.py` → `menu/out/plan.json`，每一筆都有原廠字當 GUARD）：
   - **改名**：該列子樹裡的原廠變數名與清單名改成私有字串。RES 10 處、FPS 18 處、BIT 2 處、DC 11 處（測試釘住數量與每一處的原廠字）。
     `fpui_stock` 沒有「在原廠位置寫一個字串」的 op；v1 用 `ALLOC`（step 0）＋`SETSTR_SLOT` 湊出來，不改共用函式庫。之後若要乾淨，再提案在 fpsup-ui 加一個 op（共用，要協調）。
   - **游標事件組**：List 物件補到上限（RES +2、FPS +41），事件名照原廠 `"0v"`／`"v"`，原廠池有的名字就借用（開機成本）。
     新的本地編號 = 該物件事件與片段的最大值 + 1（[實機] 掛機教訓），建置時用 `sl_lab_page.duplicate_local_ids` 同一套檢查擋。
   - **靜態上限**：MenuItem_Select、IconChange 的 controlValue 上限 = 容量 − 1（只是夾值用，放大無害）。
   - **List 上限跟著列數**：加一個動畫片段屬性（List 的 controlValue `max-value`），由私有整數 `SLM_xN`（列數）當 apply-frame，
     每個可能的列數一格。原廠就有「EXCL 變數挑清單影格」的形式，舊 Sensor Lab 用同一個片段同時換清單名與上限 [實機 r9]。
     **List 上限永遠由同一個 `SLM_xN` 和清單一起決定**（§6 風險 1）。
   - **摘要**：插一個摘要物件（drawText＋`appVariableEvent` 綁字串變數 `SLM_xText`，r43 的 58-byte 形式），原廠 IconText0N 的字改指空字串
     （等長，不用動它們的片段）。DC 列的 `IconTextGray`（鎖住時的灰字）同樣處理。
4. **私有變數**（只在記憶體、每次開機重設；不寫設定區）：每列 `SLM_x`（值 = 列號）、`EXCL_SLM_x`（0 = 可選、1 = 鎖住）、`SLM_xN`（列數）、
   `SLM_xText`（摘要字串），FPS 另有 `SLM_FpsFocus`（原廠 `B2_n5_ListFocus4` 的替身），兩頁各一個觸發變數 `SLM_Go`。
5. **私有清單**：`SLM_RES`、`SLM_FPS`、`SLM_BIT` 三份 CSV，用私有 NBR 包（`modelCSV` 宣告，舊 Sensor Lab 的格式）在 UI 執行緒註冊。
   內容由 C 從 slqs.c 自己的清單產生（`res_list`、`fps_list`、DCN），格式 = 原廠 `.cvm`（BOM、表頭、每列 CRLF 含最後一列、反灰 `0,0`）；
   `menu_lists.csv_bytes` 對原廠 `B2_5_5.cvm`、`B2_5_2_excl.cvm` 逐位元相同。容量依 §1 的表預留。
6. **C 的同步點 `menu_sync()`**：每次版面載入（容器的 `leave()`，選單頁解析之前）與每次選單裡選了東西之後：
   算出四份清單 → 寫 CSV（頁面沒開時直接寫緩衝；開著時走 `modelCSV` 介面）→ 先推 `SLM_xN`，再推 `SLM_x`（目前列）、`SLM_xText`。

### 2.2 解析度（B2_5_4）

- 列 = QS RES 選項列同一份 `res_list(DC)`（1K…6K、DC 的乾淨倍率，HD 上加 FHD／UHD，去重、由小到大）＋ **CUSTOM（只在 RES 是自訂時）**，放最後。
- `sel` → 列：`res_hit(res_now())`；沒命中 = CUSTOM 那列。
- 列 → `sel`：預設列 = `set_res(w, h)`（跟 QS 選項列一樣，會丟掉這個裁切記住的自訂 RES）；CUSTOM = §4 的開子 QS，不改 `sel`。
- 反灰：沒有（清單本來就只列 ≤ DC 的）。錄影中整列鎖住（`EXCL_SLM_Res = 1`）。
- 摘要：K 標籤或 `CUSTOM`（= QS RES 格的大字）。

### 2.3 每秒幀數（B2_5_5）

- 列 = QS FPS 選項列同一份 `fps_list`：29 個常用格率（超過這組 DC×RES 理論最高的反灰）＋ 每個配方的最高格率 ＋ 唯一的細調值。
  細調值那列寫 `CUSTOM 57.123`，選它 = 開 FPS 細調（§4）。列數超過 50 → 只列 29 個常用格率＋目前格率＋細調值（`menu_lists.fps_rows` 已實作這條退路）。
  **這份清單要不要縮短，是 §9 問題 1。**
- `sel` → 列：`fps_sel()`。列 → `sel`：`s->fps = 那一列`，`st->dirty`，`sq_push`（跟 QS 選項列選取相同；達不到的列 C 一律不收，畫面只是提示）。
- 載體：看不到。原廠 `MV_FrameRate` 被套用單元設成載體，跟這一列已經沒有綁定。
- 摘要：`FPS.v()` = QS FPS 格的大字（細調中或不在清單上就寫三位小數）。
- **同一次進選單裡先改 RES 再開 FPS**：`menu_sync` 走 `modelCSV` 介面改清單與 `SLM_FpsN`，r15 證明這條路即時生效。

### 2.4 位元深度（B2_5_2）

- 原廠 `MV_DNGQuality` 照用；只把兩個清單影格（`B2_5_2`、`B2_5_2_excl`）都改指 `SLM_BIT`：`8 bit`（0,0）、`10 bit`（0,0）、`RAW bit`。
- 12-bit 的摘要 IconText03（`0307`）改字面 `RAW`；8／10-bit 的摘要保持原廠（原廠設定若是 8／10，照實顯示）。
- 不需要 C。**唯一的問題**：開機時原廠設定若是 8／10-bit，套用單元不會生效（只答 TAB3）。是否讓套用單元像載體一樣自動設成 12-bit → §9 問題 5。
- 反灰的 8／10 按下去會跳原廠「因以下的狀態無法選擇」對話框（列出原廠依賴）。這是 v1 規格要的反灰；對話框內容上機看（§6 風險 6）。

### 2.5 DC 裁剪（MainB2，B2_1_CINE）

- popup 是 3 個固定子物件（`00/01/02`，各有 `Text01`、`BG`）。複製 `02` 四次成 `03..06`（同頁、同列的物件，符合「donor 用同一頁」），
  文字改字面 `OG HD S35 APS-C S16 SQ`，第 7 個是 `CUSTOM`；每個新子物件補游標事件。
- `CUSTOM` 子物件的顯示綁 `opacity`（[實機]：`is-visible` 綁變數沒作用，`opacity` 有），List 上限由 `SLM_DcN` 片段決定（6 或 7）。
- 列 → `sel`：`set_dc(DCW[i], DCH[i])`（QS DC 選項列同一個，會依 Bei 定案 1 帶回那個裁切記住的自訂 RES）；CUSTOM = 開 DC 子 QS。
- 原廠 `CM_DCCrop` 不碰。原廠值若是 On／Auto，picker 照樣接（`CROP` 尾碼被去掉），但 LV 與放大的行為沒驗過 → §9 問題 6。
- 摘要：DC 名或 `CUSTOM`（= QS DC 格的大字）。

## 3. 摘要文字怎麼顯示

- 每列一個字串變數 `SLM_ResText`／`SLM_FpsText`／`SLM_DcText`，C 用 `C0593FE0(0, 名字, 字串)` 寫（只排指標，字串放 `struct st` 裡的常駐緩衝）。
- 頁面上那個摘要物件的 drawText 綁這個變數（r43 已證明）；原廠 IconText0N 改指空字串，所以不管 `SLM_x` 是幾，都只畫我們的字。
- 寫入時機：`menu_sync()`。進選單本身就是版面載入，所以第一次畫出來時已經是對的值。
- 字型：原廠摘要是系統字，`2K`、`59.94`、`CUSTOM`、`RAW` 都在字表內（`menu_lists.check_text` 只放可列印 ASCII，拒絕 `, " < >`）。
- **清單列的文字（modelCSV TEXT 欄）若剛好等於 .nloc 字串 id，原生清單畫的是那個字串**：live2 SS2784 的 `1000` 畫成「關閉」（id 1000 = Off）。原廠 id 都是 4 位數字（或 4 位數字＋`_…`），所以 `slm_cell_text` 把恰好 4 位純數字的列文字送成 `1000.0`（v0.7.2test）。摘要走 drawText 字串變數，不受影響。

## 4. CUSTOM → 離開選單 → 開子 QS

```
選單 popup 選 CUSTOM（OK）
  → SLM_Res 的 watcher（C0560FB0，UI 執行緒）看到 = CUSTOM 那列
  → 不改 sel；把 SLM_Res 推回目前列（摘要不跳）
  → qsc_api->open(api, SL41, "RES", QSC_OPEN_SUB)        // 容器 API 5：記下「下次 QS 開時要開的」
  → 推 SLM_Go + 1
頁面：我們的觸發物件（appVariableChangeEvent SLM_Go → controlAppState ClearFlg、sync-request "QS"；
      兩筆動作照抄同一頁 CommonSystemKeyEvent 的 QS 鍵）
  → 原廠狀態機 WildCard —"QS"→ QS_CINE（跟在選單裡按 QS 鍵同一條路）
QS_CINE 載入 → 容器在第一個焦點通知（0xC0582DB4 的 focus 站點）消化待辦：
  RES → qc_sub_open；DC → qc_sub_open；FPS → qc_fine_begin（先把 sel.fps 設成細調值）
使用者調完：AEL 回主 QS；MENU = 原廠 MENU（關 QS 開選單，容器換版面時收掉子 QS）→ 回到選單，摘要已是新值
```

- 原廠 AEL→B2_5 的反方向（`CM_TransitionFlag = 2`）在 B2_5 上不用改頁面也能用，但 MainB2 沒有 → 兩頁統一用自己的 `SLM_Go`；
  `CM_TransitionFlag` 當 B2_5 上的對照實驗。
- **容器要改的**（容器另有負責的 agent，這裡只列需求）：
  1. API 5 `open(api, sup_id, name, how)`，how = 子 QS 或細調；只記一筆，下一次 QS 焦點初始化時執行，開不了（鎖住、錄影中、不在 CINE）就丟掉。
  2. 功能**不在使用者 8 格裡**也要能開：用「獨立子 QS」（第 1 格 = 功能、其餘依子項或空白），關閉時回使用者 8 格、焦點在第 1 格。細調同理（只有第 1 格）。→ §9 問題 7。
- 沒有容器或容器停用：CUSTOM 列照樣顯示目前值，選了什麼都不做（不切畫面）。

## 5. 誰擁有、怎麼共存

**SensorLab 擁有選單列，不交給 QS 容器。**
- fpsup-ui 的原則（[[fpsup-ui-architecture]]）：sup 自己做 UI；只有多個 sup 要改**同一個原廠位置**時才需要容器協調。
  容器存在是因為 QS 格與編輯器清單由多個 sup 共用；B2_5／MainB2 的這四列目前只有 SensorLab 要換。
- 唯一會在同一列打架的是 RES-Custom（解析度清單、格率／位深清單），但它和 SensorLab 已經因為套用站點互斥（V1 清單「卡上不能有 RES-Custom」）。
- 把列攔截做進容器 = 容器變成第二套 UI 框架，還要設計通用的「換原廠列」API，工作量大、跟原則衝突。之後如果真的有第二個 sup 要換同一列，再做容器（像 res-custom 管 QS 那樣）。

| 共存對象 | 情況 |
|---|---|
| QS 容器 | 只多 §4 的 API 5；QS 頁、編輯器、記錄層都不受影響（我們不碰 QS_CINE）。 |
| Lossless／Desqueeze／TapToZoom（MainB2 加列） | 都走 FSPG 複本鏈，各自複製目前的樣子，載入順序無關。要驗 Lossless 的列＋我們的 DC 列同卡（§7 第 6 段）。 |
| ScreenFlip（TOOLS 頁） | 不同頁，無關。 |
| RES-Custom（v3／v4） | 互斥（套用站點）。 |
| OG3K／OG2K 舊版（v3、原地改 B2_5） | v4 loader 不載入舊 sup；不支援同卡。 |
| uishare（v3 套娃） | v4 不用；字串 id 走 loader 的位址規則，不掛任何字串 hook。 |

## 6. 風險

1. **焦點落在不存在或看不見的列**（凍結、游標消失）：上限比列數大就會發生。對策：List 上限只由 `SLM_xN` 決定、`SLM_xN` 和清單在同一個 `menu_sync` 裡先後寫；
   靜態上限只放在只負責夾值的 MenuItem_Select／IconChange；建置時檢查本地編號不重複；DC 的 CUSTOM 子物件用 opacity 藏、上限同時降。
2. **setter 夾值**：私有變數不經過原廠正規化器，但 MenuItem_Select／IconChange 的上限沒放大，值會被夾回再觸發一次（規則 9 的老問題）。三個上限全列在 plan.json，測試釘住。
   位元深度列仍走原廠 setter：原廠的位深正規化（res-custom 的 `bitnorm`）沒搬，某些條件下 12-bit 可能被壓（待上機）。
3. **設定區第一守則／首次開機**：不寫任何私有值到設定區；格率載體（套用單元）與 12-bit（若 Bei 同意）都是原廠合法值。
   開機時原廠可能是 MOV、8／10-bit、UHD、DC 裁剪 On、任意格率：選單只看 `struct sel`，跟這些無關；但套用要 CinemaDNG＋12-bit，不然選單顯示我們的值、錄的卻是原廠 → §9 問題 4、5。
   第一次開機（沒有 SLQ2 記錄）選單顯示 slqs 的預設選擇。
4. **其他地方仍顯示原廠值**：LV 資訊列的解析度／格率圖示、原廠 QS 的 RES／FPS 格、錄影計時（載體）都顯示原廠或載體值 → §9 問題 9。
5. **MOV**：我們的列在 MOV 沒有意義。v1 建議 SensorLab 啟用時格式固定 CinemaDNG（跟 QS 的 FORMAT 一致）；要支援 MOV 就得「原廠列與我們的列同 y、依格式互換顯示」（原廠 B2_5_2／B2_5_3 的形式），工作量大一截 → §9 問題 4。
6. **反灰對話框**：私有變數的列按到 `0,0` 時，原廠對話框的依賴清單來自哪個原生 menu item 類別不明，可能空白或列錯 → 第 4 段最先測；不行就改成不反灰、C 不收那一列。
7. **50 列的 kind-16 popup**：要補 41 組游標事件；超過 12 列的 B2_5 popup 捲到底、游標到最後一列，舊 Sensor Lab 只記到 r15「清單畫得出、即時更新」，沒有逐列記錄。
8. **從 popup 直接切 QS**：原廠只有「按 QS 鍵」這條路（先 `ClearFlg`）。popup 收合動畫或 `SYS_SubmenuOpen` 狀態殘留，可能讓下次進選單焦點不對（r17 `MENU_Level2` 的教訓）。
9. **選單裡就提交**：`sq_push` → `ap_request` 會停／啟 LV（估 60–150 ms），在選單畫面後面發生；setter 寫載體時原廠 `EXCL` 重算也在選單開著時跑。私有列不受影響，但要確認原廠其他列（格式列）不跳 → 或改成選單裡只記帳、離開選單才提交（§9 問題 10）。
10. **錄影中**：選單在錄影中能不能開未確認；能開的話四列鎖住（`EXCL_SLM_x = 1`），`ap_request` 本來就會延後。
11. **私有 NBR 註冊**要在 UI 執行緒、畫面清單沒滿時（舊 Sensor Lab r4 的凍結：第一個參數給錯）；v4 由 fpsup-ui 的註冊路徑做，先比對 reader 與 app。
12. **暖開機**：RAM 會留著上一輪的頁面複本與 hook；entry 先驗頁面項目是不是原廠或 FSPG 慣例，不是就整個選單不裝（`UIA_PAGE`）。

## 7. 分段上機（每段先告訴 Bei 並等回覆、廣播相機使用權；錄影中與回放中不碰 USB；先讀 `\fpSup\LOAD.LOG`）

| 段 | 內容 | 看什麼 | 失敗時 |
|---|---|---|---|
| 0 | 只讀：B2_5、MainB2 的執行期項目 `+08`、plan.json 的 GUARD 字逐一 `mem get` | 全部是原廠字 | 停，回頭查 |
| 1 | 只裝 RES 列：改名＋私有清單（靜態 9 列 HD）＋游標事件；watcher 只計數 | 畫得出、游標到第 1 與最後一列、選了摘要對（先用原廠 IconText 字面）、原廠 `MV_Resolution` 與設定不變、退出重進 | 換回不帶選單的 BIN |
| 2 | 動態：摘要字串變數、`SLM_ResN` 上限片段、`menu_sync` | 在 QS 換 DC → 進選單列數跟著變；游標到得了最後一列、到不了更後面 | 同上 |
| 3 | 接上 `sel`：選單選 3K → QS RES 格 3K；`ap_status` 有提交；`leave()` 寫記錄、重開機還在 | — | 同上 |
| 4 | FPS 列：46 列、反灰按下去的對話框、捲到底；同一次進選單先改 RES 再開 FPS；原廠 `MV_FrameRate` = 載體 | — | 對話框不對 → 不反灰版本 |
| 5 | BIT 列：清單、`RAW` 摘要、原廠 12-bit 不變 | — | — |
| 6 | DC 列（MainB2）：7 個子物件、CUSTOM 的 opacity 與上限；**同卡放 Lossless**，兩邊的列都正常 | — | — |
| 7 | CUSTOM 流程：B2_5 用 `SLM_Go`（另做一張 `CM_TransitionFlag` 對照）→ QS 開、RES 子 QS 開；AEL／MENU 返回；再做 DC（MainB2）、FPS 細調；功能不在 8 格裡的情況 | 每一步截圖；切換後 `status` 確認 shell 還在 | 卡住先讀卡（凍結紀律） |
| 8 | 浸泡：暖重開、冷開機（原廠設定先放成 MOV／8-bit／UHD／DC On 各一次）、錄影鎖、記錄還原 | — | — |

## 8. 離線原型（`../menu/`）與之後要接進 slqs.c 的地方

| 檔 | 內容 |
|---|---|
| `menu_lists.py` | 四列的參考：清單、目前列、摘要、每列選了之後做什麼（`set_dc`／`set_res`／`set_fps`／`open`），CSV 產生與表頭驅動的解析；`python3 -B menu_lists.py HD --res 2K --fps 59.94` |
| `page_lists.js` | 在 node 裡跑規格網頁（`preview/dcres.html`，唯讀）自己的 DC／RES／FPS 選項列 |
| `b25_plan.py` | 原廠 B2_5、MainB2 裡要改的每一處（改名、摘要字、上限）＋原廠字當 GUARD → `out/plan.json` |
| `test_menu.py` | 15 項，約 1 秒（要 node）：清單 = 網頁（45 個預設 DC×RES × 3 個格率＋13 個邊界狀態）、CSV = 原廠格式、容量、plan 的 GUARD 與數量、私有名不撞原廠池；`--mutate` 11 個突變全被抓 |

**還沒做（要 slqs.c 或 FPUI 組裝）**：FPUI 區塊本身（INSERT 游標事件組、摘要物件、觸發物件、上限片段、DC 子物件複製）、私有 NBR 清單包、C 端。

slqs.c 的接點（之後由 v0.5.x 的負責人接，不在這一輪）：
1. `struct st`：四份清單的列快取與 CSV 緩衝（容量 7／10／50／3 列）、四個摘要字串緩衝、上次推的列數、待開的子 QS。
2. `sup_entry`：`fpui_stock_apply(svc, 選單區塊)`（B2_5、MainB2 各一個 PAGE）；登記私有變數；`C0560FB0` 掛 `SLM_Res`／`SLM_Fps`／`SLM_Dc` 的 watcher。
3. 第一次版面載入（UI 執行緒）：註冊私有 NBR 清單包；之後每次 `sq_leave()` 呼叫 `menu_sync()`。
4. `menu_pick(f, row)`：查 `menu_rows` 的動作 → `set_dc`／`set_res`／`fps`＋`fix_fps` → `sq_push`（= QS 選項列選取的同一段）→ `menu_sync`；CUSTOM → 容器 `open` ＋ 推 `SLM_Go`。
5. 錄影鎖：`ap_busy()` 時推 `EXCL_SLM_x = 1`，停錄後的下一次 `leave()` 推回 0。
6. 測試：`test_slqs` 加 `Menu` 類，unicorn 裡驅動 watcher，C 寫出的 CSV 與 `menu_lists.csv_bytes` 同狀態逐位元相同（「C = 參考」）。
7. 容器：qsc.h API 5 `open`（§4）。

## 9. 要問 Bei 的

1. **FPS 清單長度**：照「和 QS 同一份」會有 32–49 列（含配方最高格率，例 `43.665`）。還是選單只放 29 個常用格率＋目前格率＋細調值（最多 31 列）？
2. **CUSTOM 只在細調過才出現**：那沒細調過時，選單沒有進子 QS 的入口。照規格這樣就好，還是要一直留一個 CUSTOM 當入口？
3. **細調格率那列的字**：`CUSTOM 57.123`？摘要寫 `57.123`（跟 QS 格一樣）還是 `CUSTOM`？
4. **MOV**：SensorLab 啟用時選單的格式列也把 MOV 反灰（跟 QS 一致，建議），還是要能選 MOV 並在 MOV 下顯示原廠三列（要多做「同位置互換」，大一截）？開機時原廠是 MOV 怎麼辦？
5. **位元深度**：套用單元要不要像載體一樣，在 SensorLab 生效時自動把原廠設成 12-bit（原廠合法值）？
6. **原廠 DC 裁剪**：原廠值是 On／Auto 時，要不要自動設回 Off？
7. **功能不在使用者 QS 8 格裡**時，從選單選 CUSTOM：開「獨立子 QS」（第 1 格是那個功能）可以嗎？調完 AEL 回使用者的 8 格、MENU 回選單？
8. QS 容器要加 API 5（`open`）：容器那邊現在有人在做，要排進它的下一版嗎？
9. LV 資訊列、原廠 QS 的 RES／FPS 格、錄影計時仍顯示原廠值或載體，v1 可以接受嗎？
10. 選單裡選了就提交（LV 在選單後面重載），還是離開選單才提交？
11. 字串改名用 `ALLOC`＋`SETSTR_SLOT` 湊（不動共用 fpsup-ui），還是在 fpsup-ui 加一個「在原廠位置寫字串」的 op？

## Bei 定案（2026-10-30）
- 每秒幀數列：跟 QS 同一份清單（32–49 列）。
- CUSTOM：一直留著（沒細調時也能選，選了就進子 QS）。
- 格式列 MOV：SensorLab 啟用時反灰，跟 QS 一致。
- 原廠 DC 裁剪設定跟我們的 QS DC 同步；我們的 DC 是 CUSTOM（細調）時原廠也顯示 CUSTOM。原廠位元深度：未答，照 RAW bit＝原廠 12-bit。

## v0.7.0test（2026-10-30，離線）

### FPS CUSTOM → FINE
- 選單的每秒幀數選 CUSTOM：呼叫 `open(…, QSC_OPEN_SUB_AT(0))`（容器 API 6，v0.3.1）。
- 打開 FPS 子 QS（FPS、FINE），焦點停在 FINE。FPS 不在使用者 8 格裡時，走容器的獨立子 QS，跟 DC／RES 同一條路。
- 舊的 `QSC_OPEN_FINE`（原地細調）不再使用。
- 測試：`menu/test_runtime.py MenuBridge.test_fps_custom_opens_the_fps_sub_qs_on_fine`（FPS 在格內、不在格內兩種），突變兩個（改成 SUB／改成 FINE）。

### 首個 MENU 回覆逾時（live-v1 01–06）
證據：`01-menu-open.json` 是 `ERR shl frame0 rc=-7 moved=0/64`。
- 命令有送出（選單也打開了），但第一個 64 B 回覆框在 camera.py 設的 5000 ms 內沒回來。
- 之後 shell 正常：app_current 5，MainB1 → MainB2 正確繪出，apply／menu／PBUI 結果都是 0，使用者看到的畫面也正常。

離線可以確定的：
1. 原廠 `key` 指令（handler 0xC03F5DC0）用 `FUN_c02dbbe8` 送出按鍵碼：`FUN_c02dbff0` → syscall，**逾時 0xBB8 = 3000 ms**，回覆要等它返回才產生。所以按鍵佇列忙的時候，回覆最多先被卡 3 秒；shell 任務在 UI 忙的期間排不到 CPU 的時間要再往上加。
2. 開機後第一次 layout load（就是第一個 MENU）在 UI 執行緒上做所有一次性的工作：
   - 容器 `qc_freeze`：CSV、QS 記錄、編輯器頁；
   - 開機還原的 commit：LV 停止／重啟，實機量過 9–27 ms；
   - v0.6 的 HUD 數字 NBR 註冊；
   - 私有選單初始化：17 個變數、NBR pack、兩頁 FPUI 複本（`fst_move`），v0.6 還把兩個 modelCSV 各寫兩次；
   - 寫設定記錄到卡。
   - 離線量測（`runtime_camera` 模型，原生服務是 stub，沒算進去）：第一次 layout 約 **21 M 指令**，之後每次約 0.94 M。其中 SensorLab 18.1 M（`fst_move` 12.75 M、`udiv64` 3.7 M），容器 3.0 M。
3. 同樣的現象在 v0.2.x 容器時就有：live2 第一次 QSON 逾時、約 3 s 後 shell 恢復；live4 一次 MENU 逾時；live5／6 QS 按鍵逾時。**不是 v0.6 才出現，也不是卡死。**

判斷：最可能是一次性的重 UI 轉換期間的傳輸逾時，主機設的 5 s 短於這段時間。這是推論，實際耗時沒有量到。

v0.7.0test 的處理：
- 初始化完只發布、不再重建 model（`slm_publish`）。測試 `FirstMenu`，加一個突變。
- v1 回放不在首個 MENU 註冊 NBR、不套 Playback 頁。
- leave() 記錄各階段耗時（`sq_test 29`）。

2026-10-30 live 診斷（`validation/2026-10-30-menu-diag/LOG.md`，卡上是退回後的 v0.5.0test／v0.2.4）：
- 首個 MENU 正常：按鍵 0.20 s，commit 15.7 ms；
- 離開選單時 shell 安靜約 2 s 之後恢復，這是 GUI／LV 重建；
- live-v1 那次只有一個按鍵 rc=-7，「卡住」**未證實**。
- 離線指令數（`tools/first_menu_icount.py`）：首次 layout 我們的程式約 20 M 指令，約 34–67 ms（估計），見 qs/README v0.7.0test。

上機要讀的（清單第 2 項；v0.7.0test 已補：`sq_test 29` 16 字、`sq_test 31` 容器 12 字、`sq_test 30` 暫停 push、`tools/live/pingloop.py`、`tools/live/ui_shot.sh`）：
- 從送出 `key MENUON` 到 `ping` 恢復的秒數（逾時設長一點，不重送按鍵）。
- `sq_test 29`：首次 leave 的總計／push／ap_idle／選單／寫記錄（µs）。
- `sq_test 27`（ready／result／updates）與 `sq_test 17` 的 commit_us。
- 如果 `lt[0]` 遠小於 shell 的延遲，時間就花在我們的 leave() 之外：容器 `qc_freeze`，或原生選單建頁。容器沒有時鐘，下一步要在 `qc_layout` 前後加 tick 記錄。
