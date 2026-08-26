# gyro

Tools for [gyro sup](../projects/gyro-sup.md).

[gyro sup](../projects/gyro-sup.md) 的工具。

| file | what it is |
|---|---|
| `logger.S` | The logger. Hooks the gyro callback, fills one 16 KiB half while a background thread writes the other, and produces a `.GYR` per clip<br>logger 本體。掛在陀螺回呼上,一邊填 16 KiB 的半區、背景執行緒寫另一邊,每段影片產生一個 `.GYR` |
| `decode.py` | Checks a `.GYR` and converts it to Gyroflow GCSV<br>驗證 `.GYR` 並轉成 Gyroflow GCSV |
| `load.sh` | Swaps the logger in over USB, about a second, no reboot<br>透過 USB 換上 logger,約一秒,不用重開機 |
| `build_card.py` | Builds a card that boots the shell and the logger together<br>做一張開機就載入 shell 與 logger 的卡 |
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

## 實測

十五秒的一段:20 個區塊、36797 筆陀螺(2500 Hz)、737 筆加速計(50 Hz)、
CRC 全部相符、零掉批、零錯誤。停止路徑 14 ms。
