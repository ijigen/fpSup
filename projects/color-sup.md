# color sup

[English](#english) | [繁體中文](#繁體中文)

Colour science and the DaVinci workflow.
**Status: paused — the research holds, the deliverable does not**

色彩科學與 DaVinci 工作流。**狀態:暫停 —— 研究成立,但交付物不成立**

---

## English

### Goal

Reproduce the fp's in-camera colour in post, so CinemaDNG footage matches what the
camera's own JPEG looks like.

### Proven

- **fp's colour science is fully decompiled** — the whole pipeline from sensor
  output to final colour
- **A DCTL exists that reproduces the Standard colour mode** in-pipeline inside a
  DWG/sRGB grade. The anchor constant is `k = 2.124`
- **The decode colour space turns out not to matter**, which is unintuitive but
  measured, and it removes a whole category of things not to try

### Why it is paused

The DCTL works but is **awkward to actually use**, and there is nothing packaged
that could be released — no file here is in a state where handing it to someone
would help them. Reproducing a colour and shipping a colour tool are not the same
job, and only the first one is done.

Whatever specifically makes it awkward in a real grade has not been written down.
That is the first thing to record when this is picked up again, because it is the
part that decides what the deliverable should even be.

### Not done

- Anything that could be released
- Colour modes other than Standard — Vivid, Neutral, Portrait, Monochrome
- In-camera effects such as Teal & Orange
- How colour mode interacts with ISO and gain

---

## 繁體中文

### 目標

在後製軟體裡重現 fp 機內的色彩表現,讓 CinemaDNG 素材能對得上機內 JPEG 的觀感。

### 已確認

- **fp 的色彩科學已完整反編譯** —— 從感光元件輸出到最終色彩的整條管線
- **有一支 DCTL 能重現 Standard 色彩模式**,在 DWG／sRGB 調色流程中以 in-pipeline 方式運作。
  關鍵參數:錨點 `k = 2.124`
- **解碼色彩空間不影響結果** —— 這點反直覺但實測如此,省掉一整類的嘗試

### 為什麼暫停

那支 DCTL 能動,但**實際用起來很難用**,而且沒有任何打包好、能釋出的東西 ——
現在的狀態就算交給別人也幫不上忙。**「重現一個顏色」和「做出一個色彩工具」是兩件事**,
完成的只有第一件。

至於在真實調色流程裡「難用」具體卡在哪,還沒有寫下來。
那是重新撿起這一項時第一件該記錄的事,因為那決定了交付物到底該長什麼樣。

### 未做

- 任何可以釋出的東西
- Standard 以外的色彩模式(Vivid、Neutral、Portrait、Monochrome…)
- Teal & Orange 等機內效果
- 色彩模式與 ISO／增益的交互作用

---

**Notes / 相關筆記:** `COLOR_SCIENCE`, `ISO_DR_UNDERSTANDING`
