# fpGyroSup

[English](#english) | [繁體中文](#繁體中文)

Gyro, six-axis logging and the Gyroflow workflow. **Status: released**, in two
editions · [release notes](../gyro/release/)

| | The camera writes | Converting |
|---|---|---|
| [**fpGyroSup v1.10a**](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.10a.zip) | `.gcsv` and `.json`, during the take, every sample | nothing to do |
| [**fpGyroSup Base v1**](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-base-v1.zip) | `.GYR`, one per take, every sample | [in a browser](https://ijigen.github.io/fpSup/gyro/web/) or `gyro/gyr7.py` |

Gyro、六軸記錄與 Gyroflow 工作流。**狀態：已發布**,有兩個版本 · [說明](../gyro/release/)

| | 相機寫出 | 轉檔 |
|---|---|---|
| [**fpGyroSup v1.10a**](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.10a.zip) | 錄影當下寫 `.gcsv` 與 `.json`,一筆不漏 | 不用做 |
| [**fpGyroSup Base v1**](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-base-v1.zip) | 每趟一個 `.GYR`,一筆不漏 | [瀏覽器](https://ijigen.github.io/fpSup/gyro/web/) 或 `gyro/gyr7.py` |

---

## English

### Goal

Record six-axis data inside the camera and leave a Gyroflow-ready GCSV plus lens
profile beside every CinemaDNG take, with no computer conversion step and
nothing left to do after the take.

### Released path (v1.10a)

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
- A portrait take's frames are stored without the EXIF Orientation tag, and only
  while a clip is being written, so Gyroflow reads them as it reads a landscape
  take while photographs keep the camera's own auto-rotation. Without that,
  Gyroflow takes the sequence's size from the frames but rotates the picture by
  the tag, and autosync returns nonsense offsets (gyroflow#1117, with siblings
  #1115 and plugins#38 on ordinary video, all open).
- The AutoRun is 113 commands and the camera reaches `fpSup!` in about nine
  seconds. Timed on the camera against the debug card: 38 ms per command and
  4.7 s of fixed cost, so the command count is the whole story.

### The Base path (v1)

```text
accelerometer hook -> gyro drain -> block full -> writer task -> card
```

The same sensors, nothing computed and nothing thrown away. The camera writes
one `.GYR` per take beside the clip, on whichever disk the take went to, and
the conversion happens on a computer where you can look at it.

- Every gyro sample at 2499.466 Hz, not a 1250 Hz average, and the
  accelerometer's 46 Hz interleaved in the order the two actually happened —
  an accelerometer reading sits beside the gyro samples of its own instant, so
  its position in the file is its time.
- Sixty-four bytes of header, then nothing but 8-byte records. The payload
  reaches the card exactly as the producers left it: no CRC to compute, no
  sorting into per-sensor regions, no copy.
- Eight 16 KiB buffers taken from the allocator at boot, 6.6 s of slack against
  a worst measured accelerometer interval of 35 ms and a 240 ms sensor ring.
- The card sets itself up: the loader places four kilobytes of writer in the
  camera's DMA pool by offset, and `gsup_boot` wires every pointer, takes the
  buffers and only then arms the three hooks. If the allocator refuses, nothing
  is armed and the camera is an ordinary camera.
- `tscale` in the log is the sample period itself and `t` counts samples, so
  nothing rounds and nothing drifts. The old integer 400 µs was 0.085 µs fast on
  every sample — 21 ms across a 97 s take, and growing.
- The volume needs a `GYRO` folder in its root. The camera will not make one:
  writing file-system metadata at record start froze it, and doing it at boot
  can only guess which disk the take will use.

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

- **MOV:** no sidecars in v1.10a (it records through a path this build does
  not hook).
  v1.1 still writes a `.GYR` for MOV.
- **External SSD, UHD, zoom lenses:** untested.
- **Horizon lock on a portrait take:** it turns the picture itself, from the
  gravity of a camera on its side, so it fights the rotation done in the edit.
  Leave it off.
- **Selector `0x21`:** the missed-take cause was found by observation and the
  fix mirrors the firmware, but the `0x21` state has not recurred since, so that
  path has not been exercised live.

---

## 繁體中文

### 目標

在相機內記錄六軸資料，讓每段 CinemaDNG 旁邊直接留下 Gyroflow 可用的 GCSV 與
鏡頭 profile，不需要電腦轉檔，停止錄影後也沒有任何事要等。

### 已發布流程（v1.10a）

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
- 直拿片段的畫格不寫入 EXIF 旋轉標籤,而且只在寫入片段期間如此,所以 Gyroflow 讀它就跟讀
  橫拿一樣,照片仍保留相機自己的自動旋轉。不這麼做的話,Gyroflow 會從影像檔取尺寸卻照標籤
  轉畫面,自動同步就給出離譜的偏移(gyroflow#1117,同族還有一般影片的 #1115 與 plugins#38,
  全都還開著)。
- AutoRun 共 113 條命令,相機約九秒到達 `fpSup!`。與 debug 卡對照實測:每條命令 38 ms、
  固定開銷 4.7 秒,所以命令數就是全部。

### Base 流程（v1）

```text
水平儀 hook -> 陀螺搬運 -> 區塊滿了 -> writer 執行緒 -> 卡片
```

同樣的感測器,但不算任何東西、也不丟棄任何東西。相機每趟在片段旁邊寫一個
`.GYR`,錄到哪顆磁碟就寫在哪顆,轉檔放到電腦上、你看得見的地方做。

- 每一筆陀螺資料都在,2499.466 Hz,不是 1250 Hz 的平均;水平儀的 46 Hz
  **按真實發生順序交錯**在其中 —— 一筆水平儀資料就坐在它那一刻的陀螺資料旁邊,
  所以它在檔案裡的位置就是它的時間。
- 64 位元組表頭,之後全是 8 位元組記錄。酬載原封不動落卡:不算 CRC、不分區、不複製。
- 開機時跟配置器拿 8 個 16 KiB 緩衝,6.6 秒餘裕;實測水平儀最壞間隔 35 ms,
  感測器 ring 撐 240 ms。
- 卡片自己佈署:載入器把四千位元組的 writer 以「偏移」放進相機的 DMA 池,
  `gsup_boot` 把所有指標填好、拿到緩衝,**最後才**裝三個 hook。配置器不給就一個都不裝,
  相機就是一台普通相機。
- 記錄檔的 `tscale` 就是取樣週期、`t` 是取樣序號,不捨入也不漂移。舊的整數 400 µs
  每筆快 0.085 µs —— 97 秒就差 21 ms,而且會一直長。
- 磁碟根目錄要有 `GYRO` 資料夾。相機不會幫你建:在錄影開始寫檔案系統中繼資料會凍結相機,
  改在開機做則只能猜你等下要錄到哪一顆。

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

- **MOV：** v1.10a 沒有 sidecar（MOV 走的是這一版沒有掛鉤的另一條錄影路徑）。v1.1 仍會替
  MOV 寫 `.GYR`。
- **外接 SSD、UHD、變焦鏡：** 尚未測試。
- **直拿時的鎖定水平：** 它會依重力自己轉畫面,而那是側躺相機的重力,會跟剪輯時的旋轉打架。
  請保持關閉。
- **選擇器 `0x21`：** 整段沒錄到的原因是靠觀察找到、修法照韌體鏡像，但之後
  `0x21` 沒再出現，那條路徑還沒實機跑過。

---

**Notes / 相關筆記:** `GYRO_IMU_GYROFLOW`, `STREAM_DROP_INVESTIGATION`,
`ONCAMERA_GCSV_AND_LENS_PROFILE`, `SD_WRITE_LATENCY_MEASURED`,
`RECORDING_GEOMETRY_AND_LENS_PROGRAM`
