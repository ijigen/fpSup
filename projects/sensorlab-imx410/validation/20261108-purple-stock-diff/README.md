# First-frame purple: SensorLab "UHD 29.97 12b 1×1" against stock UHD 29.97 CinemaDNG, word by word (2026-11-08, offline)

Status: **offline only**. No camera, USB or card was touched. [C] = shown by the firmware's own code running under unicorn
against `out/MAIN_c0000000.bin` (ap.c's hooks live, built as the product builds it, `AP_RESYNC 0`). [I] = inference.
[D] = archived live data.

## 0. Two corrections to the brief of this task

1. **"ContSet_Adr1 took 39.8 ms, so REC start ran no SetImgMode_s" does not follow.** [C, D]
   A CinemaDNG REC start never switches the mode inside ContSet_Adr1, in stock or in SensorLab. The switch is
   ImgCtrl message 1 (`FUN_c030d0c0` → `SetImgMode_s` at C030D168), posted and waited for **before** `FUN_c0378a50`
   reaches C0379180 (`validation/20261104-first-frame-resync2`: live, the C031BF88 site was never reached, C030D168 was
   reached every take). ContSet_Adr1 then finds the mode current. So t2 − t1 ≈ one frame is the same with or without a
   switch.
2. **Whether SensorLab standby runs our mode is not known for 0.0.3test.**
   - The 11-03 bus logs (SensorLab v0.7.2x, 12v2) showed the sensor in **mode 8** in standby and a full 8 → ours mode set
     plus `0011` 0→1 at every REC start, exactly like stock 8 → 7. [D]
   - The code would give our id in standby only if the MOV answer is what the sensor runs. Our MOV answer is
     `{1, spid, our id}` whenever `sok = 1` (it is 1 for both UHD recipes **and** for 12v2), yet 12v2 still ran mode 8.
     So the MOV answer is probably not what picks the standby sensor mode. [I]
   - The hook entry being phase-locked at TG line ≈ 287 fits a SetImgMode_s that restarted the TG just before. [I]
   - The PURPLE build's ring now records every SetImgMode_s (from, to, when) and the current mode at the hook entry, so
     the first take answers this. The 0.0.3test card already counts them too: `sq_test 17` words `resync_seen` (41) and
     `resync_ours` (42).

## 1. The two recipes

| | SensorLab (core defaultPick at the stated rate) | stock (TAB3, 12-bit) |
|---|---|---|
| UHD 29.97 12b 1×1 (Bei) | DC 6048×3402 → RES 3840×2160, key 1 `12` (AD 12), mh = mv = 1, hbin = vbin = 1, HMAX 445, VMAX 5399, 29.97 | `UHD30`: pid 171, **mode 7**, HMAX 445, VMAX 5398, TG tail 735 |
| UHD 25p sweep recipe | the same DC/RES, key 3 `12fastW` (**AD 11**), HMAX 418, VMAX 6890, 25 | `UHD25`: pid 179, **mode 123**, HMAX 450, VMAX 6400 |
| virtual ids | record pid 74/75, mode 230/231; standby pid 76/77 | standby MOV: pid 5, mode 8 |

`stock_diff.py` runs both pairs. Machine-readable result: `diff.json`; every MMIO write in order: `mmio-<case>.tsv`.

## 2. The differences (UHD 29.97 12b 1×1 vs stock UHD 29.97), most suspicious first

### 2.1 Vertical readout: the sensor windows, the receiver starts at line 40 [C]

| what | stock mode 7 | SensorLab | where |
|---|---|---|---|
| sensor vertical window (v32's registers) | `0003=0`, `0022..0025=0`: full height | `0003=1`, `0022/23=0x179`, `0024/25=0x6A5`: 3402 rows | REG row words 2, 6–9 |
| RX / TG y window (`0x30100024`, `0x30100314`) | **354 .. 3766** (3412 lines) | **40 .. 3442** (3402 lines) | TIM +0x0C / +0x10 |
| front-end y (`0x300F0224`, `0x300F2224`) | `0x0160_0EB8` | `0x0026_0D74` | R38 +8 / +0xC, R28 |
| META (`0x77`) | 6064 × 3412 | 6048 × 3402 | META +4 / +8; canvas +F4 / F8 |
| 1/4-frame line IRQ (`0x3010008C`) | `0x04B7_0000` | `0x037A_0000` | from TIM |

- **Everything else in the sensor table is identical.** With the product build, the sensor writes of the whole REC start
  differ only in these five registers, plus `0005` (SHS, AE) and `00D1` (toggles per mode set). Same HMAX, VMAX, AD,
  clocks. [C]
- **The archived rates follow the RX y0.** y0 20 (12v2, 1×2) ≈ 90–100 %; y0 40 (1×1 key 1: 3/14; UHD 25p: 13/27;
  Bei's UHD 29.97 1×1: purple); stock y0 172 (FHD 106) 0/9 and 354 (UHD) 0/29. Correlation only. [D, I]
- Stock UHD reads the full sensor height and lets the receiver skip 354 lines. Ours windows the sensor, so the
  first valid line arrives about 40 TG lines after the frame start. A start-up line edge near the receiver's y0 would
  explain a partial row 0 that BUFA1 counts as a line (the "row 0 partly written, +1 row" evidence). [I]

### 2.2 Horizontal start, width [C]

| what | stock | SensorLab |
|---|---|---|
| RX x window `0x3010000C` (`x0/12 << 16 \| words`) | `0x01FA` (x0/12 = 0) | `0x1_01F9` (x0/12 = **1**) |
| TIM x0 (+8 hi) / pad `0x300F021C` | 8 / 8 | 16 / 0 |
| `0x300F10C0` (x0 % 12) | 8 | 4 |
| front-end x words (`0x300F0220/48/58/68/78/98/B8`, `0x300F1084`, mirrors `0x300F22xx`, `0x300F3084`) | `0x1FB`, `0x8_0008` | `0x1FA`, `0x4_0004` |

The x start was already tested live (v0.7.30, no effect, `FIRST_FRAME_SENSOR_RESET.md`). Lower priority.

### 2.3 Record raster and RWZM [C]

| what | stock (pid 171) | SensorLab (pid 75) |
|---|---|---|
| canvas raster +00 / +04, +DC / +E4 | 3856 × 2170 | 3840 × 2160 |
| crop +24 / +2C | 3840 × 2160 | 3824 × 2150 |
| rec RWZM +64 / +D4 → `0x300F0908/090C` | 1600 / 1600 → `0x00E0_0640` (phase 0xE0) | 1612 / 1612 → `0x00DA_064C` (phase 0xDA) |
| BUFA1 crop `0x300F0680/684/68C` | `0x1_0143`, `0x6_0880`, rem 4 | `0x0140`, `0x0870`, rem 0 |
| BUFA1 lines / line words / chunk (`0x30182210/14/18`) | 2170 / 1446 / 728 | 2160 / 1440 / 720 |
| LV src +10 / +28 / +E0 | 1135 / 1125 / 1135 | 1134 / 1124 / 1134 |

Both are anisotropic-free (h = v), both use BUFA1 with start code 4 and two chunks per line. The ContSet_Adr1 write
sequence is the same 66 writes by the same functions in the same order; only these values differ. [C]

### 2.4 Mode switch and profile class [C]

- `FUN_c03a66b0` (the LV mode decision that posts ImgCtrl message 1) **skips** the switch only when the mode is already
  current, the TG runs, and the profile's class flags (`FUN_c043a1c8`, holder +0x168) have bits 3/4/5 clear.
  - Stock pid 171 has flags **8** (bit 3: pids 131–190, 417–434), so stock **always** re-runs SetImgMode_s there.
  - Our pids 74/75 have flags 0. Standby 5 has 2, ours 76/77 have 0.
  - So if SensorLab standby ever runs our id, REC start does no mode set at all; stock always does one.
- The register image at BUFA1 start is the same in both scenarios ("standby 8 then switch" vs "standby already ours"),
  except `0x30100060`. That one is an emulation artefact of a first mode set from power-on. A real "no switch" leaves
  the sensor streaming from standby instead of a fresh `0011` 0→1 restart, which emulation cannot show. [C, I]

### 2.5 Standby [C]

| | stock | SensorLab |
|---|---|---|
| MOV answer | `{1, 5, 8}` | `{1, 77, 231}` (`sok` 1) |
| standby canvas (pid 5 vs 77) | rate 60, META 2016×1344, LV RWZM 3.0, +10 = 1344 | rate 30, META 6048×3402, LV RWZM 1.0, +10 = 1134, +38/58/C4 differ |

### 2.6 Defect table [C]

- R68: stock mode 7 loads flash table id 7 directly.
- Ours points at id 0x61 with the conversion flag (+8 = 1, window +10..+1C) and our converted table.
- `0x300F0D84` holds the table's DMA address >> 2. It differs; this is not a geometry difference.

### 2.7 TG H tail [C]

- `0x30100004` low half: stock mode 7 has 0x2DE (tail 735), ours 0x1BC (445).
- Stock mode 123 (UHD 25) has its tail equal to HMAX, as ours does. So this is not a stock-wide property. Low priority.
- VMAX: `0x30100020` = 0x1515 (stock, 5398) against 0x1516 (ours, 5399). That is one line in 5399: the frame time
  differs by 0.02 %.

The UHD 25p sweep recipe differs from stock 123 in the same way (sections 2.1–2.6). It also differs in 80 sensor
timing / AD registers, because it is the 11-bit `12fastW` readout. `diff.json` → `stockUHD25`.

**Ranking:**
1. 2.1, the sensor vertical window with RX y0 = 40. It is the only difference that tracks the archived rates.
2. 2.4, no mode set at REC start, if standby runs our id.
3. 2.3, raster and RWZM 1612 / phase.
4. 2.2, x start (already tested).
5. 2.6 and 2.7.

## 3. PURPLE TEST build: toggles

`apply/ap.c` under `#ifdef AP_PURPLE_TEST` (which requires `AP_REC_DELAY_TEST`). Build:
`cd qs && python3 -B build_slqs.py --purple-test --out <dir named *purple*>`.
- It is the REC-delay build plus the toggles. The delay word N and its sleep are unchanged.
- **The product and REC-delay builds are byte-identical** with or without this change. They were built from one slqs.c
  snapshot with the old and the new ap.c: product `c695ef44…`, REC-delay `0c472537…`, both identical.
  `test_purple` also strips every PURPLE block and compares the ARM images.

Host words: block + `purple.*_off` in the build json. **They take effect at the next commit only**: the LV is stopped
and the slot is not live. They never change while recording, and nothing depends on busy(). To re-commit, call
`sq_test 30 1` and then `sq_test 30 0` (stock, then ours again, each with the commit's own LV stop / start).

| bit | name | what the next committed slot does | refused (counted in `refused`) when |
|---|---|---|---|
| 0 | `TWIN` | The standby MOV answer uses a twin id (id + 2 = 232/233). Every lookup answers the twin with the slot's own rows, so the REC start switches twin → ours through the firmware's own ImgCtrl path, as stock does 8 → 7. Only has an effect if the sensor in standby runs the MOV answer (§0.2). | `SBSTOCK` also set |
| 1 | `NOWIN` | Our rows, with the sensor's vertical window off: REG words of `0003`, `0022..0025` = 0, the stock values. RX / TG still start at y0 40, so the band moves to the sensor top. For UHD 29.97 1×1 the **sensor table is then exactly stock mode 7's** [C]. | not 3840×2160; the REG row not windowed; frame time < stock 29.97's; `ROWS` set |
| 2 | `ROWS` | All eight mode rows (TIM META R28 R38 R14 R68 REG R10) are stock mode `smode`'s, passed to the firmware's own scans. So are the canvas META (+F4 / F8) and the defect table (stock load). The sensor, RX, TG and front end are stock; our canvas output (3840×2160 @ 1612) stays. | `smode` ∉ {7, 101, 123, 151}; frame time differs > 1 %; output not covered; not 3840×2160 |
| 3 | `RWZM` | The record canvas keeps the base row's (pid 171) raster 3856×2170, crop 3840×2160 and rec RWZM 1600/1600. BUFA1 lines, line words, crop and RWZM phase become stock's. The DNG is 3856×2170 (a stock size). The sentinel uses that raster. | not 3840×2160; not covered |
| 4 | `SBSTOCK` | The standby MOV answer is stock `{1, 5, 8}`: stock standby profile and mode, as for an `sok = 0` recipe. | — |

- `ROWS | RWZM` with `smode = 7` on the UHD 29.97 1×1 recipe gives a register image at BUFA1 start **identical to stock
  UHD 29.97**: every register written during the REC start, the defect address included. The sensor writes are
  identical except `0005` / `00D1`. [C] What still differs from stock is the virtual ids, the pid class flag (§2.4),
  the standby, and SensorLab's other hooks (rate, DNG tags).
- `smode`: 7 for the UHD 29.97 recipe, 123 for the UHD 25p recipe (the same frame time). Other combinations are refused.

### The ring (struct ap_rd ver 2)

- Header (16 words): `magic ms ver n sleeps clamped rec_words nmax bits smode live refused commits sw_total p p`.
- `bits` / `smode` are host-written. `live` / `refused` / `commits` are written at each commit. `sw_total` counts every
  SetImgMode_s since boot.
- Records (16 × 16 words, newest = `(n − 1) & 15`): the 12 REC-delay words, then:
  - `bits`: the live slot's toggles | `smode << 8` | refused << 16;
  - `sw`: SetImgMode_s calls since the previous REC start | from << 8 | to << 16 | calls into the live slot's mode << 24;
  - `sw_dt`: t0 − the end of the last SetImgMode_s, in µs;
  - `cur`: the current sensor mode at t0 (`*0xC343A6D8`).
- **The switch marker**: "switched at REC start" ⇔ `sw_dt` < 1 s and `to == cur` (the record id).
  - The standby mode is `from`: 8 = stock standby, 230/231 = ours, 232/233 = twin.
  - `ring.py <build json> <dump>` decodes a 0x440-byte dump taken at block + `rec_delay.base_off`.

## 4. Build (offline, 2026-11-08)

| build | command (in `qs/`) | file | sha256 |
|---|---|---|---|
| **PURPLE TEST** | `python3 -B build_slqs.py --purple-test --out ../validation/20261108-purple-stock-diff/out-purple-test` | `out-purple-test/fpSup/SensorLab-IMX410_v0.0.4test.BIN` (209 680 B) | `8f0b8fd414409ecfe5c03ad7547acfb435218bb0d816d650366f25b422065cd6` |

- Sources: `apply/ap.c` sha256 `582287fd…`, `qs/slqs.c` `ae396a2b…`.
  - **The tree is 0.0.4test.** The other session's FORMAT-dial work was in progress in `slqs.c`, so this BIN carries
    that client state.
  - The card in the 11-08 sweep was a 0.0.3test REC-delay BIN, and no 0.0.3test source snapshot exists.
  - **Rebuild right before going live**, with `--settings-from` the card's BIN, and use that build's json.
- json: `out-purple-test/build-0.0.4test.json`.
  - `state_off` 0x33340: magic, N at +4.
  - `purple.bits_off` = +0x20, `smode_off` +0x24, `live_off` +0x28, `refused_off` +0x2C, `commits_off` +0x30.
  - `ring_off` = +0x40, 16 records of 16 words.
  - `sq_test_off` = 0xA041.
  - All offsets are from the SensorLab block. They move with every rebuild: always use that build's json.
- Same file name as the product. The builder refuses `--purple-test` unless `--out` names a `*purple*` directory.
  Never put this BIN in a release or on the merge page.
- Claims: the same as the REC-delay build (one more than the product). No new hook site.

## 5. Tests

- `apply/test_purple.py` (`SL_EMU_COUNT=1 python3 -B -m unittest test_purple`): 11 tests, all PASS (~5 min). The whole
  REC start runs as the firmware's code: the ImgCtrl SetImgMode_s for standby, then the switch, then C0379180's BL into
  the TEST hook, then the real FUN_c030cf98 → ContSet_Adr1, up to BUFA1's start. The tests:
  - the product and REC-delay ARM images do not change when the PURPLE blocks are stripped;
  - bits 0 give the REC-delay build's rows, canvas, registers and sensor writes; the ring records the 8 → ours switch;
  - TWIN: the twin answers the same rows; a twin standby switches at REC start with the same register image; a standby
    already in ours does not; the counts restart per take;
  - SBSTOCK: the standby is {1, 5, 8}; with TWIN also set, TWIN is refused;
  - NOWIN: only the five window registers change, and the sensor table equals stock mode 7's;
  - ROWS: all eight rows are stock mode 7's, plus the canvas META; the RX / TG / front-end registers and the sensor
    writes are stock's;
  - ROWS refusals: smode 8, 123 (wrong frame time) or 0, and a non-UHD recipe; UHD 25p with 123 is accepted;
  - RWZM: the 8 canvas words are pid 171's and nothing else changes; the standby canvas is untouched; BUFA1 lines /
    words and RWZM are stock's; the sentinel geometry is 3856×2170;
  - ROWS|RWZM: every register at BUFA1 start equals stock UHD 29.97's;
  - non-UHD recipes refuse NOWIN / RWZM / ROWS;
  - the toggles change only at a commit (sq_test 30 1 / 30 0).
- Mutants: `python3 -B test_purple.py --mutate`, 14 of 14 caught. #12 survived the first run, the test was strengthened
  (a second REC start), and it is caught now.
- Other runs:
  - `test_apply.RecDelayTests` + `SourceTests`: 12/12 OK.
  - `tools/test.py fast`: every job passes except `site` (1 fail: the published `wasm_info.json` is out of date). That
    comes from the in-progress 0.0.4test client / core edits; this change touches nothing in site or core.
- `build_apply.arm` now accepts `NAME=VALUE` defines. `AP_RESYNC=0` builds the product's resync state. Without the
  define the test unit keeps `AP_RESYNC=1`, so existing tests are unchanged.
- Not run: `prelive` and the full apply mutation set. ap.c changed only inside `#ifdef AP_PURPLE_TEST`, and the product
  bytes are identical.

## 6. Live protocol (not run; AGENT_BRIEF live rules: broadcast first, no USB while recording, 12 s after a stop)

1. **Card.** Rebuild the PURPLE BIN with `--settings-from` the card's current SensorLab BIN. Deploy it with QS-Share
   0.0.2test and **no Gyro2**, using full read-back, then reboot with `ui_drive.py reboot`.
   - Read `LOAD.LOG` for `block`.
   - Check `magic` = `RDLY` and `ver` = 2 at block + `rec_delay.base_off`.
   - Keep N (`ms_off`) at 0.
2. **Recipes.** A = UHD 29.97 12b 1×1 (DC 6048×3402 → 3840×2160, key `12`). B = the UHD 25p `12fastW` sweep recipe.
3. **First take, bits 0 (baseline).** Read the ring. `sw` / `cur` / `sw_dt` tell whether the REC start ran a mode set and
   from which standby mode (§0). Record ≥ 6 takes per recipe.
4. **Per configuration** (A first; B only for the bits whose A result is clear):
   1. `mem set` block + `bits_off` to the value (and `smode_off`: 7 for A, 123 for B). Read both back.
   2. `callfn sq_test(30, 1)`, then `sq_test(30, 0)`. Take the address from this build's json (`sq_test_off`). Never use
      another build's json.
   3. Read `live_off` / `refused_off`: `live` must equal the bits and `refused` must be 0.
   4. Take 3 takes of 2 s each, 12 s apart. After each, `mem get` 0x440 bytes at block + `base_off` and decode with
      `ring.py`: `ff` (1 = shifted, 2 = written), `sw`, `cur`.
   5. Fetch frames 1–2 and run the dy check (`validation/20261103-first-frame-purple/takes.py` SHIFT).
   6. Cycle through the configurations twice, so each gets 6 takes:

      | order | bits | expectation if it is the cause |
      |---|---|---|
      | 1 | 0 | baseline ≈ 50 % (A?) / 13/27 (B) |
      | 2 | `ROWS\|RWZM` (12) | stock-identical at BUFA1 start; if this is still purple, the cause is outside these registers (ids, class, standby, other hooks) |
      | 3 | `NOWIN` (2) | the sensor window alone |
      | 4 | `ROWS` (4) | stock sensor / RX / TG; our raster / RWZM |
      | 5 | `RWZM` (8) | stock raster / RWZM; our readout |
      | 6 | `TWIN` (1) | a forced mode set at REC start (only if step 3 showed none) |
      | 7 | `SBSTOCK` (16) | stock standby |
5. **DNG spot check, one per configuration.** Colour preview, the mod-4 bit check, BitsPerSample / BlackLevel /
   WhiteLevel.
   - Expected sizes: `RWZM` and `ROWS|RWZM` give 3856×2170 (stock UHD), the others 3840×2160.
   - `NOWIN` frames show the sensor's top band, not the centre. That is expected and not a fault.
6. **Stop rule.** Any freeze (no pong for 5 s): stop, log the bits and the last action, report. No recovery loop.
   - Risk notes. `NOWIN` and `ROWS` run a readout never recorded live before.
     - For A it is stock mode 7's sensor table (NOWIN) or stock rows (ROWS) at stock frame time, and the output is
       covered by more input lines than needed.
     - For B, NOWIN reads the full height at HMAX 418, which is 23.8 ms inside the 40 ms frame.
     - Run A first.

Reading the result: the rate per configuration against the baseline (Fisher exact on 6 vs 6 is weak; extend the
configuration that changes). If `ROWS|RWZM` is clean and `NOWIN` alone is clean, the sensor window / y0 is the cause and
the product fix is to read like stock (full height, RX skip). If `ROWS|RWZM` is still purple, the cause is outside the
REC-start registers.

## Files

- `stock_diff.py`: the diff harness (it reuses `../20261103-first-frame-mmio-diff/mmio_diff.py`; cams are
  product-like, `AP_RESYNC=0`). It writes `diff.json` and `mmio-*.tsv`.
- `ring.py`: the ring decoder.
- `../../apply/test_purple.py`: the toggles' unicorn tests and their mutants.
- `out-purple-test/`: the TEST BIN and its json.
