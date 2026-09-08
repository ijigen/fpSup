# fpGyroSup v1.11a

[![Support fpSup on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/fpsup)
[![Join the fpSup Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/XeFK5zNZpT)

[English](#english) | [繁體中文](#繁體中文)

### ⬇ [Download fp-gyro-sup-v1.11a.zip](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.11a.zip) · [下載](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.11a.zip)

### Install

1. **Unzip the download.** Two files matter: `AutoRun.txt` and `VSHL.BIN`.
2. **Copy both to the root of the SD card** -- the top level, not inside a
   folder, and not mixed with files from any other build.
3. **Put the card in the camera and switch it on.** A progress bar appears on
   the screen; wait until it reads `fpSup-Gyro-v1.11a!` before recording.
4. **Shoot CinemaDNG.** Nothing else to press, and nothing to do afterwards.

Each take leaves both files Gyroflow wants inside the clip's own folder:

```text
\CINEMA\A001_013\A001_013.gcsv
\CINEMA\A001_013\A001_013.json
```

Load the frames and those two files into Gyroflow, then **run its
synchronisation** as usual. There is nothing to convert, but the offset still
has to be found: CinemaDNG carries no timecode, and the log starts about half a
second after the first frame -- measured between 470 and 570 ms, and different
on every take -- so it is not a number you can fill in once and reuse.

**To remove it:** delete `AutoRun.txt` and `VSHL.BIN` from the card. Nothing was
flashed -- this runs from RAM, so pulling the battery undoes it too.

SIGMA fp, firmware **Ver.5.02** only.

### 安裝

1. **解壓縮。** 需要的是兩個檔案：`AutoRun.txt` 和 `VSHL.BIN`。
2. **兩個都複製到 SD 卡根目錄** —— 最上層，不要放進資料夾，也不要跟其他版本的
   檔案混在一起。
3. **插卡、開機。** 畫面上會跑進度條，等到顯示 `fpSup-Gyro-v1.11a!` 再開始錄。
4. **開始錄 CinemaDNG。** 沒有別的按鈕要按，事後也不用做任何事。

每一趟錄影都會把 Gyroflow 要的兩個檔案留在片段自己的資料夾裡：

```text
\CINEMA\A001_013\A001_013.gcsv
\CINEMA\A001_013\A001_013.json
```

把影格序列和這兩個檔案丟進 Gyroflow，然後照常**跑一次同步**。不需要轉檔，但偏移量
還是得讓它自己找出來：CinemaDNG 不帶 timecode，而記錄檔的起點比第一幀晚大約半秒
（實測 470～570 ms，而且每一趟都不一樣），所以那不是一個填一次就能重複用的數字。

**要移除：** 把卡上的 `AutoRun.txt` 和 `VSHL.BIN` 刪掉。沒有刷寫任何韌體 —— 這是在
RAM 裡跑的，拔電池一樣復原。

僅適用 SIGMA fp 韌體 **Ver.5.02**。

Previous releases: [v1.10a](fp-gyro-sup-v1.10a.zip) (**do not use** -- see
below), [v1.4](fp-gyro-sup-v1.4.zip) (the same two sidecars, but the
log is decimated to 1250 Hz), [v1.3](fp-gyro-sup-v1.3.zip) (lens profile carries
no distortion), [v1.2](fp-gyro-sup-v1.2.zip) (portrait takes need Gyroflow talked
round by hand) and [v1.1](fp-gyro-sup-v1.1.zip) (GYR + post-processing; still the
only one that does anything for MOV).

### Two editions

|  | **fpGyroSup** v1.11a | **fpGyroSup Base** v1 |
|---|---|---|
| The camera writes | `.gcsv` and `.json`, during the take, inside the clip's folder | `.GYR`, one per take |
| Converting | nothing to do | [in a browser](https://ijigen.github.io/fpSup/gyro/web/), or `gyro/gyr7.py` |
| Gyro rate in the log | 2499.466 Hz, every sample | 2499.466 Hz, every sample |
| Accelerometer | 46 Hz, on the row of the sample it followed | 46 Hz, in the file; your choice in the log |
| Lens profile | the camera's own distortion data | you name the lens; distortion zero |
| Portrait takes | recorded landscape upright | the orientation is in the header, and yours to apply |
| USB SSD | untested | verified: log beside the clip on either disk |
| Download | [fp-gyro-sup-v1.11a.zip](fp-gyro-sup-v1.11a.zip) | [fp-gyro-sup-base-v1.zip](fp-gyro-sup-base-v1.zip) |

Neither writes anything for a MOV take. Use [v1.1](fp-gyro-sup-v1.1.zip) if you
need a log from MOV.

**Base** is the stream on its own: nothing is computed on the camera and nothing
is written but the samples, so the conversion happens where you can look at it.
The two editions are built from one core and differ in three functions -- the
capture underneath them is the same code, the same hooks and the same blocks.

---

## English

### What it does

Card in, camera on, shoot CinemaDNG. While the take is being recorded, the
camera writes both files Gyroflow needs into the clip's own folder:

```text
\CINEMA\A001_013\A001_013.gcsv     Gyroflow IMU log
\CINEMA\A001_013\A001_013.json     Gyroflow lens profile
```

Pressing stop ends the take and nothing else: no lock, no wait, no
post-processing, and no `.GYR` to convert.

### What changed in v1.11a

- **The second take after a warm restart works.** Switching the camera off at
  the power switch and on again does not clear its RAM, so v1.10a came back
  believing it still owned the eight buffers it had taken from the allocator
  the power-on before -- while the allocator, which *had* been reinitialised,
  considered every one of them free. The first take still worked; the second
  stopped by itself the moment it was started, with no message, and only a cold
  boot fixed it. Every power-on now asks for its own memory. **v1.10a should
  not be used.**

### What v1.10a brought, and still holds

- **Every sample.** v1.4 wrote the gyro as 1250 Hz two-tap averages; this writes
  the stream as it came off the sensor, 2499.466 Hz, nothing averaged and
  nothing thrown away. A 6.5-minute take is 993,242 rows and every record that
  went in is accounted for in what came out.

- **The accelerometer rides the gyro's row.** A reading is written into the row
  of the sample it followed, rather than on a row of its own with the gyro
  columns left empty. One row per sample, and nothing for Gyroflow to
  interpolate across.

- **Portrait takes are decided when the camera enters CINE**, not frame by
  frame. The camera works out a CinemaDNG frame's orientation from its attitude
  sensor, and in CINE that sensor is taken out of the answer, so every frame of
  every take is recorded landscape upright. Doing it at the mode change rather
  than at the take is what makes it work: at record start the answer has already
  been decided, and holding it down for the length of a take stopped recording
  by itself after about twenty seconds. Switch to photo and photographs record
  their orientation and rotate by themselves, exactly as before.

- **The sidecars go where the take does.** A CinemaDNG take is a folder of
  frames, so the log and the profile go inside it. No `GYRO/` folder to make,
  on any volume.

- **Two files on the card**, and the writer lives in the camera's DMA pool
  rather than the injection cave, which is what made room for the whole thing.

### Verified on hardware

SIGMA fp Ver.5.02, SD card. FHD and UHD CinemaDNG; LUMIX S 40/F2 and SIGMA
40mm F1.4 Art. The archive above is byte-identical to the card these were shot
on.

- Booted from the release card in CINE, without touching the STILL/CINE switch,
  and recorded a portrait take: every frame `Orientation 1`, both sidecars in
  `\CINEMA\A001_013\`, 28,089 rows, `dropped_blocks=000000`.
- A 6:37 take: 993,242 rows from 494 blocks in 494 card writes, nothing dropped.
  Records in equals rows plus readings, exactly, on every take.
- The `.json` matches what the host tool computes for the same lens and mode to
  the last printed digit, and the distortion curve is within 0.02 px of the
  camera's own `WarpRectilinear` opcode across the frame.

### Portrait takes

Hold the camera upright and it just works. Load the frames and the two sidecars,
sync, stabilise, and turn the picture ninety degrees at the end of the edit.
Leave horizon lock off -- it would turn the picture itself, using the gravity of
a camera that was on its side.

The rotation has to stay out of the frames because of how Gyroflow reads a DNG
sequence. It takes the size from the frames, which are stored landscape, and
then rotates the picture by the tag, so the preview is portrait while the
dimensions, the lens model and the stabilisation maths stay landscape. Autosync
then returns nonsense offsets -- +2283 ms and +3997 ms measured on a take whose
true offset is -260 ms -- and no sidecar can reconcile the two, because the
frame size comes from the image files rather than from the `.gcsv` or the
`.json`. Gyroflow tracks this as issue #1117, one of a family of rotation bugs
that also affect ordinary video (#1115, plugins #38, ofx #48), all still open.

### Not covered by v1.11a

- **MOV:** no sidecars. MOV records through a different path this build does not
  hook. Use [v1.1](fp-gyro-sup-v1.1.zip) if you need a log from MOV.
- **External SSD:** untested for this edition. Base is verified on both disks.
- **Zoom lenses:** untested. One held at a single focal length should be fine;
  changing focal length during a take is not -- the profile is read once, a few
  seconds in, and the format has no way to express a change.

### Build from source

```sh
gyro/release_card.py gcsv v1.11a
gyro/release_card.py base v1
```

The archive is the no-shell release. `gyro/build_base_card.py --edition gcsv`
builds the card without packaging it.

### Earlier releases in this line

#### What changed in v1.4

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

#### What v1.3 changed, and still holds

- **Portrait takes work without being talked round.** See below.
- **Boots in about nine seconds**, from about eleven. The AutoRun is 113 commands
  instead of 160: the loader's second half now travels in `VSHL.BIN` and runs
  where it lands, firmware calls are one word instead of three, and the progress
  bar is sent twice rather than three times. Measured on the camera: 38 ms per
  command and 4.7 s of fixed cost, so the count is the whole story.

#### What v1.2 changed, and still holds

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

#### Verified on hardware, v1.4

SIGMA fp Ver.5.02, SD card, CinemaDNG 1920x1080 29.97p, LUMIX S 40/F2:

- a 15.4-minute take: 27,706 DNG frames, 0 dropped samples, timestamps with no
  gaps;
- cold boot, a take started the moment the screen came up, then two more takes
  6 s apart: all three logged, all three JSON files written during the take;
- every JSON byte-identical to the profile the v1.1 converter produced for the
  same lens and mode.

---

## 繁體中文

### 功能

插卡、開機、錄 CinemaDNG。錄影進行中，相機就把 Gyroflow 需要的兩個檔案寫進片段
自己的資料夾裡：

```text
\CINEMA\A001_013\A001_013.gcsv     Gyroflow IMU 記錄
\CINEMA\A001_013\A001_013.json     Gyroflow 鏡頭 profile
```

按下停止只是結束錄影，沒有鎖、沒有等待、沒有後處理，也沒有 `.GYR` 要轉。

### v1.11a 更新

- **暖重開之後的第二段錄影正常了。** 用電源開關關機再開並不會清掉相機的 RAM，
  所以 v1.10a 開機後會以為自己還握著上一次跟配置器要來的八塊緩衝區 —— 而配置器
  **是**重新初始化過的，那幾塊在它眼裡早就是空的。第一段還錄得起來，第二段一按
  就停，畫面不給任何訊息，而且只有冷開機（拔電池）能恢復。現在每一次開機都會
  重新要自己的記憶體。**請不要再使用 v1.10a。**

### v1.10a 帶來、現在仍然成立的

- **一筆不漏。** v1.4 把陀螺以 1250 Hz 兩點平均寫出；這一版直接寫感測器產生的原始
  串流，2499.466 Hz，不平均、不丟棄。一段 6.5 分鐘的錄影是 993,242 列，進去的每
  一筆記錄都在出來的東西裡對得上。

- **水平儀併進陀螺那一列。** 一筆讀數會寫進它後面那個取樣所在的列，而不是自己
  獨占一列、把陀螺欄位留空。一個取樣一列，Gyroflow 不需要跨空列內插。

- **直拿片段在切到 CINE 時就決定好**，不是逐幀處理。相機是用姿態感測器算出
  CinemaDNG 的方向的，在 CINE 時把那個感測器排除掉，錄出來的每一幀就都是橫版正向。
  時機必須是切換模式而不是開始錄影：開錄時答案早就決定了，而且把它整段壓著會讓
  錄影在約二十秒後自己停下來。切回拍照，照片照常記錄方向、照常自動旋轉。

- **sidecar 跟著片段走。** CinemaDNG 一趟是一個資料夾，記錄檔和 profile 就放進去。
  任何磁碟都不必再建 `GYRO/` 資料夾。

- **卡上只要兩個檔案**，而且寫入器住在相機的 DMA pool 而不是注入區 —— 這就是塞得
  下整套東西的原因。

### 實機驗證

SIGMA fp Ver.5.02、SD 卡。FHD 與 UHD CinemaDNG；LUMIX S 40/F2 與 SIGMA 40mm
F1.4 Art。上面那個壓縮檔與拍出以下素材的那張卡逐位元組相同。

- 用發布版的卡在 CINE 下開機、全程沒碰 STILL/CINE 開關，直拿錄一段：每一幀都是
  `Orientation 1`，兩個 sidecar 都在 `\CINEMA\A001_013\`，28,089 列，
  `dropped_blocks=000000`。
- 一段 6:37 的錄影：494 個區塊、494 次寫卡、993,242 列，零掉樣。每一趟的帳都剛好
  平：進去的記錄數等於列數加讀數。
- `.json` 與主機工具對同一顆鏡頭、同一模式算出的結果逐位相同（到印出的最後一位），
  畸變曲線與相機自己的 `WarpRectilinear` 在整個畫面上差距在 0.02 像素以內。

### 直拿的片段

直拿就直接可用。載入序列與兩個 sidecar、同步、穩定，最後在剪輯時把畫面轉九十度。
鎖定水平請保持關閉 —— 它會依重力自己轉畫面，而那是一台側躺的相機的重力。

之所以不能讓旋轉留在畫格裡，是因為 Gyroflow 讀 DNG 序列的方式：尺寸取自影像檔
（儲存方向是橫的），卻又照旋轉標籤把畫面轉成直的，於是預覽是直的、尺寸與鏡頭模型
和穩定運算卻還是橫的。自動同步因此給出離譜的偏移（實測 +2283 ms 與 +3997 ms，真值
是 −260 ms），而且沒有任何 sidecar 救得了 —— 畫格尺寸的來源是影像檔，不是 `.gcsv`
或 `.json`。Gyroflow 把它記在 issue #1117，同族的旋轉問題也出現在一般影片上
（#1115、plugins #38、ofx #48），全都還開著。

### v1.11a 未涵蓋

- **MOV：** 沒有 sidecar。MOV 走的是這一版沒有掛鉤的另一條錄影路徑；需要 MOV 的
  記錄檔請用 [v1.1](fp-gyro-sup-v1.1.zip)。
- **外接 SSD：** 這一版尚未測試。Base 兩顆磁碟都驗過。
- **變焦鏡：** 尚未測試。固定在一個焦段應該沒問題，拍攝中變焦則不行 —— profile 是
  開錄幾秒後讀一次，格式本身也沒有辦法表達變化。

### 從原始碼建置

```sh
gyro/release_card.py gcsv v1.11a
gyro/release_card.py base v1
```

下載包是無 USB shell 的 release 版。只想建卡不想打包的話用
`gyro/build_base_card.py --edition gcsv`。

### 這條線的舊版本

#### v1.4 更新

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

#### v1.3 帶來、現在仍然成立的

- **直拿片段不必再跟 Gyroflow 周旋**,見下方說明。
- **開機約九秒**(原約十一秒)。AutoRun 從 160 條命令降到 113 條:載入器的後半段
  改成隨 `VSHL.BIN` 走、就地執行,韌體呼叫從三個字變一個字,進度條送兩次而非三次。
  實測每條命令 38 ms、固定開銷 4.7 秒,所以命令數就是全部。

#### v1.2 帶來、現在仍然成立的

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

#### 實機驗證（v1.4）

SIGMA fp Ver.5.02、SD 卡、CinemaDNG 1920x1080 29.97p、LUMIX S 40/F2：

- 15.4 分鐘的長錄：27,706 張 DNG，掉樣 0，時間戳無缺口；
- 冷開機、畫面一出來就錄一段，再隔 6 秒錄兩段：三段都有記錄，三份 JSON 都在
  錄影中寫入；
- 每份 JSON 都與 v1.1 轉換器對同一顆鏡頭、同一模式產出的 profile 逐位元組相同。
