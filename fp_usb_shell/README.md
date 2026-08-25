# fp USB Shell

[English](#english) | [繁體中文](#繁體中文)

Run the SIGMA fp's own firmware shell commands over USB. Two generations live
here; **[v2](v2/) is the one to use.**

| | [v1](v1/) | [v2](v2/) |
|---|---|---|
| Endpoints | added EP 0x84 / 0x05, unknown to the firmware | the PTP gadget's own EP 0x01 / 0x82 / 0x83 |
| Who owns them | the worker: enable by hand, keep DALEPENA alive, patch the endpoint type table | the firmware |
| After a record-mode reconfiguration | torn down, never rebuilt | rebuilt by the firmware |
| **Recording while connected** | **broken** — empty files once a command had been exchanged | **works** |
| Firmware changed | descriptor-builder hook + injected routine | seven words of descriptor template |
| Pipes | one bulk pair | three bulk pipes: commands, replies, streaming |

---

## English

### What it does

`shl <line>` hands the line to the camera's own firmware shell and returns what
it printed — all 77 commands, including `mem set` and `mem save`, so the shell
needs no memory commands of its own. Nothing is flashed: an `AutoRun.txt` on the
SD card writes everything into RAM at boot.

### Why there is a v2

v1 worked, but it built the channel out of endpoints the firmware did not know
about. They had to be enabled and maintained by hand, and when recording started
the firmware reconfigured the controller and wiped them — so recording with the
daemon attached produced empty files. No amount of gating fixed that, because the
firmware could not rebuild endpoints it had never registered.

v2 stops inventing endpoints. It leaves the PTP gadget exactly as the firmware
builds it and edits seven words of descriptor template, one of which turns PTP's
unused interrupt endpoint into a second bulk IN. The firmware then creates,
enables and re-creates all three pipes, and recording while connected works.

v1 is kept because its write-up of the "shell freezes the camera" root cause and
its hook-push experiments are still the reference for that behaviour.

### Start here

[**v2/**](v2/) — current. Build, card layout, protocol, and the two mistakes
that are easy to repeat.

---

## 繁體中文

### 這是什麼

`shl <line>` 把整行交給相機自己的韌體 shell 執行,並回傳它印出來的東西 ——
77 個指令全部可用,包括 `mem set` 和 `mem save`,所以這個 shell 不需要自己實作
記憶體指令。完全不需要重刷韌體:SD 卡上的 `AutoRun.txt` 在開機時把東西寫進 RAM。

### 為什麼有 v2

v1 能用,但它是用**韌體不認得的端點**搭出來的。那些端點必須自己啟用、自己維護,
而錄影一開始,韌體會重設控制器把它們掃掉 —— 所以 daemon 連著錄影會得到空檔案。
再怎麼加閘門也沒用,因為韌體不可能重建它從來沒註冊過的端點。

v2 不再自己發明端點。它讓 PTP gadget 完全照韌體原本的方式建立,只改七個字的
描述元範本,其中一個把 PTP 沒人用的 interrupt 端點變成第二條 bulk IN。
三條管線就都由韌體建立、啟用、並在錄影重設後重建,**連著線錄影因此正常**。

v1 保留下來,是因為它裡面「shell 為何會凍住相機」的根因分析和 hook-push 的
實驗紀錄,到現在仍然是那些行為的參考資料。

### 從這裡開始

[**v2/**](v2/) —— 目前版本。含建置方式、卡片內容、協定,以及兩個很容易重蹈的錯誤。
