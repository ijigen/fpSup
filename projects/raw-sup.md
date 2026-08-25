# raw sup

[English](#english) | [繁體中文](#繁體中文)

Bayer capture, streaming, compression and RAW packaging.
**Status: researched; lossless UHD to card hinges on one unmeasured number**

Bayer 擷取、串流、壓縮與 RAW 封裝。**狀態:研究完成;無損 UHD 寫卡壓在一個沒量過的數字上**

---

## English

### Goal

Get the sensor's raw Bayer data out of the camera and find a workable compression
and packaging path, aiming at a custom recording path or an external recorder.

### The goal: UHD RAW to the card

Recording CinemaDNG UHD 12-bit at 29.97 to the SD card, and 14-bit after that.

**Uncompressed UHD 12-bit is 12.44 MB per frame:**

| fps | rate | to SD |
|---|---|---|
| 30 | 373 MB/s | beyond even a top V90 UHS-II card (~250–290) |
| 24 | 298 MB/s | still beyond |
| 12 | 149 MB/s | feasible |
| 10 | 124 MB/s | feasible |

FHD 12-bit at 24 fps is 74.6 MB/s, the figure the camera itself allows — that the
arithmetic reproduces it is the check that the model is right.

So uncompressed 30 fps does not fit. **Compressed might.**

### The compression engine, and the number that decides everything

`0x300D0000` is a fixed-function lossless-JPEG engine — the `Compression=7` used
for still DNG. What is known:

- **Clock ≈ 300 MHz** at roughly **1 pixel per clock**, giving a ceiling near
  **300 Mpixel/s**; the working estimate is 150–300
- **UHD30 lossless needs 248.8 Mpixel/s.** At ~2:1 that is ~186 MB/s, which a top
  UHS-II card holds
- **The engine is idle during video.** Recording uses the DSP at `0x301B` and the
  RFC readout at `0x300C`, not this one, so there is no contention to design
  around
- **It is cold standalone-callable**, confirmed: the wrappers bring up power
  domain 5, the clock and IRQ 0x29 themselves, and a synthetic source buffer
  works with no live capture
- **The limits in the way are firmware, not silicon.** The SD-versus-SSD gate is
  menu-layer policy (`EXCL_CinemaDNGQuality`), the firmware never compares a MB/s
  or speed-class figure, and CinemaDNG's `Compression=1` is set by a single
  function with a single caller

**So this is potentially feasible and hinges on one unmeasured number:** the
engine's true sustained Mpixel/s. The ceiling says yes, the floor says no, and
nothing in the firmware measures it — there is no performance counter anywhere.

The one risk that cannot be settled by reading code is whether the variable-length
coder drops below a pixel per clock on high-entropy tiles.

### The experiment that settles it

While the camera is idle, drive `0x300D` on a known 1 KB-aligned buffer
(`FUN_c05a6890` to initialise, `FUN_c05a6920` to encode) and time the IRQ-0x29
completion against the pixel count. Repeat at a few sizes to separate fixed
overhead from the per-pixel rate. The engine is idle when not shooting stills, so
this is contention-safe, and the shell can now run injected code, so it costs one
routine.

### A correction worth keeping

An earlier reading of this engine put its throughput at 32 Mpixel/s and concluded
lossless UHD to card was infeasible by a factor of eight. **That number was a
watchdog timeout with about nine times' safety margin, not a throughput figure** —
it proves only that the engine is *at least* that fast. The conclusion built on it
was wrong, and it was quoted again later in this repository before being caught.
A number that is internally consistent is not thereby correct.

### 14-bit

The sensor and the codec already do 14-bit: **fp still photos are 14-bit
`Compression=7` lossless JPEG**, 6064×4042, tiled 256×256, WhiteLevel 16383. So
nothing has to be invented.

What blocks 14-bit video is the readout path. `imager set_gain_state` offers
`5` movie_raw_10bit, `6` movie_raw_12bit and `7` movie_raw_8bit — **there is no
14-bit movie mode**. Whether one can be reached is the open question, and the
rate is worse again: UHD 14-bit uncompressed is 14.5 MB per frame, 435 MB/s at 30
fps and 145 MB/s at 10.

### Proven

- **HDMI RAW output is a live path.** It puts 12-bit Bayer into DRAM and is only
  gated by a menu setting — currently the most promising way to obtain frames
- **The hardware lossless JPEG encoder** (`0x300D0000`) can be called standalone by
  the worker, at stills-class speed, which is also why video is uncompressed. It
  can pre-compress a USB capture
- **The detection image channel** at `0xC375D8C0` is a clean 320×240 linear 8-bit
  greyscale, proven over hook-push. The display scanout is **tiled** (16 px tiles)
  — do not try to decode that one
- **The hook-push channel** runs at 0.125 ms/frame with no stall, peaking around
  311 MB/s

### Retracted

`0x50000000` was taken to be the Bayer DMA base; it is idle and empty. The whole
argument built on "every `0x3011xxxx` SIG register reads 0" is **void** — the
configuration lives in a shadow bank at `0x3021xxxx`. `still_raw_dump`'s
`0xC343A624.2` **hangs the camera**; do not touch it.

### Not done

- Actually extracting Bayer frames (the HDMI RAW path is not open yet)
- CinemaDNG packaging
- The external recorder (specification written, see `RECORDER_SPEC`)

---

## 繁體中文

### 目標

把感光元件的原始 Bayer 資料從相機取出來,並找出可行的壓縮與封裝路徑,
最終目標是自製錄影路徑或外接錄影機。

### 目標:UHD RAW 寫進卡片

在 SD 卡上錄 CinemaDNG UHD 12-bit 29.97,之後再挑戰 14-bit。

**未壓縮 UHD 12-bit 每幀 12.44 MB:**

| fps | 位元率 | 寫 SD |
|---|---|---|
| 30 | 373 MB/s | 超過頂級 V90 UHS-II(~250–290) |
| 24 | 298 MB/s | 仍然超過 |
| 12 | 149 MB/s | 可行 |
| 10 | 124 MB/s | 可行 |

FHD 12-bit 24 fps 是 74.6 MB/s,正是相機自己允許的數字 —— 算術能重現它,
就是這個模型沒錯的檢查點。

所以**未壓縮的 30 fps 塞不下。壓縮之後有機會。**

### 壓縮引擎,以及決定一切的那個數字

`0x300D0000` 是固定功能的無損 JPEG 引擎,也就是靜態 DNG 用的 `Compression=7`。已知:

- **時脈約 300 MHz**、約 **1 pixel/clock**,上限接近 **300 Mpixel/s**;工作估計 150–300
- **UHD30 無損需要 248.8 Mpixel/s。** 以 ~2:1 計是 ~186 MB/s,頂級 UHS-II 卡放得下
- **錄影期間這顆引擎是閒置的。** 影片走 `0x301B` 的 DSP 與 `0x300C` 的 RFC 讀出,
  不是它,所以沒有引擎爭用要處理
- **冷啟動獨立呼叫已確認**:包裝函式自己會把 power domain 5、時脈與 IRQ 0x29 帶起來,
  用合成的來源緩衝就能跑,不需要實際拍攝
- **擋路的限制是韌體不是矽。** SD 對 SSD 的閘門是選單層政策(`EXCL_CinemaDNGQuality`),
  韌體**從不比對 MB/s 或速度等級**,而 CinemaDNG 的 `Compression=1`
  是由**單一函式、單一呼叫者**設定的

**所以這件事「潛在可行」,而且壓在一個沒人量過的數字上:**引擎的真實持續吞吐。
上限說可以,下限說不行,而韌體裡沒有任何效能計數器可以問。

唯一沒辦法靠讀程式碼定案的風險是:**變長編碼在高熵 tile 上會不會掉到 1 pixel/clock 以下。**

### 能定案的實驗

相機閒置時,對一塊已知的 1 KB 對齊緩衝驅動 `0x300D`
(`FUN_c05a6890` 初始化、`FUN_c05a6920` 編碼),對 IRQ-0x29 的完成計時、除以像素數。
換幾種尺寸重複,把固定開銷與每像素速率分離。
引擎在沒拍靜態照時是閒置的,所以不會有爭用;而 shell 現在能執行注入的程式碼,
成本只有一支常式。

### 一個值得留著的修正

早先對這顆引擎的解讀把吞吐當成 32 Mpixel/s,並據此結論「無損 UHD 寫卡差八倍,不可行」。
**那個數字是看門狗逾時、帶著約九倍安全餘裕,不是吞吐量** ——
它只證明引擎「至少」有那麼快。建立在它上面的結論是錯的,
而且在這個 repo 裡又被引用了一次才被抓到。
**一個內部自洽的數字,不因此就是對的。**

### 14-bit

感光元件與編碼器**本來就會 14-bit**:**fp 的靜態照片就是 14-bit 的
`Compression=7` 無損 JPEG**,6064×4042、tile 256×256、WhiteLevel 16383。
所以沒有東西需要發明。

擋住 14-bit 影片的是讀出路徑。`imager set_gain_state` 提供
`5` movie_raw_10bit、`6` movie_raw_12bit、`7` movie_raw_8bit ——
**沒有 14-bit 的 movie 模式**。能不能弄出一個,就是未解的問題;
而且位元率更差:UHD 14-bit 未壓縮每幀 14.5 MB,30 fps 是 435 MB/s,10 fps 是 145 MB/s。

### 已確認

- **HDMI RAW 輸出是活的路徑** —— 它會把 12-bit Bayer 放進 DRAM,只是被選單擋住。
  這是目前最有希望的取得管道
- **硬體無損 JPEG 編碼器** (`0x300D0000`) 可以由 worker 獨立呼叫,
  屬於靜態影像等級的速度(這也解釋了為什麼錄影是無壓縮的)。可以拿來預壓縮 USB 擷取
- **偵測影像通道** `0xC375D8C0` —— 乾淨的 320×240 線性 8-bit 灰階,hook-push 已驗證。
  顯示掃描輸出是**分塊的**(16 px tile),不要拿去解碼
- **hook-push 通道** 0.125 ms/frame、零 stall,峰值約 311 MB/s

### 已推翻的舊結論

`0x50000000` 曾被當成 Bayer DMA base,實測是空的;而「所有 `0x3011xxxx` SIG 暫存器讀出來是 0」
那組推論**整組作廢** —— 設定其實在 `0x3021xxxx` 的影子區。
`still_raw_dump` 的 `0xC343A624.2` 會**當掉相機**,不要碰。

### 未做

- 實際把 Bayer 影格搬出來(HDMI RAW 路徑尚未打通)
- CinemaDNG 封裝
- 外接錄影機(規格書已寫,見 `RECORDER_SPEC`)

---

**Notes / 相關筆記:** `RAW_GRAB`, `RAW_PUSH`, `RAW_COMPRESSION_RESEARCH`,
`HW_LOSSLESS_JPEG_CODEC`, `HDMI_RAW`, `HDMI_RAW_RECORDER_BUILD`, `IMAGE_CHANNELS`,
`RECORDER_SPEC`, `FORMAT`
