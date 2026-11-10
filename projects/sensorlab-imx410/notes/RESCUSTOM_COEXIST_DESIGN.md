# SensorLab 與 RES-Custom 共存：SensorLab 改當產生器（設計草稿，2026-11-07）

狀態：**只有設計，未實作、未上機**。Bei：「筆記吧 之後再做」。
證據等級：[驗] 讀過程式／資料／上機紀錄；[推] 推論待確認。

> ⚠ 這推翻 10-29 的定案「SensorLab 不要求 RES-Custom 載入；兩者永遠不同時啟用」（`APPLY_DESIGN.md` §0）。
> 開工前要先請 Bei 回答 §6 的三個問題。

## 1. Bei 的需求（2026-11-07 原話整理）

- 原廠選單維持現有的 **RES-Custom 列＋原廠解析度**。
- 在 **解析度、DC 裁切、fps** 三個清單各加一列 `Sensor Lab`。
- 選到 `Sensor Lab`：選單**不**換成現在 SensorLab 的選單，而是**跳到 QS**（像現在 SensorLab 的 CUSTOM → 子 QS），進入 SensorLab 模式。
- 在選單切回 RES-Custom 或原廠選項：退出 SensorLab 模式，**QS 也復原**成原廠。

## 2. 現況：為什麼不能同卡

- SensorLab 的套用部分（`apply/ap.c`）是把 RES-Custom 的虛擬表技術搬進自己的 sup [驗 `APPLY_DESIGN.md` §0–2]。
- 兩者掛同一批 `SL_EXCL` 站點，同卡時後載入的整個被拒 [驗 `APPLY_DESIGN.md` §2「找索引 hook 與別的 sup 衝突」]。
- 重疊的站點 [驗 `ap.c` 站點表與 `APPLY_DESIGN.md` §1 表]：
  - 找索引 ×7＋R10：`C0320BA0/0B38/0E90/0F60/0EF8/0C00`、`C0326DB8`、`C031FFA0`
  - 放大鏡：`C031AC38`、`C031ACD8`、`C031B660`、`C03249A0`
  - picker `C043CCF8`、vpro `C043A18C`、canvas `C043A19C`、gs `C03A6DD8`、recrate `C00C9BD0`
  - binfilt：`C0325228`、`C032DDF0`、`C032DE70`
  - LV／比例：`C0437E98`、`C0306EA0`、`C0306EEC`、`C02DAFA0`
  - 格率清單：frmax `C00A87E4`、frclass `C04A121C`（RES-Custom 對應的是 `frmax`／`frclass`，位置是否完全相同 [推]，實作前逐字比對）
- SensorLab 獨有、RES-Custom 沒掛的（不衝突，但多數會判斷「選中的是不是自己的 entry」）：
  - 回放：pbtag、pbname、dscale、pbw、pbh、pbres、pbprep1/2、pbheader、pbring、pbraw14、pbown
  - LV 適配：fit `C02F455C`、W v2 `C0306E70/0F28`
  - 其他：blk6/blk `C02CA1C0/21C`、RAW 讀取格式退路 `C01CE450`、defc、首幀修正 ffarm/fffix/ffdone、resync ×2

## 3. 方向：RES-Custom 擁有站點，SensorLab 當產生器

RES-Custom 已經有產生器接口（Virtual RCD ABI 2，`open-gate/build/res-custom/VIRTUAL_RCD.md`）[驗]：

- 套用者（RES-Custom consumer）是唯一擁有虛擬表站點的 sup。它管解析度列、共用動態列、格率 CSV 與反灰，負責套用交易：停 LV → 核對 busy → 提交 → 原生 setter → 重啟 LV。
- 產生器 `REGISTER` 後，`APPLY` 時 consumer 呼叫產生器的 `build()` 取得一份 RCD1，驗證後套用。
- Res Lab 已經用這條路上機，在共用動態列顯示為「RES-Lab」。

SensorLab 拆掉自己的虛擬表 hook，改成：

1. `sup_entry` 向 consumer `REGISTER`（找 consumer 用 `vrc_find`；要 consumer 先載入）。
2. QS 關閉時（Bei 10-29 定案的套用時機），把目前的選擇編成 RCD 交給 consumer `APPLY`。
3. 回放、LV 適配、首幀修正這些獨有 hook 可以留在 SensorLab。但它們要改問 consumer「目前生效的是不是我的配方、第幾代」，不能再看自己的 picker 狀態 [推，要定一個查詢 API]。

`RESCUSTOM_EXPORT_RESEARCH.md`（10-29）已確認 [驗]：

- RCD 的「donor＋覆寫」裝得下 SensorLab 的 8 張表整列：244 筆，上限 256。
- ISP 公式 31 字裡有 28 字對得上 `SEC_CANVAS`。缺的 3 個是 `+0x80/+0x84`（平面碼，14-bit 要用）和 `+0xB0`（高速格率旗標，v0.7.11）。
- 對準的版本要是**已發布的 RES-Custom v0.1.4（core 4）**；core 5 是 Bei 10-22 定不發布的重構。

## 4. 選單與 QS 流程

| 步驟 | 做什麼 | 依據 |
|---|---|---|
| 1 | 解析度、DC 裁切、fps 三個清單各加一列 `Sensor Lab`；原廠列與 RES-Custom 列不動 | consumer 已擁有解析度與格率 CSV [驗]；DC 裁切 popup 不是 CSV，是 3 個固定子物件，要複製子物件 [驗 `MENU_DESIGN.md` §1] |
| 2 | 選到 `Sensor Lab` → 跳 QS | B2_5（解析度、fps 所在頁）有原廠 `CM_TransitionFlag == 2 → "QS"` 事件；MainB2（DC 裁切所在頁）**沒有**，要另外處理 [驗 `MENU_DESIGN.md` §1] |
| 3 | QS 容器開替換模式，顯示 SensorLab 的 QS | 容器已有 replace mode、子 QS API [驗 `qs-container/qsct.c`] |
| 4 | QS 關閉 → SensorLab `build()` → consumer `APPLY` | ABI 2 [驗] |
| 5 | 選單切回原廠或 RES-Custom 列 → 原生 setter；consumer 還原虛擬表；SensorLab 標未啟用；容器關替換模式，QS 回原廠 | consumer「切回普通解析度後恢復」[驗 `VIRTUAL_RCD.md`]；SensorLab 側要新增「退出」路徑 [推] |

原則照舊：原廠設定區只存原廠合法值（backing value），SensorLab 的選擇存在自己的 BIN。

### 4.1 替代 UI：一個 Sensor Lab 開關（11-07 討論）

- **重開機才生效的開關沒有意義**：SupManager 本來就能停用 sup 再重開（Bei 11-07）。所以共存的價值只在「不重開機即時切換」。
- 即時切換不管 UI 是「三個清單加列」還是「一個開關」，底層都要 §3 的產生器改造：兩者同時常駐，hook 只能有一個主人。
- 開關版只省掉選單那部分：不用在三個清單加列，也避開 MainB2 沒有跳 QS 事件的問題。開關 ON = 進 SensorLab 模式（容器替換 QS、套用目前配方）；OFF = 退出、QS 復原、consumer 還原原廠或 RES-Custom 的列。
- 開關放哪（fpSup 頁一列或別處）未定。

## 5. RES-Custom consumer 要補的

| 缺口 | 說明 |
|---|---|
| **14-bit** | consumer 只收 8／10／12-bit（`SEC_BITDEPTH` mask 只有 3 bit，「RAW14 尚未接入 consumer」[驗]）。SensorLab 的真 14-bit 1:1 進不去 |
| **canvas 缺的 3 字** | `+0x80/+0x84` 平面碼、`+0xB0` 高速格率旗標。要新 section |
| **整列寫法** | 可以先用覆寫湊（244/256）；長遠可加「整列」section 省掉 donor 比對 |
| **SensorLab 修過的 bug 搬進 consumer** | `lk_reg` 找不到時回 0xFFFFFFFF，會讀 base−0x288（RES-Custom P5）；高速格率 `+0xB0`；錄影預覽取樣（v0.7.12）；待機門檻（source ≤1710 列、可見寬 ≤2000，v0.7.1 凍結的教訓）。這些本來就是 consumer 也該修的 |
| **列數** | 目前一個共用動態列、總共最多 6 列。`Sensor Lab` 要自己一列，或跟 Res Lab 共用動態列（§6 問題 2） |
| **相容規則** | 每個新 section 都標 required、提高 `MINCORE`，舊 consumer 明確拒絕，不能靜默忽略 |
| **查詢 API** | 給產生器問「生效中的是不是我的配方、第幾代」，讓 SensorLab 的回放／首幀 hook 能判斷 |

## 6. 開工前要 Bei 決定

1. **站點的主人**
   - 建議：**RES-Custom consumer**（已發布、上機過，選單和格率反灰都做好，HDMI RAW 套用器也規劃在那裡）。
   - 反過來：用 SensorLab 的 `ap.c` 取代 consumer 也可以，但要重寫 RCD 讀取、選單和格率處理，等於重做一個 RES-Custom。
2. **UI**：三個清單各加一列（§4，`Sensor Lab` 列獨立或跟 Res Lab 共用動態列），還是一個即時開關（§4.1）？
3. **14-bit 一定要保留嗎？** 要的話，第一步就是 consumer 支援 RAW14 和平面碼 section。

## 7. 跟 HDMI RAW 的關係

- 站點主人定成 consumer 後，HDMI RAW 套用器就照 `research/interfaces/notes/HDMI_RAW.md` §7 放進 consumer，當第二個輸出目標。
- 這等於回答了 `projects/hdmi-raw-lab/notes/PHASE1_DESIGN.md` 的共存問題 3，選的是 (c) 的變形：輸出目標在 consumer，SensorLab 和 Res Lab 都只產生配方。
- HDMI-RAW-Lab v0.1.0test 只用原廠模式、3 個不重疊的 hook，跟本設計不衝突。之後可以併進 consumer，或維持獨立。

## 8. 建議順序（之後做時）

1. Bei 回答 §6。
2. consumer：查詢 API＋SensorLab 修過的 bug（不改 RCD 格式，單獨可發）。
3. consumer：新 section（canvas 3 字；14-bit 若要）＋`MINCORE`。
4. SensorLab：拆掉重疊 hook，改成產生器，選單三列＋跳 QS＋退出路徑。
5. 離線：unicorn 跑兩個 BIN 同卡，加上 Res Lab，三者都載入；切換原廠 → RES-Custom → Sensor Lab → 原廠，每一步核對虛擬表、QS、設定區。
6. 上機。
