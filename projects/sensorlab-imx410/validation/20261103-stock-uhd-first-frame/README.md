# 原廠 UHD 第一幀對照（2026-11-03 晚，上機）

目的：模擬（`../20261103-first-frame-mmio-diff/`）顯示原廠 UHD 和 SensorLab 一樣，走 BUFA1、錄影啟動寫 4、每列 2 段；原廠 FHD 106 則走 BUFA7、啟動寫 8。用原廠 UHD 區分「錄影用 4 啟動」和「我們自己的 BUFA1 設定（垂直 1:1）」。

條件：Bei 選原廠 UHD 29.97 CinemaDNG 12-bit。SensorLab v0.7.25test 有載入，但從開機起沒有 commit（`active = 0`、`commits = 0`）。`takes.py`（從 first-frame-purple 複製）：`bufa_probe rec` 錄 2 s，用第 1、2 幀中央區域對位。

結果：**UHD 29 段（A001_095–123）第 1 幀全部 dy = 0**。t01（A001_093）錄成 FHD 1936×1090，不計入；A001_094 是錄影失敗被跳過的編號。
若原廠 UHD 的錯列率和我們的 1×1（3/14 ≈ 21 %）相同，連續 29 段 0 錯的機率約 0.1 %。

結論：錄影路徑用 4 啟動 BUFA1 本身不會讓第一幀錯列。原因在 SensorLab 模式的 BUFA1／縮放設定；最可疑的是垂直 RWZM 1:1（1×2 合併類幾乎每段都錯；1×1 是 2:1，21 %；原廠 UHD 約 1.56，0/29）。修法 B（啟動改寫 8）大概沒用。

另：剛開始時相機凍結過一次（Bei 從 SensorLab 配方切回原廠 UHD，在選單 B2_5 時 shell 就已經不穩），見 defect-virtual README 的凍結紀錄。
