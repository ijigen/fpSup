# fpSup

[English](#english) | [繁體中文](#繁體中文)

SIGMA fp firmware research and tooling. Each project has its own page with what
has been proven, what is being worked on, and what is still open.

**SIGMA fp 韌體研究與工具開發。** 每個項目各有一頁,寫清楚已經證實了什麼、
正在做什麼、還有什麼沒解。

---

## English

| Project | What it is | Status |
|---|---|---|
| [**usb shell sup**](projects/usb-shell-sup.md) | USB firmware research and data transport | **v2 shipped** — [code](fp_usb_shell/) |
| [**color sup**](projects/color-sup.md) | Colour science and the DaVinci workflow | **shipped** — working DCTL |
| [**sensor lab sup**](projects/sensor-lab-sup.md) | IMX410 modes, ISO, gain, sensor control | **mostly done** — [explainer](https://ijigen.github.io/fpSup/) |
| [**gyro sup**](projects/gyro-sup.md) | Gyro, six-axis logging, Gyroflow workflow | **in progress** — core verified on hardware |
| [**focus sup**](projects/focus-sup.md) | DFD, focus model, lens control, external follow focus | AF decompiled in depth; a host-side attempt measured its own limits |
| [**raw sup**](projects/raw-sup.md) | Bayer capture, streaming, compression, RAW packaging | researched, no deliverable yet |
| [**ui sup**](projects/ui-sup.md) | On-screen display, boot animation | in progress — text on screen works |
| [**power sup**](projects/power-sup.md) | Boot / PTP USB-C power delivery and power saving | early — charging mechanism solved |
| [**fpRemote**](projects/fp-remote.md) | Wireless bridge, low-resolution streaming, PTP control | **wired half works** — [sigma-fp-bridge](https://github.com/ijigen/sigma-fp-bridge) |
| [**firmware map**](projects/firmware-map.md) | Format, subsystems, task ABI, state sources | ongoing — the ground everything stands on |

### Headline results

- **The USB shell no longer breaks recording.** v2 builds the channel on the camera's own PTP gadget, so
  the firmware owns the endpoints and re-creates them after a record-mode reconfiguration. Verified with
  the daemon attached and commands already exchanged — the exact condition that broke v1.
- **fp's colour science is reproduced in DaVinci** by an in-pipeline DCTL.
- **The IMX410 ISO and gain chain is fully decompiled**, with an interactive explainer that separates
  firmware-confirmed behaviour from OTP values that still need measurement.
- **The camera writes its own Gyroflow `.gcsv`** when recording stops, verified row by row.

Everything runs from an `AutoRun.txt` in RAM. Nothing here reflashes the camera.

**Reference:** [the firmware shell's 77 commands](docs/SHELL_COMMANDS.md), with the
usage text asked from a live camera.

---

## 繁體中文

| 項目 | 內容 | 進度 |
|---|---|---|
| [**usb shell sup**](projects/usb-shell-sup.md) | USB 韌體研究與資料傳輸工具 | **v2 可用** — [程式](fp_usb_shell/) |
| [**color sup**](projects/color-sup.md) | 色彩科學與 DaVinci 工作流 | **已有成品** — 可用的 DCTL |
| [**sensor lab sup**](projects/sensor-lab-sup.md) | IMX410 模式、ISO、gain 與 sensor 控制 | **大致完成** — [互動說明頁](https://ijigen.github.io/fpSup/) |
| [**gyro sup**](projects/gyro-sup.md) | Gyro、六軸記錄與 Gyroflow 工作流 | **進行中** — 核心已實機驗證 |
| [**focus sup**](projects/focus-sup.md) | DFD、焦點模型、鏡頭控制與外部追焦 | AF 已深度反編譯;主機端的嘗試量出了自己的極限 |
| [**raw sup**](projects/raw-sup.md) | Bayer 擷取、串流、壓縮與 RAW 封裝 | 研究完成,尚未成品 |
| [**ui sup**](projects/ui-sup.md) | 螢幕 OSD 與開機動畫 | 進行中 — 已能在螢幕上寫字 |
| [**power sup**](projects/power-sup.md) | 開機／PTP USB-C 供電與省電 | 起步 — 充電機制已解 |
| [**fpRemote**](projects/fp-remote.md) | 外部無線橋接、低解析度串流、PTP 外控 | **有線那半已可用** — [sigma-fp-bridge](https://github.com/ijigen/sigma-fp-bridge) |
| [**firmware map**](projects/firmware-map.md) | 韌體格式、子系統、任務 ABI、狀態來源 | 持續累積 — 其他全部的地基 |

### 主要成果

- **USB shell 不再破壞錄影。** v2 把通道建立在相機自己的 PTP gadget 上,端點由韌體擁有、
  錄影模式重設後由韌體重建。已在 daemon 連著、指令往返過的條件下驗證 —— 那正是 v1 必壞的情境。
- **fp 的色彩科學已在 DaVinci 中重現**,用的是 in-pipeline 的 DCTL。
- **IMX410 的 ISO 與增益鏈完整反編譯**,並做成互動說明頁,明確區分「韌體已確認」
  與「仍需實機量測的 OTP 值」。
- **相機會自己寫出 Gyroflow 的 `.gcsv`**,停止錄影就產生,已逐列驗證。

全部靠 SD 卡上的 `AutoRun.txt` 在 RAM 裡執行,**沒有任何東西需要重刷韌體**。

**參考資料:**[韌體 shell 的 77 條指令](docs/SHELL_COMMANDS.md),用法全部是在實機上問出來的。
