# 2026-11-05 SensorLab v0.7.37test: boot apply at sup_entry (RES-Custom's way)

## Live findings (v0.7.36test and the v0.7.37test intermediate builds, no key after boot)

1. **v0.7.36test, cold boot:**
   - `stby_ok=1 stby_enters=0 var_ok=0 polls=0`, `active=0`.
   - After MENU and back, `stby_enters=1`.
   - **The boot LV screen enters before the sups load.**
2. **Build 1** (variable registered at sup_entry):
   - `var_ok=1` and polls run, but `ready_polls=0`, `picks=0`.
   - ap_boot_ready waited for a picker-seen LV start that never comes at boot.
3. **Build 2** (LV counted at load; ready = a CINE LV running now):
   - Another boot: the LV screen entered after the load (`stby_enters=1`, `lv_load=0`), but the picker still never ran (`picks=0`).
4. **Bei: "RES-Custom 就辦得到".**
   - RES-Custom's `ogc_restore` runs at the end of its sup_entry.
   - It reloads a running LV there; no task, no UI thread.
5. **Build 3** (commit at sup_entry):
   - Cold boot: `entry_rc=0 active=1 mode 231 lv_load=1 lv_reloads=1`.
   - Warm `poff`: `entry_rc=0 active=1 lv_load=0`; the LV then started on our mode.
   - But the UI-thread callback never ran (`posts 16`, `runs 0`): **a GUI watch registered from sup_entry does not fire at boot.** ScreenFlip's similar code was never live-proven.

## Final

- **sup_entry:** after ap_init, the hooks and the poller task, if not recording and CinemaMode is not STILL (`ap_cine_now`):
  - `sq_push` commits; a running LV is stopped and started, like RES-Custom's `lv_reload`.
  - AP_OK or AP_IDLE → `done=1`, no posts.
- **Fallback** (no descriptor yet, recording, STILL):
  - The poller is ready when `lv_seen` **or a CINE LV is running now** (`ap_cine_lv_now`), and no playback was seen.
  - It posts SLM_Boot. The UI-thread callback is untested at boot (it did not fire); the first `leave()` remains the last resort.
- **HUD size tiles (`ap_idle`):** at the first `leave()`, as before v0.7.35.
- **Live, final build:**
  - Warm `poff`: `entry_rc=0 done=1 posts=0 active=1 lv_load=1 lv_reloads=1`.
  - Cold boot (11-05, after a LUT-line cold boot, no key): `entry_rc=0 done=1 posts=0 active=1 mode 231 lv_load=1 lv_reloads=1`. **Pass.**

## Tests

| Suite | Result |
|---|---|
| `qs/test_bootapply.py` (13) | OK; **mutants 22/22** |
| `apply/test_apply.py` (81) | OK; ap_boot_ready test extended: LV running counts, STILL does not |
| `qs/test_slqs.py`, `qs/test_qrscan.py`, `qs/test_resmagnet.py`, `qs/test_settings_migration.py` | OK |

## Builds

| File | Bytes | sha256 |
|---|---|---|
| `card-settings-build/fpSup/SensorLab-IMX410_v0.7.37test.BIN` (**card**; settings from `live/readback-v0.7.37test-b3.BIN`) | 206048 | `a6f09349aa8684ccf35c9c07771a9a8e9ccd240bb400af5a3a9d66d43541822d` |
| `default-build/fpSup/SensorLab-IMX410_v0.7.37test.BIN` (blank; frozen fixture) | 206048 | `23c76320f62977d4447303af9a0e643f7950bd5cdb59f6fd4d3aee33df81448a` |

QSContainer stays v0.3.8 (`../20261105-boot-apply2`).
