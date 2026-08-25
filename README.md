# fpSup

[English](#english) | [繁體中文](#繁體中文)

SIGMA fp firmware research and tooling. Each project has its own page with what
has been proven, what is being worked on, and what is still open.

**SIGMA fp 韌體研究與工具開發。** 每個項目各有一頁,寫清楚已經證實了什麼、
正在做什麼、還有什麼沒解。

---

## English

Ordered by how far along each one is.

| # | Project | What it is | Status |
|---|---|---|---|
| 1 | [**usb shell sup**](projects/usb-shell-sup.md) | USB firmware research and data transport | **released** — [v2.0.0](fp_usb_shell/v2/), verified on hardware |
| 2 | [**fpRemote**](projects/fp-remote.md) | Wireless bridge, low-res streaming, PTP control | **wired half is a working tool** — [sigma-fp-bridge](https://github.com/ijigen/sigma-fp-bridge); wireless not started |
| 3 | [**sensor lab sup**](projects/sensor-lab-sup.md) | IMX410 modes, ISO, gain, sensor control | **research complete** — [explainer](https://ijigen.github.io/fpSup/) published; one open item |
| 4 | [**gyro sup**](projects/gyro-sup.md) | Gyro, six-axis logging, Gyroflow workflow | **core verified on hardware**, integration pending |
| 5 | [**focus sup**](projects/focus-sup.md) | DFD, focus model, lens control, follow focus | AF decompiled in depth; a host-side attempt measured its own limits |
| 6 | [**color sup**](projects/color-sup.md) | Colour science and the DaVinci workflow | **paused** — the research holds, nothing is releasable |
| 7 | [**raw sup**](projects/raw-sup.md) | Bayer capture, streaming, compression, packaging | researched; no deliverable yet |
| 8 | [**ui sup**](projects/ui-sup.md) | On-screen display, boot animation | text on screen works; colour encoding unsolved |
| 9 | [**power sup**](projects/power-sup.md) | Boot / PTP USB-C power delivery and power saving | charging mechanism solved; the rest untouched |
| — | [**firmware map**](projects/firmware-map.md) | Format, subsystems, task ABI, state sources | ongoing — not a product, the ground the rest stands on |

### What happens next

In the order it makes sense to do it, with the reason each one is where it is.

1. **Finish gyro sup** — separate buffers to the card, merge to one gcsv on stop.
   Closest to a finished deliverable, needs no USB, and nothing blocks it
2. **usb shell: move the hook-push sources to EP 0x83** — two constants per file,
   and doing the first one proves that pipe actually carries data. Everything that
   streams later depends on that answer
3. **sensor lab: find the mode-index field** — it is the last thing standing
   between gyro sup and a complete Gyroflow lens profile, because without it the
   rolling-shutter time is ambiguous between two modes
4. **fpRemote: does GIMBAL report the actual position or the commanded one?**
   One test. It decides whether the successor focus path is viable at all, given
   that the commanded-position lead is what made the host-side loop hard
5. **focus sup: build the DFD collector** — unblocked now that the shell can run
   injected code. Sweep, read the two-band metric, read mposm. No frame extraction
6. **raw sup: open the HDMI RAW path** — the only thing between the research and
   a deliverable
7. **ui sup: the colour encoding, then a persistent marker** — cosmetic, so it
   waits, but it is the one that makes everything else legible on the camera
8. **power sup** — nothing needs it yet

**color sup is paused.** The colour is reproduced but the tool is awkward to use
and nothing is packaged, and the useful next step is writing down what makes it
awkward rather than adding features to it.

### Headline results

- **The USB shell no longer breaks recording.** v2 builds the channel on the camera's own PTP gadget, so
  the firmware owns the endpoints and re-creates them after a record-mode reconfiguration. Verified with
  the daemon attached and commands already exchanged — the exact condition that broke v1.
- **The IMX410 ISO and gain chain is fully decompiled**, with an interactive explainer that separates
  firmware-confirmed behaviour from OTP values that still need measurement.
- **The camera writes its own Gyroflow `.gcsv`** when recording stops, verified row by row.

Everything runs from an `AutoRun.txt` in RAM. Nothing here reflashes the camera.

**Reference:** [the firmware shell's 77 commands](docs/SHELL_COMMANDS.md), with the
usage text asked from a live camera.

---

## 繁體中文

依完成度排序。

| # | 項目 | 內容 | 進度 |
|---|---|---|---|
| 1 | [**usb shell sup**](projects/usb-shell-sup.md) | USB 韌體研究與資料傳輸工具 | **已釋出** — [v2.0.0](fp_usb_shell/v2/),實機驗證過 |
| 2 | [**fpRemote**](projects/fp-remote.md) | 外部無線橋接、低解析度串流、PTP 外控 | **有線那半是能用的工具** — [sigma-fp-bridge](https://github.com/ijigen/sigma-fp-bridge);無線未開始 |
| 3 | [**sensor lab sup**](projects/sensor-lab-sup.md) | IMX410 模式、ISO、gain 與 sensor 控制 | **研究完成** — [互動說明頁](https://ijigen.github.io/fpSup/)已發布;一項未解 |
| 4 | [**gyro sup**](projects/gyro-sup.md) | Gyro、六軸記錄與 Gyroflow 工作流 | **核心已實機驗證**,整合中 |
| 5 | [**focus sup**](projects/focus-sup.md) | DFD、焦點模型、鏡頭控制與追焦 | AF 已深度反編譯;主機端的嘗試量出了自己的極限 |
| 6 | [**color sup**](projects/color-sup.md) | 色彩科學與 DaVinci 工作流 | **暫停** — 研究成立,但沒有可釋出的東西 |
| 7 | [**raw sup**](projects/raw-sup.md) | Bayer 擷取、串流、壓縮與封裝 | 研究完成;尚未成品 |
| 8 | [**ui sup**](projects/ui-sup.md) | 螢幕 OSD 與開機動畫 | 已能在螢幕上寫字;顏色編碼未解 |
| 9 | [**power sup**](projects/power-sup.md) | 開機／PTP USB-C 供電與省電 | 充電機制已解;其餘未動 |
| — | [**firmware map**](projects/firmware-map.md) | 韌體格式、子系統、任務 ABI、狀態來源 | 持續累積 —— 不是產品,是其他全部的地基 |

### 接下來的順序

依「該先做什麼」排列,並附上排在那個位置的理由。

1. **把 gyro sup 做完** —— 分開的緩衝寫卡、停錄時合併成單一 gcsv。
   離「完成品」最近,不需要 USB,而且沒有任何東西擋著
2. **usb shell:把 hook-push 程式改到 EP 0x83** —— 每個檔案兩個常數,
   而做完第一個就同時證明了那條管線真的搬得動資料。
   之後所有要串流的東西都依賴這個答案
3. **sensor lab:找出模式索引欄位** —— 它是 gyro sup 與「完整 Gyroflow 鏡頭 profile」
   之間最後的阻礙,因為沒有它,捲簾時間在兩個模式之間無法確定
4. **fpRemote:GIMBAL 回報的是實際位置還是指令位置?** ——
   一個測試就能定。考慮到「指令領先」正是讓主機端迴圈難做的原因,
   這個答案決定後繼的對焦路線可不可行
5. **focus sup:把 DFD 收集器做出來** —— shell 能執行注入的程式碼之後就沒有阻礙了。
   掃焦、讀兩段式指標、讀 mposm,不需要取出任何影格
6. **raw sup:打通 HDMI RAW 路徑** —— 那是研究與成品之間唯一擋著的東西
7. **ui sup:顏色編碼,然後是持久標示** —— 屬於外觀所以往後排,
   但它是讓其他成果在相機上「看得見」的那一項
8. **power sup** —— 目前沒有東西需要它

**color sup 暫停。** 顏色重現出來了,但工具難用而且沒有打包過的東西;
下一步該做的是把「難用在哪」寫下來,而不是繼續加功能。

### 主要成果

- **USB shell 不再破壞錄影。** v2 把通道建立在相機自己的 PTP gadget 上,端點由韌體擁有、
  錄影模式重設後由韌體重建。已在 daemon 連著、指令往返過的條件下驗證 —— 那正是 v1 必壞的情境。
- **IMX410 的 ISO 與增益鏈完整反編譯**,並做成互動說明頁,明確區分「韌體已確認」
  與「仍需實機量測的 OTP 值」。
- **相機會自己寫出 Gyroflow 的 `.gcsv`**,停止錄影就產生,已逐列驗證。

全部靠 SD 卡上的 `AutoRun.txt` 在 RAM 裡執行,**沒有任何東西需要重刷韌體**。

**參考資料:**[韌體 shell 的 77 條指令](docs/SHELL_COMMANDS.md),用法全部是在實機上問出來的。
