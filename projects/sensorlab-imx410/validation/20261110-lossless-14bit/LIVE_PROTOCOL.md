# 上機程序：Lossless 0.3.2test × Sensor Lab 1:1 真 14

尚未執行。碰相機前照規矩廣播、確認沒有別的 session 在用；錄影中、停錄後 10 秒內、回放中都不碰 USB。

## 卡

- `Lossless_v0.3.2test.BIN`（本目錄 `build/`，sha256 見 README）＋ Sensor Lab-IMX410 0.0.4test ＋ QS-Share 0.0.2test
  （＋ USB-Shell 以便讀 `card_status`）。用合併頁／`fp-merged-card` 建卡，不手拼。
- 原廠位深設定 = 12（「RAW bit」），媒體先 SD。

## 1. 小畫幅先（引擎、寫入都有餘裕）

1. Sensor Lab 選 1:1、AD 14 的配方，DC/RES = **1936×1090**（rec_bits = 14），23.976 fps。
2. 三腳架、靜物、有紋理、曝光正常，ISO 800。
3. fpSup 頁 Lossless = **OFF**，錄 3 秒 → 記下資料夾名（對照組）。
4. Lossless = **ON**，錄 10 秒 → 停錄，等 10 秒。
5. （USB）`card_status.py` 讀一次：
   - `producer 1936x1090 14-bit, raster 3,692,936 B`（= C0135D40(1936,1090,1)）；若是 12-bit 就是 §2 的 [推] 錯了（查詢回 0）。
   - `last` = OK、compressed ≈ 幀數−1、`hold.refused_by` 全 0（descriptor／handle 非 0 要記下）。
6. 卡上檔案：
   - 幀數 = 10 s × 23.976（±1）；第 1 幀未壓縮（設計如此），其餘 Compression=7。
   - `python3 -B projects/lossless-sup/tools/verify_compressed_dng.py <幀> --stock <同段第 1 幀>`
     （header_bytes／ifd_at／tile 參數依實際值傳）：BitsPerSample 14、TileWidth/Length = 512×368、12 格、檔長 = header + Σcounts。
   - 第一個壓縮 tile 的 SOF3：precision = 14、寬 = tile_w/2、2 分量。
   - LibRaw（rawpy）解碼成功；**畫面正常**（錯的位元順序 = 滿屏雜訊；錯的列距 = 斜切）——跟 OFF 對照組並排看。
   - 各 CFA 通道平均／標準差與 OFF 對照組相近（同場景、雜訊範圍內）；第 1 幀（未壓縮）與第 2 幀（壓縮）同樣相近。
   - Resolve 開 ON 那段，播放無黑幀、無斜切。
7. 壓縮比：Σ壓縮幀 bytes vs 3,692,936 × 幀數，記到本目錄（預期 1.7–2.2:1）。

## 2. 大畫幅（記憶體、混合 RAW）

8. 6048×4040 1:1 14-bit，fps 降到 **5**（VMAX 加大），媒體 **SSD**。ON 錄 10 秒。
   - `card_status`：`spare_failed`、`lane_b_failed` 是否為 0（兩個 43 MB 備用幀配得到嗎）。
   - 引擎 6.2 fps 上限 → 5 fps 應該幾乎全壓；記 compressed／passed。
   - 檔案檢查同上（96 格 512×512）。
9. 同畫幅 fps 拉到最高（19.0）：預期約 1/3 壓縮、其餘 RAW 交錯；確認沒有提前停錄、幀數正確、每幀都可解。
10. （選做）同畫幅在 SD：預期 vbuf 自停，時間與 OFF 比較。

## 判定

- 通過：步驟 5–6 全部符合、9 沒有掉幀／錯幀。
- §1 步驟 5 若是 12-bit／refused_by descriptor：0.3.2test 安全（整段 RAW），但 14 沒有生效 → 回頭查 `C0437140` 的查詢參數。
- 畫面錯（雜訊／斜切）：立刻停用，回報「引擎讀 format 1 的排列 ≠ DNG 的 MSB-first」；這是離線唯一沒證到的一環。

## 3. 列距閘測試開關：1928 寬 10-bit 與 14-bit（Bei 2026-11-10 追加）

目的：寬 ≡ 8 (mod 16) 時，引擎列距（bits×w/8）與點陣列距（補到 4 bytes）差 2 bytes，硬壓會不會斜切／雜訊。
同一個 `Lossless_v0.3.2test.BIN`。開關位址見 README「列距閘測試開關」（state + 0x2C41C）。

**⚠ 先決條件（未解）**：Sensor Lab 的 DC／RES 寬一律 `a16`（slqs.c `a16i`／`a16r`，slqs_ref.py `a16`）——
**UI 選不到 1928**，所有 Sensor Lab 錄影寬都是 16 的倍數（這也代表正式使用時列距閘從不觸發）。
要做這節，得先有一個能錄出寬 ≡ 8 (mod 16) 的來源（Sensor Lab 測試鉤子／`sq_test`、或其他 sup 的自訂解析度），由 Bei／Sensor Lab 那邊決定；Lossless 這邊已就緒。

1. 用上面那個來源錄寬 **1928** 的配方（高例如 1090），先 **14-bit**（1:1 AD14），23.976，SD，靜物有直線（門框、桌邊）。
2. Lossless ON。USB：找 state（`card_status.py` 會印 `record at … state 0x…`），`mem set <state+0x2C41C> 1`，**讀回確認是 1**。
3. 錄 **1 秒**，停錄，等 10 秒。
4. `card_status`：`pitch test switch 1 (last take 1); compressed with unaligned rows N`，N ≈ 幀數 − 1；`last` = OK。
5. 拉第一個壓縮幀（第 2 幀）與第 1 幀（未壓縮）：rawpy 解碼、並排看。
   - 預期（推論）：壓縮幀**每列往左累積錯 2 bytes** → 越往下越斜（約 8 px/列的位元錯位，畫面變雜訊或斜紋）。
   - 若壓縮幀與第 1 幀一致 → 引擎其實讀的是 4-byte 對齊列距，列距閘可以放寬（回報 Bei）。
6. 同樣步驟換 **10-bit**（原廠位深選 10，或 Sensor Lab 0.0.4test 的 10-bit 路徑），寬 1928。
7. **對照**：`mem set <state+0x2C41C> 0`（讀回 0），同配方再錄 1 秒 → 預期整段原廠 RAW（`rec_raw` +1、或 refused、pitch_forced 0），檔案全部 Compression=1。
8. 測完務必把開關設回 0（或重開機：開機必為 0）。
