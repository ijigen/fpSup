# SensorLab 模式頁匯出 RES-Custom 檔(.RCD)—— 離線研究(2026-10-29)

目標:`site/mode.html` 從 QR 解出模式後，多產生一個 `.RCD`,使用者放到卡上，**不載 SensorLab、只靠 RES-Custom** 就能錄這個模式。

本文只讀程式與紀錄，未寫程式、未上機。
- [驗]:讀過程式／資料／上機紀錄
- [推]:推論，待確認

## 0. 結論

- **可以做，但要對準「已發布的 RES-Custom v0.1.4(core 4)」。**
  - 不是 `res-custom/`(core 5)。core 5 是 10-19 的重構，Bei 10-22 定「不發布」。
  - `build_v4_rescustom.py` 檔頭 [驗]。core 4 會拒收 `MINCORE` 5 的檔。
- **RCD 能完整裝下 SensorLab 的讀出方案。**
  - 作法:donor 模式 + 覆寫(override)。把 `core_smc_create` 產出的 8 張表整列寫成覆寫。
  - 7 張表 + R10,扣掉每列第 0 字，一共 244 筆。上限是 256 筆 [驗]。
  - ISP 公式的 31 個字裡，有 28 個正好就是 Res Lab 寫進 `SEC_CANVAS` 的 29 個欄位;另外 3 個是 0x80/0x84/0xB0,不寫進去 [驗]。
- **QR 碼的內容就夠，不用加長。**
  - 網頁先跑 `core_qualities_tol(DC, RES, 不設上限, 1/50)`,再用 (mh, mv, ad, hbin, vbin, key) 找到那個品質，核對 `hm == HMAX`。
  - 然後 `core_quality_plan(q, 72e6, hm×VMAX)` → `core_smc_create`,另外 `core_quality_spec` → `core_isp_plan`。
  - 這跟相機上 `slqs.c:358` 的算法完全一樣 [驗]。
  - 條件:網頁要有**同一版** `core_data.h` 的核心,QR 的 `ver` 欄位負責綁定版本。
- **JS 用 WebAssembly 編 `core.c`,不手寫移植。**
  - `core.c` 是 freestanding C:沒有 libc、沒有 heap、沒有可寫的全域變數。
  - 本機 Apple clang `--target=wasm32 -ffreestanding -nostdlib -c` 一次就編過(45 KB 的 .o)[驗]。
  - 連結還要 `wasm-ld`,要另外裝 lld。
- **格率是最大的限制。**
  - core 4 只給原廠 9 個格率，加上核心固定的 17.98／239.76／279.72(8.99 關著)。
  - SensorLab 的任意 VMAX(48.713、72、90、144…)沒辦法照實錄。
  - 唯一的出路是 `SEC_CAPTURE_TIMING`:把感光元件的時序掛在一個原廠格率(載體)上。代價是 DNG FrameRate 和計時都顯示載體的值，而且這條路沒有有效的上機紀錄。
- **工作量**:離線約 4–5 天，上機約 2–3 天(§5)。

## 1. RES-Custom 的卡上檔案

### 1.1 位置、檔名、啟用 [驗 `res-custom-v4/ogc.c` list_rcd 1865–、load 1842、rc_set `ogc_files.c`]

- 放在 `\fpSup\RESCUS\`,也就是 RES-Custom BIN 所在目錄底下的 `RESCUS`。v4 的 BIN 名稱是 `RES-Custom_v0.1.4.BIN`。
- 檔名:
  - 副檔名 `.RCD`,大小寫不拘;整個檔名最多 11 字元，所以主檔名最多 7 字元。
  - 開頭不能是 `.`,不能是隱藏檔。
  - 只看排序後的前 16 個名字(`RCD_MAX_NAMES`)。
- 身分以檔頭的 `LABEL` 為準：檔名不必等於 LABEL,但兩檔 LABEL 相同時，後者以 `DUPLICATE` 拒收。慣例是 `<LABEL>.RCD`。
- 啟用與名額:
  - 從沒在 RES-Custom 檔案頁改過啟用清單：排序後前 6 個合格的檔自動啟用。
  - 改過：只啟用清單上的檔。新檔要到「fpSup → RES-Custom」檔案頁按 Enable,再重開機。
  - 名額共 6 個;有 Virtual RCD 動態列時是 5 個(`MAX_ROWS = 6`,`ogc_layout.py:149`)。
  - **合併頁預設已經附 5 份 RCD(OG2K/OG35K/OG3K/OG4K/S16),所以只剩 1 格。**
- 檔案在開機時讀，放進卡後要重開機。

### 1.2 二進位格式 RCD1 v3(全部 little-endian)[驗 `res-custom-v4/rcd.py` encode/decode、`ogc_layout.py:193–229`、`ogc.c:1700–`]

**檔頭 64 B**

| 偏移 | 欄位 | SensorLab 檔要填的值 |
|---|---|---|
| 0x00 | MAGIC `0x31444352`("RCD1") | |
| 0x04 | VERSION | 3(core 4 只讀 3) |
| 0x08 | HLEN | 64 |
| 0x0C | FLEN | 檔案總長(4 對齊，≤128 KiB) |
| 0x10 | SUM | **FNV-1a 32**(初值 0x811C9DC5、乘數 0x01000193),算 +0x40 到檔尾。這是唯一的校驗 |
| 0x14 | NSEC | 段數(≤16) |
| 0x18 | SECOFF | 64(段表緊接檔頭) |
| 0x1C | STOCK | 2(錄影時設定區存的原廠解析度 FHD;Res Lab 也用 2) |
| 0x20 | ASPECT | 2/3/9,依 act 比例。Res Lab 的規則：寬×1024/高 > 1934 → 9,> 1678 → 3,其餘 2 |
| 0x24 | FLAGS | bit0 video clamp(Res Lab = 1),bit1 MAG8,bit2 CROP(LABEL 要 ≤6 字) |
| 0x28 | PROFILE | 底 profile:Res Lab 用 83(video 類，公式說的那 34 個共同字) |
| 0x2C | MINCORE | **4**(有 BITDEPTH 段時至少要 4;寫 5 會被 v0.1.4 以 NEWER 拒收) |
| 0x30 | LABEL[8] | 1–7 個英數字元，NUL 補滿，第 8 字元必須是 0 |
| 0x38 | ENUM | 選單用的身分。Res Lab 用 `0x40000000 \| (fnv(label) & 0x3FFFFFFF)` |
| 0x3C | MAXRATE | 所有 mode 中最快的格率 ×100,必須等於 max(MODES.fastest) |

**段表**:每筆 16 B,`{type, offset, length, flags}`。flags bit0 = 必要(不認得就拒收)。PACK 段 64 對齊，其餘 4 對齊。

**core 4 認得的段**

| type | 名稱 | 內容 | SensorLab 用法 |
|---|---|---|---|
| 9 | MODES(必要) | `n` + n×{donor, 最快格率 ×100, hmax, PAL hmax(0 = 同 hmax), x},n ≤ 4 | 1 個 mode:donor = 讀出 key 的 donor(`core_plan.donor`);hmax = `q.hm`;x = smc 出的 TIM +0x0A |
| 2 | VMODES | `n` + n×{donor, kind, offset, value},n ≤ 256 | kind 0–6 = TIM/META/R28/R38/R14/R68/REG(offset 4…stride−4);**7 = R10 值**(offset 0);8 = 放大鏡 ZOOM |
| 3 | CANVAS(必要) | {prev_h, act w, act h, n_rec, n_pb, 0, 0, 0} + 錄影 pairs + 播放 pairs;每組 ≤ 64,offset < 0x108 且 4 對齊 | 錄影 = isp 公式的字(§2.3);播放 = Res Lab 的 13 筆規則 |
| 4 | UI(必要) | 選單列文字 32 B + 摘要 16 B,可列印字元、不含 `,@"`、NUL 補滿 | |
| 5 | PACK(必要) | NBR 圖包(magic `NBR\0`,≥16 B) | `<LABEL>_QS` 86×49、`_SET` 86×74、`_FONT` 150×38;另附兩張 `font_S_imageSize_<寬>`、`<高>`(88×38) |
| 7 | STANDBY | 待機 profile 群組 {cond<<16 \| npids, npairs, pids…, pairs…} | Res Lab 用法:pids 5/210/227/257/258/259,pairs 0x20 = 待機可見寬、0x28 = 待機可見高(isp plan 的 `standby`) |
| 10 | RATECANVAS | 依格率／Crop 的額外 pairs {rank(0 = 全部), crop, base_profile, n, pairs} | 0xB0(hirate):≥100p 設 1、其餘 0;239.76/279.72 那組只在 maxrate ≥ 23976 時要 |
| 11 | BINFILT | {h taps, v taps, h kernel, v kernel, mode},MINCORE ≥ 3 | 直接用 QR 的 hb/vb/kh/kv/km |
| 12 | CAPTURE_TIMING(必要) | {rank, crop, tw0, tw1, engine f32, nominal} | 只在要錄非原廠格率時用(§3.2) |
| 13 | BITDEPTH(必要) | u32 mask:bit0 = 8、bit1 = 10、bit2 = 12;不能是 0 | 見 §6 問題 2 |

`SEC_RATES`(15)／`SEC_WRITER`(14)是 core 5 才有的，**不能寫**。v0.1.4 碰到不認得的必要段，會以 `UNKNOWN` 拒收。

### 1.3 RES-Custom 怎麼用這些欄位 [驗 `ogc.c` vm_fill/vm_override 805–915、gen_entries `ogc_layout.py:361`]

- **虛擬 mode**:
  - 從 donor 複製 7 張表，再依 VMODES 逐字覆寫。
  - R10 先取 donor 的值，有 kind 7 時改用覆寫值。
  - 最後 picker 的時序字蓋掉 TIM +4/+8(hmax\|tail<<16、vmax\|x<<16):「the picker's timing words still win」。
  - 所以覆寫 TIM +4/+8 沒有用，那兩個字是 RES-Custom 每個格率自己算的。
- **每個格率的時序**:
  - `solve(hm, cycles)`:vmax = round(cycles/hm),tail = cycles − hm·(vmax−1),tail 至少 270(`MIN_TAIL`)。
  - 只產生格率 ≤ 該 mode 最快格率的 entry。
  - 原廠 9 個格率 + `VR_TIME` 裡開著的 239.76/279.72(載 119.88)、17.98(載 23.98)。
- **canvas**:虛擬 profile = PROFILE 底列 + CANVAS pairs + 那個格率的 RATECANVAS pairs。
- **容量**:
  - 一個檔最多 4 個 mode、256 筆覆寫。
  - 一次開機最多 16 個虛擬 mode(`MAX_VMS`)、6 列。
  - **覆寫是依 donor id 歸組的。** 同一檔的兩個 mode 若用同一個 donor,會共用同一組覆寫。所以一檔只放一個 SensorLab 模式。

### 1.4 現成的產生器 [驗]

| 產生器 | 語言 | 能不能給網頁用 |
|---|---|---|
| `open-gate/build/res-custom-v4/rcd.py` `encode()` | Python | 參考實作。JS 版照它移植，並用它的 `decode()` 驗 JS 的輸出 |
| `open-gate/build/rl_v3.c` `rl_encode()`(Res Lab,相機上) | C | **canvas 欄位清單、播放 13 筆、待機群組、RATECANVAS 規則、圖包作法**都可以照抄;但它寫 `SEC_RATES/WRITER`(core 5 版),只能用不含那兩段的版本 |
| `build_v3_reslab.py` `literal_xci` + `research/ui/tools/nbr.py` `build()` | Python | 只有字面量(literal)的 LZ4 XCI + NBR 1.5 容器，約 120 行，好移植成 JS |
| `julien-acquaviva/tools/build_rescustom.py`、`ogc_rowdata.py`、`jose_formats.py` | Python | 只用固定配方，沒有公式 |
| merge-v4／card-composer | — | 只附預先建好的 5 份 `.RCD`,**沒有 JS 產生器** |

## 2. 對應：SensorLab 的模式怎麼裝進 RCD

### 2.1 讀出(8 張表)

- `smc.create` 是「沒有 donor 複製」的整列產生器:它直接建出 7 張表加 R10 [驗 `imx410-lab/smc.py:1–4, 137`]。
- 對應作法：每張表從第 1 字到最後一字全部寫成覆寫，每列的第 0 字(mode id)除外。

| 表 | stride | 覆寫筆數 |
|---|---|---|
| TIM | 0x20 | 7(+4/+8 會被 picker 蓋掉，可以省下這 2 筆) |
| META | 100 | 24 |
| R28 | 0x28 | 9 |
| R38 | 0x38 | 13 |
| R14 | 0x14 | 4 |
| R68 | 0x68 | 25 |
| REG | 0x288 | 161(`cd_reg_order[161]`;plan 的感光元件寫入和 fast Family A 都已併進 REG) |
| R10 | — | 1(kind 7) |
| **合計** | | **244(或 242)≤ 256** |

- 整列覆寫的效果，等於 imx410-lab／isp-lab 的 vmode 路徑「8 張表整份換掉」。donor 只提供 mode id 以外、這 8 張表沒涵蓋的東西(放大鏡 ZOOM 表)。網頁不用帶任何韌體表格。
- REG 是全模式共用的一列，不隨格率變;0016(垂直遮沒)是 plan 依 fps 決定的退路。所以 REG 對所有 ≤ 最快格率的格率都成立 [驗 `readout_cfg.py:259–298`]。
- 前例:Jose 的 S16 用 donor 121 加 31 筆覆寫(kind 0/1/2/3/5/6,含 REG),已經上機錄過 [驗 `jose_formats.py:300`]。
- **kind 7(R10)只有 unicorn 測過**(`test_v3_rescustom.py:663`),沒有任何發布的檔用過。
  - 讀出類別跟 donor 不同類時(例如新的 v2/v3 合併 key 的 donor 是 10),R10 一定要對，否則錄出來是垃圾([[vmode-needs-r10]])。
  - 這是第一個要上機驗的點。

### 2.2 格率

- mode 的最快格率可以填兩種:
  - (a) QR 選的那個 fps:最安全，只會開放 ≤ 它的格率;
  - (b) 這個品質的上限 72e6/(hm·vmin)。
- 原廠格率(23.98/24/25/29.97/48/50/59.94/100/119.88)、17.98、239.76、279.72:照實錄。
- 其他 fps(QR 的 STD 表裡有 47.952/72/90/96/144/150/180/200/300/360/400/480/500/600/1000,還有細調):core 4 無法宣告。
  - 只能走 §3.2 的 CAPTURE_TIMING,不然就灰掉。
- 239.76/279.72 走 Res Lab 的「錄影路徑預覽」RATECANVAS 規則，這套規則沒跟 isp 公式 v2 對過。第一版建議最快格率封頂 119.88。

### 2.3 ISP 畫面

- `core_isp_plan` 的 `words/mask` 有 31 個字，偏移是 0x00 0x04 0x0C 0x10 0x1C 0x20 0x24 0x28 0x2C 0x38 0x58 0x5C 0x60 0x64 0x80 0x84 0x88 0x90 0xB0 0xC0 0xC4 0xC8 0xD0 0xD4 0xD8 0xDC 0xE0 0xE4 0xF4 0xF8 0xFC 0x100 [驗 `isp_formula.py:200–208`]。
- Res Lab 的 29 個 canvas 欄位，正好是這些字去掉 0x80/0x84/0xB0 [驗 `rl_v3.c` fields[]]。
  - 0x80/0x84 是平面碼：交給原生位深(8/10/12)。M12240 只開 12-bit 時才把它寫成 7/7。
  - 0xB0 交給 RATECANVAS。
- 不需要 `core_isp_row` 的 65 字底列:底列由相機上的 PROFILE 83 提供。
- 播放 13 筆、待機 0x20/0x28 照 `rl_v3.c` 的規則，從 rec、act、standby 算出。
- BINFILT 直接用 QR 欄位。
- 已知差異 [驗 APPLY_DESIGN §3]:
  - RES-Custom 的 binkernel 站點跟 isp-lab 差 8 bytes(DDF0/DE70 vs DDE8/DE68)。
  - RES-Custom 的 `out`/`aspect`/LV 是用 canvas 自己推算的。
  - 這兩點在虛擬路徑上都沒有跟公式的結果對過。

### 2.4 要灰掉的(附原因)

| 條件 | 原因 |
|---|---|
| AD 14(QR `ad` = 2) | core 4 的位深只有 8/10/12,沒有 RAW14 路線與平面碼 [驗 `BIT_DEPTHS`、VIRTUAL_RCD「RAW14 尚未接入」] |
| 格式 MOV(`fmt` = 1) | RES-Custom 只錄 CinemaDNG |
| fps 不是 §2.2 的 12 個之一 | core 4 不能宣告;要不然走 §3.2(實驗) |
| 最快格率 > 119.88(第一版) | 高格率預覽規則沒驗過 |
| QR `ver` ≠ 網頁的 core 版本 | 表格算不出相同位元 |
| smc／isp 回錯誤(`CORE_E_*`) | 同上，網頁算不出來 |
| hm > 0xFFFF、tail 不夠 | `solve` 失敗，RES-Custom 會拒收 |

AD 11(fast)、R16、2% 寬容配方、CRCT 3×1/1×3 都能裝進去;只是這些在 RES-Custom 虛擬路徑上都沒錄過。

## 3. 建議設計

### 3.1 網頁產生什麼

- 按一個鈕，下載 `<LABEL>.RCD`,一份檔只放一個模式。
- LABEL:例如 `SL` + 5 碼 base36 的 FNV(由 payload 算)。同一個模式永遠得到同名檔，重複放會覆蓋而不是多佔名額。
- 選單列：例如 `SL 3008x2010 2x3`(≤31)。摘要：例如 `3008x2010`(≤15)。
- 段:MODES、VMODES(244 筆)、CANVAS(29 + 13)、UI、PACK、STANDBY、RATECANVAS(0xB0)、BINFILT、BITDEPTH。MINCORE 4。
- 頁面同時寫明：
  - 放到 `\fpSup\RESCUS\`;
  - 名額只剩 1 格;
  - 改過啟用清單的人要去 RES-Custom 頁按 Enable;
  - 放好要重開機;
  - 只開放哪些格率。

### 3.2(可選，實驗)非原廠格率

- 在 `SEC_CAPTURE_TIMING` 放一筆 {載體 rank, 0, hm\|tail<<16, VMAX\|x<<16, 引擎 fps, nominal},感光元件就照 SensorLab 的 VMAX 跑。
- 代價:DNG FrameRate、錄影計時、快門角度都照載體的值，後製要自己改格率。
- 上機紀錄:H2S240／29.97 載體那三段是開著 shell 錄的，結果已撤回 [驗 `res-lab/validation/20261014-carrier-ab/RESULTS.md`]。**等於沒驗過。**

### 3.3 JS 要有什麼

1. **core.wasm**:
   - `clang --target=wasm32 -O2 -ffreestanding -nostdlib` 編 `core.c` + `core_data.h`,用 `wasm-ld --no-entry --export=…` 連結。
   - 約 40–50 KB,不需要 libc。
   - 測試：在 node 對 `core/build/core_host.dylib`(或 Python)逐位元比對 plan／smc 八表／isp words。用 `test_core.py` 現成的 case 集即可。
2. **rcd.js**:
   - 移植 `rcd.encode` 的 core 4 子集、FNV-1a、`solve`/`gen_entries` 的檢查。
   - 驗證:JS 產出的檔交給 `res-custom-v4/rcd.py decode()`;最好再跑 `test_v4_rescustom.py` 的 unicorn `load_rcd`(ogc.c 的實際驗證器)。
3. **pack.js**:
   - 移植 `literal_xci` + `nbr.build`。
   - 圖塊用 canvas 2D `fillText` 畫白字、取 alpha,依 Res Lab 的作法把兩個平面都寫成 alpha。
   - 字型用網站本身的 IBM Plex(OFL),不用 Res Lab 的 Helvetica 字表。
4. **map.js**:QR → `core_qualities_tol` 找品質 → plan/smc/isp → RCD row,以及 §2.4 的灰掉規則。

**不採用預算表**:`preview/fps_data.js` 有 184 KB,而且只有預設的 DC×RES,沒有 smc 表、涵蓋不了自訂 DC×RES。要加 smc 表，每格還要再多 ~2 KB。

### 3.4 工作量

| 項目 | 天 |
|---|---|
| core.wasm(裝 lld、匯出、node 逐位元測試) | 1–1.5 |
| rcd.js + 用 decode／unicorn 驗證器測 | 1 |
| canvas／standby／RATECANVAS 對應(照 Res Lab 規則，逐項跟 isp plan 對) | 1 |
| pack.js(XCI/NBR、圖塊) | 0.5–1 |
| mode.html 介面、灰掉原因、說明 | 0.5 |
| **離線小計** | **4–5** |
| 上機:8 個讀出類別各錄一段(R10 kind 7 優先)、ISP C/E1/E3、CRCT 3、AD 11 | 2–3 |

**附帶價值**:SensorLab 自己的套用步驟(APPLY_DESIGN)走的也是同一條虛擬路徑。這批 RCD 的上機結果，可以直接當成它 V1／V6 的前期驗證。

## 4. 主要風險

1. **公式結果第一次走 RES-Custom 的虛擬路徑。** 633/639 是在 isp-lab 的殼路徑上驗的，換到虛擬路徑要重驗(APPLY_DESIGN §3 已列出)。
2. R10 kind 7 沒上機過。
3. 播放／待機／LV 是 Res Lab 的規則，對任意 DC×RES 不一定成立。
4. 名額:6(或 5)格裡已經用掉 5 格。
5. 網頁的 core 版本一定要跟相機上的 SensorLab 相同，舊 QR 碼要拒收或保留舊版 wasm。

## 5. 要問 Bei 的問題

1. **對準哪一版 RES-Custom?** 已發布的 v0.1.4(core 4,我的建議)，還是等 core 5 發布、改用 `SEC_RATES`(任意格率最多 4 個、DNG FrameRate 正確)?
2. **檔案要開放哪些位深?** 照 Res Lab 一律 8/10/12,還是只開放 QR 的 AD(12 → 只開 12)?
3. **非原廠 fps 怎麼處理?** 直接灰掉;還是提供 §3.2 的載體模式並標明「DNG 格率要後製改」?
4. **最快格率填哪個?** QR 選的 fps(只開 ≤ 它的格率)，還是品質上限(開放所有跑得到的原廠格率)?第一版要不要封頂 119.88?
5. **檔名和選單文字?** LABEL 規則(例如 `SL` + hash)、選單列和 QS 圖塊顯示什麼。
6. 合併頁預設的 5 份 RCD 已經佔掉名額，要不要在頁面上提示「先停用一份」?或者 RES-Custom 要不要擴充名額?

## Bei 回覆（2026-10-29）
- 位元深度：照 Res Lab 開 8/10/12。
- 名額：RES-Custom 已經有開關（啟用清單）處理，網頁不用另外提示擴充。
- 非原廠格率：「到時候 res-custom 也會更新成能支援的吧」——預期 RES-Custom 之後更新支援任意格率。
- 對準版本：Bei 忘了 core 5 是什麼，待說明後再定。
- 2026-10-29 Bei：RES-Custom 匯出「之後再做」（排在 QR 與生效之後）；屆時先定對準 v0.1.4 還是 core 5（建議先 v0.1.4、反灰不可錄格率）。
