# fpSup

[English](#english) | [繁體中文](#繁體中文)

SIGMA fp firmware research and tooling. Each project has its own page with what
has been proven, what is being worked on, and what is still open.

**SIGMA fp 韌體研究與工具開發。** 每個項目各有一頁,寫清楚已經證實了什麼、
正在做什麼、還有什麼沒解。

---

## English

### Active

Ordered by how far along each one is.

| # | Project | What it is | Status |
|---|---|---|---|
| 1 | [**usb shell sup**](projects/usb-shell-sup.md) | USB firmware research and data transport | **released** — [v2.0.0](fp_usb_shell/), verified on hardware |
| 2 | [**sensor lab sup**](projects/sensor-lab-sup.md) | IMX410 modes, ISO, gain, sensor control | **research complete** — [explainer](https://ijigen.github.io/fpSup/) published; one open item |
| 3 | [**gyro sup**](projects/gyro-sup.md) | Gyro, six-axis logging, Gyroflow workflow | **core verified on hardware**, integration pending |
| 4 | [**focus sup**](projects/focus-sup.md) | DFD, focus model, lens control, follow focus | AF decompiled in depth; no collector built |
| 5 | [**raw sup**](projects/raw-sup.md) | Bayer capture, streaming, compression, packaging | researched; lossless UHD to card hinges on one unmeasured number |
| 6 | [**ui sup**](projects/ui-sup.md) | On-screen display, boot animation | text on screen works; colour encoding unsolved |
| 7 | [**power sup**](projects/power-sup.md) | Boot / PTP USB-C power delivery and power saving | charging mechanism solved; the rest untouched |
| — | [**firmware map**](projects/firmware-map.md) | Format, subsystems, task ABI, state sources | ongoing — not a product, the ground the rest stands on |

### Stopped or paused

Kept because what they established still holds and the rest of the work leans on it.

| Project | What it is | Why it is here |
|---|---|---|
| [**bridge**](projects/bridge.md) | PTP control over USB — [sigma-fp-bridge](https://github.com/ijigen/sigma-fp-bridge) | The most complete thing built on the fp's PTP surface. Its measurements of why host-side autofocus is hard, and that UHD 12-bit CinemaDNG cannot come over USB, are load-bearing here |
| [**gimbal**](projects/gimbal.md) | SIGMA's GIMBAL vendor protocol at `0x94xx` | Works during recording, unlike tethered focus. Relative drive only, but the absolute position is readable — one unanswered question decides whether that is usable |
| [**color sup**](projects/color-sup.md) | Colour science and the DaVinci workflow | The colour is reproduced; the tool is awkward and nothing is packaged |

### Not started

| Project | What it is |
|---|---|
| [**fpRemote**](projects/fp-remote.md) | Wireless bridge and low-resolution streaming, running through AutoRun on the camera rather than PTP |

### Headline results

- **The USB shell no longer breaks recording.** v2 builds the channel on the camera's own PTP gadget, so
  the firmware owns the endpoints and re-creates them after a record-mode reconfiguration. Verified with
  the daemon attached and commands already exchanged — the exact condition that broke v1.
- **The IMX410 ISO and gain chain is fully decompiled**, with an interactive explainer that separates
  firmware-confirmed behaviour from OTP values that still need measurement.
- **The camera writes its own Gyroflow `.gcsv`** when recording stops, verified row by row.

Everything runs from an `AutoRun.txt` in RAM. Nothing here reflashes the camera.

**Reference**

| | |
|---|---|
| [`docs/SHELL_COMMANDS.md`](docs/SHELL_COMMANDS.md) | the firmware shell's 77 commands, with the usage text asked from a live camera |
| [`docs/SHELL_CAPABILITIES.md`](docs/SHELL_CAPABILITIES.md) | what those commands can actually reach — memory and I2C writes, the menu setters, sensor readout modes |
| [`docs/FREEZE_ROOTCAUSE.md`](docs/FREEZE_ROOTCAUSE.md) | why the first USB shell froze the camera, mechanism and all |

**Code**

| | |
|---|---|
| [`fp_usb_shell/`](fp_usb_shell/) | the shell itself |
| [`focus/`](focus/) | DFD and lens data |
| [`gyro/`](gyro/) | IMU snapshot and the gyro AutoRun builder |
| [`console/`](console/) | a live view of camera state |
| [`history/`](history/) | superseded work, kept for what it established |

---

## 繁體中文

### 進行中

依完成度排序。

| # | 項目 | 內容 | 進度 |
|---|---|---|---|
| 1 | [**usb shell sup**](projects/usb-shell-sup.md) | USB 韌體研究與資料傳輸工具 | **已釋出** — [v2.0.0](fp_usb_shell/),實機驗證過 |
| 2 | [**sensor lab sup**](projects/sensor-lab-sup.md) | IMX410 模式、ISO、gain 與 sensor 控制 | **研究完成** — [互動說明頁](https://ijigen.github.io/fpSup/)已發布;一項未解 |
| 3 | [**gyro sup**](projects/gyro-sup.md) | Gyro、六軸記錄與 Gyroflow 工作流 | **核心已實機驗證**,整合中 |
| 4 | [**focus sup**](projects/focus-sup.md) | DFD、焦點模型、鏡頭控制與追焦 | AF 已深度反編譯;收集器未建 |
| 5 | [**raw sup**](projects/raw-sup.md) | Bayer 擷取、串流、壓縮與封裝 | 研究完成;無損 UHD 寫卡壓在一個沒量過的數字上 |
| 6 | [**ui sup**](projects/ui-sup.md) | 螢幕 OSD 與開機動畫 | 已能在螢幕上寫字;顏色編碼未解 |
| 7 | [**power sup**](projects/power-sup.md) | 開機／PTP USB-C 供電與省電 | 充電機制已解;其餘未動 |
| — | [**firmware map**](projects/firmware-map.md) | 韌體格式、子系統、任務 ABI、狀態來源 | 持續累積 —— 不是產品,是其他全部的地基 |

### 已停止 / 暫停

保留是因為它們建立的東西仍然成立,而且其他工作靠著它們。

| 項目 | 內容 | 為什麼保留 |
|---|---|---|
| [**bridge**](projects/bridge.md) | 透過 PTP 的 USB 控制 — [sigma-fp-bridge](https://github.com/ijigen/sigma-fp-bridge) | 目前在 fp 的 PTP 介面上做得最完整的東西。它量出的「主機端自動對焦為什麼難」,以及「UHD 12-bit CinemaDNG 拿不到」,都撐著這裡的其他研究 |
| [**gimbal**](projects/gimbal.md) | SIGMA 的 GIMBAL vendor 協定,在 `0x94xx` | 跟 tethered 對焦不同,它**在錄影中仍然有效**。只能相對驅動,但絕對位置讀得到 —— 有一個未答的問題決定它能不能用 |
| [**color sup**](projects/color-sup.md) | 色彩科學與 DaVinci 工作流 | 顏色重現出來了;工具難用,而且沒有打包過的東西 |

### 未開始

| 項目 | 內容 |
|---|---|
| [**fpRemote**](projects/fp-remote.md) | 外部無線橋接與低解析度串流,走相機端的 AutoRun 而不是 PTP |

### 主要成果

- **USB shell 不再破壞錄影。** v2 把通道建立在相機自己的 PTP gadget 上,端點由韌體擁有、
  錄影模式重設後由韌體重建。已在 daemon 連著、指令往返過的條件下驗證 —— 那正是 v1 必壞的情境。
- **IMX410 的 ISO 與增益鏈完整反編譯**,並做成互動說明頁,明確區分「韌體已確認」
  與「仍需實機量測的 OTP 值」。
- **相機會自己寫出 Gyroflow 的 `.gcsv`**,停止錄影就產生,已逐列驗證。

全部靠 SD 卡上的 `AutoRun.txt` 在 RAM 裡執行,**沒有任何東西需要重刷韌體**。

**參考資料**

| | |
|---|---|
| [`docs/SHELL_COMMANDS.md`](docs/SHELL_COMMANDS.md) | 韌體 shell 的 77 條指令,用法全部是在實機上問出來的 |
| [`docs/SHELL_CAPABILITIES.md`](docs/SHELL_CAPABILITIES.md) | 那些指令實際搆得到什麼 —— 記憶體與 I2C 寫入、選單設定器、感光元件讀出模式 |
| [`docs/FREEZE_ROOTCAUSE.md`](docs/FREEZE_ROOTCAUSE.md) | 第一版 USB shell 為什麼會凍住相機,連機制一起 |

**程式**

| | |
|---|---|
| [`fp_usb_shell/`](fp_usb_shell/) | shell 本體 |
| [`focus/`](focus/) | DFD 與鏡頭資料 |
| [`gyro/`](gyro/) | IMU 快照與陀螺 AutoRun 建置 |
| [`console/`](console/) | 相機狀態即時檢視 |
| [`history/`](history/) | 被取代的工作,保留是因為它建立的東西 |
