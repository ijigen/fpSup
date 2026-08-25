# gyro sup

[English](#english) | [繁體中文](#繁體中文)

Gyro, six-axis logging and the Gyroflow workflow.
**Status: core verified on hardware, integration in progress**

Gyro、六軸記錄與 Gyroflow 工作流。**狀態:核心已實機驗證,整合中**

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

### In progress

1. Separate small buffers (about a second each) for gyro and accelerometer,
   flushed to the card when full, to separate files
2. Merging them into one gcsv when recording stops
3. Generating the Gyroflow lens profile (JSON)

### Open

- **IMX410 mode ambiguity** — 1080p29.97 matches both mode 106 and mode 111, whose
  rolling-shutter readout times are 10.556 ms and 7.828 ms. Focal length is
  unaffected. The mode-index field has not been found
- A heavy stop-recording path can miss the next take's start event. A header guard
  is in place, but the root cause is not removed

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

### 進行中

1. 陀螺與加速計分開的小緩衝(約 1 秒)串流寫卡,滿了才寫,寫不同檔案
2. 停止錄影時把兩個檔合併成單一 gcsv
3. 產生 Gyroflow 鏡頭 profile(JSON)

### 未解

- **IMX410 模式歧義** —— 1080p29.97 對應 106 與 111 兩個模式,捲簾讀出時間分別是
  10.556 ms 與 7.828 ms,還沒辦法分辨。焦距不受影響。模式索引欄位也還沒找到
- 停止錄影的路徑太重會漏掉下一段的開始事件(已加檔頭防護,但根因未除)

---

**Notes / 相關筆記:** `GYRO_IMU_GYROFLOW`, `GYROFLOW_ORIENTATION_SOLVED`,
`ONCAMERA_GCSV_AND_LENS_PROFILE`, `SD_WRITE_LATENCY_MEASURED`,
`RECORDING_GEOMETRY_AND_LENS_PROGRAM`
