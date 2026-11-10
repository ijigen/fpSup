# CPU ×2 (ISP HBIN option, hbin = 2)

## Decisions (Bei, 2026-11-05) — read before any change; every brief and review checks against this list

| # | Decision | Status of the code |
|---|---|---|
| D1 | **It sits on the ISP pipeline**, in RWZM's place: the firmware sees a NATIVE half-width take (profile, allocation, DNG, writer, Lossless all native). Not a recording-side step. | Done offline: the pass runs in its own worker task while BUFA0 writes the frame; SRecRaw only waits a bounded time for the last strip ("Per-frame pass (streaming)") |
| D2 | **Like RWZM/HBIN, no frame-sized staging**: process strips as the DMA writes them (follow the BUFA0 write cursor 0x30182184), finishing right after the frame completes. | **Not possible as stated (11-05)**: 0x30182184 read 0 live in all 16 samples and at completion, and offline it is a configuration word, not a cursor; no BUFA0 line counter is known ("D2: no progress source"). v3: still in place, no staging, but each frame is binned **after** BUFA0 completes it (while the next is written); SRecRaw waits up to 2 frame periods; the pass must sustain one frame per period or the take stops (D3) |
| D3 | **Every frame is binned, no exceptions** ("他又不是 lossless"): no pass-through of an unbinned frame; anything that cannot be guaranteed is refused at commit, and a failure while recording stops the take (fail closed). | Done offline: refused at commit (`AP_E_CPU2`); the recipe core never offers a recipe whose geometry / merge the commit refuses (mv 3 excluded; `CpuX2GuardTests`); during a take every failure drops the frame through the firmware's own message +0xE4 path, which stops the take (cDevt_stop). No path passes a frame on unbinned (mutants) |
| D4 | **Equal weight only**: `(a+b+1)>>1`, same colour. | Done (tools/cpu_h2) |
| D5 | **12-bit and 14-bit** readouts both. | Both ADs offered and both recorded at their own depth: a 14-bit AD records **true 14 bit** through h2_p14 (D11 difference (4), Bei 11-05 choice B); a 12-bit / 11-bit AD records 12 through h2_p12. (D11's first version, 11-05, recorded the twin's 12-bit container for a 14-bit AD and left h2_p14 unreachable; superseded) |
| D6 | **Zero copy, in place** in the frame's own buffer (allocation 2× so the full-width DMA lands in it). | Done (allocation hook C037ACDC) |
| D7 | **Post-repairable 2×2 alignment**: equal weight leaves a known ¼-px CFA offset; write a private DNG tag naming the merge (H: CPU ×2 equal, V: sensor bin) and the per-colour offsets, so a host tool can realign before demosaic. | Done offline: tag 0xFD58 (UNDEFINED × 32, layout in "D7: the private tag") on IFD 0 through the IFD writer's own setter |
| D8 | **Do it all** (Bei chose "直接全部做"): build the whole feature; don't gate on a separate throughput measurement first. | Recipe core, apply unit, per-frame pass, tag and UI (v0.7.38test, "UI") done offline; the live test is open |
| D9 | **If the CPU route fails, remove it from SensorLab**: restore `validation/20261105-clean-v0.7.37test` (README has the commands), delete tools/cpu_h2 and this note. | Snapshot saved |
| D10 | isp-lab `quality.py` may be edited for hbin 2 (Bei: A). | Done |
| D11 | **No exceptions: a CPU ×2 recipe IS its RWZM twin** (the same sensor merge + ISP with RWZM ÷2 to the same RES). Everything the firmware sees — LV, standby, preview, record descriptors, TIM, profile, DNG, RS — is copied from the twin. Allowed differences: (1) RWZM coefficients unity, (2) the BUFA hardware line = full width, (3) allocation ×2 + the CPU pass, (4) **record bit depth** (Bei 11-05, **choice B**): 14-bit when the AD is 14-bit, with everything that follows from it (plane code +0x84, rec14 → BlackLevel scale, DNG BitsPerSample / packing, h2_p14, line bytes, FORMAT / UI 14bit, need_mbps, the BUFA0 line check). (1)–(3) are invisible to the firmware; (4) is the native 14-bit recording's own. A test diffs every CPU ×2 recipe's slot/descriptors against its twin and fails on any other difference (12-bit AD: (1) and (2) only). Open risk: if the LV taps the pipeline after RWZM, the LV must keep the twin's RWZM path (or RWZM stays on for the LV branch only). | Live 11-05 (v0.7.38test) violated it. **Done offline (11-05, "D11: the twin")**: apc_build builds the twin and changes only profile +0x64 (record RWZM H → 1023), hw_w and, for a 14-bit AD, the record bits (+0x84 = 8, rec14 = 1); `CpuX2TwinTests` diffs every field against exactly that set. The private tag 0xFD58 (D7) counts under (3); its bits byte follows (4) |


## D11: the twin (2026-11-05, offline)

**What was wrong (live 11-05, v0.7.38test).** The CPU ×2 slot carried its own ISP plan: window 6048 at 1:1 with a
3024 record, so the formula chose path D (record 1:1, preview RWZM ÷3 = 3072) and a preview visible of *the record's
1:1 field* — 992 × 661 of a 2016-px source, i.e. the centre half of the line (exactly the live sv). On a 1×2 readout that half is
anamorphic, so the 3:2 LV box stretched it ~2×. Standby the same (sv 992×661 / sr 1008×671 are those words, cut to the
cap). The twin (same key, ISP hbin 1, RWZM 2048×1024) is path **E3**: preview = CRCT bins ÷3 at RWZM unity, visible
1984 × 661, raster 2000 × 671 — the whole line.

**Every difference found** (host diff of every apc_out field, all 24 CPU ×2 recipes of the QS cells × 3 rates, before
the fix): profile words 0x0C/0x10/0xD8/0xE0 (preview raster), 0x20/0x28 (visible), 0x38 (16 for E3), 0x58/0xC4 (preview
bins), 0x60/0xD0 (preview RWZM), 0x64 (record RWZM), 0x84 (plane code 14 vs the twin's 12); the standby copies
sv/sr/sb, src/vis/ras; rec14 (and with it the BlackLevel scale); hw_w. Everything else (TIM/META/R28/R38/R14/R68/REG/
R10, carrier/engine, rec, box/asp/det_h, DefaultScale, FrameRate, binfilt, rok/sok) was already equal.

**Fix.** `core_quality_twin` (core.c, the same `q_isp` the candidate loop runs, for the CPU ×2 case's own readout)
gives the twin; `apc_build` builds it unchanged and then sets only (1) profile +0x64 = 1023 (unity, the formula's
UNITY_STOCK) and (2) hw_w = 2·rec_w. The recipe core still offers the same CPU ×2 recipes (every one has its twin in
the core's own list, RWZM exactly 2048×1024: `test_every_cpu2_slot_is_its_twin…`). The first version stopped here, so a
14-bit AD recorded the twin's 12-bit container (RWZM carries 12 bits) and h2_p14 was unreachable.

**(4) the record bit depth (Bei 11-05, choice B).** The CPU ×2 record does not pass RWZM (its H ratio is unity, (1)), so
the 10-30 container rule ("a 14-bit AD that scales records 12", notes/RWZM_14BIT_CHECK.md) does not apply to it:
`apc_build` evaluates the rule on the record's own RWZM H (`rec_zh` = 1024 for CPU ×2, else the spec's), the twin's zv /
bins otherwise. So a 14-bit AD records true 14. The four allowed differences are now (1) +0x64 unity, (2) hw_w,
(3) allocation ×2 + the pass (ap.c), (4) the bits — only when the AD is 14-bit.

*Which fields (4) is, derived not guessed* (`CpuX2TwinTests.test_bits_set_is_the_native_one`): every native 1:1 14-bit
recipe of the QS cells built twice — as is, and with the container rule forced — differs in exactly two apc_out fields:
profile word **+0x84** (plane code 8 vs 7; +0x80 stays 7) and **rec14** (1 vs 0). In `core_isp_plan` the bits enter only
the R7 plane-code switch; the readout key (and so TIM / HMAX / R15) is the AD's in both. Everything else follows in
ap.c from those two: `ap_h2_guard` bits = rec14 ? 14 : 12 → H->bits / row = hw_w × 14 / 8 (OG 3K: 10584 B) / n =
rec_w × rec_h × 14 / 8 / need_mbps; `ap_h2_bin` picks h2_p14 (last step from a copy); the BUFA0 line check
(0x30182114 × 4 == row, FUN_c0630e90's descriptor format 1 from plane code 8); the BlackLevel hooks (H_BLK6 / H_BLK)
answer 14 for a rec14 slot; the D7 tag's bits byte; the DNG BitsPerSample / packing are the firmware's for plane 8.
UI: slqs.c `rec_bits`, dcres.html `recBits`, site_page.js `recordBits` count hbin 2 as 1:1 again (FORMAT 14bit, MB/s at
14 bits). core.c / isp-lab quality.py are unchanged (the twin keeps the case's bits; the rule lives in apply).
Tests: `CpuX2TwinTests` allowed set = {+0x64, hw_w} ∪ {+0x84, rec14 if AD 14}, values checked; the firmware view
(profile + slot) the same; `CpuX2StreamTests.test_a_14_bit_ad_take_records_true_14_through_h2_p14` (byte-exact
against the 14-bit reference, row 7336 for S35, plane 8, BlackLevel 14) and `test_a_14_bit_take_on_a_12_bit_line_stops`;
CpuX2TagTests bits byte = 12 / 14.

**Where the LV taps (task 2).** The path selector (XC_ImageSensorIMX410::v37 C0325228, decompiled and now run for real
in `test_the_firmware_view_of_cpu2_is_the_twins`) compares record vs preview **RWZM only**; taps pass through. With +0x64
at unity the CPU ×2 profile goes to branch **B** (record = preview = unity): a0 Crmf (the pre-RWZM window line, kind ≠ 4),
main pipeline = the preview's bins ÷3 at RWZM unity. The twin goes to branch **E**: a1 RWZM → BUFA1 for the record, main
pipeline = record RWZM + preview bins, and its LV taps **before** RWZM (isp_formula R9/R14: E1/E3 previews measure
window / (preview zoom × taps); 10-28 p5 E3 FOV 0.948 predicted = measured). So the LV sees ÷3 bins at unity in both;
standby (branch A, no record) is byte-identical. The branches are separable through the profile words alone (record
+0x64/+0xD4 vs preview +0x58/+0x60/+0xC4/+0xD0), so "RWZM stays for the LV" needs nothing extra: for a twin whose LV is
after RWZM (path C, preview = record zoom) the CPU ×2 profile goes to D and the main RWZM keeps the twin's 2048.
**Risk:** B with preview CRCT bins ÷3 has no stock precedent (the 17 stock rows with preview bins are all E); with
0x300F0870 = 0 the §4b arbitration moves the horizontal bin to the second level (Hbin2), still one ÷3. Fallback if the
LV is wrong: preview RWZM ÷3 (0x60/0xD0 = 3072, bins 0) — same visible/raster, a fourth difference to ask Bei about.

## D2: no progress source (2026-11-05)

- 0x30182184: written only by FUN_c01498f0 (`param[3] & 0x3FFFFFFF`) among the start / plane words 0x30182180..1BC
  (FUN_c0181858 reads 0x30182180/188/190/… as eight destinations); FUN_c0630620 just hands `it × 4 + 0x40000000` to
  the callback. Live: 0 in all 16 samples and at completion. A configuration word, not a cursor.
- 0x301821E8: frame-slot index (&7; PUSH_CALLERS.md: byte 2 writing, byte 1 done, byte 0 shown) — frames, not lines.
- 0x30182048 bit 0: the completion IRQ status. 0x30182110 / 0x30182114: lines / words per line (FUN_c06306e0 config).
- 0x30182210 / 2214 / 2218 / 2280: BUFA1's analogues (lines, stride, …, start) — configuration, as in the trace.
- No line-done IRQ is known. So v3 bins a frame after BUFA0's completion, while the next one is written: no
  staging, in place; the per-frame budget is one frame period. `ap_h2_avail` gives 0 rows before the completion and
  only samples 0x30182184 for the record. SRecRaw waits up to `wait_ms` = ⌈2 × period⌉ ms (10..250); period =
  HMAX × VMAX / 72 MHz. A pass slower than one period per frame falls behind and stops the take (LATE / QFULL, D3).
- New guard at the destination: BUFA0's 0x30182114 × 4 must equal the slot's hardware row bytes and 0x30182110 its
  rows, else `AP_H2_W_LINE` (9) stops the take — this checks D11 (2) on the camera (the DMA must write hw_w × rec_h,
  exactly 2n). `line_words` / `lines` / `line_bad` are kept in ap_h2 (v3).

**Throughput needed** (h2 `need_mbps`, input = hw bytes per period): OG 3K 1×2 12-bit 25p: 6048 × 2014 × 1.5 B / 40 ms
≈ 457 MB/s; **14-bit (D11 (4)): 6048 × 2014 × 1.75 B / 40 ms ≈ 533 MB/s** read (+ half that written). Live 11-05
measured ~81 MB/s (338 KB strips in 4.2 ms avg; 14-bit then), about the uncached copy rate. h2_p14 costs 4.08
instructions / input px against h2_p12's 1.005 (tools/cpu_h2), so a 14-bit take is the harder of the two: ≈ 50 M
instructions per OG 3K frame, ≈ 1.24 G/s at 25p; the probe (`sq_test 50`, mode 0x10000) must show it before a take.

## Speed: aliases (2026-11-05)

Offline checks: SensorLab is built SL_F_CACHED_OK, so the loader enters it at the cached alias and `A` lives there;
the raster is addressed through `ap_h2_cached()` (0x4… + 0x80000000; an address already 0xC… stays — the old
`ras + SL_ALIAS` would have wrapped a cached raster to 0x4…, uncached); FUN_c0631640 accepts either alias, so queue /
mark matches compare physical addresses. The task entry and trampoline are handed to tk_cre_tsk at their cached alias
whatever alias the commit ran at; the worker records `run_pc` (its own PC-relative address) and `run_sp`; the first
strip's address is `ras_c`. Cache maintenance: MVA ops only (DCIMVAC / DCCIMVAC / DCCMVAC), never FUN_c000e91c
(set/way) per frame. The firmware MMU table (FUN_c000e7b0 defaults: 0x40000000 + 2 GiB non-cacheable, 0xC0000000 +
1 GiB WBWA) confirms the 0xC… alias of the RAW pool is cacheable. Nothing offline explains 81 MB/s if `run_pc` and
`ras_c` read 0xC… live — then the probe below decides between memory and maintenance cost.

## Throughput probe (no recording)

`ap_h2_bench(mem, buf, bytes, mode)` — the worker's own `ap_h2_bin` (invalidate, kernel, clean, 32-row strips) over
`bytes` of a caller buffer, through its cached alias; returns µs per MB (10⁶ B) of input, or −1 recording, −2
arguments, −3 D-cache line, −5 kernel. mode: bits 0–15 the line in px (0 = live CPU ×2 slot's hw_w, else 6048;
must be a multiple of 32), 0x10000 the 14-bit kernel, 0x20000 no cache maintenance, 0x40000 run at `buf` as given.
It overwrites the buffer. Results also in ap_h2 `bench[8]` = {µs, bytes, address used, mode, rc, CPACR, rows, µs/MB}.
Shell (standby, not recording, after `heapalloc` / cave.claim of e.g. 16 MiB class 0 → `buf`):
`callfn <sq_test> 50 <buf> 0x1000000 0` (cached, maintenance), `… 50 <buf> 0x1000000 0x20000` (no maintenance),
`… 50 <buf> 0x1000000 0x40000` with the uncached 0x4… buf (uncached rate). MB/s = 10⁶ / result. `sq_test 49` returns
the ap_h2 address (read it with MEM1 / mem get). NEON runs in the calling (shell) task, as in the worker (live: 211
strips without a fault); CPACR is recorded, not enforced.

## What the next live test must check (v3, in this order)

1. **Standby LV** of OG 3K 1×2 + CPU ×2 shows the full width at the twin's geometry: screenshot identical in framing
   to ISP HBIN 1 (sv/sr = the twin's: 1984 × 661 / 2000 × 671, was 992 × 661 / 1008 × 671).
2. **Probe first, no recording**: `sq_test 50` cached / no-maintenance / uncached over 16 MiB at 6048 px; record
   µs/MB for each. If cached < ~460 MB/s (OG 3K 25p need), the take cannot run; report and stop there.
3. Record a short take: **record-time LV** = the twin's (full width, not centre half); BUFA0 `line_words × 4` =
   9072 (14-bit AD: 10584) and `lines` = 2014 (`line_bad` 0; else failed = 9, LINE); `ras_c` and `run_pc` are 0xC…; `run_sp` noted.
4. ap_h2: `wait_ms` (25p: 80), `need_mbps`, `binned` vs `queued`, `max_us`, `total_us / strips`, `failed`
   (7 LATE / 3 QFULL means the pass is too slow, as designed); `samp[]` confirms 0x30182184 stays 0.
5. If frames are binned: the DNG is 3024 × 2014, 12-bit (14-bit AD: true 14, D11 (4)), DefaultScale as the twin's, BlackLevel at
   the recorded depth, tag 0xFD58 present;
   the picture is the full width, equal-weight binned (compare with an ISP HBIN 1 take of the same scene).
6. The stop path (+0xE4 = 1) closes the clip cleanly; `SPP_metadata.xmp` non-zero; no freeze (as item 5 of the old list).
7. Still open from the old list: TK-OS d0–d15 save for task attr 0x41, `tk_dly_tsk(1)` = 1 ms, `frame[0x6C]`, core type.

Facts to keep straight: the CPU is built as Cortex-A9 (`-mcpu=cortex-a9` everywhere); the core type and count are not
verified (an earlier version of this note said "single core Cortex-A7": withdrawn). Lossless claims C038BFF0 exclusively.


## Recipe core (hbin 2)

2026-11-05, offline only. Bei's decision: CPU ×2 replaces RWZM on the ISP pipeline. Kernel: `tools/cpu_h2/`.

### Rules (quality.py `isp()` / `candidates()`, core.c `q_isp()` / `core_qualities_tol()`, bit for bit)

- **Bins.** `BINS = ((1,1), (1,3), (3,1), (3,3), (2,1))` (`CPU2 = 2`, `cd_qbins`). The new entry comes last, so every
  existing recipe keeps its order and `seq`. CRCT vbin stays 1. Vertical reduction comes from the sensor's mv only.
- **Sensor.** The readout has to have mh == 1 (full-width read) and mv 1 or 2 (mv 3 is refused at commit, `AP_E_CPU2_MV`;
  added 11-05: OG / HD / S35 half width × H/3 offered `v3-cpu2` recipes apply refused). Other keys are skipped before
  the ISP is planned. After the record is known, `quality.cpu2_geom_ok` / core.c `cpu2_geom_ok` drop what
  `AP_E_CPU2_GEOM` refuses (rec_w % 16, hw_w % 32, rows even ≥ 2, ≤ 8192; today the ISP plan already guarantees it).
- **ISP.** The window is the readout raster `(W, H)`, as for any case. Zoom is (1024, 1024): `_z(W // 2, rw)` and
  `_z(H, rh)` must both be 1:1, within `_z`'s 0.2 %. The hardware line must also satisfy `2·rw <= W`. Anything else
  raises `NotPossible`, which is C's `CORE_E_ISP`. When W == 2·rw (OG/HD 6048 → 3024, S35 4192 → 2096) the window is
  exactly 2·rw. When W is up to 0.2 % wider, the ISP crops it top-left, as for every 1:1 record. There is no CRCT bin,
  no RWZM and no binfilt, and the path is always B or D (Crmf mux1, true 14).
- **What the ISP sees.** `core_quality_spec` / `quality.settings` / `isp_hbin()` give the ISP hbin 1. Only the
  quality (`core_quality.hbin`, the case's `hbin`) says 2. `core_isp_plan` still refuses hbin 2.
- **Record.** rec = (rw, rec_h), with rec_h computed as today: `min(rh, H) & ~1` at 1:1. This is the native
  half-width raster the firmware gets (buffers, DNG header, writer, Lossless). visible = rec − (16, 10).
  `short_ok`/tol compares against (rw, rh) as for every recipe.
- **Bits.** The plane depth is the AD's: 14-bit AD → true 14 (`apc_build` rec14, since spec hbin == 1 at 1:1).
- **No WIDEN retry.** Widening the crop would only push W past 2·rw.
- **Hardware line.** The record route at RWZM unity writes through BUFA0 (branch D, Crmf mux1) or BUFA7, not
  BUFA1. Its line comes from the receiver window (TIM/META, 0x3010000C/0x30100024). That window is the readout plan's
  full raster W ≈ 2·rec_w, because the readout is planned for the full crop at mh 1 and the mode rows' width is W.
  The allocation and DNG raster come from the record descriptor/profile: rec_w is the half width (profile 0x00/0xDC);
  0xF4 is the full-width window. The slot carries `hw_w` = 2·rec_w (else rec_w), deliberately not named after a BUFA:
  `quality.hw_line_w(c)`, `apc_out.hw_w` → `ap_slot.hw_w`. I added no core field, because `core_quality.hbin == 2` is
  the flag. The `core_quality` layout is unchanged, so no mirror changed. `apply/test_apply.py` CpuX2Tests checks that
  the TIM x1−x0 and the mode width equal the window, and that the window holds hw_w.
- **`CORE_MAX_QUAL`.** It stays 4×40. There are at most 101 distinct pick groups (92 before this change).
  `export_core.py` now refuses the data if the groups ever exceed `CORE_MAX_QUAL`. Raising it would break
  `AP_MEM_BYTES`: +5 KiB, measured as 228232 > 225280.
- **DNG DefaultScale.** `apc_build` counts `hw_w` (2 sensor px per DNG px). So 1×2 readouts give square pixels, and a
  1×1 readout at half width is tagged (2, 1).
- **Lab matrix.** `matrix.py` excludes hbin 2 (isp_custom has no CPU pass), so `matrix.json` is unchanged.

### Not done (other tasks)

- ~~The line redirect into the private buffer and the per-frame CPU worker.~~ Done: see "Per-frame pass (streaming)".
- ~~The UI (`qs/slqs.c` rec_bits / ISP HBIN values, `preview/`).~~ Done: see "UI".
- The first-frame check (`ap.c` ~762 computes the row bytes from `rec_w`; it should use `hw_w` once the redirect exists).
- The live test.

### Files changed

- `isp-lab/host/quality.py`
- `isp-lab/host/matrix.py` (excludes hbin 2)
- `core/core.c`, `core/core.h` (comments)
- `core/export_core.py`
- `core/test_core.py`
- `apply/ap_calc.c`, `apply/ap.c`
- `apply/test_apply.py`
- `preview/fps_data.js`: regenerated. It is 837 + 12 CPU ×2 recipes. Minus hbin 2 it is identical to the old file.
- `qs/test_resmagnet.py`, `preview/test_web.py`: count 837 → 849.

### Tests (2026-11-05, offline)

**Passing**

- `core/test_core.py --mutants`: `PASS`, `mutants: 67/67 caught`. That includes the new step `cpu2`: 23 cells × 4
  cap/tol variants, the rules checked on quality.py's own output, cases that must be offered (OG 3K / S35 14v2-cpu2,
  HD 12v2-cpu2), and cases that must be refused (raster < 2·RES, a 2x merge, rows not 1:1). Five new mutants were
  all caught: any sensor merge (912 mismatches), line = rw instead of 2 rw (857), RWZM V allowed (1841), WIDEN
  retry (21), ISP spec keeps hbin 2 (765).
- `apply/test_apply.py`: Ran 82 tests, OK. This includes the new `CpuX2Tests`, which checks hw_w, rec, rec14,
  binfilt 0, RWZM off, TIM/mode width = window ⊇ hw_w, and DefaultScale. `--mutate --only=0 --only=1`: both new
  mutants caught.
- `qs/test_slqs.py`: Ran 68 tests, OK.
- `qs/test_bootapply.py`: Ran 13 tests, OK.
- `qs/test_resmagnet.py`: Ran 5 tests, OK.
- `node --test preview/test_client.js`: 13 pass, 0 fail.
- isp-lab `test_matrix` and `test_visible_tol` pass.

**Failing, not caused by this change**

- `qs/test_settings_migration.py`: 1 failure, `test_default_bytes_match_both_frozen_builds` (sid SL41). The built
  SensorLab BIN no longer equals its frozen fixture, because core/apply code changed. The QSContainer sid still
  matches. The fixture was not refreshed.
- isp-lab `test_isp_formula`: `Mutation.test_every_mutant_is_caught` fails because a mutant pattern ("C capped at 3x
  again") is no longer found in `isp_formula.py`. That file was edited Nov 2 and is untouched here.
- `preview/test_server.py` and `test_web.py`: setUpClass error, `camera_qr.h:127: 'qrdec.c' file not found`.
  `server.py` extracts slqs.c's encoder, which now `#include`s `qrdec.c` (slqs.c:1171), into a temp folder without
  it. This is the same with or without this change.

## Per-frame pass (streaming)

2026-11-05, offline only (unicorn + the real image; nothing ran on the camera). It replaces the first version, which
binned the whole frame in SRecRaw after completion and let unbinned frames through. That version broke D1, D2 and D3.
Code: `apply/ap.c`, section "CPU x2 (hbin 2): the streaming ISP-stage pass". Kernel: `tools/cpu_h2/h2_packed.S`,
assembled into the unit. Tests: `apply/test_apply.py` `CpuX2StreamTests` and `CpuX2TagTests`.

### Shape

| Where | Site (stock word) | Context | What |
|---|---|---|---|
| allocation | `C037ACDC` in FUN_c037a990 (`EBFD7EA3` `bl FUN_c02da770`) | the frame's task, r4 = frame | For a guaranteed take (below) and kind 1, returns `2n`. The reserve +0x128 is unchanged (D6). The frame is marked. If `n` differs from the slot's raster, the allocation is still at least `2n`, and `alloc_bad` condemns every arrival of the slot. |
| destination, frame 1 | `C031C550` in ContSet_Adr1 (`FA0C543A` `blx FUN_c0631640`, r0 = `[r6+0x38]`) | ContSet | Take start: the queue is cleared (entries the worker holds are abandoned) and the failure latch is reset. Then the same as below. |
| destination, later frames | `C031CCF4` in ContSet_Mem0 (`FA0C5251` `blx FUN_c0631640`, r0 = r4) | ContSet | If a marked frame's `handle + reserve` equals r0, the raster goes on the worker's queue (8 entries). If `0x30182120 & 0x11` (FUN_c0631640: start one line in, or at the last line), the take fails. The destination itself is never changed. |
| completion | `C031BB50` entry, FUN_c031bb50 (`E92D40F0`) | BUFA0 IRQ (FUN_c0630620) | The entry with that raster is marked complete. Plain stores only. |
| arrival | `C038BDB4` (`H_FFFIX`, SRecRaw prio 15) | SRecRaw | A bounded wait (40 × `tk_dly_tsk(1)`) for the frame's state BINNED. Otherwise the frame is dropped and the take stopped (below). |

The **worker** is task "SH2WSL": priority 16, 4 KiB stack, created once by the first CPU ×2 commit (UI thread) with
`tk_cre_tsk` / `tk_sta_tsk`. Tasks cannot end here, so afterwards it sleeps. Its loop is
`for (;;) if (!ap_h2_step(A)) tk_dly_tsk(1)`. The task is entered through `h2.tramp`
(`ldr r0, [A]; ldr pc, [entry]`). The entry is a `b.w ap_h2_task` in the asm block, because a C function's -fropi
address only resolves within 32 KiB of its user.

One step works on the oldest queued frame:
1. Read the cursor (`0x30182184 × 4 + 0x40000000`, the same conversion FUN_c0630620 applies).
2. Work out how many rows the DMA has certainly written:
   - a cursor value counts only if it lies inside `(ras, ras + 2n)`;
   - it is trusted only once it has been seen to move up within this frame;
   - a row is done only when the cursor is a full row past it (one row of margin);
   - after the completion, all rows count.
3. Bin up to 32 of those rows in place, then return. It never spins and never turns IRQs off for longer than claiming
   the entry.

**Priority 16:**
- It sits below MRecMgr / SRecRaw (15), SRecFile (6), SRecMgr (9), EventMgr (13) and AfMgr (14), so recording control
  and file writing always preempt it. It is above DrawMgr (17), the gyro (20) and the shell (25).
- It holds no lock and calls only `tk_dly_tsk` and MVA cache operations. Nothing waits on it except SRecRaw's bounded
  wait, and no integer priority lies between 15 and 16, so the freeze pattern (SRecFile 6 waiting on our pri-28
  writer, which held the FS lock) has no counterpart here.
- CamSch's priority is not known.
- Equal-priority tasks (several fixed tasks at 16) can delay it. If they do, the deadline turns that into a stop.

**In-place ordering.** Strip `[r0, r1)` reads input bytes `[r0·row, r1·row)` and writes output bytes
`[r0·row/2, r1·row/2)`.
- Output never passes the input already read: `r·row/2 ≤ r·row`, and within one kernel call the output cursor is
  never more than half the input cursor.
- Output never passes the DMA: `r1 ≤ cursor rows − 1`.
- The 14-bit kernel reads 4 B past a non-final strip. Those bytes are in the margin row, and their bits are masked
  off anyway. The raster's last step runs from a stack copy.
- The only byte written past a strip's output end belongs to a row that has already been read, and the next strip
  overwrites it.

**Cache** (the line size comes from CTR DminLine; 32 or 64 B is guaranteed at commit):
- Before reading each strip: invalidate from `floor(in0)` to `in1` (DCIMVAC). A line reaching past the raster's end is
  cleaned and invalidated (DCCIMVAC).
- The line that holds a strip's tail together with rows the DMA is still writing is only ever invalidated. It is
  never dirty, because outputs stay below it. It is invalidated again before the next strip reads it.
- After writing: clean `[floor(out0), out1)` (DCCMVAC), then DSB. Cleaned output lines hold only bytes below the
  cursor, so a clean can never write a stale copy over DMA data.

**D3, fail closed.** Every failure during a take ends the same way:
- `AP_W(msg + 0xE4) = 1` at the arrival. FUN_c038bd98 then takes its own drop path: log, release C0377730, delete
  C0375030, drain C037DEE0, then `cDevt_stop(…, frame+0x1100, …)` ("raw2").
- The frame is never written, and the latch drops every later frame of the take.
- The failures are:
  - not queued (e.g. a BUFA7 route never reaches our destination hooks);
  - capacity below `reserve + 2n`, or raster ≠ handle + reserve;
  - `alloc_bad`;
  - the flip/offset flags;
  - queue full;
  - kind ≠ 1;
  - kernel error;
  - **late**: the worker had not finished by the end of the wait.
- A frame the worker may still be inside is first abandoned, and SRecRaw waits for the worker to leave the strip.
- A frame the firmware drops itself (+0xE4 already set) only frees its entry.

**Commit (`AP_E_CPU2` = −12, detail):** the commit is refused unless every one of these holds:
- 1: `rec_w % 16 == 0`, `hw_w == 2·rec_w`, `hw_w % 32 == 0`, `rec_h` even and ≥ 2, and both dimensions ≤ 8192;
- 2: the sensor merge is mh 1 × mv 1 or 2;
- 3: the D-cache line is 32 or 64 B;
- 4: the worker task exists or can be created and started.

Only then is `h2.armed` set, and only for that slot. Every other slot never touches the five hooks' work. This is
tested against the pre-CPU ×2 unit (`validation/20261105-clean-v0.7.37test`): same allocation size, same BUFA0
destination register, same FUN_c038bd98 native calls, same raster.

### D7: the private tag

Tag **0xFD58**, type UNDEFINED, count 32, IFD 0 of a CPU ×2 take. It is written by `C00BA310`, the IFD writer's own
setter that DefaultScale already uses, from the DefaultScale site C02C43C0. The tree has no other user of 0xFD58: a test
scans fpSup/ and projects/. Lossless uses 0xFD4C; Gyro2's MakerNote tag is 0x4653.

| Byte | Field |
|---|---|
| 0–3 | `"SLC2"` |
| 4 | layout version 1 |
| 5 | horizontal method: 1 = CPU ×2, equal weight `(a+b+1)>>1`, same colour |
| 6 | horizontal factor 2 |
| 7 | vertical method: 0 = none, 1 = sensor equal-weight bin (IMX410_RULES §35: vbin2 uses both rows) |
| 8 | vertical factor (mv) |
| 9 | offset unit denominator: 4 (¼ output pixel) |
| 10 | bits per sample (12 / 14) |
| 11 | 0 |
| 12–19 | signed `(dx, dy)` per CFA position (x&1, y&1) = (0,0), (1,0), (0,1), (1,1) |
| 20–25 | u16 LE: hw_w, rec_w, rec_h |
| 26–31 | 0 |

**Offsets.** An offset is the merged sample's centre minus the output pixel's nominal centre, in ¼ output pixel;
positive is right / down.
- Output column `j = 2k + p` merges input columns `4k + p` and `4k + p + 2`. Their centre is `4k + p + 1`. The nominal
  centre is `2j + 0.5`. So the offset is `(0.5 − p)/2` output px: +1 quarter for even columns, −1 for odd.
- The sensor's vertical 2:1 gives the same pattern in y. mv 1 gives 0. mv 3 is refused at commit, because its sample
  centre is not established (§35: probably only two of three rows are used).
- The vertical pairing (0,2)/(1,3) is an assumption [I]; §34 notes a different phase for the sensor's *horizontal* bin.

### What the first live test must confirm (in this order)

1. **0x30182184 is a live write cursor.** It must advance during a frame, word address of the next byte, inside
   `(dest, dest + 2n)`, monotonic.
   - Offline it is only seen being read at completion (FUN_c0630620 hands `it × 4 + 0x40000000` to the callback;
     FUN_c031bb50 ignores it) and restored by FUN_c01498f0.
   - BUFA7's callback hands over its *start* register 0x30182380 instead, so the register might be an end address or a
     second start.
   - Read-only probe, with no USB during the recording: record one CPU ×2 take, then read `ap_h2_info` →
     `samp[0..15]` (raw cursor, raster) and `done_cur`.
   - Expected: several distinct increasing in-range values per frame, and `strips` > 0 before `binned`.
   - If the values are constant or out of range, the worker cannot stream. Frames are then binned after the
     completion, and the deadline (40 ms) decides.
2. The granularity: the step between samples, compared with the one-row margin.
3. `C031CCF4` runs once per later frame and one frame ahead of the frame being written, and
   `frame+0x68 / +0x128` are set by then.
4. `FUN_c031bb50` is BUFA0's completion for the record route, with r0 = the raster. Also confirm the hbin-2 recipes
   take branch D with a0, not kind 4 / BUFA7. If they take BUFA7, every take stops at frame 1 (NOQ).
5. The drop through +0xE4 = 1 stops the take cleanly.
   - Confirm the clip is closed, `SPP_metadata.xmp` is non-zero and the camera has not frozen.
   - Also the first-frame case: if `C038C800` returns non-zero, `param_1[5]` stays 0x80000000 and no cDevt_stop is
     called (the frames are dropped, but the take may continue empty).
6. Throughput. Take `max_us` per strip × strips per frame against the frame period; `wait_max` should stay far
   below 40.
7. That TK-OS saves d0–d15 on a task switch for our task (from memory notes; the IRQ path is in
   PC_SAMPLER_HOOKPOINTS.md).
8. That `tk_dly_tsk(1)` sleeps about 1 ms (one tick).
9. That `frame[0x6C]` is the requested size (the harness models it so).
10. The core type / count (build: Cortex-A9).

### Not done

- ~~The UI (`qs/slqs.c` rec_bits / ISP HBIN values, `preview/`).~~ Done: see "UI".
- The first-frame sentinel for the BUFA0 route. `ap_ff_arm` now uses `hw_w`, but it sits on the BUFA1 branch.
- FUN_c037a990's second allocation (`frame+0x12C`, C037AD88) is not doubled. It must never be a BUFA0 destination; if
  it is, its frame is not queued and the take stops.
- A host tool that reads 0xFD58 and realigns before demosaic.

### Tests (2026-11-05, offline)

See the report of this change; numbers are in the run log.

## UI

SensorLab v0.7.38test, 2026-11-05, offline only. `qs/slqs.c`, `preview/dcres.html` and `preview/site_page.js` are kept
in text parity, and `qs/test_slqs.py` checks that.

- **Option.** RECIPE sub-QS, ISP HBIN (K_HB) only: `OPTS_B[13] = 2`. It is the last option, so 0..12 (1, SOFT ×6,
  STD ×6) keep their indices. ISP VBIN still has 13 options. The footer has 14 entries (QSC_FOOT_MAX 16).
- **Label.** `CPU ×2`, with U+00D7. The value is drawn in the stock bold glyphs. qsc.h / `build_qsct.GLYPHS` map
  U+00D7 to `font_menu_LB_kigou_09` (also in SB), and C, P and U are LB letters. The space falls back to the system
  font, as in `3[1,2,1]`. So no `x` fallback was needed.
- **Small line** (ISP HBIN tile): `RWZM off · →3024`, with the recorded width `rec_w` (the half width). The RECIPE
  tile's line: `12b 1x2 CPU×2 · RS 10.7 ms`, which replaces `ISP 2x1` (vbin is always 1); one decimal and no
  visible-size suffix since 11-05 ("Display rules (single source)").
- **Grey / reasons.** These are the existing `ok_v` / `why_not`. Every hbin-2 recipe has mh 1, so with a sensor
  H merge the option greys `→S.HBIN1`, and in a cell without one it shows `not at this RES`. The short name of hbin 2
  is `CPU×2` (not `I.HBIN2`), e.g. SENSOR HBIN 2 greys `→I.HBIN1` while CPU ×2 is chosen.
- **Dial.** From 1, + lands on this axis' kernel, as before. From the kernels, + after STD 0,1,0 goes to CPU ×2.
  From CPU ×2, − lands on the kernel. On ISP HBIN, when no usable ×3 exists for the other choices (true for all
  12 hbin-2 cells today), the dial steps 1 ↔ CPU ×2. Choosing CPU ×2 never changes kh / kv / km.
- **Bits / MB/s.** `rec_bits` (page `recBits`, site `recordBits`) also counts hbin 2 as 1:1, so a 14-bit AD gives
  FORMAT `14bit` (true 14, path D). MB/s already used `rec_w × rec_h` (the half width). The lossless "1x1" bpp term
  stays off (hb × vb ≠ 1, and mv is 2 anyway).
- **Record / QR.** No format change; REC_VERSION stays 2. The record stores `rq` / `rd[K_HB]` = 2 as a plain value,
  and the QR's 4-bit hbin field carries 2. The page's `decodeRecipe` accepts any non-zero hbin. `qr_restore`
  reproduces the code exactly.
- **Website** (`site_page.js`). Chips `ISP CPU×2` (width 9 ch), legend `CPU ×2`, kernel panel two equal taps with
  `kernelCpu2` (EN / 简 / 繁). `ispZoom` already gives 1024 for hbin 2 (`⌊bw/2⌋ = rw`).

### Tests (2026-11-05, offline)

- `qs/test_slqs.py`: seq 20 (HD 3K: grey `→S.HBIN1`, SENSOR HBIN 1, CPU ×2 chosen and back, 25 fps, 14-bit, record
  line) is compared step by step with the page. `CpuX2` covers the footer (14 / 13 entries, grey, cur 13),
  `ap_sel.hbin == 2`, FORMAT 14bit, MB/s 227 at 3024×1700×14 / 25p, the record reboot, and the QR → `qr_restore`
  round trip. The mutation harness now writes the mutant next to slqs.c, because slqs.c `#include`s qrdec.c.
- `test_slqs.py --mutate "CPU x2" "kernel dial leaves" "rec_bits ignores"`: 14/14 caught (12 new, 2 old patterns
  updated). Equivalent today, not listed: the `CPU×2` reason name. Every hbin-2 recipe has an hbin-1 twin, so no
  greyed option ever needs CPU ×2.
- `preview/test_client.js`: a CPU ×2 test checks the code round trip, recordBits 14 / 12, the half-width rates and
  the chips / legend / kernel text.

## Display rules (single source)

2026-11-05, offline only, still v0.7.38test (Bei: "the effective recipe is the single source of truth").

- **Source.** Every recipe-dependent text comes from the effective recipe: `cur_recipe` (page `curRecipe`), the one
  that overrides RES, never the sub-QS picks. `qs/slqs.c eff_now()` (page `effDisplay()`) gives the RES the user gets
  (the recipe's visible + 16 × 10, else the RES), its visible size, the short flag and the merge hint. The RES tile and
  the RES WIDTH / HEIGHT sub-items both read it; FORMAT (`rec_bits`), MB/s (`mbps_of`, rec_w × rec_h) and the RECIPE
  line read the same `cur_recipe`.
- **Merge hint.** Per axis, total = sensor merge × ISP bin (mh × hbin with CPU ×2 = 2; mv × vbin). `HxV` when RWZM is
  unity on both axes within 0.2 % (`500·|z − 1024| ≤ 1024`, so the ÷3 bins' forced 1025 counts as unity); `RWZM` when
  it scales. No effective recipe (no data): the old geometric DC / RES division (`div_text` / `divText`). So OG 3K with
  sensor 1x2 + CPU ×2 (records 3024 × 2014, 6 rows short) shows `→3024×2014 · 2x2`, not `2x`; sensor 1x2 + RWZM 2:1
  shows `RWZM`; a 1:1 crop shows `1x1`.
- **RECIPE line** (Bei live 11-05): `14b 1x2 CPU×2 · RS 25.6 ms`. RS has one decimal, and the ` · vw×vh` suffix is gone
  (the RES tile and sub-items show the recorded size). A short recipe still turns the line yellow (QSC_T_APPROX), as on
  the RES tile.
- **Core / apply agreement.** `apply/ap_calc.c apc_cpu2_check` holds the commit guard's geometry and merge part
  (`AP_E_CPU2_GEOM` / `AP_E_CPU2_MV`); `ap_h2_guard` calls it and the host build exports it (`apc_cpu2_host`).
  `apply/test_apply.py CpuX2GuardTests` builds every hbin-2 recipe of the six DC presets × res_list, plus half width ×
  H, H/2, H/3 (where 1x3 readouts exist), and requires apc_build rc 0, rok and apc_cpu2_check 0.
- **Boot apply.** `sq_push` sets `boot.done` whenever a push commits (AP_OK / AP_IDLE), whatever the path (sup_entry,
  the boot callback, leave(), a layout reload), so the poller stops posting SLM_Boot (live 11-05: runs 0, up to 20
  posts). A refused push (e.g. AP_E_NOTREADY) keeps the poller.

### Tests (2026-11-05, offline)

- `qs/test_slqs.py`: Ran 77 tests, OK. New seq 21 (OG 3K: 2x2 / 1x2 + RWZM / 1x2 + CPU ×2 → `→3024×2014 · 2x2`) and
  seq 22 (HD 2K ISP 3x3 at the forced 1025 → `3x3`, ISP 3x1 → `RWZM`), both step-for-step against the page.
  `--mutate` on the new / touched patterns: 23/23 caught (hint ×6, RS two decimals, RECIPE not yellow, FORMAT, CPU x2).
- `qs/test_bootapply.py`: Ran 15 tests, OK; `--mutate` 22/22 caught (the callback's ap_idle is not observable here).
- `qs/test_resmagnet.py`: Ran 5 tests, OK (hint now the RES tile's own); `--mutate` 7/7 caught.
- `apply/test_apply.py`: Ran 95 tests, OK, incl. `CpuX2GuardTests` (it failed before the core fix: 12 of 36 CPU ×2
  recipes refused with MV, the `v3-cpu2` ones). `--mutate --only=2 --only=3` (guard rec_w % 32, mv 2 refused): caught.
  A quality.py mutant re-allowing mv 3 is caught too (run by hand).
- `core/test_core.py`: PASS, 0 mismatches; cpu2 mutants 6/6 caught, new `cpu2: sensor mv 3 allowed` (114). Dropping
  `cpu2_geom_ok` is equivalent today (the ISP plan already refuses rec_w % 16; rec_h is even). core_data.h and
  preview/fps_data.js regenerate unchanged (the preset cells never had a `v3-cpu2`).
- `qs/test_qrscan.py` 23 OK, `qs/test_settings_migration.py` 8 OK (fixture refreshed: 8fddef8c…),
  `node --test preview/test_client.js` 14 pass, `preview/test_server.py` 8 OK, `preview/test_web.py` 6 OK,
  `tools/cpu_h2/test_h2_packed.py` OK.

