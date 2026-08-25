# Templates

Pieces that get copied and changed, rather than called. Each one solves the
plumbing for a class of job so that the job itself is the only part you write.

| | |
|---|---|
| `oneshot.S` | run a routine on the camera once, from the host |
| `putfile.S` | write a host-supplied blob to a file on the card |

## The one rule

The shell can write memory but nothing in it can call. Code runs by pointing an
address the firmware already calls at your routine, letting it fire, and putting
the original word back. Every template here starts from that.

The borrowed site is the gyro callback at `0xC00D0794`, which fires at 50-90 Hz.
Your code therefore runs in that callback's context: **do not block, do not take
a mutex, do not call anything that might.** Anything needing task context has to
start a task, as `putfile.S` does — file I/O blocks and takes the media mutex,
so its payload only creates the task and the writing happens there.

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
| `oneshot.S` | 讓一段常式在相機上跑一次 |
| `putfile.S` | 把主機給的資料寫成卡上的檔案 |

## 唯一的規則

shell 能寫記憶體,但**沒有任何指令能呼叫**。讓程式碼執行的方法是:把韌體本來就會
呼叫的位址指向你的常式,讓它跑一次,再把原值寫回去。這裡每個範本都從這件事開始。

借的是陀螺回呼 `0xC00D0794`,50–90 Hz。所以你的程式碼跑在那個回呼的環境裡:
**不能阻塞、不能拿 mutex、不能呼叫任何可能會的東西。** 需要 task 環境的就得自己開
task —— `putfile.S` 就是這樣:檔案 I/O 會阻塞也會拿媒體 mutex,所以 payload 只負責
建 task,寫檔在 task 裡做。

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
