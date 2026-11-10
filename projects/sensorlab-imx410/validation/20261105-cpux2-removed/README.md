# SensorLab-IMX410 v0.7.39test: CPU ×2 removed (2026-11-05, offline)

Bei dropped the CPU ×2 feature (RECIPE > ISP HBIN "CPU ×2", hbin 2). The live probe measured 103 MB/s against the 457 MB/s needed, and the memcpy ceiling is about 200 MB/s (`../20261105-cpux2-14bit-build`).
At Bei's request the code is kept: `../20261105-cpux2-archive`, `tools/cpu_h2/` and `notes/CPU_X2_DESIGN.md`, whose status line says how to restore it.

## Default build

`default-build/fpSup/SensorLab-IMX410_v0.7.39test.BIN 205936 B sha256 f949e51643c303f52497919a9e7e4540c20b3f1ed4272ee8c81984eb5d5e484b`
Built twice with `python3 -B qs/build_slqs.py --out <dir>`; both builds are byte-identical. It is also the frozen settings-migration fixture.

## Source state

- **Same as v0.7.37test (`../20261105-clean-v0.7.37test`), byte for byte:**
  - `core/*`
  - `apply/{ap.c,ap.h,ap_calc.c,build_apply.py,test_apply.py}`
  - `preview/{fps_data.js,site_page.js,test_client.js,test_web.py}`
  - `isp-lab/host/{quality.py,matrix.py}`

  `core_data.h` re-exports identical. `fps_data.js` regenerates identical (837 recipes).
- **Kept from the v0.7.38test session (non-CPU):**
  - The merge hint comes from the effective recipe (slqs.c `eff_now` / `recipe_hint`, dcres.html `effDisplay` / `recipeHint`). OG 3K 2x2 shows "2x2", not "2x".
  - The RECIPE line has RS to one decimal and no size suffix.
  - `boot.done` is set in `sq_push` on any committing path.
  - preview/server.py slices the encoder before the scan decoder.
  - The test_slqs mutation runner writes the mutant next to slqs.c, because slqs.c includes qrdec.c.
- **New:** `rec_load` maps a saved hbin 2 (option 13 in v0.7.38test) to ISP HBIN 1, the RWZM twin. See test_settings_migration `CpuX2Removed`, with 5 of 5 mutants caught (`--mutate-cpu2`).

## Card build (Bei's saved settings)

`card-settings-build/fpSup/SensorLab-IMX410_v0.7.39test.BIN 205936 B sha256 f2869412b7faef06d5d87fd6e2260026800fb50ef3255f2ce2f3973135c1c754`
Settings record from the card's v0.7.38test readback (`../20261105-cpux2-14bit-build/live/readback-v0.7.38test.BIN`, bc625c71…, record FNV fa50cff9).
Deploy: delete `\fpSup\SensorLab-IMX410_v0.7.38test.BIN` (two SensorLab BINs must not coexist), put this file, read back, poff; check sq_test 46 done=1 / entry_rc=0.
**Live 2026-11-05 (deployed, 0.7.38test deleted):** LOAD.LOG loads SensorLab-IMX410_v0.7.39test.BIN at C5615900; after poff sq_test 46 done=1 entry_rc=0, sq_test 17 active=1 result=0 commits=1.
Bei's saved CPU ×2 recipe came back as its twin: RECIPE 14b 1x2, ISP HBIN 1 "RWZM 1/2.00", RES 3008×2004 · RWZM, FORMAT 12bit, RS 25.9 ms (one decimal, no size suffix). Standby LV full width, not stretched.
Screenshots in live/ (SS3188 QS, SS3190 RECIPE options, SS3191 ISP HBIN strip, SS3193 LV). The ISP HBIN list end (former option 13) was not scrolled to; covered offline.
