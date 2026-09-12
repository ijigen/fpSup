# 6K to SSD

[English](#english) | [繁體中文](#繁體中文)

One pipeline, fixed: **6K sensor readout → RWZM reduction → hardware lossless →
SSD**, at 29.97 or better. This document is what is established about it and
what is not.

一條固定的管線:**6K 讀出 → RWZM 縮小 → 硬體無損 → SSD**,29.97 以上。
這份記錄它已確立與未確立的部分。

---

## English

### The pipeline

```
mode 3 / 121      6064x4042 1x1 @29.97, a stock mode (it is the live-view mode)
     |            rolling shutter 24.98 ms -- fixed, this is what 4042 rows cost
     v
RWZM              the 16-phase 2-tap resampler at 0x300F0900
     |            factory ratio 0x640 = 1.5625
     v
XC_HalLjpeg       0x300D0000, lossless JPEG, ~2.3:1 measured on Bayer
     |
     v
SSD               USB 3.x Gen1, 5 Gbps, 625 MB/s theoretical, 376 proven
```

Every stage exists and runs today. None of them has been run in this order.

### What decides the output size

With compression in the chain the link stops being the constraint — it would
take 31.98 Mpix at 29.97 to reach 625 MB/s after 2.3:1. **The engine is the only
gate**, and the output size follows directly from its sustained rate:

| engine | output at 29.97 | written |
|---|---|---|
| 300 Mpix/s — inferred ceiling `[I]` | **3875×2583** (10.0 Mpix) | 196 MB/s |
| 265 Mpix/s — break-even | 3644×2429 | 174 MB/s |
| 240 Mpix/s | 3466×2310 | 156 MB/s |
| 169.7 Mpix/s — measured, cold `[C]` | 2915×1943 (5.7 Mpix) | 111 MB/s |

**265 Mpix/s is the number that matters.** Below it, compressing is worse than
writing 3542×2361 uncompressed at the proven 376 MB/s. Above it, compression
wins on both size and headroom.

`6000×4000 ÷ 1.5625 = 3840×2560` — the sensor's active area through the factory
RWZM ratio, needing no scaler change — sits just under the inferred ceiling.

### The engine's API, from the stills path

The stills path already compresses a 6064×4042 Bayer frame to a lossless DNG.
It is the reference implementation, and the HAL is
`src/hal/RawCD/src/XC_HalLjpeg.cpp`:

```
FUN_c05a6890(params9)  -> FUN_c062f5a8    start the encode
FUN_c05a6920(params5)  -> FUN_c062f6f8    wait for completion
FUN_c05a6990(x, 1)     -> FUN_c062fa48    collect the result
FUN_c03d9668(addr)                        virtual -> bus address translation
```

The nine words the encode takes, read off the caller in `blk_c03.c` around the
`StillCr...` assert at `0xC037E7AC`:

```
[0] width        [1] height       [2] source buffer (translated)
[3] 0x100        [4] 0x100        [5] destination buffer
[6] from FUN_c0398b00()           [7] *(obj+0x0C)
[8] mode byte, low bits cleared
```

The wait call takes five: `{w, h, buf, 0x100, 0x100}`. `FUN_c062f6f8` is where
`timeout = pixels / 32000` lives — a watchdog with 5.3x of headroom, **not** a
throughput figure. `+0xF8` on the block is the produced-byte count; `+0x3FC` is
busy/clear.

### What is established

- **The engine is idle during video.** Recording uses the DSP at `0x301B` and the
  RFC readout at `0x300C`. No contention to design around. `[C]`
- **It is cold standalone-callable** — the wrappers bring up power domain 5, the
  clock and IRQ 0x29 themselves, inside encode. `[C]`
- **Compression ratio ~2.3:1** on this sensor's Bayer. `[C]`
- **One engine, no parallelism**, and the clock cannot be raised — it shares the
  imaging domain with sensor readout and has no divider. `[C]`
- **Mode 3 is a stock 6064×4042 1×1 @29.97 readout.** The source needs no
  invention. `[C]`
- **The link is Gen1.** The BOS device capability is SUPERSPEED_USB with
  `wSpeedsSupported = 0x000E` (FS|HS|SS) and there is no SUPERSPEED_PLUS
  capability anywhere in the descriptor region. `[C]`

### What is not

Ranked by how much each changes the design.

1. **The engine's sustained rate.** Everything above depends on it and the only
   measurement is one cold call on one frame size: 6064×4042 in 144,431 µs =
   169.7 Mpix/s. `FUN_c062fee8` does the power/clock/IRQ bring-up *inside*
   encode, so a cold call pays it every frame and a recording loop pays it once.
   Fixed overhead and per-pixel rate have never been separated. **Time two or
   three frame sizes and fit.** Probe exists: `raw/ljtime.S`, hooks
   `0xC037E7AC`, times with `FUN_c002b6e0` (a 1 MHz counter).
2. **Whether RWZM's output can feed the engine.** The engine takes CFA/Bayer —
   the stills path proves that. Whether what RWZM writes is still Bayer, in a
   layout and alignment the engine accepts, is untested.
3. **DNG packaging.** Setting the Compression tag does not compress pixels. The
   encoder's output has to be written into the DNG with the right strip
   structure. One stripe per frame, which keeps it simple. `[C]`
4. **The link's real sustained throughput.** 376 MB/s is proven by a shipping
   mode; 625 is theoretical. Irrelevant if compression works — at 196 MB/s there
   is a factor of two in hand either way.

### Do not

- **Do not cold-call the engine. Hook it.** A dozen cold calls broke stills
  compression until a reboot — card file sizes went 26–28 MB (compressed) to
  51 MB (uncompressed) and back to 36 MB after a power cycle.
- **Do not expect compression to rescue a larger frame.** The engine is slower
  than the link, so the compressed ceiling (10 Mpix) is *below* the uncompressed
  theoretical one (13.9 Mpix). Compression buys headroom and reliability, not
  resolution beyond 10 Mpix.

### Related

- `projects/open-gate.md` — the 6K source and the canvas work
- `projects/raw-sup.md` — the engine, its measurement and the roadmap
- `notes/RAW_COMPRESSION_RESEARCH.md` — the method for separating overhead from rate

---

## 繁體中文

### 管線

```
mode 3 / 121      6064x4042 1x1 @29.97,原廠模式(即時取景就是它)
     |            捲簾 24.98 ms —— 固定,那是讀 4042 列的代價
     v
RWZM              0x300F0900 的 16 相位 2-tap 重採樣器
     |            出廠比例 0x640 = 1.5625
     v
XC_HalLjpeg       0x300D0000,無損 JPEG,Bayer 上實測約 2.3:1
     |
     v
SSD               USB 3.x Gen1,5 Gbps,理論 625 MB/s,已證明 376
```

每一段都存在、都在跑。**沒有人把它們照這個順序串過。**

### 決定輸出尺寸的是什麼

鏈路裡一旦有壓縮,它就不再是限制 —— 2.3:1 之後要 31.98 Mpix @29.97 才碰得到
625 MB/s。**唯一的關卡是引擎**,輸出尺寸直接由它的穩態速率決定:

| 引擎 | 29.97 下的輸出 | 寫出 |
|---|---|---|
| 300 Mpix/s — 推論天花板 `[I]` | **3875×2583**(10.0 Mpix) | 196 MB/s |
| 265 Mpix/s — 損益平衡 | 3644×2429 | 174 MB/s |
| 240 Mpix/s | 3466×2310 | 156 MB/s |
| 169.7 Mpix/s — 實測,冷呼叫 `[C]` | 2915×1943(5.7 Mpix) | 111 MB/s |

**265 Mpix/s 是分水嶺。** 低於它,壓縮不如用已證明的 376 MB/s 直接無壓縮寫
3542×2361;高於它,壓縮在尺寸與餘裕上都贏。

`6000×4000 ÷ 1.5625 = 3840×2560` —— 感光元件有效區走出廠的 RWZM 比例、
縮放器一個字都不用動 —— 剛好落在推論天花板底下一點。

### 引擎的 API,來自靜態拍照路徑

靜態路徑本來就把 6064×4042 的 Bayer 壓成無損 DNG。**它就是參考實作**,
HAL 是 `src/hal/RawCD/src/XC_HalLjpeg.cpp`:

```
FUN_c05a6890(9 字)  -> FUN_c062f5a8    啟動編碼
FUN_c05a6920(5 字)  -> FUN_c062f6f8    等完成
FUN_c05a6990(x, 1)  -> FUN_c062fa48    取結果
FUN_c03d9668(addr)                     虛擬 → 匯流排位址轉換
```

編碼的九個字,從 `blk_c03.c` 裡 `StillCr...` 斷言(`0xC037E7AC`)附近的呼叫端讀出:

```
[0] 寬          [1] 高           [2] 來源緩衝(經轉換)
[3] 0x100       [4] 0x100        [5] 目的緩衝
[6] FUN_c0398b00() 的回傳        [7] *(obj+0x0C)
[8] 模式位元組,低位清零
```

等待呼叫吃五個字:`{寬, 高, 緩衝, 0x100, 0x100}`。`FUN_c062f6f8` 就是
`timeout = pixels / 32000` 所在的地方 —— **那是有 5.3 倍餘裕的看門狗,不是吞吐**。
區塊的 `+0xF8` 是產出位元組數,`+0x3FC` 是 busy/clear。

### 已確立

- **錄影時引擎是閒置的。** 錄影走 DSP `0x301B` 與 RFC 讀出 `0x300C`,不衝突。`[C]`
- **可以冷啟動獨立呼叫** —— 包裝函式自己在 encode 裡把 power domain 5、時脈、
  IRQ 0x29 帶起來。`[C]`
- **壓縮比約 2.3:1**(這顆感光元件的 Bayer)。`[C]`
- **單引擎、不能並行**,而且時脈不能提高 —— 與 sensor readout 共用成像域,
  沒有獨立分頻器。`[C]`
- **mode 3 是原廠的 6064×4042 1×1 @29.97 讀出。** 來源不需要發明。`[C]`
- **鏈路是 Gen1。** BOS 的裝置能力是 SUPERSPEED_USB、`wSpeedsSupported = 0x000E`
  (FS|HS|SS),描述元區裡沒有任何 SUPERSPEED_PLUS。`[C]`

### 未確立

按「改變設計的程度」排序。

1. **引擎的穩態速率。** 上面整張表都靠它,而唯一的量測是**一次冷呼叫、一個尺寸**:
   6064×4042 花 144,431 µs = 169.7 Mpix/s。`FUN_c062fee8` 把電源/時脈/IRQ 的拉起
   做在 **encode 裡面**,所以冷呼叫每幀都付,錄影迴圈只付一次。
   **固定開銷與每像素速率從來沒有分離過。量兩三個尺寸再擬合。**
   探針現成:`raw/ljtime.S`,hook `0xC037E7AC`,碼表 `FUN_c002b6e0`(1 MHz)。
2. **RWZM 的輸出能不能餵進引擎。** 引擎吃 CFA/Bayer —— 靜態路徑證明了。
   但 RWZM 寫出來的還是不是 Bayer、擺放與對齊引擎收不收,**沒測過**。
3. **DNG 封裝。** 改 Compression tag 不會讓像素被壓縮,編碼器的輸出要以正確的
   strip 結構寫進 DNG。每幀單 stripe,結構單純。`[C]`
4. **鏈路的真實持續吞吐。** 376 MB/s 由出貨模式證明,625 是理論值。
   壓縮若成立這題就不重要 —— 196 MB/s 兩邊都有一倍餘裕。

### 不要做的

- **不要冷呼叫引擎,要 hook 它。** 連打十幾次冷呼叫把靜態壓縮弄壞到重開機 ——
  卡上檔案從 26–28 MB(有壓縮)變成 51 MB(未壓縮),重開機後回到 36 MB。
- **不要指望壓縮能救更大的畫格。** 引擎比鏈路慢,所以壓縮後的天花板(10 Mpix)
  **低於**無壓縮的理論天花板(13.9 Mpix)。壓縮買到的是餘裕與可靠度,
  不是 10 Mpix 以上的解析度。

### 相關

- `projects/open-gate.md` —— 6K 來源與畫布
- `projects/raw-sup.md` —— 引擎、它的量測與路線圖
- `notes/RAW_COMPRESSION_RESEARCH.md` —— 分離固定開銷與速率的方法
