================================================================
 OG2K  fpsup-og2k-v0.1.1a
 SIGMA fp — 3:2 open gate at 2K, on the sensor's quiet readout
================================================================

WHAT IT IS

  The sensor's whole 3:2 area recorded as CinemaDNG, at the
  sensor's native 3x reduction instead of the 2x one OG3K uses:

     2016 x 1344 stored RAW matrix · 3:2 · 8, 10 or 12-bit
     DNG default crop 2000 x 1334 at (8, 5)
     rolling shutter 8.31 ms

  2016 x 1344 is the full 6064 x 4042 sensor reduced by three. It
  is not a crop: the field of view is the same open gate as OG3K,
  at a third of the data.

  Eight frame rates from 23.976 to 100, and **all eight run on the
  quiet readout** (sensor mode 139). OG3K has to use the noisier
  fast readout for its 100p; OG2K never does.

     12-bit  4.06 MB/frame     24p =  98 MB/s
     10-bit  3.39 MB/frame     24p =  81 MB/s
      8-bit  2.71 MB/frame     24p =  65 MB/s

  For comparison OG3K at 24p is 219 MB/s and UHD is 301 MB/s. This
  is the first open-gate mode an ordinary fast card can sustain.

  **Firmware Ver.5.02 only.** RAM only: delete AutoRun.txt, remove
  the battery, and the camera is stock. Nothing is written to flash.

  **OG2K replaces the third resolution choice.** It cannot coexist
  with OG3K on the same card: the resolution menu block holds three
  entries and no more.

----------------------------------------------------------------
FRAME RATES
----------------------------------------------------------------

     key          vmax  tail     fps        error    MB/s 12-bit
     ---------    ----  ----     -------    ------   ----------
     OG2K23_98    6748   585     23.97602   0 ppm        97
     OG2K24       6741   700     24.00000   0 ppm        98
     OG2K25       6471   850     25.00000   0 ppm       102
     OG2K30       5398   735     29.97003   0 ppm       122
     OG2K48       3370   795     48.00000   0 ppm       195
     OG2K50       3235   870     50.00000   0 ppm       203
     OG2K60       2699   590     59.94006   0 ppm       244
     OG2K100      1617   880    100.00000   0 ppm       406

  All eight share sensor mode 139's line time, which is what keeps
  them on the quiet readout. 119.88p is not offered: the active
  rows alone would need 598,080 of the 600,600 available cycles.

----------------------------------------------------------------
WHAT CHANGED SINCE v0.1.0test

  The recording core is the same.  What changed is the card around
  it: the payload container is fpSup.BIN, the AutoRun is 103 commands
  instead of 135, and the card is built on the entry contract the
  rest of the tree now uses -- a payload is called once and asks the
  allocator for whatever memory it needs, rather than reading a
  pointer the script used to leave behind.

  v0.1.0test announced OG3K's version number and said fpSup-OG3K on
  the screen: one version constant and one banner served both open
  gate builds.  This one names itself.

  Booted and recorded on the camera, 2026-09-19.

INSTALL
----------------------------------------------------------------

  1. Confirm the camera is a SIGMA fp on firmware Ver.5.02.
  2. Power off, REMOVE THE BATTERY, and put the card in a reader.
  3. Copy AutoRun.txt and fpSup.BIN to the ROOT of the SD card.
  4. Insert the card and power on. Wait for the progress bar and
     the final message: fpSup-OG2K-v0.1.1a!
  5. Select OG2K from MENU -> recording -> resolution, or from
     Quick Set -> RES. Choose the frame rate and the CinemaDNG
     quality normally.

  To remove: delete AutoRun.txt, power off completely, remove the
  battery, and power on. Warm restart and hot reinstall have not
  been verified; use a battery-out cold boot.

  This release carries no development USB shell.

----------------------------------------------------------------
WHAT HAS BEEN VERIFIED
----------------------------------------------------------------

  On camera, after a battery-out cold boot. Every geometry figure
  below was read out of the recorded DNG, not from a menu readback:

    - 12, 10 and 8-bit all record 2016x1344 with DefaultCropSize
      2000x1334 at (8,5).
    - FHD (1936x1090) and UHD (3856x2170) are unaffected, and
      switching OG2K -> FHD -> UHD -> OG2K does not corrupt any of
      them.
    - live view during recording matches standby: horizontal
      1.001x, vertical 1.000x, anisotropy 1.0010, no colour cast,
      full 3:2 frame.
    - in-camera playback opens, plays, and does not freeze.
    - the Settings resolution row reads OG2K.
    - the playback label reads 2000x1334 in the camera's own style.

----------------------------------------------------------------
WHAT IS NOT VERIFIED — THIS IS A TEST BUILD
----------------------------------------------------------------

    - **Highlight headroom and gain state.** OG3K originally lost
      about 2.7 stops of highlight above ISO 640 because its
      capture was classified as a stills acquisition. Mode 139 is
      a monitor-class mode and is expected to behave differently,
      but this has not been measured.
    - **Shutter angle.** Mode 139's nominal frame rate metadata is
      60 and all eight rates share it, the same structure that
      caused OG3K's shutter-angle error. The guarded wrapper
      carries mode 139's timing whitelist, but no shutter readback
      has been taken at any rate.
    - **Sustained recording.** The data rate finally fits ordinary
      fast media, but only short takes have been recorded.
    - Taking a still photo while OG2K is selected.
    - Switching CINE/STILL while OG2K remains selected.
    - Warm restart and hot reinstall.
    - The exact no-shell pair in this folder is byte-identical to
      the camera-tested debug build apart from the removed USB
      worker section, but has not itself been cold-booted.

  Treat every take as disposable until you have checked it.

----------------------------------------------------------------
HOW IT DIFFERS FROM OG3K
----------------------------------------------------------------

                     OG3K              OG2K
    sensor mode      98 (2x2)          139 (3x3)
    raster           3032x2012         2016x1344
    recorded         3024x2010         2016x1344
    DNG crop         3008x2000         2000x1334
    rolling shutter  12.44 ms          8.31 ms
    24p 12-bit       219 MB/s          98 MB/s
    100p readout     fast (noisier)    quiet
    field of view    full 3:2          full 3:2 (identical)

  Both are open gate. OG2K trades resolution for a third of the
  data, a shorter rolling shutter, and the quiet readout at every
  frame rate.

----------------------------------------------------------------
WITH THANKS TO VITALY LI
----------------------------------------------------------------

  Vitaly Li got open gate out of a SIGMA fp first.

  https://www.facebook.com/groups/1124721801045663/permalink/3266113850239770/

----------------------------------------------------------------
FILES
----------------------------------------------------------------

  AutoRun.txt   boot loader and progress display
  fpSup.BIN      OpenGate recording core plus native UI runtime
  MANIFEST.txt  exact hashes, memory map, and verification boundary
  README.txt    this file

  Only AutoRun.txt and fpSup.BIN go on the SD card.
