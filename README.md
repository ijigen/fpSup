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

**2. fp USB Shell v2** — [`fp_usb_shell_sup_v2/`](fp_usb_shell_sup_v2/) — current
- Run the camera's own firmware shell commands over USB: **`shl <cmd>`** forwards any of the 77 firmware
  shell commands and returns what it printed (`mem set` and `mem save` come along for free)
- Built on the camera's **own PTP gadget**, so the firmware owns the descriptors and the endpoints and
  re-creates them after a record-mode reconfiguration — **recording while connected now works**, which is
  what v1 could not do
- Seven words of firmware are changed; PTP's unused interrupt endpoint becomes a second bulk IN, giving
  three firmware-owned pipes: commands, replies, and streaming
- `AutoRun.txt` RAM injection (no reflash), a host daemon, a descriptor dumper, and a template for running
  a routine on the camera once without leaving anything behind

**3. fp USB Shell v1** — [`fp_usb_shell_sup/`](fp_usb_shell_sup/) — superseded, kept for reference
- The first working shell. It added endpoints the firmware did not know about, so they had to be enabled
  and maintained by hand and a record-mode reconfiguration tore them down
- Retained for its root-cause write-up of "shell freezes the camera" and the hook-push experiments

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

**2. fp USB Shell v2** —— [`fp_usb_shell_sup_v2/`](fp_usb_shell_sup_v2/) —— 目前版本
- 透過 USB 下相機自己的韌體 shell 命令:**`shl <cmd>`** 轉發 77 個韌體 shell 命令並回傳輸出
  (`mem set`、`mem save` 因此免費取得)
- 建立在相機**原本的 PTP gadget** 上,描述元與端點都由韌體擁有,錄影模式重設後也由韌體重建 ——
  **連著線錄影現在可以正常運作**,那正是 v1 做不到的事
- 只改韌體七個字;把 PTP 沒人用的 interrupt 端點改成第二條 bulk IN,得到三條韌體管的管線:
  指令、回覆、串流
- `AutoRun.txt` RAM 注入(不需重刷)、主機 daemon、描述元檢視工具,以及「讓一段程式碼在相機上跑一次
  且不留痕跡」的範本

**3. fp USB Shell v1** —— [`fp_usb_shell_sup/`](fp_usb_shell_sup/) —— 已被取代,保留供參考
- 第一個能用的 shell。它加了韌體不認得的端點,所以必須自己啟用與維護,而錄影模式重設會把它們掃掉
- 保留是因為裡面有「shell 為何會凍住相機」的根因分析與 hook-push 的實驗紀錄
