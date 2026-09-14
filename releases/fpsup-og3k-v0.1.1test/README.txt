================================================================
 OG3K  og3k-v0.1.1test
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

  **Every ISO now records correctly.** v0.1.0test was only right at
  ISO 100; the cause was found and fixed — see NATIVE ISO below.

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
NATIVE ISO — FIXED IN THIS BUILD
----------------------------------------------------------------

  v0.1.0test was only correct at ISO 100. The cause is now known.

  The IMX410 has two native sensitivities, and the switch point
  depends on what the camera thinks it is capturing:

     12-bit CinemaDNG   gain_state 7   switches at ISO 3200
     stills capture     gain_state 1/3 switches at ISO 640

  OG3K borrows a stills profile for its geometry, so its capture was
  classified as gain_state 3 and switched to the high-conversion-gain
  readout at ISO 640 — **about 2.7 stops of highlight headroom gone**
  at any ISO above that. Highlights clipped there are not recoverable.

  It also explains what people saw in playback: the movie pipeline
  records ~3 stops under and the camera's playback lifts it back by a
  fixed +3 EV. OG3K's frames were not recorded to that convention, so
  in-camera playback over-exposed them by the same 2.7 stops. Files
  were always internally consistent — a renderer that honours
  BaselineExposure (Resolve, for one) showed them correctly.

  Measured, same scene and settings, ISO 800:

     before   raw 2.675 EV brighter than stock FHD, BaselineExposure +0.322
     after    identical to stock FHD, BaselineExposure +3.000

  The fix hooks one predicate — the "is this a raw movie" test the
  gain dispatch uses — so the capture is classified correctly. It
  deliberately does not touch the sensor-mode programming that shares
  the same flag: doing that made the recording preview flicker green.
  The preview plane is also declared 12-bit, as the factory movie
  profiles do, instead of the 8-bit a stills profile declares.

----------------------------------------------------------------
THIS IS A TEST BUILD
----------------------------------------------------------------

  v0.1.1test. The 29.97 path (OG3K30) is the one that has been shot
  and verified frame by frame; the other seven share its machinery
  but have had far less time on a camera. Treat a take as disposable
  until you have checked it.

  Verified, on 29.97:
    - whole frame is picture, edge to edge (A001_070 unpacked:
      header 3024x2010, crop 3008x2000, StripByteCounts 9,117,360,
      BaselineExposure +3.000)
    - at ISO 800, raw level and channel balance match a stock FHD
      clip of the same scene (G/R 1.81, G/B 1.99 against 1.81, 2.05)
    - the capture runs on gain_state 7, measured at the decision
      function rather than inferred
    - live view correct in standby, half-press and recording
    - in-camera playback verified on v0.1.0test, not re-checked on
      this build

  Not verified: the other seven rates end to end, and in-camera
  playback on this build.

----------------------------------------------------------------
INSTALL
----------------------------------------------------------------

  1. Check the body is on Ver.5.02. It will not work on anything
     else, and a card built for one version writes into whatever
     happens to be at those addresses on another.
  2. Power off, battery out, work on the card in a reader.
  3. Copy AutoRun.txt and VSHL.BIN to the ROOT of the SD card.
  4. Card in, power on. Progress bar, then fpSup-OG3K-v0.1.1!
  5. MENU -> recording -> resolution: pick the new entry, then the
     frame rate as usual.
  6. Any ISO. The ISO 100 restriction in v0.1.0test is gone — see
     NATIVE ISO above.

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
WITH THANKS TO VITALY LI
----------------------------------------------------------------

  Vitaly Li got open gate out of a SIGMA fp first. FP3K recorded
  3000 x 2000 12-bit CinemaDNG at 24 fps to an SSD, with the full
  3:2 height, before anything here existed.

  https://www.facebook.com/groups/1124721801045663/permalink/3266113850239770/

  The two builds reach 3K by different roads, and the difference is
  only where the 2:1 happens:

     FP3K    sensor mode 151 carrying native full-height mode 3's
             geometry. The sensor reads its whole 6064 x 4042 window
             and the ISP reduces 2:1 into 3032 x 2020; the DNG is
             cropped to 3000 x 2000 at (16, 10). HMAX 445, VMAX 6740,
             tail 1145 -- 445*(6740-1)+1145 = 3,000,000 cycles, which
             is exactly 24 fps at 72 MHz.

     OG3K    sensor modes 98 and 117, which are the sensor's own
             2x2-binned 3:2 modes. The 3032 x 2012 arrives already
             reduced, so the ISP scales nothing.

  That is the whole of it, and it is what the rolling-shutter numbers
  in this file are measuring. Line time is the same 445 cycles in
  both; what differs is how many lines the sensor has to clock out:

     FP3K    445 x 4042 / 72 = 24.98 ms
     OG3K    445 x 2012 / 72 = 12.44 ms

  The 24.98 ms quoted earlier in this README is FP3K's figure,
  computed from his own timing constants. Reading fewer lines is the
  only reason this build is faster -- it is not a better idea, it is
  a different place to put the same division. His route keeps every
  photosite in the path, which this one gives up by construction;
  his own notes are careful to say the exact reduction filter is
  still unresolved, and that question does not even arise here
  because the sensor does the binning.

  His technical handoff is what made that comparison possible to
  write at all. The picture is more complete for it.

----------------------------------------------------------------
IF SOMETHING GOES WRONG
----------------------------------------------------------------

  Camera hangs at boot, or the progress bar stops: pull the battery,
  put the card in a reader, delete AutoRun.txt. Nothing persists.

  Worth reporting: firmware version, which frame rate, **which ISO**,
  what the screen showed, and whether the clip folder has any DNGs
  in it.
