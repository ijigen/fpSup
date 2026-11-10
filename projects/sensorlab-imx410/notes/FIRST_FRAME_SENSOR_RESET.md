# 首幀錯列：sensor 清除／重同步路徑調查

## 2026-11-04 上機結果複核（本次只讀封存資料）

使用者回報測試未改善。重新核對 v0.7.27～29 的 DNG、原始 bus 與 trace words，**這次模式切換後的原廠 v27 暫停／恢復沒有解決首幀錯列**。詳見 [本輪複核](../validation/20261104-resync-review/README.md)。以下覆蓋下方 11-03 的「未上機／缺少 completion 對照」狀態；下方原廠流程研究仍保留。

- **v0.7.28：9/10 錯列，但 resync 未執行。** 不能拿它判斷 resync 效力。**v0.7.29：10/10 bus 都有完整 v27 暫停／恢復寫入，仍有 8/10 錯列**，不能宣稱改善。只測了這個操作位置與序列，不是排除所有 sensor／receiver 同步機制。
- **完成端證據已補上。** 共 16 段有原始 trace（27：5；28：10；29：僅 t01）。64 組完成／交給 writer 的記錄，raster 與抽查的 160 bytes 都相同；16 個首幀 DNG 的相同區域也與完成端一致。異常首幀在 BUFA1 completion callback 時，row0 尾 64 B 的每段專屬標記仍在，但 row0 頭 32 B 已變化。因此是「首列局部未覆寫」，不能說「整列完全沒寫」，也不是全幀雜湊或線路上 sensor 封包證據。
- **並非只在垂直 1×2 發生。** v27 的水平 2×1（12h2）也有 1/5 錯列；其中 t02 trace 的 `12v2` tag 誤植，需以實際配方／bus 核對。2×2 那段沒有走到此 BUFA1 arm hook，不能沿用「已證實相同 BUFA1 對照」的說法。
- **TG 行欄位不是無效資料。** `30100590` 應依原廠 `C0125770` 解成 `(raw >> 16) & 0x3FFF`。v28 的 9 個異常首幀完成時讀到 2120，正常 t10 是 2121；v27 的異常／正常首幀分別為 4161／4162。後續幀也有少數 2120、2122、2123，故這是啟動／完成相位的線索，不能當成逐幀正誤判準，不能直接推成 sensor 少送一列。
- **實際時間線取代舊估算。** v29 t01 的恢復 `00CA=1` 到 DMA arm 還有 **760.390 ms**；這不是緊貼 arm 的重新同步試驗。`0011=1` 到 arm，在有 trace 的 v27／28 約 472～506 ms、v29 t01 約 806 ms；下方 137～168 ms／第 4～5 sensor 幀只是舊路徑估算，不再作量測依據。

後續優先核對**第一列局部寫入、接收裁切邊界及 DMA 首列計數**。既有離線 MMIO 差異中的 12-pixel 起點跨界仍只是候選，尚無單變量實拍。暫不據此新增 reset／flush 寫入或宣稱已修復。本次未操作相機、未改產品程式、未產生新 BIN。

---

## 2026-11-03 原研究（歷史狀態）

本輪時間：2026-11-03，離線研究。使用者重新要求調查 sensor 端，取代先前「不再查 sensor 根因」的工作決定。未改產品程式、未產生新測試 BIN、未操作相機。

## 結論

**找到了比現有 `0011=0→1` 更完整的原廠 sensor 暫停／恢復流程，但沒有找到可確證的 IMX410「清空影像 FIFO／緩存」指令。**

值得研究的是「完整停止輸出，再協調 sensor、時序產生器及接收端重新同步」，而不是先猜一個 reset 位元。現有證據仍不能區分 sensor 送出的開頭有缺損，或 SoC 接收／裁切／DMA 在啟動時多算了一列；也不能把第一個**錄製幀**直接稱作重啟後的第一個 **sensor 幀**。

`FIRST_FRAME_REPAIR.md` 的 v0.7.26test 是資料端偵測與避開異常的候選，不是 sensor 根因修正；其離線通過不等於相機已修復。

## 1. 先修正兩個推論

### 1.1 `0011` 不是已證實的完整 reset

fp 原廠 `XC_ImageSensorIMX410::v16 @ C0324F40` 僅連續呼叫兩次寫入：`0011=0`、`0011=1`。原始 ARM 指令與反編譯相符，兩次寫入之間沒有額外等待、sensor 讀回或完成確認（共用 SPI writer 仍有固定忙等）。現有程式證據只能稱它為**切換脈衝／模式啟動相關控制**；不能據此宣稱它清掉 sensor FIFO、重設所有列計數器，或完成一次完整 standby。

接收端的另一個流程是 `v21 @ C0325078` → `C0128D60(1,0)`。它操作 SoC link 控制，不寫 sensor 暫存器，必須和 `0011` 分開看。vtable 的 `+0x5C` 實際指向 v21；`v23 @ C03250B0` 是純數值計算，不是 link reset。

### 1.2 `041F=0E／05E2=01` 不是錯列的必要條件

重讀全部 35 段封存 bus 紀錄（不是新增上機）：

| 項目 | 結果 |
|---|---|
| `0011=1` 前最後一次 `041F`、`05E2` 寫值 | 35/35 均為 `00／00` |
| 啟動後 200 ms 內 | 兩個暫存器各 105 次寫入，全部為 `00` |
| 其中自訂 1×2 | 26 段，23 段仍錯列、3 段正常 |
| `0790` | 自訂 26 段為 `01`，原廠 9 段為 `00`；該時間窗內沒有再次寫入 |

原廠 `v10 @ C0323818` 的增益分支會重寫 `041F／05E2`；不能把 REG 表的靜態值當成整段錄影的有效模式特徵。`0790` 仍有相關性，但沒有充分性或必要性的單獨實驗，不能稱作 reset 位元。

可重跑：[audit_bus_boundary.py](../validation/20261103-sensor-reset-research/audit_bus_boundary.py)，輸出 [bus_boundary.json](../validation/20261103-sensor-reset-research/bus_boundary.json)，含每份來源 SHA-256。它核對的是韌體送出的命令，不是 sensor 內部何時鎖存。

## 2. fp 原廠有哪些候選控制

| 控制 | 程式直接支持的作用 | 對此次問題的判斷 |
|---|---|---|
| `0011=0→1`，v16 | 每次模式切換使用的兩筆寫入 | 已在好／壞 take 都執行；重送同樣脈衝沒有已知根據 |
| `0000` bit1 + `00CA／00C6／00C5` + GPIO `0x544`，v27 | 完整配套的暫停／恢復序列 | 最有根據的 sensor 端候選流程；不是已證實的 FIFO clear |
| `0002` bit0，v15 | 原廠曝光準備／結束路徑會切換 | 沒有證據可命名為通用 group hold 或 flush，暫不選它 |
| `00D1–00D3` 在 `0x2FFFA／0x2FFFB` 間切換 | 每次 mode set 尾端的值改變 | 內部用途未解；不能由「會切換」推定為清緩存 |
| `00CE` | fp mode set 寫 0；DJI 同族驅動函式標作 ECC/CRC 設定 | 不應拿作 flush 猜測寫入 |
| `C0630FA0` 的 `0x30000804` bit1 脈衝 | SoC BUFA 路徑 reset | 不是 sensor 暫存器，也不是 sensor 清除證據 |
| `C000E91C`／清 RAW DRAM | CPU cache 維護／主記憶體處理 | 不能修正 sensor 或接收端的列對齊；填黑首列也補不回尾列 |

### 原廠 v27 的實際順序

`XC_ImageSensorIMX410::v27 @ C0325110`，只在 `C0125CA8() > 15000` 時執行；該回傳值是目前幀週期的微秒數。這個 guard 不能跳過，高幀率下直接呼叫可能完全不動作。

- 暫停：`00CA=0` → 等 1 ms → `0000=shadow|2` 並更新 shadow → `00C6=1` → `00C5=0x11` → 配套 GPIO 動作。
- 恢復：`0000=shadow&0xFD` 並更新 shadow → 配套 GPIO 動作 → 等 12 ms → `00C6=0` → `00C5=0` → `00CA=1` → 等 1 ms → 呼叫原廠 link 流程。

這是**程式順序的紀錄，不是可直接送出的相機操作配方**。它原本在長曝光／曝光結束路徑使用，普通 mode set 沒有用它包住整張 REG 表。必須另外確認 call context、AE、TG、receiver、buffer 所有權與恢復配對。特別是 `0000` 有韌體 shadow；初始化實際寫 `04`，shadow 卻設為 `00`，它不是完整的硬體讀回值。不能把其他廠的 `old|bit`／`old&~bit` 直接換進 fp，也不能只直寫 sensor 而忽略原廠 shadow。

另一個值得驗證的時序差異：161 筆 mode-table 寫入中，`00C5=0／00C6=0／00CA=1` 在第 32～34 筆，早於後面的 1×2 列配對設定。這**不等於已找到 premature start**：原廠先停 TG，而且尚未知道 sensor 在沒有 XHS/XVS 時如何鎖存這些值。它只是完整 standby 方案需要核對的具體位置。

## 3. 其他 IMX410 驅動提供的線索

### Z CAM

同族驅動實作 `0000` bit0 的 standby／cancel，但有一個名稱類似的 exported cancel 函式實際是空函式。不能只看符號名稱便認為平台每次切模式都有完整 standby。

表內有 1×2 的 MODE21/22，但它們沒有被 59 個對外模式選用。這些表可供比對，**不能當作「其他相機已證實同一組 1×2 轉場正常」**。

### DJI

同族驅動可見 XCLR 與 sensor 輸出控制、外部 TG 啟動、SLVS 接收器狀態等待相互配合的流程，支持「重同步是一整套操作」這個研究方向。它沒有提供可抽出來單獨用的 image-buffer flush。其 `00CE=2` 位於 `_imx410_set_ecc_crc`，是傳輸格式相關設定，不能搬到 fp 作為 reset。

不同封裝／客製變種、平台時序與表內容可能不同；不移植整段 DJI/Z CAM 初始化 bytes。Sony 公開的 IMX410CQK flyer 也沒有提供 reset／FIFO 清除 register map。公開資料的查證與限制見 [public_sources.md](../validation/20261103-sensor-reset-research/public_sources.md)。

## 4. 仍不能排除的接收端機制

先前 `FIRST_FRAME_DMA_START_RE.md` 依 bus 與程式路徑估算，錄影 DMA 可能到 `0011` 後約 137～168 ms 才啟動，約為 29.97 fps 下的第 4～5 幀。這是**推算**，缺少同一 take 的 DMA arm 時戳，不能當成精確量測。

如果缺損只在 sensor 重新啟動後第一幀，為什麼較晚開啟錄影 DMA 的第一幀仍壞，必須有可驗證的解釋。相反地，模式相關 line-valid／crop／DMA 啟動瞬間錯位能解釋「只在第一個錄製幀發生」，也需要直接證據。

原廠 UHD 使用相同 BUFA1、相同啟動碼而正常，排除了「只要這條路就必定錯」；沒有排除「這條路與自訂模式的啟動時序互相影響」。同理，放慢 HMAX 與改 RWZM 比例未消除問題，不代表所有同步相位都已排除。

首列的 JPEG／舊暗場內容強烈支持主記憶體未完整更新或後來被覆回；sensor 本身不會產生相機 Lossless 的 JPEG tile。**觸發原因仍可能在 sensor，但殘留內容的來源不能叫作 sensor 裡的 JPEG 緩存。**

目前筆記對「DMA 從頭沒寫」使用了很強的定語，但本輪找到的原始資料主要是 DNG、sensor 命令紀錄及離線程式追蹤。尚未找到同一 frame id 在最早 DMA completion 與後續寫檔前的雙點內容對照；v0.7.26 的 sentinel 也仍未上機。故本輪採保守結論，不把這個邊界補成已量測事實。

## 5. 下一次實驗應能回答什麼

以下是研究計畫，沒有執行或新增常駐 observer。

> 2026-11-04：第 1 步已做成 v0.7.27test 的唯讀追蹤（離線通過、未上機），讀法與判讀見 [validation/20261104-first-frame-trace](../validation/20261104-first-frame-trace/README.md)。
> 2026-11-04：選項 B（原廠 v27 暫停／恢復＋link resync，開錄一次）做成 v0.7.28test，離線通過、未上機：[validation/20261104-first-frame-resync](../validation/20261104-first-frame-resync/README.md)。

1. **先對齊時間與資料邊界。** 在既有原廠回呼內做有限長度紀錄：TG frame/line counter、DMA arm/complete 時戳、frame id、目的位址與 raster、列長，以及首／尾列少量 bytes。比較同一幀在最早 completion 和交給 writer 前是否相同。不能用停錄後 snapshot 代替，也不新增全幅 CPU 複製。
2. **分開改 sensor 邊界和 DMA 邊界。** 固定 sensor 設定，將 DMA 啟動移到已確認的完整 frame boundary；另一個獨立實驗才改成經審核的 fp-native standby／resume＋同步。不可一次把 reset、延遲、crop、HMAX 全改了才看紫色消失。
3. **保留對照。** 使用相同 12v2 設定做原始流程、候選流程與撤回流程；同時保留正常的原廠 UHD／2×2。逐幀核對 row0、全圖位移、尾列、實際幀數與音訊時間。候選若只把第一幀丟掉或把異常藏成黑列，不能算 sensor 問題修復。

判讀：

| 結果 | 可以支持的結論 | 仍不能直接推出 |
|---|---|---|
| completion 正常，writer 前才異常 | 後段交接／cache／buffer 為優先調查點 | sensor reset 可修復 |
| sensor 序列不變，只調 DMA 對齊就穩定 | 啟動邊界或接收管線為較強候選 | 已解出所有 sensor 內部狀態 |
| 完整 standby＋同步才穩定 | 狀態／重同步流程有關 | 一定是 sensor FIFO，因接收端也被重新同步 |
| 能讀到原始 SLVS 封包且第一個有效 line 本身短缺 | sensor／連線上游有直接證據 | 任何猜測的 flush bit 都安全有效 |

## 證據索引

- [原廠流程與 ARM 核對](../validation/20261103-sensor-reset-research/native_trace.md)
- [跨廠驅動核對](../validation/20261103-sensor-reset-research/cross_vendor.md)
- [既有證據邊界與時間線](../validation/20261103-sensor-reset-research/evidence_boundary.md)
- [公開第一手資料](../validation/20261103-sensor-reset-research/public_sources.md)
- [既有 DMA 啟動追蹤](FIRST_FRAME_DMA_START_RE.md)、[首幀資料端處理](FIRST_FRAME_REPAIR.md)

本輪不宣稱修復成功；新增的是可重查的候選流程、被排除的暫存器推論，以及能辨別 sensor／接收端的實驗條件。
