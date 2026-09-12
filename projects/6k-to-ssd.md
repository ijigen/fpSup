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
     |            **on every other frame** -- see the next section
     v
SSD               USB 3.x Gen1, 5 Gbps, 625 MB/s theoretical, 379 measured
```

Every stage exists and runs today. None of them has been run in this order.

### The design: alternate-frame compression

Compressing **every frame** wastes the link; compressing **no frame** wastes the
engine. Compressing a *fraction* of the frames makes both constraints bind at
once, and that is worth a third more pixels than either extreme.

With `f` the fraction of frames compressed, `E` the engine's rate, `L` the link
budget and `C` the compression ratio:

```
engine allows   px <= E / (f x fps)
link allows     px <= L / (1.5 x fps x (1 - f/C))
optimum         f  =  1.5E / (L + 0.75E)
```

At E=300 Mpix/s, L=500 MB/s, C=2 the optimum is f=0.62 and 16.1 Mpix. **Take
f=1/2**: 14.83 Mpix at 4717x3144, which is 33% more than uncompressed and 48%
more than compressing everything, and unlike f=0.62 it leaves timing margin.

| | Mpix | size | vs uncompressed |
|---|---|---|---|
| compress nothing | 11.12 | 4085x2723 | — |
| compress everything | 10.01 | 3875x2583 | −10% |
| **compress every other frame** | **14.83** | **4717x3144** | **+33%** |

### Why alternate frames and not half a frame

Half a frame does not survive the container. **TIFF's `Compression` tag is per
IFD**, so one file cannot hold a compressed half and an uncompressed half; no
reader would reassemble it.

Alternate *frames* is free of that. CinemaDNG is a sequence of independent files
and each declares its own `Compression`, so frame 1 can be `Compression=7` and
frame 2 `Compression=1` with both remaining valid DNGs.

> **Assumption, not verified:** that readers tolerate a mixed sequence. A reader
> that caches the first frame's parameters for the whole sequence would break.
> This is testable on the host with no camera — build a sequence that alternates
> and open it in Resolve.

### Timing and buffer

```
frame time                     33.4 ms at 29.97
compressing one 14.83 Mpix frame at 300 Mpix/s   49.4 ms
budget when only every other frame is compressed 66.7 ms   -> 26% margin
buffer: compression may lag by one frame          ~22 MB
```

At f=0.62 the margin is zero, which is why 1/2 is the engineering choice rather
than the arithmetic optimum.

### The number the whole design rests on

```
break-even engine rate = 0.5 x 11.12 Mpix x 29.97 = 167 Mpix/s
measured, one cold call                            169.7 Mpix/s
```

**They are the same number.** At the measured rate this design gains 2% and is
not worth building; at 240 Mpix/s it gains 33%.

The measurement is a cold call and `FUN_c062fee8` brings up the power domain,
clock and IRQ *inside* encode — a cost a recording loop pays once and a cold call
pays every time — so the true sustained rate is very likely higher. Nobody has
separated them. **Until that is measured, the size of this design is unknown by
a factor of 1.3.**

### For reference: compressing every frame

Superseded by the design above, kept because the arithmetic explains why. If
*every* frame is compressed the link stops being the constraint — it would take
31.98 Mpix at 29.97 to reach 625 MB/s after 2.3:1 — and **the engine becomes the
only gate**, so the output follows straight from its rate:

| engine | output at 29.97 | written |
|---|---|---|
| 300 Mpix/s — inferred ceiling `[I]` | **3875×2583** (10.0 Mpix) | 196 MB/s |
| 265 Mpix/s — break-even | 3644×2429 | 174 MB/s |
| 240 Mpix/s | 3466×2310 | 156 MB/s |
| 169.7 Mpix/s — measured, cold `[C]` | 2915×1943 (5.7 Mpix) | 111 MB/s |

**265 Mpix/s is the break-even for this variant**, against writing 3542×2361
uncompressed at the measured 379 MB/s. Note this is a different threshold from
the 167 Mpix/s above: that one is for alternate-frame compression against a 500
MB/s budget, this one is for full compression against 379. Two designs, two
thresholds; the alternate-frame design is the one to build.

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

### 設計:隔幀壓縮

**每幀都壓會浪費鏈路,每幀都不壓會浪費引擎。** 只壓一部分的幀,兩個限制才會
同時吃滿 —— 而那比任何一個極端都多出三分之一的像素。

令 `f` 為被壓縮的幀比例、`E` 引擎速率、`L` 鏈路預算、`C` 壓縮比:

```
引擎允許   px <= E / (f × fps)
鏈路允許   px <= L / (1.5 × fps × (1 - f/C))
最佳       f  =  1.5E / (L + 0.75E)
```

E=300、L=500、C=2 時最佳 f=0.62、16.1 Mpix。**取 f=1/2**:14.83 Mpix、
4717×3144 —— 比不壓多 33%、比全壓多 48%,而且不像 f=0.62 那樣時序沒有餘裕。

| | Mpix | 尺寸 | 對比不壓 |
|---|---|---|---|
| 完全不壓 | 11.12 | 4085×2723 | — |
| 每幀都壓 | 10.01 | 3875×2583 | −10% |
| **隔幀壓** | **14.83** | **4717×3144** | **+33%** |

### 為什麼是隔幀,不是半張圖

半張圖過不了容器。**TIFF 的 `Compression` tag 是每個 IFD 一個**,所以一個檔案
不可能一半壓、一半不壓,沒有讀取器組得回來。

隔**幀**沒有這個問題。CinemaDNG 是一串獨立的檔案,每個自己宣告 `Compression`,
所以第 1 幀 `Compression=7`、第 2 幀 `Compression=1`,**兩個都是合法 DNG**。

> **這是假設,沒驗證:**讀取器能不能吃混合的序列。如果某個讀取器把第一幀的參數
> 套用到整個序列,就會壞。**這可以在主機上測,不用相機** —— 做一個交替的序列,
> 丟進 Resolve 打開。

### 時序與緩衝

```
每幀                                    33.4 ms @29.97
壓一張 14.83 Mpix @300 Mpix/s            49.4 ms
隔幀壓的預算                             66.7 ms   -> 26% 餘裕
緩衝:壓縮最多落後一幀                    約 22 MB
```

f=0.62 的餘裕是零,所以 1/2 才是工程上對的選擇,而不是算術上的最佳解。

### 整個設計壓在哪個數字上

```
損益平衡的引擎速率 = 0.5 × 11.12 Mpix × 29.97 = 167 Mpix/s
實測,一次冷呼叫                              169.7 Mpix/s
```

**兩個是同一個數字。** 用實測值算,這個設計只賺 2%,不值得做;
引擎若有 240,就賺 33%。

那次量測是冷呼叫,而 `FUN_c062fee8` 把電源域、時脈、IRQ 的拉起做在 encode
**裡面** —— 錄影迴圈只付一次,冷呼叫每次都付 —— 所以真實穩態速率很可能更高。
**沒有人分離過。在量出來之前,這個設計的尺寸有 1.3 倍的不確定。**

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
