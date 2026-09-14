================================================================
 OG3K  fpsup-og3k-v0.2.1a
 SIGMA fp — 3:2 open gate, native UI, shutter-angle fix
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

  Native OG3K choices appear in Settings and Quick Set, including
  the UHD/FHD/OG3K three-choice footer.

  **Firmware Ver.5.02 only.** RAM only: delete AutoRun.txt, remove
  the battery, and the camera is stock. Nothing is written to flash.

----------------------------------------------------------------
NEW IN v0.2.1a
----------------------------------------------------------------

  Shutter-angle mode could make OG3K roughly 1.3–2 EV darker than
  FHD at unchanged settings. Resolution reconfiguration could put
  the borrowed sensor profile's nominal frame rate back into the
  exposure state.

  v0.2.1a routes all four local shutter-angle consumers through one
  guarded wrapper. It substitutes the selected output frame rate
  only when the exact OG3K timing tuple is active. Shutter-speed
  mode, FHD/UHD, stills, mixed state and unknown state stay stock.

  The loader also performs D-cache maintenance and then invalidates
  the whole I-cache after placing all sections, before any patched
  entry can run. This prevents a previously fetched stock call from
  hiding the newly installed hook.

----------------------------------------------------------------
FRAME RATES
----------------------------------------------------------------

     key         sensor  timing donor   fps       180-degree time
     ---------   ------  ------------   -------   ---------------
     OG3K23_98      98   mode 109       23.976      20,833 us
     OG3K24         98   mode 218       24.000      20,833
     OG3K25         98   mode 125       25.000      20,000
     OG3K30         98   mode 106       29.970      16,667
     OG3K48         98   mode 220       48.000      10,417
     OG3K50         98   mode 115       50.000      10,000
     OG3K60         98   mode  27       59.940       8,333
     OG3K100       117   computed      100.000       5,000

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
     the final message: fpSup-OG3K-v0.2.1a!
  5. Select OG3K from MENU -> recording -> resolution, or from
     Quick Set -> RES. Choose the frame rate normally.

  To remove: delete AutoRun.txt, power off completely, remove the
  battery, and power on. Warm restart and hot reinstall have not
  been verified; use a battery-out cold boot.

  This release deliberately carries no development USB shell. It
  boots faster and leaves no extra USB worker resident.

----------------------------------------------------------------
WHAT HAS BEEN VERIFIED
----------------------------------------------------------------

  Recording and ISO evidence carried forward:

    - A001_036 unpacked as 3024x2010, default crop 3008x2000 at
      (8,5), StripByteCounts 9,117,360, sharp edge to edge.
    - live view was correct in standby, half-press and recording.
    - at ISO 800, raw level/channel balance matched stock FHD and
      BaselineExposure was +3.000; gain_state 7 was measured at
      the decision function.
    - playback of the earlier recording core passed on v0.1.0test.

  Native UI evidence carried forward from v0.2.0test:

    - CINE Settings collapsed summary and three-row list passed.
    - Quick Set large/small OG3K values, cursor, and three-choice
      UHD/FHD/OG3K footer passed.
    - short record transitions passed: FHD once, UHD three times,
      and OG3K three times. UHD/OG3K were stopped at about one
      second because the available SD card was too slow.

  New shutter-angle evidence for v0.2.1a:

    - after a battery-out cold boot, the camera operator compared
      real FHD and OG3K at 29.97p, 180 degrees, in idle live view;
      the earlier exposure mismatch no longer appeared.
    - this is a provisional visual pass, not an exact USB-shell
      shutter readback. The other seven frame rates remain pending.

  Offline release checks passed: all 710 OpenGate words, all 360
  selected UI records, hook order, D-cache -> I-cache publication,
  release/debug section equivalence, shell absence, and 10 loader
  fault-injection tests.

----------------------------------------------------------------
THIS IS AN ALPHA BUILD
----------------------------------------------------------------

  The exact no-shell pair in this folder is structurally identical
  to the product payload in its paired debug build; the only VSHL
  section removed is the USB worker. This exact pair has not itself
  had a camera cold-boot run.

  Still unverified:

    - exact shutter readback and idle checks at the other frame rates
    - CINE/STILL transition while OG3K remains selected
    - sustained recording on sufficiently fast media
    - playback with the native v0.2 UI runtime
    - inactive screen/style variants
    - warm restart and hot reinstall

  One earlier OG3K attempt with the UI debug build froze after
  creating a clip. Three later one-second OG3K attempts did not
  reproduce it. Treat every take as disposable until checked.

----------------------------------------------------------------
MEDIA SPEED
----------------------------------------------------------------

  OG3K30 writes about 276 MB/s using the measured DNG file size.
  The UHS-II SD card used for testing measured about 94 MB/s. A card
  that cannot keep up can fill the camera's buffers and stop or
  destabilize a take. Use verified faster media for sustained tests.

  fpSup/tools/storage-benchmark measures a card using the camera's
  own storage path.

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
  Combined versions are generated only by the web card composer.
