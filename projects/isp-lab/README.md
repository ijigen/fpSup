# isp-lab — ISP 路徑研究（2026-10-23 起）
> **2026-10-27 退版**：10-26 接手的工作已整包封存在 [`archive/handoff-20261026/`](archive/handoff-20261026/REVERT.md)；現行版本 = 交接時的狀態＋3 處核對過的 sup 修正。

研究工具，不是產品。和 imx410-lab 一起作為 RES-Custom2 的依據。
先讀：[notes/RESEARCH_PLAN.md](notes/RESEARCH_PLAN.md)（目標、檢查點、階段、分工）、
[notes/ISP_CAPABILITY_MAP.md](notes/ISP_CAPABILITY_MAP.md)（每一級的能力與待解）、
[notes/RESLAB_AUDIT.md](notes/RESLAB_AUDIT.md)（res-lab 結論哪些能用）。

**2026-10-26 接手進度**：[結果與交接](validation/20261026-resume-preflight-01/RESULTS.md)。修正推送結束後漏等 quiet、LV 失敗時未清理與重複 callfn 配置；主機端 46 項、控制 task 模擬 9 項通過。
真機：待機 LV 8/8 張且正常關閉、自動啟停成功、停錄後推回 13 個 DNG 候選，其中 **10 個與卡檔逐位元組相同，3 個尚須篩除／解釋**。
實際錄影為 3024×2010；選單雖回報 FHD，這輪不能當作原廠 FHD 校準。下一步先查候選完整性與版本篩選。

## 紀錄保存（2026-10-26 起）

每次實驗的影像、原始串流、JSON 與日誌都無損打包為 `validation/<實驗>/evidence.tar.zst`；
Git 保存壓縮檔、逐檔大小與 SHA-256 的 `ARCHIVE.json`，以及可直接閱讀的 `RESULTS.md`。
本機保留解壓工作檔，供重播測試使用；結果頁內原始檔案連結指向這些工作檔。

```sh
python3 -B host/archive_validation.py verify validation/實驗名稱
zstd -dc validation/實驗名稱/evidence.tar.zst | tar -xf - -C 空的還原目錄
```

`pack` 會逐檔解碼核對內容，成功才替換舊壓縮檔；不會刪除本機原始證據。

## 工具

| 檔 | 內容 | 狀態 |
|---|---|---|
| `sup/`（ISPL.BIN） | DNG 錄進 DRAM：從 imx410-lab 的 IMXL sink 分出（來源 sha256 在 `sup/UPSTREAM.sha256`）。加了：取樣政策（先留 K 個 block，之後每隔一段時間留一個，其餘丟棄）、每個 block 一行紀錄、控制 task 自己按 REC 開始與停止（`FUN_c03D9C20` 執行 `key MOVON/MOVOFF`，同原廠 FUN_c0405ba0 的錄影腳本）。修了 IMXL 位址檢查在 0xC0000000 以上溢位繞回的 bug | unicorn 27 項。**⛔ 擱置（10-23）**：兩次上機錄影都停不下來（第二次連實體 REC 都停不了），見 [validation/20261023-ispl-take](validation/20261023-ispl-take/RESULTS.md)。isp-lab 改成不錄影為主 |
| `host/ispl.py` | ISPL 主機工具：`take`（借記憶體＋log、寫參數、最後寫 ctl＝armed，之後完全不送指令直到停錄後 10 秒）、`status`、`pull`（拆 DNG、block 紀錄檢查 seq 連續與帳目）、`disarm`。錄影判斷用原生 `status get is_recording`；ISPL 借用 `imxl.heap`（class 0），ISPC 不借影像記憶體 | ISPL sink 上機失敗後擱置；**10-26 `--ctl-only` 自動啟停通過**；舊 sink 配置紀錄不會被 ISPC 釋放 |
| `sup/ix_push.c` | 相機端推送引擎（FPP1 over EP83）：header＋TRB 鏈放 sup 狀態、經非快取別名寫；占用 ctx 3 兩格表、release 還原；mode 0 忙就跳過、mode 1 等 | unicorn `PushEngineTests` 8 項＋CRC 突變；**10-26 上機**：待機 LV 8 張、停錄後 DNG 候選 13 個，傳輸全部完整 |
| `sup/ix_cdng.c` | 停錄後在控制 task 掃 RAW 區、只推最新時間戳的 DNG 候選（source 4、fmt 5）；`cd_go` 或 ISPC 自己錄完 `cd_after_ms` 後觸發 | unicorn `CdngTests` 4 項＋突變；**10-26 手動 cd_go 上機**：13 個候選中 10 個與卡檔相同；最終版本／完整性篩選未完成，自動 cd_after_ms 未驗 |
| `sup/ep83send.S` ＋ `host/ep83_m1.py` | 里程碑 1：一塊 16 KiB 從 EP83 推一次、主機逐位元組比對（沿用 `EP83` 指令） | unicorn 3 項＋突變；10-25 首次被 interrupt/64 描述元擋下，換開發版及重新列舉後 **16384 B 逐位元組相同**（[結果](validation/20261025-push-live/m1/result.json)） |
| `cards/build_devshell.py` | 開發版 v4 USB shell：發行版＋patches.py PUSH（目標 EP83 → bulk 1024）。不改共用檔 | **10-25 已部署**、完整讀回相符；重新插線後實際 bulk/64，也可完成推送；本輪沿用，沒有重部署 |
| `host/lvpush_live.py` | 有張數上限的待機 LV 推送；收完等待 quiet，再停用與核對計數，錯誤亦保存報告 | **10-26 上機**：8/8 張 1620×1080，正常關閉；離線涵蓋斷線、中斷 arm、清理失敗與不完整接收 |
| `host/rawpool.py` | 停錄後 RAW 區（class 10）裡還留著的 CDNG：probe（類別表與鏈）、scan（MEM1 讀整區、收下 DNG）、match（跟卡上檔案比 sha256）。錄影中、RAW 仍在用時拒絕 | 離線 6 項＋突變；**10-25 上機**：停錄後最後 14 幀與卡上逐位元組相同（[validation/20261025-rawpool-01](validation/20261025-rawpool-01/RESULTS.md)） |
| `host/bufa1.py` | 待機 BUFA1（RWZM 輸出）唯讀讀取 | **10-24 上機**：讀到 8-bit Bayer 2016×1344（[validation/20261024-bufa1-01](validation/20261024-bufa1-01/RESULTS.md)）；工具假設的 0xC31D96D4 在待機為 0，要改用 0x30182280＋1344×504 字 |
| `host/lcd.py` | LCD 影像層直取：讀三個原生輸出描述元、借一個唯讀 MEM1 窗口讀一格 ring、YUYV 解碼並自檢 stride。錄影中拒絕執行 | 離線 8 項；**10-23 上機通過**（CINE 待機 1620×911，[validation/20261023-lcd-01](validation/20261023-lcd-01/RESULTS.md)） |

```sh
cd host && python3 -B -m unittest test_lcd test_ispl test_push_rx test_rawpool test_lvpush_live
cd sup && python3 -B build.py && python3 -B -m unittest test_card     # 約 5 分鐘
python3 -B lcd.py decode RING.bin W H OUT.png     # 離線
python3 -B lcd.py grab OUT_DIR                     # 上機（先廣播相機使用權、通知使用者）
```

## 階段 0 還缺
- 讀哪一格最新：描述元 word 31 讀取中 1→3，疑似目前寫入格索引（待驗）；目前固定讀第 0 格。HDMI／EVF 接上時另外兩個描述元是否啟用待查。
- BUFA0 mux=1 參考 RAW：`imx410-lab/bufa_probe.py frame OUT --mux 1` 在一般 LV 可用（10-20 實測）；但待機是 MONIT 模式（mode 8），不是錄影模式（106/123…），要同模式參考得用 vmode 把錄影模式放到 host 10 再進放大。錄影中不能抓（韌體自己用 BUFA0）。凍結已查明（imx410-lab IMX410_RULES §70）：在幀中途停 BUFA0 會卡死匯流排；必須在相機上一次做完「清旗標 → 等下一次 BUFA0 完成 → 停」（`imx410-lab/sensor_read/bufa_stop.S`，bufa_probe.startstop 已改用），不能從主機分兩步。修正後的 300 次驗證待跑；isp-lab 若自己 arm／停 BUFA0 必須用同一停法。
- ~~ISPL 上機前要先證明：借出的記憶體跨錄影安全（用 class 0，不用 10）、非快取複製速度、控制 task 從非 UI 任務按 REC 能否開始／停止錄影、shell 執行器在錄影中被呼叫是否安全（strtok 不可重入）~~ → ISPL 擱置。
- 改成不錄影：查 BUFA1（RWZM 輸出）能否在待機手動開、用 imx410-lab 的安全停法抓。
