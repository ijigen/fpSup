# QSContainer v0.3.6：自訂 QS 編輯格的文字標題（2026-11-03，上機通過）

Bei 回報 SS__3054–3056：自訂 QS 編輯頁裡 RECIPE、MB/s、QR 三格借用 DC 圖示（`menu_crop`），容易誤認。Bei 選擇「格子顯示文字標題」，並要求完成後上機。

## 上機結果（經 peer sigmafp-re-85 確認未使用相機；用完已廣播 released）

| 步驟 | 結果 | 截圖 |
|---|---|---|
| 寫入 `card-settings-build/fpSup/QSContainer_v0.3.6.BIN`（設定記錄取自卡上 v0.3.5，`card-before/`），整檔讀回一致 | OK | — |
| 重開，LOAD.LOG | `0A … QSContainer_v0.3.6.BIN`、v0.3.5 為 `07`（重複，不載入） | `LOAD.LOG` |
| **第一版**（新物件掛在 Icon01 下） | DC 圖示消失，但**文字沒出現** | `shots/052923-editor-SS3066.jpg` |
| **修正版**（掛在 Icon01_CINE 下） | RECIPE／MB/s／QR 顯示文字，樣式與 FORMAT／RES.／FPS 一致；原廠格不變 | `shots/053144-editor2-SS3068.jpg` |
| 游標到 RECIPE | 名稱列 RECIPE | `053203-focus-recipe-SS3070.jpg` |
| OK 開清單、往右、MENU 取消 | 正常、不卡、配置不變 | `053217…SS3072`、`053235…SS3074`、`053249…SS3076` |
| 退出、開主 QS | QS 頁正常 | `053312-qs-page-SS3078.jpg` |

**第一版失敗的原因**：動畫群組 `Icon01_CINE` 由 Icon01_CINE 物件擁有；群組 pair 指向擁有者子樹外的物件時不會被播放（文字一直停在初始空白）。離線模型只檢查「pair 在群組裡」，沒抓到。已新增規則測試：每個群組的 pair 物件必須是擁有者或其子孫（原廠頁也滿足）；舊放法用反例確認會失敗。

## 還沒解決（同類，未改）

功能清單（OK 後下方的圖示條）裡，我們的三列仍顯示 DC 圖示（`SS3072`、`SS3074`）。那是清單 CSV 的 IMAGE 欄（預設 `menu_crop`），與編輯格是不同的物件；清單條只能顯示圖片，要改成文字得另做。

## 成品

| 檔案 | SHA-256 |
|---|---|
| `default-build/fpSup/QSContainer_v0.3.6.BIN`（199400 B，frozen fixture） | `eb900933c36491070d1c113198f79544ac1d1f6845f06d0bdc034dae8d3fe061` |
| `card-settings-build/fpSup/QSContainer_v0.3.6.BIN`（上機版，設定同卡上 v0.3.5） | 見 `card-settings-build/build-0.3.6.json` |

保留設定版與預設版只差設定記錄 332 bytes，記錄與卡上 v0.3.5 逐位元相同。

## 離線驗證

- `test_qsct.EditorPages` 6 項（含新增結構測試：表頭預算餘量同原廠、每物件 local／群組／子物件數、local id 不重複、pair 有 clip、pair 在擁有者子樹內）。
- 標題突變 9/9（`mutants-title.log`）；另有兩個既有突變因程式碼字串變動更新並確認抓得到；1 個等價突變註明於 MUTANTS。
- SensorLab `tools/test.py full --no-mutants`（`full-no-mutants.log`）：除設定遷移缺 v0.3.6 fixture 外全過；補 fixture 後設定遷移 8 項通過。修正版後 EditorPages、設定遷移、標題突變重跑通過，整套 full 未重跑。
- 截圖工具 `shot.py`：`dir \DCIM\100SIGMA` 回覆被截斷看不到新檔，改以編號探測；第一次截圖常是上一個畫面，所以每次拍兩張取第二張。
