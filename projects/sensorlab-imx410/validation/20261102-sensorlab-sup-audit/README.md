# SensorLab SUP 核對與 v0.7.16test LOCK 相容修正

2026-11-02，全程離線。使用者回報 LOCK 消失，卡上 QS 為 v0.3.4 或更早，並指出共用容器不應因產品小功能頻繁更新。本次只修改 SensorLab 的小字內容回呼；QS、API、裁切公式、錄影／回放及載入器程式均不變。

## 原因與共用邊界

v0.7.14／15 的 SensorLab 小字回呼回傳空字串，另回傳 QS v0.3.5 才認得的 `QSC_LOCK_SMALL_SHUT`。舊容器忽略不認得的圖示值，因此連文字也沒有。這是客戶端未提供後備顯示的相容問題，並非需要載入額外 SUP。

v0.7.16 的 `small()` 在鎖定時提供 `LOCK`，解鎖時提供空字串。QS v0.3.2–0.3.4 沿用原有小字繪製；v0.3.5 依原有規則以小字列原生圖示取代文字。比例欄仍是 `RATIO` 標題與大字比例，其他格不放掛鎖。

容器負責共用繪製、焦點與輸入；客戶端負責內容、功能狀態和比例格式。未來真正的共用顯示擴充需要明確能力與相容性設計，不能把新的專用 LOCK 值當成每次產品排版變更的解法。本輪沒有另加圖示分支、API 版本、版本配對檢查或通用排版框架。**舊 QS 的後備是 LOCK 文字，不是小字列原生圖示。**

## 目前需要哪些檔案

| 元件 | 關係與本輪處理 |
|---|---|
| `SensorLab-IMX410_v0.7.16test.BIN`／SL41 | 本輪唯一新成品。內含選單、QS 客戶端、感光元件／ISP 計算、套用及回放掛鉤；不需要另放核心或回放 BIN。 |
| `QSContainer`／QSCT | SensorLab v0.7 系列原有的 API 6 容器相依。API 6 始於 v0.3.1；本輪實際測 v0.3.2、0.3.3、0.3.4、0.3.5。現有舊版可留用文字後備；v0.3.5 的小字列圖示是可選顯示能力。 |
| `AutoRun.txt`、`fpSup/LOADER.BIN`、`fpSup/UI/*` | 原有共用載入與 UI 資源。兩個 SUP 宣告最少 loader service 6；本輪直接沿用已保存的原卡載入檔及 UI 資源核對，沒有重新配版或要求更新。 |
| `SUPMGR.BIN`／SMGR | 選用的 SUP 啟停管理介面，不是 SensorLab 計算／錄影／回放的必要 SUP。 |
| `fpui_stock.c` | 建置時納入 SensorLab／QS 的 UI 共用程式；不需另新增 FPUI 或 USHR BIN。 |
| `SLTP.BIN` 等開發測試 SUP | 不屬於交付相依，勿把回放測試程式當成正常播放必要條件。 |
| RES-Custom／RCUS、獨立 OG 模式修補 | 不是 SensorLab 的相依；RES-Custom 與 SensorLab 不應同時負責模式套用。保存快照中 RCUS 已停用，本輪沒有變更啟停清單。 |
| ISPL、UnlockWriter／ULWR、Lossless／LOSS | 都不是 SensorLab 必要相依。快照中 ISPL 與 ULWR 有相同地址的掛鉤衝突；不能據此推論它們造成 LOCK 消失。Lossless 若產生壓縮 CinemaDNG，目前 SensorLab 回放仍只接受未壓縮片段；「已載入」不等於「已開壓縮」。 |
| Gyro、LUT、RAW-View、Desqueeze、ScreenFlip、TapToZoom、EarlyFlush、Stop-FX、USB-Shell | 其他獨立功能，均非 SensorLab 必要相依。本輪未逐一執行它們的功能，不宣稱所有組合已相容。 |

## 保存的卡片清單，不是即時卡片狀態

目前 `/Volumes/fpSup` **未掛載**，未讀取或修改現在卡上的檔案。本表源自 `20261102-card-boot-freeze/card-before`，保存時間為 **2026-11-02 04:56:44 台北時間**（UTC 2026-11-01 20:56:44）。檔案雜湊、SUP ID、最少服務版本及 LOAD.LOG 已逐項核對，詳細值見 `inventory.json`。

| 保存檔案 | SUP ID | 保存的 LOAD.LOG 狀態 |
|---|---|---|
| Desqueeze_v0.1.5.BIN | DSQZ | 停用 |
| EarlyFlush_v0.1.0.BIN | FCAP | 停用 |
| Gyro2_v0.2.1.BIN | GYR2 | 停用 |
| ISPL.BIN | ISPL | 載入 |
| LUT.BIN | LUT4 | 停用 |
| Lossless_v0.3.1.BIN | LOSS | 載入 |
| QSContainer_v0.3.2.BIN_.BIN | QSCT | 同 ID 重複，未選用 |
| QSContainer_v0.3.3.BIN | QSCT | 同 ID 重複，未選用 |
| QSContainer_v0.3.4.BIN | QSCT | 載入 |
| RAW-View_v0.3.1.BIN | RAWV | 停用 |
| RES-Custom_v0.1.5.BIN | RCUS | 停用 |
| SUPMGR.BIN | SMGR | 載入 |
| ScreenFlip_v0.1.1.BIN | FLIP | 停用 |
| SensorLab-IMX410_v0.7.10test.BIN | SL41 | 同 ID 重複，未選用 |
| SensorLab-IMX410_v0.7.11test.BIN | SL41 | 同 ID 重複，未選用 |
| SensorLab-IMX410_v0.7.12test.BIN | SL41 | 載入 |
| Stop-FX_v0.1.0.BIN | STFX | 載入 |
| TapToZoom_v0.1.1.BIN | TAPZ | 停用 |
| USB-Shell_v3.4.0.BIN | SHEL | 停用 |
| UnlockWriter_v0.1.0test.BIN | ULWR | 與 ISPL 在 C063F140 衝突，釋放 |

同 ID 的舊檔存在，不代表同時執行。loader 會依檔名版本排序、選用該 ID；FSB4 header 的 `file_version` 並不總是產品標示版號，例如 SensorLab header 的 20 不等於 v0.7.15 或 v0.7.16。`inventory.json` 的 `current_delivery` 是核對開始時保存的 v0.7.15／QS v0.3.5 交付資料；新候選另見 `release.json`。

UI 快照為 `0.BIN`–`4.BIN`、`COLOR.BIN`、`FPSUP.BIN`、`SUPMGR.BIN`；UI 目錄的 SUPMGR 資源與根目錄的 SUPMGR 執行檔是不同檔案。本輪均未更新。

## 離線驗證

- `matrix-before.json`：實際 v0.7.15 BIN 配 QS v0.3.2／0.3.3／0.3.4，小字在 LOCK 和 FREE 都空白；v0.3.5 正常顯示／隱藏原生小字圖示。
- `matrix-after.json`：實際交付 v0.7.16 BIN 配同四版 QS。前三版 LOCK 為文字、FREE 為空白；v0.3.5 圖示寬度為 120／0。DC／RES 都測，標題維持 RATIO，新版圖示只在比例格，退出子選單清除。
- `focused-tests.log` 與 `fallback-settings-tests.log`：合計 18 項相關測試通過，涵蓋比例、即時更新回呼、建置、實際註冊的小字回呼及設定遷移。
- `artifact-tests.json`：預設／保存設定 × descriptor 就緒／未就緒四種實際成品載入。沿用原卡 AutoRun／LOADER／UI、保存的 QS v0.3.5。既有 RAW14 格式與過期 owner 反例、300 格回放緩衝上限與清理均通過；每次全部 55 筆 journal 還原核對。
- `settings-preservation.json`：交付的 260-byte 設定記錄與 v0.7.15 保存包逐位元相同。預設／保存設定兩成品在設定記錄以外完全相同。
- `source-diff.txt`／`sources.json`：生產程式僅 SensorLab 小字回呼與版號變動。QS 與 apply／回放來源對前版指紋核對未變。

保留兩個測試工具修正紀錄：版本比較腳本必須把測試 helper 定位到實際被測的舊檔名；新單元測試一開始誤把 UI 格索引當作子陣列索引，取到空回呼，已依既有內部 ID 換算修正。後者首跑輸出留在 `fallback-settings-first-attempt.log`；不是相機程式執行結果。

Unicorn 執行實際 ARM／Thumb BIN，但 UI、檔案、RTOS 等仍為既有模型；本輪沒有相機、LCD、USB 或 SD 寫入。回放測試沿用明列的 frame descriptor fixture，**不代表已證實實機 14-bit 花屏、高速 liveview 停住或插卡凍結已解決**。

## 交付與確認

只交付 `SensorLab-IMX410_v0.7.16test.BIN`，185352 bytes，SHA256：

`6b229d7bd700826abb7b70994907bc199e8b798fcf0533b524af3784dcab7c9c`

預設設定測試成品的 SHA256 為 `3ad6568f3cd3326849017e68cf5fe1360d566ef46aaf3a826b4dafcb7b52e2bd`。兩者設定以外相同。交付包保存的是前次備份中的設定，並非本次讀取目前 SD 卡的設定；其中為 S16、自動 FPS、約 320×196 顯示尺寸，測別的配置時需自行重選。

沿用目前 QS、AutoRun、LOADER、UI。更新 SensorLab 後，在 DC／RES 的 RATIO 格切換 LOCK／FREE：舊 QS 應顯示／隱藏小字 `LOCK`，已有 v0.3.5 則為原生掛鎖與 LOCK。實體位置與顯示結果待使用者確認。這個 ZIP 不包含新 QS，也不是完整卡片套件。
