# isp-lab 的三個推送呼叫端：掛點與資料位置（2026-10-24，離線 RE，未上機）

協定：PUSH_PROTOCOL.md（FPP1 v1）。引擎（相機端 push()）由 sigmafp-re-40 做；這裡只查「推什麼、從哪裡拿、何時推」。
證據：[C] 反編譯／反組譯、[M] 上機、[I] 推論。

**2026-10-26 更新**：[接手驗證](../validation/20261026-resume-preflight-01/RESULTS.md)。待機 LV 8 張且清理通過；ISPC 無借影像記憶體自動啟停通過；停錄後 `cd_go` 推出 13 個候選，10 個與卡檔逐位元組相同。
另外兩個是未壓縮版本，一個保留壓縮檔頭但 JPEG 資料不符；掃描器還缺完整性與最終版本篩選。實際是 3024×2010，不能算原廠 FHD 校準。

## 1. LV 顯示 ring（錄影中、半按、放大）——**不需要 hook**
- 輸出描述元 `0xC30255B4`（3 個，間隔 0x80）：[3] 寬、[4] 高、[8] 格數、[9..] handle（位址 = 0x40000000 + 4·handle）[M]（lcd.py 10-23）。
- 第 31 字（`0xC3025630`）＝ `FUN_c01822b8(通道)`，**直接讀 DMA 通道硬體暫存器的目前格索引**：
  通道 = `[0xC31DF8D8] + 2`（≥ 7 時用 8），暫存器 0x301821E8／0x301822E8／0x301832E8…（通道 2、5 取 `& 0x1F`，其餘 `& 7`）[C]
  （blk_c01.c:126255 `FUN_c0181e..`，`FUN_c01822b8`）。描述元這個字只在有人呼叫 getter 時更新——10-23 讀取前後 1→3 就是這個。
- 所以「最新寫完的一格」＝（目前索引 − 1）mod 格數 [I]。**錄影中由 sup 的控制 task（pri 25，每 20 ms 醒一次）定時讀暫存器、推上一格**，
  完全不碰顯示程式碼。一格 2.9 MB，USB 約 10 ms 推完；ring 4 格，60 fps 下被覆寫前有 ~50 ms [I]。
- ~~待驗~~（10-24 已驗，見下）：連讀幾次暫存器，看索引是否 0..3 循環、速率等於 LV 幀率；`[0xC31DF8D8]` 在待機／錄影／放大／HDMI 時的值。
- 主機端 lcd.py 也能用同一招挑「剛寫完」的那格（目前固定讀第 0 格）。
- **已實作（10-24，離線）**：`sup/ix_wr.c` `ix_lv_step`，ix_cap layout 3（`lv_push lv_every_us lv_lag lv_max` 主機寫；
  `lv_t_last lv_n_sent lv_n_skip lv_n_bad lv_n_err lv_last_reg lv_last_addr` 相機寫）。每一步（20 ms）都跑，與 ctl 狀態無關；
  引擎入口由主機寫進 `lv_push`（0 = 關），呼叫 `uint32_t push(ix_push_req *)`，回 0 送出／1 忙跳過／其他 = 錯。
  通道表照抄 FUN_c01822b8（0..8）；**10-24 實測（validation/20261024-lvslot-01）暫存器分三欄：byte2 正在寫、byte1 上一格寫完、byte0 顯示中**，
  所以推 byte1（lag 1）、lag k = 再舊 k−1 格；描述元不合理（n∉1..8、寬高不在 16..4096、
  一格 > 16 MiB−1 KiB、handle 0）就不推、記 lv_n_bad。flags 只填 bit0（我們的 ctl 在 REC）；半按／放大位元還沒有來源。
  unicorn `LvTests` 9 項 + 突變 `IX_MUTANT_LV_CURRENT`（推目前那格）會被抓。ISPC sha ec8ad26e…、ISPL f862c9d5…。
- 已知限制：ctl 跑 movrecstwai／movsavewai（阻塞最多 60 s）時不會取樣，所以錄影剛開始、剛停止那段沒有 LV。

## 2. BUFA1（待機 RWZM 輸出）
- 待機固定一格 0x30182280 → 0x4A900380，8-bit Bayer 2016×1344，不輪替 [M]（validation/20261024-bufa1-01）。
- 不輪替＝讀時可能正在寫（撕裂）。推送時在 flags 標 bit3；量測時比對兩次。
- 由控制 task 在主機要求時推（mode 1 可；待機不是錄影中，主機可以觸發）。

## 3. 停錄後的 CDNG 幀——`0xC358DCC0` 這條線索作廢（10-25 離線）
- `0xC358DCC0` 是 **StillRecFunc.cpp 的類別**（assert 字串 `src/framework/recMgr/src/StillRecFunc.cpp`），由 `movRec`（MovRecFunc.cpp）
  在錄影開始時配置 [C]：`FUN_c0386198` 先呼叫 `FUN_c0386540` 拆掉舊的 8 個物件，再配 8 個（或 5 個）0x654 B 物件，各帶一塊 class 10 緩衝。
- 用它的只有錄影狀態機的 REC／RECHOLD／RECSTART／RECWAITAF／THR 幾個事件：v16 → `FUN_c0386388`（另配一塊 +0x54 緩衝、交給 C0383910），
  v36 → `FUN_c0385e08`（逐一處理 +0x5c 狀態不為 0 的物件、寫檔，最後 `FUN_c0386540` 全部拆掉）[C]。
  形狀是「**錄影中拍靜態照**」的緩衝池，不是 CDNG 幀的環 [I]；10-24 待機實測 8 個指標全 0 也跟這個一致。
- 它仍然重要：**錄影開始時從 class 10 定量配這 8 塊**，就是 memory allocator-not-across-recording 裡 `lack_mem` 的那個配置——
  isp-lab 任何會佔 class 10 的東西都會讓錄影起不來。
- **新路線（10-25，不用 hook）**：原廠每一幀的 RAW 是一塊獨立的 class 10 配置（C037A990，frame+0x68；DNG 在配置 +0x2000，lossless-sup C1），
  寫完卡就還回配置器（C03777B8）；配置器是 first-fit 鏈（FUN_c00104a8，區塊頭 0xDEADBEEF、[1] 大小、[3] 下一塊），**釋放不清資料**；
  停錄後 `memmgr bufuse` 的 RAW used = 0（lossless-sup 10-12：MOVIE_REC_DNG 模式 total 742 MB）。
  → 停錄後最後幾幀的 DNG 應該還完整躺在 RAW 區，直到下一次錄影開始配置 [I]。
  驗證工具 `host/rawpool.py`（離線 6 測試＋突變）：probe 讀類別表 0xC30739DC[10] 與鏈；scan 在待機用 MEM1 讀整個 RAW 區（~2 s），
  收下每個 0x40 對齊、像 DNG 的緩衝；match 跟卡上同一段的檔案比 sha256。全部成立後，相機端「停錄後推 CDNG」就只是
  在控制 task 裡做同一件事（掃描＋push），完全不碰錄影路徑。
  **10-25 上機成立**（validation/20261025-rawpool-01）：FHD 53 幀的一段，停錄後 RAW 區裡找到 **最後 14 幀（40–53）與卡上檔案逐位元組相同**；
  另有昨天 OG3K 那段的 14 幀還在更高的位址（撐過重開機），所以相機端掃描要挑最新那一段。
- **相機端已實作（10-25，離線）**：`sup/ix_cdng.c` `ix_cdng_run`（控制 task 裡）：從類別表找 RAW 區、0x400 步長找 `II*\0`、解 IFD0 大小與 DateTime，
  第一輪找最新 DateTime、第二輪只推那一段（mode 1、source 4、fmt 5、aux0 = 位址），最後還原引擎占用的表。觸發：主機寫 `cd_go`（手動錄的那段），
  或 ISPC 自己錄完 `cd_after_ms` 之後。unicorn `CdngTests` 4 項＋突變 `IX_MUTANT_CD_ALL`（不分段落）。
- 舊退路（要 hook，排最後）：寫入層交出每幀片段的地方（ULWR 掛過 C063F048／C063F140）記下取樣幀的 (位址, 長度)，
  停錄後再確認那些位址還沒被蓋。RAW 池本身在哪、停錄後保留多久，要另外找（下一步離線）。

## 下一步（10-26）
1. 離線重播 `validation/20261026-cdngpush-01`：排除無效 JPEG／區分同幀壓縮前後版本；不要把 DateTime 最新等同卡檔完整。
2. 尚未驗：`cd_after_ms` 自動觸發、錄影中 LV、原廠 UHD/FHD/OG3K 工具校準、AF／放大／回放。
3. 進行新一輪 RAW 殘留掃描前，先保存本次 LOAD.LOG 位址；`getfile` 會配置 RAW，可能先覆寫要研究的殘留資料。10-26 上機用既知位址，推完才讀卡檔。
