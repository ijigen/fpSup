# First-frame +1 row: emulated MMIO diff of the record start (2026-11-03)

Status: offline only. I did not touch the camera, the USB shell or fpshd, and I changed no product code.
[C] = shown by code or by emulation (the firmware's own instructions ran under unicorn). [I] = inference.
Nothing here is a camera measurement.

## Run

```sh
cd projects/sensorlab-imx410/validation/20261103-first-frame-mmio-diff
python3 -B mmio_diff.py           # ~1 min; writes mmio-<case>.tsv, sensor-<case>.tsv, diff.txt, (stdout -> run.log)
python3 -B mmio_diff.py --geom    # the LV geometry object ContSet_Adr1 reads (FUN_c04370e8), per case
```

`mmio-<case>.tsv` records every write to 0x30000000–0x30FFFFFF made during the record start, in order, with its pc
and the function that made it. `diff.txt` holds the final value per focus register for every case, followed by
the full arm block of each case.

## What runs, what is stubbed

The harness reuses `apply/test_apply.DefectCam`. Our slots are built by ap.c's real `ap_init`/`ap_request` against
`out/MAIN_c0000000.bin`, so the firmware's own table lookups, its canvas gather and ap.c's hooks answer for modes
230/231.

**Runs for real** [C]:
- `SetImgMode_s` (standby mode 8 first, then the record mode), `FUN_c0314708`, `FUN_c03149b0` and `FUN_c0320008`.
- The receiver window (`FUN_c0635ed8`/`c0636048`), the clock switch, and the defect load.
- The BUFA selector `FUN_c031d988`, which calls IMX410 v37 and `FUN_c032d9a0` (RWZM/CRCT) with ap.c's `H_BINPATH`/`H_BINK` hooks live.
- All of `ContSet_Adr1` @C031BE60, called the way `FUN_c030cf98` calls it. The descriptor holds the record mode, fmt 0 and a dummy destination.
- The LV canvas comes from `FUN_c043a158(pid)`, and the geometry object from `FUN_c04370e8`.

**Harness fixes** (needed for correctness, not stubs):
- `out/MAIN_c0000000.bin` holds the wrong bytes above 0xC2EF6E00 (see `research/imaging-hw/notes/CRCT_PATH_SELECTOR_SOLVED.md` §1). `out/seg1_c2ef6e00.bin` is overlaid there.
- The descriptor's scalar fields and the `+0x114` reduction table (0xC0B5F770) are copied from the real descriptor at 0xC2F1E654, after `FUN_c0322ea0` has run. `test_apply`'s synthetic descriptor lacks them.
- The IMX410 object is built by its real constructor, `FUN_c03255b0`.

**Stubbed** (behaviour is identical for all cases):

| Category | What | Stub behaviour |
|---|---|---|
| Logging and asserts | log printf, assert | return 0 |
| Waits | VD wait `C01269A8`, ms sleep `C03705D8`, delay `C0000A08` | return immediately |
| Frame-counter loop | counters `C0125870`/`C0126010` | both return 0, so the VD-count loops exit at once |
| Semaphores | `C01F8E8C`/`C01F8CDC` | return 0 |
| Allocation | `operator new` for the geometry object | bump allocator; the unique_ptr destructor `C022EDB0` is a no-op |
| IMX debug print | `C0322B90` | return 0 |
| IMX ctor tail | `C0121D18` | return 0 |
| Lens branch | `C035F560` | return 0 |
| Gain lookup | `C03131E0` | return 0 (1.00×) |
| LV-side pipeline sizing | `FUN_c0313510` in `FUN_c03149b0` | return 1; it needs LV-manager route objects the harness does not build |

- Singletons whose constructors create RTOS objects are marked as already built: Corr, ImagCtrl and the LV manager.
- MMIO is plain RAM: a read returns the last write. The one exception is the clock-switch poll bit (0x30000000 bit 8), which is forced to "done".
- The arm-timing guard therefore always sees line counter 0. This is the same for every case.

**Sanity:**
- 12v2 differs from stock in 13 sensor writes. 14v2 differs from 12v2 in 40, so our rows are in use.
- Without `seg1`, the run died on build-time garbage, which is how the image bug above was found.
- **Positive controls:** both variants change the trace exactly where expected:
  - `+lvrwzm=rec` (canvas words patched in memory) moves the arm block onto the BUFA7 path.
  - `+start8` (a one-word code patch) makes the start write 0x30182004 = 8.

## Result

The table below holds the final values written during `ContSet_Adr1`. Full rows and the order of writes are in
`diff.txt`.

| | stock 106 (FHD) | stock UHD30 (ref.) | 12v2 / 14v2 (DC 4020) | 1×1 key 1 |
|---|---|---|---|---|
| route chosen by v37 [C] | **BUFA7** (rec RWZM == LV RWZM, 1600/1600) | BUFA1 (LV 1023 → clamped 0x400) | **BUFA1** | **BUFA1** |
| start | `FUN_c0631f08(2)`: **0x30182008 = 8**, plus **0x30182048 = 0xFFFFFEFF** (IRQ ack) and 0x3018231C = 0 | `FUN_c0631c08(1)`: 0x30182004 = 4 | **0x30182004 = 4**, no IRQ ack, no +1C reset | same as 12v2 |
| lines / line words / chunk | 1090 / 726 / 728 (1 chunk) | 2170 / 1446 / 728 (2) | 2010 / 1134 / 568 (2) | 2020 / 1134 / 568 (2) |
| RWZM h, v (phase<<16 \| ratio) | 0xE00640, 0xE00640 | 0xE00640, 0xE00640 | 0x800, **0x400** (v 1:1, phase 0) | 0x800, 0x800 |
| main hvbin bypass 0x300F0870 | 0 | 1 | 1 | 1 |
| crop x rem, 12-px misalign flag | x0=2/x1 rem 6; 0x30182324 bit20 = 1 | rem 4 | 0 / 0 | 0 / 0 |
| RX y window, TG H/V | 172..1880, tail 735, V−1 5397 | 354..3766 | 20..2030, 445, 5398 (14v2: 911/2637) | 40..4080, 445, 5398 |

Findings:
1. **Stock 106 does not record through BUFA1 at all** [C].
   - IMX410 v37 sends it to BUFA7 because the rec and LV RWZM are equal (profile 175: 1600/1600).
   - It programs crop 0x300F06E0, DMA 0x301823xx and destination 0x30182380, then starts with code 8 and acks all pending BUFA interrupt status.
   - Ours and stock UHD take BUFA1 with start code 4, which acks nothing.
   - `notes/FIRST_FRAME_DMA_START_RE.md` §2 assumed stock 106 uses BUFA1 "by v37's rules". That is contradicted here.
2. **The firmware's own stills code arms BUFA1 with 8 whenever RWZM or binning is active** [C].
   - In `PreExpos_s`/`AcqStartExp` (blk_c03 ≈16762/17337), `DAT_c343A738/739` are set when RWZM ≠ 1:1 or bin ≠ 1. The arm is then `FUN_c0631c08(2)` = 8, otherwise 4.
   - The movie path `ContSet_Adr1` hard-codes 4 for BUFA1 (site C031CAE0, `mov r0,#1`), although it only ever selects BUFA1 when RWZM is active.
3. **No MMIO write is made only for the first frame**, apart from the start itself [C].
   - Crop, line length and height are written once, before the start.
   - The per-frame path only changes the destination (previous note, consistent with this run).
4. **Within the BUFA1 group, the only per-case difference on the DMA side is the vertical RWZM** [C].
   - It is 1:1 (0x400, phase 0) in the ~100% group, 2:1 in 1×1 (~21%), and 1600 with phase 0xE0 in stock UHD.
   - Chunking (2 per line) and the start code are the same for all BUFA1 cases, stock UHD included.
5. **Side observation** [C, on the Python]: today's `quality.qualities` turns DC 6048×4040 → 3024×2014 into rec 3024×2008 with RWZM v 1027.
   - The live t02–t19 DNGs are 3024×2014, so that build had a different recipe.
   - The live-matching 4020 variant (3024×2010, v 1024) is used as the main 12v2 case. `12v2_dc4040` is kept for reference.

## Ranking: which differing write could put the first DMA one line late

1. **BUFA1 armed with code 4 instead of a VD/RWZM-synchronised code 8, with no IRQ-status ack.** [C writes, I effect]
   - This is the only start-path difference between stock 106 (0/9) and all our takes.
   - Stills uses 8 for RWZM paths, which suggests 4 means "arm now". If so, a fragment of the RWZM line in flight at arm time (an RWZM output FIFO tail) would be counted as line 0, which fits the 12- to 48-px row-0 fragments.
   - What 4 and 8 mean in hardware is not documented, and the emulation cannot show which line the DMA catches.
2. **Vertical RWZM exactly 1:1 (0x00000400) while horizontal is 2:1.** [C value, I effect]
   - Every input line produces an output line, so an output line is almost always in flight at a random arm time.
   - 2:1 halves that duty, which matches 1×2 ≈ 90–100% against 1×1 ≈ 21%.
   - This explains the rate spread inside the BUFA1 group but not stock 0/9 (stock is not on BUFA1).
3. Engine choice BUFA1 vs BUFA7 as such: a different DMA channel and crop block. [C] Inseparable from item 1 on stock FHD.
4. Two chunks per line. [C] This is shared with stock UHD, so it cannot be the discriminator unless stock UHD also fails.
5. The horizontal items (crop x remainder, 0x30182324 bit20, RX x pad) and the TG/RX y0 and tail. [C values] They cannot make a vertical +1 by themselves, and HMAX/frame time were already refuted. [I]

## Smallest change to our side (proposals, not applied)

- **A. Rows only: make our record canvas's LV RWZM equal to its rec RWZM.** That means profile words `+0x60`/`+0xD0` equal `+0x64`/`+0xD4`, for example 2048/1024.
  - Emulated (`12v2+lvrwzm=rec`) [C]: v37 then takes stock 106's branch. The arm block becomes the same functions in the same order as stock: BUFA7, start 8, IRQ ack, 0x3018231C = 0. Only geometry values differ.
  - Side effects it also produces [C]:
    - main hvbin bypass goes 1 → 0;
    - the CRCT kernel words 0x300F0800–08C4 and 0x300F2810–2850 switch to the stock pattern, so ap.c's binfilt result no longer lands;
    - 0x300F06D0 goes 3 → 4.
  - The LV-during-REC sizing (`FUN_c0313510`, stubbed here) also reads these words. The preview during REC and the image path need checking. [I]
- **B. Hook: keep BUFA1 but arm it with 8.**
  - Patch the word at C031CAE0 from `E3A00001` to `E3A00002`, only while our slot is live, so `FUN_c0631c08(2)` writes 0x30182004 = 8.
  - Emulated (`12v2+start8`) [C]: the only change in the trace is that one write.
  - This is the firmware's own stills convention for RWZM paths. It does not add BUFA7's IRQ ack. Whether 8 starts BUFA1 cleanly in the movie path is unknown. [I]

## Cheapest on-camera check (described only, not run)

1. **Stock UHD 29.97 CinemaDNG, 10 short takes, SensorLab not applied.** Measure the first frame with the existing `takes.py` row-shift/row-0 audit.
   - Stock UHD is emulated on the same BUFA1 path as ours: start 4, two chunks, hvbin bypass on, no IRQ ack. Only RWZM 1600 (phase 0xE0) and the crop differ.
   - If any stock UHD take shows +1: the BUFA1 movie arm (item 1) is the cause, and B or A is the fix.
   - If 0/10 (and especially 0/20): the cause is in our BUFA1 config, with vertical RWZM 1:1 first.
   - No sup and no code are needed.
2. If step 1 implicates the arm, run 12v2 ×10 with patch B, which is one word at C031CAE0 while our slot is live. Compare against the 15/18 baseline.

## Files

- `mmio_diff.py` is the harness. Its cases are `stock106`, `12v2`, `14v2`, `1x1_12`, `12v2_dc4040` and `stockUHD30`. Its variants are `12v2+lvrwzm=rec`, `1x1_12+lvrwzm=rec` and `12v2+start8`.
- `mmio-*.tsv` hold the ordered MMIO writes, and `sensor-*.tsv` the sensor-bus writes during the record start.
- `diff.txt` holds the focus table and the arm blocks. `run.log` is the per-case summary, including stub hit counts.

## Follow-up (same day): vertical RWZM 1:1

Live input: stock UHD records through BUFA1 with start code 4 and two chunks, and showed 0/29 shifted takes (`../20261103-stock-uhd-first-frame/`). The start code and the engine therefore do not cause the shift on their own, and patch B is dropped. The rates follow the vertical RWZM: 1:1 gives about 100%, 2:1 gives 21%, and 1.5625 gives 0/29.

New variants in `mmio_diff.py`:
- `12v2+v1023` and `12v2+v1025` patch the canvas rec RWZM v (`+0xD4`).
- `12v2_dc4040` is today's quality pick: RX 2014 rows, v 1027, output 2008 rows.

### What the firmware programs for the vertical scaler [C]

- **No 1:1-only write exists.**
  - `FUN_c032d9a0` clamps each ratio to at least 0x400 and enables the main RWZM (0x300F0900 = 1, 0x300F0004 bit 8) whenever either axis is not 0x400.
  - `FUN_c0633e60` then writes `ratio | phase<<16`, with `phase = 0x200 − f/2`, where `f = ratio&0x3FF` if that is > 0x200, else `0x400 − (ratio&0x3FF)`.
  - So 0x400 (1:1) and 0x800 (2:1) both get phase 0. 1600 gets 0xE0, 1025 gets 1, and 1027 gets 2.
  - The firmware writes no per-axis bypass bit, accumulator or line-counter preset.
- **The full 12v2 vs 1×1 trace differs only in geometry.** The differing registers are:
  - 0x300F090C, the vertical ratio: 0x400 vs 0x800;
  - the RX y window 0x30100024/0314, with y0 20 vs 40;
  - the 1/4-frame line interrupt 0x3010008C;
  - the front-end windows 0x300F0224/024C/026C and 0x300F2224/224C/226C;
  - the BUFA1 crop height 0x300F0684 and line count 0x30182210 (2010 vs 2020).

  hvbin bypass (0x300F0870 = 1) and 0x300F06D0 (= 3) are identical. 0x30182210 is derived from the crop alone and does not depend on the ratio.
- **Stock never runs the main RWZM with an axis at exactly 0x400.**
  - Every stock record profile in `raw-profiles.json` is isotropic: rec 1600/1600 (UHD, FHD) or 1500/1500 (pid 365).
  - Otherwise it is unity (1023, which the firmware clamps to 0x400 on both axes, so the RWZM is off and the BUFA0 path is used).
  - So an anisotropic RWZM with vertical exactly 1:1 has no stock precedent. [C for the table; the stills path takes its RWZM from the same geometry.]
- **The "1023 = unity" convention does not avoid 0x400.** Our 12v2 canvas already carries v = 1023. Both `FUN_c031d988` and `FUN_c032d9a0` clamp values ≤ 0x400 to 0x400, and `12v2+v1023` gives a trace identical to `12v2`. Unity is 0x400 in the register whatever the row says.
- The emulation cannot show what the hardware does internally at 1:1: line buffering, or when the first output line-valid fires. [I]

### Smallest row-side change that avoids exact 1:1 (not applied)

To keep the vertical ratio just above 0x400, the receiver must supply the extra rows.

- **Option 1: read 2 more sensor rows and set rec RWZM v to 1025.** RX 2012 rows → floor(2012·1024/1025) = 2010 output rows.
  - Emulated register diff: only 0x300F090C changes, from 0x00000400 to **0x00010401** (phase 1).
  - The rows must also be changed: the RX window y1 by +2, the TIM/REG window, and the defect-table window, all from core.
  - Do not change only `+0xD4`. `12v2+v1025` shows the crop and 0x30182210 stay at 2010 while the RWZM would emit only 2008 rows. BUFA1 would then wait for 2 lines that never come. [C values, I effect]
- **Option 2 (no new code): use today's quality pick at DC 6048×4040.** It gives RX 2014 rows, v 1027 (0x00020403, phase 2) and 3024×2008 output (`12v2_dc4040` in `diff.txt`).
  - It differs from the current 12v2 only in the vertical ratio, the RX/front-end y1 (+4 rows), the 1/4-frame interrupt, and crop/height 2008.
- **What either option alters:** a real vertical resample instead of a pass-through. [I]
  - With v 1025, rows drift by up to about 2 lines over the frame. The interpolation weights stay near 0/1, so there is mild softening that varies down the frame.
  - 1027 drifts about 6 lines.
  - Output height becomes 2008 under option 2.
  - The aspect ratio and DNG size follow the rows. Stock's 1600 shows the RWZM handles Bayer data.

### Cheapest camera check (describe only)

1. Record 12v2 ×10 with the current build at DC 6048×4040, where today's core gives 3024×2008 with v 1027. Run the `takes.py` row-0/dy audit.
   - First confirm the DNGs are 2008 rows, which proves the 0x403 config was live.
   - A rate well below the 15/18 (≈ 100%) baseline means vertical exactly 1:1 is the trigger. If it does not drop, the cause is upstream of the ratio value, for example the sensor's 1×2 readout. No new code is needed.
2. If step 1 helps, build option 1 (RX +2 rows, v 1025) and confirm 2010-row output and the same rate.

## 2026-11-04：接收端／前端比對（原廠 UHD、原廠 FHD 106 vs 我們的 BUFA1 配方）

`rx_diff.py` 現在跑不動：v0.7.27 之後的 arm hook 會寫標記到未映射的目的位址。比對改用上次存下的 `mmio-*.tsv`（12v2 是 DC 4020、1x1_12 是 key 1）。原廠兩種一致、我們三種一致、兩邊不同的：

| 暫存器 | 原廠 UHD | 原廠 106 | 我們（12v2／1×1） | 來源 |
|---|---|---|---|---|
| `0x3010000C`（接收端 x 起點：`(x0/12) << 16 \| 字數`） | `0x1FA`（x0/12 = 0） | `0xFD`（0） | **`0x101F9`（x0/12 = 1）** | `FUN_c0635ed8`：x0 = TIM +4，字數 = (寬 − x0%12)/12 |
| `0x300F10C0` bits 16–19（x0 % 12） | 8 | 4 | 4 | 同上 |
| `0x30100024`（接收端 y 範圍） | 354–3766 | 172–1880 | **20–2030（1×1：40–4080）** | 同上，TIM +8／+10 |
| `0x300F020C` 低半、`0x300F021C`、`0x300F0244/264/284/2A4` | `4444`、8、`0xC0` | `4444`、4、`0xC0` | **0、0、0** | `FUN_c0632108`、`FUN_c0635ed8` |
| `0x30100004` 低半 | `0x2DE` | `0x2DE` | `0x1BC` | `FUN_c0126128` |
| `0x30100020` | `0x1515…` | `0x1515…` | `0x1516…` | `FUN_c01265c0` |

- **x 起點**：我們的 TIM x0 = 16，接收端會先跳過 1 個 12 px 的字（x0/12 = 1）。原廠一律是 0（x0 = 8／4）。壞幀第 0 列開頭正是「12 px 一組重複 4 次」，和這個以 12 px 字為單位的起點邏輯對得上 [推]。
- **y 起點**：我們的接收窗從第 20 列開始（1×1 是 40），原廠是 172／354。錯列率剛好跟 y0 反向排列：20 ≈ 100 %、40 21 %、172／354 0 % [推，相關不等於因果]。
- 前端 `0x300F0244…`（原廠 0xC0、我們 0）的含義還沒查。
