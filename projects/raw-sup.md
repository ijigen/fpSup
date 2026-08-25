# raw sup

[English](#english) | [繁體中文](#繁體中文)

Bayer capture, streaming, compression and RAW packaging.
**Status: researched; the arithmetic says which version of the goal is reachable**

Bayer 擷取、串流、壓縮與 RAW 封裝。**狀態:研究完成;算術已經指出這個目標哪個版本搆得到**

---

## English

### Goal

Get the sensor's raw Bayer data out of the camera and find a workable compression
and packaging path, aiming at a custom recording path or an external recorder.

### The goal: UHD RAW to the card

Recording CinemaDNG UHD 12-bit at 29.97 to the SD card, and eventually 14-bit.
The arithmetic decides most of this, so here it is.

**Uncompressed UHD 12-bit is 12.44 MB per frame:**

| fps | rate | to SD |
|---|---|---|
| 30 | 373 MB/s | beyond even a top V90 UHS-II card (~250–290) |
| 24 | 298 MB/s | still beyond |
| 12 | 149 MB/s | **feasible** |
| 10 | 124 MB/s | **feasible** |

FHD 12-bit at 24 fps is 74.6 MB/s, which is the figure the camera itself allows —
that the arithmetic reproduces it is the check that the model is right.

**Lossless compression does not rescue 29.97.** The `0x300D0000` engine's
throughput works out to about 32 Mpixel/s — roughly a pixel per clock at a 32 MHz
engine clock — which is 0.26 s for a UHD frame, or about **4 fps**. Even FHD only
reaches about 15. The camera uses that engine for **still** DNG only, never for
video, and this is why. A factor of seven is not a tuning problem.

**So the reachable version of this goal is UHD 12-bit uncompressed at 10–12 fps**,
through a three-address gate patch and no codec at all. That is worth having for
timelapse, astro and product work even though it is not 29.97.

**That throughput number is an estimate, not a measurement**, and it is the single
number the whole conclusion rests on. The engine is standalone-callable and the
shell can now run injected code, so compressing one known frame and timing it
would settle it. If the real figure is far higher, this all gets recomputed; if it
matches, lossless UHD at video rate is closed and no more time goes into it.

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
這件事大部分由算術決定,所以直接把數字放上來。

**未壓縮 UHD 12-bit 每幀 12.44 MB:**

| fps | 位元率 | 寫 SD |
|---|---|---|
| 30 | 373 MB/s | 超過頂級 V90 UHS-II(~250–290) |
| 24 | 298 MB/s | 仍然超過 |
| 12 | 149 MB/s | **可行** |
| 10 | 124 MB/s | **可行** |

FHD 12-bit 24 fps 是 74.6 MB/s,那正是相機自己允許的數字 ——
算術能重現它,就是這個模型沒錯的檢查點。

**無損壓縮救不了 29.97。** `0x300D0000` 那顆引擎的吞吐算出來約 **32 Mpixel/s**
(約 1 pixel/clock @ 32 MHz 引擎時脈),一張 UHD 要 0.26 秒,也就是**約 4 fps**。
連 FHD 都只到約 15。相機**只在靜態 DNG 用那顆引擎、從不用在影片上**,原因就在這裡。
差七倍不是調參數的問題。

**所以這個目標能達成的版本是:UHD 12-bit 未壓縮、10–12 fps**,
靠三個位址的 gate patch,完全不需要 codec。
雖然不是 29.97,但對縮時、天文、產品攝影都值得。

**那個吞吐數字是推估不是量測**,而整個結論就壓在它身上。
那顆引擎可以被獨立呼叫,而 shell 現在能執行注入的程式碼 ——
**壓一張已知的圖並計時就能定案**。實測遠高於推估的話,以上全部重算;
吻合的話,「影片速率的無損 UHD」就正式關閉,不必再投入時間。

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
