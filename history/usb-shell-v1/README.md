# USB shell v1 — superseded

> **Superseded by [fp USB Shell v2](../../fp_usb_shell/).** Kept as history. Its
> documentation and its tools have been moved out to where they belong; what
> remains here is the transport itself, which no longer runs.
>
> **已被 [fp USB Shell v2](../../fp_usb_shell/) 取代**,保留作為歷史。
> 它的文件與工具都已搬到該去的地方;留在這裡的是傳輸層本身,已經不能運作。

## What was wrong with it / 它錯在哪

It added endpoints — EP 0x84 and EP 0x05 — that the firmware did not know about.
They had to be enabled and maintained by hand, and a record-mode reconfiguration
tore them down and never rebuilt them, because the firmware cannot rebuild
endpoints it never registered. That is why recording with the daemon attached
produced empty files, and no amount of gating fixed it.

它加了韌體不認得的端點 —— EP 0x84 與 EP 0x05。那些端點必須自己啟用、自己維護,
而錄影模式重設會把它們掃掉且不會重建,因為**韌體不可能重建它從來沒註冊過的端點**。
這就是 daemon 連著錄影會得到空檔案的原因,再怎麼加閘門也沒用。

v2 stops inventing endpoints and uses the PTP gadget's own, so the firmware owns
them. See [fp USB Shell](../../fp_usb_shell/).

v2 不再自己發明端點,改用 PTP gadget 自己的,端點因此由韌體擁有。
見 [fp USB Shell](../../fp_usb_shell/)。

## Where its parts went / 各部分去了哪裡

| was | now |
|---|---|
| `docs/SHELL_COMMANDS_AND_EXECUTOR.md` | [`docs/SHELL_CAPABILITIES.md`](../../docs/SHELL_CAPABILITIES.md) |
| `docs/V27_FREEZE_ROOTCAUSE.md` | [`docs/FREEZE_ROOTCAUSE.md`](../../docs/FREEZE_ROOTCAUSE.md) |
| `dfd_hookpush/` | [`focus/dfd/`](../../focus/dfd/) |
| `lens/` | [`focus/lens/`](../../focus/lens/) |
| `console/` | [`console/`](../../console/) |
| `worker/imu_snapshot.S`, `build_stage5_autorun.py` | [`gyro/`](../../gyro/) |

## What is left here / 這裡剩下什麼

The superseded transport: six historical AutoRun scripts, the old host daemon,
and the old camera-side worker. Nothing here is current.

被取代的傳輸層:六份歷史 AutoRun 腳本、舊的主機 daemon、舊的相機端 worker。
這裡沒有任何東西是現行的。
