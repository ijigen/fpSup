# 比例欄小字 LOCK（2026-11-02，離線候選）

SensorLab v0.7.14test + QSContainer v0.3.5：DC／RES 比例格上方恢復 RATIO，大字保留比例。掛鎖與 LOCK 使用原生 menu_lock_qs，縮為 120 × 59.2，放在 (68,147)；圖形實際不透明區位於小字列，解鎖與退出清除，其他欄位不顯示。

以 opt-in SMALL_OPEN/SHUT 回傳值及獨立小字圖物件實作，既有 TITLE 及 API 3/4 客戶端保持原行為。只新增 8 個整數寬度變數，保留原編號、API 6 和持久設定格式；裁切／預覽公式、apply、錄影與回放程式不變。

76 項 QS 測試中 75 通過、1 項既有 opt-in MENU-back 測試跳過；58 項 SensorLab、8 項設定遷移通過。三個可執行反例分別驗證隱藏標題、解鎖殘留、水平偏移確實被攔下。四組最終實際 BIN（預設／備份設定 × descriptor 未就緒／就緒）載入、比例圖示切換與舊 ring 防越界檢查通過；每組所有 54 筆 journal 逐位元還原。首次 exact UI 測試缺少測試用 CINE 排列，以及反例環境鍵誤用，均保留初始 log，最終結果與限制列於 REPORT.json。

建置以獨立預設產物作 frozen fixture，再重建比對完全一致。交付包的兩個 BIN 保留先前已保存的設定記錄，並非現在相機卡上的最新設定。ZIP 完整讀回且每個成員核對 SHA。沒有操作相機、USB、daemon、實體 SD、原始 ISPC 或 BIN 韌體映像。

交付：SensorLab-v0.7.14-ratio-test.zip。需一併換兩個模組；AutoRun、LOADER 及其他模組不換。實體 LCD 尚未確認。14-bit 花屏並未在本版修復，調查記錄保存在相鄰的 20261102-playback-raw14。

sources.json / source-before / source-final / changes.patch 為本次來源差異；settings-migration/report.json、artifact-tests.json 及測試 log 為詳細證據。
