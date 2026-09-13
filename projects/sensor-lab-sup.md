# sensor lab sup

[English](#english) | [繁體中文](#繁體中文)

IMX410 modes, ISO, gain and sensor control.
**Status: research complete — ISO and gain fully solved, and the mode-table
ambiguity closed on 2026-09-10**

IMX410 模式、ISO、gain 與 sensor 控制。**狀態:研究完成 —— ISO/gain 已完整解出,模式表的歧義 2026-09-10 已解**

---

## English

### Goal

Work out what the IMX410 actually does in the fp: how ISO maps onto conversion
gain and analog gain, what each sensor mode's parameters are, and which numbers
the firmware confirms versus which are OTP values that still need measuring.

### Proven

- **The ISO and gain chain is fully decompiled** — conversion gain, analog gain,
  analog readout and the ADC stage
- The result is an [interactive explainer](https://ijigen.github.io/fpSup/) in
  English and Traditional Chinese that **separates firmware-confirmed behaviour
  from OTP values that still require measurement**
- Recording geometry at `0xC37CE210` = {1936, 1090, 3244544 bytes per frame}

### Open

> ✅ **Resolved 2026-09-10 — and the mode-index field was never needed.**
> The mode is chosen by a table, so read the table. The picker's three arrays
> (`0xC0BE5810` / `0xC0BE59B0` / `0xC0BE5B50`, 26 entries of 16 bytes, `+0x08`
> the sensor mode) are laid out as *(readout geometry × frame rate)*, and the
> FHD 29.97 slot holds **106**. **Mode 111 does not appear in any of the three.**
> A real take reads 106 back from `0xC343B590`.
>
> **FHD 29.97 CinemaDNG rolling shutter is 10.556 ms.** That is the number gyro
> sup's lens profile was missing. See `notes/FRAME_RATE_IS_VMAX.md`.

---

## 繁體中文

### 目標

搞清楚 IMX410 在 fp 上的實際行為:ISO 怎麼對應到轉換增益與類比增益、
各感光模式的參數,以及哪些是韌體確認的、哪些只是 OTP 值。

### 已確認

- **ISO / 增益鏈完整反編譯** —— 轉換增益、類比增益、類比讀出、ADC 階段都對出來了
- 成果做成了[互動說明頁](https://ijigen.github.io/fpSup/),英文／繁體中文雙語,
  而且**明確區分「韌體已確認」與「仍需實機量測的 OTP 值」**
- 錄影幾何 `0xC37CE210` = {1936, 1090, 每影格 3244544 bytes}

### 未解

> ✅ **2026-09-10 已解 —— 而且根本不需要那個「模式索引欄位」。**
> 模式是由一張表選的,所以去讀那張表。picker 的三個陣列
> (`0xC0BE5810` / `0xC0BE59B0` / `0xC0BE5B50`,26 筆 ×16 bytes,`+0x08` 是感光元件模式)
> 排列成 *(讀出幾何 × 幀率)*,而 **FHD 29.97 那一格填的是 106**;
> **模式 111 在三張表裡都不存在**。實錄後 `0xC343B590` 也讀回 106。
>
> **FHD 29.97 CinemaDNG 的捲簾是 10.556 ms。** 這正是 gyro sup 鏡頭 profile 缺的數字。
> 見 `notes/FRAME_RATE_IS_VMAX.md`。

---

**Notes / 相關筆記:** `ISO_FIRMWARE_COMPLETE`, `ISO_HANDLING`, `ISO_DR_UNDERSTANDING`,
`COLOR_SCIENCE`
