# 相機主動推送協定 FPP1（v1，2026-10-24；v0 經 sigmafp-re-40 審過，五點修正已併入）

**10-26 上機更新**：[接手驗證](../validation/20261026-resume-preflight-01/RESULTS.md)。fpshd 3.3.0、內建引擎的待機 LV 與停錄後 CDNG 已通；錄影中 LV 未驗。主機 `listen()` 現在等完 quiet 才返回，串流出錯時先用主機端 STATUS 確認 listener 結束。
相機掃出的 13 個 DNG 候選只有 10 個與卡檔相同，最新 DateTime 不代表最終版本。

imx410-lab 與 isp-lab 共用一份。分工（10-24 雙方同意）：
- **相機端推送引擎＋BUFA0 整合**：sigmafp-re-40（imx410-lab）
- **協定規格、fpshd 內的 EP83 接收、python 解析、isp-lab 的三個呼叫端**（LV、BUFA1、停錄後 CDNG）：sigmafp-re-38（isp-lab）

## 0. 原則
1. **相機推、主機收**。錄影中主機**不送任何指令**（純監聽模式）。收完後的靜默時間是**參數**（預設 1000 ms）：
   hookpush-quiet-period 是 EP84 時代量的，而 EP84 在現行描述元下不存在，那些「halt」其實是在等不存在的端點逾時；
   EP83 的真實值由引擎里程碑一實測後再定（sigmafp-re-40）。
2. **相機端兩種模式**：mode 0「忙就跳過」（hook、錄影中用：上一筆 HWO 未清就跳過、記一筆，不睡不等）；
   mode 1「保證送達」（只能在 task 裡用：等上一筆完成再推，推完等 HWO 清才回）。
3. **零拷貝、不借配置器**：TRB 直接指向資料所在（顯示 ring、BUFA 緩衝、RAW 池）；引擎狀態放 shell 的池（memory allocator-not-across-recording、isp-lab-no-recording）。
4. **介面 0 只有 fpshd 一個擁有者**：接收放在 fpshd 裡，python 經 socket 拿位元組（ep83_libusb_owner.py 在 sock 存在時拒絕執行，就是這個原因）。

## 1. 傳輸層
- 端點：**EP 0x83**（bulk IN；DALEPENA=0xA7，EP84 不存在；memory push-endpoint-is-ep83）。實體端點與 ctx 編號由相機端引擎文件寫明。
- EP83 當成**位元組串流**：主機不依賴傳輸邊界，只靠 header 的長度切張。相機端可以把一張拆成任意多個 TRB／StartTransfer（單一 TRB ≤ 16 MiB − 1 KiB），
  也不需要 ZLP。
- 每次 StartTransfer 的回傳都要檢查；失敗計數、放棄這張（不重送半張）。半張的後果由主機端處理（§3：下一個 header 出現在這張的資料裡 = 截斷）。
- **TRB 由引擎自己擁有**：池裡一個 TRB 陣列（CHN 鏈接，最後一個 LST|IOC），StartTransfer 直接給它的實體位址，不用韌體 ctx3 原本那一格。
  header 與 TRB 陣列放在 DMA 可達的非快取別名，arm 前做快取清理（C000E91C）。上限 header + 48 段，每段切 ≤ 16 MiB − 1 KiB，最多 64 個 TRB。
- 相機**不送 ZLP**，段長不必是 1024 的倍數。

## 2. 一張的格式
```
[header 256 B][段 0][段 1]...[段 n-1]      段與段之間沒有填充；總長 = header.total
```
header（little-endian，256 B）：

| 偏移 | 欄位 | 說明 |
|---|---|---|
| 0x00 | magic | `FPP1` = 0x31505046 |
| 0x04 | hdr_len | 256 |
| 0x08 | source | 1 LV 顯示 ring、2 BUFA1（RWZM 輸出）、3 BUFA0、4 CDNG 幀、其他保留 |
| 0x0C | seq | 每個 source 自己的序號，連續遞增；**主機看到跳號 = 相機端跳過**（不是錄影掉幀） |
| 0x10 | t_us | `C002B6E0` 微秒時鐘（取樣當下） |
| 0x14 | frame_no | 來源自己的幀號（CDNG：錄影幀號；BUFA：完成計數；LV：ring 索引）；沒有就 0 |
| 0x18 | nseg | 段數 1..48 |
| 0x1C | total | 段長總和（不含 header） |
| 0x20 | w, h | 寬、高（像素），u16+u16 |
| 0x24 | fmt | 1 YUYV422-8、2 Bayer-8、3 Bayer-12（BUFA 位元流，decode12）、4 Bayer-14、5 DNG 檔（檔頭＋RAW，原樣） |
| 0x28 | stride | 每列位元組（fmt 5 填 0） |
| 0x2C | flags | bit0 錄影中、bit1 半按中、bit2 放大中、bit3 讀取時來源可能正在被寫（撕裂風險） |
| 0x30 | n_skip | 這個 source 到目前為止相機端跳過的張數 |
| 0x34 | aux[2] | 來源自訂（CDNG：clip 號、檔號） |
| 0x3C | hdr_crc | CRC32（IEEE）of header 0x00..0x3B 與 0x40..0xFF（即整個 header、本欄當 0）；**主機用來 resync** |
| 0x40 | seg_len[48] | 每段長度（u32），未用的填 0 |
| 0x100 | — | 結束（header 不帶位址：位址只對相機有意義） |

## 3. 主機端
### fpshd 3.3.0：`LISTEN83 <max> <idle_ms> <deadline_ms> [q=<quiet_ms>] [shellline]`
- 回 `OK83L <seq>\n`，然後把 EP83 收到的位元組以 `[u32 len][bytes]` 區塊原樣轉給 socket，`len=0` 結束，
  接著 `END83 <bytes> <reason> <last_rc> <trigger> <reply_len>\n`（reason = full｜idle｜deadline｜closed｜error｜nodevice｜trigger），
  帶觸發行時再一行 `REPLY <escaped>`。
- **不帶觸發行**：純監聽（錄影中用）。
- **帶觸發行**（imx410-lab 的用法：一個 shell 命令觸發 grab+push）：順序固定——EP01 送觸發行 → 收 EP83 串流到 max／idle／deadline →
  收那個觸發命令在 EP82 的回覆。實作是在 `exchange()` 送完 OUT、收回覆之前呼叫串流函式，回覆走原本的完整路徑（序號比對、分段、bulk）。
- 每次 libusb bulk 讀 **1 MiB**（整數個封包），短包就轉送，不等讀滿；逾時帶回的部分資料也轉送。
- 結束後 `q=` 毫秒內（預設 1000）除 STATUS 外一律回 `ERR quiet`，把靜默規則放在唯一的擁有者身上。
- 不改既有的 `EP83 <bytes> <shellline>`（64 KiB 一問一答）。
- 原始碼 `fpSup/fp_usb_shell/host/fpshd.c`；`-Wall -Wextra` 無警告；**10-25 已切換 3.3.0，10-26 端到端上機通過**。

### python：`push_rx.py`（isp-lab/host，兩邊共用）
- 連 fpshd、送 LISTEN83、把區塊串回位元組流，依 header 切張；magic + CRC 對不上就往後找下一個 `FPP1` 重新同步，並記下丟掉的位元組數。
- **截斷偵測**：一張收齊時先在它的資料裡找合法（CRC 對）的下一個 header；找到 = 這張只送了一半，丟掉它、從那裡繼續（torn 計數）。
  所以 **header CRC 實際上是必要的**（0 = 不檢查仍可解析，但截斷時會連下一張一起毀）。
- 離線測試 `host/test_push_rx.py` 8 項（任意切塊、截斷後重新同步〔mutation 已驗〕、CRC 錯、CRC=0、seq 跳號、長度不一致、經假 fpshd 的端到端兩種模式）。
- 輸出：每張存成 `<source>_<seq>.bin` ＋ `index.jsonl`（header 全欄位、收到時間、是否完整）。按 fmt 另存可看的 png（YUYV／Bayer-8／decode12）。
- 統計：每個 source 的 seq 跳號（相機跳過）、resync 次數、總位元組、平均速率。

## 4. 相機端引擎（10-25 起由 sigmafp-re-38 接手；實作 `sup/ix_push.c`，10-26 待機 LV／停錄後 DNG 上機通過）
- **實作要點（10-25）**：header 256 B 與 TRB 鏈放在 sup 狀態裡，一律經非快取別名寫，不需快取維護；TRB 的 buffer 是 **DMA 位址 = 非快取 CPU 位址 − 0x40000000**
  （韌體自己就這樣寫）。StartTransfer(phys) 交給控制器的是 `[0xC31E3238 + 4·ctx]`（DMA），`[0xC31E3264 + 4·ctx]` 是同一個 TRB 的 CPU 位址；
  引擎占用 ctx 3 時改寫這兩格、`ix_push_release` 還原。中段 TRB ctrl 0x15（HWO|CHN|normal），最後 0x813（韌體的）。
  忙／超時／啟動失敗都會讓 seq 前進並記 n_skip，主機看到跳號。`lv_push = 1` 時 LV 取樣直接用內建引擎。
  unicorn `PushEngineTests` 8 項（假控制器沿 TRB 鏈收位元組、用 push_rx 解析）＋ CRC 突變。
- **上機前提**：EP83 必須是 bulk（patches.py PUSH 的目標為 1024；10-25 重新列舉實際 bulk/64 也完成 16 KiB 推送，10-26 LV/CDNG 亦通）；現行 v4 發行版刻意不帶（v4 負責人 10-25 確認），
  要用開發版 shell（`build_v4.shell_sup` 帶 `ep_patches=True`），且相機要在修補寫入**之後**才列舉（開機完成後再插線）。
- `push(mode, source, frame_no, w, h, fmt, stride, flags, aux, segs[], nseg)`：組 header（在池裡）、依序 arm header＋各段。
  mode 0：上一張未完成 → 不做，n_skip[source]++，回「跳過」；任何 task／hook 可呼叫，不睡不配置。
  mode 1：等上一張完成再推、推完等 HWO 清才回；只能在 task 裡。
- 完成靠檢查 HWO，不靠中斷。
- 取樣政策（按時間、位元組預算）由呼叫端決定，引擎不管。
- isp-lab 端呼叫形式（10-24 定，引擎可直接收或加一層轉接）：`uint32_t push(ix_push_req *q)`，
  `ix_push_req = {mode, source, frame_no, w, h, fmt, stride, flags, aux0, aux1, nseg, {addr,len}[4]}`（u32，見 sup/ix_wr.h）；
  回 0 = 送出、1 = 忙跳過（n_skip 由引擎記）、其他 = 錯。位址是非快取別名 0x4…。
  **sigmafp-re-40 10-24 同意**：引擎直接用這個入口、不轉接；呼叫端 4 段、引擎內部仍可切到 48 段／64 TRB；mode 0 保證不睡不配置（hook／ISR 可用）、mode 1 只限 task；入口位址由主機寫進 cap，0 = 關。

## 5. isp-lab 的三個呼叫端（sigmafp-re-38）
| 來源 | 掛點 | 取樣 | 狀態 |
|---|---|---|---|
| LV 顯示 ring（錄影中、半按、放大） | 不用 hook：控制 task 讀 DMA 通道格索引、推上一格（PUSH_CALLERS §1） | `lv_every_us`，例：每 250 ms 一張 | 離線完成（unicorn），等引擎 |
| BUFA1（待機 RWZM 輸出） | 待機固定一格 0x30182280（10-24 實測），可從控制 task 定時推 | 主機要求時 | 格式已知（8-bit Bayer 2016×1344） |
| 停錄後 CDNG | 錄影中只記取樣幀的 (位址, 長度) 段清單（寫入層交出片段處），停錄後逐張推 | 例：前 3 張＋每 0.5 s 一張，≤ 94 張 | 待查：停錄後 RAW 池內容能保留多久 |

## 6. 待定
1. CRC 由相機算 256 B（很便宜）；若引擎不想算，改成 0 = 不檢查，主機只靠 magic＋長度合理性。
2. 引擎第一個里程碑（sigmafp-re-40）：EP83 第一次真的把 payload 送到主機（目前 Start 被接受過，但從沒有資料到主機）。
3. 錄影中從相機端 StartTransfer：從沒試過，第一個要驗的風險。
4. fpshd 3.3.0 已寫好（紀錄在 fpSup/fp_usb_shell/README.md）；換掉正在跑的 3.2.0 要先跟所有在用相機的 session 協調。
5. 靜默時間的預設值：等 EP83 實測。
6. **projectFP 交接 F1／F2（2026-10-24，已對反組譯核對，未上機）**：
   - F1：主機的 CLEAR_FEATURE(ENDPOINT_HALT) 會讓相機結束端點 1..6 的所有傳輸（C01E4260 case 1 → C01E6D48），推到一半的 EP83 會被打斷。
     fpshd 3.3.0 已改成 stall = 斷線重開，不送 clear-halt（tests/test_no_clear_halt.py 守著，突變已驗）。
   - F2：PTP class request 0x64（Cancel）／0x66（Reset）→ C04DBC10 → C01E9498 → C01E5F98 把 `0xC31E38FC` 設 1，
     之後 bulk StartTransfer（C01E6B80）回 −2，直到未 arm 的 bulk 端點收到 XferNotReady 才清。**ptpcamerad 的 kill 迴圈要一直開著**；
     引擎遇到 StartTransfer −2 時要記成「聾」而不是一般失敗（可讀 `0xC31E38FC` 判斷）。
