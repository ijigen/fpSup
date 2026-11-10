# QS 的「模式 QR 碼」—— 離線研究（2026-10-29）

目標：SensorLab-IMX410 加一個 QS 功能，畫出一張 QR 碼。手機掃了會打開 fpSup 網站，頁面顯示目前模式的 DC、RES、FPS、
recipe（感光元件合併、AD 位元數、ISP bin／核心／模式）、看到的尺寸與捲簾。

全部離線完成：沒碰相機、沒改原始碼。韌體 Ver.5.02。
證據等級：**[驗]** 反組譯讀過，或在 unicorn 裡跑過真映像並用 OpenCV 解碼確認；**[推]** 推論，還沒上機。

---

## 0. 結論

1. **原廠的 QR 編碼器可以直接借用** [驗]。它是純計算函式 `FUN_c05c5be8`，不碰硬體也不碰 OS。
   在 unicorn 裡拿真映像跑，輸入自訂 URL，輸出的 YUYV 或 Y8 影像用 OpenCV 解得回**一模一樣的 URL**。
   限制有三個：
   - 版本**固定 20**（97×97 模組）。
   - 只能用 byte 模式，所以 URL 的任何位元組都可以放。
   - 原廠會先把資料逐位元組 **+i**（混淆）。我們送進去之前先做 −i 就能抵銷。
2. **原廠的顯示路徑不適合在 QS 用** [推]。原廠是「播放序列」的訊息 `QrCodeMake`，只有 `XC_PlayFuncSeqIndex` 會處理它，
   而且畫在播放影像平面（整片 1024×682 YUV 白底）。在即時取景的 QS 裡會不會出現、出現後怎麼回到 QS，都沒有證據。
3. **建議路線**：借原廠編碼器，畫面由我們自己畫。
   - 用 `FUN_c05c5be8` 產生 97×97 的 Y8 模組矩陣。
   - 用已知可行的 **DrawingObserver** 每個重繪週期把矩陣放大貼進主 OSD 層（1024×682 ARGB4444）。
   - QS 端用容器 API 4 的 `fine()`：AEL 開、AEL／移開焦點／關 QS 時收掉。
   - 編碼器本身不佔程式碼，我們只寫 observer 和貼圖，約 200–300 行 C。
4. **掃描難度是唯一的硬傷**：版本 20 在 3.15 吋 LCD 上一格只有約 0.39 mm（放大 6 倍時）。
   如果實測手機掃起來吃力，就換我們自己的小編碼器（版本 4，33 模組，一格約 1 mm），顯示的那一半不用改。
5. **URL**：171 bit 用 base64url 打包成 29 字元。
   - `https://ijigen.github.io/fpSup/m#<29>` 共 62 B
   - `https://fpsup.ijigen.xyz/m#<29>` 共 56 B
   - 兩種都放得進版本 4-L（78 B）。原廠的版本 20-L 容量 858 B，空間很多。
   - 解碼頁現在還沒有。最接近的是 `explainers/sensorlab-dcres/`（已上線的 DC×RES 預覽），它只認 `#recipe`。

---

## 1. 原廠 QR 碼

### 1.1 呼叫鏈

| 角色 | 位址 | 內容 | 證據 |
|---|---|---|---|
| shell 指令 `qr` | handler `0xC0407298`，子指令表 `0xC0BC1654`（每項 12 B `{name, help, fn}`） | `test` `0xC0407068`、`play_make` `0xC0406F90`、`play_read` `0xC0407028`、`lv_read` `0xC0407048`、`decode_log`／`dump_yuv`／`dump_y8` | [驗] 從映像讀表 |
| `qr play_make [data]` | `0xC0406F90` | 用 non-cache 配置 0x100 B（`FUN_c0406cb0` → `0xC3757F00`），strncpy 最多 0x100，len = min(strlen, 0x100)；接著呼叫 `FUN_c03adfd8(FUN_c03ad6f0(), buf, len)` | [驗] |
| 播放執行器單例 | `FUN_c03ad6f0` 回傳 `0xC35CC4F0` | 第一次呼叫時建構 | [驗] |
| 送出 QrCodeMake | `FUN_c03adfd8(exe, data, len)` | 訊息 class 0x26、cmd **0x3C**、+0x14 data、+0x18 len → `FUN_c03a0798(*exe, msg)` | [驗] |
| QrCodeRelease | `FUN_c03ae098(exe)` | cmd **0x3D** | [驗] |
| SetReadMode／ReqRead | `FUN_c03ae0e8`／`FUN_c03ae198` | cmd 0x3E／0x3F（讀碼用） | [驗] |
| 命令名稱表 | `0xC0BA2408` 起 | `QrCodeMake`、`QrCodeRelease`、`QrCodeSetReadMode`、`QrCodeReqRead`（0x3C..0x3F，夾在 Cinemagraph 與 ScreenShot 之間） | [驗] 字串 |
| 收訊端 | `XC_PlayFuncSeqIndex::v58` `0xC03B3F58` | 從 memory class 9 配 1024×682 YUV（`DAT_c2dfe928` = 0x400×0x2AA）→ `FUN_c05c4680(qr, img, data, len)` → `FUN_c03b4568` 顯示 | [驗] |
| 釋放 | `XC_PlayFuncSeqIndex::v59` `0xC03B40A0` | 把 class 9 還回去 | [驗] |
| 選單預覽 | `MenuQrCodePreviewHandler::v72` `0xC0476698` | `FUN_c0489fe0` 配緩衝（大小 `FUN_c052bd28`）→ 填 0xFF → `FUN_c052c070` 序列化推薦設定 → `FUN_c03adfd8` 送出 → `FUN_c0527b08(CYC_DRAW, 0, 5000, 1, 0)` | [驗] |
| 選單收尾 | `::v73` `0xC0476748` | `FUN_c03ae098`（Release）→ `FUN_c03add48(exe, 0)`（class 0x27／cmd 0x11）→ `FUN_c048a038` 釋放 | [驗] |

### 1.2 編碼器 `FUN_c05c4680`（XC_QrCode::Make）與核心 `FUN_c05c5be8`

`FUN_c05c4680(qr, img, data, len)` 的流程：
1. 檢查影像是不是 1024×682。
2. 用 `0x80FF80FF` 把整張填白（YUYV，Y 在偶數位元組）。
3. 配 0x9380 B 工作區。
4. 填下面的 0x28 B 參數結構，呼叫 **`FUN_c05c5be8(p)`**。

| 偏移 | 原廠值 | 意義 | 證據 |
|---|---|---|---|
| +0x00 (u8) | 0x14 | **QR 版本 20**，只接受這個值（`FUN_c05cbe08` 只有 version==0x14 且 mode==2 才回傳容量） | [驗] |
| +0x04 | 2 | 模式 = **8-bit byte** | [驗] |
| +0x08 | 1 | ECC 索引，照 QR 格式位元：0=M、1=**L**、2=H、3=Q；容量表 `0xC2DFF2BC` = {666, 858, 382, 482} | [驗] 表 |
| +0x0C | ptr | 工作區 0x9380 B（37,760 B） | [驗] |
| +0x10 | len | 資料長度，上限是上表的容量 | [驗] |
| +0x14 | ptr | 資料 | [驗] |
| +0x18 | 4 | **每模組像素數**（放大倍數） | [驗] 模擬：2→194 px、4→388 px、6→582 px |
| +0x1C | 2 | 每像素位元組數（2 = YUYV、1 = Y8） | [驗] 模擬 |
| +0x20 | 1024 | 每列像素（stride） | [驗] |
| +0x24 | ptr | 左上角目標位址。原廠放在 (586, 63)，388×388（`0xC0BA0B74..80` = 0x24A, 0x3F, 0x184, 0x184） | [驗] |

- **混淆**：`FUN_c05c5b98` 在編碼前做 `data[i] += i`（mod 256）；解碼端 `FUN_c05c5bc0` 再減回去。
  手機不會減，所以原廠設定 QR 拿手機掃出來是亂碼。**自訂內容要先做 `data[i] -= i`** [驗]：
  不補償時解出 `huvsw?56…`，補償後解出原 URL。
- **只畫黑格**：白格要事先填好。bpp=1 時先填 0xFF 再呼叫，就得到乾淨的 97×97 Y8 矩陣 [驗]。
- **ECC 只用 L 或 M**。H、Q 產出的碼 OpenCV 解不出來 [驗 模擬]，可能是原廠的 RS 區塊表只有 L/M 正確，原因沒有追。
- **成本**：一次約 **8.4 M 指令**（unicorn 計數）。韌體程式碼走快取別名，估計 10 ms 左右 [推]。只在打開 QR 時算一次。
- **共用狀態**：池配置器的全域在 `0xC37CE9B8..0xC37CE9F4`，跟 QR **解碼器**共用。只要不同時在讀碼就不會衝突 [推]。
- 函式是 ARM 模式（偶數位址、unicorn 用 ARM 模式跑通）。上機呼叫前仍照 [[callfn-thumb-plus-one]] 先讀首字。

**模擬重現**：載入 `out/MAIN_c0000000.bin`（0xC0000000，0x03000000 B），對映 0xC3000000 的 16 MB BSS（全零），
其他函式都不用 stub，直接呼叫 `0xC05C5BE8`。腳本在 scratchpad 的 `qrtools/emu_qr.py`、`emu_y8.py`
（暫存位置，要留的話搬進 `validation/`）。核心片段：

```python
data = bytes((b - i) & 0xFF for i, b in enumerate(url))       # 抵銷原廠的 +i
p = struct.pack('<B3xIIIIIIIII', 0x14, 2, 1, WORK, len(data), DATA, 1, 1, 97, DST)  # 版本20 byte L, x1, Y8
mem[DST:DST+97*97] = b'\xff' * 9409;  run(0xC05C5BE8, [P])   # → 97x97 0/255 矩陣，OpenCV 解回 url
```

### 1.3 子問題的答案

- **sup 能不能餵自己的字串？** 可以。直接呼叫 `FUN_c05c5be8` 最乾淨，不用走 `qr play_make`：
  play_make 上限 256 B，而且沒有做 −i 補償，手機掃出來會是亂碼。
- **長度、版本、ECC**：版本 20 固定，byte 模式，L 級 858 B／M 級 666 B。任何位元組都可以放，不限英數。
- **能不能從我們的程式碼觸發，再關掉？**
  - 編碼：可以，純函式 [驗]。
  - 原廠顯示（`FUN_c03adfd8` 送 0x3C、`FUN_c03ae098` 送 0x3D、再 `FUN_c03add48(exe, 0)`）：函式本身叫得到。
    但收訊端只有 `XC_PlayFuncSeqIndex` 有實作 [驗]，其他序列走基底類別，行為未知。
  - 即時取景／QS 裡有沒有播放序列在 Index 狀態、播放平面會不會合成到 QS 上 [推：大概不會]，都要上機才能確定。
  - 最便宜的驗法是 shell 打 `qr play_make test`，分別在播放、即時取景、選單三種狀態下截圖。
  - 原廠顯示是整片白底加右側 388 px 的碼，左邊留給選單文字。

---

## 2. 自己畫圖（建議走這條；用原廠編碼器或自己的編碼器都一樣）

| 選項 | 可行性 | 說明 |
|---|---|---|
| **A. 主 OSD 層 + DrawingObserver** | **好** [驗 機制] | `FUN_c0528300(0xC3783020, group, obs)` 註冊，`FUN_c05283D8` 解除。obs vtable：+0x0C = 我們的繪製函式，+0x10/+0x14/+0x18 = no-op，+0x1C 回傳 0（不會被自動移除）。主層是 **1024×682 ARGB4444**（`0xF000` 不透明黑、`0xFFFF` 白），三重緩衝，每個週期都要重畫；cache clean 和 present 由相機處理（research/display/notes/OSD_PERSISTENT_MARKER.md、DISPLAY_OSD_MAP.md）。純寫 RAM，不改程式碼。 |
| B. 執行期生成圖片資源（NBR 目錄 8 B 換指標） | 差 | 要即時產生 .xci（RLE／LZ4）；QS 格子的圖示位置只有小圖示大小，放不下 QR；整頁換圖還得找一個大圖槽。工多又沒好處。 |
| C. 寫進顯示 ring | 不行 | ring 每幀都被即時取景覆蓋，而且是錄影鏈的一部分（別碰）。 |
| D. 硬體矩形 marker | 不行 | 數量太少（42 個 slot），只能畫框。 |

**尺寸**：LCD 是 3.15 吋、1024×682（就是 2.1M 點），682 px 約 44 mm，1 px 約 0.065 mm。

| 碼 | 放大 | 含 4 模組靜區 | 一格 | 整張 | 每週期寫入 |
|---|---|---|---|---|---|
| 原廠 V20（97） | ×6 | 630 px | 0.39 mm | 41 mm | 約 0.8 MB（ARGB4444） |
| 自訂 V3（29） | ×18 | 666 px | 1.17 mm | 43 mm | 約 0.9 MB |
| 自訂 V4（33） | ×16 | 656 px | 1.04 mm | 43 mm | 約 0.86 MB |
| 自訂 V5（37） | ×15 | 675 px | 0.98 mm | 44 mm | 約 0.9 MB |

- 每週期約 0.4 M 像素。可以先畫一張，之後每個週期 memcpy 整列，估計約 1–2 ms／週期 [推]。
  比對：UI_DRAW_CPU_COST.md 的選單重繪成本。
- 只在 QR 開著時註冊 observer，關掉就解除，平時零成本。
- 畫面置中、四周填白，遮住 QS 面板，像一個暫時的全畫面。
- **自己的編碼器**：
  - Nayuki qrcodegen（MIT，跟 GPL-3 相容）編成 Thumb 約 5–7 KB [推]。
  - 或寫一個只支援 byte 模式、L 級、固定 V4、固定 mask 的精簡版，約 1.5–2 KB [推]。
  - 用 unicorn 跑完再拿 OpenCV 解碼，做法跟本筆記的模擬一樣。

---

## 3. URL 內容

### 3.1 欄位（171 bit，用 base64url 寫成 29 字元）

來源：`slqs.c` 的 `st->applied`／`struct rcp`／`struct sel`，以及 `core.h` 的 `core_quality`。

| 欄位 | bit | 範圍／編碼 |
|---|---|---|
| 格式版本 | 4 | 1；同時綁定 core_data 的版本（key 索引表跟著它走） |
| DC 寬 | 13 | 256..6048 |
| DC 高 | 12 | 144..4040 |
| RES 寬 | 13 | 輸出寬 |
| RES 高 | 12 | 輸出高 |
| FPS 選擇 | 5 | 0..28 = `STD_S` 索引，29 = 細調／自訂，30 = recipe 上限 |
| VMAX | 15 | ≤16384；實際 fps = 72 000 000 ÷ (HMAX × VMAX)（`CD_CLK`） |
| HMAX | 16 | `rcp.hm` |
| AD | 2 | 0=11（fast）、1=12、2=14 |
| 感光元件 mh | 2 | 1..3 |
| 感光元件 mv | 3 | 1..6（有 3x6） |
| ISP hbin | 4 | CRCT |
| ISP vbin | 4 | CRCT |
| readout key | 6 | `cd_key_name` 索引，0..39 |
| 核心 kh | 3 | `KERN` 0..5 |
| 核心 kv | 3 | `KERN` 0..5 |
| 模式 km | 1 | SOFT／STD |
| recipe 是預設或 CUSTOM | 1 | |
| 看到的寬 | 13 | `vis_w`（由相機算好） |
| 看到的高 | 12 | `vis_h` |
| 捲簾 µs | 17 | `rs_us`，上限 131 ms |
| 格式 | 1 | DNG／MOV |
| RES 是 K 標籤或 CUSTOM | 1 | |
| CRC-8 | 8 | 對前 163 bit 算；擋掉讀錯或格式版本不符 |

- 看到的尺寸與捲簾可以由網頁重算。但網頁的 `fps_data.js` 只是替身，相機的數字才是真值，所以照樣放進去（+42 bit）。
- 拿掉它們只剩 129 bit = 22 字元，可以縮到 V3-L。
- 位元序：MSB 優先，依上表順序。base64url 不加 `=`。

### 3.2 長度與版本

| 前綴 | 長度 | 總長 | 最小版本 |
|---|---|---|---|
| `https://ijigen.github.io/fpSup/m#` | 33 | 62 B | V4-M（剛好 62）／V4-L 78 |
| `https://fpsup.ijigen.xyz/m#` | 27 | 56 B | V4-L |
| 同上、拿掉 vis/rs（22 字元） | | 49 B | V3-L（53） |

- 主機名稱改大寫可以用 alphanumeric 模式，但 fragment 會跟著變成只能大寫（base32），有些掃描器處理大寫 scheme 會出問題。不建議。
- 原廠 V20 的容量用不完（858 B），長度只影響自訂編碼器能用多小的版本。
- `fpsup.ijigen.xyz` 是 CT124 鏡像，fpsup-sync 從 10-27 起暫停（[[proxmox-server-conventions]]），可能拿到舊頁。
  GitHub Pages 才是正本（`og:url`）。

### 3.3 網站解碼

- **現成頁面**：`fpSup/explainers/sensorlab-dcres/index.html`（worktrees/fpsup-merged，commit `3fa2666c`）。
  這是 Bei 認可的 QS 網頁版，hash 只認 `#recipe`（設定焦點）。
- 沒有任何頁面會從 hash 解出模式。
- **建議**：新增 `fpSup/m/index.html`，一個靜態小頁：
  1. 用 `atob` 把 base64url 轉成 bit 讀取器，驗 CRC。
  2. 顯示 DC、RES、FPS（用 VMAX/HMAX 算出精確值，同時顯示選的標籤）、RECIPE（例如 `12b 3x3`、ISP `2x2 1,2,1 STD`、key 名稱）、看到的尺寸、RS。
  3. 附一個「在 DC×RES 預覽裡打開」的連結，把 DC／RES／recipe 帶進 `sensorlab-dcres` 的 S（那邊要加約 20 行 `#m=` 解析）。
  4. 依 key／recipe 連到 `isp-custom.html` 對應的驗證錨點（id 形如 `20261028-p5-FHD60_C…`，要另外做對照表）。
- 網址短、跟頁面結構脫鉤，以後改版只要提高格式版本。

---

## 4. 建議路線與工時

**第 1 階段：上機前的離線工作，約 1.5 天**

1. `slqs.c` 新增功能 `QR`（QSC_F_CINE | QSC_F_LOCK_REC，API 4 `fine()`）。
   - `fine(1)`：打包 URL → 在快取別名的工作區（0x9380 + 9409 B，跟配置器要）呼叫 `FUN_c05c5be8` → 註冊 observer。
   - `fine(0)` 或 `leave()`：解除 observer、釋放記憶體。
2. 測試：
   - unicorn 測：真映像編碼器 → OpenCV 解回 URL。
   - observer 的繪製函式對假的 descriptor 寫 ARGB4444，比對像素。
   - 突變測：拿掉 −i、ECC 用 H、放大倍數錯，測試都要失敗。
3. 網站 `m/index.html` 加 JS 解碼與單元測試（node 跑打包↔解碼來回）：約 0.5 天（含在上面）。

**第 2 階段：上機，約 0.5–1 天**（照 [[notify-user-before-camera]]、[[broadcast-before-camera]]）

1. observer 畫在 QS 面板上面還是下面（z-order）。
2. AEL／MENU／關 QS 時有沒有收乾淨。
3. 用 iPhone／Android 在 LCD 上實際掃，記錄最大掃描距離與反光情況。
4. （選做）`qr play_make test` 在三種狀態下截圖，把 §1.3 的 [推] 補成 [驗]。

**第 3 階段（只在 V20 掃不好時）：約 1 天**。換成自己的 V4 編碼器，observer 不用動。

---

## 5. 要問 Bei 的問題

1. **網域**：用 `ijigen.github.io/fpSup/m#…`（正本、穩定）還是 `fpsup.ijigen.xyz/m#…`（短 6 字，但鏡像目前停止同步）？
2. **碼的大小**：先用原廠編碼器（零程式碼，但版本 20 很密，一格 0.39 mm），還是一開始就用自己的 V4（一格 1 mm、好掃，多 2–7 KB）？
3. **放在哪**：要獨立一個 QS 功能「QR」（AEL 開關），還是掛在 RECIPE 的子 QS 裡？SL 現有 6 個功能，容器上限 16。
4. **網頁**：新做 `/m/` 小頁，還是直接讓 `sensorlab-dcres` 吃 `#m=`？或兩者都做，小頁連過去。
5. **看到的尺寸／捲簾**：要放相機算的真值進 URL（建議），還是由網頁重算、讓碼小一號？
6. **錄影中**：一律鎖住（建議，照 [[no-usb-during-rec-or-playback]] 的精神不碰顯示鏈），還是允許？
7. **畫面**：全畫面白底置中（掃描最可靠），還是半透明、只蓋 QS 面板？

## Bei 定案（2026-10-29）
- 網域：ijigen.github.io/fpSup（正本）。
- 編碼器：先借原廠 V20（之後掃描吃力再換自己的 V4）。
- 獨立 QS 功能「QR」，AEL 顯示、再按或移開收掉。
- 只蓋住 QS 面板（不是全畫面）。
- 未問、照建議：網頁新做 `/m/`；碼內放相機算的真值（可見尺寸、捲簾）；錄影中鎖住。

---

## 6. 原廠編碼器能不能出版本 4？（2026-10-29 追加）→ **不能，版本 20 是真的限制**

### 6.1 每個版本的表只有 V20 與 V26 兩份 [驗：反組譯]

選表函式全部寫死成 `version == 0x14`（20）或 `== 0x1A`（26）。遇到其他版本時，回傳全域裡上一次留下的指標，或直接回傳 0。

| 函式 | 內容 | V20 | V26 | 其他版本 |
|---|---|---|---|---|
| `FUN_c05cbdc8` | 對齊圖案位置 | `0xC2DFF27C` | `0xC2DFF29C` | 回傳舊的 `[0xC37CEA30]` |
| `FUN_c05cbe30` | 總碼字數（依 ECC 級） | `0xC2DFF2CC` | `0xC2DFF2DC` | 0 |
| `FUN_c05cbe78` | 資料碼字數 | `0xC2DFF2EC` | `0xC2DFF2FC` | 0 |
| `FUN_c05cbec0` | RS 區塊結構（每個 ECC 級 0x18 B） | `0xC2DFF30C` | `0xC2DFF36C` | 回傳舊的 `[0xC37CEA34]` |
| `FUN_c05cbe08` | byte 容量（閘門） | `0xC2DFF2BC` | 無 | 0 |
| `FUN_c05cbf10` | RS 生成多項式 | EC 長度只有 10、14、16、26、28、30、32 | | V4-L 要 **20**，沒有 |

`FUN_c05cbcc8` 算邊長（4v+17）是通用的；格式資訊 BCH 也是通用的。但上表這些是整套 V20/V26 的資料，不是 40 個版本的表。

### 6.2 unicorn 實跑 [驗]

腳本：`tools/qr/emu_ver.py`。在模擬器裡做了兩件事：把 `0xC05C5C00` 的 `bne`（結構第一個位元組 ≠ 0x14 就拒絕）改成 nop，並 hook `FUN_c05cbe08` 讓它回傳很大的容量。這兩處只改模擬器，相機沒動。

| 版本 | 結果 |
|---|---|
| V20-L（對照組） | 回傳 0，OpenCV 解回原 URL |
| V3 / V4 / V5-L | 在 `0xC05C8978` 讀到未對映位址而崩潰：選表函式回了空指標。在相機上，那個全域會是上一次 V20 留下的指標，結果是用 V20 的表去畫小碼，得到垃圾或越界寫入 |
| V26-L | 回傳 −10（`0xFFFFFFF6`），工作區配置器的 class 上限不夠。V26 比 V20 還大，本來就沒有用處 |

### 6.3 在相機上要怎麼做才能出 V4

至少要動這些地方：
- 自己放一份 V4 的表：對齊位置 {6, 26}、總碼字數 100、資料碼字數 80（L）、1 個區塊、EC 20。
- 自己放 **EC 20 的生成多項式**，原廠沒有。
- 改寫 5 個選表函式加上 `0xC05C5BFC` 的閘門，總共 6 處以上的程式碼補丁，每一處都要經過 claim 與 journal。

這個工程量等於自己寫一個編碼器，風險卻更高，因為會改到原廠讀 QR 也在用的共用程式碼。**不建議。**

### 6.4 修正後的結論

- 要好掃的小碼（V3–V5），就**自己寫編碼器**。精簡版只支援 byte 模式、L 級、固定 V4，約 1.5–2 KB；或用 Nayuki 版，約 5–7 KB。
- 原廠編碼器只適合「版本 20 也能接受」的情況。
- §2 的 observer 貼圖本來就是吃 n×n 的 Y8 矩陣再放大，n = 33（V4）或 97（V20）都一樣，不用改。
  V4 放大 16 倍、加 4 模組靜區是 41×16 = 656 px，放得進 682 列。
- 2026-10-29 Bei：先用原廠 V20，上機掃不到再換自己的 V4。

### 3.4 定案的位元細節（2026-10-29，相機與網頁共用；同日改：網址改 sensor_lab_imx410、加 4 個裁切欄位）
- 依 §3.1 表格順序 MSB 優先，**後面再接 4 個欄位**（Bei 10-29：網頁要畫感光元件裁切、合併、ISP 裁切與縮放）：

  | 欄位 | bit | 來源 |
  |---|---|---|
  | `scw` 感光元件裁切寬 | 13 | `rcp.scw` |
  | `sch` 感光元件裁切高 | 12 | `rcp.sch` |
  | `ww` ISP 視窗寬（合併後像素） | 13 | `rcp.win_w` |
  | `wh` ISP 視窗高 | 12 | `rcp.win_h` |

  資料共 163 + 50 = **213 bit**；欄位值超出 bit 寬一律截掉高位（相機端保證不會超）。
- FPS 選擇：0..28 = STD 索引；29 = 細調／非常用格率；30 = recipe 上限點（31 保留）。STD 優先於上限點。
- AD：0=11、1=12、2=14、3 保留。mh 存 1..3、mv 存 1..6 原值；hbin/vbin 存原值（1 或 3）。
- 1 bit 旗標：recipe 1 = CUSTOM（ISP bin 不是 1x1）、0 = 預設；格式 0 = DNG、1 = MOV；RES 1 = CUSTOM（不在清單）、0 = 清單裡的 K／比例。
- 捲簾 µs：上限 2^17−1。VMAX = 所選格率的 VMAX 步（`fps_at(VMAX) ≤ 所選` 的最小值，= `sq_apply`）。readout key = `cd_key_name` 索引。
- CRC-8：多項式 0x07、初值 0x00、不反射、不 XOR，逐位元（MSB 優先）算前 213 bit，接在後面成 221 bit。
- 補 1 個 0 到 222 bit = **37 個 6-bit**，base64url（A–Z a–z 0–9 - _），不加 `=`。
- 格式版本仍是 1（還沒出貨）。
- 網址：`https://ijigen.github.io/fpSup/sensor_lab_imx410/#` + 37 字元 = 50 + 37 = **87 B**（V20-L 容量 858 B）。
- 實作：相機 `qs/slqs.c` `qr_fields`/`qr_pack`、網頁 `preview/dcres.html` `qrFields`/`qrPack`、
  參考 `qs/test_slqs.py` `qr_pack`（三份由 `QRPayload`／`QR`／`Preview` 測試逐位元比對）。

## 7. live7 之後（2026-10-29 v0.4.1test）：自己的 V5-L、畫在 QR 格子裡
- Bei 改方向：自己的編碼器（V5-L 37×37，87 B 網址放得下；V4-L 只有 78 B），畫在 QR 那一格裡。
- **只有 group 2、3 會呈現** [驗]：`FUN_c0528178(g)` 只對 g = 2、3 回 1，`FUN_c0528700` 只對它們 commit + present。
  live7 註冊在 group 0，畫進的緩衝永遠不會上 LCD。
- **GUI 的 observer** = UIC draw handler 單例 `0xC38D3D0C`（`UicContentsIfBase::v16` 回傳）[驗]，live7 看到它在 group 2 slot 0。
  observer 依 slot 順序呼叫，所以我們放在它後面的 slot。
- `UicDrawHandler::v5`（+0x1C）回 0 [驗]：沒有前→後緩衝複製，三個輪替緩衝各自保留畫過的東西，UIC 只重畫有變的部分。
  所以收掉時要把每個畫過碼的緩衝補回去：client 存一份 UIC 在那塊畫的內容（shadow），逐緩衝還原。
- 原廠「強制全畫」`ReqForceDraw` = `FUN_c0527e68(CYC_DRAW(), {0x101, -1, 0})` [驗]，但強制旗標畫一輪就清（`DrawThread::v1`），只蓋到一個緩衝；沒用。
- 尺寸：格子 256×223，對焦框 = 格子本身（左右 4 px、上下 5 px）；每模組 5 px（0.325 mm），白方塊 205 px。細節在 `qs/README.md` v0.4.1test。
