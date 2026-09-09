# open gate

[English](#english) | [繁體中文](#繁體中文)

Recording the sensor's full 3:2 area instead of the 16:9 window the camera crops to.
**Status: the sensor side is solved and was never the obstacle. The output canvas is
the wall, and it has one unfound conversion in it.**

用感光元件完整的 3:2 面積錄影,而不是相機裁出來的 16:9 視窗。
**狀態:感光元件那一側已解,而且從來就不是障礙。牆在輸出畫布,缺一個還沒找到的轉換。**

---

## English

### What "open gate" means here

The IMX410 is 6064×4042, 3:2. Every movie mode the camera will select is 16:9 —
either 6064×3412 (1×1) or 3032×1708 (2×2 binning). Open gate means getting the
full 4042 rows into a CinemaDNG.

### The sensor side is done

This was the surprise: the full-frame readout already exists, already runs, and
is not what stops us.

| | mode | readout | note |
|---|---|---|---|
| boot / live view | 3 | 6064×4042 1×1 @29.97 | **full 3:2, running at power-on** |
| UHD CinemaDNG | 123 | 6064×3412 1×1 | full width, no downsampling |
| FHD CinemaDNG | 106 | 3032×1708 2×2 | rolling shutter 10.556 ms |
| 3K candidate | 117 | 3032×2012 2×2 @100 | **full width binning, not a centre crop** |
| 6K candidate | 121 | 6064×4042 1×1 @24.9997 | full sensor |

Measured, not read off a datasheet: the recording mode is recoverable after a take
from `0xC343B590` (the sensor object's *previous* mode — `0xC343B588`+8). FHD read
106, UHD read 123.

**And the mode can be changed.** The picker `FUN_c0437078` resolves through
`XC_LiveViewConfiguratorW71c1::v3` (`0xC043BE68`, vtable `0xC0BE44D0`+0x14) into one
of three 26-entry tables — `0xC0BE5810` / `0xC0BE59B0` / `0xC0BE5B50`, sixteen bytes
per entry, **`+0x08` is the sensor mode**. UHD 25p sits in the first entry of each.
Patching all three (`0xC0BE5828` / `0xC0BE59C8` / `0xC0BE5B68`) to 121 made the probe
answer 121 immediately, and a real take afterwards read **121** back — the camera
recorded with a full-frame 6064×4042 1×1 readout.

### How a mode actually gets set, end to end

Measured and confirmed against the machine code, not read off the decompiler —
the last time this was traced from the C alone it produced a wrong answer that
survived several readings:

```
master settings *(0xC3075230)      +0x00 width  +0x04 height  +0x14 fps enum
    ↓
FUN_c0437078(kind, 0, block, 3)                  the picker, 0xC0437078
    ↓
capture request +0x60                            written by FUN_c0374268
    ↓
acquisition struct +0x14        FUN_c0378a50 single / FUN_c0379b68 continuous,
                                both under XC_StillCreateRaw__v4
    ↓
message +0x1c                   0x1C0 bytes, payload from +8
    ↓
SetImgMode_s → FUN_c0314708:  str r7,[r6]  at 0xC0314750
    ↓
FUN_c03212e0:  sensorObj+4 = mode            (0xC343B58C)
```

`kind`: **2 = movie/monitor** (answers 123, matching a real UHD 25p take),
3 = still (97), 4 = continuous (142).

### What the picker answers when you ask it

`FUN_c0437078` is a pure function of the settings, so the whole table can be
read off with nothing recording. `kind=2`, rows are the requested output size,
columns the frame-rate enum:

```
size            23.976  24.000  25.000  29.970    100   119.88
1920x1080          109     218     125     106     89      58
3840x2160          101     151     123       7      7       7
4096x2160            7       7       7       7      7       7
3032x2012          109     218     125     106     89      58
6064x4042          109     218     125     106     89      58
```

Two things fall out of it:

- **3032×2012 and 6064×4042 answer identically to 1920×1080.** The picker does
  not recognise them; they fall through to the default row. Width and height are
  not being compared against a size table at all.
- **Every mode it returns is 16:9** — 3032×1708 or 6064×3412. It has never once
  returned a 3:2 full-height mode (121 / 11 / 117 / 98 / 143).

So the nights spent watching settings get "put back" were not about illegal
combinations. Those modes **do not exist for the recording path**, and that is a
table, not a rule.

The other branch of the picker has not been exercised: `kind=2` with
`query+0x24 == 0` goes to `FUN_c043b988` and five tables (default `0xC0BE4D50`,
0x300 = 48 entries) instead of the three 26-entry ones. The camera takes the
three-table branch in practice.

### The result that decides the shape of the problem

**The field of view did not change.**

Two independent checks, by numerical comparison — best scale 1.00, mean absolute
difference 0.04:

- UHD: mode 121 (6064×4042 3:2) against mode 123 (6064×3412 16:9) — identical framing
- FHD: mode 3 (6064×4042 3:2) against mode 106 (3032×1708 16:9) — identical framing

The ISP crops to the canvas aspect regardless of what the sensor hands it. And the
live view was *seen* to widen mid-recording, so the wider data is genuinely in the
pipe — only the recording branch throws it away.

**So what is missing is the canvas, not the mode.** Every further attempt at the
sensor is wasted effort.

### The canvas: what is known and what is eliminated

The recorded DNG dimensions are the settings block's `+0x00` / `+0x04` plus 16 and
10. That block exists in three copies — master `*(0xC3075230)`, mirror `0xC3758B98`
(what `setting get/set` edits), and CameraMgr `FUN_c0206e98()+0x40`. Writing a legal
combination into **all three** and pressing record put all three back to 3840×2160.

> **Settings are an output, not an input.** Four approaches were reversed this way,
> including the last with a legal pair (6064×4042 + 25p).

> **Corrected 2026-09-10.** This section used to name `+0x48` as the load-bearing
> observation — "it never changes (FHD 0, UHD 4) and the geometry always agrees
> with it". **`+0x48` reads 0 in both FHD and UHD.** The field that holds 0/4 is
> **`+0x08`**, and it tracks the *frame rate*, not the resolution (fps enum 4 → 0,
> fps enum 3 → 4). The original diff changed resolution and frame rate together, so
> the two were confounded. A controlled diff — FHD 29.97 against UHD 29.97, same
> frame rate — shows **only `+0x00` and `+0x04` differ** in the first 0x80 bytes.
> There is no hidden resolution field in this block. See `notes/FRAME_RATE_IS_VMAX.md`.

Eliminated by patching and re-testing — none of these move the recorded size:

| address | what it is | result |
|---|---|---|
| `0xC0B51044` | 14 rows `{w,h,fps_idx,x}` — the CINE menu list | height changed, DNG unchanged |
| `0xC0BE4474` | 5 rows `{1920,1080,3840,2160,"UHD"}` | UHD height changed, master still 2160 |
| `0xC096F580` | the CinemaDNG frame-size table (3856×2170 / 1936×1090 / 6064×4042 / 3968×2640) — the only one in the firmware | 2170→2570, DNG still 2170 |

Found instead, by diffing `menu dump` (UI store `0xC31B32BC`, 2496 bytes) across a
resolution change: **the UI enum is one byte at `0xC31B3A4C`** (2 = FHD, 3 = UHD).
Writing it does not propagate; a menu action has to trigger the conversion.

The menu command table is at `0xC0BBB5E8`, three words per entry `{name, help,
handler}`:

```
SetMovRecSize     -> 0xC03FDAB0   with an argument: FUN_c005c020(0xC31AC530, v, 1)
SetMovFramerate   -> 0xC03FDB20   property system, vtable slot +0x1A0
SetMovBiningSupport -> 0xC03FDB90  boolean, currently 0, clamps to 1
```

`menu SetMovRecSize <n>` is the **one path that actually updates the master block** —
everything written directly into RAM was downstream of it. But sweeping 0–7 gives
only two answers: 2 → 1920×1080, everything else → 3840×2160 (and it sets the frame
rate as a side effect: 3 → fps enum 3, else 4). There is no hidden 3:2 size.

**So the enum → (width, height) conversion lives in an observer of the `+0x1A0`
property on `0xC31AC530`, and that observer has not been located.** This is the next
thing to find, and `menu SetMovRecSize` is a reliable trigger for it: set it and the
conversion runs once, on demand.

### Frame rate, and a correction

The recording frame rate matches the sensor mode's exactly (FHD 29.97 ↔ mode 106's
29.97; UHD 25 ↔ mode 123's 25.0). The movie frame rate is an enum;
`FUN_c00c9bd0` (`0xC00C9BD0`) is its table:

```
1 = 23.976   2 = 24.000   3 = 25.000   4 = 29.970   6 = 48.000
7 = 50.000   8 = 59.940   9 = 100.000  10 = 119.880
```

Against the two full-sensor modes:

- **6064×4042 = mode 121 @ 24.9997** ≈ enum 3 (25p). Legal.
- **3032×2012 = mode 117 @ 100** — enum 9 is 100.000. Also legal.

> **Correction.** 3032×2012 was ruled out once on the grounds that its frame rate was
> 99.9001 and matched no enum. That figure came from a CSV derived from the firmware
> image; the camera's own `imager mode_list` says `042 MONIT1_100 / 0117 /
> 3032x2012 / 100 fps / 3:2 full`. **3K open gate is not blocked by frame rate.** The
> older note that concluded "the only legal combination is 121" predates this and
> should not be relied on.

The user reports 100 fps is not selectable on the SD card path — a separate
constraint on the 3K route, not yet traced.

### The 3K route is not cheaper

The premise "do 3032×2012 first, it is a quarter of the data" is false, because the
only frame rate that mode offers is four times higher:

```
6064×4042 × 12 bit × 25 fps   = 24,510,688 px  →  919 MB/s
3032×2012 × 12 bit × 100 fps  =  6,100,384 px  →  915 MB/s
```

Within half a percent of each other. For scale, today's UHD CinemaDNG frame is
3856×2170, which is 2.9× fewer pixels than the full sensor.

> **Superseded 2026-09-10. The 3K route is the cheap one after all, and it needed
> no decoupling.** The premise above — "the only frame rate that mode offers is
> four times higher" — was wrong: a mode's frame rate is not a property of the
> mode. It is `vmax`, one u16 in the timing table at `0xC0B59500`, and the table
> is directly writable. `hmax` is untouched, so the rolling shutter does not move.
>
> Mode 117 with `vmax 2184 → 7280` is **3032×2012 3:2 at 29.97003 fps, rolling
> shutter 9.221 ms**, and the camera's own `imager mode_list` reports it. A real
> take read **117** back from `0xC343B590`. That is **274.2 MB/s uncompressed —
> 27% below the UHD 29.97 the camera already writes** (mode 7, 376.2 MB/s), so it
> needs no compression engine and no measurement of one.
>
> Read rate and record rate never had to be decoupled. Set the rate you want.
> See `notes/FRAME_RATE_IS_VMAX.md`.

### Rolling shutter, which nobody has asked for yet

This matters more here than in most projects, because the whole gyro product
corrects for it. Measured, from `hmax × height ÷ 72`:

| mode | | rolling shutter |
|---|---|---|
| 8 | live view | 6.160 ms |
| 106 | FHD CinemaDNG | 10.556 ms |
| 123 | UHD CinemaDNG | **21.325 ms** |
| **121** | **6K open gate** | **24.981 ms** — asked, see below |

121 reads 4042 rows where 123 reads 3412. If `hmax` is unchanged between them
the answer is about 25 ms, but that is arithmetic on an assumption, not a
measurement — and the camera can be asked directly, in one call, with nothing
recording: `FUN_c0320FC8(obj, 121)` for hmax, `FUN_c0321028(obj, 121)` for the
height. **Ask before designing around a guess.**

### The second lead, and the experiment that would settle +0x48

Two threads were left open before the canvas became the obvious target, and
neither is dead:

**Who fills message `+0x1c` with 123?** The chain above ends at
`ContSet_Adr1`: `if (*(param_2+0x1c) != *request) SetImgMode_s(request,
*(param_2+0x1c))`. During recording that descriptor is built by the movie
recorder, so the question is what `movRec` (`0xC038A3E8`) /
`MovRecFuncStateTHR` puts there. This is the mode side, which is solved, so it
is only worth following if the canvas turns out to be chosen in the same place.

**What drives `+0x48`?** It never moves, and the geometry always agrees with it,
so it is upstream of everything we can write. Rather than guessing at another
table: switch the menu to FHD, `setting read`, dump all 178 named parameters;
switch to UHD, dump again; **diff**. Whatever changed is the source. This has
not been run.

`SetMovBiningSupport` (`0xC03FDB90`) is a boolean, currently 0, and clamps a 2
to 1. It does nothing to the canvas or the mode while idle. It may only be
consulted when the mode is chosen at record start — untested.

### If the canvas cannot be moved

The ISP crops to the canvas aspect, and the canvas is set by something we have
not found. If it turns out to be unreachable, the alternative is not a better
patch — it is not using the recording branch at all: take the Bayer data from
the sensor path and write the container ourselves. That is `raw-sup.md`'s
territory, and its own blocker (the compression throughput needed for UHD) is
measured there. The two projects meet at that point.

### Tools that make this cheap to work on

- **Ask the picker without touching the camera.** `FUN_c0437078` is a pure function
  of the settings. A stub that calls it with your *own* copy of the settings block
  returns the whole settings→mode table with nothing recording. Verify a patch this
  way before spending a take on it.
- **`imager mode_list`** prints the camera's own 70-entry mode table — names, enum,
  bit depth, size, fps, aspect, crop. More reliable than anything derived from the
  image. **`imager mode_now`** for the current one.
- **After a take, read `0xC343B590`** for the mode that was actually used.
- **Per-mode geometry and timing at runtime**: `FUN_c0321028(obj, mode)` for the
  geometry row (`+4` width, `+8` height), `FUN_c0320FC8` for timing (`+4` hmax).
  Rolling shutter = hmax × height ÷ 72 µs.

### Do not

- **Do not hook `FUN_c03212e0`.** It runs ten times taking a photo with no trouble,
  and freezes the camera the instant record is pressed. Cause never established.
- One garbled UHD frame was seen once with a shell card attached over USB, and did
  not reproduce on either of the next two attempts. **Not evidence.**

### The next step

Find the observer of the `+0x1A0` property on `0xC31AC530`. Everything else about
this problem is either solved or eliminated.

---

## 繁體中文

### 這裡的「Open Gate」指什麼

IMX410 是 6064×4042、3:2。但相機會選的每一個動態模式都是 16:9 —— 不是 6064×3412
(1×1)就是 3032×1708(2×2 binning)。Open Gate 就是把完整的 4042 列錄進 CinemaDNG。

### 感光元件那一側已經解完了

這是意外的部分:**全片幅讀出本來就存在、本來就在跑**,不是擋住我們的東西。

| | 模式 | 讀出 | |
|---|---|---|---|
| 開機 / 即時取景 | 3 | 6064×4042 1×1 @29.97 | **完整 3:2,開機就在跑** |
| UHD CinemaDNG | 123 | 6064×3412 1×1 | 全寬、不降採 |
| FHD CinemaDNG | 106 | 3032×1708 2×2 | 捲簾 10.556 ms |
| 3K 候選 | 117 | 3032×2012 2×2 @100 | **全寬 binning,不是中央裁切** |
| 6K 候選 | 121 | 6064×4042 1×1 @24.9997 | 完整感光元件 |

這些是量出來的,不是從規格書抄的:錄完之後讀 `0xC343B590`(感光元件物件
`0xC343B588` 的 +8,存的是**前一個**模式)就拿得到。FHD 讀到 106,UHD 讀到 123。

**而且模式改得動。** 選擇器 `FUN_c0437078` 經 `XC_LiveViewConfiguratorW71c1::v3`
(`0xC043BE68`,vtable `0xC0BE44D0`+0x14)落到三張 26 筆的表之一 —— `0xC0BE5810` /
`0xC0BE59B0` / `0xC0BE5B50`,每筆 16 位元組,**`+0x08` 就是感光元件模式**。UHD 25p
在每張表的第一筆。三個都改成 121(`0xC0BE5828` / `0xC0BE59C8` / `0xC0BE5B68`)之後,
探針立刻回 121,實錄一段之後讀回 **121** —— 相機真的用 6064×4042 1×1 全片幅讀出錄了。

### 模式是怎麼被設定的,從頭到尾

這條鏈是對著機器碼確認的,不是從反編譯的 C 讀的 —— 上一次只讀 C 就推論,得到一個
錯誤答案,而且我讀過好幾次都沒發現:

```
主設定 *(0xC3075230)        +0x00 寬  +0x04 高  +0x14 幀率列舉
    ↓
FUN_c0437078(kind, 0, block, 3)              選擇器,0xC0437078
    ↓
擷取請求 +0x60                                FUN_c0374268 寫的
    ↓
取像結構 +0x14              FUN_c0378a50 單張 / FUN_c0379b68 連續,
                            都在 XC_StillCreateRaw__v4 底下
    ↓
訊息 +0x1c                  0x1C0 位元組,payload 從 +8 起
    ↓
SetImgMode_s → FUN_c0314708:  str r7,[r6]  於 0xC0314750
    ↓
FUN_c03212e0:  sensorObj+4 = 模式             (0xC343B58C)
```

`kind`:**2 = 動態/監看**(回 123,與 UHD 25p 實錄一致)、3 = 靜態(回 97)、
4 = 連拍(回 142)。

### 直接問選擇器,它會怎麼回答

`FUN_c0437078` 是設定的純函式,所以整張表可以在完全不錄影的情況下問出來。
`kind=2`,橫列是要求的輸出尺寸,直行是幀率列舉:

```
尺寸            23.976  24.000  25.000  29.970    100   119.88
1920x1080          109     218     125     106     89      58
3840x2160          101     151     123       7      7       7
4096x2160            7       7       7       7      7       7
3032x2012          109     218     125     106     89      58
6064x4042          109     218     125     106     89      58
```

兩件事直接掉出來:

- **3032×2012 與 6064×4042 的答案跟 1920×1080 完全相同。** 選擇器不認得它們,
  落到預設列。**寬高根本沒有被拿去比對任何尺寸表。**
- **它回傳的每一個模式都是 16:9** —— 3032×1708 或 6064×3412。**從來沒有回過**
  3:2 全高模式(121 / 11 / 117 / 98 / 143)。

所以那些夜裡看著設定被「刷回去」,不是組合不合法。那些模式**對錄影路徑不存在**,
而那是一張表,不是一條規則。

選擇器的另一個分支還沒被走過:`kind=2` 且 `query+0x24 == 0` 會走 `FUN_c043b988`
與五張表(預設 `0xC0BE4D50`,0x300 = 48 筆),而不是那三張 26 筆的。實機走的是
三張表那一支。

### 決定問題形狀的那個結果

**視野沒有變。**

兩次獨立驗證,數值比對 —— 最佳縮放 1.00、平均絕對差 0.04:

- UHD:模式 121(6064×4042 3:2)對模式 123(6064×3412 16:9)—— 構圖完全相同
- FHD:模式 3(6064×4042 3:2)對模式 106(3032×1708 16:9)—— 構圖完全相同

不管感光元件交出什麼,ISP 都照畫布的長寬比裁。而且**使用者親眼看到即時預覽在錄影中
變寬了**,所以更寬的資料確實流進了管線,只有錄影分支把它丟掉。

**所以缺的是畫布,不是模式。** 再往感光元件那邊試都是白費力氣。

### 畫布:已知的與已排除的

錄下來的 DNG 尺寸 = 設定 block 的 `+0x00` / `+0x04` 再加 16 與 10。那個 block 有三份
複本 —— 主本 `*(0xC3075230)`、鏡像 `0xC3758B98`(`setting get/set` 改的是這份)、
CameraMgr `FUN_c0206e98()+0x40`。**三份同時**寫進合法組合再按錄影,三份全被改回
3840×2160。

> **設定是輸出,不是輸入。** 四種做法都這樣被刷回去,包括最後一次用合法組合
> (6064×4042 + 25p)。

> **2026-09-10 訂正。** 這裡原本把 `+0x48` 當成關鍵觀察 ——「從頭到尾沒變過
> (FHD=0、UHD=4),而幾何永遠跟它一致」。**實測 `+0x48` 在 FHD 和 UHD 都是 0。**
> 拿 0/4 的是 **`+0x08`**,而且它**跟著幀率走**,不是解析度(fps enum 4 → 0、
> fps enum 3 → 4)。原本那個 diff 同時動了解析度與幀率,兩個變因混在一起。
> 控制良好的對照(FHD 29.97 對 UHD 29.97,同幀率)顯示 **0x80 bytes 內只有
> `+0x00` 與 `+0x04` 不同**。這個 block 裡沒有隱藏的解析度欄位。
> 見 `notes/FRAME_RATE_IS_VMAX.md`。

改了再測、確定**不會**改變錄影尺寸的:

| 位址 | 是什麼 | 結果 |
|---|---|---|
| `0xC0B51044` | 14 筆 `{w,h,fps_idx,x}`,CINE 選單清單 | 改了高度,DNG 不變 |
| `0xC0BE4474` | 5 筆 `{1920,1080,3840,2160,"UHD"}` | 改了 UHD 高度,主設定仍 2160 |
| `0xC096F580` | CinemaDNG 畫格尺寸表(3856×2170 / 1936×1090 / 6064×4042 / 3968×2640),全韌體唯一一處 | 2170→2570,DNG 仍 2170 |

反過來找到的:用 `menu dump`(UI 設定區 `0xC31B32BC`,2496 bytes)在切換解析度前後
逐位元組比對 —— **UI 的解析度列舉是 `0xC31B3A4C` 的單一位元組**(2 = FHD、3 = UHD)。
直接寫它不會傳播,要有選單動作才觸發轉換。

選單指令表在 `0xC0BBB5E8`,每筆三個字 `{名稱, 說明, 處理函式}`:

```
SetMovRecSize       -> 0xC03FDAB0   有參數時:FUN_c005c020(0xC31AC530, 值, 1)
SetMovFramerate     -> 0xC03FDB20   都走屬性系統的 vtable slot +0x1A0
SetMovBiningSupport -> 0xC03FDB90   布林,現值 0,給 2 會夾成 1
```

`menu SetMovRecSize <n>` 是**唯一真的會更新主設定的路徑** —— 我們之前直接寫 RAM 都
在它下游。但掃過 0–7 只有兩個結果:2 → 1920×1080,其餘 → 3840×2160(順帶決定幀率:
3 → fps 列舉 3,其餘 → 4)。**沒有藏起來的 3:2 尺寸。**

**所以列舉 →(寬,高)的轉換在 `0xC31AC530` 那個 `+0x1A0` 屬性的某個觀察者裡,
而那個觀察者還沒被定位。** 這是下一件要找的事,而 `menu SetMovRecSize` 是個可靠的
觸發器:設一次它就跑一次。

### 幀率,以及一個訂正

錄影幀率跟感光元件模式的幀率是**精確匹配**的(FHD 29.97 ↔ 模式 106 的 29.97;
UHD 25 ↔ 模式 123 的 25.0)。動態幀率是列舉,`FUN_c00c9bd0`(`0xC00C9BD0`)就是它的表:

```
1 = 23.976   2 = 24.000   3 = 25.000   4 = 29.970   6 = 48.000
7 = 50.000   8 = 59.940   9 = 100.000  10 = 119.880
```

對到兩個覆蓋全感光元件的模式:

- **6064×4042 = 模式 121 @ 24.9997** ≈ 列舉 3(25p)。合法。
- **3032×2012 = 模式 117 @ 100** —— 列舉 9 就是 100.000。也合法。

> **訂正。** 3032×2012 曾經被判出局,理由是它的幀率 99.9001 配不上任何列舉。那個數字
> 來自從韌體影像推出來的 CSV;**相機自己的 `imager mode_list` 寫的是**
> `042 MONIT1_100 / 0117 / 3032x2012 / 100 fps / 3:2 full`。**3K Open Gate 沒有被幀率
> 封死。** 舊筆記裡「唯一合法的組合是 121」那句寫在這個訂正之前,不要再引用。

使用者回報 SD 卡路徑下選不到 100 fps —— 那是 3K 路線上另一道限制,還沒追。

### 3K 那條路並沒有比較便宜

「先做 3032×2012,資料量只有四分之一」這個前提是錯的,因為那個模式唯一提供的幀率
高了四倍:

```
6064×4042 × 12 bit × 25 fps   = 24,510,688 px  →  919 MB/s
3032×2012 × 12 bit × 100 fps  =  6,100,384 px  →  915 MB/s
```

兩者相差不到半個百分點。對照:現在 UHD CinemaDNG 的畫格是 3856×2170,像素數是全感光
元件的 1/2.9。

> **2026-09-10 取代。3K 那條路其實才是便宜的,而且根本不需要脫鉤。**
> 上面那個前提 ——「那個模式唯一提供的幀率高了四倍」—— 是錯的:**幀率不是模式的
> 固有屬性**,而是時序表 `0xC0B59500` 裡的一個 u16 `vmax`,而且那張表直接寫得進去。
> `hmax` 不動,所以捲簾不變。
>
> 模式 117 把 `vmax 2184 → 7280`,就是 **3032×2012 3:2 @29.97003 fps,捲簾 9.221 ms**,
> 相機自己的 `imager mode_list` 也這樣報。實錄一段後 `0xC343B590` 讀回 **117**。
> 位元率 **274.2 MB/s 未壓縮 —— 比相機每天在寫的 UHD 29.97(模式 7,376.2 MB/s)
> 還低 27%**,所以不需要壓縮引擎,也不需要去量它。
>
> 讀出率與記錄率從來不必脫鉤,想要幾格就設幾格。見 `notes/FRAME_RATE_IS_VMAX.md`。

### 捲簾,而且還沒有人問過

這一項在這個題目上比在別的題目重要,因為整個陀螺產品就是在修正它。實測值,
由 `hmax × 高 ÷ 72` 算出:

| 模式 | | 捲簾 |
|---|---|---|
| 8 | 即時取景 | 6.160 ms |
| 106 | FHD CinemaDNG | 10.556 ms |
| 123 | UHD CinemaDNG | **21.325 ms** |
| **121** | **6K Open Gate** | **24.981 ms** —— 問過了,見下 |

121 讀 4042 列,123 讀 3412 列。如果兩者的 `hmax` 相同,答案大約是 25 ms ——
但那是建立在一個假設上的算術,不是量測。而**相機一個呼叫就能回答,不用錄影**:
`FUN_c0320FC8(obj, 121)` 拿 hmax、`FUN_c0321028(obj, 121)` 拿高度。
**先問再設計,不要照著猜出來的數字做。**

### 第二條線索,以及能定案 +0x48 的那個實驗

在畫布成為明顯目標之前有兩條線被擱著,兩條都還沒死:

**誰把訊息 `+0x1c` 填成 123?** 上面那條鏈的終點是 `ContSet_Adr1`:
`if (*(param_2+0x1c) != *request) SetImgMode_s(request, *(param_2+0x1c))`。
錄影時那個描述元由電影錄影器建,所以問題是 `movRec`(`0xC038A3E8`)/
`MovRecFuncStateTHR` 往裡面填了什麼。這是模式那一側,已經解了,所以只有在
「畫布也是在同一個地方決定的」時才值得追。

**是什麼在驅動 `+0x48`?** 它從來不動,而幾何永遠跟它一致,所以它在我們能寫的
一切之上游。與其再猜一張表:**選單切 FHD → `setting read` → 把 178 個具名參數
全部 dump;切 UHD → 再 dump;逐項 diff。** 變了的那一項就是來源。這個還沒跑過。

`SetMovBiningSupport`(`0xC03FDB90`)是布林,現值 0,給 2 會夾成 1。閒置時它不影響
畫布也不影響模式。它可能只在錄影開始選模式的那一刻才被讀 —— 沒測過。

### 如果畫布動不了

ISP 照畫布的長寬比裁,而畫布由一個我們還沒找到的東西決定。萬一它真的碰不到,
替代方案不是更好的補丁 —— 是**完全不走錄影分支**:從感光元件路徑把 Bayer 拿下來,
容器自己寫。那是 `raw-sup.md` 的地盤,而它自己的瓶頸(UHD 需要的壓縮吞吐)也在那裡
量過了。兩個專案在這一點會合。

### 讓這件事變便宜的工具

- **不碰相機就能問選擇器。** `FUN_c0437078` 是設定的純函式。寫一段 stub,用**自己準備
  的一份設定副本**呼叫它,就能在完全不錄影的情況下把整張「設定 → 模式」表問出來。
  任何補丁先這樣驗,回傳對了再去花一段錄影。
- **`imager mode_list`** 會印相機自己的 70 筆模式表(名稱、列舉、位元深度、尺寸、fps、
  長寬比、crop),比從影像推的可靠。**`imager mode_now`** 印目前的。
- **錄完讀 `0xC343B590`** 就知道剛才用的是哪個模式。
- **執行期查每個模式的幾何與時序**:`FUN_c0321028(obj, mode)` 幾何列(`+4` 寬、
  `+8` 高)、`FUN_c0320FC8` 時序列(`+4` hmax)。捲簾 = hmax × 高 ÷ 72 µs。

### 不要做的

- **不要在 `FUN_c03212e0` 掛 hook。** 拍照時它跑十次都沒事,但**按下錄影的瞬間相機
  凍結**。原因從來沒查明。
- 用 shell 卡、USB 連著錄 UHD 時出現過**一次**花屏,之後兩次都乾淨。**那不是證據。**

### 下一步

找出 `0xC31AC530` 的 `+0x1A0` 屬性有誰在觀察。這個問題其他部分不是已解就是已排除。
