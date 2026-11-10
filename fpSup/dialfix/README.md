# Dial Fix — loader v4 sup(`DialFix_v<版本>.BIN`,sup_id `DIAL`)

後轉盤(Shinmei TSW-26)解碼器，作者 **Andy_hal9000**。目前帶的是他的 **v6**(`reference/v6/`:他的發布原檔，凍結自他的 commit 45b7796;
作者 2026-11-07 以 AutoRun 卡上機驗證)。2026-10-21 收到的第一版片段與當時的 sup 原始碼從未發布，未收進 repo。

版本與顯示名在 `fpSup/loader-v4/names_v4.py`(`DIAL`):`0.2.1test` —— sup 版上機前保留 test。

## 他的卡怎麼做、sup 怎麼做

他的 AutoRun 把解碼器寫到原廠程式碼 C02E1CE8..C02E1E90(107 字),vtable +0x10 指向那裡(Thumb,+1);
原廠的邊緣處理器 C02E20D8 / C02E20F0(`r1 = 通道; bl C02E1D78`)於是落進他放在 +0x90 的 ARM 跳板，再跳 Thumb 中斷碼。

sup 不覆寫韌體程式碼：同樣的 107 個字放在 sup 自己的區塊(快取別名)執行，改 vtable(0xC0B4E778)三格，一次 claim 12 B(`SL_EXCL`),關機時核心還原：

| 格 | 原廠 | 換成 |
|---|---|---|
| +0x10 輪詢 | C02E1D08 | `dial_v6 + 1`(他的 Thumb 輪詢) |
| +0x14 A 邊緣 | C02E20D8 | `dial_edge_a`:`r1 = 0`,跳他的 +0x90 跳板 |
| +0x18 B 邊緣 | C02E20F0 | `dial_edge_b`:`r1 = 1`,同上 |

和他的卡相同：物件(0xC3425A78)+8..+0x18 重設為 {3,0,0,4,0}、0x301502E4 低 4 位設 1;全部在關中斷下完成。
`obj+4` 不是 0xC0B4E778 時直接 RELEASE、什麼都不寫。他卡上其餘的寫入(開機延遲 NOP、借 echo 呼叫韌體)是那張卡自己的安裝步驟，sup 不需要。

他的程式碼只用 ADC 位址(0x301502C0)一個絕對位址，內部都是相對跳轉、沒有重定位，所以搬到 sup 區塊照樣能跑。

## 解碼器(他的 `dial2_fast.S`,NOTES 21–22)

12.5 ms 的輪詢決定一格何時開始與結束，邊緣中斷決定方向(哪個接點先閉合、哪個最後打開)並計算快轉；一格一下，順時針(B 先閉合、A 最後打開)= +1。
ADC 0x301502C0 低 16 位 A、高 16 位 B,遲滯 <1200 閉合、>2896 打開；比較器 +0x30 的 bit0 / bit16。

## 建置與測試

```sh
python3 -B fpSup/dialfix/build_dialfix.py --out DIR      # DIR/fpSup/DialFix_v0.2.1test.BIN
python3 -B -m unittest fpSup/dialfix/test_dialfix.py     # 8 項，真核心 + 真韌體映像(從 repo 根目錄)
```

- sup 內的 107 字 = 他 AutoRun 寫入的字 = clang 組譯他的 `.S`(且無重定位)。
- 載入：輪詢格是 Thumb、邊緣格是 ARM,都在 sup 區塊(快取別名);物件狀態與暫存器同他的卡；journal 只有這 12 B;關機還原。
- 原廠 C02E20D8 / C02E20F0 確實是 `mov r1, #通道; bl C02E1D78`(sup 的兩個包裝就是照這個做)。
- 沒有該物件 → RELEASED,一個位元組都沒寫。
- 他的原位版(經原廠邊緣處理器呼叫)vs sup 版:600 步隨機輸入(輪詢/A/B 邊緣、門檻邊界值)狀態與計數完全相同。
- 轉盤：慢轉(每個位置都被輪詢看到)、中間夾一次輪詢、兩次輪詢之間快轉，三種都是一格一下，順 +3 / 逆 −3;彈回不算。
- 突變 10 個全被抓到(兩個邊緣通道、Thumb 位元、旗標初值、暫存器、物件檢查、claim、包裝跳錯、解碼器頭尾各改一字)。

他 README 提到的 `test_fast.py` 與實機錄下的轉盤資料不在發布包裡，這裡只有合成輸入。

## 未做

- **sup 版未上機。** 待驗:LOAD.LOG `LOADED`、一格一下、順時針 +1、快轉、關機後回到原廠。
- 原廠輪詢在計數非零時會送事件 0x200000(C0019DC0/C001A0D8),他的解碼器不送;影響(例如省電計時是否因轉撥盤重設)未查。

## 載入時凍結(2026-11-10,離線修正，未上機)

使用者回報 `DialFix_v0.2.0test.BIN` 載入時凍結。原因：sup 寫的暫存器位址是 **0x321522E4**,但作者安裝碼
(`reference/v6/AutoRun.txt` 第 11–18 行，在 C02E1E78 執行一次)是 `movw r2,#0x02E4; movt r2,#0x3015` = **0x301502E4**
(ADC 區塊，緊鄰 0x301502C0)。兩個立即數從 v1 就解錯，測試又把同一個錯位址映射成可寫，所以離線全過、上機一讀寫就凍結。

- `dialfix.c` 的 `EDGE_CFG` 改為 0x301502E4;版本 0.2.1test(與 0.2.0test 只差這 2 個位元組)。
- 測試只映射 ADC 那一頁(位址不在裡面就會 fault),並新增 `test_the_register_is_the_one_his_installer_writes`:
  位址由作者 AutoRun 的 movw / movt 解出來比對，不再手抄常數。把舊位址放回去 12 項失敗。
- 建好的檔：`projects/loader-v4/cards/20261110-dialfix/fpSup/DialFix_v0.2.1test.BIN`。merge 頁的 0.2.0test 快照還沒換。
- **上機(2026-11-10)**:`DialFix_v0.2.1test.BIN` 寫入、重開：**沒有凍結**。LOAD.LOG `0A … 00000001 DialFix_v0.2.1test.BIN`(載入、1 筆 claim)。
  讀回：vtable 三格 = `C505E2F1 / C505E49C / C505E4A4`(sup 區塊，輪詢帶 Thumb 位元)、`0x301502E4` = 0xF(裝之前 0xA)、
  物件 +8..+0x18 = {3,0,0,4,0}。撥盤手感使用者實測：「效果超好的」。關機還原未另外確認。
