# raw sup

[English](#english) | [繁體中文](#繁體中文)

Bayer capture, streaming, compression and RAW packaging.
**Status: researched, no deliverable yet**

Bayer 擷取、串流、壓縮與 RAW 封裝。**狀態:研究完成度高,尚未做出成品**

---

## English

### Goal

Get the sensor's raw Bayer data out of the camera and find a workable compression
and packaging path, aiming at a custom recording path or an external recorder.

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
