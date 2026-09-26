# LV Boost (Live View Boost): STILL preview +1 / +2 / +3

Part of the [RAW/live-view tools](../README.md), alongside [RAW View](../../releases/fpsup-raw-view-v0.2.0test/).

Development module for **SIGMA fp firmware 5.02**. LV Boost adds a COLOR-menu
row that brightens the preview at a fixed capture exposure. The included
v0.6.0 card enables **Fast Start 2** and restores the last selected LV Boost
level after stable STILL live view begins. First use defaults to **+2**.
Selecting OFF or a native color preset saves LV Boost as disabled; the next
boot leaves the native color choice alone. A manual menu selection cancels a
pending startup restore.

[Download the v0.6.0 development card](LV-Boost-v0.6.0-FS2-Saved-Sigma-fp-5.02.zip).
This is a standalone alternative to RAW View, not a merge input. Both use the
same color-menu hooks. It is deliberately outside the release catalogue.

## Install and use

Back up your existing card files. Copy `AutoRun.txt`, `fpSup.BIN`, and the
`FPSUPUI` folder from the ZIP to the card root, then safely eject. The first
FS2 boot can be slower while the stored loader is provisioned. Boot with USB
unplugged; attach USB only after boot if using the diagnostic shell.

To update an existing v0.5.1 or v0.5.2 FS2 card, replace **only `fpSup.BIN`**.
AutoRun and all five splash files are byte-identical.

Select LV BOOST in COLOR and adjust it to +1, +2, or +3. Turn the camera off
normally to let its existing settings save complete. On next boot, the saved
level is applied once after ten consecutive 100 ms samples of stable STILL.
Selecting OFF or another color preset disables automatic LV Boost restoration
while retaining its last level for when you select LV BOOST again. A battery
removal before normal shutdown may lose the latest change. Reset/invalid
settings fall back to the built-in +2 default.
The menu icon reads LV BOOST. The full color title may still read OFF because the native firmware sees OFF
plus private mod state. The lifted display is not an exposure/clipping reference.

FS2 uses the existing shared loader's stored bootstrap and warm-restart hook.
It writes loader bytes to the camera's persistent common settings area;
deleting the card files does not erase those bytes or the saved LV Boost preference.

## Build

Requirements: Python 3, Clang with the `armv7-none-eabi` target, and the existing
build/test dependencies:

```sh
python3 -m pip install numpy capstone unicorn pillow
```

Supply these extracted **5.02** firmware segments in the repository's `out/`
directory. Firmware images are not included in this PR. If using the full
research devkit, these are the same segments its builders use; its extracted
`DAT1_c2ef6e00.bin` is copied as `seg1_c2ef6e00.bin`.

| File | SHA-256 |
|---|---|
| `out/MAIN_c0000000.bin` | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| `out/seg1_c2ef6e00.bin` | `0dcaca8f5441fe4ddc6ed801cb888e325df4e76006e4f53a1c3219809b22ce7b` |

From the repository root, build into a fresh directory:

```sh
python3 raw/lv-boost/build/build_lv_boost.py --fs2 --out raw/lv-boost/out/auto2
python3 raw/lv-boost/test_lv_boost.py -v
python3 raw/lv-boost/verify_card.py raw/lv-boost/out/auto2
```

`--default-level 1|2|3` selects the first-use/fallback level (default: 2); a valid
saved preference takes precedence. Omit `--fs2`
for ordinary AutoRun loading; add `--no-shell` to omit the diagnostic shell.
The builder uses the repository's shared `fp_usb_shell/build_autorun.py` and
its existing loader, stage2, journal, Fast bootstrap and splash resources.
There is no separate loader implementation. Generated includes and local
build output are ignored. Do not commit extracted firmware images.

The `rv_*` sources are derived from the research devkit's RAW View implementation.
Its LV_BOOST assembly variant is retained to preserve the tested startup and tone behavior. The Python wrapper is restricted to LV Boost and uses this repository's
paths, so no external research-tree modules or data are required after supplying
the firmware segments. The unused matrix buffers retain their original layout;
the LV Boost hooks do not install the RAW gain, global tone/matrix-root, or
DNG-writer patches.

## Implementation

Three 2048-entry tone curves apply +1/+2/+3 stops in linear light with a soft
highlight shoulder. The tone-pointer hook replaces only the stock OFF table
for context 0, native single-table dispatch, and live-view attribute 1 with
application status 2 or 5. The gain hook only invalidates the preview tone
cache when the selection changes; it preserves the original gain-state result.
All firmware hook sites are declared for the shared loader's shutdown journal.

A priority-28 task with an 8 KiB stack waits for stable STILL, requests OFF
through the native settings facade with the private LV Boost selection,
checks the result, and parks. It does not call settings APIs from ISP hooks,
retry failed selections, or hold pointers into the freed staging buffer.

Preferences occupy one aligned word at `0xC307544C` (`XC_CommonSaveData +0x210`):
`0x4C560100 | (enabled << 2) | level_index`, where the index is 0..2. The
upper 29 bits identify format version 1; both invalid index encodings are
rejected. Installation only reads it. Successful startup, menu selection, and
level changes update the RAM mirror; the camera's normal shutdown saves it.
Native initialization/apply callbacks do not overwrite it before restoration.
No new file I/O, explicit flash writes, or polling saves are introduced.
This preference deliberately stays out of the firmware-patch shutdown journal.

The full devkit's `research/firmware/notes/PERSISTENT_STORE_COMMONSAVE.md`
records power-cycle survival of the +0x210..+0x280 span. This word is outside
Fast's entire +0x028..+0x200 reservation and OpenGate's +0x290 preference.
Those research notes are not bundled here. Historical survival does not prove
that no untested native feature uses this reserved area; this remains an
experimental allocation for fp 5.02 and needs camera power-cycle validation.

With an already connected USB shell, read diagnostics without changing settings:

```sh
python3 raw/lv-boost/read_diagnostics.py --out /path/to/diagnostics.json
```

`startup_state`: 0 waiting, 1 applied, 2 manual menu override, 3 applying,
4 verification failed, 5 saved disabled. `startup_task` and `startup_task_result` report native
task creation/start results. A task id at or below zero is a creation failure
(the JSON reader presents native words as unsigned integers).

## Validation and limits

- On-camera feedback: the v0.4 curve visibly lifted STILL preview. The user
  subsequently confirmed v0.5.0 automatically selected +3 and worked when
  powering up in STILL. Cold versus warm startup was not distinguished.
- v0.5.1 +2 was installed, fully read back and safely ejected. Physical +2
  startup confirmation is still pending.
- All 16 LV Boost tests pass in this repository, including native tone lookup,
  restricted navigation, selection/disable, startup +2, transitions, cancellation,
  task/selection failure handling, saved levels/disabled state, invalid data,
  boot callback protection, and writes confined to the preference word.
- Exact-card emulation runs the actual payloads through ordinary, stored-bootstrap
  and warm-hook loading, checking task creation and shutdown restoration.
  Native I/O, task scheduling, and settings side effects are mocked.
- Before the rename, the standalone sources reproduced all seven installed
  v0.5.1 card files byte-for-byte. The renamed v0.5.2 package was rebuilt and
  passed the same 13 tests and exact-card emulation; it has not booted on camera.
  The shared loader/splash suite and composer checks were also exercised.
- v0.6.0 passes all 16 tests and exact-card emulation of all three loading paths.
  Fast provisioning and shutdown preserve the preference word. Saved settings
  have not yet been validated on the camera; flash persistence and native task
  scheduling are not simulated.
- Development mutation checks caught a shortened stabilization wait and an OFF
  request substituted for the private LV Boost request. Removing the saved-word
  store also makes the new persistence test fail for all three levels.

No native startup gate was bypassed: FS2 still depends on the existing AutoRun
trigger. The STILL power-up report is not evidence that every cold-start path
works. Repeated idle power cycles, capture/JPEG/embedded-preview isolation,
AE behavior, focus magnification, and HDMI/EVF behavior remain unverified.
This is a development PR, not a production-readiness claim.

v0.6.0 `fpSup.BIN` SHA-256:
`02da37e5f987350114dcadde56f72fe5eaaf4344b23de5cf5b08a54a30909281`.
The ZIP includes checksums for every card file.
