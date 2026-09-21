# fpSup

[![supMe on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/fpsup)
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
products you want on one card and get `AutoRun.txt` and `fpSup.BIN`. Merged cards are
produced here and nowhere else, and every combination is checked against the same
rules the build scripts use. Runs in the browser — no toolchain, no camera.

### Releases

Two files each — copy `AutoRun.txt` and the payload container to the root of
the card (`fpSup.BIN`; releases published before 2026-09-19 name it `VSHL.BIN`). No
folder to make, nothing to convert, no step afterwards. To put two of them on one
card, use the composer rather than copying both.

| product | version | what it does |
|---|---|---|
<!-- releases:begin:en -->
| [`fpsup-gyro`](releases/fpsup-gyro-v1.12.1/) | v1.12.1 | Writes Gyroflow's `.gcsv` and `.json` while recording — every sample at 2500 Hz, distortion read off the lens. The profile now carries the size the take was actually recorded at, which open gate got wrong. |
| [`fpsup-og2k`](releases/fpsup-og2k-v0.1.1a/) | v0.1.1a | The same open gate at 2016×1344, on the sensor's quiet readout at every frame rate. 98 MB/s at 24p 12-bit, 8.3 ms rolling shutter. Test build. |
| [`fpsup-og3k`](releases/fpsup-og3k-v0.2.4a/) | v0.2.4a | The sensor's whole 3:2 area at 3024×2010, eight frame rates from 23.976 to 100, native UI in Settings and Quick Set. 219 MB/s at 24p 12-bit. Alpha. |
| [`fpsup-usbshell`](releases/fpsup-usbshell-v3.1.1/) | v3.1.1 | The shell that answers `shl` over USB, parasitic on the camera's own PTP gadget so the firmware keeps owning the endpoints. |
<!-- releases:end:en -->

**The two open-gate builds see the same picture.** OG2K is the sensor reduced by three
rather than two, so it is a third of the data and stays on the quiet readout even at 100p.
They cannot share a card — the resolution menu holds three entries and each build takes the
third. **Super35/crop must be off for either.** Both are pre-release; each release's
`README.txt` lists exactly what was verified and what was not. Open gate on an fp was first
done by [Vitaly Li](https://www.facebook.com/groups/1124721801045663/permalink/3266113850239770/).

Named `fpsup-<product>-v<version>`, one directory each, and the tag is spelled
identically — see [`releases/README.md`](releases/README.md) and
[`releases/TAGS.md`](releases/TAGS.md).

> **The thing most likely to bite:** CinemaDNG is limited by write speed long
> before anything else. Open gate at 24p is about 221 MB/s at 12-bit, 184 at
> 10-bit and 148 at 8-bit; a mid-range UHS-II card measured here sustains 94,
> and plain FHD 12-bit already needs 97. A card that
> cannot keep up buffers in RAM and then stops the take. That is the card, not a
> bug — [`tools/storage-benchmark/`](tools/storage-benchmark/) measures yours.

### Projects

Each page says what has been proven, what is being worked on, and what is open.

| # | Project | What it is | Status |
|---|---|---|---|
| 1 | [**usb shell sup**](projects/usb-shell-sup.md) | USB firmware research and data transport | **released** — v3.1.0. The channel is built on the camera's own PTP gadget, so recording survives it |
| 2 | [**sensor lab sup**](projects/sensor-lab-sup.md) | IMX410 modes, ISO, gain, sensor control | **research complete** — [explainer](https://ijigen.github.io/fpSup/explainers/imx410-iso-gain.html), and the mode-table ambiguity closed |
| 3 | [**gyro sup**](projects/gyro-sup.md) | Gyro, six-axis logging, Gyroflow workflow | **released** — two editions; Base writes a raw `.GYR` instead, converted [in a browser](gyro/convert/) |
| 4 | [**open gate**](projects/open-gate.md) | Recording the sensor's full 3:2 area | **OG3K v0.2.3a alpha · OG2K v0.1.0test** — 3024×2010 or 2016×1344, same field of view; Super35/crop must remain off |
| 5 | [**6k to ssd**](projects/6k-to-ssd.md) | Getting the best 6K the link can carry | designed; 8-bit lands within 94–100% of native 6K across every remaining unknown |
| 6 | [**focus sup**](projects/focus-sup.md) | DFD, focus model, lens control, follow focus | AF decompiled in depth; no collector built |
| 7 | [**raw sup**](projects/raw-sup.md) | Bayer capture, streaming, compression, packaging | researched; the engine's sustained rate is still the one unmeasured number |
| 8 | [**ui sup**](projects/ui-sup.md) | On-screen display, boot animation | text, colour and a hardware overlay line all work on a camera |
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
- **The 12-bit open-gate path works across every ISO, with native Settings and Quick Set UI.**
  3024×2010 of a 3:2 sensor read, edge to edge — verified by unpacking a real
  take, not inferred. v0.2.2a adds 8-bit and 10-bit: all three depths were
  measured recording at OG3K geometry, where 8 and 10-bit previously fell back
  to UHD30 without any on-screen sign. v0.2.1a's four-callsite shutter-angle fix
  and loader instruction-cache synchronization carry forward. v0.2.3a fixes
  v0.2.2a's format-table pass-through pointer; all 100 DNGs in exact no-shell
  OG3K/UHD/FHD 25p/180° tests recorded at 1/50 with correct geometry. Super35/
  crop must remain off. 8/10-bit playback and highlight headroom, other frame rates,
  sustained-media and playback-with-UI regressions remain.
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
產生 `AutoRun.txt` 與 `fpSup.BIN`。**合併版只在這裡產生**,而且每個組合都用建置腳本
同一套規則檢查過。在瀏覽器裡跑 —— 不用工具鏈,不用相機。

### 釋出版

每份就兩個檔 —— `AutoRun.txt` 與 `fpSup.BIN`(2026-09-19 之前發布的版本叫 `VSHL.BIN`)放進卡片根目錄。不用建資料夾、不用轉檔、事後沒有步驟。要把兩份放同一張卡,用合併器,不要兩份都複製。

| 產品 | 版本 | 做什麼 |
|---|---|---|
<!-- releases:begin:zh -->
| [`fpsup-gyro`](releases/fpsup-gyro-v1.12.1/) | v1.12.1 | 錄影當下就把 Gyroflow 要的 `.gcsv` 與 `.json` 寫進片段資料夾。2500 Hz 每個樣本都在,畸變直接讀鏡頭。profile 的尺寸改成實際錄下的那個 —— open gate 下先前是錯的。 |
| [`fpsup-og2k`](releases/fpsup-og2k-v0.1.1a/) | v0.1.1a | 同樣的 open gate,2016×1344,每個幀率都走感光元件的安靜讀出。24p 12-bit 為 98 MB/s,捲簾 8.3 ms。測試版。 |
| [`fpsup-og3k`](releases/fpsup-og3k-v0.2.4a/) | v0.2.4a | 感光元件完整的 3:2 面積,3024×2010,八個幀率從 23.976 到 100,Settings 與 QS 有原生 UI。24p 12-bit 為 219 MB/s。Alpha。 |
| [`fpsup-usbshell`](releases/fpsup-usbshell-v3.1.1/) | v3.1.1 | 透過 USB 回應 `shl` 的 shell。寄生在相機自己的 PTP gadget 上,端點仍由韌體管。 |
<!-- releases:end:zh -->

**兩個 open gate 看到的是同一個畫面。** OG2K 是把感光元件縮三倍而不是兩倍,所以資料量只有三分之一,
而且連 100p 都還在安靜讀出上。兩者**不能放同一張卡** —— 解析度選單只有三格,各自佔用第三格。
**兩者都必須關閉 Super35/crop。**都還是預覽版:各自的 `README.txt` 寫明了驗過什麼、沒驗什麼。
最早在 fp 實現 open gate 的是 [Vitaly Li](https://www.facebook.com/groups/1124721801045663/permalink/3266113850239770/)。

命名是 `fpsup-<產品>-v<版本>`,一個版本一個資料夾,tag 逐字相同 ——
見 [`releases/README.md`](releases/README.md) 與 [`releases/TAGS.md`](releases/TAGS.md)。

> **最可能咬人的一件事:** CinemaDNG 遠在其他東西之前就先被寫入速度卡住。
> Open gate 24p 在 12/10/8-bit 各約 221 / 184 / 148 MB/s;這裡實測一張中階
> UHS-II 卡持續寫入 94,而純 FHD 12bit 就已經要 97。撐不住的卡會先用 RAM 緩衝,然後**停止錄影** ——
> 那是卡不是 bug。用 [`tools/storage-benchmark/`](tools/storage-benchmark/) 量自己的。

### 項目

每一頁都寫清楚已經證實了什麼、正在做什麼、還有什麼沒解。

| # | 項目 | 是什麼 | 狀態 |
|---|---|---|---|
| 1 | [**usb shell sup**](projects/usb-shell-sup.md) | USB 韌體研究與資料傳輸 | **已釋出** —— v3.1.0。通道建在相機自己的 PTP gadget 上,所以錄影撐得過去 |
| 2 | [**sensor lab sup**](projects/sensor-lab-sup.md) | IMX410 模式、ISO、增益、感光元件控制 | **研究完成** —— [互動說明](https://ijigen.github.io/fpSup/explainers/imx410-iso-gain.html),模式表的歧義也收掉了 |
| 3 | [**gyro sup**](projects/gyro-sup.md) | 陀螺儀、六軸記錄、Gyroflow 流程 | **已釋出** —— 兩個版本;Base 版寫原始 `.GYR`,[在瀏覽器裡](gyro/convert/)轉換 |
| 4 | [**open gate**](projects/open-gate.md) | 錄下感光元件完整的 3:2 面積 | **OG3K v0.2.3a alpha · OG2K v0.1.0test** —— 3024×2010 或 2016×1344,視角相同;Super35/crop 必須關閉 |
| 5 | [**6k to ssd**](projects/6k-to-ssd.md) | 把鏈路載得動的最好 6K 拿出來 | 設計完成;8bit 在所有剩餘未知數下都落在原生 6K 的 94–100% |
| 6 | [**focus sup**](projects/focus-sup.md) | DFD、對焦模型、鏡頭控制、跟焦 | AF 深度反編譯完成;收集器還沒做 |
| 7 | [**raw sup**](projects/raw-sup.md) | Bayer 擷取、串流、壓縮、封裝 | 研究過;引擎的持續速率仍是唯一沒量到的數字 |
| 8 | [**ui sup**](projects/ui-sup.md) | 螢幕顯示、開機動畫 | 螢幕出字可行;顏色編碼未解 |
| 9 | [**power sup**](projects/power-sup.md) | USB-C 供電與省電 | 充電機制已解;其餘未動 |
| — | [**firmware map**](projects/firmware-map.md) | 格式、子系統、任務 ABI、狀態來源 | 進行中 —— 不是產品,是其他東西站著的地面 |

### 主要成果

- **相機自己在錄影當下寫出 Gyroflow 要的檔案。** GCSV 邊錄邊串流,JSON 開始幾秒後落地,停止就只是停止。15 分鐘的 take 零掉樣,時間戳逐列驗過。
- **Open gate 的 12-bit 路徑已驗證全 ISO,原生 UI 已整合。** 3:2 讀出的 3024×2010,整幅邊到邊 —— 解檔實錄驗證,不是推論。v0.2.2a 新增 8-bit 與 10-bit;v0.2.3a 修正 format-table pass-through 指標。精確 no-shell 的 OG3K/UHD/FHD 25p/180°三段共100張 DNG 全為1/50且幾何正確。OG3K 必須關閉 Super35/crop。8/10-bit 的回放與高光餘裕、其他幀率、長時間寫入與新 UI runtime 回放仍待回歸。
- **IMX410 的 ISO 與增益鏈完整反編譯**,說明頁把「韌體確認的行為」跟「還需要量測的 OTP 值」分開。
- **USB shell 不會弄壞錄影。** 它建在相機自己的 PTP gadget 上,端點由韌體管,錄影模式重配之後韌體會自己重建。

---

**Support** · [Ko-fi](https://ko-fi.com/fpsup) · [Discord](https://discord.gg/XeFK5zNZpT)
