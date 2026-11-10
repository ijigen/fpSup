# v0.7.27test: first-frame trace, read-only (offline, 2026-11-04)

Status: **offline only**. I did not touch the camera, the USB shell or fpshd. The build is not deployed.
This is step 1 of `notes/FIRST_FRAME_SENSOR_RESET.md` §5. It answers one question: is frame 1 already shifted when
BUFA1 reports it complete, or does it go wrong between the completion and the writer?
[C] = code or emulation of the real image. [I] = inference.

## What changed against v0.7.26test

- **The drop and the repair are both removed.** No frame is dropped, moved or written.
- **The per-take sentinel stays.** At C031C948 it writes 16 xorshift32 words into raster row 0's last 64 B, before
  the BUFA1 start.
  - It goes through the uncached alias, after one full `C000E91C` D-clean.
  - **A shifted frame 1 therefore carries the sentinel in row 0's last 64 B, where it used to carry stale DRAM.** That
    region is inside the DNG raster and may fall inside DefaultCrop, where it shows as 42 noise pixels at the end of
    row 0.
  - Normal frames overwrite it.
- **Status (`sq_test 17`, AP_ABI 3, 38 words).** The last 8 words are `first_arms first_skips first_checks
  first_intact first_ok first_miss trace_n trace_lost`.
  - `first_intact` counts frame-1 arrivals at the writer with the sentinel still in place, which means shifted.
- **AP_MEM_BYTES** goes from 0x36000 to 0x37000, and STATE_RESERVE follows.
- **47 apply hooks, 48 claims** with the clock gate. The new hook is `H_FFDONE`.

## Hook sites and contexts [C]

| record | site | context | what it may do |
|---|---|---|---|
| arm (kind 1) | C031C948 `blx FUN_c0631b98(dest)` in ContSet_Adr1's BUFA1 branch, before the start `FUN_c0631c08(1)` at C031CAE0 | REC-start task | Writes the sentinel, calls `C000E91C` and the tick, then records. Only when the descriptor's mode is the live slot's id. |
| done (kind 2) | **C031BCA0, the entry of `FUN_c031bca0`**, BUFA1's completion callback. ContSet_Adr1 sets it at C031C884 (`local_b4` → `FUN_c0630d30` → `_DAT_c37cf8fc`). The BUFA1 IRQ handler `FUN_c0630d60` calls it with the completed raster from 0x30182280 (+0x40000000, uncached). This is the earliest point that knows the address. | IRQ | Plain loads and stores into `struct ap` only. No firmware call, no cache operation, no tick call. Tested by emulation: every executed instruction is in the unit, the veneers or the cave, and every write is in `struct ap` or the stack. |
| write (kind 3) | C038BDB4, the frame lookup in `FUN_c038bd98` | SRecRaw (prio 15) | Runs before `cineCapture`, the header DMA C038C5F8 and the enqueue C038BFF0 (Lossless). The lookup's answer is passed on unchanged. |

Timing at the IRQ site comes from the two words `C002B4E0` reads: the epoch `0xC30781A4` and timer 5's count
`[*0xC30337F0 + 0x54]`. The site does not mask IRQs and does not apply the pending-bit correction.
`tick_us ≈ epoch·1e6 + raw/12`, mod 2³², which can be off by ±1 s right at a wrap. The task sites also record
`ap_now_us()`.

Registers read, each read by the firmware itself [C, decomp]:

- TG: 0x30100588 (frame counter), 0x30100590 (line counter), 0x3010058C (bit 12 = frame active).
- BUFA1: 0x30182210, 0x30182214, 0x30182218, 0x30182280, 0x30182048.
- 0x301821E8, which the firmware reads in `blk_c01.c` (`&7`, `>>16 & 7`).
- **The rest of 0x301821E0–F8 is not read.** No firmware read of it was found, so those registers are not proven
  read-safe.

At the arm, 0x30182214 still holds the *previous* line-word value, because `FUN_c0630e90` writes it after the
destination. Use the done records, or `rows` / `row` in the header.

## Ring layout: `struct ap_trace`, little-endian words

Header (16 words):

| word | field |
|---|---|
| 0 | magic `0x52544653` ("SFTR") |
| 1 | ver 1 |
| 2 | rec_words 56 |
| 3 | nmax 12 |
| 4 | n, the records written this take |
| 5 | lost, refused because the ring was full |
| 6 | take, the takes armed since boot |
| 7 | live |
| 8 | seed, the take's sentinel seed |
| 9 | row, bytes per raster row |
| 10 | rows |
| 11 | id, the mode |
| 12 | done, completions recorded |
| 13 | writes, writer arrivals recorded |
| 14–15 | pad |

Record *i*, at word `16 + 56·i`:

| word | field |
|---|---|
| 0 | kind: 1 arm, 2 done, 3 write |
| 1 | seq |
| 2 | epoch |
| 3 | raw, timer 5 |
| 4 | us: tick_us at the task sites, 0 at the IRQ site |
| 5 | 0x30100588 |
| 6 | 0x30100590 |
| 7 | 0x3010058C |
| 8 | ras, the raster address as the site has it |
| 9–12 | arm: {mode, 0x30182210, 0x30182214, 0x30182218}<br>done: {0x301821E8, 0x30182280, n, 0x30182048}<br>write: {frame id (+0x10FC), frame, n, 0} |
| 13 | ok: 1 = the digest was read |
| 14–21 | row 0, first 32 B |
| 22–37 | row 0, last 64 B (the sentinel's place) |
| 38–45 | row 1, first 32 B |
| 46–53 | last row, last 32 B |
| 54–55 | pad |

All digests are read through the **uncached** alias (0x4…).

A take produces at most 1 arm, 4 done and 4 write records, 9 in all. Tracing starts at the arm (a SensorLab-mode take
only) and stops once 4 + 4 are recorded. The next take's arm, or any commit, ends it.

## Reading it on the camera (after a take, idle only)

```sh
cd projects/sensorlab-imx410/validation/20261104-first-frame-trace
python3 -B read_trace.py --load-log RUN/LOAD-current.LOG --build default-build/build-0.7.27test.json --out RUN/trace.jsonl
```

- The script reuses `tools/live/dc_probe.py`'s `Cam` and `idle`. It calls `sq_test(33, 0)` to get the address, then
  reads 16 + 12·56 words with `mem get`. `sq_test(33, 1)` gives the record count.
- It refuses unless `is_recording -> 0`. Do not use it during recording or playback.
- To decode a dump offline: `python3 -B read_trace.py --words dump.json`.
- `sample-emulated-shifted.json` is an emulated shifted take, for trying the decoder.

## Interpreting it (frame 1 = the first done and the first write record)

| done record | write record | means |
|---|---|---|
| row 0 tail = sentinel (`frame1_shifted_at_completion`) | the same | **Capture side.** BUFA1 completed frame 1 without writing row 0. Look at the receiver, crop and DMA start, or the sensor (§5 step 2). |
| row 0 tail overwritten, digests equal | the same | Normal take. Compare its TG frame and line counters with a shifted one's. |
| row 0 tail overwritten | sentinel back, or a digest changed | **Hand-off / cache side.** Something rewrote the raster between the IRQ and SRecRaw: a cache writeback, or buffer reuse. |

Also compare:

- `r2280_dest` against `ras`;
- the done / write raster addresses (`frame1_raster_same`);
- the time between the arm and done 1, and the TG counters at each point;
- the take's DNG: does `head1` equal the DNG's row 1? Do the last-row bytes match?

## Tests [C] (`apply/test_apply.py FirstFrameTests`, 11 tests)

- **Order and content.** The ring fills arm → (done, write) × 4 for frames 1–4; a fifth frame is not recorded.
  Completions running ahead of the writer are capped at 4 each.
- **Digest addresses.** Digests equal the memory, and the reads touch exactly the intended uncached addresses. The only
  other reads are the writer-side 64-byte sentinel check. Nothing goes through the cached alias.
- **Read-only.** Rasters are unchanged except the arm's sentinel, all frames are enqueued, and there is no cache pass
  after the arm.
- **IRQ site.** No code outside the unit, veneers and cave runs, and no write lands outside `struct ap` and the stack.
- **Lifetime.** The trace resets per take, and an unfinished trace never spills into a stock-mode take. A commit ends
  tracing.
- **Formats.** True-14 lines are handled (format 1, 5292 B/row). A normal frame shows the overwritten sentinel.
- **Stock.** Stock modes are never armed, traced or touched, with or without a live slot.
- **Full REC start.** The `mmio_diff` REC start arms before `0x30182004 = 4`, and the armed geometry equals BUFA1's.
- **Site words** and the callback registration at C031C884.
- **sq_test 33** (`qs/test_slqs.py ApplyUnit`): it returns the trace in `ap_mem`; it is empty before any take, and
  reading it changes nothing.

Mutation: all 20 FirstFrameTests mutants are caught (MUTANTS #91–110). Five survived the first run and are now caught
after new tests: 14-bit format, fixed seed, the done cap, the writer `live` check, and the arm's trace reset.

Runs:

- `test_apply` 75/75.
- `tools/test.py fast`: PASS.
- `test_settings_migration` 8/8.
- `test_slqs` Build + ApplyUnit.
- `tools/test.py mutants --only apply`: 107 of 111 caught (`tools/test-logs/mutants-20261103-230347/`). The four
  failures are the known pre-existing "mutant text not found" entries (#48, 54, 56, 61), unrelated to this change.

`read_trace.py` decodes the emulated traces as "capture side" for the shifted take and "normal" for the normal one.

## Build

- `default-build/fpSup/SensorLab-IMX410_v0.7.27test.BIN`: 188,732 B, sha256
  `0639af10d61dc1ecc33c4d8a5d06e5b3d7cf6157e54fe7cd6dab0bd508d2e566`, block 573,312 B.
- It is also in `qs/test-fixtures/settings-migration/frozen/`, with a README.txt entry.

## Not verified (needs the camera)

- That `FUN_c0630d60` runs in true IRQ mode and that its stack absorbs the hook. The veneer pushes 56 B, the C path is
  shallow, and the native chain below it (observer → `FUN_c037a590`) is much deeper. [I]
- That reading 0x301821E8, 0x30182048 and the TG counters from the IRQ has no side effects. The firmware reads each of
  them, but not necessarily from this context. [I]
- The timer-word arithmetic on the camera.
- Whether frame 1's done record really comes before its write record in time. The task priorities say yes. [I]

## 上機（2026-11-04）

部署 v0.7.27test（卡上設定版 `card-settings-build/`，188,732 B，讀回比對相同）、重開、MENU 進出 commit。`RUN/`：`takes.py`（DNG 位移）、`read_trace.py` → `RUN/trace.jsonl`。讀紀錄改成每次 64 字（一次 688 字的 `mem get` 回覆不完整）。

| take | clip | 配方 | DNG 第 1 幀 | trace 判讀 | 開錄 arm → 第 1 次完成 |
|---|---|---|---|---|---|
| t01 | A001_150 | 2×2（key 4） | 正常 | 沒有紀錄：`first_arms = 0`，這段沒經過 BUFA1 的 arm 點 | — |
| t02 | A001_151 | 12h2（key 12，Bei 選的「12b 2x1」） | **dy 1** | **capture side**：DMA 完成時第 0 列尾端標記還在；完成到交寫卡 133 µs，內容沒變 | 53.6 ms |
| t03–t06 | A001_152–155 | 12h2 | 正常 ×4 | normal ×4 | 53.4–54.0 ms |

- **trace 判讀 5/5 和 DNG 位移一致**。錯列在 BUFA1 回報完成那一刻就已經存在，後段交接（寫卡、Lossless、快取）沒有改變內容 → 排除後段，問題在擷取端。
- **SensorLab 2×2 不走 BUFA1**（arm hook 從沒觸發，三個 hook 讀回都已安裝）。之前「2×2 和 12v2 同一條 DMA、0/10」的推論要更正：2×2 不能當 BUFA1 對照；BUFA1 對照只有原廠 UHD 0/29。
- **水平合併 12h2 也會錯**（1/5），所以不是垂直合併獨有。
- 開錄 arm 到第 1 次完成都是 53.4–54.0 ms（≈ 1.6 幀），之後每 33.37 ms 一次；錯列那段的時間不突出。TG 計數器欄位（0x30100588／590）讀出 `tg_frame = 0`、`tg_line` 是很大的值，看起來不是幀／列計數，**不能用**。
  - **更正（11-04，`../20261104-resync-review/`）**：`0x30100590` 要照原廠 `C0125770` 解成 `(raw >> 16) & 0x3FFF`，是有效的列計數。錯列首幀完成時讀 2120、正常 4161→4162 一類差 1 列，是啟動相位線索，詳見 `notes/FIRST_FRAME_SENSOR_RESET.md` 11-04 節。
- 相機全程正常，hook 在 IRQ 裡沒出事。
