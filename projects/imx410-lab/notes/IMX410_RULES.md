# IMX410 on the SIGMA fp — rules, measured

How the camera drives the sensor, from the sensor bus itself (IMXB logger) and the
first DRAM copy of each frame (CRCT → BUFA0 tap). Firmware 5.02.

Evidence levels: **[M]** measured on the camera this round · **[C]** read in the code · **[I]** inferred.

Tools: `bufa_probe.py` (frame / bus / focus), `analyze.py` (sweep → table), `buslog/` (IMXB sup).
Raw data: `captures/` (one directory per point: frame.raw, frame.json, bus.json).

Unless noted, every measurement is in CINE live view, sensor mode 8
(MONIT1_60, 2016×1344 12-bit, 59.94 fps), 2026-10-20.

## 1. The sensor bus

- **One write path [C].** Every sensor register write is `FUN_c0322c70(reg, val)`
  (570 call sites) → `FUN_c0128898`. That function is the only writer of the sensor-bus
  controller at `0x21C00100..`: command `0x21C00114 = reg_lo<<16 | reg_hi<<8 | 0x81`,
  data `0x21C00118 = val`. It is write-only; there is no read-back path.
- **Per-frame traffic [M].** In idle live view the firmware writes the same 13 registers
  once per frame (every 16.7 ms), in this order:
  `041F 05E2 05A6 05A8 05E1 003D 003E 003F 0040` (gain, from `C0323884..C03239A8`),
  then `0005 0006 0007 0008` (exposure, from `C0325804..C032583C`).
  No other register is written while the mode stays the same.

## 2. Frame timing: the SoC is the master

- **[C+M]** VMAX and HMAX are **not** sensor registers. They live in the SoC receiver /
  timing block, and the frame period is computed from it (`FUN_c0125ca8`):

  ```
  HMAX   = (0x30100004 & 0x3FFF) + 1          # also the tail, high half
  VMAX-1 = (0x30100020 >> 16) & 0x3FFF
  period = (VMAX-1)·HMAX + tail   cycles at 72 MHz   (FUN_c0128880 = 72000 kHz)
  ```

  Live mode 8: `0x30100004 = 0x01490149` → HMAX = tail = 330; `0x30100020 = 0x0E370000` → VMAX = 3640.
  3639 × 330 + 330 = 1,201,200 cycles → **59.94 fps** ✓.
  This matches the existing frame law (`research/imx410/notes/FRAME_RATE_IS_VMAX.md`) and shows
  where it is enforced: the sensor runs as a timing slave and the SoC generates its sync.
  It answers the old question of "how VMAX reaches the sensor": it never does.
- **[C]** Exposures longer than a frame: `FUN_c0321398` splits the requested time into whole
  frames plus a remainder. The remainder becomes SHS. The whole-frame count goes to the SoC
  (`FUN_c0125f68` → `0x30100048` bits 26:16).

## 3. Exposure (shutter)

- **[C]** `FUN_c03257d0(shs)`: `0x0005 = shs & 0xFF`, `0x0006 = (shs >> 8) & 0x3F`, clamped to 2..0x3FFE.
  `FUN_c0325818` always writes `0x0007 = 0`, `0x0008 = 0`. The value it is passed is ignored.
- **[M]** Sweep with `imager fixed_shutter 1 <µs>`, gain held (`captures/sweep_shutter/table.csv`):

  | µs | 100 | 250 | 500 | 1000 | 2000 | 4000 | 8000 | 16000 |
  |---|---|---|---|---|---|---|---|---|
  | SHS | 1810 | 1793 | 1766 | 1711 | 1602 | 1384 | 948 | 75 |

  **exposure = (VMAX − 2·SHS) · HMAX / 72 MHz.** One SHS step is 2 lines (9.167 µs at HMAX 330).
  SHS counts back from the end of the frame; SHS = VMAX/2 means zero exposure.
  Check: 16000 µs → (3640 − 150) × 4.583 µs = 15,995 µs.
- **[M]** The RAW signal is linear in exposure from 2 ms up (×1.94–2.01 per doubling, G channel 27 → 211 DN).
  Below 1 ms there is a ≈1–2 DN offset against the OB black.

## 4. Black level and optical-black rows

- **[M]** Widening the receiver window to y = 0 (`0x30100024` high half; live view uses 14) adds 14 rows above the image:
  row 0 = all zeros; rows 1–13 = optical black (no CFA structure).
- **[M]** The OB rows are real pixels: at a gain of 117 → 1600 their noise goes 1.00 → 2.46 DN,
  while their mean stays at ≈251–253 (the black is clamped inside the sensor).
- **[M]** DCLP (`imager dclp_off`) measures black on rows 1–10 and adds +3–4 DN from row 11 on, toward ≈255–256.
  With DCLP off, rows 11–13 read the same as rows 1–10.
- Details: `BUFA_FRONT_TAP.md`.

## 5. Gain

- **[M]** Sweep with `imager fixed_gain 1 <relative×100>` (117 ≈ ISO 100) at 4000 µs.
  Data: `captures/sweep_gain/table.csv`; the high-gain repeat at 250 µs is in `captures/sweep_gain_hi/`.

  | relative | analog code (3D/3E = 3F/40) | 4095/(4095−code) | 05E2 | 041F | 05E1 (HCG) | 05A6/05A8 | RAW G above black | OB noise |
  |---|---|---|---|---|---|---|---|---|
  | 117 | 985 | 1.317 | 0 | 0 | 0 | 41/39 | 54.4 | 0.99 |
  | 160 | 1821 | 1.801 | 0 | 0 | 0 | 41/39 | 77.5 | 1.04 |
  | 234 | 2540 | 2.633 | 0 | 0 | 0 | 41/39 | 106.3 | 1.19 |
  | 468 | **2540** | 2.633 | 0 | 0 | 0 | 41/39 | 108.6 | 1.21 |
  | 936 | 3317 | 5.264 | 0 | 0 | 0 | 41/39 | 215.1 | 1.72 |
  | 1872 | 3706 | 10.53 | 1 | 14 | 0 | 41/39 | 403.7 | 2.79 |
  | 3744 | 3900 | 21.0 | 1 | 14 | 0 | 41/39 | 861.8 | 4.88 |
  | 7488 | 3965 | 31.5 | 1 | 14 | 0 | 41/39 | clipped | 9.52 |
  | 14976 | **3840** | 16.06 | 1 | 29 | **1** | **42/41** | clipped | **4.07** |
  | 29952 | 3965 | 31.5 | 1 | 29 | 1 | 42/41 | clipped | 7.92 |

- **[M] Analog law confirmed.** The RAW signal follows 4095/(4095 − code):
  measured ×1.95 where the law gives ×2.00 (2540 against 985), ×3.95 against 4.00 (3317), ×15.85 against 15.9 (3900).
  Both register pairs always carry the same code (3D/3E = 3F/40).
- **[M] A digital band.** Relative gains 234 and 468 produce the same analog code. Part of the requested gain
  is applied as digital gain after the sensor, which is why `fixed_gain` ×13.7 gave only ×6.8 in RAW (§4).
- **[M] High-analog readout.** From analog code ≈3700 up: `05E2 = 1`, `041F = 0x0E` (0x1D with HCG).
- **[M] HCG.** It switches on between relative 7488 and 14976: `05E1 = 1`, the analog code steps down
  (3965 → 3840), the trims move 41/39 → 42/41, and OB read noise drops 9.5 → 4.1 DN.
- **[M]** The black stays at ≈250–253 for every gain (clamped in the sensor).

### 5b. High-gain repeat at 250 µs (`captures/sweep_gain_hi/`)

| relative | code | HCG | G above black | OB noise | black |
|---|---|---|---|---|---|
| 1872 | 3706 | 0 | 30.7 | 2.76 | 251.3 |
| 3744 | 3900 | 0 | 58.9 | 4.85 | 251.1 |
| 7488 | 3965 | 0 | 119.0 | 9.47 | 249.9 |
| 14976 | 3840 | 1 | 221.5 | 4.01 | 250.8 |
| 29952 | 3965 | 1 | 441.9 | 7.79 | 250.4 |
| 59904 | 3965 | 1 | 839.0 | 14.97 | 245.2 |

- **[M] HCG = ×3.71**, at the same analog code (3965): 441.9 / 119.0.
- **[M] A gain stage that is not on the sensor bus, before the tap.** From 29952 to 59904 every sensor register
  is identical, yet the RAW is ×1.90, the OB noise ×1.92, and the black falls to 245. The digital gain sits
  between the receiver and BUFA0, which fits the CRCT "Gain" stage (`0x300F06B0` mux 0 = Gain) [I: the block is not yet located].
  The 3900 → 3965 step measures ×2.02 against ×1.50 from the analog law, so this stage is already active there [I].
- **[M] Not every digital gain reaches the RAW.** Relative 234 → 468 has the same code and the RAW changes only ×1.02,
  so in that band the extra gain is applied after the tap (ISP).
- Gain chain on this tap: `sensor analog 4095/(4095−code), code ≤ 3965` × `HCG 3.71 (05E1)` × `CRCT digital (top end only)`,
  then ISP digital (not visible here).

## 6. Test pattern and DCLP target (`captures/testpattern2/`)

- **[M] Test pattern register `0x02B2`.** It is not part of the 161-register mode blob, and only `imager testpattern`
  writes it (`C0324FD0`): `testpattern 1` → `02B2 = 1`; `testpattern 2` and `3` → `02B2 = 5`; `0` → `02B2 = 0`.
- **[M] Pattern 1 = a diagonal ramp** (6, 6, 6, 7, 7, 7, 7, 8 … along rows and columns; 840 distinct values, monotone).
  This proves the 12-bit unpacking (`decode12.py`) and the row stride exact: a wrong bit order would scramble it.
- **[M] Pattern `02B2 = 5` is a flat ≈59 from the sensor, OB rows included (58.9).** The image rows come out as 255/256.
  **DCLP adds (target − mean of OB rows 1–10) with target ≈ 255.** That explains the +3–4 DN on normal frames, where OB ≈ 252.

## 7. Live-view modes and the mode switch

- **[M]** CINE live view runs **mode 8** (MONIT1_60, 3× binned, 2016×1344) for every stock movie size and rate
  (FHD 0–7, UHD 0–3: `captures/modescan/`, no mode-switch burst in any bus log). The record mode is chosen at REC.
- **[M]** Magnify (`key OKON`/`OKOFF` in live view) switches to **mode 10** MONIT1_60_LOWP2, 6064×2022 1:1, 59.93 fps.
- **[M] What a mode switch sends** (`captures/magnify/ok1/bus.json`):
  1. the table writer (`FUN_c03258c8`): the mode's 161 registers, plus `0x00CE = 0` and **`00D1/00D2/00D3`
     (251/255/2 for mode 10, 250/255/2 on the way back)**, which are not in the ROM table;
  2. then, outside the table: **`0x0003 = 1`, `0x0022/23 = 0x042D` (1069), `0x0024/25 = 0x03F3` (1011)**;
  3. **`0x0011 = 0` then `1`**: the sensor is stopped and restarted around the switch.
- **[M] Vertical crop window (the undecoded `0003`, `0022–0025`).**
  `0x0024/25` = output rows / 2 (1011 → 2022). `0x0022/23` = first row read (1069 = (4160 − 2022)/2, centred).
  `0x0003 = 1` enables the window. This confirms the Z CAM hypothesis ("0x0024/25 ≈ height ÷ 2, 0x0022/23 ≈ vertical start").
  The array is therefore 4160 rows tall [I from the centring].
- **[M] SoC timing per mode** (`0x30100004` = HMAX−1 | (tail−1)<<16, `0x30100020` = VMAX−1 << 16, `0x3010000C` = width/12):

  | mode | HMAX | VMAX | period (cycles) | fps | width (12-px units) | CRCT x-offset 0x300F021C | receiver y window |
  |---|---|---|---|---|---|---|---|
  | 8 MONIT1_60 | 330 | 3640 | 1,201,200 | 59.94 | 168 → 2016 | 0 | 14..1358 |
  | 10 MONIT1_60_LOWP2 | 445 | 2700 | 1,201,500 | 59.93 | 506 → 6072 (−8 = 6064) | 8 | 40..2062 |

- **[M] OB rows per mode.** Mode 10: rows 1–36 ≈ 254 (σ 1.0); rows 37–39 ≈ 255.7, with the DCLP offset applied from 3 rows
  before the window; the image starts at row 40 (an R/G row). Mode 8: OB rows 1–13, DCLP from row 11, image from 14.
  No horizontal OB columns appear in either mode: the image starts at column 0.

## 8. The timing table is what the SoC timing block runs

- **[C+M]** ROM timing table `0xC0B59500` (stride 0x20: `+0` mode id, `+4` HMAX | tail<<16, `+8` VMAX | x_start<<16,
  `+0xC` x_end | y_start<<16, `+0x10` y_end) against the live SoC registers:

  | mode | table HMAX / tail | live 0x30100004 | table VMAX | live 0x30100020 | x | y | fps |
  |---|---|---|---|---|---|---|---|
  | 8 | 330 / 330 | 0x149 = HMAX−1 | 3640 | 0xE37 = VMAX−1 | 6..2022 | 14..1358 | 59.94 |
  | 10 | 445 / 445 | 0x1BC | 2700 | 0xA8B | 8..6072 | 40..2062 | 59.93 |
  | 106 (FHD take) | 445 / 735 | — | 5398 | — | 4..3036 | 172..1880 | 29.97 |
  | 123 (UHD take) | 450 / 450 | — | 6400 | — | 8..6072 | 354..3766 | 25.00 |

  The receiver x window is loaded in 12-pixel units (`0x3010000C` low half = width/12 rounded up);
  the remainder goes to CRCT (`0x300F021C`: 0 in mode 8, 8 in mode 10 → 6072 − 8 = 6064).
  frame = (VMAX − 1)·HMAX + tail at 72 MHz for every row checked.

## 9. Record-mode switches (`captures/recmode/`, `bufa_probe.py rec`)

- **[M]** A take is a mode switch on both ends. On the bus: the table (161 regs + `00CE` + `00D1–D3`), then `0011` 0→1.
  - FHD take → mode **106**: 0001 = 0x2A (1×, 12-bit)… (see bus.json); full height, so `0003` and `0022–0025` = 0.
  - UHD take → mode **123**: `0001 = 0x2A`, `001C = 5` (no merge), `0016 = 0x23`, `0062 = 0`, `007E = 0x46`.
  - Back to live view (mode 8): `0001 = 0x2F`, `001C = 2`, `0016 = 0x32`, `0062 = 0x10`, `007E = 0x3C`.
- **[C+M]** `00D1/D2/D3` = a 24-bit value that **toggles 0x2FFFA ↔ 0x2FFFB on every mode set** (end of `FUN_c03258c8`,
  global `DAT_c2f1e7b0`). It flips on each set, so it looks like a "new settings" handshake [I].
- **[C]** `0011` 0 → 1 = `XC_ImageSensorIMX410::v16`: the sensor stops and restarts around every switch.
- **[C]** A second, unused driver table with a 0x460 stride writes `005B 0060 0061 0067 00A5 00A6 00A9 00C6 00CC 00CE 00D1 00D3 00D4
  00D5 00D7 00DA 010E …` (`blk_c03.c:28236`, `C0327868`). It was not seen on the bus in any mode used here.

## 10. The firmware override (`imager mode_reg_add` / `mode_reg_test`) works

- **[M]** `mode_reg_add 0 0x2B2 0x1` + `mode_reg_test 1 10`, then entering magnify (mode 10):
  the bus shows `02B2 = 01` from the consumer (`lr = 0xC0323528`, after the 161-register table), and the frame is the test pattern.
  The earlier "no effect" (open-gate REDUCTION_KERNEL_MEASURED §7.12–7.13) happened because the mode was never set again.
- **[M] Trap: a register that is not in the mode table is not reset by the next mode switch.**
  `02B2` stayed on after leaving magnify and contaminated the next 12 captures (moved to `captures/override_bad/`).
  An override of a register outside the 161 must be undone explicitly (`imager testpattern 0` for `02B2`).

## 11. Undecoded registers, override sweep in mode 10 (1×, no binning) — `captures/override/`

Each value was applied on top of mode 10's table through the firmware override (written once, `lr 0xC0323528`, confirmed in bus.json),
then compared against a reference capture taken in the same session.

| register | values tried | effect in mode 10 |
|---|---|---|
| `0056` | 0x01, 0xFF | none (≤1 DN) |
| `0057` | 0x01 | none |
| `0057` | **0xFF** | **the pedestal leaves the image rows**: per pixel ≈ 1.11–1.16 × ref − 225…244; black near 0 (R/B min 1). OB rows unchanged (254). Bit test pending (`captures/override57/`) |
| `008A` | 0x00, 0x44 | none |
| `0726` | 0x01, 0x02 | none |
| `0790` | 0x00, 0x02 | none |
| `079C` | 0x00, 0x3F | none |

In a 1× mode the merge-block registers would have nothing to act on, so they are repeated in binned mode 8 (`captures/override8/`).

### 11b. `0057` by bit (mode 10, `captures/override57/`) and the same registers in mode 8 (`captures/override8/`)

| `0057` | effect (mode 10, vs reference) |
|---|---|
| 0x02 / 0x04 / 0x08 | none |
| 0x10 | clip ceiling rises (max 896 → 1178), OB noise 1.0 → 1.27; level unchanged |
| 0x20 / 0x40 / 0x80 / 0xFF | image pedestal removed (phases −205 DN, black near 0), OB rows unchanged |

- **[M]** In **mode 8 (3× binned)** none of `0056 = FF`, `0057 = FF`, `0726 = 1/2`, `0790 = 0/2`, `079C = 0/3F`, `008A = 0/44` changes the frame
  (all within ≈2 DN; each write confirmed on the bus). The `0057` effect therefore depends on the mode; it shows only on the 1× readout.
- **[M]** `0726`, `0790` and `079C` are confirmed **no-ops at these values** in both a 1× and a 3× mode. The vtap_test octal bug (§7.54) cannot explain these results:
  the values went in as `0x..` and the bus shows the exact bytes.

## 12. Where the pre-tap digital gain lives (offline RE 2026-10-20; live check pending)

- **[C] CRCT `0x300F0310`** (twin `0x300F0320`) = unsigned Q8.8 digital gain (0x100 = ×1), written by `FUN_c0634508` / `FUN_c06345e8`
  (blk_c06.c:46280–46342) from the gain path `FUN_c030c878 → FUN_c0312f18` (blk_c03.c:14282, 14529–14545),
  **before** the sensor analog code goes out (v9/v10). The two may therefore land one frame apart [I].
- **[C] Split rule (three tiers):**
  1. v31 ladder trim (gain_state 0: nodes at mgr `+0x98`/`+0x9c`, fitting ≈234/≈468 [I]) → ISP `AeDigitalGainBase 0xC320209C` (Q10). **Not on the tap.**
     This is the 234 → 468 band in §5.
  2. Sensor analog: code = 4095·(1 − 10^(−dB/20)), minus the HCG dB (`S+0x7c`) when HCG is on.
  3. Above the analog cap `S+0x68` (= 30 dB, so code 3965 = 4095·(1 − 10^−1.5)) the excess goes to **CRCT 0x300F0310**:
     digital = `S+0x70`·10^((dB − 30)/20). That is the "gain with no sensor writes" of §5b.
     Prediction for 3744 → 7488: analog ×1.50 × CRCT ×1.33 = ×1.99 (measured ×2.02).
- **[C] The CRCT pedestal.** `0x300F0318/031C` = p (14-bit, reset value 0x400 = 256 DN at 12-bit) and `0x300F0308/030C` = 0x4000 − p
  (`FUN_c03132b8`, blk_c03.c:14483). Every frame `FUN_c0313ec0`/`FUN_c0314228` move p by ±1–3 toward the OB measured at
  `0x300F02C0..2CC`, clamped to 0x100..0x700. This is the DCLP loop of §4 and §6.
- **[I] The gain pivots on the pedestal:** out = p + (x − p)·G. Raw OB sits ≈5.6 DN under p, so the black moves to p − 5.6·G:
  the fit gives p = 255.4 from 250.4 → 245.2 at G ≈ 2.04, and predicts 249.5 at G = 1.33 (measured 249.9).
- **[I]** `05E2/041F` (code ≥ 0xDFD = 3581) do not change the analog law: 3900 with 05E2 on is within 1% of the law.
- Correction to `research/imx410/notes/ISO_FIRMWARE_COMPLETE.md` §3c: the cap overflow is **not** applied in the ISP; it is CRCT, before BUFA.
- To verify on the camera: read `0x300F0310` at relative 7488 / 29952 / 59904 (expect ≈0x154 / 0x100 / 0x200) and `0x300F0318` (≈0x3FC–0x400).
- **[M] Confirmed on the camera (2026-10-20, `bufa_probe.py peek` after `fixed_gain`):**
  `0x300F0310` = 0x100 (auto) / **0x154** (rel 7488) / 0x103 (rel 29952) / **0x208** (rel 59904). Those are the predicted ×1.33 / ×1.0 / ×2.0.
  Pedestal `0x300F0318/031C` = 0x0400 in each 16-bit half (4 channels; 1024 at 14-bit = 256 DN); `0x300F0308/030C` = 0x3C00 = 0x4000 − p.

## 13. Sony-only registers (the fp never writes them), override in mode 10, reboot after each — `captures/sony/`

Values are the ones Sony's a7 III uses. Each value was written once (bus-confirmed), captured, then the camera was rebooted so the sensor came back from power-on.

| register | values | effect |
|---|---|---|
| **`0018`** | 0x00 / **0x0A / 0x64** | **N → 2N black rows (≈255.6, clamped) inserted at the top of the image, and the picture shifts down 2N** (10 → 20 rows, 100 → 200). A leading dummy/OB row count in 2-row units |
| **`0236/0237`** | 0x6D/0x00: none; **0x20, 0x30 / 0x01, 0x04: data corrupted** (≈1100 ± 880, or partly scrambled) | 16-bit value whose fp power-on value behaves like 0x006D; a readout or AD timing parameter [I] |
| `0002` | 0x00, 0x04 | none |
| `000B` | 1, 2, 3 | none (Sony's SetExposure_ZAF group) |
| `0012` | 0x10–0x16 | none |
| `0026` | 3, 4 | none |
| `002C` | 0–0x0A | none |
| `002E` | 0–0x15 | none |
| `0030` | 0, 3 | none |
| `0033` | 0, 0xA8 | none |
| `0061` | 0x30, 0x82, 0xEB | none |
| `023C` | 0x30, 0x6D | none |
| `0572` | 0x22, 0x66 | none |
| `078C` | 0, 1 | none |

"None" means: within ≈2 DN on every CFA phase, no change in sharpness, banding or geometry, in mode 10 (1×, 59.93 fps) — a coarse screen, not an exclusion (§17a).
A register can still matter in another mode, or for something the frame cannot show (timing, PDAF, power).

## 14. The two gain pairs are per colour; the second exposure pair is not a second exposure (IMXB v2 substitution, `captures/dual/`)

> ⚠ 2026-10-21 訂正：「0007/0008 ≠ 0 → 黑幀」的解讀錯了——0007/0008 是多幀長曝光，黑幀是累積中的幀（見 §44、§53）。


IMXB v2 replaces the value of a listed register on every write. The firmware rewrites gain and exposure each frame,
so the override cannot hold them, but the substitution can. Mode 8, gain fixed at 117 (code 985), shutter 4000 µs (SHS 1384).

| substituted | R (row 0, col 0) | Gr / Gb | B |
|---|---|---|---|
| `3F/40` → code 3071 | ×1.03 | **×2.95** | ×1.03 |
| `3D/3E` → code 3071 | **×3.01** | ×1.09 | **×3.00** |

- **[M] `3D/3E` = R/B analog gain, `3F/40` = G analog gain.** Same law (4095/(4095 − code); 3071 vs 985 → ×3.04).
  The firmware always writes the same code to both, so **per-colour analog gain (analog white balance) is available and unused**.
- **[M] `0007/0008` ≠ 0 (0x0674 or 0x0100) → the frame is black** (no signal; OB rows 1–10 also read 0), and stays a valid frame.
  That rules out a second exposure (which would add an image) [I]; the most likely reading is that `0005–0008` is one SHS field wider
  than 14 bits, so any upper byte puts SHS beyond VMAX [I]. The firmware masks SHS to 0x3FFE and always writes 0007/0008 = 0.

## 15. Arbitrary vertical crop / offset, and frame rate by VMAX (`captures/crop/`, `captures/vmax/`)

> ⚠ 2026-10-21 訂正：本節的「fps」是韌體幀計數（AE 開了多幀曝光補亮度），**成像幀率未驗證**；VMAX 1300 → 167 fps 不成立，mode 8 真下限 ≈146 fps（§46、§48）。垂直裁切本身成立。


- **[M] Vertical offset.** Entering magnify (mode 10) with `0022/23` substituted, a reference patch is found where the start row says:
  start 500 → +566/+568 (expected +569); start 0 → +1066/+1068 (+1069); start 2138 → −1070 (−1069). Accurate to 1–3 rows.
  Start 0 shows ≈52 dark rows at the top of the array, and 2138 + 2022 = 4160 shows ≈50 dark rows at the bottom.
- **[M] Vertical height.** `0024/25` = 505 (1010 rows) alone gives **no frame**: the SoC receiver still waits for its 2062-row window.
  With the receiver window cut to match (`--yend 1050`: 40 OB + 1010 image rows) the frame completes, and start 500 + 1010 rows lands at +568.
  **The rule: sensor height (`0024/25`·2) and receiver window (`0x30100024`) must agree.**
- **[M] Frame rate = 72 MHz / (HMAX·VMAX), set by SoC `0x30100020` alone** (mode 8, HMAX 330, `frame_count` over 2 s):

  | VMAX | 7280 | 4500 | 3640 | 3400 | 3000 | 2600 | 2200 | 1800 | 1500 | 1300 |
  |---|---|---|---|---|---|---|---|---|---|---|
  | measured fps | 29.98 | 48.41 | 59.80 | 64.23 | 72.71 | 83.63 | 99.14 | 120.63 | 144.82 | 167.40 |
  | law | 29.97 | 48.48 | 59.94 | 64.17 | 72.73 | 83.92 | 99.17 | 121.2 | 145.5 | 167.8 |

  Every BUFA0 frame stayed intact (correlation with the 59.94 fps frame ≥ 0.999, same sharpness).
- **Open:** at VMAX 1300 there are fewer line periods than the 1358 rows delivered, and the exposure level did not change with VMAX.
  The counter follows the SoC's sync, but whether the sensor really reads that fast has to be checked by timing BUFA0
  completions (not done). The live-view display drops frames above ≈60 fps (`trans_count` falls behind `frame_count`).

## 16. HDR: what works and what doesn't (2026-10-20)

### Spatial HDR through Sony's ZAF exposure registers: no effect in fp modes
- **[M]** `000B/000C` = 0x0700 (ZAF SHS 1792 ≈ 250 µs, same 14-bit format as `0005/0006`) with `0036` = 0x00, 0x01, 0x02 … 0x80 and 0xFF,
  applied by the override on entering mode 10 (1:1), every write confirmed on the bus. Against a reference taken right before:
  **no row, column or pixel responds** (all rows within ±1.5%; the 0x10 point that seemed to move was scene drift, retaken
  back to back: nothing). `captures/zaf/`, `zaf2/`, `zaf3/`.
- [I] The ZAF (PDAF) lines are probably read only in Sony's PDAF readout mode, which no fp mode sets up.

### Per-colour HDR: possible, but it is a colour split, not an exposure split
- §14: `3D/3E` (R/B) and `3F/40` (G) are independent analog gains. A G/RB gain split works, but each pixel still sees one exposure.

### Temporal HDR: works (IMXB v3 alternation + burst, `captures/burst/hdr_shs/`)
- **[M]** `bufa_probe.py burst --alt 0x05=0x68,0x01 --alt 0x06=0x05,0x07` (SHS 1384 / 1793 alternating per frame),
  gain fixed at 117, mode 8, 59.94 fps. G above black, 8 consecutive frames:
  **219.8, 3.3, 219.8, 3.3, 219.8, 3.3, 219.8, 3.3** — ratio **66× (6.0 EV)** every pair, frame interval 16,683 µs ± 4.
- **[M]** The short frame is the programmed ≈250 µs (÷16 against a steady 4 ms frame). The long frame is ≈16.4 ms, nearly
  the whole frame period, not the 4 ms its own SHS asks for. [I] The reset for a frame happens at the previous frame's SHS point,
  so alternating SHS a/b gives exposures ≈ (T − short) and short. To choose both freely, the alternation has to be designed with
  that one-frame offset in mind.
- [M] Infrastructure (IMXB v3, unicorn 13/13): `alt` flips per `041F` block; `frame_cb` steps BUFA0 through up to 16 buffers
  and timestamps each completion in the ISP interrupt. A plain 6-frame burst gave distinct frames, temporal noise 2.34 DN, 16,683 µs ± 3.
- Note: the frame-complete callback's "done address" (from `0x30182184`) always reads 0x40000000; `0x30182184` is not the latched address.
- Caution: one shell `reboot` with IMXB v3 freshly on the card did not come back (shell silent, UI normal); a manual power cycle
  recovered it, LOAD.LOG normal (IMXB v3 + SHELL loaded), and 6 later shell reboots were fine. Cause unknown.

### Single-frame monochrome HDR from split colour gain (`captures/split2/`, `hdr_split.py`)
Mode 10 (1:1), same exposure for all three frames, gains forced by IMXB substitution:
`all_low` (every pixel code 0, ×1.0), `all_high` (every pixel code 3900, ×21, with the high-analog readout `05E2=1/041F=0x0E`),
`split` (R/B code 0, G code 3900 + high-analog readout). Merge per Bayer cell: Y = G/21 in the shadows, Y = kR·R + kB·B where G clips
(kR 0.832, kB 0.912 from cells where both are valid), blended over 2800–3800 DN of G.

| | all-low | all-high | split |
|---|---|---|---|
| read-noise floor (scene units, from OB rows) | 0.532 | 0.249 | **0.251** (G) |
| G cells clipped | 0 % | 39.1 % | 39.1 % on G, **0 %** on R/B |
| brightest 1 % (scene units) | 389.4 | 182.9 (clipped) | 362.4 (0.93× all-low) |
| engineering DR, log2(clip / floor) | 12.82 EV | 9.52 EV | **13.9 EV** |

- **[M] It works, and the gain is ≈1.1 EV:** the read-noise floor of the high-gain frame together with the highlights of the low-gain frame,
  in one exposure, with no motion artefacts. The image (`low_high_split.png`) shows the all-high frame's clipped face recovered in the split.
- **[M] Limits.** (1) The floor only improves 0.8 EV at G (0.44 → 0.25 against the AE frame): above ≈×5 analog gain the input-referred read noise
  stops falling (§5 table). (2) Highlights come from R/B with fixed colour coefficients, so on coloured objects they are off by a few
  percent (7 % on this scene's brightest 1 %). (3) This scene's shadows are photon-noise limited, so the split shows the same
  shadow noise as both references (1.63–1.68); the gain appears only where read noise dominates.
- Every substitution value is in the firmware's own range; nothing outside the per-frame registers was touched.

## 17. Sony constant-valued registers, scan part 1 (points 0–64 of 176, `captures/const/`)

Plan in `captures/sony_const_plan.json`: Sony's value where it is non-zero, else 0x01; override on entering mode 10, reboot after each,
fresh reference every 15 points. Every write confirmed on the bus (`lr 0xC0323528`). Paused at point 65 (user, 2026-10-20 06:16).

- **[M] `0018/0019` is one 16-bit field**: leading dummy (black) rows = 2·N. `0019 = 0x01` (N = 256) blanks the first ≈500 image rows
  and shifts the picture down; `0018 = 0x0A` gave 20 rows (§13).
- **[M] `0004 = 0x01` and `003A = 0x01`**: the sensor output becomes a flat 256 in every image pixel, with the OB rows at 0.
  Output-mute or standby controls, not image controls.
- **[M] No visible effect in this screen (see §17a for what that does and does not mean)**: 0000=04, 001E=0D, 0028=26, 002A=02, 0036=01, 003B=06, 0041=EE, 0044/0045=50,
  0059=08, 005C=FF, 005D=03, 0063=0B, 0065=59, 0069=6B, 006B=21, 006D=5B, 0080=28, 0087/0088=77, 0238=6A, 023A=03, 023E=63,
  042C/042F/0440=21, 0442=40, 0443=03, 0483=80, 0486=2B, 0488=28, 0507=20, 0509/050C/050E=03, 0510=04, 0512/0513=02, 0514=04,
  0515=0A, 0560=1E, 056B=01, 056F=50, 0573/0574=77, 0579=50, 05A7=05, 05DC=0F, 05F7=29, 05F8=27, 07DA=C0,
  0009/000A/000C/000D/000E/000F/0010/0013/0014/0015/0017 = 01.
- No row-interleaved or pixel-interleaved exposure/gain control has turned up so far.

### Scan part 2 (points 65–119)
- **[M] Row-count group:** `001A`, `001B`, `001D` = 0x01 blank or shift rows like `0018/0019` (001B/001D ×0.74 with the picture moved).
- **[M] `008B = 0x01`:** black → 2174, and R/B and G move in **opposite directions** (R/B up ×8–9, G negative): a colour-dependent offset.
- **[M] `00B5 = 0x01`:** black +42 (254 → 296), R/B drop more than G (×0.79 vs ×0.89). An offset or clamp control.
- **[M] `00B0 = 0x01`:** uniform ×1.06.
- **[M] `002D = 0x01`:** sharpness/noise metric +6%; small.
- **[M] `023D = 0x01`:** **R/B ×1.74–1.94, G ×0.55–0.61**. The same CFA-diagonal split as `3D/3E` vs `3F/40`, from a different register.
- **[M] `0239 = 0x01`, `0241 = 0x01`:** data corrupted (≈1500 ± 870), like `0236/0237`, so the `0236–0243` block is a readout/AD timing block.
- **[M] No visible effect in this screen (§17a):** 001F 0020 0021 0027 0029 002B 002F 0031 0032 0034 0035 0037 0038 0046 0047 0048 0049 004A 005A 005B 005E 005F 0060
  0064 0066 006C 006E 0082 0095–0099 00AE 00AF 00B1–00B4 023B 023F 0243 028C 028D 02BC.
  The ZAF read-gain registers `0047–004A` included: nothing.
- Point 120 (`02BD = 0x01`) failed before capture: callfn could not return the echo slot, the shell `reboot` did not come back, and the
  user power-cycled the camera. The echo slot was stock afterwards. To be retried alone.

### 17a. What "no visible effect" means in this scan — and what it does not (user's question, 2026-10-20)
This was a **coarse screen**, not a decode:
- **one value per register** (Sony's, or 0x01): a bit field can be inert at that value and active at another (`0057`: 0x01 nothing, ≥ 0x20 strong);
- **one mode** (mode 10, 1:1), one scene, one frame: effects tied to binning, 14-bit, high-speed readout or PDAF readout cannot show
  (`0057` acts in mode 10 and not in mode 8);
- **registers tested alone**: fields that need an enable or a partner (16-bit pairs such as `0018/0019`; ZAF exposure possibly needing a
  PDAF readout mode) can look inert;
- **coarse metrics**: per-phase means, neighbour difference, row/column means, thresholds 2–8 % set by hand, not by a measured noise floor.
  Timing, power, temporal noise, fixed-pattern noise, temperature, OB/embedded content and anything under ≈2 % are invisible to it.
So "no visible effect" = **not excluded**. What the screen does establish: the registers that *did* respond (§13, §17).
A real decode needs: a ref-vs-ref noise floor as the threshold; a bit walk (or field sweep) per register; per-pixel difference maps,
row/column FPN, burst temporal noise, a dark frame and a bright frame; at least mode 10 and mode 8; Sony's whole per-mode column applied as a set, then split.

### Scan part 3 (points 121–143)
- **[M] ★ `05A9 = 0x01`: row-parity-selective.** In mode 10 the **R/G rows (even) go black** (signal ×0.016 / ×0.008, black level
  unchanged) while the **G/B rows (odd) are untouched** (×1.003 / ×1.001). The first control found that treats rows differently.
  Sony's a7 III sets or clears bits 0 and 2 of `05A9` from mode flags in its PDAF-related helper (`0x637B32E0`,
  `sony_a7iii_v404_imx410_pdaf_reverse_comparison.md` §223).
  **Hypothesis [I]:** bit 0 puts the even rows under a second exposure/gain setting that is 0 by default, so they integrate nothing.
  If so, setting that second setting gives row-interleaved dual exposure (spatial HDR).
  Next: `05A9` with `000B/000C`, with `0007/0008`, and with `0047–004A`, and a bit walk of `05A9` (bits 0 and 2 first).
- **[M] `042E = 0x01`:** output a flat 4095 (an output-mode control).
- **[M] No visible effect in this screen (§17a):** 0424 042B 0431 0432 043F 0485 04DD 04E3 0506 0508 050B 056A 056D 056E 0570
  071F 0721 0771 078E 078F 0791.

## 18. `05A9`: two row groups (2026-10-20, `captures/r05a9/`)

Mode 10, override on entering magnify, reboot after each; ratio per CFA phase against a reference taken just before.

| `05A9` | R / Gr (even rows) | Gb / B (odd rows) |
|---|---|---|
| 0x01 (bit 0) | **×0.011 / ×0.005 (dark)** | ×0.992 / ×0.986 |
| 0x04 (bit 2) | ×0.989 / ×0.990 | **×0.008 / ×0.016 (dark)** |
| 0x05 | dark | dark |

- **[M] The sensor treats the rows as two groups by parity, each switchable on its own** (bit 0 → even rows, bit 2 → odd rows),
  with the black level unchanged. Single-row alternation (rows mod 4 = dark, ok, dark, ok).
- **[M] Not relit by:** ZAF exposure `000B/000C` = 256 or 1024, ZAF read gain `0047–004A` = code 985. `0007/0008` cannot be judged:
  on its own it blackens the whole frame (§14).
- [I] A switched-off group most likely gets a second shutter/transfer setting whose default gives no exposure. Finding that setting
  would give row-interleaved dual exposure. Next batch: `05A9` bit walk, and bit 0 with the other ZAF parameters (`000D/000E`, `000F/0010`)
  and `0009/000A` (`captures/r05a9b/`).
- **[M] Bit walk** (`captures/r05a9b/`): only bits 0 and 2 act; 0x02, 0x08, 0x10, 0x20, 0x40, 0x80 are within ±1.5 % everywhere.
- **[M] Still not relit** with bit 0 set: ZAF P1 `000D/000E` = 256 or 1024, ZAF P3 `000F/0010` = 256 or 1024, `0009/000A` = 256.
- **[M] The "dark" rows keep a trace of the scene** (16×16-block correlation 0.94 for R, 0.90 for Gr), but with **colour-dependent slopes**
  (R 0.0050, Gr 0.0013, ≈ +1 DN offset). A real exposure would scale every colour alike, so this is most likely crosstalk or leakage
  from the live neighbouring rows [I], not a usable short exposure.
- Status: `05A9` switches a row-parity group off. The register that would give that group its own exposure (row-interleaved HDR) is not found yet.

### Scan complete (all 176 points, 2026-10-20 07:26)
- Points 144–175 (`0799 079B 079D 07A0 07A1 07BA–07D2 07DB 07DC`): no visible effect in this screen (§17a).
- Point 120 (`02BD = 0x01`) retried alone: captured normally, no visible effect. The earlier shell hang at that point was incidental.
- **Responding registers, whole screen:** `0004`, `003A` (flat output); `0018/0019/001A/001B/001D` (leading dummy rows);
  `002D` (small); `008B` (colour-dependent offset); `00B0` (×1.06); `00B5` (offset/clamp); `023D` (R/B vs G split);
  `0236–0243` block (readout timing: 0236/0237/0239/0241 corrupt the data); `042E` (flat 4095); **`05A9` (row-parity groups, §18)**.
- **No row-interleaved second exposure was found.** `05A9` can switch a row group off, but no register in the screen gives that group its own exposure.

## 19. Detailed sweep of the responding registers (bit walk, two modes, noise floor) — `captures/sweep_responders/`, `sweep.py judge`

Method: `sweep.py` (§17a done properly). Values 0x01…0x80 and 0xFF; mode 10 (1:1) and mode 8 (3× binned);
a fresh reference after every reboot + AF; a point counts when it exceeds 4× the ref-vs-ref floor
(mode 10: phase 0.66 %, colour spread 0.27 %; mode 8: 2.5 %, 1.5 %). Texture alone (tex) is not counted: AF jitter moves it.
fastreboot (`poff 1`) resets the sensor (the sticky `02B2` test pattern is gone after it), so it is used between registers.

| register / bit | mode 10 (1:1): R, Gr, Gb, B | mode 8 (3×) |
|---|---|---|
| `008B` bit 0 | **R/B ×2.06, G → 0**, black +91 | R/B ×1.6, G ×0.83 |
| `008B` bit 1 | **G ×1.89, R/B → 0**, black +97 | G ×1.2, R/B ×0.6 |
| `008B` bit 2 | **all ×0.62** | — |
| `008B` bit 3 | all ×0.97 | — |
| `008B` 0xFF | R/B → 0, G ×0.55, black +185 | ≈ ×1.07 |
| `00B5` bit 0 (and 0xFF) | image flat, black +389: output fixed | same |
| `00B5` bit 4 | all ×0.95 | — |
| `00B0` bit 3 / bit 7 | ×0.89 / ×0.92 | none |
| `002D` bits 2/4 | ×0.97–0.98 | none |
| `0057` bit 4 | **row banding** (row profile 47× floor), level unchanged | none |
| `0057` bits 5/6/7 | image collapses to black (pedestal removed, §11b) | **none** |
| `05A9` bit 0 | even rows off | even rows ×0.05, **odd rows ×2.0** |
| `05A9` bit 2 | odd rows off; even ×1.87 (**inconsistent with §18's ×0.99: recheck**) | odd ×0.05, even ×1.65 |

- **[M] `008B` bits 0/1 select a CFA diagonal:** bit 0 keeps R/B (×2) and blanks G; bit 1 the reverse. A pixel-diagonal output select.
  The ×2 on the kept diagonal and the black jump suggest the readout doubles the selected samples [I].
- **[M] In 3× binning `05A9` doubles the group that stays on**, so the vertical merge normalises by the number of active rows [I].
- `023D`: the first run was contaminated (bit 0 in mode 8 stopped the sensor and every later value failed). Redone with a reset after each value: `captures/sweep_023d/`.
- **[M] `023D` redone, a reset after each value** (`captures/sweep_023d/`): bits 0–4 stop the sensor output (mode 8 for every one of them,
  mode 10 for bits 1–4); only bit 0 in mode 10 still delivers a frame (R/B ×1.6–1.9, G ×0.54–0.62). Bits 5–7: nothing in either mode.
  With `0236/0237/0239/0241` corrupting the data, **`023D`'s low 5 bits are a readout-timing value** in the `0236–0243` block [I];
  the colour split at bit 0 is mis-timed sampling, not a usable gain [I].

## 20. Bit-flip sweep of the mode-table registers (161 regs × 8 bits × modes 10/8) — `captures/sweep_table_bits/`, 2026-10-20

> ⚠ 2026-10-21 訂正：本節「mode 8 的 0003 b0 會停輸出」只是窗高為 0 的結果；3×3 給正確窗值可以裁切（§58）。本節其他位元結果是在 mode 10 底下直接寫（DCLP 未對齊），解讀以 §39 之後的虛擬模式結果為準。


Method: `sweep.py run captures/plan_table_bits.json` flips each bit against **that mode's own stock value** (xor), via the
mode-set override, mode 10 and mode 8 each; refs every 4 registers and after every reset. `sweep.py judge` (k = 4 × floor),
then `rawlv.py` (raw OB and per-phase active levels, no black subtraction) and `classify.py` (labels below).
Done: the first **115 registers (0001 … 0592) complete, 059A bit 0 only**; 059A–08B7 (46 regs) still to run —
the run stopped when the reset after `059A` bit 1 did not bring the shell back.

Labels: `Z` flat 256 (pixel signal gone, only the clamp target) · `W` flat 3327 with OB 4095 (conversion broken) · `X` no frame ·
`O±n` only the OB rows moved · `P±n` pedestal (all phases +n DN) · `L×r` signal ratio · `C` CFA phases unequal · `R`/`K` row/column structure.
Cells are `mode10/mode8`. `L×0.96–1.05` alone in mode 10 shows up on ~25 unrelated registers: treat it as scene/light drift, not an effect [I].

| reg (stock m10/m8) | b0 | b1 | b2 | b3 | b4 | b5 | b6 | b7 |
|---|---|---|---|---|---|---|---|---|
| 0001 (2A/2F) | Z/. | X/C | X/C | X/C | ×0.50/C | X/C | Z/C | ./. |
| 0003 (01/00) | ./X | ./. | ./C | ./. | ./×0.82R | ./P+3674 | ./. | ./. |
| 001C | R/R | R/C | R/R | R/R | R/R | ×0.94R/R | ×0.92R/R | ×0.83RK/×1.32RK |
| 0057 (00/00) | | | | | R/. | P−145/. | P−143/. | P−135/. |
| 0058 (20/70) | P−113/. | C/. | C/. | | | | | |
| 0062 (00/10) | ./P+2972 | ./P+2974 | | | P+335/P+2837 | | | |
| 0067 (0B/12) | | | | ./R | ./O+236 | ./×0.03 | ./Z | ./Z |
| 0068 (00/10) | ./W | ./W | | | O+513/C | | | |
| 006A | ./Z | ./Z | | | ./W | | | |
| 006F | | | | | | | ./W | ./W |
| 0070 (00/10) | ./W | ./W | | | ./W | | | |
| 007E | | | | | ./C | | ./O−59 | |
| 0083 / 0084 | | | | | ./C (R/B ×1.42, G ×0.92) / ./C (R/B ×0.80, G ×1.14) | | | |
| 0094 (00/01) | P+1756/×1.11 | | | | | | | |
| 00C5 | **C/C: R,B → black, G kept** | **C/C: G → black, R,B kept** | | | | | | |
| 00C6 / 00CA | X/X | | | | | | | |
| 0240 (00/02) | | **×0.25/×0.90** | | | | | | |
| 0242 (00/00) | C K/C K (R ×0.95, B ×1.10) | | R/R | | | Z/Z | | |
| 0244 (00/03) | ./×0.94 | ./**×0.60** | ./×1.13 | | | | | |
| 0429 (31/2C) | | | | | K/K | K/K | ×1.06RK/O+55 | ×1.21RK/K |
| 042A | | | | | ×1.06K/K | ×1.06K/K | ×1.23RK/O−24 | ×1.07K/K |
| 042D | | | | | | | | W/W |
| 0433/0435 (23/21) | | | | | | W/W · Z/Z | Z/Z · . | |
| 0434/0436 (1F/1D) | | ./×1.42 · ./C | | | | W/W | W/W | |
| 0437 0438 0439 043A 043B 043D | | | | | | W/W | W or K | |
| 043C | | | ./C | O+31/C | O+478/P+365 | Z/Z | Z/Z | |
| 043E | | | ./Z | ×1.10/Z | ×0.07/Z | W/W | W/W | |
| 0453 (00/00) | W/W | ×0.54/×1.20 (R) | ×0.02/×0.08 | | | | | |
| 0511 (6A/60) | | | P+337/C | ./C | P+333/C | | | ×1.11/×1.13 |
| 0516 0518 (23/21) | | P+754 · Z | | | | W/W | | |
| 0517 0519 (21/1F) | | P+755 · Z | W/. | W/. | W/. | C/W · O+280/W | W/W | |
| 0520 0522 (2A/28) | | | | W/W | | W/W | | |
| 0521 0523 (28/26) | | | W/. | ./W | W/W | ./O±88 | W/W | W/W |
| 0524 (01/31) | | | | | ./×1.14 | ./×1.18 | ./×0.94 | |
| 0531 / 0532 / 0530 / 052F | | | | | ./O+24 (0532) · ./O−15 (0530) | ./Z (0531) · ./C (052F) | | |
| 0585 (6C/50) | | | | ./C | | | **×2.06**/C (R,Gr → 0, Gb,B ×3) | **×2.03**/×1.12 |
| 0590 / 0591 (01/03) | ./R | ./×1.10 · ./×1.11R | ./×1.07 | ./×1.07 | ./×1.07 | | | |
| 059A | ×0.01/×0.10 | X (reset did not return) | | | | | | |

No effect on any bit in either mode (41): 0005 0016 0024 0042 0043 0056 007F 0081 0085 0086 008C 0403 041B 0430 0441 0444 044D 0482 0484
0487 048B 04DB 04DC 04DE 04DF 04F1 0505 050A 050D 050F 0525 052E 0569 056C 0575 0577 0584 0592 0593 0594 0595.
(`0005` = SHS low byte is in the table but rewritten every frame by the AE, so the override cannot show it.)

Rules read from the table:
- **[M] Readout-timing family `0433–043E`, `0516–0523`.** Stock values are mode-dependent and **m8 = m10 − 2** for every one
  (`0433/0435` 23/21, `0434/0436` 1F/1D, `0516/0518` 23/21, `0517/0519` 21/1F, `0520/0522` 2A/28, `0521/0523` 28/26), and they come in
  pairs with identical values. Bits 0–1 (±1…3 counts) do nothing; bits 5–6 (±32/64) break the conversion (W) or kill the signal (Z).
  So these are **timing counters (pulse positions in the AD/readout sequence) with a tolerance window of a few counts** [I]; the two
  members of a pair are presumably the two column-ADC banks [I]. Not usable as image controls; leave at stock.
- **[M] `0240` bit 1 and `0244` are the vertical merge normalisation.** Mode 8 (3× bin) has `0240=02`, `0244=03`; mode 10 has 0/0.
  Setting `0240` bit 1 in 1:1 divides the signal by 4; clearing it in mode 8 gives ×0.90. In mode 8 clearing `0244` bit 1 gives ×0.60,
  bit 0 ×0.94, setting bit 2 ×1.13 → **`0244` is a weight/divider of the binned sum** [I]. Together with §19 (`05A9` doubles the group
  left on) this is the binning arithmetic.
- **[M] `00C5` bits 0/1 select a CFA diagonal**, same as `008B` (§19): bit 0 blanks R/B, bit 1 blanks G; both modes.
- **[M] `0585` bit 6 or 7 in mode 10 = ×2.0 signal, all phases alike** — a clean analog ×2 outside the normal gain code [I: which stage].
  In mode 8 the same bit splits row groups (R/Gr rows off, Gb/B rows ×3): `0585` is mode-specific; candidate for extra gain in 1:1 only.
- **[M] Pedestal / clamp:** `0057` b5–7 and `0058` b0 remove ~140 DN of pedestal in mode 10 (image sinks toward 0; §11b);
  `0062`/`0511` bit 4 (and `0511` b2) add +335 in mode 10; in mode 8 `0062`/`0068`/`0070` b0/b1 push everything to ~3000+.
  `0067` b4, `0068` b4, `043C` b3/b4, `0429/042A` b6 move only the OB rows → **OB-row clamp offsets**.
- **[M] Column structure `0429`, `042A`** (stock 31/2C m10/m8): bits 4–7 give column fixed-pattern (K) and ×1.06–1.23 — column ADC
  reference/ramp trim [I].
- **[M] `001C`**: every bit adds row structure; b7 ×0.83 (m10) / ×1.32 (m8): a row-noise/row-clamp control [I].
- **[M] Output stoppers** (no frame, reset needed): `00C6` b0, `00CA` b0, `0001` b1–3/b5 in mode 10, `0003` b0 in mode 8, `059A` b1 (the reset
  after it did not bring the shell back: avoid).
- `0003` b5 in mode 8 saturates the image (P+3674): `0003` is the window-enable register (§7), bit 5 is not a window bit.
- `0453` b0 → W, b2 → signal ×0.02–0.08, b1 ×0.54 (m10) / ×1.20 (m8).

### 20b. 059B–0726 (`captures/sweep_table_bits2/`, after a power cycle; own refs)

| reg (stock m10/m8) | effect |
|---|---|
| 059B b1, 059C b0/b2/b3/b4, 059D b1 | **readout off**: mode 10 flat 256 (Z), mode 8 saturated (W). With 059A b0 (§20) the `059A–059D` block is all-or-nothing readout enables/sequence; never touch [I] |
| 059C b1 (cleared) | mild colour split, R/B ×1.1–1.27, G ×0.9–0.97, both modes |
| 06D0, 06D3, 06D6 (same behaviour, 06D9 none) | b3: OB +140…+260, active drops, noise ×1.5 (clamp/offset broken); **b4: R ×0.85, B ×1.13 (mode 10), R ×0.91, B ×1.12 (mode 8), G unchanged** — an R-vs-B trim, three copies [I: one per ADC bank or per readout phase] |
| 0717 (02/06) | mode 10 b3–b6: OB +27…+47 and the active image −75 DN (OB and active clamp no longer agree); mode 8 b4–b6: R and B samples sink to the pedestal (G kept ×0.47 → ×0.17); b7 in mode 8: output 0, OB 2172 |
| 071E | mode 8 b5/b6 same as 0717 (R/B gone), b7 output 0; mode 10 only small OB shifts |
| 0722, 0723 (00/02) | mode 8 b5/b6: small row/column structure, R/B −3…−11 % |
| no effect | 06D9 0716 0720 0724 0726 (0727: b0 only, the rest in `sweep_table_bits3`) |

- **[M] `0717`/`071E` in mode 8 act on the R/B diagonal of the binned readout** (G survives, R/B go to the pedestal) — like
  `008B`/`00C5` but only in 3× binning, so they belong to the binned row-pair pipeline [I].
- **[M] `06D0/06D3/06D6` bit 4 is the only R-vs-B (anti-correlated) control found so far** that leaves G alone.

### 20c. 0727–078C (`captures/sweep_table_bits3/`) — **per-row-group signal controls (spatial HDR candidate)**

`rowgroup.py` compares odd rows (Gb) with even rows (Gr) **inside the same frame**, by brightness, normalised by the
reference — this cancels scene/AF/light changes between frames (the per-frame ratios of this batch are polluted by
a reboot between the reference and the points; within-frame ratios are not).

| reg (stock m10) | effect in mode 10 (odd/even ratio, flat across brightness = linear) |
|---|---|
| **0738** (00) | **odd row group only**, linear: value 2 → ×0.52, 4 → ×0.35, 8 → ×0.21, 16 → ×0.13, 32 → ×0.075, 64 → ×0.045, 128 → ×0.021 (≈ v^−0.74); even rows untouched. Value 1 is different: even rows nearly dark too |
| **0737** (00) | even row group: 0x80 → even ×0.03, odd untouched; lower bits dim both groups unequally |
| **0735** bit 0 (stock 1 → 0) | **odd rows ×2.08**, exactly linear (2.07–2.08 over the whole range) |
| **073A** bit 7 | odd rows ×0.65 · **0739** bit 7: even rows ×0.65 (odd/even 1.55) |
| 0734 bit 0 | odd rows split by column: B ×1.83, Gb ×0.66 (R/Gr untouched) |
| 0736 bit 0 | colour split R/B ×2.5–2.8, G ×1.5–1.7 |
| 0727–072A, 072C | every bit: row and column structure; 0729 in mode 8 adds pedestal +217·2^bit (a linear DC offset register); 072A b5/b7 and 072B b1 stop mode 8 |
| 078D | no effect |

- **[M] Odd-row OB noise is unchanged (4.1–5.0 DN, same as the even rows) while the odd signal drops to ×0.02:**
  the attenuation acts **before** the read-noise source — less charge or less integration, not a digital/ADC gain [M].
  Whether it is time (exposure) or charge transfer is not settled: test with a moving/flickering subject next [I].
- **[M] This is the row-pair partner that §18 (`05A9`) was looking for:** one frame, two row groups, independent
  signal level, linear, with full-res even rows. Spatial HDR recipe candidate: 0738 = 8 → odd rows ×0.21 (−2.2 EV),
  0735 b0 = 0 → odd ×2 (+1 EV). Next: a fine value sweep of 0737/0738/0735 and the time-vs-charge test.

### 20d. 078D–08B7 (`captures/sweep_table_bits4/`, buffers kept across captures — zero failures in 240)

Little here: `0793` (mode 8 bits 0–4: ×1.08–1.15 with row structure; mode 10 b6: ×0.72), `0795` b4 m8 ×0.92,
`0792`, `078D` b4, `079C` b6/b7, `08B6` b0: row structure only. No effect: 0790 0794 0796 0797 0798 079A 079E 08B7.

**Sweep complete: all 161 mode-table registers × 8 bits × 2 modes.** Stability fix that made the last batches clean:
`bufa_probe.py frame --keep` (two 20 MB buffers allocated once per boot, uptime-checked) instead of 4 class-10
allocator calls per capture — those raced liveview's own allocations on the magnify switch and left the shell blocked
inside the allocator, so even `poff`/`reboot` could not be delivered (four manual power cycles on 2026-10-20).
- `08B6` bit 0 (mode 10): **OB noise 5 → 17–22 DN** with the level unchanged — a noise/clamp-filter control (leave 0) [I].

## 21. How the mode table is built: three independent families (offline, all 70 modes) — `offline/mode_deps.py`

Of the 161 table registers, 132 vary between modes. Each varying register is determined by **one** mode attribute;
none needs a combination except the window (0003, 0022–0025: start row / row count, already §7/§15). The geometry
record (`imx410_mode_geometry.csv`) gives the attributes: `f44` = horizontal bin, `f50` = vertical bin (1/2/3/6),
`f48` = vertical add count, `f60` = **readout class** 16–23.

| readout class `f60` | HMAX | bits | binning | modes (examples) | `0001` |
|---|---|---|---|---|---|
| 16 | 911 | 14 | 1×1 | 0, 6, 95, 100, 129 | 29 |
| 17 | 445/450 | 12 | 1×1 | 97, 3, 7, **10**, 101, 108 | 2A |
| 18 | 445/450 | 12 | 2×2 | 98, 27, 88, 106, 107 | 39 |
| 19 | 330/360 | 12 | 2×2 fast | 58, 103, 11, 89 | 39 |
| 20 | 445 | 12 | 3×3 | 139, 134 | 2F |
| 21 | 330/395 | 12 | 3×3 fast | 56, **8**, 147 | 2F |
| 22 / 23 | 445 / 330 | 12 | 3×6 | 140 / 12, 9 | 30 |

**Family A — AD speed (≈ 85 registers, 0042…06D9):** depend only on the conversion speed, three sets:
14-bit (class 16), 12-bit normal (17, 18, 20, 22; HMAX 445/450), **12-bit fast** (19, 21, 23; HMAX 330–395).
Examples (14-bit / normal / fast): `0433…043E` pairs 23,1F / 23,1F / **21,1D**; `0516–0523` same −2 step;
`042D` 98/7E/72, `0441` 89/7D/65, `0585` 7B/6C/50, `05D8` 74/5E/4B, `0511` 84/6A/60 — counters that shrink with
the line time. The fast set also switches on `0062/0068/006A/0070 = 10`, `0094 = 01`, **`0240 = 02`, `0244 = 03`**,
`04E2 = 70`, `0524 = 31`. 14-bit alone: `0042/0403 = 22` (else 88), `0453 = 30`, `007F = FC`, `008C/057A = 00`.

**Corrections to §20 from this:**
- `0433–043E`, `0516–0523` are **ADC-speed timing**, not "mode 8 vs mode 10": mode 8 is the fast class, mode 10 the
  normal class; the −2 is the fast set.
- `0240`/`0244` are **part of the fast-AD set**, not of vertical binning (2×2 normal, class 18, has 0/0). Their measured
  effects (0240 b1 in mode 10 → ×0.25; in mode 8 clearing 0244 b1 → ×0.60) are therefore an **ADC gain/ramp
  compensation of the fast conversion** [I], not merge normalisation.
- `0585` (×2 in mode 10 at b6/b7) is in the same family: an AD reference/ramp value, and its "gain" is a ramp-slope
  change [I] — it rescales the conversion, so it moves the clip point as well (to verify).

**Family B — vertical drive (0005, 0016, 001C, 0058, 0716–079F):** depend only on the vertical bin `f50`
(1, 2, 3; vbin 6 sets every 07xx to 00). Laws:

| reg | vbin 1 / 2 / 3 | law |
|---|---|---|
| 0717, 072C | 02 / 04 / 06 | 2·vbin |
| 0793 | 01 / 02 / 03 | vbin |
| 0724, 0725, 0739, 073A | 00 / 02 / 04 | 2·(vbin−1) |
| 0722, 0723, **0737, 0738** | 00 / 02 / 02 | 0 in 1×1, 2 when binned |
| 0728 | 3B / 3D / 3F | 0x39 + 2·vbin |
| 071E, 0734 | 01 / 05 / 03 · 0720, 0735, 0794: 01 / 05 / 01 · 0792: 10 / 22 / 30 | per-bin codes |
| 072A | E5 / F0 / A0 · 072B: 07 / 03 / 02 | per-bin |
| 0726 | 00 / 01 / 00 | 2×2 only |
| 0716 0727 0795 0796 0797 0798 079A 079E 079F | constant when vbin ≤ 3 (01 01 01 19 10 2C 25 08 10) | enable set of the 07xx block |
| 0058 | 20 (1×1) / 70 (binned) · 0056/0057: 02/06 in 1×1 only · 001C: 05 / 03 / 02 · 0016: 0F / 14–19 / 32 · 0005: 02 / 03 / 02 | |

- **[M+I] `0737/0738` are row-group controls of the vertical adder:** 0 in 1×1, 2 in every binned mode. Set in 1×1,
  they attenuate one row group linearly (§20c); in binning they are the per-group weights of the sum [I]. So the
  "spatial HDR" control is the binning adder's per-group input scaling — consistent with the noise result (applied
  before the read-noise source).
- **[I] 0739/073A (0, 2, 4) and 0724/0725 track 2·(vbin−1)**: row offsets of the added rows (which neighbours are summed).

**Family C — readout format:** `0001` per class (29/2A/39/2F/30), `0003`+`0022–0025` window, `0056/0057` 1×1 only.

**Use:** a new mode = pick a readout class (Family A set by speed + `0001`), a vbin (Family B column), then the window.
Example derived: a 2×2-binned mode at the normal speed is class 18 = Family A "normal" + Family B vbin 2 + `0001 = 39`.

## 22. Z CAM E2-F6 cross-check (offline, `notes/ZCAM_COMPARE.md`, `offline/zcam/`) and the read path (`notes/SENSOR_BUS_READ.md`)

- **[C] Family A = Sony's ADC bit modes:** Z CAM names its readouts (MODE0…22, MODE1A…2D) with the ADC width
  14/12/11. Against §21's 86 Family-A registers: Z 14/12/11-bit = fp 14-bit / normal / **fast** with 0 mismatches.
  So **the fp's "fast" class is 11-bit AD** (output still packed as 12 bit).
- **[C] Names (Z's AE list):** SHR 05/06 (= our SHS), **SVR 07/08** (frames of extra exposure — Z uses it for
  long exposures across frames; the fp keeps 0 — our "nonzero → black" in §14 needs retesting with VMAX/SHS set to match),
  **SPL 09/0A**, APGC_N 3D/3E, APGC_S 3F/40, APGC_ADD1 041F, APGC_ADD2 05E2, MGAIN_ADD1 05A6, MGAIN_ADD2 05A8,
  MCOVGAIN (HCG) 05E1, **DGAIN 0055** (sensor digital gain 0–3), `0000` bit 0 = standby. No DOL/Clear-HDR/dual-gain code.
- **[I] Correction to §20c:** `0728/0729` and `072A/072B` are the **vertical-drive window** (start row, rows/2, 16-bit
  each) — Z's 4K crop writes 0728/29 = 0x03E7, 072A/2B = 0x0439. The "pedestal +217·2^bit" of 0729 in mode 8 is the
  drive window moving (rows outside the driven area read as offset), not a DC-offset register.
- **[C] Readout formats the fp never uses:** `0001` = 2B/2C (4160 crop), 31, 34/35/36, 3B (h-bin 2, v 1×);
  11-bit 1×1 modes (MODE5 4160×2160 up to 90 fps, MODE5C/5D up to 170 fps, MODE2D 6064×2700); vertical-only 2:1
  (MODE21/22 6064×2012: `0001=2A` + `0242=2C 0278=04 0279=01 027B=04 08B6=01 08B7=68`).
- **[C] Sensor read-back:** the stock firmware never reads the sensor; the ch1 serial channel has an RX register
  (0x21C0011C) and writes run in a mode that may already sample it. Untested: whether SDO is wired, and the read chip-ID.

## 23. Astro-camera SDKs (ZWO ASI2400MC Pro, QHY410C, ToupTek) — `notes/ASTRO_IMX410.md`, `offline/astro/`

- **[C] Mode tables are identical to the fp's** register for register (14-bit 1×1: 188 regs, 2×2: 275, 3×3: 182,
  12-bit 1×1): an independent confirmation of §21 Families A/B including `0737/0738`, `0739/073A`, `0728/072A/072B`.
  Systematic differences only: `0016` (astro and Z CAM always 07; fp 07–32 by mode) and `0058` (astro 70 in 1×1 too).
- **[C] `005C/005D` = 16-bit black level in 14-bit LSB** (ZWO writes offset×8, QHY offset×16, high byte in 5D;
  Sony a7 III writes 0x03FF ≈ 256 in 12-bit = the fp's black). The fp never writes it (power-on value), which is why
  §17 saw nothing for `005C=FF` alone, and why `005C/005D` moved the black by −60…−190 DN in the 05A9 partner sweep.
- **[C] Gain:** analog code = 4095·(1 − 10^(−dB/20)) (= our 4095/(4095−code)); 30 dB = 3965 = fp max. HCG (`05E1`) from
  ZWO gain 140 (14 dB). Above the analog limit ZWO uses **`0055` = n<<4** (6 dB steps; Z CAM writes 0–3: encoding to verify).
  None of the three writes `041F/05E2/05A6/05A8`. Vendor HCG ratios ×4.6–5.3 vs our §5b ×3.71 → **re-measure** at a
  fixed mid analog code with fixed trims.
- **[C] Long exposure:** neither ZWO nor QHY uses SVR/SPL; VMAX is stretched in the FPGA, SHR at its minimum →
  on the fp, stretch the SoC VMAX (§15) for long exposures.
- **[C] Standby:** stop sequences write `0000 = 05` (ZWO) or `06` (QHY/ToupTek) → bits 0 and 1 are standby bits [I].
  QHY's sensor power-save command touches `05D6 05A2 04F0 04D2 04D1 04DD`. QHY writes only `0001=29` and no
  Family A → the power-on defaults are the 14-bit MODE0 set [I].
- Registers no fp/Z CAM path writes: ZWO `00DB/00DC` (0x01BC), `03E1=01`, `03E2=0F`. Queued in `plan_sony_bits.json`
  (with `005D` black steps, `0055` DGAIN codes, `0058=70` and `0016=07` in mode 10).

## 24. 05A9 partner sweep (05A9 = 01 + one of 183 non-table registers × 01/10/80/FF, mode 10) — `captures/sweep_05a9_partner4/`, `a9partner.py`

Baseline (05A9 = 01 alone, median of 719 points): even rows 0.008, odd rows ×1.84.
**Artifact:** the first two values after each reset (01, 10) show odd ×0.97 → ×1.2–1.5 on ~50 unrelated registers —
05A9's odd-row doubling builds up over the first captures after a reset. Only effects at 80/FF, or far outside that
band, are counted below.

| class | registers (value) |
|---|---|
| stop output (X) | 0000 (01/10/FF), 0013, 0017 (10/80/FF), 005E FF, 023D (10/80/FF) |
| conversion broken (W, OB 4095) | 042C 80, 0432 FF, 0512–0514 (01/FF…) |
| signal gone (Z) | 0019, 001D (10/FF), 0060 FF, 0515 FF |
| **row-group swap** (even back, odd off) | **023A** 10/80 (even ×1.5–1.7), **023C** 80/FF (×0.9–0.96), 023D 01 (×0.53) |
| both groups on, scaled | **050B** 10/FF (even ×1.7, odd ×4.8–5.0), **0510** 80/FF (even ×1.7–1.9, odd ×4.7–5.6), 023F 10/FF (both ×0.32), 001A FF (even ×0.31, odd ×1.88) |
| odd group scaled | 0069 (10/80/FF: ×0.08), 0512–0515 (×0.07–0.48), 0095 80 (×0.49), 0560 10 (×0.46), 056B (×0.86–0.90) |
| black / OB | **005C/005D** (16-bit black level, §23: 5D=10 → +966, FF → +3838; 5C/5D 01 → black −60…−190), 0238 80/FF (OB +85), 008B (OB +93), 00B5 (OB +395/+738), 001B (−22) |

- **[M] `0236–023F` is the row-group sequencer:** 023A/023C/023D select which group is read, 023F scales both;
  with 0236/0237 (§13) and 023D (§19) it is a readout-timing block — the group select is a timing position, not a gain.
- **[M] `050B` and `0510` restore the even group and multiply the odd one ×5** with 05A9 on — the strongest analog-like
  scale found outside the gain registers. Next: test them without 05A9 (are they a per-group gain?).
- No register restored the even rows **with an independent exposure** — so no hidden second shutter for the off group
  showed up; the per-group controls remain `0737/0738` (§20c) and this sequencer.

### 20e. Row-group fine sweep (`captures/sweep_rowgroup/`, `rowgroup.py`, mode 10, odd/even within the frame)

| reg = value | odd/even (dark → bright bins) | rule |
|---|---|---|
| 0735 = 01 / 03 | 1.00 | stock (bit 0 set) |
| **0735 = 00 / 02** | **2.07–2.08, flat** | **bit 0 alone: 1 = normal, 0 = odd rows ×2.08**; OB noise unchanged |
| **0738 = 2,3 / 4,5 / 6 / 8 / 0C / 10 / 18 / 20 / 30 / 40 / 60 / 80 / C0** | 0.52 / 0.35 / 0.27 / 0.22 / 0.16 / 0.13 / 0.092 / 0.074 / 0.05 / 0.04 / 0.034 / 0.023 / 0.023 | **bit 0 ignored** (3 = 2, 5 = 4); **odd = 1 / (1 + 0.45·v)** up to v ≈ 16, then flattens to ≈ 0.02 at v ≥ 0x80 |
| 0738 = 01 or FF | even rows go dark too (≈ 0.3–0.8, brightness-dependent) | bit 0 with no other bit (or all bits) is a different state |
| 0737 = 01…40 | 1.2–2.7, not flat in brightness; 80/FF: even rows ≈ 0 | dims the even group, non-linearly |
| 0739 = 80…FF | 1.31–1.65, falls with brightness | even group ×0.6–0.75, non-linear |
| 073A = 80…FF | 0.63–0.74 | odd group ×0.65–0.74 |
| 0739 / 073A = 40 | 1.00 | no effect |

- **[M] `0738`'s law is 1/(1 + k·v), not linear in v** — that is the shape of a charge split / added capacitance
  (conversion-gain reduction), not of an exposure-time change (which would fall linearly). With the OB noise of the
  odd rows unchanged, the odd group is converted with **lower conversion gain** [I]. If so, the odd rows should clip
  later than the even rows → **spatial (row-interleaved) dual-conversion-gain HDR**. Test next: a scene with clipped
  highlights, check whether odd rows keep detail where even rows clip (needs the user's bright light source).
- **[M] `0735` bit 0 = 0 doubles the odd rows exactly (×2.08) with unchanged OB noise** — consistent with two rows'
  charge summed in the pixel/floating diffusion (charge binning) [I]; check vertical resolution of the odd rows.

## 25. Public data (`notes/WEB_IMX410.md`) checked against our measurements, and the fast sweep

- **[C] Sony flyer: 23 readout modes, fps = 72 MHz/(HMAX·VMAX), HMAX ∈ {911 (14-bit), 445 (12-bit), 431 (11-bit full
  width), 330 (11-bit, width ≤ 4160)}**, VMAX ≥ rows + 38…76. Ceilings per fp class: 3×3 fast (mode 8) 156.7 fps
  (runs 59.94), 2×2 fast 105.5, 2×2 normal 78.2, 1×1 12-bit 39.3. Unused by the fp: 11-bit open gate 40.6 fps,
  4160×2160 at 72/97.6 fps, 3032×4040 half width 53 fps, 6064×2012 78–81 fps.
- **[C] Our gain law is right:** PhotonsToPhotos fp base 4.86 e⁻/DN14 vs ZWO 6.35 e⁻/ADU ÷ ×1.317 (code 985) = 4.82.
  fp stills switch to HCG at ISO 640. Flyer: saturation ≥ 15105 LSB14 at 0 dB → at code 985 the ADC clips at ≈74 ke⁻
  while the pixel holds ≈96–100 ke⁻: a lower code (a7 III ≈ 290) gains up to 0.4 EV of highlight.
- **[M, fast sweep 2026-10-20] `0055` = n<<4 → ×2^n exactly** (0x10 ×1.97, 0x20 ×3.96, 0x30 ×7.90, noise scales alike:
  digital, after the ADC). Low nibble does nothing. Matches ZWO and the IMX455/571 sibling layout.
- **[M] `005D` (with 5C = FF): 64 DN12 per unit, linear** (00 −192, 01 −128, 02 −63, 03 stock, 05 +129, 08 +320).
  Sibling sensors write black twice → `005E/005F` likely mirrors `005C/005D` [I] (005E/0060 FF → Z in §24/§25 data).
- `0000`: b0 standby, b2 wakeup on the siblings [V]; our 01/02/FF stop the output (§24).
- **Fast sweep (`fastsweep.py`)**: one magnify entry, buffers allocated once inside mode 10 and freed before leaving,
  BUFA0 kept running into scratch, each point = one IRQ-masked direct sensor write (`sensor_read/spi_read.S`, chip 0x81)
  + one whole-frame grab: **≈0.3 s per point** (was 4–5 s); reproduces 0738/0735/0055/005D from the slow sweeps.
  Caveat: registers that latch only at a mode set, or that the AE rewrites per frame, need `sweep.py`.

## 26. Sony-only registers, value walk (00, FF, each bit, Sony's value) — 187 registers, mode 10

Data: `captures/sweep_sony_bits/` (slow, full frame, 0005…005D), `captures/sweep_sony_bits2/` (slow, top 600 rows,
005E…0239), `captures/fast_sony/` (fast direct writes, 023A…07DC). Labels per value: `offline/sony_walk/*.txt`
(`valclass.py`). **Caveat [M]:** a direct write does not take effect for some registers that do act when written at
a mode set: 0069 = 40 → ×2.09 (slow) vs nothing (fast); 0019/001B/001D = 40/80 → ×2.1 (slow) vs nothing (fast), while
their low values (01, 04 → ×0.02–0.1) act both ways. Toggling `0011` 0→1 after the write (what the mode set does
15 ms after the table) does not make them latch. So the fast sweep's "no effect" is reliable only for registers
that latch immediately; the 75 fast "no effect" registers (023B…07DC) need a slow-path spot check before being
declared dead.

| class | registers |
|---|---|
| **black level** | 005C/005D (16-bit, LSB14), 0095 10/20 (OB +1500), 00B5 01/FF (+400), 008B 01/02/FF (+90…+180, with the CFA-diagonal select of §19), 0238/0239/0241 (OB +24…+111, OB noise ×4–12), 0080 FF (+1969) |
| **digital gain** | **0055 bits 5:4 → ×2^n** (exact); 0019/001B/001D/0069 = 40 (and 80) → ×2.1 at a mode set (noise ×2) |
| **signal killed (×0.01–0.1, noise down alike)** | 0019, 001D (01…20, FF), 0069 (01…20, FF), 001B (04…20), 0004 (04/08), 0095 40 — a digital output shift/scale [I] |
| **analog / readout** | 00E9 40/80 ×0.23 (Z CAM writes 80 at init!), 050B/0510 (10/80/FF: ×1.2–1.8 with OB noise ×4–4.6) |
| row groups | 05A9 01 even off / 04 odd off (direct write: odd stays ×1.01 — the ×1.84 seen in §24 comes with the mode set), 023A/023D colour split |
| conversion broken (W) | 042C 80, 042E 01/FF, 0432 FF, 0512 01/FF, 0513 04–40/FF, 0514 00–02/80, 0515 01/04, 0004 FF |
| output gone (Z) | 0004 01, 005E FF, 0060 FF, 0515 FF |
| stops the sensor (X) | 0000 01/02/FF, 0013 02–40/FF, 0017 02–40/FF, 00D9 every value, 00E9 01/02/20/FF |
| row/column pattern only | 000C 00–02 (K), 0009 08/20 (K), 0020 FF, 079B FF, 079D 04 |
| no effect | 128 registers, listed in the three files (75 of them fast-only: unconfirmed) |

- **[M] `00D9`: every value stops the sensor** — written only during the init sequence (Z CAM: `00E9=80, 00D9=60` before
  the standby release); so are `0000` and probably `00E9`. Init-only registers.
- **[M] The ×0.08 / ×2 family (0019, 001B, 001D, 0069, 0004, 0095 40)** scales signal and noise together → after the ADC,
  i.e. the sensor's digital output stage (bit shift / output width) [I].

## 27. Single-frame row-group HDR, measured (fast sweep, full frame, frame pairs) — `captures/hdr_rows/`, `hdr_rows.py`

Scene: clipped diffuser (37 % of cells), dark cloth, a print. Mode 10, direct writes, `0738` restored to 00 after.

| 0738 | odd/even (mid tones) | odd rows still clipped where even rows clip | odd median there | headroom |
|---|---|---|---|---|
| 00 (stock) | 0.997 | 100 % | 4095 | 0 |
| 02 / 03 | 0.502 | 61.5 % | 4095 | 1.0 EV |
| 04 | 0.335 | 5.7 % | 2922 | 1.6 EV |
| 06 | 0.251 | 0.2 % | 2149 | 2.0 EV |
| **08** | **0.200** | 0.2 % | 1702 | **2.33 EV** |
| 0C | 0.145 | 0.2 % | 1215 | 2.8 EV |
| **10** | **0.110** | 0.2 % | 964 | **3.18 EV** |
| 18 | 0.080 | 0.2 % | 713 | 3.6 EV |
| **20** | **0.059** | 0.2 % | 591 | **4.09 EV** |
| 30 / 40 / 60 | 0.044 / 0.034 / 0.025 | 0.2 % | 474 / 419 / 367 | 4.5 / 4.9 / 5.3 EV |
| 80 | 0.081 (5.6 % clipped) | — | — | anomalous: avoid |

- **[M] Works in one frame, linear, no AE help needed:** `hdr_rows.py` builds green Y = Gr below the clip, Gb/k above;
  0738 = 10 gives 3.18 EV more highlight range with the clipped diffuser fully textured (`hdr_0738_10.png`).
- **[M] Limits:** the groups are single Bayer rows, so **R exists only in the full-sensitivity rows and B only in the
  attenuated rows** → this is a green/mono HDR (or colour with R clipping first); highlight cells lose half the vertical
  green sampling. Odd-row dark temporal noise falls only 11 → 8 DN while the signal falls ×0.11: the attenuated rows
  are noisier per unit of light (shadows must come from the even rows, which the blend does).
- `0737` 02…20: odd/even 1.15 → 2.07 but the odd rows also stop clipping at ≥ 10 → it dims **both** groups, the even more;
  `0735 = 00`: odd ×1.81 here (×2.08 in §20e at lower light: the gain saturates near the clip).
- Use: write `0738` once per take (direct write latches at once); `0738 = 00` restores.

## 28. Search for a two-row (colour) grouping — none found (`rowpair.py`, `captures/rowpair/`, `captures/rowpair_m8/`)

Goal: a control that treats Bayer cells (raw rows 0-1 vs 2-3) differently, so every colour gets a full and an
attenuated sample (single-frame colour HDR). Metric: per colour, ratio in even cells vs odd cells (and per row mod 4).
- Mode 10, 55 registers (Family B 0716–079F, 0016/001C/0056–0058, 05A9, sequencer 0236–0243), 495 points: only
  single-row effects (05A9, 023C/023D, 0738-type); broken frames aside, no even/odd-cell split.
- Mode 8 (3×3 binned), 25 registers, 229 points: `0738` stays single-row (Gb/B ×0.35 at 10, R/Gr ×1.00);
  `0737 = 20` scales R ×0.48, Gr ×0.27, Gb ×0.33, B ×0.51 in every row (colour-dependent: it changes which rows are
  summed); **`072C` odd (01/03; stock 06 = 2·vbin)** gives a 4-row period — row%4 = 0 ×0.02, 1 G×1.9/B×2.0,
  2 R×0.8/G×1.1, 3 G×1.0/B×2.3 — unequal per colour within a row, i.e. the adder sums rows of different colours
  (mis-addressed binning), not a per-cell gain. `0793` (vertical add count) 0…8 scales all channels alike (×0.2…0.84).
- **Conclusion [M+I]:** the per-group controls act on single pixel rows (the vertical pixel-sharing pair), never on
  row pairs. Single-frame row-group HDR is green/mono (§27); colour needs R estimation in highlights
  (`hdr_color.py`) or two frames alternating the attenuated group.

## 29. `023A` bit 0 moves the attenuated group → two-frame colour HDR with no estimated channel (`captures/swap/`, `swap_pair.py`, `hdr_swap.py`)

Found by re-scanning the sequencer with `0738 = 10` already on (`captures/plan_swap.json`): a group swap is invisible
while both groups are equal, which is why §24/§26/§28 called these registers dead.

| with 0738 = 10 | R | Gr | Gb | B |
|---|---|---|---|---|
| 023A bit 0 = 1 (stock behaviour) | 1.01 | 1.00 | **0.114** | **0.122** |
| **023A bit 0 = 0** (00, 02, 04 … 80) | **0.146** | **0.115** | 1.06 | 0.93 |
| 023C = 80/FF, 023D = 01 | 0.22 | 0.07 | 0.48 | 1.76 (rows re-ordered: colours mixed) |
| 0240 bit 1 | ×0.25 on everything (§21) | | | |
| 05A9 = 03 | 0.44 | 0.65 | 0.43 | 0.59 |

- **[M] Two-frame colour HDR:** frame A (023A = 01) gives full R/Gr + attenuated Gb/B; frame B (023A = 00) gives full
  Gb/B + attenuated R/Gr. Each colour has a measured full and attenuated sample; k per colour (0738 = 10):
  R 0.137 (2.87 EV), Gr 0.109 (3.20), Gb 0.111 (3.18), B 0.140 (2.84). `swap_pair.py` (A→B 0.8 s from the host) +
  `hdr_swap.py` → `captures/swap_pair/hdr_swap_pair.png`: highlights white, no colour estimation; residual fringes on
  thin edges come from the 0.8 s gap (air-conditioner sway).
- **In camera** the two frames would be consecutive (16.7 ms apart at 60 fps): needs IMXB to write `023A` on alternate
  frames (v3 alternation only rewrites registers the firmware writes every frame → an inject mode is needed).
- `023A` is a non-table register (no write by the fp): 01 behaves as the power-on value.
- **Single-frame colour reconstruction v2 (`hdr_color.py`, 0738 = 08, 2.33 EV, `captures/hdr_rows/hdr_color_0738_08_v2.png`):**
  B = measured attenuated value where it has signal, else G × ratio-of-means B/Gb over 63×63 cells (unbiased in noise);
  R = measured, handed over early and smoothly (0.6–0.9 of clip) to G × local R/G from unclipped cells (window grows,
  global median fallback — never 0). Highlights white and textured, no fringes; R in the clipped 32 % of cells is
  estimated, which is the single-frame limit of this sensor's row grouping (§28).

## 30. ★ True single-frame colour HDR: `0242` bit 0 + `0738` = a 2×2-cell checkerboard (`checker_capture.py`, `hdr_checker.py`)

Found by `colscan.py` (period-4 column split over all 6825 captured frames): only `0242 = 01/03` **with 0738 on**
(`captures/swap/`) split every colour by column pair. Measured against the stock frame (mid tones, mode 10):

| 0738 = 10, 0242 = 01 | cell columns a (raw cols 0–1 mod 4) | cell columns b (raw cols 2–3 mod 4) |
|---|---|---|
| R | **0.144** | 1.011 |
| Gr | **0.114** | 1.007 |
| Gb | 1.011 | **0.113** |
| B | 0.855 | **0.120** |

- **[M] `0242` bit 0 swaps which row group `0738` attenuates every second cell column** → each colour has a full and an
  attenuated sample within 2 cells, in one frame, nothing estimated. Without 0738, 0242 = 01 alone: R ×1.21 / B ×0.85
  in columns a (a small side effect, absorbed in the per-colour k). `0242 = 20/FF` breaks the image.
- k per colour (from the frame itself): 0738 = 10 → G 0.110 (3.19 EV), R/B 0.138 (2.86 EV); 20 → G 4.09 / R,B 3.72 EV;
  **40 → G 5.01 / R,B 4.57 EV**.
- Reconstruction: per colour plane, full and attenuated samples interpolated horizontally to every cell; **one
  hand-over weight for all four colours per cell** (from the colour nearest its clip) — per-colour weights put the
  switch at different places and fringe every edge. Output at cell resolution (3032 × 1011 in mode 10); the
  attenuated half costs horizontal resolution in the highlights only.
- Use: two direct writes (`0242 = 01`, `0738 = V`), latch at once, per frame; `0738 = 00`, `0242 = 00` restore.
  Residual: isolated bright specks in the highlights (attenuated samples ×20–30 amplify hot pixels → median them).
- **Fusion v2 (`hdr_fuse.py`)**: per colour plane, radiance = raw/g with variance (READ² + SHOT·raw)/g²; each cell =
  inverse-variance mean of itself and its left/right neighbours (other gain), neighbours weighted down across edges
  (exp(−z²/2τ²), z in noise units); hot attenuated samples replaced by their same-gain up/down mean before ×1/k;
  **one joint clip map for all colours** (any full-gain sample ≥ 85 % of clip in the cell or its neighbours drops the
  full samples of every colour). Against the hard switch: no white specks, finer texture in the highlights, no
  colour fringe; remaining: a 2-cell staircase along steep high-contrast edges (`captures/checker/crop_old_vs_fuse2.png`).
- **Reconstruction v3 (`hdr_cd.py`)**: (1) isolated hot samples (above all four same-gain neighbours by 4σ and 1.5×)
  replaced, ~0.1 %; (2) per-colour, per-column-parity gains measured against the full green (removes column-period
  stripes); (3) **G per cell from its own two greens** — full one faded out smoothly 0.70→0.85 of clip using the
  brightest full sample of the cell and its neighbours; the attenuated green **centred with [1,2,1] across cell
  columns**, because it alternates between the Gr (top-right) and Gb (bottom-left) positions and otherwise zig-zags
  one pixel diagonally — that was the comb on slanted edges; (4) R, B in the colour-difference domain (D = X − G) from
  the own sample and 8 neighbours, inverse-variance × green-similarity weights. Result
  (`captures/checker/crop_fuse_vs_cd.png`): no specks, no comb, neutral highlights; a faint purple band remains along
  the dark side of bright edges, in the full→attenuated hand-over zone.

## 31. Synthesised readouts on the fp (batch writes after the mode-10 set) — `readout_test.py`, `sensor_read/batch.S`

> ⚠ 2026-10-21 訂正：本節 L2b「4160×2160 @ 96 fps」低於最小幀長公式，很可能不實（§49）；隔列失效的原因見 §38/§49（前端處理寬度）。


`batch.S` writes a register table in one call (stock ch1 transaction, IRQs masked per write); the frame is grabbed in
the same fast session; a `poff 1` reset undoes everything. Base: mode 10 (6064×2022 window, 12-bit, HMAX 445).

| test | writes | result |
|---|---|---|
| **L1 window + VMAX** | output window 0022–0025 (1010 rows), receiver window, SoC VMAX | **6064×1010 1×1 at 107.6 / 140.6 fps** (VMAX 1500 / 1150), frames intact (corr 0.998 vs 60 fps, level ×1.00) [M] |
| **L3 vertical-only 2:1** (Z MODE21) | 30 regs (Family B vbin-2 + `0242=2C 0278=04 0279=01 027B=04 08B6=01 08B7=68`) + `0003=00`, receiver 1500 rows | **works**: twice the vertical field at full 6064 width [M]; OB rows shrink 40 → 5; **black offset shifts** (darks clip at 0) → needs `005C/5D` or the CRCT pedestal retuned. Receiver 2062 rows never completes (sensor sends fewer) |
| **L2a 4160 crop 12-bit** (Z MODE4) | 5 regs: `0001=2C`, drive window `0728/29=03E7`, `072A/2B=0439` + `0003=00` | **works**, receiver can stay 6064 wide (right ~1/3 padded black) [M] |
| **L2b 4160 + 11-bit fast ADC** (Z MODE5) | 77 regs (MODE4 + fast Family A) | works at HMAX 445 and 400 with the receiver at 6064; **HMAX ≤ 360 needs the receiver width cut to 4176** (`0x3010000C = 0x15C`) and the BUFA0 window redone; then **HMAX 335 works (4160×2160 ≈ 96 fps)**; **HMAX 330 → every other line empty** (the sensor cannot finish a line in 330 cycles here) [M] |

- `0001` (Z CAM table): format × output word — 29/2A 6064 14/12-bit, 2B/2C 4160 14/12, 2F 2020 (h-bin 3),
  39 3032 (2×2), 3B 3032 h-bin 2 v-full, 30/31 v÷6, 34–36 strips; the 11-bit ADC uses the 12-bit word code.
- **L7 (14-bit 2×2)** needs a 14-bit output word (no 14-bit code for 3032 exists in any table; 38 would be the
  pattern) **and** the receiver/CRCT in 14-bit unpacking — SoC side solved offline in `notes/L7_14BIT.md`
  (per-mode link key: `0x30100800` 0x…11→0x…13, `0x300E10B4` 2→3, BUFA enum 1, HMAX 911; `decode14.py`), live test pending.
- **[M, hdr_ml.py analysis] The attenuated group is spatially shifted:** block matching (same colour, full vs attenuated)
  shows the attenuated sample in output row y comes from physical row **y + 0738** (G: 0x10 → 16.8, 0x20 → 32.3,
  0x40 → 64.0 rows); R/B drift an extra ~5 rows top-to-bottom (per-colour linear fit). Full-gain samples are aligned
  with stock. The dark band / bead colour rings of v1–v4 were this misregistration, not the blend.
- **[M] Attenuated/full ratio falls with level** (R: 0.085 at 100 DN, 0.077 at 1000, 0.068 at 3500; full gain stays
  linear vs stock 0.995) → per-colour monotone LUT, not a line. Frame-pair noise: attenuated read noise ≈ 70 DN²,
  shot term ≈ 0.15 DN/DN (full 1.6–2) — behaves like the same charge read at lower gain, not a shorter exposure [I].
- **[M] Checker-only defect:** column phases col%16 = 5 (also 1, 9) misread on steep vertical gradients (−15…−17 % of
  the gradient) → period-16 comb below bright edges; clamped to the range of same-colour same-gain neighbours ±4 cols.
- `hdr_ml.py` (v5): register the attenuated group by the measured shift → one radiance scale (LUT) → hot/cold and
  column-phase repair → trust maps (full fades 0.80→0.93 clip on the 5×5 maximum; attenuated kept only where full is
  clipped or the alias map says it carries detail) → replace untrusted pixels from same-colour other-gain neighbours
  (G directional, R/B colour difference) → chroma median → one Hamilton–Adams demosaic in asinh space. ~8 s/frame.
  References and cr2hdr formulas: `notes/HDR_RECON_REFS.md`. In-camera merge must buffer 0738 rows.

## 32. What the attenuated group really is: an exposure-proportional low-gain read with a SMALL ceiling (`calib_att.py`, `calib_headroom.py`)

Exposure sweeps (SHS forced per frame through IMXB, 0242 = 01, 0738 = 0x20, attenuated rows registered by 32 rows):
- **[M] Not overflow, not digital gain:** att/true is constant over exposure (0.056–0.068 for E = 40…325 lines, AE gain)
  and the attenuated samples keep rising after the full group clips (up to true ≈ 19 400 for G vs clip 3841).
- **[M] Its own ceiling is small and fixed in charge:** it tops at ≈ 455 DN at the AE gain, at ≈ 20 DN at 0 dB
  (gain forced through 3D–40, LCG): i.e. **≈ 600–800 DN of full-group signal at 0 dB, about 1/5 of the 0 dB range**.
- Headroom over the full clip therefore depends on the analog gain only: AE gain (live view): G +2.34 EV, R/B +1.65 EV;
  +12 dB: −0.5 / −1.3 EV; **0 dB: the attenuated group saturates 2–4 EV below the full clip — no HDR benefit at base
  ISO**. Usable as a highlight keeper only above ≈ +14 dB analog gain (headroom ≈ log2(gain / 5)).
- `0738` sets the scale (k) but not the ceiling: larger V only maps the same small capacity lower (the "+5.9 EV" of
  0x80 is k, not usable range). Shutter shorter than V lines breaks the attenuated read (E = 20 < 32: att jumps ×20).
- k depends on level and on the gain setting (att/true at 500: 0.066 G at AE gain, 0.055 at +12 dB, 0.031 at 0 dB):
  the coefficient must come from a per-gain LUT (`captures/calib20/att_lut.json` for the AE gain case).
- **[M] Read time (flicker test, `flicker_timing.py`, 120 Hz LED, E = 300 lines, sinusoid phase fit of frame-ratio
  band profiles):** the attenuated sample placed in output row y carries the flicker phase of physical row y + V:
  0738 = 0x00 → 0.0 rows (15 pairs, spread 0.2), 0x20 → −36 (3 pairs, spread 16), **0x40 → −59.5 (15 pairs, spread 8.8)**.
  So it is **not an early peek**: the pixel of row y + V is read at its own time through a second, low-gain,
  small-swing path, and its value is output V rows early. Together with §32: a second readout path (ceiling scales
  with analog gain, not with HCG → a voltage-swing limit after the FD, before the analog amplifier); 0738 = row
  address offset of that path (and its gain falls with V); 0242 bit 0 = which column pairs use it; 023A bit 0 = which
  row of the shared pair. Probably a Sony fast/pre-read path, not a designed dual-gain HDR.
- **L3 black fixed:** with `0018 = 0x12` (36 inserted dark rows) the CRCT clamp again sees only dark rows: black 255,
  darks unclipped (min 174). Vertical-only 2:1 is complete.
- **L4 vertical-only 1×3 works** (mode 10 base, `--set none` + the mode-139 Family B values for vbin 3 + the MODE21
  "no horizontal merge" set `0242=2C 0278=04 0279=01 027B=04 08B6=01 08B7=68` + `0003=00 0018=12`): the image is
  squeezed 3:1 vertically at full 6064 width, black fine (`captures/l4/v3/`). Not in any Sony/Z CAM table.
- **L6 checkerboard HDR in 3×3 binning (mode 8):** both column groups mix attenuated and full rows in the vertical
  sum; per colour the two groups differ by only ~1 EV (0738 = 0x20: R 0.42/0.80, Gr 0.79/0.38, Gb 0.79/0.38,
  B 0.33/0.62) → spatial HDR is a 1×1-only feature (as the brief assumed).
- **[M] Stock ISO 3200 (CINE live view, set on the camera): analog 26.4 dB (code 3900, ×21), HCG off, 041F 0E, 05E2 01,
  05A6/05A8 29/27** (`captures/iso3200_bus/`). Exposure sweep with exactly these gains, 0738 = 0x20, frames up to 4×
  long (`captures/calib_iso3200/`, after AF): attenuated ceiling ≈ 270–290 DN; **headroom over the full clip:
  R/B +2.2 EV (plateau reached), G ≥ +3.8 EV (range ended before the plateau)** → **colour latitude at ISO 3200:
  about +2.2 stops**, luminance ≥ +3.8.

## 33. Arbitrary horizontal crop on the SoC receiver — measured (`hcrop_test.py`, `captures/hcrop/`)

`0x3010000C = (x1 / 12) | (x0 / 12) << 16` — **low half = END column, high half = START column, both in 12-px units**
(FUN_c0635ed8; writing a width into the low half shrinks the BUFA line and overflows once x0 > width). After the
write: stop BUFA0, redo its window (F_WINDOW reads the receiver), restart. Mode 10, 3000-px window at
x0 = 0 / 1200 / 2400 / 3060: content found at exactly 0 / 1200 / 2400 / 3060 px of the full frame (corr 1.000);
BUFA width 2992 px (line = 1122 words; BUFA trims to its 16-px packing). For x0 not a multiple of 12, the stock code
also sets `0x300F10C0[19:16] = x0 % 12` and `0x300F021C = 12 − remainder` (not tested).
**Together with §15 (vertical): crop is arbitrary in both directions; only the vertical one shortens the readout.**

## 34. 感光元件 2×2 vs 垂直 2:1 + 主機水平平均（⚠ 已被 §35 取代：此次垂直 2:1 暗部被截、無幀對、無 MTF 去雜訊；「2×2 較軟」不成立）（2026-10-21，`captures/bin2/`，`offline/bin2_compare.py`）
同場景、同 AE、皆 12-bit HMAX 445、皆由 mode 10 合成（`l7.py t2 … 0x39 12 12` 與 `l7.py vhdr … 0`）。
- [M] 雜訊（平坦區 G，調到同亮度）：比值 vbin2h/2×2 = 0.95–1.10 → **感光元件水平合併沒有雜訊優勢**，等同數位平均。
- [M] OB 雜訊：2×2 4.08；vbin2 原始 4.4 → 平均後 3.13（√2 ✓），換到同刻度 3.77。
- [M] 細節：G 高頻能量 2×2 32.2、vbin2+平均 42.5（+32%）→ 感光元件水平合併較軟（核心較寬或相位不同）[I]。
- [M] 亮度：2×2 約 ×1.2；Gr/Gb 比值不一致（1.36/1.07），對位 dx 為奇數 → 水平合併的取樣中心與 (0,2) 配對不同，細節待釐清。
- 捲簾相同（列數、HMAX 都相同）。感光元件 2×2 的唯一優勢：有快速等級（HMAX 330–360）；垂直 2:1 全寬快速最低 400。
- 未做：真正的 RWZM 1/2（此處用理想盒式平均模擬）。

## 35. 所有感光元件合併 vs 1×1 數位平均（2026-10-21，`bins.py`，`captures/bins/`，`offline/bins_compare.py`）
同場景（靜物）、同 AE，都由 mode 10 合成（005D=05 墊黑），每種兩張連續幀；不重開——拍完寫回 0018/005D，切回 mode 8 時韌體重寫整張表（`m10_end` 與 `m10_1x1` 雜訊比 1.00、MTF 1.00 驗證）。
比較基準 = 1×1 同色盒式平均到同尺寸。雜訊 = 幀差（時間雜訊），換成同場景刻度；MTF = 去雜訊功率譜比，0.1–0.3 cy/px 可信，0.4 以上雜訊太大不採用。

| 讀出 | 雜訊比（暗→亮） | MTF x / y @0.3 | 推論 |
|---|---|---|---|
| 垂直 2:1（vbin2，12） | 1.03 → 1.00 | 1.04 / 1.01 | 兩列全用，等同數位平均 |
| 垂直 2:1 14-bit | 0.69（曝光 ×2.05，HMAX 911 而 AE 未更新）→ 換算後 ≈ 0.99 | 1.05 / 1.01 | 讀出雜訊優勢在此亮度看不出 |
| 水平 2:1（`3B`） | 1.14 → 1.13 | 1.05 / 1.13 | 非等權（約 3:1）或部分取樣 [I] |
| 原廠 2×2（mode 98 表） | 1.18 → 1.13 | 1.05 / 1.02 | 同上，誤差來自水平那一半 |
| 垂直 3:1（vbin3） | 1.27 → 1.24 | — / 1.09 | ≈ √(3/2)=1.22：三列只用兩列 [I] |
| 原廠 3×3（mode 139 表） | 1.45 → 1.30 | 1.04 / 1.10 | 水平+垂直兩者疊加 |
| 原廠 3×3 快速（mode 8 原生） | 1.55 → 1.35 | 1.04 / 1.09 | 快速 AD 再多約 5% |
| 合成 2×2 快速、3×3 快速、3×6 | — | — | 擷取壞（半數相位空白/亂碼），合成缺東西，待查 |

- 結論 [M]：**感光元件合併從不比 1×1 數位平均乾淨**；垂直 2:1 打平，其餘多 13–55% 雜訊、略銳（有效樣本較少 → 疊紋風險較高 [I]）。感光元件合併換到的是捲簾與幀率，不是畫質。
- 產品規則：「品質」= 1×1（或垂直 2:1，免費）+ RWZM/數位縮放；「低果凍」= 感光元件合併/快速 AD。
- 未做：真 RWZM 的核心（是否等同盒式平均）；同光量 12 vs 14-bit 暗部雜訊（要修正 14-bit 的曝光）。
- [M] 邊緣/鋸齒目視（QR 碼，`offline/bins_card.py` → `captures/bins/card_part*.png`）：垂直 2:1（12/14）、水平 2:1、原廠 2×2、原廠 3×3、mode 8 與數位平均幾乎看不出差別（感光元件版略利）；
  **垂直 3:1 例外：邊緣有明顯橙/藍彩邊與鋸齒** → 各顏色的取樣中心不同列（與「三列只用兩列」一致 [I]）。原廠 3×3（mode 139/8）沒有這個問題，所以原廠的 3 列組合與我們的 vbin3 合成不同。

## 36. 合併內的暫存器掃描（2026-10-21，`binsweep.py`，`captures/binsweep*/`，`offline/binsweep_eval.py`、`binsweep_abs.py`）
基底：合成原廠 2×2（mode 98 表）與 vbin3；每暫存器一個 session、同 session 對照、每值兩幀；不重開（切回 mode 8 韌體重寫表）。量測精度 ±0.5%。
**先檢查每輪對照幀的絕對雜訊**（binsweep_abs）：第一輪 027A 對照偏吵（假的 −2%）、027B/027E/072C 對照幀亮部雜訊 ×4–10（場景在動）→ 重掃後 027B 任何值都無效。
- [M] 2×2 內約 60 個暫存器（0716–079F、0274–027F、0240–0244、08B4–08B9、001C、0058）：**沒有任何值讓合併用到更多光而不壞顏色**；水平合併的 13% 損失找不到控制。
- [M] `0737`＝上排（偶數輸出列）的垂直取列：00 → 只剩一列（雜訊 ×1.37）；01/02 原值；03/04 → 亮度 ×0.73、雜訊 ×0.95；≥05 → 四個相位都變（R/B ×1.05–1.36、G ×0.43–0.85，雜訊 ×0.62–0.85，相關 0.98–0.99）= 混入**別的顏色的列**（色彩串擾），不是更完整的同色合併。值兩兩相同（bit0 無效）。
- [M] `073A`＝下排（奇數輸出列）的對應：01 → 下排 ×0.95；08/09 → ×0.6；≥0A → 下排幾乎全暗。
- [M] `0738`（=下排的列錯開，§30 HDR 用）在 2×2 內：00 → 雜訊 ×1.2；≥01 多為破壞。
- 結論：感光元件的垂直合併只能選「哪些列」，同色更多列 = 換感光元件縮減倍數；沒有「等權更多樣本」的開關。

## 37. 垂直 3:1 彩邊的原因（2026-10-21，`captures/bins3/`，`offline/colshift.py`）
彩邊指標：R/B 平面相對 G 的垂直位移（格列，已扣 CFA 幾何），線性化最小平方；1×1 ≈ 0.05、原廠 3×3 ≈ 0.1。
- [M] vbin3（L4 = mode 139 Family B + MODE21「不水平合併」組 `0242=2C 0278=04 0279=01 027B=04 08B6=01 08B7=68`）：R +0.45 / B −0.50 → 彩邊。
- [M] **拿掉那組（全回 0，與原廠 139/8 相同）→ R +0.00 / B +0.01，彩邊消失**；雜訊比仍 1.23–1.26（三列用兩列不變），MTF 正常。
- [M] 反過來，垂直 2:1 拿掉那組 → R −0.37 / B +0.37 出現彩邊；保留則 0.08/−0.09。
  → 那組不是「不水平合併」開關，而是**兩列相加時的同色配對設定**：vbin2 必須有、vbin3 必須沒有。（L3/L4 的「Z MODE21 組」標籤要改。）
- [M] `0734=05` + `0737=00` 一起（v3_fix）：亮度 ×0.45–0.58、雜訊 ×2.2 → 壞；單獨各自只減半彩邊（§36 掃描）。
- 產生器規則：vbin2 → 加那組；vbin3 → 不加。

## 38. 合成快速等級（2×2 快速、3×3 快速）仍失敗（2026-10-21，`captures/bins4/`）
- [M] 不加重啟：每隔一列空白（偶數列 = 256 常數），最低位元仍會變化。
- [M] 加 `0011` 0→1：**11-bit AD 已啟動**（最低位元全 0），但每隔一列空白依舊。
- [M] 再加 `00D1=FA`（mode 8 切換時的值；mode 10 是 FB）：不變 → `00D1` 不是原因。
- [C] ROM 時序表 mode 139 vs 8 只差 HMAX/VMAX，SoC 端無其他差異。
- 待查：從 mode 8 出發（原生快速）合成，反向找出 mode 10 → 快速時缺的那一項；或 HMAX 360/400 看是否只是列時間不足。
- [M] 2026-10-21 續（`captures/bins5–7/`）——已排除的原因：
  - 位置：合成版第 k 個有效列 = 原生第 2k+1 列（2D 相關 0.9996），水平 3:1 正確 → **感光元件輸出列有一半沒進記憶體**。
  - HMAX 階梯（快速設定、mode 10 出發）：445/400 正常，370/350/340 隔列 → 極限約 380 週期（原生 330 正常）。
  - 不是：`0018`（原生加了正常、合成拿掉仍壞）；`00D1`；感光元件寫入值（CSV 與匯流排 161 筆完全一致）；寫入順序（先停後寫、先設 HMAX 再重啟都無效）；
    接收端 0x54/0x60/0x8C、CRCT 29 個幾何暫存器（0x300F02xx/22xx/068x）、VMAX、`0x30200054`——合成版全改成 mode 8 值仍壞；反向把 mode 10 值套到原生 mode 8 也不會壞。
  - 唯讀差異清單：`captures/soc_m8_m10.json`、`crct_m8_m10.json`、`isp_m8_m10.json`（BUFA 0x3018、0x301A 等 65 筆，多為視窗/位址）。
  - 從 mode 8 出發合成一般 3×3（139）可行；從 mode 8 出發合成 2×2 快速沒出圖（接收端幾何待查）。
  - 下一步：(a) 以 mode 8 為快速等級的基底（實用路線）；(b) 追 mode 10 獨有、mode 8 不需要的狀態：把 `isp_m8_m10.json` 剩餘可寫差異逐組套用；或以 mode 10 → mode 8 的韌體切換流程追 SoC 寫入。
- [M] 續（`captures/bins8–9/`）：BUFA `0x30180228`（可寫，無效）、`0x30180328`/`0x301803E4`（唯讀）、接收端 `0x30100120`/`0x30100200`（mode 8 值，無效）→ 皆排除。
- [M] **接收端狀態暫存器（拍完當下讀，`rxstatus.json`）給出方向**：
  | | 原生 mode 8 | 合成 HMAX 400（正常） | 合成 HMAX 330（隔列） |
  |---|---|---|---|
  | `0x301005D8` | 0xE38 = 3640 | 0x57E = 1406 | **0x1518 = 5400 = 2 × VMAX 2700** |
  | `0x30100588` | 0 | 0x10000001 | **0x10000000（bit 28 旗標）** |
  閒置時 mode 10 的 0x5D8 = 0x81A = 2074 ≈ 送出列數 → 推論 0x5D8 = 每幀收到的列同步數 [I]。合成 330 時接收端每幀收到**兩倍**的列同步 →
  感光元件每個 HMAX 送出兩個列同步（一實一空），問題在感光元件端的列產生，不在 SoC [I]。bit 28 可能是錯誤/溢位旗標 [I]。
- [M] 續（`fastprobe.py` → `captures/fastprobe/probe.txt`；`captures/bins10/`）：
  - 快速組 78 個暫存器逐一換回一般值（每次重啟）：列數仍 5400、仍隔列 → 不是單一 Family A 暫存器。
  - 一般 AD（139 表）在 HMAX 445→330：列數恆為 1406（不加倍）；400 以下影像壞（一般 AD 太慢，預期）。
  - **完全複製韌體 10→8 切換的 165 筆匯流排寫入**（不加 0018/005D）+ mode 8 的 SoC 值：列數 1370、旗標 0（加倍消失）——**但仍隔列空白**。
    → 「列數加倍」是我們加的 0018/005D 或只寫差異所致，與隔列無關；隔列的原因仍在 SoC 管線某處停在 mode 10 的設定。
  - 下一個嫌疑：`0x301A` 區塊（另一條列處理/DMA 管線，mode 10 時 `0x301A0250=3`、`0x214=0x5EC` 與 CRCT 的「3 段 / 6064 寬」同型）。
    它有 DMA 指標，高度/寬度改大可能寫出緩衝區 → **先離線找韌體設定 0x301A 的函式再上機**。
- [M] 續：`0x301A` = **BUF-D**（韌體 dump 的區段名；0x3018 = BUF-A）。CRCT_TOP 之外還有 ROUTE / SRAM_MGR / WAIT / V LATCH / SLEEP（硬體在 0x3011 0x10–0x1D0，讀回 0）。
  影子區 0x3021 mode 8 vs 10 的差異：`0x30210028` 0x110700/0、`0x3021004C` 1/0、`0x302100AC` 0x110000/0、`0x3021011C` 0x111101/0x101101（`captures/shadow3021_m8_m10.json`）。
  寫入這 4 個 mode 8 值（加在完整 replica 上）→ 仍隔列。**未確認寫入是否被韌體每幀蓋回**（影子由設定函式寫、register-DMA 套用）。
- [?] 2026-10-21 一次相機在兩輪之間自行回到 PTP 模式（冷開機）；原因未知（可能是 bins10 的 rep8 狀態或使用者操作）。

## 39. ★ 虛擬模式可用（2026-10-21，`vmode.py`，`captures/vmode/`）
- 原因（`MODE_TABLES_CONSUMERS.md`）：每幀 AE 回呼 `FUN_c0313658` 依「目前模式 id」的 R38 列重寫 DCLP（我們叫 CRCT 的那塊）；id 還是 10 → 每列 506 字、
  12 px/clk、96 MHz → HMAX 下限 379.5，正是 §38 的掉列門檻。手動補暫存器在結構上不可能成功。
- 做法：8 張表（TIM META R10 R28 R38 R14 R68 + REG）整份複製到配置器記憶體，只換 host id（10 = 放大）那一列，改描述子 0xC2F1E654 與 REG 物件 0xC343B67C 的指標，
  進放大 → 韌體跑完整 SetImgMode_s；拍完指回 ROM 表並釋放。不碰設定區，重開也會還原。
- [M] 驗證：mode 8 的列放在 id 10 下 → 韌體回報 `MONIT1_60_LOWP2, 2016x1344`、11-bit（LSB 全 0）、每列都有影像、接收端旗標 0。
- **§31–§38 的合成讀出都是在 mode 10 的 DCLP/時脈/接收設定下測的**：HMAX < 380 的結果、黑位/暗區截斷、像素位置類結論都要用虛擬模式重驗；
  同一輪內的相對量測（雜訊比、MTF、彩邊）受影響較小但仍要複驗。

## 40. 合併比較重測——虛擬模式（取代 §35 的原廠合併部分）（2026-10-21，`captures/vbins/`，`captures/vbins_cmp/`）
每種讀出都由韌體完整切換（`vmode.py test DONOR`），快門 16663 µs、增益 936 全部相同。基準 = 同次 1×1（mode 10）同色盒式平均。
| 讀出 | k | 雜訊比 暗(10–40) → 亮(640–2000) | MTF x / y @0.3 |
|---|---|---|---|
| 1×1 結束對照 | 1.00 | 1.00 → 1.00 | 0.99 / 1.00 |
| 原廠 2×2（98） | 1.02 | **1.40** → 1.14 | 1.04 / 0.99 |
| 2×2 快速（58） | 1.02 | **1.56** → 1.15 | 1.05 / 1.00 |
| 原廠 3×3（139） | 1.02 | **1.91** → 1.34 | 1.06 / 1.14 |
| 3×3 快速（8） | 1.02 | **2.12** → 1.36 | 1.07 / 1.17 |
| 3×6（140） | **0.51**（6 列只加 3） | 3.13 → 2.34（40–160 起） | 1.10 / 1.14 |
| 3×6 快速（12） | **0.64** | 2.86 → 2.11 | 1.11 / 1.14 |
- 與 §35（mode 10 底下手動合成）比：亮部幾乎相同，**暗部差很多**——§35 的暗部數字被錯誤的 DCLP 設定污染，作廢。
- 暗部比值大 = 感光元件合併後只經過一次讀出雜訊（類比相加再 AD），而數位平均 N 個像素讀出雜訊降 √N；亮部比值 = 有效樣本較少（非等權/跳列）。
- 結論不變但更強：**感光元件合併在暗部比 1×1 數位平均差 1.4–2.1 倍**；快速 AD 再差約 10%。3×6 只用一半的光。
- 彩邊指標（colshift）在虛擬模式擷取上受首列奇偶影響，數值不可信，待改成「各色平面分別對 1×1 對位」。

## 41. PDAF：Sony 的 ZAF 暫存器整組寫入——無作用（2026-10-21，`zaf.py`，`offline/zaf_eval.py`，`captures/zaf_set/`）
- 虛擬 V1（mode 10 列，1×1 12-bit），`imager pdaf_cor_off 1`，每步 DCLP 開/關、第 1/10 幀，累加寫入（照 a7 III 的 SetExposure_ZAF / SetRead_ZAF）：
  exp（000B/0C=0x0700、000D/0E=0x0100、000F/10=0x0100、0036=FF）→ read（0047–004A=0x0100 兩組）→ gate（0424=0E、05E2=03）→ sel1（0036=01）→ gate2（0424=1B）。
- [M] 每一步對兩張參考：全域指標無變化；接收端列數 2074 不變（沒有多送列）；>6σ 稀疏像素數 1397–1488，與參考對參考 1434 相同，
  兩張參考都判出的 65–83 個在五步之間**沒有共同像素**（隨機，非固定相位像素）；位置無週期。
- 結論：fp 的 IMX410 對 Sony 的 ZAF 路徑沒有可見反應。加上韌體閘門與靜態 RAW 無遮罩的舊結果 → PDAF 停止（CAPABILITY_MAP）。

## 42. 14-bit 線時間的下限（2026-10-21，`half14.py`，`offline/half14_eval.py`，`captures/half14/`、`half14_fine/`）
- 虛擬 V2（mode 6 列，14-bit，保留原感光元件窗），直接寫 SoC HMAX（0x30100004）。
- [M] 911→863：影像正常（相關 0.996，雜訊、黑位不變，亮度隨曝光時間 ∝ HMAX 下降）；857：第二幀雜訊加倍（撕裂/不穩）；
  **850 起 AD 失效**（整幅 3347、暗區 4075）；800/750 影像錯亂；700 不出圖。
- 結論：14-bit 的 AD 只能縮 ~5%。「半快速 14-bit」不能只靠 HMAX，要改 Family A 的斜坡/計數器（042D、0441、0585、05D8、0511、0433–043E、0516–0523 在 14/12/快速三套中隨線時間縮短）。
- 未量：亮部最大碼（場景最高只到 1350/4095，看不出截頂）。
- **續（`ramp14.py`，`captures/ramp14/`；`half14.py --word 2B --rxw 4176`，`captures/half14/V2_w2B/`）**：
  - [M] 只把 Family A 的「時間計數器」27 個換成 12-bit 值：911 就壞（雜訊爆、OB 亂）→ 計數器必須跟其餘設定配套。
  - [M] 換「解析度組」10 個或整組 37 個 Family A 成 12-bit 值：911 正常，但**輸出仍是真 14-bit**（低 2 位元均勻使用），800 一樣失效 → AD 位數與線時間下限由 `0001`（29）決定，不是 Family A。
  - [M] 14-bit 4160 寬（`0001=2B`、接收端 4176）：850 一樣失效（≤700 時隔列空白）→ **下限與寬度無關＝欄 AD 轉換時間，不是介面頻寬**。
  - 結論：14-bit 線時間硬下限 ≈ 860 週期（911 的 94%）；半快速 14-bit 不可行。14-bit 最高幀率 = 72 MHz /(≈860 × 列數)。
- **⚠ 更正（2026-10-28，isp-lab 連續錄影，`validation/20261028-p6ab*`、`hsA`、`hsB`、`hsC`）：上面的 ≈860 只對單幀成立。**
  - [M] 6048 寬（`0001=29`）連續錄影、每次 5–6 幀 CDNG：870 → 12/12、12/12、10/12、6/12 壞幀（CFA 錯一列、雜訊、整幅偏移）；
    875–900 每一格都壞；905 在 h3v3 仍 2/12 壞；**911（原廠值）0 壞**（共 70 幀以上）。
  - [M] 4192 寬：860、865 乾淨（各 4 幀），p5 在 870 的 33 幀全乾淨 → 連續錄影的下限**跟寬度有關**，與上面「與寬度無關」相反。
  - 規則（isp-lab `isp_formula` R15、C 核心 `core_line_hmax`）：14-bit 光柵寬度 > 4192 時 HMAX ≥ 911；≤ 4192 維持 870。
    4192–6048 之間沒有量，所以取保守值。原因（感光元件或 ISP 接收端）未分開；單幀量法不能用來定下限。

## 43. `0001` 全值掃描（2026-10-21，`sweep0001.py`、`focus0001.py`，`captures/sweep0001/`、`captures/focus0001/`，`offline/sweep0001_eval.py`）
虛擬 V1（mode 10，原值 2A），直接寫入 00–FF，每值重啟，讀接收端列數 6 次（約每幀一次）＋抓連續兩幀，之後寫回原值確認恢復（256/256 全恢復，零卡死）。
- [M] **bit 7 不起作用**（2A=AA、3B=BB…）→ 有效 7 位元。
- [M] 列數從未加倍（最大 2086 = +12 列），接收端旗標全 0，6 次讀數從未跳動 → **沒有 DOL/一幀多次讀出格式、沒有隔幀交替格式**（至少在 `0001` 這個開關上）。
- [M] 172 個值輸出平坦（無影像）；能出圖的新值（未列在原廠表）：
  `01`、`16`（6064 寬；`16` 時間雜訊 ×5、欄狀破碎 → 可能需要別的 AD 等級/HMAX）、`18`（**5073 寬**）、`03`（**4016 寬**）、`1A`（4177 寬，同 2C）、
  `3A`（= 3B，水平 2:1）、`3D/3E`（6064 寬、2086 列）、`15`（欄條紋圖樣、靜止）、`1B`（影像亮 ×1.5、連續幀完全相同 → 疑似凍結）、`1C`（全白）。
- [M] `3D/3E` 的「兩幀不同」不是格式交替：前約 700 列 ×0.6 且整幅錯位約 110 列 → 2086 列超出幀長，幀邊界在滑動。
- 待做（FAST_READOUT 相關）：`18`（5073）、`03`（4016）寬度格式的速度下限；`16` 在快速 AD 等級下是否變乾淨。

## 44. ★ `0007/0008` = 多幀長曝光（感光元件內累積），不是第二組曝光（2026-10-21，`shs2.py`、`shs2seq.py`，`captures/shs2/`、`captures/shs2seq/`）
推翻 §14「0007/0008 ≠ 0 → 黑幀」的解讀（使用者要求重測：寫入順序/重新載入）。韌體每幀依 0005→0006→0007→0008 寫入，用 IMXB 代換保持值，匯流排記錄確認送出。
- [M] 虛擬 V1、SHS=2（接近整幀曝光），訊號（減黑 256）：0007=00 → 302；**01 → 605（2.0×）；02 → 907（3.0×）；04 → 1511（5.0×）**；08 → 2344（7.8×，亮部已截）。
  → **曝光 = (0007 + 1) 幀**。其餘幀輸出「全黑、暗區也 ≈7」＝ 累積期間感光元件不送影像。§14 的黑幀是剛好抓到累積中的幀。
- [M] 0008 bit 0–3（01/02/04/08）：一直黑（推測是幀數的第 8–11 位元 → 256 幀以上，在取樣時間內沒出圖）；bit 4–7 無作用 → 0007/0008 = 12 位元「長曝光幀數」[I]。
- 寫入後重啟（0011）與否結果相同（`n`/`r` 兩組）；寫入順序由韌體固定（低→高），代換下有效。
- 意義：感光元件原生長曝光（快門長於一幀）、只讀一次 → 一次讀出雜訊（多幀疊加是 N 次）。用途：影片慢快門、天文、夜景。不是一幀多次讀出。
- 待做：用逐幀計數器確認週期 = 0007+1 幀；與 SHS 的組合（長曝光的精確時間）；錄影/顯示鏈對黑幀的處理；0008 低位元的實際幀數。
- 續（2026-10-21，`shs2seq.py --pairs`，`captures/shs2pairs/`）：成對擷取的兩幀間隔不固定（工具每次跳過一幀），週期無法逐幀確認；亮幀比例隨 0007 下降（01 ≈0.4、02 ≈0.25、04 ≈0.3、08 ≈0.17），亮度倍數 2.0/3.0/5.0 穩定。逐幀週期待用每幀 hook 驗證。

## 45. 12-bit 一般 AD 的線時間下限與寬度無關（2026-10-21，`half14.py --base V1 --word W --rxw X`，`captures/widthspeed/`）
- [M] V1（12-bit 一般 AD，HMAX 445），格式 `2C`（4176 寬）、`18`（5076）、`03`（4020）：**三者都在 420 失效**（整幅定值），≤380 隔列空白，≤320 不出圖或全黑。
- 結合 §42：**線時間下限由 AD 等級決定，跟寬度無關** —— 14-bit ≈860、12-bit 一般 ≈430–445、11-bit 快速 ≈330（窄）/ ≈400（6064 寬時才受介面限制，§31 L2b）。
- 推論：提高幀率的槓桿只有「少讀列」（垂直裁切/合併）與「快速 AD 等級」；窄寬度只在快速等級下有幫助。
- `18` 在 445 時時間雜訊 20.6（2C 為 7.3）→ 5073 寬格式可能需要配套設定；`03` 正常（7.3）。

## 46. SoC VMAX（0x30100020）確實是感光元件幀長；最小幀長 ≈ 影像列 + ~120（2026-10-21，`vmaxreal.py`、`shszero.py`、`vmaxsrc.py`，`captures/vmaxreal*/`、`captures/shszero/`、`captures/vmaxsrc2/`）
（本節初版寫「SoC VMAX 不是感光元件幀時序」——**錯**，原因見下「陷阱」。）
- [M] 方法：IMXB 代換 SHS=4、增益 003D–0040=0（曝光 = VMAX−8 列），`imager fixed_shutter 1 100` 讓 AE 不開多幀曝光；訊號（影像−暗區）∝ 真實幀長。
  VMAX 4188/3500/2700/2300 → 訊號/VMAX = 21.2–21.6 /1000 列（常數）→ **感光元件跟著 0x30100020**。直接寫入與模式切換結果相同
  （SHS 歸零點：VMAX 4188 直接寫 → 2094 ✓；原廠 2700 → 1350 ✓）。
- [M] 模式切換只多改 `0x30100054`/`0x30100120`（∝ VMAX，0x3F↔0x7E）、`0x30100048` bit 16+、`0x30100644`；手動補寫 054/120 對曝光無影響。
- [M] **最小幀長**（12-bit 一般 AD，HMAX 445，1×1）：低於門檻時影像全黑（訊號 0），幀計數照跑：
  | 影像列 N | 可 | 黑 | 門檻 − N |
  |---|---|---|---|
  | 2022 | 2150 | 2120 | ≈ 113–128 |
  | 1010 | 1150 | 1125 | ≈ 115–140 |
  | 254 | 380 | 370 | ≈ 116–126 |
  → **VMAX_min ≈ N + ~120 列**（含 40 列暗區；其餘約 80 列為固定消隱）。254 列：72 MHz/(445×380) ≈ **426 fps 實測可成像**（訊號/VMAX 仍為常數 → 真的是新幀）。
- **陷阱（初版誤判的原因）**：AE 開著時，短 VMAX 讓畫面變暗 → 韌體用 `0x30100048` bits 26:16 開「多幀曝光」（訊號/VMAX 呈 1×、2×、3× 階梯），亮度看起來不隨 VMAX 變。
  另外 `fixed_shutter` 的 SHS 是照原廠 VMAX 算的，VMAX 小於其兩倍就變黑。量幀率一定要「代換 SHS + 鎖增益 + 固定快門」。
- 工具：>400 fps 時 BUFA0 尾端哨兵寫入來不及讀回驗證 → `vmaxreal.py` 改用不驗證寫入。
- 推論 [I]：1000 fps 需要 VMAX ≤ 72e6/(HMAX·1000)：11-bit 窄幅 HMAX 335 → 215 列 → 影像約 95 列；若能縮掉暗區列（`0018/0019`）與消隱，可多出約 100 列。
- `vmaxsrc.py` 首版切進 donor 143（18 fps）虛擬模式時卡死 shell（原因未查）；改用 donor 98 只改時序表 VMAX 則正常。

## 47. ★ 1000 fps 實測：2×2 快速 + 160 列（2026-10-21，`hs11.py`，`captures/hs11/`、`captures/hs11g/`）
- **消隱 = `0016`**（V1 1×1，254 列，`vmaxreal.py --sensor 0016=..`）：最小 VMAX 35 → 370–380、0x0A → 320–330、0x02 → 300–305
  → **VMAX_min ≈ N + 46 + 2·`0016`**（`0016` = 原廠 mode_list「vblank」的一半，§21 Family B 裡它隨 vbin 變，其實是消隱）。0x02 時影像正常、訊號仍 ∝ VMAX。
- **2×2 快速基底**（虛擬模式 donor 11：3032×2012、HMAX 330、`0016`=7、窗關 `0003`=0；KEEP_WINDOW）：
  `0003=1`、`0022/23` 起點、`0024/25`=H → 輸出 2H 列，接收端每幀列數 = 2H+30（H=100 → 230、H=80 → 190）。
- [M] H=80（160 影像列，接收端 190 列），代換 SHS=4、增益碼 3800（約 ×14）、`fixed_shutter 1 100`：
  | VMAX | 640 | 480 | 320 | 260 | 230 | 220 | 215 | 212 | 210 |
  |---|---|---|---|---|---|---|---|---|---|
  | fps（幀計數） | 346 | 454 | 688 | 840 | 963 | 973 | 1015 | **1029** | 1039 |
  | 影像位準 | 362.4 | 332.0 | 300.8 | 289.0 | 283.2 | 280.2 | 279.2 | 278.7 | 0（接收端只收到 188 列） |
  位準 = 237.1 + 0.196·VMAX（640→215 全部落在直線上，誤差 ≤1 DN）→ **曝光跟著 VMAX 走 = 每幀都是新曝光，1029 fps 為真**。
  下限：VMAX < 接收列數 + ~22 時感光元件少送列（210 → 188 列）。
- 意義：**3032×160（2×2 快速、12-bit）≈ 1029 fps 已在感光元件端實現**；H=100（200 列）下限約 255 → ~855 fps。
- 注意：`0016=02` 在此基底讓探測幀抓不到（原因未查；原廠值 7 已很小）。高幀率下 BUFA0 尾端哨兵要用不驗證寫入（hs11.py 內建）。
- 未做：連續錄製/串流（只驗證單幀擷取）；14-bit 或 1×1 的同類極限（1×1 一般 AD：254 列、`0016`=2 → ≈ 530 fps 推算）。

## 48. 幀率重驗（RESEARCH_DIRECTION #1，2026-10-21，`vmaxreal.py --donor 8`，`captures/reverify_m8/`）
- [M] mode 8（3×3 快速、HMAX 330、接收端 1370 列），標準方法（代換 SHS=4、增益 0 dB、`fixed_shutter 1 100`）：
  訊號 = 2.9 + 0.01477·VMAX，VMAX 3640→1500 全在直線上（誤差 <0.3 DN）；**1450 起全黑且接收端少送列**（1344、1294、1194 = VMAX − 106）。
- **§15「VMAX 1300 → 167 fps、幀完整」不成立**：真正下限 ≈ 1476–1500 → **≈ 146 fps**（72e6/(330×1500) = 145.5）。
  與公式 VMAX_min ≈ N + 46 + 2·`0016`（N 1344、`0016`=50 → 1490）相符。
- L1（6064×1010 1×1 @ 140.6 fps，VMAX 1151）：由 §46 的 1010 列門檻 1125–1150 判定**屬實**（餘裕 1–26 列）。
- L2b（4160×2160 11-bit @ 96 fps）：合成快速等級，待 #2 在虛擬模式重建後一起驗。

## 49. ★ 1×1 快速 AD 成立（§38 解開）＋ 讀出規則表（RESEARCH_DIRECTION #2，2026-10-21，`vmaxreal.py --fast/--timw/--r38w/--hmax/--donor`，`captures/fast1x1_*`、`captures/m8_h*`、`captures/obrows_*`）

> ⚠ 2026-10-22 訂正：本節「HMAX 320 可用」只看了曝光線性，沒看幀間雜訊；批次驗證（captures/readout_batch/）在 320 時相鄰幀雜訊 150–190（畫面損壞）→ 快速 AD 下限取原廠 330。

> 補充 2026-10-22：本節所稱「TIM 行長 +0xC」其實是**接收端 x 終點**（TIM +0xA = x 起點、+0xC = x 終點；原廠 mode 102 用 952..5128 裁 4176 寬，見 ISP_SIZE_RULES.md 補充）。

- 做法：虛擬 V1（mode 10 列）但 **時序表行長 TIM +0xC = 4180**（原 6072）、**DCLP R38 +8 = 349 字**（原 507）；進入後直接寫
  Family A 快速值（`bins.diff('8','139')`，77 筆）、`0001=2C`（4160 寬）、接收端寬 4176（`0x3010000C`低半 = 348）、HMAX。
- [M] 只改 R38 寬度、或只直接寫：HMAX < ~380 仍隔列空白（§38 現象）。**加上 TIM 行長 = 4180 才完整**（前端每行處理寬度由 TIM 行長決定，
  MODE_TABLES_CONSUMERS §1 的 379.5 = 6072 px 在 96 MHz 的下限）。單獨 TIM 是否足夠未分開測。
- [M] 1×1 快速（4160×2022）：HMAX 335/320 完整、訊號對 VMAX 線性；**300 失效**（位準不隨 VMAX 變、整幅平）。最小幀長 2120–2150（同 §46 公式）。
  → **4160×2022 1×1 @ HMAX 320、VMAX 2150 ≈ 105 fps，捲簾 ≈ 9.0 ms**（一般 AD 445 為 12.5 ms）。
- [M] 3×3 快速（mode 8）：HMAX 320 線性正常、310/300 失效 → **快速 AD 下限 ≈ 315，與合併/寬度無關**。
- L2b 重驗：§31 的「4160×2160 @ 96 fps（VMAX ≈ 2239）」低於公式下限 2160+46+70 = 2276（`0016`=35 時）→ **當時的 96 fps 很可能不實**；
  今天的 1×1 快速在 2022 列下 2150 為真（若要 2160 列需 VMAX ≥ ~2276 或把 `0016` 調小）。
- 暗區 40 列：`001A=01` 讓接收端列數 306 → 308（+2），沒有減少；暫不再追（收益 ≤ 40 列）。

### 讀出規則表（目前已實測）
| AD 等級 | HMAX 下限 | 實測依據 |
|---|---|---|
| 14-bit | 單幀 ≈ 860；**連續錄影：寬 > 4192 要 911、≤ 4192 為 870**（原廠 911） | §42（含 10-28 更正） |
| 12-bit 一般 | ≈ 430–445 | §45（4176/5076/4020 寬相同） |
| 12-bit 快速 | ≈ 315（原廠 330） | §49（1×1 4160 寬、3×3 皆同） |
幀長：**VMAX_min ≈ 影像列 N + 46 + 2·`0016`**（§46–48；1×1、3×3、2×2 快速都符合；`0016` 可降到 2，2×2 快速下 2 失效原因未查）。
fps = 72 MHz /(HMAX·VMAX)；捲簾 = HMAX·(讀出列)/72 MHz。量法一律用曝光線性（SUMMARY_2026-10-21 §3）。
寬度不影響線時間（AD 限制），但 1×1 快速需要 TIM 行長與接收端寬度一致才能低於 380。

## 50. ★ 連續 1029 fps 交付到 DRAM 不掉幀（RESEARCH_DIRECTION #3，2026-10-21，`hs11.py --burst`、`hsburst.py`，`captures/hsburst/`）
- 方法：§47 的條帶（donor 11 2×2 快速、H=80 → 160 影像列/接收 188 列、3032 寬，SHS=4、增益碼 3800、`fixed_shutter 1 100`），
  IMXB v3 `frame_cb`（BUFA0 完成中斷）每幀換緩衝（16 個）並記 64 個完成時間（µs）。
- [M] 結果：
  | VMAX | 理論間隔 | 實測中位 | 最小/最大 | >1.5× | 16 幀位準 | 相鄰幀雜訊 |
  |---|---|---|---|---|---|---|
  | 640 | 2933.3 µs（341 fps） | 2933 | 2890/2979 | 0 | 355.8–356.9 | 5.66–5.69 |
  | 260 | 1191.7 µs（839 fps） | 1191 | 1186/1198 | 0 | 285.6–286.7 | 4.49–4.51 |
  | **212** | **971.7 µs（1029 fps）** | **971** | 929/1046 | **0** | 275.7–277.7 | 4.34–4.35 |
  → 每一幀都在中斷層準時完成、無掉幀；16 幀內容各不相同（相鄰差雜訊穩定非零）、位準穩定。完成計數在等待期間持續增加（≈1030/s）。
- 資料率：855 KB/幀 × 1029 ≈ **880 MB/s 進 DRAM**（BUFA0 DMA 撐得住）。
- 限制：frame_cb 只有 16 個緩衝、64 筆時間 → 已證實「交付」；長時間連拍需 RAM 環形緩衝（配置器上限決定秒數）與之後的搬出（USB ≈380 MB/s、SD ≈94 MB/s）
  → 實用形式 = **RAM 連拍（例：1 GB ≈ 1.2 s @1029 fps 全寬 160 列；裁寬可延長）**，或降幀率/裁寬做串流。

## 51. PDAF 結案（RESEARCH_DIRECTION #4，2026-10-21，`pdaf_t1.py`，`captures/pdaf_t1b/`、`captures/pdaf_t2/`；設計 `notes/PDAF_A7III_DIFF.md`）
- 離線（a7 III 反組譯）：ZAF 不是模式表裡的開關；ZAF 欄（5–18）與非 ZAF 欄只差 `0001` 格式碼、**`001C`（ZAF 欄 00、其餘 03）**、`0728–072B` 垂直窗；
  §41 的寫法有三個缺陷（ZAF 快門 0x700 > VMAX/2、0008 低位元 = 長曝光、05E2 被每幀重寫）。
- [M] T1：V1 + `0001=1A`（4177 寬，Sony 欄 16）+ `001C=00` + ZAF 組（000D–0010=0、0036=01、0047–004A=主增益碼 0x400），
  主 SHS=4、增益以 IMXB 代換固定；ZAF 快門 4 ↔ 0x542、選擇器 FF、ZAF 增益 0 ↔ 0xD00 包圍。
  **差分 = 雜訊底**（>6σ 13–19 點 vs 同設定重拍 10 點，無共同點、無週期；列/欄均值差 ≤0.8 DN）。
- [M] T2：donor 9（3×6 快速）+ `0001=10`、`001C=00` + Sony 欄 11 表內 8 值（0016=02 0043=00 0057=06 0058=30 0484=25 04E2=BF 056C=0D 0571=AA），同樣包圍：**差分 = 雜訊底**（>6σ 2 點 vs 5 點）。
- 副產品：`001C` = 開頭虛擬列數（每 1 = 2 列；V1 由 05→00 接收列數 2068→2058）。
- **結論：依停止規則 PDAF 結案**——fp 的 IMX410 對 Sony ZAF 讀出協定（格式、001C、快門/增益/選擇器）在兩種最接近的讀出下都無可量反應。
  證據：韌體閘門（fp-af-assist 筆記）、靜態 RAW 無遮罩、§41、本節 T1/T2。重開條件：出現新的硬體證據（例如 OTP/型號差異資料、另一台 fp 的不同結果）。

## 52. 1920×1080 高幀率實測：2×2 快速裁切 ≈ 192 fps（2026-10-21，`hs11.py --h 540 --hcrop 1920`，`captures/hs1080/`）
- donor 11（2×2 快速），感光元件窗 H=540 → 1080 影像列（接收 1110 列），接收端水平裁 1920（視角 = 感光元件 3840×2160，1.58× 裁切）。
- [M] HMAX 330：訊號/(VMAX−8) = 232–234 恆定（VMAX 1300→1135 線性）；**1130 起少送列** → **VMAX_min 1135 → 192 fps**；
  連拍 VMAX 1140（191.4 fps）：64 間隔中位 5225 µs = 理論，最小/最大 5220/5229，無掉幀；8 幀位準 519.4–519.5、相鄰幀雜訊 7.6（皆新幀）。
- [M] HMAX 320（2×2 快速）：位準不隨 VMAX 變、相鄰幀雜訊 117（影像損壞）→ **2×2 快速 AD 下限在 320–330 之間**（1×1/3×3 快速 320 可用，§49；2×2 加總較慢 [I]）。
- 3×3 快速 1920×1080：mode 8 開感光元件窗（0003 b0）會停輸出（§20），無法垂直裁 → 只能讀滿 1344 列 ≈ 146 fps（§48），寬度可由接收端裁。
- 資料率：1920×1080×12 bit ≈ 3.1 MB/幀 × 192 ≈ 600 MB/s 進 DRAM（實測無掉幀）；只能 RAM 連拍，不能即時寫卡。

## 53. 多幀長曝光的規則與價值（RESEARCH_DIRECTION #5，2026-10-21，`lexp.py`，`captures/lexp/`）
- 虛擬 V1（VMAX 2700、HMAX 445）、254 列、SHS/增益 IMXB 代換、`fixed_shutter`；frame_cb 連拍 16 張連續幀。
- [M] **週期 = 0007+1 幀**（16 張完全規律）；訊號（減黑 256）：0→84、1→169、2→253、3→338、7→679 = **(0007+1)×84**，精確線性。
- [M] **曝光 = (0007+1)·VMAX − 2·SHS 列**：0007=1 時 SHS 4→170、700→126、1340→86、2000→44、2600→6、2690→0，2710 起繞回滿曝光（歸零點 = VMAX）。
- [M] `0008=01`（0007=0）：10 秒內只有 1 張亮幀（4.05 s，已飽和 4021）→ 與「0008 = 幀數第 8 位起、257 幀 ≈ 4.29 s」相符 [I：只見一次，間隔未量]。
- [M] **雜訊收益很小**：同總曝光，一次 4 幀長曝光 vs 4 張相加，時間雜訊比 1.13（最暗檔，位準 325）→ 1.01（亮部）。此增益下讀出雜訊遠小於散粒雜訊；
  理論上限（純暗/高增益）約 2×（√4），未量。
- **價值判斷**（使用者 10-21 指出）：「降低幀率」（加大 VMAX）本身就是單次讀出的長曝光，效果相同且有效幀率一樣；
  VMAX 欄位 14 位元 → 最長單幀 ≈ 16384 列（HMAX 445 時 ≈ 101 ms、330 時 ≈ 75 ms）。0007/0008 只有在需要**比這更長**的曝光時才有用，
  而韌體自己已有 SoC 端的多幀曝光（0x30100048[26:16]）。→ **#5 結案：機制已懂，產品價值低**；僅在「固定幀時序下穿插長曝光」（例如時域 HDR 長/短交替、維持輸出節奏）時再考慮。

## 54. HDR 收尾：14-bit 與棋盤的暗部雜訊（RESEARCH_DIRECTION #7，2026-10-21，`hdrnoise.py`、`offline/hdrnoise_eval.py`，`captures/hdrnoise/`）
同場景、同曝光時間（0 dB：16.6 ms；26.4 dB ≈ ISO 3200：0.79 ms），SHS/增益/HCG(05E1=0) 以 IMXB 代換固定，幀對時間雜訊（DN12 單位）。
| 組 | 0 dB 暗區讀出雜訊 | 0 dB 訊號 3 / 10 / 30 | 26.4 dB 暗區讀出雜訊 | 26.4 dB 訊號 3 / 10 / 30 |
|---|---|---|---|---|
| A 12-bit 1×1 | 0.65 | 0.58 / 0.78 / 1.06 | 5.29 | 5.37 / 5.73 / 6.98 |
| B 14-bit 1×1 | **0.29** | 0.44 / 0.67 / 0.99 | **3.61** | **3.82** / 4.45 / 6.24 |
| C 14-bit + 棋盤（全亮組） | 0.27 | 0.45 / 0.68 / 0.99 | 2.72 | 3.48 / 4.41 / 6.26 |
| D 垂直 2:1（12-bit） | 0.55 | 0.52 / 0.65 / 0.84 | 4.18 | 4.97 / 5.17 / 5.76 |
| E 垂直 2:1 + 棋盤（全亮組） | 0.66 | 0.56 / 0.67 / 0.85 | 4.16 | 4.63 / 5.01 / 5.73 |
- [M] **14-bit 讀出雜訊**：0 dB 少 2.2×（0.65→0.29）、ISO 3200 少 1.47×（5.29→3.61）；最暗處（訊號 3）ISO 3200 少 1.41× ≈ **0.5 級**；訊號 ≥30 時被散粒雜訊主導、差異縮小。
- [M] **棋盤不增加每個全亮像素的雜訊**（C≈B、E≈D）。棋盤 HDR 的暗部代價只來自「每 2×2 只有一半像素是全亮組」（√2 ≈ 0.5 級，HDR_RESEARCH §3 的 −0.5）。
- 結論 [I：由兩個實測合成]：**14-bit + 棋盤 HDR 的暗部 ≈ 12-bit 一般讀出**（0.5 級的增益抵銷 0.5 級的代價），高光仍多 +2.2（色彩）/ ≥+3.8（亮度）級。
  代價是 14-bit 的速度（HMAX 911，1×1 全幅約 29 fps，§42）。垂直 2:1 + 棋盤同理不增雜訊，但 12-bit 沒有讀出雜訊紅利。
- 上機：第一次批次在「C 26.4 dB」進虛擬 14-bit 時凍結一次（使用者重開）；單獨重跑正常，原因未查。同批 B/C 首跑因 HMAX 讀成尾段（1915）曝光減半，已作廢移到 `captures/hdrnoise_bad/`。

## 55. 防閃爍：用捲簾當時間取樣、曝光與幀率對齊（RESEARCH_DIRECTION #6，2026-10-21，`flicker.py`，`captures/flicker/`；使用者準備的 LED 燈）
- 方法：虛擬 V1（HMAX 445 → 每列 6.18 µs，2022 列 = 12.5 ms 的時間軸），SHS/增益/HCG 代換固定、`fixed_shutter`；
  短曝光列剖面 ÷ 全幀曝光列剖面 = 燈的波形。
- [M] **波形**：近似正弦，相對亮度 0.43–1.75（約 ±60% 調變），無 PWM 高頻成分。單幀擬合只涵蓋 1.5 個週期，頻率粗（120–123 Hz）。
- [M] **精確頻率由相位漂移量**：HMAX 480 × VMAX 2500 = 精確 60.000 fps，每幀相位漂移 −0.00639 rad → 燈 **119.939 Hz**；
  VMAX 2502（59.952 fps）漂移 +0.00381 rad → **119.940 Hz**。兩個獨立設定一致到 0.001 Hz → 市電 ≈ 59.97 Hz。
- [M] **條紋 vs 曝光**（列剖面標準差）：1/1000 s 29.8%、1/240 s 20.1%、**1/120 s（8331 µs）0.34%**、1/60 s 0.19% → 曝光 = 週期整數倍即消除條紋。
- [M] **幀率鎖定**：60.000 fps 時條紋仍以每幀 −0.0064 rad 漂移（因為燈是 119.94 Hz 不是 120）；要完全靜止需 fps = 59.970 → VMAX 2501.25（HMAX 480）。
  VMAX 一列 = 0.04%（60 fps 時 ≈ 24 mHz），可以追到市電的實際頻率；市電本身會漂移，實用作法 = 量漂移 → 每隔幾秒微調 VMAX（閉迴路）。
- 應用：
  1. 自動防閃爍：量到燈頻 → 快門自動取週期整數倍（條紋 30% → 0.3%）。
  2. 高速快門下（曝光 < 週期）無法消除條紋 → 改鎖幀率讓條紋靜止（再由後製平場校正）。
  3. 量測工具：單張短曝光即可看出燈有無閃爍、深度與波形（產品可做「閃爍偵測」提示）。

## 56. 閃爍條紋的相位擺放（使用者構想，2026-10-21，`flickphase.py`，`captures/flickphase2/`（重算 `reanalysis.json`））
- 各家做法調查（Sony Var. Shutter、Panasonic Synchro Scan、Nikon 1/96 級、Canon 高頻防閃爍）：影片都是「快門 = 週期整數倍」（= §55）；
  拍照另有「偵測亮峰時間、在亮峰曝光」（Canon/Sony 防閃爍拍攝、專利 US10868972）。車用感光元件的 LFM 需晶片支援。
- 構想：幀率鎖在燈頻（每幀 = 1 個週期），讀出窗短於週期 → 調相位讓暗段落在消隱裡。
- [M] 2×2 快速 1920×1080 裁切：讀出 4.99 ms / 燈週期 8.34 ms（60%），快門 500 µs；VMAX 比鎖定值長 12 列讓相位慢慢漂，取 48 幀：
  **條紋峰峰值隨相位 44%（最好）↔ 92%（最差）**、標準差 14% ↔ 31% → 相位擺放讓條紋**減半**，但這盞正弦燈消不掉。
- 理論吻合：正弦相對振幅 a≈0.35–0.45、窗佔週期比 r=0.6：最好（窗心在峰/谷）= a·(1−cos(π r)) ≈ 0.46、最差（窗心在過零）= 2a·sin(π r) ≈ 0.86。
- 推論 [I]：**PWM 燈（暗段 < 1−r）可完全消除**；讀出越短越好（r=0.3 時最好情況降到 0.41a）。
  應用 = 快門必須短於週期時（高速快門、高幀率）的補救：鎖幀率 + 把相位停在最佳點（§55 已證實可鎖定；本次「停車」程式的鎖定段因檔名覆寫只留 1 幀，待補）。
- 首兩跑的數字（1800%）是程式錯誤：黑位不是 256、參考列尾端 ≈0；已改為 OB 列黑位 + 有效列遮罩重算。

## 57. 原廠防閃爍模組（離線，韌體字串；2026-10-21，未上機）
- [C] 原始碼路徑：`src/library/CameraController/AeMgr/src/flicker/AeFlicker.cpp`、`AeFlckComparison.cpp`、`AeFlckDebug.cpp`（AE 管理器的一部分）。
- [C] 偵測用捲簾：字串 `SensorLineSize:`、`all_line_freq:`、`angular_freq:`、`calcAngularFrequency`、`VARIATION_ABS_AVE`、`VARIATION_LINEARITY`、
  `initAeArea`（hst/vst/hsize/vsize/hnum/vnum）、結果 `D COMP,%d,(0:NO 1:50 2:60)`、`cnt,%d,flicker,%d,50Hz,%d`、除錯檔 `FLCK_DET` + `%04d%02d%02d_%02d%02d%02d.bin`。
  → 在 AE 測光區逐列比較亮度變化，只分三類：無閃爍 / 50 Hz / 60 Hz（與 §55 同原理，但只到名目頻率）。
- [C] shell 指令（字串位置 ≈0xC0BACFAC–0xC0BAD10C）：`ae flck`（flicker test）→ `get`（`flicker state = %s`：noflck / 50hz / 60hz）、
  `set [off|no|50|60]`（`turn off state locking` / `turn on state no flicker / 50Hz / 60Hz`）、`disp`（偵測數據）、`sim`。
- [I] 偵測到後 AE 應會把快門限制在 1/100 或 1/120 的倍數（使用者聽說「P 模式有防閃爍」）；**AE 如何用這個狀態、手動快門/錄影時是否介入：未查**。
  → **已離線查完，見 `AE_FLICKER_STOCK.md`**：進 LV 時切到 240 fps 的模式 12，取 4 幀做一次偵測；結果在 0xC320228C，鎖定值在 0xC32006FC/0xC3200700（只在 RAM）；唯一讀取入口是 FUN_c0210118；Tv 對齊表在 0xC0911A0C/0xC0911994（ROM），另有 RAM 表 0xC2F18278/0xC2F182A0。
- 比較：原廠＝名目 50/60 Hz、AE 模式；我們（§55/§56）＝實測頻率（±0.001 Hz）、快門 12.5 µs 細調、幀率鎖定、相位擺放。
- 後續（使用者 10-21）：兩條路之後再決定——(a) 優化原廠 P 模式（例如把 `ae flck` 的結果換成實測頻率、快門對齊實際週期）；
  (b) 加我們自己的防閃爍模式（DEV_PLAN D2）。上機確認可先用唯讀的 `ae flck get` / `ae flck disp`。

## 58. ★ 3×3 快速可以裁切 → 全片幅寬 1920×1080 ≈ 195 fps（2026-10-21，`hs11.py --donor 8`，`captures/crop3x3b/`；`captures/crop3x3_flickerlamp/` 在閃爍燈下拍、作廢）
- 離線：`072A/072B` 不是裁切窗，是整個陣列的驅動範圍（1×1 0x7E5=2021、2×2 0x3F0=1008、3×3 0x2A0=672 = 4032/(2·vbin)），`0728` = 0x39+2·vbin；
  原廠 **mode 134（3×3）本身就用 `0003=1` + 窗**（起點 365、高 570）→ §20「mode 8 開 0003 b0 會停輸出」只是窗高 0 的結果，不是 3×3 不能裁。
- [M] donor 8（3×3 快速）、`0003=1`、`0022/23`=380、`0024/25`=540 → 接收 1106 列（1080 影像列 = 3240 感光列 ≈ 16:9 全寬）、水平裁 1920（= 5760 感光寬）。
  穩定光源、增益碼 0x400、SHS=4：
  | `0016` | 訊號/(VMAX−8)（線性檢查） | 最小 VMAX | fps | 連拍 |
  |---|---|---|---|---|
  | 50（原廠） | 117.1→116.7 恆定（1600→1212） | **1212**（1205 起少送列） | **180** | VMAX 1250：中位 5729 µs = 理論、8 幀位準 400.7–401.7、相鄰幀雜訊 1.38 |
  | **2** | 115.4→115.0 恆定（1300→1115） | **≈1116–1120**（1115 少 1 列） | **≈195** | VMAX 1130（193 fps）：間隔 5175–5185 µs、無掉幀、8 幀位準一致 |
- `0016=2` 在 3×3 快速可用（2×2 快速不行，§47）。公式 VMAX_min ≈ 列數 + 46 + 2·`0016` 再次成立（1106 + 10 ≈ 1116）。
- 意義：**全片幅寬（5760×3240 感光區 → 1920×1080）的 3×3 快速 ≈ 195 fps**；2×2 裁切（1.58×）≈ 192 fps（§52）。代價：3×3 的雜訊與鋸齒（§40）。
- 教訓：閃爍燈下 SHS=4（曝光 ≈ 整幀、非週期整數倍）會讓位準不線性、幀間跳動（544–596）→ 線性檢查前先確認光源穩定。

## 59. 增益 × 轉換增益（HCG）畫質地圖（2026-10-21，`gainmap.py`、`offline/gainmap_eval.py`，`captures/gainmap/`，穩定光源）
虛擬 V1（12-bit）/ V2（14-bit）1×1，SHS/增益/`05E1` 以 IMXB 代換固定，曝光隨增益反比調整；光子轉移（綠平面 16×16 區塊 平均–時間變異）。
| 增益 dB | HCG | 12-bit 讀出雜訊 e⁻ | 14-bit 讀出雜訊 e⁻ | DN12/e⁻ | ADC 滿刻度 e⁻ | 12/14-bit DR（ADC/讀出雜訊，級） |
|---|---|---|---|---|---|---|
| 0 | 關 | 14.7 | 7.5 | 0.038 | ~100k | 12.8 / 13.7 |
| 12 | 關 | 9.0 | 5.6 | 0.15 | 25k | 11.5 / 12.1 |
| 27 | 關 | 6.6 | 4.5 | 0.85 | 4.5k | 9.4 / 10.0 |
| 0 | **開** | 3.2 | 1.7 | 0.20 | 19k | 12.5 / 13.4 |
| 12 | 開 | 2.1 | 1.4 | 0.80 | 4.8k | 11.2 / 11.7 |
| 30 | 開 | 1.5 | 1.15 | 6.3 | 0.6k | 8.7 / 9.0 |
（完整 44 點見 `captures/gainmap/eval.json`）
- [M] **HCG 讓轉換增益 ×5.2**（0.038→0.20 DN12/e⁻），讀出雜訊（e⁻）降 4.6×（12-bit 14.7→3.2、14-bit 7.5→1.7）。
- [M] 同樣滿刻度（≈ 同等總增益）比較：LCG 15 dB（18k e⁻、8.2 e⁻）vs **HCG 0 dB（19k e⁻、3.2 e⁻）→ HCG 暗部好 ≈1.4 級**；
  LCG 27 dB（4.5k e⁻、6.6 e⁻）vs HCG 12 dB（4.8k e⁻、2.1 e⁻）→ HCG 好 ≈1.7 級。→ **總增益 ≥ ~14 dB（×5）時都該用 HCG**。
- [M] 14-bit 在所有點讀出雜訊（e⁻）低 1.3–2×（低增益差最多）。
- 注意：0 dB LCG 的「ADC 滿刻度 100k e⁻」超過像素滿井（推測約 50k e⁻ 級，未量）→ 低增益時實際 DR 由滿井決定，表中 DR 是 ADC 上限。
- **待查（可能是大收益）**：HDR_RESEARCH 記錄「原廠 ISO 3200 = 26.4 dB、LCG」。若屬實，原廠在 ISO ~640–6400 用 LCG + 高類比增益，
  比 HCG + 低增益多 1.4–1.7 級暗部雜訊 → 需確認原廠各 ISO 的 增益/HCG 對應（IMXB 匯流排記錄，每個 ISO 一次；改 ISO 是選單合法值）。

## 60. 原廠 ISO → 感光元件增益 / HCG 對應（即時預覽，2026-10-22，`isomap.py`，`captures/isomap/`）
- 條件：CINE、即時預覽（mode 8）、`SetMovRecFormat`=0、`SetMovCinemaDNGQuality`=0、P（exp_mode 0）；`menu SetIso N`（值就是 ISO 數字，合法值，測完改回原值 0）；IMXB 匯流排記錄每個 ISO 的最後一筆。
| ISO | 類比 dB | HCG | SoC 數位增益 |
|---|---|---|---|
| 100 / 125 / 160 | 2.39 / 4.31 / 6.46 | 關 | 1.0 |
| **200–400** | **8.41（四檔相同）** | 關 | 1.0 |
| 500 / 640 / **800** / 1000 / 1250 / 1600 | 10.36 / 12.48 / **14.43** / 16.37 / 18.30 / 20.45 | 關 | 1.0 |
| 2000 / 2500 / **3200** / 4000 | 22.39 / 24.32 / **26.44** / 28.38 | 關 | 1.0 |
| 5000–10000 | 29.97（類比上限） | 關 | 1.04 → 2.08 |
| **12800** / 16000 / 20000 / 25600 | 24.11 / 26.05 / 27.95 / 29.97 | **開** | 1.0 |
- [M] 即時預覽下 **HCG 直到 ISO 12800 才開**；ISO 200–400 送給感光元件的增益相同（差異在後段，RAW 相同 [I]）。
- 結合 §59：**HCG 0 dB 的滿刻度（19k e⁻）≈ ISO 800（LCG 14.43 dB）的滿刻度**，但讀出雜訊 3.2 e⁻ vs ≈8.3 e⁻（12-bit）→
  若 ISO 800 改用 HCG 0 dB（並把 ISO 800–10000 都改用 HCG + 低類比），暗部可好 **≈1.4 級**（同高光餘裕）。
- **待確認**：使用者說「CinemaDNG 12-bit 的雙原生 ISO 是 100/3200、拍照與 8-bit 是 100/640」，與即時預覽量到的不符 →
  錄影時的對應可能不同（錄影模式切換時重設）。需在**實際錄影**下記錄匯流排（錄影中不碰 USB：錄前開記錄、停錄後再讀，IMXB 環形緩衝 32768 筆夠 40 s）。

## 61. ★ 錄影實測：CinemaDNG 12-bit 的 ISO 100–800 RAW 完全相同（ISO 只寫在 BaselineExposure）（2026-10-22，`bufa_probe.py rec`，`captures/isorec/`）
- 條件：CINE、FHD（`SetMovRecSize`=2 → 錄影 mode 106、`0001`=0x39）、`SetMovCinemaDNGQuality`=0（DNG 12-bit）、快門 1/125 固定；每個 ISO 錄 3 s，
  錄前開 IMXB、停錄（USB 按鍵脈衝）後 10 s 才讀；DNG 第 20 幀從卡上取回（clip A001_007–012；檔名日期 007 為 20261021、其餘 20261022）。
- [M] 錄影中送給感光元件的值（兩次模式切換之間）：
  | ISO | 類比碼（dB） | HCG 05E1 | AR 05E2 / 041F | DNG 綠中位 / p99.9 | DNG BaselineExposure |
  |---|---|---|---|---|---|
  | 100 | 985（2.39） | 0 | 0 / 0 | 400 / 740 | 0.00 |
  | 500 | 985（2.39） | 0 | 0 / 0 | 400 / 739 | 2.32 |
  | 640 | 985（2.39） | 0 | 0 / 0 | 400 / 740 | 2.68 |
  | 800 | 985（2.39） | 0 | 0 / 0 | 400 / 740 | 3.00 |
  | 2500 | 3473（16.37） | 0 | 0 / 0 | 982 / 2690 | 2.32 |
  | 3200 | 1546（4.12） | **1** | 0 / 0 | 1180 / 3374 | 2.32 |
- 結論：
  1. **12-bit CinemaDNG 的 ISO 100–800 是同一份 RAW**：感光元件增益不變、RAW 數值逐統計量相同，差別只在 DNG 的 BaselineExposure（+2.32 / +2.68 / +3.00 級）。
     → ISO_MODE_SWITCH.md 的韌體模擬（類比固定、其餘是數位倍率）在感光元件端成立，且**數位倍率沒有乘進 RAW**，只寫成中繼資料。
  2. **AR 在這些 ISO 都是 Normal**（含 2500：16.37 dB < 18.03 dB）→ 說明頁「錄影 ISO 640 切 AR High」的推算不成立（它假設 2× 微調改由類比承擔）。
  3. ISO 2500 = 類比 ×6.6 + BaselineExposure 2.32；ISO 3200 = HCG + 4.12 dB + 2.32 → HCG 在 3200 切換（12-bit 規則）實錄證實。
  4. 「12-bit 的 640 是谷底」「ISO 800 標竿」需要重新解讀：在 12-bit CinemaDNG，ISO 100–800 的 RAW 一樣，選 800 只是讓相機以 +3 級的解讀去測光/顯示（實際上就是 ISO 100 少曝 3 級）。
- 待查：其他解析度（UHD mode 7）、8/10-bit（推算 640 切 HCG）、拍照 14-bit；說明頁需要更新。

## 62. 讀出驗證批次：10 種讀出全部通過（模組 1 第 1 層，2026-10-22，`readout_batch.py`，`captures/readout_batch*/`、`captures/readout_validated.json`）
每組：接收列數 = 規劃值（±8）、曝光線性（3 個 VMAX 的 訊號/(VMAX−8) 差 < 6%）、8 幀連拍（間隔 = 理論、無掉幀、相鄰幀雜訊 0.3–30）。
| 讀出 | 裁切 → 輸出 | 實測 fps | RS |
|---|---|---|---|
| 12-bit 1×1 | 6060×3408 → UHD | 45.7 | 21.4 ms |
| 12-bit 1×1 | 3840×2160 | 70.5 | 13.7 ms |
| 14-bit 1×1 | 4152×2160 → UHD | 36.4 | 26.7 ms |
| 12-bit 快速 1×1 | 4176×2016 | 101.5 | 9.5 ms |
| 12-bit 快速 1×1 寬（6064） | 6060×3408 → UHD | 50.8 | 19.2 ms |
| 12-bit 2×2 | 6060×3408 → FHD | 90.6 | 10.7 ms |
| 12-bit 快速 2×2 | 3840×2160 → FHD | 192.1 | 5.1 ms |
| 12-bit 3×3 | 6060×3408 → FHD | 127.0 | 7.2 ms |
| 12-bit 快速 3×3 | 5760×3240 → FHD | 179.1 | 5.1 ms |
| 12-bit 3×6 | OG → 1008×662 | 209.0 | 4.3 ms |
| 12-bit 快速 3×6 | OG → 1008×662 | **289.4** | 3.2 ms |
- 訂正：**快速 AD 下限 = 330**（§49 的 320 只看線性；320 時相鄰幀雜訊 150–190 = 畫面損壞）。3×6 的接收端額外列 = 19（不是 26）。
- 驗證程式修正：量列數前先把 VMAX 加大（VMAX 小於光柵時感光元件只送 VMAX−~76 列）；14-bit 幀要標 bits=14；連拍視窗 14-bit 用 enum 1；加相鄰幀雜訊上限。
- 首跑每組重開機（不必要，使用者指出）；之後只在原廠表檢查失敗時才重開。

## 63. 重建測試：只用模式屬性能重建原廠 70 個模式的多少（2026-10-22，`offline/reconstruct.py`，離線）
規則類型：常數、類別查表（cls/hbin/vbin/vadd/bits/窗/ACQ/CROP/CONT）、單變數線性（含 floor/除法）、位元組拆分、門控（某類別為 0）、雙變數線性。
| 表 | 欄位 | 可重建 |
|---|---|---|
| REG（161 暫存器） | 161 | **100%** |
| TIM | 14 | **100%** |
| R14 | 8 | 100% |
| META | 48 | 97.9%（缺 +0x24：一個模式的寬度不同） |
| R68 | 50 | 82.0% |
| R38（DCLP 幾何） | 26 | 69.2% |
| R28（推測 AF/評估格點） | 18 | 72.2% |
| **合計** | 325 | **92.9%** |
- 留一驗證（拿掉一個模式、用其餘推它）：84.3% 的預測正確 → 類別查表無法外推到原廠沒有的組合，這部分是生成全新組合時的真正缺口。
- 剩下 23 個欄位的性質：R38 的 x 寬 ≈ ⌈(寬 + 6096/hbin)/24⌉、y 窗 ≈ 接收 y 窗 ±2..6（近似規則，有逐模式微調）；R28 與 R68 的語意未解（R68 含 32 位元值 1,000,000 / 30,000,000、寬高、偏移，僅部分模式非零）。
- 下一步：查 R28/R68 的使用者（MODE_TABLES_CONSUMERS）與上機擾動測試，判斷「沿用 donor 值」對影片模式是否無害。

## 64. ★ 垂直視窗起點：感光元件列為單位、中心 2080、必須 ≡ 1 (mod 4)（2026-10-22，`winbound.py`、`smc_stockblack.py --light`，`captures/winbound/`、`captures/phase_stock/`）
- **單位**：0x0022/23 起點在所有合併方式都是**感光元件列**；視窗涵蓋 2H 輸出列 = 2H × mv 感光元件列。原廠視窗模式全都置中在第 2080 列：10（1069+1012）、100（993+1087）、58（369+2×855）、134（365+3×570）、132（897+2×589，差 5）。
  → 舊 readout_cfg 的 2×2 中心 1224、3×3 中心 935 是把單位當成輸出列（借自 58/134 的 st+H），**錯**：高 4000 的 2×2/3×3 視窗底部越界，最後 ~50/~47 列讀成 4095（接收列數照樣對）。
- **可讀範圍**（2×2 光照，起點掃 0..224）：感光元件列約 56..4104；起點 0 → 頂端 24 輸出列不受光；起點 124/174/224 → 底部出現暗列/飽和列。
- **奇偶 = 色彩相位**（同一光照場景）：原廠 12 個模式全是 [R/B, G, G, B/R]（兩個綠相等且最亮）。
  | 起點 | 1×1（12-bit，高 2160） | 2×2（高 4000） | 3×3（高 4000） |
  |---|---|---|---|
  | 奇數（997/999/1001、49/77/81/99、77/79/81） | 正確 Bayer | 正確 | 正確 |
  | 偶數（1000、0/24/74/124/174/224、80） | **顏色混合**（四相位幾乎相等、整體偏亮 27%） | **列相位翻轉**（綠到對角線另一側） | **顏色混合** |
  原廠所有起點都 ≡ 1 (mod 4)（1069、993、369、365、897），生成器照抄。
- **規則**（readout_cfg.plan）：start = 2080 − H·mv，取最接近且 ≡ 1 (mod 4) 的值；start < 56 或 start + 2H·mv > 4104 → 拒絕。
- ⚠ 影響：在此之前所有**有視窗**的生成/驗證（§62 讀出驗證、SMC 第 1–4 輪）起點都是偶數——列數、預覽、線性、連拍、黑位全部照樣通過，**但顏色是錯的**。驗證已加 Bayer 相位檢查（光照：兩綠差 < 2%、綠比 R/B 亮 > 5%），SMC 第 5 輪全部重跑。

## 65. 偶數垂直合併的列相位偏移（2026-10-22，`rowphase.py`，離線用 `captures/phase_stock/`、`captures/winbound/`；來源：Julien Acquaviva sigma-fp-raw 的「3K row phase」）
- Julien 說 OG3K（3024×2010＝原廠 mode 98）的 G2/B 列偏離 Bayer 格 0.5 px（他量的 G2−G1 為 +0.51，B−R 為 +0.54），所以他的外掛在 demosaic 前做 Row Phase −0.125 plane pitch。我們用 `rowphase.py` 量了 12 個原廠模式（captures/phase_stock，看 G2 對 G1 的偏移，因為同色不受場景顏色影響；上下兩半各量一次）。偏差的單位是輸出 px：
  | 讀出 | 模式 | 垂直偏差 | 水平偏差 | 理論 |
  |---|---|---|---|---|
  | 1×1 | 10、3、100 | −0.003..−0.06 | ≈0 | 0 |
  | 2×2（含快速） | **98（OG3K）**、11、58、132 | **−0.48..−0.55** | ≈0 | −1/2 |
  | 3×3（含快速） | 134、139、8 | −0.002..−0.045 | ≈0 | 0 |
  | 3×6（含快速） | 140、12 | −0.18..−0.21 | ≈0 | −1/6 |
- **原因是物理，不是 OG3K 設錯**。合併垂直 n 列同色時，一對輸出列的兩個顏色只能各用自己奇偶的感光列。n 是奇數時可以均勻排開（3×3：R 用 0,2,4、B 用 3,5,7，中心 2、5、8…）。n 是偶數時，第二列的中心一定差 1 個感光列，也就是 −1/n 輸出 px。水平方向量到 0，表示 IMX410 的水平合併不是這種同色相加。
- 原廠自己的 2×2 模式（11、58、132）也一樣偏 0.5，不只 OG3K。Julien 的外掛只對 3024×2010 的 M98 修正；我們生成的其他尺寸 2×2 偏 0.5，3×6 偏 1/6，要靠匯出的中繼資料讓後製修正。
- 改視窗起點救不了：≡1 和 ≡3 (mod 4) 都量到 −0.5；偶數起點則讓顏色錯掉（§64）。
- 檢查：`rowphase.judge(img, vbin)` 要求兩半的 G2 垂直偏差都在預期值 ±0.1、水平偏差 ±0.1 以內（頻帶 < 0.07 週期/plane px；頻帶開到 0.2 時，1×1 原廠畫面會因混疊偏 0.3）。原廠 12/12 通過。突變測試：把 98 當成 vbin 1 或 3 判 → 不過；移動 1 列（相位翻轉）→ +0.5，不過。winbound 的生成畫面中，奇數起點 10/10 通過，偶數起點 8/8 不過。已接進 smc_validate 的光照檢查（`rowphase`）。
- 給 ISP / res-custom：每個生成模式要帶 `row_phase = −1/vbin`（vbin 為奇數時為 0）給後製；不要用解析度來猜模式。

## 66. 14-bit + 垂直 3:1 可行（2026-10-22，`bins.py … v3_14`，`captures/vbin3_14/`）
- 寫法：從 mode 10 出發，寫入 14-bit Family A（`fam14.json`）、L4 垂直 3:1 組，**不帶**同色配對組（§37），加上 `0001=29`（6064 寬 14-bit）。SoC 端 HMAX 911，接收端與 BUFA 用 14-bit 設定。同一批還拍了 1×1、12-bit 垂直 3:1、14-bit 垂直 2:1 當對照，最後再拍一次 1×1；拍完 poff 重開並自動對焦。
- [M] 出圖、兩幀都正常。是真 14-bit：影像區最低兩位元 0/1/2/3 各占 25%。
- [M] 列相位 `rowphase.judge`：14-bit 垂直 3:1 為 −0.03/−0.05（預期 0，通過）；14-bit 垂直 2:1 為 −0.51/−0.52（預期 −0.5）。
- [M] 跟 1×1 數位合併比（`bins_compare`，160–640 DN 區間）：12-bit 垂直 3:1 雜訊比 1.30，14-bit 垂直 3:1 為 0.84，但 14-bit 的曝光多了約 2 倍（k≈2.0；AE 是照 HMAX 445 算的，換到 911 沒更新）。照光子數換算後約 1.19，比 12-bit 的 1.30 好一點，這個亮度主要是散粒雜訊。暗部的讀出雜訊紅利要在同曝光、低亮度下另外量。MTF 正常；各顏色的 k 分布跟 12-bit 一致，沒有彩邊。
- 推算：全高 4040 → 1347 列 × HMAX 911，捲簾約 17 ms，最高約 56 fps；適合 2016×1344（水平 ÷3 交給 RWZM），等於「14-bit 的 OG2K」。
- 未做：同曝光暗部比較、全高 1347 列的完整幀（這次接收端只開 1000 列）、韌體切換的虛擬模式（要先在生成器加 `14v3` 類別，並建立黑位參考）。

## 67. 讀出組合表（2026-10-22/23，`readout_cfg` new 類別，`readout_batch.py --set matrix [--fresh]`，`captures/matrix_r1/`、`matrix_r2/`、`w14_sweep/`）
起因：生成器原本只覆蓋原廠 8 種讀出；已實測可行的垂直/水平單軸合併、14-bit 垂直合併都沒有加進去（使用者 10-22 指出）。
做法：水平 {1,2,3} × 垂直 {1,2,3,6} × AD {14、12、快速}。暫存器拆自原廠表：水平合併只由 `0001` 決定，垂直合併由 07xx 那組決定（V2 = Z MODE21，V3 = mode 139 的 Family B），v/6 = mode 140 的歸零組；每格都用第 1 層驗證（列數、Bayer、列相位、線性、連拍）跑全片幅。
- [M] **14 種通過**（五項全過；列相位：垂直 2 約 −0.5，其餘約 0）：
  | 類別 | 格式 | 垂直組 | 全片幅輸出 | HMAX | 最高 fps | 捲簾 |
  |---|---|---|---|---|---|---|
  | 12v2 / f12v2 | 2A | V2＋配對組 | 6064×2020 | 445 / 400 | 74.8 / 83.2 | 12.9 / 11.6 ms |
  | 12v3 / f12v3 | 2A | V3 | 6064×1346 | 445 / 400 | 105 / 117 | 8.8 / 7.9 ms |
  | 12h2 / f12h2 | 3B | — | 3032×4040 | 445 / 330 | 38.4 / 51.8 | 25.5 / 18.9 ms |
  | 12h3 / f12h3 | 2F | — | 2016×4040 | 445 / 330 | 38.6 / 52.0 | 25.4 / 18.8 ms |
  | 12h2v3 / f12h2v3 | **3B** | V3 | 3032×1346 | 445 / 330 | 105 / 142 | 8.8 / 6.5 ms |
  | 12h3v2 / f12h3v2 | 2F | V2＋**配對組** | 2016×2020 | 445 / 330 | 74.8 / 101 | 12.9 / 9.5 ms |
  | 14v2 | 29 | V2＋配對組 | 6064×2020 | 870 | 38.2 | 25.2 ms |
  | 14v3 | 29 | V3 | 6064×1346 | 870 | 53.8 | 17.2 ms |
- [M] **格式碼決定感光元件會不會自己配對兩列**：`39`（原廠 2×2）會自己配對，搭 V3 時兩色差 2 列（rowphase −1.98）；`2F`、`2A`、`3B` 不會自己配對，所以搭 V2 時要加同色配對組（不加的話 h3v2 差 +1.45 列）。§37「vbin2 要、vbin3 不要」是同一件事。
- [M] 不可行：v/6 一定要配 h3 的格式碼 `30`（只寫 07xx v6 組時，12v6 送 2272 列、12h2v6 送 2080 列，沒有除以 6）。14-bit `0001` 掃描：01/03/15/16/18/1A/1B/3A/3D/3E 都是定值，只有原廠已有的 2B（4160 寬）有影像 → 14-bit 除了 29/2B 沒有別的格式，§42 的結論成立。
- [M] 接收端多出的列數（over）跟原廠類別不同，實測值為：h2v1 90、h3v1 70、v2 62、h3v2 60、v3 79、h2v3（3B）79。水平合併後像素擠在接收行的左邊（接收窗 x0 = 0）；影像第一列可能落在奇數列（12v3 為 53），要往下對齊到偶數。
- [M] 14v3 列相位：三次為 −0.05..−0.13，第四次 −0.075/−0.079；分四段量時一度偏到 −0.16..−0.26，12-bit 垂直 3:1 約 −0.06。差異看起來隨每次執行而變（場景或對焦），列為觀察項。
- 工具教訓：
  - 讀出類別第一次上機時，三種「失敗」其實都是工具的錯：接收窗置中、預估列數、影像起點奇偶。
  - 全高畫面拍連拍要配 9 塊各 19 MB 的緩衝區，配置器會卡死 shell；連拍改成只接收約 500 列。
  - 開機後第 3、第 7 組各卡死一次。改成每組前先重開（`--fresh`）後，連續 19 組沒有再卡。累積狀態的假設成立，但根因未知。

## 68. VMAX 上限與多幀長曝光（2026-10-23，`longexp.py`，`captures/longexp/`）
- [M] **SoC VMAX（0x30100020 高半）只有 14 位元：16384 可用，寫 16385 時欄位繞回極小值，shell 卡死**（需手動重開）。規劃器現在會拒絕 VMAX > 16384（`readout_cfg.VMAX_MAX`）。不用累積時，單幀最長 = 16384·HMAX/72 MHz：12-bit 一般 AD 101 ms（9.9 fps），14-bit 207 ms（4.8 fps），快速 AD 330 時 75 ms。
- [M] V1（12-bit 1×1），固定增益 0x400、SHS 4：VMAX 2700–16384 時訊號/(VMAX−8) = 0.0196..0.0191，在 3% 以內 → 一直到上限都線性。
- [M] **多幀累積 0007 = n（IMXB 代換保持）**，12 幀連拍：
  - **週期**：每 n+1 幀出一張亮幀，其餘是空幀（暗區讀 0，影像約等於黑位）。n = 1、2、4 的週期在 V1 和 V3 都剛好是 n+1。幀間隔照常等於 VMAX 的時間（16687 µs），空幀也照樣送出。
  - **亮度**：V1 的亮幀為單幀的 1.99 倍（n=1）、2.97 倍（n=2）→ 曝光 = n+1 幀。
  - **快門和累積一起用**（n = 2，SHS = VMAX/2）：亮幀約 2.0 倍，不是假設「SHS 只削第一幀」時的 2.5 倍。換算成列數約 (n+1)·VMAX − 2·SHS，只有這一個點，待用更多 SHS 值確認。
  - **錄影端**：每 n+1 幀只有一張有影像，其餘要丟掉；有效 fps = 基礎 fps/(n+1)。
- [M] V3（2×2 底，donor 98）：改 VMAX 或 SHS 時訊號幾乎不變（957→1160），表示這個底下我們的快門代換沒有生效（曝光不受控）；累積的週期仍正確。2×2 底的快門控制待查。
- 生成器規則（待實作）：要求的 fps 低於 16384 列時的 fps，或快門長於一幀時，加上累積 n = ceil(所需曝光 / 一幀) − 1；這需要執行期代換 0007/0008（模式表帶不了），交給 res-custom。


### §68 補正（2026-10-23，longexp5）
- [M] 「V3 底部 487 列過曝」是工具假象：longexp 沒設 `vmode.KEEP_WINDOW`，vmode 改寫了 donor 視窗。設了之後 V1/V3 全高都沒有過曝列。
- [M] 曝光 ≈ (n+1)·VMAX − 2·SHS + c（線）。c：V1 ≈ 20–55，V3（donor 98 讀出）≈ 228；V3 的累積亮度比（1.90/2.80/4.60）與 SHS 掃描（2.356/1.902/1.452）全部由 c = 228 解釋。
- [M] 全高影像列數（SMC_VERIFY 第 14 輪）：原廠合併讀出一律 4032 感光列（2×2/V2 2016 列含 y0 前的不穩定對、3×3 1344、3×6 672）；不做垂直合併（含 h2/h3）4042 列。

## 69. BF 的 PDAF-6C 暫存器組在 fp 上（2026-10-23，`pdaf_bf.py`，`captures/pdaf_bf/`）

來源 sigma_bf/AF_ANALYSIS.md；`offline/bf_imx410_modes.csv` 已重新萃取並逐筆比對（0 筆不符）。donor 139（3×3），IMXB 固定 SHS 與增益，鏡頭開、場景固定。
- [M] ref1 / ref2 差異：std 0.88，雜訊 0.81 → 基準可信。
- [M] **tbl**（8 個表差異：0016=07、0242=01、0722/0723=00、0728=43、0736=10、0737/0738=00）：
  - 1370 行不變，各 Bayer 通道亮度變化 < 1.5 DN。
  - **只有水平梯度從 1.45 升到 3.44**（垂直 1.51→1.66），時間雜訊 0.81→0.99，即 ×1.22 ≈ √1.5。
  - 推論：水平相加從 3 欄變 2 欄（每 3 欄排除 1 欄）。
  - 沒有稀疏遮光像素網格。
  - → BF 的 PDAF 像是「把 PD 欄從相加中拿掉／另外讀」，與 Sony ZAF（§41）的機制不同。待確認：哪個暫存器造成、被排除的欄會不會出現在別的地方（行尾、額外行）。
- [M] **g_hcnt**（再加 0241=05、0246–0251）：接收端仍收到 1370 行，但抓不到畫面，推測行寬改變、接收視窗沒對上。感光元件沒有停。
  - 下一步：量 1 行的位元組數或像素寬，再把視窗調寬。
- [M] 收尾後相機停在模式 050（6064×2022 1:1），即時畫面在跑，但螢幕全黑；按 OK 也沒退出。`poff 1` 快速重開後恢復成 053/0008。
  - 這是收尾退出放大那一步的漏洞，探針要在收尾後檢查 mode_now。

## 70. 整機凍結 = 在幀中途停 BUFA0（2026-10-23，`freeze_iso.py`，`captures/freeze_iso/`）

使用者 10-23 要求查清楚：暗場驗證每 50–90 組就整機凍結一次（畫面停、按鍵無效）。

**[M] 隔離結果**

| 組 | 內容 | 次數 | 凍結 |
|---|---|---|---|
| A | 只切換到產生的模式（vmode + 放大進出） | 50 | 0 |
| B | 原廠放大中 Session 開 → 抓一對幀 → IMXB 8 幀連拍 → 關 | 26 + 50 + 66 | 2 |
| B2 | 同 B，只連拍不抓幀 | 50 | 0 |
| C | 即時畫面中 IMXB 代換開關 + fixed_shutter | 50 | 0 |

- 第二次凍結有逐步記錄（`B/steps.jsonl` it 65）：連拍結束的 `c06316b8(100)` 送出後沒有回來。它前面的 mutex 試拿與歸還都成功。
- 第一次凍結時，連拍那一步拖了 62 秒才結束，接著收尾卡住。暗場驗證那次「收尾第一個還原寫入不生效」也是同樣的現象：凍結早就發生，到收尾才被看到。

**[C] 機制**

- `c06316b8(100)` 不拿 mutex，整段只做兩次寫入：清 `0x30002060` bit0、寫 `0x30182000 = 0`。一個只寫兩個暫存器的函式不會自己卡住。
- 所以凍結應該是在 DMA 寫到一半時切斷 BUFA0，匯流排交易卡住，SoC 跟著停。
- 韌體自己的停法（`C031D434..C031D488`）：先 `tk_clr_flg(flag, ~1)`，再 `tk_wai_flg(flag, 1, ORW, …, TMO_FEVR)` 等下一次 BUFA0 完成，醒來後立刻 `c06316b8(100)`。也就是一定在兩幀之間停。
- 我們的工具是在任意時間點停：每組設定 ≥3 次（Session 開、連拍前後、Session 關），約每 100 次會切到幀的中途。

**修正**

- `sensor_read/bufa_stop.S`：在相機上一次做完「清旗標 → 等完成（≤500 ms）→ 立刻停」。旗標用 `[0xC2F14C98]`，BUFA0 中斷每幀會設 bit0。
- `bufa_probe.startstop(100)` 一律改走這個 stub。
- 不能從主機分兩步做：USB 來回約 30 ms，比兩幀之間的空檔長。

**對用戶的影響**

- 原廠流程本身就是這樣停的，用戶拍攝不會碰到。
- 只有「自己 arm BUFA0 再停」的工具會碰到，包括 imx410-lab 測試工具、將來 isp-lab 的 BUFA0 抓幀。
- res-custom 走原廠模式切換，A 組 50 次 0 凍結。

## 71. 14-bit 收尾卡死 = 共用執行區沒清指令快取（2026-10-24，`captures/prof/`，`trace_one.py` 逐步記錄）

**[M] 現象**
- 主機端加速後，14-bit 全幅每次在借 echo 的呼叫卡住，5 次中 4 次，每次位置不同：連拍釋放後、視窗還原、SETADDR、Session 釋放、連拍配置。
- 卡住時畫面還在跑，但按鍵沒反應。12-bit 從沒發生。
- 用今天之前的抓幀和停止方式（`OLDWAIT`）跑 3 次，3 次都過。

**[C] 機制（符合所有記錄，未直接量到）**
- callfn（`callfn.S`）和配置器 stub（`heapalloc.S`）都寫進 shell 的同一個執行區 `putfile.CODE`，輪流透過 echo 執行；參數區也同一塊。
- 寫入走資料路徑，中間沒有指令快取維護，所以 CPU 可能執行到另一段的舊指令：
  - 跑完 callfn 後馬上配置：callfn 把 heap 的 op=0 當函式位址，跳到 0。
  - 跑完 heap 釋放後馬上 callfn：heapalloc 拿 callfn 的參數去釋放。
- 加速前，兩次呼叫之間夾著上千個 USB 輪詢，舊快取線早就被擠掉；加速後兩次呼叫貼在一起，就容易中。

**修正（4/4 通過：14、14v2、14v3、12v2）**
- `imxl.heap`：程式放進自己的 cave 區塊 `imxl.heap.code`。內容不同才寫入，寫入後先做 C000E91C 快取維護，再執行。
- `fastsweep.cached_assemble`：callfn 的 CODE 改指向自己的區塊 `imxl.callfn.code`。
- 原則：**借 echo 執行的程式碼一律放自己的區塊，不跟別人輪流寫同一塊**。

**同時換掉的兩件事**（不再碰韌體的完成旗標 `[0xC2F14C98]`）
- 停止：`sensor_read/bufa_stopcb.S`。暫時接上 BUFA0 完成回呼，在完成中斷裡做 `c06316b8(100)` 的兩個寫入，所以一定停在兩幀之間。
- 抓幀：`sensor_read/bufa_grabcb.S`。也是完成回呼，分三個階段：NEXT 指向 buf → NEXT 指回 scratch → 完成。再用尾端哨兵確認那一幀真的寫進來。
- 這兩個取代了 `bufa_stop.S` 和 `bufa_grab.S`。舊的會清掉並等待完成旗標，而韌體的停錄／拍照路徑也在等這個旗標；它是不是卡死的原因沒有單獨驗證，但已經不用了。
- 已知：`0x30182184` 在這些模式下讀起來一直是 0，所以中斷傳給回呼的 done_addr 也是 0x40000000，不能拿來驗證。

## §72 full_v1（2026-10-24）：ISO 設定會移動黑位；寬度預設最寬時右邊 24 欄是假的

**相機設定**（離線比對＋上機重量；`captures/stockblack_iso800`）
- full_v1 的亮場與暗場都是在 ISO 800 固定、快門 1/30 下跑的（peer 借用時改的；之前是 ISO 自動）。
- 強制類比增益碼（0x400 / 3900）只蓋類比增益；ISO 設定仍會移動影像對 OB 的黑位。原廠模式自己就變了：98（2x2）0x400 下 6.1 → 3.9，11（2x2 快速）3900 下 7.3 → 3.3。
- 所以 86 組 2x2 / 2x2fast 暗場的 black_gain 失敗是參考值條件不同，不是模式問題。換成 ISO 800 參考值後全過（暗場 641/647）。
- 規則：smc_validate 開跑前讀 `menu SetIso` / `menu SetShutterSpeed`，必須等於 `CAMERA`（ISO 800、1/30，= full_v1，使用者 10-24 定：暗光源用 1/30），讀值記在 `<out>/settings.jsonl`。`menu SetShutterSpeed 1/125` 用 shell 寫不進去（讀回仍 1/30），要在機身上改。
- 亮場檢查都是同一組幀之間互比（比值、相位、行數），不受 ISO 影響，不必重跑。

**寬度預設的假欄**（離線，`colscan_edge.py`，647 組亮場幀）
- 每一種非 6064 的格式字（w03 4016、w18 5073、w2C / 12fast 4176、w2B 4176）在它最寬的寬度、x0 = 8 時，右邊最後 24 欄不是影像：一般 AD 是平的 256（填充），快速 AD 是亂碼（暗場列雜訊因此 2.0，f12w03 的 black 失敗就是這個）。
- 同一格式字的較窄寬度沒有；原廠 4176 寬的模式 100（x0 = 952）也沒有。是 x0、格式字還是寬度本身造成的，還沒上機分辨。
- 109 組受影響（亮場已標 cols 失敗，`captures/full_v1_edges.json`）。之前沒抓到是因為沒有任何逐欄檢查；smc_validate 已加 `cols`（只看右邊：亮場裡平坦的場景區域在左邊會被誤判）。

**rowphase 門檻**：0.1 → 0.2（分辨 0 與 -0.5 所需差距的一半）；低於 1000 列的幀整張量一次（`rowphase.judge`，`rowphase_rejudge.py`）。160–240 列的 6 組仍量不出來。

**14v3 頂端 14 列沒有曝光**（上機 `v3top.py`，captures/v3top，14v3:6064x3408>6064x1136@0）
- 視窗頂端第 20–33 列（14 列）的值等於 OB（差 ≈1 DN、std 0.4）：不是沒送，是送了但沒有曝光。從第 34 列起才是影像。
- 跟 SHS 無關（4 → 1200 都一樣）、跟 AE 或固定快門無關；只有改 SHS 之後的過渡幀那 14 列有曝光（10 DN vs 本體 8 DN）——full_v1 的 gainprobe 幀「正常」就是這個過渡幀，所以先前的「懷疑 AE 的 SHS」是錯的。
- 待決：生成器要把 14v3 視窗的影像起點下移 14 列（可用列 = 規劃 − 14），還是把視窗起點上移 14 輸出列補回來；兩者都還沒上機。

**根因調查（2026-10-24 上機，`v3top.py --burst`：IMXB 連拍＋匯流排記錄，captures/v3top）**
- 新 V3 類別（12v3、f12v3、14v3、12h2v3、w2C/w2B）開視窗時才有；全高、原廠 3x3 沒有。跟視窗起點（201…2001）、視窗高、AD 位元無關。
- 是**一幀一幀交替**的：同一設定連拍 12 幀 = 0,14,0,14…。單張抓幀時「有時 0、有時 14」就是這個。
- 不是黑位暫存器 0x005C/5D（AE 每 15.6 ms 寫一次 0x03FF，但連拍時完全沒寫，暗行照樣交替）——該假說已推翻。
- 觸發條件是**幀被拉長**：AE 在暗光下把 SoC VMAX 拉到 4×（720 視窗 875 → 3500 行，42.3 ms）。固定快門下手動重現：VMAX 875 任何 SHS 都正常；VMAX 拉長後，只有 SHS 落在 VMAX/2 正下方一小段（3500：1700、1746 正常；100、371、1000、1750、2000、2800、3200 交替）才正常；1750：873 正常、875 交替。
- 週期隨 VMAX 變：2×、3×、4× 基本 VMAX → 每 2 幀；1.5×、2× → 每 3 幀（1312、1750）。像是感光元件內部的幀以 VMAX/2 在跑，跟 SoC 幀的相位在轉。[I] 原廠模式拉長 VMAX 沒有這個現象，推測新 V3 少了原廠長曝光用的某個暫存器，尚未找到。
- 影響：這些視窗模式只能在 VMAX 等於基本值、或 SHS 在那一小段時用；相機 AE 在暗光下一定會拉長 VMAX。
- Z CAM 參考（readout 28 = 6064×1188）不是垂直 3:1，只是 1×1 開視窗；兩家韌體都沒有垂直 3:1 可抄。
- **`08B6=01 08B7=68` 讓感光元件跳過視窗最上面 16 個輸出列**（量到內容上移 16 列、最後 2 列空白；只加 08B6 → 暗列 14 → 8，w18 的 8 列就是同一件事）。它不是讓那 14 列曝光，而是不輸出它們。全高加了會壞（接收列 1390 → 1374，抓不到幀）。
- **修法（readout_cfg `V3_WIN` / `V3_SKIP`，上機確認）**：只在新 V3 類別開視窗時加這兩個，同時視窗多讀 16 列（H + 8）、起點上移 16 × 3 = 48 感光元件列（仍 ≡ 1 mod 4）→ 輸出列數與第一列都跟規劃相同。AE 下 14v3、12v3 的 1136、720 視窗連拍 9 幀暗列 0；接收列 1182 / 766（規劃 1179 / 763，跟修之前一樣）；720 視窗內容位移 0，1136 對舊幀差 2 列（一個 Bayer 週期，比對的舊幀不是同一次抓的）。OB 雜訊（0.35）、Bayer 相位、rowphase 不變。
- ~~修法~~ **撤回**（readout_cfg `V3_SKIP_ON = False`）：加了跳列後，曝光不足的帶子跑進畫面中間（線性的 VMAX 點：第 605–739、20–206、359–479 列），12v3 視窗線性失敗。08B6 掃描：bit0 = 內容上移 6 列（暗列 14 → 8）、02 = 下移 2 列、加 08B7=68 = 上移 16 列但中段出現上百列壞帶——它們只是輸出起始列的位移，不是時序。HMAX 870 → 1740 也無關。
- ~~V3 的 SHS 單位是 2 列~~ **更正**：曝光 = VMAX − 2·SHS 是**所有模式**的規則（§3，早就量過），不是 V3 特有；原廠 AE 本來就照它算，V3 的曝光沒有對不上。這次的量測（SHS 4/371/1000/1400 → 26.4/20.5/9.2/2.1 DN；SHS ≥ VMAX/2 → 沒有快門重置、整幀曝光）只是重新證實 §3。之前「SHS 在 VMAX/2 正下方才正常」是假象：那裡曝光趨近 0，整幀暗，暗列判斷抓不到。
- 頂端 14 列暗列仍未解：SHS 100（2·SHS ≪ VMAX）、VMAX 3500 時照樣隔幀出現。矩陣（視窗開）：2A+V3、3B+V3 壞；2F+V1（h3）壞（偏綠）；2A+V1/V2、3B+V1、2F+V2、2F+V3（原廠 3×3）正常。

**h3 不能開感光元件視窗**（full_v1 重跑，增益上限 3300 之後仍失敗的 4 組）
- 12h3 / f12h3 的 3408、2160 視窗：一半像素低於黑位（到 129，OB 254），曝光越長越暗，預覽整片偏綠。同場景的 12h3v2 視窗、12h3 全高都正常。
- Bayer 檢查（兩個綠相等且最亮）對整片偏綠照樣通過——它不是顏色檢查。
- readout_cfg.plan 與模擬器已拒絕 mh = 3、mv = 1 的視窗（all 集合 647 → 643）；這種裁切要讀全高再由 ISP 裁。

**h3 增益上限**：smc_validate 的自適應增益對 12h3 / f12h3 封頂 3300（SMC_VERIFY 第 16 輪：3711 以上變凸）。full_v1 重跑：全高 12h3 5/5、f12h3 5/5 過。

**§72 續：週期與一個作廢的修法（2026-10-24 上機，captures/v3top_vt、v3top_per、v3top_u）**
- [M] 暗列是**週期性**的，VMAX 基本值也會發生：固定快門、SHS 4，VMAX 875 / 1000 / 1200 / 1312 / 1750 / 3500 → 每 5 / 4 / 4 / 3 / 3 / 2 幀一次 = 「累計超過約 3600–3800 列之後的下一幀」。以**列數**計（HMAX 870 → 1740 週期不變），不是時間。
- [M] 韌體的寫入批次每幀都在同一相位（例：完成後 0.8 / 2.3 / 11.6 ms），出事幀與正常幀沒有差別 → 不是寫入造成。
- ✗ **作廢**：用 IMXB 把 0x0007/0x0008 換成非 0（FFFF、05DC、036B）時「暗列 0」是假的——感光元件根本不送畫面（OB 0、整幀定值、std 0），而暗列判斷把空白幀算成 0 列。0x1000 與 0 相同（畫面正常、照樣週期出現）。v3top.dead_rows 已改：空白幀回 −1。
- 仍未解：那個約 3700 列的內部週期是什麼、為何只有混搭格式字（2A/3B + V3）會打到視窗頂端。

**h3（水平 3:1、垂直不合併）沒有紅藍（2026-10-24 離線，full_v1 亮場幀）**
- [M] 12h3 / f12h3 全 10 組：R、B 平面在黑位（R/G 0.0–0.26、B/G −0.13–0.12；1×1 同場景 0.59 / 0.53），只有 G 有影像——預覽整片綠。全高也一樣，所以不是視窗問題（視窗另有一半低於黑位）。
- 驗證器的 Bayer 檢查（兩綠相等且最亮）對這種幀照樣通過；增益封頂 3300 後「線性通過」也只是 G 的線性。已加 `colour` 檢查（扣黑位後 R、B > 0.3·G），全部類別離線重判：只有 h3 這 10 組不過。
- 格式碼 2F（原生 3×3）配 V3（3×3）、V2（h3v2）正常，配「不合併」（donor 10 的垂直設定）就沒有紅藍。h3 暫時從產生器移除（readout_cfg.plan 拒絕 mh = 3、mv = 1；all 集合 651 → 641），找到對的垂直組再加回來。

## §73 14-bit 錄成 DNG：檔頭看 plane code，不看選單（外部 [C]，未上機；2026-10-24）
來源：Ruari / Arktri（projectFP）交接文件 `~/Downloads/HANDOVER.md` F4，他們讀 5.02 映像得到，自己也還沒上機。
- BitsPerSample、WhiteLevel、BlackLevel、strip 大小都取自 RAW profile 的 plane code（profile +0x84），不取自位元深度選單：
  `FUN_c04381e8` → `FUN_c0436218(profile)` = `FUN_c0436360(*(profile+0x84))`：7→0、**8→1**、9→3、0xA→4、0xB→2；
  `FUN_c04385c8` 把同一個值存進 RAW 描述子 +0x20、+0x24；IFD 建構 `FUN_c06a5290` 寫 tag 0x102 = `FUN_c02da870(desc[+0x24])`（0→12、1→14）。
- 意義：本專案的 14-bit 類別（14、14v2、14v3、14w2B…）要錄成 CinemaDNG 時，選單可以留在 12-bit（保持 12-bit 的增益策略），寫 plane code 8 就有 14-bit 檔頭。跟 Julien Acquaviva R120 的兩字法、以及 10-04 的模擬（r86）一致。
- 待驗 [camera]：打包方式（緊密 14-bit 還是 16-bit 字）要錄一段才知道；14-bit 黑位 = 12-bit 黑位 << 2 也還沒逐行確認。

## §74 沒用過的 12-bit 格式碼（2026-10-24 上機，`fmtprobe.py`，captures/fmtprobe）
直接寫入掃描（`sweep0001.py`，captures/sweep0001，00–FF；0x80 以上 = 低 7 位元的鏡像）有畫面、但沒做成類別的碼，用正規方式（類別 12 的計畫、接收端配上該寬度、固定 SHS 4 / 增益 0x400）各抓一對：
- 2A（對照）：6064、雜訊 1.18、R/G 0.59。
- 3D：6064、顏色亮度同 2A，但兩幀不一樣（21.5 vs 11.6 DN），差異由上往下 2 → 16 DN——曝光在漂移，感光元件看起來沒跟 SoC 同步（自由跑）。不可用。
- 1B（4177）：OB 1107、影像低於 OB、R/G = B/G = 1.0；以 14-bit 解也不成影像。資料格式與接收設定不符。
- 15（3514）：兩幀完全相同（時間雜訊 0）= 定值圖樣。1C（3889）：整幀飽和 4092。
→ 12-bit 直接寫入能出影像的格式碼就是已用的 2A/01/16/3E、18、03、2C/1A、3B/3A。直接寫入時抓不到幀的 33 個碼（04–14、1D–28、2D–39 中的大部分）仍未知：它們改了行寬或列數，要逐一猜寬度與合併方式才能配接收端。

## §75 給 Res-Custom2 的可用模式清單（2026-10-24，`export_modes.py` → `export/modes_verified.json`）
- 只收：產生器現在還會產生（smc_validate.all_set）＋光照每項檢查都過（含離線補的 cols / top_exposed / colour）＋類別沒被排除（h3、新 V3 開視窗）。
- 每筆：id、類別、位元、合併、裁切、輸出、fps、時序（HMAX、VMAX、捲簾、接收列數）、感光元件輸出（格式寬、實際行寬、raster、列數、是否視窗、RWZM）、donor 與疊加的感光元件寫入、ISP 端 attrs、驗證狀態（暗場 true / null = 還沒跑）。完整模式表列不放進清單，在主機端用 readout_cfg.plan + smc.create 從 (key, crop, out, fps) 重建。
- 2026-10-24 版：617 筆、38 類別；暗場已驗 512、未跑 105（新寬度）；略過 24（新 V3 視窗 20、光照失敗 4）。
- 規則：清單外的模式一律不用。重新驗證後要重跑 export_modes.py。

## §76 新 V3 的插入暗列與修法（2026-10-25 上機，`v3top.py --burst`，captures/v3top_T、_R、_M、_A0/_A16、_FH*）
**現象**（新 V3 = 格式字 2A / 3B / w 預設 + V3 垂直組；原廠 3×3〔2F + V3〕沒有）：感光元件在輸出裡**插入 14 列沒曝光的列**，畫面內容跨過它們連續（第 33 列接第 49 列）。
- **全高**：每一幀、任何曝光（AE 或固定快門、任何 VMAX）都在第 14 個輸出列之後插入 14 列（y0 20 → 第 34–47 列）。之前沒抓到：top_exposed 遇到第一個有光的列就停；rows 的 std < 0.5 只在 @29.97 碰巧觸發。
- **開視窗**：插在視窗最上面 14 列，**週期性**——門檻 T ≈ 2 ×（視窗外沒讀的感光元件列數）：1136 視窗（632 列）T 在 1291–1350 列之間，720 視窗（1880 列）T 在 3748–3800 列之間；VMAX ≥ T 就每幀都有，小於 T 就每 ⌈T/VMAX⌉ 幀一次（以列數計，HMAX 870 → 1740 不變）。
- 會改週期／列數的暫存器：0790 bit0（1 → 0：T 約 ×4–5，仍週期性）、0016（列數 14 → 13 / 7）、001C（同時改接收列數）。0791–079F、0058、0794、0720、0735 都無效。08B6/08B7 只是輸出起始列位移（見 §72）。根本原因未知。
**修法（readout_cfg，上機確認）**
- 視窗：`V3_MARGIN = 16`——視窗往上多讀 16 列（起點 −48 感光元件列，仍 ≡ 1 mod 4），`y_skip` 讓 ISP 的 y0 也 +16。暗列只落在 margin 裡（固定快門 VMAX 1800 與 AE 下 14v3/12v3 的 1136、720 視窗輸出 12/12 乾淨；同場景對照內容位移 = 16，起點與規劃一致）。捲簾 +16 列（14v3 2160：9.22 → 9.41 ms）。
- 全高：`V3_FULL_SKIP = 28`——y0 +28（跳過前 14 列好的與插入的 14 列），輸出 1358 → 1330（w18 1352 → 1324）。接收列數、捲簾不變。AE@29.97 與固定快門 8/8 乾淨。
- 工具配合：OB 範圍改到 `top − 4 − y_skip`（之前把 margin 列算進黑位，線性錯判）；`top` 檢查扣掉 y_skip；新增 `bands` 檢查（輸出內任何位置低於 0.5 倍中值的列，畫面 < 15 DN 不判）。
