# gyro sup

[English](#english) | [繁體中文](#繁體中文)

Gyro, six-axis logging and the Gyroflow workflow.
**Status: released — [fpGyroSup v1](https://github.com/ijigen/fpSup/raw/main/gyro/release/fpGyroSup-v1.zip)** · [release notes](../gyro/release/)

Gyro、六軸記錄與 Gyroflow 工作流。**狀態:已發布 —— [fpGyroSup v1 下載](https://github.com/ijigen/fpSup/raw/main/gyro/release/fpGyroSup-v1.zip)** · [說明](../gyro/release/)

---

## English

### Goal

Log six-axis data inside the camera and write a Gyroflow-ready `.gcsv` the moment
recording stops, together with a lens profile, so stabilisation needs no
conversion step at all.

### Proven

- **The gyro hook** at `0xC00D0794`; the ring is at `*(0xC31E3FCC) + 0x60`,
  600 samples × 8 bytes = 240 ms
- **The camera writes its own gcsv.** Stopping a recording produces Gyroflow
  format directly, matched row by row against a reference
- **Orientation is `xyz` with all three axes negated** — verified column by column
  on three single-axis takes. The archived `YxZ` is wrong. Accelerometer data must
  be left out (it poisons the A/B comparison through VQF), and the offset differs
  per clip
- **Card writes during recording take up to 692 ms** while the ring holds only
  240 ms, so the gyro thread cannot write the card itself — a background writer is
  required. `OVERFLOW=0` does not mean nothing was lost
- **Recording geometry** at `0xC37CE210` = {1936, 1090, 3244544}, which closed the
  resolution gap in the lens profile
- IMU: ICM20321 gyro at 2500 Hz, MMA8452Q accelerometer at 100 Hz
- **Streaming to the card as it records** (2026-08-26). Two 16 KiB halves, one
  filling while a background thread writes the other. A six second take gave
  eight blocks, 15036 samples at 2500.0 Hz, every CRC-32 recomputing, sequence
  numbers unbroken, nothing dropped and nothing clamped. The take no longer has
  to fit in memory, and a flat battery costs one block instead of everything

### Fixed the day the first capture decoded

The camera reported success on all of these. The file did not.

- **The buffers were not ours.** `memmgr bufmem get 0 0x20000 0x40` returns 128
  bytes: the handler parses the alignment into the size slot. Everything past
  those 128 bytes belonged to a 256 KiB buffer that the recorder reinitialises,
  so 16 KiB every 0.8 s landed in video memory — a torn picture, a freeze, or
  nothing, depending on timing. Ask for three arguments, never four, and check
  what you got with `memmgr bufchk`
- **Every ring wrap carried four stray bytes.** The count treated the ring as
  0x12C4 bytes when it holds 0x12C0, so each wrap shifted every later sample out
  of phase. The breaks in a 247 KB capture fell exactly 0x12C4 apart. Stage-5 has
  the same constant
- **The header said `YxZ` and 0.000121385**, both corrected in stage5 long ago and
  never here

### In progress

1. Accelerometer alongside the gyro in the same stream
2. Writing the gcsv on the camera at record stop, as stage5 does
3. Generating the Gyroflow lens profile (JSON)

### Open

- ~~IMX410 mode ambiguity~~ — **settled 2026-08-26: mode 106, readout 10.556 ms.**
  `FUN_c032c720()` takes no arguments and returns the current sensor mode enum;
  it is what `imager mode_now` prints, and the logger calls it at record start so
  every clip now carries its own. A 1080p29.97 12-bit CinemaDNG take reads 106,
  which makes the archived answer of 111 wrong by 35%
- A heavy stop-recording path can miss the next take's start event. A header guard
  is in place, but the root cause is not removed
- **MOV writes no gcsv and no json.** The `.GYR` is written as usual, so the gyro
  data is there, but both other files take their path from `\CINEMA\<clip>\`,
  which a MOV recording has no equivalent of. The open fails and the writer
  returns, so recording is unaffected. Confirmed on hardware 2026-08-30. The fix
  needs to know where a MOV's clip identity lives, or to fall back to `\GYRO\`

---

## 繁體中文

### 目標

在相機內記錄六軸資料,停止錄影時直接產生 Gyroflow 可用的 `.gcsv`,
連同鏡頭 profile 一起,讓穩定化不需要任何後製轉檔。

### 已驗證

- **陀螺 hook** `0xC00D0794`,ring 在 `*(0xC31E3FCC)+0x60`,600 筆 × 8 bytes = 240 ms
- **機身端直接產生 gcsv** —— 停止錄影就寫出 Gyroflow 格式,逐列與參考資料比對一致
- **方位確定為 `xyz` 且三軸全部取負** —— 用三段單軸素材逐欄驗證過;
  archive 裡的 `YxZ` 是錯的。加速度計要排除(它會透過 VQF 汙染 A/B 比對),offset 每段不同
- **錄影中寫卡最壞延遲 692 ms** —— 而 ring 只有 240 ms,所以陀螺執行緒不能直接寫卡,
  必須有背景 writer。`OVERFLOW=0` 不代表沒掉資料
- **錄影幾何** `0xC37CE210` = {1936, 1090, 3244544},解掉 lens profile 的解析度缺口
- IMU:ICM20321 陀螺(2500 Hz)+ MMA8452Q 加速度計(100 Hz)

### 錄影中即時寫卡(2026-08-26 完成)

兩個 16 KiB 半區,一邊填一邊由背景執行緒寫另一邊。六秒的一段產出八個區塊、
15036 筆樣本、2500.0 Hz,CRC 全部相符、序號無斷點、零掉批、零截斷。
**錄影長度不再受記憶體限制,而且沒電只會丟一個區塊而不是整段。**

### 第一次成功解碼那天修掉的

以下每一項相機都回報成功,是**檔案**說出真相的。

- **緩衝根本不是我們的。** `memmgr bufmem get 0 0x20000 0x40` 只給 128 bytes ——
  handler 把對齊參數寫進了 size 的位置。那 128 bytes 之後屬於一塊 256 KiB 的緩衝,
  錄影開始時被它的擁有者重新初始化。我們每 0.8 秒往裡面寫 16 KiB,踩到影像緩衝
  就花屏、踩到別的就凍結。**只能傳三個參數,而且配完要用 `memmgr bufchk` 驗**
- **每次環形繞回多 4 個位元組。** 環形長度是 0x12C0,計數卻用 0x12C4,於是每繞回
  一次後面所有樣本就位移。247 KB 的檔案裡斷點正好相隔 0x12C4。**stage5 也有**
- **檔頭寫著 `YxZ` 和 0.000121385**,兩個都是 stage5 早就修過、這裡卻沒跟上的

### 進行中

1. 陀螺與加速計分開的小緩衝(約 1 秒)串流寫卡,滿了才寫,寫不同檔案
2. 停止錄影時把兩個檔合併成單一 gcsv
3. 產生 Gyroflow 鏡頭 profile(JSON)

### 未解

- **IMX410 模式歧義** —— 1080p29.97 對應 106 與 111 兩個模式,捲簾讀出時間分別是
  10.556 ms 與 7.828 ms,還沒辦法分辨。焦距不受影響。模式索引欄位也還沒找到
- 停止錄影的路徑太重會漏掉下一段的開始事件(已加檔頭防護,但根因未除)
- **錄 MOV 不會產生 gcsv 與 json。** `.GYR` 照常寫,陀螺資料沒有丟,但另外兩個檔
  的路徑都是從 `\CINEMA\<clip>\` 組出來的,MOV 沒有對應的片段資料夾;開檔失敗
  就返回,不影響錄影。2026-08-30 實機確認。要修得先知道 MOV 的片段身分放在哪,
  或者退一步全部寫進 `\GYRO\`

---

**Notes / 相關筆記:** `GYRO_IMU_GYROFLOW`, `GYROFLOW_ORIENTATION_SOLVED`,
`ONCAMERA_GCSV_AND_LENS_PROFILE`, `SD_WRITE_LATENCY_MEASURED`,
`RECORDING_GEOMETRY_AND_LENS_PROGRAM`
