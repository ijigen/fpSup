# SensorLab v0.7.20test：程式碼品質整理（2026-11-03，離線候選）

依 Bei 要求檢查程式碼品質後的整理。全程離線：未接觸相機、USB、daemon、PTP 或 SD 卡。**不打算改任何產品行為**；實機尚未驗證。

## 發現的建置懸崖（最重要）

`qr_show` 被 inline 進 `sq_value`，它用 PC 相對的 `movw/movt` 取 `qr_nop`／`qr_draw` 的位址。Apple clang 21 的組譯器在同一個 `.text` 內自行解析這種位址對時，只接受 ±32 KiB；v0.7.19 的距離已是 `0x7C26`（31,782 B），只剩約 1 KB。

- 選單突變測試的兩個突變體（選單事件中同步套用／重寫 model）多 inline 一份 `slm_sync`，距離變 `0x8148`，編譯報 `Relocation Not In Range`。這兩條規則因此自 10-30 後沒有突變保護。
- 修正：`qr_show` 加 `noinline`。QR 距離降到 `0x13A`；全檔最遠的同類位址對為 `0x36C4`（約 14 KB 餘裕）。
- `build_slqs.py` 遇到此錯誤時附上原因說明。

## 其他改動

| 檔案 | 內容 |
|---|---|
| `qs/slqs.c` | 內嵌位址／常數改為具名：`F_MUTEX_LOCK/UNLOCK`、`UIC_OWNER(_VT)`、`UIC_RECS(_END)`、`QS_SUB_ID0`(70)、`QSC_UI_BASE/QSC_INT_BASE`(49/54) |
| `apply/ap.c` | `AP_PB_RAW_SETUP`(0xC31DECCC)、`AP_TADD_STOCK`（init 檢查用；表格保留字面值，test_apply 會解析表格）；`ap_pb_tag` 先比對 header 綁定再呼叫韌體讀 tag；`H_PBRING` 補 r4 非零／對齊檢查 |
| `qs/test_slqs.py` | 一個突變體的比對字串跟著改名 |
| `tools/test.py` | 接上 6 個未登記的測試：pb-checked、pb-entry、hirate-preview、hirate-route、dc-steps、qr-present |
| `qs/test-fixtures/.../frozen/` | 補 v0.7.19（原本缺，設定遷移 6 項因此出錯）與 v0.7.20 預設 BIN |
| `qs/.mut_build_slqs_*.py` ×4 | 10-30 中斷的突變暫存檔，移到 `removed-leftovers/` |

共用公式、hook 數（43 claims）、AP ABI 2／QS API 6、設定格式、QSContainer、AutoRun、LOADER 都沒有變。

## 成品

| 檔案 | 大小 | SHA-256 |
|---|---|---|
| `default-build/fpSup/SensorLab-IMX410_v0.7.20test.BIN` | 184492 | `cc615b3d53f0dea375ceafbe51c460ab2528e384ad65b8c94414bdb3a6e68f88` |
| `card-settings-build/…v0.7.20test.BIN`（設定沿用 v0.7.19 交付檔 `b2b1c8ff…`，非卡上最新設定） | 184492 | 見 `card-settings-build/build-0.7.20test.json` |

比 v0.7.19 小 1,776 B，因為 `qr_show` 不再被複製成多份 inline。重建兩次逐位元相同。

## 驗證

- `full.log`／`full-report.json`：584 個 job。所有單元測試通過（含新接的 6 組）；`menu-runtime-mutations` 恢復通過；core 62、qsc 34、qsc-page 84 個突變全部抓到。
- 唯一由本輪造成的失敗：test_apply 的 2 項（表格改成巨集後正規式解析不到）。已改回字面值，重建 SHA 不變，`InstallTests`／`SourceTests` 重跑 6/6 通過。
- `artifact-tests.json`：真 AutoRun／LOADER／QSContainer v0.3.5 + v0.7.20，預設與保留設定 × descriptor 未就緒／就緒 4 組，DC 5040 套用與寫回、55 筆 journal 全部還原。

## 還沒處理（本輪之前就存在）

5 個突變體在 10-30 之後就失效，本輪沒有改：

- apply 48／56／61：比對的原始碼在 v0.7.9～v0.7.10 已改寫（`mutant text not found once`），需要改寫成對準現行程式碼。
- slqs 81「QR: the shadow never learns」：突變存活，表示 v0.7.17／18 的 QR shadow 邏輯沒有測試能抓到。
- slqs 39「runner: the yellow flag lost」（preview_runner.js）：突變存活。

審查清單第 2 項（`sq_value` 取文字時會顯示／隱藏 QR）屬設計變更、第 7 項（QSContainer 的 `QSC_LOCK_TITLE_*` 已無使用者）要動共用容器，兩項都未改。
