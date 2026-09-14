================================================================
 OG3K  og3k-v0.2.0test
 SIGMA fp — 3:2 open gate, native Settings and Quick Set UI
================================================================

WHAT IT IS

  The sensor's whole 3:2 area recorded as CinemaDNG instead of the
  16:9 window the camera normally crops to:

     3024 x 2010 stored RAW matrix · 3:2 · 12-bit
     DNG default crop 3008 x 2000 at (8, 5)

  This is the IMX410's native 2x2-binned 3032 x 2012 readout, not
  a 6064 x 4042 image downscaled by the ISP. Eight frame rates are
  available from 23.976 through 100 fps. Every ISO uses the native
  CinemaDNG gain path fixed in v0.1.1test.

  NEW IN v0.2.0test: OG3K now appears natively in both Settings and
  Quick Set. The Settings summary/list, large and small QS values,
  cursor, and UHD/FHD/OG3K three-choice footer have all worked on
  the camera.

  **Firmware Ver.5.02 only.** RAM only: delete AutoRun.txt, remove
  the battery, and the camera is stock. Nothing is written to flash.

----------------------------------------------------------------
FRAME RATES
----------------------------------------------------------------

     key         sensor  timing donor   fps       rolling shutter
     ---------   ------  ------------   -------   ---------------
     OG3K23_98      98   mode 109       23.976      12.435 ms
     OG3K24         98   mode 218       24.000      12.435
     OG3K25         98   mode 125       25.000      12.575
     OG3K30         98   mode 106       29.970      12.435
     OG3K48         98   mode 220       48.000      12.435
     OG3K50         98   mode 115       50.000      12.575
     OG3K60         98   mode  27       59.940      12.435
     OG3K100       117   computed      100.000       9.222

  Modes 98 and 117 have the same 3032 x 2012 geometry. They differ
  in line time. The donor contributes timing only; it does not crop
  the frame. OG3K100 uses computed timing because no factory mode
  runs 100 fps at this size.

----------------------------------------------------------------
INSTALL
----------------------------------------------------------------

  1. Confirm the camera is a SIGMA fp on firmware Ver.5.02.
  2. Power off, REMOVE THE BATTERY, and put the card in a reader.
  3. Copy AutoRun.txt and VSHL.BIN to the ROOT of the SD card.
  4. Insert the card and power on. Wait for the progress bar and
     the final message: fpSup-OG3K-v0.2.0!
  5. Select OG3K from MENU -> recording -> resolution, or from
     Quick Set -> RES. Choose the frame rate normally.

  To remove: delete AutoRun.txt, power off completely, remove the
  battery, and power on. A warm restart does not clear the patch.

  This release deliberately carries no development USB shell. It
  boots faster and leaves no extra USB worker resident.

----------------------------------------------------------------
WHAT HAS BEEN VERIFIED
----------------------------------------------------------------

  Recording core, inherited unchanged from v0.1.1test:

    - A001_036 unpacked as 3024x2010, default crop 3008x2000 at
      (8,5), StripByteCounts 9,117,360, sharp edge to edge.
    - live view was correct in standby, half-press and recording.
    - at ISO 800, raw level/channel balance matched stock FHD and
      BaselineExposure was +3.000; gain_state 7 was measured at
      the decision function.
    - playback of the unchanged core was verified on v0.1.0test.

  Native UI integration, tested with the full equivalent debug build:

    - CINE Settings collapsed summary and three-row list passed.
    - Quick Set large/small OG3K values, cursor, and three-choice
      UHD/FHD/OG3K footer passed.
    - short record transitions passed: FHD 1 time, UHD 3 times,
      and OG3K 3 times. UHD/OG3K were stopped at about one second
      because the available SD card cannot sustain the data rate.

  The released no-shell VSHL contains the exact same 590-word
  OpenGate plan and exact same native UI code, private resources,
  state, and three hooks as that debug build. An offline section-map
  verifier checks every word and proves that only the USB worker and
  its interface patches were removed.

----------------------------------------------------------------
THIS IS A TEST BUILD
----------------------------------------------------------------

  The exact no-shell pair in this folder has not yet had its own
  camera cold-boot run. One earlier OG3K recording attempt with the
  UI debug build froze after creating a clip; three later one-second
  OG3K attempts did not reproduce it.

  Still unverified with the v0.2 UI runtime:

    - sustained recording on sufficiently fast media
    - in-camera playback regression
    - inactive screen/style variants
    - full end-to-end coverage of all eight frame rates

  Treat every take as disposable until you have checked the files.

----------------------------------------------------------------
MEDIA SPEED
----------------------------------------------------------------

  OG3K30 writes about 273 MB/s. The UHS-II SD card used for these
  tests measured about 94 MB/s; plain FHD 12-bit already needs about
  97 MB/s. A card that cannot keep up can fill the camera's buffers
  and stop or destabilize a take. Use an external SSD or verified
  faster media for sustained testing.

  fpSup/tools/storage-benchmark measures a card using the camera's
  own storage path.

----------------------------------------------------------------
NATIVE ISO
----------------------------------------------------------------

  v0.1.0test borrowed a stills profile and was classified as a stills
  capture. That moved the dual-native switch from ISO 3200 to ISO 640
  and cost about 2.7 stops of highlight headroom above ISO 640.

  v0.1.1test fixed the classification at the gain dispatch only and
  declared the preview plane 12-bit. v0.2.0test carries that exact
  recording core unchanged. No ISO 100 restriction remains.

----------------------------------------------------------------
WITH THANKS TO VITALY LI
----------------------------------------------------------------

  Vitaly Li got open gate out of a SIGMA fp first. FP3K records the
  full 3:2 height and performs its 2:1 reduction in the ISP. OG3K
  uses the sensor's native 2x2-binned 3:2 mode instead.

  https://www.facebook.com/groups/1124721801045663/permalink/3266113850239770/

----------------------------------------------------------------
FILES
----------------------------------------------------------------

  AutoRun.txt   boot loader and progress display
  VSHL.BIN      OpenGate recording core plus native UI runtime
  MANIFEST.txt  exact hashes, memory map, and verification boundary
  README.txt    this file

  Only AutoRun.txt and VSHL.BIN go on the SD card.
