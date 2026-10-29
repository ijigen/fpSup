# 20261027-bufa-fmtcode — BUFA0 format codes the firmware never writes (standby, RAM only)

Tool: `host/bufa_fmtcode.py` = imx410-lab `bufa_probe.py frame` unchanged, plus 0x3018210C = CODE right after its window call.
Mode 053 MONIT1_60 (2016×1344, still standby). Receiver window cut to 320 rows; class-0 buffers 4.5 MB each with guards;
line length left at the 12-bit value (756 words). Everything restored by bufa_probe (restore_diff only status counters 0x301821F0/F8).

| code | ran? | words written per line (0x301821F0 high half, and the buffer) | what it is |
|---|---|---|---|
| 0 | yes | 756 = 2016 × 12 / 32 | 12-bit linear (reference) |
| 5 | **no** | buffer byte-identical to code 0's frame (only the tail sentinel) | not a format |
| 6 | yes | **644** (≈ 10.2 bpp); rest of each 756-word line untouched; no overrun | **compressed** — decoded as 10/11/12-bit linear it correlates 0.13/0.19/0.01 with the reference |
| 7 | yes | 644, same layout as 6 (new frame over code 6's data) | same as 6 |

Conclusion: **BUFA0 has no 11-bit linear packing.** Linear formats are only the firmware's 0=12, 1=14, 2=10, 3=8, 4=16
(FUN_c06306e0); 6/7 are the compressed mode (the firmware writes 0x806 for it, ratio in 0x30182130 — left at its baseline here).
So 11-bit AD data either stays in the 12-bit container (one zero LSB, 8.3 %), goes to BUFA 10-bit (one real bit dropped),
or is repacked by the CPU.
