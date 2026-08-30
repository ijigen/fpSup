# fpGyroSup

[English](#english) | [繁體中文](#繁體中文)

Gyro, six-axis logging and the Gyroflow workflow.
**Status: released — [fpGyroSup v1.1](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.1.zip)** · [release notes](../gyro/release/)

Gyro、六軸記錄與 Gyroflow 工作流。**狀態：已發布 —— [fpGyroSup v1.1 下載](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.1.zip)** · [說明](../gyro/release/)

---

## English

### Goal

Record six-axis data inside the camera and leave a Gyroflow-ready GCSV plus lens
profile beside every CinemaDNG take, with no computer conversion step.

### Released path

```text
recording -> streamed .GYR -> native finalise -> GCSV -> JSON -> unlock
```

- The ICM20321 gyro is captured at 2500 Hz and the MMA8452Q accelerometer at
  100 Hz.
- The `.GYR` streams during recording through two bounded buffers. A one-hour
  take does not have to fit in RAM.
- The camera converts the closed `.GYR` into a seven-column GCSV and generates a
  Gyroflow lens profile from its lens and IMX410 mode data.
- v1.1 extends the firmware's native `MovieSaving` state from GYR close through
  GCSV and JSON. The camera rejects another recording and delays normal shutdown
  until the transaction is complete.
- There is no boot recovery or deferred rewrite path. An interrupted sidecar is
  not silently repaired later.

### Verified on hardware

The v1.1 release image was tested on a SIGMA fp with firmware 5.02 and an SD card:

- consecutive CinemaDNG recordings of 41.56 s and 51.48 s;
- 103,888 and 128,688 six-axis rows;
- zero dropped samples and zero logger errors;
- both GCSV data bodies byte-identical to host decoding;
- both JSON profiles complete and valid;
- the second recording began only after the first JSON completed.

This also verifies the intended bounded post-process delay: about 9 seconds for
the 42-second take and 11 seconds for the 51-second take. Normal power-off uses
the same native wait state.

### Established technical facts

- Gyro callback: `0xC00D0794`; hardware ring:
  `*(0xC31E3FCC) + 0x60`, 600 × 8-byte samples, or 240 ms.
- GYR v5 identifies the native clip, volume and adapter explicitly. Every block
  has sequence, timestamps, payload length and CRC-32; the footer carries block
  count, dropped samples and error flags.
- Orientation is `xyz`; gyro axes are stored with the camera's verified sign
  transform. GCSV accelerometer axes are mapped `(ax, ay, az) -> (ay, -ax, az)`.
- GCSV is written in 16 KiB chunks with 5 ms cooperative yields. The writer does
  not retain the entire converted take in memory.
- Recording geometry, sensor mode, rolling-shutter time and focal length come
  from the camera and lens rather than filename guesses.

### Remaining scope

- **MOV:** v1.1 records its `.GYR`, but does not yet place `.gcsv` and `.json`
  sidecars because MOV lacks the current `\CINEMA\<clip>\` destination.
- **External SSD:** the native adapter has explicit volume state, but v1.1 has
  only been verified with CinemaDNG on SD. SSD recording remains untested.
- **Performance:** GCSV generation is correct but not yet interleaved with GYR
  writing. Optimising it must preserve zero dropped samples and the single
  transaction guarantee.

---

## 繁體中文

### 目標

在相機內記錄六軸資料，讓每段 CinemaDNG 旁邊直接留下 Gyroflow 可用的 GCSV 與
鏡頭 profile，不需要電腦轉檔。

### 已發布流程

```text
錄影 -> 串流 .GYR -> 原生收尾 -> GCSV -> JSON -> 解鎖
```

- ICM20321 陀螺以 2500 Hz 記錄，MMA8452Q 加速度計為 100 Hz。
- `.GYR` 在錄影期間透過兩個有限緩衝串流寫入；錄一小時也不需要全部塞進 RAM。
- 相機把關閉後的 `.GYR` 轉成七欄 GCSV，並依鏡頭與 IMX410 模式資料產生 Gyroflow
  鏡頭 profile。
- v1.1 從 GYR 關檔一路延長韌體原生的 `MovieSaving` 狀態，涵蓋 GCSV 與 JSON。
  在交易完成前，相機會拒絕下一段錄影，正常關機也會等待。
- 沒有開機復原或延後補寫流程；被強制中斷的 sidecar 不會在之後悄悄重寫。

### 實機驗證

v1.1 release image 已在 SIGMA fp 韌體 5.02 與 SD 卡上完成：

- 連續錄製 41.56 秒與 51.48 秒兩段 CinemaDNG；
- 分別 103,888 與 128,688 列六軸資料；
- 掉樣 0、logger 錯誤 0；
- 兩份 GCSV 資料本體與主機解碼逐位元相同；
- 兩份 JSON 都完整有效；
- 第一段 JSON 完成後，相機才接受第二段錄影。

這也確認預期的有限後處理時間：42 秒素材約 9 秒，51 秒素材約 11 秒。正常關機會
等待同一個原生狀態解除。

### 已確立的技術資料

- 陀螺 callback：`0xC00D0794`；硬體 ring：
  `*(0xC31E3FCC) + 0x60`，600 × 8 bytes，也就是 240 ms。
- GYR v5 明確記錄原生片段身分、volume 與 adapter。每個 block 都有序號、時間戳、
  payload 長度與 CRC-32；footer 記錄 block 數、掉樣與錯誤旗標。
- 方位為 `xyz`，陀螺軸使用實機驗證過的符號轉換；GCSV 加速度軸為
  `(ax, ay, az) -> (ay, -ax, az)`。
- GCSV 每次寫 16 KiB，協作讓步 5 ms，不會把整段轉換結果留在記憶體。
- 錄影幾何、sensor mode、捲簾時間與焦距都取自相機與鏡頭，不靠檔名猜測。

### 後續範圍

- **MOV：** v1.1 會記錄 `.GYR`，但尚未產生 `.gcsv` 與 `.json`，因為 MOV 沒有目前
  使用的 `\CINEMA\<clip>\` 目的地。
- **外接 SSD：** native adapter 已有明確 volume 狀態，但 v1.1 目前只實測 SD 卡的
  CinemaDNG；SSD 錄影尚未驗證。
- **效能：** GCSV 計算正確，但尚未與錄影期間的 GYR 寫入交錯。任何最佳化都必須
  同時維持零掉樣與單一交易保證。

---

**Notes / 相關筆記:** `GYRO_IMU_GYROFLOW`,
`ONCAMERA_GCSV_AND_LENS_PROFILE`, `SD_WRITE_LATENCY_MEASURED`,
`RECORDING_GEOMETRY_AND_LENS_PROGRAM`
