================================================================
 OG3K  fpsup-og3k-v0.2.2a
 SIGMA fp — 3:2 open gate, native UI, 8/10/12-bit CinemaDNG
================================================================

WHAT IT IS

  The sensor's whole 3:2 area recorded as CinemaDNG instead of the
  16:9 window the camera normally crops to:

     3024 x 2010 stored RAW matrix · 3:2 · 8, 10 or 12-bit
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
NEW IN v0.2.2a — 8-bit and 10-bit CinemaDNG
----------------------------------------------------------------

  In v0.2.1a, choosing 8-bit or 10-bit CinemaDNG quality while OG3K
  was selected silently recorded UHD30 instead. The resolution name
  still said OG3K everywhere, so takes could be ruined without any
  on-screen sign.

  The camera's format picker has three tables, not one. The table
  is chosen by eRawBitType: 8-bit and 10-bit each have their own,
  and all three are CinemaDNG. OG3K was registered only in the
  12-bit table, so the other two missed and the firmware's error
  fallback returned that table's first entry — UHD30, at its 12-bit
  profile, discarding both the chosen resolution and the chosen bit
  depth, at any frame rate.

  v0.2.2a registers OG3K in all three tables and sets the canvas
  plane format codes to match the selected depth, so the DNG tag
  and the packed data always agree. No new hooks; no stock data is
  modified.

  Measured on camera with the recorder's own per-frame file size:

                 v0.2.1a            v0.2.2a          correct
     12-bit       9,196,544 ok       9,196,544 ok    3024x2010x1.50
     10-bit      12,630,528 UHD       7,676,928 ok    3024x2010x1.25
      8-bit      12,631,552 UHD       6,158,336 ok    3024x2010x1.00

  12-bit is unchanged. The UHD fallback is gone. Recording preview
  showed no colour shift at any depth.

  8-bit OG3K is 6.16 MB per frame against 12-bit's 9.20 MB, about
  148 MB/s at 24p instead of 221 MB/s. Slower cards have a better
  chance of sustaining a take.

  In-camera playback and highlight headroom at 8-bit and 10-bit are
  NOT yet verified. See WHAT IS NOT VERIFIED below.

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
     the final message: fpSup-OG3K-v0.2.2a!
  5. Select OG3K from MENU -> recording -> resolution, or from
     Quick Set -> RES. Choose the frame rate and the CinemaDNG
     quality normally.

  To remove: delete AutoRun.txt, power off completely, remove the
  battery, and power on. Warm restart and hot reinstall have not
  been verified; use a battery-out cold boot.

  This release deliberately carries no development USB shell. It
  boots faster and leaves no extra USB worker resident.

----------------------------------------------------------------
WHAT HAS BEEN VERIFIED
----------------------------------------------------------------

  New in v0.2.2a, on camera, after a battery-out cold boot:

    - 12-bit OG3K per-frame size unchanged at 9,196,544 bytes.
    - 10-bit recorded 7,676,928 and 8-bit recorded 6,158,336,
      both exactly 3024 x 2010 at the selected depth plus header.
    - the 12,630,528-byte UHD30 fallback no longer occurs.
    - recording preview at all three depths: full 3:2 frame, HUD
      correct, 29.97p, and no green cast (centre-region G/R was
      0.951, 0.962, 0.962).

  Carried forward:

    - A001_036 unpacked as 3024x2010, default crop 3008x2000 at
      (8,5), StripByteCounts 9,117,360, sharp edge to edge.
    - live view was correct in standby, half-press and recording.
    - at ISO 800, 12-bit raw level/channel balance matched stock
      FHD and BaselineExposure was +3.000; gain_state 7 was
      measured at the decision function.
    - 12-bit playback passed on v0.1.0test and again on 2026-09-13.
    - CINE Settings collapsed summary and three-row list passed.
    - Quick Set large/small OG3K values, cursor, and three-choice
      UHD/FHD/OG3K footer passed.
    - after a battery-out cold boot, the camera operator compared
      real FHD and OG3K at 29.97p, 180 degrees, in idle live view;
      the earlier exposure mismatch no longer appeared. This is a
      provisional visual pass, not an exact shutter readback.

  Offline release checks passed: all 749 OpenGate words, all 360
  selected UI records, hook order, D-cache -> I-cache publication,
  and release/debug section equivalence with the USB shell absent.

----------------------------------------------------------------
WHAT IS NOT VERIFIED — THIS IS AN ALPHA BUILD
----------------------------------------------------------------

  The exact no-shell pair in this folder is structurally identical
  to the product payload in its paired debug build; the only VSHL
  section removed is the USB worker. This exact pair has not itself
  had a camera cold-boot run.

  Specific to the new 8/10-bit support:

    - in-camera PLAYBACK of 8-bit and 10-bit OG3K clips. The
      playback path splits on the same bit-depth field and its
      OG3K guards were not extended. Expect this to be broken.
    - highlight headroom at 8-bit and 10-bit. The gain dispatch
      chooses its state by bit depth, and the OG3K gain hook still
      answers unconditionally. 12-bit is unaffected and verified.
    - a still photo taken while OG3K is selected, to confirm the
      borrowed photo profile is still clean.

  Also still unverified from v0.2.1a:

    - exact shutter readback and idle checks at the other frame rates
    - CINE/STILL transition while OG3K remains selected
    - sustained recording on sufficiently fast media
    - playback with the native v0.2 UI runtime
    - inactive screen/style variants
    - warm restart and hot reinstall

  One earlier OG3K attempt with the UI debug build froze after
  creating a clip. Later one-second OG3K attempts did not
  reproduce it. Treat every take as disposable until checked.

----------------------------------------------------------------
MEDIA SPEED
----------------------------------------------------------------

  Using the recorder's own per-frame size, OG3K at 24p writes about
  221 MB/s at 12-bit, 184 MB/s at 10-bit and 148 MB/s at 8-bit. The
  UHS-II SD card used for testing measured about 94 MB/s. A card
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
