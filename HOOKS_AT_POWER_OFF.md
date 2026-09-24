# Hooks must come out at power-off

SIGMA fp Ver.5.02. Found 2026-09-24/25 while chasing a freeze in fpGyroSup
v1.13; fixed in e87eae2 and shipped as fpsup-gyro-v1.13.1.

**Readers:** anyone who installs a hook from an SD-card payload — our sups, and
module platforms built on the same loader. If your hook's code lives in memory
you got from the allocator, this applies to you.

## The rule

> A hook whose landing point or body is not firmware image must be taken out
> when the camera powers off. Register a power-off callback **before** arming
> anything, and do not arm if the registration fails.

A static patch whose code sits in the firmware image (a VBIN section at a fixed
address in the cave) is not covered: that code stays valid, and it survives a
warm restart along with the patch that calls it (see *What survives a
restart*).

## What happened

With gyro v1.13 loaded, the camera powered off normally, and the **next boot
froze** — with any card in the slot, a blank one included. With no card in the
slot it booted. It happened whether the power-off came 3 seconds or a minute
after loading. Recording never showed it, and neither did any test that
recorded before powering off.

Bisected on the camera. Every card used the v1.13 AutoRun and a cut-down BIN:

| card | result |
|---|---|
| stage2 only | clean |
| every section placed, payload not run | clean |
| payload run, stops before arming any hook | clean |
| payload run, no hook armed, everything after the hooks run | clean |
| only the **record-stop** hook armed | **froze, every time** |
| only the accelerometer hook armed | froze once, not reproducible |
| only the record-start hook, only the mode hook | clean |

## Two causes

**1. A state word lost its initial value when it moved (certain).**
The gyro drain keeps a cursor into the coprocessor's ring. `0xFFFFFFFF` means
"first visit: take the current head and copy nothing". While the cursor lived in
the cave, the deployer wrote that value. When it moved into the payload's own
blob it became `.word 0` — and 0 is a real cursor. The first drain after boot
treated everything from address 4 up to the ring as unread and copied it into
every buffer.

A take never showed this, because the record-start hook sets the cursor itself.
The only drain that runs *without* a take before it is the record-stop hook
firing while the camera powers off. That is why the stop-hook card froze every
time.

**2. Hook bodies moved into allocator memory, and the hooks outlive the boot.**
v1.12.1 kept the hook bodies in the cave, which is firmware image. v1.13 keeps
only an 8-byte veneer there and branches into the pool — memory from the
allocator. With cause 1 fixed, one freeze was still seen (and one on the
accelerometer-only card). Taking every hook out at the start of power-off made
the remaining freeze disappear.

Why, became clear a day later (*What survives a restart*, below): the power
switch is a warm restart, and the patched firmware image — the branch at each
hook site and the veneer in the cave — is still in memory on the next boot. The
pool is not: its pointer lives in the firmware's variables, which boot clears,
and the allocator hands its memory to others. So on the next boot, with any card
in the slot, a hook that fires jumps into somebody else's memory. A hook firing
during shutdown, while the pool is still being torn down, is the same hazard a
little earlier.

We still do not know why the freeze needs a card present at boot; presumably
only a path that runs with a card reaches one of the hooks early. The fix does
not depend on it.

## What survives a restart

Measured 2026-09-25 with open gate: its card, powered off with the switch, then
a card carrying only the USB shell. Every one of open gate's patches and all of
its cave code were still in memory — three restarts in a row — and open gate
recorded correctly before AutoRun had run.

| region | after the power switch |
|---|---|
| firmware image and cave `0xC0000000…0xC2F30800` | **kept**: patches, cave code, pointers and state words in the cave |
| firmware variables (BSS) `0xC3000000…0xC38D6FB0` | **cleared**: every observer and power-off callback registered with the firmware, and the pool pointer `0xC3757A7C` |
| heap / pool | **gone**: the allocator starts again; image data allocated at boot is lost |

What clears the image is not pinned down yet. Earlier measurements lost the heap
after 10–25 minutes off and after a battery pull; a USB cable can keep the camera
powered without its battery.

So, for a sup:

- **Registrations do not survive; register again on every load.** That is fine
  for the disarm here: it runs at power-off, when the registration still exists,
  and leaves a stock image behind.
- **Code in the image or the cave survives, and runs before AutoRun on the next
  warm boot** — whatever card is inserted, or none. Load code must not assume
  the words it patches are stock: the previous card, or an older build of the
  same sup, may still be there.
- **Anything that points into the pool must not be left behind.** Take it out at
  power-off, or check it before using it.

## The firmware's power-off callbacks

`XC_PowerOffMgr` (`src/library/PowerOffMgr/src/XC_PowerOffMgr.cpp`) keeps two
lists of callbacks and calls every one of them before it goes on to its own
shutdown steps. Read statically from `out/MAIN_c0000000.bin`:

| | |
|---|---|
| the manager | `0xC0023A98()` → the singleton |
| register | `0xC0024118(mgr, cb, forced)` → 1 registered, 0 list full |
| ordinary list | `mgr+0x0C`, 10 slots; the firmware fills 8 |
| forced list | `mgr+0x34`, 10 slots; the firmware fills 1 (the USB gadget) |
| the calls | `0xC0023C50` (ordinary), `0xC0023F38` (forced, reason 4) |
| each call | `obj->vtbl[+0xC](obj, reason)`, return value ignored |

Just before each call the manager logs the object's address through
`0xC001A048`. It stores the pointer and does not read through it, so no RTTI
is needed.

The smallest object that works is two words, with the vtable pointer aimed so
that `vtbl+0xC` lands on the object's second word:

```
X+0   X-8          vtable pointer:  (X-8)+0xC == X+4
X+4   routine      the slot the manager calls
```

Register in **both** lists. The USB gadget does, for the same reason.

## What the disarm routine must be

- **It lives in the cave, not in the pool.** It runs at power-off, so it
  must not depend on the memory it exists to stop you jumping into. Take its
  space from the cave allocator (`CAVE_BUMP` `0xC072E060`), copy it there, then
  `0xC000E91C()` → `0xC000EABC()` before anything can call it.
- **Immediates only.** No literal pool and no pc-relative load: it runs from a
  copy, and anything it reads must be in its own instructions. Each site's
  address and original word are `movw`/`movt` pairs.
- **It writes each site's original word back, then `0xC000E91C()` →
  `0xC000EABC()`.** Writing the original word to a site that was never armed is
  harmless, so it need not track which hooks are armed.
- **Register before arming, and do not arm if registration fails.** A hook must
  never be armed without its way out.
- **Keep the hook bodies safe to run anyway.** Firmware callbacks registered
  before yours run first, and some of them stop devices. The record-stop hook
  can still fire before your disarm runs, so a hook must behave correctly with
  no take in progress. That is exactly what cause 1 violated.

Reference implementation: `gyro/writer_core.inc.S`. `s_poff` allocates, copies
and registers; `poff_disarm` is the routine; `gsup_boot` calls `s_poff` before
the first `s_hook`. Tests: class `PowerOff` in `gyro/test_imu_stream.py`. They
decode the assembled routine and require it to restore exactly the sites and
words the build arms, reject any load instruction in it, and check the order.

## When you move state

Cause 1 is its own lesson. When state words move from one home to another,
carry their **initial values** with them, and test the value the code starts
with, not just where the words are. A value that meant "not yet" is easy to
lose, because nothing fails until the one path that depends on it runs.

## How to test for this

Recording tests do not reach it. For every card that arms a hook:

1. Boot the card and wait for the load to finish. **Do not record.**
2. Power off, wait a few seconds, then power on **with a card in the slot**.
   A blank card is enough.
3. Do this about ten times. The residual freeze was rare.

Also power off right after a take, and after switching still/cine.

## Next

This is gyro's own code today. The plan is to move it into the shared loader:
stage2 registers one power-off callback, and a shared `hook_arm(site, target)`
records each site's original word before writing the branch. Every sup, and
every module on a platform built on this loader, would then get the disarm
without writing it. Not implemented yet. It changes stage2, so every product
has to be verified on the camera again.

---

## 中文摘要

**規則:hook 的程式本體或落點不在韌體映像裡的,關機時必須拆掉。**
先向 `XC_PowerOffMgr` 註冊關機回呼,註冊成功才裝 hook。

- **症狀:** gyro v1.13 載入後正常關機,下次開機只要插著卡就凍結,空白卡也會。
- **原因一(確定):** 游標搬進 blob 時初值從 `0xFFFFFFFF`(還沒讀過)變成 0。錄影時看不出來。沒錄影就關機時,停止 hook 會觸發一次讀取,從位址 4 開始搬一整片記憶體。
- **原因二:** hook 本體從 cave 搬進了池。撥電源開關是暖開機,補過的映像(hook 位址、cave 跳板)會留到下次開機,但池指標在會被清零的 BSS、池的內容會交給別人 —— 下次開機 hook 一觸發,就跳進別人的記憶體。
- **什麼會跨重開保留:** 映像與 cave 保留(補丁、程式、指標);BSS 清零(向韌體註冊的 observer、關機回呼、池指標);堆積重來(圖像資料)。所以註冊每次載入都要重做,載入時不能假設要改的位址還是原廠值,指向池的東西不能留下。
- **註冊:** 管理器 `0xC0023A98()`,註冊函式 `0xC0024118(mgr, cb, forced)`。一般清單與強制清單各 10 格,兩張都要註冊。呼叫方式是 `obj->vtbl[+0xC](obj, reason)`。
- **拆除程式:** 住在 cave、只用立即數、寫回每個位址的原字,最後清 D/I 快取。
- **測法:** 開機、不錄影就關機,插卡再開機,重複約 10 次。
