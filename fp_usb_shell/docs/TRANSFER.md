# Moving bytes over the shell

Everything here was measured on the camera, and every rule replaced a wrong
guess. Transfers went from 448 seconds for 14 KB to under a second, and none of
the difference was the wire — USB is running at SuperSpeed and a short command
answers in a third of a millisecond.

| | |
|---|---|
| write | ~30 KiB/s, 240 bytes per command in the command line |
| read | ~44 KiB/s, 64 words per `mem get`, flat from 48 words up |
| one command | 0.3–1 ms when it works, 200 ms when it is lost |

## Send data in the command line

`mem set` moves four bytes per round trip. A shell command line holds about 502
characters, so one invocation carries ~240 bytes of hex instead — sixty times as
much. `bulkload.S` keeps the destination on the camera and advances it, so the
host sends nothing but data.

Use `mem set` only for repairs and for loading the bulk loader itself.

## Never stage past the allocation

This is the one that cost the most. Staging 247 KB into the 64 KiB that was left
ran off the end into memory somebody else kept rewriting, so the verify could
never converge: six passes of retries, six minutes, reported as slowness rather
than as the out-of-bounds write it was.

`check_fits()` refuses now. The bound is `POOL_SIZE`, which has to match the
AutoRun's `memmgr bufmem get`.

## Ask for three arguments, never four

`memmgr bufmem get 0 0x20000 0x40` returns **128 bytes**. The handler parses the
alignment into the size slot — the size goes to `[sp, #4]` at 0xC03FA558 and the
alignment goes to `[sp, #4]` again at 0xC03FA580, while the alignment slot at
`[sp, #0xc]` only ever gets zero.

`memmgr bufmem get 0 1048576` gets a megabyte. Check it with `memmgr bufchk`,
which lists every allocation with its owner.

## Do not put memmgr on the transfer path

The memmgr commands wedge the endpoint when issued live. `bufmem get` froze the
camera twice; `bufchk`, added to find the allocation end on every transfer, did
it again. Read the bound from a constant and check `bufchk` by hand when the
AutoRun changes.

## Short timeout, and drain on failure

Roughly one command in ten goes missing. With the daemon's original five second
timeout, an empty `echo` averaged 137 ms and a 550 character `mem get` averaged
774 ms — fast commands with an occasional five second hole averaged in. The
timeout is 200 ms now.

Worse, every failed exchange used to return without reading the reply that
arrived late, so it stayed on EP 0x82; the next command read that instead of its
own, mismatched the sequence, and left one behind in turn. Each failure created
the next, and the rate climbed from 3% to 45% over one session. `drain_in()` on
every error path takes it back to 2%, and of 400 commands sent under it not one
word failed to land: what is still lost is the reply, not the write.

## Verify, and repair one word at a time

A chunk that goes missing leaves a 240 byte hole rather than a four byte one.
Write, read back, rewrite what is missing, repeat. Repairs go through `mem set`,
which is exact.

## Poison sparsely

Filling a 247 KB buffer with a pattern before reading a file into it took longer
than reading the file twice. One marker every 4 KiB catches the case it is there
for — a read that did not happen — and costs nothing.

## Mode 7 does not truncate

`open(path, 7)` creates or overwrites from the start, and leaves anything past
the new length in place. Every AutoRun written this way happened to be larger
than the last until one was not, and 195 bytes of the previous file stayed on the
end. Check the size in `dir` against what was written.

---

# 傳輸

以下每一條都是實機量出來的,而且每一條都取代了一個錯誤的猜測。14 KB 從 448 秒
變成一秒以內,而**沒有一分是線路本身** —— USB 跑在 SuperSpeed,短指令 0.3 毫秒就回來。

| | |
|---|---|
| 寫入 | 約 30 KiB/s,一條指令列帶 240 bytes |
| 讀取 | 約 44 KiB/s,一次 `mem get` 讀 64 個字,48 個字以上就飽和 |
| 單一指令 | 成功時 0.3–1 ms,掉了就是 200 ms |

## 資料塞在指令列裡送

`mem set` 一次搬四個位元組。指令列容得下約 502 字元,所以一條可以帶 **240 bytes**
的十六進位 —— 六十倍。`bulkload.S` 把目的指標留在相機上自己推進,主機只送資料。

`mem set` 只用在補寫,以及載入 bulkload 自己。

## 絕對不要暫存到配置範圍之外

這條代價最大。247 KB 塞進只剩 64 KiB 的地方,超出的部分寫進別人持續覆寫的記憶體,
**驗證永遠不收斂** —— 重試六輪、六分鐘,而且回報成「慢」,不是「寫出界」。

現在 `check_fits()` 會直接拒絕。上界是 `POOL_SIZE`,必須跟 AutoRun 的
`memmgr bufmem get` 對應。

## 只能傳三個參數

`memmgr bufmem get 0 0x20000 0x40` 會給你 **128 bytes**。handler 把對齊參數
解析後存進了 size 的位置 —— size 在 `0xC03FA558` 存進 `[sp, #4]`,對齊在
`0xC03FA580` **又存進 `[sp, #4]`**,而真正的對齊槽 `[sp, #0xc]` 永遠是 0。

`memmgr bufmem get 0 1048576` 才會真的給一 MB。配完用 `memmgr bufchk` 確認 ——
它會列出每一塊配置和它的擁有者。

## memmgr 不能放在傳輸路徑上

memmgr 家族的指令線上執行會弄僵端點。`bufmem get` 凍結過相機兩次;而
`bufchk` 被我放進「每次傳輸都去查上界」之後又凍一次。上界用常數,
`bufchk` 只在 AutoRun 改變時手動查一次。

## 逾時要短,失敗要抽乾管線

大約每十條指令會掉一條。daemon 原本的五秒逾時之下,空的 `echo` 平均 137 ms、
550 字元的 `mem get` 平均 774 ms —— 都是快指令,只是平均裡混進了五秒的洞。
現在逾時是 200 ms。

更糟的是:每次失敗的交易都直接返回,**沒有把遲到的回覆從 EP 0x82 讀走**。
下一條指令讀到它、序號不符、又留一個下來 —— **每次失敗都製造下一次失敗**,
一個 session 內從 3% 滾到 45%。錯誤路徑一律 `drain_in()` 之後回到 2%,
而且那 2% 裡 400 條指令**沒有任何一個字沒寫進去**:掉的是回覆,不是寫入。

## 驗證,而且逐字補寫

掉一塊是 240 bytes 的洞,不是 4 bytes。寫 → 回讀 → 補寫缺的 → 重複。
補寫走 `mem set`,那個是精確的。

## 毒值要稀疏

讀檔前把 247 KB 的緩衝全部填毒值,比讀兩遍檔案還久。每 4 KiB 放一個就夠了 ——
它要抓的只是「讀取根本沒發生」。

## mode 7 不會截斷

`open(path, 7)` 會建立或從頭覆寫,但**新長度之後的舊內容會留著**。
每次寫的 AutoRun 都剛好比上一次大,直到有一次不是 —— 舊檔的 195 bytes 就留在尾巴。
寫完要拿 `dir` 的大小跟實際長度對一下。

## 讀取為什麼慢,以及錯的都是什麼 (2026-08-26)

一直以為慢是「把記憶體轉成文字」的代價。不是 —— 那在 `dumpraw.S` 就解決了,它不走
printf,回覆就是資料本身,一塊 3000 位元組的往返**中位 0.39 ms**。

真正的成本在主機端:`read_bulk` 每讀一塊之前要用 `mem_set` 重寫三個參數字告訴相機
下一塊在哪。四個命令搬 3000 位元組,三個便宜命令花掉 97%,而且其中一個
(`P+0x08`)dumpraw 根本不讀。

**改法:參數寫在命令列上。** 借來的 handler 本來就拿得到 `argc`/`argv`,所以

    echo C0100000 BB8          位址與長度,都是十六進位

一個命令就講完,而且**無狀態** —— 回覆掉了就重問同一句,沒有東西會不同步。
(先前讓 dumpraw 自己遞增位址也可行,但那是有狀態的,回覆掉包兩邊就會對不上。)

**handler 的參數慣例**:`argc` **不含**命令名,`argv[0]` 就是第一個參數。
(`echo AA` → `argc=1, argv[0]="AA"`。這是問相機問出來的,不是猜的。)

### 實測

| | |
|---|---|
| 中位往返(3000 B) | **0.39 ms** |
| 連續讀取實效 | 1500 KiB/s(最好),275–760 KiB/s(一般) |
| 18 KB 檔案從卡讀回並驗證 | **1.4 秒**(原本數分鐘) |
| 768 KB × 4 輪 | 全部逐位元組相符 |

顯示的即時速率是累積平均,平台值才是真的。

### 那些「資料錯誤」不是資料錯誤

USB bulk 自己有 CRC 和硬體重傳,**它不會把壞掉的位元組交給你**。每一個看起來錯的
位元組,都是別的請求的正確位元組。實測 400 塊:390 正確、10 次逾時、
**0 個舊回覆、0 個壞資料**。

早先看到的「靜默壞資料」是**我同時跑了兩個 `fpshd` 搶同一個 USB 裝置**。
`pkill` 沒清乾淨就再開一個,兩邊交錯讀同一個端點。
**動 daemon 之前一定要 `ps ax -o pid,command | grep '[f]pshd --socket'` 確認只有一個**
(`grep -c` 會連 shell 的包裝行一起數,不可信)。

### 逾時要長,不要短

| 逾時 | 沒回應 | 資料錯 | 中位 |
|---|---|---|---|
| 30 ms | 20/270 (7.4%) | 0 | 0.39 ms |
| 200 ms | 6/400 (1.5%) | 0 | 0.39 ms |
| 1000 ms | 6/400 (1.5%) | 0 | 0.39 ms |

短逾時**自己製造掉包**,而且 200 ms 與 1000 ms 完全相同,表示剩下那 1.5% 是真的
丟失而不是慢。中位只有 0.39 ms,所以逾時設多長都不影響速度,只影響出事時的代價。

**代價不只是等待。** 主機放棄一個相機已經備妥的資料塊,worker 就再也回不了話 ——
不是 50 秒後恢復(實測等兩分鐘沒有回來),是要斷電。所以寧可等久一點。
daemon 的 `TMO <ms>` 前綴可以單次指定,別把全域值調短:開檔讀檔本來就要幾百毫秒。

### 其他地雷

- **`dumpraw` 在 `CAP_MAX = 0x4000` 靜默截斷。** 要更多就只送 16384,主機卻還在等
  剩下的。主機端 `DUMP_CAP` 擋著,不要繞過。
- **小回覆的二進位會被當文字送壞。** 只有大到觸發 `reply_bulk`(≥128 B)的回覆才會
  被 daemon 十六進位包起來;小的走逐行文字,NUL 和換行就毀了。用 `HEX ` 前綴要求
  照原樣編碼。
- **不要在 `arm_in` / `arm_in_block` 前加 `EndTransfer(LOG_IN)`。** `arm_out` 每次都
  這樣做且沒事,IN 端看似只是漏了對稱的一半,但實機上 worker 一開機就全聾(兩次,
  各賠一趟讀卡機)。借 shell 命令呼叫一次是無害的 —— 那個探針**證明力不夠**:
  它驗的是「呼叫一次、再用原本方式回覆」,不是「每次 arm 之前都呼叫」。

## 讀原始碼讀出來的三個 bug (2026-08-26)

實機來回猜了一整天之後才去讀 worker 的原始碼。三個都是讀出來的,不是量出來的。

**1. 相機沒東西可送時,一個位元組都不回,而且還算自己服務過了。**

```asm
reply_raw:
    cmp     r9, #0
    beq     reply_done      @ 什麼都不送,但 served++
```

主機說「我要 3000 位元組」,相機手上是 0,就直接結束。主機只能等到逾時。
量到的 `moved=0/3000` 就是這個,也解釋了為什麼逾時從 200 ms 拉到 2000 ms 毫無差別 ——
根本沒有東西在路上。

**2. worker 從不檢查收到的框架。** 協定有 magic `FPSH` 和 CRC-32,daemon 收的時候
都驗,worker 只看酬載開頭是不是 `"shl "`。殘缺的命令框架會被當成「不是命令」,
`r9 = 0`,然後撞上第 1 點。

**3. `fault` 會從多幀回覆的中途跳走**,回去等新命令。主機還在等第 2 幀,拿到的卻是
下一個回覆的第 1 幀 —— 一旦錯開就一直錯開。`mem get` 走的正是多幀路徑。

**但這三個都不是連結會死掉的原因。** 改走有表頭的路徑(它的表頭會誠實說出長度,
第 1 點就不成立)實測**照樣死**,而且只有三分之一的速度。所以弄壞連結的是別的東西,
還沒找到。

## 已知界線 (2026-08-26)

- **單次讀取上限 512 KiB**(`READ_MAX`)。768 KB 反覆成功過,1.35 MB 與 2.2 MB 都死過。
- 死掉之後**不會自己好**:worker 還在跑、`rounds` 還在增加,但 20 個命令裡有 19 個
  到不了,**只有斷電能清**。相機本體完全正常,沒有凍結。
- 死掉的條件跟「連續大量讀取時對沒回應的塊重試」高度相關。不重試就不會死
  (400 塊跑好幾輪都活著),一重試就會。

## 路徑寫法 (2026-08-27)

根目錄要 `dir \\`(雙反斜線),但**子目錄要單反斜線**:

    dir \\                          根目錄
    dir \DCIM\100SIGMA           子目錄 ✅
    dir \\DCIM\\100SIGMA       ✗ cannot access

指令自己印的用法範例寫的是 `dir \\test\\testdir`,照著做會失敗。

## 31 MB 一次讀完 (2026-08-27)

`_SDI0130.DNG` 32,676,609 bytes,一次 `getfile.py` 讀完:74 秒(429 KiB/s),
`sips` 解得出 6000x4000 的 DNG,轉得出 JPEG。緩衝是**跟韌體要的**
(`heapalloc.S`,要了 32,680,705 bytes),用完還回去。

舊的 1 MB 池限制沒了。

**76 秒 → 23 秒**,兩件事:

1. **塊大小 3000 → 16380**(擷取緩衝 16 KiB 減去四個位元組的位址標記)。那個 3000 是
   printf 時代選的,raw 路徑跟它無關 —— 一塊就是一個命令,不管多大。31 MB 從一萬一千
   個來回變成兩千個。
2. **daemon 排空的等待 350 ms → 20 ms**。當初讓它蓋過相機的 300 ms,結果一次失手要賠
   「主機逾時 200 + 排空 350」= 超過半秒;5% 失手率 × 2000 塊 ≈ 55 秒,正是量到的全部。
   晚到的區塊現在有**位址標記**會擋下來,重問一次只要幾毫秒,不需要等它。

三次獨立讀取結果完全相同,`sips` 解得出 6000x4000。

剩下的成本是主機逾時(200 ms)× 約 5% 的失手。要再快就得把**相機端**的 IN 等待從
300 ms 再調低(它會擋住 worker 那麼久),主機才跟著調低 —— 那要燒卡。

### 比對韌體映像時要注意

`out/seg0_c0000000.bin` **不含我們自己的開機修補**。4 MB 以上的讀取會撞到
`0xC03E4698`/`0xC03E46A0`(螢幕文字座標)而看起來像「資料損壞」——
那是我們改的。比對前要先把 `build_autorun.py` 的 `PATCHES` 和 `SCREEN` 套用上去。
2026-08-27 我為此白繞了一圈去查快取。
