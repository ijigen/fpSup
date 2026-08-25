# fp USB Shell v2

[English](#english) | [繁體中文](#繁體中文)

## English

A command channel to the SIGMA fp over USB, built on the camera's **own PTP gadget**.

The firmware builds the descriptors, creates and enables the endpoints, and
re-creates them after a record-mode reconfiguration. That last point is the whole
reason for the rewrite: v1 bolted on endpoints the firmware did not know about,
so recording tore the channel down. **Recording while connected now works** —
verified with the daemon attached and commands already exchanged, which is the
exact condition that broke v1.

Seven words of firmware are changed. Everything else is our code.

## What you get

```
EP 0x01 OUT  bulk 1024, burst 3    commands
EP 0x82 IN   bulk 1024, burst 3    replies
EP 0x83 IN   bulk 1024, burst 3    streaming, for a hook to arm directly
```

All three are firmware-owned. The third one is PTP's unused interrupt endpoint,
turned into a second bulk IN so a stream and the command channel do not block
each other.

One command: **`shl <line>`** runs `<line>` in the firmware's own shell and
returns what it printed. `mem set` and `mem save` come along for free, so the
worker needs no memory commands of its own.

## The patches

| address | from → to | why |
|---|---|---|
| `0xC0CF3740` | `03 06 01 01` → `03 ff ff ff` | interface class → vendor, so the host's PTP stack does not claim interface 0 first |
| `0xC0CF3780/84` | interrupt → bulk | PTP's unused EP 0x83 becomes a second bulk IN (SuperSpeed) |
| `0xC0CF3758/5C` | companion burst 0 → 3 | its SuperSpeed companion |
| `0xC0CF3798/9C` | interrupt → bulk | the same at full speed |

Every descriptor keeps its length, so the configuration totals still hold and
nothing else moves. Delete the lines and reboot to get stock PTP back.

The firmware normalises `wMaxPacketSize` per speed and type when it emits the
descriptor, so only the type has to be patched — the host receives 1024 even
though the staging array still reads 64.

## Two things that are easy to get wrong

**Do not touch an endpoint before the firmware configures it.** `DALEPENA`
(`0x2100C720`) is the controller's own record of which physical endpoints exist,
and it stays `0x003` — EP0 only — until the host completes SET_CONFIGURATION.
Issuing DEPCMDs before that competes with the driver while it is enumerating,
and enumeration is what loses: three boots in a row failed this way. `USB_STATE`
is no substitute; it reads 2 long before the endpoints exist. The worker gates on
`(DALEPENA & 0x24) == 0x24`.

**Judge from a clean boot.** Several wrong conclusions in this work came from
reading a state that earlier experiments had already disturbed.

## Layout

```
camera/worker.S      camera side, loaded at 0xC072E000
camera/oneshot.S     template for running a routine once, from the host
armasm.py            assembles ARM source and resolves its internal calls
build_autorun.py     assembles worker.S and emits the card script
inject.py            writes a one-shot routine, arms it, waits for it
host/fpshd.c         daemon, listens on /tmp/fpshd.sock
host/fpsh            client
host/lsdesc.c        prints the descriptor the host actually received
autorun/AutoRun.txt  what goes on the card
docs/                reverse-engineering notes (Traditional Chinese)
```

## Requirements

- A SIGMA fp (this is developed against Ver. 5.02) and an SD card
- macOS or Linux, and `libusb-1.0` — `brew install libusb`, or
  `apt install libusb-1.0-0-dev`
- `clang` targeting `armv7-none-eabi` to assemble the camera-side worker; any
  recent clang can do this, no cross toolchain needed
- Python 3 for the build script

Nothing is flashed. Everything the camera runs is written into RAM at boot by an
`AutoRun.txt` on the card, and is gone the moment you power off — including all
seven firmware patches.

## Use

```sh
make                                  # builds fpshd, lsdesc and the AutoRun
make LIBUSB=/path/to/libusb           # if libusb is somewhere unusual
make card CARD=/Volumes/<card name>
```

Then, in this order:

1. **Unplug USB** and power the camera on with the card in it
2. Watch the screen: a progress bar runs to `fpSup!`. **A bar that stops is a
   load that stopped there** — the position tells you which block failed
3. Attach the USB cable

```sh
./fpshd &
./host/fpsh ping                          # OK pong seq=1
./host/fpsh mem get 0xC072F000,,0x34      # worker state
./lsdesc                                  # what the host enumerated
./host/fpsh display colorbar 1 0          # any of the 77 firmware shell commands
```

The boot order matters: the USB gadget is built when the cable is attached, so
the patches have to land first, and the patched words sit in code that has not
run yet, so no stale instruction-cache line can shadow them.

## If something does not work

| symptom | what it means |
|---|---|
| The progress bar stops partway | The load stopped there. Read which block it was from `build_autorun.py`'s output |
| The screen never shows anything | AutoRun did not run. Check the file is `\AutoRun.txt` at the card root, and that the card is not write-protected |
| No device appears on the host | The gadget did not enumerate. Boot with USB unplugged and attach afterwards; if it still fails, remove the seven `mem set 0xC0CF37xx` lines and confirm stock PTP comes back |
| `fpsh ping` times out | Check `./lsdesc` first. If the interface is there, read the worker state — `served` should climb and `faults` counts idle timeouts, not errors |
| The channel worked and then stopped | Unplug and replug USB. **A cold boot is not needed** — the firmware rebuilds the gadget on attach and the worker keeps running through it, so the round and command counters carry straight on. Verified after wedging the endpoint with several daemons competing for the interface |
| The camera is unresponsive | Pull the battery. Nothing here is persistent, so the next boot is clean |

## Reverting

Delete the AutoRun from the card, or delete just the `mem set 0xC0CF37xx` lines
to keep the shell out of the way and get stock PTP back. Either way a power cycle
restores the camera completely — nothing is written to non-volatile storage.

## Running code on the camera

The shell can write memory but nothing can call it, so there is no `call`
command and no need for one. To run something, point an address the firmware
already calls at your routine, let it fire once, and put the original word back.
`camera/oneshot.S` is that plumbing with a payload slot; `inject.py` writes it,
arms the call site and waits for it to report back. Neither the AutoRun nor the
daemon is involved.

```sh
./inject.py camera/oneshot.S
./host/fpsh mem get 0xC072F500,,0x20
```

The borrowed site is the gyro callback at `0xC00D0794` (50-90 Hz), so the payload
runs in that callback's context: do not block and do not take a mutex.

## Protocol

FPSH v1, 64-byte frames, little-endian.

```
+00 magic "FPSH"   +04 version   +05 command   +06 flags
+08 sequence       +0C payload_length          +0E status
+10 crc32 (whole frame with this field zeroed)
+14 payload, 44 bytes
```

A reply may span several frames — **flags bit 0 means another frame follows** —
and a command may be longer than 44 bytes, because the camera reads the payload
as a NUL-terminated string and the OUT TRB is 1 KiB. The CRC still covers only
the first 64 bytes.

## Not done yet

* EP 0x83 has not moved a byte yet. It is enabled and correctly described, but
  nothing has armed it — the first hook that needs it will be the test.
* v1's hook-push sources still target the old endpoint (`0xC31E3274`,
  `StartTransfer(9)`); on this gadget those become `0xC31E3270` and
  `StartTransfer(7)`.


---

## 繁體中文

透過 USB 對 SIGMA fp 下指令的通道,建立在相機**自己的 PTP gadget** 上。

描述元由韌體建立、端點由韌體建立與啟用,而且**錄影模式重設之後由韌體重建** ——
最後這點就是重寫的全部理由:v1 加的是韌體不認得的端點,所以錄影會把通道扯掉。
**現在連著線錄影可以正常運作**,而且是在 daemon 已連線、指令已往返過的條件下驗證的,
那正是 v1 必壞的情境。

只改韌體七個字,其餘都是我們的程式。

### 得到什麼

```
EP 0x01 OUT  bulk 1024, burst 3    指令
EP 0x82 IN   bulk 1024, burst 3    回覆
EP 0x83 IN   bulk 1024, burst 3    串流,給 hook 直接武裝
```

三條都由韌體擁有。第三條原本是 PTP 沒人用的 interrupt 端點,改成第二條 bulk IN,
讓串流和指令通道不互相擋。

指令只有一個:**`shl <line>`** 把整行丟給韌體自己的 shell 並回傳輸出。
`mem set` 和 `mem save` 因此免費取得,worker 不需要自己實作記憶體指令。

### 那七個字

| 位址 | 改法 | 理由 |
|---|---|---|
| `0xC0CF3740` | `03 06 01 01` → `03 ff ff ff` | 介面 class 改成 vendor,主機的 PTP stack 才不會先 claim interface 0 |
| `0xC0CF3780/84` | interrupt → bulk | PTP 沒人用的 EP 0x83 變成第二條 bulk IN(SuperSpeed) |
| `0xC0CF3758/5C` | companion burst 0 → 3 | 對應的 SuperSpeed companion |
| `0xC0CF3798/9C` | interrupt → bulk | 同上(full speed) |

所有描述元長度都不變,所以 config 的總長仍然成立,其他東西一個都不用動。
刪掉那幾行重開機就回到原廠 PTP。

韌體在送出描述元時會依速度與型別正規化 `wMaxPacketSize`,所以**只要改型別就夠** ——
暫存區裡仍讀到 64,主機收到的卻是 1024。

### 兩個很容易重蹈的錯誤

**端點還沒被韌體配置好之前,不要碰控制器。** `DALEPENA`(`0x2100C720`)是控制器
自己的紀錄,在主機完成 SET_CONFIGURATION 之前一直是 `0x003`(只有 EP0)。
在那之前發 DEPCMD 會跟正在列舉的驅動搶,而輸的是列舉 —— 連續三次開機都栽在這裡。
`USB_STATE` 不能拿來代替,它在端點存在很久之前就已經是 2。
worker 的閘門是 `(DALEPENA & 0x24) == 0x24`。

**判斷要以乾淨開機為準。** 這項工作中好幾個錯誤結論,都來自讀一個已經被先前實驗
擾動過的狀態。

### 目錄

```
camera/worker.S      相機端,載入到 0xC072E000
camera/oneshot.S     讓一段常式在相機上跑一次的範本
armasm.py            ARM 組譯並解析內部呼叫
build_autorun.py     組譯 worker.S 並產生卡片腳本
inject.py            寫入一次性常式、武裝、等它回報
host/fpshd.c         daemon,監聽 /tmp/fpshd.sock
host/fpsh            客戶端
host/lsdesc.c        印出主機實際列舉到的描述元
autorun/AutoRun.txt  放進卡片的東西
docs/                逆向筆記(繁體中文)
```

### 需求

- 一台 SIGMA fp(針對 Ver. 5.02 開發)與一張 SD 卡
- macOS 或 Linux,以及 `libusb-1.0` —— `brew install libusb`,
  或 `apt install libusb-1.0-0-dev`
- 能以 `armv7-none-eabi` 為目標的 `clang`,用來組譯相機端的 worker;
  近期的 clang 都可以,不需要另外裝交叉工具鏈
- Python 3(建置腳本用)

**不需要重刷韌體。** 相機執行的一切都是開機時由卡上的 `AutoRun.txt` 寫進 RAM 的,
一關機就消失 —— 包括那七個韌體 patch。

### 使用

```sh
make                                  # 建置 fpshd、lsdesc 與 AutoRun
make LIBUSB=/path/to/libusb           # libusb 在特殊位置時
make card CARD=/Volumes/<卡片名稱>
```

然後照這個順序:

1. **拔掉 USB**,插卡開機
2. 看螢幕:進度條會跑到 `fpSup!`。**進度條停在哪,就是載入停在哪** ——
   位置直接告訴你是哪一段失敗
3. 插上 USB 線

```sh
./fpshd &
./host/fpsh ping                          # OK pong seq=1
./host/fpsh mem get 0xC072F000,,0x34      # worker 狀態
./lsdesc                                  # 主機列舉到什麼
./host/fpsh display colorbar 1 0          # 韌體 77 條 shell 指令的任何一條
```

開機順序有意義:USB gadget 是插線時才建立的,所以 patch 必須先落地;
而被 patch 的那些字所在的程式碼此時還沒被執行過,不會有殘留的 I-cache 行蓋掉修改。

### 出問題的時候

| 症狀 | 意思 |
|---|---|
| 進度條停在中間 | 載入停在那裡。對照 `build_autorun.py` 的輸出就知道是哪一段 |
| 螢幕完全沒反應 | AutoRun 根本沒執行。確認檔案是卡片根目錄的 `\AutoRun.txt`,以及卡片沒有防寫 |
| 主機看不到裝置 | gadget 沒列舉。先確認是「拔線開機、開完再插」;若仍失敗,把七行 `mem set 0xC0CF37xx` 刪掉,確認原廠 PTP 會回來 |
| `fpsh ping` 逾時 | 先跑 `./lsdesc`。介面在的話就讀 worker 狀態 —— `served` 應該會增加,而 `faults` 算的是閒置逾時不是錯誤 |
| 通道本來好好的突然不通 | 拔插一次 USB。**不需要冷啟動** —— 韌體會在插線時重建 gadget,而 worker 全程沒死,計數器會直接接著跑。實測過:先用多個互搶介面的 daemon 把端點弄僵,拔插一次就恢復 |
| 相機沒反應 | 拔電池。這裡沒有任何東西是持久的,下次開機就是乾淨的 |

### 還原

把 AutoRun 從卡片刪掉,或只刪那七行 `mem set 0xC0CF37xx` 讓 shell 讓開、換回原廠 PTP。
不論哪種,重開電源就完全復原 —— **沒有任何東西寫進非揮發儲存**。

### 在相機上執行程式碼

shell 能寫記憶體但不能呼叫,所以**沒有 `call` 指令,也不需要**。做法是把韌體本來就會
呼叫的位址指向我們的常式,讓它跑一次,再自己把原值寫回去。`camera/oneshot.S` 就是
那套外框加一個 payload 空位;`inject.py` 負責寫入、武裝、等它回報。
AutoRun 和 daemon 都不用動。

```sh
./inject.py camera/oneshot.S
./host/fpsh mem get 0xC072F500,,0x20
```

借用的呼叫點是陀螺回呼 `0xC00D0794`(50–90 Hz),所以 payload 是在那個回呼的脈絡執行:
**不能阻塞,也不能拿 mutex**。

### 協定

FPSH v1,64 byte 幀,little-endian。

```
+00 magic "FPSH"   +04 version   +05 command   +06 flags
+08 sequence       +0C payload_length          +0E status
+10 crc32(整幀,此欄位歸零後計算)
+14 payload,44 bytes
```

回覆可以跨多幀 —— **`flags` bit 0 表示還有下一幀** —— 指令也可以超過 44 bytes,
因為相機把 payload 當 NUL 結尾字串讀,而 OUT 的 TRB 有 1 KiB。CRC 仍只涵蓋前 64 bytes。

### 還沒做的

* EP 0x83 還沒實際搬過一個 byte。它已經啟用、描述元也正確,但還沒有東西去武裝它 ——
  第一個需要它的 hook 就是測試。
* v1 的 hook-push 程式碼仍指向舊端點(`0xC31E3274`、`StartTransfer(9)`);
  在這個 gadget 上要改成 `0xC31E3270` 與 `StartTransfer(7)`。
