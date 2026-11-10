# v0.7.13test 回放修正（2026-11-02，僅離線）

使用者要求嘗試修復高速錄影後的回放凍結。候選保留卡片備份設定；沒有相機／USB 操作，也未寫入實體 SD。

## 實作

- 原廠 ring C05C2D10 描述表 0x6F090 / 0x5EC = 300 格，成功配置第 301 個 RAW buffer 時越界。於 C05C2DE8（原字 EBE968FE）增加 BL hook，count >= 300 回傳 NULL，走原廠完成／清理路徑。沒有另存計數器。
- 既有兩個 prepare hook 在 owner/file/模式/壓縮等 guard 通過後，只將目前選中 player 的高速格率類別 11–13 改用原廠有表的類別 10。保留檔案幀率標記；非精確原速回放，低於 23 fps 的類別 0 仍不支援。
- 41 apply hooks 加 clock，共 42 claims。幾何公式、錄影路徑、設定格式、AP ABI 2 與 QS API 6 沿用。

前因與未修改原廠對照見 ../20261102-hirate-playback-diagnosis/；該資料夾與壓縮檔維持凍結。

## 驗證

- `ring-tests.json`：4 個測試方法通過。4 種檔案大小 × 8 種配置結果，包含 299/300/301/1000；最多 300 個且表外 sentinel 保留。非零配置可依原廠清理並重建；0 個 RAW 配置只測界限，未宣稱修正原廠該路徑的描述表釋放缺陷。
- 24 份卡上首末 DNG 標頭 × 單格／串流 prepare = 48 個案例通過。原廠選片、TIFF、prepare、ring、descriptor、queue、cleanup 執行真實 ROM；物理配置、鎖、XMP 空初始化、copy、檔案服務、非同步工作與解碼是明列模型，未解碼 LCD 像素。
- `mutants/`：允許第 301 個、取消格率轉換、取消選中 player guard 三個可執行變異分別觸發 60、36、1 個 assertion failures，均 0 errors；沒有把編譯／匯入錯誤當作有效反例。
- `regression.log`：74 個方法中 73 個通過，唯一失敗為測試尚未將新增的 C05C2DE8 列入 branch 白名單。補齊既定預期後，`install-final.log` 的 SourceTests／InstallTests 6/6 通過；沒有修改 hook 來迎合測試。
- `build-settings-final.log`：10/10 通過，包含設定遷移、錯誤封裝、設定驗證反例及載入。初次執行缺少新版本 frozen fixture，依該目錄既有 README 規定新增 v0.7.13 的獨立預設基準，舊版本未覆寫。
- `artifact-tests.json`：實際交付 BIN／預設 BIN × descriptor ready/not-ready 共 4 組，以保存的實際 AutoRun、LOADER、QSContainer v0.3.4、UI 檔載入；沒有載入卡片其他 companion。每組確認 42 claims、native ring 上限、完整釋放及全部 54 筆 journal 的逐位元還原。
- Exact-artifact 檢查最初遇到模擬計時上限，最終改用固定 20M 指令上限（SL_EMU_COUNT=1）。另發現既有單一載入器 helper 只讀到外層 stage2 的空 journal；本輪明確讀取每個唯一 registered object，再執行各個實際還原 callback，要求新 hook 存在於非空 journal。先前 `20261102-card-boot-freeze/settings-replay.json` 中 journal_entries=0 的還原敘述不能視為內層 hook 還原證據；本輪已補足，舊證據未改寫。

重跑新增回放測試：在 apply 目錄執行 `python3 -B test_playback_ring.py --report <新輸出路徑>`。
重播實際候選：`SL_EMU_COUNT=1 python3 -B replay_artifact.py`（請複製到新證據目錄後再執行，避免覆寫本輪）。

## 成品與限制

`SensorLab-v0.7.13-playback-test.zip` 只含說明與 SensorLab BIN。`card-settings-build` 為交付版，設定 record 260 bytes 與先前卡片 v0.7.12 備份完全一致；與預設版的差異僅在此 record。雜湊、完整案例與交付位置見 `summary.json`。`changes.patch` 相對本輪 source-before，並非相對 Git HEAD；source-final 與 sources.json 保存本輪來源。

上限越界為離線已重現缺陷，尚未證實使用者那次回放／插卡凍結一定走此路徑。真實記憶體池可用量、解碼、DMA、LCD、聲音及實機改善未驗證。高速錄影 liveview 卡住也未在本輪額外修正。此次 callback 驗證不等同實體電源流程測試。
