# ISP Lab 接手驗證 — 2026-10-26

接續 Claude 2026-10-25 的 EP83/LV 上機工作。這輪完成主機端收尾修正、待機 LV、自動啟停，以及停錄後 CDNG 推送與卡檔核對。
**推送已可用；RAW 掃描找到的 DNG 仍是候選，不能全部當作已寫卡的影格。**

## 實際環境與範圍

- 沿用既有 fpshd 3.3.0、開發版 USB shell 與 ISPC；沒有換 daemon、部署 BIN、重開或修改相機設定。
- 本次開機識別字 `LOAD_DONE_US=0x003D6224`。`LOAD.LOG`：ISPC `0xC4FEC1C0`，shell `0x456BBAC0`，shell 12 claims。
- [ISPC 完整讀回](ISPC.BIN) 11244 B，SHA-256 `87558560117f5d8c398ff81a258dd663b8c7de60d59f8da2b343c3e49a872c7b`，與 `sup/build/build-ctl.json` 相同。
- 選單 getters：`SetMovRecSize=2`、`SetMovRecFormat=0`、`SetMovFramerate=3`、`SetMovCinemaDNGQuality=0`。
  **選單值不足以認定是原廠 FHD：實際本次 DNG 是 3024×2010、12-bit、30000/1001 fps**，卡上有 RES-Custom 等 sup。
  這輪不是原廠 FHD 的工具校準，也沒有驗證幾何來源。

## 主機端修改

1. `push_rx.listen()` 在 END83 後等完要求的 quiet 時間才返回；舊版 `q=500` 後立即清理，會撞上 daemon 的 `ERR quiet`。
   若串流中斷，先排入只在主機處理的 STATUS，確認單執行緒 daemon 已離開 LISTEN83，再等待 quiet；確認失敗則回報 `ListenerUnsettled`，禁止接著寫相機。
2. `lvpush_live.py` 即使接收、arm 或中斷出錯，也嘗試關閉取樣並保存成功或失敗報告；未收齊或計數錯誤不回報通過。
   不接管仍在跑的 sampler，不混用非空輸出資料夾。
3. `ispl.flush()` 沿用共用 `callfn.code`，移除額外的 `ispl.callfn.code`。
4. ISPC 不配置也不釋放 ISPL sink 的影像記憶體，所以 `--ctl-only take` 不受舊 `.ispl_alloc.json` 阻擋；舊檔及指標原封保留，沒有釋放舊開機的地址。

**更正舊交接的越界推定**：當時 `ispl.callfn.code` 是 `0xC072EBA0..0xC072EC40`，合法終點為 `0xC072EFB4`，並未越界。
重複配置浪費 160 B，但「cave 滿／配置器漏擋越界」沒有證據。原始錯誤為 `callfn: still short after 6 passes`。
程式確實漏等 quiet [C]；本輪同時修正等待與重複配置後收尾成功 [M]。沒有重跑錯誤版本做真機 A/B，不能把原始失敗唯一歸因給 quiet。

## 待機 LV [M]

[lvpush.json](../20261026-lvpush-01/lvpush.json)、[影像檢查](../20261026-lvpush-01/image-check.json)、[接觸表](../20261026-lvpush-01/contact-sheet.jpg)。

- 指令：`cd host && python3 -B lvpush_live.py ../validation/20261026-lvpush-01 --count 8 --every-ms 250`。
- 8/8 張，1620×1080 YUYV，總計 27,995,648 B（含 FPP1 標頭）；CRC 全通過，無跳號、截斷、重同步或剩餘資料。
- 8 張雜湊都不同，亮度有變化，stride 自檢全通過；畫面偏暗且失焦，**只能驗證取樣／傳輸，不能拿來量 MTF、AF 或畫質**。
- 相機取樣間隔 252005..255015 µs；收尾 `lv_push=0`，新增 skip/bad/error 都是 0。

## 控制 task 自動錄影 [M]

[before.json](../20261026-ispc-take-01/before.json)、[after.json](../20261026-ispc-take-01/after.json)。

- ISPC 控制 task，`start_ms=3000, rec_ms=2000, focus=False`；錄影仍由原有寫入路徑寫卡，沒有 ISPL sink，也沒有借大塊記憶體。
- arm 後主機靜默 20 s；結束才查狀態，開始與存檔旗標都是 1、`ctl=done`、按鍵共 2 次。
- `t_stop-t_rec=2625 ms`，含停止與存檔等待，不等於精確曝光時長。新片段為 `\CINEMA\A001_022`，已讀到第 63 號檔案，未驗全片幀連續；片段保留在卡上。
- 沒重現停止卡住；**這只能證明目前 ISPC 工作，不能單憑這次測試確定舊 ISPL 事故原因**。

## 停錄後 CDNG [M]

[cdngpush.json](../20261026-cdngpush-01/cdngpush.json)、[卡檔匹配](../20261026-cdngpush-01/match.json)、[依時間碼推算的檔名](../20261026-cdngpush-01/card-plan.json)。

- 停錄超過 10 s、RAW used=0；使用本次 LOAD.LOG 已知的 ISPC 位址，避免先用 getfile 配置 RAW 而覆寫殘留影格。
- 設 `cd_after_ms=0, cd_max=32, cd_state=0`，最後寫 `cd_go=1`；主機 LISTEN83 純收，quiet=1000 ms。
- 掃描及推送相機計時 770684 µs；13 個候選、41,325,152 B（含標頭），13/13 收齊、CRC 全通過，沒有傳輸錯誤、跳號或截斷。
- 由卡上第一幀的 TimeCodes 計算候選的幀號；只讀明確檔名，**沒有列舉片段目錄**。第一幀參考是 4 MiB 前綴，僅用於檔頭；其餘比較檔案完整讀回，均小於讀取上限。
- **10/13 與卡檔逐位元組相同**：52、55..63 幀。
- 3 個未通過卡檔核對：
  - `cdng_000000.bin`、`cdng_000009.bin`：第 63／62 幀的未壓縮版本（9,200,304 B）；卡上是壓縮版本（2,083,840 B）。
  - `cdng_000002.bin`：第 54 幀，檔頭及長度像壓縮檔，但從 82944 (`0x14400`) 開始與卡檔不同，預期 JPEG 起點是 `FF D8`，候選卻是 `10 61`。
    [M] 可證明不是卡檔；處理中殘留／後續覆寫是 [I]，尚未追出精確時點。

**下一步是影格有效性與版本篩選，不能把「最新 DateTime + TIFF 長度合理」當成最終檔案完整性證明。**
本次沒有改相機端掃描器來臆測最終版本，也沒有把 3 個差異說成 USB 傳輸損毀。

## 驗證與收尾

- 主機端：`cd host && python3 -B -m unittest test_ispl test_lvpush_live test_push_rx test_lcd test_rawpool`，**46 項通過**。
- ARM 離線模擬：`cd sup && python3 -B -m unittest test_card.ControlTests test_card.CtlOnlyTests`，**9 項通過、無跳過**；相機端來源未修改。
- 隔離的記憶體內突變：移除 quiet 等待、移除錯誤時停用、恢復 ISP 額外 claim，三項都被測試抓到。
- [final-state.json](final-state.json)：待機，`echo=0xC03D99A0`、LV 關閉、`cd_go=0`、`cd_after_ms=0`、`cd_state=done`、RAW used=0。
- 只有主機程式與研究紀錄改動；不需要更新 AutoRun 或 BIN，沒有 commit/push。

後續優先：離線重播這 13 個候選與 11 個卡檔，研究如何排除無效壓縮資料／挑最終版本；再做原廠模式校準及錄影中 LV。
**本輪沒有驗證錄影中推送 LV、AF、MF 放大、UHD/FHD/OG3K 三組原廠校準、回放或 ISP 畫質規則。**
