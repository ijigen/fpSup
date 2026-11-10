# T-C 上機：CRCT bin 抽頭的精度（2026-10-30 02:42–02:50）

> **後續H1補測**：本日另一輪已保住原廠每幀來源，取得mux3 bypass與兩筆原廠H÷3核的有效影像；
> 已測H1配置低兩位皆零，前後Crmf仍保留14-bit低位。見 [H1實機結果](../h1-live-20261030/README.md)。
> 本檔下方的H1「沒有幀」只描述這次舊T-C，不再代表目前的覆蓋狀態。

> 後續離線訂正（2026-10-30）：下方保留原始測試紀錄與當時結論。有效樣本證明的是
> **所測 Vbin／Hbin2 抽頭配置只有 12-bit 內容**；mux 3 Hbin 沒取得有效幀。
> 因而不能由本次結果排除所有機內 RAW 縮寬路徑。另找到 PRE_TOP_HSEP 的水平 ÷2／÷3
> 與 RAW14 DMA 格式入口，內部算式、精度尚未驗證，見 [後續研究 §10](../../notes/TRUE14_2X_RESEARCH.md)。

依據 `notes/TRUE14_2X_RESEARCH.md` §7。工具：`tools/rwzm14/tc_stages.py`（匯入 imx410-lab 的 bins、fastsweep、bufa_probe、l7、sweep，沒有修改它們）、
`tools/rwzm14/tc_bits.py`（解碼成 14-bit，計算 mod 4、mod 16 熵、p2–p98 碼佔用、兩幀時間雜訊，輸出 view.png）。
卡：沒換（QSContainer v0.2.4 + SensorLab v0.5.0test + USB-Shell v3.4.0 …）。
讀出：`v3_14`（14v3，14-bit AD，HMAX 911，接收端 14-bit，BUFA0 enum 1，1000 列 × 2653 字）。每次執行都在待機 mode 10（放大）裡完成，結束一律 `poff 1`。

## 過程
- 開始時 SensorLab 是 active=1：callfn `sq_test(22)`（0xC55FF311，入口字是 push.w）回 0，之後 active=0。之後每次 `poff 1` 開機都是 active=0（沒按 MENU）。
- run1、run2：在 batch 的 cave.claim 失敗（`imxl.batch.tab` 要 1024 B，cave 只剩 796 / 956 B），沒有寫入任何感光元件暫存器，正常收尾並 poff。已刪除。
  - 修正：tc_stages 自己做 batch，表格照實際大小 claim（62 筆 = 496 B）。
- run3（S0、S1、S2）：
  - **`0x300F0800`（Vbin）寫入時讀回驗證過，但 0.3 s 後讀回是 0**：韌體每幀會改寫它。所以 S1 是「mux 2，Vbin 沒開」，畫面是 320 列的頂部裁切，不是 ÷3。
  - S2（`0840 = 1`，882 字）：**guard 被蓋（DMA overrun）**。0840 同樣沒保住，資料仍是全寬，DMA 照實際行長寫；還在自己的 24 MB 緩衝內。腳本停下並收尾。
  - 結論：2114 不會限制 DMA 寫入的量。
- run4（S0、S5、S3f）：
  - S5 = mux 4、不開 bin，正常。
  - S3f：**`0x300F08C0 = 1` 保住了**，但用全幅幾何時 1 s 內沒有完成。收尾路徑先還原 bin 和 mux，再在 ISR 裡 safe stop，正常。
- run5（S0、S3n）：S3n = Hbin2 開、882 字，guard 與讀回改成涵蓋全幅範圍，**拿到乾淨的水平 ÷3 幀（2016 寬、完整視野）**。
- 全程沒有凍結。restore_diff 只剩 DMA 狀態字（0x301821F0..F8）和 HMAX（之後 poff 會還原）。

## 結果（每格一對幀，影像區；view.png 都看過，都是真場景）
| 階段 | 內容 | mod 4（0/1/2/3） | mod 16 熵 | 佔用 | 時間雜訊 | 判讀 |
|---|---|---|---|---|---|---|
| S0（run3/4/5） | mux 1 Crmf | 0.248 / 0.252 / 0.248 / 0.252 | 4.00 | 1.00 | 37–44 | **14 bit** |
| S1（run3） | mux 2，Vbin 沒保住 | 1.0 / 0 / 0 / 0 | 2.00 | 0.251 | 55 | **12 bit**（Vbin 抽頭即使不 bin 也是 12） |
| S2（run3） | mux 3 | — | — | — | — | overrun，沒有幀（0840 沒保住） |
| S3n（run5） | mux 4 + Hbin2 ÷3（2016 寬） | 1.0 / 0 / 0 / 0 | 2.00 | 0.25 | 32 | **12 bit** |
| S4 | V + Hbin2 | — | — | — | — | 沒做（0800 保不住） |
| S5（run4） | mux 4，不開 bin | 1.0 / 0 / 0 / 0 | 2.00 | 0.25 | 37 | **12 bit** |

R/G 很小是 tc_bits 的黑位取法問題（窗口頂部不是 OB），跟這個判讀無關；畫面都是同一個場景（白色貓玩偶、架子、日文書背）。

## 結論
- **Hbin2 保不住 14 bit**：mux 4 就算不 bin（S5）也是 12 bit。Vbin 抽頭（mux 2）也一樣。
  CRCT 裡只有 Crmf 抽頭（mux 1）是 14 bit，bin 鏈本身就是 12 bit 寬。
- ⇒ 機內真 14 的 3×（14v3 + CRCT h3）不存在。這也表示 RWZM 的 12 bit 很可能是從 bin 鏈一路繼承下來的。
- 相機最後的狀態：`poff 1` 之後在 CINE 待機 mode 0008（MONIT1_60），shell 正常，SensorLab active=0（第一次按 MENU 會重新 commit 開機紀錄），沒有錄影。
