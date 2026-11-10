# Lossless 14-bit（v0.3.2test，2026-11-10，離線）

Bei：「讓 lossless 支援 14bit」。14-bit 的來源只有 Sensor Lab 的 1:1 真 14（原廠位深設定仍是 12，
畫布平面碼 7/8 → Sigpro 格式碼 1）；原廠 CinemaDNG 錄影沒有 14-bit。
調查（為什麼原本整段不壓）見 [projects/sensorlab-imx410/notes/LOSSLESS_14BIT.md](../../projects/sensorlab-imx410/notes/LOSSLESS_14BIT.md)。
驗證紀錄、BIN sha256、上機程序：
[projects/sensorlab-imx410/validation/20261110-lossless-14bit/](../../projects/sensorlab-imx410/validation/20261110-lossless-14bit/)。

標記：[驗] 讀碼並由測試執行（host／ARM／Unicorn 跑韌體映像）；[推] 推論；[待] 要上機。
**未上機。**

## 1. 改了什麼

| 檔案 | 改動 |
|---|---|
| `control.c` `capture_eligible` | 位深 `10/12` → `10/12/14`；新增「列距一致」閘：`((width × bits) >> 3) & 3` 非 0 就 UNSUPPORTED |
| `native/codec_job.c` `fpl_codec_source_bytes` | 同一條列距閘（引擎邊界的第二道），回 0 → 該幀不 hold、原樣 RAW |
| `native/workspace_layout.h` | 只改註解（14 已在 planner 裡） |
| `loader-v4/names_v4.py`（本機） | LOSS `0.3.1` → `0.3.2test`（檔名 `Lossless_v0.3.2test.BIN`；header 的 VERSION=1 不變） |

其餘路徑本來就吃 14：`producer_facts.c`（格式 1 → 14）、`codec_job.c`（格式碼直接當引擎位深碼）、
`workspace_layout.c`（`width×bits/8`）、`frame_hold.c`（每幀比對寬／高／格式字）、
`header_tag.c`（壓縮 IFD 原樣搬 root IFD 的 BitsPerSample=14、WhiteLevel 等，只換掉 strips 與 Compression）、
`play_decode.c`（`format_code(14) = 1`）。**輸出沒有 16 MiB 上限**：v0.3.x 的引擎直接寫進備用幀
（`spare`，一整個 RAW 幀大小，class 10），壓不下（引擎錯誤位元）就該幀照原樣 RAW。

### 列距閘為什麼要加（10-bit 也受益）

- 引擎讀來源的列距 = `bits × width / 8` bytes：`C062FFF8` 把 `300D006C` 設成 `bits×width/16`（16-bit 單位）
  [驗：`test_producer_facts.test_c062fff8_programs_the_source_pitch_as_bits_times_width` 從映像執行，12/14/10 bit × 三種寬]。
- Sigpro 點陣（`C0135D40`）每列補到 4 bytes [驗：同檔 `test_format_1_rows_…`，Unicorn 跑韌體]。
- 12-bit 寬 8 的倍數永遠一致；**10／14-bit 只有寬是 16 的倍數才一致**。寬 ≡ 8 (mod 16) 時引擎會把每列 2 bytes 補白當像素讀
  ──壓出來的檔可解但畫面錯位。原本 10-bit 沒擋（FHD/UHD/6K 寬都恰好是 16 的倍數所以沒踩到）。
  Sensor Lab 所有 1:1 14-bit 配方的寬都是 16 的倍數（6048、5040、4144、4112、3984、3856、3024、2576、1936、1296）。

## 2. 引擎吃的 14-bit 格式 = Sensor Lab 平面碼 8 的點陣

證據鏈：

1. **原廠靜態照就是這樣餵引擎**：`StillCr` 的 `FUN_c037e7ac` 段把 `frame+0x10` 寬、`+0x14` 高、**`+0x30` 格式碼**
   原樣當 F_INIT／F_ENC 的位深碼，來源 = `frame+0x68` 點陣，256×256 tile [C，out/decomp/full/blk_c03.c:85600–85630]。
   `frame+0x30` 就是 `frame+0x10` 描述子的第 8 字 —— Lossless 的 `producer_facts` 與 `frame_hold` 讀的同一個字。
   靜態照輸出 14-bit LJ92（`_SDI0011.DNG` SOF3 P=14）→ 格式 1 的點陣就是引擎的 14-bit 輸入 [驗 檔案]。
2. **格式 1 的位元排列 = TIFF 的 MSB-first packed 14**：Sensor Lab 的未壓縮 14-bit 幀（`B_A001_265_000003.DNG`，
   6048×4040）就是那塊點陣原樣寫出，StripByteCounts = 6048×4040×14/8 正好（列距無補白），
   LibRaw 讀出的值 == 自己 MSB-first 解包的值；LSB-first 解包則不同 [驗：`test_lossless14_roundtrip`]。
3. **列距**：見 §1，寬 16 的倍數時兩邊相同 [驗]。
4. 每幀格式比對：REC 時查到的是格式 1、每幀描述子也是 1 才 hold；查到 0 而幀是 1（或反之）就整段 RAW、不會壓錯 [驗 碼＋`test_frame_hold`]。

[待] 仍未直接比過「引擎讀 format 1」與「DNG 寫 format 1」是同一個解包（靜態照沒有同幀未壓縮版本可比）。
1＋2 合起來很強，但要上機看第一個壓縮幀才算定案（上機程序第 3 步：錯的話是滿畫面雜訊或斜切，一眼可見）。
另：Lossless 查描述子用的是 `C0437140(&obj, 2, settings, 3)`；Sensor Lab 真 14 時它回 1 只在 R86 錄影分支驗過 [推]
──若回 0，結果是「每幀都不 hold、整段 RAW」（安全、但沒壓），`card_status` 的 `hold.refused_by` 會是 descriptor。

## 3. 離線 round-trip（真幀、逐位元）

`native/test_lossless14_roundtrip.py`：Sensor Lab 真 14 的 6048×4040 幀 → 依 `tile_grid.h`（編譯後呼叫）切 512×512、96 格 →
照引擎格式 LJ92 編碼（2 分量、predictor 1、P=14、每格自己的 Huffman；向量化版，逐位元組等於 `research/slimRAW/ljenc`）→
補到 1 KiB → `header_tag.c`（相機原始碼，host 編譯）在韌體式模板裡 prepare + complete →
**LibRaw 解碼 == 原幀每一個樣本**；另用 repo 自己的 `ljpeg.decode_tile` 解一格。header_tag 的三個突變都會讓它失敗。
這幀（偏暗）：payload 19,875,840 B，**2.15:1，6.51 bpp**。

`test_card_emulation`：同一個 14-bit 模板經 ARM 編譯的卡（Unicorn）走 observer：壓縮 IFD 是 6048×4040、BitsPerSample 14、Compression 7、四個 tile 標籤、沒有 strips。

## 4. 吞吐與寫入（估算）

引擎 14-bit 實測 169.7 Mpix/s（6064×4042 靜態，144 ms）；每格另加 0.137 ms（TILE_GRID 擬合）。
壓縮後大小：保守 8.5 bpp（Sensor Lab 格子的 1:1 14-bit 公式）／實測 6.51–8.4（上面那幀與 6K 靜態照）。
寫入：SD 94 MB/s、SSD 390 MB/s（全壓縮、不計 cluster 補齊）。

| 1:1 14-bit | grid | RAW MB/幀 | 引擎 ms → 上限 fps | LL MB/幀 (8.5 bpp) | 配方最高 fps | SD 全壓可持續 fps | SSD 全壓可持續 fps |
|---|---|---|---|---|---|---|---|
| 6048×4040 | 512×512 ×96 | 42.8 | 161 → **6.2** | 26.0 | 19.0 | 3.6 | 15.0 |
| 6048×3412 | 512×496 ×84 | 36.2 | 137 → 7.3 | 22.0 | 22.4 | 4.3 | 17.7 |
| 6048×2560 | 512×512 ×60 | 27.2 | 101 → 9.9 | 16.5 | 29.6 | 5.7 | 23.6 |
| 5040×2844 | 512×480 ×60 | 25.2 | 95 → 10.5 | 15.3 | 26.7 | 6.1 | 25.5 |
| 4112×2170 | 416×448 ×50 | 15.7 | 62 → 16.2 | 9.6 | 36.2 | 9.8 | 40.8 |
| 3856×2170 | 352×448 ×55 | 14.7 | 59 → 17.1 | 9.0 | 36.2 | 10.5 | 43.5 |
| 3024×2010 | 512×512 ×24 | 10.7 | 40 → 24.8 | 6.5 | 39.0 | 14.4 | 59.6 |
| 2576×1450 | 448×496 ×18 | 6.6 | 26 → 38.4 | 4.1 | 52.9 | 23.2 | 96.3 |
| 1936×1090 | 512×368 ×12 | 3.8 | 15 → 66.8 | 2.3 | 68.7 | 40.4 | 167.8 |

（fps 上限來自 isp-lab `quality.qualities`，VMAX 最小；VMAX 可加大到 16384 所以每個配方都能降速。）

**超過引擎速度時**：沒有拒絕邏輯，也不丟幀 ── `frame_pipeline` 的設計是引擎忙時新到的幀**原樣 RAW** 通過
（同一段裡混合壓縮／RAW），只是平均檔變大。6048×4040 14-bit 在最高 19 fps 約 1/3 幀壓縮、2/3 RAW。
**媒體跟不上時**：跟原廠未壓縮一樣，錄影緩衝滿了相機自己停錄（vbuf）。Lossless 只減少要寫的量，不加任何新停錄條件。
`control.c` 只要求 fps 非 0，不做速度拒絕；本版不加（加的話是改產品行為，要 Bei 定）。

**記憶體**：每段兩個備用幀（兩條 lane），各 `0x15400 + align512(raster)`，class 10。
6K 14-bit = 2 × 42.8 MB ≈ 86 MB，從錄影 RAM 緩衝（約 600–750 MB）裡扣。配不到 → 該段整段原廠 RAW（`spare_failed`／`lane_b_failed`）[驗 碼]。
批次寫入：被接受的壓縮段把 0xC0B9E5D8 設成 clamp(3×原始檔, 4 MB, 64 MB) → 6K 14-bit 直接 64 MB（每批約 2–3 幀）[推，沿用 EARLY_STOP_94]。

## 5. 測試（2026-11-10）

見 validation 目錄的 README。新增／改動的案例：control（14 候選、列距閘、ARM 版 direct control）、
rec_workspace（6K 14-bit 准入、8 mod 16 與 16-bit 拒絕）、codec_job（格式 1 送引擎、96 格、列距閘＋突變）、
producer_facts（Unicorn 跑 `C0135D40` 與 `C062FFF8`）、frame_hold（14-bit fixture：告訴引擎的長度、同幀、格式字不同不 hold）、
round-trip（上面 §3）、card_emulation（14-bit 模板）。

## 6. 未決（Bei）

1. 6K 14-bit 在 SD 只撐約 3.6 fps、SSD 約 15 fps（且引擎只到 6.2 fps）；要不要在 fps 超過引擎速度時乾脆不開（現在是混 RAW）？
2. 兩個 43 MB 的備用幀會吃掉錄影緩衝；6K 是否改成單 lane？（要量）
3. Sensor Lab MB/s 格子：14-bit 比率已用（+2 bpp）；但它的 `LL_MAX_FRAME` 16 MiB 規則（壓縮幀 >16 MiB 就顯示 `LL —`）
   對 v0.3.x 不成立（沒有 16 MiB 上限）。目前 6048×≥~2600 的 14-bit 會顯示 `LL —`。等 6K 上機後再決定拿不拿掉。本次未改 Sensor Lab。
4. 10-bit 寬 ≡ 8 (mod 16) 現在會被拒絕（原本會壓錯）。這是行為改變，但只影響原本就會出錯的寬度。

## Bei 的決定（2026-11-10）
1. fps 超過引擎速度：維持「同一段裡壓縮與未壓縮混在一起」，不整段關壓縮。
2. 6K 14-bit 兩個備用幀（約 86 MB）：先上機量錄影緩衝的影響，再決定要不要改單 lane。
3. Sensor Lab MB/s 格的 16 MiB 單幀規則：等 6K 上機測試結果再決定。
4. 10/14-bit 列距不對齊的寬度改成不壓：已向 Bei 解釋，待確認。

## 7. 列距閘測試開關（Bei 2026-11-10 追加，同一個 0.3.2test BIN）

目的：上機直接看 10／14-bit、寬 ≡ 8 (mod 16)（例 1928）硬壓會不會歪，不用另建 BIN。

- **開關**：卡狀態裡的 u32 `pitch_test`（`native/card.c` struct `fpl_card`）。0 = 正式行為（不對齊就不壓）；
  **只有恰好 1** 才開；其他值都當 0。開機為 0（loader 把整塊清零，`fpl_card_init` 要求全零），不存設定、不寫卡。
- **位址**：state = cave 記錄的 +36（掃 0xC072E064..0xC072EFB4 找 "FLPC" 0x43504C46，在記錄 +32）；
  開關 = state + `layout.json` 的 `pitch_test`。本 BIN：**state + 0x2C41C**；
  計數 = state + 0x153D0（lane A `hold.pitch_forced`）+ state + 0x2A640（lane B）；該段實際用的開關值 = state + 0x153CC。
  這些都寫在 build 的 `build.json` → `pitch_test_switch` 與 `layout.json`（v4 builder 現在也輸出 layout.json）。`card_status.py` 會印一行。
- **作用範圍**：只跳過兩道列距閘 —— `control.c`（context `ready` 的 bit 30 `FPL_TEST_PITCH`，由 card 的 readiness 在開關 = 1 時加上；不是 readiness，單獨不會讓任何東西 ready）
  與 `codec_job.c`（`fpl_codec_input.pitch_any`，由 frame_hold 的 `pitch_test` 帶入；`frame_hold` 自己的 told 長度也用它）。
  位深 10/12/14、寬 8 的倍數、高偶數、160 格、fps、媒體、每幀寬／高／格式比對、BLOCK_REC 全部照舊。
- **何時生效**：REC 那一刻讀（readiness 與 `start_hold` 各讀一次）；錄影中改不影響當段。
- **計數**：`hold[_b].pitch_forced` = 這段在列不對齊情況下**壓成功**的幀數（job 的 `misaligned`），每次 REC 歸零。
- **預設 0 = 首版 0.3.2test**：`validation/…/default_equivalence.py` 把開關前後的 `control.c`／`codec_job.c` 一起編，
  148,010 個決策（位深 × 寬 8..6192 × 高 × readiness，與 source_bytes）全部相同。
- 為什麼不另做 TEST build：開關預設 0 時行為逐決策相同、只多 12 bytes 狀態；同一個 BIN 上機才能直接比 0／1。
  代價是正式版帶一個主機可寫的測試字（寫它要有 USB shell）。
- 附帶：`control.c` 的 `fpl_can_enable` 主體移到 always_inline 的 `can_enable`（行為不變），
  因為加了判斷後 clang 不再內聯，ARM 測試的嚴格抽取器會拒絕 `.text` 重定位。
- ⚠ Sensor Lab 的 DC／RES 寬一律 `a16`（16 的倍數），UI 錄不出 1928；上機這節要先有別的來源（見 LIVE_PROTOCOL §3）。
  反過來說：Sensor Lab 正常使用時列距閘從不觸發。
