# gyro

Sources and tools for [fpGyroSup](../projects/gyro-sup.md). The shipping package
and bilingual installation notes are in [`release/`](release/).

[fpGyroSup](../projects/gyro-sup.md) 的原始碼與工具。正式包與雙語安裝說明位於
[`release/`](release/)。

> The generation before v1.12.0 kept the whole logger in the firmware RAM gap
> and is retired: see [`../history/gyro-logger-card/`](../history/gyro-logger-card/).
> Nothing here builds it any more.
>
> v1.12.0 以前那一代把整個記錄器放在韌體 RAM 的空隙裡,已經退役:見
> [`../history/gyro-logger-card/`](../history/gyro-logger-card/)。這裡不再建置它。

## Where the code runs / 程式碼在哪裡執行

`AutoRun.txt` is a loader spelled out in `mem set` commands; it reads
`fpSup.BIN` into the camera's DMA pool and branches to stage2, which places
every section and calls the payload's entry. The writer is fourteen kilobytes
of code **in the pool** — the firmware RAM gap holds only four eight-byte
veneers, and those are asked for at boot rather than named in a build.

`AutoRun.txt` 是用 `mem set` 拼出來的載入器;它把 `fpSup.BIN` 讀進相機的 DMA 池、
跳進 stage2,由它放置每個區段並呼叫 payload 的進入點。writer 是**池裡**的十四 KB
程式碼 —— 韌體 RAM 的空隙只放四個 8 bytes 的 veneer,而且是開機時跟配置器要的,
不是在 build 裡指定的。

| file | purpose |
|---|---|
| `gcsv_task.S` | the edition file: `writer_put`, `writer_openfile`, `writer_closefile` |
| `writer_core.inc.S` | everything both editions share: the task, the take, the shared block |
| `ring_task.inc.S` / `imu_stream.inc.S` | firmware addresses, the ring, the GFS7 header |
| `accel_hook.S` `rec_trigger.S` `mode_hook.S` | the three firmware hooks |
| `gyro_drain.S` `stream_space.S` | the drain and the block provider |
| `gcsv_rows.S` `gcsv_json.S` `gcsv_dist.S` | text, the Gyroflow lens profile, distortion |
| `gsup_launch.S` | the entry stage2 branches to |
| `build_base_card.py` | builds one edition's `AutoRun.txt` + `fpSup.BIN` |
| `release_card.py` | builds, checks the sections and writes the archive |
| `ring_task_deploy.py` / `imu_stream_deploy.py` | place and inspect over USB |
| `decode.py` | validates GYR and makes a host reference GCSV |

## Editions / 版本

`base` writes `\GYRO\A001_037.GYR` beside the clip: sixty-four bytes of header
and then interleaved gyro and accelerometer records, exactly as the producers
left them. `gcsv` writes the two files Gyroflow wants inside the clip's own
folder, while the take is being recorded — `A001_037.gcsv` and
`A001_037.json`. One source, one define.

## GYR v7 / GFS7

```text
0x00 "GFS7"      0x04 version     0x08 period_ps    0x0C gscale (float)
0x10 orientation 0x14 clip id (8) 0x1C volume
0x20 payload     0x24 dropped     0x28 sensor mode  0x2C exposure_us
0x30 width       0x34 height
```

Sixty-four bytes, then nothing but records. v5's GFS6 put a CRC and a count in
front of every block and kept gyro and accelerometer in separate regions; both
meant touching the payload. This one does not, so the bytes reach the card as
the producers wrote them.

## Build / 建置

```sh
gyro/build_base_card.py --edition gcsv --version dev --out /tmp/card   # a card
gyro/build_base_card.py --edition gcsv --debug ...                     # + USB shell
gyro/release_card.py gcsv v1.13                                        # an archive
```

Copy `AutoRun.txt` and `fpSup.BIN` to the root of the card the camera boots
from. Nothing else: no folder to make, no file to convert, no step after the
take.

Host validation and conversion:

```sh
gyro/decode.py A001_018.GYR
gyro/decode.py A001_018.GYR --gcsv A001_018.gcsv --accel
```

## Scope / 範圍

- CinemaDNG on SD and on the external SSD are both verified.
- MOV records GYR; MOV sidecars are not written.
- A forced power loss during a take leaves the files short; there is no
  next-boot repair.

- SD 與外接 SSD 的 CinemaDNG 都已驗證。
- MOV 會記錄 GYR,但不寫 MOV 的 sidecar。
- 錄影中強制斷電會讓檔案不完整,沒有下次開機自動修補。
