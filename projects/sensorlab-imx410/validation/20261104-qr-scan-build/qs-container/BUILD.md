# QSContainer v0.3.7 (API 7, "AEL opens a stock page"), offline build, 2026-11-04

This build was made offline. No camera, no USB and no card were used. Source: `projects/qs-container/`
(README section "v0.3.7（2026-11-04，AEL 開原廠頁）"). SensorLab files were not edited.

| File | Bytes | sha256 |
|---|---|---|
| `fpSup/QSContainer_v0.3.7.BIN` | 201416 | `646ef5202ac5e250f96fba593a4ee937f76b40aa1c7a52b56679be280881abbc` |
| `build-0.3.7.json` | 4251 | (build offsets: go_file_off 197568 / len 336, go_text_off 197492, go_page_off 197524, state_off 201472) |

Command: `cd projects/qs-container && python3 -B build_qsct.py --out out`. The build is deterministic: two builds gave
the same sha256. The settings record is the **default blank** one. If the card has a v0.3.6 with the user's slots
record, rebuild with `--settings-from <that BIN>`, as for v0.3.6.

## Contract (qsc.h)

```c
#define QSC_F_GO(t)  ((((uint32_t)(t)) & 0xFu) << 8)
#define QSC_GO_MASK  0x00000F00u
enum { QSC_GO_READQR = 1u };
```

- **Requirements:** a GO target needs an API 4 table (QSF4), a non-0 `fine` and no `sub`. If any of these is
  missing, or the target is unknown, the function is refused at registration.
- **AEL:** the container calls `fine(arg, 1)` as the request, but only if the tile is not greyed, not
  LOCK_REC-locked, and the camera is not recording at all.
  - Non-0: the container closes any fine mode or sub-QS, then asks the stock state machine for `Y5_ReadQR`.
  - 0: nothing happens.
  - `fine(arg, 0)` is never called for a GO function.
- **`open(QSC_OPEN_FINE)`** on a GO function returns 0.
- **`api->version` = 7.** Older containers ignore the bits and run `fine` as a fine mode, so the client must check
  the version. SensorLab's `sq_qr_go` returns 0 when the version is below 7.

## Tests and mutants (all offline, real ARM under unicorn, real firmware image)

| Suite | Tests | --mutate |
|---|---|---|
| test_qsct | 33 OK | 43/43 caught |
| test_qs_page | 61 OK (1 skip: QSCT_MENU_BACK=1 only, as before) | 84/84 caught  |
| test_api5 | 15 OK (version assert 6 -> 7) | 20/20 caught |
| test_api7 (new) | 11 OK | 21/21 caught |

## live-check (unproven; [C] = read in code/data, [I] = inference)

1. Our `appVariableChangeEvent` on `QSC_Go` (45 B, mask 3, type 3) fires on QS_CINE when the value is posted.
   - [I] The same form was proven on the camera on the fpSup pages (MainY5 base) on 2026-10-25, but not on QS
     (GUI 159).
   - The deferred `controlAppState` (the stock AEL's mask 0x23 form) then runs with the go text.
2. The QS is left by the transition `QS_CINE -> Y5_ReadQR`, and the read page starts normally.
   - [C] Stock only enters this page from MainY5.
   - [I] From QS, live view is already running. It is unknown whether `MenuQsHandler`/`UicGuiMenuQs` exits cleanly
     into a menu-level page, and whether `QRDetectStart` and the LV-up message both arrive.
3. The private machine installs on the camera: `fpui_install` at entry, with a pack that carries one page that is
   never shown (`QSC_GoPack`, END record only).
   - [C] The pack shape is the proven fpsup-ui one.
   - [I] The never-shown page has not been tried on the camera.
   - Read `go_result` (`qsc_api.timing` + 112): it must be 0.
4. The go text is emptied at the next layout load, after the request was taken.
   - [I] This is the loader v4 rule, moved from "target page writes FT_Go = 0" to "container clears at the layout
     load".
   - Check that a later QS open (the QS button on the read page, or a new QS) does not bounce back to the read page.
5. The way back, all by stock transitions [C]:
   - MENU on the read page -> `Return` -> MainY5 (setup menu page 5). Which row then has the focus is [I].
   - The QS button -> `QS` -> QS_CINE.
   - A half-press -> LV.
6. `leave()` runs on the go's layout load. This is [C] in ARM offline, and needs checking with the camera's
   SensorLab record write.
