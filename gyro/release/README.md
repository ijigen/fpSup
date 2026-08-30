# fpGyroSup v1.1

[![Support fpSup on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/fpsup)
[![Join the fpSup Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/XeFK5zNZpT)

[English](#english) | [繁體中文](#繁體中文)

### ⬇ [Download fp-gyro-sup-v1.1.zip](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.1.zip) · [下載](https://github.com/ijigen/fpSup/raw/main/gyro/release/fp-gyro-sup-v1.1.zip)

Unzip it, copy everything inside the folder to the root of an SD card, and
power the camera on.

解壓縮後，把資料夾裡的東西整批複製到 SD 卡根目錄，再開啟相機。

SIGMA fp, firmware **Ver.5.02** only. This is RAM injection: nothing is flashed,
and removing the card files or pulling the battery restores the camera.

僅適用 SIGMA fp 韌體 **Ver.5.02**。這是 RAM 注入，不會刷寫韌體；移除卡上的
啟動檔或拔電池即可完全復原。

---

## English

### What it does

Card in, camera on, shoot CinemaDNG. Every completed take leaves everything
Gyroflow needs on the card without a computer:

```text
\GYRO\A001_017.GYR                 raw six-axis capture
\CINEMA\A001_017\A001_017.gcsv     Gyroflow IMU log
\CINEMA\A001_017\A001_017.json     Gyroflow lens profile
```

The `.GYR` is streamed throughout the recording, not accumulated for the whole
take in RAM. The camera converts it to GCSV in 16 KiB chunks after recording and
then writes the JSON profile.

### What changed in v1.1

v1.1 makes recording finalisation one native transaction:

```text
CinemaDNG finalise -> GYR close -> GCSV -> JSON -> unlock
```

- The GYR closes only after the camera's native recording finaliser completes.
  This removes the intermittent record-stop freeze caused by overlapping media
  operations.
- The same writer task continues directly from GYR close into GCSV and JSON;
  there is no unprotected idle gap between the three files.
- fpGyroSup extends the firmware's own `MovieSaving` state through that work.
  The native recording manager refuses a new take, and normal power-off waits,
  until both sidecars are complete.
- GCSV remains bounded-memory streaming: 16 KiB writes with 5 ms cooperative
  yields. Long recordings do not have to fit in RAM.
- There is no boot-time recovery scan or automatic rewrite of old clips.

Hardware verification on the release image covered two consecutive CinemaDNG
takes of 41.56 s and 51.48 s: 232,576 six-axis rows in total, zero dropped
samples, zero logger errors, both GCSV files byte-identical to host conversion,
and both JSON files valid. The second take was not admitted until the first
take's JSON had completed.

### Install

Copy these as one matching set to the root of the card. Do not mix files from
v1, a debug build, or an earlier test build.

```text
/AutoRun.txt
/VSHL.BIN
/PGEN.BIN
/GYRO/            required before the first recording
```

Power the camera on and wait until the progress display reaches `fpSup!` before
recording.

### Expected behaviour after stop

GCSV conversion is intentionally incremental. In the release validation, a
42-second take took about 9 seconds to finish both sidecars and a 51-second take
took about 11 seconds. During this period:

- starting another recording is locked;
- normal power-off waits for completion;
- forced power loss can still leave the current GCSV or JSON incomplete.

Wait for the camera to finish or use normal power-off. v1.1 deliberately does
not repair an interrupted sidecar on the next boot.

### CinemaDNG and MOV

CinemaDNG gets `.GYR`, `.gcsv`, and `.json`.

MOV still gets a `.GYR`, so its sensor data is captured, but v1.1 does not make
MOV sidecars because MOV has no `\CINEMA\<clip>\` folder for their current path.
Convert the MOV take on a computer with:

```sh
gyro/decode.py A001_017.GYR --gcsv A001_017.gcsv --accel
```

The release has been verified with CinemaDNG on SD. External SSD recording has
not yet been tested.

### Build from source

The release command builds the native lifecycle image, copies it to a mounted
card, verifies every byte, creates `GYRO/`, and ejects the card:

```sh
gyro/makecard.py release
```

For development, `gyro/makecard.py debug` builds the same logger and pool code
with the USB shell included. The downloadable package is the no-shell release.

---

## 繁體中文

### 功能

插卡、開機、錄 CinemaDNG。每段完成後，卡上會直接留下 Gyroflow 所需的三個檔，
全程不需要電腦：

```text
\GYRO\A001_017.GYR                 原始六軸資料
\CINEMA\A001_017\A001_017.gcsv     Gyroflow IMU 記錄
\CINEMA\A001_017\A001_017.json     Gyroflow 鏡頭 profile
```

`.GYR` 在錄影期間持續串流寫卡，不會把整段資料全部囤在記憶體。停止錄影後，相機以
16 KiB 為單位轉成 GCSV，最後寫入 JSON。

### v1.1 更新

v1.1 把錄影收尾變成一個原生交易：

```text
CinemaDNG 收尾 -> GYR 關檔 -> GCSV -> JSON -> 解鎖
```

- 等相機原生錄影收尾完成後才關閉 GYR，解決媒體操作重疊造成的偶發停止錄影凍結。
- 同一個 writer 從 GYR 關檔直接繼續 GCSV 與 JSON，中間沒有失去保護的閒置空窗。
- 整段工作期間延長韌體原生的 `MovieSaving` 狀態。相機自己的錄影管理器會拒絕下一段
  錄影，正常關機也會等待，直到兩個 sidecar 完成。
- GCSV 維持有限記憶體的串流處理：每次寫 16 KiB、協作讓步 5 ms。長時間錄影不需要
  全部塞進 RAM。
- 不做開機掃描，也不在下次開機自動補寫舊片段。

正式 release image 已用兩段連續 CinemaDNG 實機驗證：41.56 秒與 51.48 秒，合計
232,576 列六軸資料，掉樣 0、logger 錯誤 0；兩份 GCSV 與主機轉檔逐位元相同，兩份
JSON 都完整有效，而且第一段 JSON 完成前，相機沒有接受第二段錄影。

### 安裝

把以下內容當成同一組複製到 SD 卡根目錄。不要混用 v1、debug 版或先前測試版的檔案。

```text
/AutoRun.txt
/VSHL.BIN
/PGEN.BIN
/GYRO/            第一段錄影前必須存在
```

開機後等進度顯示到 `fpSup!` 再開始錄影。

### 停止錄影後的正常現象

GCSV 轉換刻意採漸進式處理。正式版驗證時，42 秒素材約 9 秒完成兩個 sidecar，
51 秒素材約 11 秒完成。這段期間：

- 下一段錄影會被鎖住；
- 正常關機會等待完成；
- 強制斷電仍可能留下不完整的 GCSV 或 JSON。

請讓相機完成，或使用正常關機。v1.1 刻意不在下次開機修復被中斷的 sidecar。

### CinemaDNG 與 MOV

CinemaDNG 會得到 `.GYR`、`.gcsv`、`.json`。

MOV 仍會得到 `.GYR`，六軸資料不會遺失；但 v1.1 尚未替 MOV 產生 sidecar，因為
MOV 沒有目前路徑所需的 `\CINEMA\<clip>\` 資料夾。可在電腦上使用：

```sh
gyro/decode.py A001_017.GYR --gcsv A001_017.gcsv --accel
```

正式版已驗證 SD 卡的 CinemaDNG；外接 SSD 錄影尚未測試。

### 從原始碼建置

正式版指令會建立 native lifecycle image、寫入已掛載的卡、逐位元組驗證、建立
`GYRO/`，最後退出卡片：

```sh
gyro/makecard.py release
```

開發用的 `gyro/makecard.py debug` 使用同一份 logger 與 pool 程式碼，但會包含 USB
shell。下載包是無 USB shell 的 release 版。
