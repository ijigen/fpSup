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

## Use

```sh
make                                  # builds fpshd, lsdesc and the AutoRun
make card CARD=/Volumes/<card name>

# Boot the camera with USB UNPLUGGED. The screen shows a progress bar and ends
# at fpSup! — a bar that stops is a load that stopped there. Then attach USB.
./fpshd &
./host/fpsh ping
./host/fpsh mem get 0xC072F000,,0x34    # worker state
./lsdesc                                # what the host enumerated
```

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

### 使用

```sh
make                                  # 建置 fpshd、lsdesc 與 AutoRun
make card CARD=/Volumes/<卡片名稱>

# 相機**拔掉 USB** 開機。畫面會顯示進度條,最後停在 fpSup! ——
# 進度條停在哪,就是載入停在哪。然後才插上 USB。
./fpshd &
./host/fpsh ping
./host/fpsh mem get 0xC072F000,,0x34    # worker 狀態
./lsdesc                                # 主機列舉到什麼
```

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
