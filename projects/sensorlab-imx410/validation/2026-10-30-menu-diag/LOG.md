# 第一次 MENU 上機診斷，2026-10-30 06:41–06:48

Bei 授權上機；沒改卡、沒改原始碼、沒錄影、沒回放。工具：`diag.py`（mem get 讀狀態、callfn 呼叫 sq_test、
不寫記憶體），`fpSup/fp_usb_shell/ui_shot.sh N`（截圖按編號取，`dir` 截斷在 SS__2577）。

## ⚠ 前提不成立：卡上不是 v0.6.0 組合

- `host/fpsh dir \fpSup` 與當次 LOAD.LOG（`LOAD-initial.LOG`、`LOAD-boot1.LOG`）：
  **QSContainer_v0.2.4（173 888 B，05:06 寫入）＋ SensorLab-IMX410_v0.5.0test（98 824 B，05:45 寫入），沒有 SLTP.BIN。**
  這就是 progress.json `recovery` 記的 rollback。live-v1 manifest 的 v0.3.0 / v0.6.0test / SLTP 已不在卡上。
- 依「不改卡」規則，沒有重新部署 v0.6.0；以下是 **rollback 卡的基準測試**，不能直接證明 v0.6.0 的阻塞點。

## 時間線

| 時間 | 動作 | 結果 |
|---|---|---|
| 06:41 | ping、fpshd --status | pong；fpshd 3.3.0、stalls 0、fault none；is_recording 0、app 2 |
| 06:43 | LOAD.LOG | SensorLab v0.5.0test @C55F8280 claims 0x1B=27；QSContainer v0.2.4 @C55BCC80 claims 8；Lossless/ISPL/LUT/Stop-FX/SUPMGR/USB-Shell 也載入 |
| 06:44 | 截圖 2764 | 待機 LV、16:9 黑邊、清楚（原廠） |
| 06:44:39 | `ui_drive.py reboot` | 10.4 s 回 pong；LOAD.LOG 同上 |
| 06:44:59 | MENU 前讀狀態（`01-boot1-preMENU.json`） | LV_CINE_MEDIUM；ap armed 1、active 0、commits 0；**sq_test(21) ap_init_rc = 0**；容器 lay_calls 0、N 0、qs_ready 0 |
| 06:45:20 | **第一次 MENU** | `key MENUON` 0.20 s 回覆，無逾時 |
| 06:45:24–28 | 每 0.6 s ping＋app_current ×8 | 全部 pong、app 5 |
| 06:45:3x | 讀狀態（`02-boot1-afterMENU.json`） | MainB1；**active 1、cur 1、commits 1、result 0、commit_us 15 712 µs**、lv_reloads 1；容器 phase 2、N 7、lay_calls 1、qs_ready 1、leaves 1、posts 182 |
| | 截圖 2765 | SHOOT 第 1 頁正常（焦點在分頁列） |
| 06:46 | MENU 退出 | **`key` 回 frame0 TIMEOUT（fpshd 預設 200 ms），1.5 s 後 ping 也 ERR**；之後 app 2、LV_CINE_MEDIUM，commits 仍 1 |
| 06:46:49 | 100 ms ping 迴圈＋MENU 開→4 s→MENU 關（`04-pingloop-open-exit.txt`） | 開：無空窗；**關：shell 約 2 s 不回（5 個 ERR，14.11→~16.2）**，之後恢復 |
| 06:47 | callfn sq_test(22)（`05-op22.json`） | 回 0；active 0、lv_reloads 2 |
| 06:47:21 | 同樣 ping 迴圈（`06-pingloop-stock-open-exit.txt`） | 開：1 個 ERR（緊接 MENU）；關：無空窗。**但開 MENU 時 leave() 又 commit 了一次：commits 2、active 1、lv_reloads 3** |
| 06:48 | 截圖 2766 | 待機 LV，全高 3:2（無黑邊，配方 LV），畫面灰、失焦樣（不是花屏）；ping、is_recording 0 正常 |

## 判讀

1. **rollback 卡的第一次 MENU 不阻塞**：回覆 0.2 s、10 秒內全 pong，commit 15.7 ms。所以 live-v1 的逾時是 v0.6.0／v0.3.0／SLTP 帶進來的，或者只是傳輸掉包，舊的資料分不出來（見 2）。
2. **「key 逾時」這個證據本身很弱**：fpshd 預設 200 ms 就判逾時（`host/fpshd.c:98`），傳輸大約每十個指令會掉一個。
   live-v1 `01-menu-open.json` 只有一行 `frame0 rc=-7`，沒有記時間，也沒有連續 ping。今天退出選單時也出現同樣的 ERR，加上約 2 s 的 shell 空窗，相機本身沒事。
   live-v1 之後的讀值（`04-menu-diag.json`）其實正常：apply result 0、commit_us 9 403、menu ready 1 result 0、updates 11。
3. **「截圖停了」很可能是工具問題**：`dir \DCIM\100SIGMA` 回覆上限 16 KB，今天只列到 SS__2577，但檔案已到 2763。
   `ui_drive.shot` 靠 dir 找新檔，所以一定會說 no new screenshot。今天按編號取（2764–2766）都正常。
4. **選單開關造成 shell 短暫不回**（rollback 卡）：一次發生在退出（約 2 s，沒有 commit），一次發生在打開（有 commit 的那次）。
   這是 GUI／LV 重建期間 shell 任務搶不到 CPU 或 USB 的現象，不是凍結。沒有原廠卡對照，不能說是我們造成的。
5. **sq_test(22) 撐不過下一次 MENU**：v0.5.0test 的 leave() 每次 layout load 都會把 record 裡的選擇重新送出（apply1 LOG §3 記的是「第一次」，實際上每次都送）。
   所以第 7 步「MENU 前先 22 回原廠」在這個設計下隔離不了：一開選單就又套用了。要隔離，需要不會重推的開關（見建議）。

## 相機狀態（結束時）

CINE 待機 app 2，沒在錄影，ping 正常。SensorLab v0.5.0test active 1（record 的選擇，LV 全高 3:2），容器 v0.2.4 正常。
卡內容沒動（rollback 組合）。截圖編號用到 SS__2766。
