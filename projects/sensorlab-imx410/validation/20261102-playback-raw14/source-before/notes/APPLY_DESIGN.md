# SensorLab-IMX410：讓 QS 選擇真正生效（套用步驟設計）

2026-11-02 v0.7.13test 候選：新增 `H_PBRING`（C05C2DE8，原字 EBE968FE），以原廠描述表大小／步長取得 300 個緩衝上限，在配置前回傳 NULL 結束；不另存計數器。既有兩個回放 prepare 入口只對已通過 guard 的目前選中片段，把無原廠播放表的高速類別 11–13 改用類別 10。拍攝幀率標記、持久化設定與幾何公式保留。41 apply hooks＋clock 共 42 claims，AP ABI 2／QS API 6 沿用。實際交付 BIN 的掛鉤、300 格上限、清理及所有 54 筆載入器還原記錄均完成離線執行；相機回放／插卡凍結改善待實測，見 `validation/20261102-playback-ring-fix/` 與 `PLAYBACK_DESIGN.md`。

2026-11-02 v0.7.12test 候選：使用者確認 v0.7.11 未解決、停錄即恢復。`core_spec.record_preview` 與 Python `Spec.record_preview` 預設為 0／False；只有 `apc_build` 依 `o->fast` 開啟。在既有 scaled 分支中，C 的條件增加「偏好錄影取樣且 act width ≤2000」，同時仍要求 source ≤2100×1710；B／D、bin 與不適合 C 的情況維持原規則。共用 `isp_visible()` 計算全部尺寸，沒有第二份預覽公式。新欄位只在內部計算結構中，未改持久化設定／AP ABI 2／QS API 6。歷史 r10 的 240p LCD 穩定紀錄僅為本候選選路的依據，不是新版本實機證據。驗證見 `validation/20261102-hirate-followup/`。

2026-11-02 v0.7.11test：`apc_build()` 在純幾何 `core_quality_spec()` 之後，依既有格率載體補上 `spec.hirate = (cr->rank >= 10000)`，供 `core_isp_plan()` 產生 canvas +B0。原廠 100／120 載體的 engine=50／60，故與 >99 的 clock／高速引擎路徑分開。profile 5 的 standby mask 不含 +B0。原廠 mapper C0434EF8 將其傳到 config +14，C01D1630 存到 C31DF578，C01D0640 再供 C01CABA0 的 descriptor +0C；嚴格離線執行及舊來源／錯門檻反例見 `validation/20261102-hirate-preview/`。此修正尚未通過實機持續錄影驗收，不能宣稱已消除 liveview freeze。

**v2，2026-10-29**：依 Bei 的四個回答改寫。v1 的「借殼」做法被否決。
Bei 的原話：「我們有虛擬表的做法，已經很純熟了」。

本文是離線設計，未寫程式、未上機。
- [驗]：讀過程式、資料或上機紀錄。
- [推]：推論，待確認。

## 0. 結論

**採用 RES-Custom 的虛擬表技術：虛擬 mode、虛擬 profile、picker entry、DNG FrameRate。把技術和程式碼搬進 SensorLab 自己的 sup。**
- 不要求 RES-Custom 載入；兩者永遠不同時啟用。
- 公式換成 SensorLab 的：readout_cfg.plan + smc.create（含 R10），以及 isp_formula v2。
- 相機上用的是 C 核心版本，逐位元相同 [驗 core/README.md]。

Bei 定案：
1. 用虛擬表。
2. QS 關閉與開機時自動套用，沒有總開關。
3. 原廠設定不改成殼的值，原廠選單也不顯示 FHD。
4. 非原廠格率的 DNG FrameRate 第一版就要做。

## 1. RES-Custom 的虛擬表是什麼 [驗]

出處：`open-gate/notes/OG_MULTIFORMAT_CORE_DESIGN.md` §3.2、`build/res-custom/VIRTUAL_RCD.md`、`ogc.c`、`ogc_virtual.c`、`ogc_layout.py`、
`archive/virtual-rate-20261020/README.md`、`res-lab/RESCUSTOM_STATUS.md`。

| 部分 | 作法 | 站點 |
|---|---|---|
| 虛擬 mode | 原廠表與描述子都不寫。IMX410 的 7 張模式表都靠「找索引」函式存取（比對 `row[0] == mode_id`）。hook 這 7 個函式加上 R10 查詢，遇到虛擬 id 就回傳假索引，讓「基底 + 假索引 × 步距」正好落在 sup 塊裡的列。R10 回值本身 | `lk_tim` C0320BA0、`lk_meta` C0320B38、`lk_r28` C0320E90、`lk_r38` C0320F60、`lk_r14` C0320EF8、`lk_r68` C0320C00、`lk_reg` C0326DB8、`lk_r10` C031FFA0 |
| 放大鏡 | 描述子 +0x128 表是內聯掃描，另需 6 個 hook | `ac38` C031AC38、`acd8` C031ACD8、`zg` C031B660、`v32` C03249A0（核心 hook 清單有 4 個）|
| 虛擬 profile | mapping 不寫。`C043A18C` 換成底列，canvas hook `C043A19C` 再整列宣告。pid 從類別 0 的空號取（74…）| `vpro`、`canvas` |
| picker | 錄影選路線時，命中虛擬列就回自己的 entry（虛擬 pid + 虛擬 mode）| `picker` C043CCF8 |
| 格率（10-20 泛化）| RCD 宣告 `SEC_RATES` {rank, num, den, cycles, carrier, nominal, engine}，相機設定只存載體格率。另外改三處：DNG FrameRate 有理數、最慢快門、角度→Tv | `recrate` C00C9BD0、`tvmin` C007F5B4、`angtv` C052DCFC |
| ISP bin | `SEC_BINFILT`：selector 修正 branch C 的重複水平 /3、選 soft/std，兩個 driver writer 改 H/V 係數 | `binpath` C0325228、`binkernel1/2` C032DDF0/C032DE70 |
| LV／比例 | 改 LV 緩衝尺寸、長寬比 | `out` C0437E98、`aspect` C0306EA0/EEC、`ratio` C02DAFA0 |
| 選單 | 解析度清單加 CUSTOM 一列，設定區只存原廠合法值（FHD 2／UHD 3）作為「backing」。選中哪個格式記在 sup 自己的 BIN；格率與位深依 entry 反灰 | `setter` C005C020、`cmt_set` C057A6A0、`frmax`、`frclass`、`bitclass`、`bitnorm` |
| 交易 | 在自有 scratch 預編譯、核對；確認沒在錄影（`busy`）後停 LV、關中斷提交，再重啟 LV；任何一步拒絕都保留原表 | `vrc_apply`（ogc_virtual.c）|

上機實績：
- 虛擬 mode 230/231 與原生 mode 12 逐字相同：7 張表、mode 判斷、錄影 profile 記錄 67 字 [驗 res-lab 20261014-parity-live]。
- 10-bit 239.76p 在 SSD 錄 90.9 s；OG3K/OG2K/S16 等磁碟 RCD 都上機過。

## 2. RES-Custom 的限制：根因，以及 SensorLab 怎麼解

| 限制 | 根因（程式） | SensorLab 的解法 |
|---|---|---|
| **無 14-bit** | 位深 mask 只有 8/10/12 三個位元（`ogc_layout.BIT_DEPTHS`、`SEC_BITDEPTH`）；picker 只有三張依 eRawBitType 分的路線表（`TAB1/2/3` 0xC0BE5810/59B0/5B50），沒有 RAW14 表，consumer 也沒接平面碼 [驗] | 14-bit 不靠路線。原廠位深留在 12，虛擬 profile 的 +0x80/+0x84 平面碼由 `core_isp_row` 依 AD 14 算出。isp-lab 的 14b 案例就是這樣過的 [驗 isp-custom-night1、isp_custom `d14`]。這條要在虛擬路徑上重驗 |
| **宣告格率最多 4 個** | `RCD_MAX_RATES = 4`（`VRC_MAX_RATES 8`），是靜態陣列。每個宣告格率要佔 picker entry（`MAX_GEN = 2×(9+4)`），因為 RES-Custom 要讓使用者在多個格率間切換 [驗 ogc_layout.py:210,325] | SensorLab 一次只有一個生效格率（QS 選的 fps／VMAX）。只產生「當下這一個」entry：載體 = 原廠設定裡的格率，exact num/den 給 `recrate`。換 fps 就重新提交，沒有清單上限 |
| **一次開機最多 16 個虛擬 mode** | `MAX_VMS = 16`：mode id 只能用 230..245（id < 250 才有名稱槽、不能是原廠 70 個 id、避開 0x99..0xB7 的常數比較）；每個 VM 在 S 裡有固定緩衝。RCD 依格式各佔 mode [驗 ogc_layout.py:141,238、§3.2.1] | 只用 **2 個 id**（例如 230/231）輪流：新選擇寫進非生效的那個，提交時 picker 改指它。韌體看到換 mode 會整組重設；舊 id 的列下次再覆寫。開機次數與選擇次數都沒有預算問題 |
| **找索引 hook 與別的 sup 衝突** | 8 個 lookup、6 個放大鏡、picker、canvas 都是函式入口的 B/BL hook。RES-Custom 會佔同一批站點 [驗 HOOKS] | 照用同一批站點。靠 loader v4 的 claim/journal：兩者同時在卡上時，後到的被拒，所以絕不會疊在一起（與「永不同時啟用」一致）。另外要補 RES-Custom 的已知洞：`lk_reg` 找不到時回 0xFFFFFFFF，會讀 base−0x288 [驗 RESCUSTOM_STATUS P5]，SensorLab 版要回原廠路徑 |
| （附帶）RES-Custom 自己的 QS 三層與存檔 hook | `qsrec` C05E6400、`qslay` C05D90F0、`qsload` C05E84D8、`save` C0088C60，和 QS 容器搶同一批站點 [驗] | **SensorLab 不搬這幾個**：QS 由容器負責；選擇存在 SensorLab 自己的 BIN（已有 SLQ2 紀錄）|

## 3. 公式怎麼接進去

| RES-Custom 原本的來源 | SensorLab 改用 |
|---|---|
| RCD 的 donor mode + overrides {kind, off, value}（`SEC_MODES`/`SEC_VMODES`）| `core_quality_plan(q, fps)` → `core_smc_create` 直接產出 8 張表的整列（TIM/META/R10/R28/R38/R14/R68/REG），寫進虛擬 mode 的列緩衝；不再用 donor 加 diff |
| R10：複製 donor 的值（`VM.R10`）| `core_smc_create` 的 R10（依 readout cls，[[vmode-needs-r10]]）|
| RCD canvas pairs（rec／act／producer…）+ 底列 | `core_quality_spec` → `core_isp_row(spec, base)` 的 65 字整列；canvas hook 整列宣告，+0x30 引擎格率照 RES-Custom 取載體 entry 的值 |
| `SEC_BINFILT` 的 5 個 u32 | QS 的 HBIN/VBIN、kernel kh/kv、mode km（打包法同 `binfilt_cfg`）|
| `SEC_STANDBY` 待機可見寬高、aspect | 由 isp plan 的 standby 與 DNG 長寬比算（isp_custom `standby_diffs`/`display_diffs`/`lvout_rules` 的算法移植成 C）|
| `SEC_RATES` | 當下的 fps_n/fps_d、載體、引擎格率 |
| DNG DefaultCrop | 每個 recipe 自己的可見尺寸（rec − 16×10，含 2% 寬容）|

**為什麼要重驗**：633/639 用的是殼的路徑（描述子整體換指、殼那一列的欄表直接改 RAM）。換成虛擬路徑，下列各點都要重驗：
- 公式算出的位元組送進韌體的方式不同：
  - 找索引 hook 與假索引；
  - picker；
  - 虛擬 pid 的類別旗標；
  - canvas 整列宣告；
  - binfilt 的站點與 isp-lab 差 8 bytes（DDF0/DE70 vs DDE8/DE68）。
- 每一種 readout key（40 個）與 ISP branch 至少要在虛擬路徑上錄一次。
- res-lab 的 parity-live 證明虛擬 mode 能做到與原生逐字相同，但那只涵蓋 mode 12。
- 14-bit、R16、2% 寬容配方、非原廠格率在虛擬路徑上都沒錄過。

## 4. 原廠選單顯示什麼（Bei 3）

RES-Custom 的作法 [驗 §12、custom-format-selection-is-a-variable]：
- 解析度清單多一列 **CUSTOM**，選單與摘要顯示 CUSTOM。
- 設定區只存原廠合法的 backing 值（FHD 2 或 UHD 3）。韌體內部衍生的寬高在存檔前設回原廠，選中哪個格式記在 sup 的 BIN。
- 格率清單用六份 CSV 複本，依 entry 反灰。

SensorLab 照這樣做，並接上 Bei 的選單計畫：
- **記錄設定 → 解析度**：原廠預設（UHD／FHD……）+ **CUSTOM**。
  - 選 CUSTOM 就退出選單、打開 QS 的 RES 子選單（Bei 的計畫，選單那一輪再做）。
  - 選原廠預設就是原廠行為，虛擬 entry 不生效。
- **生效條件**：解析度 = CUSTOM 且格式 = CinemaDNG。
  - QS 的 FORMAT/DC/RES/FPS 在取代模式下就是 CUSTOM 的內容；在 QS 上動了這幾格，解析度自動變成 CUSTOM。
- **格率列**：設定存的是載體（原廠 9 個之一）。CUSTOM 時這一列要顯示什麼，見 §8 問題 1。
- **位深列**：AD 11/12 顯示 12bit，AD 14 顯示 14bit。14bit 不是原廠選項，要比照 RES-Custom 的位深 CSV 複本加一項或改摘要，見 §8 問題 2。

## 5. 什麼時候套用（Bei 2）

| 時機 | 做什麼 |
|---|---|
| QS 關閉（`leave()`，已在呼叫 `sq_apply`）| 選擇變了才提交。錄影中或 busy 就記欠帳，閒置輪詢時再提交 |
| 開機 | 從 SLQ2 紀錄還原選擇，等 LV 起來後的第一次閒置才提交（不在 loader entry 裡做）|
| 錄影中 | 一律不動 |
| 熱重開 | RAM 會留著（[[warm-restart-keeps-the-cave]]）。開機時 hook 站點與狀態先驗，不是自己的就不 arm |

## 6. 相機端要寫的（`projects/sensorlab-imx410/apply/`，新目錄）

- 從 `open-gate/build/res-custom/`（`ogc.c`、`ogc_virtual.c`、`ogc_shims.S`、`ogc_binfilt.c`）**複製**需要的部分，記下來源 sha256。
- 不改 RES-Custom，也不改 isp-lab、imx410-lab 的任何檔（nightrun 用的檔不動）。

| # | 模組 | 來源 |
|---|---|---|
| B1 | 8 lookup + R10 hook、假索引計算、2 個虛擬 mode id 的列緩衝 | ogc.c 的 VLOOK／shims（搬）|
| B2 | 放大鏡 6 hook（ac38/acd8/zg/v32）| 搬；zoom_mode 用 readout 的 donor 類別 |
| B3 | 虛擬 profile（vpro + canvas）、pid 2 個輪流 | 搬；canvas 內容改成 `core_isp_row` |
| B4 | picker：解析度 = CUSTOM 且 CinemaDNG 時回自己的 entry（虛擬 pid、虛擬 mode、載體 key、引擎格率）| 搬 entry 產生；不搬 RCD 解析 |
| B5 | 格率：recrate、tvmin、angtv；frmax/frclass 讓載體可選 | 搬（10-20 泛化版）|
| B6 | binfilt：binpath + binkernel1/2 | 搬 |
| B7 | LV：out、aspect、ratio、standby 可見範圍 | 搬；值由公式算 |
| B8 | 選單：解析度 CUSTOM 一列（uishare add_option）、setter backing、格率／位深 CSV 反灰 | 搬一部分。選 CUSTOM → 開 QS 留到選單那一輪 |
| B9 | 提交交易：預編譯 → busy → 停 LV → 提交 → 快取 → 重啟 LV；失敗保留舊表 | `vrc_apply` 的流程 |
| B10 | 錄完驗收：`0xC343B590` == 虛擬 mode id，錯誤碼給 QS 顯示 | 新 |
| B11 | `sq_apply()` 接 B9；開機還原 | 新 |

## 7. 風險

1. **計時顯示錯**：RES-Custom P2 未解。錄影計時顯示「幀數 ÷ 載體原生格率」，非原廠格率時會錯。計時程式碼還沒找到。
2. **載體副作用**：載體 > 99.99 fps 時有一整族閘門（時脈閘 C0189440 已處理；FUN_c01302f8、c01cb9b8、c0179b38、c01d6980 未處理）。119.88 載體錄影時會關 LV 管線 [驗 RESCUSTOM_STATUS P1/P4]。載體挑法要定：最接近且 ≥ 目標的原廠格率？還是固定 29.97？
3. **12-bit 高格率持續錄影**：RES-Custom 的 12-bit 239.76p 在 SSD 只撐 36–40 s 就自停，根因未定。
4. **picker entry 與 profile 類別**：任意 DC×RES 的虛擬 pid 類別旗標、寫檔器的 writer 政策（4 MiB 批次、檔頭 CPU 複製）不一定適用每種尺寸。
5. **每次提交都會停／重啟 LV**：QS 關閉時畫面會閃一下（RES-Custom 也一樣）。
6. **工作量大**：要搬的 hook 約 30 個。每段新程式先直接呼叫一次再 arm，一次只改一件事（[[freeze-postmortem-discipline]]）。

## 8. 分段上機（每段先告知 Bei、廣播相機使用權）

1. **V1 單一固定配方**：OG 3K 29.97p 12b 2x3，載體 29.97。
   - QS 關閉時提交，錄 3 秒。
   - 驗：DNG 尺寸、位深、彩色預覽（先扣黑階再乘白平衡）、`0xC343B590` = 虛擬 id、待機範圍、LV 比例。
   - 與 isp-lab 殼路徑同配方的 DNG 比內容統計；用 parity 工具比 7 張表與 profile 記錄。
2. **V2 選單**：選回原廠 FHD 錄一段，必須是原廠畫面。解析度顯示 CUSTOM／原廠、格率位深反灰都要對。熱重開再錄一段。
3. **V3 換 fps**：同配方在 23.98、25、59.94，以及非原廠的 48.713、60.562。
   - 驗：幀計數 ±0.1%、DNG FrameRate num/den、最慢快門與角度、計時顯示（風險 1）。
4. **V4 ISP bin 與 14-bit**：HBIN 3、SOFT/STD、14-bit 平面碼。
5. **V5 開機還原**：關機再開，選擇自動還原並生效。
6. **V6 矩陣抽樣**：40 種 readout key × ISP branch 各一組，加上 R16、寬容配方，與 633 筆的主機結果逐項比。
7. 之後：> 59.94 載體（100/119.88、SD 灰掉的政策）、高格率持續錄影。

## 9. 工作量

- 離線：B1–B11 搬碼與接公式，unicorn 測試照 RES-Custom 的測試分層，含 mutation。約 7–9 天。
- 上機：V1–V5 約 3 天；V6 依結果 1–3 天。
- 比 v1（殼）多約 4–5 天。多出來的主要是 hook 數量、選單 CUSTOM，以及 DNG FrameRate。

## 10. 要 Bei 決定的

1. **CUSTOM 時格率列顯示什麼？** 選項：
   - 顯示載體（例如 29.97，跟實際不同）；
   - 換成摘要文字，顯示實際格率（要搬回 10-20 封存的格率介面 hook）；
   - 留到選單那一輪再定，第一版先顯示載體。
2. **14-bit 在原廠位深列怎麼顯示？** 位深列加一個 14bit 選項，還是 CUSTOM 時位深列整列鎖住、只顯示 QS 的值？
3. **載體挑法**：最接近且 ≥ 目標的原廠格率，還是一律用 29.97？前者 DNG 計時比較接近，後者避開 > 99 那一族閘門。
4. 有了 CUSTOM 之後，在 QS 上動 DC/RES/FPS/RECIPE，要自動把解析度切成 CUSTOM 嗎？還是要先在選單選 CUSTOM 才生效？

## 2026-10-29 Bei 更正：套用時機
- 改為**修改後馬上套用**：QS 半透明時就能在 live view 看到變化（不是關 QS 才套）。
- 實作要點：轉盤連轉要去彈跳（停手約 300 ms 才提交）；每次提交會停/重啟 LV，畫面會閃一下（風險已知）；錄影中仍然不動。
- 開機時一樣自動套用。
- Bei：「請開始做生效」（2026-10-29）。

## 11. 套用單元 V1（2026-10-29，離線，未上機）

全部在 unicorn 對真映像（`out/MAIN_c0000000.bin`）跑過；「上機」一項都沒有。

### 11.1 V1 配方更正
- **OG 3K 沒有 12b 2x3。** OG 3K = 3024×2020，`quality.qualities(..., tol 2%)` 只有 1x1、h2、v2、2x2 等 [驗]。
  - 12b 2x3（`12h2v3`，3024×1330 → 2016×1330，看到 2000×1320）在 **OG 2K**（2016×1346）[驗]。
- V1 主配方因此用 **OG 2K 29.97p 12b 2x3**。副配方用 **OG 3K 12b 2x2**，測輪換用。見 §11.10 問題 1。

### 11.2 檔案（`apply/`）
| 檔 | 內容 |
|---|---|
| `ap.h` | 對 slqs.c 的介面（§11.3） |
| `ap_calc.c` | 純計算：選擇 → 一個 slot 要裝的全部值。沒有韌體存取，主機可測 |
| `ap.c` | hook、虛擬表、交易、去彈跳。include `ap_calc.c`；在 sup 裡放在 `core.c` 之後 |
| `build_apply.py` | ARM 平面映像（sup 同一組旗標、`link_flat` 是 `qs/build_slqs.py` 的複本）＋主機 dylib |
| `test_apply.py` | 24 項測試＋`--mutate` |

- 技術照 RES-Custom（ogc.c／ogc_shims.S）複製，**不需要它載入**。
- 24 個站點都 `SL_EXCL`：和 RES-Custom 同卡時，後到的會被拒、完全不 arm。
- 每個 hook 共用一個 88 B 的 ARM veneer：存全部暫存器、對齊 8、呼叫 `ap_hook(A, frame, id)`。
  - 處理器回傳 0：往下（下一層或 replay）。回傳 1：直接返回。
  - veneer 放在呼叫端給的記憶體；cave 每站只佔 8 B（`ldr pc,[pc,#-4]`）。

| hook | 站點 | 做什麼 |
|---|---|---|
| 7 個找索引＋R10 | C0320BA0… C031FFA0 | 230／231 回假索引（落在我們的列）；R10 回值 |
| 放大鏡 | ac38 / acd8 / zg / v32 | 我們的列＝donor 列換 id。acd8／zg 看 donor。v32 對我們的 id 不寫窗（REG 列已帶窗，等同 vmode KEEP_WINDOW） |
| picker | C043CCF8 | 只答 TAB3（12-bit），且 key 的格率尾碼＝載體 → `{5, 74/75, 230/231, "SL30"}` |
| vpro／canvas | C043A18C／C043A19C | 虛擬 pid 拿 profile 171 的列（isp-lab BASE_ID）；canvas 寫公式字＋0x30＝載體引擎格率。6 個待機 pid 寫 +0x20／+0x28 |
| gs | C03A6DD8 | 我們的 canvas 是 raw movie |
| recrate | C00C9BD0 | 原生值先算；我們的 entry 被選中且原生值≈載體時，換成 §11.4 的有理數 |
| binfilt | C0325228、DDF0、DE70 | RES-Custom ogc_binfilt 同算法；只在我們的 entry 被選中時 |
| LV 輸出 | C0437E98 | 1620×911（待機）、選中後 1620×1080 → lv_box；320×180／213 → 320×round(320/a) |
| 比例 | C0306EA0／EEC＋C02DAFA0 | 兩處 `mov r0,#3` 改 9，比例 getter 對 9 回 limit_denominator(1000) 的 pair。不寫原廠表 |

- **兩個 id 輪流**：提交寫「不在用」的 slot。上一個 slot 保留到下下次提交，所以韌體手上的列永遠不會被改寫。
- **原廠表、設定區一個字都不寫**。測試逐位元組比對了 TIM／META／REG／mapping／TAB3／canvas +0x30 欄。

### 11.3 slqs.c 要呼叫的介面（`ap.h`）
- `ap_init(mem, AP_MEM_BYTES, svc)`：**只在 sup_entry 裡呼叫**（loader 把 claim 算在正在跑 entry 的 sup 上）。
  - mem 要 32 KiB、8 對齊、常駐（裡面有 veneer 程式碼）。實際 `sizeof(struct ap)` 約 28 KiB。
  - 整合：在 `struct st` 加 `u8 ap_mem[AP_MEM_BYTES] __attribute__((aligned(8)))`，`STATE_RESERVE` 加 0x8000。
- `ap_request(mem, &sel, now_us)`：每次有效選擇變了就呼叫（每一步轉盤都可以；只存起來）。
  - `struct ap_sel` = `sq_apply()` 已算出的 `st->applied`，加上 `fmt` 與 `valid`：`{dcw,dch,rw,rh,key,hbin,vbin,hm,vmax,fps_n,fps_d,kh,kv,km}`。
  - 配方用 (key, hbin, vbin) 在 `core_qualities_tol(DC,RES,不設上限,2%)` 裡重找，hm 必須相同。
  - 所以 slqs 不必把 core_quality 傳過來，這裡會再算一次（3.8–4.5 M 指令）。
- `ap_tick(mem, now_us)`：最後一次 request 後 ≥ 300 ms 才提交；錄影中只記欠帳。
- `ap_flush(mem, now_us)`：leave()／開機還原用，不等 300 ms（錄影中仍不做）。
- `ap_status_get`：狀態、最後結果與 detail（CORE_E_*／ISP_WHY_*）、各 hook 命中數、上次提交耗時。
- 時間用 `ap_now_us()`（0xC002B6E0）。
- 開機還原：entry 呼叫 `ap_init`，讀回 SLQ2 紀錄後 `ap_request`。第一次 LV 起來後 `ap_flush`；描述子還沒建時回 `AP_E_NOTREADY`，下次 tick 再試。

### 11.4 DNG FrameRate 規則
- 實際格率 = 72 MHz ÷ (HMAX × VMAX)。
- 實際值在所選格率的 50 ppm 以內 → 寫所選格率。廣播格率寫成 k×1000/1001（29.97 → 30000/1001）。
- 否則 → 寫實際值的最簡分數（例：48.713 → 7200000/147829）。
- 50 ppm 是我定的；見 §11.10 問題 3。

### 11.5 交易（`ap_commit`）
1. 錄影／XMP／MOV 寫入中（RES-Custom `busy()`）→ 不做，記欠帳。
2. 檢查格式＝CinemaDNG、描述子已建、載體是 9 個之一。
3. `apc_build` 算出全部值。寫進不在用的 slot，列依各表基底對齊放好，放大鏡列複製 donor，清 D-cache。
4. LV 在跑就 CamSch1→6、LV_STOP。
5. 關中斷，再檢查一次 busy，翻 `cur`、`active=1`，開中斷。
6. LV_START，CamSch 還原。
- **任何失敗都回原廠**：`active=0`；之前是我們的就重載 LV，所以畫面是原廠。
- 第 5 步發現開始錄影：回原廠、LV 起回、記欠帳。
- 同一個選擇不重提交，不閃。

### 11.6 誰來呼叫 ap_tick（未定）
- QS 容器沒有計時回呼，轉盤停了就沒有 UI 事件。
- 提案：常駐一個低優先權任務（tk_cre_tsk 已實證），每 50 ms `tk_dly_tsk` 一次並呼叫 `ap_tick`。
  - LV stop／start 從非 UI 任務呼叫，isp-lab 經 shell 任務做過幾百次 [驗]。
  - 但 QS 開著、使用者同時操作時有沒有競爭，沒驗過 [推]。
- V1 上機前先不用任務：由 shell 呼叫 `ap_flush`，加上容器的 leave()。見問題 4。

### 11.7 每次提交的閃爍與耗時
- **計算**：unicorn 量 OG 2K 2x3 是 4.54 M 指令，OG 3K 2x2 3.82 M，OG 1K 3x3 4.31 M（含 core_qualities_tol）。
  - 快取別名上約 1 指令／週期，約 5–10 ms。**沒上機量過**；BIN 已是 SL_F_CACHED_OK。
- **LV 黑畫面**，從韌體路徑估 [推]：
  - LV_STOP（FUN_c0428da0）：等幀到齊（穩態 0 ms，最多 20×10 ms）、等通道結束；ch1 在跑時無條件 `dly_tsk(34)`。
  - LV_START（FUN_c0428ab8）：重建 profile、送 PARAM，路徑上沒有 sleep。
  - 同一感光元件模式：約 50–130 ms，3–8 個 LV 幀。
- 待機的 LV 是待機路線（MOV* 表），**不換感光元件模式**。所以 QS 半透明時看得到的是取景範圍（待機可見寬高）與長寬比，**不是**錄影讀出本身（雜訊、RS）。錄影開始才走我們的 entry。見問題 2。
- `commit_us` 會記錄實際耗時，上機時讀它。

### 11.8 測試（`python3 -B -m unittest test_apply`，24 項，約 16 s）
- **Install**：24 站都 claim（4 B、stock 字、EXCL）。veneer 先 publish 才寫站點。有一個 claim 被拒就全部不 arm。arm 了但還沒提交時，每個站點都和沒 hook 的相機逐值相同。
- **Commit**：
  - 7 張表＋REG＋R10 經**韌體自己的查表函式**讀回，與 Python `smc.create` 逐位元組相同。
  - 模式設定 C0321290 加 7 個讀取函式的感光元件寫入，與「同樣的列寫進原廠表、donor id、NOZOOM=0」（isp-lab vmode 路徑）**完全相同**，>150 筆寄存器寫入。
  - picker 的載體、表、CROP。
  - 經 **FUN_c0439d18 實跑** 的 canvas ＝ `isp_formula.row(spec, profile 171)`，+0x30 = 30.0。stock／stills pid 不動，待機 6 pid 只動 +0x20／+0x28。
  - zg／vpro／v32 直接驗。
  - LV 描述子與比例對 `isp_custom.lvout_rules`／`display_diffs`，含一個窄框（SQ）。
  - recrate 與 binfilt：下層是 Python stub。
- **Transaction**：去彈跳、同選擇不閃、錄影中欠帳、提交中開始錄影、8 種失敗都回原廠、兩 id 輪換、LV 沒在跑。
- **Calc（主機）**：6 組 DC×RES 的**每一個** recipe，表、ISP 字與 mask、待機、比例、LV 框、binfilt、DNG 有理數都對 Python 比過。另有 limit_denominator 的平手窮舉，以及 16:9 邊界 ±1%。
- **Mutation**：結果見 `apply/build/mutate.log`。編不過的突變判為無效，不算數。
- **沒測的**：recrate／binpath 的真實下層、真實 LV stop／start、真實待機路線的 picker 呼叫、多執行緒競爭。

### 11.9 fps 到 1000：研究結論與提案
研究由子代理完成，重點已核對；證據在 `research/imaging-hw/notes/HIGH_FRAME_RATE_PATH.md`、`out/decomp/full/blk_c01.c`。

**(a) >99.99 閘門族**
- 全族只看一個值：canvas +0x30（`FUN_c01cec08`：chfps − 99.0 > 0）[驗]。不看格率 enum、mode、pid。
  - 所以「引擎格率」由我們的 canvas hook 決定，跟載體無關。
- 成立時：
  - S2R／R2V／R2Y／Y2Y 改成固定 `dly_tsk(8)` 輪詢，DMA 連續。**1000 fps 一定要走這條**（每幀 1 ms，來不及每幀重設 ISP）[推]。
  - 時脈閘 C0189440 會降到 5/16。**要照 RES-Custom 強制全開**（V1 未搬，待加的 hook）。
  - VD 的 1 s 看門狗被跳過（無害）。
- 會把格率值往下傳的：`FUN_c01cc868` 存 `(int)fps`，`FUN_c01d11e8` 送 `fps×1000` 給 `FUN_c0625e30`。消費者未知，是風險。
- **更正舊筆記**：錄影時關 LV 管線的 `FUN_c03a1558` 用的是另一套 enum。它在 **48／50／59.94 與 100／119.88** 都會觸發，29.97 不會 [驗]。
- **提案**：
  - ≤ 99.99：載體＝原廠 9 個之一，+0x30 照原廠。
  - > 99.99：載體 119.88，+0x30 用固定 > 99 的值（例如 119.88 或真實格率，要上機 A/B），並加回時脈閘 hook。
  - LV 關閉可以另外 hook 掉，不必跟著載體。

**(b) 12-bit 高格率 SSD 36–40 s 自停**
- 停止原因是 RAW 描述子池（96 個，94 可用）用完。描述子只有寫入同步完成才釋放；SSD Standard 每幀同步寫 [驗]。
- 算術 [推]，239.76p 每幀 4.17 ms：
  - 12-bit 1.095 MB 跨 3 個 512 KiB cluster，約 4.33 ms > 4.17 ✗。
  - 10-bit 2 個 cluster，約 3.06 ms ✓。
  - cluster 量化把 1.18× 的資料差放大成 1.5×。
- **1000 fps**：瓶頸是每個檔的固定成本。每幀 CPU 約 0.37 ms，加上每檔 FS 約 0.51 ms，Standard 約 1.5 ms／幀 > 1 ms。
  - **原廠「一幀一 DNG」路徑做不到 1000**。估計上限約 400–600 fps [推]。
- **提案**：
  1. 持續錄影的上限先定在約 400–600，用 SSD Custom 批次、128 KiB cluster、調低批次門檻（同 lossless 修法 0xC0B9E5D8）實測。
  2. **1000 fps 做成「RAM 連拍」**：錄進 RAW 池（class 10 約 742 MB，[[cdng-survives-in-raw-class]]），停錄後再寫卡。幀小時可撐約 0.7–3 s。
  3. 長期：自有 writer，FS 工作與 DMA 重疊（rec-core W1），並擴大描述子池（`cmp #0x60` 多處）。

**(c) 錄影計時顯示錯**
- `FUN_c038c7b8` = round(幀數 ÷ fps)。fps 由載體 enum 經 `C02DB1D8` 換成 double [驗]。
- **改法**：把 0xC038C7D4 的 BL 換成 shim，我們的 entry 生效時在 d0 回真實格率。只有這一個呼叫點。
- 還在用載體秒數的：剩餘時間、7200 s 上限（1000 fps 在 119.88 載體上約真實 863 s 就停）、每幀音訊估算（C03A0DF0、C03A48E8、C03A4B00），以及時間碼（enum 6–8 每 2 幀、9–10 每 4 幀進 1）。

**(d) 還沒搬的、> 59.94 前要補的**：時脈閘、tvmin／angtv／fps1–4（快門角與最慢快門）、計時 shim、writer 政策（4 MiB 批次、hdrcopy）。

### 11.10 V1 第一次上機（照慣例：先問 Bei、廣播相機使用權；錄影中不碰 USB）
要的檔：
- `apply/ap.c`、`ap_calc.c`、`ap.h`，由另一個代理在 QR 完成後併進 slqs.c：
  - `#include "../apply/ap.c"`；
  - st 加 ap_mem，STATE_RESERVE +0x8000；
  - entry 呼叫 `ap_init`；
  - `sq_apply` 呼叫 `ap_request`；
  - leave() 呼叫 `ap_flush`；
  - 新增一個 op 讓 shell 呼叫 `ap_flush`／`ap_status_get`。
- 新 BIN 由 `build_slqs.py` 產生（必須腳本建）；搭配 v4 LOADER.BIN 與 QSContainer v0.2.2；卡上不能有 RES-Custom。

步驟：
1. 備份 LOAD.LOG，記下 Format／Size／Framerate 原值。相機設 CinemaDNG、12-bit、29.97、SSD、HDMI／shell 照 res-lab 規則。
2. 部署並讀回，`poff` 重開。LOAD.LOG 要是 LOADED，claim 數 = 原本 + 24。
3. `mem get` 讀 24 個站點：都是 B／BL，cave 字 = `E51FF004 + veneer`。
4. QS 選 OG 2K、29.97、recipe 12b 2x3。shell 呼叫 `ap_flush`，讀 `ap_status`：result 0、active 1、mode 230／231、`commit_us`。截圖看待機取景／比例。
5. 錄 3 秒（錄影中不碰 USB），停錄等 10 秒。
6. 驗：
   - DNG 2016×1330、DefaultCrop 2000×1320、12-bit、FrameRate；
   - 彩色預覽（先扣黑階再乘白平衡）並肉眼看一張；
   - `0xC343B590` = 230／231（錄完再問模式）；
   - `ap_status` 的 picks／lookups／canvases／recrates > 0。
7. 和 isp-lab 殼路徑同配方的 DNG 比內容統計。
8. 退回：QS 選無效（valid 0）→ 原廠；再錄一段應為原廠 FHD／UHD。

### 11.11 要問 Bei
1. V1 是 **OG 2K 12b 2x3**（OG 3K 沒有 2x3），還是 OG 3K 12b 2x2？
2. 待機時 QS 後面只看得到取景／比例，錄影讀出要等開錄。要不要讓待機也跑我們的讀出（hook 待機路線）？風險：R12 待機來源 ≤ 1710 列，曾凍結過。
3. DNG FrameRate：實際值在 50 ppm 內寫所選值、否則寫實際值，可以嗎？或者改 TIM tail，讓週期精確等於所選格率（RES-Custom solve 的做法；會偏離 core_smc_create 的 TIM）？
4. 去彈跳的時鐘：開一個常駐低優先權任務每 50 ms 呼叫 ap_tick，可以嗎？還是只在 leave() 提交（就失去半透明即時看）？
5. 1000 fps：先接受「持續錄影約 400–600、1000 用 RAM 連拍」？
6. 相機格率設定（載體）不是我們要的時，picker 會退回原廠。要自動換載體嗎？這會寫原廠設定，違反「原廠設定不改」。還是在 QS 顯示「請把格率設成 X」？

## 2026-10-29 Bei 定案（§11 的問題）
- 套用時鐘：不開常駐任務，「修改事件套用」——在 QS 的修改事件（adjust/pick）當下提交；連轉時正在提交就只記最新選擇，提交完再補一次最新的。
- 待機也要跑我們的讀出（Bei：「當然要啊，而且我有測試過很多待機畫面」）；先查 imx410-lab／isp-lab 的待機實測紀錄，處理 >1710 列的凍結風險。
- 1000 fps：持續錄影先到約 400–600；1000 用記憶體連拍（停錄後寫卡）。
- 載體格率：自動改原廠格率設定（選單顯示我們的清單，用戶看不到載體值）。
- 未問、照建議：V1 配方 OG 2K 29.97p 12b 2x3；DNG FrameRate 在所選格率 50 ppm 內寫所選值，否則寫實際值。

## 12. 依 Bei 定案改版（2026-10-29，離線，未上機）

**§12 取代 §11 的這些段落**：§11.3（介面）、§11.6（時鐘）、§11.7 的待機那一段，以及 §11.11 的問題 1–6。其餘照舊。

### 12.1 修改事件套用（ap.h ABI 2）
- **刪掉** `ap_tick`、300 ms 去彈跳和常駐任務的提案。
- `ap_request(mem, &sel)`：在 QS 的 adjust／pick 事件裡直接呼叫，**當下就提交**。
  - 同一個選擇第二次 → `AP_IDLE`，LV 不閃。
  - 提交進行中又來一個請求：只換掉「想要的選擇」，計數 +1，回 `AP_PENDING`。進行中的提交做完後，若想要的已經不同，就把**最新的**再提交一次（最多連續 8 輪）。
  - 錄影中 → `AP_PENDING`，記欠帳。
- `ap_flush(mem)`：leave()、開機還原、停錄之後呼叫，用來還欠帳；錄影中仍不做。
- `struct ap_sel` 加了 `standby` 欄（1 = 待機也跑我們的讀出）。

### 12.2 待機跑我們的讀出
**查到的凍結紀錄 → 處理方式：**

| 紀錄 | 根因 | 這裡怎麼處理 |
|---|---|---|
| isp-lab R12：E1 1:1 預覽、4040 列視窗，錄影凍結兩次（10-28 SQ 2032×4040） | 預覽來源 > 1710 列 | 公式本身會拒絕（core R12）。待機另加閘門：來源 ≤ 2100×1710 |
| ISP_SIZE_RULES 2.10 r71：預覽光柵超出來源 → 花屏、凍結 | 光柵 > 來源 | 閘門：光柵 ≤ 來源；可見 ≤ 2000×1334（原廠待機上限 STANDBY_VIS_MAX） |
| imx410-lab §7：14-bit donor 放進 id 10 後進放大，沒有幀或卡死；全高下 1/4 變黑 | 放大路徑用 v32 把感光元件窗改成 mode 10 的 2022 列 | 我們的 id 一律不寫窗（v32 hook）。放大鍵 MAG\* 一律走原廠 mode 10 |
| imx410-lab §70：每 50–90 組整機凍結一次 | 工具在幀中途停 BUFA0 | 不適用：我們只走韌體自己的 LV 停／啟（res-custom 走原廠模式切換：50 次 0 凍結） |
| isp-lab 10-28 hs1：14-bit 寬幅 870 停不了錄 | R15：14-bit 寬於 4192 要 HMAX 911 | core R15 已強制 |

**作法 [推]：**
- picker 在待機表（0xC0BE4990）的 `MOV*` 鍵上回 `{1, 待機虛擬 pid 76/77, 同一個虛擬 mode, "SLMOV"}`。
- 待機 pid 的 gather 用原廠待機 profile 5 的列當基底。只寫公式的預覽側 14 個字（0x0C/10/1C/20/28/38/58/60/C4/D0/F4/F8/FC/100）和 +0x30。
- 錄影字維持 0，+0x80/+0x84 = 10/10（LV 平面），+0x90 = 0。gs 不把待機 pid 當 raw movie。
- 閘門不過或 `standby=0` → 待機回原廠讀出，只改取景（V1 原本的行為）。
- 測過的組合都在閘門內，因為公式本來就守這些規則；閘門只是第二道防線。
- **沒有原廠前例**：原廠待機都是固定讀出（mode 8 = 3×3 全片幅）。這條路要在 V1 上機時第一個驗，見 §12.7 第 4 步。

### 12.3 時脈閘門（照 RES-Custom CLK0）
- `ap_init` 以 EXCL claim C0189440（Thumb `movw ip,#0x1249`）。
- 只有生效的 slot 引擎格率 > 99 時才改成 `#0xffff`，回原廠或換成慢配方就寫回。
- 每次改都清 D-cache、作廢 I-cache（C000E91C／C000EABC），而且在 LV 停住的時候做。

### 12.4 載體自動設定
- 原生格率 setter：**`C005C0B8(settings, enum, 0)`** [驗]。
  - 它和解析度 setter C005C020 是一對：C005C020 用 vtable +0x1A0，C005C0B8 用 +0x1A4，對應 getter C005C0F0。
  - 韌體 12 個呼叫點都是 `(GET_OBJ(), v, 0)`。
- 時機照 RES-Custom `vrc_apply` 的順序：LV 停 → 翻 slot → setter → 重算格率／位深清單類別（EXCL 0x19/0x1E）→ LV 起。
- 讀回不是載體（被正規化或反灰）→ `AP_E_RATE`，回原廠。
- 載體挑法：**不比所選慢的最慢原廠格率**（50 ppm 容差），超過 119.88 就用 119.88。
  - 例：29.97 → 29.97，48.713 → 50，144 → 119.88。
- 引擎格率 +0x30：119.88 以下照原廠載體值；以上 = 真實格率（float，> 99 走高格率路徑），RES-Custom 240p 實證過。
- 待確認 [推]：
  - setter 會不會自己再觸發一次 LV 重建（多閃一次）。
  - 解析度 UHD／SD 等反灰規則會不會擋載體。RES-Custom 的 frmax／frclass 兩個 gate 還沒搬，擋到時會回 `AP_E_RATE`。

### 12.5 1000 fps：記憶體連拍（只設計，不實作）
- **持續錄影**：先做到約 400–600 fps（§11.9 b 的上限估計），走 SSD Custom 批次、128 KiB cluster、調低批次門檻。
- **連拍**（之後的階段）：
  1. 開錄時 recorder 的 writer 不送卡。幀完成的 hook（BUFA0 完成旗標，韌體自己的停法 §70）把每幀的 RAW 位址記進我們的環。
     - RAW 池約 742 MB（[[cdng-survives-in-raw-class]]）；描述子只有 94 個，所以要用自己的環，不佔描述子。
  2. 容量：1000 fps 要 VMAX ≈ 72e6/(HMAX×1000)。以 HMAX 400 算是 180 列，每幀約 2016×170×1.5 ≈ 0.5 MB，約 1450 幀 ≈ 1.45 s。
  3. 停錄後用自己的檔案寫入器寫 CinemaDNG（IFD 佈局已知，[[cinemadng-ifd-layout]]）。FrameRate = 1000，音訊靜音。
     - 每檔固定成本約 0.5 ms，SSD 約 390 MB/s，1450 幀約 3–5 s。QS 顯示「寫入 N／M」，期間不接受新錄影。
  4. 分段：B1 環＋幀完成 hook（不寫卡，主機讀回驗）→ B2 停錄後寫入器 → B3 介面（連拍長度、寫入進度）。

### 12.6 測試（30 項，約 23 s；42 個突變全部被抓，`apply/build/mutate.log`；兩個等價突變不列，見 MUTANTS 註解）
新增：
- 修改事件立即提交、同選擇不閃。
- 提交中來兩個新選擇 → 只再提交最新的那一個，共 3 次提交，最後生效的是 c。
- 提交中呼叫 `ap_request` 只存起來。
- 錄影中欠帳，`ap_flush` 補上。
- 待機 picker（MOV／MOVAF60／MOVAF30CROP／MOVEIS 回我們的，MAG\* 與原廠相同）。
- 待機 canvas 經 FUN_c0439d18 實跑 = profile 5 列＋預覽 14 字＋30.0。
- gs 對待機 pid 走原廠；`standby=0` 回原廠讀出。
- 144 fps 配方：載體 119.88 由原生 setter 在 LV 停住時寫入，之後重算清單；+0x30 = 真實格率；時脈閘打開、I-cache 作廢；換慢配方或回原廠就寫回。
- setter 拒絕 → `AP_E_RATE` 並回原廠。
- 主機上：
  - `apc_f32` 隨機 5000 組逐位元對 Python；
  - 載體挑法對 Python（固定清單＋隨機 3000 組）；
  - 6 組 DC×RES 的每個 recipe 加驗載體、引擎格率、閘門、待機字遮罩；
  - 2 組 DC×RES 在 144 fps 再跑一遍。

### 12.7 V1 上機（取代 §11.10；卡上的容器是 **QSContainer v0.2.4**）
1. 同 §11.10 的 1–3。claim 數 = 原本 + 27（26 個 hook + 時脈閘，見 §12.9）。
2. 相機先設在別的格率（例如 59.94）。QS 選 OG 2K 29.97 12b 2x3，轉盤當下就套用。
   讀 status：carrier 3、carrier_sets 1，選單格率變成 29.97，fast 0。
3. 連轉幾格：每格都套用一次，LV 閃的次數 ≤ 轉的格數；status 的 commits 符合。
4. **待機**：status 的 standby_picks 要 > 0。截圖看待機畫面：讀出的 FOV、比例、無花屏，觀察 30 s 穩定。
   - 異常就把 `standby=0` 再試一次對照。
   - 凍結就照 [[freeze-postmortem-discipline]]：先讀卡，一次只改一件事。
5. 錄 3 秒，驗收同 §11.10 第 6–8 步。
6. 之後另一輪：144 fps 配方，CLK 字讀回 7CFFF64F，SSD 錄一段。

### 12.8 要 Bei 的
1. 待機讀出是新路徑，原廠沒有前例：可以把 V1 上機第 4 步當成第一個實驗嗎？
2. 原生格率 setter 被反灰規則擋下時（例如某些解析度／媒體不允許 119.88），要不要同時搬 RES-Custom 的 frmax／frclass gate 放寬限制？
3. 停錄之後誰呼叫 `ap_flush`？建議 slqs 在容器的下一個事件或 leave() 呼叫；或者另外掛停錄點（多一個 hook）。

## 2026-10-29 Bei 定案（§12 的問題）
- 待機讀出：V1 上機第 4 步（待機截圖、觀察 30 秒）就是第一個實驗。
- 格率閘門：一起搬 RES-Custom 的 frmax／frclass gate。
- 停錄後補套用：下一個 QS 事件或 leave() 呼叫 ap_flush，不另掛停錄點。

### 12.9 格率閘門（2026-10-30，離線）
- 搬了 RES-Custom 的 frmax 與 frclass 兩個 hook，都是函式中段的 B 型 hook，被蓋掉的那一條指令照原樣補執行（replay）：
  - **frmax**：C00A87E4 `mov r1, r4`。r4 是正規化允許的最快格率。
  - **frclass**：C04A121C `mov r0, r1`。r1 是格率清單的類別。
- **規則**：只在有 slot 生效時放寬，而且只放寬到剛好容得下它的載體。
  - frmax：原值比載體慢 → 改成載體；否則照原值。
  - frclass：原類別的上限已經容得下載體就照原值；否則換成「上限 ≥ 載體」裡最緊的那一類。類別上限表是 RES-Custom 的 class_max。
  - 沒有 slot 生效 → 兩個都照原廠。
- hook 數變成 26 個；claim 數 = 原本 + 27（26 個 hook + 時脈閘）。
- **測試**：31 項。
  - 直接在韌體的兩個站點上跑：沒有 slot 生效、119.88 載體、29.97 載體、回原廠，每個值都對 Python 版的規則。
  - 突變 46 個全部被抓（新增 4 個）。
- 待上機：setter 前後讀選單格率；119.88 在 UHD、SD 上不再被反灰。

## 13. v0.5.1test（2026-10-30，離線）：live 1 之後的修正

**待機閘門。**
- live 1 實測：待機的 picker 走的是 CinemaDNG 路線表 TAB3（FUN_c043b828，params+0x24），不是 MOV 表。所以 §12.2 的閘門原本掛錯路徑，完全沒作用。
- 現在閘門放在 TAB3 分支：
  - 不在錄影、而且選擇不過閘門（或 `standby=0`）→ 待機走原廠路線，`gated` +1；
  - 錄影中一律給我們的 entry；
  - `standby_picks` 改成計「不在錄影時的 TAB3 選取」。
- 會被擋下的（764 個 recipe 掃過）只有 HD 的 12b 3x2 這一族：可見 2000×1671–1686，超過 1334。
- [推] 錄影一開始重新選路線的那一刻，`busy()` 是否已經是 1？如果還是 0，這一族會錄成原廠格式。要上機確認：錄一段 HD 2K 12b 3x2，讀 `0xC343B590`。

**14-bit 經 RWZM：改用 12-bit 容器（Bei 10-30）。**
- `apc_build` 的規則：14-bit AD 而且任一軸 zoom ≠ 1024 或有 CRCT bin → ISP 的 bits 改成 12。結果：
  - 平面碼 (7,7)，DNG 12-bit；
  - 感光元件表照舊是 14-bit AD 讀出；
  - 只有 1:1 的 14-bit 維持 (7,8)。
- 韌體端有沒有實證：isp-lab `20261027-iso14-FHD60_M24-d12` 正好是「14-bit AD 讀出 `14` 6048×3402 + RWZM 1536 + 平面碼 12」。
  - DNG 12-bit、尺寸對、CFA 與 frames 檢查都通過；verdict 只因 `lv_colour` 失敗，而這一項跟平面碼無關 [推]。
  - 所以這個組合可以錄 [M]，但只有這 1 筆、只測了 FHD60 路線。

**BlackLevel。**
- 來源是 FUN_c02ca190 [驗]：感光元件狀態 +0x208（12-bit 尺度，約 256）。它依 `FUN_c02da870(RAW 描述子 +0x24（mode 6）或 +0x08)` 給的位數移位：14 就 <<2。
- 真 14-bit 錄影時，這兩個欄位給的是 12，所以寫成 256；但 tag 0x102 用的是 +0x24 的平面碼 8，所以寫成 14。這就是黑位對不上的原因。
- 新增兩個 BL hook：C02CA1C0、C02CA21C。真 14 的 slot 生效而且被選中時回 14，黑位變成約 1024。
- 12-bit 容器的 recipe 不會被 hook 改，照原本寫 256／4095。資料經 RWZM 截掉低 2 位，1024 → 256，所以自動一致。[推] 上機時讀一張 DNG 的 BlackLevel 與 OB 確認。
- hook 數 26 → 28；claim 數 = 基準 + 29。

**預設配方。**
- defaultPick 的位數那一步改成「實際錄的位數」（頁面 `recBits`，C 版 `rec_bits`）。HD 2K 29.97／59.94／90 都變回 12b 3x3。
- FORMAT 小字與 MB/s 也改用 recBits。ADC 格仍顯示 14bit；QR 的 ad 不變。
- DC WIDTH 轉盤在 6048／5040／4144／3984 上加點線標記。這四個寬度都是 16 的倍數，轉盤本來就轉得到。

**測試。**
- test_apply：33 項，53 個突變全被抓。新增兩項：TAB3 閘門；真 14 的黑位與縮放 14 的 12-bit 容器。
- test_slqs：51 項（新增腳本 18：真 14 對縮放 14、WIDTH 標記），1 項略過（原本就有）。新增 7 個突變全被抓。

## 14. v0.7.2test（2026-10-30，離線）：gated 待機在開錄時凍結

**現象（live2 第 14 項）。** HD 2K 11b 3x2 @19.026：待機 `gated` 613（可見 2000×1671–1686 > 1334，§13 的閘門擋下）。`rec_take.sh 3` 後 USB shell 不回應；卡上有 `A001_266`，所以錄影有開始。

**機制 [推，程式碼驗]。**
- v0.7.1test 的 TAB3 分支：`!ap_busy() && !s->sby` → 原廠路線；`busy()` 時 → 我們的 entry。CinemaDNG 的待機與錄影都問 TAB3（§13），所以同一個鍵的答案**隨 busy() 翻轉**。
- picker 被問得非常頻繁（live2 錄影 A：一次 3 秒錄影 picks +2749，其中約 1200 次在 busy() 時），開錄那一刻 `busy()` 變 1，答案立刻從原廠 entry 變成我們的（virtual pid／mode 230），**沒有經過 commit 的 LV 停→翻 slot→LV 起**。感光元件與 ISP 仍是原廠讀出，而 lookups、recrate、binpath、BlackLevel、mode getter（FUN_c0437078 讀表項 +8）已經回答我們的 mode——同一幀內兩套幾何。停錄時又翻回去。
- RES-Custom 的 picker（`ogc_pick`）從不看 busy()：同一選擇在待機與錄影永遠回同一個 entry。這是 RES-Custom 50 次切換 0 凍結與我們這次凍結的差別。
- 不管韌體在開錄時有沒有重新切模式，結果都是「待機讀出 ≠ 錄影讀出」且沒有交易保護；所以修法不賭是哪一種。

**選擇 (b)＋拒絕的後備，不做 (a)。**
- (a) 讓開錄時可靠地切換：要在開錄路徑裡做 LV 停／啟，沒有任何實證，而且原廠 CinemaDNG 開錄從不換讀出。不做。
- (b) 讓這些配方的待機跑我們的讀出：**1334 這個上限保護的是原廠待機 profile**（全片幅 ÷3 = 2016×1344 → 可見 ≤ 1334，isp_formula `STANDBY_VIS_MAX`、`rl_v3.c` 的 `sb_vis_h`），不是凍結規則。`rl_v3.c` 對錄影預覽的可見高只要求 ≤ 來源；凍結規則是 R12（來源 ≤ 1710 列）與 r71（光柵 ≤ 來源）。而且 CinemaDNG 待機用的就是錄影的 entry，所以「待機可見 1686」與「錄影可見 1686」是同一個畫布——閘門擋待機並沒有保護錄影。
  - 實證：isp-lab 10-28 p5 把這一整族裝進待機再真實錄影，6 筆全過（5/5 檢查點，含 `standby_lv`）：HD 2016×1134／1920×1080／1008×566 的 3x2，11b 與 12b，可見 1671–1686、來源 1702、路徑 E1。`20261028-p5-FHD60_Cdae66428`（HD 2016×1134 3x2 11b）的 `applied.json`：0x28 = 1686、0x10 = 1696、來源 1702；`standby_lv` 與 `rec_lv` 的 Y/std 相同（144.0／39.4），畫面正常。
- (c) 只當後備：閘門（`rok`）不過或 `standby=0` 時，`ap_commit` 回 `AP_E_STANDBY`（−11）、整台回原廠，而不是「待機原廠、錄影我們的」。全部預設 DC×RES 的配方都過 `rok`（`RouteSweepTests`），所以 QS 不需要反灰或顯示原因；之後若有配方不過，它會錄成原廠，不會凍結。

**改了什麼。**
- `ap_calc.c`：`rok = apc_route_ok(...)` = 來源 ≤ 2100×1710、光柵 ≤ 來源、可見寬 ≤ 2000、可見 > 0。`sok`（再加可見 ≤ 1334）只剩 MOV 表待機（基底是原廠待機 profile 5）在用。`apc_out` 尾端加 `rok`。
- `ap.c`：TAB3 分支不再看 busy()（只有 `standby_picks` 仍只計非錄影時）；`lv_stock` 與它在 LV 框／比例 hook 的三個檢查刪掉（不再可能發生）；`ap_commit` 在 `apc_build` 之後檢查 `sel->standby && rok`，否則 `AP_E_STANDBY`、`gated++`；`s->sby = o->sok`（standby 0 已在前面拒絕）。
- v0.7.1test 的 1335→1334 待機裁切（`sclamp`）保留：上機證實過，而且跟 `rok` 無關。
- `ap.h`：`AP_E_STANDBY`；`standby` 欄與 `gated` 的說明。ABI 不變（2）。

**測試（test_apply 52 項）。**
- `test_rec_start_never_changes_the_route`：模擬開錄（錄影旗標升起、不經 commit）：V1 配方、`standby=0`（拒絕，前中後都是原廠）、HD 2K 12b／11b 3x2（可見 1686、來源 1702；前中後都是同一個我們的 entry，待機畫布 = 錄影的字）。
- `test_a_refused_selection_keeps_the_stock_lv_shape_through_rec_start`：拒絕的選擇在待機與錄影中 LV 框、比例都是原廠。
- `RouteSweepTests`：六個預設 DC × `res_list` × 每個配方，`rok` 全過（> 700 筆，含可見 > 1334 的）。
- `CalcTests`／`DcSweepTests`：`rok` 對 Python 規則；MOV 閘門 `sok` 與 1334 裁切仍守著。
- 突變：新增 7 個（拒絕整段拿掉、只看 rok、用 sok 當路線、picker 回到 busy() 判斷、錄影中也計 standby_picks、rok = sok、路線不檢查可見寬）、改 1 個，刪掉 5 個 `lv_stock` 的（程式碼已不存在）與 1 個變等價的（`s->sby` 的 standby 條件）。

**上機（v0.7.2test 清單第 14 項）**：先只看待機 30 s（gated 0、standby_picks 增加、可見 2000×1686 無花屏），再錄 3 秒；錄影中與錄影後 `0xC343B590` 相同。

## 15. v0.7.3test（2026-10-30）：裁切後 LV 比例吸附

live3 已證實感光元件有裁切，但部分高度／寬度在 LCD 仍被拉成 3:2 或16:9。舊測試只跑比例getter的8 bytes，沒有執行後面的整數fit。

**原生原因與修正。** `C02F4410` 先依 `round(9a)==16`／`round(2a)==3` 把比例吸附成16:9／3:2；W71C1 v4在 `C0306DB0` 更早經過一次原廠比例分類器。
新增兩個宣告過claim的hook，沿用原安裝、快取publication及loader還原流程：

- `H_FIT @ C02F455C`（原字 `E300EE04`，K_MID）：僅當 active非16:9的live slot、非播放，而且原始param2（r11）正是本slot的`asp`指標時，還原r6/r7。**return0重播movw lr**，再走原廠矩形算術；不複製fit、不改全域round或分類器。相同數值的外部pair不取得此權限。
- `H_ASP3 @ C0306DB0`（原字 `EBFF50E2`，K_BL）：只在與既有ASP1/2相同的live gate下回enum9，下一個原生getter取本slot比例；inactive或播放完整執行原分類器。

兩個hook append於既有索引之後，38 hooks＋clock共39 claims（`00000027`）；state仍在AP_MEM_BYTES內，AP ABI 2／QS API 6不變。
配方、sensor／ISP列、錄影資料與設定格式均未改。候選只換SensorLab BIN，沿用原QSContainer與loader／AutoRun。

**離線證據。** `apply/test_lv_fit.py`：原廠真ROM特徵與數學函式全部執行、未知程式／寫入拒絕；8:5舊產品RED（1620×1080），候選GREEN（1620×1012）。
另有8組live3真配方（11-bit 3x2、30.018p，key21／HMAX330／VMAX7269）、unrelated pointer／inactive／pb.active／pbc保護。
5個隔離來源突變全被抓：移除比例還原、指標守衛、兩個播放守衛、跳過displaced movw。證據在 `validation/2026-10-30-lv-fit-offline/`。
`test_lv_routes.py`執行真v4 classifier/getter兩個BL；只保留FIT、拿掉ASP3的反例會失敗，證明兩處均有必要。
`test_lv_outer.py`區分原生串流`C02F4010→C02F3E30→v2/v4`與外部圖片提交`C02F4098→C02F3ED0→v3/v5`；後者非空source不再次fit。metadata／UI predicate是明示fixture，不能當成已讀到實機當時描述子。

**比例更正。** 不能用DC寬高比取代公式產出的slot pair；寬5040／5008分別為840:671／1117:893，仍在3:2吸附區，4800為800:671才脫離。這與LV晚於QS換框相符。
**回歸結果。** fast72項＋core PASS；prelive471個工作中的非設定測試、core與285組突變工作通過。原prelive的6個設定error都是新版本fixture缺檔，依測試README規則新增v0.7.3預設BIN後，設定遷移8項重跑全過（含真loader還原、損壞記錄拒絕、原設定不變）；沒有修改測試斷言或覆寫舊fixture。
晚加入的outer4項另跑PASS，清單主機9項PASS；保留一項既有PageStrip skip。原失敗prelive報告保留，結果合併於 `validation/20261030-lv-aspect-fix/verification.json`，不把原報告改成PASS。
**授權上機結果：未驗收，已回退。** 使用新鮮原卡記錄建置的候選`811b4473…`整檔讀回一致，重開後39 claims／init0；以原11-bit3x2／19.026p（HMAX330／VMAX11468）跑高度3800／3500及寬5088／5008／4800，全部active1、result0、gated0、refusals0，無凍結。每點拍QS及關QS等8s後的LV。

但返回截圖不符合乾淨置中畫框：高度3800／3500每643／592列重複，連AF圓／QS焦點框也回捲；寬5088／5008／4800的有效畫面為860／852／812px、均從x0起，僅右側黑。尺寸接近本次19.026p的native預期，**不足以判定LCD實際scanout正常，也不能單憑SS推定LCD同樣損壞**。下一步須追fit後descriptor至最終顯示與原生CAPTURE的來源尺寸／stride；現有單元測試沒有執行這段。

還原原v0.7.2test並獨立標準reboot，fresh LOAD.LOG37 claims／init0、CINE待機active0；SensorLab／QSC／loader／AutoRun四個完整卡檔與測試前備份相同，63個resident設定字完全相同。未錄影或回放；未測實體電源。證據在`validation/20261030-lv-aspect-fix/live/LOG.md`、`screenshot-review.json`、`final-verification.json`。候選留存供離線追查，不提升為實機通過版本。

**實體LCD無法觀看後的離線追查。** 使用者回覆「現在看不到相機」，沒有再操作相機。補齊真CAPTUREON→GUI→RecMgr screenshot事件xref，8項原生fixture通過。追到`C03833B8`以`C0388668`的固定1024×682建SS配置，而`C00EAD70→C00EB290→C00EAEF8`另讀當前display W/H並使用動態clear長度／stride；`C042EAD0/C042EC90`交JPEG的描述仍為固定1024×682及同一buffer。1項native writeback測試內11組宣告尺寸已重現此不一致，沒有geometry stub，但未執行DMA或JPEG引擎、未讀得實機當時getter與direct/intermediate分支，所以不能宣稱已重現RGB回捲全部成因或證明LCD正常。

另補3項fit→直接`C00E9C20` packet producer測試，6組真配方幾何×2個packet layer ID保持source／完整尺寸與置中origin；layer在fit後指定，沒有consumer隔離證據。13張圖片亦排除單一全域offset／compact-stride模型。上述測試均獨立重跑；產品程式未改。新證據、limits與下一個精確接點見`validation/20261030-lv-aspect-fix/offline-capture/README.md`。


## 16. v0.7.4test（2026-11-01）：保留RGB／QS／menu的原生比例

§15把W v4當作liveview路徑並增加H_ASP3的判斷已被實機回報與原生建構器回歸推翻。RGB bitmap由C03078E0→C0307EA8→C02F3DC8建立kind3/4，會進W v4；YUV由C0307810→C0307E08→C02F3D10建立kind0/1，進W v2。H_ASP3先把RGB請求導向本slot比例，後面的指標守衛無法區分被錯誤導入的請求。移除此hook及claim，保留YUV ASP1/2與H_FIT。這不是更改全域畫布或關閉所有比例修正。

新增真ROM建構器／分派反例：舊版8個RGB子案例失敗、隔離移除後通過，YUV仍按slot比例fit；同步修正舊測試「v4也必須跟sensor裁切」的錯誤契約。37 hooks＋clock＝38 claims，ABI不變。完整回歸94項及642組三路fit通過，實體LCD仍待使用者手動驗收。來源diff、原始失敗報告與限制見[UI圖層範圍驗證](../validation/20261101-ui-layer-scope/README.md)。

## 17. v0.7.5test：YUV LCD 3:2分支（2026-11-01）

v0.7.4使用者確認UI正常、原本LV問題仍在。補跑原生W v2 predicates後，+23C=1的明示狀態會走C0306E70的enum2，而非已改的C0306EA0／C0306EEC。新增H_YUV32於該MOV指令，用active slot比例；is169時必須取原廠enum3（H_RATIO只在非is169時提供enum9），inactive／pb.active／pb.pbc仍取原生enum2。RGB分類器不改。38 hooks＋clock=39，ABI2／API6。

離線：98 tests、642選擇／3852 fit案例PASS。v0.7.4在同一分支測試失敗2個子案例，移除新播放守衛的隔離副本亦失敗2個子案例；均0errors。ROM predicates／getter／fit真正執行，邏輯狀態與實體顯示參數仍是fixture，未斷言使用者現場的分支。此輪無相機操作，交付預設設定版由使用者測LCD。詳見[本輪證據](../validation/20261101-yuv-32-branch/README.md)。
