# fpSup Open Gate — OG3K

**3024×2010 3:2 CinemaDNG at 29.97 on the SIGMA fp.** The sensor's whole 3:2 area
instead of the 16:9 window the camera crops to.

Firmware **Ver.5.02 only.** Everything is RAM-only: remove `AutoRun.txt`, fully
power-cycle, and the camera is stock. Nothing is ever written to flash.

用感光元件完整的 3:2 面積錄影,而不是相機裁出來的 16:9 視窗。
**僅限韌體 Ver.5.02**,全部只改 RAM,拿掉 `AutoRun.txt` 完整斷電就回原狀。

---

## What you get

```
3024 × 2010 · 3:2 · 12-bit · 29.97003 fps · rolling shutter 9.221 ms
DNG cropped to 3008 × 2000 at (8, 5) · 273.2 MB/s
```

Rolling shutter is **better than any shipping CinemaDNG mode**, which matters if
you are also running the gyro logger — it corrects for exactly this:

| | readout | rolling shutter |
|---|---|---|
| **OG3K** | **3024×2010 2×2 3:2** | **9.221 ms** |
| FHD CinemaDNG | 3032×1708 2×2 | 10.556 ms |
| UHD CinemaDNG | 6064×3412 1×1 | 21.088 ms |

## Install

1. Check the body is on **Ver.5.02**. It will not work on anything else, and a
   card built for one version writes into whatever happens to be at those
   addresses on another.
2. Power off, remove the battery, and work on the SD card in a reader.
3. Copy **`AutoRun.txt`** and **`VSHL.BIN`** to the **root** of the card. Nothing
   else — no folder to make, no file to convert.
4. Card in, power on. The screen shows a progress bar and then `fpSup-OG3K-v0.1.1!`.
5. **MENU → recording → resolution** now offers a third entry. Pick it.

To remove it: delete `AutoRun.txt`, power off **completely** (battery out, not
just the switch — a warm restart does not clear RAM), power on.

## Verified

- **Whole frame is picture.** A001_036 unpacked: header 3024×2010, crop
  3008×2000 at (8, 5), `StripByteCounts` 9,117,360 = 3024 × 2010 × 1.5, sharp
  edge to edge, nothing clipped.
- **Live view** correct in standby, half-press and recording — a recording frame
  against a standby frame is 1.000× on both axes, anisotropy 1.0000, correlation
  0.9787.
- **In-camera playback** works, paused and running (A001_037, on v0.1.0test;
  not re-checked on v0.1.1test).
- **Every ISO records correctly** (v0.1.1test). At ISO 800 the raw level and
  channel balance match a stock FHD clip of the same scene — G/R 1.81, G/B 1.99
  against 1.81, 2.05 — and `BaselineExposure` is +3.000, as the factory writes.
  The capture is measured to run on `gain_state` 7 at the decision function
  itself, not inferred.

## Native ISO — what v0.1.1test fixed

The IMX410 has two native sensitivities, and where it switches between them
depends on how the capture is classified:

| classification | switch point |
|---|---|
| 12-bit CinemaDNG (`gain_state` 7) | ISO 3200 |
| stills capture (`gain_state` 1/3) | ISO 640 |

OG3K borrows a stills profile for its geometry, so up to v0.1.0test the capture
was classified as a stills acquisition and moved to the high-conversion-gain
readout at ISO 640 — **about 2.7 stops of highlight headroom lost** above that.
Clipped highlights do not come back.

It is also why in-camera playback looked over-exposed. The movie pipeline
records roughly 3 stops under and playback lifts it by a fixed +3 EV; OG3K's
frames were not recorded to that convention, so playback over-exposed them by
the same 2.7 stops. The files themselves were always internally consistent —
anything that honours `BaselineExposure` rendered them correctly.

Measured, same scene and settings, at ISO 800:

| | raw vs stock FHD | `BaselineExposure` |
|---|---|---|
| v0.1.0test | 2.675 EV brighter | +0.322 |
| v0.1.1test | identical | +3.000 |

The fix hooks the single predicate the gain dispatch uses to ask "is this a raw
movie". It deliberately leaves alone the sensor-mode programming that reads the
same flag: driving that too made the recording preview flicker green. The
preview plane is also declared 12-bit, as the factory movie profiles do, rather
than the 8-bit a stills profile declares.

## Known cosmetic issues — they do not affect recording

- **MENU → recording → resolution shows `3` instead of a name.** That column
  wants a string-resource id and we put a literal string there, so it falls back
  to printing the index.
- **QS cannot switch to it.** The RES. cell draws garbage and the strip offers
  only UHD and FHD. Selecting OG3K from MENU works normally.

## Do not

- **Do not run this on a firmware other than Ver.5.02.**
- **Do not expect it to fit a slow card.** 273.2 MB/s is two and a half times
  what a mid-range UHS-II card sustains; a card that cannot keep up will buffer
  in RAM and then stop the take after a few seconds. That is the card, not a bug.
  See `tools/storage-benchmark/` to measure yours.

## Where this comes from

`MANIFEST.txt` carries the checksums and the reasoning — why 3024×2010 rather
than 3032×2012, which profile is borrowed and why, and what was verified when.
The research is in [`projects/open-gate.md`](../projects/open-gate.md); how the
answers were found is archived in `../projects/open-gate/notes/OPEN_GATE_EXPLORATION_ARCHIVE.md`.

To put the gyro logger on the same card, merge them with
[`tools/card-composer`](../tools/card-composer/) — that is the only place merged
cards are made.
