# sensor lab sup

[English](#english) | [繁體中文](#繁體中文)

IMX410 modes, ISO, gain and sensor control.
**Status: ISO and gain fully solved, one open item in the mode table**

IMX410 模式、ISO、gain 與 sensor 控制。**狀態:ISO/gain 已完整解出,模式表有一項未解**

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

- **Mode ambiguity** — 1080p29.97 matches mode 106 (hmax 445, vmax 5398, readout
  10.556 ms) and mode 111 (hmax 330, vmax 7280, 7.828 ms) equally well. The
  rolling-shutter times differ substantially; focal length does not.
  **The mode-index field has not been found** — `*(0xC375D840 + 8)` returns 175
  and 3, which are not valid mode ids
- This blocks gyro sup's lens profile: without the rolling-shutter time it cannot
  be completed

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

- **模式歧義** —— 1080p29.97 同時符合模式 106(hmax 445 / vmax 5398 / 讀出 10.556 ms)
  與模式 111(hmax 330 / vmax 7280 / 7.828 ms)。捲簾時間差一截,但焦距不受影響。
  **模式索引欄位還沒找到**(`*(0xC375D840+8)` 讀到 175 和 3,不是有效的模式 id)
- 這一項擋著 gyro sup 的鏡頭 profile —— 沒有捲簾時間就填不完整

---

**Notes / 相關筆記:** `ISO_FIRMWARE_COMPLETE`, `ISO_HANDLING`, `ISO_DR_UNDERSTANDING`,
`COLOR_SCIENCE`
