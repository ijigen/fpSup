# SensorLab-IMX410 — agent brief (read this first, then only what you need)

Keep this file short and current. It replaces reading every note. If you change something it states, update it.
Owner of decisions: Bei (the user). Replies to Bei are in Traditional Chinese.

## What it is
A loader-v4 sup for the SIGMA fp (fw 5.02, IMX410) that replaces the stock Quick Set and menu with:
- crop (DC), resolution (RES), frame rate (FPS) and recipe (RECIPE);
- MB/s and QR tiles;
- an **apply** step that installs the choice as a virtual sensor mode + ISP row, so recordings really use it.
A separate sup, **QS container** (`../qs-container`), owns the native QS/editor plumbing; SensorLab registers functions with it (API in `../qs-container/qsc.h`).

## The spec
- `preview/dcres.html` is the behavioural spec (browser prototype). The C client must match it step by step.
- `QS_DC_RES_SPEC.md` records every Bei decision (latest sections win).
- Don't invent UI text: use stock strings only; no Chinese in camera UI.

## Code map
| Path | What |
|---|---|
| `qs/slqs.c` | The client: QS functions, footers, records, menu hooks, includes apply/core |
| `apply/ap.c`, `ap_calc.c`, `ap.h` | Apply: virtual modes 230/231, hooks (v0.7.2:37 claims; v0.7.3 candidate:39), carrier rate, standby gate, playback guard |
| `menu/slm_runtime.h`, `slm_state.h` | Native menu rows (RES/FPS/BIT/DC lists, CUSTOM → sub-QS). **Never commit or rebuild models inside a menu change event** (froze live) |
| `core/` | Formula: readout plan + smc tables (R10) + ISP row; also host tests |
| `../qs-container/qsct.c` | Container: CSV rows, editor, QS page, replace mode, sub-QS, API 6 |
| `preview/dcres.html` + `site_page.js`, `site/build_site.py` | The one web page: simulator + camera QR landing (`#code`), EN/简/繁; generated into `fpSup/sensor_lab_imx410/` (see `site/README.md`) |
| `notes/` | Designs and research. Read only the one your task needs. Pending (11-07, not started): `RESCUSTOM_COEXIST_DESIGN.md`, SensorLab as a RES-Custom producer; 3 questions open for Bei |

## Build and test
- Build: `cd qs && python3 -B build_slqs.py --out out` → `out/fpSup/SensorLab-IMX410_v<ver>.BIN`, container `cd ../qs-container && python3 -B build_qsct.py` → `QS-Share_v<ver>.BIN`.
- Names/versions (11-07, Bei): display `Sensor Lab-IMX410` / container `QS-Share` (sup_id still QSCT), both restarted at 0.0.1test; they live in `fpSup/loader-v4/names_v4.py` (SL41, QSCT), the builders read them. On the merge page (`fpSup/tools/merge-v4`) QS-Share is auto-included, Sensor Lab ⟂ RES-Custom. Upgrade: delete old `SensorLab-IMX410_v0.7.*.BIN` (newer by version) and `QSContainer_v*.BIN` (same sup_id).
- Tests, from `projects/sensorlab-imx410`:
  - `python3 -B tools/test.py fast`: about 7 s. Run it after every edit.
  - `prelive`: unit tests plus only the mutants whose target file changed. This is enough before a live test.
  - `full`: about 16 min. Run it only before a release.
- No `/` or `%` in camera C: use `udiv64`. No libgcc. ARM stack 8-aligned.

## Live (camera) rules
- **Before**: broadcast to all peer sessions (ListAgents → SendMessage) that the camera is taken; **after**: broadcast "released".
- **When**: Bei allows going live directly once offline tests are green. Ask first only if Bei or Codex is using the camera.
- **Deploy**:
  - read back the card's current BINs, rebuild with `--settings-from` to keep the user's record, write with full read-back (`deploy_v3`);
  - reboot with `fpSup/fp_usb_shell/ui_drive.py reboot`, as a separate step. Never `poff`/fastreboot unless the procedure says so.
- **Tools**:
  - `tools/live/ui_shot.sh N`: screenshots by number (`dir` truncates);
  - `tools/live/pingloop.py`: a 100 ms ping around keys (one timeout alone is not a freeze);
  - `tools/live/dc_probe.py`: sq_test 17/18 + sensor V window.
  - Read the sq_test offset from `qs/out/build-<ver>.json`; never hard-code it.
- **During recording or playback**: never send USB. Wait 10 s after stopping a recording.
- **On a freeze**: stop at once, log the last action, report. Bei pulls the battery. No recovery loops.
- **Known freeze risks must be fixed or blocked before going live**; never "verify on camera".
- **DNG checks**: look at a colour preview, run the mod-4 bit check, and check BitsPerSample, BlackLevel and WhiteLevel.

## Live runs: use run_checklist.py
- `python3 -B tools/live/run_checklist.py v1 --version <ver> --out validation/<date>-<run> --shot <next SS number> [--from N] [--only 3,4]`
  runs the checklist end to end with no reasoning between steps; `--list` prints it without touching the camera.
- Steps are data (`tools/live/checklists/v1.py`): keys, `nav` by screen, ping loop around risky keys, sq_test (offset from
  `build-<ver>.json`), mem, position checks `at` (screen + MENU_Level* + QS focus + the container's sub_open), screenshots
  (visual checks only), `rec` (rec_take.sh), DNG fetch + bit check + colour PNG, `pause` (a hand step, Enter to go on).
- Built in: no S1/S2/MOV/PLAY/CAPTURE keys, no playback, no USB < 12 s after a stop, no pong 5 s = FREEZE (stops, says the
  last action, no recovery).
- Read only `<out>/summary.md` and the screenshots it lists; details are in `<out>/results.jsonl`. A wrong key path: fix the
  checklist data and rerun with `--from N`. Offline test: `python3 -B -m unittest test_run_checklist` (in tools/live).

## Navigate by UI log, not screenshots (Bei)
- Use `ui_drive.py where` (~4 s, mem reads only): the current screen (app+0x84C) and each page's focus variable (MENU_Level1/2, SL_*, QS focus 0xC37B72A8+0xBC, the container's sub_open etc.). Use it after every key to know where you are.
- Take a screenshot **only** when the visual result itself is being checked (layout, text, icons, the LV crop), via `tools/live/ui_shot.sh N`.
- Batch keys when the path is known (`ui_drive.py MENU RIGHT DOWN:2 …`), then confirm with one `where`.

## Facts that matter
- **14-bit product policy**: current supported recipes record true 14-bit only at **1:1** (no RWZM, no CRCT bin). The measured reduction paths lose the low two bits, so those recipes use a **12-bit container**; the ADC tile still shows 14bit. Live-verified 10-30. This is not a claim about every unknown hardware configuration; research evidence stays in `notes/TRUE14_2X_RESEARCH.md`.
- **Standby gate** (v0.7.2): source ≤ 1710 rows (R12), raster ≤ source, visible width ≤ 2000. A refused selection is rejected at commit (all stock). v0.7.1 froze when recording a gated recipe because the picker switched on busy().
- **Default recipe**, in order: vertical merge closest to the reduction → higher recorded bits → horizontal closest → larger RS.
- **Playback v1**: non-stock clips are refused before decode. v2 (proper playback) is deferred.
- **Freeze lessons**: OSD is triple-buffered (draw only in the presenting group 2/3). A menu change event must not rebuild lists.

## Current state (update when it changes)
- **0.0.6test candidate (11-10, offline; not deployed)**: exact merges (Bei: "2x2 3x3 6x6 ... the most important").
  quality.py / core.c `q_isp` (product list only): (E) a merge within 16 px / 4 rows / 1.5 % FOV of the RES records 1:1
  (RWZM off); (V) RWZM-on recipes crop 1..12 spare rows at the aspect-keeping ratio (else 1:1) when the margin holds;
  ÷6 presets = ev(H/6) − 10 so 6x6 / 3x6 record the RES; RES list + 1x2 / 1x3 (menu RES page 12 rows); hint "HxV" /
  "HxV+RW" (+ " /2.00" per axis on RES WIDTH / HEIGHT when it fits). Evidence: `validation/20261110-binning-exact/`.
- **0.0.5test candidate (11-10, offline; product not deployed)**: first-frame purple fix = vertical margin. Every
  product recipe (`core_qualities_tol` / `quality.qualities(vmargin_floor=)`, applied after the pick) keeps >= 4.875
  spare RWZM input rows below the record on its own readout (Bei: no extra rows, RS / fps unchanged): both RWZM ratios
  smaller by one factor, else (an axis 1:1) a shorter record in tol, else not offered (62 of 837 presets). Old QR codes
  restore by their 17 input fields (`qr_diff` / `qr_map_rate`). Evidence: `validation/20261110-vertical-margin/`.
- **0.0.4test candidate (11-08, offline only, on top of 0.0.3test)**: the QS FORMAT dial picks 8 / 10 / RAW bit through
  the menu BIT row's stock setter (C04AAE08) + `MV_DNGQuality` post; MOV grey (spec 11-08 FORMAT section,
  `notes/BITDEPTH_8_10.md` 0.0.4test). QS-Share unchanged (0.0.2test). Evidence: `validation/20261108-format-dial/`.
- **0.0.3test candidate (11-08, offline only, on top of 0.0.2test)**: CinemaDNG 8 / 10-bit (`notes/BITDEPTH_8_10.md`).
  The stock BIT row is the source of truth: 8 / 10 are selectable again. The picker answers TAB1 / TAB2 too, and the
  canvas takes 10/10 or 10/9. FORMAT / MB/s / defaultPick use the recorded depth. MOV stays greyed; its research is in
  `notes/MOV_FEASIBILITY.md` (not implemented). Frozen 0.0.2test copies: `validation/20261108-candidate-0.0.2test/`.
- **0.0.2test candidate (11-07, offline only, not deployed)**: main-QS FPS AEL = in-place fine again; the FPS sub-QS only from the menu's CUSTOM (QS_DC_RES_SPEC last section). Needs **QS-Share 0.0.2test (API 9: fine + sub on one function)**; with an older container SensorLab keeps the 0.0.1 behaviour. Separate TEST build `--rec-delay-test` (REC-start delay at 0xC0379180, `validation/20261107-rec-delay/README.md`); the product build is byte-identical without the flag.
- Current card freshly verified after this run: **SensorLab_v0.7.2test (61a2c577…) + QSContainer_v0.3.2 (4ac035ef…)**, original saved settings. CINE standby, recording0, apply active0, init0; `LOAD-restored.LOG` has one SensorLab with37 claims. Original SensorLab/QSC/loader/AutoRun full files and all63 selection words match the pretest backup. Editor CINE slots remain `21 12 23 25 57 50 59 60`.
- Latest source/candidate: **SensorLab v0.7.3test (default766dd87c…; fresh preserved-record live811b4473…)**, **NOT ACCEPTED; rolled back**. Bei authorized deployment/standby verification; initialization and five crop cases succeeded without freeze, but captured images have vertical wrap / origin anomalies. Actual LCD output has not been independently confirmed. See `validation/20261030-lv-aspect-fix/live/LOG.md`; do not redeploy solely on the passing fitter tests. Candidate sq_test_off0x7B85, 38 hooks+clock=39 claims, AP ABI2/QSC API6 unchanged.
- Last accepted live baseline: **SensorLab v0.7.2test (defaultaf2a7271…) + QSContainer v0.3.2**, prelive PASS, live3 PASS (items a–c,14,16 by shell reboot,17;15 needs Bei). Its sq_test_off is0x7AFB. Default hashes differ from the current saved-record files above.
- v0.7.2 changes:
  - the gated-recipe freeze fix: the picker ignores busy(); the 1334 visible cap is removed; R12 1710 is kept;
  - FPS row `1000.0`;
  - AEL after boot;
  - the RATIO layout.
- Offline evidence: `validation/20261030-lv-aspect-fix/verification.json`. Fast 72 + core PASS; prelive's non-settings tests/core and all285 mutation jobs PASS (lv-fit group covers5 variants). The original prelive had6 errors from a missing v0.7.3 frozen fixture; added the new default fixture without overwriting older ones, then all8 settings-migration tests PASS. Late-added outer tests4 PASS, checklist host tests9 PASS. One existing PageStrip skip. Original failed prelive report is retained, not relabelled PASS. Mac Unicorn requires approved host execution (sandbox initialization SIGILL); one runner per checkout (shared host dylibs).
- Known-bug list: `qs/README.md` →「已知上機問題總表」 (25 rows). #23 remains open. v0.7.3 captured effective dimensions track custom aspect, but h3800/h3500 repeat at643/592 rows and width cases start atx0. Determine capture source size/stride versus actual LCD composition beyond the native fitter; current tests do not execute final scanout/capture. Transient false-colour screenshots and inconsistent QS focus remain separate unconfirmed issues.
- Offline follow-up after Bei replied「現在看不到相機」: `validation/20261030-lv-aspect-fix/offline-capture/README.md`. True CAPTURE key/event chain8 tests PASS; fixed SS allocation/JPEG1024×682 versus dynamic native writeback W/H/stride reproduced in11 declared-size cases; direct fit→packet3 tests PASS (6 geometries×2 packet-layer IDs). All independently rerun. No product edit/USB. Pixel DMA, actual live getter/branch and physical LCD remain unverified; single global offset/compact-stride models do not explain all13images. Next trace actual registered-output geometry and C0383910's consumer/branch selection, rather than patching SS dimensions speculatively.
- Latest live evidence: `validation/20261030-lv-aspect-fix/live/` (`LOG.md`, `screenshot-review.json`, `final-verification.json`). Prior accepted run: `validation/2026-10-30-v1-live3/`.

## How to work
- One change at a time, then build, then `fast`, then live if it needs the camera.
- Keep reports short: what changed, the evidence, what's left.
- Don't expand scope. If you find something else, list it; don't fix it unasked.
- Other tools (Codex) may edit files: check mtimes before writing.
