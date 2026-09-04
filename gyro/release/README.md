# fpGyroSup v1.4

[![Support fpSup on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/fpsup)
[![Join the fpSup Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/XeFK5zNZpT)

[English](#english) | [繁體中文](#繁體中文)

### ⬇ [Download fp-gyro-sup-v1.4.zip](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.4.zip) · [下載](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.4.zip)

Unzip it, copy the three files inside the folder to the root of an SD card, and
power the camera on.

解壓縮後，把資料夾裡的三個檔案複製到 SD 卡根目錄，再開啟相機。

SIGMA fp, firmware **Ver.5.02** only. This is RAM injection: nothing is flashed,
and removing the card files or pulling the battery restores the camera.

僅適用 SIGMA fp 韌體 **Ver.5.02**。這是 RAM 注入，不會刷寫韌體；移除卡上的
啟動檔或拔電池即可完全復原。

Previous releases: [v1.3](fp-gyro-sup-v1.3.zip) (the same stream, but the lens
profile carries no distortion), [v1.2](fp-gyro-sup-v1.2.zip) (portrait takes need
Gyroflow talked round by hand) and [v1.1](fp-gyro-sup-v1.1.zip) (GYR +
post-processing transaction; still the one to use for MOV).

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

### What changed in v1.4

- **The lens profile carries real distortion.** Until now `distortion_coeffs`
  was `[0, 0, 0, 0]`, which is not "no correction": Gyroflow's fisheye model
  reads all-zero as an *equidistant fisheye*, and a rectilinear 40 mm is 78 px
  away from that at the corner of the frame. The numbers now come off the lens.

  The camera already holds, for whatever is mounted, the coefficients it writes
  into a DNG's `WarpRectilinear` opcode — five focus support points of four
  values per colour plane. Interpolating them reproduces a real DNG's opcode to
  the eighth decimal, so nothing here is fitted to a picture, and nothing is
  read back out of the footage. The camera does the whole conversion itself.

- **The focal length is the measured one.** The mount reports the name on the
  barrel; the calibration data reports what the optics actually are. A SIGMA
  40 mm F1.4 Art says 40.0 and calibrates at 39.4, and that 1.5% is 1.5% of
  over-correction on every rotation. Focus breathing rides on it too — 1.2% on
  the LUMIX S 40/F2 between infinity and its near limit.

- **`fps`, `focal_length`, `crop_factor`, `global_shutter` and `asymmetrical`**
  are in the JSON now.

- **Boots in about ten seconds**, one more than v1.3. The progress bar is back
  to nine steps from five, and no longer blinks out halfway: the OSD runs three
  buffers, so a step sent twice leaves one of them holding the old frame.
  Zero-padding the percentage means each frame paints over the last completely
  and the wipes are gone, so three sends cost what two used to.

One profile per take, which is what the format allows: the distortion is read
at the focus the lens is at when the JSON is written, a few seconds in. A large
focus pull is not tracked — Gyroflow's lens profile has no way to express one.
Verified on two primes; a zoom held at one focal length should be fine, changing
focal length during a take is not. A lens the camera has no calibration data for
falls back to zeros, as before.

### What v1.3 changed, and still holds

- **Portrait takes work without being talked round.** See below.
- **Boots in about nine seconds**, from about eleven. The AutoRun is 113 commands
  instead of 160: the loader's second half now travels in `VSHL.BIN` and runs
  where it lands, firmware calls are one word instead of three, and the progress
  bar is sent twice rather than three times. Measured on the camera: 38 ms per
  command and 4.7 s of fixed cost, so the count is the whole story.

### What v1.2 changed, and still holds

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

### Portrait takes

Hold the camera upright and it just works. While a clip is being written the
camera stores its CinemaDNG frames without the rotation tag, so Gyroflow reads
a portrait take exactly as it reads a landscape one: load the sequence and both
sidecars, sync, stabilise, and turn the picture ninety degrees at the end of
the edit. Leave horizon lock off -- it would turn the picture itself, using the
gravity of a camera that was on its side. Photographs are untouched: they still
record their orientation and still rotate by themselves.

The tag has to go because of how Gyroflow reads a DNG sequence. It takes the
size from the frames, which are stored landscape, and then rotates the picture
by the tag, so the preview is portrait while the dimensions, the lens model and
the stabilisation maths stay landscape. Autosync then returns nonsense offsets
-- +2283 ms and +3997 ms measured on a take whose true offset is -260 ms -- and
no sidecar can reconcile the two, because the frame size comes from the image
files rather than from the `.gcsv` or the `.json`. Gyroflow tracks this as
issue #1117, one of a family of rotation bugs that also affect ordinary video
(#1115, plugins #38, ofx #48), all still open. Leaving the tag out sidesteps
all of it.

### Not covered by v1.3

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

### v1.4 更新

- **鏡頭 profile 有真正的畸變資料了。** 以前 `distortion_coeffs` 是 `[0, 0, 0, 0]`,
  那不是「不校正」—— Gyroflow 的 fisheye 模型把全零當成**等距魚眼**,而 40 mm 這種
  直線鏡頭在畫面角落跟等距魚眼差 78 像素。現在這組數字是從鏡頭來的。

  相機本來就握著它寫進 DNG `WarpRectilinear` 的那組係數:五個對焦支撐點,每點每個
  色平面四個值。把它內插出來,可以逐位重現真實 DNG 的數值到小數第八位 —— 所以這不是
  對著畫面擬合,也沒有回頭去讀素材。整個換算都在相機上完成。

- **焦距改用量測值。** 接環回報的是鏡身上印的名字,校正資料記的才是光學上的實際值。
  SIGMA 40mm F1.4 Art 回報 40.0、校正在 39.4,這 1.5% 就是每一次旋轉多補的 1.5%。
  對焦呼吸也在這條路上 —— LUMIX S 40/F2 從無限遠到近攝差 1.2%。

- **JSON 補上** `fps`、`focal_length`、`crop_factor`、`global_shutter`、`asymmetrical`。

- **開機約十秒**,比 v1.3 多一秒。進度條從五格回到九格,而且不會再中途消失:
  OSD 有三個緩衝區,一步只送兩次就會有一個緩衝區留著舊畫面。改成把百分比補零成
  三位數之後,每一格都能完全蓋掉上一格,清除命令就省下來了,送三次的成本等於以前送兩次。

一段影片只有一組 profile,這是格式本身的限制:畸變取的是寫 JSON 當下(開錄幾秒後)
的對焦距離。大幅度的拉焦不會被追蹤 —— Gyroflow 的鏡頭 profile 沒有辦法表達這件事。
已在兩顆定焦鏡上驗證;變焦鏡固定在一個焦段應該沒問題,拍攝中變焦則不行。
相機沒有校正資料的鏡頭,和以前一樣輸出全零。

### v1.3 帶來、現在仍然成立的

- **直拿片段不必再跟 Gyroflow 周旋**,見下方說明。
- **開機約九秒**(原約十一秒)。AutoRun 從 160 條命令降到 113 條:載入器的後半段
  改成隨 `VSHL.BIN` 走、就地執行,韌體呼叫從三個字變一個字,進度條送兩次而非三次。
  實測每條命令 38 ms、固定開銷 4.7 秒,所以命令數就是全部。

### v1.2 帶來、現在仍然成立的

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

把以下三個檔案當成同一組複製到 SD 卡根目錄。不要混用 v1、v1.1、v1.2、debug 版或先前測試版的檔案。

```text
/AutoRun.txt
/VSHL.BIN
/PGEN.BIN
```

開機後等進度顯示到 `fpSup!` 再開始錄影。不再需要 `GYRO/` 資料夾。

### 直拿的片段

直拿就直接可用。相機在寫入片段期間,讓 CinemaDNG 不帶旋轉標籤,所以 Gyroflow 讀直拿
片段就跟讀橫拿一樣:載入序列與兩個 sidecar、同步、穩定,最後在剪輯時把畫面轉九十度。
鎖定水平請保持關閉 —— 它會依重力自己轉畫面,而那是一台側躺的相機的重力。照片完全
不受影響,方向照常記錄、自動旋轉照常。

之所以要拿掉標籤,是因為 Gyroflow 讀 DNG 序列的方式:尺寸取自影像檔(儲存方向是橫的),
卻又照旋轉標籤把畫面轉成直的,於是預覽是直的、尺寸與鏡頭模型和穩定運算卻還是橫的。
自動同步因此給出離譜的偏移(實測 +2283 ms 與 +3997 ms,真值是 −260 ms),而且沒有任何
sidecar 救得了 —— 畫格尺寸的來源是影像檔,不是 `.gcsv` 或 `.json`。Gyroflow 把它記在
issue #1117,同族的旋轉問題也出現在一般影片上(#1115、plugins #38、ofx #48),全都還開著。
不寫那個標籤就完全繞開了。

### v1.3 未涵蓋

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
