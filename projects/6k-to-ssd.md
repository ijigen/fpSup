# 6K to SSD

[English](#english) | [繁體中文](#繁體中文)

One pipeline: **6K sensor readout → 8-bit companded → hardware lossless on a
fraction of the frames → SSD *and* SD card in parallel**, at 29.97.

一條管線:**6K 讀出 → 8bit companding → 一部分幀走硬體無損 → 同時寫 SSD 與 SD 卡**,
29.97。

> **Revised 2026-09-13** after the first real storage measurements. Three things
> in the previous version of this document were wrong: the link ceiling (625
> MB/s — it ignored 8b/10b), the claim that the SSD had untested headroom, and
> the claim that the fp's DNGs cannot carry a companding curve. All three are
> corrected below and the design changed as a result: **the output is 8-bit
> now, not 12-bit.**

---

## English

### The storage measurements

Taken with the firmware's own benchmark, `sdcard test3 <slot> <bytes> <loops>`
(`FUN_c0408A20`), which times one write with the 1 MHz counter `FUN_c002b940`
and prints `MB/sec` as bytes per microsecond — decimal MB, the same unit as
everything else here. `[M]` = measured, twice, on 2026-09-13.

```
                        write        read
SSD 2 TB, enclosure A    390         400      [M]
SSD 2 TB, enclosure B    363         370      [M]   same drive
SD 128 GB UHS-II          94         218      [M]   reproduced within 1%
```

**The SSD is bus-limited, not drive-limited.** Write and read land within 3% of
each other, and swapping the enclosure moved it 7%. USB 3.0 Gen1 is 5 Gbps with
8b/10b encoding = **500 MB/s of payload**, and practical bulk mass-storage sits
at 400–450. We are already there. A faster drive will not help.

**Block size matters, and it is not a small effect:**

```
             10 MB      50 MB     100 MB
SSD           328        390        393     flat from 50 MB
SD             66         94          ?     +48%, no plateau yet
```

One 6K 8-bit frame is 24.5 MB. Writing one file per frame — which is what
CinemaDNG is — puts the SD card at the slow end of that curve. A writer that
accumulates and writes 100–200 MB blocks may get more out of the same card for
free. **The SD card above 50 MB has not been measured.** `[?]`

### The link budget

```
SSD   390   measured, enclosure A
SD    160   assumed -- a good V90 card; the one measured does 94
-----------
      550   the planning figure
```

Only the second line is an assumption, and it is one that can be settled by
buying a card. `tools/storage-benchmark/` is the card that settles it.

**The two paths are structurally independent** and can be expected to add: the
SD card goes through `XC_MediaDriverSdcard` with its lock at `0xC351EE18`, the
SSD through USB host mass storage (`MscHost`). Different drivers, different
locks, different controllers, no shared write queue. `[C]`

> **Assumption, not verified:** that they actually add. They were measured
> separately. Concurrent writes share DRAM bandwidth and CPU.

### Why 8-bit, and why that is not a compromise

**The camera already ships 8-bit CinemaDNG with a proper companding curve.**
A UHD 8-bit clip off the card (`3856×2170`, `BitsPerSample=8`,
`Compression=1`) carries **59** tags where the 12-bit clips carry 58. The extra
one is `LinearizationTable` (50712), 256 SHORT entries, monotonic 0 → 4095,
`WhiteLevel` still 4095:

```
code   0- 32    8.5 levels per code
code  32- 64    4.0                  <- shadows fine
code  64-128    5.75
code 128-192   16.0
code 192-255   36.6                  <- highlights coarse
```

That is a piecewise-linear log curve, carried by the DNG standard's own
mechanism. Every DNG reader handles it. `[M]`

The previous version of this document listed "8-bit needs a companding curve and
the fp's DNGs do not carry one" as an open problem. It was wrong: that is true
of the 12-bit files and false of the 8-bit ones. **The obstacle does not exist.**

### The design at L = 550

`f` is the fraction of frames sent through the compressor. `f` trades the two
bottlenecks against each other: raising it moves bytes off the link and work
onto the engine.

```
engine allows   px <= E / (f x fps)
link allows     px <= L / (k x fps x (1 - f + f/C))      k = bytes/pixel
and f settles at  f  =  Ek / (L + Ek(1 - 1/C))    -- see below, it is not chosen
```

With C = 2.3, and both constraints binding at once — which is where the greedy
scheduler of the next section lands on its own:

| | E = 300 `[I]` | E = 240 | E = 169.7 `[M]` |
|---|---|---|---|
| 12-bit | 17.89 Mpix `5181×3453` | 16.76 `5014×3342` | 15.43 `4812×3208` |
| 10-bit | 20.34 `5524×3682` | 19.21 `5368×3578` | 17.88 `5179×3452` |
| **8-bit** | **24.01 `6002×4000`** | **22.88 `5859×3905`** | **21.55 `5686×3790`** |

### The point of the table: 8-bit is insensitive to the one number nobody has measured

The engine's sustained rate is still unmeasured and the estimates span 77%
(169.7 to 300 Mpix/s). In 8-bit that moves the output by **5% of linear
dimension** — 5686×3790 to 6002×4000, i.e. 94% to 99% of native 6K.

It is insensitive to the compression ratio too. `C = 2.3` was measured on
**12-bit** Bayer; using it for 8-bit is an assumption, so here is the whole
range (8-bit, L = 550, E = 300):

```
C = 1.5    5704x3802        C = 2.3    6002x4000
C = 2.0    5920x3946        C = 3.0    6064x4042  (native)
```

**Both of the design's unmeasured inputs move the answer between 94% and 100% of
native 6K.** That is why 8-bit is the path: not because it is cheaper, but
because it is the only variant whose answer is already known.

### Native 6064×4042 does not fit in 550, and at the measured engine rate it cannot

```
6K 8-bit uncompressed = 734.6 MB/s
to reach 550          = must remove 25.1%
removable             = f x (1 - 1/C),  and f is capped by the engine
```

| E | f cap | most removable | needs C |
|---|---|---|---|
| 169.7 `[M]` | 0.231 | 23.1% | **impossible** |
| 240 | 0.327 | 32.7% | 4.33 |
| 300 `[I]` | 0.408 | 40.8% | 2.60 |

The first row is not "the compression is not good enough". At `f = 0.231` the
most that can be removed is 23.1% **even if the compressed frames were zero
bytes**, and 25.1% is needed. There are not enough compressible frames.

To get spec-native 6064×4042 the link has to reach **565 MB/s** (at E = 300) or
**639** (at E = 169.7) — SD at 175 or 249 MB/s. The first is possible with a
good card; the second is not.

For practical purposes 6002×4000 and 6064×4042 differ by 1% of linear dimension.

### There is no `f` to choose — the scheduler finds it

`f` is a way of *describing* the result, not a knob to set. The compressor takes
the next frame the moment it is free; a frame that arrives while it is busy goes
out uncompressed. Nothing schedules, nothing decides a duty cycle.

```
frame arrives -> engine idle?  yes -> compress it, write Compression=7
                               no  -> write it as-is, Compression=1
```

That is work-conserving, and it lands exactly on the arithmetic optimum above.
For any given frame size a higher `f` always means fewer bytes, so the best `f`
is the highest the engine can sustain — which is what a greedy scheduler
produces by definition:

```
f  =  E / (px x fps)      automatically, as an outcome
```

Substituting that back gives `px <= (L + Ek(1 - 1/C)) / (k x fps)`, which is the
same bound the "optimum f" formula produces. **The greedy scheduler is optimal
and needs no knowledge of `E`.**

**This removes the margin problem entirely.** The previous version of this
document worried that at the optimum the engine runs at 100% with no timing
margin, and recommended backing off to `f = 1/2` to buy slack. That worry was an
artefact of treating `f` as fixed: with a fixed duty cycle, "compress this frame"
is a *deadline*, and missing it is a failure. With a greedy scheduler there is no
deadline — the engine being busy is not an error, it is just a frame that goes
out uncompressed. **100% engine utilisation is the normal operating point, not a
danger.**

It also absorbs variation nothing else can:

- compression time varies with frame content; a fixed `f` must assume the worst
- the engine may throttle, or share the bus on some frames
- `E` is unmeasured, and the scheduler does not care

The cost is that the output size varies frame to frame and which frames are
compressed is not known in advance. For a flat stream with an index that is
nothing; for CinemaDNG each file declares its own `Compression` anyway.

### Why alternate frames, and what relaxes if the output need not be legal DNG

**TIFF's `Compression` tag is per IFD**, so one file cannot hold a compressed
half and an uncompressed half. Alternate *frames* is free of that: CinemaDNG is
a sequence of independent files and each declares its own `Compression`, so
frame 1 can be 7 and frame 2 can be 1 with both valid.

> **Assumption, not verified:** that readers tolerate a mixed sequence. Testable
> on the host with no camera — build one and open it in Resolve.

If the on-card format does not have to be legal DNG — a flat stream converted on
the host — then three things change, and **none of them is bandwidth**:

1. **Large sequential writes become possible.** Worth more than the other two:
   see the block-size numbers above. The SD card at 10 MB blocks is 30% slower
   than at 50 MB, and one frame is 24.5 MB.
2. **The per-frame DNG header goes away** — measured at 79,240 B (open gate)
   and 79,960 B (UHD 8-bit) per frame, about 0.9%, or 2.4 MB/s. Small, free.
3. **The mixed-sequence assumption above stops mattering**, because the host
   converter produces whatever the reader wants.

The cost is a host-side converter, which the mixed-sequence risk may require
anyway.

### What the camera records today, measured off the card

Useful as calibration for anything above. Taken from the DNG headers of real
takes, `bytes/frame x 29.97`:

```
FHD  1936x1090  12-bit    3,244,544 B     97.2 MB/s
UHD  3856x2170   8-bit    8,447,488 B    253.2 MB/s
UHD  3856x2170  12-bit   12,630,528 B    378.5 MB/s
open gate 3032x2012 12b   9,229,824 B    276.6 MB/s
```

Two things fall out of this:

- **FHD 12-bit needs 97.2 MB/s and the measured card does 94.** It records only
  because the RAM buffer covers a 3% shortfall. That is the real explanation for
  the 692 ms worst-case write latency during recording, for the writer at
  priority 28 losing the card lock, and for dropped gyro samples: during an FHD
  take this card is saturated.
- **Every open-gate take on the card stops at 3–4 s.** 276.6 MB/s against a
  94 MB/s card drains a buffer at 182 MB/s; the lengths imply 600–750 MB of
  buffer. Not a bug — the card.

### The engine's API, from the stills path

The stills path already compresses a 6064×4042 Bayer frame to a lossless DNG.
It is the reference implementation; the HAL is `src/hal/RawCD/src/XC_HalLjpeg.cpp`:

```
FUN_c05a6890(params9)  -> FUN_c062f5a8    start the encode
FUN_c05a6920(params5)  -> FUN_c062f6f8    wait for completion
FUN_c05a6990(x, 1)     -> FUN_c062fa48    collect the result
FUN_c03d9668(addr)                        virtual -> bus address translation
```

The nine words the encode takes, read off the caller in `blk_c03.c` around
`0xC037E7AC`:

```
[0] width        [1] height       [2] source buffer (translated)
[3] 0x100        [4] 0x100        [5] destination buffer
[6] from FUN_c0398b00()           [7] *(obj+0x0C)
[8] mode byte, low bits cleared
```

The wait call takes five: `{w, h, buf, 0x100, 0x100}`. `FUN_c062f6f8` is where
`timeout = pixels / 32000` lives — a watchdog, **not** a throughput figure.
`+0xF8` is the produced-byte count; `+0x3FC` is busy/clear.

### What is established

- **SSD ~390 MB/s write, bus-limited.** Two enclosures, 363 and 390; read
  matches write. `[M]`
- **SD 94 MB/s write, 218 read.** Reproduced across two boots within 1%. `[M]`
- **Write block size matters** — SD +48% from 10 to 50 MB, not yet flat. `[M]`
- **8-bit CinemaDNG carries `LinearizationTable`**, 256 entries, piecewise log.
  Companding is a solved problem, in shipping firmware. `[M]`
- **The two media are independent** — separate drivers, separate locks. `[C]`
- **The engine is idle during video.** Recording uses the DSP at `0x301B` and
  the RFC readout at `0x300C`. No contention to design around. `[C]`
- **Compression ~2.3:1** on this sensor's 12-bit Bayer. `[C]`
- **One engine, no parallelism**, clock cannot be raised. `[C]`
- **Mode 3 is a stock 6064×4042 1×1 @29.97 readout.** `[C]`
- **The link is Gen1.** BOS says SUPERSPEED_USB, `wSpeedsSupported = 0x000E`,
  no SUPERSPEED_PLUS anywhere. `[C]`

### What is not

Ranked by how much each changes the design. **The engine is no longer first** —
choosing 8-bit demoted it.

1. **Whether the SD card can reach 160 MB/s.** The whole link budget rests on
   it. Settled by buying a card and running `tools/storage-benchmark/`.
2. **Whether large blocks help the SD card.** Unmeasured above 50 MB, and the
   curve was still rising. Free to find out, same card.
3. **Whether the two media add.** Measured separately; concurrent writes share
   DRAM and CPU.
4. **The engine's sustained rate.** Still one cold call, 6064×4042 in 144,431 µs
   = 169.7 Mpix/s, with the power/clock/IRQ bring-up *inside* encode. Probe
   exists and has never been run: `raw/ljtime_deploy.py`, hooks `0xC037E7AC`.
   In 8-bit this only moves the output 94% → 99%.
5. **The compression ratio on 8-bit companded data.** 2.3:1 is a 12-bit figure.
   Range tested above; also only worth 5%.
6. **Whether RWZM's output can feed the engine.** Only matters if the output is
   reduced below sensor size, which at 8-bit it no longer needs to be.
7. **Whether readers tolerate a mixed-`Compression` sequence.** Host-side test,
   no camera.

### Do not

- **Do not cold-call the engine. Hook it.** A dozen cold calls broke stills
  compression until a reboot — card file sizes went 26–28 MB (compressed) to
  51 MB (uncompressed), back to 36 MB after a power cycle.
- **Do not buy a faster SSD.** The bus is the limit. Buy a better *enclosure*
  if anything, and a better *SD card* first.
- **Do not plan around 12-bit.** At L = 550 it yields `5181×3453` at best —
  worse than 8-bit at `6002×4000`, and it is the variant whose answer depends
  on the unmeasured engine rate.

### Related

- `projects/open-gate.md` — the 6K source and the canvas work
- `projects/raw-sup.md` — the engine, its measurement and the roadmap
- `tools/storage-benchmark/` — the card that settles items 1 and 2 above
- `notes/research/imaging-hw/RAW_COMPRESSION_RESEARCH.md` — separating overhead from rate

---

## 繁體中文

### 儲存實測

用韌體自己的跑分 `sdcard test3 <slot> <bytes> <loops>`(`FUN_c0408A20`)量的。
它用 1 MHz 計數器 `FUN_c002b940` 夾住單次寫入,印出的 `MB/sec` 是 bytes/µs ——
十進位 MB,跟這份文件其他數字同一把尺。`[M]` = 2026-09-13 實測,跑了兩次。

```
                          寫         讀
SSD 2 TB,外接盒 A        390        400      [M]
SSD 2 TB,外接盒 B        363        370      [M]  同一顆硬碟
SD 128 GB UHS-II           94        218      [M]  兩次誤差 <1%
```

**SSD 卡在匯流排,不是硬碟。** 讀寫落差 3% 以內,換個外接盒差 7%。
USB 3.0 Gen1 是 5 Gbps **8b/10b 編碼 = 500 MB/s 載荷**,bulk 大量儲存實務值
400~450。我們已經貼著了。**換更快的硬碟沒有用。**

**寫入區塊大小有影響,而且不小:**

```
              10 MB      50 MB     100 MB
SSD            328        390        393     50 MB 起就平
SD              66         94          ?     +48%,還沒看到平台
```

一格 6K 8bit 是 24.5 MB。「一格一個檔」—— CinemaDNG 就是這樣 —— 讓 SD 卡永遠
在這條曲線的慢端運作。一個會攢成 100~200 MB 再寫的 writer,可能從同一張卡上
白撿一截。**SD 卡 50 MB 以上沒量過。** `[?]`

### 鏈路預算

```
SSD   390   實測,外接盒 A
SD    160   假設 —— 好一點的 V90;實測那張只有 94
-----------
      550   規劃值
```

只有第二行是假設,而且是**可以用買的解決**的假設。
`tools/storage-benchmark/` 就是拿來收掉它的卡。

**兩條路結構上獨立,可以預期相加**:SD 走 `XC_MediaDriverSdcard`,鎖在
`0xC351EE18`;SSD 走 USB host 大量儲存(`MscHost`)。不同驅動、不同鎖、
不同控制器,沒有共用寫入隊列。`[C]`

> **假設,未驗證:**它們真的會相加。兩者是**分開量**的。同時寫要共用 DRAM
> 頻寬與 CPU。

### 為什麼是 8bit,以及為什麼那不是妥協

**相機本來就出 8bit CinemaDNG,而且帶了正規的 companding 曲線。**
卡上一段 UHD 8bit(`3856×2170`、`BitsPerSample=8`、`Compression=1`)有
**59** 個 tag,12bit 的只有 58。多的那個就是 `LinearizationTable`(50712),
256 筆 SHORT,單調 0 → 4095,`WhiteLevel` 仍是 4095:

```
code   0- 32   每個 code  8.5 階
code  32- 64             4.0        <- 暗部細
code  64-128             5.75
code 128-192            16.0
code 192-255            36.6        <- 亮部粗
```

這就是一條分段線性的 log 曲線,走 DNG 標準自己的機制。任何讀 DNG 的軟體都吃
得下。`[M]`

這份文件的上一版把「8bit 需要 companding 曲線,而 fp 的 DNG 帶不了」列為未解
問題。**那是錯的**:12bit 的檔案沒有,8bit 的有。**這個障礙不存在。**

### L = 550 的設計

`f` 是送進壓縮器的幀的比例。它把兩個瓶頸互相對換:調高 f,位元組從鏈路移走、
工作移到引擎身上。

```
引擎允許   px <= E / (f × fps)
鏈路允許   px <= L / (k × fps × (1 - f + f/C))      k = 每畫素位元組
而 f 會停在  f  =  Ek / (L + Ek(1 - 1/C))    —— 見下節,它不是選的
```

C = 2.3,兩個約束同時綁住 —— 那是下一節的貪婪排程器自己會走到的點:

| | E = 300 `[I]` | E = 240 | E = 169.7 `[M]` |
|---|---|---|---|
| 12bit | 17.89 Mpix `5181×3453` | 16.76 `5014×3342` | 15.43 `4812×3208` |
| 10bit | 20.34 `5524×3682` | 19.21 `5368×3578` | 17.88 `5179×3452` |
| **8bit** | **24.01 `6002×4000`** | **22.88 `5859×3905`** | **21.55 `5686×3790`** |

### 這張表的重點:8bit 對那個沒人量過的數字不敏感

引擎的持續速率仍然沒量過,估計值跨度 77%(169.7 到 300 Mpix/s)。
在 8bit 下,那只讓輸出**邊長差 5%** —— 5686×3790 到 6002×4000,
也就是原生 6K 的 94% 到 99%。

對壓縮比也不敏感。`C = 2.3` 是在 **12bit** Bayer 上量的,用在 8bit 上是假設,
所以把整個範圍都算了(8bit、L = 550、E = 300):

```
C = 1.5    5704x3802        C = 2.3    6002x4000
C = 2.0    5920x3946        C = 3.0    6064x4042(原生)
```

**這個設計的兩個未量輸入,都只把答案在原生 6K 的 94%~100% 之間移動。**
這才是選 8bit 的理由:不是因為它便宜,而是因為**只有它的答案已經知道了。**

### 原生 6064×4042 塞不進 550,而且在實測的引擎速率下是不可能

```
6K 8bit 未壓縮 = 734.6 MB/s
要到 550       = 必須減掉 25.1%
能減掉的       = f × (1 - 1/C),而 f 被引擎鎖死
```

| E | f 上限 | 最多能減 | 需要的 C |
|---|---|---|---|
| 169.7 `[M]` | 0.231 | 23.1% | **不可能** |
| 240 | 0.327 | 32.7% | 4.33 |
| 300 `[I]` | 0.408 | 40.8% | 2.60 |

第一列不是「壓縮比不夠好」。`f = 0.231` 時,**就算被壓的幀變成 0 bytes**,
最多也只減得掉 23.1%,而需要 25.1%。**能壓的幀數本身就不夠。**

要規格上的原生 6064×4042,鏈路得到 **565 MB/s**(E = 300)或 **639**
(E = 169.7)—— SD 要 175 或 249 MB/s。前者好卡有機會,後者不存在。

實務上 6002×4000 跟 6064×4042 差 1% 邊長。

### 沒有 `f` 要選 —— 排程器自己找到它

`f` 是用來**描述結果**的,不是要設的旋鈕。壓縮器一空下來就抓下一幀;在它忙的
時候到達的幀就原樣寫出去。不需要排程,不需要決定 duty cycle。

```
一幀到達 -> 引擎閒著? 是 -> 壓,寫 Compression=7
                      否 -> 原樣寫,Compression=1
```

這叫 work-conserving,而且它**剛好落在上面那個算式的最佳解上**。
對任何固定的幀尺寸,`f` 越高位元組越少,所以最好的 `f` 就是引擎撐得住的最高值 ——
那正是貪婪排程器依定義會產生的結果:

```
f  =  E / (px × fps)      自動得到,是結果不是輸入
```

代回去得到 `px <= (L + Ek(1 - 1/C)) / (k × fps)`,跟「最佳 f」公式給的界一模一樣。
**貪婪排程器是最佳的,而且完全不需要知道 `E`。**

**這把餘裕問題整個消掉了。** 這份文件的上一版擔心「最佳解讓引擎跑 100%、沒有
時序餘裕」,因此建議退到 `f = 1/2` 換點空間。那個擔心是**把 `f` 當成固定值的
副作用**:duty cycle 固定時,「這一幀要壓」是一個**死線**,錯過就是失敗。
貪婪排程沒有死線 —— 引擎忙不是錯誤,只是那一幀原樣寫出去。
**引擎 100% 是正常工作點,不是危險。**

它還吸收掉別的方法吸收不了的變異:

- 壓縮時間隨畫面內容變動;固定 `f` 必須照最壞情況假設
- 引擎可能降頻,或在某些幀上跟別人搶匯流排
- `E` 沒量過,而排程器不在乎

代價是輸出大小逐幀不同、哪些幀被壓事先不知道。對「自己的串流 + 索引」來說那不算
什麼;對 CinemaDNG 來說每個檔案本來就各自宣告 `Compression`。

### 為什麼是隔幀,以及「不必是合法 DNG」鬆開了什麼

**TIFF 的 `Compression` 是每個 IFD 一個**,所以同一個檔案不能一半壓一半不壓。
隔**幀**就沒這個問題:CinemaDNG 是一串獨立檔案,各自宣告 `Compression`,
幀 1 寫 7、幀 2 寫 1,兩個都合法。

> **假設,未驗證:**讀取端能接受混用的序列。**這個不用相機就能測** ——
> 主機端做一段交錯的丟進 Resolve。

如果卡上的格式**不必**是合法 DNG(自己的串流,主機端轉檔),鬆開三件事,
而且**沒有一件是頻寬**:

1. **可以大塊順序寫入。** 比另外兩件值錢:見上面的區塊大小數字。SD 卡在
   10 MB 區塊比 50 MB 慢 30%,而一格是 24.5 MB。
2. **省掉每幀的 DNG header** —— 實測 79,240 B(open gate)與 79,960 B
   (UHD 8bit),約 0.9%,即 2.4 MB/s。零頭,但白送。
3. **上面那個混合序列的假設不再重要**,因為轉檔器可以產出讀取端要的任何東西。

代價是一個主機端轉檔器 —— 而混合序列的風險**反正可能也要寫**。

### 相機今天實際在錄什麼(從卡上的檔案量的)

拿來校準上面所有數字。從真實 take 的 DNG header 讀出,`每格位元組 × 29.97`:

```
FHD  1936x1090  12bit    3,244,544 B     97.2 MB/s
UHD  3856x2170   8bit    8,447,488 B    253.2 MB/s
UHD  3856x2170  12bit   12,630,528 B    378.5 MB/s
open gate 3032x2012 12b  9,229,824 B    276.6 MB/s
```

兩個推論:

- **FHD 12bit 要 97.2 MB/s,而實測那張卡只有 94。** 它錄得下去只是因為 RAM
  緩衝墊掉了 3% 的差額。**這才是**錄影中 SD 寫入最壞 692 ms、優先權 28 的
  writer 搶不到卡鎖、陀螺樣本被擠掉的真正解釋:錄 FHD 時那張卡是滿載的。
- **卡上每一段 open gate 都停在 3~4 秒。** 276.6 對上 94 MB/s,緩衝以
  182 MB/s 的赤字被吃掉;由片長反推緩衝約 600~750 MB。**不是 bug,是卡。**

### 引擎的 API,來自靜態拍照路徑

靜態拍照路徑已經會把 6064×4042 的 Bayer 壓成無損 DNG,那就是參考實作。
HAL 是 `src/hal/RawCD/src/XC_HalLjpeg.cpp`:

```
FUN_c05a6890(params9)  -> FUN_c062f5a8    開始編碼
FUN_c05a6920(params5)  -> FUN_c062f6f8    等完成
FUN_c05a6990(x, 1)     -> FUN_c062fa48    取結果
FUN_c03d9668(addr)                        虛擬 -> 匯流排位址轉換
```

編碼吃的九個字,從 `blk_c03.c` 中 `0xC037E7AC` 附近的呼叫端讀出:

```
[0] 寬          [1] 高           [2] 來源緩衝(已轉換)
[3] 0x100       [4] 0x100        [5] 目的緩衝
[6] FUN_c0398b00() 的回傳        [7] *(obj+0x0C)
[8] 模式位元組,低位元清掉
```

等待呼叫吃五個:`{w, h, buf, 0x100, 0x100}`。`FUN_c062f6f8` 裡的
`timeout = pixels / 32000` 是**看門狗,不是吞吐量**。
`+0xF8` 是產出位元組數,`+0x3FC` 是忙碌/清除。

### 已確立

- **SSD 寫 ~390 MB/s,卡在匯流排。** 兩個外接盒 363 與 390;讀寫相當。`[M]`
- **SD 寫 94、讀 218。** 兩次開機重現,誤差 <1%。`[M]`
- **寫入區塊大小有影響** —— SD 從 10 到 50 MB 提升 48%,還沒平。`[M]`
- **8bit CinemaDNG 帶 `LinearizationTable`**,256 筆,分段 log。
  **companding 是已解決的問題,而且在出廠韌體裡。**`[M]`
- **兩個媒體互相獨立** —— 不同驅動、不同鎖。`[C]`
- **錄影期間引擎是閒的。** 錄影用 `0x301B` 的 DSP 與 `0x300C` 的 RFC 讀出,
  沒有爭用要設計。`[C]`
- **壓縮比約 2.3:1**,在這顆感光元件的 12bit Bayer 上。`[C]`
- **只有一個引擎、沒有平行度**,時脈不能拉高。`[C]`
- **mode 3 是原廠的 6064×4042 1×1 @29.97 讀出。**`[C]`
- **鏈路是 Gen1。** BOS 是 SUPERSPEED_USB、`wSpeedsSupported = 0x000E`,
  描述元區完全沒有 SUPERSPEED_PLUS。`[C]`

### 未確立

按對設計的影響排序。**引擎已經不是第一名了** —— 選了 8bit 把它降級了。

1. **SD 卡能不能到 160 MB/s。** 整個鏈路預算壓在這上面。
   買一張卡、跑 `tools/storage-benchmark/` 就收掉。
2. **大區塊對 SD 卡有沒有幫助。** 50 MB 以上沒量過,而且曲線還在往上。
   同一張卡免費就能知道。
3. **兩個媒體會不會相加。** 是分開量的;同時寫要共用 DRAM 與 CPU。
4. **引擎的持續速率。** 仍然只有一次冷呼叫:6064×4042 花 144,431 µs =
   169.7 Mpix/s,而且電源/時脈/IRQ 的啟動在 encode **裡面**。
   探針寫好了但從沒跑過:`raw/ljtime_deploy.py`,掛 `0xC037E7AC`。
   **在 8bit 下這只把輸出從 94% 移到 99%。**
5. **8bit companded 資料的壓縮比。** 2.3:1 是 12bit 的數字。
   上面算過整個範圍,一樣只值 5%。
6. **RWZM 的輸出能不能餵給引擎。** 只有在輸出要縮到小於感光元件時才重要,
   而 8bit 已經不需要縮了。
7. **讀取端能不能吃 `Compression` 混用的序列。** 主機端就能測,不用相機。

### 不要做的

- **不要冷呼叫引擎,要用 hook。** 十幾次冷呼叫把靜態壓縮弄壞到重開機才復原 ——
  卡上檔案大小從 26~28 MB(壓過)變成 51 MB(沒壓),重開後 36 MB。
- **不要買更快的 SSD。** 瓶頸是匯流排。真要花錢,先換**外接盒**,更先換**記憶卡**。
- **不要照 12bit 規劃。** L = 550 時它最多給 `5181×3453`,比 8bit 的
  `6002×4000` 還差,而且它是那個「答案取決於沒量過的引擎速率」的版本。

### 相關

- `projects/open-gate.md` —— 6K 來源與畫布的工作
- `projects/raw-sup.md` —— 引擎、它的量測與路線圖
- `tools/storage-benchmark/` —— 收掉上面第 1、2 項的那張卡
- `notes/research/imaging-hw/RAW_COMPRESSION_RESEARCH.md` —— 把固定開銷與速率分開的方法
