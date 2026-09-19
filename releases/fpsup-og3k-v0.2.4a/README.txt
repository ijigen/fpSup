================================================================
 OG3K  fpsup-og3k-v0.2.4a
 SIGMA fp — 3:2 open gate, native UI, 8/10/12-bit CinemaDNG
================================================================

WHAT CHANGED SINCE v0.2.3a

  The recording core is unchanged -- the same 3,188 writes, the same
  sensor modes, the same native UI.  What changed is the card around
  it.  The payload container is fpSup.BIN, the AutoRun is 103
  commands instead of 135, and the card is built on the entry
  contract the rest of the tree now uses: a payload is called once
  and asks the allocator for whatever memory it needs, instead of
  reading a pointer the script used to leave behind for it.

  Measured on the camera, 2026-09-19: 3024 x 2010, 12-bit, sensor
  mode 98, on a card that also carried the gyro logger and the USB
  shell.

  KNOWN, AND NOT FIXED HERE.  If you run the gyro logger on the same
  card, the `.json` it writes beside an OG3K take carries the FHD
  frame size, not this one -- 1936 x 1090 where the DNG is 3024 x
  2010.  The sensor mode and the rolling shutter figure in it are
  correct.  OG3K does not update the settings word the profile
  generator reads, and that is where the fix belongs; until it
  lands, correct the two dimensions by hand in Gyroflow.

WHAT IT IS

  The sensor's whole 3:2 area recorded as CinemaDNG instead of the
  16:9 window the camera normally crops to:

     3024 x 2010 stored RAW matrix · 3:2 · 8, 10 or 12-bit
     DNG default crop 3008 x 2000 at (8, 5)

  This is the IMX410's native 2x2-binned 3032 x 2012 readout, not
  a 6064 x 4042 image downscaled by the ISP. Eight frame rates are
  available from 23.976 through 100 fps. The 12-bit path uses the
  native CinemaDNG gain path at every ISO, fixed in v0.1.1test;
  8/10-bit highlight headroom is not yet verified.

  Native OG3K choices appear in Settings and Quick Set, including
  the UHD/FHD/OG3K three-choice footer.

  **Firmware Ver.5.02 only.** RAM only: delete AutoRun.txt, remove
  the battery, and the camera is stock. Nothing is written to flash.

----------------------------------------------------------------
NEW IN v0.2.3a — SAFE FORMAT-TABLE PASS-THROUGH
----------------------------------------------------------------

  v0.2.2a used r1 as a temporary bit-depth register inside the
  format-table hook. r1 is also the factory lookup's table pointer.
  When a non-OG3K FHD/UHD key passed back to the factory lookup, the
  pointer could therefore be 0, 3 or 4 instead of the original table.

  v0.2.3a keeps the bit depth in preserved register r5 and adds a
  build-time guard against writing r1 before the factory pass-through.
  The shutter-angle code and every other functional payload are
  unchanged. Compared with public v0.2.2a, fpSup.BIN differs in exactly
  seven 32-bit words, all inside this one fmttable fix.

  The exact no-shell fpSup.BIN in this folder was cold-booted on a
  SIGMA fp. Every DNG in three 25 fps / 180-degree clips was checked:

     OG3K  45/45 frames  12-bit  3024x2010  25.000 fps  1/50 s
     UHD   20/20 frames   8-bit  3856x2170  25.000 fps  1/50 s
     FHD   35/35 frames  12-bit  1936x1090  25.000 fps  1/50 s

  All 100 frames also carried the expected default crop and no
  metadata outliers. This validates the reported 25p/180-degree case;
  it is not a claim that every possible source of lighting flicker is
  fixed.

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
  3. Copy AutoRun.txt and fpSup.BIN to the ROOT of the SD card.
  4. Insert the card and power on. Wait for the progress bar and
     the final message: fpSup-OG3K-v0.2.4a!
  5. Turn Super35 / crop OFF. OG3K cannot create a clip while it is on.
  6. Select OG3K from MENU -> recording -> resolution, or from
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

  New in v0.2.3a, on the exact no-shell fpSup.BIN after a battery-out
  cold boot:

    - OG3K, UHD and FHD all recorded at 25.000 fps and 1/50 second
      with shutter angle 180 degrees.
    - all 100 DNG frames were checked, not only representative frames.
    - OG3K was 3024x2010 / crop 3008x2000; UHD was 3856x2170 /
      crop 3840x2160; FHD was 1936x1090 / crop 1920x1080.
    - the tested paths covered 12-bit OG3K/FHD and 8-bit UHD.

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

  Reproducibility boundary: the research worktree moved on to
  post-freeze canvas experiments after this camera-tested artifact was
  frozen. Do not rebuild from that mutable tree and substitute the
  result for this release. From the repository root, verify this exact
  artifact with:

    python3 tools/release-audits/verify_og3k_v0_2_3a.py

  That audit checks the immutable hashes, no-shell section shape,
  current-card copies, and the exact seven-word v0.2.2a -> v0.2.3a
  allowlist independently of the later source state.

----------------------------------------------------------------
WHAT IS NOT VERIFIED — THIS IS AN ALPHA BUILD
----------------------------------------------------------------

  The final AutoRun.txt differs from the camera-tested RC only in its
  printable version banner and padding; its 135 functional commands
  are identical. fpSup.BIN is byte-for-byte the camera-tested binary.

  IMPORTANT: turn Super35 / crop OFF before selecting OG3K. OG3K with
  crop enabled cannot resolve a valid format key and does not create a
  clip. This limitation predates v0.2.3a and is not changed here.

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

    - exact shutter readback and idle checks at frame rates other than 25p
    - the 25p pass-through test at 10-bit
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
  fpSup.BIN      OpenGate recording core plus native UI runtime
  MANIFEST.txt  exact hashes, memory map, and verification boundary
  README.txt    this file

  Only AutoRun.txt and fpSup.BIN go on the SD card.
  Combined versions are generated only by the web card composer.
