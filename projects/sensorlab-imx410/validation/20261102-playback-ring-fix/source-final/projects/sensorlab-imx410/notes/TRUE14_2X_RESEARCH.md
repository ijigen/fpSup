# 真 14-bit 的 2× 縮小：候選路線與 HSEP 實測（2026-10-30）

> **最新H1實測**：§18完成5階段10幀，保住每幀來源後，mux3第一級水平÷3有效，
> bypass與兩筆原廠核都失去最低兩位。前後Crmf保留14-bit低位。舊文「H1未有有效影像」只描述舊T-C。
> 結果限於已測a0抽頭；沒有覆蓋所有未知配置或完整BufA7→SIG錄影路徑。

> **後續狀態**：§9 已有 T-C 上機結果，否定現有 Hbin2 真 14-bit 路線。
> **§10 是 2026-10-30 後續離線追查**：使用者要求只在機內補水平 ÷2，垂直已由 sensor 完成；
> 同時評估借用其他硬體與 RWZM 未解參數。前文「CPU 做不到」沒有跑分支持，
> 「RWZM 只能內插所以不能平均」也過度概括；以下保留歷史推論，現行判斷以 §10 為準。

**目標（Bei）**：真 14-bit、兩軸各 2×，例如 OG 6048×4040 → 3024×2020。
**前提**：`RWZM_14BIT_CHECK.md`（錄影只要經過 RWZM 就是 12-bit 內容；1:1 是真 14）。
標記：**[驗]** 實測或反組譯讀到、**[推]** 推論。資料率一律以緊密 14-bit（1.75 B/px）計算。
「寫卡上限」取原廠實際跑得到的 UHD 12-bit 29.97 ≈ 373 MB/s（SSD）。SD 約 94 MB/s。無損引擎 169.7 Mpix/s（記憶 ljpeg-throughput-measured）。

## 0. 目前結論（§9、§10 更新）

1. **已測的 RWZM 與 CRCT Hbin2 設定會失去最低兩位，但不能據此排除所有機內 RAW 路徑。**
   Crmf 抽頭仍保留 RAW14；T-C 的 Hbin 抽頭 mux 3 未取得有效影像，不能當作成功量過。
2. **PRE_TOP_HSEP 已完成第一輪硬體小圖測試，現行原生路徑仍會失去低兩位。**
   `c01aa030 → c0131410` 的 ÷2 平均、÷2 相加、÷3 都取得有效 RAW14 packed 輸出；
   ÷2／÷3 的 101 都變成 100，÷2 相加為 200。32 次小圖執行正常返回且邊界、輸入與承諾的 shadow 復原通過。
   這只證明目前整條 native memory path 的行為，未隔離前後級截位，不能宣稱 HSEP 電路本身只有 12-bit；詳 §11。
3. **CPU 可以正確計算 RAW14 同色水平平均；實時錄影是否跑得動仍未知。**
   §10 的 ARM NEON 核心已通過 526 個離線測試；只處理 u16 容器，尚未整合 packed RAW14、DMA、cache 與錄影。
   原稿「CPU 做不到」缺少跑分支持，撤回。
4. **RWZM 的平均核與精度要分開問。**
   相位／係數可調，因此原稿「內插不能平均」不成立；但改成平均不會自行救回已截掉的兩位。
   找到幾個未解控制欄位，尚無證據顯示其中有 14-bit 開關。
5. **Julien Acquaviva 的 Discord「RAW-path /3 column bin」仍待對上具體設定。**
   使用者提供引文與作者；沒有原始連結、配置或樣本。不能擅自把該術語等同 CRCT Hbin2，
   也不能因發現 HSEP 就認定 Julien 指它。後續優先驗證 HSEP，詳 §10。

## 1. 新的交叉表：14-bit AD 讀出 × ISP 分支 × 有效位元

用 `isp-lab/host/isp_formula.path()` 依每個 case 的 want 算分支，再對上 RWZM_14BIT_CHECK §6 的有效位元（285 個 14-bit DNG case）。

| 讀出 | 分支（BUFA 來源） | case 數 | 有效位元 |
|---|---|---|---|
| `14` | **D**（a0/a7 mux 1 Crmf，RWZM 關） | 12 | **14** |
| `14` | E3（a1 → RWZM → BUFA1） | 66 | 12 |
| `14` | C（a7 mux 4 Hbin2，RWZM 開） | 112 | 12 |
| `14v2` | E3 | 15 | 12 |
| `14v2` | C | 41 | 12 |
| `14v3` | C | 39 | 12 |

- E 和 C 兩條**不同的 BUFA 出口**都丟掉 2 位，D 沒丟。兩條掉位的路共同的地方是 RWZM 有開（`0x300F0900 = 1`）。
  所以截斷點在 RWZM 本身，或在 RWZM 開著時才會經過的那一段 [推]。單看 E3，就足以排除「只有 Hbin2 抽頭是 12 bit」這個說法。
- **14v2 + RWZM H 2048、V 1024（正好是「V 由感光元件、H 由 RWZM」的 2×2）** 全部是 12：
  `20261027-g1-M121`、`20261028-p1/p5-C87da6120`、`20261028-p7-C424a32a5`（6048×1702 → 3024×1700）。
  4192 寬的 `p6r14/p7-C75c3e294` 也是 12。
- **沒有任何 14v2 在 zoom 1024×1024 的錄影**。這一格是本文最想補的 [驗：matrix 與 validation 都沒有]。

## 2. 候選路線

### C1. 感光元件端合併（不經 ISP 縮放）

| 子項 | 結果 | 證據 |
|---|---|---|
| **14-bit 水平合併**（`0001` = 39 / 38 / 3A，搭配 14-bit Family A） | **不可行**：39 出定值 4094/3837；38 與 3A 配 14-bit 接收端出定值 14611/13958。同樣的合成改用 12-bit Family A 就正常（t2ref），所以幾何與接收端都沒錯 | [驗] L7_14BIT §6 T2，`captures/l7/t2*` |
| 14-bit `0001` 掃描 | 01、03、15、16、18、1A、1B、3A、3D、3E 都是定值，只有 29 和 2B 出影像 | [驗] IMX410_RULES §67，`captures/w14_sweep/eval.json` |
| 外部參考 | Sony flyer 列的 23 個讀出，14-bit 只有全幅與裁切；ZWO：「12-bit 只用於 bin2/bin3」；fp、Z CAM、ZWO、QHY、ToupTek 都沒有 14-bit 合併表 | [驗] ASTRO_IMX410、WEB_IMX410 |
| 水平抽點、間引、次取樣 | 沒有任何已知的暫存器。`0001` 的寬度格式（2B = 4160、18 = 5073、03 = 4016）都是裁切，不是抽點。抽點也不會降雜訊，還會疊紋 | [驗：表內無] / [推] |
| 沒試過的 | 14-bit AD 搭配 `2F`（h3）、`30/31`（÷6）、`34–36`（條帶），以及 12-bit 下就抓不到幀的 33 個碼。這些都不是 ÷2，先驗機率低 | — |
| **14v2（V2，真 14）** | 可行：BUFA0 擷取的 OB 四個餘數都有用到；本文重算 `vbin3_14/vbin2_14` 的 mod 4 = 0.252 / 0.248 / 0.252 / 0.248 | [驗] L7 T1、§66、本文 §3 |
| **14v2 錄 1:1 的變形片 6048×2020，主機壓扁** | **應該是真 14**。BUFA0 的 14v2 是真 14，而 D 路徑（Crmf 抽頭、RWZM 關）錄影保得住 14（`14` 1:1 共 12 case）。但沒有錄過，屬於 [推]，不過推論只差一步 | 見 §1 |

- **RS/fps**（14v2，6048 寬要 HMAX 911，見 R15）：
  - 全高 2020 列：捲簾 911 × 2020 / 72 MHz = **25.6 ms**，感光元件上限約 **36 fps**（§67 在 870 時是 38.2，換算到 911）。
  - 16:9 的 1702 列：捲簾 21.5 ms，上限約 42 fps。
- **資料率**：
  - 6048×2020 每幀 **21.4 MB**：23.976p 是 513 MB/s，超過上限。373 MB/s 時約 **17.4 fps**；無損引擎 12.2 Mpix/幀，上限約 **13.9 fps**；SD 約 4 fps。
  - 6048×1702 每幀 18.0 MB：373 MB/s 時約 20.7 fps。
  - 主機 H2 之後是 3024×2020 的真 14（兩軸都平均，雜訊 ÷2）。

### C2. CRCT bin 不開 RWZM（R2 的機制與繞法）

- **R2 為什麼成立** [驗，CRCT_PATH_SELECTOR_SOLVED §3–4]：
  1. 選擇器 `FUN_c0325228` 看到錄影 RWZM 兩軸都是 unity（≤ 1024 夾成 unity），就走分支 B 或 D。
  2. 這兩支的 a0/a7 mux 都寫 **1 = Crmf**，也就是 bin 之前的抽頭。RWZM 的致能條件是「任一軸 ≠ 1024」，所以 RWZM 關著。
  3. 於是資料沒經過 bin，profile 卻宣告成 bin 後的尺寸，結果是左上角裁切（E1、night1c s1365/s1100、OGN A001_167）。
  4. 只要一軸 ≥ 1025，就改走分支 C（a7 mux = **4 Hbin2**，RWZM 開）→ 12 bit。
     10-27 的 bin4（b3x3-z1025、b3x1-z1025）通過，但那是 12-bit 路線（`want.bits = 12`），對位元寬度沒有資訊。
- **「CRCT h2 + zoom 1024」不存在**：抽頭數只有 1/3/5（`FUN_c022ee10/ee90`），兩筆 reduction record 都只有三抽頭核（`[1 2 1]/4`、`[1 14 1]/16`），
  `isp_formula.HBIN = {1:0, 3:1}`。**CRCT 做不出 2×** [驗]。
- **可以繞的是 ÷3**：讓分支 B 帶 bin 時，mux 從 1 改成 4（Hbin2）。
  - B 的主管線吃的是預覽欄位，而 B 的條件本來就是錄影等於預覽，所以 bin 的設定已經是錄影的。只差抽頭 [推]。
  - 水平 ÷3 還要 binfilt（R3）。
  - B 要求預覽寬 ≤ 2100、高 ≤ 1710：2016×1346 符合。
- **前提還沒量**：CRCT 的 Vbin、Hbin、Hbin2 抽頭是不是 14 bit。L7 T0 量到的「CRCT ≥ 14 bit」是在 **Crmf 抽頭**，在 bin 之前。
- 成品：
  - 14v3 + CRCT h3 → **2016×1346 真 14（3×，也就是 Bei 最早說的「3 列合併 + /3 欄」）**。捲簾 17.0 ms，上限約 51 fps。每幀 4.75 MB：24p 114 MB/s、29.97p 142 MB/s。SSD 可以，SD 不行。
  - `14` 1:1 + h3v3 也是 2016×1346，但捲簾 51 ms、上限 19 fps，不划算。

### C3. 其他資料路徑

| 路徑 | 結果 | 證據 |
|---|---|---|
| RWZM（E 經 BUFA1，C 經 Hbin2） | 12 bit，跟倍率無關（1025 也一樣） | [驗] §1 |
| 換平面碼 | +0x84 = 8 已經是 14-bit RAW 平面，1:1 時完整。RWZM 的位元在平面碼之前就沒了 | [驗] RWZM_14BIT_CHECK §3 |
| 分支 F（`0x30100980` bit4 bypass） | 會把錄影也 ÷3，R5 禁止 | [驗] |
| 拍照或 JPEG 縮放 | LOW 6M 不是縮放器做的：S 尺寸拍照 profile 43/83 用的是感光元件 2×2 的 mode 98/143（12-bit 讀出，RWZM 是 unity），所以本來就只有 12 bit（訂正 10-30 初稿把它當成縮放器證據）。JPEG 縮放器在去馬賽克之後，處理的是 YUV | [驗] OG3K_IS_THE_STILLS_PATH / [推] |
| BUFA 壓縮模式（14 → 8/7） | 有損 | [驗] IMX410_LAB_SPEC |
| 機上 CPU 做水平 2:1 | 約 2.9 億輸入樣本/s（6048×2020×24，已包含 sensor V2）。舊判斷「做不到」未經跑分；§10 有 NEON 正確性驗證與硬體 u16 packing 候選 | [推；§10 更新] |
| **RWZM 可能不是天生 12 bit** | `0x300F0004` bit8（record +0x2D，一直是 1，語意不明）和 BUFA1 的格式設定都還沒排除 | 未驗 |

- 就算 RWZM 能修到 14 bit，它也只內插、不平均：純 RWZM 不降雜訊，z3072 甚至更吵（ISP_CAPABILITY_MAP §0.5）。
  所以「14v2 + RWZM H 2048」只有垂直的雜訊紅利。
- 這條的好處是資料率：3024×2020 每幀 10.7 MB，24p 257 MB/s，SSD 可以。

### C4. 主機端合併（退路）

| 錄法 | 每幀 | 感光元件上限 | 373 MB/s 時 | 備註 |
|---|---|---|---|---|
| `14` 1:1 6048×4040 → 主機 2×2 | 42.8 MB | 19.2 fps（捲簾 51 ms） | **8.7 fps** | 不能當影片用 |
| **14v2 6048×2020 → 主機 H2**（= C1） | 21.4 MB | 約 36 fps | **17.4 fps** | 雜訊與 2×2 相同，資料量少一半 |
| `14` 1:1 4192×2358（裁切，已有真 14 實測） | 17.3 MB | — | 21.6 fps | 裁切，不是 OG |

- 主機 H2 可以放進 cdng-mount：掛載時即時把變形片解成 3024 寬的 DNG [推，該專案已經能即時解 JXL]。

## 3. 離線重算（本文）

- 資料：`imx410-lab/captures/vbin3_14/vbin2_14`（BUFA0、14v2、6064 寬、1500 列、兩幀，2026-10-22）。
  用 `tools/bayer-jxl/bayer_jxl.py unpack` 還原，`decode14(raw, 1500, 2653)` 解碼。
- 影像區的 mod 4 = 0.252 / 0.248 / 0.252 / 0.248，OB 列（37–55）也一樣 → 真 14 [驗]。
- 同色水平 2:1（欄 4k 與 4k+2 平均，4k+1 與 4k+3 平均）。時間雜訊用兩幀相減 ÷ √2：

| 處理 | OB 雜訊（DN14） | 最暗 5% 區塊 |
|---|---|---|
| 1:1 真 14 | 4.00 | 9.63 |
| 1:1 截成 12 bit | 4.16 | 9.68 |
| **H2 真 14** | **2.84** | 6.88 |
| H2 之後截成 12 bit | 3.06（+7.6%） | 6.99 |
| 截成 12 bit 之後再 H2 | 2.96 | 6.93 |

- 這組是待機 AE 的增益（OB 4.0 DN14）。在 0 dB（§54：14-bit 1×1 的讀出雜訊 0.29 DN12 ≈ 1.16 DN14）、2×2 之後約 0.58 DN14，
  加上 12-bit 量化 1.155 DN14 會變成 1.29（約 2.2 倍）[推]。
- 腳本當時放在 scratchpad（branch.py、h2.py、ob.py），沒進 repo。
  要重做：照 RWZM_14BIT_CHECK 的 rows 跑 `isp_formula.path()`；H2 的做法照上面那一行。

## 4. 排名

| # | 路線 | 真 14 | 2×2 雜訊紅利 | 可行性 | 卡在哪 |
|---|---|---|---|---|---|
| 1 | **14v2 1:1 變形片 + 主機 H2** | 是 [推，差一次錄影] | 完整 | 高 | 寫入：約 17 fps（SSD）、約 14 fps（無損） |
| 2 | 14v2 + RWZM H2048（要先證明 RWZM 能 14 bit） | 目前不是 [驗] | 只有垂直 | 低 | RWZM 的位元寬度 |
| 3 | 14v3 + CRCT h3，改選擇器 B 的 mux（**3×**，不是 2×） | 未知 | ÷3 平均 | 中 | bin 抽頭的精度、選擇器 hook |
| 4 | `14` 1:1 全幅 + 主機 2×2 | 是 [驗] | 完整 | 不能當影片 | 8.7 fps |
| × | 感光元件 14-bit H2、CRCT ÷2、拍照縮放器、分支 F | — | — | 死路 [驗] | — |

## 5. 最值得做的上機測試

**T-A（最便宜、直接回答核心問題）**：在 isp-lab 的丟棄錄影流程加一個 case，與已有的 12-bit 組正好 A/B：
`FHD60: 14v2 window 6048×1702, zoom 1024×1024, bin 1×1, bits 14, rec 6048×1702`。

- 對照組是同一個讀出的 M121 / C87da6120（zoom 2048×1024，結果 12 bit）。
- 預測：`isp_formula` 走分支 **D**（預覽 ÷4，`k = max(3, 4, 1)`），HMAX 911（R15）。
- 判讀：DNG 6048×1702、14 bit；`tools/rwzm14/bits.py` 量到 mod 4 四個餘數各約 25%、碼佔用約 1.0。
  再用 §3 的 H2 做出 3024×1702，跟 M121 的 3024×1700 比暗部雜訊與清晰度。
- 通過後再試全高 6048×2020（R12：D 的預覽是 ÷4，不受 1710 列限制）。
- 風險：已知的 14-bit 偶發壞幀，疑似 12-bit 緩衝溢位 1/6。照 RWZM_14BIT_CHECK 排除撕裂幀。
- 這一步不寫卡，所以不涉及 17 fps 的限制。

**T-B（只有在 Bei 要機內 3024 寬時才做）**：RWZM 位元寬度的鑑別。在 T-A 的同一套流程跑一個 `14` + RWZM 1025×1025 的 case，
apply 時把 `0x300F0004` bit8 清掉，看低 2 位會不會出現。也可以在待機用 vmode14 + `host/bufa1.py`，BUFA1 改 14 或 16-bit 格式取一幀。
BUFA1 在待機是 LV 的來源，要記得還原。

**T-C（3× 路線的前提）**：在待機用 vmode14 1:1，直接寫 CRCT 的 bin 暫存器（`0x300F0800/0840/08C0/08C4`），
a0 mux 依序設 2、3、4，BUFA0 用 14-bit enum 各抓一幀，看每一級的 mod 4。不錄影，沿用 `bufa_probe.py frame`。

## 6. 要問 Bei

1. 全 OG 真 14 2×2 只能做到約 17 fps（SSD 未壓縮）或約 14 fps（無損），可以接受嗎？還是改 16:9（6048×1702，約 20 fps），或接受裁切？
2. 「2×」可以在主機做嗎（變形片 6048×2020，由 cdng-mount 掛載時壓成 3024×2020）？還是一定要機內就出 3024 寬的 DNG？
   後者目前沒有路，只能先做 T-B 去賭 RWZM。
3. 真 14 的 **3×**（2016×1346，最高約 51 fps，24p 114 MB/s）要不要列成另一個目標？它要選擇器 hook 加 binfilt，先做 T-C。
4. 真 14 的好處只在低 ISO（錄影 ISO 100–800 同一份 RAW）。產品要不要在高 ISO 直接用 12-bit 容器？
5. T-A 可以排進下一輪 isp-lab 嗎？（不寫卡；上機前照例先通知。）

## Bei 定案（2026-10-30）
- 真 14 2×：不另外做——現有選項已經選得出 14v2 1:1 變形片（例：OG + RES 6048×2020 → 14b 1x2，不經 RWZM），水平 2:1 交給後製。
- 真 14 3×（2016×1346）：列為目標，**先做 T-C 待機實驗**量 CRCT 每級 bin 的精度。
- T-A（14v2 6048×1702 不縮放驗證錄影）：先不要。

## 7. T-C 上機準備：CRCT 每一級 bin 的精度（待命，未上機）

**目的**：回答「CRCT ÷3（Vbin / Hbin / Hbin2）本身保不保得住 14 bit」，這是真 14 3×（14v3 + CRCT h3 → 2016×1346）的前提。
做法：在待機用合成的 14-bit 讀出抓 BUFA0，a0 mux 依序設 1 / 2 / 3 / 4，每一級各抓一對幀。RWZM 在待機是關的
（`0x300F0900` = 0x01010000，bit0 = 0，見 `imx410-lab/captures/crct_m8_m10.json`），a0 這條本來就不經 RWZM。

### 7.1 用什麼工具、什麼 sup

- **工具：imx410-lab 的主機端工具**：`bins.py` 的 `run()` 流程，加上 `fastsweep.Session` 與 `bufa_probe`（mux、還原、safe_stop）。
  - 感光元件寫入用 `sensor_read/spi_read.S`，執行期透過 cave.claim 注入，不是 sup。
  - 抓幀用 `sensor_read/bufa_grabcb.S`（`CAMERA_WAIT=True`）。讀回走 MEM1（EP82 回覆路徑）。
  - **不需要 imx410-lab sup**：IMXB 只有 `--bus` 才用。**也不需要 isp-lab ISPL**：ISPL 是錄影檢查點的控制 task，這次不錄影。
- **卡上需要的是 `\fpSup\USB-Shell_v3.4.0.BIN`**（callfn、MEM1、cave、mem set／get），現在的卡已經有。
- **現在的卡不用換**。2026-10-30 apply1 的 LOAD.LOG 載入了：
  `EarlyFlush_v0.1.0`、`ISPL.BIN`、`Lossless_v0.3.1`、`LUT.BIN`、`QSContainer_v0.2.4`、`SensorLab-IMX410_v0.5.0test`（27 個 claim）、
  `Stop-FX_v0.1.0`、`SUPMGR.BIN`、`USB-Shell_v3.4.0`，加上 `LOADER.BIN`。
- **唯一的條件：SensorLab 必須是 inactive。**
  - 它掛了選擇器 `0xC0325228`、bin 核寫入點 `0xC032DDF0/DE70`、link key `0xC031FFA0` 等 26 個點。
  - 只要 active = 1，進放大（mode 10）時，它可能把我們要的 mode 10 換成它的 vmode，或改寫 mux 與 bin。
  - 開機後**第一次按 MENU 就會 commit 開機紀錄，變成 active 1**（apply1 §3）。所以開機後不按 MENU。
  - 先用 `qs-container/validation/2026-10-30-apply1/apstat.py` 確認 `active=0`。
    如果是 1，就 callfn `sq_test(22)`：位址 = LOAD.LOG 裡 SensorLab 的 block + 0x7111，10-30 那次是 0xC55FF311，r0 = 22，應回 0。
  - 退路：用 All Sups 把 SensorLab 停用（記在 LOADER.BIN 尾的清單），再 `poff 1`。檔案不用動。
- ISPL、Lossless、LUT、QSContainer 不碰 BUFA0 和 CRCT bin，閒置時不動作 [推]。不必移除。

### 7.2 讀出：`v3_14`（14v3，就是 3× 路線的輸入）

`bins.V['v3_14']` = `FAM14`（`captures/l7/fam14.json` 的 37 個 Family A 14-bit 值）+ `L4_NOSET` + `0001=29` + `005D=05`。
- HMAX 911：`0x30100004 = 0x038E038E`。
- 接收端 14 bit：`0x30100800 = 0x00112013`、`0x300E10B4 = 3`。
- yend 1000，BUFA0 enum 1：`l7.rewindow(s, 1)` → 每列 2653 字。
- 這個讀出 10-22 已經實測是真 14（§66）。可選的第二個讀出：`vbin2_14`（14v2）。

### 7.3 每一級的暫存器值

數值來自 reduction record 0（分支 C，也就是 3× 路線會用的那一組）與 `FUN_c0633b30` 的反組譯；
待機時的原值取自 `crct_m8_m10.json`（mode 10）。

| 步驟 | `0x300F0800` V | `0x300F0840` H1 | `0x300F08C0` H2 | `0x300F08C4` | a0 mux `0x300F06B0` | 預期輸出 | BUFA0 列 `0x30182110` × 字 `0x30182114` |
|---|---|---|---|---|---|---|---|
| S0 參考 | 0 | 0 | 0 | 0x102010 | 1 | 6064 × 1000 | rewindow 給的值（約 1000 × 2653） |
| S1 Vbin | **0x00000001** | 0 | 0 | 0x102010 | **2** | 6064 × 約 333 | **320** × 2653 |
| S2 Hbin | 0 | **0x00000001** | 0 | 0x102010 | **3** | 約 2021 × 1000 | 1000 × **882**（2016·7/16） |
| S3 Hbin2 | 0 | 0 | **0x00000001** | **0x00102010** | **4** | 約 2021 × 1000 | 1000 × 882 |
| S4 V + Hbin2 | 0x00000001 | 0 | 0x00000001 | 0x00102010 | 4 | 約 2021 × 333 | 320 × 882 |
| S5 控制組 | 0 | 0 | 0 | 0x102010 | 4 | 6064 × 1000（mux 4 但沒有 bin） | 同 S0 |

- 係數保持待機原值（record 0 的 `[1 2 1]/4`）：
  `0810 = 0x08000400`、`0814 = 0x04000400`、`0818 = 0x04000800`、`081C = 0x08000400`、`0820 = 0x400`；
  `0850..085C = 0x00102010`。
- V 代碼 0x1 的依據：`+0 = 2`（垂直 ÷3）→ 低 4 位 = 1；record 0 的 `+1 = 3` → bit16 = 0（FP3K trace 的分支 E 用 record 1，寫的是 0x10001）。
  H 的 bit16 = (record `+0x1B` == 0)，record 0 是 1 → 0。
- **DMA 的列數與字數故意比實際輸出小**（320 < 333；882 字 = 2016 px ≤ 2021）。這樣每一幀一定會觸發完成中斷，不會出現「DMA 等不到資料」再被從中間切斷的情形（§70 的凍結）。
  - 多出來的像素會換到下一列，或跨到下一幀，畫面可能撕裂或錯位。但精度只看樣本值，不受影響。
  - 列數與字數要在 `rewindow` 之後直接寫。`s.size`、`s.tail`、`s.guard` 要跟著換成「列 × 字 × 4」，否則 grab_cb 的哨兵永遠等不到。
- **S2 沒有變窄**（畫面寬度仍是 6064、像素沒有被平均），代表第一級 Hbin 在 `0x300F0870 = 0` 時不會作用。
  這時重跑 S2，把 `0x300F0870` 設成 1（分支 E 的 main hvbin_bypass 值），還原時記得寫回 0。

### 7.4 步驟（每一步都等上一步回來才送）

0. 上機前先通知、廣播使用權。CINE 待機、不錄影、不回放、插著 USB、shell ping OK。場景要有紋理和暗部。不按 MENU。
1. 跑 `apstat.py`，確認 `active=0`。`imager mode_now` 要是 0008。
2. `F.cached_assemble()`，再 `s = F.Session(out, 1000, True, 10, min_alloc=24<<20)`。
   這一步會進放大 mode 10、記錄基準、配兩塊 class-10 緩衝，讓 BUFA0 跑在 scratch。
3. 讀出：`B.startstop(100)`（safe_stop），然後 `l7.batch(regs)`。
   - SoC：`B.wr(0x30100004, 0x038E038E)`、`B.wr(0x30100800, 0x00112013)`、`B.wr(0x300E10B4, 3)`。
   - 等 0.3 s，`l7.rewindow(s, 1)`，再等 0.5 s。
4. S0：`s.grab(out/'S0_mux1')`，抓一對幀。
5. S1–S5 每一級：
   1. `B.startstop(100)`，走 safe_stop，在 ISR 裡停在幀與幀之間。
   2. 用 `B.wr` 寫 7.3 表裡這一級的 bin 暫存器與 `0x300F06B0`，每筆都讀回驗證。
   3. 寫 `0x30182110/2114`，並更新 `s.size/tail/guard`。
   4. `B.call(B.F_SETADDR, s.scratch)`，然後 `B.startstop(10)`，等 0.3 s。
   5. `s.grab_cb()` 兩次，抓一對幀。存 frame.json（mux、bin 值、列、字、bits 14）。
   6. `B.startstop(100)`，把 bin 暫存器寫回原值（0800 = 0、0840 = 0、08C0 = 0、08C4 = 0x102010、0870 = 0），mux 寫回 1，
      列與字寫回 rewindow 的值，`B.startstop(10)`。
6. 收尾：`s.write(0x0018, 0)`、`s.write(0x005D, 0x03)`、`s.close()`（`B.restore` + 歸還緩衝 + 離開放大）。
   接著**一律 `sweep.fastreboot()`（`poff 1`）**：14-bit 的 key-2 link 狀態只有重開才會清（L7 §5）。重開後檢查 mode_now、ping，再自動對焦。
- 實作：照 `bins.run` 寫一個 `tc_stages.py`，執行期才建，屬於工具修改，上機前要 Bei 同意。
  它只多做三件事：每一級的 POST 寫入、`s.size` 跟著改、bin 暫存器的明確還原。
  `bufa_probe.RESTORE` 涵蓋 mux、a0 crop、接收端視窗與 BUFA0 暫存器，**但不含 0x300F08xx**，所以 bin 要自己還原。

### 7.5 凍結風險與救法

| 風險 | 來源 | 防法 | 救法 |
|---|---|---|---|
| 在幀中途停 BUFA0 → 整機凍結 | §70 | 一律 safe_stop。DMA 幾何小於等於實際輸出，保證每幀都有完成中斷。grab_cb 在 1 s 內等不到完成時，**先把 bin 和 mux 還原成全幅再停**，不要直接停 | 拔 USB → 撥開關冷開機 |
| 主管線 bin 也作用在 LV（分支 A 的主管線吃預覽，BUFA1 → LV） | [推] | 每一級只開到抓完一對幀為止。我們不停 BUFA1 | LV 黑或卡住：先還原暫存器；沒恢復就 `poff 1` |
| 配置器卡死（class 10、全幅 14-bit） | §67、fastsweep 註解 | 進放大後固定等 1.5 s，只配一次 | `poff 1`；shell 沒回應就冷開機 |
| 14-bit session 卡死（用掉完成旗標） | §71 | 用 grab_cb、safe_stop（不用旗標版本） | 同上 |
| callfn DID NOT RETURN 或 echo 槽沒還原 | skill fp-firmware-call | fastreboot 會先還原 echo | 冷開機 |
| SensorLab 改寫 mux／bin | 7.1 | `active=0`，不按 MENU | 停用後重開 |
| 錄影或回放中碰 BUFA | 記憶 | `B.not_recording()` 擋著 | — |

### 7.6 判讀（「CRCT ÷3 保得住 14 bit」的定義）

每一級兩幀，用 `decode14(raw, 列, 字)` 解碼。指標沿用 `tools/rwzm14/bits.py` 的 `analyse()`：
mod 4、mod 2、mod 16 分布與熵、p2–p98 碼佔用、最平坦 16×16 綠塊的佔用、最暗 5% 的佔用。
`analyse()` 吃的是 DNG，所以要加一個薄包裝，把陣列餵給同一套算式（`tc_bits.py`，執行期才建）。

另外要確認拿到的是真影像（記憶 checks-pass-degenerate-frames、checks-must-be-colour）：
- 兩幀的時間雜訊 > 0（不是舊緩衝或定值）；
- 同色鄰點差 dx2 小；
- R/G、B/G > 0.3；
- **這一級真的有 bin**：S1 的列內容是 S0 的 1/3 尺度、S2–S4 的寬度是 1/3。拿 S0 降採樣後做相關，r ≥ 0.85。

| 結果 | 判讀 |
|---|---|
| mod 4 四個值各 0.25 ± 0.02（熵 ≥ 1.98）、mod 16 熵 ≥ 3.9、佔用 ≥ 0.9，兩幀都是，而且真的有 bin，同一 session 的 S0 也是真 14 | **這一級保得住 14 bit**（≥ 14；`[1 2 1]/4` 的 /4 也許有更多小數位，但 BUFA 只寫 14 位） |
| mod 4 = 0 的比例 ≥ 99%、佔用約 0.25 | 這一級是 12 bit（跟 RWZM 一樣） |
| mod 2 = 0 的比例 ≥ 99%，但 mod 4 有 0 和 2 | 13 bit |
| 寬度或列數沒變、跟 S0 逐像素相同 | 這一級沒作用：S2 要加 `0870=1` 重做；其他級屬於無法判讀，不是 14 bit |
| S5（mux 4、沒有 bin）跟 S0 不同 | Hbin2 抽頭本身有處理：記下來，不影響判讀 |

**決定 3× 路線的是 S3（Hbin2，因為 14v3 + h3 走的是 Hbin2 抽頭）**。S1、S2、S4 是附帶的資料。
- S3 通過：下一步才是選擇器 B 分支的 mux 1 → 4 hook 加 binfilt，再錄影驗證。
- S3 是 12 bit：本節提出的 **CRCT Hbin2 3× 路線**不成立；不能排除其他 RAW 路徑（§10）。

## 8. Bei 的方案 A：RWZM 跑兩次保住 14 bit（離線評估）

方案：第 1 次餵 `x>>2`，第 2 次餵 `(x&3)<<10`，重建 `4·A' + B'/1024`。

### 8.1 數學：照原樣做沒有改善 [推，可證]

RWZM 是線性內插：輸出 = Σ wᵢ·xᵢ / 1024。權重是 16 相位的表，`0x300F0940..095C`（另一組 `0980..099C`）在待機讀到的值是
1024、1013、980、930、864、787、700、608、512、417、324、238、160、95、44、12：一條平滑的升餘弦曲線，權重 10 位 [驗 讀值；用途 推]。

- 第 1 次的輸出 A' = Q(I(x>>2)) 是 12-bit 整數。I(x>>2) 本身帶小數（內插），被 Q 捨去。
  重建時 ×4，誤差範圍 ±2 DN14、σ ≈ 4/√12 = 1.15 DN14，**跟直接截成 12 bit 一樣**。
- 第 2 次只救回 `x&3` 那一部分的內插，救不回第 1 次被捨掉的小數。
- **例外：只有在 I(x>>2) 剛好是整數時才完全重建**。也就是 2048 相位 0 的純抽點（`0x00000800`，相位 0），權重 1024/0。
  但那等於丟掉一半的欄，沒有平均，不如主機自己抽。
- 「捨去還是四捨五入」只會差 0.5 LSB12 的偏移，σ 一樣。現有資料看不出來：12-bit 路徑沒有丟位，14-bit 路徑是恆 0，兩種都相容。
  要分清楚需要已知斜坡輸入。不影響本結論。

**改成可行的版本：「暗部通道」**。第 2 次不餵殘差，改餵整個值，只是放大 ×4 再裁頂：
- CRCT 數位增益 Q8.8 `0x300F0310/0320` 以 pedestal p 為支點：`out = p + (x − p)·G`。
  白位 `0x300F0308 = 0x4000 − p` 會裁頂 [驗 §12：0x154 / 0x208 都實測過]。
- G = ×4（`0x400`）時，RWZM 截掉 2 位以後看到的是 `p/4 + (x − p)`，**每階 1 DN14**。
  只要訊號在黑位以上 3839 DN14（14-bit 白位以下約 2 級）內都不會裁頂。
- 重建：所有抽頭都沒裁頂的像素（第 2 次輸出 < 裁頂值 − 餘量），用第 2 次的值（σ_q ≈ 0.29 DN14）；其他像素用第 1 次 ×4。
- 截斷雜訊只在暗部有意義（亮部被散粒雜訊蓋掉：3839 DN14 時約 28 DN14），所以這個切法剛好夠。
- **前提一樣：同一幀要經過 RWZM 兩次。**

### 8.2 能不能從記憶體再餵一次 RWZM

- **RWZM 在 CRCT 裡**（`0x300F0900/0908/090C`，`FUN_c0633e60`），串在即時資料流上：接收端 `0x3010` → CRCT → a1（`bufa1 : CrctRwzmToBufA`）→ BufA DMA → DRAM [驗]。
- 韌體字串裡的 CRCT 出口只有 13 個「`Crct… ToBufA`」（a0/a7 各 6 個 + bufa1 一個），**沒有任何「BufA → Crct」或從記憶體讀進 CRCT 的路徑** [驗 字串掃描]。
- 0x3016 的 SIES / COPY / RDMA 都在 SIG 那一側（BufA 之後）：
  - COPY `0x30160200..`（`FUN_c00fb418` 寫來源、目的、尺寸，然後 `0x30160230 = 1` 啟動）是 DMA 複製；
  - RDMA `0x30160600..62C`（`FUN_c019e670`，8 個位址欄位）是 SIG 讀記憶體；
  - 機內 RAW 顯影（`Development1..9`、`RawDeveloperSimulator`）也走 SIG。
  - **它們都接不到 CRCT／RWZM 的輸入** [推：沒有找到任何寫 CRCT 輸入選擇的程式碼；接收端只接 SLVS-EC PHY]。
- 有**兩個** RWZM：主 `0x300F0900` 和副 `0x300F2900`。分支 F 會讓兩者同時處理同一幀（錄影 + 預覽）[驗 選擇器]。
  - 但數位增益在分岔之前，只有一份 [推]，副管線也沒有自己的增益或位移級（`FUN_c0633da0` 只寫 bin 與係數）[驗]。
    兩支看到的是同一份 `x>>2`，做不出兩種輸入。
  - 加上 R5：F 會把錄影也 ÷3，現在禁用。所以不可行 [推]。
- 唯一能做出「兩種輸入」的是**時間交替**：逐幀切換 `0x300F0310`（×1 ↔ ×4），像 IMXB 的時間交替 HDR 那樣。
  - 代價：錄影 fps 減半；有動態時暗部與亮部來自相鄰兩幀，邊界會錯位；
  - AE 每幀會重寫 `0x300F0310`（§12 的增益分層），要掛 hook 才能交替。

### 8.3 RWZM 之前能做位移、遮罩、增益、偏移嗎

| 級 | 能做什麼 | 證據 |
|---|---|---|
| CRCT 數位增益 `0x300F0310/0320`（Q8.8，0x100 = ×1，以 p 為支點，裁到白位） | ×¼ 與 ×4 都在範圍內 → 可以做「增益 + 偏移 + 裁頂」 | [驗] §12 實測 0x154 / 0x208 |
| pedestal `0x300F0318/031C`（0x100..0x700，DCLP 每幀調整）、白位 `0x300F0308/030C` | 偏移與上限 | [驗] |
| 「×3.996」 | 是 12-bit AD 換算成 CRCT 14-bit 單位的增益加偏移（L7 T0），不是可以設定的位移 | [驗] |
| 位元遮罩 `x&3`、取模 | **沒有這種級** | [推：CRCT 暫存器與 mux 名稱沒有] |
| 平面碼（+0x80/+0x84） | 是 BUFA 的打包格式，在 RWZM 之後 | [驗] |
| 8-bit 的 LinearizationTable 正向曲線 | 位置不明；它對應的是寫出時的 8-bit 壓縮，在 RWZM 之後的可能性高 | [推] |

所以：做不出 `x>>2` / `(x&3)<<10`，做得出「×4 加裁頂」。

### 8.4 輸出量與時間

- RWZM 跟著感光元件的行速率串流，不是可以排程的記憶體對記憶體引擎。一幀只能過一次 [推]。第二次只能用下一幀（時間交替）。
- 時間交替的上限：14v2 6048 寬約 36 fps，所以輸出約 18 fps。要 24p 輸出，感光元件要跑 48 fps，做不到（6048 寬時 HMAX 911）。
- 4192 寬（HMAX 870）也只到約 2×24 的邊緣。
- 主 RWZM 會和 LV 共用：待機時它輸出 BUFA1 給 LV（8-bit 2016×1344）[驗 PUSH_CALLERS]；錄影時給錄影，預覽走另一支。
- 結論：**方案 A 照原樣在數學上沒有好處；改成暗部通道後數學可行，但硬體只給得出時間交替**（fps 減半、動態會錯位）。
  不建議當產品路線，除非 T-C 的 S3 失敗，而且 Bei 接受「靜態場景、半格率」這個代價。

## 9. T-C 結果（2026-10-30 上機，`validation/2026-10-30-tc/LOG.md`）
- **[驗] 本次成功取得影像的 CRCT bin 抽頭，在所測設定下只有 12-bit 內容**：
  - mux 2（Vbin 抽頭）、mux 4（Hbin2 抽頭）不 bin 時低 2 位都恆 0；Hbin2 實際 ÷3（2016 寬、完整視野）也恆 0。
  - 同一 session 的 mux 1（Crmf）是真 14：mod 4 各約 0.25、熵 4.0、佔用 1.0。
- ⇒ 本文原先提出的 **CRCT Hbin2 真 14 的 3×**（§2 C2、§4 #3）不成立。
  在本次有效樣本中，只有 Crmf 保留 14-bit；這不排除 §10 的其他 RAW 處理單元或未測設定。
- 附帶：
  - 待機時 `0x300F0800`（Vbin）每幀被韌體改寫，`0x300F08C0`（Hbin2）則會保住；
  - BUFA0 的 `0x30182114` 不會限制 DMA 寫入的量（行長是真實行長）。

## 10. 後續：只補水平 ÷2，RAW path、其他硬體與 CPU（2026-10-30）

本節全部為離線分析。沒有操作相機、部署 probe、修改錄影管線或量測實機吞吐。
目標是 **sensor 已完成 V2，再對同一 Bayer 列的同色樣本做 H2**，不重做垂直合併。
下文「保 14-bit」指保留 14-bit 輸入的低位資訊並得到 14-bit 範圍的平均結果，
不是保留未除以二的 15-bit 總和，也不是宣稱感光元件的有效類比精度等於 14 bits。

### 10.1 使用者引文與證據邊界

使用者提供以下說法，並確認作者是 **Julien Acquaviva，在 Discord 發言**：

> Careful the fp’s RWZM scaler only carries 12 bits, so any scaled or 2x2-binned mode keeps the 14-bit ADC’s lower noise (higher rolling shutter!) but records 12-bit values in a 14-bit DNG. True 14-bit only survives 1:1 recording, or a 3x3 using the sensor’s 3-row merge plus the RAW-path /3 column bin

本輪沒有取得該 Discord 訊息連結、上下文、配置或樣本。因此：

- `RAW-path /3 column bin` 是作者用語，不能自行等同 CRCT Hbin2。
- T-C 排除的是已測 Hbin2 路線；mux 3 Hbin 未獲有效影像，也不能當作成功量過。
- 韌體 `FrameExpos_s/rawpath.c` 的 `raw_hvbin` 欄位確實對應 CRCT 枚舉，
  但這不替 Julien 的自然語言定義硬體單元。
- 本地 Julien R120 分析只有 M100 的 crop RAW14 與原生 12-bit LQ 3×3，
  未找到這段聲稱的實作；舊版本資料不能否定他在 Discord 提到的另一方案。
- [HDMI RAW audit](../../../research/interfaces/notes/HDMI_RAW.md) 的 28 profiles 只閉合到 CRCT 配置，
  不足以排除後段 SIG 的 RAW 處理。

### 10.2 第一順位候選：PRE_TOP_HSEP

**[驗：靜態] `FUN_c01aa030 → FUN_c0131410` 是記憶體 RAW 處理入口，
有與 CRCT Hbin2／RWZM 分開的水平 ÷2、÷3 配置。**
`out/decomp/full/blk_c01.c:33315–33322` 計算縮後寬；`33440–33447` 改輸出 DMA 寬。
高度沿用輸入（除非另外指定 output height），符合只做水平方向的需求。

| `c01aa030` 外部參數 byte offset | `c0131410` 內部 byte offset | HSEP control bits[1:0] | 輸出寬 |
|---|---|---|---|
| `+0x47 = 1`，`+0x48 = 0` | `+0x46 = 1`，`+0x47 = 0` | `01` | W/2 |
| `+0x47 = 0`，`+0x48 = 1` | `+0x46 = 0`，`+0x47 = 1` | `00` | W/2 |
| `+0x47 = 0`，`+0x48 = 2` | `+0x46 = 0`，`+0x47 = 2` | `10` | W/3 |

外部／內部結構偏移不同（`blk_c01.c:94608–94610`），不能混用。
此表只列無衝突的單一模式配置；不要同時啟用兩個不同縮寬 flag。

- `blk_c01.c:33487–33503`：寫 shadow `0x302109A4` 低兩位、清 bit16，
  `0x302109B0` 設定水平範圍。
- `blk_c01.c:84643`：descriptor 將 `0x302109A4` 的 9 words 映射到 `0x30114000`；
  `50070` 附近的診斷名稱是 **PRE_TOP_HSEP**。這是有實際 setter 的硬體，不只是猜區塊名稱。
- `c0131410` 內部 `param[0xE]`／`param[0xF]` 是輸入／輸出格式。
  輸出格式在 `33432` 原樣送給 DMA descriptor，沒有因縮寬而強制設 12-bit。
  `c014cfd0` 的 case 1 明確配置 RAW14 packing（`44782–44790`），case 2 配置 16-bit。
- `XC_SigproRawMakePreview`（`c04321a0`，`blk_c04.c:33590` 起）實際使用 mode `00` 的水平 ÷2，
  後面另接 `c01a9b20`。這個 wrapper 自己選 output enum 0（12-bit），
  **不能把 wrapper 的預設格式當作 HSEP 的固定位深**。
- 在本次已查的直接 caller 中，尚未找到 mode `01`／`10` 的常數啟用實例。

**尚未確認**：模式是同色平均、抽點、拆分還是其他運算；內部資料寬度；
捨入與飽和方式；CFA 相位；這條路是否就是 Julien 指的 RAW-path。
HSEP 的名稱與 DMA14 輸出都不足以證明上述事項。
目前未找到可解釋算式的 tap／係數設定；不能把 W/2 直接寫成「已證明 H2 binning」。

建議的最小後續驗證（尚未執行）：

1. 從兩個 H2 mode 與 H3 mode 各跑已知的小型 RAW14 記憶體圖；只啟用水平階段，固定輸出高。
2. 交錯色常數和逐位置單點訊號，分辨同色平均、相鄰異色混合、選點、裁切；分別檢查偶數／奇數列。
3. 固定高 12 位，只改低兩位的輸入組合，與完整 RAW14 參考及「先截 12-bit 再算」參考比較。
   H2 的 `(100,100)` 與 `(101,101)` 應能分辨；接近 `0x3fff` 的值另查飽和。
4. 確認算式與精度後，才量全幅 V2 的實際速度、排程與錄影輸出。

單看輸出的 mod 4 四種餘數都有出現不足以證明保真：12-bit 內插也能生成低位。
必須證明**輸入最低兩位會按預期改變輸出**。

### 10.3 CPU：算術已驗證，實時效能未量

原型與完整結果在 [h2_neon_offline/README.txt](../tools/rwzm14/h2_neon_offline/README.txt)。
實際編譯的 ARMv7 NEON 指令已在 Unicorn 執行，**526 cases PASS**；
包括所有 CFA 起始相位、低位捨入、邊界值、隨機列、讀寫界限、來源不變及暫存器保存。
將 rounded average 改成 truncating average 的 mutant 會失敗。

正確算式是同色相加：

```text
輸入：R0 G0 R1 G1 R2 G2 R3 G3 ...
輸出：avg(R0,R1) avg(G0,G1) avg(R2,R3) avg(G2,G3) ...
avg(a,b) = (a+b+1) >> 1
```

另一列照自己的 CFA 相位獨立處理，不混合上下列。
核心每 16 個輸入樣本用 3 個向量指令與 2 個 loop 指令，讀 32 bytes、寫 16 bytes；
這是 **5 個指令，不是 5 cycles**。52-byte kernel 的 SHA256：
`66073162da74bdd73f0a16c58da3ad122558d98f52b5aa6e5eeb2e7c9f439320`。
只用 q0–q1，不超出本機已知 RTOS 的 d0–d15 保存範圍；執行 task 仍須有適當 VFP context。

限制：目前只吃 little-endian、右對齊的 u16 RAW14；寬須為 16 的倍數，來源／目的分離，
沒有 packed RAW14 unpack／pack、列 stride wrapper、hook、DMA/cache 同步或相機效能測試。
模擬器選 Cortex-A7 不代表已讀取本機 MIDR 或確認時脈。

**硬體格式候選**：BUFA 原始 RAW14 為 packed14，平面碼 8 的配置大小不代表 DMA 一定輸出 u16。
`c06306e0`（`blk_c06.c:43604` 起）格式 enum 1 設 14-bit packing、row words = `W*7>>4`；
enum 2 設 16-bit、row words = `W>>1`。BUFA1／7 也有對應格式 setter。
所以有硬體 unpack／pack 的方向可追，但不能只改全域 enum 而忽略 pitch、buffer allocation 與 writer。
`c014cfd0` 等 SIG DMA helper 也具備 RAW14／16-bit 格式。

以 **6048×2020 → 3024×2020**、十進位 MB 計算，不含 OB、padding：

| 每秒資料量 | 24 fps | 30 fps |
|---|---:|---:|
| packed14 輸入讀取＋輸出寫入的最低流量 | 769.7 MB/s | 962.1 MB/s |
| u16 輸入讀取＋輸出寫入 | 879.6 MB/s | 1099.5 MB/s |
| 縮寬後 packed14 錄影資料 | 256.6 MB/s | 320.7 MB/s |

這還不含 sensor DMA 寫入、writer 再讀取、預覽與 cache 流量；簡單的全記憶體流程會再增加約同量的幀讀寫。
既不能只因每秒約 2.9 億輸入樣本就說 CPU 做不到，也不能只看 NEON 指令少就說能達 24/30p。
舊測得的 72.3 MB/s 是特定 uncached mirror copy，不是整機記憶體或 CPU 的總上限。
目前首要未知是實機完整資料路徑吞吐。

### 10.4 RWZM：平均與保留位元是兩個問題

**[驗：靜態] 尚有可查參數，但沒有找到 14-bit 開關。**

- `c0101c30`（`blk_c01.c:1291–1318`）完整 setter 包含 `0x300F0900` 的 bit16／24、
  `0910`、`0914` 四個 byte、`0918`，以及 H/V 各 17 個係數。
  原廠初始化值為 flags 1/1、`0910=16`、`0914={16,8,16,8}`、`0918=0`。
  這些未解欄位是查證對象，不能逕自稱為量化開關。
- `c0634038`（`blk_c06.c:46071` 起）可分開寫 H/V ratio 與 phase；
  `c017f990` 存在 phase `0x200` 的原廠 caller。
  H ratio 2048 加適當相位可能形成等權取樣，但相位單位、CFA 對應及實際 tap 還要驗。
  內插可以構成平均，所以「RWZM 內插，不能平均」應撤回。
- `0x300F0004` bit8 在 `c06340c8` 與 window `06A0/06A4/06AC` 一起設定，
  且有 bit12／16／20 平行 window；它更像視窗 gate，沒有精度開關證據。
- BUFA1 初始化雖設 12-bit，後續 `c0630e90` setter 也允許 14／16。
  但現有 E3 RAW14 輸出已失去低兩位，所以只改最後容器未必能解決。

現有 273 個 RWZM case、766 幀仍是強證據：**已測配置會丟兩位**。
未知寄存器不等於存在可用 RAW14 模式；相反地，這些實測也不能形式上證明所有未測配置均不可能。

### 10.5 借用其他機內單元

| 候選 | 已有證據 | 主要缺口 |
|---|---|---|
| **HSEP** | 水平 ÷2／÷3 setter，RAW14 DMA 格式入口 | 算式、內部精度、CFA 與吞吐；第一順位 |
| **RawMix／FPNR** | `XC_SigproRawMix c0426ed0 → c01a9b20 → c0132d20` 有兩路 RAW 位址、可調權重與 `0x3fff` 上限；shadow `3021028C` 映射 `30112300`，診斷名 SIG0_FPNR | 是否能餵同一列相差兩樣本並等權平均；對齊／邊界；還需要縮寬，未驗 |
| CPU NEON | 同色 H2 算術已通過 526 個離線測試 | packing、buffer／cache／排程、實機 fps |
| SIG1_RAW_ZOOM | `30113380` 的 descriptor 與診斷名稱 | 未找到實際 setter，弱於 HSEP |
| SIG1_RAWOUT | `c0156b90` 有 setter | 已見欄位是裁切／拼接幾何，不能把 mask 位寬當像素精度 |
| COPY／一般 DMA | 複製、搬運、格式轉換 | 尚無同色相加證據，單獨不能完成平均 |

RWZM、HSEP、FPNR 在這裡都是影像處理 SoC 內的單元，不應當成可獨立替換的外接晶片。
本輪優先順序為 **HSEP 像素語義／位深驗證 → CPU 實機吞吐 → FPNR 借用**；
RWZM 未解欄位保留為旁線。沒有足夠證據支持「機內完全沒辦法」，也還沒有完成的 RAW14 H2 錄影方案。


## 11. HSEP 第一輪實機（2026-10-30）

證據：`projects/isp-lab/validation/hsep-20261030-live/report.json` 與每個 case 的
`request.json`、`status.json`、`input-u16le.bin`、`output.bin`、`analysis.json`。
確切 HSEP.BIN：2,124 B，SHA256 `b58393d07bbfa9e3b35ecf3e93fd37a8cc56d0eb67cb9c5f26976838fae2c464`。
載入位址 C4F94000、task124；獨立 v4 常駐區，沒有改 ISPL／ISPC ABI 或掛錄影 hook。

- 32 次 96×8 小圖測試全部 native_rc=0、預期寬度、guard完整、輸入hash相同；bank1 HSEP九字與LM[0] shadow復原一致。
- **格式校準**：host 的 MSB-packed RAW14 與 native endian=1 相符。
  endian=0 的 packed 結果無法用同一 decoder 解讀，不能當低位元保留證據。
  u16/endian0 的100→96與RAW14/endian1的100→100不同，因此精度結論只用已校準RAW14資料。
- **mode0（寬÷2）**：100/101/102/103→100，104→104。脈衝10000→同色輸出5000。
  斜坡、CFA、脈衝、高光同時符合「輸入先清低2位→每兩個同色像素平均→輸出清低2位」模型。
- **mode1（寬÷2）**：101→200；斜坡與脈衝符合兩個同色像素相加，RAW14輸出高光飽和於16380。
  相加增加數值，沒有恢復輸入被丟棄的低兩位。
- **mode2（寬÷3）**：101→100；12000脈衝放在x=0/2時，輸出x=0都是6000；放x=1時沒有輸出。
  x=3/5則落在輸出x=1，x=4被略過。現有圖樣符合每三欄取首尾同色兩點平均，
  即`R G R / G R G → avg(R,R),avg(G,G)`，**不是三個同色點的等權平均**。
  所有已校準的輸出仍為4的倍數。

這是硬體 HSEP 的 native memory-path 試驗。CPU只設定與取回資料；沒有做像素平均。
尚未證明可接入錄影串流、全幅吞吐或持續穩定，也未證明這條路等同Julien的「RAW-path /3」。
下一步需分清DMA格式／前處理與HSEP本體的精度，不能把輸出12-bit格點直接等同電路規格。

## 12. HSEP bypass 對照：同一 native 記憶體路徑可完整保留 RAW14（2026-10-30）

**[驗] 不縮寬的 bypass 逐像素保留 RAW14；同一輪啟用 HSEP ÷2／÷3 時，101 變成 100。**
因此低兩位損失已縮小到「啟用 HSEP 操作的路徑，或與它一同啟用的階段」，不能再把它泛稱為所有 native memory 路徑都只有 12-bit。這仍不是 HSEP 電路不可變更的位深規格，也沒有否定其他未知 RAW 路徑。

證據目錄：`projects/isp-lab/validation/hsp3-20261030-live/`；七個 case 的彙整與輸入／輸出、request／status／state 雜湊在 `report.json`。
HSP3.BIN 為 **2,252 B**，SHA256 `4c71d8da527a020a0f7abce340332b528682df3bf5276a7bf663153c54f08253`；
載入位址 `C5061240`、task 125、boot ID `0x00311C89`。這是獨立 loader-v4 companion／ABI3，沒有修改 §11 的 HSEP 成品或 ISPL／ISPC ABI。

### 12.1 對照如何略過 HSEP

新增 mode3 使用 `c01aa030` 外部 byte `+0x47=0,+0x48=0`，輸出寬保持 W、高保持 H。這是原廠允許的參數組合：

- `c0131410` 只在縮寬旗標有效時改 output DMA 寬、寫 HSEP／LM 縮寬狀態並加入 sequencer feature bit `0x8`。
- 真 ROM `c018cea0` 的離線執行也確認 bypass 路由與 HSEP 路由不同，且 bypass→HSEP→bypass 不會單純沿用前一次路由；命令提交與像素產生仍是明示 stub，不作硬體模擬結果宣稱。
- bypass 不回填外部 `+0x4C`，所以 `returned_width=0` 是正常；HSP3 在 native 返回且仍持 mutex 時另讀 output DMA shadow，驗證全寬。96×8 RAW14 的 `programmed_row_words=42`、`programmed_height=8`、`programmed_format & 0x77=1`。

另外更正兩層參數的偏移：**外部 `+0x58/+0x5C` 才映射內部 `+0x70/+0x74` 的 DMA shift flags**；外部 `+0x70/+0x74` 是另一組欄位。本輪全部保持零。packed14→packed14（enum 1→1）本來就不走原廠的 u16 shift 分支，不能靠那兩個旗標解釋或修復本輪差異。完整來源行號見 `projects/isp-lab/hsep/native-precision-20261030.txt`。

### 12.2 七個 case 的順序與結果

全部使用 **96×8、RAW14 enum 1→1、endian=1**。高度未縮減；全寬 bypass 共 768 個樣本。

| seq | case | 輸出 | 證據 |
|---:|---|---|---|
| 1 | mode3，flat101 | 每點 101 | 768 點逐像素 identity |
| 2 | mode3，ramp | 0…774，與輸入完全一致 | low2 的 0／1／2／3 各 192 點；identity |
| 3 | mode3，CFA | 4096…12291，與輸入完全一致 | 四種 low2 各 192 點；各 CFA 相位保留；identity |
| 4 | mode3，ceiling | 16380…16383，與輸入完全一致 | 四種 low2 各 192 點，包含白位附近；identity |
| 5 | mode0，flat101，寬÷2 | 每點 100 | 48×8，384 點低兩位皆零 |
| 6 | mode2，flat101，寬÷3 | 每點 100 | 32×8，256 點低兩位皆零 |
| 7 | mode3，flat103，接在縮寬測試之後 | 每點 103 | 再次 768 點逐像素 identity |

七次皆 status DONE、native rc 0、request/state 與 accepted sequence 一致、輸入 hash 不變、buffer guard 完整、HSEP 九字與 LM[0] shadow 還原一致、mutex／clock 正常釋放，DMA 格式與形狀也通過。健康檢查另存 `after7-health.json`：未錄影、app_current 2、MONIT1_60／12-bit 預覽仍正常。因此「全域預覽當時是 LV12，所以所有記憶體處理都必然丟位」不足以解釋此對照。

此輪 flat101 的兩個縮寬樣本只驗證低位差異；平均／相加／÷3 首尾取樣的算式證據仍以 §11 的脈衝、CFA 與斜坡為準。已證明 native RAW14 輸入／輸出具有保留低位的能力，但**尚未得到保留真 14-bit 的 HSEP 水平 2× 縮寬配置**，亦未驗證全幅吞吐或錄影串流整合。計時包含鎖與 native 前後處理，不拿小圖時間外推影片 fps。


## 13. 復原後的水平硬體追查（2026-10-30）

使用者在影片回放黑屏後自行重開，要求繼續找水平 ÷2／÷3 真 14-bit 的硬體與既有參數。
已備份並驗證設定未變，卡片還原到 SensorLab v0.5.0test／QS v0.2.4；詳 STATUS 與 playback-recovery。
本節只討論水平，沒有新增垂直合併需求。

### 13.1 COPY 可作保留位元的抽取設定，尚無像素／速度實測

真 ROM 執行的24個設定案例：
`../../isp-lab/host/prove_copy_decimation.py` 與
`../../isp-lab/validation/copy-decimation-20261030/report.json`。
依次執行 `c00fb960`（範圍）、`c00fb8b8`（矩形轉bytes）、`c00fba98`（descriptor）、
`c00fb418`（暫存器設定）；事件等待／清除與memset是明示stub，未模擬DMA像素。

原廠介面接受每個短列搬4 bytes、source pitch8或12 bytes、dest pitch4 bytes。
對 u16 Bayer，這是保留一組兩個像素，再略過1或2組；高度若按原影像列邊界排好，可只縮寬。
它本身只是抽點，不會降雜訊；要平均，前面仍需另一個已驗的同色運算。
packed14的兩像素是3.5bytes，不能直接沿用此word對齊方案。

`seg1_c2ef6e00.bin` 的實際重定位資料顯示公開介面上限：8bpp 8000列、16bpp5500列、32bpp4000列。
6048×2020 的H2抽取有3,054,240個短列，以u16需至少556次提交，以byte模式也需382次。
目前沒有吞吐量或錄影併發證據；不能稱為已完成的即時解法。

### 13.2 外部可程式硬體：算術可行，fp介面未閉合

例如 AMD 7-series／Artix-7 的 DSP48E1 支援寬加法、累加、位移；官方資料：
[DSP48E1](https://docs.amd.com/r/en-US/ug953-vivado-7series-libraries/DSP48E1)、
[Artix-7 DS181](https://docs.amd.com/v/u/en-US/ds181_Artix_7_Data_Sheet)。
從其運算位寬可推得足以實作以下水平同色平均；不是已做過板上測試：

- H2：每4個Bayer像素保留一對，`(a+b+1)>>1`，中間需要15bits。
- H3：每6個Bayer像素保留一對，`(a+b+c+1)//3`，中間需要16bits。
- 輸出均為0…16383，高度不變。這些算式保留輸入低兩位的影響，只在最後做一次整數捨入。

純運算可串流做，不必先保存整張圖；接到fp仍需取得尚未截位的RAW14、實作傳輸與錄影介面。
本專案尚未驗明可用的外接RAW14資料入口／回送途徑，所以不能推薦成買一顆晶片即可插上的方案。

### 13.3 HSEP／RWZM 原生參數覆核

- HSEP 原生參數與序列器18個離線案例通過，見 `../../isp-lab/hsep/v3/precision-offline/README.txt`。
  額外執行輸入DMA setter、default clamp、gain／colour path與feature推導；bypass與縮寬的clamp相同。
  已找到的shift/gain/colour係數均非HSEP精度開關。沒有新增上機掃未知bit的依據。
- RWZM 原廠setter的8組離線矩陣通過，見 `../validation/rwzm-setters-20261030/README.md`。
  一般入口整字寫0900而清flags16/24；另一原廠入口保留兩旗標且可單獨設水平phase512。
  可區分H={2048,3072}×flags={00,11}×phase={0,512}，高度保持unity。
  尚未證明任何一組保留14-bit；現有擷取只有sensor來源，不能以非零low2代替受控低位擾動。
  7份既有sensor test-pattern fixtures也全是12-bit，RAW14 pattern的步階仍待前級驗證。
- RawMix另做獨立one-shot companion與真ROM檢查，首輪只驗兩路96×8 RAW14的精度與權重，
  不宣稱縮寬、不碰錄影hook。準備期間尚未上機；最新實機狀態以後續證據為準。

### 13.4 Sensor 3B／2F 的覆蓋缺口

限定盤點沒有找到 `0001=3B` 或 `2F` 搭配 Family-A14 的直接測試。
39／38／3A的負結果不能形式上代替兩者；這是待補覆蓋，並非已找到14-bit模式。
詳 [Sensor H14 audit](SENSOR_H14_AUDIT_20261030.md)。2F+V1的舊通過已被缺R/B結果撤回；
後續有限補試應沿已驗證的V2+PAIR／HMAX911，分開RX12與RX14對照，核對實際接收窗與pitch。
RX12輸入經CRCT增益後也可有非零low2，不能只看DNG低位判定真14。

## 14. RawMix 找到可保留14-bit的硬體平均（2026-10-30實機）

**10筆96×8 RAW14對照全部通過。** 原廠RawMix自訂係數(32,0)為A、(0,32)為B、(16,16)為`floor((A+B)/2)`。
100/104→102，102/104→103；另外101/105→103。後兩組分別只改輸入bit1或bit0，
高12位保持完全相同，證明兩個低位都會影響平均。白位16380…16383、ramp、CFA、impulse也逐點符合模型。

證據：[RawMix實機報告](../../isp-lab/validation/rmix-20261030-live-v2/README.md)。
BIN2840B，SHA256 `0cb6aaec1640d8cd018a9090d8e77673efedeea363508bfb41fc4ec420f30660`；離線33項先通過後才上機。
全案native正常返回，guard/input hashes/格式與位址/8個指定shadow還原/power與mutex釋放皆通過。
獨立複核直接按每7bytes解包四個樣本，與主分析器結果一致。

這改變的是「fp有沒有可保真14-bit做平均的硬體」：**有，RawMix在此設定已量測通過。**
不是把既有RWZM或HSEP改成14-bit，也不是完成2×／3×縮寬。高度未做合併。
H2仍需解決同色配對、縮寬與格式銜接，不預設必須COPY或轉成u16；COPY候選參數見[36-case gather](../../isp-lab/validation/rawmix-gather-20261030/README.md)，
目前只證descriptor、不證DMA像素或速度。H3還缺精確等權除3與不丟中間和的算術鏈。

是否比CPU快仍未知：大量分流提交、DRAM搬運與pack/unpack可抵銷硬體算術優勢；
必須以相同有效尺寸、輸入輸出格式及完整鏈比較，不能用這次小圖時間外推fps。
RawMix是floor平均，先前NEON範例是round平均；效能對照也需先統一捨入規則。

已移除RMIX.BIN並重開，新的LOAD.LOG確認原有SensorLab v0.5.0test／QS v0.2.4載入且沒有RMIX。
待機app2、record0、ping正常；本輪沒有錄影或進入回放。

## 15. 資源優先的替代方向（2026-10-30，離線）

使用者指出RawMix分流方案耗用資源，因此不把「COPY分流＋RawMix」視為預設產品方向。
本節只做來源覆核與資料量計算，沒有新上機、錄影或設定修改。高度仍由sensor處理。

同樣u16輸入與u16輸出、N個來源像素的H2，只計額外影像處理的邏輯讀寫：

- 單趟CPU：讀2N bytes，寫N bytes，共3N。
- COPY分流：讀2N、寫2N；RawMix再讀2N、寫N，共7N，為前者約2.33倍。
- 6048×2020分別為36.65 MB與85.52 MB／幀；這不是實測DRAM流量或速度，還沒計packed14格式轉換、cache、原始擷取及錄影。
- 分小塊可以降低暫存RAM容量，但不自動消除硬體需要讀寫中間資料的成本。

算式與界限存於`../validation/20261030-takeover/resource-paths.json`。

使用者隨後明確提出「能否修改ISP，像送入RWZM一樣直接送進RawMix」。
因此目前優先查**既有ISP連線與RawMix輸入的免COPY配置**；以下各項是候選方向，不是已完成的管線。

三個問題分開記錄：

- **免COPY**：RawMix直接讀既有RAW緩衝，不另建A/B影像；仍可能有DRAM讀取。
- **免DRAM中轉**：sensor／CRCT串流直接接FPNR；必須找到實際硬體來源選擇，不能只改軟體函式呼叫。
- **完成H2**：同一Bayer列的`R0 G0 R1 G1 R2 G2 R3 G3`必須產生`mean(R0,R1) mean(G0,G1) mean(R2,R3) mean(G2,G3)`。
  只把同圖送兩路，或只讓B平移兩像素，不能自動完成不重疊配對與半寬輸出。

候選方向：

1. **Sensor直接水平縮寬**：資源成本最低的目標，3B/2F + Family-A14仍缺直接對照。
   但這不等於有正向成功證據；原廠同類讀出表將水平合併列為12-bit，換Family未必改變輸出word位深。
   最小補試要保留已驗Vbin/PAIR與HMAX，核對接收窗/實際pitch、三色及真正的量化精度，不能只看low2非零。
2. **RAW輸入crop＋stride直接供應RawMix**：原廠`C0144AE8`有已被caller使用的crop支路，
   可能免去先建立完整A/B平面。當前RawMix入口不暴露這組幾何；最小有效寬、fetch重疊/尾端、height分批及內部512-padding仍需驗明。
   Setter能描述crop不代表硬體完成或吞吐可行，不直接把output DMA改短當成抽點。
3. **CPU融合解包／平均／打包**：設計上可逐小塊處理，無需完整u16中間影像及A/B平面，保留真14-bit的同色平均。
   現有已驗NEON只是u16平均核心，融合packed14管線尚未實作或量速；不能將此設計當現成功能。
4. **RawMix＋COPY**保留為功能驗證與備案。它已證明有14-bit硬體算術，沒有證明整條方案更省資源。

純裁切或抽點可減少工作，但會改變視角或失去合併降噪，不能冒充原需求的全視角binning。
外接FPGA可串流平均，但fp端的RAW14接入/回送仍未閉合，現階段沒有可直接加裝的低成本方案。

### 15.1 免COPY：新增原廠crop支路的8組離線證據

證據：[RAW input crop報告](../../isp-lab/validation/raw-crop-20261030/report.json)，
SHA256 `a3758c04d896354455ff53ff870501a282573847339ed3ed1c20feee9c8e3060`。
原ROM來源及測試程式hash已核對；只執行setter，MMIO為被動記憶體，沒有DMA像素或完成中斷。

- 6組輸入：u16有效寬2、來源寬4或6；正常flags `0x400000`與加入原廠crop bits23/24對照。
  Crop支路產生編碼fetchwidth5、crop start1/end3、pitch2或3 words；正常支路fetchwidth4、crop欄位0。
- 2組輸出：原廠output formatter能描述u16寬2或4、pitch1或2 words。
- 這讓「窄的A/B視圖直接讀同一原RAW緩衝」成為有來源的候選，不是必須先COPY完整平面的證據。
  現成RawMix入口沒有暴露這組crop；雙來源共用crop，另一種分channel路徑可另設輸入，但新組合尚未整合。
- crop start/end差2僅為描述意圖，不能當成已量到2個有效像素。fetch重疊下一虛擬列、最後一列越界、
  內部至少512寬padding、虛擬列數與分批成本、CFA相位及實際輸出長度都仍需驗證。
- 本組只驗u16。Packed14以各自crop x=0/x=2處理半byte相位的可能性未排除；
  尚不能判定一定要先解包／重打包，也不能宣稱已能直接處理packed14。

### 15.2 像RWZM一樣直接串流：目前查到與尚缺的證據

RWZM已知位於接收端→CRCT→BufA寫入的路徑；已測RawMix是兩路記憶體輸入→SIG/FPNR→輸出DMA。
這是兩條已知路徑的差別，不是所有FPNR硬體接法的窮舉。

**原廠確實有把FPNR嵌入較大SIG工作中的程式路徑，不限於獨立RawMix API：**

- `C0136018`於`out/decomp/full/blk_c01.c:35913`附近設定FPNR係數／threshold；
  同函式`:35987`將兩個輸入轉成DRAM word address，條件分支另建第二input descriptor，
  `:36072/:36089`交`C0141468/C0143388`。
- `C0161840`於`:54189`附近設定FPNR；`:54434`起依其旗標加入feature2，再交`C018CEA0/C01983F8`。
  `:54027`起兩路來源可為獨立word address或相差一個打包列長的地址，`:54159`提交input DMA。

這支持研究「在既有SIG工作內啟用FPNR、直接引用原RAW」；以上找到的兩條仍有記憶體輸入，
沒有證明sensor直通、水平兩像素延遲或每RG pair的跳取。嵌入SIG也不自動保證錄影並行與精度。

`C0635CA8/C0635CD0`寫`300F06B0/06D0`的三位元欄位，原廠已解出的0…5選擇
Gain/Crmf/Vbin/Hbin/Hbin2/Spc哪個抽頭送到BufA；不能把這個欄位當成任意改接FPNR的目的端選擇。
尚未找到已解義的sensor／CRCT→FPNR直通選項，也未找到把FPNR第二路設成同列延遲兩個Bayer像素的參數。
未找到不等於硬體不存在；不能藉由已測RawMix wrapper使用DRAM就排除直接串流。

即使找到直通，仍須證明14-bit一路保留、兩路能做同色配對，以及輸出可每4個Bayer像素留下2個。
因此目前可下的結論是**COPY不是已證必要條件；直接串流是待解的硬體路由問題，尚無已完成設定**。

### 15.3 「相鄰合併參數」用語更正

使用者指出：若仍要先搬成A/B平面，就沒有達到其低資源直通目標。正確；不能以兩路平均已驗證，
推成原生水平相鄰配對已找到。已證的是權重(16,16)使兩路同索引樣本做floor平均；
把兩路安排成原圖x與x+2是未完成的輸入配置，不是已找到的單一水平bin開關。

外部+0x20=1曾以「interleaved」註記；這是對wrapper布局／派工的研究標籤，不能當成
硬體自動選水平相鄰同色點的證據。`C0161840`可將B地址加一個打包列長，也不是水平兩像素延遲。
`C01A9B20`的op0/1/6另派至`C0133758`，該函式以`ceil(H/2)`設定幾何並回傳原W、半H。
**後續沿helper補正：這條分支確有自動垂直配對的原廠preset。** 雖然先帶入A/B欄位，
其`0x10080000`高階flags會在`C0144AE8`把B覆寫為`A+2*rowWords`，再以4列步進、兩phase
處理0/2與1/3列。這是設定程式算地址後交DMA，不是已解出的硬體H/V切換位。
該分支未做像素驗證，不能把半高設定說成已證水平縮寬，也不能再說它的B完全由caller決定。

片上兩個取樣點／延遲若能完成配對，可以不建兩張中間影像，仍有直通價值；
目前尚未找到可用的水平延遲＋不重疊配對＋半寬輸出組合。

## 16. RawMix最後有界查核：停止低資源水平縮寬主線

使用者授權「研究看看，不然就放棄RawMix」後，完成16組真ROM離線setter案例與獨立來源覆核。
**決定停止把RawMix當作目前H2／H3低資源實作路徑**，保留其已測14-bit平均成果。
本輪沒有連線、讀取或操作相機，也沒有改已驗證的RMIX程式／BIN。

完整決策與證據：[RawMix H2 decision](../../isp-lab/validation/rawmix-h2-decision-20261030/README.md)。
最終report SHA256 `4225056d3d24446db1816e8d084c8000bc80e295b7087ed4fb0d8d47bf07a444`；7個報告來源hash獨立核對相符。

- 「同圖A、B偏移2 Bayer像素」的配對算式正確；不必先COPY兩張影像。RawMix平均後仍需逐pair步進與半寬輸出。
- 原廠auto-B的兩個高階flags由`C0144AE8`解成A+1或2列地址，沒有直接傳成硬體H/V切換位。
  只把原vertical preset的width改2，u16便是B+8bytes（4像素），且兩phase排程仍非所需H2。
- packed14兩獨立channel可同base、crop x=0/x=2，原ROM確實生成互不覆寫的crop欄位。
  這是輸入對齊的正向線索，未證實際像素或寬列的週期跳取。
- packed14寬2的原生輸入行距為0，A/B重合；輸出行距為0但傳輸1word。寬16對照行距與傳輸均為7words。
  因此「每對一短列」不能直接套用packed14。多phase／分組或改u16仍有可能，但沒有完整且低成本的輸入輸出方案。
- 所查setter未找到單一寬列的水平逐pair步進、週期輸出抽取或XY交換。以一對輸出樣本為一虛擬列的方案，
  6048×2020有3,054,240條；僅輸出高度欄位的樂觀下界也需187批，先前dual-crop既定條件為374批。
  這只適用該短列方案，不是所有未知接法的最低成本；沒有把512-padding當成處理週期，也沒有實測CPU／RawMix速度。

本輪停止是因為沒有找到符合使用者資源要求、值得繼續部署的具體路徑；不把它寫成硬體絕對不可能。
重啟此方向應以新的明確水平步進／抽取或直通來源證據、或已證低成本完整鏈為依據，不再重複現有未知參數推測。

## 17. SIG1_RAW_ZOOM／COPY 2D：新增的有界離線研究

使用者指定追查這兩個候選後，補查原始韌體的 ARM／Thumb 位址建構，並執行 COPY 底層幾何與 MMIO 編碼。
這輪沒有連線、讀取或操作相機。完整報告與可重現程式：
[RAW_ZOOM／COPY 2D 覆核](../../isp-lab/validation/copy2d-rawzoom-20261030/README.md)。

- **RAW_ZOOM**：`30113380/384` 對到 bank-relative `3021075C/760` 的兩字 descriptor。
  兩段韌體的直接位址常數為0 hits，ARM／Thumb候選43筆，完整反編譯的明確引用3筆。
  已識別的相關指令是 `C015A248..252` 診斷與 `C019CB64..7E` descriptor 建構，沒有新增可用倍率／精度 setter。
  此模式搜尋不能涵蓋所有計算指標、表驅動與bulk寫入，不排除未知能力；目前不具備可部署的RAW14縮寬設定。
- **COPY**：20組真ROM測試確認，5500是公開u16 API限制；較低層將`rows-1`存成16-bit。
  65536在設定層可表達，65537靜默回繞為1，0回繞為65536。
  pitch也是word單位16-bit；非4倍數被截成word，超界會回繞。原生return=0不保證幾何正確。
- **提交數更新**：6048×2020 u16、無列尾padding、每個RG pair當一個短列，
  H2公開API需556次；若硬體接受完整65536列範圍可降到47次。
  H3相應是371→32次。這是候選編碼與條件式估算，不是已驗硬體上限或實際吞吐。
- **仍是抽點**：COPY沒有加法／平均，也沒解決packed14每對像素3.5bytes的位元收集。
  新結果不能替代NEON的同色平均，也不重啟已停止的RawMix水平實作。

COPY report SHA256 `a789d8c1de67c9028b263a6acbe9cea78bbba029f7d772881caa67734b58e832`；
RAW_ZOOM report SHA256 `e0e778980270b3a47f83ac7b4aaaad08a41666012fa2017e891cbcde68b30b0f`。
兩份報告分別核對5／21個來源hash相符；未執行DMA像素、IRQ、完成、cache或錄影測試。

**使用者追問NEON的結論**：NEON是CPU向量指令，能實作水平或垂直同色平均；既有526組離線證據只覆蓋u16的H2 row kernel。
尚未驗證packed14完整流程或相機吞吐。Bayer垂直配對須用同色的y與y+2列，不能直接混合相鄰異色列；
本專案的目標仍是sensor已處理高度，只補水平縮寬，沒有新增垂直產品實作範圍。

## 18. H1實機補試：水平÷3成立，已測配置仍只有12-bit內容

使用者授權「測看看」後，實測第一順位H1。沿用sensor V3 RAW14、HMAX911、RX14、BUFA0獨立擷取，
只抓512列；更新並保住`C31DF600/604`原廠每幀來源，以`C0633B30`兩筆原廠driver核及`C017FAA0`
設定第一級H1，H2與垂直CRCT bin關閉。此輪沒有部署整條BufA7→SIG錄影工作。

| 階段（各2幀） | 有效幾何 | 低兩位 |
|---|---|---|
| 前置Crmf mux1 | 6064×512 | mod4各約25% |
| H1 mux3，不合併 | 6064×512 | 全幀皆0 |
| H1 mux3，÷3，原廠核0 | 2016×512 | 全幀皆0 |
| H1 mux3，÷3，原廠核1 | 2016×512 | 全幀皆0 |
| 後置Crmf mux1 | 6064×512 | mod4各約25% |

每幀先填滿可能的全寬寫入區，再讀回整區檢查實際DMA extent。
全寬5,433,344 bytes、縮寬1,806,336 bytes均吻合幾何，guard完整；兩個原廠核、H1／H2／來源／mux讀回正確。
影像已目視確認同一場景水平壓縮，高度不變，不是截圖或只裁掉水平視野。
舊T-C的H1失敗已補成有效影像；本輪已測a0 H1配置的14-bit目標未通過。

**結論只限已測輸出路徑與設定**：不把全幀低兩位零直接擴大為電路固定內部位寬，
也沒有排除未知參數或另一條完整BufA7→SIG路徑。沒有受控RAW14擾動、精確tap方程式或全幅速度證據。

自有capture與helper RAM已釋放。後續查核已回mode8 MONIT1_60、app2、record0、frame counter59957→59976；
H1/H2與每幀來源回0，BUFA0 idle，兩個callback為0，echo回原handler。無錄影、寫卡或重開機。

完整結果：[H1實機10幀](../validation/h1-live-20261030/README.md)。report SHA256
`2f6288e446d80d97872aa2343f8d4fdb61333213583b1c5cd22d020ffa89526e`，21個來源hash保存於report。
