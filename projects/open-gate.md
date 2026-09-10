# open gate

[English](#english) | [繁體中文](#繁體中文)

Recording the sensor's full 3:2 area instead of the 16:9 window the camera crops to.
**Status, 2026-09-10: the `0xC043A19C` hook now produces a correct 3032×2012 DNG
envelope, header, and allocation. The last recorded test still carried about
1936×1288 of valid content in its upper-left. Changing the four profile-122 RWZM
cells to unity changes the hardware policy; the next test is whether that makes
the Bayer producer fill the envelope. See [`fpsup-opengate-test`](../opengate/).**

The test has no menu yet and temporarily occupies CinemaDNG 12-bit FHD 29.97p.
Live view flickers, and in-camera playback does not display the result correctly.

用感光元件完整的 3:2 面積錄影,而不是相機裁出來的 16:9 視窗。
**狀態,2026-09-10:`0xC043A19C` hook 已產生正確的 3032×2012 DNG envelope、檔頭與
配置;上一個實錄檔的有效內容仍只有左上角約 1936×1288。把 profile 122 的四個 RWZM
值改成 unity 已使硬體 policy 切換;下一個測試是 Bayer producer 是否因此填滿整個
envelope。見 [`fpsup-opengate-test`](../opengate/)。**

目前沒有獨立選單,暫時寄生在 CinemaDNG 12-bit FHD 29.97p。live view 會閃爍,
機身回放也無法正常顯示結果。

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

> **Corrected 2026-09-10: this is correlation, not the chain.** With the enum ->
> (w,h) conversion patched, the settings block held 3032×2012 through an entire
> take — record start no longer puts it back — and the DNG stayed 1936×1090,
> 3,244,544 bytes across all 82 frames. `+16/+10` happens to hold for the two
> shipping sizes and nothing reads the block to get there. **The whole settings
> block is eliminated.** See `notes/CANVAS_IS_NOT_THE_SETTINGS_BLOCK.md`.

An early correlation suggested that the recorded dimensions were the settings
block's `+0x00` / `+0x04` plus 16 and 10. Testing eliminated it. The block has three
copies — master `*(0xC3075230)`, mirror `0xC3758B98` (what `setting get/set` edits),
and CameraMgr `FUN_c0206e98()+0x40`. Even when all three held 3032×2012 through a
take, the DNG stayed 1936×1090. **Settings are an output, not the canvas input.**

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

Later tracing found the enum → (width, height) conversion in
`MenuItemMovieRecSize` metadata at `0xC0742204` / `0xC0742228`. Patching it moves
the master settings block through record start, but not the DNG. This entire
settings path is downstream of the canvas and no longer an open lead.

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

### Retired leads

Two earlier leads are closed. Message `+0x1c` belongs to the sensor-mode side,
which is solved. The claim that settings `+0x48` tracked FHD/UHD came from a
comparison confounded by frame rate: `+0x48` is 0 in both, while `+0x08` follows
frame rate. A controlled FHD/UHD comparison at the same frame rate found no
hidden resolution field. Neither lead determines the DNG canvas or the remaining
producer shape.

### Superseded fallback

Before the canvas hook was found, the fallback was to bypass the recording branch,
take Bayer data from the sensor path, and write a container independently. The
`0xC043A19C` result makes that unnecessary for the current 3K test; it remains only
historical context shared with `raw-sup.md`.

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

The canvas question is solved: one hook at `0xC043A19C` changes the real DNG
allocation and header to 3032×2012. A two-column log then showed that the producer
still supplied about 1936×1288 of valid pixels. The remaining live input was the
profile-122 RWZM ratio: record/live H/V were all `0x640`.

Changing those four cells to unity (`0x400`) made the hardware path leave Hbin2,
select Crmf, and disable RWZM. What has **not** yet been established is the final
DNG content after that transition. Run [`fpsup-opengate-test`](../opengate/), record
only a short take, and measure whether valid Bayer data now fills 3032×2012.

Integration work remains after that result: remove live-view flicker, add a real
menu instead of occupying FHD 29.97p, and restore in-camera playback.

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

> **2026-09-10 訂正:這是相關,不是那條鏈。** 把「列舉 →(寬,高)」的轉換表改掉之後,
> 設定 block **整場錄影都維持 3032×2012 —— record-start 不再把它刷回去** ——
> 而 DNG 仍然是 1936×1090,82 幀全部 3,244,544 bytes。`+16/+10` 只是在那兩個出貨
> 尺寸上剛好成立,沒有任何東西讀這個 block 去得到它。**整個設定 block 排除。**
> 見 `notes/CANVAS_IS_NOT_THE_SETTINGS_BLOCK.md`。

早期相關性曾讓人以為錄下來的 DNG 尺寸 = 設定 block 的 `+0x00` / `+0x04` 再加 16 與
10;實測已排除。那個 block 有三份複本 —— 主本 `*(0xC3075230)`、鏡像
`0xC3758B98`(`setting get/set` 改的是這份)、CameraMgr `FUN_c0206e98()+0x40`。
三份在整段錄影中都維持 3032×2012 時,DNG 仍是 1936×1090。**設定是輸出,不是畫布輸入。**

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

後續已找到列舉 →(寬,高)的轉換:`MenuItemMovieRecSize` 的 metadata 位於
`0xC0742204` / `0xC0742228`。改它會讓主設定 block 撐過 record start,但 DNG 不跟。
因此整條設定路徑都在畫布下游,不再是未解線索。

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

### 已關閉的線索

早期兩條線索都已關閉。訊息 `+0x1c` 屬於已解的 sensor mode 路徑。設定 `+0x48`
跟著 FHD/UHD 的說法來自混了幀率的比較:`+0x48` 在兩邊都是 0,實際變成 0/4 的
`+0x08` 跟著幀率。同幀率的 FHD/UHD 對照沒有找到隱藏解析度欄位。兩者都不決定
DNG 畫布或剩下的 producer 形狀。

### 已被取代的備案

找到畫布 hook 之前,備案是完全繞過錄影分支,從感光元件路徑取得 Bayer 並自行寫容器。
`0xC043A19C` 的結果讓目前 3K 測試不再需要這條路;它只保留為與 `raw-sup.md` 共用的
歷史脈絡。

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

畫布問題已解:`0xC043A19C` 的單一 hook 會把真正的 DNG 配置與檔頭改成 3032×2012。
兩欄 log 隨後證明 producer 仍只交出約 1936×1288 的有效像素。剩下的 live input 是
profile 122 的 RWZM 比率:record/live 的 H/V 四格都是 `0x640`。

把四格改成 unity (`0x400`) 後,硬體路徑已離開 Hbin2、改選 Crmf 並停用 RWZM。
**尚未定案的是這個切換之後的最終 DNG 內容。** 執行
[`fpsup-opengate-test`](../opengate/),只錄一小段,量有效 Bayer 是否已填滿 3032×2012。

結果確認之後仍有整合工作:消除 live view 閃爍、加入真正的選單而不是占用 FHD 29.97p,
以及恢復機身回放。
