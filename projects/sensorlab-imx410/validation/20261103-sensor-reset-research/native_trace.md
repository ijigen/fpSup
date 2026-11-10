# IMX410 native restart / suspend trace

Offline source and original-byte review, 2026-11-03. No camera, USB, card, build, or product-code operation.

Evidence classes: **C** = original firmware/decompiled control flow; **D** = previously archived measurements; **I** = interpretation, not measured.

## Result

No native operation reviewed here can be called a proven **sensor FIFO flush**. Three distinct operations must not be conflated:

1. `0011=0; 0011=1` is a mode/startup toggle (**C**). The firmware has no register readback, delay, or completion check in that method. Calling it a full sensor reset or cache clear exceeds the evidence. A training/startup latch is also possible; native code alone does not name the hardware bit.
2. `0000` bit 1 plus `00CA/00C5/00C6` and GPIO `0x544` is a much more extensive native suspend/resume path (**C**), used during extended exposure. Its effect on sensor line buffers is unknown (**I**).
3. `C0128D60` changes SoC receiver/link registers, not sensor registers (**C**). Any reset effect here is not a sensor cache clear.

The latest archived first-frame evidence places the fault somewhere between sensor output and RAW DMA. These code facts do not settle which side emits/counts the extra leading row.

## Byte identity and vtable numbering

Source image: `out/MAIN_c0000000.bin`, SHA-256 `92a8ee993f6c3d66c251e88d45a2ccd5135c6cf7342717784321c2ed506e2fb4`.

The IMX410 object's `+0xD0` points to `0xC0B5FCC0` (`blk_c03.c:25631`, constructor `C03255B0`). Original words at that table are:

| Table offset | Address | Label in decompilation |
|---|---|---|
| `+00` | `00000000` | header |
| `+04` | `C0B5FC8C` | type metadata |
| `+08` | `C03256E8` | destructor / v0 |
| `+0C` | `C03233D8` | v1 init |
| `+44` | `C0324EF0` | v15 register 0002 bit 0 |
| `+48` | `C0324F40` | v16 register 0011 toggle |
| `+5C` | `C0325078` | v21 receiver/link enable |
| `+64` | `C03250B0` | v23 arithmetic conversion, no I/O |
| `+74` | `C0325110` | v27 suspend/resume |

These functions are **ARM32**, not Thumb. `native_rom_audit.json` / `native_rom_disassembly.txt` retain exact bytes and decoded instructions. v23 is not the link operation: v21 at `+0x5C` is.

## Exact ordinary mode-switch ordering

`SetImgMode_s C0313400` → `C0314708` → `C03149B0` (`blk_c03.c:14592,15264,15352`). Relevant ordering:

1. Disable RAW receiver/evaluation blocks, prepare table state.
2. `C0126560(1)` → `C0125C50` → `C0127FC8` stops the SoC timing-generator path (`blk_c03.c:15304`; `blk_c01.c:24593`). This is **not** a sensor standby-register write.
3. v6 `C03234A0` → `C03258C8` writes 161 mode registers, then `00CE=0` and the 24-bit `00D1–D3` alternating `0x2FFFA/0x2FFFB` marker. `C0326D88` is empty. Up to ten optional override pairs follow in v6.
4. In the 161 writes, ordinals **32/33/34** are `00C5=0 / 00C6=0 / 00CA=1` in **all 70 stock rows**. The same-colour pairing registers come later: `0242` #36, `0278` #38, `0279` #39, `027B` #40, `08B6` #160, `08B7` #161. These are a single ordered table, not an independently established atomic transaction.
5. `C03149B0` sets timing/window, invokes v16 at table `+48` (source line 15426), then prepares gain/exposure and pipeline state.
6. `C0126560(0)` starts the timing generator; **after that** v21 at table `+5C` enables the receiver/link path (source lines 15535–15539).
7. The existing max(table delay, readout-start) wait and receiver enable follow.

**C**: Ordinary mode-switch does not surround the table writes with v27 suspend/resume. This makes proper standby sequencing a distinct research variable, but does not establish that the original sequence is wrong.

## 0011 toggle: exact calls, bounded meaning

`XC_ImageSensorIMX410::v16 C0324F40`, `blk_c03.c:25275`:

```text
C0324F48 mov r1,#0
C0324F4C mov r0,#0x11
C0324F50 bl C0322C70     ; bus logger sees LR C0324F54
C0324F54 mov r1,#1
C0324F58 mov r0,#0x11
C0324F5C bl C0322C70     ; bus logger sees LR C0324F60
```

It immediately returns success. The common writer `C0322C70 → C0126550 → C0128898` sends the register/value to serial controller `21C00114/118`; no sensor-side acknowledgement or register readback is used. Thus a successful function return does not establish that internal row-pair state, exposure charge, or a serial FIFO was cleared.

The same v16 also occurs in still `PreExpos_s` after exposure setup (`blk_c03.c:16705`). Its use is broader than a mode-table commit alone. The public-facing phrase “stop and restart the sensor” in older notes is stronger than the semantic proof currently available.

## Receiver/link operation is separate

v21 `C0325078` executes `C0128E68(0x29); C0128D60(1,0)` (original calls `C0325084`, `C0325090`). `C0128E68` sets RAM flag `C31D8E7D`.

The forced `0x29` branch in `C0128D60` (`blk_c01.c:25224`) does:

```text
30100B00.bit0 = 1
C0000A08(0xD2)
30100B08 = 0xFF
forced flag = 0
```

It does **not** pulse that bit low first in this forced branch and does not write the sensor. Other branches do clear bit 0 and delay, but cannot be silently substituted for the actual forced path.

Delay units: `C0000A08(n)` runs `C0000CBC((n * C3033260) >> 4)`. Its calibration `C00008C8` measures 11,000 versus 1,000 spin iterations using the timer described as 12,000,000 ticks/s by `C0016190`; scale is `(timer_frequency/100 *16)/(tick_delta)+15`. This corresponds to approximately **microseconds**, plus rounding margin, rather than an OS millisecond sleep (`blk_c00.c:300–352,426,19831`). `0xD2` is therefore an approximately 210 µs calibrated busy delay; no oscilloscope measurement was made here.

## Native stronger suspend/resume candidate

v27 `C0325110`, `blk_c03.c:25410`, is **guarded by `C0125CA8() > 15000`**. `C0125CA8` computes frame period in µs from live timing-generator HMAX/VMAX/tail (72,000 kHz return from `C0128880`) and the current frame multiplier, unless overridden by callback. At simple rates faster than about 66.7 fps it is a **no-op**. Do not bypass this guard to “try a flush”.

| Suspend (argument nonzero) | Resume (argument zero) |
|---|---|
| `00CA=0` | `0000 = shadow & 0xFD`; update shadow |
| sleep 1 ms | configure GPIO `0x544`, drive 0 |
| `0000 = shadow | 2`; update shadow | sleep 12 ms |
| `00C6=1` | `00C6=0` |
| `00C5=0x11` | `00C5=0` |
| configure GPIO `0x544`, drive 1 | `00CA=1` |
| | sleep 1 ms, then v21 receiver/link enable |

The `0000` shadow is `C343B688`, read by `C0325840` and written by `C0325858`. Init writes physical `0000=4` but stores shadow `0`; the shadow is not a readback of all register bits. Replacing this with a guessed physical read-modify-write would change native behavior. GPIO `0x544` hardware identity is not proved in this review.

Native callers include extended exposure loops `C0318490` and `C031D0E0` (`blk_c03.c:17437,20370`), with resume in stop cleanup (`20549`). This is not an ordinary REC-start FIFO-clear API. Its minimum waits, frame-period guard, GPIO, timing-generator and link state all belong to the candidate transaction. Merely replaying CA/C5/C6 writes is not equivalent.

## 0002 bit 0 is not a demonstrated group hold

v15 `C0324EF0` RMWs shadow `C343B68C`, then writes `0002`. v14 `C0324EC8` forwards to it. Its callers in `PreExpos_s C0316CA8` set or clear bit 0 according to the exposure-path flag (`blk_c03.c:16660,16685`); acquisition completion clears it (`17663`). It is not used to bracket the ordinary 161-register mode-set, and no register-latch completion test follows. **Exposure-mode control** is a defensible tentative label; **group hold**, **output mute**, and **FIFO flush** are unproven. Do not borrow another Sony model's register-name mapping.

## Dynamic AE values and startup interpretation

v10 `C0323818` (`blk_c03.c:24604`) overwrites `041F/05E2` according to analog gain, unless RAM override `C343B698` is active:

- gain `< 0xDFD`: `041F=0`, `05E2=0`;
- gain `>= 0xDFD`: `05E2=1`, `041F=0x0E` in low-conversion-gain or `0x1D` in high-conversion-gain;
- updates `05A6/05A8/05E1`, then `003D–0040` gain pairs.

The peer evidence audit finds these writes ~51–54 µs after `0011=1` in archived good/bad takes. Thus mode-table `041F=0E/05E2=1` are **not persistent mode-only settings**. Any hypothesis based on those table values must track subsequent AE writes and the time at which the sensor latches them. This remains a timing hypothesis, not a proven fault.

## Appropriate next boundary

An offline control-flow test can verify the ordering, guard, and restore paths of a proposed native suspend/resume transaction. It cannot prove sensor row buffers or SLVS line phase are cleared. A future authorized experiment would need to separate (a) unchanged sensor registers with altered receiver arm timing, (b) a complete native suspend/resume before the same acquisition, and (c) baseline, while retaining first-row validity evidence and a stock control. No such experiment was performed here.
