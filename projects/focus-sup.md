# focus sup

[English](#english) | [繁體中文](#繁體中文)

DFD, the focus model, lens control and external follow focus.
**Status: the camera's AF is decompiled in depth; the collector and the external
AF are not built**

DFD、焦點模型、鏡頭控制與外部追焦。
**狀態:相機的 AF 已深度反編譯;收集器與外部 AF 尚未實作**

---

## English

### Goal

Understand fp's focus system well enough to rebuild it outside the camera: read
the focus state, drive focus, compute depth ourselves, and eventually run an
autofocus that is better than the camera's for the shots we care about.

### How the camera's AF actually works

Contrast-detect, but with several ideas that are what make it usable rather than
slow:

- **Multi-band high-pass filtering.** A coarse band decides direction and keeps
  the search from getting lost; a fine band finds the sharp peak. Two numbers,
  readable live: `saf_jdat_h` at `0xC32985E8` and `saf_jdat_l` at `0xC32986B4`
- **Defocus-per-pulse prediction** — the part that makes contrast AF fast. Each
  lens is calibrated with a `DefocusPerPulse` table (thin/max/min/ave/now). From
  the contrast curve's slope and how fast that slope is decaying, the firmware
  estimates how much defocus is left and divides by `DefocusPerPulse` to get a
  pulse count. It does not step and re-measure — it computes the move.
  `CalcCafDriveSpeed`, `CalcPdCafDriveDir`, `CafMode5_CalcDrivePulse`. The result
  is clipped so it cannot run into an end stop
- **Three-point parabolic interpolation** to recover the true peak after passing
  it — this is what sets final sharpness
- **The metric is normalised against exposure** (gain, shutter, f-number),
  otherwise the slope is polluted by AE changes rather than by focus
- **Speed planning** — slow down near the peak, so it is both fast and accurate
- **Overshoot then come back**, with backlash compensation
- **AF-C** adds subject-movement detection, motion prediction, and a buffer of
  previous positions

If you are writing your own AF, the notes rank these by value for effort:
multi-band HPF first, then parabolic interpolation, then exposure normalisation,
then defocus prediction, then speed planning.

### Face, eye and subject tracking

A three-stage pipeline, all decompiled: the detection engine, the result
structure, and the face/eye selection priority. Subject tracking (AAT) has a
colour back end in use and a histogram back end that is present but disabled. The
selected box is converted into the AF evaluation region as `xs/xe/ys/ye` and fed
to the drive state machine.

### Prior work: focus-ai, and what it ran into

[`focus-ai/`](https://github.com/ijigen/sigma-fp-bridge/tree/main/focus-ai) in
sigma-fp-bridge drove focus from the host using face width in frame, defocus
blur, and linear prediction against a measured 135 ms image latency. It learned
the lens's face-width to focus-position curve during use, with no calibration
step. It is unmaintained, and its
[FINDINGS](https://github.com/ijigen/sigma-fp-bridge/blob/main/focus-ai/FINDINGS.md)
are worth reading before anyone tries the same thing:

- **No optical direction cue exists on these lenses.** Axial chromatic aberration
  measured 0.1–0.6 units of R/G/B peak separation against a 25–40 unit sample
  spacing on the 45mm and 28mm F1.4. Spherical aberration and astigmatism came
  out symmetric around the peak (±129/±121, ±229/±221). **A single frame cannot
  tell front focus from back focus.** Correlations that appear on natural scenes
  are scene structure, not lens behaviour
- **Face width is a weak signal.** 0.75% variance, degrading 9% on a 30–45° head
  turn against a predicted 20% cosine correction, and geometry magnifies 1.3 px
  of detection noise into about 10 units of focus error
- **The defocus curve's shape is subject-dependent** — half-width ranges 500–1400
  units — so no choice of sharpness metric fixes it
- **The latency is two things, not one.** 135 ms of image acquisition plus a
  speed-dependent command lead, because the camera reports the commanded position
  rather than the actual one. At 8500 units/s the total compensation is 345 ms.
  Four earlier scan-based estimates agreed with each other only because they
  shared the same confound
- **It stopped at recording.** Focus commands sent through tethering are silently
  ignored once recording starts, and live view drops to 640×360, which the
  face-width geometry reads as the subject retreating threefold

### What the firmware offers that a host-side loop cannot get

The findings above are limits of *what the host can see through live view*. Most
of them are not limits of the camera:

- **Direction does not have to come from one frame.** The camera's own AF gets it
  from the contrast curve's slope and how fast that slope is decaying, and its
  coarse band exists specifically to decide direction. Two samples, not one frame
- **The sharpness metric is available at source.** `saf_jdat_h` and `saf_jdat_l`
  are produced by the SIG engine from full-resolution Bayer, not by running
  Tenengrad on a downscaled MJPEG — and they survive recording, because the AF
  statistics engine keeps running
- **Per-lens defocus calibration already exists.** `DefocusPerPulse` is what turns
  "how far off am I" into "how many pulses", which is the step focus-ai had to
  learn empirically per lens
- **Position and distance convert exactly**, through the lens's own support points
  interpolated in reciprocal distance
- **Recording refuses focus in the handler, not in PTP** — the gate is
  `captureState[0x220] == 0 && [0x7c] == 0`. That is why tethered focus commands
  vanish during recording, and it is a firmware condition rather than a protocol
  one
- **GIMBAL reads absolute position** (`0x9405`) while only being able to drive
  relative (`0x9411`), so closed-loop absolute positioning is possible.
  **Whether that readback is the actual position or the commanded one is not
  verified** — and given the command-lead finding above, it is the first thing to
  check

### Focus position and distance

- **The conversion is linear in reciprocal distance.** A lens supplies calibrated
  support points of position against distance; the firmware converts distance to
  `1/distance` and interpolates piecewise-linearly there, because focus position
  is close to linear against `1/distance` and strongly non-linear against distance
  itself. Source: `FUN_c033e0d8` (`LmountFocusL::v21`) and `FUN_c04d0a20`
- **There is one absolute position domain**, a singleton at `0xC347FA6C`.
  **PTP gives the two endpoints** of that domain, min and max.
  **GIMBAL can only drive relative** (`0x9411 ExecRelativeFocusDriving`) — but it
  **can read the current absolute position** (`0x9405 GIMBAL_GetFocusPosition`),
  in the same domain as PTP's min/max. So absolute positioning through GIMBAL is
  possible as a closed loop: read, compute, drive relative, read again

### Lens data

- The firmware's own API reads it: borrow `FUN_c03554a0` and
  `FUN_c0355de0`/CmdRead. They take the bus mutex, so they can only be called from
  task context, never from an interrupt. Block ids index the ROM table at
  `0xC0B94364`
- A LUMIX lens carries no SIGMA DFD blocks but has its own tables at `0x001500`
- Code: [`focus/lens/`](../focus/lens/)
- **The lens-data program is verified end to end** — create `\LENS`, read blocks
  0x2d and 0x0a, parse focal length and minimum focus distance, sanitise the file
  name, write, and read the file back to confirm

### DFD without extracting frames

AF-C consumes green-channel high-frequency energy produced by the SIG engine at
`0x30050000`, and the two-band metric above is readable live. So a DFD collector
is sweep focus + read the stats + read mposm — **no Bayer frame extraction
needed**. The green AF band already streams at 0.125 ms/frame with no stall.
**Method, addresses and code: [`focus/dfd/`](../focus/dfd/).**

### Phase detection — read, but never verifiable here

The firmware carries a **complete phase-detect drive path**, decompiled in
detail: `CalcCafDriveSpeed`, the phase-to-pulse conversion, the `pkcnt`
accumulation with its stability predicate, and the near-peak deceleration.

**On this body it is dead code.** The AF-model subclass vtable's slot `0x184`
returns 0 unconditionally, and the only call site to `CalcCafDriveSpeed` is
guarded by exactly that — so it never runs. The same gate also disables the
`pkcnt` writes, the PdCaf setup, and the PDAF availability check, and
`measured_defocus` stays at its `-0x80000000` sentinel forever.

So the algorithm can be read but nothing about it can be exercised, measured or
falsified. Every claim in that part of the notes is static analysis with no path
to a hardware check.

There is also an unresolved contradiction worth flagging: one note states that
neither the IMX410 nor the IMX455 has on-chip phase detection, while the drive
path exists in the firmware in full, with per-lens scaling and reliability
inputs. Which body actually feeds it is not established here.

**If you want phase-detect research to happen, sponsor an fp L.** That is the
honest position: the code is understood, and the hardware to test it against is
the missing piece.

### Open

- **Focus is refused while recording** — and it is the handler that refuses, not
  PTP. It only drives when `captureState[0x220] == 0 && [0x7c] == 0`
- The DFD collector itself is not written
- An external AF loop, using the readable metric plus the reciprocal-distance
  model, has not been attempted

---

## 繁體中文

### 目標

理解 fp 的對焦系統到足以在外部重建它:讀得到焦點狀態、驅動得了對焦、自己算得出景深,
最終目標是在我們在意的拍攝情境下,跑一個比相機本身更好的自動對焦。

### 相機的 AF 實際上怎麼運作

是對比偵測,但有幾招才是讓它「能用」而不是「很慢」的關鍵:

- **多頻帶高通濾波** —— 粗頻帶判方向、防止搜尋迷路;細頻帶找銳峰。
  兩個值都能即時讀:`saf_jdat_h` `0xC32985E8`、`saf_jdat_l` `0xC32986B4`
- **每脈衝離焦量預測** —— 讓對比式 AF 快起來的核心。每顆鏡頭標定一張 `DefocusPerPulse`
  表(thin/max/min/ave/now)。韌體由**對比曲線斜率**與**斜率遞減率**估出「現在還離峰多遠」,
  除以 `DefocusPerPulse` 就直接得到要驅動幾個脈衝 —— **它不是一步步試,是算出來的**。
  函式 `CalcCafDriveSpeed`、`CalcPdCafDriveDir`、`CafMode5_CalcDrivePulse`。
  驅動量會夾限,避免衝過頭撞端點
- **三點拋物線峰值內插** —— 越過峰值後回推真正的合焦位置,最終銳利度由它決定
- **評價值對曝光正規化**(gain / shutter / f-number)—— 否則斜率會被 AE 變化污染,
  而不是被對焦污染
- **速度規劃** —— 近峰減速,兼顧快與準
- **越峰才停 + backlash 回驅補償**
- **AF-C** 另加主體移動判定、運動預測、前幀位置緩衝

如果要自製 AF,筆記依「CP 值」排序:先做多頻帶 HPF,再做拋物線內插,再做曝光正規化,
然後才是離焦量預測與速度規劃。

### 人臉、眼睛與主體追蹤

三段式管線全部反編譯完成:偵測引擎、結果資料結構、選臉/選眼優先權。
主體追蹤(AAT)有色彩後端(使用中)與直方圖後端(存在但停用)。
選中的框會轉換成 AF 評價區的 `xs/xe/ys/ye`,再餵給驅動狀態機。

### 先前的嘗試:focus-ai,以及它撞到什麼

sigma-fp-bridge 裡的
[`focus-ai/`](https://github.com/ijigen/sigma-fp-bridge/tree/main/focus-ai)
在主機端驅動對焦,用的是**畫面中的臉寬**、**離焦模糊**,以及針對量到的 135 ms 影像延遲做**線性預測**。
它在使用過程中自己學鏡頭的「臉寬 ↔ 對焦位置」曲線,不需要校正步驟。
該專案已停止維護,而它的
[FINDINGS](https://github.com/ijigen/sigma-fp-bridge/blob/main/focus-ai/FINDINGS.md)
值得任何想再做一次的人先看:

- **這些鏡頭上不存在光學方向線索。** 軸向色差在 45mm 與 28mm F1.4 上量到的 R/G/B 峰值分離
  只有 0.1–0.6 單位,而取樣間距是 25–40 單位。球差與像散在峰值兩側對稱
  (±129/±121、±229/±221)。**單一影格分不出前焦後焦。**
  自然場景上出現的相關性是場景結構造成的,不是鏡頭特性
- **臉寬是弱訊號。** 變異數 0.75%;頭轉 30–45° 時只縮 9%,而餘弦修正預測是 20%;
  而且幾何會把 1.3 px 的偵測雜訊放大成約 10 單位的對焦誤差
- **離焦曲線的形狀跟主體有關** —— 半寬從 500 到 1400 單位 —— 所以換任何銳利度指標都救不了
- **延遲是兩件事,不是一件。** 135 ms 的影像取得延遲,加上**隨速度變化的指令領先**,
  因為相機回報的是**指令位置而不是實際位置**。在 8500 單位/秒時總補償是 345 ms。
  先前四個掃描法的估計會互相吻合,只是因為它們共用同一個混淆
- **它卡在錄影。** 一旦開始錄影,透過 tethering 送的對焦指令會被**靜默忽略**,
  而且 live view 掉到 640×360,臉寬幾何會把那讀成「主體一秒內退後三倍」

### 韌體能提供、而主機端迴圈拿不到的東西

上面那些是**「主機透過 live view 能看到什麼」的限制**,大部分不是相機本身的限制:

- **方向不必從單一影格取得。** 相機自己的 AF 是從對比曲線的**斜率**與**斜率遞減率**得到方向,
  而且它的粗頻帶的存在目的就是判方向。那是兩個取樣點,不是一張影格
- **銳利度指標可以從源頭拿。** `saf_jdat_h` / `saf_jdat_l` 是 SIG 引擎用**全解析度 Bayer**
  算出來的,不是在縮小過的 MJPEG 上跑 Tenengrad —— 而且**錄影時它們照樣在跑**
- **每顆鏡頭的離焦校準本來就存在。** `DefocusPerPulse` 就是把「還差多少」換成「要走幾步」的那張表,
  正是 focus-ai 得靠經驗逐鏡頭學的東西
- **位置與距離可以精確換算** —— 用鏡頭自己的支撐點,在倒數距離空間內插
- **錄影中拒絕對焦是 handler 擋的,不是 PTP 的限制** —— 閘門是
  `captureState[0x220] == 0 && [0x7c] == 0`。這就是 tethered 對焦指令在錄影時消失的原因,
  而它是韌體條件,不是協定限制
- **GIMBAL 讀得到絕對位置**(`0x9405`),雖然只能相對驅動(`0x9411`),
  所以閉迴路絕對定位是可行的。**但那個回讀是實際位置還是指令位置,尚未驗證** ——
  考慮到上面那條「指令領先」的發現,這是最該先查的一件事

### 對焦位置與距離

- **換算是在「倒數距離」空間做線性內插。** 鏡頭提供一組「位置 ↔ 距離」的校準支撐點,
  韌體先把距離取倒數,在 `位置 ↔ 1/距離` 之間做分段線性內插 ——
  因為對焦位置對 `1/距離` 接近線性,對「距離」本身則強烈非線性。
  來源:`FUN_c033e0d8`(`LmountFocusL::v21`)與 `FUN_c04d0a20`
- **存在單一絕對位置域**,singleton 在 `0xC347FA6C`。
  **PTP 給的是那個域的兩個端點**(min / max)。
  **GIMBAL 只能相對驅動**(`0x9411 ExecRelativeFocusDriving`),
  但**讀得到目前的絕對位置**(`0x9405 GIMBAL_GetFocusPosition`),而且與 PTP 的 min/max 同域。
  所以用 GIMBAL 做絕對定位是可行的,做成閉迴路:讀 → 算 → 相對驅動 → 再讀

### 鏡頭資料

- 走韌體自己的 API:借 `FUN_c03554a0` + `FUN_c0355de0`/CmdRead。
  它們會拿匯流排 mutex,所以只能在任務脈絡呼叫,不能在中斷裡。
  block id 索引 ROM 表 `0xC0B94364`
- LUMIX 鏡頭沒有 SIGMA 的 DFD 區塊,但自己有一組表在 `0x001500`
- 程式在 [`focus/lens/`](../focus/lens/)
- **鏡頭資料程式已端到端驗證** —— 建立 `\LENS` 目錄、讀 block 0x2d/0x0a、
  解析焦距與最近對焦距離、檔名淨化、寫檔後回讀確認

### 不用取出影格的 DFD

AF-C 消耗的是 SIG 引擎 `0x30050000` 產生的綠通道高頻能量,而上面那兩個頻帶的值可以即時讀。
所以 DFD 收集器 = 掃焦 + 讀統計 + 讀 mposm,**完全不需要把 Bayer 影格搬出來**。
綠通道 AF band 已經能以 0.125 ms/frame 零 stall 串流。
**方法、位址與程式在 [`focus/dfd/`](../focus/dfd/)。**

### 相位對焦 —— 讀得懂,但在這裡永遠驗證不了

韌體裡有一條**完整的相位偵測驅動路徑**,而且已經被詳細反編譯:
`CalcCafDriveSpeed`、相位到脈衝的換算、帶穩定性判準的 `pkcnt` 累積、近峰減速。

**在這台機身上它是死碼。** AF-model 子類的 vtable slot `0x184` 無條件回 0,
而 `CalcCafDriveSpeed` 唯一的呼叫點前一行檢查的正是它 —— 所以**永不執行**。
同一個閘也關掉了 `pkcnt` 寫入、PdCaf 設定與 PDAF 可用性檢查,
`measured_defocus` 因此永遠停在 `-0x80000000` 這個 sentinel。

所以那套演算法讀得懂,但**沒有任何一項能被執行、量測或推翻**。
筆記裡那一段的每一條主張都是純靜態分析,沒有通往實機驗證的路。

另外有一個尚未解決的矛盾值得標出來:一份筆記寫著 IMX410 與 IMX455 **都沒有**片上相位對焦,
但韌體裡那條驅動路徑卻完整存在,還帶著逐鏡頭的縮放係數與可靠度輸入。
到底是哪一台機身在餵它,這裡沒有定論。

**想要相位對焦的研究,請贊助我一台 fp L。** 這是誠實的說法:
程式碼已經讀懂了,缺的是能拿來對照驗證的硬體。

### 未解

- **錄影中對焦被拒絕** —— 而且是 handler 自己擋的,不是 PTP 的限制。
  它只在 `captureState[0x220]==0 && [0x7c]==0` 才驅動
- DFD 收集器本身還沒寫
- 用「可讀的評價值 + 倒數距離模型」在外部跑一個 AF 迴路,還沒試過

---

**Notes / 相關筆記:** `AF_DESIGN_REFERENCE`, `AF_COMPLETE`, `AF_AE_INTERNALS`,
`AF_LIVE_STATE_MAP`, `AUTOFOCUS`, `FACE_EYE_AF`, `DFD_VIA_AF_STATS`,
`FOCUS_DISTANCE_PRINCIPLE`, `FOCUS_POSITION_DOMAIN`, `LENS_BLOCK_API`,
`LENS_DATA_ACCESS`, `LENS_CALIBRATION`, `DISTCONVERTER_MATH`
