# 6K 回放半解析度：RAW 資料路徑 RE（2026-11-03，離線）

範圍：fp Ver.5.02 機內 CinemaDNG 回放，單格從「檔案進 ring」到「RAW reader 讀取」之間，哪裡能插入 2×2 同色平均（保留 Bayer 相位），讓畫布光柵可以減半、FieldAngle 從 ~40.5 MB 降到 ~11.8 MB。
只讀 `out/MAIN_c0000000.bin` 與 `out/decomp/full`；沒有碰相機、USB、daemon 或卡。
標記：**[驗]** 反編譯或 ROM 位元組直接看到；**[推]** 推論，未上機。

## 0. 摘要

1. **沒有中間 RAW 平面。** RAW reader 直接用 DMA 讀 file-ring 的緩衝區：每格位址 = `entry+0x14`（緩衝區基址）+ `entry+0x10`（StripOffsets[0]）。這個值由 `CinemaDngRawMemInterface::v1 @C05BC8C0` 回傳，再由 SigManTr 執行緒寫進 SIG 輸入 DMA 的位址暫存器（shadow `0x30230144`）。[驗]
2. **原廠播放器從不解 LJ92**（不讀 Compression）。tiled 無損片能播，是 lossless-sup 在 `C05C0EA4` 掛了解碼，把內容解回 IFD0 的未壓縮 strip。[驗：lossless-sup PROGRESS_20261001 + `C05C1A58` 反編譯]
3. reader 的列距、高度、寬度都從**畫布光柵字**來：`0xD8/0xE0`（不為 0 時）→ 平面 `+0x20/+0x28`，列距 = 打包位元組數(`+0x20`, 格式)。跟 FieldAngle 用的是**同一組字**，所以「光柵寫半、reader 讀全 6K」不能只靠改畫布字做到。[驗 呼叫鏈／推 回放走哪個分支]
4. 畫布的 bin 字（`0x58/0xC4`）與 RWZM 字（`0x60/0xD0`）只會在 `0xD8/0xE0 == 0` 時影響平面尺寸；RWZM/CRCT 硬體位在「感光元件 → BufA」的線上路徑，回放的記憶體輸入在 BufA 之後，**不會經過它們**。所以使用者想的「ISP vbin/hbin 或 RWZM 在回放時硬體縮 2 倍」走不通。[驗 C01CB388／推 硬體位置]
5. **建議的插入點**：`C05C0EA4`（CPlyFiW 讀完一格、原廠快取維護之前），把 strip **原地**縮成半尺寸，再把畫布光柵減半。`v1` 不用改；單格、暫停、播放都會經過這裡。lossless-sup 也掛在同一個點，兩者要串接。[驗 站點／推 行為]
6. 原廠有現成的「RAW → 半尺寸 RAW」硬體 helper：`XC_SigproRawMakePreview @C04321A0`（HSEP 水平 ÷2 同色平均 + RawMix 垂直 preset，輸出 12-bit）。缺點是它在 pool 10 自己配置輸出，而回放 ring 會先把 pool 10 用光。它是硬體備案，不建議當第一版原型。[驗 程式碼／推 用途]

## 1. 資料流（單格）

```
CPlyFiW 執行緒 (CinemaDngFileReader, C05C0C38)
  f_read(file, entry+0x14 = 緩衝區, cap entry+0x18, got entry+0x1c)   @C05C0EA0  bl C0366060
  ★ C05C0EA4  ldr r2,[r5,#0x1c]   <- lossless-sup 解碼站點；建議的縮小站點
  C05C0ECC  bl C000E91C           (原廠快取維護)
        │
CPlyTag 執行緒 (C05C1880)
  解析 TIFF；C05C1964: tag 0x111 → entry+0x10 (StripOffsets[0])
  C05C1978: C05C1BD8 → entry+0x5E4 (每格 tag 物件)
        │
CinemaDngPlay (C05BE3A0 單格 / C05BE4B0 播放)
  C05BC908 (=RawMem v2) → C05BB4A0  每格 tag → 顯影參數 (WB/色彩，不含幾何)
  C0423CA8 → C04291B0 (把 RawMemInterface 包成 SigManTr) + C0428AB8 (FieldAngle 配置與 SIG 啟動)
        │
SigManTr 執行緒 (C0428878, pri 7, stack 0x3000)
  r0 = RawMem->v1()            @C04288C4  blx [vt+0xC] = C05BC8C0: entry+0x14 + entry+0x10
  C042B048(r0)                 @C04288C8  轉成 DRAM word address
  C01D55E8(word)               @C04288CC  存 C31E0DE4；C018B890 寫 shadow 0x30230144 (SIG 輸入 DMA 來源)
  RawMem->v2()                 @C04288E4  (= C05BC908)
  C01C82B0()                   @C04288E8  觸發／等待 SIG 工作
  RawMem->v3()                 @C0428938  (= C05BC6E8, ring 前進)
        │
SIG 記憶體輸入 → 前處理 → … → YUV (pool 9 的 80 MiB) → LCD
  幾何在 setup 時從畫布決定：C0434EF8 → C01D1630 → C01CABA0/C01CB388 (frame desc)
                             → C01CDBE0 (C31DECCC+ch*0x10C) → C0173F20 → C0141468 (0x302300xx/0x302301xx)
```

## 2. 逐題回答

### Q1 RAW 平面是誰產生的

- **未壓縮（Compression=1、單一 strip）**：沒有中間平面。`v1 @C05BC8C0` 的 ROM 指令是 `ldr r1,[r2,#0x10]; ldr r0,[r2,#0x14]; bl C0010C98`（`C0010C98` 就是 `a+b`），回傳 `buf + strip`。[驗]
  - `entry+0x14/0x18/0x1C` = 緩衝區／容量／實際讀取長度（`C05C0C38` 的 `C0366060` 呼叫）。[驗]
  - `entry+0x10` 由 tag 執行緒 `C05C1964 bl C05C1DB8(tiff,0,0x111,entry+0x10)` 寫入。[驗]
  - 緩衝區 = pool 10 的 ring，`C05C2D10` 依第一個檔案大小 `(bytes+0x1FFF)&~0xFFF` 反覆配置（PLAYBACK_DESIGN §7）。實測位址在 `0xD1B00780` 這類快取別名，不保證 1 KiB 對齊（lossless-sup card aa）。
  - 佈局就是檔案 strip：打包 12-bit、列距 = W×3/2 bytes，沒有補白。這跟 reader 的列距公式 `C0135DB8`（fmt0 = W*3/2、fmt1 = W*7/4、fmt3 = W*5/4、fmt4 = W）吻合。[驗 公式／推 回放走此分支]
- **tiled LJ92（Compression=7）**：原廠 tag reader `C05C1A58` 只讀 0xC620、0x100/0x101/0x102、0x10A、0xC764，**不讀 0x103**，也不會解碼。[驗]
  - 原廠 HW 解碼（`C062FAD0`，0x300D0000 decode mode）只有 `XC_PlayFuncSeqDngDeveloping`（靜態 DNG 顯像）在用。
  - lossless-sup ab/ac 在 `C05C0EA4` 解碼：tile 列由下往上解到 scratch，再 DMA 進 strip。IFD0 保留未壓縮 strip 的位置與大小，所以 reader 讀到的是解完的 12-bit 打包資料，跟未壓縮片相同。[驗：PROGRESS_20261001「Card ab on the camera」]

### Q2 reader 的位址、寬高、列距從哪來（兼答主對話 (a)）

| 項目 | 來源 | 證據 |
|---|---|---|
| 來源位址 | 每格 `v1()` → `C01D55E8` → shadow `0x30230144`；setup 時 `C0173F20` 也用平面位址陣列 `C01D4BA8(ch)` 加 crop 偏移，經 `C0141468` 寫同一暫存器 | [驗]；回放每格只換位址、幾何在 setup 決定 [推，強] |
| 平面寬高 `desc+0x58/+0x60`（平面 `+0x20/+0x28`） | `C01CB388`：先取 `canvas+0xF4/0xF8`（只有 fps == -1 時，`C01D3518`），否則讀回硬體尺寸 `C017F880(…,5)`；接著依 bin(`0x58/0xC4`)÷3/÷5、zoom(`0x60/0xD0`) `(w-1)*1024/z+1` 縮小；**最後只要 `canvas+0xD8/0xE0` 不為 0，就直接覆蓋成 D8/E0**（frame flag bit0 = 0 且 type ≠ 0x26）；之後依 `canvas+0x08` 把高 ÷2/3/5/7 | [驗 `blk_c01.c` C01CB388] |
| reader 寬 `base+0x34` | 平面 `+0x2C` = `canvas+0x20`(cfg+0x30) + `C0151AF0(0,ch)` 邊距；+0x2C 為 0 才用 `+0x20` | [驗 C01CDBE0、C01CB388] |
| reader 高 `base+0x38` | 平面 `+0x28`(E0) + `+0x34/+0x38`(=`canvas+0x8C/0x88` 額外列)，上限 `+0x30` | [驗] |
| reader 列距 | `C0173F20`：`C0135DB8((short)base+8 = 平面+0x20, 格式 base+0x50)>>2`（當 `base+0x9C` = `desc+0x42C` = `C01D5538()` 不為 0）；否則讀 BufA 寫入 DMA 暫存器 `0x30182114/214/314` 當列距 | [驗 程式碼／推 回放走前者] |
| 格式 `base+0x50` | 平面類型 7/9/10 → 0/3/4（RAW14 由 H_PBRAW14 補 1） | [驗，見 raw14-fix] |

**結論**：FieldAngle（`0x0C/0x10`、`0xD8/0xE0`）跟 reader 的列距與高（`0xD8/0xE0`）**共用同一組字**。reader 的寬多一個來源（`0x20` + 邊距），但列距跟著 D8 走。只把 D8/E0 減半，會變成用半列距讀全尺寸資料，畫面錯位。要減半，**reader 讀到的資料本身就要是半尺寸**：畫布的 0x0C/0x10/0xD8/0xE0/0xF4/0xF8 改成半光柵、0x20/0x28 改成半裁切，同時讓 strip 內容變成半尺寸（列距 = 半寬×3/2）。

**主對話 (b)：bin/zoom 字會不會在回放時讓硬體縮小？**
- `C01CB388` 裡 bin/zoom 字只用來算平面尺寸，而且會被不為 0 的 D8/E0 蓋掉，所以在 SensorLab 現在的畫布（D8/E0 = 光柵）下，**完全沒有作用**。這跟實測「改它們不影響配置」一致。[驗]
- `C0434EF8` 把 `0x58→cfg+0x9C`、`0xC4→cfg+0xA0`、`0x60→cfg+0x1C`、`0xD0→cfg+0x20`、`0x64→cfg+0x108`、`0xD4→cfg+0x10C`、`0x5C→cfg+0xFC`、`0xC8→cfg+0x100`。[驗]
- `C0173F20` 另有 `+0xB4/+0xB8`（= `desc+0x4E0/0x4E4`，bin 模式 1/3/5）與 `+0xF8`（`desc+0x94/0x98` 的 1/1024 比例）的除法，用在某些輸出尺寸計算（`local_b34/b30`）。它們不改輸入 DMA 的列距或位址。[驗 存在／推 用途]
- RWZM（0x300F0900）與 CRCT bin 位在接收端 → BufA 的線上路徑（HW_REDUCTION_CANDIDATES C1–C4），回放的記憶體輸入（0x302301xx）在 BufA 之後。沒有找到能把記憶體輸入導回 RWZM 的設定。[推，強]
- **所以不能「光柵寫半、reader 讀全 6K、ISP 硬體縮 2 倍」。** 唯一已知會在記憶體裡縮 RAW 的硬體是 HSEP/RawMix（見 Q5）。

### Q3 「RAW 已就緒」到「reader 啟動」之間可掛的點

見 §3 的表。最好的是 `C05C0EA4`，原因如下：
- 每次讀檔只跑一次，暫停重畫不會重跑，不會把同一格縮兩次。
- 在 CPlyFiW 執行緒（優先權數字 0x25，低），跟顯示管線並行，可以預讀管線化。
- 原廠緊接著呼叫 `C000E91C` 做快取維護，CPU 寫入會被 DMA 看到。
- 單格選片（`C05BE3A0`）與播放（`C05BE4B0`）都經由同一個 RawMemInterface，所以都會吃到縮小後的資料。[驗 呼叫點／推 單格也先經 C05C0C38 讀檔]

### Q4 HW 無損解碼器的輸出能不能指到別處

- 原廠回放不呼叫解碼器（Q1）。lossless-sup 呼叫它時，輸出位址就是參數（init word 5 = raw buffer，word 6 = 壓縮流），可以任意指定。實際上它已經是先解進 scratch、再 DMA 進 strip。[驗 PROGRESS_20261001]
- 對 6K LJ92：可以先解成全尺寸（目標可以是 strip 本身或 scratch），再縮半寫進 strip。全尺寸解碼目前每張 3K 約 59 ms，6K 約為 4 倍，加上縮小，幀率會很低。[推]
- 解碼器整塊寫 tile，緩衝要容得下補白後的高度（曾溢出約 0.9 MB 造成卡死）。[驗]

### Q5 有沒有原生的降解析度讀取

- reader setup（`C01CDBE0`/`C0173F20`）**沒有**找到記憶體輸入的抽行／抽列欄位。`canvas+0x08`（平面高 ÷2/3/5/7）只改平面高，不改列距，等於只讀上半部。[驗 C01CB388／推 效果]
- **`XC_SigproRawMakePreview @C04321A0`**（caller `C0425040`）會產生半尺寸 RAW：
  - `C01AA030` 走 HSEP mode 00，水平 ÷2 同色平均，12-bit。
  - 接著 `C01A9B20`；TRUE14 §15.3 記錄其垂直 preset 由 `C0133758`/`C0144AE8` 以 B = A+2 列做配對。
  - 輸出結構 `[6]/[7] = 輸入[6]/[7]>>1`；輸出用 `C001CF78(10)`/`C001D038(size,0x200)` 在 pool 10 配置。
  - HSEP 已在相機上以 harness 跑過 32 次小圖（TRUE14 §0.2）。12-bit 截位對回放預覽無害。[驗 程式碼／推 垂直半高與完整鏈]
  - 限制：pool 10 會先被 ring 配置用光，這個 wrapper 自己配置一定失敗。若要用硬體，必須自己組 C01AA030 + C01A9B20 的描述子，並在 ring 配置**之前**預留輸出（像 lossless-sup 在 `C05BDDAC` 預留 scratch 一樣）。另外 SIG 正在播放時跟 SigManTr 搶同一引擎，排程衝突未知。

## 3. 候選 hook 站點

| 站點 | 原字 | 模式 | 執行緒 | 用途 | 評語 |
|---|---|---|---|---|---|
| `C05C0EA4` | `E595201C` `ldr r2,[r5,#0x1c]` | ARM | CPlyFiW | 讀完一格、原廠快取維護前；r5 = ring entry（+0x14 buf、+0x1C 長度） | **首選**；lossless-sup 已佔用，要串接（先解碼、再縮小） |
| `C2DFDD7C`（資料） | `C05BC8C0` | vtable 字 | SigManTr | 把 v1 換掉，回傳縮好的 scratch 位址 | 不改程式碼；但每次重畫都會跑（要自己快取），而且要在 pool 10 以外有雙緩衝 |
| `C04288C8` | `EB0009DE` `bl C042B048` | ARM | SigManTr | r0 = 本格 RAW 位址，可以改成 scratch | 同上，影響所有 RawMem 使用者（LV 樣本類也走這裡），要檢查 vptr |
| `C05C1964` | `EB000113` `bl C05C1DB8` | ARM | CPlyTag | 讀 StripOffsets → entry+0x10 | 可以改 strip 位移，讓半尺寸資料放在別處；R181 也掛過這裡 |
| `C05BDDAC` | `E58430A0` `str r3,[r4,#0xa0]` | ARM | CinemaDngPlay | 第一格大小 → ring 單格容量 | ring 配置前預留 scratch 的時機（lossless-sup 先例） |
| `C05C2DE8` | `EBE968FE` `bl C001D1E8` | ARM | CinemaDngPlay | ring 配置迴圈 | SensorLab H_PBRING 已佔；必要時限制 ring 張數、讓出 pool 10 |
| `C043A19C`（畫布） | （H_CANVAS） | — | — | `ap_pb_canvas` 寫半光柵 | 已有，只要加減半分支 |

`C04288C4`/`C04288CC` 這兩個字分別是 `E12FFF31`（`blx r1`）與 `FAF6B345`（`blx C01D55E8`，Thumb 目標）。[驗 ROM 反組譯]

## 4. 風險與未知

- **半光柵的尺寸**：6064×4050 ÷2 = 3032×2025，高是奇數，3032 也不是 16 的倍數（SensorLab 的 `ap_pb_tag` 要求 `rw%16==0`；`C01CB388` 有 `(w+7)&~7` 的捨入）。建議輸出 **3040×2030**，也就是半裁切 3024×2020 加上原廠慣例的 +16/+10。實作時要自訂 4×4 塊從偶數列／欄起算，才能保留相位，並且要對齊 DefaultCropOrigin。[推]
- 單格選片的路徑：假設它也經 `C05C0C38` 讀檔。PLAYBACK_DESIGN §7.3 提到 `C03C5C88` 另配 1024×576 暫存，未確認那條路是否另讀 strip。[推]
- reader 列距的分支：回放時 `C01D5538()` 是否為 1（走 `C0135DB8`），還是讀 BufA 暫存器。若是後者，列距來自哪次設定未查。兩者都由畫布光柵推出。[推]
- CPU 成本：每格讀 36.8 MB、寫 9.2 MB。要用快取別名、NEON；估計 60–150 ms/格（約 7–15 fps）。這只是估計，沒有量測。[推]
- strip 與 IFD 都在同一緩衝區。原地縮小只能寫 `[strip, strip + 半尺寸)`，不能碰 TIFF 標頭；CPlyTag 會在之後解析它。第 0 列輸出會跟第 0、1 列輸入重疊，要先讀進暫存再寫。[推]
- 跟 lossless-sup 同站點：兩個 sup 同卡時要明確串接順序。[驗 站點衝突]
- 14-bit：縮小核要按 RAW14 打包；格式碼仍走 H_PBRAW14。
- 每格 `C05BB4A0` 只讀 WB／色彩 tag，不讀幾何，不受影響。[驗]
- FieldAngle 11.79 MB 是主對話用 og4k_sizes 算出的值，本筆記沒有重算。

## 5. 建議的第一個原型

1. **畫布**：`ap_pb_canvas` 在已驗證的選中片、光柵 > 門檻（例如寬 > 4112）時，寫半光柵 3040×2030、半裁切 3024×2020（0x0C/0x10/0xD8/0xE0/0xF4/0xF8 與 0x20/0x28）。平面碼不變。
2. **縮小**：在 `C05C0EA4` 加新 hook（若 lossless-sup 在場，排在它的解碼之後）。條件與 H_PBRAW14 同一組（selected、prepared、owner/file 吻合、mode 開）。對 `entry+0x14` 緩衝區解析 IFD0 的 strip（沿用 `ap_pb_compression` 的 TIFF 讀法），原地 2×2 同色平均：12-bit 打包 → 12-bit 打包，列距 4560。最後一列對齊後，交給原廠 `C000E91C`。
3. **防重入**：在 entry 留標記（例如縮完後把 strip 末端改成固定 magic，或記錄 `entry+0xC` 檔案序號與緩衝指標），避免同一緩衝被縮兩次。
4. **離線驗證**：
   - C 核心對主機參考逐位元相同（含相位、邊界、奇數列）。
   - 在 unicorn 跑真 ROM 的 `C05C0C38` 片段與 hook，用 6K 首格 DNG。
   - 用 og4k_sizes 確認 FieldAngle 實際降到 ~11.8 MB。
   - mutation：錯相位、錯列距、重複縮小。
5. **上機**：先選片看單格（原本會凍結的 6K），再暫停、播放，並量每格縮小時間。
6. **後備**：若 CPU 太慢，再研究自組 HSEP(C01AA030) + RawMix 垂直 preset，輸出到 ring 配置前預留的 pool 10 scratch。
