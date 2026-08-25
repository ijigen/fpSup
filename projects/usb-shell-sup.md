# usb shell sup

[English](#english) | [繁體中文](#繁體中文)

USB firmware research and data transport. **Status: v2 shipped** — code in
[`../fp_usb_shell/`](../fp_usb_shell/)

USB 韌體研究與資料傳輸工具。**狀態:v2 可用**

---

## English

### Goal

A channel that can command the camera and pull data out of it without reflashing
anything — and **without disturbing the camera's normal operation**, recording in
particular.

### Where it stands

`shl <line>` hands the line to the camera's own firmware shell and returns what it
printed; all 77 commands work. The channel is built on the camera's own PTP gadget
and changes seven words of descriptor template.

```
EP 0x01 OUT  bulk 1024  burst 3    commands
EP 0x82 IN   bulk 1024  burst 3    replies
EP 0x83 IN   bulk 1024  burst 3    streaming — PTP's unused interrupt endpoint
```

All three are created, enabled and re-created by the firmware after a record-mode
reconfiguration.

### Proven

- **Recording while connected works.** With the daemon attached and commands
  already exchanged, recording is normal and `DALEPENA` reads `0x0A7` before and
  after. v1 could not do this; it is the reason for the rewrite
- Memory read and write through the firmware shell's own `mem get` / `mem set`
- Three bulk pipes, confirmed from the host with `lsdesc`
- Running injected code once: point an address the firmware already calls at the
  routine, let it restore the call site, touch neither the AutoRun nor the daemon
- A boot progress bar — where it stops is where the load stopped

### Not done

- **EP 0x83 has not moved a byte yet.** It is enabled and correctly described, but
  nothing has armed it. The first hook that needs it will be the test
- v1's hook-push sources still target the old endpoint (`0xC31E3274`,
  `StartTransfer(9)`); here they become `0xC31E3270` and `StartTransfer(7)`

### Two things that cost time to learn

**A worker must not touch an endpoint before the firmware configures it.**
`DALEPENA` stays `0x003` until the host completes SET_CONFIGURATION; issuing
DEPCMDs before that competes with the driver mid-enumeration and enumeration
loses. Three boots failed this way, and it was briefly misdiagnosed as a
descriptor or class-handler problem. `USB_STATE` is no substitute — it reads 2
long before the endpoints exist.

**Judge from a clean boot.** Several wrong conclusions came from reading a state
that earlier experiments had already disturbed.

### Paths tried that do not work

- **The firmware's own vendor gadget** (the selector's default branch). The
  builder runs and registers, but its descriptors have two objective defects —
  high speed and SuperSpeed share one interface object, and the SuperSpeed config
  `totalLength` does not add up — and the host never assigns an address. It is
  dead code SIGMA never shipped
- **A PTP opcode as the channel.** Bandwidth is fine (a data phase is one bulk
  transfer), but a hook's data always waits for a scheduler, so it cannot be
  zero-latency
- **Borrowing CDC's endpoints.** `StartTransfer` returns 0 and nothing moves; not
  fully diagnosed

---

## 繁體中文

### 目標

在不重刷韌體的前提下,建立一條能對相機下指令、把資料搬出來的通道,而且**不能影響相機正常運作**
(特別是錄影)。

### 現況

`shl <line>` 把整行交給相機自己的韌體 shell 執行並回傳輸出,77 個指令全部可用。
通道建立在相機原本的 PTP gadget 上,只改七個字的描述元範本。

```
EP 0x01 OUT  bulk 1024  burst 3    指令
EP 0x82 IN   bulk 1024  burst 3    回覆
EP 0x83 IN   bulk 1024  burst 3    串流(PTP 沒人用的 interrupt 端點改的)
```

三條都由韌體建立、啟用,並在錄影模式重設後由韌體重建。

### 已驗證

- **錄影共存** —— daemon 連著、指令往返過之後錄影正常,`DALEPENA` 前後都是 `0x0A7`。
  這是 v1 做不到的事,也是整個重寫的理由
- 記憶體讀寫透過韌體 shell 的 `mem get` / `mem set`
- 三條 bulk 管線(主機端 `lsdesc` 確認)
- 一次性執行注入程式碼:把韌體會呼叫的位址指向我們的常式,跑完自己還原,
  不動 AutoRun 也不動 daemon
- 開機進度條 —— 停在哪就是載入停在哪

### 尚未完成

- **EP 0x83 還沒實際搬過資料**。已啟用、描述元正確,但還沒有東西武裝它。
  第一個需要它的 hook 就是測試
- v1 的 hook-push 程式碼仍指向舊端點(`0xC31E3274` / `StartTransfer(9)`),
  在新 gadget 上要改成 `0xC31E3270` / `StartTransfer(7)`

### 過程中付出代價才學到的兩件事

**worker 不能在端點被韌體配置前碰控制器。** `DALEPENA` 在主機完成 SET_CONFIGURATION
之前一直是 `0x003`;在那之前發 DEPCMD 會跟正在列舉的驅動搶,輸的是列舉。
連續三次開機都栽在這裡,而且一度被誤判成描述元或 class handler 的問題。
`USB_STATE` 不能代替 —— 它在端點存在很久之前就是 2。

**判斷要以乾淨開機為準。** 好幾個錯誤結論都來自讀一個已經被先前實驗擾動過的狀態。

### 走過但不通的路

- **韌體的 vendor gadget(選擇器 default 分支)** —— builder 會跑、也會登記,
  但描述元有兩個客觀缺陷(HS/SS 共用介面物件、SS config totalLen 對不攏),
  主機連位址都不指派。那是 SIGMA 沒出貨、沒測過的死碼
- **PTP opcode 當通道** —— 頻寬沒問題(data phase 是一次 bulk 傳輸),
  但 hook 觸發到資料離開相機中間一定隔著排程,達不到零延遲
- **借 CDC 的端點** —— `StartTransfer` 回 0 但資料不動,未查清

---

**Notes / 相關筆記:** `USB_SHELL`, `USB_MODES_COMPLETE`, `USB_GADGET_REGISTRATION`,
`SHELL_COMMANDS`, `RECORD_SHELL_COEXIST_RESOLVED`, `TASK_ABI_VERIFIED`,
`HOOKPUSH_PACING`, `EGRESS_MAP`
