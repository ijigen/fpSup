# DFD — depth from defocus, without extracting a single frame

[English](#english) | [繁體中文](#繁體中文)

Part of [focus sup](../../projects/focus-sup.md).

---

## English

### The finding this rests on

Depth-from-defocus needs a sharpness-versus-focus curve. The obvious way to get
one is to pull Bayer frames out of the camera and compute sharpness on the host,
which on the fp is hard and, it turns out, unnecessary.

**The camera already computes it, in hardware, on the Bayer green channel.**
AF-C's statistics engine at `0x30050000` taps the raw stream *before* debayer,
picks the green channel, runs it through an IIR high-pass bank, and accumulates
high-frequency energy per ROI in two bands. The results land in ordinary readable
cells.

So the collector becomes **sweep focus, read the statistics, read the encoder
position** — no frame extraction, no recording, no decode.

### Why it is certainly Bayer and not developed YUV

The registers only make sense before debayer:

- `GAF_ID` / `GAFPICK` at `0x30050440` carry a **2-bit CFA position field** —
  "pick one of four mosaic positions" is a concept that does not exist after
  debayer
- `gain_af_RGB` at `0x30050464` applies digital gain **per Bayer channel**
- `AF_Y_SEL` at `0x30050450` bit 0 chooses between a luma computed *from the CFA*
  and a straight green pick — raw-domain either way
- The block never reads a developed YUV frame buffer. The pipeline is
  `SIG0 → SIG1 RAWOUT → PRE_TOP CSEP`, and the AF/AE statistics tap sits in the
  SIG raw cluster, before CSEP

### The signals

Readable directly — no firmware call, no recording, no freeze risk.

| value | address | meaning |
|---|---|---|
| `saf_jdat_h[]` | `0xC32985E8` | per-ROI **high band** HF energy (bandval − scanmin, order 1e4) |
| `saf_jdat_l[]` | `0xC32986B4` | per-ROI **low band** HF energy |
| `mposm` | `0xC3291958` | **focus position in encoder pulses** — the x axis |
| peak now / max / min | `0xC32915C4` / `C8` / `CC` | peak tracking |
| target / `g_afpos` | `0xC32915B0` / `0xC32914E0` | focus target and position |

Resolution is per-ROI, not per-frame: the window geometry at `0x30050010` caps at
1023, over a downsampled Bayer-green grid, at most 256 accumulated lines per
region. It updates once per CAF evaluation frame — roughly 17 ms or 33 ms
depending on the divisor.

### The procedure

```
for each focus position in the sweep:
    drive focus, or rack it by hand
    read mposm            0xC3291958      encoder pulses
    read saf_jdat_h[roi]  0xC32985E8      high band
    read saf_jdat_l[roi]  0xC32986B4      low band
    record {mposm, h, l}

→ a sharpness-versus-pulse curve per ROI
→ fit a Lorentzian  F(z) = A / (1 + ((z − z_p)/w)²) + B
→ peak z_p is focus, width w is the defocus, and from that, depth
```

### Two things about the fit

**The curve is Lorentzian, not parabolic** — measured R² of 0.983 to 0.997 across
distances, with the value at `u = ±1` sitting at 0.44 to 0.52. Its shape is set by
optics and only its width moves with defocus, so there is one unknown to solve.

**Keep the x axis in encoder pulses.** Width expressed in pulses varies only 1.44×
across a 5.6× change in distance, which is why `mposm` is the right axis and
converting to µm or metres first is not.

### Two traps

**The band ratio `E_high / E_low` is monotonic, not peak-stable.** On a badly
defocused distant subject the high band decays to noise — a flat spectrum — so the
ratio climbs and the apparent peak walks away. Subtract the noise floor before
taking any ratio. Two bands are available precisely so this can be done.

**Widths measured elsewhere do not transfer.** Comparable work measured HDMI YUV
after development, so with sharpening and noise reduction applied. These
statistics are raw-domain Bayer green with neither. The structural conclusions
carry over; the absolute widths need recalibrating. This source is the cleaner of
the two.

### What this engine does not give you

Filtered high-frequency energy — edges and contrast — not raw Bayer pixels. If a
custom DFD kernel over actual pixels is wanted, that is the separate and much
harder Bayer DMA path. But if what is wanted is a Bayer-domain sharpness signal,
the camera has already computed it.

### Address index

| item | address |
|---|---|
| AF statistics engine | `0x30050000` (`af_common.cpp`) |
| `GAFPICK` / `GAF_ID`, 2-bit CFA pick | `0x30050440`, setter `FUN_c0636ff8` |
| `gain_af_RGB`, per-Bayer gain | `0x30050464`, `FUN_c0637138` |
| `AF_Y_SEL` | `0x30050450` bit 0, `FUN_c0637020` |
| HPF banks, high / low | `0x30050220-238` / `0x30050260-278` |
| per-frame read | `FUN_c023e1a0`, slots 0/1/5, `memcpy` 0x400 |
| descriptor table, buffer pointer at `+0xC` | `0xC340474C` |
| band write / span | `FUN_c023e9d0` / `FUN_c023ec28` |
| AE metering sibling block | `0x30058000` |

### The code here

| file | what it is |
|---|---|
| `push_green.S` | camera side: arm the endpoint straight at the live green band buffer, zero copy |
| `push_n.S` | camera side: push N frames |
| `dfd_live.py` | host side: a live plot of the band profile against `mposm` |
| `HOOKPUSH.md` | how the transport was measured — 0.125 ms per frame, about 680× a host pull |

**These target the old endpoint** (`0xC31E3274`, `StartTransfer(9)`), which the
current gadget does not have. On [fp USB Shell v2](../../fp_usb_shell/) they
become `0xC31E3270` and `StartTransfer(7)`, and the entry point moves from the
retired worker `call` command to
[`camera/oneshot.S`](../../fp_usb_shell/camera/oneshot.S). Nothing else changes.

---

## 繁體中文

### 這件事建立在一個發現上

DFD 需要一條「銳度 vs 對焦位置」的曲線。最直覺的取得方式是把 Bayer 幀從相機拉出來、
在主機端算銳度 —— 在 fp 上那很難,而且結果證明**沒有必要**。

**相機已經在硬體裡算好了,而且是對 Bayer 綠通道算的。**
AF-C 的統計引擎 `0x30050000` 在 **debayer 之前**接上 raw 流,挑出綠通道,
過 IIR 高通濾波器組,再**逐 ROI 累加兩個頻帶的高頻能量**。結果就落在一般可讀的位址裡。

所以收集器變成**掃焦 + 讀統計 + 讀編碼器位置** —— 不抽幀、不錄影、不解碼。

### 為什麼確定是 Bayer 而不是 developed YUV

那些暫存器只有在 debayer 之前才有意義:

- `0x30050440` 的 `GAF_ID` / `GAFPICK` 帶著 **2-bit 的 CFA 位置欄位** ——
  「從四個 mosaic 位置挑一個」這個概念在 debayer 之後根本不存在
- `0x30050464` 的 `gain_af_RGB` 是**逐 Bayer 通道**施加數位增益
- `0x30050450` bit 0 的 `AF_Y_SEL` 在「**從 CFA 算出來的** luma」與「直接挑綠」之間選,
  兩者都在 raw domain
- 這個區塊從不讀 developed YUV frame buffer。管線是
  `SIG0 → SIG1 RAWOUT → PRE_TOP CSEP`,而 AF/AE 統計的 tap 在 SIG raw cluster、CSEP 之前

### 訊號

可直接讀 —— 不需要呼叫韌體、不需要錄影、沒有凍結風險。

| 值 | 位址 | 意義 |
|---|---|---|
| `saf_jdat_h[]` | `0xC32985E8` | 逐 ROI 的**高頻帶** HF 能量(bandval − scanmin,約 1e4 量級) |
| `saf_jdat_l[]` | `0xC32986B4` | 逐 ROI 的**低頻帶** HF 能量 |
| `mposm` | `0xC3291958` | **以編碼器脈衝表示的對焦位置** —— 這是 x 軸 |
| peak now / max / min | `0xC32915C4` / `C8` / `CC` | 峰值追蹤 |
| target / `g_afpos` | `0xC32915B0` / `0xC32914E0` | 對焦目標與位置 |

解析度是逐 ROI 而不是逐幀:`0x30050010` 的窗口幾何上限 1023,
建立在**降採樣的 Bayer 綠格**上,每區最多累加 256 條線。
更新頻率是每個 CAF 評估幀一次,依除數約 17 ms 或 33 ms。

### 流程

```
對掃描範圍中的每個對焦位置:
    驅動對焦,或手動掃
    讀 mposm            0xC3291958      編碼器脈衝
    讀 saf_jdat_h[roi]  0xC32985E8      高頻帶
    讀 saf_jdat_l[roi]  0xC32986B4      低頻帶
    記錄 {mposm, h, l}

→ 每個 ROI 得到一條「銳度 vs 脈衝」曲線
→ 擬合 Lorentzian  F(z) = A / (1 + ((z − z_p)/w)²) + B
→ 峰位 z_p 是合焦,寬度 w 是離焦量,由此得到深度
```

### 關於擬合的兩件事

**那條曲線是 Lorentzian,不是拋物線** —— 跨距離實測 R² 在 0.983 到 0.997,
`u = ±1` 處的值落在 0.44 到 0.52。**形狀由光學決定,只有寬度隨離焦改變**,
所以只有一個未知數要解。

**x 軸要留在編碼器脈衝。** 用脈衝表示的寬度在距離變化 5.6 倍時只變 1.44 倍 ——
這正是 `mposm` 該當 x 軸、而不該先換算成 µm 或公尺的原因。

### 兩個陷阱

**頻帶比 `E_high / E_low` 是單調穩定,不是峰值穩定。**
遠處主體嚴重失焦時,高頻帶會衰減到只剩雜訊(平譜),比值因此爬升,表觀峰值就跑掉了。
**取任何比值之前先扣掉雜訊底。** 有兩個頻帶正是為了做這件事。

**別處量到的寬度不能直接套用。** 可比較的研究量的是 **HDMI 開發後的 YUV**,
帶著銳化與降噪;這裡的統計是 **raw domain 的 Bayer 綠**,兩者都沒有。
結構性結論可以沿用,但**寬度的絕對值要重新標定**。這個來源是兩者中比較乾淨的那個。

### 這顆引擎不會給你的東西

它給的是**濾波後的高頻能量**(邊緣與對比),不是 raw Bayer 像素。
如果要對實際像素跑自訂的 DFD kernel,那是另一條困難得多的 Bayer DMA 路徑。
但如果要的是 **Bayer domain 的銳度訊號**,相機已經算好了。

### 位址索引

| 項目 | 位址 |
|---|---|
| AF 統計引擎 | `0x30050000`(`af_common.cpp`) |
| `GAFPICK` / `GAF_ID`,2-bit CFA pick | `0x30050440`,setter `FUN_c0636ff8` |
| `gain_af_RGB`,逐 Bayer 增益 | `0x30050464`,`FUN_c0637138` |
| `AF_Y_SEL` | `0x30050450` bit 0,`FUN_c0637020` |
| HPF 濾波器組,高 / 低 | `0x30050220-238` / `0x30050260-278` |
| 每幀讀取 | `FUN_c023e1a0`,slot 0/1/5,`memcpy` 0x400 |
| 描述子表,buffer 指標在 `+0xC` | `0xC340474C` |
| band 寫入 / span | `FUN_c023e9d0` / `FUN_c023ec28` |
| AE 測光的姊妹區塊 | `0x30058000` |

### 這裡的程式

| 檔案 | 是什麼 |
|---|---|
| `push_green.S` | 相機端:直接把端點指向即時的綠 band 緩衝,零拷貝 |
| `push_n.S` | 相機端:推 N 幀 |
| `dfd_live.py` | 主機端:即時畫出 band profile 對 `mposm` 的曲線 |
| `HOOKPUSH.md` | 傳輸方式怎麼量的 —— 0.125 ms/幀,約為 host pull 的 680 倍 |

**這些程式指的是舊端點**(`0xC31E3274`、`StartTransfer(9)`),現在的 gadget 沒有那個端點。
在 [fp USB Shell v2](../../fp_usb_shell/) 上要改成 `0xC31E3270` 與 `StartTransfer(7)`,
進入點也要從已退役的 worker `call` 指令改成
[`camera/oneshot.S`](../../fp_usb_shell/camera/oneshot.S)。其餘不變。
