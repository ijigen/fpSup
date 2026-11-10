# SensorLab v0.7.19test：DC 原生寬度停靠

SensorLab v0.7.19test — DC 原生裁切點粗調修正

後轉盤粗調 DC → WIDTH 時，跨過 6048、5040、4144、3984 會先停在該點，並顯示原有點狀底線。正反方向都適用，再轉一次即可離開。
前轉盤仍每步 16 px；比例鎖、HEIGHT、RES、錄影及 HDMI Mirror 的公式不變。

安裝：相機關機後，備份並移出卡片 fpSup 內原本的 SensorLab BIN，放入本包的新版 BIN。同一卡只保留一個啟用中的 SensorLab。
QSContainer、HDMI Mirror、AutoRun、LOADER、UI 均沿用，不需更新。
此檔沿用上次交付 v0.7.18test 檔案中的設定，沒有讀取你卡上後續新增的設定。

測試：進入 DC 的 WIDTH，從 6048 用後轉盤向下，應依序到 5888、5728、5568、5408、5248、5088、5040；5040 顯示點狀底線，再轉到 4880。反向也能停靠，前轉盤仍可細調。
已通過離線轉盤、保存、套用及還原測試；尚未上機確認實體轉盤與 LCD。

交付 BIN：186268 bytes，SHA-256 `b2b1c8ff056f19dc6148e4fe9720a5779afa9bfb79e1e1325fb9789b9f735e0f`。

## 證據

- `old-counterexample.json`：實際舊 v0.7.18test 的後轉盤序列 6048 → 5888 → 5728 → 5568 → 5408 → 5248 → 5088 → 4928，跨過 5040；不是所有操作都無法到達，前轉盤原本可以。
- `dial-tests.json`：5 項測試，真 ARM／QS key callback 執行。雙向所有原生點、LOCK／FREE、可離開標記、前轉盤、HEIGHT／RES 不變、5040 套用及保存重載。檢查 footer callback 與 QSContainer 實際張貼的點狀底線文字。
- `regressions.json`、`regressions.log`：19 項既有 UI／比例／保存／apply 測試，以及兩條瀏覽器預覽與 ARM 逐步對照序列。
- `artifact-tests.json`：實際預設／保存設定 BIN、既有 AutoRun／LOADER／QSContainer，descriptor 未就緒及已就緒共 4 案例；5040 套用及寫回、55 筆 journal 全部還原。
- `artifact-tests.initial.log` 保留首版整合測試失敗：測試在首次收集容器格子前就換了全部 QS slots，descriptor 就緒時第一次 layout 未正常返回。調整為既有 `S.boot` 的先收集、再換版面順序後四例通過；沒有為此改產品碼或放寬測試指令上限。
- 只有離線證據。File／RTOS／UI 服務為現有明列模型，實體轉盤事件、LCD 及實拍未驗；本輪未連相機、寫 SD、操作 USB、commit 或 push。

## 重現

```sh
python3 -B projects/sensorlab-imx410/qs/build_slqs.py --out NEW_OUTPUT
SL_EMU_COUNT=1 python3 -B projects/sensorlab-imx410/qs/test_dc_steps.py --build NEW_OUTPUT --report dial-tests.json
SL_EMU_COUNT=1 python3 -B projects/sensorlab-imx410/validation/20261102-dc-native-stops/run_regressions.py
SL_EMU_COUNT=1 python3 -B projects/sensorlab-imx410/validation/20261102-dc-native-stops/check_artifacts.py
```

只有 SensorLab BIN 更新，沒有新掛鉤、QS API 或設定格式。來源與指紋見 `source-after/`、`manifest.json`。
