# v1 上機第三輪（SensorLab-IMX410 v0.7.2test ＋ QSContainer v0.3.2），2026-10-30 15:43–16:15

Bei 核准直接上機；peer 已由 coordinator 通知。工具：`sl.py`／`rows.py`／`dngcheck.py`／`shot.sh`（從 live2 複製，shot 目錄改本資料夾），
新增 `hstep.sh`／`wstep.sh`（關 QS → LV 截圖 → dc_probe → 重開 DC 子 QS）、`dial.sh`（逐格送 CMDDIAL）、`tile.py`（裁 QS 格子看數字）。
截圖 `shots/SSnnnn-tag.jpg`（SS2820–2886），讀值 `results.jsonl`，動作 `actions.txt`。

## 部署 — PASS
- 備份 `backup/`：QSContainer_v0.3.1（c43d1e30…）、SensorLab v0.7.1test（5f6ea5ee…，15:01 有寫回記錄）、LOAD.LOG、dir before/after。
- `--settings-from` 重建 → `build/`：SensorLab v0.7.2test **1b216037…**（182 944 B，與預設 af2a7271 只差 rec 區 182 665–182 924）、
  QSContainer v0.3.2 **4ac035ef…**（176 736 B，只差 176 381–176 712）。
- `deploy_v3`（整檔讀回）OK；再獨立 getfile 讀回 sha 相同（`readback/`）；`fl del` 兩個舊版 True。卡上只剩 v0.3.2、v0.7.2test；無 SLTP、無 RES-Custom BIN。
- `ui_drive.py reboot`（獨立一步）12.1 s。`LOAD-boot1.LOG`：`0A … QSContainer_v0.3.2.BIN`、`0A C55F9D40 00000025 SensorLab-IMX410_v0.7.2test.BIN`。sq_test 21 = 0，0xC343B590 = 12。

## v0.7.2 修正
- (a) AEL — PASS。開機後第一次開 QS（第一次 QS 鍵回覆逾時但鍵有到），RIGHT:3 到 FPS，**第一下 AEL 就開 FPS 子 QS**（SS2822）。
  選單 FPS 清單 → `CUSTOM 30.018` → RIGHT 跳 FPS 子 QS、焦點 FINE（SS2828）→ **AEL 一下就回主 QS 的 FPS 格**（SS2829）。
- (b) `1000.0` — PASS。清單最後一列顯示 `1000.0`（反灰），不是「關閉」（SS2826）。清單 47 列，CUSTOM 在第 7 列（`CUSTOM 30.018`），清單尾沒有單獨的 CUSTOM 列。
- (c) RATIO — PASS。DC 子 QS 第 4 格：上方 `1.497 : 1`、下方鎖頭圖示，互不重疊（SS2830）。格子沒有「RATIO」字樣（比例數字當標題）。
- 首個 MENU：pingloop 最長空窗 0.24 s（`02-pingloop-menu.txt`）。

## 第 14 項 HD 2K 11b 3x2 — PASS
- 設定：DC HD、RES 2K（2000×1124）、RECIPE 11b 3x2、**FPS 30.018**（上一輪是 19.026；這次 CUSTOM 測試把 FPS 改成 30.018，沒改回），MB/s 105（SS2832）。
- 待機（`i14-standby-t0`／`-t30`）：**gated 0**、active 1、mode_id 231、standby_picks 9667 → 14075（持續增加）、refusals 0、blacks 0；
  sel key 21、rw×rh 2016×1134、vmax 7269；REG 列 vstart 377／vsize 851（同 live2）。60 次 ping 全回（`14-standby-ping.txt`）。LV 16:9 乾淨無花屏（SS2833）。
  註：待機時 W(0xC343B590) 讀 12（原廠 id），不是 230／231。
- `rec_take.sh 3`（停錄後等 12 s）：腳本 ping 正常。錄影中不碰 USB，所以「錄影中」的 0xC343B590 沒讀；**錄後兩次讀都是 231（0xE7）**，與 ap.mode_id 231 相同；recrates 1。
- 片段 `A001_266`（81 張，3 508 224 B）。`dng/C_A001_266_000040.DNG`：raster **2016×1134**、BitsPerSample **12**、BlackLevel 255.87×4、WhiteLevel 4095、
  DefaultCrop 2000×1124（= 看到尺寸 +16／+10）、FrameRate 30.015；mod 4 = 0.259/0.239/0.264/0.238。場景很暗（max 409），彩色預覽正常（`dng/…png`）。

## 第 15 項 回放安全 — 未做（需要看 LCD），步驟交 Bei（見報告）

## 第 16 項 暖開機 — 部分 PASS（用 `ui_drive.py reboot` 代替；撥開關的暖開機要 Bei 手動）
- `LOAD-boot2.LOG` 兩個都 `0A`；QS 選擇保留（HD／2K 2000×1124／30.018／11b 3x2，SS2834）；首個 MENU pingloop 最長空窗 0.22 s；
  sq_test 29 首次 leave 131.7 ms（push 24.4 ＋ 選單 107.3，fpui_stock_apply 58.0）。

## DC 高度（OG，寬 6048）— dc_probe ＋ LV 截圖
| HEIGHT | 比例 | rw×rh | REG vstart／vsize | LV 外框（1024×682 螢幕） | 判定 |
|---|---|---|---|---|---|
| 4040 | 1.497 | 2016×1346 | 0／0（不開窗） | 全螢幕 3:2 | 正常 |
| 3800 | 1.592 | 2016×1266 | 181／950 | 全螢幕 3:2 | 裁切後被**垂直拉伸**填滿 3:2 |
| 3600 | 1.680 | 2016×1200 | 281／900 | 全螢幕 3:2 | 同上 |
| 3520 | 1.718 | 2016×1172 | 321／880 | 全螢幕 3:2 | 同上 |
| 3500 | 1.728 | 2016×1166 | 329／875 | 16:9 上下黑邊（576 列） | 有框，比例差 3% |
| 3400 | 1.779 | 2016×1132 | 381／850 | 16:9（576 列） | 正確 |
| 3300 | 1.833 | 2016×1100 | 429／825 | 16:9（576 列） | 有框，比例差 3% |
| 3100 | 1.951 | 2016×1032 | 529／775 | 1.954（524 列） | 正確 |
- 全部 gated 0、refusals 0、key 21、hbin／vbin 1、vmax 7269；mode_id 230／231 交替（正常）。
- vsize = HEIGHT／4；vstart = (4162 − HEIGHT)／2（以 4162 列為中心置中；3100 差 2 列，應是對齊）。
- 與 4040 的畫面做相關比對：每一步「中央裁切」都比「整張壓扁」吻合（0.984–0.997 對 0.877–0.978）→ **感光元件確實裁了，FOV 有變小**；
  問題只在 LV 的外框：3520–3800 都被塞進 3:2 外框（變形），≤3500 才換 16:9 外框。

## DC 寬度（OG，高 4040；3500 走不到，前轉盤一格 16，用 3504）
| WIDTH | 比例 | rw×rh | LV 外框（QS 關） | QS 背景外框 | 判定 |
|---|---|---|---|---|---|
| 6048 | 1.497 | 2016×1346 | 全螢幕 1.501 | 全螢幕 | 正常 |
| 5600 | 1.386 | 1856×1346 | 全螢幕 1.501 | 全螢幕 | 裁切（0.989 對 0.966）但**水平拉伸** |
| 5088 | 1.259 | 1696×1346 | 全螢幕 1.501 | 全螢幕 | 拉伸 |
| 5040 | 1.248 | 1680×1346 | 全螢幕 1.501 | 左右黑邊 1.243 | LV 拉伸；QS 背景正確 |
| 5008 | 1.240 | 1664×1346 | 全螢幕 1.501 | 左右黑邊 1.243 | 同上 |
| 4800 | 1.188 | 1600×1346 | 左右黑邊 1.192 | 1.185 | 正確 |
| 4144 | 1.026 | 1376×1346 | 1.038 | — | 正確 |
| 3984 | 0.986 | 1328×1346 | 0.991 | — | 正確 |
| 3504 | 0.867 | 1168×1346 | 0.870 | — | 正確，裁切（0.902 對 0.555） |
- 全部 gated 0、refusals 0、key 21、hbin／vbin 1、vmax 7269、REG V 窗 0／0；H 窗暫存器 dc_probe 沒讀（不知道位址）。
- **斷點**：LV（QS 關）在 5008 → 4800 之間從「3:2 外框拉伸」換成「正確左右黑邊」；QS 背景在 5088 → 5040 之間換。兩條路斷點不同。
- 6048 → 5008：畫面是**裁切**（FOV 變小），不是縮放；但 5008–5600 的 LV 被拉寬填滿 3:2，**有變形**。

## 異常（非凍結）
- 從寬度第 3 步起，關 QS 後約 1.5 s 的 LV 截圖是**假色**＋資訊列（`48 FPS`、1/125、F2.0、測光 +0.3 → +2.7、ISO 4000 → 20000）（SS2864、2866、2869、2871、2875–2881）。
  QS 開著時、以及關 QS 後等 8 s 再拍（SS2872、SS2882）都是正常彩色、沒有資訊列。`setting get pic_false_color_on` = 0、`exp_comp` = 0。
  原因未查。我沒送過 DISP（只有 SS2873 試按一次 DISP，畫面沒變）。ISO 一路往上，最後 LV 很亮（SS2885／2886）。
- 從 DC 子 QS 用 QS 鍵關掉再開，主 QS 的焦點不固定（高度那段是 RES，寬度那段是 DC），`ui_drive.py where` 沒有 QS 焦點，只能靠截圖。

## 第 17 項 收尾 — PASS
- 先把 QS 改回開場的選擇：OG／2K 2000×1332／19.026／11b 3x2（SS2885）。
- `sq_test(22)` → active 0、mode_id 0、commits 157、refusals 0；0xC343B590 = 12（與開機時相同）；原廠 cam_movie_format 0、imagesize 1920×1080、cam_frame_rate 6。
  LV 原廠 16:9（SS2886）；ping 正常。

## 結束時狀態
相機有回應，SensorLab 已回原廠（active 0），QS 記錄 = OG／2K／19.026／11b 3x2。卡上：QSContainer_v0.3.2（4ac035ef）＋ SensorLab-IMX410_v0.7.2test（寫回記錄後的版本 15:50）。
CINE 編輯器格子沒動（`21 12 23 25 57 50 59 60`）。新片段 A001_266（HD 2K）。截圖用到 SS2886。
