# gyro

Tools for [gyro sup](../projects/gyro-sup.md).

[gyro sup](../projects/gyro-sup.md) 的工具。

| file | what it is |
|---|---|
| `imu_snapshot.S` | One call gathers accelerometer and gyro into a fixed result block at `0xC072F240`. Position independent, no firmware hook<br>一次呼叫把加速計與陀螺收進 `0xC072F240` 的固定結果區。位置無關,不需要 hook |
| `build_imu_snapshot.py` | Assembles it and emits the `mem set` lines<br>組譯並產生 `mem set` 指令 |
| `build_stage5_autorun.py` | Builds the gyro timestamp hook into an AutoRun<br>把陀螺時戳 hook 打包成 AutoRun |

**Not runnable as-is.** `imu_snapshot.S` was entered through the retired worker
`call` command; on [fp USB Shell v2](../fp_usb_shell/) it goes through
[`camera/oneshot.S`](../fp_usb_shell/camera/oneshot.S) instead.
`build_stage5_autorun.py` builds `stage5_gyro_timestamp_hook.S`, which is not in
this repository yet.

**目前不能直接跑。** `imu_snapshot.S` 原本是靠已退役的 worker `call` 指令進入的,
在 [fp USB Shell v2](../fp_usb_shell/) 上要改走
[`camera/oneshot.S`](../fp_usb_shell/camera/oneshot.S)。
`build_stage5_autorun.py` 建的是 `stage5_gyro_timestamp_hook.S`,那份原始碼還沒放進這個 repo。
