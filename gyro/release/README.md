# fpGyroSup v1

[English](#english) | [繁體中文](#繁體中文)

### ⬇ [Download fpGyroSup-v1.zip](https://github.com/ijigen/fpSup/raw/main/gyro/release/fpGyroSup-v1.zip) · [下載](https://github.com/ijigen/fpSup/raw/main/gyro/release/fpGyroSup-v1.zip)

Unzip, copy everything inside to the root of an SD card, power the camera on.
解開後把裡面的東西整批複製到 SD 卡根目錄,相機開機即可。

Card in, camera on, shoot. Every clip leaves everything Gyroflow needs on the
card. **No computer is involved at any point** — the camera reads its own lens,
looks up its own sensor tables, and writes the files itself.

卡片插進去、開機、拍攝。每一段影片結束後,卡上就有 Gyroflow 需要的一切。
**全程不接電腦** —— 相機自己讀鏡頭、查自己的感光元件表、自己寫檔。

```
\GYRO\A001_017.GYR                 raw gyro log (kept for reference)
\CINEMA\A001_017\A001_017.gcsv     gyro + accelerometer, seven columns
\CINEMA\A001_017\A001_017.json     lens profile
```

SIGMA fp, firmware **Ver.5.02** only. RAM injection only — nothing is flashed,
and a power cycle restores the camera completely.

僅適用 SIGMA fp 韌體 **Ver.5.02**。只做 RAM 注入,不寫韌體,拔電池即完全復原。

---

## English

### Install

Copy the three files from `card/` to the root of a card, then **create an empty
`GYRO` folder next to them**. Without that folder the `.GYR` cannot be opened and
that take has no gyro data.

```
/AutoRun.txt
/VSHL.BIN
/PGEN.BIN
/GYRO/            <- must exist
```

Put the card in the camera and power on. A progress bar runs to `fpSup!`, about
18 seconds. Shoot as usual.

Building from source does all of this for you, including a byte-for-byte verify:

```
gyro/makecard.py release     what is in card/
gyro/makecard.py debug       the same, plus the USB shell for diagnosis
```

### What the camera does by itself

- **Lens profile.** Reads the L-mount lens name and focal length, looks up the
  firmware's own IMX410 timing and geometry tables, computes the rolling shutter
  and `focal_px`, and formats the JSON. Changing lenses is picked up
  automatically — verified live, LUMIX 40 mm to SIGMA 28 mm, `fx` 2157.103 to
  1509.972.
- **Rolling shutter from the mode that take actually used**, sampled at the first
  block write (766 ms), clear of the live-view modes at both ends of a recording.
  FHD 29.97 resolves to mode 106, 10.556 ms.
- **gcsv** with gyro at 2500 Hz and accelerometer at 100 Hz, byte-identical to the
  host decoder. Axes `(ax,ay,az) -> (ay,-ax,az)`, `ascale = 1/1024`,
  `orientation xyz`.

### Two builds, one source

| | release | debug |
|---|---|---|
| AutoRun commands | 157 | 221 |
| loader | 97 words, no task | 128 words, creates a task |
| USB shell | none | yes |
| boot | about 18 s | longer |

The only difference is one assembler flag. `templates/loader.S` carries an
`#ifdef NOTASK` that `build_autorun.py` sets whenever `--no-shell` is given, so
the logger and the pool code are identical in both — whatever passes on debug
holds on release.

The debug loader creates a task because that task goes on to *become* the USB
shell's worker. The release build has no worker, so its loader reads the file
straight from the gyro callback and returns. That saves 31 words of loader, which
is 31 `mem set` commands, about 1.9 s of boot. Calling the firmware's file API
from the callback is safe: it happens once at boot with nothing recording, and
the sample ring holds 240 ms.

### Where the boot time goes

```
power on -> 0%     6 s   the camera's own start-up, before AutoRun runs
101 mem set        6 s   about 60 ms each
 55 display        2 s   about 36 ms each
memmgr, 1 MiB      4 s
                  ────
                  18 s
```

Measured by A/B: the same card with only the progress bar thinned, or only the
loader's task removed, one boot each on a stopwatch. Display is not the
bottleneck — cutting 42 of those commands saved 1.5 s. The 1 MiB pool cannot
shrink; it is where the gcsv and profile builders run.

### Known issues

1. **Boot can fail after a soft power-off**, needing a battery pull. Not seen in
   recent builds, probably fixed by the logger's resume guard — but **not
   confirmed over enough power cycles**.
2. Occasionally a take produces no `.GYR` (seen on A001_044, 068, 069). Cause
   unknown.

If a take ever does freeze, `\CINEMA\<clip>\SPP_metadata.xmp` is **0 bytes** —
the camera creates it when recording starts and writes it at finalise. 298–299
bytes means that take was clean. It is the only evidence readable after the fact.

---

## 繁體中文

### 安裝

把 `card/` 裡的三個檔複製到卡片根目錄,然後**自己建立一個空的 `GYRO` 資料夾**。
沒有它,`.GYR` 開不起來,那一段就沒有陀螺資料。

```
/AutoRun.txt
/VSHL.BIN
/PGEN.BIN
/GYRO/            <- 必須存在
```

卡片放進相機開機,進度條跑到 `fpSup!`,約 18 秒。之後照常拍攝。

從原始碼建置會自動處理這一切,包含逐位元組驗證:

```
gyro/makecard.py release     card/ 裡就是這個
gyro/makecard.py debug       一樣的東西,另外加上可診斷的 USB shell
```

### 相機自己做的事

- **鏡頭 profile**:讀 L-mount 鏡頭的名稱與焦距、查韌體自己的 IMX410 時序與幾何
  表、算出捲簾時間與 `focal_px`、格式化成 JSON。換鏡頭自動跟上 —— 實機驗證過,
  LUMIX 40mm 換到 SIGMA 28mm,`fx` 從 2157.103 變成 1509.972。
- **捲簾時間取自那一段真正使用的模式**,在第一個區塊寫入時取樣(766 ms),避開
  錄影開始與結束兩端的即時取景模式。FHD 29.97 解析為 mode 106,10.556 ms。
- **gcsv** 含陀螺 2500 Hz 與水平儀 100 Hz,與主機解碼器逐位元組相同。軸向
  `(ax,ay,az) -> (ay,-ax,az)`,`ascale = 1/1024`,`orientation xyz`。

### 兩個版本,同一份原始碼

| | release | debug |
|---|---|---|
| AutoRun 指令 | 157 | 221 |
| loader | 97 字,不建任務 | 128 字,建任務 |
| USB shell | 無 | 有 |
| 開機 | 約 18 秒 | 較久 |

差別只有一個組譯器旗標。`templates/loader.S` 裡的 `#ifdef NOTASK`,由
`build_autorun.py` 在 `--no-shell` 時帶進去,所以兩版的 logger 與池程式碼完全相同
—— debug 上通過的,release 上也成立。

debug 版的 loader 要建任務,是因為那個任務讀完檔之後**要變成 USB shell 的 worker**。
release 版沒有 worker,loader 就直接在陀螺回呼裡把檔案讀完返回。這省下 31 個字的
loader,也就是 31 條 `mem set`、約 1.9 秒開機時間。在回呼裡呼叫韌體的檔案 API 是
安全的:只在開機時發生一次,當下沒有任何東西在錄影,而取樣環有 240 ms 餘裕。

### 開機時間花在哪裡

```
開機 → 0%         6 秒   相機自己開機,AutoRun 還沒開始跑
101 條 mem set    6 秒   每條約 60 ms
 55 條 display    2 秒   每條約 36 ms
memmgr 配 1 MiB   4 秒
                 ────
                 18 秒
```

用 A/B 量的:同一張卡只改進度條粗細、或只改 loader 建不建任務,各開機一次按碼表。
**顯示不是瓶頸** —— 砍掉 42 條只省 1.5 秒。那 1 MiB 的池不能縮,gcsv 與 profile
生成器就在裡面跑。

### 已知問題

1. **軟關機後下次開機可能失敗**,要拔電池冷開。近期版本沒再出現,推測是 logger 的
   復歸防護修掉的,**但沒有經過足夠次數的確認**。
2. 偶爾有一段不產生 `.GYR`(曾見於 A001_044、068、069),原因未查。

萬一某一段真的凍結,`\CINEMA\<clip>\SPP_metadata.xmp` 會是 **0 bytes** —— 相機在
錄影開始時建立它,收尾才寫。298–299 bytes 表示那一段是乾淨的。這是事後唯一能判讀
的證據。
