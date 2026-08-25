# color sup

[English](#english) | [繁體中文](#繁體中文)

Colour science and the DaVinci workflow. **Status: shipped**

色彩科學與 DaVinci 工作流。**狀態:已有可用成品**

---

## English

### Goal

Reproduce the fp's in-camera colour in post, so CinemaDNG footage matches what the
camera's own JPEG looks like.

### Proven

- **fp's colour science is fully decompiled** — the whole pipeline from sensor
  output to final colour
- **A working DCTL** reproduces the fp's Standard colour mode in-pipeline inside a
  DWG/sRGB grade
- The anchor constant is `k = 2.124`
- **The decode colour space turns out not to matter**, which is unintuitive but
  measured, and it removes a whole category of things not to try

### Not done

- Colour modes other than Standard — Vivid, Neutral, Portrait, Monochrome
- In-camera effects such as Teal & Orange
- How colour mode interacts with ISO and gain

---

## 繁體中文

### 目標

在後製軟體裡重現 fp 機內的色彩表現,讓 CinemaDNG 素材能對得上機內 JPEG 的觀感。

### 已確認

- **fp 的色彩科學已完整反編譯** —— 從感光元件輸出到最終色彩的整條管線
- **可用的 DCTL** —— 在 DWG／sRGB 調色流程中,以 in-pipeline 的方式重現 fp 的 Standard 色彩模式
- 關鍵參數:錨點 `k = 2.124`
- **解碼色彩空間不影響結果** —— 這點反直覺但實測如此,省掉一整類的嘗試

### 未做

- Standard 以外的色彩模式(Vivid、Neutral、Portrait、Monochrome…)
- Teal & Orange 等機內效果
- 色彩模式與 ISO／增益的交互作用

---

**Notes / 相關筆記:** `COLOR_SCIENCE`, `ISO_DR_UNDERSTANDING`
