# jxl-metal — JPEG XL 無損壓縮與解碼跑在 Metal 上

目的：剪輯時邊播邊解 cDNG 的 JPEG XL 存檔（見 `projects/cdng-image`，比較數據在
`projects/cdng-image/validation/jpegls-20261024/RESULTS.txt`）。
輸入是**標準** JPEG XL 碼流（cjxl / libjxl 產生），不是自訂格式。

## 架構

| kernel | 平行單位 | 做什麼 |
|---|---|---|
| `jxl_parse_frame` | 一幀一條執行緒 | 檔頭、TOC、LfGlobal（全域樹與熵表，若有） |
| `jxl_decode_group` | 一個群組一條執行緒 | 群組自己的 MA 樹與 ANS/prefix 表、熵解碼、MA 樹、預測（含 WP）、調色盤反轉換，直接寫進整幀平面 |

CPU 只做：上傳碼流、讀回每幀群組數、排 job、分批送出、比對。

效能關鍵（都量過才留下）：
- 列狀態（上一列像素、WP 誤差）以 job 編號交錯存放，同一 SIMD 群組讀同一個 x 時合併成一次存取。
- 鄰居值在暫存器裡滑動，每像素只讀 x+2 / 上上列 / WP 誤差各一次。
- ANS 每個 bucket 壓成一個 64-bit（cutoff、別名符號、offset、兩個頻率），每符號一次讀取。
  32-bit + 另一張頻率表反而較慢（兩次相依讀取）。
- MA 樹的分支節點（單一屬性樹用兩層 8-byte 節點）與 4-byte 葉節點資訊放 threadgroup 記憶體（每條執行緒 512 B），葉節點紀錄帶熵表位置、
  hybrid 參數、預測器。effort 3 的樹是單一屬性（WP max error）的 33 分支二分搜尋。
- 分批：每批群組數 = 核心數 × 32 × 3（M1 Max 為 3072）；太多會撐爆快取，不整除核心數會讓核心閒置。

## 壓縮器（`jxl-metal encode in.pgm out.jxl`，2026-10-25）

輸出標準碼流（單幀灰階 modular、128 群組、整幀一棵 MA 樹與一套熵碼，同 `cjxl --buffering=0 -g 0` 的結構），
每個檔案都用官方 djxl 解回比對。

| 步驟 | 在哪裡 |
|---|---|
| 抽樣（每 8 像素 1 個）、屬性分位數、逐層節點直方圖 | Metal（`learn_*`） |
| 挑切點（熵增益 > `JXL_SPLIT_BITS`）、直方圖分群（≤255 群）、ANS 表 | CPU（資料量小） |
| 每像素情境、Gradient 殘差、符號、直方圖 | Metal（`enc_tokens`） |
| rANS（每群組一條執行緒，反向編碼、正向寫出） | Metal（`enc_ans`） |
| 檔頭、TOC、樹、碼規格 | CPU |

夜景 4K 四幀（同一組 PGM，djxl 逐位元組一致、本解碼器 32/32 逐像素一致）：

| 設定 | 平均每幀 | GPU 解碼（32 幀） |
|---|---|---|
| libjxl `-e 7 --faster_decoding=1 --buffering=0 -g 0` | 2.025 MB | 72.6 fps |
| **本壓縮器預設**（`JXL_SPLIT_BITS=400`，~800 葉 / ~170 群） | **2.005 MB** | **78.9 fps** |
| `JXL_SPLIT_BITS=800` | 2.020 MB | 95.0 fps |
| `JXL_SPLIT_BITS=2500` | 2.053 MB | 116.6 fps |

### 批次與速度（2026-10-25，夜景 A001_043 連續 64 幀，djxl 64/64 逐位元組一致）

`jxl-metal encode OUTDIR a.pgm b.pgm ...`：模型（樹＋分群）只從第一幀學一次（`JXL_RELEARN=N` 每 N 幀重學），
每批 16 幀（`JXL_BATCH`）共用一套 ANS 表（`JXL_SHARED_TABLES=0` 改回每幀一套）。

| | 每幀 | 4K 壓縮速度 |
|---|---|---|
| 每幀重學 | 2,022,441 B | 2.5 fps |
| 只學一次、每幀一套表 | 2,023,594 B（+0.06%） | 48 fps |
| **只學一次、每批一套表（預設）** | **2,026,130 B（+0.18%）** | **69.5 fps**（含學模型；讀 PGM 另計） |
| libjxl e7 fd1（同 8 幀抽樣比較） | 本壓縮器小 0.88%（每幀一套表） | ~2 fps |

各段（每幀）：符號 3.4 ms、ANS 3.3 ms、建表 0.15 ms、學模型 389 ms／次。

**之後再加速（同一組 64 幀，djxl 64/64、手持 FHD 16/16 逐位元組一致）：4K 69.5 → 119.7 fps（含學模型）。**
- ANS：每個符號的頻率、起點、32 位元倒數併成一次 8 bytes 讀取（`mulhi` 加一次修正，精確）。
- 符號改成「每群組 8 個一段」交錯：符號 kernel 的寫入只碰幾條 cache line，ANS 一次讀 8 個。
- 學模型 366 → 90–107 ms：分群改成不配置記憶體、x·log2x 查表（175 → 19 ms）；切點增益改在 GPU 算
  （`learn_gain`，每層只讀回約 10 萬個 float，不再讀回 27 MB 直方圖；189 → 84 ms）。
- **試過、不可行**：直接沿用學模型那一幀的熵表、整批不算直方圖——後面的幀會出現那一幀沒有的符號（頻率 0），
  64 幀壞了 63 幀（量到的「更小」是假的）。每批的直方圖保留。
- 批次大於 16 在短測試裡較慢，主要是第一次碰到數 GB 新緩衝區的成本，長片段會攤掉。
速度關鍵（都量過）：暫存緩衝區跨批重用（33→44 fps）；符號以「群組交錯」存放，讓一個 SIMD 的 ANS 執行緒
讀同一條 cache line（大批次時 ANS 快 2–5 倍）；整批共用表（每幀一套表時批次越大越慢，表擠出快取）。
ANS 的除法改成乘以 2^44 倒數（可證明精確，輸出逐位元組相同）但不是瓶頸。

注意：
- **屬性 8 不能用**：用了 djxl 會失敗（J40 與本解碼器的定義一致，但 libjxl 不同），libjxl 自己的 e7 也不用它。學樹時排除。
- 解碼器的 lean 路徑把表位址壓進 17 位元；群組多時打包表曾被擠到 2^18 之外而退回慢路徑（42.9 fps）。
  現在讀表前先預留打包表的位置（`S_TBASE`）。

調整用環境變數：`JXL_SPLIT_BITS`、`JXL_MAX_LEAVES`（預設 2048）、`JXL_CLUSTER_BITS`（200）、`JXL_MAX_CLUSTERS`（255）、
`JXL_STRIDE`（8）、`JXL_PROPS`（十進位位元遮罩）、`JXL_FIXED_TREE=1`（81 葉固定樹）。

## 支援範圍

- 灰階、整數樣本、單幀、modular、單 pass、無升取樣、無 ICC/預覽/動畫/額外通道。
- 全域樹或群組自帶樹皆可；ANS 與 prefix code；LZ77（未實測到）；TOC permutation。
- 檔案可為裸碼流或 ISOBMFF 容器（jxlc/jxlp，主機端取出）。輸出平面為 16-bit 有號（超出會報錯）。
- 群組轉換：單通道調色盤（含 synthesized 與 delta；delta 用 WP 預測的情況未實作，負索引路徑未被素材覆蓋）。
- 未做：彩色/RCT、squeeze、單一 section 的小圖、全域轉換、previous-channel 屬性（16+）。遇到會回報 `unsupported/N`。

## 驗證（2026-10-24，M1 Max 32 核心，達芬奇關閉）

素材：夜景 A001_043 4K 幀以 Bayer 同色四象限排成 3856×2170 PGM，`cjxl -q 100 -e N -g 0`（128×128 群組）。
14-bit 是 12-bit ×4 加隨機低 2 位元合成的（不是真的 14-bit 素材）。比對對象是 cjxl 的輸入 PGM，逐像素。

| 設定 | 結果 | GPU（32 幀一批） | libjxl CPU 10 執行緒 |
|---|---|---|---|
| e2 12-bit | 32/32 逐像素一致 | 597 Mpx/s（71 幀/秒） | 348 |
| e3 12-bit | 32/32 逐像素一致 | **429 Mpx/s（51 幀/秒）** | 168–186 |
| e3 14-bit（cjxl 會包容器） | 32/32 逐像素一致 | 306–332 | 181 |
| e7 12-bit（有調色盤） | 16/16 逐像素一致 | 178 | 100 |

## 效能紀錄（e3 12-bit，有效的才留下）

37 → 158（表壓縮、葉節點直指表）→ 249（樹進 threadgroup、分批）→ 265（64-bit 對齊補位元）→
290（單一屬性樹）→ 342（列狀態 16-bit）→ 364（無分支 token）→ 394（每核心 3 個 threadgroup、兩層 8-byte 節點）
→ 429（葉節點資訊 4 bytes 放 threadgroup）。

試過變慢、已還原：ANS 預取、32-bit ANS 表、除法表放 threadgroup、值→節點捷徑表、SIMD 共享葉節點表、
固定預測器的專用 kernel、setup 與 decode 重疊。教訓：內層迴圈多一個執行時分支或多佔暫存器就會慢 5–12%；
threadgroup 記憶體超過 16 KB 會降低佔用率。

拆解（目前）：熵解碼約 50%、WP 約 15%、setup 約 11%。

## ★ 建議的存檔設定（2026-10-24）

`cjxl -q 100 -e 7 --faster_decoding=1 --buffering=0 -g 0`（輸入：Bayer 同色四象限 PGM）

- 夜景 4K：**比相機 LJ92 再省 24.9%，GPU 605–609 Mpx/s（4K 72 幀/秒）**，32 幀逐像素一致（兩段不同的 16 幀）。
- 手持 FHD 片段：16/16 逐像素一致，436 Mpx/s（FHD 207 幀/秒）。
- 合成 14-bit（低 2 位元隨機）：490 Mpx/s（4K 58.6 幀/秒），逐像素一致。
- 編碼約 2.3 秒/幀（CPU），只在打包時發生。

關鍵是 `--buffering=0`：cjxl 預設對大圖分段編碼，每個群組自帶 MA 樹與熵表（GPU 上幾千份表撐爆快取）；
`--buffering=0` 改成整幀共用的全域樹與表，壓縮更好、GPU 快取一直命中。全域樹裡以屬性 0/1（通道、群組編號）
切開的分支在設定 kernel 依群組預先走掉；仍然很大的樹（e7）整幀共用一份，用 16-byte 兩層節點走。

| `--buffering=0` 加上 | 比 LJ92 再省 | GPU Mpx/s |
|---|---|---|
| -e 3 | 16.7% | 795 |
| -e 4 | 16.9% | 776–795 |
| -e 5 | 19.6% | 637 |
| -e 6 | 21.4% | 585 |
| **-e 7 --faster_decoding=1** | **24.9%** | **607** |
| -e 7 | 25.9% | 447 |

## 編碼參數 × 解碼成本（分段編碼，舊）（夜景 4 幀，`-g 0`，GPU 32 幀一批，CPU = djxl 10 執行緒，全部逐像素一致）

| cjxl | 比 LJ92 再省 | GPU Mpx/s | CPU Mpx/s |
|---|---|---|---|
| -e 4 --faster_decoding=4 | 8.4% | 722 | — |
| -e 3 | 14.8% | 430 | 198 |
| **-e 4** | **15.8%** | **458** | 165 |
| -e 5 | 16.5% | 310–324 | — |
| -e 6 --faster_decoding=2 | 14.9% | 387–425 | — |
| **-e 7 --faster_decoding=2** | **20.3%** | **243** | 170 |
| -e 7 | 20.5% | 180 | 113 |

e4 全面勝過 e3。e7 慢在多屬性的樹（每節點 switch）；試過「每像素先算 ≤4 個屬性槽」反而更慢（180 → 101），已還原。

修正：RFC 7932 允許第一層 prefix code 只有一個非零長度（不填滿碼空間），J40 會拒絕；e4 以上的檔案用得到。

## 其他 M 系列

每批群組數預設 = GPU 核心數 × 32 × 3（核心數從 IORegistry 讀）。`JXL_TUNE=1` 在該機器實測 ×2..5，
結果依「GPU 名稱 + 核心數」存在 `~/Library/Caches/jxl-metal/chunk.txt`。SIMD 寬度 32、threadgroup ≤ 32
為所有 Apple GPU 共通；M3 起的動態快取可能讓 16 KB 門檻不同，需要在該機器上重量。

## 用法

```
cargo build --release
./target/release/jxl-metal a.jxl b.jxl ...      # x.jxl 會和同名 x.pgm 比對
```

環境變數：`JXL_CHUNK`（每批群組數，預設依核心數或快取）、`JXL_TUNE=1`（實測並快取）、`JXL_TG`（≤32）、`JXL_SCRATCH`（每群組暫存 int 數）、
`JXL_DEFS="NO_ENTROPY FLAT_TREE NO_PLANE"`（計時拆解，輸出會錯）、`JXL_DUMP=<lane>`（印出該群組的樹）、
`JXL_TRINFO=1`（列出失敗群組用到的轉換）。第一次編譯 shader 約 10–30 秒，之後系統會快取。

`third_party/j40/`（J40，public domain）只當閱讀參考，不編譯、不進 git。

## 下一步

- effort 7：樹較大、預測器較多，目前比 e3 慢 2.6 倍。
- 還原排列 kernel：四象限 → Bayer、立方體反排、12-bit 打包成 DNG。
- 在立方體排法（`rows=(y,t)` 蛇形）的檔案上量。
