# 2026-10-26 上机只读核对（第 1 次）

相机：SIGMA fp Ver.5.02，USB shell 已加载（interface 0 = vendor，EP01/EP82/EP83）。
主机：Linux，`fpSup/fp_usb_shell/fpshd` 3.2.0（sha256 前缀 `842ef32c827f389c`）。
没有按键、拍摄、写卡或改设定。

## 读到的值

| 命令 | 回复 | 解读 |
|---|---|---|
| `menu SetStillDNGQuality` | `1` | [I] 14 bit（菜单顺序 12 bit, 14 bit；默认 14 bit）。映射未核实 |
| `menu SetDriveMode` | `0` | 单张 |
| `menu SetContinuousShootingSpeed` | `0` | 高速（与固件推论"录制设定 `+0x4C` = 0 → HIGHCONT"一致） |
| `imager mode_now` | `053 MONIT1_60, enum 0008, 12 bit, 2016x1344, 60 fps, 3:2 full` | 待机取景模式 |

`imager mode_now` 全文：

```
No ,mode                         ,enum,bit,size     ,frame ,fps ,aspect ,crop,
053,MONIT1_60                    ,0008, 12,2016x1344,016683,0060,  3: 2 ,full,
shutter:00011767,gain:000497
frame_count:00003051,trans_count:00003048
gain_state: through
small_raw
base_size h:2016 v:1344
raw_zoom  h:1024 v:1024
hvbin     h:0001 v:0001
bef_size  h:2016 v:1344
offset    h:0000 v:0000
v_down_sample    v:0001
```

## 传输问题

- `fpshd` 默认回复超时 200 ms：`version` 超时 → 守护进程 clear-halt（xHCI `Set TR Deq Ptr cmd failed`）
  → 相机断开并在约 0.2 s 后重新枚举。改用 `fpshd --timeout 2000` 后，`ping` 与上表四条读取全部成功。
- `still lvinfo 2`：命令送出后、第一帧回复前设备断开（`LIBUSB_ERROR_NO_DEVICE`），0.23 s 后重新枚举。
  没有重试。离线读码确认它只查询并打印（`FUN_c040ed20` → `FUN_c0437740`、`FUN_c040ef50(…,3/4)`），
  断开原因未知：可能是输出较长或处理时间超过 worker 的某个门限。下次先试 `still lvinfo 1`（输出较短，
  含 `stillSize … bit`），仍断开就不再用 `lvinfo`。
- 第 2 次（`fpshd --timeout 2000`）：`ping`、`menu SetStillDNGQuality`（仍为 `1`）正常；
  `still lvinfo 1` 回复超时，相机 USB 断开后 0.22 s 重新枚举（设备 8→9）。**`still lvinfo` 系列在这套
  USB shell 上会让连线断开，不再使用。** 记录：`precap-oncam-2.txt`、`precap-fpshd-2.log`。
- 离线：位深枚举换算 `FUN_c02da870`（`lvinfo` 打印 `stillSize … bit` 时使用）是跳转表
  0→12、1→14、2→16、3→10、4→8、5→7、6→6、7→5 bit；与 `research/ui/HOW_CHANGES_TAKE_EFFECT.md`
  "选 14 bit → `eRawBitType = 1`" 一致。若 `SetStillDNGQuality` 用同一枚举，读到的 `1` 即 14 bit [I]。
- 第 3 次：使用者拍了一组原厂高速连拍。`dir \DCIM\128SIGMA`（原生命令，只读）列出
  `SDIM0183`–`SDIM0191` 共 9 张，相机时间 19:01:46–19:01:50，每张 28,217,181–28,235,224 B（几乎一致）。
  文件大小不足以判定位深（≈9.2 bit/像素，12 与 14 bit 无损都可能）；要读 DNG 头。
  `getfile.py`／`cardread.py` 需借用 echo 处理指针，USB 断线会冻住相机（只能拔电池），本次不用。
  记录：`precap-dir128.txt`、`precap-oncam-3.txt`、`precap-fpshd-3.log`。
- 第 4 次（使用者同意后）：`getfile.py '\DCIM\128SIGMA\SDIM0183.DNG' --size 65536 --partial`。
  在最前面的 `cave.claim` 读分配指针时失败（`the bump pointer did not read back`），同时 USB 断开重连
  （内核 60629.89 s，device 9 → 10）。写分配指针、写代码、借用 echo 都在这之后，均未执行；没有重试。
  今天每次断开都紧跟某条命令，不是定时断开 → USB 读文件路线停用，改用读卡器。
  记录：`getfile-0183.txt`、`precap-fpshd-4.log`、`dmesg-usb-4.txt`。
- 第 5 次：卡改插主机读卡器（自动挂载为读写，先 `remount,ro` 再读；读完 `umount`）。
  `tools/dnghead.py` 解析 `SDIM0183`–`SDIM0191`（输出 `dnghead-0183-0191.txt`）：
  - **Q1 定案：原厂高速连拍是 14 bit。** 主 RAW（SubIFD0）6064×4042，`BitsPerSample` 14，
    `WhiteLevel` 16383，`BlackLevel` 1024，Compression 7（无损 JPEG），256×256 分块。固件 5.02.0.V91。
  - 9 张曝光完全一致：1/20 s、f/1.4、ISO 100、85 mm（场景静止，不足以证明 AE 锁首帧）。
  - EXIF 无 SubSecTime；`DateTimeOriginal` 6 张在 19:01:45、3 张在 :46 → 全组在 2 s 内，
    帧间隔只能定上限。精确帧距需另测（例如对着手机秒表连拍）。
- 第 6 次（Q8，使用者半按住、授权后）：`menu SetDriveMode` = 1、`menu SetContinuousShootingSpeed` = 2；
  主机 19:56:58.285 `key S2ON`，19:56:59.317 `key S2OFF`，两条都 rc=0，USB 未断。
  `dir` 显示新增 `SDIM0192`–`SDIM0205` 共 14 张（相机时间 19:49:38–19:49:46，相机钟比主机慢约 7 分钟）。
  **代按全按能让原厂连拍持续出帧，S2OFF 能收尾。** 约 1.03 s 拍到 14 张。
  异常：第一张 `SDIM0192` 51,277,716 B，其余 28.89–28.91 MB；原厂实拍那组第一张与其余一样大。
  使用者观察：全程没有完全按下快门；快门声是连续一串（没有单独的第一声）；连拍期间取景画面一直在动。
  DNG 头（读卡器只读挂载，`dnghead-0192-0205.txt`）：14 张全是 6064×4042、14 bit、同曝光
  （1/20 s、f/1.4、ISO 100）。**第一张 `SDIM0192` 的主 RAW 是 Compression 1（未压缩、不分块）**，
  其余 13 张是 Compression 7（无损 JPEG、256×256 分块），与原厂实拍那组一样。
  `DateTimeOriginal`：9 张 19:49:37、5 张 19:49:38。编号 0192–0205 连续。
  记录：`precap-key-1.txt`、`precap-dir128-after-key.txt`、`precap-fpshd-5.log`。
- 内核 USB 时间线见 `dmesg-usb.txt`（59517–59720 的 200 s 空档是使用者重新连接相机）。

## 第 7 次：P1 写卡（读卡器，相机未连线）

- 使用者指定用相机里现有的卡（没有空白卡）。卡：exFAT 119 GB，Loader v3 卡（README.txt：Instant Start ON、Fast Start OFF），已用 11 GB。
- 写卡前整卡文件备份到 `/opt/sigma/card-backups/20261026-before-p1/`（`files/`、分区前 32 MB 映像 `sdd1-first32M.img`、清单 `card.sha256`，副本 `card-before-p1.sha256`）；4194 个路径全部按哈希核对一致。
- 卡上原有问题（非本次造成）：`CINEMA/A001_008`、`A001_011`、`A001_020` 各有一个 `…_000001.DNG` 重复目录项（同名、同大小、同时间）；`fsck.exfat -n`（exfatprogs 1.2.2）只报这 3 项，未修复；内核提示卷上次未正常卸载。
- 写入：根目录 `AutoRun.txt` 换成 P1 版（sha256 `7d764f55…`），新增 `fpSup.BIN`（`87d9ae5b…`）；`fpSup\` 目录未动。清缓存重挂后读回哈希一致，已卸载。
- 还原 v3：把备份里的 `files/AutoRun.txt` 拷回根目录、删掉根目录 `fpSup.BIN`，再拔一次电池。

## 第 8 次：P1 第一次开机（22:21–22:34）

- 使用者：插卡后拔过电池再开机；屏幕上"什么文字都没有，和原厂开机一样"；相机操作正常。
- USB：22:23:40 相机出现，22:23:58 断开、22:24:07 再出现。fpshd 启动后 `ping` 得 `pong`——**这是 fpshd 自己回的（host/fpshd.c），不经过相机，不能当作相机命令行存活的证据**。第一条真正发往相机的 `mem get 0xC038F0E8` 回 `LIBUSB_ERROR_NO_DEVICE`，相机 0.2 s 后重新列举（设备 16→17）；按规则停止，未重试，fpshd 以 `QUIT` 关闭。记录：`/tmp/precap-fpshd-7.log`。
- 读卡（只读；系统自动挂在 `/media/DCIM/DJI_001/1755-A2A6`，先 remount,ro）：除本次写入的 `AutoRun.txt`、`fpSup.BIN` 外，全卡 4194 个路径与写卡前清单逐一哈希相同；`fpSup/LOAD.LOG` 与备份逐字节相同 → 今晚 v3 载入器没有运行（排除残留 Instant hook 抢先载入）。
- 尚不能区分：(a) 相机没执行 AutoRun；(b) AutoRun 执行、P1 已装，但文字横幅未被注意、`mem get` 掉线是今天的 USB 不稳。区分方法：开机后只读 sysfs 的 USB 介面类别（有命令行时 iface-class 补丁会改掉 PTP 类别），不向相机发命令。

## 第 9 次：P1 第二次开机（22:44）——AutoRun 执行，但钩子没装

- 使用者：拔电池、不接 USB 开机，盯背屏：`fpSup[........]000` → `060` → `090` → `fpSup-DEV-PreCap1!` **全部出现**。第 8 次的"什么都没有"应是没看到（文字横幅不停留）。
- 接 USB 后 sysfs：`2-1:1.0 class=ff sub=ff proto=ff eps=3`（iface-class 补丁生效，命令行已载入；原厂 PTP 为 06）。
- `p1_read.py read`：两处改动点仍是原厂 `blx r3` → 启动码没有装钩子。
- 原因（离线确认）：stage2 每次开机把 `CAVE_BUMP` 重设为 `CAVE_ARENA = LOADER_END = 0xC072E064`，只是 4-byte 对齐；`pc_launch.S` 要求 8-byte 对齐（`tst r5,#7`）→ 每次开机都按"失败不装"返回。rawview 只检查容量、不检查对齐。模拟器测试用了 8-byte 对齐的初值 0xC072E400，所以没抓到。
- 之后一条 `mem get 0xC072E060`（想直接读 CAVE_BUMP）回 `LIBUSB_ERROR_TIMEOUT moved=0/64`；按规则停止、未重试；fpshd `QUIT` 关闭。记录：`precap-fpshd-8.log`。
- 修正：改为 `tst r5,#3`；测试初值改用 `cave.CAVE_ARENA`，加"开机值只有 4-byte 对齐"与新边界（满 0xC072EFA8、刚好放得下 0xC072EFA4、不对齐 +2）。旧代码下新测试 9 项失败；修正后 23 项全过；9 处改坏全部被抓到。
- 新卡 `out/p1-dev`：`AutoRun.txt` 不变（`7d764f55…`），`fpSup.BIN` → `68a69c3e…`。旧版留在 `out/p1-dev-v1-align-bug/`。

## 第 10 次：尝试经 USB 更新 fpSup.BIN（22:52）——未写入

- 使用者同意经 USB 改卡（"卡上的你随便动"）。用原版 `/opt/sigma/fpSup/fp_usb_shell/deploy.py --bin-only out/p1-dev`（原版 getfile 会核对路径字、cave 读 12 次；相机端 asm 与 fork 相同）。
- 结果：`dir` 正常（卡上 AutoRun 3439 B）；读 AutoRun 前 `cave.boot_id()` 失败："LOAD_DONE_US reads zero"。同一时刻 14:52:53 UTC 相机 USB 断开重连（设备 19→20）。stage2 第 294 行无条件写 LOAD_DONE_US，而 `boot_id()` 把"12 次都没有回复"也当成 0 → 实为链路掉线，不是卡缺标记。
- 未借用 echo（失败在 claim 之前），未写卡。之后 sysfs 仍 class=ff；fpshd `QUIT` 关闭。记录：`precap-deploy-1.txt`、`precap-fpshd-9.log`。
- 22:44 起这次开机的链路：p1_read 的几条 `mem get` 成功 → 下一条 `mem get` 超时 → deploy 的 `dir` 成功 → 接着掉线。几条命令就掉一次，不适合需要借用 echo 的传档。

## 第 11 次：读卡器换 fpSup.BIN（23:03）

- 写前（只读）：卡上 `AutoRun.txt` `7d764f55…`、`fpSup.BIN` `87d9ae5b…`（第 7 次写入的旧版），自上次写入后没有其他文件变动。
- 只换 `fpSup.BIN` → `68a69c3e…`（4-byte 对齐修正版）；清缓存重挂读回两个文件哈希一致；已卸载。

## 第 12 次：P1 上机通过（23:14–23:30）

- 拔电池开机，横幅正常；sysfs class=ff。
- 拍前 `p1_read.py read`（`p1-read-2-idle.txt`）：观察器 `0x44F5A980`，跳板 `0xC072E064`／`0xC072E06C`（= 开机时 CAVE_ARENA），PCP1 layout 1、ring 64，计数全 0。
- 使用者手按高速连拍约 1 s：快门声连续、取景在动、松手即停，与原厂一样；之后相机正常。
- 第一次读计数：`mem get` 回 NO_DEVICE，15:23:49 UTC 断线且**没有**重新列举（xhci：Set TR Deq Ptr cmd failed）。相机本身正常。使用者重插 USB 后恢复（设备 23，class=ff），计数仍在。
- 重插后第一次读：一条 `mem get` 只收到 12/64 字节（无断线）。`mem get` 为只读，重读一次成功（`p1-read-3-burst.txt`／`-report.txt`）：
  - **14 帧，全部经 B 点 `C038F174`，A 点 `C038F0E8` 0 次**；job id 0–13 连续；Yuv 对象恒为 `0xC35201E0`。
  - 间隔 53.1–56.6 ms，平均 55.5 ms = **18.01 fps**；首末 721.7 ms。
- `dir \DCIM\128SIGMA`（`precap-dir128-after-p1.txt`）：新增 `SDIM0206`–`SDIM0219` 共 14 张，与计数一致。
- 第一张 `SDIM0206` 51,558,672 B，其余约 29.4 MB：与 0192（注入）相同的"首张未压缩"；19:01 原厂实拍 0183–0191 则全部约 28.2 MB。→ 首张未压缩与注入、与 P1 都无关，原因待查（Q8 更新）。

## 第 13 次：插着 USB 开关机（23:31–23:33）

- 使用者：插着 USB 用电源开关开关机，"开机不出现横幅了"。USB 时间线 15:31:20–15:32:45 UTC 断开／列举数次（设备 23→29）。
- sysfs class=ff。`p1_read.py read`（`p1-read-4-usbboot.txt`）：观察器 `0x4505A9C0`（上次 `0x44F5A980`），计数 0 → 本次开机重新安装；`LOAD_DONE_US` = 0x0028C6D2 = 2,672,338 µs（开机后 2.7 s 载入完成）。
- 结论：插着 USB 开机时 fpSup 照常载入，只是横幅不显示；上一次关机的写回有效（否则 guard 会拒装）。
- ×10 测试改为拔掉 USB 做：插着 USB 关机按 BUILDING.md 会让固件重新载入，测不到暖开机（映像留在内存）的写回路径。

## 第 14 次："开机-不拍-关机"×10（拔掉 USB，电源开关，不拔电池）——P1 通过

- 使用者：10 次都出现横幅，正常。USB 15:35:19 拔下、15:35:51 插回（设备 30，class=ff）。
- `p1_read.py read`（`p1-read-5-after10.txt`）：观察器 `0x44F5A980`（不接 USB 开机时堆位址每次相同），计数 0；`LOAD_DONE_US` = 0x00348605 = 3,442,181 µs（本次开机写入）。
- `CAVE_BUMP` = `0xC072E074` = CAVE_ARENA + 16 → **本次开机启动码通过 guard 并装上两个跳板**。stage2 每次开机把它重设为 0xC072E064，只有装成才会 +16。
- 推论：任何一次关机写回失败，改动点都会留着 bl，之后每次开机 guard 都拒装（且 journal 把残留当原厂值记下，不会再写回），指针会停在 0xC072E064。最后一次装成 → 这一串关机写回全部有效。
- P1 结论：钩子机制、关机写回、重复载入都正常；观察期间拍摄与原厂无异。

## 第 15 次：整理卡、还原 v4 正式卡（23:44，读卡器）

- 使用者要求：卡同步到最新 fpSup；杂项迁到电脑；非实验阶段卡上只留最新 fpSup 与照片／视频文件夹。
- 版本核对：卡上 `fpSup/` 与 `/opt/sigma/card-v4-official/`（10-26 01:58，Loader v4）25 个文件逐字节一致；产品 BIN 与 `fpSup-next/fpSup/tools/merge-v4/inputs/v4-20261025`（唯一、最新快照）逐字节一致；01:58 之后 loader-v4／build_autorun／asm 源码未改（只改了 merge-v4 网页模板与测试）→ 卡上已是最新，不需要换版本。
- 写前（只读）：自第 11 次后只新增 `SDIM0206`–`SDIM0219`。
- 迁出到 `/opt/sigma/card-offload/2026-10-26/`（保留卡上路径；先复制、逐一 cmp，`MANIFEST.sha256`）共 31 个文件：根目录 `af_dbg00`–`16.csv`、`timing.csv`、`README.txt`（过时的 v3 说明）、`NIKON001.DSC`；`fpSup/LOAD.LOG.bak`、`fpSup/LOAD.LOG.20261017-full`；`fpSup/_off/` 7 个停用／坏掉的旧 BIN；P1 的根目录 `AutoRun.txt`、`fpSup.BIN` 放在 `p1-experiment/`。
- 卡上：删除上述文件；`AutoRun.txt` 换回 `card-v4-official/AutoRun.txt`；删空目录 `WORK/`、`fpSup/_off/`。（删除一步被自动审核拦下，经使用者批准后执行。）
- 写后（清缓存、只读重挂）：根目录只剩 `AutoRun.txt`、`CINEMA`、`DCIM`、`fpSup`、`System Volume Information`；`AutoRun.txt` 与 `fpSup/` 25 个文件和 `card-v4-official` 一致，另有 `fpSup/LOAD.LOG`（载入器诊断，保留）；DCIM 124 个文件、CINEMA 4029 个文件；`fsck.exfat -n` 仍只报原有 3 个重名项。已卸载。
- 下次开机前要拔一次电池（清掉内存里可能残留的 P1 补丁，让 v4 干净开机）。
