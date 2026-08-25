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
- **The lens-data program is verified end to end** — create `\LENS`, read blocks
  0x2d and 0x0a, parse focal length and minimum focus distance, sanitise the file
  name, write, and read the file back to confirm

### DFD without extracting frames

AF-C consumes green-channel high-frequency energy produced by the SIG engine at
`0x30050000`, and the two-band metric above is readable live. So a DFD collector
is sweep focus + read the stats + read mposm — **no Bayer frame extraction
needed**. The green AF band already streams at 0.125 ms/frame with no stall
(`dfd_live.py`).

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
- **鏡頭資料程式已端到端驗證** —— 建立 `\LENS` 目錄、讀 block 0x2d/0x0a、
  解析焦距與最近對焦距離、檔名淨化、寫檔後回讀確認

### 不用取出影格的 DFD

AF-C 消耗的是 SIG 引擎 `0x30050000` 產生的綠通道高頻能量,而上面那兩個頻帶的值可以即時讀。
所以 DFD 收集器 = 掃焦 + 讀統計 + 讀 mposm,**完全不需要把 Bayer 影格搬出來**。
綠通道 AF band 已經能以 0.125 ms/frame 零 stall 串流(`dfd_live.py`)。

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
