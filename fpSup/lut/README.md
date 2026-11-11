# fpSup LUT：完整匯入、硬體表格與 CPU 補正基準

2026-10-22：已有 Loader v4 格式的 **LUT 開發 sup**，首頁只留一個 Color 入口。
新版加入逐份 LUT 的輸入色域／Gamma、強度、啟用清單及目前選擇。
依使用者要求，修改色域／Gamma 會直接更新該 `.cube` 的註解；啟用／目前選擇／強度仍由自身 BIN 保存。
監看影像路由尚未接通，沒有實作機內 Live View、MOV 或 JPG 套用。
產品需求、機內多區塊地圖與下一階段在完整研究樹的 [`projects/lut-sup`](../../projects/lut-sup/README.md)。
這裡是供 native runtime 與 DNG writer 共用／比對的匯入和檔案基準，無相機 I/O。

2026-10-16 增加 `color.py`／`cinemadng.py`／`monitor.py` 與 `monitor-*` 指令：
**8 個 CinemaDNG 輸入色域、獨立 Gamma 選擇、固定 Rec.709 D65／Gamma 2.4 輸出**。
選單依使用者實際畫面；35 組標準數學參考已實作，Resolve 的 Rec.709 Gamma 與兩組 Blackmagic
模型仍待核實，選取時明確拒絕產生數值結果。全部模型尚未通過 Resolve 成對顯影的像素核對。
這層接受已校準的 scene-linear XYZ／明確標示的 RGB；尚未接入 fp 的 live frame 或校準原生 YUYV。

## color 容器與新版 UI（2026-10-21）

使用者確認本對話負責 [color 容器](../projects/color-sup.md)，RAW View 未來可能納入。
目前 LUT 是其子功能；RAW View 尚未搬移，`LUT.BIN`／`LUT4` 介面不因此改名。
色彩功能碰到同一組原廠 hook、root table、ISP 或 UI 位置時，由 color 統一協調。

新版 Loader v4 只管理 fpSup 首頁與固定頁面／字串規則。LUT 只用 `page_add` 註冊一個 **Color** 入口，
LUT 清單及每份設定由自己的私有頁面管理。此版使用 v6 的 `file_read`／`borrow` 裝入並保護私有頁面，最低服務需求因此為 v6。
首頁與 SupManager 改用 `fpsup-ui/fpsup_ui.c` 的私有 FT4S 頁面、位址字串 ID 與 `borrow` 範圍，
不再使用舊 uishare 共用字串執行層。`uishare/tab/build_fp4.py` 仍是上游維護的資料產生器，僅保留歷史目錄名稱。

現行共用來源位於 [`../loader-v4`](../loader-v4/README.md) 與
[`../fpsup-ui`](../fpsup-ui/README.md)。LUT 的建置與測試直接引用新位置；既有驗證快照與開發包保留原樣。
搬移後的[路徑驗證](../../projects/lut-sup/validation/20261021-layout-update-01/report.json)：24 項原生／UI 測試通過、無跳過，
重新建置的 AutoRun 與全部 BIN／LUT 資料均與 `20261021-color-v4-private-ui-04` 逐 byte 相同。
建置追溯已改記真正編入的 `fpsup_home.c` 與私有頁面函式庫。

這輪是 UI 核心／資料格式遷移：LOADER、SUPMGR 和兩份 UI 資料須取自同一份新版開發包，
不能把新 FT4S 資料混入舊 UI 核心。舊凍結產物保留供追溯；沒有寫入相機或更新實體卡。
後續 color 自己的頁面也使用私有 `fpsup-ui`，loader 不負責色彩子功能的協調。

[新版離線開發包](../../projects/lut-sup/cards/20261021-color-v4-private-ui-04/)與
[遷移驗證](../../projects/lut-sup/validation/20261021-color-v4-private-ui-04/migration.json)：
86 項測試通過、無跳過，7 個隔離故障副本全部被偵測，包含缺少私有字串 `borrow` 登記。
已對實際成品驗證設定、分頁、SupManager、字串解析／保護及關機還原；數值比較最大通道 code 誤差 7.01e-5。
採用逐 byte 保存的維護來源快照，避免共用來源的更新或測試變體混入同一輪；快照不是另一套維護的 loader。
相對舊 `20261021-loader-v4-ui-04`，LUT.BIN 與 AutoRun 都相同，LOADER、SUPMGR 與 UI 資料已更新。
機內監看 backend 仍未接通，尚未上機驗收，也沒有操作相機或改動 RAW View。

## 每份 LUT、啟用清單與作者標示（2026-10-22）

fpSup 首頁維持 `Color >`。進入後只有目前 LUT、LUT 管理、監看開關三項；設定說明留在文件與對話。
「LUT 管理」列出所有匯入檔案，各自可選 Enable／Disable／Settings；概念與 res-custom 的啟用清單相同。
「Active LUT」只列出已啟用者及 Off，一次套用一份。停用目前那份會回到 Off，不自動跳到別份。
每份獨立保存輸入色域、Gamma 及 0／25／50／75／100% 強度；編輯另一份不改目前那份。
未標示輸入者顯示 Setup required，必須先設定才可使用。待核實模型仍保留名稱並拒絕運算，不代用其他模型。

**檔名是顯示名稱，不是色域判定來源。** 作者可用 `Portrait_P3D65_G26_to709.cube` 方便辨識，
但程式不從名稱猜輸入設定。辨識用 SHA-256 排除 fpSup 自己的色彩註解與管理區塊；
改名或只更新這些註解不會變成新 LUT，同名不同內容各自獨立，清單加短 ID 區分。
TITLE、其他作者註解、domain、格點或數值改變仍視為新來源。僅色彩註解不同的來源視為同份 LUT；
若要另外保存成獨立版本，使用不同 TITLE。檔名目前最多 63 UTF-8 bytes。

作者可在 `.cube` 原檔加入以下**自訂可選註解約定**，不是新增標準 cube 指令：

```text
# FPSUP_INPUT_COLOR_SPACE p3-d65
# FPSUP_INPUT_GAMMA gamma26
# FPSUP_OUTPUT_COLOR_SPACE rec709
# FPSUP_OUTPUT_GAMMA gamma24
```

使用者改色域／Gamma 時直接替換這些註解；下次匯入以檔案內的值為準，不另維護一層隱藏覆寫。
沒有標示就保持未設定；部分設定用 `unset` 表示尚未選擇。輸出若明示不是 Rec.709／Gamma 2.4，匯入會拒絕；
沒有輸出標示仍須由使用者確認該 LUT 符合監看契約，不能靠表格數字驗明。
輸入 ID 見下方表格。LUT 數值、TITLE 與其他作者註解保留原 bytes，只有 fpSup 管理的註解會變動。

本開發版最多 32 份，每份準備後的文字來源最多 64 MiB，超過明確拒絕，不截掉檔案。
原始 `.cube` 目前須先在主機準備為原生資料，
尚未支援直接丟入文字 cube 後由相機掃描／解析。

從本目錄執行：

```sh
python3 -B fplut.py library-import out/library.json look-a.cube look-b.cube
python3 -B fplut.py library-set out/library.json look-a.cube --input-space p3-d65 --input-gamma gamma26 --enabled on --active
python3 -B fplut.py library-set out/library.json look-b.cube --input-space rec709 --input-gamma gamma24 --enabled on
python3 -B fplut.py library-list out/library.json
python3 -B build_sup.py --library out/library.json --out out/library-card --card --debug
```

`library-set --input-space/--input-gamma` 會直接改傳入的本機 `.cube`。主機採暫存檔、解析及讀回核對後替換，
保持其 BOM 與非管理區內容。卡上的 `LUT/SOURCES/<ID>.cube` 則在準備時加入 512-byte 的純註解區塊；
機內只定位更新這個區塊，不移動或改寫後方的 LUT 資料。先確認來源 ID、原本長度與完整資料區 checksum，
再寫入並讀回核對；錄影中、缺檔、來源被替換或資料已變更時拒絕寫入。
重新開機與切換 LUT 都從 `.cube` 註解讀取輸入色域／Gamma，BIN 中的快照不覆蓋它。

啟用／目前選擇／強度繼續依 res-custom 方式存入自身現存 `LUT.BIN`，不改相機設定區。
來源或 BIN 寫入失敗會回報 Save failed 並保留原 RAM 設定；來源註解損壞時，下次啟動保持未設定／Off。
這不是 SD 掉電原子交易。重建前取回卡上的 BIN 及 SOURCES，按內容 ID 合併：

```sh
python3 -B fplut.py library-recover out/library.json saved-from-card/LUT.BIN --sources saved-from-card/LUT/SOURCES
```

也可直接把更新後的 `.cube` 匯入新清單，色域／Gamma 就會跟著檔案走。只有 BIN 不能取回未來自目前檔案的色域設定；
沒有先取回來源就重建，會以本機 `.cube` 為準。新 library 記錄為 v2，舊 v1 開發清單須重新匯入來源並重建。
在其他文字編輯器更改註解後也要重新準備卡片資料；相機只寫入主機已準備的區塊，不解析任意文字 cube。

[目前註解寫回開發包](../../projects/lut-sup/cards/20261022-color-comments-01/)與
[成品驗證報告](../../projects/lut-sup/validation/20261022-color-comments-01/report.json)：
119 項通過、無跳過，17 個隔離故障副本全部偵測；另有
[CLI 往返](../../projects/lut-sup/validation/20261022-color-comments-01/cli-roundtrip.json)。
包含 BOM／多塊來源讀取、只改管理註解、重新開機與全新匯入、來源缺失／header／資料區／長度變更拒寫、
寫入讀回失敗拒用及錄影中保護。實際輸出成品也完成註解修改／重載及原始資料區 bytes 核對。
AutoRun、共用 LOADER／SUPMGR 及首頁／管理頁資料保持相同，LUT.BIN 與 library 素材需一併取自新包；
`UI/COLOR.BIN` 的版面未改。沒有寫卡或操作相機，SD 寫入、掉電與實機 UI 仍待驗收，Live View 仍為 Off。

[先前 BIN 保存設定的開發包](../../projects/lut-sup/cards/20261022-color-library-03/)與
[當時離線報告](../../projects/lut-sup/validation/20261022-color-library-01/final/report.json)：
114 項測試通過、無跳過，13 個隔離故障副本全部偵測。已用實際成品驗證單一首頁入口、
管理／選擇／設定頁、32 份最後一頁、逐份寫回與重新載入、MENU 返回及共用 hook 關機還原。
AutoRun、LOADER、SUPMGR、首頁與管理頁資料均與先前單一入口包相同；只更新 Color 自身 BIN、頁面及 LUT 素材。
另用同版核心的獨立數值素材比較 35 模型 × 161 筆，最大通道 code 差 7.01e-5；報告明確區分該素材與清單示範 LUT。
原生檔案／GUI 呼叫由模擬器提供，未證明 SD 實體寫入、機內顯示或即時效能；沒有寫卡或操作相機，監看仍為 Off。
`20261022-color-library-01`／`02` 為未完成驗收的候選，保留失敗紀錄，不供部署。

## Color 設定說明

子頁用 `fpsup-ui`，有自己的 `LC_` 變數；每份 LUT 的 Settings 有啟用開關與色域／Gamma／強度控制，分成兩頁。
MENU 從設定返回管理清單，從管理／選擇頁返回 Color，再從 Color 返回 fpSup。機內不新增說明頁。
`native/color_ui.c` 負責子頁，`color_ui.py` 使用共用原生元件產生 `UI/COLOR.BIN`；不修改 loader 或 fpsup-ui。

[先前單一入口開發包](../../projects/lut-sup/cards/20261021-color-single-entry-01/)已通過
[88 項離線回歸與 7 個故障副本偵測](../../projects/lut-sup/validation/20261021-color-single-entry-01/results/report.json)，
包含單一首頁入口、全部私有設定、MENU 原生返回、缺檔與字串保護。新版本尚未再寫入相機或實機驗收。

| 設定 | 用途 |
|---|---|
| Enabled in list | 決定該 LUT 是否出現在目前 LUT 的選單，不代表同時套用多份。 |
| LUT file / status | 顯示目前素材的載入狀態；missing／invalid 表示缺檔或資料無效，model pending 表示所選模型待核實。 |
| LUT color family | 色域清單的分組，先選群組，再用下一項選真正的色域；本身不是另一道色彩轉換。 |
| LUT color space | 選擇這份 LUT 預期接收的輸入色域，須依 LUT 的製作設定選擇。 |
| LUT gamma family | Gamma 清單分組；Blackmagic 會自動改用其專屬清單。 |
| LUT gamma value | 選擇 LUT 預期接收的輸入曲線，與色域分開設定。 |
| LUT strength range | 強度清單分組：0／25／50% 或 75／100%。 |
| LUT strength value | 真正的套用強度；0% 為基準監看，100% 為完整 LUT，其餘混合兩份同為 Rec.709／Gamma 2.4 的結果。 |
| LUT monitoring | 監看開關；目前影像路由未接通，選 On 會被拒絕並回到 Off。 |

Family／Range 是原廠 popup 最多三個選項所需的分組，不會增加額外的色彩運算。
切換分組時會先選該組第一個值，再用對應的 space／value 選擇實際項目。
輸出固定 Rec.709 D65／Gamma 2.4；使用者只指定 LUT 輸入。Rec.709 Gamma 與兩項 Blackmagic 模型仍待核實，
選取後明示 pending，不代用其他曲線。library 模式將輸入設定寫回 cube 註解，其他監看偏好寫回自身 BIN；
舊單份參考模式仍只修改本次開機 RAM。

## Ole2026 離線 CST 驗證（2026-10-21）

`ole2026.py` 新增使用者提供的 Ole Berek March 2026 配色實驗，獨立於 CinemaDNG 產品選單。
實作 P3-D60/Linear → BWG4/5/Film5 → 將數值重解為 Gen1/sRGB 並轉 sRGB/sRGB
→ 重解為 BWG4/5/Film5 並轉 DWG/DI。CAT 依序為開／關／關，tone/gamut mapping 及 OOTF 關。
預設是明示未驗證的舊 Gen1 常數候選；傳入 `MeasuredMatrices` 才使用本輪量出的四組矩陣。

已在獨立 Resolve Studio 21.0.4.5 專案，使用真正 ResolveFX CST 的 Fusion 時間軸合成匯出 float32 EXR。
檔案往返逐值相同，包括負值與 16 倍超白。四組矩陣各只用三個 unit-basis RGB 像素量測，
再以其餘樣本驗證；完整三節點鏈在兩組共 2,048 筆樣本的最大 code 誤差 **5.84e-7**。
原始浮點檔、完整 `.comp`、節點設定、各檔 hash、舊常數誤差及曝光測試均保留在
[最終報告](../../projects/lut-sup/validation/20261021-ole2026-offline-01/final/report.json)。
Resolve 介面已核對 BWG4/5 實際使用舊內部 ID `BMD4KBCASTFILM_COLORSPACE`，不是從代號猜顯示名稱。

另有固定 Rec.709 D65／Gamma 2.4、線性硬裁切的監看實驗；這是自訂顯示方案，沒有模擬作者
最後的 DaVinci tone mapping／Rec.709 Gamma。33³／65³ 的 Q 與 bypass cube 均已匯出回讀、
以獨立樣本檢查；**本實驗的完整 Film5 0..1 輸入域加硬裁切，四份均未通過每通道 1/1023 門檻**。
65³ Q 在 scene-linear 709 來源分布最大誤差 .381、均勻 log 立方體 .810；不能部署這四份研究檔。
此結果針對這個合成方式，不是對使用者原始 `.cube` 的一般限制。

`factorized_monitor()` 改以兩組矩陣、sRGB decode、sRGB encode→Film5 decode 的合成一維曲線，
最後接線性裁切／Gamma 2.4。它與未拆分監看算式在 16,384 筆樣本、Q 開／關的最大誤差
**1.29e-14**；[拆分圖與係數](../../projects/lut-sup/validation/20261021-ole2026-offline-01/final/cubes/factorized-graph.json)
可用於後續 ISP＋CPU 殘差規劃。一維曲線目前以解析式執行，尚未量化為硬體表，也未測機內效能。

這輪只驗證已解碼 RGB 的 CST 子鏈：沒有驗證 CinemaDNG RAW 解碼、作者未知 Node04/06、
原廠 OFF／normal profile、Highlight Recovery、Pyxis 色準或機內 tap。Q 在撤銷 ±2 EV 後仍有色度變化，
不能當曝光不變的 sensor 校正。沒有操作相機、寫卡、更新 sup，也沒有開啟待核實的 Blackmagic RAW 模型。

從研究樹根目錄可用已保存的 Resolve 參考重跑（輸出目錄須不存在，無 Resolve／相機連線）：

```sh
python3 projects/lut-sup/probes/validate_ole2026_offline.py /tmp/ole-offline-check \
  --calibration projects/lut-sup/validation/20261021-ole2026-offline-01/cst-reference-04 \
  --independent projects/lut-sup/validation/20261021-ole2026-offline-01/cst-reference-05
```

## Loader v4 開發 sup（2026-10-21）

`build_sup.py` 產生 `fpSup/LUT.BIN`（FSB4、最低服務表 v6、`LUT4` ID）。沿用現有
`loader-v4/build_v4.py`，沒有修改／複製共用 loader。entry 完成讀檔和註冊後返回。
程式、設定、API 和 LUT 都由自己的常駐 block 保管；沒有指向 loader staging。

```sh
# 預設使用明確標示的 identity 診斷 LUT，輸出目錄必須不存在。
python3 -B build_sup.py --out ../../projects/lut-sup/cards/my-lut4 --card --debug
# 使用自己的監看 cube，保留原始 1D/shaper/3D 節點，不重採樣格點。
python3 -B build_sup.py --cube look.cube --input-space p3-d65 --input-gamma gamma26 --out out/lut4
```

`--card` 加入目前共用的 v4 AutoRun、LOADER、SUPMGR 及 UI 資料；`--debug` 才加 SHELL。
UI 預設開啟，`--no-ui` 可建立不含畫面的核心測試卡。
`--splash`、`--instant`、`--fast` 明確選用，不因這是 LUT sup 就開啟持久化快速啟動。
同一載入配置更換 LUT 素材不改 AutoRun、LOADER 或 LUT.BIN。

上句適用舊單份 `--cube` 參考模式；`--library` 的清單與設定嵌入 LUT.BIN，重建清單會更新該 BIN，
但不要求更新 AutoRun 或共用 loader。相對已遷移的單一 Color 入口版本，本次只改 Color 自身程式與頁面，
共用 LOADER／SUPMGR 與首頁資料沿用。

檔案配置（2026-11-06 起；Bei：清單＝資料夾、不帶內建 LUT、sup 自己的檔案移出使用者資料夾）：

- `fpSup/LUT.BIN`：常駐 ARM 程式與私有資料（`--library` 版區塊約 0.7 MB：程式＋字串＋清單＋匯入常數、
  state、8 KiB io、一格 COLOR 圖磚、ISP 表組 `LVB_CAP`、轉檔常駐狀態 `CONV_CAP`），完整 BSS／DMA 範圍由 v4 標頭宣告；
  內含 LUT 清單（每份 .cube 的啟用、色域／Gamma／矩陣、強度、目前選擇）。
  大工作區不常駐（2026-11-07 Bei；常駐 6 MB 時 MOV 一開錄就整機凍結）：解析好的 cube（4 MiB）、擬合樣本、
  轉檔工作區都在用到時向韌體配置器（class 0，與 loader 同一組函式）借、用完立刻還，錄影中一律不借（`native/borrow.c`）。
  `LUT_ASSET_CAP` 現在只改借用的大小（參考模式則是常駐區大小），不再影響 `--library` 版區塊。
- `fpSup/LUT/*.cube`：**只放使用者自己的 .cube**。相機開機與每次開 LUT Manager 掃描，子資料夾與非 .cube 檔略過。
  檔案不在就不出現在任何清單；記錄留在 LUT.BIN（隱藏），同名檔放回來設定就恢復。正在用的那份不見了就 Off。
  清單滿 32 份時，新檔優先佔用已不見那份的位置。`.cube` 本身相機不寫。
- `fpSup/LUTDATA/<sha 前 16 hex>.JFT`：Manager 轉檔結果，相機轉檔時自己建資料夾（mkdir 已上機驗證，見 conv.c）。
  2026-11-07 起檔尾多一段 212 B 的**色卡區塊**（`'JFC1'`、長度、還原度 %、核心的 FNV、48 個 0xRRGGBBAA＝0 EV 色卡
  24 格的目標／擬合，正是轉檔畫面最後留下的值、自身 FNV；格式見 `jft.py`、`native/lvb.c JFC_*`）。
  標頭的 total（+12）仍是 64＋payload，JFIT 版本仍是 2：舊 v2 檔（沒有區塊）照樣有效、ISP 表照樣從它讀，
  不必重轉；只有「查看色卡」會說 `Convert again`。ISP 讀取只讀前 JFT_BYTES，看不到區塊。
  **2026-11-10 起 JFIT 版本 4（CEQ 色相順序）**：ISP 在相鄰兩個 CEQ 色相目標之間是「往前、mod 360」內插，
  遞減的一對會繞遠路、中間色相掃過整圈（上機：Fuji 3513DI／Kodak 2383 綠色出現洋紅，v3 檔節點 16→17 遞減）。
  擬合加了順序鉸鏈（`jfit.c jf_hinge`：相鄰前進間距 15＋dh[a+1]−dh[a] 低於 4.75° 就罰，權重 10/°），
  打包再夾一次（`jf_hue_safe`／`jft.hue_safe`，目標 3.8°）並檢查每步 ≥ 683 字（3.75°＝節點間距 1/4）且合計一圈，
  不合就不寫（`CVE_HUE`／`ValueError`）。模型（`jf_hue_dd`、`lut_batch_eval.hue_lerp`）也改成往前 mod 360。
  v3 以前的檔一律視為過期（`lvb.c JFT_JFIT`＝4），列顯示 Off，開 On 時重轉。
- 每份 LUT 的設定頁（AEL）第 4 列 `Color chart`（查看色卡，Bei 2026-11-07）：OK／右鍵 → 從該份 .JFT 的色卡區塊
  畫出色卡與還原度（上半＝cube 目標、下半＝擬合），**不載入 cube、不借 4 MiB 區**（檔案讀進常駐的 lvb jbuf），錄影中拒絕
  （`Recording busy`）。任何鍵關閉：OK／右鍵再按一次、上下移動、MENU（MENU 只關色卡、不離開，再按一次才回 Manager）。
  沒有區塊或沒有檔：該列顯示 `Convert again`。設定頁的色卡是 Y5_1 自己物件做的複本（`settings_y51.chart_overlay`），
  與 Manager 的轉檔色卡共用變數 LC_Chart／LC_Match／LC_P00..47。**未上機。**
  `fpSup/LUTDATA/ACTIVE.LUT` 只有舊單份參考模式（`--cube`／不給 `--library`）才有。
- 不再產生：`LUT/DATA/`、`LUT/SOURCES/`、`LUT/source.cube`、`LUT/settings.json`、`LUT/menu.json`、`LUT/JFIT/`。
  建置紀錄只在 `build()` 回傳值，或 `--info FILE`（卡片目錄之外）。
- 舊卡：LUT.BIN 裡電腦準備的記錄（origin 0，含示範 LUT）開機時從清單拿掉，下次存檔時從檔案消失；
  舊 `LUT/JFIT/` 的轉檔不再讀，需在 Manager 重轉。舊子資料夾可手動刪除，留著也無害。
- `--library`：把清單裡的 .cube 原樣放進 `fpSup/LUT/`，LUT.BIN 預填同名記錄（相機依檔名接手設定）。
- `fpSup/UI/FPSUP.BIN`、`SUPMGR.BIN`：由共用 v4 builder 產生的首頁／管理頁資料。
- `fpSup/UI/COLOR.BIN`：Color 自己的私有 LUT 設定頁，與 `LUT.BIN` 一起更新。
- `fpSup/COL-Share_v0.0.1test.BIN`（2026-11-07 起，`--card --library` 預設帶，`--no-colshare` 不帶）：
  原生 COLOR 清單的列、setter、±框與 ISP root 共用字歸 COL-Share（`fpSup/colshare/`），LUT 是它的客戶
  （`native/cols.c`，取代 `clist.c`／`clist_ui.py`）。LUT 只 claim 自己專屬的點：DNG 六點＋兩張表、
  MakerNote 0x124/0x12D/0x34/0x129、YGAM。卡上沒有 COL-Share：沒有 COLOR 列、不裝任何點，Manager 照常，
  頁尾顯示「COLOR list needs COL-Share」。

程式在快取別名執行；只有 8 KiB 檔案物件／分塊讀取 scratch 用 `svc->uncached()`。
完成讀取後由 CPU 複製到自己的快取 LUT 資料。缺檔、短讀、錯誤尺寸、checksum 錯誤、
多餘檔尾均明確拒用。素材的 FNV-1a 是偶發損壞檢查；來源 SHA-256 用於主機追溯，
不建立 AutoRun／BIN runtime 配對。

透過 `page_add()` 只註冊 Color 入口；管理、選擇及每份設定留在私有頁面。子頁配合原生 popup 的 3 選項上限，以群組＋值選擇
完整的 8 色域、6 Gamma 與五段強度，另有檔案狀態及監看開關。
在只有 Color 與 SupManager 的卡上，首頁共兩列。清單按需要分頁，每份 LUT 的設定不占首頁列。
離線測試實際載入共用 ARM renderer 與 UI 資料，透過模擬原生 GUI 驗證 popup、相依欄位立即更新、
全部色域／Gamma／強度、分頁及管理頁；另用原生頁面 interpreter 核對頁面與 MENU 離開路徑。
**這些結果不代表 LUT 設定畫面已在相機上驗收。**
色域／Gamma 在 RAM 中可獨立切換，Blackmagic 自動換成自己的 Gamma 清單；pending 模型不執行。
本版強度先提供 0／25／50／75／100%。library 模式可切換素材並保存每份設定；
舊單份參考模式 UI 修改只在這次開機有效。尚未加入錄影 metadata。

`native/lut4.h` 定義本產品的 `LUT4` 服務。真正 ARM 核心可處理呼叫者自己擁有、已分離的
scene-linear XYZ D65：Q20 色域矩陣 → Gamma → 原始 1D／四面體 3D → 共同 709 強度混合。
不依賴軟體浮點 runtime。LUT 節點及樣本採 signed Q20；Gamma 表每 octave 256 格，
查表權重 24-bit；所有量化誤差必須和 float64 參考分開報告。
每次 1–4096 筆，XYZ 各通道 ±64，轉入色域後各通道 ±128；超界拒絕而不暗中裁切。
輸出保留負值／超白。原地同一陣列可用，其餘重疊拒絕；後段樣本錯誤不留下部分輸出。

**這是原生查表／控制開發版，不是已完成的監看產品。** 未安裝影像 hook、不借用原廠 ring、
不改 RAW 或原生 ISP 設定。`enable(1)` 回報 `NO_BACKEND`，監看值仍為 Off；
尚待 fp 輸入校準、owned frame 路由、ISP 主要處理＋CPU 殘差、LUT 畫面上機驗收與效能驗證。
CPU 參考批次通過不能當作已達即時幀率，也不改變已選定的硬體主要處理架構。

離線測試：`python3 -B -m unittest -v test_sup_native test_sup_ui`（需本機韌體映像、Unicorn、clang）；
缺依賴造成跳過就是未驗證。建置不代表已獲准寫實體卡、操作相機或發布。

[含 UI 的開發產物](../../projects/lut-sup/cards/20261021-loader-v4-ui-04/)：`LUT.BIN` 7,408 bytes，
私有常駐容量 4,214,016 bytes；附共用 v4 核心、UI、除錯 shell 和明確標示的 identity 診斷 LUT。
[驗證報告](../../projects/lut-sup/validation/20261021-loader-v4-ui-04/report.json)：82 項測試通過、無跳過，
6 個隔離突變全部被偵測，包含移除相依欄位更新。35 組模型 × 161 筆獨立輸入，共 5,635 次比較，
包含 XYZ／矩陣／Gamma／節點與內插量化，最大通道 code 誤差 7.01e-5、平均 1.26e-6。
這不是 DeltaE、Resolve 像素等價或相機實測。另以**這份實際輸出檔案**載入 LUT／SHELL／SUPMGR 與 UI，
確認 9 列可達、拒絕監看啟用並重繪 Off、關機還原；所有成品 hash 與本次來源 hash 已保存。
[最初不含 UI 的 66 項驗證](../../projects/lut-sup/validation/20261021-loader-v4-01/report.json)與對應開發包保持原樣。

2026-10-09 增加 `native_ceq.py` 與 `residual.py`，支援使用者選定的「硬體主要處理＋CPU 少量補正」。
前者保存六個 24 點 CEQ 平面、原生 16＋8 路由與倍率；已用原廠 Thumb-2 函式核對兩個 context，
包括 83 份可編碼的實機觀測與錯誤倍率測試。一份暫態值超出可表示範圍會明確拒絕。
**這驗證 anchor 資料格式，不是 CEQ 的像素算式，也不是完整 ISP job。**

CPU 補正接受實測硬體輸出與完整 cube 目標的 RGB 配對，提供 48-byte affine 係數及
5³／9³／17³ 四面體殘差表（float32 為 1,500／8,748／58,956 bytes）。
擬合採有界求解、明確 domain、獨立樣本驗證；不默默剪掉輸入或輸出。
另量 exact output collisions 的不可還原下限。七項測試使用合成配對，**沒有實機 RGB 配對、效能或還原率**。
先比較小型候選，再按驗證誤差升級；小表格省記憶體，不直接證明逐幀 CPU 成本低。

`preview.py` 可明確 unpack 線性 YUYV8，要求正確 geometry、byte stride 和有效資料範圍，
另要求選定 601／709 matrix、full／limited range 才能解 RGB；不裁切 decoded RGB。
這些 RGB 轉換仍是候選假說，不代表已校準 fp 色域／gamma，也不是可寫回的 frame owner。
實際授權的 CINE MONIT1 讀值已解出完整 1620×911 場景；不能推廣為所有格式皆為線性 YUYV8。 **封裝是 Y0 Cr Y1 Cb（YVYU）**：舊版當成 Y0 Cb Y1 Cr，橘色解成藍色（2026-10-27 對照 LCD，使用者確認）。

## 已可用

- `.cube` 的純 1D、純 3D（包括 17/33/65）及 Resolve 1D shaper＋3D；保留完整原檔。
- `TITLE`、註解、BOM、指數數字、`DOMAIN_MIN/MAX`、各 stage 的 `INPUT_RANGE`；拒絕矛盾或不完整資料。
- 完整 3D 四面體內插、可調強度；lookup 座標夾到 LUT domain，輸出負值／超白不自動剪掉。
- 離線 sRGB→sRGB PNG 預覽（先轉來源 ICC）；不代表相機 Live View 已接上。
- 在**新的 DNG 副本**中嵌入完整 `.cube`、名稱、輸入／輸出色域、強度、插值方法與 source hash。
  可逐 byte 取回原始 `.cube`；不搬 RAW／預覽資料、不改 ColorMatrix／WB 或 MakerNote。
- 可選 Adobe `RGBTables`，完整跨通道表；**軟體支援未驗證，尤其不能當成 Resolve 自動套用的保證**。
- `monitor-presets` 輸出 8 個色域、相依的 Gamma 清單及數值實作狀態；`monitor-preview` 提供有 sRGB ICC 的 PNG，
  `monitor-render` 保存不裁切的浮點 Rec.709／Gamma 2.4 資料及逐階段範圍報告。
- `monitor-prepare` 保存原始 cube、輸入矩陣／曲線識別與參數、監看設定及選定輸入域的
  17³／33³／65³ 合成查表；附 float32 節點的獨立樣本誤差，仍標記 `on_camera_ready=false`。

## 使用

需要 Python 3、numpy；PNG 預覽另需 Pillow（ICC 轉換需其 ImageCms）。從本目錄執行：

```sh
python3 -B fplut.py inspect look.cube
python3 -B fplut.py prepare look.cube out/my-look --input-space srgb --output-space srgb
python3 -B fplut.py preview look.cube chart.jpg chart-look.png --input-space srgb --output-space srgb
python3 -B fplut.py embed look.cube original.DNG with-look.DNG --input-space srgb --output-space srgb
python3 -B fplut.py extract with-look.DNG recovered.cube
```

`prepare` 的 `source.cube`／`settings.json`／float32 表是**離線整合素材**，不是可直接裝進卡片的產品。
設定內明示 `on_camera_ready=false`。所有輸出拒絕覆蓋現有檔案。

標準 `.cube` 指令與格點本身不描述輸入色域／gamma；本專案另提供上方的自訂註解約定。
使用者或作者必須提供真正的 LUT 輸入與輸出；
不能把 V-Log、BMD Film、DaVinci Intermediate 等技術 LUT 直接當 sRGB look。
通用 metadata-only 保存可使用明確的任意空間名稱；既有 `preview` 指令只處理 sRGB→sRGB。

機內監看產品已限定只接受 Rec.709 輸出的 LUT，使用者只選輸入色域／gamma，逐 LUT 保存。
固定輸出與監看強度的完整契約見 [產品需求](../../projects/lut-sup/README.md#機內產品行為目標尚未實作)。
本目錄的通用離線輸入／輸出設定仍用於保存及驗證素材；機內跨色域預覽尚未接入。

## 選擇監看 LUT 輸入

`monitor-*` 指令只選輸入，輸出契約固定為 Rec.709 D65／Gamma 2.4、full-range 正規化值。
cube 內容不能可靠辨識它的輸出空間；匯入的是依此契約製作的監看 LUT。

```sh
python3 -B fplut.py monitor-presets
python3 -B fplut.py monitor-preview look.cube chart.jpg monitor.png --input-space p3-d65 --input-gamma gamma26
python3 -B fplut.py monitor-render look.cube scene.npy monitor.npy --input-space rec709 --input-gamma gamma24 --source-space linear-709
python3 -B fplut.py monitor-prepare look.cube out/monitor --input-space aces --input-gamma linear --size 33
```

色域與 Gamma 是兩個控制項；不從色域名稱自動綁定 Gamma。

| 色域 ID | 選單名稱 | 標準數學參考／白點 |
|---|---|---|
| `aces` | ACES | AP0／D60；與 Resolve 名稱的對應尚待像素核對 |
| `adobe-rgb` | Adobe RGB | Adobe RGB (1998)／D65 |
| `blackmagic-design` | Blackmagic Design | CinemaDNG 專用模型待核實，不能用 BWG／Film Gen5 代替 |
| `p3-d60` | P3 D60 | P3 原色／D60 |
| `p3-d65` | P3 D65 | P3 原色／D65 |
| `rec2020` | Rec.2020 | BT.2020 原色／D65 |
| `rec709` | Rec.709 | BT.709 原色／D65 |
| `srgb` | sRGB | 與 BT.709 相同原色／D65；Gamma 仍獨立選擇 |

非 Blackmagic 共用六項 Gamma：`adobe-rgb`（Adobe RGB）、`gamma24`（Gamma 2.4）、
`gamma26`（Gamma 2.6）、`linear`（Linear）、`rec709`（Rec.709）、`srgb`（sRGB）。
Blackmagic 只有 `blackmagic-film`（Blackmagic Design Film）及 `blackmagic-extended-video`
（Blackmagic Design Extended Video）；跨組搭配會拒絕。

35 組標準模型 = 7 個非 Blackmagic 色域 × 5 條已實作曲線。Adobe RGB 曲線採官方的
2.19921875 指數；Resolve 標示 Rec.709 的 Gamma 公式尚未確認，保留選單項但不偷換成 BT.709 OETF。
兩組 Blackmagic 也保留並標明待核實。畫面中的灰字不作為啟用狀態證據。
[三張選單原圖與雜湊](../../projects/lut-sup/validation/20261016-cdng-menu-01/evidence.json)
才是目前清單依據，不能把手冊較短的列舉當成完整清單。

數學模型先在 scene-linear XYZ D65 與所選 RGB 原色之間轉換，白點不同時採 Bradford，
再套所選 Gamma，最後查原始 LUT。ACES 使用 AP0 原色的參考模型，沒有隱含 ACES RRT／ODT。
這些標準算式尚不等於 Resolve CinemaDNG 解碼；相機校準、白平衡、曝光與負值行為也要核對。

浮點來源必須明示 `--source-space`，scene-linear 18% 灰為 0.18，1.0 不是 sensor 飽和值。
`monitor-preview` 讀一般 ICC／sRGB 圖像，適合桌面流程檢查；不把已顯示化的照片當 fp RAW 校準。
輸出 PNG 先將 709／Gamma 2.4 換算成 sRGB，附 ICC；`.npy` 保留未裁切的 709 數值。
PNG 旁的 `.json` 分別記錄輸入色域、Gamma、曝光、強度、模型驗證狀態、lookup 超界與顯示裁切前的範圍。

基準監看明訂為 `clip-linear-rec709-gamma24-v1`：線性 709 裁切到 0..1，再編碼 Gamma 2.4。
CinemaDNG 標準模型在查表前不因色域名稱為 Rec.709／sRGB 而裁切，負值／超白保留到 LUT domain；
純冪次曲線的負值使用明訂的帶符號延伸，尚未證實等於 Resolve。
LUT 後不再套場景到顯示的轉換。`--strength 0..1` 混合兩份 709／Gamma 2.4 監看結果，
0% 回到基準畫面，避免用 `Cube.apply` 的數值混合把 Log 與 709 混在一起。
這個基準不是 Resolve、ARRI 或原廠 fp 的顯示渲染。

合成表的輸入仍是所選 LUT 的編碼及原本 domain，fp 校準／白平衡／曝光、色域矩陣及 transfer
放在查表前，LCD 適配放在之後。曝光不烘入表，強度烘入表；調整強度需重新產生合成表。
含 shaper、改變格點數或混入基準顯示時仍可能有重採樣誤差，以各包的報告為準。
不把整條跨色域管線壓進固定 DWG 格點：ARRI 極端飽和樣本顯示此作法可能產生明顯誤差。

官方公式來源列在 `color.py`，包括 [ACES AP0](https://docs.acescentral.com/encodings/aces2065-1/)
及 [Adobe RGB (1998)](https://www.adobe.com/digitalimag/pdfs/AdobeRGB1998.pdf)。
[更新後驗證](../../projects/lut-sup/validation/20261016-cdng-monitor-01/report.json)保存目前來源 hash、
53 項測試及選單範圍。`color.py` 的 `REFERENCE_SPACES` 另保留 ARRI／Sony 等通用數學回歸資料，
不列入 CinemaDNG 選單。回歸對照既存 14,648 筆
ARRI Classic 資料，最大 RGB 差約 3.01e-14；原輸入域 33³ float32 合成表的 9,217 筆獨立樣本最大差
約 2.90e-8。這是數值參考誤差，不是 fp 色準、LCD 或機內 backend 的還原度。

完整研究樹已取得 [ARRI 官方](https://www.arri.com/en/learn/camera-systems/tools/lut-generator)
Classic 709（K1S1）與 LogC3 Rec.709 v1 的原始 33³ cube，並建立 `prepare` 素材。
[候選與原始來源](../../projects/lut-sup/assets/arri/official-20261009/selected-cubes.json)
記錄 ARRI Wide Gamut 3／LogC3 → Rec.709 D65／Gamma 2.4，full-range 輸入／輸出。
fp 輸入轉換尚未校準；素材不是已可上機的 sup，不能交 `preview` 假裝 sRGB→sRGB。

## CDNG 自動顯影表的界線

預設只有保存設定；一般 DNG 軟體不會自動讀取 fpSup 自訂 XMP。
加 `--render-table` 才另外寫標準 DNG **RGBTables（52543）**，將 DNGVersion 至少設為 1.6，
保留原 DNGBackwardVersion。舊 reader 仍可能只讀 RAW、忽略外觀。
輸入與輸出必須同色域／同 gamma，支援名稱查 `dng.py` 的 `SPACES`。
log→709 等跨編碼 LUT 尚未做前後色彩空間轉換，會拒絕標準表輸出；原檔依然可完整保存。

標準表最多 **32³**，所以 33/65³ 會重採樣；設定中附 RGB 數值誤差，完整原始 `.cube` 仍在 XMP。
表以 float32 保存，DNG 是 R 外層／B 內層，與 `.cube` 的 red-fast 順序不同。
超出 0..1 的 table output 拒絕轉標準表，不默默裁掉。已有 RGBTables 的 DNG 會拒絕覆寫。
RGBTables 的 reader 插值、與既有 ProfileToneCurve 的處理順序、Resolve／Adobe 的實際效果，仍待 A/B 渲染。
依據：[Adobe DNG 1.7.1 §RGBTables，頁 75–81](https://helpx.adobe.com/content/dam/help/en/camera-raw/digital-negative/jcr_content/root/content/flex/items/position/position-par/download_section_733958301/download-1/DNG_Spec_1_7_1_0.pdf)。

支援 classic TIFF 的 II/MM、strip／tile／SubIFD，BigTIFF 不支援。
另附影像 payload SHA-256；嵌入後先做完整讀回與 source round trip 才寫出新檔。
完整研究樹的驗證紀錄另保留原始檔與解壓 Bayer 比對。

## 驗證

```sh
python3 -B -m unittest test_lut
python3 -B -m unittest test_residual
python3 -B -m unittest test_preview
python3 -B -m unittest test_native_ceq
python3 -B -m unittest test_monitor
```

涵蓋六種四面體分支、red-fast／DNG 次序、1D shaper、domain、strength、壞檔拒絕，
以及大小端、多 strip、SubIFD、opaque metadata、原檔完整還原、重採樣誤差與輸出不覆蓋。
CEQ 驗證另需 Unicorn 與完整研究樹的 fp 5.02 韌體／實機試驗紀錄；缺少時不是已驗證。
