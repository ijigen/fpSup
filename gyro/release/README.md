# fpGyroSup v1.2

[![Support fpSup on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/fpsup)
[![Join the fpSup Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/XeFK5zNZpT)

[English](#english) | [繁體中文](#繁體中文)

### ⬇ [Download fp-gyro-sup-v1.2.zip](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.2.zip) · [下載](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.2.zip)

Unzip it, copy the three files inside the folder to the root of an SD card, and
power the camera on.

解壓縮後，把資料夾裡的三個檔案複製到 SD 卡根目錄，再開啟相機。

SIGMA fp, firmware **Ver.5.02** only. This is RAM injection: nothing is flashed,
and removing the card files or pulling the battery restores the camera.

僅適用 SIGMA fp 韌體 **Ver.5.02**。這是 RAM 注入，不會刷寫韌體；移除卡上的
啟動檔或拔電池即可完全復原。

Previous release: [fpGyroSup v1.1](fp-gyro-sup-v1.1.zip) (GYR + post-processing
transaction; still the one to use for MOV).

---

## English

### What it does

Card in, camera on, shoot CinemaDNG. While the take is being recorded, the
camera writes both files Gyroflow needs next to it:

```text
\CINEMA\A001_017\A001_017.gcsv     Gyroflow IMU log
\CINEMA\A001_017\A001_017.json     Gyroflow lens profile
```

There is no `.GYR` any more. The GCSV streams to the card during the take and
the JSON is written a few seconds after the take starts. Pressing stop ends the
take and nothing else: no lock, no wait, no post-processing.

### What changed in v1.2

```text
recording -> GCSV streamed during the take -> JSON written during the take -> stop
```

- **GCSV-only stream.** The gyro is captured at 2500 Hz and written as 1250 Hz
  two-tap averages, the accelerometer at 50 Hz on its own rows. Every block goes
  to the card within seconds of being filled; a one-hour take does not have to
  fit in RAM and a flat battery loses at most the last block.
- **Zero dropped samples under heavy motion.** v1.1's converter and the first
  stream builds lost samples when a block needed several SD writes behind the
  video stream. The stream now keeps every block under one write.
- **Seamless timestamps.** Block boundaries carry the sample count recorded at
  seal time, so the 2500 Hz grid continues across blocks exactly; a real gap is
  still reported as a gap.
- **JSON during the take.** Frame size comes from the camera's live image-size
  setting, the lens name and focal length from the firmware's own lens-info
  object, so the profile needs no DNG read and no lens-bus access and is written
  a few seconds into the take. Stop, power off or start the next take at will.
- **Attach fixed.** The firmware publishes its recording flag to one of two
  objects depending on an internal selector; v1.1 read only one of them and
  could miss whole takes. v1.2 reads the same one the firmware wrote.

### Verified on hardware

SIGMA fp Ver.5.02, SD card, CinemaDNG 1920x1080 29.97p, LUMIX S 40/F2:

- a 15.4-minute take: 27,706 DNG frames, 0 dropped samples, timestamps with no
  gaps;
- cold boot, a take started the moment the screen came up, then two more takes
  6 s apart: all three logged, all three JSON files written during the take;
- every JSON byte-identical to the profile the v1.1 converter produced for the
  same lens and mode.

### Install

Copy these as one matching set to the root of the card. Do not mix files from
v1, v1.1, a debug build, or an earlier test build.

```text
/AutoRun.txt
/VSHL.BIN
/PGEN.BIN
```

Power the camera on and wait until the progress display reaches `fpSup!` before
recording. A `GYRO/` folder is no longer needed.

### Not covered by v1.2

- **MOV:** no sidecars. MOV has no `\CINEMA\<clip>\` folder for the stream to
  write into. Use v1.1 if you need a `.GYR` from MOV.
- **External SSD, UHD, zoom lenses:** untested. UHD frame size follows the same
  rule as FHD (setting + CinemaDNG border) but has not been recorded; the focal
  length is read from the firmware's lens object and has only been checked
  against a prime lens.

### Build from source

```sh
gyro/makecard.py release --gcsv-stream
```

`gyro/makecard.py debug --gcsv-stream` builds the same logger and pool code with
the USB shell included. The downloadable package is the no-shell release.

---

## 繁體中文

### 功能

插卡、開機、錄 CinemaDNG。錄影進行中，相機就把 Gyroflow 需要的兩個檔案寫在片段
旁邊：

```text
\CINEMA\A001_017\A001_017.gcsv     Gyroflow IMU 記錄
\CINEMA\A001_017\A001_017.json     Gyroflow 鏡頭 profile
```

沒有 `.GYR` 了。GCSV 在錄影期間持續串流寫卡，JSON 在開錄幾秒後就寫好。按下停止
只是結束錄影，沒有鎖、沒有等待、沒有後處理。

### v1.2 更新

```text
錄影 -> GCSV 錄影中串流 -> JSON 錄影中寫入 -> 停止
```

- **只有 GCSV 串流。** 陀螺以 2500 Hz 取樣、以 1250 Hz 兩點平均寫出，加速度計
  50 Hz 獨立成列。每個區塊填滿後幾秒內就落到卡上；錄一小時不需要塞進 RAM，
  斷電最多只丟最後一塊。
- **劇烈晃動也零掉樣。** v1.1 的轉換器和最初幾版串流，在一個區塊需要好幾次 SD
  寫入、又排在影像串流後面時會掉樣。現在每個區塊都控制在一次寫入內。
- **時間戳無縫。** 區塊邊界帶著封緘當下的取樣計數，2500 Hz 的格線可以跨區塊精確
  延續；真正的缺口仍然照實記錄。
- **JSON 在錄影中產生。** 畫格尺寸取自相機即時的影像尺寸設定，鏡頭名稱與焦距取自
  韌體自己的鏡頭資訊物件，不讀 DNG、不碰鏡頭匯流排，開錄幾秒後就寫好。要停、要
  關機、要接著錄都可以。
- **修正掛載問題。** 韌體的錄影旗標會依內部選擇器寫到兩個物件之一；v1.1 只讀其中
  一個，可能整段沒錄到。v1.2 讀韌體實際寫入的那一個。

### 實機驗證

SIGMA fp Ver.5.02、SD 卡、CinemaDNG 1920x1080 29.97p、LUMIX S 40/F2：

- 15.4 分鐘的長錄：27,706 張 DNG，掉樣 0，時間戳無缺口；
- 冷開機、畫面一出來就錄一段，再隔 6 秒錄兩段：三段都有記錄，三份 JSON 都在
  錄影中寫入；
- 每份 JSON 都與 v1.1 轉換器對同一顆鏡頭、同一模式產出的 profile 逐位元組相同。

### 安裝

把以下三個檔案當成同一組複製到 SD 卡根目錄。不要混用 v1、v1.1、debug 版或先前
測試版的檔案。

```text
/AutoRun.txt
/VSHL.BIN
/PGEN.BIN
```

開機後等進度顯示到 `fpSup!` 再開始錄影。不再需要 `GYRO/` 資料夾。

### v1.2 未涵蓋

- **MOV：** 沒有 sidecar。MOV 沒有可供串流寫入的 `\CINEMA\<clip>\` 資料夾；需要
  MOV 的 `.GYR` 請用 v1.1。
- **外接 SSD、UHD、變焦鏡：** 尚未測試。UHD 的畫格尺寸沿用 FHD 的規則（設定值加
  CinemaDNG 邊界）但沒有實錄過；焦距讀自韌體鏡頭物件，只用定焦鏡核對過。

### 從原始碼建置

```sh
gyro/makecard.py release --gcsv-stream
```

`gyro/makecard.py debug --gcsv-stream` 使用同一份 logger 與 pool 程式碼，但會包含
USB shell。下載包是無 USB shell 的 release 版。
