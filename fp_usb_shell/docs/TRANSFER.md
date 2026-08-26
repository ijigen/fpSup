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
