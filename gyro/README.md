# gyro

Tools for [gyro sup](../projects/gyro-sup.md).

[gyro sup](../projects/gyro-sup.md) 的工具。

| file | what it is |
|---|---|
| `logger.S` | The logger. Hooks the gyro callback, fills one 16 KiB half while a background thread writes the other, and produces a `.GYR` per clip<br>logger 本體。掛在陀螺回呼上,一邊填 16 KiB 的半區、背景執行緒寫另一邊,每段影片產生一個 `.GYR` |
| `decode.py` | Checks a `.GYR` and converts it to Gyroflow GCSV<br>驗證 `.GYR` 並轉成 Gyroflow GCSV |
| `load.sh` | Swaps the logger in over USB, about a second, no reboot<br>透過 USB 換上 logger,約一秒,不用重開機 |
| `build_card.py` | Builds a card that boots the shell and the logger together<br>做一張開機就載入 shell 與 logger 的卡 |
| `lens_profile.py` | Builds a Gyroflow lens profile; `--gyr` takes the sensor mode from the clip rather than guessing it, `--dist-table` the lens's own distortion<br>產生 Gyroflow 鏡頭 profile,`--gyr` 用 clip 記下的模式,`--dist-table` 用鏡頭自己的畸變資料 |
| `lens_dist.py` | Reads the lens's 17-point distortion table out of the camera<br>從相機讀出鏡頭的 17 點畸變表 |
| `imu_snapshot.S` | One call gathers accelerometer and gyro into a fixed result block<br>一次呼叫把加速計與陀螺收進固定結果區 |

## What a capture holds

Three layers, each describing itself, so the decoder needs to know nothing.

```
file header   64 B   GFS6, rate, camera/reel/clip, orientation, gscale,
                     sensor mode, exposure
block header  32 B   GFB6, sequence, first and last timestamp, sample count,
                     flags (bit 0 wrap, accel count above), payload, CRC-32
payload              gyro samples, then accel records
footer        32 B   GFE6, block count, samples dropped, error flags
```

`orientation` and `gscale` are in the file rather than in this document because
they are per camera. The block's magic, sequence and CRC are there for a
different reason: closing a file does not commit its directory entry, so a
capture can be on the card with no name, and those thirty-two bytes are what
makes it recoverable.

## The whole path

```
record            .GYR beside the clip, streamed as it goes
decode.py         -> Gyroflow GCSV
lens_profile.py   -> Gyroflow lens profile, mode taken from the .GYR
```

```
gyro/decode.py A001_018.GYR --gcsv A001_018.gcsv
gyro/lens_dist.py > dist.txt          # with the lens mounted
gyro/lens_profile.py --size 1936x1090 --fps 29.97 --focal-mm 40 \
    --gyr A001_018.GYR --dist-table dist.txt --lens "SIGMA 45mm F2.8 DG DN"
```

The distortion is the lens's own. The firmware carries only the interpolation
engine -- a 17-point radial map in Q15, piecewise linear, no polynomial -- and
the coefficients are downloaded from the lens at boot and interpolated for the
current focus distance and focal length. `lens_dist.py` reads what landed in RAM;
`lens_profile.py` fits Gyroflow's coefficients to it.

Two terms, not four. Four fit better inside the frame, 0.42 px rms against 0.74,
and then turn over 1.4 corner-radii out and go negative -- which is exactly where
stabilisation samples. The generator prints how far the fit stays monotonic and
says so when that is barely past the frame.

Nothing in either is measured by eye. The sample rate, orientation, scale factor
and sensor mode come out of the capture; the readout time, geometry and focal
length follow from the firmware's own IMX410 tables. The one number that cannot
come from a table is the lens focal length in mm, because it depends on the lens.

## Measured

A fifteen second take: 20 blocks, 36797 gyro samples at 2500 Hz, 737 accel
records at 50 Hz, every CRC recomputing, no drops, no errors. The stop path
takes 14 ms.

---

## 一次擷取包含什麼

三層,每層都自己描述自己,所以解碼器不需要知道任何事。

```
檔頭    64 B   GFS6、取樣率、機身/卷/片、orientation、gscale、感光元件模式、快門
區塊頭  32 B   GFB6、序號、起止時戳、樣本數、flags(bit0 繞回,高位加速計筆數)、
               payload 長度、CRC-32
payload        陀螺樣本,然後加速計記錄
檔尾    32 B   GFE6、區塊數、掉的樣本數、錯誤旗標
```

`orientation` 和 `gscale` 寫在檔案裡而不是寫在這份文件裡,因為**每台相機不同**。
區塊的魔數、序號、CRC 則是另一個理由:**關檔並不會把目錄項寫進卡**,所以一次擷取
可能人在卡上卻沒有名字 —— 那三十二個位元組就是它還能被救回來的原因。

## 完整流程

```
錄影              .GYR 與影片同時產生,邊錄邊寫
decode.py         → Gyroflow GCSV
lens_profile.py   → Gyroflow 鏡頭 profile,模式取自 .GYR
```

兩邊都沒有任何「目測」的數字。取樣率、orientation、比例因子、感光元件模式
來自擷取檔本身;讀出時間、幾何、焦距由韌體自己的 IMX410 表推出。
唯一不能從表裡來的是鏡頭焦距(mm),因為那取決於裝了什麼鏡頭。

## 實測

十五秒的一段:20 個區塊、36797 筆陀螺(2500 Hz)、737 筆加速計(50 Hz)、
CRC 全部相符、零掉批、零錯誤。停止路徑 14 ms。
