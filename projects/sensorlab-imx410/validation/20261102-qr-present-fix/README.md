# SensorLab v0.7.18test：QS QR 閃爍修正候選

只替換 SensorLab BIN；同一卡只保留一個啟用中的 SensorLab。QSContainer、AutoRun、LOADER、UI 沿用。
QR 仍直接顯示在主 QS，不需 AEL。QR 改為跟隨原生完成繪製的輪次，避免只畫 QR 卻提交舊 QS 背景。

交付的 BIN 保留上次 v0.7.17 提供檔案中的已驗證設定；沒有讀取卡上之後新增的設定。
離線驗證通過，未連接相機，實體 LCD 結果仍待確認。
可測：QS 停留、移動欄位、改數值、進出子選單與關閉後重開；核對畫面是否穩定及 QR 是否更新。

## 根因與驗證界線

原廠 C0528700 對每組 observer 回傳值做 OR，非零即 flush／commit／present。UIC mode 1 不畫圖，mode 0 的空 rect 也不畫圖；v0.7.17 的 QR 仍回傳 1，因此會提升未完成原生背景繪製的 back buffer。新版 bounded lookup C37B7048+18..158 的十筆 record，對應相同 framebuffer、mode 0/2、正寬高才畫 QR／還原。缺 record、其他 mode、空或負範圍皆不動作。

`test_qr_present.py` 執行實際 C0528700、C0721370 與 ring，故意在 back buffer 放不同舊背景；mode 1、空 rect 不提交，下一正常 draw 只提交一次且 QR 可解碼。restore 同樣延後到有效 draw。原廠 C05615E0 的 mode 1 零輸出另有實際執行。舊 v0.7.17 source 能編譯但在相同 native present test 失敗，記於 negative-tests.json。

原先 QRScreen 無條件換頁、所有初始 buffer 都相同，會漏掉此錯誤；現在 honoring drawer return，並顯式模型化原生重畫。UIC renderer/OS 服務仍為模型，實機 LCD 尚未驗證。

共 34 個 focused/preview 實際案例、8 個設定案例通過。第一個 focused 指令誤用兩個不存在的 Preview 類別；32 個實際案例通過，兩個正確方法另跑通過；原始失敗紀錄保留，未算成成功。最終 BIN 的 native present 6 cases、完整開機 4 cases（含原有 RAW14/ring、55 journal 還原）及 QSContainer 0.3.2–0.3.5 的 4 cases 通過。

保存設定檔 SHA256 `76bd93371324b4e5258028d13a68f7624101c75a5aff7c7b72055e9e9b8ca92c`；186132 bytes。設定 record SHA256 `71e67c9453e65b5044064f1e201b11fa14e544729ed999c0ef2f52330ee1fe6c`。預設版 SHA256 `f037e8d7624ebdddbbb083555926630aba18efb77b3d2d280a5e614010c25797`。原廠 ISPC、原始 BIN、共用載入器與 QSContainer 未改動；未操作相機、SD 卡或 USB。
