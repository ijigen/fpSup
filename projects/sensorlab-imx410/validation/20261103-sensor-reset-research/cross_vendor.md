# IMX410 cross-vendor restart / flush investigation

2026-11-03. Offline static examination only. No camera, USB, imported vendor code execution, product edits, or card changes. C = code/data verified this session; H = historical extraction reviewed; I = inference.

## Result

**No dedicated first-frame / image-buffer flush register was identified.** There is a concrete, independently implemented **sensor standby / wakeup sequence** using `0000`, `00CA`, `00C5`, `00C6`, plus a physical **XCLR** reset in DJI's IMX410-family driver. These are alternatives to the fp's `0011` restart, not proof that a buffer is cleared, and not drop-in fp patches.

The strongest new evidence is DJI's separation of sensor wakeup, mode-table application, external timing-generator enable, and receiver state-machine waiting. This makes an orderly stop/configure/synchronize/restart a grounded research candidate; it does not establish a sensor-side root cause.

## DJI: code verified from the local vendor binary

Input: `projects/fp-lidar-direct/evidence/20261022-ronin4d/derived/system/lib64/libsensor_imx410.so`.

- SHA256: `390e4e03043778dd91a618f3b5eebce281cdb455545da15f939db894ab841786`.
- AArch64 ELF; dynamic symbols preserved, other symbols stripped. No binary execution.
- Source-path string: `hardware/dji/common/camera/sv_sensor_phy/sensor_driver/imx410/plat/eagle/sensor_imx410.c`.
- The driver name establishes the IMX410 family. Exact die revision / package equivalence to the fp is **not established**.
- Static reproduction: `python3 -B projects/sensorlab-imx410/validation/20261103-sensor-reset-research/cross_vendor_audit.py`. The script asserts the input hash, reads ELF symbols/PLT, disassembles selected ranges with Capstone, and extracts readout-table columns. Output is preserved in `cross_vendor_audit.txt`; Capstone version appears at its top.

### Physical reset [C]

Inside `sensor_imx410_probe`:

| VA | operation |
|---|---|
| `5F08` | `imx410_plat_xclr_set(context, 0)` |
| `5F10` | `sensor_phy_msleep(1)` |
| `5F1C` | `imx410_plat_xclr_set(context, 1)` |
| `5F24` | `sensor_phy_msleep(10)` |
| `5F44` | write/verify `0043=02` |
| `5F64` | read `00D7` |

This is a probe/startup path, not a proven per-recording reset. The delay unit comes from the imported function name `sensor_phy_msleep`; its implementation is outside this binary. It is not a measurement of actual elapsed time.

### Global initialization, then parking [C]

Inside `sensor_imx410_open` (`6478`, logging names `_imx410_config_global_reg_settings`):

1. `imx410_plat_dataintf_init` (`65E8`).
2. `0043=02` (`6608`), `00E9=80` (`6624`), `00D9=60` (`6640`), `04E6=00` (`6658`).
3. `sensor_phy_msleep(11)` (`6660`).
4. `00C5=00` (`667C`), `00C6=00` (`6698`), `0000=04` (`66B4`), `00CA=01` (`66D0`).
5. Immediately park: `00CA=00` (`66E8`), sleep 1 (`66F0`), `00C5=03` (`670C`), `00C6=01` (`6724`), `0000=05` (`6740`).

### Stream start [C]

The code contains `_imx410_start_stream` at string `1759B`. Two branches converge on these operations:

- One branch requests receiver FSM operation `1` at `6E64` **before** wakeup/table application (`73F4`, `7400`). A mode-change branch does wakeup/table application (`7100`, `710C`) **before** requesting operation `1` (`71B4`). Do not collapse this conditional order into a universal sequence.
- Both call helper `CD40(context, 0)`:
  - `0043=02` (`CD90`).
  - `0000=04` (`CE24`).
  - `00CE=02` (`CE3C`). The associated log function string is **`_imx410_set_ecc_crc`** (`1777B`): this is evidence for a link-integrity-format control, **not a buffer flush**. It must not be copied to the fp without receiver compatibility analysis.
  - `sensor_phy_msleep(11)` (`CFE0`).
  - `00C5=00` (`CFF8`), `00C6=00` (`D010`), `00CA=01` (`D028`).
- Then call full readout-table writer `D060(context, readout)` at `710C` or `7400`.
- Then `imx410_plat_timing_gen_enable` (`74F8`).
- Then `imx410_plat_slec_fsm_wait(context, 3, 200)` (`7508`). The wrapper forwards state `3` and value `200` to `combo_rx_slec_fsm_wait(port, 3, 0, 200)` (`125E8–125FC`). **The state enum and timeout units were not resolved**; do not call state 3 “first full frame received” or promise a 200 ms limit.

The readout table is applied **after** the wakeup register sequence but **before** timing-generator enable in this path. Wakeup therefore must not be equated to the start of externally clocked valid frames. The full startup includes host/receiver state, not just sensor SPI writes.

### Stream stop [C]

`_imx410_stop_stream` string `17EA0`; direct operations `7220–72E4`:

1. `0043=02`, `00CA=00`, sleep 1, `00C5=03`, `00C6=01`, `0000=05`.
2. Disable timing generator (`72B4`).
3. Wait receiver state `8`, argument `200` (`72C8`).
4. Request receiver FSM operation `3` (`72D4`).
5. Wait receiver state `1`, argument `200` (`72E4`).

Helper `CD40(context, nonzero)` also contains the same sensor parking sequence; the two observed direct callers pass zero. These values clearly control streaming/standby state; their internal clock/PLL/line-memory semantics are not proved.

### Readout-table support and overwrite hazards [C]

`sensor_imx410_readout_setting_table` at `3D2C8`, size 8592 = 179 × 48 bytes. Rows contain address at +8 and 38 one-byte readout values at +10; 178 real registers followed by FFFF terminator. Decoding is corroborated by the writer at `D100–D154`, which selects the column and sends contiguous runs of at most 8 registers at `D2C4`.

- Columns **21/22** contain `0001=2A`, `0242=2C`, `0278=04`, `0279=01`, `027B=04`, `08B6=01`, `08B7=68`: the same 1×2-specific group as Z CAM and SensorLab. This is **table support**, not evidence that shipping DJI UI modes exercise these columns or have clean first frames.
- Table rows 25/26/27 rewrite `00C5=00`, `00C6=00`, `00CA=01` in every column. Any attempt to park the sensor and then apply an unmodified full table would release these controls mid-table.
- No table entry for `0000`, `0011`, or `00CE` was found. `00CE=02` belongs to the separate wakeup/link setup path and is not overwritten by this table.
- The fp also has C5/C6/CA values inside its mode table (historical Z CAM comparison). Any fp standby experiment must account for this ordering rather than wrap a blindly copied sequence around the table.

## Z CAM: verified limitations and a correction

Sources: `zcam_e2f6/ghidra/imx410_drv.c` and `projects/imx410-lab/offline/zcam/zcam_imx410_tables.json`.

The wrapper and standby instructions were also rechecked directly in `zcam_e2f6/out/rootfs/usr/bin/imvt_camera`, SHA256 `5882b6c18a2fda4f95efa4d0877e6ce1b8b34b69c9200a450a9d564239896e39`: `B94A10: b B96478`, `B94A18: ret`, `B96490: orr w2,w0,#1`, `B964C0: and w2,w0,#FE`.

- [C] `sensor_standby @B96478` reads `0000` then writes `old | 1`; `sensor_standby_cancel @B964A8` reads it and writes `old & FE` (`imx410_drv.c:5160–5185`).
- [C] The exposed wrapper **`imvt_sensor_standby_cancel @B94A18` is a no-op** (`imx410_drv.c:3670`). The old note saying “Z uses 0000 bit 0 instead” establishes available routines, not that every exposed transition uses the cancel routine.
- [C] `sensor_init @B94990` / body `B949A4` uses platform stage1 → bus → common table → exposure calculation → AE registers → other registers → platform stage2 (`imx410_drv.c:3611–3654`). A skip-once flag can bypass initialization. Again this is a platform-coordinated path.
- [C] The common-table walker at `B94178` skips FFFF values and respects per-entry delays (`imx410_drv.c:3200`). `0000` rows with delay-only are **not writes of 00**, an easy extraction mistake to avoid.
- [C] The extracted table has no `0011` write. MODE21/22 table columns exist, but **zero of the 59 exposed mode entries selects either**. They cannot be cited as live proof of a successful 1×2 restart recipe.

## Astronomy SDK extractions [H]

Original SDK binaries are not present at the previously recorded temporary paths; the retained JSON was inspected, but not regenerated. Treat these as corroborating archived extractions, weaker than the directly rechecked DJI binary.

- `offline/astro/toup_tables.json`, stop fragment file offset `340C95C`: `00CA=00`, delay 1, `00C5=03`, `00C6=01`, `0000=06`, then delay 100. Start fragment `340C9A0`: `0000=04`, `00C5=00`, `00C6=00`, `00CA=01`. Additional fragments at `3490D10`/`3490D70` agree.
- `offline/astro/qhy410_writes.json`, sensor writes in power-down command function `40008C2C`, at `4000A0A0–4000A1AC`: sleep path changes `05D6`, `05A2`, `04F0`, `04D2`, `04D1`, `04DD`, then CA/C5/C6/0000 = `00/03/01/06`; wake path begins `0000=04,C5=00,C6=00,CA=01` then reverses analog controls. This is broader power management, not evidence of a first-row-only flush.
- These astro tables expose 1×1, 2×2, 3×3; no examined vertical-only 1×2 table provides a tested reset counterexample.

## Candidate assessment

| Candidate | What is established | Relevance / limits |
|---|---|---|
| `0000` standby plus `00CA/00C5/00C6`, coordinated with external sync / receiver | Same-family vendor drivers repeatedly implement the sequence | Best grounded alternative to fp `0011` for studying a deeper restart. No proof it clears a line buffer or fixes the first recorded frame. Full-table writes can undo parking. |
| XCLR physical reset | DJI toggles in sensor probe with 1/10 delay calls | Strong reset mechanism, weak suitability for each REC start; needs complete reinitialization and actual fp wiring/provenance. |
| `00CE=02` | DJI labels setup `_imx410_set_ecc_crc` | Link-format diagnostic/control, **not flush**; receiver must agree. |
| `00E9/00D9/04E6` initialization | Shared power-up writes, with delay | Init-only in examined paths. Historical fp sweeps show D9 changes stop output. Not an ad hoc clearing operation. |
| `08B6/08B7` | 1×2 readout group / output positioning | Already tested zero without eliminating the issue. No evidence these are flush controls. |
| QHY analog sleep group | Archived power-save routine | Too broad and unvalidated for this symptom; not a first choice. |

The observation requiring explanation remains **the first recorded DMA frame**, not yet the first sensor frame following reset. A deeper sensor restart test is meaningful only if it records the ordering of external sync, receiver-ready state, and RAW arming; otherwise success/failure would still be confounded by a changed acquisition phase.
