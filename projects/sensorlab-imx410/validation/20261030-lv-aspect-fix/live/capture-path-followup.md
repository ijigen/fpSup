# CAPTURE / SS 截圖路徑待查（2026-10-30）

本輪 v0.7.3test **未驗收**。本文件只整理離線讀到的原廠程式，沒有操作 USB、相機或修改產品。
Root 已回報：試驗完成後回退本輪測試前的 v0.7.2test 卡片檔案，標準 reboot，完整讀回與原檔一致；本輪相機已釋放。

## 已有觀察

- Root 回報 H3800 的 SS 影像在約第 643 列回捲，H3500 在約第 592 列回捲；JPEG 仍為 1024×682。
- 這兩個高度接近離線計算的裁切影像高度（約 642／591 px）。這是相關性，不能直接推成截圖 stride 錯誤。
- 實體 LCD 的結果尚無使用者確認。SS 裡有效尺寸跟著裁切改變，不能單獨證明 LCD 置中、完整輸出或無回捲。

## 已確認的固定 1024×682 原廠候選

以下來源均為 `/Users/dido/Developer.localized/SIGMAfp_re/out/decomp/full/` 的現有反編譯檔。

| 函式／資料 | 原始碼位置 | 已確認內容 | 尚未證明 |
|---|---|---|---|
| `FUN_c042f990`，`0xC042F990` | `blk_c04.c:31524` | `param_1==0` 時在鎖 `0xC375C278` 內呼叫 `FUN_c02e5b38(0xC375C240,0x400,0x2AA)`；另一分支在鎖 `0xC375C270` 內初始化 `0xC375C258` 為 2048×1364，傳回相應結構位址。 | 這個 drawer/rectangle 路徑是否就是 CAPTURE 的 SS 來源。 |
| `FUN_c02e5b38`，`0xC02E5B38` | `blk_c02.c:147689` | 單純寫六個 u32：`[width,height,0,0,width,height]`。因此上一列的 1024×682 是明確的矩形尺寸，不是由字串名稱猜出。 | 這個六字結構不是已確認的 framebuffer 位址／stride 描述子。 |
| `FUN_c04217f0`，`0xC04217F0` | `blk_c04.c:21136` | 呼叫 `FUN_c042f990(param_2)`，複製其六字結果到呼叫者物件，另外設定第 6／7 字。 | 尚無 CAPTURE→此函式的完整呼叫鏈。 |
| `FUN_c04a6b20`，`0xC04A6B20` | `blk_c04.c:124640` | `param_1+0x5C` 非零時，明確建立 `local_604=0x400`、`local_600=0x2AA`，交給 `FUN_c04d1460`，再呼叫 `FUN_c04d14c8`。 | 不能稱它為 screenshot handler；目前所見呼叫者／字串鄰域屬 LV operation。 |
| `FUN_c04d1460`，`0xC04D1460` | `blk_c04.c:158082` | 將輸入二字尺寸複製到輸出前兩字，加入另外三個值，再由 `FUN_c04d1630` 產生兩字。 | 尚未識別 CAPTURE 使用的 source address、pitch、像素格式、JPEG 輸出欄位。 |

`FUN_c04a6b20` 的相鄰流程尤其需要保留疑問：`FUN_c04a6ef8`（`0xC04A6EF8`，`blk_c04.c:124812`）把狀態 0／1／2 轉成 100／400／800；
呼叫者 `FUN_c04a5fc8`、`FUN_c04a6028` 使用 `param+0x18` 與 `param+0x5C` 控制它。這較像 LV 放大操作的尺寸路徑，**不是已找到 SS encoder 的證據**。

## 已找到的標記，未接成完整 xref

- 韌體字串 `CAPTUREON` 在 `0xC0BB7C8C`；鄰接 `CAPTUREOFF`、`MODEDIAL`、`CMDDIAL1/2/3`。
- `INTR_REC_SCREENSHOT` 在 `0xC0B9FD5A`；`INTR_REC_SCREENSHOT_SAVE_FILE` 在 `0xC0B9FD6E`。
- `SS__` 字串在 `0xC2E399EE`。目前找到的 `FUN_c069f8d8`（`0xC069F8D8`，`blk_c06.c:129838` 附近）逐字元、忽略大小寫檢查這個檔名前綴；它是檔案分類，不能當成截圖生成函式。
- 尚缺：CAPTURE key event → screenshot request/worker → image source acquisition → layout/stride handling → JPEG encode → `SS__nnnn.JPG` 的連續鏈。

## 推論與後續邊界

固定全畫面尺寸的 consumer 若收到改變的有效高／pitch，確實可能重讀舊資料或錯行；但目前沒有對上 SS 的實際 framebuffer descriptor，
也沒有證明 SS 與 LCD 掃描使用相同／不同 consumer。不得把這個可能性寫成根因，更不能據此把實體 LCD 排除。

後續若另獲准做只讀比對，可考慮：

- `0xC375C240` 與 `0xC375C258` 各六個 u32：比較原廠／custom 時候選矩形；它們是尺寸結構，**不要把前兩字當記憶體指標**。
- `0xC375D840+8`：既有 apply 的目前 LV canvas 指標（`apply/ap.c` 的 `AP_LV_MGR`）。先驗指標落在合法 RAM，再讀必要欄位；不把快照宣稱成原子取樣。
- SensorLab 自有 block／建置 metadata 的目前狀態與輸出 template，配合既有 `sq_test17/18`，確認本次 producer/consumer 尺寸。

以上只是未執行的讀取候選。不要為了取得它們呼叫 allocator、draw/fit 函式、CAPTURE recovery 或任意 MMIO。
優先完成離線 CAPTURE xref，再決定最小讀取欄位；LCD 是否正常仍需獨立的實體觀察。此次停止在「未驗收、已回退」結論。
