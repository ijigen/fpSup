# v0.7.10test：選片時誤拒（2026-11-02）

使用者測 v0.7.9 回報「一樣」，並確認選到片段就顯示「檔案內容不能檢視」。這是修正候選，尚未上機驗收。

## 已證實的原因與範圍

原廠 v11 以 mode 2 呼叫 TIFF parser。`C0746DA4` 的 14 個 IFD0 filter entries 不包含 Compression 0x103（原字及清單見 `native-sites.json`）。v0.7.9 卻在這個精簡物件查詢 Compression；原廠 helper 回傳 0，導致正常未壓縮檔也被 admission guard 擋下。舊的人工 tag helper 提供了原廠不保留的標記，造成驗證盲點。

新增 `C05BDC9C` BL hook，只掃描 v11 已讀進記憶體的 IFD0，核對 endian/magic、範圍、最多 512 個條目，以及 Compression 的唯一 SHORT×1 定義。結果綁定本次 player、檔案描述物件和 TIFF handle。原廠 parser、後續幾何與位深 guard 照常運作。沒有新增檔案 I/O、影格緩衝、影格複製或預覽公式。檔案描述物件可被原廠重用，本版不把指標宣稱為永久唯一的檔案 ID。

40 個 apply hooks＋clock 共 41 claims；AP ABI 2／QS API 6 沿用。只需換 SensorLab BIN；QSContainer、AutoRun／LOADER 不變。成品詳見 `REPORT.json`、`delivery-manifest.json`；兩次建置逐位元組相同。

## 離線驗證

- 71 項既有 apply、頁面、預覽路徑／比例回歸：`regression-verified.log`。
- 10 項既有回放選取／畫布／buffer 尺寸測試：`checked.json`。
- 5 項新增原廠選片／TIFF／prepare 與反例：`native-entry-final.json`。三份保存的實拍 DNG 皆由原廠 parser 讀實際 bytes，經 v2/v11 的原廠順序填回 crop，未人工預填選取尺寸。
- 9 項完整 BIN/QS／比例欄位整合、8 項設定遷移：`qs-integration.log`、`settings-migration/report.json`。
- 舊來源對照：三份同樣的 DNG 均被 v0.7.9 拒絕；同一套 5 項測試產生 14 個 assertion failures、0 errors，見 `old-v079-final.json`。前後使用相同檔案雜湊。
- 兩個隔離來源反例（放行 Compression=7、忽略 header owner）各被 assertion 捕捉，均無例外／編譯錯誤。

檔案 I/O、allocator、audio/timecode、RTOS、configurator 和解碼工作為明示 fixture。`setPlayInfo`、v2/v11、TIFF parser/tag lookup、原廠格率表與 prepare 執行 ROM；未解碼像素，不能代替實機。

初期 `regression.log` 保留新增掛點清單尚未更新的兩項失敗及一次不存在的測試模組名稱錯誤；`regression-final.log` 仍保留清單尚未更新的失敗。這些不計成功；清單與命令核對後的完整結果為 `regression-verified.log`。調查原型 `entry_probe.py` / `parser_probe.py` 保留，維護入口為 `apply/test_playback_entry.py`。

重跑：

```sh
python3 -B projects/sensorlab-imx410/apply/test_playback_entry.py --report /tmp/sl-native-entry.json
python3 -B projects/sensorlab-imx410/apply/test_playback_checked.py --report /tmp/sl-checked.json
python3 -B projects/sensorlab-imx410/qs/build_slqs.py --out /tmp/sl-v0710-rebuild
```

## 上機待驗與已知限制

可先測既有未壓縮 2K、24/25/30 fps 片段：選片單格 → 播放 → 暫停 → 退出回 liveview。無須為本版重新錄製或轉檔。預設設定包需重選 SensorLab 設定。

小於 23 fps（及其他原廠沒有格率項目的值）仍由原廠 rate lookup 拒絕；本版不假造播放格率。壓縮 DNG、缺少／畸形標頭仍拒播。LCD、DMA、記憶體可用量、聲音、持續播放、高解析度／RAW14 效能、先前黑屏原因均未驗證。此次沒有連接相機或寫卡。
