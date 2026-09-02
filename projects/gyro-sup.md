# fpGyroSup

[English](#english) | [繁體中文](#繁體中文)

Gyro, six-axis logging and the Gyroflow workflow.
**Status: released — [fpGyroSup v1.2](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.2.zip)** · [release notes](../gyro/release/)

Gyro、六軸記錄與 Gyroflow 工作流。**狀態：已發布 —— [fpGyroSup v1.2 下載](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.2.zip)** · [說明](../gyro/release/)

---

## English

### Goal

Record six-axis data inside the camera and leave a Gyroflow-ready GCSV plus lens
profile beside every CinemaDNG take, with no computer conversion step and
nothing left to do after the take.

### Released path (v1.2)

```text
recording -> GCSV streamed during the take -> JSON written during the take -> stop
```

- The ICM20321 gyro is captured at 2500 Hz in the firmware's own callback and
  written to the GCSV as 1250 Hz two-tap averages; the MMA8452Q accelerometer is
  written at 50 Hz on its own rows.
- Samples go through two 32 KiB slots; a dedicated writer task formats each
  sealed slot and writes it in one 64 KiB call. Keeping a slot under one write is
  what removed the dropped samples: each write waits behind the video stream for
  the single SD lock.
- Every slot carries the dropped-sample count latched at seal time, so the
  formatter continues the exact 2500 Hz grid across slots and only re-anchors
  when a sample was really lost.
- The lens profile is built once the clip is established: frame size from the
  camera's live image-size setting plus the CinemaDNG border, lens name and
  focal length from the firmware's lens-info object, rolling shutter and frame
  rate from the IMX410 mode tables. No DNG read, no lens-bus access.
- Stop is just stop. There is no post-processing, no `MovieSaving` lock and no
  `.GYR`.

### Verified on hardware

SIGMA fp Ver.5.02, SD card, CinemaDNG 1920x1080 29.97p, LUMIX S 40/F2:

- 15.4-minute take: 27,706 DNG frames, 0 dropped samples, no timestamp gaps;
- cold boot, take started the moment the screen came up, two more takes 6 s
  apart: all three logged, all three JSONs written during the take;
- JSON byte-identical to the v1.1 converter's profile for the same lens and mode.

### Established technical facts

- Gyro callback: `0xC00D0794`; hardware ring: `*(0xC31E3FCC) + 0x60`,
  600 × 8-byte samples, or 240 ms.
- The firmware publishes `MovieRecording` to `0xC347DF38+0x157`, or to
  `0xC34765CC+0x3D` when the movie-engine selector `0xC347D1C0+0x14` reads
  `0x21` (`FUN_c0332480`). The logger mirrors that selection.
- Live movie image size: `FUN_c0206e98()+0x40` (`.h`, `.v`); the CinemaDNG frame
  is that plus 16 columns and 10 rows. `0xC3758B98` is only the USB shell's
  `setting readcam` mirror.
- Lens name and focal length: `FUN_c03341c8()` → `0xC3464980`, name at `+0x24`,
  focal length in tenths of a millimetre at `+0x68`.
- Orientation is `xyz`; gyro axes are stored with the camera's verified sign
  transform. GCSV accelerometer axes are mapped `(ax, ay, az) -> (ay, -ax, az)`.
- Native clip lifecycle (identity, volume, finalise) is observed in RAM by the
  pool code; the SD write lock is held by `SRecFile` (priority 6) and our writer
  runs at 28.

### Remaining scope

- **MOV:** no sidecars in v1.2 (no `\CINEMA\<clip>\` folder to stream into).
  v1.1 still writes a `.GYR` for MOV.
- **External SSD, UHD, zoom lenses:** untested.
- **Selector `0x21`:** the missed-take cause was found by observation and the
  fix mirrors the firmware, but the `0x21` state has not recurred since, so that
  path has not been exercised live.

---

## 繁體中文

### 目標

在相機內記錄六軸資料，讓每段 CinemaDNG 旁邊直接留下 Gyroflow 可用的 GCSV 與
鏡頭 profile，不需要電腦轉檔，停止錄影後也沒有任何事要等。

### 已發布流程（v1.2）

```text
錄影 -> GCSV 錄影中串流 -> JSON 錄影中寫入 -> 停止
```

- ICM20321 陀螺在韌體自己的 callback 內以 2500 Hz 取樣，以 1250 Hz 兩點平均寫進
  GCSV；MMA8452Q 加速度計以 50 Hz 獨立成列寫入。
- 取樣經過兩個 32 KiB 槽；獨立的 writer 任務把封緘的槽格式化後一次 64 KiB 寫出。
  把一個槽控制在一次寫入內就是掉樣消失的原因：每次寫入都要排在影像串流後面等
  唯一的 SD 鎖。
- 每個槽帶著封緘當下的掉樣計數，格式化時可以跨槽精確延續 2500 Hz 格線，只有真的
  掉樣才重新對齊。
- 片段一確立就產生鏡頭 profile：畫格尺寸取自相機即時的影像尺寸設定加 CinemaDNG
  邊界，鏡頭名稱與焦距取自韌體鏡頭資訊物件，捲簾與幀率取自 IMX410 模式表。不讀
  DNG，不碰鏡頭匯流排。
- 停止就是停止。沒有後處理、沒有 `MovieSaving` 鎖、沒有 `.GYR`。

### 實機驗證

SIGMA fp Ver.5.02、SD 卡、CinemaDNG 1920x1080 29.97p、LUMIX S 40/F2：

- 15.4 分鐘長錄：27,706 張 DNG，掉樣 0，時間戳無缺口；
- 冷開機、畫面一出來就錄，再隔 6 秒錄兩段：三段都有記錄，三份 JSON 都在錄影中
  寫入；
- JSON 與 v1.1 轉換器對同一顆鏡頭、同一模式的 profile 逐位元組相同。

### 已確立的技術資料

- 陀螺 callback：`0xC00D0794`；硬體 ring：`*(0xC31E3FCC) + 0x60`，600 × 8 bytes，
  也就是 240 ms。
- 韌體把 `MovieRecording` 寫到 `0xC347DF38+0x157`；當錄影引擎選擇器
  `0xC347D1C0+0x14` 為 `0x21` 時改寫到 `0xC34765CC+0x3D`（`FUN_c0332480`）。
  logger 照同一套選擇讀取。
- 即時錄影尺寸：`FUN_c0206e98()+0x40`（`.h`、`.v`）；CinemaDNG 畫格 = 設定值 +16
  欄 +10 列。`0xC3758B98` 只是 USB shell `setting readcam` 的鏡像。
- 鏡頭名稱與焦距：`FUN_c03341c8()` → `0xC3464980`，名稱在 `+0x24`，焦距（十分之一
  mm）在 `+0x68`。
- 方位為 `xyz`，陀螺軸使用實機驗證過的符號轉換；GCSV 加速度軸為
  `(ax, ay, az) -> (ay, -ax, az)`。
- 原生片段生命週期（身分、volume、收尾）由 pool 程式碼在 RAM 觀察；SD 寫入鎖由
  `SRecFile`（優先權 6）持有，我們的 writer 是 28。

### 後續範圍

- **MOV：** v1.2 沒有 sidecar（沒有可串流寫入的 `\CINEMA\<clip>\`）。v1.1 仍會替
  MOV 寫 `.GYR`。
- **外接 SSD、UHD、變焦鏡：** 尚未測試。
- **選擇器 `0x21`：** 整段沒錄到的原因是靠觀察找到、修法照韌體鏡像，但之後
  `0x21` 沒再出現，那條路徑還沒實機跑過。

---

**Notes / 相關筆記:** `GYRO_IMU_GYROFLOW`, `STREAM_DROP_INVESTIGATION`,
`ONCAMERA_GCSV_AND_LENS_PROFILE`, `SD_WRITE_LATENCY_MEASURED`,
`RECORDING_GEOMETRY_AND_LENS_PROGRAM`
