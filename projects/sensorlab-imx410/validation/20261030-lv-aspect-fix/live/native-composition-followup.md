# Native composition follow-up — 2026-10-30

v0.7.3test 本輪**未驗收**。本筆記只記離線 source／截圖證據；未新增 USB 操作或修改產品。
`final-verification.json` 已記錄 v0.7.2test 完整回退、active 0、63 個 selection words 與測前相同，以及四個卡片檔完整讀回一致。

## 已證實的欄位與呼叫鏈

- `XC_DisplayZoomParameterW71C1__v4`（`out/decomp/full/blk_c03.c:5371`，C0306D90）先從裝置取得比例，再把 `param_1+0x14` 的來源尺寸經 C02DB140 分類、C02DAFA0 取比例，呼叫 C02F43A8。候選的 H_ASP3 在 C0306DB0 改掉這次分類結果；守衛只有 live slot／is169／playback，**沒有 consumer／layer 身分守衛**。
- C02F43A8（`blk_c02.c:159680`）以 C02F49F0 → C02F4890 讀 destination 六個欄位：`+0x78/+0x7A` 是完整尺寸，`+0x7C/+0x7E` 是可見尺寸，`+0x80/+0x82` 是偏移。C02F4410 只改其本機矩形副本，再交給 C02F4A90。
- C02F4A90（`blk_c02.c:160004`）**只寫 descriptor 的 `+0x7C/+0x7E/+0x80/+0x82`**。這條 fit 路徑沒有直接改來源尺寸 `+0x60/+0x62`、完整 destination `+0x78/+0x7A` 或已證明的 pitch 欄位。不能由截圖重複直接宣稱 H_FIT 改了 framebuffer pitch。
- 共用送件路徑 C02E85C8（`blk_c02.c:149783`）把 descriptor 放在 message `+8`，先 C02F4098，再 C02F3ED0。顯示管理器的 C02E6B90（`:148547`）將 message 的 source／destination 六欄各自解包，經 C02E7518（`:149029`）通知 observer。它可證明 fit 結果進入顯示管理流程，**尚不能證明這次執行對應 video、OSD、實體 LCD 或截圖哪一個 consumer**。

H_FIT 的 `param_2 == slot.asp` 守衛只證明比例 pair 的擁有者；H_ASP3 本身會把 pair 送進 v4。兩者合併仍不能證明目的 descriptor 屬於應裁切的 video layer。

## 截圖證據與目前界線

`screenshot-review.json` 已記錄：H3800 LV 的 643 列週期、39 列重複區、RGB MAE 1.334/255；H3500 LV／QS 為 592 列週期，AF marker／焦點框也重複。寬度案例則顯示有效圖像靠左、右側黑區。這證實**取得的 SS JPEG 並非正確置中結果**。

SS 檔仍為 1024×682；重複週期接近裁切後應有的有效高，支持「擷取來源的有效尺寸／viewport 與 SS 輸出尺寸不同」這個待查假說。它不構成 capture-only 或實體 LCD 損壞的證明。實體 LCD 的人眼回覆尚未取得。

CAPTUREON → RecMgr screenshot event → JPEG 擷取來源／stride 的完整 xref **未完成**。目前不把其他固定 1024×682 routine 冒認成這條路徑。

## 下一個最小離線缺口

現有測試從 C0306DB0 的兩個 BL 或 C02F4410 開始，驗的是比例 pair、整數 fit 與守衛，未涵蓋 descriptor 建立、完整 v4 呼叫、observer 消費、OSD 合成或 SS 讀取。

下一步應先建立帶 consumer 身分與完整 descriptor 的 native fixture，追 C02F3ED0／v4 → C02E6B90 的實際輸出，獨立比較 video、OSD 與 screenshot 的完整尺寸、可見尺寸、偏移及 stride；加入「只有 video viewport 可變，OSD／SS 完整 canvas 不隨 DC 縮短」的失敗回歸。CAPTURE xref 補齊前，不以再改尺寸或再次上機來補這項證據。
