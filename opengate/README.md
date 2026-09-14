# fpSup Open Gate — OG3K

**3024×2010 3:2 CinemaDNG at eight frame rates on the SIGMA fp.** The sensor's
whole 3:2 area instead of the 16:9 window the camera crops to. v0.2.1a includes
the native OG3K Settings and Quick Set UI and fixes OG3K shutter-angle exposure.
Release package: **`fpsup-og3k-v0.2.1a`**.

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
4. Card in, power on. The screen shows a progress bar and then
   `fpSup-OG3K-v0.2.1a!`.
5. Select **OG3K** from **MENU → recording → resolution** or Quick Set **RES.**

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
- **Native CINE UI** (v0.2.0test): the collapsed Settings summary, the Settings
  list, large and small Quick Set OG3K values, cursor, and the UHD/FHD/OG3K
  three-choice footer all passed on the camera. This evidence carries forward;
  the full UI suite was not re-run specifically for v0.2.1a.
- **Short recording transitions with the full UI runtime** (v0.2.0test): FHD
  once, UHD three times, and OG3K three times. UHD and OG3K were stopped at
  about one second because the test SD card cannot sustain their data rate.
  v0.2.1a makes no new recording-test claim.

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

## Shutter angle — what v0.2.1a fixes

OG3K could be roughly 1.3–2 EV darker than FHD at the same shutter-angle
setting. One nominal-frame-rate call had been redirected, but resolution
reconfiguration could later write the stock borrowed profile's nominal rate
back into exposure state. v0.2.1a redirects all four local consumers at
`C02092CC`, `C0218AEC`, `C0219260`, and `C03AA568` through the same guarded
wrapper. It substitutes the selected OG3K frame rate only for the exact OG3K
timing tuple; every other mode keeps the factory result.

The stage-two loader now publishes generated executable code with D-cache
maintenance followed by whole I-cache invalidation before entry. This prevents
the CPU from executing an older cached instruction after the patch has been
written.

## v0.2.1a boundaries

- **Provisional visual pass for the shutter-angle fix:** after a battery-out
  cold boot, the user compared real FHD and OG3K at 29.97p, 180°, in idle live
  view. The earlier exposure offset no longer appeared. This was a visual result,
  not an exact USB-shell readback, and the other frame rates remain pending.
- The exact shipped no-shell `AutoRun.txt` + `VSHL.BIN` pair is structurally
  verified against the corresponding debug build: only the USB shell worker and
  its patches are removed, while the OpenGate and UI payload bytes are identical.
  This exact no-shell pair has not itself been cold-booted on the camera.
- Warm-restart behaviour is unverified. Use a battery-out cold boot for install,
  retest, and recovery.
- The recording core grew from the v0.2.0test 590-word plan to 710 words for the
  four shutter-angle callsites. The camera-tested 360-record native UI runtime is
  otherwise carried forward unchanged.
- One earlier OG3K attempt froze after creating a clip. It was not reproduced by
  three later one-second OG3K recordings, but sustained recording on sufficiently
  fast media has not been tested with the new UI runtime.
- Playback with the native UI runtime and inactive screen/style variants remain
  untested. Playback of the earlier recording core was verified on v0.1.0test;
  it was not re-tested for v0.2.1a.

## Do not

- **Do not run this on a firmware other than Ver.5.02.**
- **Do not expect sustained OG3K or UHD on a slow card.** OG3K30 needs about
  273.2 MB/s; the test UHS-II card measured 94 MB/s. Insufficient media speed can
  fill the camera's buffers and stop or destabilize a take, so use faster media
  and treat every take from this test build as disposable until checked. See
  `tools/storage-benchmark/` to measure yours.

## Where this comes from

`MANIFEST.txt` carries the checksums and the reasoning — why 3024×2010 rather
than 3032×2012, which profile is borrowed and why, and what was verified when.
The research is in [`projects/open-gate.md`](../projects/open-gate.md); how the
answers were found is archived in `../projects/open-gate/notes/OPEN_GATE_EXPLORATION_ARCHIVE.md`.

To put the gyro logger on the same card, use
[`tools/card-composer`](../tools/card-composer/). Combined versions are generated
only by that composer; this repository does not ship hand-built combined cards.
