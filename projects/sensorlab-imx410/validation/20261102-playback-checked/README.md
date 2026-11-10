# SensorLab v0.7.9test 回放候選

使用者要求離線修正、由使用者操作相機。本輪未接觸相機、USB、daemon、PTP 或記憶卡，沒有啟動測試 runner、寫卡或推送。

## 變更

v0.7.8 的預設 `mode=0, block=1` 會在解碼前拒絕自訂尺寸。新預設 `mode=1, block=1` 開啟回放畫布，保留選中片段的標頭檢查：

- 由原廠 v11 的 context/raster 指標關係取得 player 物件與檔案識別。必需的 width、height、crop、bits、Compression 重新讀取並核對返回值，避免缺標籤時沿用原廠 reader 留下的舊值。
- 只接受 Compression=1、8/10/12/14-bit、raster width 32–6064 且 16 對齊、height 12–4050 且偶數、crop=raster−(16,10)。沿用共用比例公式與檔案 DefaultScale，不新增個別尺寸特例。
- 兩個 prepare 入口先核對 player、檔案識別、尺寸、位元深度；canvas 只使用該片段快照。同 crop 的索引快取不能替換 raster、bits 或 DefaultScale。
- RAW14 沿用原先的 12-bit profile lookup＋RAW14 平面碼 8；實際 RAW14 解碼仍待測。HUD 自訂圖塊與 Playback 頁實驗保持關閉。

維持 39 個 apply hooks 加 clock 共 40 個登記；AP ABI 2／QS API 6 沿用。v0.7.8 預覽公式、錄影運算、QSContainer、AutoRun 與 LOADER 均沿用。原廠限定 fallback mode 0 及舊診斷模式保留，產品預設不關閉 admission guard。

## 離線驗證

共 99 項測試通過、無跳過：

| 檢查 | 數量 | 紀錄 |
|---|---:|---|
| apply／播放頁／liveview 回歸 | 71 | `regression-final.log` |
| 選中片段與原廠 prepare／尺寸計算 | 10 | `checked-final.json`、`checked-final.log` |
| QS 建置、套用、比例欄位、預設回放設定 | 10 | `qs-integration.log` |
| 真實 loader/client/container ARM 與設定遷移 | 8 | `settings-migration/` |

`checked-final.json` 包含 4 種 raster × 4 種 bits 的單格／連續入口案例、3 份已保存實拍 DNG 的標頭、索引碰撞、錯誤標頭與切片／退出隔離。原廠 `C05BE080` 及 `C05BC408` 實際執行；準備成功時驗得原廠固定 80 MiB 配置要求與傳入配置器的片段 crop/enum。配置器、allocator、file-ring、RTOS、decoder 任務為明列 stub；不是實機記憶體配置或解碼成功。

原廠 FieldAngle 計算對真正自訂 canvas 執行，最大測例 6064×4050 的總需求 42,815,976 bytes，低於名義 48 MiB LVIEW pool。這不代表實機當時有足夠連續空間，也沒有證明 file-ring、其他 pool、DMA 或播放效能。

原有 `PoolTests` 在預設拒播模式下曾誤算原廠 fallback canvas，本輪將它明確設為診斷 canvas 測試並斷言 raster 正確；另外用產品預設的選中片段測例驗證相同原廠尺寸運算。舊錯誤結果不當作容量證據。

負例：v0.7.8 原始碼在當時的 8 項新測試產生 27 個預期 assertion failures，無執行錯誤。四個獨立副本分別移除檔案識別、誤用索引快取、允許壓縮、改錯列寬，都被 assertion 攔下（見 `mutation-results.json`）。初次 fixture 的位元碼預期、串流 stub、veneer 執行白名單缺漏已修正；早期日誌保留，不計入成功結果。壓縮負例初次落入未模擬服務的錯誤也不計入，最終改由 prepare 返回值斷言捕捉。

## 成品與重現

由維護中的 `qs/build_slqs.py --out <fresh-directory>` 產生，`default-build` 與 `repro-build` 逐位元組一致，設定遷移測試也對新的凍結副本比對。只增加 v0.7.9 fixture，未覆寫任何舊版本。

- `SensorLab-IMX410_v0.7.9test.BIN`，184448 bytes。
- SHA-256：`389e93c2ff7ac0cd6ae9a75e26974d5d62a5ba0ec3d7a8342ebb512036f1b58b`。
- 預設設定版；使用者需重選 SensorLab 設定。只換 SensorLab BIN，QSContainer v0.3.4、AutoRun／LOADER 沿用。
- `source-before/` 保留修改前來源；`source-final/` 與 `source-manifest.json` 記錄最終來源；`REPORT.json` 彙整結果。

## 使用者待測

先用一段短的 2K／12-bit 未壓縮 CinemaDNG：選取片段、檢查單格、播放、暫停、退出回到 liveview；再比較原廠片與其他尺寸。既有片段可先試，不必為本版轉檔。若仍不能檢視，記錄 RES／DC／RECIPE／FORMAT／FPS 與錯誤出現階段。若凍結，停止追加播放測試並回報最後一步。

相機像素、DMA、聲音、持續播放、6K／RAW14 效能及先前黑屏原因均未驗證。不能宣稱所有格式已支援或黑屏已修復。Compression=7 等壓縮 CinemaDNG 與不符合幾何的檔案仍拒播；本輪不包含轉碼器或新解碼器。
