# SensorLab-IMX410 v0.7.36test + QSContainer v0.3.8: boot apply without leave(), RES display, dial guide (2026-11-05, offline candidate)

Fixes on v0.7.35test (`../20261104-boot-apply/`): boot apply that needs no `leave()`, the RES display per Bei 11-05 (the one-step filter reverted: no recipes dropped), and the dial guide (QSContainer **v0.3.8**, API 8).

## RES display (Bei 11-05)

- **The 2 % tolerance is kept.** All 837 recipes stay. The v0.7.35 filter is reverted in `slqs.c`, `dcres.html` and `menu_lists.py`.
- **WIDTH / HEIGHT values:** they show the **dialled RES** (its nominal visible size, −16×10). The value moves on every click.
- **WIDTH / HEIGHT small line:** when a tolerance recipe applies, it shows what is recorded plus the bin hint, e.g. `→3008×2004 · 2x2` (U+2192, already drawn live). Otherwise it shows the hint of the dialled RES.
- **RES tile:** its `· div` follows the effective recipe.
- Camera and page stay in text parity (`test_slqs`, `test_resmagnet`).

## Dial guide (QSContainer v0.3.8, API 8)

- **The flag:** `QSC_F_DIAL_HINT` (0x1000), opt-in per function. SensorLab sets it on every function with `adjust()`: DC, RES, FPS, RECIPE. FORMAT, MB/s and QR do not get it.
- **Where it shows:** in the band above the option strip, at the left: `[front-dial glyph] ±1  [rear-dial glyph] ±10`.
  - The glyphs are the stock `font_G_dial_front` / `font_G_dial_rear` / `font_G_plusminus`, white on a 60 % black box.
  - It shows only while the focused tile or sub-item has an adjust and is not locked. Fine mode and the sub-QS are included.
  - Stock tiles keep their stock guide.
- **Older containers** ignore the bit.
- Details and the unproven placement items are in `qs-container/BUILD.md`.

## The finding

v0.7.35test registered `SLM_Boot` and its callback at the first `leave()`. The first `leave()` comes with the first MENU / QS, which is exactly the case boot apply is for. As built, it was a no-op there.

## The fix: a UI-thread one-shot at boot, with no key needed

**Why not register from the task.** `FUN_c05db308` (variable registration) changes the GUI registry directly. It allocates entries and grows the table, takes no lock, and the UI thread reads that registry. So registering from the poller task is **not** safe [C].

**The hook.** `StandbyEventHandler_w71c1::v72` [C]:
- It is the standby (live view) screen's handler enter.
- It registers that screen's rec-seq observer, the same as `FUN_c0371598`.
- It runs on the GUI thread when the LV screen comes up at boot, and on every return to LV.
- Its vtable word is unique: `0xC0CD7A88 = 0xC0481D80`.

**What it does:**
- `sup_entry` (only with a valid record) claims that word (`SL_EXCL`, only over the stock value) and points it at `sl_stby_v72`.
- `sl_stby_v72` runs the stock enter first, then registers the variable and its callback **once**, on the UI thread.
- If the word is someone else's, it is left alone; the first `leave()` still registers, as before.

Everything else is as in v0.7.35test: the poller posts after readiness has held for 0.5 s, and the UI-thread callback commits.

## The poller task after it is done

There is no `tk_ext_tsk` in this firmware, so the task cannot end.

- **While owed:** it wakes every 100 ms and stops after 20 posts.
- **Once done, or once it gives up:** it **parks** in `tk_dly_tsk(0x00FFFFFF ms)`, waking about once every 4.7 hours. Each wake does nothing and goes back to sleep.
  - The value is kept well inside any delay range. A non-zero return from `FUN_c03705d8` hits the firmware's assert.
  - A true forever block (`tk_slp_tsk`) is not used: the notes' slp/wup addresses are known to be wrong.
- **Cost:**
  - **Memory:** one TCB plus a **2 KiB** stack.
  - **Priority 28:** below the UI, the shell (25) and the gyro thread (20), and above none of the recording tasks that matter (the writer is 28 too; see the task priority map). While owed, each 100 ms wake is a few dozen instructions. After that it is effectively nothing.
- **No record:** no task is created at all.

## Builds (deploy both card builds)

| File | Bytes | sha256 |
|---|---|---|
| `card-settings-build/fpSup/SensorLab-IMX410_v0.7.36test.BIN` (**card**; settings from `../20261104-qr-scan-build3/live/readback.BIN`) | 205928 | `167302e82492a9c93bf0d0511356227066f4d8ba0a31fc01e8f74c325b65ba04` |
| `qs-container/card-settings-build/fpSup/QSContainer_v0.3.8.BIN` (**card**; settings from `../20261104-qr-scan-build/live/rb-QSContainer_v0.3.7.BIN`) | 202888 | `5b2044392736ade9e2b58482c124589009f73a237883dfbbc657f628843b28ed` |
| `default-build/fpSup/SensorLab-IMX410_v0.7.36test.BIN` (blank record; frozen fixture) | 205928 | `0170ba75700496abdc9e0fcd60d82b7314748ff19f2dc98b569203f23d86fad8` |
| `qs-container/default-build/fpSup/QSContainer_v0.3.8.BIN` (blank; frozen fixture; equals a fresh build of the source) | 202888 | `cf297822fbd206a805e23cbcf79a64a3edfff0a12933ff7751ba7d519c690aa0` |

Delete the card's old `SensorLab-IMX410_v0.7.3x` and `QSContainer_v0.3.7` BINs.

## Tests

| Suite | Result |
|---|---|
| `qs/test_bootapply.py` (7, including a real boot with no layout load ever) | OK; **mutants 13/13** |
| `qs/test_resmagnet.py` (5) | OK; **mutants 5/5** |
| `qs/test_qrscan.py` (23, including the dial-hint flags) | OK; **mutants 29/29** |
| `qs/test_slqs.py` (68, camera = page) | OK |
| `qs/test_settings_migration.py` (8, new fixtures: SensorLab v0.7.36test, QSContainer v0.3.8) | OK |
| `apply/test_apply.py` (81) | OK (`ap.c` unchanged since the v0.7.35 mutant run: all new caught, 4 old stale patterns) |
| QSContainer `test_qsct` 33 / `test_qs_page` 61 (+1 skip) / `test_api5` 15 / `test_api7` 11 / `test_api8` 12 | all OK; **mutants 43/43, 84/84, 20/20, 21/21, 18/18** |
| `site/test_site.py` (9; local copy regenerated) | OK |
| `tools/test.py fast` | PASS |

## Live test (before touching any key, then the rest)

1. **Cold boot** with the power switch, USB unplugged, then plug in for the shell.
   - `sq_test 46`: `stby_ok 1`, `stby_enters ≥ 1`, `var_ok 1`, `posts ≥ 1`, `done 1`.
   - `sq_test 17`: `active 1`.
   - `mem get 0xC0CD7A88` is SensorLab's wrapper.
2. **Warm restart** (`poff N`): the same checks.
3. **Playback at boot, or STILL mode at boot:** stays stock; applied after going back to the CINE LV.
4. **MENU / QS afterwards:** nothing extra happens (`AP_IDLE`).
5. **RES sub-QS:** every WIDTH / HEIGHT click changes the value. Near a bin size the small line shows `→W×H · 2x2`.
6. **Dial guide:** on DC / RES / FPS / RECIPE tiles and their sub-items, `[front] ±1 [rear] ±10` at the lower left. Not on FORMAT / MB/s / QR or on stock tiles. Check the glyph alignment (`qs-container/BUILD.md` live items).
