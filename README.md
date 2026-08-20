# fpSup

[English](#english) | [繁體中文](#繁體中文)

SIGMA fp firmware research and tooling — organised as independent sub-projects, one folder each.

---

## English

SIGMA fp firmware research and tooling project. Each development item lives in its own folder.

### Sub-projects

**1. IMX410 ISO / gain explainer** — sensor reverse-engineering results
[Open the interactive explainer](https://ijigen.github.io/fpSup/)
- English / Traditional Chinese interface
- Interactive ISO, conversion-gain, analog-gain, analog-readout, and ADC-stage explanation
- Distinguishes firmware-confirmed behavior from OTP values that still require measurement
- Single-file static page (`index.html`); no build step required

**2. fp USB Shell** — [`fp_usb_shell_sup/`](fp_usb_shell_sup/)
- Run the camera's own firmware shell commands over the USB vendor interface: **`shl <cmd>`** forwards any
  of the 77 firmware shell commands and returns their output (live-verified — `shl display colorbar 1 0`
  turned the camera screen to colorbars over USB)
- `AutoRun.txt` RAM injection (no reflash) + a host daemon (`fpshelld`) + the camera-side worker source
- Includes the full write-up of the "shell freezes the camera" root cause and the remaining structural limit
  (recording while connected still freezes)

---

## 繁體中文

SIGMA fp 韌體研究與工具開發專案。每個開發項目各自放在獨立資料夾。

### 子項目

**1. IMX410 ISO／增益互動說明** —— 傳感器逆向結果
[開啟互動說明頁](https://ijigen.github.io/fpSup/)
- 英文／繁體中文介面
- 互動解說 ISO、轉換增益、類比增益、類比讀出與 ADC 階段
- 區分韌體已確認行為,以及仍需實機量測的 OTP 數值
- 單一靜態 HTML(`index.html`),無須建置步驟

**2. fp USB Shell** —— [`fp_usb_shell_sup/`](fp_usb_shell_sup/)
- 透過 USB vendor 介面下相機自己的韌體 shell 命令:**`shl <cmd>`** 轉發 77 個韌體 shell 命令中的任何一個
  並回傳輸出(實機驗證 —— 一個 `shl display colorbar 1 0` 讓相機螢幕變彩色條)
- `AutoRun.txt` RAM 注入(不需重刷)+ 主機 daemon(`fpshelld`)+ 相機端 worker 原始碼
- 附「shell 為何會凍住相機」的完整根因分析,以及尚未解決的結構性限制(連著時錄影仍會凍)
