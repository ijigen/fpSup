# Templates

Pieces that get copied and changed, rather than called. Each one solves the
plumbing for a class of job so that the job itself is the only part you write.

| | |
|---|---|
| `shellcmd.S` | run code in task context by borrowing a shell command |
| `oneshot.S` | run a routine once, from the gyro callback |
| `bulkload.S` | carry bytes over in the command line, ~240 at a time |
| `putfile.S` | write a host-supplied blob to a file on the card |
| `getfile.S` | read a file off the card into memory |

## The one rule

The shell can write memory but nothing in it can call. Code runs by pointing an
address the firmware already calls at your routine and letting it fire. Every
template here starts from that; they differ in which address they borrow, and
that choice decides what your code is allowed to do.

**Borrow a command handler** (`shellcmd.S`) unless there is a reason not to. The
command table is 77 entries of `{char name[0x14]; void *handler}` at
`0xC0BAC14C`, stride `0x18`, so entry *n*'s handler pointer is at
`0xC0BAC14C + n*0x18 + 0x14`. `echo` is entry 17, pointer `0xC0BAC2F8`. Your code
then runs in the dispatcher's task, where blocking is fine — the shell's own
`dir`, `mkdir` and `sdcard` do file I/O — it returns like an ordinary function,
and `[r0]` is a printf so it can answer the host directly.

**Borrow the gyro callback** (`oneshot.S`) when you need to run at a moment no
command can reach — during recording, between frames. It fires at 50-90 Hz, so
the code runs interrupt-ish: **do not block, do not take a mutex, do not call
anything that might.**

Work needing task context used to mean creating one from the callback, which is
a dead end: `ext_tsk`'s stub is not in the firmware's syscall table — the 16
stubs matching its template carry service ids `0x8001`, `0x8003`, `0x801B`-`0x8024`,
`0x8037`-`0x8044`, and no `0x8004` constant exists anywhere in `0xC0010000`-`0xC0040000`
— so a task that finishes has no way to exit, and returning from a task entry is
undefined. Borrow a command instead.

## Writes get dropped

`mem set` loses writes, silently. Measured over 200 words: 18 lost at full
speed, none on the next run, 48 on the one after — so it is not pacing, and no
delay makes it safe. Reads are sound: three verifies of one region named the
same two words every time.

**So write, read back, rewrite what is missing, and repeat until nothing is.**
Two words lost out of `putfile.S`'s 78 turned `movt ip, #0xC044` into the `blx
ip` that followed it — a call to whatever `ip` happened to hold.

Send the bytes in the command line rather than one word per `mem set`.
`bulkload.S` moves about 240 at a time against four, which took 14 KB of AutoRun
from 448 seconds to under one. The transport was never slow: reading the same
file back always took 22 seconds, because `mem get` answers sixteen words at
once. Verification still applies, and matters more, because a chunk that goes
missing leaves a 240 byte hole rather than a four byte one.

## Push an even number of registers

AAPCS wants the stack eight byte aligned at a call, and `push` of an odd count
leaves it four. Nothing complains. It costs nothing until the callee reaches an
`LDRD` or `STRD`, and then it is a data abort — with the shell task holding the
dispatcher, so the shell dies and the battery has to come out.

`callfn.S` pushed nine registers and froze the camera on its first call, to the
firmware's own monotonic clock, which is as safe a target as exists. Every other
template here had the same fault and had simply not called anything that cared.

Save `lr` too, in anything that calls out. `blx` overwrites it, so a routine
that ends in `bx lr` after calling something returns into whatever the callee
left behind. The gyro logger's `writer_open` called out five times without
saving it, and `writer_close` four; neither had ever run.

## Keep your state to yourself

Templates share `0xC072F500`, so a template that both stores state there and is
loaded by another one will corrupt it. `bulkload.S` did: its destination pointer
sat at `+0x14`, which is `getfile.S`'s buffer, so loading getfile advanced that
word past its own buffer and the read landed elsewhere. Every byte came back as
the poison the host had written first — which is the only reason it was noticed.

## Memory

```
0xC072F500  parameters and results, 256 bytes, yours
0xC072F600  the routine, up to 0xC0730000
```

## Adding one

Two things earn a file a place here, and neither is "it worked once".

**Every return value is checked.** The media API reports failure by returning
zero, and a write that never happened looks exactly like one that worked if
nobody looks. The gyro logger's file sequence checks nothing and opens with mode
`0x402`, which fails when the file already exists — harmless for a logger that
always picks a new name, wrong for anything that updates a file in place. That
sequence is not a template; `putfile.S` uses mode 7 and checks each step.

**What is verified is written down, and what is not is written down too.** A
constant that came from watching working code is a guess about what the firmware
does, not a fact about it. Say which is which in the header.

---

# 範本

**拿去改**的東西,不是拿去呼叫的。每一個處理掉一類工作的管線,讓你只要寫工作本身。

| | |
|---|---|
| `shellcmd.S` | 借一個 shell 指令,讓程式碼跑在 task 環境 |
| `oneshot.S` | 借陀螺回呼,跑一次 |
| `bulkload.S` | 把資料塞在指令列送過去,一次約 240 bytes |
| `putfile.S` | 把主機給的資料寫成卡上的檔案 |
| `getfile.S` | 把卡上的檔案讀進記憶體 |

## 唯一的規則

shell 能寫記憶體,但**沒有任何指令能呼叫**。讓程式碼執行的方法是:把韌體本來就會
呼叫的位址指向你的常式,讓它跑起來。這裡每個範本都從這件事開始;差別在**借哪個
位址**,而那個選擇決定了你的程式碼被允許做什麼。

**優先借指令 handler**(`shellcmd.S`)。指令表是 77 個 `{char name[0x14]; void *handler}`
在 `0xC0BAC14C`,間距 `0x18`,所以第 *n* 個的 handler 指標在
`0xC0BAC14C + n*0x18 + 0x14`。`echo` 是第 17 個,指標 `0xC0BAC2F8`。這樣程式碼跑在
dispatcher 的 task 裡,**可以阻塞** —— shell 自己的 `dir`、`mkdir`、`sdcard` 都在做
檔案 I/O —— 而且像普通函式一樣 return,`[r0]` 還是 printf,可以直接回話給主機。

**借陀螺回呼**(`oneshot.S`)只在需要跑在指令到不了的時刻時用 —— 錄影中、影格之間。
它 50–90 Hz 觸發,環境接近中斷:**不能阻塞、不能拿 mutex、不能呼叫任何可能會的東西。**

需要 task 環境的工作,以前的做法是從回呼裡開 task —— 那是死路:`ext_tsk` 的 stub
**不在韌體的 syscall 表裡**(符合同一樣板的 16 個 stub 服務 ID 是 `0x8001`、`0x8003`、
`0x801B`–`0x8024`、`0x8037`–`0x8044`,而 `0xC0010000`–`0xC0040000` 內根本沒有 `0x8004`
開頭的常數),所以做完事的 task 沒有辦法結束,而從 task 進入點直接 return 是未定義
行為。改成借指令。

## 寫入會被丟掉

`mem set` **會靜默掉寫入**。實測 200 個字:全速掉 18 個,下一輪 0 個,再下一輪 48 個
—— 不是速度問題,加延遲也沒用。讀取是可靠的:同一區域驗證三次,每次都指出同樣那兩個字。

**所以寫完要回讀、補寫缺的、重複到乾淨為止。** `putfile.S` 的 78 個字掉了兩個,結果
`movt ip, #0xC044` 變成後面那條 `blx ip` —— 也就是呼叫 `ip` 當下剛好是什麼就跳去哪裡。

而且**資料要塞在指令列裡送**,不要一個字一條 `mem set`。`bulkload.S` 一次搬約 240
bytes 而不是 4,14 KB 的 AutoRun 從 448 秒降到一秒以內。傳輸本身從來不慢:同一個檔案
讀回來一直都只要 22 秒,因為 `mem get` 一次回 16 個字。驗證還是要做,而且**更重要**
—— 掉一塊是 240 bytes 的洞,不是 4 bytes。

## 推入偶數個暫存器

AAPCS 要求呼叫時堆疊八位元組對齊,而 `push` 奇數個暫存器會讓它變成 4-mod-8。
**沒有任何東西會抱怨。** 一直到被呼叫的函式遇上 `LDRD`/`STRD` 才會 data abort ——
而那時 shell 的 dispatcher task 正卡在裡面,所以 shell 直接死掉,要拔電池。

`callfn.S` 推了九個暫存器,第一次呼叫就把相機凍住 —— 而且目標是韌體自己的
單調時鐘,已經是最安全的對象了。這裡每一個範本本來都有同樣的缺陷,只是剛好
沒呼叫到在意的東西。

**會呼叫別人的常式也要存 `lr`。** `blx` 會覆寫它,所以一個呼叫過別人、結尾又
`bx lr` 的常式,會返回到被呼叫者留下的任意位址。陀螺 logger 的 `writer_open`
呼叫了五次都沒存,`writer_close` 四次 —— 而它們從來沒跑過。

## 狀態要自己帶

範本共用 `0xC072F500`,所以一個既在那裡存狀態、又會被別的範本載入的範本一定會出事。
`bulkload.S` 就踩了:它的推進指標放在 `+0x14`,那是 `getfile.S` 的緩衝參數,結果載入
getfile 的程式碼時把它推過了頭,讀取落在別的地方。回來的每個位元組都是主機事先寫的
毒值 —— **那也是唯一發現它的原因**。

## 記憶體

```
0xC072F500  參數與結果 256 bytes,你的
0xC072F600  常式本體,到 0xC0730000
```

## 要加新的範本

有兩個條件,「跑過一次沒事」不算。

**每個回傳值都檢查。** 媒體 API 用回傳 0 表示失敗,而**沒發生的寫入跟成功的寫入
長得一模一樣**,只要沒人去看。陀螺 logger 的寫檔序列一個都沒檢查,而且用
mode `0x402` —— 檔案已存在就失敗。對總是換新檔名的 logger 無害,對要「就地更新」
的東西就是錯的。所以那段不是範本;`putfile.S` 用 mode 7,而且每步都檢查。

**驗證過的寫下來,沒驗證的也寫下來。** 從「看能跑的程式碼怎麼用」推出來的常數,
是對韌體行為的猜測,不是事實。在檔頭裡分清楚。
