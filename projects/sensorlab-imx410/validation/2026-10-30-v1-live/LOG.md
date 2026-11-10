# v1 上機清單（SensorLab-IMX410 v0.7.0test ＋ QSContainer v0.3.1），2026-10-30 12:19–12:26

Bei 授權開始；其他 session 已被告知相機占用。清單：`../../qs/README.md`「v1 上機清單」。
工具：`sl.py`（callfn sq_test／mem get，結果附加到 `results.jsonl`）、`rows.py`（私有選單清單）、`shot.sh`（截圖按編號、帶 `--size`）。

**結果：第 3 項選擇 2K 時 USB shell 停止回應（凍結），依規則停止。第 4–17 項未執行。**

## 第 0 項 部署 — PASS

- 備份（`backup/`）：`fpSup-dir-before.txt`、`LOAD.LOG`、`QSContainer_v0.2.4.BIN`（173 888 B，sha 2516eed9…）、
  `SensorLab-IMX410_v0.5.0test.BIN`（98 824 B，sha a627aa57…；卡上時間 06:53:02，比 menu-diag 晚，記錄可能已被寫回）。
- 原廠設定（`00-stock-settings-before.txt`，`setting readcam` 後）：imagesize 1920×1080、cam_frame_rate 6、movie_format 0、raw_bittype 0、cam_aspect 3、pic_crop_mode 0。
- `--settings-from` 重建（`build/`）：SensorLab 83a29493…（181 916 B，與預設 ce1f9704 只差 0x2C584–0x2C687 = rec_off 181 636 的記錄，41 bytes）；
  容器 c43d1e30…（176 608 B，與預設 59bdd136 只差 0x2B07C–0x2B1C7 = rec_off 176 252，106 bytes）。
- putfile 兩個新檔 → getfile 全長讀回（`readback/`）sha 相同 → `fl del` 刪 v0.2.4、v0.5.0test。
- 卡上（`backup/fpSup-dir-after.txt`）：QSContainer_v0.3.1、SensorLab-IMX410_v0.7.0test 各一份；沒有 SLTP、沒有 RES-Custom BIN
  （只有舊的 macOS `._RES-Custom_v0.1.5.BIN` 等 4 KB 資源分支檔，原本就在，沒動）。

## 第 1 項 開機 — PASS

- 12:20:33 `ui_drive.py reboot`，10.9 s 回 pong。`LOAD-boot1.LOG`：
  `0A C55BCC80 00000008 QSContainer_v0.3.1.BIN`、`0A C55F9D40 00000025 SensorLab-IMX410_v0.7.0test.BIN`，沒有 SLTP；
  另有 `0D 54435351 … QSC … C2DEAD7C`（容器服務註冊）。
- callfn getter 0xC0407E20 → 1；`sq_test 21` = 0；MENU 前 LV_CINE_MEDIUM，ap armed 1、active 0、commits 0；menu ready 0。

## 第 2 項 首個 MENU — PASS

- `02-pingloop-menu.txt`：MENUON 回覆逾時（rc −7，0.29 s，單次不算），接著 7 個 ping ERR，**最長空窗 2.31 s 後恢復**，之後全 pong（115/122）。
- 截圖 SS2767：MainB1（SHOOT 第 1 頁、焦點在分頁列），正常。
- `sq_test 29`（µs）：`[125217, 17885, 6, 107322, 2, 125217, 125217, 1, 48424337, 48549554, 48424342, 48442224, 60924, 664, 107287, 0]`
  → lt[7]=1；首次 leave 總計 125.2 ms = push 17.9 ms ＋ 選單 107.3 ms（fpui_stock_apply 60.9、slm_model 0.66、整個初始化 107.3）。
- `sq_test 31`：`[48383803, 48383811, 48424333, 48424335, 48549559, 48647978, 118, 1, 264175, 264175, 264175, 1]`
  → 首次 layout 整個 hook 264.2 ms：收集 40.5 ms、leave 125.2 ms、原廠 loader 到結束再 98.4 ms；寫回 118 µs。
- `sq_test 27`：ready 1、result 0、updates 1；清單數 7／8／40。`sq_test 17`：result 0、active 1、cur 1、mode 231、commits 1、commit_us 9 582。
- 秒級空窗不在我們的程式碼裡（合計 0.26 s），其餘約 2 s 是 GUI／LV 重建。sq_test(30) 拆分沒有做。

## 第 3 項 選單：解析度 — FAIL（凍結）

- RIGHT DOWN:2 RIGHT → 記錄設定（SS2768：格式 CinemaDNG／位元深度 RAW／解析度 3K／每秒幀數 30）。
- DOWN:2 RIGHT → 清單（SS2769）：1K、2K、3K（游標）、3.5K、4K…；`rows.py`：RES `1K 2K 3K 3.5K 4K 5K 6K *CUSTOM`（cur 2）——**清單內容符合預期**。
  DC 清單 `OG HD S35 APS-C S16 SQ *CUSTOM`；FPS 40 列 19.026…105.097 可選、119.88–1000 反灰、`*CUSTOM`。
- 12:23:5x `ui_drive.py UP OK`（UP→2K，OK 確定）。**之後 shell 再也沒有回應**：下一個 `mem get`（LOAD_DONE_US）讀 0／逾時，
  ping 12:24:15–12:25:59 每 1–5 s 一次全部 ERR（>100 s）。USB 裝置仍在 ioreg（SIGMA fp，USBSpeed 4），fpshd 行程還在。
  LCD 看不到；沒有截圖（SS2770 讀不到）。沒有做任何恢復動作。

### 離線推測（未上機證實）

OK 確定清單 → 原生變數改變事件 → `slm_changed`（`menu/slm_runtime.h:199`）→ `slm_pick` → **在 GUI 事件回呼裡同步 `sq_push`（commit：LV 停／啟）**
（`menu/slm_runtime.h:185-188`），接著 `ap_idle`、`slm_sync`（在同一個變數的事件裡再寫原生清單變數）。
第 2 項的 commit 在 leave()（layout）裡跑，正常；這是第一次在清單彈出、變數事件回呼中 commit。
疑點兩個：commit（LV reload）在選單 popup／事件回呼中執行；`slm_sync` 在 change-event 內重入。下一張卡建議做「pick 只記錄＋dirty，push 延到 leave／idle」的對照。

## 工具問題

- `tools/live/ui_shot.sh:13` 的 getfile 沒帶 `--size`，getfile 會去 `dir` 找檔 → 截斷後永遠「not readable」（SS2767 其實已存在）。改用 `shot.sh`（先 `--size 600000` 取得 file length 再抓）。
- `fpSup/fp_usb_shell/ui_drive.py:191` `where()`：`mem(APP_PTR)` 沒回該字就 KeyError（此次在記錄設定頁發生一次）。

## 結束時狀態

USB shell 不回應（凍結），相機未知（LCD 未觀察）。卡上：QSContainer_v0.3.1 ＋ SensorLab-IMX410_v0.7.0test（含遷移後記錄）。
最後的選擇可能已是 RES 2K（OK 已送出）。需 Bei 拔電池。截圖用到 SS2769（2770 若存在是凍結前的 CAPTURE）。

## 凍結確認

Bei 回報相機凍結（「卡住了」）。最後送出的指令：第 3 項，`ui_drive.py UP OK`（`key UPON` → 0.8 s → `key OKON`），約 12:23:5x
（最後一筆讀值 `i3-rows` 之後、第一次失敗的 mem get 之前）。最後看到的畫面是 SS2769：記錄設定的解析度清單、游標在 3K。
收到停止指示後沒有再送任何按鍵或 USB 指令。

## 離線分析與修正（v0.7.1test，同日，未上機）

- 凍結（第 3 項）：變數事件與 QS 轉盤一樣在 UI 執行緒（`C0560FB0` 回呼）。QS 轉盤在同樣的回呼裡 commit 38 次（LV 重載、carrier setter）都正常（qs-container apply1），
  所以「事件裡 commit」本身不是差別。差別是 `slm_sync` → `slm_model`：先刪光 SLM_RES 的列再重插，接著 `C05D83A8(type 1)`，
  它在 GUI 鎖內對每個綁定的清單同步呼叫 `C05CE8A0`，刪掉並重建 item 實例 —— 正是 OK 的 commit 動作序列還在執行的那個 popup。
  變數寫入 `C0593F30`／`C0593FE0` 只是入 GUI 佇列（`GUI_QUEUE_FULL` 上限 0x5DC），不會重入。最可能的原因 = 重建正在派送事件的清單（未上機證實）。
- 修法見 `qs/README.md` v0.7.1test。`tools/live/ui_shot.sh` 已改成帶 `--size`；`fpSup/fp_usb_shell/ui_drive.py` 的 `where()` 對漏回的字不再 KeyError。
