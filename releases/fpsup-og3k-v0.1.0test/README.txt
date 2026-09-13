================================================================
 OG3K  og3k-v0.1.0test
 SIGMA fp — 3:2 open gate, eight frame rates
================================================================

WHAT IT IS

  The sensor's whole 3:2 area recorded as CinemaDNG, instead of the
  16:9 window the camera crops to — and at your choice of frame
  rate rather than 29.97 only.

     3024 x 2010 · 3:2 · 12-bit
     DNG cropped to 3008 x 2000 at (8, 5)

  **This is a native readout, not a downscale.** The sensor is put
  into mode 98 or 117 — its own 2x2-binned 3:2 mode, 3032 x 2012 —
  and the camera records that. It is not 6064 x 4042 read out and
  resampled to 3K, which is a different thing that costs 24.98 ms
  of rolling shutter where this costs 12.4.

  **ISO 100 only.** It is the only sensitivity this build has been
  seen to record correctly — see ISO 100 ONLY below.

  **Firmware Ver.5.02 only.** RAM only: delete AutoRun.txt, pull the
  battery, and the camera is stock. Nothing is written to flash.

----------------------------------------------------------------
FRAME RATES, AND WHY THEY ARE EXACT
----------------------------------------------------------------

     key         sensor  timing        picker   fps       rolling
                  mode                  slot
     ---------   ------  ------------  ------   -------   --------
     OG3K23_98      98   from mode 109   10      23.976   12.435 ms
     OG3K24         98   from mode 218    9      24.000   12.435
     OG3K25         98   from mode 125    8      25.000   12.575
     OG3K30         98   from mode 106    7      29.970   12.435
     OG3K48         98   from mode 220    6      48.000   12.435
     OG3K50         98   from mode 115    5      50.000   12.575
     OG3K60         98   from mode  27    4      59.940   12.435
     OG3K100       117   330/270/2182    12     100.000    9.222

  **98 and 117 are sensor modes.** Both read 3032 x 2012 out of the
  IMX410 — the full 3:2 area, 2x2 binned — and the camera records
  3024 x 2010 of it. They differ in line time, not in geometry:

     mode  98    hmax 445    native 77.27 fps
     mode 117    hmax 330    native 99.90 fps

  The **timing** column names a second sensor mode whose hmax, tail
  and vmax are copied onto the first. Those donors are all the
  3032 x 1708 FHD readout: what is borrowed is timing, not geometry,
  so the frame is unaffected and the rate comes out at the exact
  value the camera already ships. OG3K100 is the one exception —
  nothing factory runs 100 fps at this size, so its 330/270/2182 is
  computed.

  Seven rates sit on mode 98 because its 445-cycle line matches the
  factory FHD timings (445 or 450), and because one sensor mode
  carries one set of timings — so the hook rewrites them during the
  table lookup, which happens just before the sensor is programmed.
  100 fps needs mode 117's shorter line instead. 120 is impossible:
  at 3032 x 2012 the camera's smallest hmax caps out at 108.4 fps.

  Rolling shutter is hmax x height / 72 microseconds. Every rate
  here beats UHD CinemaDNG (21.088 ms); only FHD (10.556) is ahead,
  and only below 100 fps.

  You never choose any of this — you pick a frame rate in the menu.
  It is written down because a report saying "48p looks wrong" is
  worth far more when someone can go and check mode 220's timing.

----------------------------------------------------------------
ISO 100 ONLY
----------------------------------------------------------------

  **Shoot this at ISO 100.** That is the only sensitivity this build
  has been seen to record correctly. Other ISOs are not blocked — the
  menu will let you pick them — but what comes out of them has not
  been verified and should not be trusted.

  Why other ISOs misbehave is not yet known — it has not been traced,
  only observed. So the note is exactly what was seen and nothing
  more: ISO 100 records correctly, the rest have not been shown to.
  If you shoot one anyway, a report saying which ISO and what went
  wrong is genuinely useful.

----------------------------------------------------------------
THIS IS A TEST BUILD
----------------------------------------------------------------

  v0.1.0test. The 29.97 path (OG3K30) is the one that has been shot
  and verified frame by frame; the other seven share its machinery
  but have had far less time on a camera. Treat a take as disposable
  until you have checked it.

  Verified, on 29.97, at ISO 100:
    - whole frame is picture, edge to edge (A001_036 unpacked:
      header 3024x2010, crop 3008x2000, StripByteCounts 9,117,360)
    - live view correct in standby, half-press and recording
    - in-camera playback works, paused and running

  Not verified: the other seven rates end to end, and any ISO
  other than 100 at any rate.

----------------------------------------------------------------
INSTALL
----------------------------------------------------------------

  1. Check the body is on Ver.5.02. It will not work on anything
     else, and a card built for one version writes into whatever
     happens to be at those addresses on another.
  2. Power off, battery out, work on the card in a reader.
  3. Copy AutoRun.txt and VSHL.BIN to the ROOT of the SD card.
  4. Card in, power on. Progress bar, then fpSup-OG3K-v0.1.0t!
  5. MENU -> recording -> resolution: pick the new entry, then the
     frame rate as usual.
  6. Set ISO to 100. See ISO 100 ONLY above — it is the only one
     verified to record correctly.

  To remove: delete AutoRun.txt, power off COMPLETELY (battery out —
  a warm restart does not clear RAM), power on.

----------------------------------------------------------------
KNOWN COSMETIC ISSUES — they do not affect recording
----------------------------------------------------------------

  - MENU -> recording -> resolution shows `3` instead of a name.
    That column wants a string-resource id and we put a literal
    string there, so it falls back to printing the index.
  - QS cannot switch to it: the RES. cell draws garbage and the
    strip offers only UHD and FHD. MENU works normally.

----------------------------------------------------------------
THE THING MOST LIKELY TO BITE
----------------------------------------------------------------

  At 29.97 this writes 273 MB/s — about three times what a mid-range
  UHS-II SD card sustains. Measured on one here: 94 MB/s write,
  against the 97 MB/s that plain FHD 12-bit already needs.

  A card that cannot keep up buffers in RAM and then STOPS THE TAKE
  after a few seconds. That is the card, not a bug. Higher rates are
  proportionally worse — 48p is 437 MB/s, 60p is 546.

  Use an external SSD, or measure your card first:
  tools/storage-benchmark/ in the fpSup repository runs the camera's
  own benchmark and tells you what it actually does.

----------------------------------------------------------------
IF SOMETHING GOES WRONG
----------------------------------------------------------------

  Camera hangs at boot, or the progress bar stops: pull the battery,
  put the card in a reader, delete AutoRun.txt. Nothing persists.

  Worth reporting: firmware version, which frame rate, **which ISO**,
  what the screen showed, and whether the clip folder has any DNGs
  in it.
