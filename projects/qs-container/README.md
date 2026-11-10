# QS-Share（舊名 QS Container，sup_id `QSCT`）—— 0.0.1test（= v0.3.8 的程式，API 8）

## 0.0.2test（2026-11-07，API 9：細調與子 QS 並存，離線候選）

- Sensor Lab 0.0.2test 的需求（Bei 11-07）：主 QS 的 FPS 按 AEL 要回到原地細調，但選單 CUSTOM 仍要開 FPS 子 QS。
- 改動只有一處：註冊時不再拒絕「同時有 `fine()` 和 `sub`」的功能。行為沿用原本的優先順序：AEL 先走 `fine()`（原地細調），子 QS 只能由 `open(QSC_OPEN_SUB[_AT])` 打開。`api.version` 8 → 9。
- 舊用戶端不受影響（沒有人同時設兩個）。用戶端要在 `version >= 9` 才同時設，否則舊容器會整個拒絕那個功能。
- 測試：`test_api5.Api5.test_api9_fine_and_sub_on_one_function`（註冊、AEL 原地細調不換版、open 開子 QS 並落在第 2 格、子 QS 裡 AEL 回上層、細調中 open 會先結束細調）；兩個突變都抓到。

## 0.0.1test（2026-11-07，改名）

Bei 定：產品改名 **QS-Share**，版本從 **0.0.1test** 重新起算，卡上檔名 `QS-Share_v0.0.1test.BIN`；名稱與版本只在
`fpSup/loader-v4/names_v4.py`（`QSCT`），`build_qsct.py` 從那裡取。**sup_id 不變**（`QSCT`：用戶端用它找容器、設定記錄以它為鍵）。
合併頁上它不是選項：勾 Sensor Lab 時自動附上（`fpSup/tools/merge-v4`，`infra`）。
- 修正：`build()` 的字形迴圈把參數 `name`（顯示名稱）蓋掉了，0.2.1～0.3.8 的檔頭顯示名稱都是 `font_menu_SB_kigou_09`。
  迴圈變數改名 `glyph`；`test_qsct.Header` 檢查檔頭名稱 = names_v4 的 `QS-Share`。
- 跟 v0.3.8 的差別只有檔頭：名稱短了 → 檔案 202 888 → 202 876 B，`state_off`／`dma_off`／block 往下 64 B（設定字 2、3 隨之改）；
  程式碼、表格、設定記錄格式與位置（`rec_off`）都不變。檔頭的 version 字只是資訊（`sloader4.c` 只在 sups_list 回報；
  同名取新是比檔名的版本，`cand_cmp`），固定 `HEADER_VERSION = 38`（v0.3.8 原值），不再從版本字串算。
- `out/fpSup/QS-Share_v0.0.1test.BIN`：202 876 B，sha256 `dcc773534fc9778d9116796790f71879a4aa3fca650685b3da849a7763cc4028`
  （= `../sensorlab-imx410/qs/test-fixtures/settings-migration/frozen/QS-Share_v0.0.1test.BIN`）。
- **升級**：先刪卡上的 `QSContainer_v*.BIN` —— 同一個 sup_id，兩個都在時只載入一個（另一個記 dup）。設定記錄存在自己的 BIN 裡
  （`self_path`，跟檔名、版本字串無關），換新檔就回到預設；要保留就 `python3 -B build_qsct.py --out DIR --settings-from 舊.BIN`。
- 全部離線：沒碰相機、USB、卡片。


## v0.3.8（2026-11-05，轉盤提示）

很多使用者不知道後轉盤也能調。焦點在**我們的**格子或子項、而且那一項轉盤有作用（有 `adjust()`、沒反灰、沒被錄影鎖）時，
QS 頁尾提示列的**左端**顯示原廠前／後轉盤圖與步進：`[前轉盤圖]±1  [後轉盤圖]±10`。只有英文／符號，跟我們其他 QS 文字一樣。
**全部離線：沒碰相機、沒碰 USB。** SensorLab 由另一個 session 設旗標，這版只改容器與測試用戶端。

**合約（`qsc.h`，API 8，結構不變）**
```c
#define QSC_F_DIAL_HINT 0x00001000u
```
- 功能帶這個位元：焦點在它的 QS 格（含細調模式、子 QS 第 1 格）或它的子項，且**那一項**有 `adjust()`、`state()` 為 0、
  不是 `QSC_F_LOCK_REC` 錄影中 → 顯示；其餘（沒有 adjust、反灰、錄影鎖、GO 格、空白格、原廠格）一律不顯示。原廠格的提示照舊由原廠管。
  判斷跟箭頭（`QSC_Arw`）同一個條件、同一個地方（`qc_focus`，`FUN_c0582da0` 的焦點通知、轉盤之後、版面載入）。
- 後轉盤的步進照實際行為：API 4 表（`QSF4`）`±10`（`QSC_STEP_REAR`）；API 3／2 表 `±1`。前轉盤一律 `±1`。用戶端不用給文字、不用回呼。
- 位元選法：已用的是 1／2／4、`QSC_F_GO` 0x0F00、`QSC_F_REPLACE` 0x00FF0000（`FX_API4` 0x80000000 是容器內部）。0x1000 空著。
- **舊容器**（v0.3.7 以前）註冊時不檢查這個位元：功能照收、照舊運作、沒有提示 —— 所以用戶端不用看版本就能設
  （測試用實際的 v0.3.7、v0.3.2、v0.2.3 BIN 跑過：ui_id、箭頭、後轉盤 ±10 都照舊）。
- `api->version` = 8。設定記錄、表格式、其他 API 不變。

**原廠圖（證據）**
- 轉盤圖只有 `font_G_dial_front`／`font_G_dial_rear`（XCI 88×76，不透明列 6..67；另有 `_all`、`_release`），**沒有**頁尾尺寸（`_K153`／`_K187`）的版本。
  原廠用法 `English.nloc`：`0759` = `<!font_G_dial_front,CENTER>Front Dial`、`0760` = `<!font_G_dial_rear,CENTER>Rear Dial`（設定選單的轉盤列）。
- `±` 用原廠的 `font_G_plusminus`（36×54）：`0738..0743` = `<!font_G_plusminus,CENTER>5%`…、`0351` = `…0 dB`（後面接一般字的數字）。
- 頁尾提示的寫法：`Footer14_K` = `<!font_G_bt_AEL_K187,CENTER>Further Options`；兩段之間用 `<!44sp,CENTER>`（`Footer42` 等，`44sp.xci` 44×1）。
- 我們的字串（`qs_page_data.DIAL_TEXTS`）：`<!font_G_dial_front,CENTER><!font_G_plusminus,CENTER>1<!44sp,CENTER><!font_G_dial_rear,CENTER><!font_G_plusminus,CENTER>10`（API 3：最後是 `1`）。

**機制**
1. **QS 頁資料**（`qs_page_data.Design.dial_hint`，記錄層照舊）：原廠提示 `Option`（8512，Footer 下，1024×69 在 Footer (0, −69) = 螢幕 y 539..608）
   和它的 `BG` 子物件（8462，60% 黑底 1200×69）照抄成我們的一組，放在 Footer 下：
   `String`（Option 的 objectBase、Option 的 drawText —— 同字型、字級 54、垂直置中 —— 改**靠左**、rect (55, 1, 914, 54)，text 綁 `QSC_DH`）
   ＞ `BG`（toggleVisible，綁 `QSC_DHB`，跟選項列的框同形）＞ 子 0 = 空、子 1 = 原廠 BG 的 objectBase＋drawRect，位置移到框右緣 x≈450。
   原廠是「文字物件＞底框子物件」，我們同一個父子形狀，所以字在框上面的關係跟原廠一樣。
   標頭：物件 +4、objectBase +4、drawText／toggleVisible／drawRect +1、appVariableEvent +2、Footer 子物件 +1（預算測試照舊全過）。
2. **變數**（`NAMES` 尾端加兩個，舊 id 不動）：`QSC_DH`（文字，平常 " "）、`QSC_DHB`（整數，1 = 框）。
3. **文字放在 BIN**：兩段 128 B 的槽緊接在 go 文字之後（`cfg.dial_off`），跟名字、空白、go 文字同一段 borrow（GUI 留指標）。
   `qc_dial_hint` 只在變了才發（0 無、1 = ±10、2 = ±1），狀態字 `dh_last`、`dh_posts` 接在 `struct st` 尾端。
4. **為什麼是左端、行頂 y 1**：原廠提示靠右（文字右緣 969、框從字左 43 px 起到右邊外），有子項時「AEL Further Options」還在那裡，所以放左端、鏡像原廠的 55 px 邊距。
   轉盤圖 76 高、比 54 的行高，帶寬只有 69：照 live 3 的量法（內嵌圖從行頂 = rect y +（高 − 字級）÷ 2 畫起），原廠的 rect y 8 會讓圖的不透明列伸進選項列 6 px；
   改 y 1 → 不透明列在螢幕 546..607（格子到 531 為止、選項列從 608 起）。

**畫面上應該長這樣（離線推的，未上機）**
- 焦點在 SensorLab 帶旗標、可轉的格子：選項列正上方那條帶（y 539..608，原廠「AEL Further Options」那條）的**左端**，
  一塊 60% 黑的半透明框從螢幕左緣到 x≈450；框裡從 x 55 靠左：前轉盤圖（大實心圓帶黑環＋右下小空心圓）、`±`、白色一般字 `1`、44 px 空、
  後轉盤圖（大空心雙環＋右下小實心圓）、`±`、`10`。
- 有子項或細調的格子，右端照舊是原廠的 `[AEL] Further Options`；兩塊框中間約 120 px 空（右邊框的左緣是估的）。
- 子 QS／細調中右端沒有字（照 v0.2.2），左端照樣顯示。移到沒 adjust 的項、空白格、原廠格、或錄影中的 LOCK_REC 格：左端整塊（字與框）消失。

**離線**：新測試 `test_api8.py`（12 項：版本／變數／BIN 的兩段文字、原廠圖與字串存在、文字在 borrow 範圍（C05E61C8 owns）、
只在有 adjust＋旗標處顯示（B 無 adjust、D 無旗標、GO、原廠格、空白格不顯示；原廠格照舊寫 `QS_FooterGuidDisp`）、只在變了才發、
錄影鎖／`state()` 反灰、細調模式、子 QS（第 1 格、spinner、無 adjust 子項、鎖頭子項、無旗標功能的子 QS）、API 3 表顯示 ±1、
三個舊容器 BIN 忽略位元、頁面資料（物件、綁定、靠左、框、螢幕幾何）、標頭與本地 id），`--mutate` 18/18 抓到（程式 13、資料 5）。
測試用戶端 QSTest 加 `Q_DIAL`（config 位元 16 → `QSC_F_DIAL_HINT`）。`test_api5`／`test_api7` 的版本斷言改 8；其餘不動。
BIN 與建置紀錄另存 `projects/sensorlab-imx410/validation/20261105-boot-apply2/qs-container/`。

**上機才知道（未證實）**：靠左的 drawText 裡內嵌圖的水平位置（live 3 只看過置中的偏移；原廠選單列靠左帶圖是正常的）；
76 高的圖跟 54 的字在同一行時，字是跟圖頂對齊（推論，字會比圖中心高約 11 px）還是基線對齊；一般字 `1`／`10` 的實際寬度（框右緣 450 是估的）；
框在字下面（照原廠父子形狀推論）；toggleVisible 在 Footer 下切換（選項列的框已上機，但在 QSMode 下）。

## v0.3.7（2026-11-04，AEL 開原廠頁）

SensorLab 的 QR 格（`slqs.c` `F_QR`）要在 AEL 時離開 QS、打開 SIGMA 原廠「Load from QR Code」頁（狀態／頁名 `Y5_ReadQR`，`MenuQrCodeReadHandler`）。
容器加一個通用的「AEL 開原廠頁」，目前只有這一個目標。**全部離線：沒碰相機、沒碰 USB。** SensorLab 端由另一個 session 做，這版只改容器與測試用戶端。

**合約（`qsc.h`，API 7，結構不變）**
```c
#define QSC_F_GO(t)  ((((uint32_t)(t)) & 0xFu) << 8)
#define QSC_GO_MASK  0x00000F00u
enum { QSC_GO_READQR = 1u };
```
- 功能帶 GO 目標、`fine` 非 0：在它的 QS 格按 AEL（沒反灰、`state()` 為 0、`QSC_F_LOCK_REC` 不在錄影中）→ 呼叫 `fine(arg, 1)` 當**請求**：
  非 0 = 走，容器先收掉子 QS／細調，再經原廠狀態機要求換到目標頁；回 0 = 什麼都不發生，留在 QS。**走了之後不會呼叫 `fine(arg, 0)`**（GO 功能沒有細調模式）。
- 錄影中一律不走（就算沒設 `QSC_F_LOCK_REC`：錄影中原廠選單本來就進不去），容器自己的狀態機沒裝好也不走；這兩種情況不問 `fine()`。
- 註冊時檢查（跟 `QSC_F_REPLACE` 同一套）：目標不是 `QSC_GO_*`、不是 API 4 表（`QSF4`）、`fine` 為 0、或同時有 `sub` → 整個功能不收（`st.bad`）。
- `open(…, QSC_OPEN_FINE)` 對 GO 功能一律拒絕（回 0）。
- 舊容器（API ≤ 6）不認這幾個位元，會把 `fine` 當細調模式；所以用戶端要看 `svc->find(svc, QSC_ID)` 的 `api->version >= 7`
  （SensorLab 的 `sq_qr_go` 是在 `fine()` 裡檢查版本、舊容器時回 0，效果相同：舊容器上 AEL 什麼都不做）。
- `api->version` = 7。設定記錄、表格式、其他 API 不變。

**機制（照 loader v4 的 `ui_go`，`fpSup/loader-v4/README.md`「快速連按掉鍵 = 直接設畫面」那段）**
1. **QS 頁資料**（`qs_page_data.Design.go_event`，記錄層照舊）：Root 下多一個我們的物件 `ChangeScreen`（`dial_on` 的形式，objectBase 0×0），
   一個 `appVariableChangeEvent` 監看私有整數變數 `QSC_Go`（45 B、mask 3、type 3 = loader v4 `FT_Go` 那筆的形式；QS_CINE 本身沒有 type 3 的事件，
   用同頁 45 B 的記錄改 type），唯一的動作是原廠 AEL 開 `B2_5` 那筆 `controlAppState`（mask 0x23：sync-request、app-sync-request 0、view-state-event 1），
   **請求字串換成私有字串 = 容器的 go 緩衝區**（新 patch 種類 `P_GO`，緩衝區 32 B，放在 blank 之後、一起 borrow）。
   標頭：物件 +1、objectBase／appVariableChangeEvent／controlAppState 各 +1、Root 子物件 +1（預算測試照舊全過）。
2. **AEL**（`qc_ael` → `qc_go`）：`fine(arg, 1)` 說好 → 緩衝區寫入目標頁名 `Y5_ReadQR` → `QSC_Go` 推下一個值。變數是批次套用的，事件在同一批之後才送
   延後的 controlAppState（loader v4 的道理，2026-10-25 上機）。
3. **防回彈**：這個事件在 QS 頁每次建立時也會觸發一次。所以緩衝區平常是空字串（空請求什麼都不要），**只在一次 go 時有字**，
   下一次版面載入（`qc_layout`，換到 `Y5_ReadQR` 那一次）就清空。原廠頁不能寫回變數（loader 的做法是目標頁進場寫 `FT_Go = 0`），所以改由容器在版面載入清。
4. **狀態機**：原廠 17 台狀態機沒有任何一條從 `QS_CINE`（或 `WildCard`）用 `"Y5_ReadQR"` 轉換 [C：NBM `0xC2DE3D20`，`test_api7.test_stock_needs_the_private_machine…`]；
   原廠進入路徑只有 `TransMain_Y: MainY5 —"Y5_ReadQR"→ Y5_ReadQR`（MainY5 的 `JumpEvent` 送 `controlAppState "Y5_ReadQR"`）。
   容器在 entry 用 fpsup-ui 的 `fpui_install` 裝一個私有狀態機 `TransQscGo`：**只有 `QS_CINE —"Y5_ReadQR"→ Y5_ReadQR` 一條**
   （FT4S 檔放在 BIN 裡；fpsup-ui 的包一定帶頁，所以帶一個永遠不顯示、只有 END 記錄的頁 `QSC_GoPack`；沒有變數、沒有字串）。
   比對器 [C]：`FUN_c05ed028` 依序走 app+0xF4 的每台狀態機，`FUN_c05ece48` 找目前狀態，`FUN_c05ecce0` 比事件字串（`FUN_c0013e2c`）再看條件；
   那台沒有相符的轉換就換下一台，最後才走 `WildCard`。所以多一台只有一條獨有事件的機器，不影響任何原廠轉換（位置也無關）。
   用韌體自己的 NBR 解譯器、狀態建構式與比對器（`sl_pages.native_switch`）跑這個包：`(QS_CINE, "Y5_ReadQR") → Y5_ReadQR`；
   `(QS_CINE, "")`、`(Y5_ReadQR, "Return")`、`(QS_CINE, "B2_5")`、`(LV_CINE_LARGE/MainY5, "Y5_ReadQR")` 都不命中（留給原廠）。
   裝失敗時 `go_result` = 0x100 | fpui 錯誤碼，GO 格按 AEL 不做事。
5. **leave()**：go 造成的換頁就是一次版面載入，`qc_layout` 照舊先收掉細調／子 QS、再呼叫每個表的 `leave()`（測試確認 go 之後 leaves +1）。

**離開讀碼頁回到哪裡（決定：照原廠，不加轉換）**
- 讀碼頁自己的按鍵 [C：`Y5_ReadQR` 的 NBU 記錄]：**MENU**（KeyEvent 物件 4239，key 0x1B）→ `controlAppState "Return"` →
  `TransMain_Y: Y5_ReadQR —Return→ MainY5`（設定選單第 5 頁，「Save / Load settings」那一列所在）；**QS 鍵**（CommonSystemKeyEvent，key 0x14）→ `"QS"` →
  `TransSystem: WildCard —QS→ Choice0002 → QS_CINE`（CINE 時）＝ **直接回 QS**；半按／錄影／播放鍵 → `ClearFlg` + `"LV"` 等 ＝ 回即時畫面。
  讀到原廠設定碼 → `Y5_ReadQR_SaveSettings`（`TransLevel3`），返回再回讀碼頁。每一條都是原廠轉換，**不會卡住**。
- 原廠 QS 的 AEL 往返（`CM_TransitionFlag = 2`）**用不上**：那是目的頁自己的 `ChangeScreen` 物件在 `CM_TransitionFlag == 2` 時送 `"QS"`
  （`B2_5` 的物件 131 有 [C]；原生端 `XC_GuiMenuNotifier*::v402`（0xC059A148）只寫 0／1 [C]）；`Y5_ReadQR` 頁**沒有** `ChangeScreen` 物件 [C]，MENU 是頁面自己的 `"Return"`。
- 想過、沒做的兩條：
  - 歷史狀態（type 6 `PrevScreen`，回到 app+0x85c = 上一個畫面名，`FUN_c05e0690` [C]）：從 QS 進來會回 QS，但經過 `Y5_ReadQR_SaveSettings` 返回之後，
    「上一個畫面」變成存檔頁，MENU 會在兩頁之間來回 → 拒絕。
  - 帶條件的 `Y5_ReadQR —Return [QSC_xxx:v()==1]→ QS_CINE`：比對器確實在事件相符後才看條件 [C]，但條件式能不能讀到執行期才註冊的私有變數沒查到 [I]，
    而且容器看不到讀碼頁什麼時候被離開，旗標的壽命管不住（半按回 LV 後再從選單進讀碼頁，MENU 會被錯送回 QS）→ 先不做，要做得先上機查條件式。
- 結論：從 QS 進讀碼頁後，**QS 鍵回 QS、MENU 回設定選單第 5 頁、半按回即時畫面**。SensorLab 的「OK 套用後走原廠返回」也會回設定選單。

**新增狀態字（`struct st` 尾端，舊位移不動）**：`go_result`、`go_armed`、`go_seq`、`goes`、`go_refused`、`go_skips`
（位置 = `qsc_api.timing` + 112；`timing` 是 `tm[12]`，之後是兩組 8 字的鎖頭寬）。

**離線**：新測試 `test_api7.py`（11 項：API 版本與狀態機安裝、註冊檢查、AEL go（請求、文字、收掉細調、不呼叫 `fine(0)`、版面載入後清空、leave()）、
用戶端回 0、鎖／反灰／錄影、沒有狀態機、無 GO 位元的細調照舊與 `open(FINE)` 拒絕、QS 頁資料（事件／動作／請求 id）、私有狀態機經原廠比對器、
原廠狀態機與讀碼頁的返回路徑），`--mutate` 21/21 抓到（程式 16、資料／狀態機 5）。
測試用戶端 QSTest 加 `Q_GO`（config 位元 8..11 = 目標；`fine` 回 demo 的 `toggle`）。`test_api5` 的版本斷言改 7、`test_qs_page` 的參考值加 `P_GO`；其餘不動。
BIN 與建置紀錄另存 `projects/sensorlab-imx410/validation/20261104-qr-scan-build/qs-container/`。

**上機才知道（未證實）**：見該資料夾 `BUILD.md`「live-check」；要點：QS_CINE 上的變數改變事件會不會觸發（loader v4 只在 MainY5 底的頁證實過）、
QS（GUI 159，`MenuQsHandler`）直接轉到選單層的 `Y5_ReadQR` 時讀碼頁能不能正常起動（原廠只從 MainY5 進）、
私有狀態機帶一個永不顯示的頁在相機上裝得起來、「下一次版面載入才清空請求」的時機、MENU 回到 MainY5 時焦點落在哪一列。

## v0.3.6（2026-11-03，自訂 QS 編輯格的文字標題）

Bei 回報（SS__3054–3056）：自訂 QS 編輯頁裡 RECIPE、MB/s、QR 三格都借用 `menu_crop`（DC 的圖示），看起來像多了三個 DC。Bei 選擇「格子顯示文字標題」。

- **2026-11-03 上機通過**（Y2_3C；ShutterAngle 頁未上機）：三格顯示文字、原廠格不變、清單開關正常。第一版掛在 Icon01 下文字不出現——群組 pair 必須在擁有者子樹內，已改並加規則測試。**未解**：功能清單圖示條裡我們的列仍是 DC 圖示（CSV IMAGE 欄）。見 `validation/20261103-editor-title/README.md`。
- **做法（`editor_title.py`）**：兩個編輯頁（Y2_3C、Y2_3C_ShutterAngle）每格在 Icon01_CINE 下新增一個 `String` 物件（`string` 的同構：objectBase、drawText、clip 2），drawText 取名稱列 `MenuText/Text` 的樣式（置中、字級 36）。clip 2 的 text：t=0 空白，t(49+i) = 功能 i 若有 `QSC_F_TITLE` 就是它的標籤，否則空白；加入格子自己的 `Icon01_CINE` 群組（多一組 pair），跟圖示、名稱列一起隨 `MV_QSMENU_QSn` 播放。原廠 id 全部空白，原廠格不變。
- `QSC_F_TITLE` 功能在編輯格的圖示 rect／size = 0（QS 頁原本就是這條規則）。
- **串流複本新增三種編輯**（`qsct.c qc_page`）：`K_FRAG` 插入片段、`K_FPATCH` 片段內補值（`S_TITLE`／`S_BLANK`）、`K_ADDC` 加常數（記錄大小、群組 pair 數、Icon01 子物件數、表頭預算）。表頭照 `qs_page_data.Design.header` 的規則：objects／objectBase／drawText／animationClip 各 +8、群組 pair 數、pair-props 與 prop-keys 陣列各 8 筆。
- API 6、qsc.h、QS 頁記錄層、設定記錄格式都不變；用戶端不用改（SensorLab 早已對這三個功能設 `QSC_F_TITLE`）。
- **離線**：`test_qsct.EditorPages` 6 項（新增結構測試：表頭預算餘量與原廠相同、每個物件的 local／群組／子物件數、local id 不重複、每組 pair 都有 clip；16 個功能其中 6 個有標題），title 相關突變 11/11 抓到（1 個等價突變註明於 MUTANTS）。`cblob()` 快取鍵補上 Python 建置模組（原本只看 qsct.c）。證據 `validation/20261103-editor-title/`。

## 共用容器邊界與舊版顯示（2026-11-02）

文字內容、比例格式與功能狀態由客戶端提供；容器維護共用繪製、焦點及輸入介面。產品改文字或排版不應自動要求容器改版。新增可選顯示能力時，客戶端必須保留既有介面能表達的基本內容，不能在舊容器忽略新選項後整個消失；真正共用的介面擴充才另行處理能力與相容性。

SensorLab v0.7.16test 已在既有 `small()` 提供 `LOCK` 文字後備。QS v0.3.2–0.3.4 能顯示文字，v0.3.5 保留小字列原生圖示，解鎖都隱藏；已離線執行四版實際 BIN 核對。本次不改 QS 程式、不新增 QS 版本，亦不改 API 6。以下各版說明保留歷史。見 [SUP 與相容性核對](../sensorlab-imx410/validation/20261102-sensorlab-sup-audit/README.md)。

## v0.3.5（2026-11-02，比例欄小字 LOCK，離線候選）

新增 `QSC_LOCK_SMALL_OPEN/SHUT`，讓客戶端保留標題與大字值，將原生 `menu_lock_qs` 顯示在小字列。圖示 rect `(68,147,120,59.2)`，保持原圖比例，實際不透明區落在小字列內；`QSC_SW1..8` 綁定寬度 0／120，解鎖或離開子選單清除。舊 TITLE／OPEN／SHUT 客戶端保持原行為，API 6 與設定格式不變。

配對 SensorLab v0.7.14test，DC／RES 比例格的標題為 `RATIO`。這版不修改 14-bit 回放；實體 LCD 尚待使用者確認。見 [本輪紀錄](../sensorlab-imx410/validation/20261102-ratio-small-lock/README.md)。

## v0.3.4（2026-11-02，LOCK 位置修正候選，離線）

使用者提供 SS__2900.JPG：v0.3.3 的比例格 LOCK 向右偏並遭裁切。內嵌圖原點落在格子中心 x=128，而不是減去半個圖寬後的 x=53；這與下方 live3 已記錄的 inline 圖偏移相符。v0.3.3 的離線檢查只驗證垂直不重疊，手工排版圖也沒有走原生水平定位，因此未抓到這個錯誤。

`menu_lock_qs` 的 TITLE_SHUT 顯示改成獨立原生 `drawImage`，rect `(53,42,150,74)`；`QSC_LW1..8` 整數綁定 rect 第2維，150顯示、0清除。物件維持可見，避免藏起物件後其變數事件不再更新。圖示僅在所屬比例格顯示，解鎖、退出子選單或離開該格功能時清除。其他 icon／舊API的圖示規則沿用。

API 6、設定記錄格式、AutoRun／LOADER均不變。SensorLab v0.7.7test 沿用，只需換 QSContainer。驗證記錄見 [本輪 REPORT](../sensorlab-imx410/validation/20261102-lock-position/REPORT.json)；實體 LCD 尚待使用者確認。


## v0.3.3（2026-11-02 使用者截圖確認 LOCK 偏右，已由 v0.3.4 候選取代）

新增可選 `QSC_LOCK_TITLE_OPEN/SHUT` 回傳值：SHUT 在標題行使用 `qsc_sub.icon`，OPEN 留空，值行保持原生粗體。SensorLab v0.7.7test 提供原生 `menu_lock_qs`，讓比例在大字區；既有 OPEN/SHUT 客戶端的鑰匙位置不變。ABI／設定格式不變，舊容器會忽略新回傳值而保留文字標題與值。

原生圖示在行頂／框中心兩種位置解讀下均不碰大字；實際 ARM 子選單檢查兩種狀態與即時比例更新。相關 QS 回歸57項、兩產品設定遷移8項通過，LCD 未驗收。需與 SensorLab 配對更新，不改 AutoRun／LOADER。見 [候選驗證及精確產物](../sensorlab-imx410/validation/20261101-ratio-ui/REPORT.json)。


## v0.3.2（API 6 不變，2026-10-30，離線，未部署）

`out/fpSup/QSContainer_v0.3.2.BIN`：176 736 B，sha256 `a73c9fcd6d7ca8c122a085cd77251e59209778442427e0930a2ebacbdcaff512`（`out/build-0.3.2.json`，預設空白記錄）。
修「開機後 AEL 沒反應，焦點經過 K 格才好」（live4 第 8 點、SensorLab v1-live2 第 7／9 點）：
- 成因：我們的 AEL keyEvent 放在原廠 `Button/AEL`（物件 8514）裡；QS_CINE 的 `Button` 有兩個事件：`QS_AELbtn` 一變 → AEL `is-visible` 0，`== 1` → 1。
  看不見的物件 keyEvent 不觸發。`QS_AELbtn` 只有原廠 `QSMode` 底下每個 id 的 holder 會寫（K 的 `WhiteBalance` 寫 1 等），我們的 49..72 沒有 holder，
  所以值停在上一個原廠格留下的：開機第一次開 QS 焦點就在我們的格子、或選單 CUSTOM 直接跳進子 QS 時是 0 → AEL 死；經過 K 之後是 1 → 好了。
  轉盤不受影響（`Dial` 由 T2 自己開）。
- 修法：`qc_focus`（GUI 路徑）焦點在我們的 id 時寫 `QS_AELbtn`（韌體字串 0xC2DAAD34）：AEL 有作用（有子項／細調、子 QS 或細調中返回）= 1，否則 0，跟原廠 holder 一樣；原廠格不碰。
- 測試：`test_api5.Api5.test_ael_object_shown_on_our_tiles`（資料：原廠閘門與我們不寫它；ARM：開機第一個焦點、無功能格 0、子 QS 1、原廠格不寫、選單跳子 QS 項目／細調 1）；
  兩個突變（不寫、只在 more 時寫）都抓到。SensorLab 端不用改。

同版另修 live4 第 15 點「RATIO 格的鑰匙圖蓋住 `1.778 : 1`」：
- 量測（live4 SS2585，格子原點 y≈73）：內嵌圖從**行頂**畫起 = 框 y +（框高 − 字級）÷ 2，值框 96+62、字級 54 → 圖頂 y≈100；
  `menu_select_lock/unlock` 是 96×96，不透明列 30..68／11..85 → 鑰匙在 130..168／111..185，小字框 150..190 → 重疊。
- 改法（`qc_texts`，API 4 鎖圖）：圖仍在值行；**小字有內容時改放標題行**（38..86，白色細體），小字列留空；沒小字時標題照舊。
  SensorLab 的 RATIO 格會變成「`1.778 : 1`／鑰匙」，`RATIO` 這個標題字不再出現。兩種讀法（行頂、框中心）圖的不透明列都在 86 以下（≥ 90）。
- 測試 `test_api5.Api5.test_lock_icon_clear_of_the_text`（ARM：鎖／開兩個圖都是 L=小字、V=圖、S／Y 空；沒小字時標題留著；幾何：兩種讀法下圖與有字的列不重疊，且舊版位置在模型下確實重疊）；
  突變「小字留在圖下」「沒小字也蓋掉標題」都抓到。

## v0.3.1（API 6，2026-10-30，離線，未部署）

`out/fpSup/QSContainer_v0.3.1.BIN`：176 608 B，sha256 `59bdd1361d973707d313cd77f8eea98264a9cc1ba3ae62cc3c9aafa03436752d`（`out/build-0.3.1.json`，預設空白記錄）。
`api->version` 改成 6，table magic 和結構佈局不變。給 SensorLab v0.7.0test 的 FPS 子 QS 用：
- `qsc_sub.blur(arg)`（原本的 `reserved` 欄位）：子項目有焦點時記住，焦點移到別處、AEL／MENU 返回、子 QS 關閉、任何 layout load 時呼叫一次。轉盤不會觸發。呼叫在貼文字之前，所以畫面看到的是離開後的值。舊容器收到非 0 的值會拒絕整個功能。
- `open(…, QSC_OPEN_SUB_AT(k))`：打開子 QS，焦點停在子項目 k（第 k+2 格）。功能在 8 格裡、或是獨立子 QS 都可以。k 超出範圍、對 FINE 帶 k、或帶未知位元，都會拒絕。
- `qsc_api.timing`：12 個字，記錄 layout 的耗時，用韌體 tick `0xC002B6E0`、單位 µs。
  - 首次 layout 的六個絕對時間點：進入、收集開始、收集結束、leave 開始、leave 結束、原廠 loader 結束。
  - 首次 layout 的寫回耗時。
  - layout 次數、最大耗時、最近一次耗時、首次總計、寫回次數。
  - 給首個 MENU 的量測用；SensorLab 的 `sq_test 31` 會回傳這組字的位址。
- `STATE_RESERVE` 從 64 KiB 改成 68 KiB。`struct st` 原本離 64 KiB 只差幾十 bytes；超過時 entry 會靜靜地拒絕載入。
- 測試：`test_api5` 新增三項：`test_open_sub_at_focuses_the_item_present_or_standalone`、`test_blur_on_focus_move_back_and_layout_not_on_dials`、`test_layout_timing_words`。`python3 -B test_api5.py --mutate` 共 16 個突變，全部抓到。

2026-10-30 的前一版離線版本是 **v0.3.0／API 5**：menu `open()`、QS 原廠格取代與隱藏重複清單列，見 [README-api5.txt](README-api5.txt)。下文保留早期版本與實機觀察；目前建置在 `out-takeover-v030/`，尚未部署。

`fpSup/QSContainer_v0.2.1.BIN` + 測試用戶端 `fpSup/QSTest_v0.2.1.BIN`。讓別的 sup 把功能加進原廠「自訂 QS」編輯器的清單與 **QS 頁**：
編輯器裡那格有圖、有名字（階段 1，10-29 上機通過）；QS 頁上那格有圖、粗體值、小字、下方選項列，轉盤調用戶端的值，AEL 在同一個 QS 面板開子 QS（階段 2）；
設定區（flash）永遠只存原廠 id。
設計：`projects/qs-touch/notes/QS_CONTAINER_DESIGN.md`（§8 子 QS、§9 Bei 定案、§10 子 QS 版面更正）；`QS_EDITOR_ID_PATHS.md`、`QS_ADD_FUNCTION_RESEARCH.md`、
`research/ui/CUSTOM_QS.md` §3/§8/§12。韌體 Ver.5.02，loader v4。
**v0.2.1 全部離線：沒碰相機、沒碰 USB、沒寫卡。** 共用 loader 位元組與其他產品都沒動（只讀 `fpSup/uishare/ui/qs_recipe.json` 來避開它的記錄）。
升級注意：檔名換成 v0.2.1，卡上不要同時留 v0.2.0（舊 BIN 的格子記錄不會被讀，那幾格開機後是放入前的原廠功能，重新放一次即可）。
第一個正式用戶端：`projects/sensorlab-imx410/qs/`（SensorLab-IMX410 的 DC／RES）。

## v0.2.3（API 4 不變）：主 QS 畫面排版（live run 4，`validation/2026-10-29-live4/LOG.md`；規格 QS_DC_RES_SPEC.md「排版逐項修正 1」）

`out/fpSup/QSContainer_v0.2.3.BIN`（172 760 B）；v0.2.2 的 BIN 留著。

| 問題 | 成因 | 修法 | 測試／突變 |
|---|---|---|---|
| 選項列沒有第二行的數字（FPS、RES）貼在框的上緣，點狀標記看起來像第二行 | 標籤 drawText 的 rect 固定在 74 px 框的上 42 px（給兩行選項用）；標記是另一個 drawText（16 px，y 34） | 加三個置中角色 `QSC_FP/FQ/FR<j>`（白／灰／黃，rect y 16..58，中心 = 框中心 37，跟原廠 K 轉輪同高）；選項沒有第二行（含 spin 的值與箭頭）就用置中角色。標記改 12 px、y 56..68（在置中數字下方、框內），8 點。名稱 148 → 193 | `MainQS.test_one_line_label_centred_and_mark_thin`、`Api4.test_footer_roles`／`test_fine_mode`；`footertop`、`fatmark`、`one-line label in the top role`、`spinner arrows in the top role` |
| RECIPE 標題上蓋著 DC 圖示 | `QSC_F_TITLE` 只換了標題文字，Icon01 仍依 P_LOOK 拿預設借用外觀（menu_crop） | P_LOOK：`QSC_F_TITLE` 的功能 rect／size = 0（跟子 QS 格同法） | `MainQS.test_title_function_has_no_icon`；`title function keeps the borrowed icon` |
| 我們的格子留著「AEL 白平衡調整」 | 提示文字 = `QS_FooterGuid1` 的影格，原廠只有 K 格寫它（4/5 = 白平衡調整）；`QS_FooterGuidDisp` 的事件掛在 10632（`LensStatus` 影格 1 才可見，看不見的物件事件不觸發），所以單寫 Disp 藏不住 | 焦點到我們的格子：有自己的提示寫 1（AEL 更多選項），沒有（無子項、鎖住、子 QS／細調且 MENU 不返回）寫 0（無字、無底框）；原廠格不動 | `MainQS.test_hint_text_ours`；`hint text left to the stock`、`hint text always "more"` |

**沒上機驗證**（10-29 15:05：卡上 CINE 格是原廠 21 12 23 25 39 50 27 19，不是我們的功能；改格被權限擋下）。
另外原廠格之間 GuidFooter1 照舊由原廠管：離開我們的格子到 COLOR／WB 等時提示可能是 0（無字）——原廠本來也只有 K 寫它。

## v0.2.2（API 4）：live run 3 的修正與 SensorLab 要的新 API（`validation/2026-10-29-live3/LOG.md`）

`fpSup/QSContainer_v0.2.2.BIN`、`fpSup/QSTest_v0.2.2.BIN`（`out/build-0.2.2.json`；v0.2.1 的 BIN 與 `out/build.json` 留著）。全部離線。

| live 3 | 成因（離線查到的） | v0.2.2 |
|---|---|---|
| 子 QS 按 MENU：回到 8 格**而且**原廠 MENU 也跑了（關 QS、開選單），之後 shell 卡住（關係未證實） | 我們在 MENU 的處理裡**同步**把 8 格寫回使用者的 id；原廠 `Menu` keyEvent 是用 `type` clip 依 id 關掉的，寫回之後其他格又是原廠 id、`Menu` 又開著。keyEvent 處理器 C05FBFB8 讀的就是 `type`（bit0 按下、bit1 down），所以只要同一次按鍵還有格子被處理，就會跑原廠的 `controlAppState "Menu"`。離線無法證明是哪一格（沒有按鍵分派的模型） | 預設**不接 MENU**：頁面不再加 MENU 開關（`QSCT_MENU_BACK=1` 可建回 v0.2.1 的資料，cfg flags bit0），MENU 在子 QS 就是原廠 MENU（關 QS，換版面時容器把子 QS 收掉）；**AEL 回上層**（AEL 從 t(49) 起只有我們的 keyEvent，寫回後焦點格是我們的 id，不會跑原廠 AEL）。子 QS／細調裡提示列**隱藏**（原廠沒有「AEL 退回」的字串） |
| 鎖頭圖蓋到 LOCK/FREE | 96×96 的圖放在 48 高的標題列 | API 4：標題留 `RATIO`，鎖頭圖畫在**值**的位置（API 3 不變） |
| 第 1 格 `RES.` 偏右 | inline 的外觀圖在 drawText 裡置中位置不對（偏移 ≈ 圖寬的一半，鎖頭也一樣） | API 4 的功能：子 QS 第 1 格標題用標籤文字；`QSC_F_TITLE` 讓主格也用文字 |
| `CUSTOM` 塞滿整格 | LB 字形每字 40 px | 值的字形寬（建置時從 XCI 讀）超過 220 px 改用系統字 |
| 長小字跑到箭頭下 | 小字框 256 寬 | 小字框改 x 24..232、字級 30 |
| 我們的小字是白的（原廠灰） | 字形圖（XCI 是 L8A8，亮度 255）不吃 drawText 的顏色；`mm`、`x` 這些系統字是灰的 | 小字一律系統字（灰／黃都是 drawText 顏色） |

API 4（`qsc.h`，表的 magic `QSF4`；`QSF3`/`QSF1` 照收、行為不變）：

| 新東西 | 怎麼用 |
|---|---|
| 細調模式 `qsc_func.fine(arg, on)`（原 `reserved`） | 沒有子 QS 的功能可給；AEL → `fine(arg,1)`（回 0 = 不進），版面不變，轉盤照常 `adjust`／`footer`（用戶端自己回數字轉輪）；AEL 再按、焦點移走、任何換版面 → `fine(arg,0)` |
| 選項列 `mark`／`custom`／`grey`（`qsc_foot` 尾端加 `grey`） | 位元 i：點狀底線（`. . . . . .`，焦點色）、標籤黃色（#ffd66b）、反灰（標籤 #55595e、小字 #8a6f3a，當原因列）。頁面每個位置 7 個 drawText（v0.2.1 是 3 個），變數名 148 個 |
| 後轉盤 | 頁面 BL/BR 的碼改成 3/4；API 4 的 `adjust` 收到 ±`QSC_STEP_REAR`（10），API 3 照舊 ±1 |
| 子項 7 個 | 第 8 格用 UI 72（只有 7 項時它是第 7 項，否則是空白） |
| `QSC_F_TITLE` | 主格標題用標籤文字、不畫借來的圖 |
| `qsc_table.leave(arg)` | 每次換版面呼叫（不在按鍵路徑上）：用戶端在這裡寫設定記錄 |
| 選項文字 | 每個 ≤ 63 bytes（`FT_BYTES` 64，反灰原因列較長） |

**用戶端要不要自己做 FORMAT**：要。原廠格的值是 `Icon02` 影格、選項列是 holder 的 keyEvent（直接改 `MV_RecordingFormat`），
容器只管自己 id 的格子；讓用戶端蓋原廠格要改頁面資料讓原廠 holder 停用，而且原廠選項列會寫原廠設定。SensorLab 自帶 `SL FORMAT`。

測試：`test_qs_page.Api4`（細調三種結束方式、後轉盤 ±10 只給 API 4、灰／黃／底線各自的 drawText、`QSC_F_TITLE`、`leave` 只在換版面）、
`test_no_menu_switch_by_default`、`test_menu_is_the_stock_one_by_default`；突變：test_qs_page 70/70、test_qsct 34/34（新增 18 個；v0.2.1 的 MENU 開關與提示切換突變在預設建置下等價，已移除並註明）。

## v0.2.1：10-29 第二次上機（`validation/2026-10-29-live2/LOG.md`）的修正

| # | 上機看到的 | 成因 | 修法 | 回歸測試（＋讓它失敗的突變） |
|---|---|---|---|---|
| 1 | 子 QS 回來後 6 個原廠格只有標題、沒有值（再開 QS 才好），之後改值也不畫 | 我們用 `Icon02` **自己的** `is-visible` 把它藏起來（我們的 id 上），而**看不見的物件的事件不會觸發**：回來時 `MV_QSMENU_QSn` 變了，`Icon01` 的事件有跑（標題回來），`Icon02` 自己身上的同一個事件卻沒跑，`Icon02` 停在隱藏。改 RES 值之後也不畫（024445）＝整個 `Icon02` 子樹看不見，不是值沒重發 | 每格的**值文字物件**（永遠看得見）加一份同樣的事件＋動作（`MV_QSMENU_QSn` → 播 `Icon02` 的 `Icon02` 動畫）；藏的方式不變 | `Icon02Return`：模型加上「看不見的物件不觸發事件」，8 格 × 原廠 id × 每個子 QS id 走「原廠 → 子 QS → 原廠」，`Icon02` 套用回原廠影格且看得見；`notrigger` |
| 2 | 我們的格子下方一個空的反白框 | `Footer` 群組在我們的 id 上停在中性影格，原廠游標（`Cursor` 9113）是上一格的 holder 打開的，沒人關 | API 加**選項列**（標籤、第二行、目前索引；`spin` = 原廠色溫格那種 `◀ 5550K ▶` 數字轉輪）。頁面加一個我們的物件（掛在 `QSMode` 下，跟原廠 holder 同層）：`QS_QSMode` ∈ 49..72 → `Cursor` OFF；15 個位置（64 px 格點、每格 128 寬，n ≤ 7 個選項不論奇偶都置中：第 q 個在位置 8 − n + 2q）× 標籤／小字／黃色小字的 drawText；框 = `toggleVisible`（耳機格的同形）綁 `QSC_FB`，子物件 0..14 是原廠游標的 drawRect、15 = 無。超過 7 個以目前那個為中心捲動 | `Footer`、`PageStrip`；`nocursoroff`、`nostrip`、`footer not centred`、`box never drawn`、`not following the dial`、`spinner ignored` |
| 3 | 沒有 adjust 的功能也有 ◀ ▶；沒有子項的也有「AEL 更多選項」 | 箭頭是 Root 的 `Arrow` 動畫，由原廠 holder 開，我們的格子上沒人關；提示是 `FUN_c057f310` 對所有 id ≥ 4 都寫 `QS_FooterGuidDisp = 1` | 箭頭：同一個物件加 `QSC_Arw == 1 / == 0` → `Arrow` ON／OFF（原廠 holder 的兩個動作），容器在焦點到我們的格子時發（有 adjust 且未鎖 = 1）。提示：hook `FUN_c0582da0` 裡的 `bl FUN_c057f310`（0xC0582DB4，`SL_CHAIN`）：我們的 id 照原廠寫法（比對 QS 狀態的副本再經 `FUN_c054dd38` vt+0x2C）只在有子項時寫 1；這個點同時是「焦點換了」的通知（選項列、箭頭在這裡更新） | `test_arrows_only_with_adjust_and_hint_only_with_sub_items`；`arrows always on`、`hint for every function`、`stock hint not set` |
| 4 | 我們的值是細體 | drawText 用 `fontsetting` | 值改用 drawText 內嵌**原廠值的字形圖**：每個字元 → `<!font_menu_LB_…,CENTER>`（原廠 QS 的 `2500`、`DNG` 就是這組圖；數字、A–Z、`. : ; - / + × # %`）；字形沒有的字元（小寫、空白、`·`）照原樣，同一行混排。小字用 `font_menu_SB_…`（數字、`. : - / + ×`、`K F T s`）。對照表在 `build_qsct.GLYPHS`（字形圖逐張畫出來看過） | `test_value_is_drawn_in_the_stock_bold_glyphs`；`value in the plain font` |
| 5 | 子 QS 格子跟原廠格不像 | 只有標籤＋值，同字級 | 每格三行：標題列（rect y 38、字級 40；子項的標題、或 `icon`、或鎖頭圖 `menu_select_lock`／`unlock`；子 QS 第 1 格 = 功能自己借來的外觀圖）、粗體大字（y 96）、小字（y 150，灰；`QSC_T_APPROX` → 黃）。小字兩個物件（灰／黃）各有自己的顏色 clip（＝格子的白／反灰 clip 乘上色） | `SubTiles`、`test_title_value_and_small_text_objects`；`small line not drawn`、`approximate line ignored`、`lock icon ignored`、`tile 1 without the function look` |
| 6 | 重解析計數一直是 0，但命中 114 | 計數只算「快取還握著開機前解析的 QS 版面、我們放掉它」的情況。上機時快取握的已經是別的頁（MENU 之後最後載入的那頁），沒有東西要放，下次開 QS 本來就會重新解析經過我們（命中 114 證明了） | 不是 bug；加 `qs_fresh`（S+10920）：「快取沒握著它，照樣會經過我們」記 1。上機判讀：`qs_reloads` + `qs_fresh` = 1，命中 > 0 | `test_not_cached_counts_as_parsed_fresh`；`fresh parse not counted` |

另外照 Bei 10-29（設計 §10、規格 6）：**子 QS 裡功能移到第 1 格**（UI 65，焦點在它），子項從第 2 格排（66..71，最多 6 個），
其餘空白（72）；**MENU 返回**（AEL 也可以），焦點回到功能原本那格。MENU 的路：每格的原廠 `Menu` keyEvent（關 QS）用
每格 `Icon01_CINE` 群組裡一個新的 clip 依 id 切換：65..72 時它的 `type` = 0、我們的新 keyEvent（同鍵，`QSC_Key ← 6`）= 2
（原廠格子的 `Lock` clip 就是這樣開關方向鍵）。子 QS 裡的提示是原廠字串「MENU 退回」（`Footer03_K`，編輯器頁尾那一條）：
提示文字物件 `Option` 的影格 = `QS_FooterGuid1`，原廠 0..13；加第 14 格 = `Footer03_K`，子 QS 開時寫 14、回來寫 1（`Footer14_K`「AEL 更多選項」）。
（測試 `test_menu_key_switches_at_the_sub_ids`、`test_menu_returns_from_the_sub_qs`、`test_hint_frame_menu_back`；
突變 `nomenu`、`menuopen`、`nohint`、`MENU ignored`、`sub-QS keeps the function in place`、`focus not on tile 1`、`return focus not on the own tile`、`hint not switched`、`return hint not restored`。）

## v0.2.0：10-29 第一次上機 bug 的成因（從資料確認）

上機 D 段：QS 焦點從 FORMAT（或 RES）移到我們那格、轉轉盤 → **改的是上一格**（FORMAT 變 MOV、解析度 2→3）；那格什麼都沒畫；`hp_blocks` 0。
QS_CINE 的每一個「依 id 的行為」都是動畫，影格 t(ui) = ui×100÷3，由事件套用：

| 東西 | 原廠的上限 |
|---|---|
| 每格 `Icon01`／`Icon02` 的 `appVariableChangeEvent MV_QSMENU_QSn`（type 0x23，value-range） | range-upperlimit 48.0 |
| `DialKeyEvent`（254）`controlValue` | −1..48 |
| 區間 `Icon01_CINE`、`Icon02`、`FR`/`FL`/`BR`/`BL`、`Btn`（AEL）、`Footer` | 都是 0..1600 = t(48) |

所以 UI ≥ 49 的影格**從來沒被套用**，那個物件停在上一格留下的影格。`qs_page_data.Model`（同一套播放模型）在**原廠頁**上算出：
FORMAT(20)→49 後 FR/FL/BR/BL 開著的是 keyEvent `19`（holder 341 = `MV_RecordingFormat`）、RES(21)→49 是 `20`（holder 343 = `MV_Resolution`）——
與上機逐項相同；**AEL 也一樣會跑上一格的 AEL**（FORMAT 的 → B2_5，上機沒按到）。耳機音量的 keyEvent `48` 在 1600 之後沒有關閉鍵
（套到 49 就會開著），但因為 49 根本沒被套用，所以 Q4 的 hook 沒被走到（`hp_blocks` 0）——兩件事一起解釋了。
（測試 `KeyClips.test_the_model_reproduces_the_live_bug_on_the_stock_page` 釘住這個重現。）

## QS 頁怎麼改（`qs_page_data.py`，經 C05E6400 記錄層）

固定的 id 區（跟 N 無關，所以整份資料建置時就算好）：UI 49..64 功能（internal 54..69）、65..71 子項格（70..76）、72 空白格（77）。

| # | 改什麼 | 依據 |
|---|---|---|
| R1 | 8 格 × `Icon01`/`Icon02` 事件 range 上限 48 → 72 | 同階段 1 編輯器 E2（上機通過） |
| R2 | 上面所有區間終點 1600 → t(72)=2400 | 同 E3 |
| R3 | `DialKeyEvent` controlValue max 48 → 72（DialKeyEvent 上限） | |
| K1 | FR/FL/BR/BL/AEL 的 keys clip：t(49) 起**所有原廠 keyEvent = 0**（含耳機音量 `48` 的關閉鍵），加一個我們的 prop：t(49) 起 = 1 | 原廠 clip 是 `keys` 屬性、c = keyEvent 本地編號 |
| K1′ | 每個物件加一個 keyEvent（抄該物件最後一個 keyEvent）＋一個動作 `controlAppVariable(QSC_Key ← 碼)`（抄 AEL 的 `CM_TransitionFlag ← '2'`）；碼 = 該物件原廠方向：FR 1(+1)、FL 2(−1)、BR 2(−1)、BL 1(+1)、AEL 5 | 同頁 donor（fp-native-ui §8b） |
| K2 | 那些群組、`Icon02`、`Footer` 的其他屬性 t(49) 起 = 中性影格 D=30 的值（CINE 沒有功能用 UI 30；建置時檢查 D 上所有 is-visible/type 為 0） | |
| I1 | 8 格 `Icon01` clip：t(49+i) = 功能 i 借來的 QS 外觀（image/rect/size/position，開機重定位）；65..72 寬 0（不畫圖） | QS 自己的外觀表 `qs_icon_looks`，32 個圖名 8 格一致 |
| I2 | 8 格 `Icon02` 加一個 clip：is-visible t(49) 起 0，放進 `Icon02` 群組 → 我們的格子不殘留原廠值圖 | |
| T1 | 8 格各加四個物件（v0.2.1：標題、值、灰小字、黃小字，rect y=38／96／150／150、字級 40／54／34／34）：`drawText`（抄 LockMessage，置中、寬 256）＋綁定 `appVariableEvent`（抄 `48_EXCL_HeadphoneVolume`，mask 0x2f，component-id = drawText 本地編號，property `text`）到 `QSC_L/V/S/Y<k>`；顏色 clip 進該格 `Color` 群組（小字乘灰／黃）；`QSC_G<k>` 事件播該格的反灰影格（抄 `ActDeact00`）；值物件再加一份 `Icon02` 的觸發（修 1） | r43 形式 |
| T2 | 一個我們的物件：`QS_QSMode` ∈ [49,72] → `DialKeyEvent` 的 `Dial` ON（原廠由各功能的 holder 自己開） | |
| M | 8 格各加一個 `Menu` keyEvent（`QSC_Key ← 6`）與一個 clip（放進該格 `Icon01_CINE` 群組）：65..72 時原廠 `Menu` 關、我們的開 | 原廠 `Lock` clip 開關方向鍵的形式 |
| F | 選項列：`QSMode` 下一個物件（`Cursor` OFF、`QSC_Arw` → `Arrow` ON/OFF）＋ 45 個 drawText ＋ 一個 `toggleVisible`（16 個子物件）；`Option`（提示）第 14 格 = `Footer03_K` | 修 2、3，子 QS 的提示 |
| H | 配置標頭 0x10002：物件數 +96（v0.2.0 是 +17）、各元件數、配對／屬性／key 預算（保持原廠不變式：Σ群組 nC = 配對表 = animationClip，Σ配對表 = key 表） | 四頁原廠都成立 |

- 新物件 id 從 30000 起（原廠最大 11686）；每個物件的新本地編號 = 該物件現有最大 +1（事件與 clip 共用）。
- **記錄層**：收集時（第一次版面載入）把 126 筆目標記錄（v0.2.0：114）（原廠位元組 + FNV 驗過）照表做成輸出，**常駐**（169 KB，其中標頭 65 KB）；
  之後 `C05E6400` 收到 base = NBU、位置是目標 → 把輸出（1 筆或多筆記錄）逐筆餵給下一層，再把 base 放回、位置 = 原廠記錄之後。
  別層的複本（base ≠ NBU）→ 不碰、`qs_foreign`+1。任何一筆不符 → 整個 QS 層不裝、**也不發功能**（`freeze` 6），因為半套就是 10-29 的 bug。
- **與 res-custom／uishare QS 配方共存**：配方的 171 筆 QS_CINE 記錄與我們的 126 筆**不重疊**（建置時排除了 Footer 裡 3 筆重疊的 clip，測試釘住）。
  兩層都 `SL_CHAIN` 在 C05E6400，各自只處理自己的原廠記錄。代價：Footer 的那 3 個列表項在我們的格子上保留 t(48) 的值（外觀）。
- **強制重解析**：QS 版面開機就被快取。收集後的下一次「別的」版面載入，照 res-custom `ogc_qslay` 的規則（v5c 凍結之後版）放掉一次：
  只在快取握的仍是 entry 時記下的那份、參考數 1、不是正在載入的那個、不是目前／保留畫面時，`v3(快取物件)` 再 `v2`。res-custom 也在時誰先放都只放一次。

## 子 QS（§8）：在 QS_CINE 上換版面，不另做頁

機制：**改 `MV_QSMENU_QS1..8` 這 8 個 app 變數（不是設定）**。依據：
- QS 頁 8 格完全由 `MV_QSMENU_QSn` 畫：`Icon01`/`Icon02` 的事件與 apply-frame 都是它；焦點時 `controlAppVariable QS_QSMode ← MV_QSMENU_QSn`，
  轉盤、AEL、Footer 都跟 `QS_QSMode` 走（上表）。所以換這 8 個值就是「同一個 QS 面板換內容」。
- `C0593F30` 寫 app 變數是佇列、靜默，不回打 C 的訂閱（`QS_EDITOR_ID_PATHS.md` §2；階段 1 的重發與 r34 的回寫都靠這點，上機過），
  所以不會經 setter 進設定；設定一直是使用者的 8 格。
- `Check`（10575）只在 `QS_FocusPos` 變時抄 `QS_QSMode`，不會被我們的寫入觸發（已讀）。
- 另做 QS 樣式頁要：1.2 MB 頁面複本、私有 NBR 包、狀態機轉換、GUI 頁表 hook，且原廠 AEL 的往返是經 LV 的 `CM_TransitionFlag==2` 再開 "QS"
  （畫面會閃回 LV）；違反 §8「同一個面板」。

流程（`qsct.c` `qc_key`，`QSC_Key` 的訂閱回呼，UI 執行緒；`qc_guid`，`FUN_c0582da0` 裡焦點換了的那一刻）：
- 焦點格 = `[FUN_c05666a0()+0xBC]`（QS GUI 的 QS_QSMode 回呼剛寫的 internal；轉換器有子項／空白的對，所以 70..77 也對，不會掉成 0 = 拍攝模式）。
- **AEL 在功能格**（有子項、未鎖）：k0 = 放這個功能的第一格；8 格寫成 65（功能自己，第 1 格）、66+j（j < 子項數）、72；
  `QS_FocusPos` ← 0（Root 的 controlValue 事件把焦點移到第 1 格）、`QS_QSMode` ← 65、+0xBC ← 70、提示 `QS_FooterGuid1` ← 14（MENU 退回）。
- **AEL 或 MENU（碼 6，只有 65..72 的 Menu keyEvent 會送）在子 QS 裡**＝返回：8 格寫回設定裡的 id，`QS_FocusPos` ← k0、`QS_QSMode` ← 那格的 id、
  +0xBC 同步、提示 ← 1（AEL 更多選項）。
- **任何版面載入**（關 QS、進選單、OK）時子 QS 開著 → 先寫回（不動焦點）。使用者的版面與設定從頭到尾沒變。
- **轉盤**：碼 1 → +1、2 → −1，給焦點功能（65 也是它）或子項的 `adjust`；之後重算 8 格文字與選項列。`QSC_Key` 每次寫回 0，下一下仍是「變化」。
- **焦點換了**（hook，原廠 `FUN_c057f310` 之前／代替它）：我們的 id → 提示（有子項才 1；子 QS 裡 1 = MENU 退回）、箭頭（`QSC_Arw` 先 2 再 adjust?1:0）、
  選項列（`footer()`）；原廠 id → 原廠寫提示、我們的列清空。版面載入時用 +0xBC 重算一次（QS 重開、焦點沒變也對）。
- 文字：每格 `QSC_L/V/S/Y<k>`，內容變了才寫（雙緩衝，GUI 留指標）；原廠格是 " "。值與小字轉成原廠字形圖（修 4）。
- **錄影鎖**：`QSC_F_LOCK_REC` 且在錄影（`busy()`，同存檔替換）或 `state()` 非 0 → `QSC_G<k>`=1（該格反灰）、轉盤與 AEL 不動作（`locked`+1）、沒有箭頭與提示。

## 用戶端 API（`qsc.h`，API 版本 3）

表的 magic `QSF3`（API 2 的 `QSF1` 版位照收，子項最多 6 個）。`struct qsc_func`：`value()`（大字，≤23 bytes，ASCII 或 UTF-8）、
`adjust(arg, ±1)`（0 = 沒有箭頭）、`state()`、`flags & QSC_F_LOCK_REC`、`sub`（0 = 沒有子 QS、沒有「AEL 更多選項」），API 3 加：
`small(arg, &flags)`（第二行；`flags |= QSC_T_APPROX` → 黃色）、`footer(arg, &foot)`（選項列，回傳個數；0 = 沒有列）、`reserved`（0）。
`struct qsc_sub`：`label`（標題）、`value()`、`adjust()`、`arg`，API 3 加 `icon`（原廠圖名，取代標題）、`small()`、`footer()`、
`lock()`（`QSC_LOCK_OPEN/SHUT` → 開鎖／鎖頭圖取代標題；`QSC_LOCK_NONE` = 標題）、`reserved`。
`struct qsc_foot { n, cur, approx, spin, mark, custom, label[16], small[16] }`：容器先清零；標籤 ≤15 bytes（呼叫後就複製）；
`cur` = 有框的那個（n = 無框）；`approx` 位元 = 那項小字黃色；`spin` = 數字轉輪（`◀ label[0] ▶`，原廠色溫格的箭頭圖）；
`mark`/`custom` 保留給 API 4（FPS：點底線／黃色，現在忽略）。`qsc_func.reserved` 留給 API 4 的「微調模式」。

測試用戶端 `QSTest` v0.2.1：**QS Test A**（menu_crop，`LOCK_REC`）值 `N=<計數>`、小字 `STEP 1`、選項列 C0..C4（框 = 計數 mod 5），
AEL 開三個子項「Count」（數字轉輪）、「Toggle」（Off/On，列 Off | On，On 時小字黃）、「Ratio」（鎖頭圖，轉盤切換）；
**QS Test B**（menu_lock）值 = 標籤、無轉盤、無子項、無列（看「沒有箭頭、沒有提示、沒有框」）。值只在 RAM。

## 註冊（用戶端只要一行）

```c
svc->provide(svc, QSC_TAG(MY_SUP_ID), &table);     // table/func 常駐在自己的區塊；-fropi 要在 entry 裡填指標
```

- 容器在**所有 entry 跑完之後的第一次版面載入**（`FUN_c05d90f0`，每次換畫面都經過，`SL_CHAIN`）收一次：
  走 `sups_list` 的 LOADED 項目、`find(QSC_TAG(id))`、逐筆驗。所以載入順序無關（測試兩種順序結果逐位元組相同）。
  編輯器、清單、QS 頁都是換畫面之後才載入，一定在收集之後。
- 編號只在 RAM、每次開機重發：依**載入順序、表內順序**，第 i 個 = UI `49+i`、internal `54+i`（設計 §2.3 寫的是依顯示名排序；
  這裡用載入順序，因為只有「鍵」會被保存，順序不影響任何持久狀態）。上限 16，第 17 個起記 `st.full`。
- 每筆驗：`sup_id` 要等於提供者、`QSC_F_CINE`、回呼是 0 或程式位址、`sub` 是 0 或 1..7 個標籤合格的子項、名字 1..11 字且同 sup 內唯一、
  **標籤 1..11 個可列印 ASCII、不可全是數字、不可含 `,` `"` `{` `}`**（它是 CSV 文字）；不合格的那一筆跳過（`st.bad`）。
- 圖示：給清單用的原廠圖名（`menu_crop`…）。格子沿用那個原廠功能在格子裡的外觀（圖、寬、位置，`editor_data.icon_table`，32 個，16 格兩頁都一致才收）；不認得 → `menu_crop`。
- `svc->find('QSCT')` → `struct qsc_api`：`ui_id(sup_id, name)` 回這次發的 UI id（或 -1）；`refresh` 重畫 QS 格子（API 版本 2）。
- **與 ZQS 互斥**（§9 Q5）：收集時 `QSN1`（ZQS.BIN）已載入 → 容器整個不加功能（`st.phase` 3、`st.freeze` 1），存檔替換照樣跑。
- **不在 fpSup 頁放列**（§9 Q6）。


## 改了什麼

全部在 entry 先 claim（任一被拒 → RELEASE、什麼都沒寫），關機時核心寫回原廠。

| # | 什麼 | 位置 | 方式 |
|---|---|---|---|
| — | 收集觸發 | `0xC05D90F0` 第一條 `push.w`（Thumb） | B.W → Thumb veneer；下一層由 `chain_next`，原廠時自己重做 `push.w` 再跳 `C05D90F5` |
| C1 | CSV 四份 `Y2_3_CINE{,_W91C1,_angle,_angle_W91C1}.cvm` 每個功能一列 `NO,49+i,<圖名>,<標籤>,S` | 共用取檔處理器 `C05E5BEC`（entry 用 fpui_stock 的 HOOK_FV 找到或裝好；列在收集時加，照 uishare 的提交順序） | 資料 |
| C4 | 轉換器 `[0xC37B7728]` → vtable 複本，只改 +0x344；階段 2 多 8 對 `{70+j, 65+j}`、`{77, 72}`（QS 頁的子項／空白格） | RAM 單例 | `SL_CHAIN`；下一層的表撞到 54..77 / 49..72 → RELEASE |
| C5 | 存檔替換：序列化前把兩組 8 格裡**所有 ≥ 54** 換成占位，複製完放回 RAM | `0xC0088C60 bl FUN_c0088660` | `SL_CHAIN` |
| C6 | QR／設定 dump 讀取：≥ 54 → 占位 | `0xC053DBF8 bl FUN_c0061b08` | `SL_CHAIN` |
| C7 | 開機還原：記錄說是我們的、那格仍是記錄的占位、用戶端在 → 放回 54+i，重發 `MV_QSMENU_QS1..8` | 收集時 | 執行期 |
| E2–E5 | 編輯器兩頁的修正（下節） | `Y2_3C`、`Y2_3C_ShutterAngle` 的執行期項目換成複本 | 資料（uishare FSPG 慣例的複本） |
| Q | QS 頁 `QS_CINE` 的記錄（下節） | `0xC05E6400` 第一條 `push.w`（Thumb，記錄解譯器）| `SL_CHAIN` 套娃記錄層；收集時建好 114 筆輸出 |
| K | `QSC_Key` 等 25 個私有 app 變數 | `C05DB309` 註冊、`C0560FB0` 訂閱 `QSC_Key`、`C0593FE0/F30` 寫 | 執行期，無 claim |
| Q4 | QS 頁耳機音量（保險，見下） | `0xC0582AE8 bl FUN_c0062bb0`（`FUN_c0582ab0` = QS GUI 的 `CM_HeadphoneVolume` 回呼） | `SL_CHAIN` |
| G | v0.2.1：焦點換了／「AEL 更多選項」提示 | `0xC0582DB4 bl FUN_c057f310`（`FUN_c0582da0`，QS GUI 的 QS_QSMode 回呼） | `SL_CHAIN`，veneer 在 cave（48 B） |

**占位 = 那格放我們之前的原廠功能**（§9 Q1）：轉換器每次被呼叫時（編輯器的 setter 寫格子之前一定先轉換）記下 16 格各自最後一個原廠值；
存檔時用它，並寫進本 BIN 的記錄 `{'QSC1', 1, 16 × {鍵 16 B, 占位}, FNV}`（332 B，檔案位移 `rec_off` = 87748）。
沒有歷史的 ≥ 54（別人留下的）用原廠預設（`FUN_c04b4688` 那 16 個）。記錄只在內容變化時寫、寫前 `file_is` 比前 48 B、
**絕不建檔**、錄影中不寫（替換照做）、收集前不寫。

**用戶端被停用**（§9 Q2）：那格顯示占位（flash 本來就是它），記錄保留這一筆（孤兒）；用戶端回來、那格仍是占位 → 自動放回；
期間使用者改了那格 → 刪掉這筆，不蓋掉。

## 編輯器修正（階段 1，10-29 上機通過）


上機重現的凍結（`validation/2026-10-28-live/LOG.md` §4）：格子存著 UI 49 時重進編輯器 → 名字列「XXXX」→ OK → 格子變灰、沒有 popup、
所有按鍵無反應。成因（資料，`editor_data.py` 從頁面讀出）：每格 `Icon01_CINE` 的 `appVariableChangeEvent` 範圍 0..48，49 不觸發，
所以頁面建好時那格停在靜態初值：`string` 的 drawText `xxxx`、`index` 的 `position_x` **90.0**。格子的 OK 用 index 的位置當清單索引
→ 清單只有 36 列，焦點進了清單容器卻沒有任何 ListItem（`FUN_c05f1fc0` 沒有範圍檢查）。同一格「選完直接按 OK」沒事，是因為那時用的是上一次的影格。

修法是讓新 id 在頁面建立時跟原廠 id 走同一條路，每頁、每格（8 × 2）：

| | 原廠 | 改成 |
|---|---|---|
| E2 `Icon01_CINE` 事件範圍上限（type 0x23 那一筆；W91C1 雙胞胎 type 0 不動） | 48.0 | 48 + N |
| E3 `Icon01_CINE` 區間終點（群組 +36） | 1600 | t(48+N) |
| E4 `Icon01_CINE/2` image、rect[2]、size[0]、position[0] | — | 在 t(id) 加鍵：借來的圖與外觀 |
| E4 `index/3` position | — | t(id) = **清單列號**（CSV 裡 ID = id 那一列，0 起算：32、33…） |
| E4 `string/2` text | — | t(id) = 標籤的私有字串 id（核心的解析 hook 把它變回文字） |
| 清單游標上限 `Visible` | 31 | 31 + N |
| E5 總數的兩個數字圖 `total1/total2` | `font_menu_S_3`/`_2` | 32+N 的十位/個位 |

- t(id) = ⌊id × 100 / 3⌋（1633、1666…），新鍵一律「保持」（旗標 0）。這些 clip 在 1800..3400 還有一份只給 W91C1（fp L）的雙胞胎區間
  （它的事件 type 0，在 fp 上永不觸發）；id 49..53 落在 1600 與 1800 之間，**54 起會落在雙胞胎的鍵上 → 那個鍵的值與插值旗標被改寫**。
- 頁面是**一次串流複製**（不是逐筆 INSERT：每插一次就搬 800 KB，16 個功能會到幾百 MB），寫成 uishare 的 FSPG 複本（標頭 + 位移表），
  所以別的 sup 之後用原廠座標改同一頁仍然對得上；來源若已是別人的 FSPG 複本，就在它上面再加。任何一處的原廠位元組不符 → 那頁不換、整批功能不加。
- 原廠 1600 之前的 49 個 id 在 16 格每個屬性上的播放值，改前改後逐一相同（測試）。

### 標籤用哪一條路（任務要求說明）

10-28 上機：清單 KEY 欄放私有字串 id → 清單顯示那串數字（1163655400）。KEY 是一段文字：清單把它拿去查 `.nloc`，查不到就**照原樣畫出來**
（fp-native-ui「TEXT 可以直接寫字面文字」同一個機制）。所以：

- **清單列（與它的名字列）**：KEY 直接寫**標籤文字本身**（例 `QS Test A`）。不經私有字串，也不動 `.nloc`。全數字的標籤會被當 `.nloc` 鍵查，所以拒收。
- **格子的名字（`string` drawText，焦點進格時複製到名字列）**：clip 鍵的值是字串池位移；這裡放標籤複本的**私有字串 id**（非快取位址，
  核心 `C05E5B58` 解析回快取位址，與 fpsup-ui 頁面的字串同一個機制），文字同樣不是 `.nloc` 鍵，照原樣畫。
  標籤複本在容器自己的區塊，整塊 `borrow`，韌體不會釋放它。


## Q4：QS 頁的耳機音量

階段 2 用資料修：FR/FL/BR/BL 的 keyEvent `48` 在 t(49) 有關閉鍵（K1），我們的格子上它不會開（測試 `test_headphone_closing_key`）。
階段 1 的程式點 `0xC0582AE8`（焦點是我們的 → 不呼叫 setter）**保留當保險**，範圍擴到子項／空白格（70..77）；資料對的話它永遠走不到（`hp_blocks` 應該一直是 0）。

## 檔案

| 檔 | 內容 |
|---|---|
| `qsc.h` | 用戶端合約（API 3：值、小字、選項列、轉盤、狀態、子項、鎖頭） |
| `qsct.c` | 容器本體（v4、`-fropi` Thumb、只有 .text） |
| `editor_data.py` | 編輯器的修正（階段 1） |
| `qs_page_data.py` | QS 頁：分析、要改的每一筆（`Design`）、相機套用的表（`table`）與參考實作（`apply_table`）、播放模型（`Model`） |
| `build_qsct.py` | `python3 -B build_qsct.py --out out` → `out/fpSup/QSContainer_v0.2.1.BIN` + `out/build.json`；字形對照 `GLYPHS` |
| `testclient/qstest.c`、`build_qstest.py` | 測試用戶端 `QSTest`（sup_id `QSTS`）→ `out/fpSup/QSTest_v0.2.1.BIN` |
| `test_qsct.py` | 階段 1 的 unicorn 測試（照跑；相機模型多了提示的讀寫） |
| `test_qs_page.py` | 階段 2 的 unicorn 測試與 `--mutate` |
| `test_api5.py`、`test_api7.py` | API 5／6 與 API 7（v0.3.7 AEL 開原廠頁）的測試與 `--mutate` |
| `validation/qstest_v0.2.0.BIN` | API 2 的舊用戶端（測 `QSF1` 照收） |

| 產物 | bytes | sha256 |
|---|---|---|
| `out/fpSup/QSContainer_v0.2.1.BIN` | 132260 | `63febef47ce58841…`（全文在 `out/build.json`） |
| `out/fpSup/QSTest_v0.2.1.BIN` | 2088 | `fc6619c2c6a0d061…` |

## 沒做的、離線證明不了的

1. **GUI 建頁與繪製本身沒有模擬**。測試判的是「相機程式餵給解譯器的記錄」，用播放模型（保持／線性插值、事件的 value-range 與
   controlValue 範圍、區間；v0.2.1 加上「看不見的物件不觸發事件」）算每個 id 的值；這條規則是從 10-29 第二次上機反推的
   （它同時解釋了標題回來、值不回來、改值也不畫三件事），沒有在韌體裡讀到。
2. 修 4 的粗體：drawText 的文字裡內嵌 `<!font_menu_LB_…,CENTER>` 圖。原廠字串池有同形字串（`<!font_menu_LB_0,CENTER>` 等），
   但**原廠是放在 .nloc／池字串裡**，我們的是私有字串變數；能不能照樣解析、圖的大小與基線、混排的系統字、顏色 clip 對內嵌圖有沒有作用，都要上機看。
3. 修 5 的版面（rect、字級 40／54／34）是照截圖估的；子 QS 第 1 格的圖是外觀圖原尺寸（不經 rect/size 縮放）。
4. 修 2 的選項列：15 個位置、每格 128 寬、字級 34／24 是估的；`toggleVisible` 依子物件**順序**選（`LensStatus` 的子物件名不是數字，推定如此）；
   原廠游標關掉用的是 holder 的 `Cursor OFF` 動作原樣（沒有 owner 欄，放在同一個父物件下讓它照樣解析）。
5. MENU 的開關 clip 放在 `Icon01_CINE` 群組（擁有者是 `Icon01`）裡，但 clip 的物件是格子本身（父物件）；原廠群組都是指向自己或子孫，指向父物件沒有先例。
6. 提示：「MENU 退回」是 `Option` 的新影格 14；回來時寫 1（`Footer14_K`）——原廠在非光圈格都是 1，光圈格由原廠 C 再寫。
7. 子 QS 進出時寫 `QS_FocusPos`（Root 的 controlValue 事件移焦點）與 QS 狀態的 +0xBC（照 QS GUI 回呼的寫法）；焦點已在第 1 格時不會有焦點事件，靠直接寫的那兩個。
8. 選項列與箭頭在「焦點換了」時更新：靠新的 hook 點 0xC0582DB4，假設 `FUN_c0582da0` 只被 QS_QSMode 回呼（和 `QsMenuLensDetectObserver` 以 id 3）呼叫。
9. 錄影中開 QS 才會看到反灰；QS 開著時才開始錄影，要到下一次版面載入才反灰（轉盤每次都重查，照樣鎖住）。
10. 前後轉盤送一樣的 ±1（preview 的「後轉盤 ×10」沒做）；API 只有 ±1。
11. 階段 1 的「沒做的」2–8 照舊（編輯器建頁未模擬、清單 NN/總數外觀、W91C1 雙胞胎、存檔路徑涵蓋）。

## 狀態（`mem get` 讀）

LOAD.LOG 的 `LOADED` 行給區塊位址 B；容器自己一行 `QSC <result<<16|fv_result> <下一層 vtable>`（正常：`QSC 00000000 C2DEAD7C`）。
狀態 S = B + **132288**（v0.2.1 的 `state_off`）：+0 `QRUN`、+4 result（1 claim、2 vtable 不像、3 撞號、4 chain、5 cave）、
+8 phase（0 未收集、2 就緒、3 停用）、+12 freeze（0 好、1 ZQS、3 頁面、4 CSV、5 沒有用戶端、**6 QS 層**）、+32 N、+36 收到、+40 滿、+44 不合格；
+3224 saves … +3236 耳機擋下（應為 0）、+3240 restored、+3248 orphans、+3252 writes（同階段 1）；
階段 2：+9992 qs_result（0 好；3 = QS_CINE 項目已被別人換頁，+10024 是它的位移；16+i·256+r = 第 i 筆目標不符）、+9996 qs_ready、
+10012 放掉快取的次數、**+10920 qs_fresh**（快取沒握著，照樣會經過我們；兩個加起來開機後 = 1）、+10016 記錄層命中（每次解析 QS_CINE +126）、
+10020 別層複本、+10028 註冊的變數數（88）、+10680 sub_open（−1 = 沒開）、+10684 子 QS 的 8 格 id、
+10716 keys、+10720 dials、+10724 aels、+10728 opens、+10732 closes、+10736 adjusts、+10740 locked、+10744 文字寫入數、
+10908 menus、+10912 焦點回呼次數、+10916 提示寫入數、+10924 子 QS 的原格、+10928 焦點 id、+10932 框的位置（15 = 無）、+10936 箭頭（0/1）。
設定影像兩組 8 格：`mem get 0xC31B07A4,,32`（STILL）、`mem get 0xC31B0ABC,,32`（CINE）。

## 上機步驟（照慣例：先告訴 Bei 並等回覆、廣播相機使用權；錄影中與回放中不碰 USB）

**永遠不要按「建立 QR code」**（任何一步都不要）。QS 開著時可以截圖：`python3 -B fpSup/fp_usb_shell/ui_drive.py shot`（10-29 證實）。

準備：
1. 讀 `\fpSup\` 清單與 LOAD.LOG 備份。**刪掉 `QSContainer_v0.2.0.BIN`、`QSTest_v0.2.0.BIN`**（`fl del`）；不放 ZQS、`SLQSProbe*`。
2. 記下兩組 8 格；記下 FORMAT／解析度／格率／ISO／耳機音量。
3. `python3 -B fpSup/fp_usb_shell/v3/deploy_v3.py projects/qs-container/out --only fpSup/QSContainer_v0.2.1.BIN --only fpSup/QSTest_v0.2.1.BIN`（讀回比對）。
4. `python3 -B fpSup/fp_usb_shell/ui_drive.py reboot`。LOAD.LOG：兩個都 LOADED、`QSC 00000000 C2DEAD7C`。按一次 MENU 後讀：phase 2、freeze 0、N 2、
   qs_result 0、qs_ready 1、qs_vars 88、放掉 + fresh = 1。
5. 編輯器：第 2 格 = **QS Test A**、第 7 格 = **QS Test B**（CINE 組 `21 54 23 25 39 9 55 19`）。離開到 LV。

G. v0.2.1 的六項（每步截圖）：
6. `key QSON`：命中 = 126。第 2 格：裁切圖、**粗體** `N=0`（同 DNG/2500 的字形）、灰小字 `STEP 1`。第 7 格：鎖圖、粗體 `QS Test B`（小寫是系統字）。
7. 焦點到第 2 格：左右箭頭有、「AEL 更多選項」有、下方 `C0 C1 C2 C3 C4` 置中、`C0` 有框；前轉盤 +1 → `N=1`、框到 `C1`。轉回。
8. 焦點到第 7 格（B）：**沒有箭頭、沒有提示、下方沒有框**（修 2、3）。轉盤什麼都不變。
9. 第 2 格按 **AEL**：同一面板，**A 在第 1 格且有焦點**，第 2–4 格 Count／Toggle／Ratio（Ratio 的標題是鑰匙圖），其餘空白；提示「MENU 退回」。
   Count：下方 `◀ N=0 ▶`；Toggle：`Off | On`，轉到 On 時小字變黃；Ratio：轉盤 → 鑰匙圖變開鎖、`FREE`。
10. 按 **MENU**：回到原本 8 格、焦點在第 2 格（不是關 QS）。**原廠 6 格的值都畫出來**（修 1：FORMAT `DNG 12bit`、RES `FHD`…）。
    到 RES 格轉盤改一格再改回：值跟著畫。再開子 QS、按 AEL 返回一次：同樣。
11. 再開子 QS → QS 鍵關掉 → `key QSON`：原本的 8 格、值都有。
12. 原廠格按 AEL：照原廠（例如 FORMAT → 錄影設定頁），返回 QS 正常；原廠格在 QS 裡按 MENU：照原廠關 QS。
13. 讀計數：menus、opens、closes、guid_sets；`mem get 0xC31B0ABC,,32` = 第 5 步；FORMAT／解析度／格率／ISO／耳機音量 = 第 2 步。

E. 錄影反灰（**手動**：錄影中不用 USB）：
14. Bei 自己按 REC 開始錄一段 → 開 QS：第 2 格（A，LOCK_REC）反灰、轉盤不改值、AEL 不開、沒有箭頭與提示；第 7 格（B）不灰。停錄、等 10 秒後才接 USB 讀 locked。

F. 收尾：編輯器把第 2、7 格換回原本的原廠功能，讀回兩組 8 格 = 第 2 步。

- 任何一步卡住（GUI 不回應）：**不要關機**，先讀 S+8/+12、+9992..+10028、+10680、+10908..+10936，回報；再照「還原」。

## 還原

- 某格存著我們的 id（RAM 54/55）而要拿掉容器：`menu SetFunction <internal>` —— **只寫第 2 格**（`FUN_c0401c80` 寫死格號 1），
  例：`menu SetFunction 12`。其他格在編輯器裡換回原廠功能。讀回兩組 8 格確認沒有 54 以上。flash 本來就只有原廠 id。
- 子 QS 開著時卡住：設定沒被改過（只改了 8 個 app 變數與焦點變數）；任何換畫面都會寫回。
- 卡住（GUI 不回應）：先確認 RAM 乾淨，再 `python3 -B fpSup/fp_usb_shell/ui_drive.py reboot`。
- 移除：`fl del \fpSup\QSContainer_v0.2.1.BIN`、`fl del \fpSup\QSTest_v0.2.1.BIN`，重開（QS_CINE 回到原廠解析；容器的 claim 關機時寫回）。

## 離線測試

```
cd projects/qs-container
python3 -B -m unittest test_qsct         # 階段 1：32 項，約 40 s
python3 -B -m unittest test_qs_page      # 階段 2：45 項，約 50 s
python3 -B test_qsct.py --mutate         # 階段 1：34/34 被抓到
python3 -B test_qs_page.py --mutate      # 階段 2：57/57 被抓到（資料 18 + 程式 39）；1 個等價突變已註明不列
python3 -B -m unittest test_api7         # v0.3.7 API 7：11 項
python3 -B test_api7.py --mutate         # v0.3.7：21/21 被抓到
```

`test_qs_page`：真 v4 核心載入真的兩個 BIN、真映像；QS_CINE 的 **14,285 筆記錄逐筆**從被 hook 的 `C05E6400` 進去，收集解譯器拿到的東西。

| 類 | 測試 |
|---|---|
| 記錄層 | 收集後 qs_result 0、88 個變數（型別、`QSC_FB` 初值 15）、只訂閱 `QSC_Key`；不是目標的記錄原樣、base/位置放回；**相機做的 126 筆輸出逐位元組等於 Python 參考**；標頭計數＝串流實數、預算不變式、每個物件的本地／群組／子數量關係同原廠；新本地編號不撞；與 res-custom 配方的記錄不重疊 |
| 10-29 第一次 bug | 模型重現原廠頁的錯；每個新 id、每個先前 id、FR/FL/BR/BL/AEL：影格有套用、唯一開著的是我們的 keyEvent |
| 耳機 | keyEvent `48` 在 48 開、49..72 關 |
| 格子 | 每個新 id 都套得到；外觀；Icon02 在原廠 id 顯示、新 id 隱藏；原廠 id 每個屬性值同原廠；四個文字物件（綁定、rect、字級、顏色 clip＝白／灰／黃）；Dial ON |
| **修 1** `Icon02Return` | 「看不見的物件不觸發」模型：8 格 × 原廠 id × 子 QS id，原廠 → 子 QS → 原廠後 `Icon02` 回到原廠影格且看得見；我們的 id 仍然藏 |
| **修 2、3** `Footer`、`PageStrip` | 選項置中（位置 8 − n + 2q）、有框、跟著轉盤；B 與原廠格沒有列；箭頭 `QSC_Arw` 2→1／2→0；提示只在有子項（原廠格照原廠 `FUN_c057f310`）；數字轉輪 `◀ N ▶`；黃小字；頁面：45 個文字物件的綁定與位置、16 個框、`Cursor` OFF、`Arrow` ON/OFF 事件 |
| **修 4、5** | 值＝原廠粗體字形圖；子 QS 第 1 格＝功能的外觀圖、標題、粗體值、小字、鎖頭圖隨轉盤換 |
| **修 6** | 快取沒握著 → `qs_fresh` 1、不放、只一次 |
| 子 QS／MENU（§10） | 功能到第 1 格、焦點 0、`QS_QSMode` 65、+0xBC 70；子項 66..；返回焦點回原格；MENU（碼 6）返回、子 QS 外不做事；頁面：每格原廠 `Menu` 在 65..72 關、我們的開；提示影格 14 = `Footer03_K` |
| 其他 | API 2 的舊 QSTest 照常；錄影鎖；離開 QS 時寫回；沒有子項不開；耳機保險涵蓋子項 id |
