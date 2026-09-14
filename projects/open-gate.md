# open gate

[English](#english) | [繁體中文](#繁體中文)

Recording the sensor's full 3:2 area instead of the 16:9 window the camera crops to.
**Status: v0.2.1a alpha. 3024×2010 3:2 CinemaDNG at eight frame rates, DNG
cropped to 3008×2000, whole frame. Native Settings and Quick Set UI pass on
camera. The shutter-angle and loader instruction-cache fixes received a
provisional battery-out cold-boot visual pass at 29.97p/180°; exact readback,
the other frame rates, sustained-media, playback-with-UI and inactive-variant
regressions remain.**

用感光元件完整的 3:2 面積錄影,而不是相機裁出來的 16:9 視窗。
**狀態:v0.2.1a alpha。3024×2010 3:2 CinemaDNG、八個幀率,DNG 裁切
3008×2000,整張畫面。Settings/QS 原生 UI 已通過實機;快門角度與 loader
指令快取修正在完整斷電冷開機後,29.97p/180° 取得暫定目視通過。精確讀值、
其他幀率、持續寫入、UI runtime 回放與非啟用 variants 尚待回歸。**

---

## English

### What it does

```
3024 × 2010 · 3:2 · 12-bit · 29.97003 fps · rolling shutter 9.221 ms
DNG cropped to 3008 × 2000 at (8, 5) · 9,117,360 bytes of strip · 273.2 MB/s
```

Read off the card, not inferred: adjacent-row correlation on a finished clip is
+0.876 to +0.933 on all four edges. The earlier clips, where the producer filled
only the top left, read +0.048 down the right and +0.053 across the bottom. The
whole frame is picture.

**274.2 MB/s is 27% below the UHD 29.97 this camera already writes** (mode 7,
376.2 MB/s), so the lossless JPEG engine and its never-measured throughput are
not on the critical path. Nothing here compresses anything.

Rolling shutter is better than what ships, which matters because the gyro
product corrects for it:

| | mode | readout | rolling shutter |
|---|---|---|---|
| **open gate** | **117** | **3024×2010 2×2 3:2** | **9.221 ms** |
| FHD CinemaDNG today | 106 | 3032×1708 2×2 | 10.556 ms |
| UHD CinemaDNG today | 7 | 6064×3412 1×1 | 21.088 ms |
| full sensor 1×1 | 3 | 6064×4042 1×1 | 24.981 ms |

### Why 3024×2010 and not 3032×2012

The camera's own three recording profiles all crop **+16 wide and +10 high** from
the recorded size, and the recorded width is always a multiple of 16 — p171 is
3856×2170 for 3840×2160, p173 is 1936×1090 for 1920×1080. 3032 is only 8-aligned,
and following the convention rather than fighting it is what made in-camera
playback work: the playback profile's stride *is* the source row pitch, and the
factory strides equal the recorded size of that format's clips.

Verified by unpacking A001_036: header 3024×2010, crop 3008×2000 at (8, 5),
`StripByteCounts` 9,117,360 = 3024 × 2010 × 1.5, sharp edge to edge, nothing
clipped.

### Stored matrix versus default crop

The recording is a **3024×2010 stored RAW matrix**, and the hook deliberately writes
`DefaultCropSize = 3008×2000` with `DefaultCropOrigin = (8, 5)`. The difference is a
centred margin — 8 pixels each side, 5 rows top and bottom — and `ActiveArea` still
covers the whole matrix.

Most DNG applications honour `DefaultCropSize`, so they will report and export
3008×2000 even though `ImageWidth`, `ImageLength`, the strip and the allocation are
all 3024×2010. **That is a presentation crop the hook writes on purpose, not evidence
that the producer only filled 3008×2000.** The margin is what the camera's own three
recording profiles do — +16 wide and +10 high from a 16-aligned recorded width — and
following it is what made in-camera playback work.

A full-matrix variant would set the crop pair to 3024×2010 with the origin at zero,
and then the edge pixels are worth re-testing: they are inside the readout but have
never been looked at, because nothing has displayed them.

### Four separate problems

Each needed its own fix, and each was mistaken for the others at some point.

| | where | what |
|---|---|---|
| **Sensor** | timing table `0xC0B59500` | a frame rate is one u16 — `vmax` — not a property of the mode. Mode 117 at `vmax 7280` is 29.97003 at 0 ppm, and `hmax` is untouched so the rolling shutter does not move |
| **Canvas** | `0xC043A19C`, inside `FUN_c043a158` | the geometry record at `r4+0x5C`, written after the gather and before anything derives from it. Eight fields, two layers: the allocator sizes the RAW buffer from base, the size getter reads override |
| **Producer** | RWZM columns, profile 122 | `0x640` is a 1.5625× reduction that pinned the filled region to 1936 wide. Unity `0x400` releases it |
| **Shutter angle** | four local calls to `FUN_c032c750` | the stock conversion follows the borrowed sensor mode's rate instead of the selected output rate. A narrow wrapper substitutes the requested nominal FPS only for the exact OG3K timing tuple; shutter-speed mode and unknown states stay stock |

### The patch set

RAM only. Remove the AutoRun and cold boot to return to stock; nothing is written
to flash at any point.

```
0xC0B59A28  0x00041C70   mode 117 vmax 2184 → 7280        stock 0x00040888
0xC0BE5888  0x00000075   picker table 1 idx7, 106 → 117   stock 0x0000006A
0xC0BE5A28  0x00000075   picker table 2 idx7
0xC0BE5BC8  0x00000075   picker table 3 idx7
0xC0BD9A34  0x00000400   profile 122 live   RWZM H        stock 0x00000640
0xC0BE1684  0x00000400   profile 122 record RWZM H
0xC0BD9EFC  0x00000400   profile 122 live   RWZM V
0xC0BE1B4C  0x00000400   profile 122 record RWZM V
0xC072F800  232 bytes    the geometry hook payload
0xC043A19C  0xEB0BD597   arm it last; stock is 0xE1A00004 (mov r0, r4)
```

v0.2.1a also redirects the four local shutter-angle callsites at `0xC02092CC`,
`0xC0218AEC`, `0xC0219260` and `0xC03AA568` to one guarded wrapper. The stage-2
loader places every section first, then cleans/invalidates D-cache and invalidates
the whole I-cache before execution, so a previously fetched stock instruction
cannot hide an installed hook.

The hook conditions on the record's own contents — `base == 1936×1090` — rather
than on the selector, so it holds for whichever path a take walks and leaves
every other profile alone.

The build and its manifest are in [`opengate/`](../opengate/).

### Known limits

- **Firmware Ver.5.02 only.** The AutoRun language has no runtime version guard.
- **The native CINE UI, carried forward from v0.2.0test, works.** The collapsed
  Settings summary, three-row Settings list, large and small Quick Set values,
  cursor, and the UHD/FHD/OG3K footer have all been seen working on the camera.
- **v0.2.1a is an alpha shutter-angle fix.** After a battery-out cold boot, the
  user saw FHD and OG3K idle exposure match at 29.97p/180°, a provisional visual
  result without exact shell readback. The other frame rates have not yet had
  the same idle live-view check; this is not a claim that all eight rates passed
  hardware testing.
- **The UI recording regression is deliberately short.** With the full UI
  runtime resident, FHD passed once and UHD/OG3K passed three times each; the
  UHD and OG3K takes were stopped at about one second because the available SD
  card is too slow. One earlier OG3K attempt froze and was not reproduced.
  Sustained recording on fast media, playback with the UI runtime, and inactive
  screen/style variants remain untested.
- The exact release pair is the no-shell form. Its 710 OpenGate words and native
  UI sections are byte-identical to the camera-tested debug form, but the
  no-shell pair has not yet had its own cold-boot camera run.
- The hook's payload occupies `0xC072F800–0xC072F8E8` and its telemetry
  `0xC072FA00–0xC072FA0F`, which collides with the host tools' scratch area.
  While it is armed, plain `mem get`/`mem set` are fine but `getfile.py`,
  `putfile.py`, `inject.py` and `callfn.py` are not.

> Live view flicker, in-camera playback and the lack of a menu were limits until
> 2026-09-13 and are not any more. Live view is verified correct in standby,
> half-press and recording (recording frame against standby: 1.000× on both axes,
> anisotropy 1.0000, correlation 0.9787); playback was fixed by `og3kcanvas.S`,
> one hook with two cases, and verified paused and running on A001_037.

### What is eliminated

Worth as much as what worked, because most of it cost whole evenings.

| candidate | verdict |
|---|---|
| the settings block — three width/height pairs × three copies | all outputs. Held at 3032×2012 through a whole take with the DNG unchanged |
| `MenuItemMovieRecSize` / `StillImageSize` / `HdmiOutputFormat` | the three tables that feed those pairs. Under control, and none of them decides the DNG |
| `0xC37CE210` | reflects the geometry, does not set it — a take with it at `{0,0,0}` still produced 1936×1090 |
| `0xC096F588` | the CinemaDNG frame-size table. Not on this data flow at all |
| CINE menu list `0xC0B51044` | changing the selected row does nothing |
| `setting set` | writes a mirror nothing reads: a set that verifies correctly and changed nothing |

### Corrections kept

- **`+0x48` was never the tell.** It reads 0 in both FHD and UHD. The field
  holding 0/4 is `+0x08` and it tracks the *frame rate*. An early diff moved
  resolution and frame rate together and confounded them.
- **"DNG dimensions = settings block + 16/10" is correlation.** The block held
  3032×2012 through a take and the DNG stayed 1936×1090.
- **The `+0x1A0` observer was never needed.** The enum → (w,h) conversion is a
  table in the property's own metadata, reachable by finding the name string and
  reading what follows.
- **`*(0xC375D840 + 8)` returning "175 and 3" was not a broken mode id.** 175 is
  the FieldAngle selector.
- **RWZM is not only a digital zoom.** An early round dismissed it after testing
  it in live view, where base equals the sensor and the whole stage is
  degenerate. On the record path `0x640` is a real 1.5625× reduction, and unity
  is what let the producer fill the frame.
- **1080p29.97 is mode 106, rolling shutter 10.556 ms** — the picker's 29.97 slot
  holds 106 and mode 111 appears in none of the three arrays. That closes sensor
  lab's last open item and supplies the number the gyro lens profile was missing.

### Asking the camera

- **Ask the picker without touching the camera.** `FUN_c0437078` is a pure
  function of the settings. A stub that calls it with your *own* copy of the
  settings block returns the whole settings→mode table with nothing recording.
  Verify a patch this way before spending a take on it.
- `imager mode_list` — the sensor's own 70-entry table, better than anything
  derived from the image. `imager mode_now` for the current one.
- `menu <SetterName>` with no argument is a **getter**.
- `FUN_c0321028(obj, mode)` for a mode's geometry, `FUN_c0320FC8` for its timing.
  Rolling shutter is `hmax × height ÷ 72` µs.
- After a take, `0xC343B590` holds the mode that was used — but read it
  immediately, because the camera switches again afterwards.

### Do not

- **Do not hook `FUN_c03212e0`.** Ten calls taking a photo are fine; the instant
  record is pressed the camera freezes. Cause never established.
- **Do not read past a structure's known extent in a hook.** A dump that copied
  0x140 bytes from a 0x104 record took the whole camera off USB — a data abort on
  the live path with the shell task holding the dispatcher.

---

## 繁體中文

### 它做到什麼

```
3024 × 2010 · 3:2 · 12-bit · 29.97003 fps · 捲簾 9.221 ms
DNG 裁切 3008 × 2000 @ (8, 5) · strip 9,117,360 bytes · 273.2 MB/s
```

從卡上量的,不是推的:完成的 clip 四邊相鄰列相關性是 +0.876 ~ +0.933。
先前 producer 只填左上角的那些 clip,右邊是 +0.048、下面是 +0.053。整張都是畫面。

**273.2 MB/s 比相機每天在寫的 UHD 29.97(mode 7,376.2 MB/s)低 27%**,
所以那顆無損 JPEG 引擎和它從沒量過的吞吐不在關鍵路徑上。這裡沒有任何壓縮。

捲簾比出貨的還好,而這對 gyro 產品有意義,因為它就在修這個:

| | 模式 | 讀出 | 捲簾 |
|---|---|---|---|
| **open gate** | **117** | **3024×2010 2×2 3:2** | **9.221 ms** |
| 現行 FHD CinemaDNG | 106 | 3032×1708 2×2 | 10.556 ms |
| 現行 UHD CinemaDNG | 7 | 6064×3412 1×1 | 21.088 ms |
| 全感光元件 1×1 | 3 | 6064×4042 1×1 | 24.981 ms |

### 為什麼是 3024×2010 而不是 3032×2012

相機自己的三個錄影 profile 全都是從記錄尺寸**裁掉 +16 寬 / +10 高**,而且記錄寬度
一定是 16 的倍數 —— p171 是 3856×2170 對應 3840×2160,p173 是 1936×1090 對應
1920×1080。3032 只有 8 對齊。**遵守這個慣例而不是跟它對抗,正是機內回放能正常的
原因**:回放 profile 的柵格就是來源列距,而原廠柵格正好等於該格式片子的記錄尺寸。

解檔 A001_036 驗證:標頭 3024×2010、裁切 3008×2000 @ (8, 5)、
`StripByteCounts` 9,117,360 = 3024 × 2010 × 1.5,整幅清晰、邊到邊、無剪切。

### 儲存矩陣與預設裁切

錄下來的是 **3024×2010 的 RAW 儲存矩陣**,而 hook 刻意寫入
`DefaultCropSize = 3008×2000`、`DefaultCropOrigin = (8, 5)`。差額是置中的邊界 ——
左右各 8 pixels、上下各 5 rows —— `ActiveArea` 仍然涵蓋整個矩陣。

多數 DNG 軟體會遵循 `DefaultCropSize`,所以會顯示與匯出 3008×2000,即使
`ImageWidth`、`ImageLength`、strip 與配置全都是 3024×2010。
**那是 hook 主動寫進去的顯示裁切,不是 producer 只填了 3008×2000 的證據。**
那圈邊界就是相機自己三個錄影 profile 的做法 —— 從 16 對齊的記錄寬度裁 +16 寬 / +10 高
—— 而遵守它正是機內回放能正常的原因。

若要做完整矩陣的版本,就把 crop pair 設成 3024×2010、原點歸零;
那時邊緣 pixels 值得重測 —— 它們在讀出範圍內,但從來沒有人看過,因為沒有東西顯示過它們。

### 四個各自獨立的問題

每一個都要各自的解法,而且每一個都曾經被誤認成另外兩個。

| | 位置 | 內容 |
|---|---|---|
| **感光元件** | 時序表 `0xC0B59500` | 幀率是一個 u16 —— `vmax` —— 不是模式的固有屬性。mode 117 設 `vmax 7280` 就是 29.97003(0 ppm),`hmax` 不動所以捲簾不變 |
| **畫布** | `0xC043A19C`,在 `FUN_c043a158` 裡 | `r4+0x5C` 的 geometry record,在組好之後、任何推導之前寫。八個欄位、兩層:allocator 從 base 算 RAW buffer,尺寸 getter 讀 override |
| **Producer** | profile 122 的 RWZM 欄 | `0x640` 是 1.5625× 的縮小,把有效區釘在 1936 寬。改成 unity `0x400` 才放開 |
| **快門角度** | 四個呼叫 `FUN_c032c750` 的本地位置 | 原廠換算跟著借用的感光元件模式幀率,而不是選定的輸出幀率。窄守衛 wrapper 只在精確 OG3K timing tuple 下代入所選 nominal FPS;快門速度模式與未知狀態維持原廠 |

### 補丁清單

只寫 RAM。移除 AutoRun 並完整斷電重開就回到原廠;全程沒有任何東西寫進 flash。

```
0xC0B59A28  0x00041C70   mode 117 vmax 2184 → 7280        原值 0x00040888
0xC0BE5888  0x00000075   picker 表1 idx7,106 → 117        原值 0x0000006A
0xC0BE5A28  0x00000075   picker 表2 idx7
0xC0BE5BC8  0x00000075   picker 表3 idx7
0xC0BD9A34  0x00000400   profile 122 live   RWZM H        原值 0x00000640
0xC0BE1684  0x00000400   profile 122 record RWZM H
0xC0BD9EFC  0x00000400   profile 122 live   RWZM V
0xC0BE1B4C  0x00000400   profile 122 record RWZM V
0xC072F800  232 bytes    幾何 hook 的 payload
0xC043A19C  0xEB0BD597   最後才武裝;原指令是 0xE1A00004(mov r0, r4)
```

v0.2.1a 另外把 `0xC02092CC`、`0xC0218AEC`、`0xC0219260`、`0xC03AA568`
四個本地快門角度 callsite 導向同一個有守衛的 wrapper。stage-2 loader 先放完
全部 section,再 clean/invalidate D-cache 並 invalidate 整個 I-cache 才執行,
避免 CPU 已取出的原廠指令遮住剛裝上的 hook。

Hook 的條件寫在 record 自己的內容上(`base == 1936×1090`),不是寫在選擇器上 ——
所以不管某次錄影走哪一條路都會命中,而其他 profile 一概不動。

建置與雜湊在 [`opengate/`](../opengate/)。

### 已知限制

- **僅限韌體 Ver.5.02。** AutoRun 語言沒有執行期的版本守衛。
- **從 v0.2.0test 延續的 CINE 原生 UI 可用。** Settings 收合摘要、三列選單、
  QS 大小 OG3K 值、游標與 UHD/FHD/OG3K 三選項底欄都已在相機上看見正常運作。
- **v0.2.1a 是 alpha 快門角度修正。** 使用者完整斷電冷開機後,29.97p/180°
  的 FHD 與 OG3K idle 曝光取得暫定目視一致,沒有精確 shell 讀值;其他幀率
  尚未做相同 idle live-view 實測,不能宣稱八個幀率皆已通過硬體驗證。
- **UI 錄影回歸刻意很短。** full UI runtime 常駐時,FHD 通過 1 次,
  UHD 與 OG3K 各通過 3 次;因手邊 SD 卡太慢,UHD/OG3K 都在約一秒停止。
  先前有一次 OG3K 凍結,之後未重現。快速媒體長時間錄影、新 UI runtime
  的回放與非啟用 screen/style variants 尚未驗證。
- 真正出貨的是 no-shell 形式;710 筆 OpenGate 與 UI sections 已逐字證明等同
  實機測過的 debug 形式,但這對 no-shell 檔案本身尚未另做一次冷開機實測。
- hook 的酬載佔 `0xC072F800–0xC072F8E8`、遙測佔 `0xC072FA00–0xC072FA0F`,
  跟主機工具的暫存區相撞。armed 的時候 `mem get`/`mem set` 沒問題,但
  `getfile.py`、`putfile.py`、`inject.py`、`callfn.py` 不行。

> live view 閃爍、機內回放不正常、沒有獨立選單 —— 這三條在 2026-09-13 之前是限制,
> 現在不是了。live view 在待機、半按、錄影三個狀態都驗證正確(錄影期對比待機:
> 兩軸都 1.000×、異向比 1.0000、相關 0.9787);回放由 `og3kcanvas.S` 修好
> ——一個 hook 兩個 case——並在 A001_037 的暫停與播放中都驗證過。

### 已排除的

跟做成的東西一樣值錢,因為其中大部分各花掉一整晚。

| 候選 | 判定 |
|---|---|
| 設定 block —— 三對寬高 × 三份複本 | 全部是輸出。整場錄影維持 3032×2012 而 DNG 不變 |
| `MenuItemMovieRecSize` / `StillImageSize` / `HdmiOutputFormat` | 餵那三對的三張表。全部在控制中,而且沒有一個決定 DNG |
| `0xC37CE210` | 反映幾何,不決定幾何 —— 它是 `{0,0,0}` 的那次錄影照樣產出 1936×1090 |
| `0xC096F588` | CinemaDNG 畫格尺寸表。根本不在這條資料流上 |
| CINE 選單表 `0xC0B51044` | 改被選中的那一列沒有任何反應 |
| `setting set` | 寫的鏡像沒人讀:一個驗證會通過、實際什麼都沒改的設定 |

### 保留的訂正

- **`+0x48` 從來就不是那個 tell。** 它在 FHD 和 UHD 都是 0。拿 0/4 的是 `+0x08`,
  而且跟著**幀率**走。早期那個 diff 同時動了解析度和幀率,兩個變因混在一起。
- **「DNG 尺寸 = 設定 block +16/+10」是相關不是因果。** block 整場錄影維持 3032×2012,
  DNG 仍是 1936×1090。
- **`+0x1A0` 的觀察者根本不用找。** 列舉 →(寬,高)的轉換是一張表,就在屬性自己的
  中繼資料裡,找到名稱字串讀後面就有。
- **`*(0xC375D840 + 8)` 讀到「175 和 3」不是壞掉的模式 id。** 175 是 FieldAngle 的選擇器。
- **RWZM 不只是數位變焦。** 早期有一輪在即時取景測完就把它排除了,
  但即時取景的 base 等於感光元件,整個階段是退化的。在錄影路徑上 `0x640`
  是實實在在的 1.5625× 縮小,而 unity 正是讓 producer 填滿畫面的那一步。
- **1080p29.97 是 mode 106,捲簾 10.556 ms** —— picker 的 29.97 格填的是 106,
  而 mode 111 三張表裡都不存在。這關掉了 sensor lab 最後一項未解,
  也補上了 gyro 鏡頭 profile 缺的那個數字。

### 怎麼問相機

- **不碰相機也能問選擇器。** `FUN_c0437078` 是設定的純函數。寫一個 stub 帶**自己的**
  設定 block 複本去呼叫它,就能拿到整張「設定 → 模式」對照表,而且什麼都不用錄。
  花一次實錄之前先用這個驗證補丁。
- `imager mode_list` —— 感光元件自己的 70 筆表,比任何從映像推的都可靠。
  `imager mode_now` 看目前的。
- `menu <SetterName>` 不帶參數是 **getter**。
- `FUN_c0321028(obj, mode)` 拿某個模式的幾何,`FUN_c0320FC8` 拿時序。
  捲簾 = `hmax × 高 ÷ 72` µs。
- 錄完 `0xC343B590` 是剛才用的模式 —— 但要**立刻**讀,相機之後還會再切一次。

### 不要做的

- **不要在 `FUN_c03212e0` 掛 hook。** 拍照時跑十次都沒事,按下錄影的瞬間就凍結。
  原因從來沒查明。
- **hook 裡不要讀過結構已知的範圍。** 有一版從 0x104 的 record 倒 0x140 bytes,
  整台從 USB 消失 —— 活路徑上的 data abort,而 shell task 正握著 dispatcher。

---

**Notes / 相關筆記:** `FRAME_RATE_IS_VMAX`, `CANVAS_IS_NOT_THE_SETTINGS_BLOCK`,
`CANVAS_MOVED_AT_C043A19C`

---

**探索過程的封存**:`../projects/open-gate/notes/OPEN_GATE_EXPLORATION_ARCHIVE.md` 是 2026-09-10 的版本,
留著「怎麼找到答案」—— 模式如何被設定、直接問選擇器的回答、畫布的逐步排除、
3K 路線為何不便宜、已關閉的線索。它的狀態宣告已過時,只拿來查過程。
