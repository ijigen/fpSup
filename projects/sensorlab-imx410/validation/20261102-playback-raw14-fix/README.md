# v0.7.15test：14-bit 機內回放格式候選修正

2026-11-02；全程離線，未操作相機、USB、PTP、daemon 或 SD 卡。使用者回報：S16／2K／29.97／14b 1×1，選到片段時花屏但不當機。本次尚未取得該片段完整檔案，也沒有 LCD 實測。

## 發現與修正

原廠 `C01CDBE0` 內 `C01CE400..C01CE458` 將 frame 主平面的類型轉為 RAW reader 格式，7／9／10 分別寫入 0／3／4，沒有處理 plane 8。SensorLab 提供的 RAW14 plane 8 因而寫入 0（RAW12）。下游 `C0173F20` 直接使用此欄，且已實作 format 1（RAW14）。ROM 指令見 `native-format-disassembly.txt`；韌體 SHA256 為 `92a8ee993f6c3d66c251e88d45a2ccd5135c6cf7342717784321c2ed506e2fb4`。

新 `H_PBRAW14` 位於 `C01CE450`，原字 `0282EB05`（Thumb `add.w r2,r5,r2,lsl #2`）。經既有 loader claim/cave/journal 進共用 ARM veneer，再回 Thumb。只有選中且準備完成的 RAW14、目前 playback canvas、owner／file／raster 一致、channel 0、正確原廠 setup base、主平面與尺寸均吻合時，將 r3 改為 1；所有路徑都重做原 ADD，由原廠後續 store 寫入格式欄。42 apply hooks 加 clock 共 43 claims。

未改共用裁切公式、14-bit 錄影封裝、DNG、profile 的 `AP_PB14_EN=0`、endian、水平 crop offset 或 metadata converter；沒有 observer、SD 日誌或新增影格複製。RATIO／大字比例／小字掛鎖沿用 v0.7.14 + QSContainer v0.3.5。

## 驗證範圍

- `before.json`：原版 14-bit 的四種尺寸全部讀成 0；失敗來自預期斷言，無執行錯誤。
- `after.json`：8／10／12／14-bit × 2096×1240、1936×1090、336×206、6064×4050，共 16 組。格式分別為 4／3／0／1；停用掛鉤仍重現 14-bit→0。
- 過期檔案、未 prepare、離開回放、不同 channel／尺寸／plane 均保持原廠行為；r0/r1/r4–r12、SP 與 Thumb 返回核對。
- `mutations.json`：錯格式值、移除 owner guard、錯 ADD 三個實際執行的變異均被斷言抓出，沒有把 emulator error 當成成功抓到變異。
- `regression.log`：28 個安裝、選片、parser／prepare、ring 與 RAW14 測試通過。
- `apply-tests.log`：完整 apply 51 tests 通過。設定及 QS 的結果另見 `test-results.json`、`slqs-settings-tests.log`。
- `artifact-tests.json`：**實際成品**預設／保存設定 × descriptor ready／not ready 共四種載入；原 AutoRun、共用 LOADER、QSContainer v0.3.5，實際安裝的 RAW14 掛鉤及過期 owner 反例皆通過。既有 300 格 ring 上限、canary／cleanup 和比例 UI 核對。每次遍歷全部 journal，55 筆逐位元還原。
- `settings-preservation.json`：260-byte 設定記錄與上一版保存包逐位元相同；保存設定及預設設定版程式碼相同。

重要邊界：RAW14 轉換測試的 frame descriptor 是由原廠 playback canvas 結果建立的明列 fixture。實際 BIN 測試則複製該選片 fixture 的狀態及 player，執行成品自己的 hook code，沒有替換成 unit code。這不是完整 imager／DMA／LCD 模擬，不能證明顏色、位元組順序、所有 crop offset 或硬體播放時序。allocator／RTOS／檔案 I/O 等服務仍使用既有明列模型。

## 交付

`SensorLab-IMX410_v0.7.15test.BIN`，185320 bytes：

- 保存設定版（交付）：`6591b48cdf4edc7ba6eb64c0ce0204e8336daa83a8855899cd21be483f90388e`
- 預設版（離線 fixture）：`8abbf6c669b5ea91ec2b568c61cdeb3fbf6f489e1162cf5c3cd75d3188cf319b`

交付只含 SensorLab BIN 和說明，不含新的 LOADER／AutoRun／QSContainer。保存的是既有 v0.7.14 包中的備份設定，並非本次讀取 SD 卡的即時設定。先測既有 S16 2K 29.97 14b 1×1 片段，確認選片單格與播放，無須為此重錄；若仍花屏，才能進一步決定是否需要小型 RAM observer 取得實際格式／stride／endian／guard 狀態。**目前只確認離線格式缺口修正，未宣稱實機修復。**
