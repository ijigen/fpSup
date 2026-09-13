# fpSup

[![Support fpSup on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/fpsup)
[![Join the fpSup Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/XeFK5zNZpT)

**SIGMA fp firmware research and on-camera tools.**
**SIGMA fp 韌體研究與機身端工具。**

[English](#english) | [繁體中文](#繁體中文) · **[→ ijigen.github.io/fpSup](https://ijigen.github.io/fpSup/)**

Everything here runs from an `AutoRun.txt` on the SD card, in RAM only. Remove the
file, power-cycle, and the camera is stock. **Nothing is ever written to flash.**
**Firmware Ver.5.02 only** — a card built for one version writes into whatever
happens to be at those addresses on another.

---

## English

### Start here

**[ijigen.github.io/fpSup](https://ijigen.github.io/fpSup/)** — the tools, the
releases and the reference, in one page.

**[fpSup-Merge](https://ijigen.github.io/fpSup/tools/card-composer/)** — pick the
products you want on one card and get `AutoRun.txt` and `VSHL.BIN`. Merged cards are
produced here and nowhere else, and every combination is checked against the same
rules the build scripts use. Runs in the browser — no toolchain, no camera.

### Releases

Two files each — copy `AutoRun.txt` and `VSHL.BIN` to the root of the card. No
folder to make, nothing to convert, no step afterwards. To put two of them on one
card, use the composer rather than copying both.

| product | version | what it does |
|---|---|---|
| [`fpsup-gyro`](releases/fpsup-gyro-v1.11b/) | v1.11b | Writes Gyroflow's `.gcsv` and `.json` into the clip's own folder while recording. Every sample at 2500 Hz, distortion read off the lens, portrait too, no computer afterwards. |
| [`fpsup-og3k`](releases/fpsup-og3k-v0.1.1test/) | v0.1.1test | The sensor's whole 3:2 area — 3024×2010 CinemaDNG, DNG cropped to 3008×2000, at eight frame rates from 23.976 to 100. **Sensor modes 98 and 117: a native 2×2-binned 3:2 readout, not 6K resampled down.** Rolling shutter 9.2–12.6 ms, against 24.98 ms for a full 6064×4042 read. **v0.1.1test: every ISO now records correctly** — the capture was being classified as a stills acquisition, which moved the dual-native switch to ISO 640 and cost ~2.7 stops of highlight headroom above it. |
| [`fpsup-usbshell`](releases/fpsup-usbshell-v3.1.0/) | v3.1.0 | The shell that answers `shl` over USB, parasitic on the camera's own PTP gadget so the firmware keeps owning the endpoints. |

Named `fpsup-<product>-v<version>`, one directory each, and the tag is spelled
identically — see [`releases/README.md`](releases/README.md) and
[`releases/TAGS.md`](releases/TAGS.md).

> **The thing most likely to bite:** CinemaDNG is limited by write speed long
> before anything else. Open gate at 29.97 is 273 MB/s; a mid-range UHS-II card
> measured here sustains 94, and plain FHD 12-bit already needs 97. A card that
> cannot keep up buffers in RAM and then stops the take. That is the card, not a
> bug — [`tools/storage-benchmark/`](tools/storage-benchmark/) measures yours.

### Projects

Each page says what has been proven, what is being worked on, and what is open.

| # | Project | What it is | Status |
|---|---|---|---|
| 1 | [**usb shell sup**](projects/usb-shell-sup.md) | USB firmware research and data transport | **released** — v3.1.0. The channel is built on the camera's own PTP gadget, so recording survives it |
| 2 | [**sensor lab sup**](projects/sensor-lab-sup.md) | IMX410 modes, ISO, gain, sensor control | **research complete** — [explainer](https://ijigen.github.io/fpSup/explainers/imx410-iso-gain.html), and the mode-table ambiguity closed |
| 3 | [**gyro sup**](projects/gyro-sup.md) | Gyro, six-axis logging, Gyroflow workflow | **released** — two editions; Base writes a raw `.GYR` instead, converted [in a browser](gyro/web/) |
| 4 | [**open gate**](projects/open-gate.md) | Recording the sensor's full 3:2 area | **working** — live view, in-camera playback and its own menu entry all verified |
| 5 | [**6k to ssd**](projects/6k-to-ssd.md) | Getting the best 6K the link can carry | designed; 8-bit lands within 94–100% of native 6K across every remaining unknown |
| 6 | [**focus sup**](projects/focus-sup.md) | DFD, focus model, lens control, follow focus | AF decompiled in depth; no collector built |
| 7 | [**raw sup**](projects/raw-sup.md) | Bayer capture, streaming, compression, packaging | researched; the engine's sustained rate is still the one unmeasured number |
| 8 | [**ui sup**](projects/ui-sup.md) | On-screen display, boot animation | text on screen works; colour encoding unsolved |
| 9 | [**power sup**](projects/power-sup.md) | USB-C power delivery and power saving | charging mechanism solved; the rest untouched |
| — | [**firmware map**](projects/firmware-map.md) | Format, subsystems, task ABI, state sources | ongoing — not a product, the ground the rest stands on |

<details>
<summary><b>Stopped or paused</b> — kept because what they established still holds</summary>

| Project | Why it is here |
|---|---|
| [**bridge**](projects/bridge.md) — [sigma-fp-bridge](https://github.com/ijigen/sigma-fp-bridge) | The most complete thing built on the fp's PTP surface. Its measurements of why host-side autofocus is hard, and that UHD 12-bit CinemaDNG cannot come over USB, are load-bearing here |
| [**gimbal**](projects/gimbal.md) | SIGMA's `0x94xx` vendor protocol works during recording, unlike tethered focus. Relative drive only, but absolute position is readable |
| [**color sup**](projects/color-sup.md) | The colour is reproduced; the tool is awkward and nothing is packaged |
| [**fpRemote**](projects/fp-remote.md) | Not started. Wireless bridge and low-resolution streaming through AutoRun rather than PTP |

</details>

### Headline results

- **The camera writes its own Gyroflow files while it records.** The GCSV streams
  during the take and the JSON lands a few seconds in; stop is just stop. Zero
  dropped samples over a 15-minute take, timestamps verified row by row.
- **Open gate works, at every ISO.** 3024×2010 of a 3:2 sensor read, edge to edge — verified by
  unpacking a real take, not inferred. Live view, playback and the menu entry too.
- **The IMX410 ISO and gain chain is fully decompiled**, with an explainer that
  separates firmware-confirmed behaviour from OTP values still needing measurement.
- **The USB shell does not break recording.** It is built on the camera's own PTP
  gadget, so the firmware owns the endpoints and re-creates them after a
  record-mode reconfiguration.

### Reference

| | |
|---|---|
| [`docs/SHELL_COMMANDS.md`](docs/SHELL_COMMANDS.md) | the firmware shell's 77 commands, with usage text asked from a live camera |
| [`docs/SHELL_CAPABILITIES.md`](docs/SHELL_CAPABILITIES.md) | what those commands reach — memory and I²C writes, menu setters, sensor readout modes |
| [`docs/MENU_MODIFICATION.md`](docs/MENU_MODIFICATION.md) | every menu item carries its own metadata in ROM, right after its name string |
| [`docs/FREEZE_ROOTCAUSE.md`](docs/FREEZE_ROOTCAUSE.md) | why the first USB shell froze the camera, mechanism and all |

---

## 繁體中文

### 從這裡開始

**[ijigen.github.io/fpSup](https://ijigen.github.io/fpSup/)** —— 工具、釋出版、參考資料都在一頁。

**[fpSup-Merge](https://ijigen.github.io/fpSup/tools/card-composer/)** —— 勾選要的產品,
產生 `AutoRun.txt` 與 `VSHL.BIN`。**合併版只在這裡產生**,而且每個組合都用建置腳本
同一套規則檢查過。在瀏覽器裡跑 —— 不用工具鏈,不用相機。

### 釋出版

每份就兩個檔 —— `AutoRun.txt` 與 `VSHL.BIN` 放進卡片根目錄。不用建資料夾、不用轉檔、事後沒有步驟。要把兩份放同一張卡,用合併器,不要兩份都複製。

| 產品 | 版本 | 做什麼 |
|---|---|---|
| [`fpsup-gyro`](releases/fpsup-gyro-v1.11b/) | v1.11b | 錄影當下就把 Gyroflow 要的 `.gcsv` 與 `.json` 寫進片段自己的資料夾。2500 Hz 每個樣本都在,畸變直接讀鏡頭,直拿也支援,事後不用電腦。 |
| [`fpsup-og3k`](releases/fpsup-og3k-v0.1.1test/) | v0.1.1test | 感光元件完整的 3:2 面積 —— 3024×2010 CinemaDNG、DNG 裁切 3008×2000,八個幀率從 23.976 到 100。**用感光元件 mode 98 / 117:原生 2×2 binning 的 3:2 讀出,不是 6K 縮下來的。**捲簾 9.2–12.6 ms,而完整 6064×4042 讀出是 24.98 ms。**v0.1.1test:全 ISO 都正確** —— 先前擷取被歸類成拍照,雙原生切換點落在 ISO 640,640 以上少了約 2.7 檔高光餘裕。 |
| [`fpsup-usbshell`](releases/fpsup-usbshell-v3.1.0/) | v3.1.0 | 透過 USB 回應 `shl` 的 shell。寄生在相機自己的 PTP gadget 上,端點仍由韌體管。 |

命名是 `fpsup-<產品>-v<版本>`,一個版本一個資料夾,tag 逐字相同 ——
見 [`releases/README.md`](releases/README.md) 與 [`releases/TAGS.md`](releases/TAGS.md)。

> **最可能咬人的一件事:** CinemaDNG 遠在其他東西之前就先被寫入速度卡住。
> Open gate 29.97 是 273 MB/s;這裡實測一張中階 UHS-II 卡持續寫入 94,
> 而純 FHD 12bit 就已經要 97。撐不住的卡會先用 RAM 緩衝,然後**停止錄影** ——
> 那是卡不是 bug。用 [`tools/storage-benchmark/`](tools/storage-benchmark/) 量自己的。

### 項目

每一頁都寫清楚已經證實了什麼、正在做什麼、還有什麼沒解。

| # | 項目 | 是什麼 | 狀態 |
|---|---|---|---|
| 1 | [**usb shell sup**](projects/usb-shell-sup.md) | USB 韌體研究與資料傳輸 | **已釋出** —— v3.1.0。通道建在相機自己的 PTP gadget 上,所以錄影撐得過去 |
| 2 | [**sensor lab sup**](projects/sensor-lab-sup.md) | IMX410 模式、ISO、增益、感光元件控制 | **研究完成** —— [互動說明](https://ijigen.github.io/fpSup/explainers/imx410-iso-gain.html),模式表的歧義也收掉了 |
| 3 | [**gyro sup**](projects/gyro-sup.md) | 陀螺儀、六軸記錄、Gyroflow 流程 | **已釋出** —— 兩個版本;Base 版寫原始 `.GYR`,[在瀏覽器裡](gyro/web/)轉換 |
| 4 | [**open gate**](projects/open-gate.md) | 錄下感光元件完整的 3:2 面積 | **可用** —— live view、機內回放、獨立選單項目都驗證過 |
| 5 | [**6k to ssd**](projects/6k-to-ssd.md) | 把鏈路載得動的最好 6K 拿出來 | 設計完成;8bit 在所有剩餘未知數下都落在原生 6K 的 94–100% |
| 6 | [**focus sup**](projects/focus-sup.md) | DFD、對焦模型、鏡頭控制、跟焦 | AF 深度反編譯完成;收集器還沒做 |
| 7 | [**raw sup**](projects/raw-sup.md) | Bayer 擷取、串流、壓縮、封裝 | 研究過;引擎的持續速率仍是唯一沒量到的數字 |
| 8 | [**ui sup**](projects/ui-sup.md) | 螢幕顯示、開機動畫 | 螢幕出字可行;顏色編碼未解 |
| 9 | [**power sup**](projects/power-sup.md) | USB-C 供電與省電 | 充電機制已解;其餘未動 |
| — | [**firmware map**](projects/firmware-map.md) | 格式、子系統、任務 ABI、狀態來源 | 進行中 —— 不是產品,是其他東西站著的地面 |

### 主要成果

- **相機自己在錄影當下寫出 Gyroflow 要的檔案。** GCSV 邊錄邊串流,JSON 開始幾秒後落地,停止就只是停止。15 分鐘的 take 零掉樣,時間戳逐列驗過。
- **Open gate 可用,全 ISO。** 3:2 讀出的 3024×2010,整幅邊到邊 —— 解檔實錄驗證,不是推論。live view、回放、選單項目也都好了;v0.1.1test 修好了原生 ISO 的分類,ISO 640 以上不再少 2.7 檔高光。
- **IMX410 的 ISO 與增益鏈完整反編譯**,說明頁把「韌體確認的行為」跟「還需要量測的 OTP 值」分開。
- **USB shell 不會弄壞錄影。** 它建在相機自己的 PTP gadget 上,端點由韌體管,錄影模式重配之後韌體會自己重建。

---

**Support** · [Ko-fi](https://ko-fi.com/fpsup) · [Discord](https://discord.gg/XeFK5zNZpT)
