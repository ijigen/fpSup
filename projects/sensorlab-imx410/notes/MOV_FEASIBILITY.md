# MOV feasibility: Sensor Lab readout recipe, stock MOV output (2026-11-08, offline research only)

The question (Bei 11-08, 「…MOV」): can a virtual sensor mode plus a virtual profile feed MOV (H.264) at a non-stock
readout, while the encoder still sees a stock size (UHD / FHD)? Nothing was implemented.
Evidence: `tools/mov_feasibility.py` (unicorn + `out/MAIN_c0000000.bin`, apply unit armed) →
`validation/20261108-bitdepth-mov/mov_feasibility.json`. **[驗]** = shown by that run, by decomp or by image data;
**[推]** = inferred.

## Conclusion

**Possible in principle, but not low-risk. Recommendation: do not implement now.** If Bei wants it, start with the
research steps in §4 rather than product code.

- The readout half is the same as today [驗]. The MOV table's keys use **the same sensor modes as CinemaDNG** (24 of
  the 26 shared keys; only FHD120CROP / FHD100CROP differ). So the virtual mode that Sensor Lab installs could also
  serve MOV.
- The output half is new work [驗 / 推]. A MOV profile differs from its CDNG twin in about 26 of 65 canvas words. The
  YUV encoder input is the "preview" pipe at full size, and isp-lab's formula has not been validated for that use.
- The product model narrows a lot under MOV. The output is fixed 16:9 at UHD / FHD, the FPS only stock carriers, and
  there is no RES, no DefaultCrop / DefaultScale, no 14-bit and no anamorphic. So MOV would be "a readout choice
  (bin / crop / AD) for UHD / FHD at stock rates", not Sensor Lab's DC × RES × FPS.

## 1. Route [驗]

- `XC_LiveViewConfiguratorW71c1::v3` sends CINE with `cfg[0x24]` = CinemaDNG to `FUN_c043b828`, which uses our
  picker `C043CCF8` over TAB1–3. Otherwise it goes to `FUN_c043b988`.
- `FUN_c043b988` (not HDMI, `cfg[0x45]` = 0) scans the general table `0xC0BE4D50` (48 entries, `{3, pid, mode, key}`)
  with its own searcher `FUN_c043cdb8` (span 0x300). With `cfg[0x45]` set it scans `0xC0BE5050` (16 FHD entries, pids
  301..312 / 413..416) with `FUN_c043ce78`. HdmiRec uses `FUN_c043cdb8` too, on `0xC0BE5150`.
- With a Sensor Lab slot live, the MOV searcher returns the stock entry for UHD30 / UHD30CROP / FHD30 (pid 101 / 116 /
  109). The apply unit's picker hook ran 0 times; the CDNG table on the same key returns ours. **MOV records stock
  today, by construction** (`ap_commit` also refuses non-CinemaDNG: AP_E_FORMAT).
- MOV-only keys: 22 `…EIS` variants (same mode; the profile carries the EIS margins).
- Standby in MOV already goes through `C043CCF8` with the standby table `MOV*` (profile 5, mode 8). Sensor Lab has a
  path for it (`s->sby` / `sentry`).

## 2. What a virtual MOV profile would have to own [驗 gather, 推 meaning]

Native gather of 13 MOV / CDNG pairs (same key, same mode):

| Word | MOV (e.g. UHD30 p101) | CDNG (p171) | Meaning |
|---|---|---|---|
| `+0x00/04`, `+0xD8..E4` | 0 | record raster | no RAW record in MOV |
| `+0x0C/10`, `+0x20/28` | 3888×2184 / 3840×2160 (FHD: 3032×1708 / 3000×1687) | LV preview 2016×1135 / 2000×1125 | the YUV pipe at encoder size [推] |
| `+0x58/60/64`, `+0xC4/D0/D4` | MOV's own pre-scale / zoom | the RAW record's RWZM | the YUV scaling chain |
| `+0x80/84` | 9 / 10 | 7 / 7 | YUV plane formats |
| `+0x44` | 2 (UHD) / 1 (FHD) | 0 | output selector (FHD: 3000×1687 → 1920×1080 downstream?) [推] |
| `+0xF0` | 4 | 2 | record class [推] |
| `+0x30/A4/B0` | differ at 120 / 100 | | high-rate path |

- The isp-lab formula computes the RAW record and a ≤ 2000-wide preview. For MOV the YUV pipe would have to run
  full-width (3840) from our source. The freeze rules we know (R6 raster ≤ source, R12 source ≤ 1710 rows, visible ≤
  2000) were found on the CDNG preview pipe. At the MOV pipe's sizes they are unknown territory.
- **Profile id class** [驗 in `open-gate/notes/OG_MULTIFORMAT_CORE_DESIGN.md` §R1]: `FUN_c043a1c8` classifies by pid
  range (101..129 / 191..198 / 301..312 / 401..416 = MOV; 131..190 / 417..434 = raw movie). The MOV ranges have no
  free id. A virtual MOV pid needs a class hook, or a stock MOV pid has to be borrowed. Our `H_GS` answers "raw movie"
  for our record pid, so it would have to answer 0 for a MOV slot.

## 3. What would break or be limited [推 unless marked]

1. **Encoder size and rate**: H.264 takes the stock profile's size and the stock carrier rate. The recipe's VMAX must
   hit the carrier exactly (no 43.665 fps). Rates above the stock MOV maxima (UHD 29.97, FHD 119.88) are out.
2. **Aspect**: the output is 16:9. A non-16:9 DC is either refused or stretched; RES is fixed to UHD / FHD.
3. **New hook site**: the general searcher `FUN_c043cdb8` (or its call in `FUN_c043b988`). Nothing in the repo claims
   it today [驗 grep: only research tools and `og6k_hdmi/build.py` mention it]. It is shared with HdmiRec, so it must
   check that the table is `0xC0BE4D50`. Another option is the `cfg[0x45]` table.
4. **EIS**: refuse EIS (its profile carries margins the formula does not model), or force EIS off.
5. **Gain / colour / NR**: tuned per stock MOV profile. A different readout (binning / AD) changes noise and levels.
   No in-camera "look" for our readouts has been checked.
6. **LV and magnifier**: same issues as CDNG (aspect hooks, `MAG*` stays stock), plus the record pipe now being YUV.
7. **Freeze risk**: the CDNG work found three freeze classes (R12, the busy() route switch, a raster past the source).
   MOV adds a pipe we have never driven. AGENT_BRIEF: known freeze risks must be fixed before going live.

## 4. If Bei wants to continue: research first, in order

1. Offline: extend `tools/mov_feasibility.py` to run the full native configurator for a key, with a test-only entry
   for a virtual MOV pid. Record what each consumer of `+0x44/+0xF0/+0x80/+0x84` and the class reads (the way
   `research/interfaces/audit_hdmi_rescustom_interface.py` does for HDMI RAW).
2. Offline: derive the YUV-pipe words for one easy case: a stock-size readout that already exists. Example: UHD30 on
   mode 7 with a different AD, or FHD from a 3×3 bin. Then the profile only differs where the readout does.
3. Live, standby only, with the shell: one MOV standby / LV of that case. No recording until standby is proven (the
   isp-lab rule).
4. Only then a recording, at a stock carrier, and a product decision about the UI: MOV un-greyed in FORMAT, RES
   locked to UHD / FHD, FPS limited to carriers.

Estimate: steps 1–2 take about a day offline, and step 3 needs Bei's camera time. A product build after that is
another larger round (UI rules, tests, live).
