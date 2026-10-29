# ISP 鏈能力地圖（第一輪，2026-10-23，離線整理）

RESEARCH_PLAN §2 的第一版。只整理既有證據，沒碰相機。
證據：**[M]** 上機量過、**[C]** 程式碼／反組譯、**[I]** 推論。主張後面附出處。
縮寫：`OGN/` = `projects/open-gate/notes/`、`IHW/` = `research/imaging-hw/notes/`、`RC/` = `projects/open-gate/build/res-custom/`。

## 0. 鏈（訂正過的版本）

```
感光元件（含自己的合併） → 接收端 0x3010 → CRCT 0x300F（DCLP／DEFC／PDAF 校正／Crmf／增益／Vbin・Hbin・Hbin2）
   ├─ a0 視窗 → 六選一 mux → BUFA0        ← 參考 RAW：mux=1 Crmf（與 imx410-lab 的邊界）
   ├─ a7 視窗 → 六選一 mux → BUFA7
   └─ bufa1 → RWZM → BUFA1                 ← 錄影縮放
→ DRAM → SIG／寫入層（CDNG）
   預覽分支：另一組 bin/RWZM 欄位 → 顯示 ring（YUYV，descriptor 寬）→ LCD／HDMI
```
走哪條分支由**路徑選擇器 `FUN_c0325228`** 依（錄影 RWZM、預覽 RWZM、兩邊 bin）決定 [C]（IHW/CRCT_PATH_SELECTOR_SOLVED.md、OGN/IMX410_FULL_DESIGN §6.2）。

| 分支 | 條件 | a7 mux | 主管線吃 | 原廠 profile 數 |
|---|---|---|---|---|
| B | 錄＝預覽，且 unity | 1 Crmf | 預覽 | 172 |
| C | 錄＝預覽，非 unity | 4 Hbin2 | 錄影的 bin 與 RWZM | 36 |
| D | 錄≠預覽，錄 unity | 1 Crmf | 預覽 | 81 |
| E | 錄≠預覽，預覽 unity | 3 Hbin（a7 未啟用） | RWZM＝錄影、bin＝預覽 | 17（原廠 UHD：預覽 ×3） |
| F | 兩邊都縮且不同 | 4 Hbin2 | 錄影；副管線＝預覽 | 0 |

**ISP 的設定面 = 一整列 PARAM profile（65 字）**：32 欄由公式決定，其餘是影片類常數或沿用底列（`open-gate/build/imx410_profile.py`，與原廠 78 組影片 profile 逐字相同 [C]）。
res-custom 以「虛擬 profile = 底列 + (偏移, 值) 對」安裝；錄影 29 欄、回放 13 欄、各格率另一組（SEC_CANVAS／SEC_RATECANVAS，`RC/ogc_layout.py`）。

## 0.5 ★ 2026-10-27 isp-lab 實機結果（FHD 29.97 路線 row 122／mode 106，ISO 3200，丟棄錄影，validation/20261027-night1*）

每案都是 `isp_custom.py` 由公式產生整列 profile，在 RAM 換列、真錄、相機推回五個檢查點；判定＝DNG 尺寸符合預測且與待機 LV 視野相關 ≥0.6。

| 題目 | 結果 | 證據 |
|---|---|---|
| 錄影 RWZM 範圍 | **1024–8191 全對**（1024、1200、1536、2048、3072、4096、4608、6144、7168、8191；兩軸不同 2048×1024、4096×3072 也對）；**8192 起失敗**（8192／16384 亂碼、12288 未縮放左上裁切）→ 13 位元欄位 | night1／1b／1e |
| 分支 F（預覽 bin3＋預覽 RWZM≠1:1，錄影 RWZM 不同） | **錄影也被 ÷3**（兩軸），DNG 只有左上 1/3 有畫面 | night1 z4096／z6144（修正前） |
| → 公式修正 | 無 bin 錄影倍數 >3x 時預覽停在 ÷3＋1:1（分支 E）；`imx410_profile.preview_factors` 與 `sl_modes.c` 同步，突變測試守 | night1b 三案通過 |
| 分支 B／D（錄影 RWZM 1:1，含 bin） | 未縮放左上裁切（重現 §1.2 的否定） | E1、night1c s1365／s1100 |
| **分支 C 的錄影 CRCT bin** | **垂直 bin3 有效且真的平均**：與同尺寸純 RWZM（z4608）比，時間雜訊 2.78→**1.74**（`[1 2 1]/4` 理論 ×0.61＝1.70）。**水平 bin3 不可用**：畫面被擠進左 1/3、右 2/3 規則橫紋；宣告成 ×9 也是亂碼 | night1d b1x3-z4608x1536、b1x3-z1536 通過；b3x3／b3x1／h9 失敗 |
| RWZM 的雜訊 | 純 RWZM 縮小**不降雜訊**（z4608 2.78＝原廠 2.77；整數比 z3072 反而 3.22，單點抽樣） | 同上 |
| 位深 | 12 bit 路線只改平面碼 `+0x80/+0x84`：**8 bit 與 10 bit CinemaDNG 都正確**（尺寸、視野、畫面）。14 bit 未測（16 bpp 容器大於 12 bit 路線的緩衝，要用原廠 14 bit 路線） | night1e d8／d10 |
| 自動化 | 相機開機後自己 `usb off/on` 重連（ISPL ix_ur_step），EP83 不必拔線；推送引擎偵測端點重設（DEPCMD≠StartTransfer）丟掉失效的傳輸鏈 | usb-reconnect-01、night1-E0 |

⇒ 對產品的意義：**降解析度的畫質只有「感光元件合併」與「CRCT 垂直 bin」兩條會降雜訊**；RWZM 只是內插。品質選項要把這兩條和 RWZM 的組合列出來。

**第二輪（同日，night2／night3，路線由選單切換，每案錄後讀 0xC343B590 確認模式、DNG 位深確認是改到的那一列）**

| 路線（選單） | 結果 |
|---|---|
| UHD25 8 bit（mode 123，6064 1×1） | RWZM 1024–6144、垂直 bin、d10、**d12** 全過；**z1024＝6048×3412 全幅 1:1 @25p 通過**。切到 UHD 時相機自動降成 8 bit／25p（寫卡考量，ISP 本身 12 bit 做得到） |
| FHD60 12 bit（mode 27） | 10 組全過，含 **3024×1708 1:1 @59.94p** |
| FHD60CROP 12 bit（mode 88）、UHD25CROP 8 bit（mode 124） | 尺寸／位深全對；但**改 RWZM 後 DNG 用整個窗（2088／4176），比原廠 1:1 裁切寬約 8%，待機 LV 仍是原廠裁切視野**（配準縮放 0.92–0.94）→ 判失敗。原廠裁切的待機視野由別的機制決定（不是那 6 個待機 profile；`standby_visible()` 對裁切算出 1280×720，不是原廠值）——留給 IMX410 custom 的虛擬模式設計 |
| UHD25CROP **d14** | **14 bit CinemaDNG 正確**（緊密打包 14 bit，不是 16 bit 容器）；12 bit AD 資料呈梳狀（低兩位幾乎全是 01），與 §4 結論一致 → 14 bit 管線本身可用，真 14 bit 只差 14 bit AD 的感光元件模式 |
| 100／119.88 fps | 選單灰掉：「記憶媒體：SD 記憶卡」。丟棄寫入時這只是 UI 政策；繞過屬設計變更，待使用者決定 |

判定工具同日補強：DNG 位深必須等於 Want（改錯列一定抓到）；視野改用雙向配準，縮放偏差 >3% 判失敗（相關係數 0.86 抓不到 8% 的差）。

**第三輪（night4）：分支 F 從公式消失**
- 錄影中 LV 也量視野（原廠基準 0.985＝LV 裁掉 16/10 邊距）：FHD z1200 只有 **0.80**（放大的局部）。原因：錄影 1200、預覽只能挑 1536（3032 窗要塞進 2100 來源）→ 兩邊都縮放且不同 = **分支 F**，錄影中 LV 走副管線。
- **規則**：預覽要嘛每軸等於錄影（C），要嘛 RWZM 1:1（B／D／E），**永不 F**。公式：錄影 1:1 → 原廠候選；錄影縮放且等向、放得進來源 → 等於錄影；窗 ≤2100 → 預覽 1:1；否則 ÷3＋1:1。`imx410_profile.preview_factors` 與 `sl_modes.c` 同步；新測試 `test_scaled_record_never_gets_a_different_scaled_preview`＋突變；原廠 78 列不變。
- 改動影響共用公式：兩軸不同的錄影（例 M102 2640×916、M98 2042×2027）原本是 F，現在走 E（預覽解析度較低但視野正確）。
- 實機（FHD60）：z1200、z1400、2048×1024、1600×2400、1600×1200、6144、E0 全過，錄影中 LV 0.96–0.985。

## 1. 每一級

### 1.1 接收端（0x3010）
- 能裁：x 窗（12 px 單位，任意位置）、y 窗（要和感光元件一致，否則不出幀）[M]（imx410-lab IMX410_RULES §33 §15）。
- 不能縮放。水平裁不加速 [M]。
- **錄影路徑目前沒用它裁**：畫布視窗＝模式光柵 [C]。原廠窄寬模式用 TIM +0xA/+0xC 在接收端裁（mode 102 952..5128）[C]。→ 自訂裁切要走虛擬模式表（imx410-lab 的範圍）。

### 1.2 CRCT（0x300F）
- **錄影欄位的 bin（+0x5C/+0xC8）**：原廠 306/306 全 ×1 [C]。
  - 分支 B（bin×3 + RWZM unity）上機否定：只有幾何宣告縮小、拿到左上角裁切（A001_167，相關 +0.987 對裁切）[M]（OGN/IMX410_FULL_DESIGN §6.1）。
  - 分支 C（bin + 非 unity RWZM）理論上會開 Hbin2：**I0／I 對照組從沒上機** [C]。res-lab 的 M98 hbin3 992×360 只驗了檔頭，沒驗像素真的被平均 → **CRCT 錄影 bin 有沒有作用仍未證明**。
- **預覽欄位的 bin（+0x58/+0xC4）**：原廠 UHD 預覽用 ×3（分支 E，17 列）[C]。⚠ imx410-lab 說「306 個 profile CRCT 合併全關」只對錄影欄位成立；預覽路徑屬 isp-lab，CRCT 預覽 bin 是現役功能。
- 合法列舉：hbin 0/1/2 → ×1/×3/×5、vbin 0/1 → ×1/×3；**非法值會讓相機當場鎖死（要拔電池）** [C]（FUN_c022ee10/ee90）。×5 的五抽頭係數沒找到 [C]，先不當選項。
- 核：Hbin2 三抽頭 `[1 2 1]/4` 或 `[1 14 1]/16`（soft/std）；係數暫存器 0x300F0800/0840/08C0 [C]。res-custom SEC_BINFILT 可選 6 種核 [C]，上機效果未驗。

### 1.3 RWZM
- Z 為 ×1024 整數，1023 夾成 1024；兩軸獨立 [C]；非等向錄過（M12 2048/1023）[M]。
- 範圍 1024..16384、只縮不放：**規劃器政策**，硬體極限未量。
- **畫質已量過**（OGN/REDUCTION_KERNEL_MEASURED.md §0、§7）[M]：
  - RWZM 不做前濾波，每相位只是 2 抽頭級內插；抗疊紋完全來自感光元件那一級。
  - 相位表 16 格，`floor(16×frac(nR))`；用幾格取決於比例的分母：25/16 全開、3/2 兩格、整數一格。
  - 碰到 RWZM 的路線誤差 2.2–7.3%（和比例、尺寸無關），不碰的 0.7%／2.7%；FHD（÷1.5 經 RWZM）有 16 列週期橫紋。
  - → 這就是 Pareto 代價向量裡「條帶／疊紋」兩項的現成量法，isp-lab 沿用它的方法。
- 預覽 RWZM 原廠只用過 1024/1280/1536/1600/2048/3072 [C]。

### 1.4 寫入層／CDNG
- rec／act／16-10 邊／寬 16 的倍數：ISP_SIZE_RULES §1（imx410-lab notes）。
- 位深：原廠 8/10/12 平面碼 `PLANE={8:(10,10),10:(10,9),12:(7,7)}` 寫 +0x80/+0x84 [C]；14-bit 是 16 bpp 容器，consumer 尚未接 [C]。
- >99 fps：canvas +0x30（通道格率）> 99 → 管線改輪詢、時脈閘門 5/16 [C]（IHW/HIGH_FRAME_RATE_PATH.md）；全開閘門有效 [M]。
- 94 格 RAW 池、64 MiB 結算（memory lossless-early-stop-94）。

### 1.5 預覽分支（LCD）
- 規則：來源寬 ≤2100、可見寬 ≤2000 且 16 的倍數、光柵＝可見+16/10 不能超出來源（超出會花屏凍結）[C]+[M]。
- 無合併時兩軸要等向，否則開錄第一秒接縫 [M]（只在 M12）。
- 240/280：預覽走錄影路徑 [C]+[M]；大幅面未驗。
- **待機預覽是另外 6 個固定 profile**（視窗 2016×1344，3×3 全片幅讀出），可見寬高由錄影 FOV 換算 [C]（imx410_profile.standby_visible）。→ 待機畫面不是錄影管線的縮圖，**待機檢查要另外驗 FOV 對齊**。
- 顯示 ring 可依 descriptor 寬線性解成 YUYV [M]（IHW/IMAGE_CHANNELS.md 頁首）。

## 2. 安裝路徑與自動化相關（res-custom consumer）

- **Virtual RCD 的 APPLY 不用重開機**：producer 回傳 RCD blob → consumer 驗證 → 停 LV → 換表 → 原生 setter → 重啟 LV [C]（`RC/ogc_virtual.c`）。
  → isp-lab 可以註冊成 producer，每組配方幾秒內切換，自動化的關鍵。
- 限制：只能在 **UI thread** 呼叫；錄影中、XMP/MOV 活動中拒絕；每次開機最多 32 份圖示 pack／4 MiB（同 pack 去重）；最多 16 個虛擬 mode。
  isp-lab 的 producer 可以固定用同一份 pack，避免吃光名額。
- **主機怎麼進 UI thread（第 11 題，第一輪結論）**：三條候選
  1. **★ GUI 佇列 + 私有變數回呼**（建議）：isp-lab 的 sup 用 `C0560FB0(GUI_OBJECT, name, fn)` 訂閱自己的私有 app 變數，
     回呼「跑在 UI thread、新值在 descriptor+8、回 0」[C]（`open-gate/build/sl_menu/sl_modes.c:117-124`，引 C057A448/C057A6F8）；
     主機用 callfn 呼叫 `C0593F30(0, name, value)` 把整數更新丟進 GUI 佇列——668 個原廠呼叫者、任何任務都可呼叫 [C]
     （`research/firmware/notes/DISPLAY_MODE_SWITCH.md` §2b）。回呼裡做 vrc_apply。
     證據：res-lab 面板（sl_modes.c 的 subscribe/post）與 res-custom 管理頁（ogc_files.c rc_int）在相機上用過 [M]，
     但那些 post 都是從 UI 自己發的；**從 shell task 發 post 沒有實測**。要先上機確認：回呼的任務 id 是 UI task、不卡死 shell。
     注意：私有變數要先在 app 變數表登記（fp-native-ui skill）；觀察者另有 10 格上限的那套是別的機制（XC_Observer），不要混。
  2. 按鍵注入（imx410-lab 用 `key OKON/OKOFF` 進出放大，已實測）[M]：只適合「按一下就到」的動作；Apply 要走選單會很脆弱。
     且 imx410-lab 每 50–90 組在「退出放大」收尾時整機凍結一次，原因調查中（sigmafp-re-40，10-23）——等結果再判斷這條。
  3. 在 UI thread 週期性會跑的路徑掛 hook 查信箱：要多一個 claim，沒必要。

## 3. 矛盾與待解（第一批題目）

1. ~~CRCT 錄影 bin 在分支 C 是否真的平均像素~~ → **10-27 解：垂直是、水平不可用**（§0.5）。待解：水平為何被擠進 1/3（Hbin 與 Hbin2 疊加？）。
2. ~~RWZM 硬體極限~~ → **10-27：上限 8191**（§0.5）；<1024 仍未測。
3. 寬度粒度：寫入器算 8、BUFA0 實測 16（ISP_SIZE_RULES §5-1）。
4. 留邊 16/10 是否必要（原廠 28 列沒留）。
5. 奇數起始列的 Bayer 相位。
6. 大幅面配 240/280 時預覽走錄影路徑會不會超出 2100/2000。
7. 待機 6 個 profile 與錄影 FOV 的對齊（待機檢查點）。
8. AF 統計格網（R28）與偵測影像在自訂幾何下是否跟著對（對焦檢查點）。
9. 放大（MF）時換讀出：自訂模式下放大的目標模式與放大區域（memory zoom-is-a-sensor-mode-change；imx410-lab 自己就是借 host 10 放大進虛擬模式，兩者會互相干擾，要確認）。
10. 回放：13 個回放欄位的意義、非標準尺寸 DNG 的縮圖與播放。
11. APPLY 進 UI thread 的方法（自動化前提）→ §2 候選 1，待上機確認「從 shell task post 是否在 UI thread 回呼」。
12. imx410-lab vmode 會覆寫 consumer 的描述元（它從 ROM 複製、還原回 ROM）；目前有 check_stock() 擋著會報錯。共用卡前要改成「從現值複製、還原原值、避開 consumer 的 mode id」（sigmafp-re-40 同意到時一起改）。

## 4. 通知 imx410-lab
- 第 1.2 節的訂正（預覽 bin 是現役功能）要告訴 sigmafp-re-40：邊界本身不變，但「CRCT 不算任何一邊」只對錄影欄位成立。

### 2026-10-27 下午：IMX410 custom 虛擬模式進錄影（validation/20261027-vctl, vm1, vm41*, seq1, ov*, chk*, fps120）
- 對照組：mode 27 自己的列當虛擬模式裝在 host 27 → 與原廠相同（pass，fov 0.962）。虛擬模式路徑成立。
- V33（OG 3:2 2×2 59.94）、V49（3×3）、V33-z1600、V49-z1200：pass（DNG 尺寸／位深／待機與錄影中視野）。
- **V41（2×2 fast，11-bit AD，類別 19）不可用**：
  - 錄影中 LV 全白（Y≈244），任何順序都一樣；META +0x5C、+0x60（類別）單獨改回都沒救 → 在 TIM／fast REG 層。
  - DNG 只有接在 V33 之後才正常（且有 ~0.1% 亮點）；接在原廠模式後整幀壞 → fast 暫存器組少寫了某些暫存器，靠前一模式殘留。待 IMX410 custom 修。
  - META +0x54 / R38 +0x4 / +0x18 在原廠是「錄影 1/8/0x4C003、全高 2/0/0x40003」兩組，V33/V49 用全高組照樣 pass → 不是原因。
- 100/120：`setting set cam_frame_rate 7` 改得到變數，但錄影仍用 mode 27（59.94）→ 錄影不讀這個值；已設回 0。要走兩層 RAM 補丁（CSV variant + C00A87E4 normalizer）。
- **⚠ 更正（同日 14:35）：V41 與 1×1 失敗的根因是 R10，不是 fast 暫存器組。** smc 不產生 R10（SoC 讀出模式號，依等級：
  16→2、17→3、18→6、19→7、20/22→4、21/23→5，MODE_TABLES §1），vmode 沿用 host 27 的 6 → 1×1／fast 2×2 的接收端錯。
  smc.create 現在寫 R10（selftest 比對原廠 70 模式，突變會抓到）；修後 V41、1×1 OG／S35／S16 錄影中 LV 與 CDNG 全對。
  上面「接在 V33 後才正常」是殘留的接收端狀態造成的假象。
- 矩陣（host/matrix.py → matrix.json，isp_custom 實驗 `FHD60:M<n>`）：6 DC × RES × 7 種讀出（14/12/12fast/2x2/2x2fast/3x3/3x3fast）×
  {無, CRCT v3} = 179 案例，fps 上限 59.94（host 27）。煙霧測試：所有裁切（S35／S16）錄影中 LV 與 CDNG 正確，只有待機／對焦 LV 不跟裁切（§5-1 待解）。
- **LV 解碼更正（10-27）**：推送的 LV 是 **Y Cr Y Cb（YVYU）**，不是 YUYV。使用者對照 LCD（中間橘貓、右側娃娃橘角）確認；舊網頁的 LV 全部偏藍。
  case.py 已改並加 `lv_colour` 判定：錄影中 LV 平均 Cb／Cr 與同一案例待機 LV 差 ≤4、Y 平均 16–235、std ≥4（壞 R10 的全白 LV 會被抓到）。
  test_case.py：合成橘色、原廠過、壞 V41 不過、修好的 V41 過；把色度順序改回舊的會失敗。

### 矩陣 mx1 前 92 組（新判定重算，validation/20261027-mx1-*，reeval.py）：46 過／46 不過
1. **裁切待機視野（36）**：S35、APS-C 全部；CDNG 與錄影中 LV 正確，待機／對焦 LV 不跟裁切 → 公式待機欄位（v2 §5-1），最大一類。
2. **14-bit 讀出（key 14）不穩**：
   - HD 14-bit 錄影中 LV 偏洋紅（Cb/Cr ≈150/161 對 124/131），M24/26/30/37/44/46/47；同為 14-bit 的 M22、M36、OG 14-bit 正常。寫入欄位除幾何外無差別。
   - CDNG 壞幀（中位數 ≈1400 的雜訊，檔頭卻是這次的尺寸）只出現在 14-bit：M8、M30、M44（尾幀）、M36、M37（中間幀）。12-bit／fast 全部正常。
   - 假設（未驗）：host 路線是 12-bit，幀緩衝照 12-bit 配置，14-bit 多出 1/6 蓋到鄰幀。待重跑確認可重現，再查配置大小。
3. **E1 截掉錄影中 LV**：M74/M76（S35 688 2×2，Z 3119）錄影中 LV 0.945（r 0.993）：E1 預覽 1:1，act×Z = 2047 > 可見上限 2000。
   本可走 C，但 C_MAX = 3072 未測 → 實驗開關 `ISPF_C_MAX`，矩陣跑完後上機驗 C 於 Z > 3072。
- 量測工具修正：nightrun 打包驗證後刪 push/（磁碟曾剩 2.5 GB）；丟棄錄影仍在卡上建檔 → cardclean 逐組刪新片段；錄影縮成 1 秒。

### 矩陣 mx1 完成（179 組，判定改為 rec LV 比例對 act/rec ±0.02、配準 r ≥ 0.85、LV 色度）
- 通過 46（OG 21、HD 25）；只差裁切待機視野 111（S35 24、APS-C 33、S16 21、正方形 33）→ 待機欄位是最大缺口。
- **C 路徑不設倍率上限（公式 R9，已改 isp_formula）**：cmax 實驗 M74/M76（Z 3119）C 下 rec LV 0.97（預測 0.977），E1 時 0.945；
  M140/M142（Z 3218）也過；vbin C 的水平 Z 6239–6436 在矩陣中正常。test_isp_formula 加回歸與突變。
- **14-bit HD 錄影中 LV 偏洋紅可重現**（M24 三次相同：Cb/Cr ≈149/160）。平面碼改 12（DNG 確實變 12-bit）仍偏色 → 不是 ISP 平面碼。
  同一個讀出 `14:6048x3402` 在 Z 6144（M36）與 1:1（M22）正常；OG 14-bit 各倍率正常；12-bit 同倍率正常。⇒ 14-bit 讀出 × 某些 RWZM 的組合，原因未明。
  下一步：拿原廠 14-bit 模式（mode 100）的列當虛擬模式對照。
- **14-bit 壞幀是偶發**：M8、M36 重跑時正常。
- 量測：丟棄錄影的「遲到幀」（停錄後才完成）會走原廠路徑真的寫卡（M173：停錄 37 s 後第 17 幀 750 KB）；cardclean 改成刪完等 5 s 再看，連續兩次乾淨才算。

### CRCT bin 規則實測（10-27 晚，validation/20261027-bin{1,2,2c,3,4}-*）
- **水平 bin 可用（R3 改寫）**：根因是分支 C 的 Hbin2 加主管線 Hbin 疊成 ÷9；照 res-custom `ogc_binpath` 清掉第二次 → b3x1-z1536 CDNG 完整、水平 ÷3。
  無 hook 對照 fov_r 0.679（重現舊失敗）。hook = `host/asm/binfilt.S`，`test_binfilt.py`（unicorn，5 突變全抓）。
- **R2 放寬**：單軸 1:1 + bin 可用（兩個方向都過）；兩軸 1:1 時 RWZM 1025 走分支 C（b3x3-z1025、b3x1-z1025 過）。
- 核：kh0／kh1／km1 時間雜訊 1.11–1.18，kh5（[0 64 0]）1.78；b3x3 0.87。kv0 與預設差異小。
- b3x3-z1536 fov_scale 0.970（容差邊界，畫面正常），其餘 0.975–0.98。
- 矩陣改成每軸「感光元件合併 × CRCT bin × RWZM」：40 種讀出 × {h1,h3}×{v1,v3}，RWZM 補足；1109 組（Raw；10/8 bit 之後）。
