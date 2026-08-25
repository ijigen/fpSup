# raw sup

Bayer 擷取、串流、壓縮與 RAW 封裝。

**狀態:研究完成度高,尚未做出成品**

---

## 目標

把感光元件的原始 Bayer 資料從相機取出來,並找出可行的壓縮與封裝路徑,
最終目標是自製錄影路徑或外接錄影機。

## 已確認

- **HDMI RAW 輸出是活的路徑** —— 它會把 12-bit Bayer 放進 DRAM,只是被選單擋住。
  這是目前最有希望的取得管道
- **硬體無損 JPEG 編碼器** (`0x300D0000`) 可以由 worker 獨立呼叫,
  屬於靜態影像等級的速度(這也解釋了為什麼錄影是無壓縮的)。可以拿來預壓縮 USB 擷取
- **偵測影像通道** `0xC375D8C0` —— 乾淨的 320×240 線性 8-bit 灰階,hook-push 已驗證。
  顯示掃描輸出是**分塊的**(16 px tile),不要拿去解碼
- **hook-push 通道** 0.125 ms/frame、零 stall,峰值約 311 MB/s

## 已推翻的舊結論

`0x50000000` 曾被當成 Bayer DMA base,實測是空的;而「所有 `0x3011xxxx` SIG 暫存器讀出來是 0」
那組推論**整組作廢** —— 設定其實在 `0x3021xxxx` 的影子區。
`still_raw_dump` 的 `0xC343A624.2` 會**當掉相機**,不要碰。

## 未做

- 實際把 Bayer 影格搬出來(HDMI RAW 路徑尚未打通)
- CinemaDNG 封裝
- 外接錄影機(規格書已寫,見 `RECORDER_SPEC`)

## 相關筆記

`RAW_GRAB`、`RAW_PUSH`、`RAW_COMPRESSION_RESEARCH`、`HW_LOSSLESS_JPEG_CODEC`、
`HDMI_RAW`、`HDMI_RAW_RECORDER_BUILD`、`IMAGE_CHANNELS`、`RECORDER_SPEC`、`FORMAT`
