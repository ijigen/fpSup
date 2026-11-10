# First-frame sensor-reset investigation: evidence boundaries

2026-11-03. Offline only: archived command logs, recorded DNG audit results, native decompilation and existing emulation reports. No camera access, new captures, product changes or sensor writes.

## New finding: two alleged mode-specific registers are gain-dependent

The latest `notes/FIRST_FRAME_PURPLE.md` and `validation/20261103-purple-2x2/README.md` group `041F=0E`, `05E2=01`, `0790=01` as common to 1×1 and 1×2 but absent from 2×2. **The first two values are not a necessary condition for this fault.**

Re-read all 35 original `20261103-first-frame-purple/bus/tNN/bus.json` files. Labels come from the independent saved DNG audit `20261103-first-frame-purple-review/row0-audit.json`, not from assumptions about mode:

| Register | Last logged value before the first `0011=01` | Logged writes in the following 200 ms |
|---|---|---|
| `041F` | `00`: 35/35 takes | `00`: 105/105 writes |
| `05E2` | `00`: 35/35 takes | `00`: 105/105 writes |
| `0790` | `00`: 9 stock takes; `01`: 26 custom takes | No writes |

Those 26 custom 1×2 takes comprise **23 shifted and 3 normal** first frames. Both `041F` and `05E2` are already zero in the failing examples; clearing them cannot be the missing universal flush.

Native `XC_ImageSensorIMX410::v10 @ C0323818`, `out/decomp/full/blk_c03.c:24604–24656`, explains the difference:

- The gain input is capped at descriptor `+0x54`.
- With the override disabled, a value below `0xDFD` writes `041F=00`, `05E2=00`.
- At/above that threshold, it writes `05E2=01` and `041F=0E` or `1D`, selected by object state `+0x34`.
- It then writes gain registers `003D–0040`.

The dark tests deliberately used high gain; an initial bus segment that includes AE writes is not a pure mode-table signature. This does **not** exclude a gain interaction in the three shifted 1×1 dark takes, but it excludes the stronger claim that `0E/01` explains the 1×2 failures. `0790` remains a genuine observed difference whose meaning is not established here.

Reproduce only this offline analysis:

```sh
python3 -B projects/sensorlab-imx410/validation/20261103-sensor-reset-research/audit_bus_boundary.py
```

`bus_boundary.json` contains all 35 bus-file hashes, the prior row-audit hash, each take's sequence and these counts. The script imports no camera tooling. It records software writes, not sensor readback or internal latch state.

## “First recorded frame” is not yet “first sensor frame after restart”

The bus timestamp origin here is the first `0011=01`, logged from caller `C0324F60`. For example, shifted take t03 has:

| Relative time | Recorded sensor command |
|---|---|
| +53 / +58 µs | `041F=00`, `05E2=00` |
| +133 µs | SHS write, caller `C0325804` |
| +4.078 ms | SHS write |
| +4.139 / +4.145 ms | `041F=00`, `05E2=00` |
| +133.916 ms | SHS write |
| +167.957 ms | Next gain update begins |

`notes/FIRST_FRAME_DMA_START_RE.md:37–40` places the RAW arm after the +133.9 ms shutter branch and before the +167.9 ms periodic update: roughly sensor frame 4–5 at 29.97 fps. **That placement is a native-call-chain inference; the bus log itself contains no BUFA arm event or sensor frame ID.**

Consequently, a sensor FIFO that emits one incomplete frame immediately after restart is not yet sufficient to explain this recording fault. It would also require the incomplete data to survive until arm, a later sensor state transition, or the inferred mapping to be wrong. A startup flush can be relevant, but the missing temporal link must be measured rather than assumed.

## What the pixel evidence establishes

- Saved bad DNGs contain a +1 raster-row shift, a partial/anomalous leading row and no complete final row in the file trailer. The independent packed12 decoding agrees with tifffile. These are direct file observations (`20261103-first-frame-purple-review/README.md:8–30`).
- Thirteen of the original 23 bad first rows contain valid JPEG DHT/SOS structures. This strongly supports reused host DRAM as the stale material. Common headers do not identify the previous allocation, and the sensor need not contain any JPEG buffer for this to happen.
- Nine bad examples have four exact repetitions of one 12-pixel group at the beginning of row 0 (`FIRST_FRAME_DMA_START_RE.md:71`). This favors a word/line handshake or replay mechanism over ordinary scene noise. It does not locate that mechanism uniquely in the SoC or sensor serializer.
- Clearing old bytes in the destination would not move the subsequent image rows back or recover the missing final row. Host buffer clearing and sensor stream/counter reinitialization are different hypotheses.

**Boundary:** the reviewed live artifacts are DNG files plus sensor-write logs. `20261103-first-frame-mmio-diff` is explicitly an offline trace with waits/counters stubbed and MMIO behaving as RAM. `FIRST_FRAME_REPAIR.md:177–180` explicitly says the sentinel has not run on camera and real cache behavior was not emulated. I did not find a same-frame live DMA-completion snapshot among these referenced sets. Thus “row 0 was left stale” is well supported; “the exact moment when the physical DMA failed to overwrite it” is not independently measured by these artifacts. A post-DMA overwrite or pointer-boundary error is less direct than the current leading hypothesis but is not excluded solely by the saved bytes.

## Existing negative controls should remain narrow

| Existing control | What it excludes | What it does not exclude |
|---|---|---|
| 14v2 HMAX 1000: 8/10 shifted | Raising HMAX to this tested value is not a cure | Receiver/sensor phase interaction or all timing faults |
| Vertical RWZM 1032: 10/10 shifted | Exact ratio `0x400` is not necessary | RWZM startup, anisotropy or small initial phase values in general |
| Stock UHD on BUFA1/start 4: 0/29 | BUFA1 or code 4 alone is insufficient | A code-4 interaction with the custom RX window or line-valid timing |
| SensorLab 2×2: 0/10 | A shared runner/virtual-slot defect affecting every mode | A rare fault or mode-dependent receiver behavior |
| Equal software waits and sensor-write values | No simple static value difference between good/bad takes | Hardware latch timing, line phase, FIFO state or pending IRQ state |
| 1×1: 3/14 shifted | The symptom is not observed only with 1×2 | Whether the same root cause explains both groups; dark/high-gain conditions differ |

Stock FHD mode 106 is **BUFA7** in the corrected native emulation; the old BUFA1 inference in `FIRST_FRAME_DMA_START_RE.md` is superseded by `20261103-first-frame-mmio-diff/README.md`.

The crop-start hypothesis also remains open: DC 4020 changed the sensor's physical window but retained software receiver y0=20. That experiment did not independently move the receiver away from the first valid sensor rows.

## Smallest discriminating follow-up, plan only

1. **Establish event identity before any reset experiment.** A bounded camera-side record should associate the same take/frame with `0011` restart, BUFA1 arm, first completion and SRecRaw arrival. Record the frame/line counters, relevant active/status bits, destination/raster address and fixed small samples of row 0/1 and the final row. Avoid a full-frame CPU copy. This separates sensor startup time from the first saved-frame time and distinguishes acquisition from later handoff.
2. **Separate “flush sensor” from “flush receiver.”** For any documented candidate identified by native/cross-vendor tracing, record its actual scope: sensor serial reset, readout/standby, register latch, SoC receiver reset, or host cache maintenance. One candidate per trial; an apparent improvement after a combined restart is not proof of a sensor cache.
3. **Use a sensor-stable arm control if later justified.** Keeping a known-good sensor stream unchanged while rearming only the receive path would directly test whether the bad first frame can be recreated without sensor restart. Conversely, sensor restart with a pre-established synchronized receive path would test the other side. These require separate ownership/synchronization design and are not commands to execute now.
4. **If timing is the candidate, vary measured phase rather than blindly adding a delay.** “Wait another frame” can shift arm phase and mask a receiver issue. A clean boundary established from current frame/line observations has more explanatory value than a larger sleep alone.

No firmware patch or live trial is justified by this audit alone. The new actionable result is to remove `041F/05E2` from the purported reset/mode discriminator list and retain the sensor-versus-receiver boundary until measured.
