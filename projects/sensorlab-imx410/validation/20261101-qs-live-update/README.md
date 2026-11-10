# v0.7.6test — QS 調整中的預覽比例候選修正

使用者最新回報：v0.7.5 在退出 QS 後似乎正常，希望調整時就更新。全程離線；沒有相機、USB、寫卡操作。

## 修改

在原廠 YUV `W71C1::v2` 的 fallback 加一個 hook：`C0306F28`，原字 `E28D102C`（`add r1,sp,#0x2c`）。原先以來源尺寸的堆疊副本交給原廠比例分類器，可能重新吸附至 3:2／16:9。現在每幀直接取目前已提交 slot 的自有比例指標，沿用既有 H_FIT 精確指標保護；連續調整後不保留上一次的 slot 指標。

inactive／播放保持原指令。RGB／W v4 沒有新增 hook。既有近 16:9 容差、裁切計算、sensor／ISP、QS API6／AP ABI2、設定格式維持原規則。39 hooks＋clock＝40 claims。

QS 每次調整原本就會呼叫 ap_request；這次不增加硬切裁切、重開 QS、CPU 全畫面複製或新的韌體呼叫。

## 證據與界線

- regression.log：83 項 apply／原廠畫框／圖層／分支／連續更新測試。
- qs-regression.log：12 項，含真實 BIN 經 QS 調整回呼連續提交 WIDTH／HEIGHT，保持 sub-QS 開啟並核對新 fallback 使用的比例；近 16:9 另比較原生 fitter 輸出。
- settings-migration/report.json：8 項設定遷移測試，核對完整 BIN 的空白設定和保存格式。
- ranges.json：321 個裁切×2 格率＝642 次選擇，五種明示狀態，共 9630 次 YUV／RGB 原生 fit。寬 5088..6048（步進16、高4040）；高3520..4040（步進2、寬6048）。
- baseline-final.json：v0.7.5 原始 ap.c 的反例，14 個失敗子案例、0 errors。
- mutant-no-playback-valid.json：只移除新增 hook 的播放保護，4 個失敗子案例、0 errors。
- native-continuation.txt：新 hook 後的原廠指令；下一段無條件呼叫的 fitter 在使用條件前自行設定 NZCV。寄存器、SP、CPSR 控制狀態有獨立測試；此 site 不要求保存死值 NZCV。

**未證實相機在 QS 開啟時採用 state 0／1。** 它們是可重現 fallback 的明示 fixture；QS 原生排程、DMA、scanout 和實體 LCD 未模擬。完整 BIN 的 QS 回呼驗證採既有「no LV」服務模型，只證明提交與比例選取，不代表 LCD 已即時更新。實機結果由使用者確認，不能標為修復成功。

保留的初期失敗紀錄包括測試尺寸不符合配方、反例 include 路徑未備齊、錯誤測試類別名稱、對死值 NZCV 的過度斷言、將近 16:9 當精確比例、分數化後的容差邊界及未初始化 VFP。這些不計為有效產品反例；以上列出的最終報告為準。沒有為通過測試而移除產品 guard。

## 重建與交付

`python3 -B projects/sensorlab-imx410/qs/build_slqs.py --out /tmp/sensorlab-v076-clean-build`

只更換 SensorLab BIN，AutoRun／LOADER／QSContainer 不需更新。預設設定版，不含目前卡上的設定。BIN／ZIP 的 SHA256、來源指紋、測試結果見 REPORT.json；交付包內含安裝和 QS 內連續調整步驟。

未做本版實機 LCD、錄影、暖啟動與重複關機測試；測試候選並非已驗收發行。
