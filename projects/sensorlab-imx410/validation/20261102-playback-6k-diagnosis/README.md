# 6K 選片凍結：離線診斷，尚未完成修復

使用者回報：選到 6K 片段即死機，尚未按播放。本次未取得該片段的實際 DNG、RES 高度、位深與 FPS。未操作相機、USB、PTP、daemon 或 SD 卡，未修改產品來源／BIN，也未建立新的測試版。

## 已完成

`check_native.py` 與 `native-audit.json` 保存可重跑的原廠指令核對：4 種 raster × 12/14-bit，共 8 組 canvas、32 組 FieldAngle 配置、6 組格率。原廠 sizing 結果與既有獨立算術模型一致；執行有指令數與寫入範圍限制。

這些是合成幾何案例，SelectedCam 的 TIFF tag、prepare 與部分服務是明列 fixture，不是使用者的錄影檔。未模擬真實 allocator、RTOS 任務、imager、DMA、LCD；`freeze_reproduced=false`。通過不代表 6K 可回放，亦不排除硬體路徑問題。

## 查到的邊界

- 6K 自訂尺寸映射到原廠 FHD playback profile；12-bit 為 profile 73。原廠輸出選擇器的非 UHD 分支使用 1920×1080 輸出描述，不可把 3840×2160 的試算當成本案例的現場輸出。
- raster 6064×4050、1920×1080 輸出時，FieldAngle 要求 42,815,976 bytes。`C03C5C88` 在 TakeOneFrameImage 前另外配置固定 1024×576 暫存平面；`C02DA6E0` 的這條路徑需求 1,179,648 bytes。兩者相加仍低於名義 48 MiB pool 3。其他存活配置／碎片未知，故不能宣稱已證實 OOM。
- `C0423D28 → C0428DA0 → C0437390` 會釋放 FieldAngle；不能把停止後才產生的平面無條件加進上述峰值。
- CinemaDNG file-ring `C05C2D10` 依實際檔案大小加餘量並按 4 KiB 對齊，在 pool 10 配置，不是固定 32 MiB 單格上限。原廠 mode 8/9 的 pool 10 名義容量分別為 `0x21200000`／`0x13600000`。目前沒有證據支持「單格超過 32 MB 就必然失敗」。
- 原廠 `C06A0770` 對低於 23 的整數格率回傳 enum 0；`C05BE080` 在配置／啟動準備後，發現該 enum 的 rate descriptor 為零才返回失敗。既有低格率測試也只驗證這個失敗，未重現使用者的凍結。不能由此直接斷定本片段的死機原因，亦未任意改寫播放速度。
- 已沿 `C01CDBE0 → C0173F20` 與 `C01D1630 → C01D2328` 檢視 RAW reader／影像處理設定，但尚未證實哪項 6K 參數令硬體停止完成影像。先前 RAW14 修正只證實格式值 0→1，不是完整影像解碼測試。

## 下一個必要輸入

會令相機凍結的那段影片之第一張原始 DNG（不必整段）。先從原檔讀出 raster/crop、BitsPerSample、Compression、StripOffsets/ByteCounts、FrameRate、DefaultScale 與檔案長度，接到既有原廠 parser／prepare／ring 測試，與上述合成案例比較。若檔頭仍不足以定位，再明確列出仍缺少的硬體狀態；本次不先用擴大記憶體或縮短 row pitch 當作修復。

核對基準為既有 SensorLab v0.7.19test 的 apply 來源（SHA256 存於 JSON）。本輪新增的只有這份診斷與離線重跑程式／結果，沒有可交付的新 BIN。
