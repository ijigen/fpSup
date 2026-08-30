# gyro

Sources and tools for [fpGyroSup](../projects/gyro-sup.md). The shipping package
and bilingual installation notes are in [`release/`](release/).

[fpGyroSup](../projects/gyro-sup.md) 的原始碼與工具。正式包與雙語安裝說明位於
[`release/`](release/)。

| file | purpose |
|---|---|
| `logger.S` | 2500 Hz capture hook, bounded double buffer, GYR writer and single post-process handoff |
| `lifecycle.inc.S` | native CinemaDNG/MOV identity, volume and finalise-state adapter |
| `profilegen.S` | post-process scheduler, native `MovieSaving` ownership and JSON generator |
| `gcsvgen.S` | bounded-memory six-axis GCSV conversion |
| `decode.py` | validates GYR and makes a host reference GCSV |
| `build_card.py` | builds the AutoRun loader, logger and firmware-patch sections |
| `build_pgen.py` | builds the position-independent post-process pool image |
| `makecard.py` | builds, installs, verifies and ejects a release or debug card |

## Release lifecycle

```text
CinemaDNG native finalise
        -> GYR close
        -> acquire native MovieSaving
        -> GCSV
        -> JSON
        -> release MovieSaving
```

The GYR is streamed while recording; only bounded buffers are resident. GCSV is
read back and written in 16 KiB chunks with 5 ms cooperative yields, so neither
recording nor conversion requires RAM proportional to take length.

`MovieSaving` is the firmware field checked by the core recording manager and by
normal power-off. Keeping it owned through GCSV and JSON makes the three fpGyroSup
artifacts one transaction without a boot recovery or deferred rewrite path.

## GYR v5

```text
file header   64 B   GFS6, version, rate, clip id, volume, adapter, orientation,
                     scale, sensor mode, geometry and exposure
block header  32 B   GFB6, sequence, first/last timestamp, sample count, flags,
                     payload length and CRC-32
payload              gyro samples followed by accelerometer records
footer        32 B   GFE6, block count, dropped samples and error flags
```

The block framing lets the decoder reject truncation, discontinuity and
corruption explicitly. The footer makes logger loss and media errors visible.

## Build

With one writable SD card mounted:

```sh
gyro/makecard.py release
```

This builds the no-shell native lifecycle image, copies `AutoRun.txt`,
`VSHL.BIN` and `PGEN.BIN`, creates `GYRO/`, verifies every byte and ejects.
`gyro/makecard.py debug` adds the USB shell but uses the same logger and pool
source.

Host validation and conversion:

```sh
gyro/decode.py A001_018.GYR
gyro/decode.py A001_018.GYR --gcsv A001_018.gcsv --accel
```

## Release verification

The v1.1 no-shell image was rebuilt byte-for-byte from this source and tested on
a SIGMA fp running firmware 5.02. Two consecutive SD CinemaDNG takes produced
103,888 and 128,688 six-axis GCSV rows, zero dropped samples, zero logger errors,
valid JSON and data bodies identical to host conversion. Recording remained
locked until the prior JSON completed.

## Scope

- CinemaDNG on SD is verified.
- MOV records GYR but v1.1 does not yet create MOV sidecars.
- External SSD recording is not yet tested.
- Forced power loss during post-processing can leave a sidecar incomplete;
  v1.1 intentionally performs no next-boot repair.

---

## 中文摘要

錄影時 `.GYR` 以有限雙緩衝串流寫入；停止後依序完成 GYR 關檔、GCSV、JSON。
整段後處理期間接管韌體原生 `MovieSaving`，因此相機會鎖住下一段錄影，正常關機也
會等待。GCSV 每次只寫 16 KiB 並讓步 5 ms，錄影或轉換所需 RAM 都不會隨片長增加。

正式版可用以下指令建置、寫卡、逐位元組驗證並退出：

```sh
gyro/makecard.py release
```

v1.1 已在 SIGMA fp 韌體 5.02、SD 卡 CinemaDNG 上實測。MOV 目前只有 GYR，外接
SSD 尚未測試；強制斷電中斷的 sidecar 不會在下次開機自動補寫。
