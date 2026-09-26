# LV Boost (Live View Boost): STILL preview +1 / +2 / +3

Development module for **SIGMA fp firmware 5.02**. LV Boost adds a COLOR-menu
row that brightens the preview at a fixed capture exposure. The included
v0.5.2 card enables **Fast Start 2** and automatically selects **+2** after
stable STILL live view begins. Selecting a native color preset disables the
lift; a manual menu selection cancels a pending startup selection.

[Download the v0.5.2 development card](LV-Boost-v0.5.2-FS2-Auto2-Sigma-fp-5.02.zip).
This is a standalone alternative to RAW View, not a merge input. Both use the
same color-menu hooks. It is deliberately outside the release catalogue.

## Install and use

Back up your existing card files. Copy `AutoRun.txt`, `fpSup.BIN`, and the
`FPSUPUI` folder from the ZIP to the card root, then safely eject. The first
FS2 boot can be slower while the stored loader is provisioned. Boot with USB
unplugged; attach USB only after boot if using the diagnostic shell.

To update the previously installed v0.5.1 +2 card, replace **only `fpSup.BIN`**.
AutoRun and all five splash files are byte-identical. This v0.5.2 build changes
the COLOR-menu icon to **LV BOOST**; the automatic +2 behavior is unchanged.

The default is applied once after ten consecutive 100 ms samples of stable
STILL live view. You may then select +1, +2, +3, OFF, or another preset normally.
The next boot uses the built-in default again; the last-used level is not saved.
The menu icon reads LV BOOST. The full color title may still read OFF because the native firmware sees OFF
plus private mod state. The lifted display is not an exposure/clipping reference.

FS2 uses the existing shared loader's stored bootstrap and warm-restart hook.
It writes loader bytes to the camera's persistent common settings area;
deleting the card files does not erase those bytes. No new persistent storage
for LV Boost preferences is introduced.

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
python3 focus/lv-boost/build/build_lv_boost.py --fs2 --out focus/lv-boost/out/auto2
python3 focus/lv-boost/test_lv_boost.py -v
python3 focus/lv-boost/verify_card.py focus/lv-boost/out/auto2
```

`--default-level 1|2|3` selects the startup level (default: 2). Omit `--fs2`
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

With an already connected USB shell, read diagnostics without changing settings:

```sh
python3 focus/lv-boost/read_diagnostics.py --out /path/to/diagnostics.json
```

`startup_state`: 0 waiting, 1 applied, 2 manual menu override, 3 applying,
4 verification failed. `startup_task` and `startup_task_result` report native
task creation/start results. A task id at or below zero is a creation failure
(the JSON reader presents native words as unsigned integers).

## Validation and limits

- On-camera feedback: the v0.4 curve visibly lifted STILL preview. The user
  subsequently confirmed v0.5.0 automatically selected +3 and worked when
  powering up in STILL. Cold versus warm startup was not distinguished.
- v0.5.1 +2 was installed, fully read back and safely ejected. Physical +2
  startup confirmation is still pending.
- All 13 LV Boost tests pass in this repository, including native tone lookup,
  restricted navigation, selection/disable, startup +2, transitions, cancellation,
  and task/selection failure handling.
- Exact-card emulation runs the actual payloads through ordinary, stored-bootstrap
  and warm-hook loading, checking task creation and shutdown restoration.
  Native I/O, task scheduling, and settings side effects are mocked.
- Before the rename, the standalone sources reproduced all seven installed
  v0.5.1 card files byte-for-byte. The renamed v0.5.2 package was rebuilt and
  passed the same 13 tests and exact-card emulation; it has not booted on camera.
  The shared loader/splash suite and composer checks are also exercised.
- Development mutation checks caught a shortened stabilization wait and an OFF
  request substituted for the private LV Boost request.

No native startup gate was bypassed: FS2 still depends on the existing AutoRun
trigger. The STILL power-up report is not evidence that every cold-start path
works. Repeated idle power cycles, capture/JPEG/embedded-preview isolation,
AE behavior, focus magnification, and HDMI/EVF behavior remain unverified.
This is a development PR, not a production-readiness claim.

Renamed v0.5.2 `fpSup.BIN` SHA-256:
`b248c7e1764c0b8a6b7c7357166e74f48776fddd75b2343d06f7719d0dee6bf2`.
The ZIP includes checksums for every card file.
