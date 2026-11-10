# 首幀紫屏：離線複核，2026-11-03

狀態：找到新的 RAW 位元組證據；根因未定，未改產品程式、未上機、未製作測試版。
輸入為旁邊 `20261103-first-frame-purple/` 的封存檔，沒有重錄或改寫原始證據。

## 1. 新證據：異常第一列含 JPEG 結構

`audit_rows.py` 重查全部 35 組 bus/tNN 前兩幀，結果保存於 `row0-audit.json`，含 70 個 DNG 的 SHA-256、原始位元組、TIFF 幾何、位移誤差與尾列對照。

| 組別 | 組數 | 有效影像位移 | 第 0 列 |
|---|---:|---|---|
| 原廠 106 | 9 | 0 | 正常 |
| 自訂 1×2，正常首幀 | 3 | 0 | 正常 |
| 自訂 1×2，異常首幀 | 23 | +1 列 | 全部異常；13 組有結構完整的 DHT/SOS |

例：`../20261103-first-frame-purple/bus/t34/A001_049_20261103_000001.DNG`：

- RAW12，3024×2010，Compression=1，StripOffsets=80896；每列 4536 bytes。
- 第 0 列相對 +18、+46 有 `FF C4` DHT（長度欄位各 26），+74 有 `FF DA` SOS（長度欄位 10）。結構檢查包含 DHT 符號個數與 SOS 分量長度，不只是搜尋兩個 FF 標記。
- 這三段與同 take 第 2 幀第一個 JPEG tile 的同位置標頭段完全相同。首列均值 1838.62 DN，第 2 幀正常首列 306.12 DN。
- 首列前約 16 bytes 已呈 RAW 樣式，後面仍有 JPEG 結構與熵編碼樣式；下一列從 +4536 起恢復影像。因此不能寫成「整列完全沒寫」；是首列部分異常／可能未完整更新或被覆回。
- t03 等 12 組壞幀有與第 2 幀相同的標頭段；t15 有結構完整但內容不同的段。其餘 10 組首列也異常，但不能將其任意位元組直接認定為 JPEG。
- 從各首列 +128、+512、+2048 取 64 bytes，搜尋全部封存 DNG（含同檔預覽／metadata）：無非自身命中。**還未找出殘留內容來自哪張舊影像**；共同 Huffman/SOS 標頭不是 frame identity。

獨立 packed12 解包與 tifffile 的第 0 列完全一致。中央位移也不只是 CFA 奇偶誤判：t03 的 +1 列 MAE=1.003 DN，−1=1.707、−3=2.615。
底部同樣錯列：t34 最後一列對第 2 幀倒數第二列 MAE=0.121，對最後一列=9.508。檔尾剩 336 bytes，t03 剩 112 bytes，均少於一整列。因此不能只把 StripOffsets 加 4536 便宣稱恢復完整影像；最後一列不在現有檔尾中。

原 `takes.py` 的量測裁掉四周 200 像素，適合中央對位，卻漏看最關鍵的首列。新的複核保留中央對位並額外檢查第一列與尾列，沒有改寫舊量測。

另複核 `card/` 先前四段的前三幀（`audit_card_rows.py`、`card-row0-audit.json`）：14v2 A001_012 與12v2 A001_015 都有異常首列＋1列位移；012 首列均值3582.33 DN，965/3024像素達4095，但沒有可確證的完整 JPEG 標頭，不能宣稱殘留來源與 t34 完全相同。正常的013與1×1的014首列正常；四段第2→3幀皆不錯列。四段檔案皆存為 packed12，勿將 ADC 14v2 與檔案14-bit混為一談。此次未找到舊355–387的本地DNG，33/33仍僅引用先前紀錄，未重新驗證。

## 2. 優先假說與辨別方式

| 優先度 | 尚未證實的機制 | 支持／限制 | 最有辨識力的資料 |
|---|---|---|---|
| 1 | 首幀 RAW DMA／有效列啟動錯位，首列未完整更新 | 同時解釋舊 JPEG 與後續整列錯位；感光元件仍可能透過同步訊號觸發 | 首次 completion 的實際 base、crop、列長、前兩列及尾列摘要 |
| 2 | DMA raster 與 frame／檔案起點不一致 | 若相差一列，可把舊內容納入檔案；目前 TIFF 靜態標籤不夠判斷 | 比較 DMA base、frame+0x4C、file+header 長度；3024 RAW12 一列是 4536 bytes |
| 3 | buffer reuse／交接或 cache 把舊內容帶回 | 壓縮輸出會交換回原生 allocation；首幀 bypass 不會清除舊 DRAM。單純 cache 殘留不能獨自解釋整張位移 | 同一 frame id 在 DMA 完成與 enqueue／寫入前的內容摘要是否不同 |
| 4 | SoC 時脈／接收器切換尚未穩定 | 自訂與原廠還有寬度、R10、FE clock 差異，bus trace 看不到；目前沒有壞幀同步紀錄 | receiver／BUFA 狀態與第一個完成事件，不能以停錄後 snapshot 代替 |

此時不建議先二分破壞性 sensor 配對暫存器，也不把固定丟一幀當成已修復。若日後安排診斷，只需有限的描述子／前後列紀錄，不需要新增全幅 CPU 複製；先離線驗證 hook 上下文、所有權與成本。
若捕獲完成時已壞，定位往接收／DMA 端；若當時正常、enqueue 前後才壞，定位往交接／writer。首幀輸出仍未被直接觀測，現在不能判定其中一項。

## 3. 原有推論需要修正的地方

1. **原廠 106 是 2×2，也做垂直合併。** `projects/imx410-lab/offline/mode_tables.csv` 的 106 列為3032×1708、hbin/vbin=2/2、class18、R10=6；RULES 較新記錄與 bus 的 `0001=39 / 001C=03` 一致。舊 RULES §9 的 106=2A 有矛盾，應以此次實測和後續表格為準。
2. 「同樣 167 筆 sensor 寫入」不排除 SoC。原廠106 的 R10=6／FE48MHz；自訂12v2 class17→R10=3／FE96MHz，讀出寬度也不同。IMXB 在 `C0322C70` 入口先記錄，再呼叫原生 bus writer；不是接收器/MMIO/DMA trace，也不是感光元件內部 latch 的觀測。
3. y0=20 為偶數只能排除靜態奇數裁切，不能證明第一幀有效起點已同步生效。
4. 「正常首幀也未壓縮」不能排除第一幀分支的偶發 buffer／writer 問題。現有 RAW 首列位元組正是要重開此調查的理由。
5. `0242/0278/0279/027B/08B6/08B7` 在 RULES §37 已改稱同色列配對，不能再直接稱「不水平合併」。單獨清零最後兩個沒有消除錯列，不代表整組或其時序皆無關。

歷史反例：RULES §38 一度將隔列／同步數加倍推斷為 sensor；§39 最後定位為每幀 AE 依舊模式重寫 DCLP／時脈。這不是此次根因證據，但說明相同 sensor bus 值不足以排除 SoC 管線。

## 4. 已對照的來源

- `fpSup/lossless/native/card.c`，`fpl_card_arrive`：第一幀直接原生 enqueue，後續才進 lanes；`release_spare`：回收緩衝區。
- `fpSup/lossless/native/frame_hold.c`：`raster=handle+0x15400=file+header_bytes`；frame raster `+0x4C`、allocation `+0x68`、header `+0x14C`；完成壓縮後交換 spare 與 frame allocation。CPU payload 搬移採 uncached alias，故不能直接指控 Lossless 的 cached head writeback。
- `out/decomp/full/blk_c03.c`，`ContSet_Adr1`（c031be60）：首幀分別設定 BUFA1 crop、base、格式／列長後啟動；後續幀另走換址流程。`FUN_c038c5f8` 的原生 header 複製設計上止於 raster 前，JPEG 首列不是 header DMA 越界的證明。
- `out/decomp/full/blk_c00.c`，配置鏈 `C001CFD8→C001D038→C00104A8→C00108E0`：已查正常路徑建立 allocation metadata／尾端 guard，沒有清除 raster；已知 callback `C03DF4B0` 更新地址清單。釋放鏈 `C001D3D0→C001D2B8` 亦未清 payload。這支持舊 JPEG 可能保留在重用記憶體中，尚未證明此次第一幀實際拿到哪個舊 allocation。
- `out/decomp/full/blk_c06.c`，`FUN_c06319e0`／`FUN_c0631b98`／`FUN_c0630e90`：裁切窗 `300F0684`、目的指標 `30182280`、列長設定。
- `projects/imx410-lab/notes/MODE_TABLES_CONSUMERS.md`：TIM receiver window 與 R10／FE clock；`projects/imx410-lab/buslog/buslog.S`：sensor write trace 的觀測邊界。
- `projects/isp-lab/host/isp_formula.py` R13/R15：有 HMAX 不足造成單幀錯一列的先例；目前445／911已符合既有下限，不能宣稱此例也由 HMAX 不足造成。

## 重跑

在 repository 根目錄執行：

```sh
projects/cdng-image/.venv/bin/python -B projects/sensorlab-imx410/validation/20261103-first-frame-purple-review/audit_rows.py
projects/cdng-image/.venv/bin/python -B projects/sensorlab-imx410/validation/20261103-first-frame-purple-review/audit_card_rows.py
```

只讀封存 DNG；需要既有 numpy／tifffile／imagecodecs。JSON 另記錄分析腳本 SHA-256。原廠 DNG 的 StripByteCounts 比完整像素長度多12 bytes，正常組亦如此；腳本保留此值，沒有把 padding 誤認為另一列。

驗證：兩支分析腳本已重跑，35組bus與4段card結果一致，手動解包核對全數通過；檔案與所讀來源指紋在 `review-manifest.json`。依專案流程另跑快速檢查：首次受限環境有9個job中途退出，保留 `tools/test-logs/fast-20261103-050924/`；未改產品程式的主機重跑為89個unit tests＋core全部PASS，紀錄 `tools/test-logs/fast-20261103-051030/`。這些檢查不代表相機問題已修復。

## 5. 補充：11-03 下午的暗場（`dark_first_frame.py` → `dark-first-frame.jsonl`）

`defect-virtual/live/` 的 20 段暗場（鏡頭蓋上，IMXB SHS 4／30 dB）都有第 1、2 幀。熱點是感光元件固定位置，所以用兩幀熱點集合的最大重疊判斷位移，不受場景影響。

| 讀出 | 段數 | 第 1 幀錯 1 列 | 第 0 列 |
|---|---|---|---|
| 12-bit **1×1**（key 1，DC 6048×4040→3024×2020，模式 231） | 14 | **3**（f03、f05、f09） | 3 段都異常（均值 1960–2030 DN）；f03 有 FF C4／FF DA |
| 12v2（模式 230） | 2 | 2 | 異常（1240、1987 DN；v2_off 有 JPEG 標記） |
| 14v2（模式 231） | 4 | 4 | 3 段異常；**v14_new 錯列但第 0 列看起來是正常暗場**（256 DN） |

- **1×1 也會發生**（3/14 ≈ 21%）。先前 1×1 只有 1 段樣本（0/1），所以不是垂直合併獨有，垂直合併只是機率高得多（今天 6/6，先前 8/9、7/9、8/8）。
- v14_new 的第 0 列是正常暗場值，但影像照樣錯 1 列 → 第 0 列只是「沒被寫到、留著記憶體的舊內容」，舊內容剛好是之前的暗場幀。這支持「第 0 列沒寫入」，而不是「寫入了某種異常資料」。
- 錯列都是 +1（`frame1[y+1] = frame2[y]`），沒有出現其他位移量。
