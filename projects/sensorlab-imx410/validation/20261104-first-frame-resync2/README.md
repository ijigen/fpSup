# v0.7.29test: resync at the switch a REC start really makes (offline, 2026-11-04)

Status: **offline only**. I did not touch the camera, the USB shell or fpshd. The build is not deployed.
[C] = code or emulation of the real image. [I] = inference.

## Why v0.7.28test never ran it

In the v0.7.28test live run (`../20261104-first-frame-resync/`), `resync_calls` and `resync_skips` stayed 0 on all
10 takes, so the C031BF88 hook was never reached.

**`SetImgMode_s` (C0313400) has exactly two callers in the image** [C, decomp plus a scan of every BL]:

1. **ContSet_Adr1, C031BF88.** It switches only when the record mode differs from the current one, and that was the
   v0.7.28 hook.
2. **The image controller task (ImgCtrl, prio 7), C030D168.** It handles message 1 in the loop of `FUN_c030d0c0`, as
   `SetImgMode_s(FUN_c03133a0(), msg[+0x1BC])`.
   - `FUN_c030ce00(ctl, mode)` posts that message and waits for its event.
   - Every other mode switch goes through it, for example `setChangeSensorMode` C022DF68, which stops the LV first.

Live, the REC-start switch (standby 8 → 231) therefore went through the image controller. ContSet_Adr1 then found the
mode already current and skipped its own call.

mmio_diff's `record_start` had forced the current mode back to standby, which is why the v0.7.28 emulation took the
ContSet branch.

## What changed (on top of v0.7.28test; trace, sentinel and resync body unchanged)

- **New hook `H_RESYNC2` at C030D168** (`bl SetImgMode_s`; `ldr r1,[r4,#0x1bc]` is the mode).
  - It shares the handler with C031BF88. After the switch, and only for the live slot's mode, it runs the same native
    sequence: `v27(1)`, VD, `v27(0)`, VD.
- **Context.** This runs in the ImgCtrl task, the same task in which the native long-exposure path runs v27
  (`FUN_c031d0e0`, message 1/2 of the same loop) [C].
  - The poster waits for the event, which is set after our return. So the REC-start path, and with it ContSet_Adr1
    and the BUFA1 arm, continues only after the resync.
  - ImgCtrl's other messages (FrameExpos_s, Cont) wait about 50–80 ms during it, once per take. [I]
- **New status counters.**
  - `resync_seen` counts every mode switch through either site, so a live miss is now visible.
  - `resync_ours` counts the switches into the live slot's mode; it equals `resync_calls + resync_skips`.
  - `sq_test 17` is now 43 words.
- **Assumption.** Standby runs stock mode 8 (FIRST_FRAME_PURPLE, APPLY_DESIGN §14 correction), so the only switch into
  our mode is the REC start. [D] If standby ever switched into our id, the resync would also run there; check
  `resync_ours` against the number of takes.

## Tests [C] (`apply/test_apply.py ResyncTests`, 6 tests)

- **Default order, as on the camera.** Standby is set to mode 8. Then the image controller's message-1 code runs
  (C030D160–C030D16C, the real `SetImgMode_s`, the mode taken from the message), and ContSet_Adr1 runs without
  forcing the mode back.
  - For 12v2 and 1×1: the C030D168 site is hit and **C031BF88 is not**, as live.
  - The exact native sequence runs once, after `0011=1` and before the BUFA1 arm and start.
  - Counters: `resync_seen`/`ours`/`calls` = 1/1/1.
- **Stock** (UHD30, FHD106, and UHD30 with a slot live): `seen` 1, `ours` 0, no resync, nothing armed.
- **ContSet's own switch.** If it is ever taken (`contset_switch=True`), the sequence runs once there too.
- **The 15000 µs guard** skips without a call.
- **Mutants.** #111–120, 10 for ResyncTests, all caught. New ones:
  - the C030D168 site moved;
  - `resync_seen` not counted;
  - `resync_ours` not counted;
  - the resync run before the switch.
- **Runs.**
  - `test_apply` 80/80.
  - `tools/test.py fast`: PASS.
  - Settings-migration + `test_slqs` Build / ApplyUnit: 15/15.
  - `tools/test.py mutants --only apply`: 117 of 121 caught (`tools/test-logs/mutants-20261104-000617/`). The four
    failures are the known pre-existing "mutant text not found" entries (#48, 54, 56, 61).

## Build

- `default-build/fpSup/SensorLab-IMX410_v0.7.29test.BIN`: 189,036 B, sha256
  `b88f616dd4ed1a1395e9913f5b389cb259c0cef3abccaf28fe4a40f4a1d21b61`, block 573,632 B.
- It is also in `qs/test-fixtures/settings-migration/frozen/`, with a README.txt entry.

## Live test

The plan is the same as `../20261104-first-frame-resync/README.md`: 12v2 ×10 and 12h2 ×10, each take read with
`read_trace.py` and `takes.py`.

Check after the first take:
- `resync_seen` ≥ 1 and `resync_ours` = 1 per take;
- `resync_calls` +1 per take, with `resync_us` around 50–80 ms.

Then compare the shift rate with v0.7.27/28 (12v2 9–10/10). Also check A/V alignment, and that 0000 bit 2 stays
cleared after the first resync.

## 上機（2026-11-04）

部署 v0.7.29test（卡上設定版 `card-settings-build/`，189,036 B，讀回比對相同）、重開、MENU 進出（離開後等 6 s 再送指令）。配方 12v2（key 10，OG 6048×4040 → 3024×2020，29.97）。

| take | clip | 幀數 | 第 1 幀 dy | resync |
|---|---|---|---|---|
| t01 | A001_166 | 41 | 1 | calls 1，63.3 ms；trace：capture side |
| t02–t10 | A001_167–175 | 46–51 | 1,1,0,1,1,0,1,1,1 | calls 2…10，每次 62.5–63.4 ms，skips 0 |

- **重新同步每段都執行了**（`resync_ours` = `resync_calls`，`resync_seen` 也算到待機的切換）。
- **錯列 8/10**，v0.7.28／0.7.27 的基準是 9/10、≈100 %。原廠的「暫停 → 恢復 → 重新同步」沒有改善第一幀錯列。
- 代價：開錄晚約 63 ms，一段 2 s 的錄影少 2–3 幀（46–47，原本 48–49）。影音對齊、`0000` bit 2 清除後的原廠格式都沒有測。
- 結論：選項 B 無效。錯列發生在擷取端（v0.7.27 trace），但和感光元件／接收端的完整暫停恢復無關。
