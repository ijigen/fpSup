# v1 上機清單第二輪（SensorLab-IMX410 v0.7.1test ＋ QSContainer v0.3.1），2026-10-30 13:28–

Bei 核准直接上機；其他 session 已被告知相機占用。清單：`../../qs/README.md`「v1 上機清單」＋ v0.7.1test 段。
工具（本資料夾）：`sl.py`（從上一輪複製；**SQ_OFF 改成 0x7B61**＝build-0.7.1test.json 的 sq_test_off 31585，舊值 0x79DF 是 v0.7.0 的；
`menu` 多讀 `owed`（slm_state +7484）；新增 `sel`（sq_test 18 = ap_sel）、`regs`（firmware lk_reg 0xC0326DB8(HOLDER 0xC343B67C, mode)
→ REGDESC 0xC0B5FDA4 的 REG 列，word 1+i = REG_ORDER[i]：0x0003→w2、0x0022..25→w6..9）、`dc`）、`rows.py`、`shot.sh`、`dngcheck.py`。
截圖：`shots/SSnnnn-tag.jpg`，每張都看過。

## 第 0 項 部署 — PASS
- 備份 `backup/`：`fpSup-dir-before.txt`、`LOAD.LOG`、`QSContainer_v0.3.1.BIN`（c43d1e30…，與上一輪讀回相同）、
  `SensorLab-IMX410_v0.7.0test.BIN`（fe3d6d02…，**與上一輪部署的 83a29493 不同 = 記錄被寫回過**）。
- `build_slqs.py --settings-from backup/…v0.7.0test.BIN` → `build/sl/`：0b505eb2…（182 892 B），與預設 c9a4e8bd 只差
  182 612–182 871（rec_off 182 612，41 bytes）。
- putfile → getfile 全長 182 892 讀回 sha 相同（`readback/`）→ `fl del` v0.7.0test（True）。`backup/fpSup-dir-after.txt`：
  QSContainer_v0.3.1、SensorLab-IMX410_v0.7.1test 各一份，無 SLTP、無 RES-Custom BIN（只有原本的 `._RES-Custom_v0.1.5.BIN` 資源分支檔）。

## 第 1 項 開機 — PASS
- `ui_drive.py reboot`（獨立一步）10.9 s。`LOAD-boot1.LOG`：`0A C55BCC80 00000008 QSContainer_v0.3.1.BIN`、
  `0A C55F9D40 00000025 SensorLab-IMX410_v0.7.1test.BIN`，`0D 54435351 … QSC … C2DEAD7C`，無 SLTP。
- `sq_test 21` = 0；MENU 前 LV_CINE_MEDIUM，ap armed 1、active 0；`0xC343B590` = 12（regs 讀出 stock 列 id 12，0x0003/0x22–25 = 0）。

## 第 2 項 首個 MENU — PASS
- `02-pingloop-menu.txt`：MENUON rc 0（0.10 s），**130/131 pong，最長空窗 0.20 s**（上一輪 2.31 s）。SS2770 MainB1。
- `sq_test 29`：`[121397, 18632, 6, 102754, 1, 121397, 121397, 1, …, 54146, 1782, 102749, 0]`：首次 leave 121.4 ms = push 18.6 + 選單 102.8
  （fpui_stock_apply 54.1、slm_model 1.8）。`sq_test 31`：首次 layout 256.8 ms，寫回 134 µs。
- 27：ready 1、result 0、updates 1；清單 7／8／40；**記錄裡 DC = CUSTOM（cur0 6）、RES cur 2（3K）、FPS cur 4（29.97）**。17：active 1、mode 231、commits 1。

## 第 3 項 選單：解析度 — PASS（凍結已修）
- SS2771 記錄設定（CinemaDNG／RAW／3K／29.97）；SS2772 清單 1K…6K（游標 3K）＋ CUSTOM。
- UP → 2K，`pingloop --key OK`（`03-pingloop-ok.txt`）：**103/104 pong，最長空窗 0.24 s，shell 照常回應**。
- OK 後：27 picks 0→1、**owed 1**、rejected 0；17 commits **1→1 不變**；摘要立刻變 2K（SS2773）。
- MENU 離開（`03-pingloop-leave.txt`，最長空窗 2.20 s 後恢復）：commits 2、**owed 0**、mode 230、FPS 清單 40→47；QS RES = 2K 2000×1070（SS2774）。

## 第 4 項 選單：每秒幀數 — PASS（附一個顯示 bug）
- 清單 47 列（SS2775）：23.564…194.458 可選，~200…~1000 反灰，`*CUSTOM`。選 30（OK，ping 無中斷）→ owed 1；離開後 commits 3，QS FPS 30（SS2777）。
- **bug**：清單倒數第二列（rows.py 是 `~1000`）在 LCD 顯示成「關閉」（SS2784）。原生清單最後一個原廠項的文字蓋過我們的列文字。
- 細調後清單多一列 `*CUSTOM 30.001`，記錄設定摘要顯示 `30.001`（SS2789；預期寫 `CUSTOM 59.9xx`，實際摘要只有數字）。

## 第 5 項 選單：位元深度 — PASS
SS2776：8 bit、10 bit 反灰，RAW bit 可選。

## 第 6 項 選單：DC — PASS
SS2778：OG、HD、S35、APS-C、S16、SQ、CUSTOM（列文字底線稍擠）。選 OG：owed 1 → 離開後 commits 4、mode 230；QS DC OG、RES 2K 變 2000×1332（SS2779）。

## 第 7 項 CUSTOM 跳轉 — PASS（AEL 返回有問題，見第 9 項）
- DC CUSTOM（SS2780→2781）：QS_CINE，DC 子 QS，焦點第 1 格（DC OG 6048×4040）；menu opened 1、go 1，ping 最長空窗 2.39 s。
- RES CUSTOM（SS2782→2783）：RES 子 QS，焦點第 1 格（2K 2000×1332）；opened 2。清單最後一列 CUSTOM 被切在畫面底（SS2782）。
- FPS CUSTOM（SS2784→2785）：FPS 子 QS（SL FPS、FINE），**焦點 FINE，下方 `◀ 30.000 ▶`**；opened 3。
  前轉盤 +1 → 30.001（SS2786，**commits 4→5 在轉的當下就套用**）；**AEL 沒反應**（SS2787）；LEFT 移焦點 → 清單插入黃色 30.001（SS2788）。
  再進選單 FPS 列摘要 30.001、清單 `*CUSTOM 30.001`，沒有重複跳（SS2789）。

## 第 8 項 QS 取代模式 — PASS
- 編輯器（MainY2 → 自定QS，SS2798–2804）：清單 **35 項**（舊 39，少了 4 個重複列）；SL 格顯示原廠名稱（格式／DC裁剪模式／解析度／每秒幀數）。
  四格各 OK 選原廠項 → `0xC31B0ABC` = `21 12 23 25 57 50 59 60`。
- 開 QS（SS2805）：FORMAT DNG 12bit、DC OG、RES 2K、FPS 30.018 都是 SensorLab 的值；RECIPE、MB/s、QR 仍在。關 QS 後 slots 不變。

## 第 9 項 QS 的 FPS 子 QS — PASS（附 AEL 問題）
- 主 QS 的 FPS 按 AEL：前兩次沒反應（SS2791、2792，只顯示「AEL 更多選項」）；焦點經過 K 格後再按才開（SS2793）——與 qs-container live4 第 8 點同一個現象。
- FINE 前轉盤 +1、後轉盤 +1 → 30.019（SS2794；後轉盤 = 10 步），commits 5→7（**每轉一格就套用**，離開時不再 +1）。
- 三種離開：移焦點（SS2788）、AEL（SS2795，FINE 中按 AEL 有效）、關 QS（SS2796/2797，30.019→前轉盤 −1→30.018）：都只留一個黃色細調值並生效。
- 配方上限的細虛線：清單裡 37.140 等之下有虛線（SS2788），上限點沒特別檢查。

## 第 10 項 QR — PASS
SS2806：QR 畫在 QR 格（白底）。OpenCV 解碼 = `https://ijigen.github.io/fpSup/sensor_lab_imx410/#G9B-QfgVC6KSQOPlCKxIfQU0MpAXoPyL0D7zw`，
與 `sq_test 13`（37 字）相同。再按 AEL 隱藏（SS2807）。（手機掃描與 404 需 Bei 自己確認。）

## 第 11 項 MB/s — PASS（部分：記下的配方都符合公式）
公式 `fps × (W×H×b/8 + 79 184)/1e6`，W×H 用 DNG raster（看到尺寸 +16／+10），b 用容器位元數：
| 配方 | 格 | 計算 | 實檔 |
|---|---|---|---|
| OG 2K 14b 1x2 @30.018（raster 2016×1342，12-bit 容器） | 124 | 124.2 | — |
| OG 2K 14b 1x3 @30.018（2016×1330，12） | 123 | 123.1 | DNG 4 101 120 B（公式 4 101 104 ＋16） |
| OG 6K 14b 1x1 @19.026（6048×4040，14） | 815 | 815.0 | DNG 42 838 528 B |
| HD 3.5K 14b 1x1 @19.026 | 208 | 未算 | — |
| HD 2K（11b 3x3／3x2…）@19.026 | 67 | 未算 | — |
SD 上數字是白色；LL 小字有值（6K 時 `LL ?`）。顏色依媒體未切 SSD 驗。

## 第 12 項 錄影 A：OG 2K 14b 1x3，12-bit 容器 — PASS
- 錄前 SS2809：FORMAT 12bit、RECIPE 14b 1x3、RES 2000×1320。`rec_take.sh 3`（13:53:11），之後等 ≥10 s。
- `0xC343B590` = **231**；ap recrates 1、refusals 0。片段 `\CINEMA\A001_264`，81 張 DNG。
- `dng/A_A001_264_000040.DNG`：raster 2016×1330、**BitsPerSample 12**、BlackLevel 256×4、WhiteLevel 4095、DefaultCrop 2000×1320（= RES 格）、
  FrameRate 30.018；mod 4 = 0.25/0.25/0.25/0.25；p0.1 258、最小 255（暗部貼著 256，無 MaskedAreas，無 OB 可比）。彩色預覽 `A_…png` 正常（散焦的玩偶）。

## 第 13 項 錄影 B：OG 6K 14b 1x1，真 14 — PASS（尺寸與清單寫的不同）
- RES 6K = **6032×4030**（不是清單寫的 6048×4040）；FPS 降到 19.026 後自動選 14b 1x1，FORMAT 14bit，MB/s 815（SS2811–2813）。
- `rec_take.sh 3`（13:56:18）：`0xC343B590` = 230；ap recrates 2、**blacks 21**。`A001_265` 只有 6 張（815 MB/s ≫ SD，緩衝滿後相機自己停，預期）。
- `dng/B_A001_265_000003.DNG`：**raster 6048×4040、BitsPerSample 14、BlackLevel 1024×4、WhiteLevel 16383**、DefaultCrop 6032×4030、FrameRate 19.026；
  mod 4 = 0.248/0.252/0.248/0.252（真 14）；p0.1 1029、p1 1036（貼著 1024）。左右邊 0／1／6046／6047 欄有 8 個 ~522 的孤立像素（壞點級）。彩色預覽正常。

## 第 14 項 錄影 C：HD 2K — **FAIL：錄影後 USB shell 不回應（凍結），依規則停止**
- 設定：DC HD、RES 2K（2000×1124）、FPS 19.026。**HD 2K 的配方清單沒有 `12b 3x2`**（SS2815–2818：12b 1x3、14b 1x1、14b 1x2、14b 1x3、12b 2x2、
  11b 2x2、12b 3x3、11b 3x3、11b 2x1、11b 2x3、11b 3x2、11b 1x2、11b 1x3），改用 **11b 3x2**（SS2819）。
- 錄前（`i14-preRec`，13:58:47）：commits 38、mode 230、**gated 613（待機閘門擋下 ✓）**；sel key 21、hm 330、vmax 11468；
  REG 列 0x0003 = 1、0x0022/23 = 121/1（V start 377）、0x0024/25 = 83/3（V size 851）。
- **最後動作：13:58:55 `rec_take.sh 3`**（MOVON/OFF → 3 s → MOVON/OFF → 5 s → ping）。腳本自己的 ping 就 ERR；之後 `status get is_recording`、
  `mem get` 逾時（rc −7），`cave` 報 LOAD_DONE_US reads zero。20 s 後再 ping 一次仍 ERR（13:59:40）。USB 裝置仍在 ioreg；fpshd 行程存在（PID 已變 16337，原 26349，不是我重啟的）。
- 沒有做任何恢復動作。相機是否仍在錄影（停止脈衝可能沒送到）、LCD 狀態未知。

第 15–17 項與 DC 高度調查未執行。

## 工具備註
- `rec_take.sh`（`fpSup/fp_usb_shell/rec_take.sh:11`）停錄後 5 s 就 ping，比「停錄後等 10 秒」的規則早。
- 在 QS 裡第一次 CAPTURE 鍵回覆逾時、沒拍到（SS2774 第二次才成功）。
- （事後離線修正）`rec_take.sh` 停錄後的等待改成具名常數 `POST_STOP_WAIT=12`（≥10 s）。
- **fpshd PID 換掉不是 13:59 發生的**：`ps -o lstart` 顯示 PID 16337 從 **13:31:23** 就在跑（PPID 1），`/tmp/fpshd.sock` 也是 13:31 建的
  ＝第 1 項 `ui_drive.py reboot`（`pkill -9 -f fpshd` 後重開，`ui_drive.py:reboot()`）換的；26349 是開機前那個。13:59 沒有任何東西重啟它。
  沒有 launchd（~/Library/LaunchAgents、/Library/Launch* 都沒有 fpshd）、fpshd.c 不會 fork/exec 自己、fpsh／putfile／callfn／getfile 都不會重啟；
  會殺／重開 daemon 的只有 `ui_drive.py reboot`、`bootmeasure.py`、`fastreboot.py now`（及 `projects/imx410-lab/sweep.py`），都是靜默的。
  已改成每次重啟都印一行 `fpshd restarted by <tool> because <reason>; old pid … -> new pid …` 到 stderr 並追加到
  `~/Library/Logs/fpshd-restarts.log`（`fpSup/fp_usb_shell/daemon_restart_log.py`；行為不變，不加旗標——reboot 本來就必須重開 daemon）。
- `sl.py` 不再寫死 SQ_OFF：從 LOAD-current.LOG 的 SensorLab 版本找 `../../qs/out/build-<ver>.json` 的 `sq_test_off`（或 `--version`／`--build`），找不到就報錯。
- DC 高度調查的讀值工具：`../../tools/live/dc_probe.py`（ap 17＋sel 18＋lk_reg REG 列，一行 JSON，`--tag`／`--out`），離線測試 `test_dc_probe.py`。

## 結束時狀態
USB shell 不回應。卡上：QSContainer_v0.3.1 ＋ SensorLab-IMX410_v0.7.1test（0b505eb2，含遷移記錄）。QS 選擇：DC HD、RES 2K、FPS 19.026、RECIPE 11b 3x2。
CINE 編輯器格子 = `21 12 23 25 57 50 59 60`（第 8 項改成原廠 id，未還原）。截圖用到 SS2819。片段 A001_264（A）、A001_265（B）、A001_266（C，內容未讀）。
