# SensorLab-IMX410 v0.7.35test: boot apply + RES one-step window (2026-11-05, offline candidate)

Two changes on top of v0.7.34test. QSContainer stays **v0.3.7**.

## 1. The saved selection applies after boot without MENU / QS

**Before:**
- `sup_entry` set `ap_boot_owed`, and the record was pushed only at a `leave()` (layout load).
- At boot the first push hit `AP_E_NOTREADY` (no mode descriptor before the first LV). The commit stayed owed, and nothing retried until the user opened MENU or QS.

**Trigger chosen** (no new hook point, and no commit off the UI thread):

| Step | Where | What |
|---|---|---|
| a | apply hook `H_PICK` (the picker, LV-start path) | **Only counts** a standby LV start (`"MOV…"` on the standby table; the magnifier `MAG…` does not count). The playback hooks (`H_PBTAG`, `H_PBPREP1/2`) mark "playback since". |
| b | `ap_boot_ready()` (new, `ap.c`) | 1 when all of these hold — the same tests `ap_commit` makes before it touches the LV: <ul><li>a standby LV start has been seen;</li><li>no playback since, and no playback canvas;</li><li>not recording (`ap_busy`);</li><li>no commit running;</li><li>the format is CinemaDNG;</li><li>the mode descriptor and the register record exist.</li></ul> |
| c | **poller task** `LSBOOT` (priority 28, stack 2 KiB; created in `sup_entry` **only with a valid record**) | Every 100 ms: once `ap_boot_ready` has held for 5 polls (~0.5 s), it **posts** the private app variable `SLM_Boot` with `FUN_c0593f30`. That puts a message in the GUI queue, the way the firmware's own notifiers post from their tasks. At most 20 posts, 1.5 s apart. **It never commits.** |
| d | the variable's change callback (`FUN_c0560fb0`, registered at the first `leave()` on the UI thread) | **UI thread**, outside the picker / LV start: checks `ap_boot_ready` and not recording again, then `sq_push` + `ap_idle` (HUD tiles), as `leave()` does. Done on `AP_OK` / `AP_IDLE`. |

**Why it is safe:**
- The commit (LV stop / start) runs only on the UI thread, from a GUI message processed after the LV start that the picker saw.
- Readiness is required for 0.5 s first, and is checked again in the callback.
- Never while recording: `ap_boot_ready`, `busy()`, and `ap_commit`'s own guard.
- **Playback at boot:** no standby pick, or a playback hook after it → not ready, so it stays stock until the LV is back.
- **Non-CINE (STILL) mode:** no `MOV` standby pick → it stays stock until CINE.
- **No record:** no task and nothing owed. Behaviour is as before.
- **Idempotent:** the later first `leave()` pushes the same selection → `AP_IDLE`.

**Unchanged:** the Playback page frame (`slm_runtime.h`, needs the UI reader) is still set at the first menu, and `leave()` remains the fallback.

**Task entry:** `boot.tramp` in the sup state (`ldr pc, [pc, #-4]` + the Thumb body). Same pattern as the shell / lossless / screen-flip tasks: an ARM entry, made with a D-cache clean (`FUN_c000e91c`).

**Unproven [I]:**
- That the boot LV's first layout load (`leave()`) happens on the camera, so the variable gets registered at boot. If the first layout load is the first MENU / QS, the behaviour is today's (nothing worse).
- That the task's GUI post from a non-UI task is fine. The notifiers do this, but our own use is untested live.
- `sq_test 46` shows: `task`, `var_ok`, `posts`, `runs`, `done`, `why`, `last_rc`.

## 2. RES "magnet" (Bei 11-04)

**Where the overlay lives** [C]:
- The dial moves the RES itself (16 px / 2 rows; the adjust value is never touched by the snap).
- The **shown** WIDTH / HEIGHT is `visible()`, which is the current recipe's own visible size.
- The core accepts recipes up to **2 % short** (`core_qualities_tol`, TOL 1/50). A bin-native recipe (e.g. 2×2) therefore stayed current for ~2 % of the size past it: 3–4 width clicks at 3000 px, at any turning speed. The hint, meanwhile, was computed from the raw RES (`res_now` / `res()`), so it showed only at the exact size.

**Fix (camera `slqs.c` and page `preview/dcres.html`, kept in parity):**
- **Window:** a recipe whose visible size is short of the RES by **more than one step** past the 16×10 margins (> 16 px or > 2 rows) is not that RES's recipe. This is filtered in `cell_now` / `allQuals` (`shortOk`), so the FPS list, RECIPE and `visible()` all agree. A bin-native size now holds for **at most one click** above it and none below.
- **Hint:** the WIDTH / HEIGHT small line and the RES tile's `· 2x2` come from the **effective RES** (recipe visible + 16×10: `eff_res` / `effRes`), so the hint shows whenever the overlay is active.

**Side effect (please confirm):**
- On the 45 preset cells, 59 of 837 recipes are now dropped as more than one step short, e.g. `OG:2016x1346` goes from 36 to 18 recipes and `OG:1008x672` from 58 to 48. No cell is left without a recipe.
- A QR code made for a dropped recipe will now be refused by the camera's restore check.
- The core's 2 % tolerance itself is unchanged.

## Builds

| File | Bytes | sha256 |
|---|---|---|
| `card-settings-build/fpSup/SensorLab-IMX410_v0.7.35test.BIN` (**card**; settings from `../20261104-qr-scan-build3/live/readback.BIN`) | 205152 | `41a58179606cd84b5de78ce8f5e980db631aa84cb1095672dfa03af519c10cf4` |
| `default-build/fpSup/SensorLab-IMX410_v0.7.35test.BIN` (blank record; frozen fixture) | 205152 | `a3fd557c9dabb73a1267a58aa027e07ed7529a2eb05c002af689d75f6d0eb830` |

## Tests

| Suite | Result |
|---|---|
| `qs/test_bootapply.py` (5) | OK; **mutants 9/9** (`boot-mutants.log`): no task, task without a record, no stability wait, poll ignores readiness, callback does not push, never done, no spacing, no variable, leave does not register |
| `apply/test_apply.py` (81, including the new `BootReadyTests`) | OK; mutants: all new `ap_boot_ready` / counting mutants caught. The 4 survivors (48, 54, 56, 61) are old patterns no longer in `ap.c`, from before this change. |
| `qs/test_resmagnet.py` (3: page properties over 168 sequences plus camera parity on HD) | OK; **mutants 5/5** (`res-mutants.log`) |
| `qs/test_qrscan.py` (22; site inputs now skip recipes outside the window) | OK |
| `qs/test_slqs.py` (68: camera = page, string for string) | OK |
| `qs/test_settings_migration.py` (8, new fixture) | OK |
| `site/test_site.py` (9; local copy regenerated) | OK |
| `tools/test.py fast` (`menu_lists.py` gets the same window: its rows = the page's) | PASS |

Recording is guarded twice: `busy()` in the poll and callback, and `ap_busy()` in `ap_boot_ready`. Removing either one alone is equivalent at the SensorLab level. `ap_boot_ready`'s own guard is covered by the apply tests and their mutants.

## Live test

1. **Cold boot** (power switch off/on, USB unplugged; then plug in for the shell). **Before touching any key:**
   - `sq_test 17`: `active = 1`, and the mode is the record's.
   - `sq_test 46`: `done 1`, `posts ≥ 1`, `last_rc 0`.
   - Check the LV framing / HUD.
2. **Warm restart:** `poff N` (fastreboot), then the same checks before any key.
3. **Boot into playback** (PLAY held at boot, or the last state): stock while in playback. Leave to LV → applied within ~1 s without MENU / QS.
4. **STILL mode at boot:** stays stock. Switch to CINE → applied.
5. **RES magnet:** RES sub-QS, from 2x2 / 3x3 sizes. WIDTH +1 shows the bin size at most once; the next click moves on. −1 moves at once. The `· 2x2` hint shows whenever the bin size is shown.
6. **Regression:** MENU / QS after boot do nothing extra (`AP_IDLE`). Record a clip.
