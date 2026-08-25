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

**2. fp USB Shell** — [`fp_usb_shell/`](fp_usb_shell/)
- Run the camera's own firmware shell commands over USB: **`shl <cmd>`** forwards any of the 77 firmware
  shell commands and returns what it printed (`mem set` and `mem save` come along for free)
- `AutoRun.txt` RAM injection — nothing is flashed — plus a host daemon, a descriptor dumper, and a
  template for running a routine on the camera once without leaving anything behind
- Two generations, with the comparison and the reasoning inside: **v2** builds the channel on the camera's
  own PTP gadget, so the firmware owns the endpoints and re-creates them after a record-mode
  reconfiguration — **recording while connected works**, which is what v1 could not do. v1 is kept for its
  root-cause write-up of "shell freezes the camera" and its hook-push experiments

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

**2. fp USB Shell** —— [`fp_usb_shell/`](fp_usb_shell/)
- 透過 USB 下相機自己的韌體 shell 命令:**`shl <cmd>`** 轉發 77 個韌體 shell 命令並回傳輸出
  (`mem set`、`mem save` 因此免費取得)
- `AutoRun.txt` RAM 注入,完全不需重刷韌體;另有主機 daemon、描述元檢視工具,以及
  「讓一段程式碼在相機上跑一次且不留痕跡」的範本
- 兩個世代,對照與理由都在裡面:**v2** 把通道建立在相機自己的 PTP gadget 上,端點由韌體擁有、
  錄影模式重設後由韌體重建 —— **連著線錄影可以正常運作**,那正是 v1 做不到的事。
  v1 保留下來,是因為它的「shell 為何會凍住相機」根因分析與 hook-push 實驗紀錄仍有參考價值
