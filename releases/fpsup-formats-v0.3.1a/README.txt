================================================================
 fpSup-Formats  fpsup-formats-v0.3.1a
 SIGMA fp -- six resolutions in one menu: Super 16 crop and
 3.5K open gate next to the stock and OG rows
================================================================

  Firmware Ver.5.02 only.  RAM only: delete AutoRun.txt, remove the
  battery, and the camera is stock.  Nothing is written to flash.

  Only AutoRun.txt and fpSup.BIN go on the SD card, in the root.
  Boot WITHOUT the USB cable attached.

  This version replaces fpsup-formats-v0.3.0a (2026-09-28): same six
  rows, three fixes (first frame of OG3.5K and S16, playback size
  numbers).  History: CHANGELOG.txt.

WHAT IT IS

  The Resolution menu gets six rows:

     UHD   FHD   S16   OG2K   OG3K   OG3.5K

  - UHD and FHD are the camera's own, untouched (Crop Mode included).
  - S16 is a Super 16 crop: 2112x1250 photosites read 1:1, no
    binning, no scaling (12.55 x 7.43 mm, crop factor 2.87), DNG
    crop 2096x1238.  The live view shows the crop in standby too.
  - OG2K and OG3K are the binned 3:2 open gates of the fpSup-OG2K and
    fpSup-OG3K cards, on the same card.
  - OG3.5K reads EVERY photosite of the 3:2 area and lets the ISP
    scale it by 1.75: more detail and less aliasing than binning,
    more rolling shutter (25 ms).  Its live view is the stock UHD
    one (hardware-binned), fluid, no reframing when REC starts.

  All six rows record CinemaDNG at 12-bit (8/10-bit: see below) and
  the LCD shows the right picture in standby and while recording.
  Settings and Quick Set show the six choices with native UI.

  row     sensor readout                    stored     DNG crop   fps           MB/s 12b 24p
  ------  --------------------------------  ---------  ---------  ------------  ------------
  UHD     stock                             3856x2170  3840x2160  stock         301
  FHD     stock                             1936x1090  1920x1080  stock         stock
  S16     2112x1250 window, 1:1             2112x1250  2096x1238  23.98..29.97   95
  OG2K    6048x4032 binned 3x3              2016x1344  2000x1334  23.98..100     98
  OG3K    6064x4024 binned 2x2              3024x2010  3008x2000  23.98..59.94  219
  OG3.5K  6062x4032 every photosite, /1.75  3464x2304  3456x2304  23.98..29.97  290

  Rolling shutter: S16 25 ms (the full readout still runs; the crop
  is the ISP's), OG2K 8.3 ms, OG3K 12.4 ms, OG3.5K 25 ms.

----------------------------------------------------------------
NEW SINCE v0.3.0a  (2026-10-01)
----------------------------------------------------------------

  - OG3.5K: the first frame of about 70 % of takes had one extra
    line on top and the Bayer rows swapped (magenta in playback).
    Cause: 4040 rows / 1.75 = 2308.57 lines.  The window is now
    6062x4032 (2304 lines exactly); raster 3464x2304, DNG crop
    3456x2304.  Measured: 23 of 23 takes clean.
  - S16: the first frame of every take was NOT a frame of that take
    but whatever the recorder's buffer held before (white after a
    cold boot, a frame of another format after switching rows, the
    previous take otherwise).  Two causes, two fixes: the centred
    crop's row margin was odd (window now 2112x1250, margin 1396),
    and the DNG recorder replaces the DMA address 6.5 ms after each
    vertical sync while S16's first active line arrives 8.6 ms
    after it, so frame 1 landed one buffer ahead of the one written
    to the file.  The card now skips the first address replacement
    of each S16 take.  Measured: 5 of 5 takes clean right after a
    cold boot, after OG3.5K, after FHD and back to back; the old
    build failed every one of those.  Details: docs/firmware/
    GRABACION_CINEMADNG.md in the source repo.
  - Playback header: the "W x H" numbers for S16, OG2K's 1334 and
    OG3.5K drew garbage (the firmware has one image per stock
    number).  The card now carries the five missing numbers, drawn
    without the stock outline (the resource cave has no room for
    it).
  - The Resolution menu text reads "OG3.5K 3456x2304".
  - S16: the focus magnifier kept the whole frame around the
    magnified area; it now keeps the S16 crop (the magnifier draws
    through two live-view profiles of its own, 4x and 8x).

----------------------------------------------------------------
NEW SINCE v0.1.0a  (v0.3.0a, 2026-09-28)
----------------------------------------------------------------

  Formats
  - S16 and OG3.5K are new.  FHD+, 3K+, OG2K+ and OG3K+ are gone:
    OG3.5K replaces OG3K+ with a better live view, the others did
    not earn their place (SSD-only, or aliasing on the /3 rows).
  - OG3.5K goes through the stock UHD video profile: the live view is
    hardware-binned like UHD's, the recording is the ISP's /1.75.
    The DNG crop is centred by the camera ((raster - crop) / 2).

  Menu
  - Frame rates a row cannot record are greyed in the popup and in
    Quick Set, and the stored rate is kept (OG3K at 50 -> OG3.5K
    reads 29.97 -> OG3K reads 50).  OG2K tops at 100 and OG3K at
    59.94: 119.88 is greyed on both (selecting it recorded stock
    UHD30 through the firmware's error path).
  - Crop Mode is greyed and effectively OFF on the four new rows,
    stored value kept.
  - After a battery pull the card applies the saved row itself
    (~20 s after loading) and refreshes the display.

  Loader
  - Built on fpSup's shared loader of 2026-09-25: every firmware
    word the card changes is journaled at load and written back at
    power-off, so the camera powers off stock.  No USB shell.
  - Combines on the fpSup-Merge page with fpSup-Gyro, Gyro-Base, the
    shell and Fast Start 2 (checked on the page; not booted).  Not
    with fpSup-OG3K or fpSup-OG2K: this card already contains them.

----------------------------------------------------------------
INSTALL
----------------------------------------------------------------

  1. Confirm the camera is a SIGMA fp on firmware Ver.5.02.
  2. Power off, REMOVE THE BATTERY, and put the card in a reader.
  3. Copy AutoRun.txt and fpSup.BIN to the ROOT of the SD card.
  4. Insert the card and power on, USB cable unplugged.  Wait for
     the progress bar and the final message:  fpSup-Fmt-v0.3.1a!
  5. Recording format CinemaDNG.  Select a row from MENU ->
     recording -> resolution, or from Quick Set -> RES.  Choose the
     frame rate and the CinemaDNG quality normally.

  To remove: delete AutoRun.txt, power off, remove the battery, and
  power on.

  If the camera freezes: remove the card, take the battery out with
  the USB cable unplugged, and boot.  Switching it off and on is not
  enough after a freeze.

----------------------------------------------------------------
MEDIA SPEED  (measured with a Samsung T5 over USB-C, 2026-09-28)
----------------------------------------------------------------

  The camera never dropped a frame in any test: it records cleanly
  until its buffer (about 400-470 MB) is full, then stops the take.
  What decides is the drive's SUSTAINED write rate once its cache is
  full and it is warm, not the number on the box.

     format  bits  fps    MB/s   Samsung T5
     OG3K     8    100    616    2 s
     OG3K     8    59.94  369    42 s
     OG3K     8    50     308    58 s OK
     OG3K    10    50/48  384    23-30 s
     OG3K    10    29.97  230    OK
     OG3K    12    29.97  276    OK
     OG3.5K  12    29.97  362    81 s cold, 12-17 s warm
     OG3.5K  12    25     302    ~2 min
     OG3.5K  12    24     290    2m45 + 1m36 OK (fresh drive)

  Rule of thumb for a T5: about 275 MB/s sustained.  OG3.5K 12-bit
  at 24/25p works on a fresh, cool drive; 29.97 does not.  8-bit
  OG3.5K (192-240 MB/s) fits.  S16 and OG2K fit a fast SD card at
  24p; OG3K and OG3.5K need an SSD.  Rates are not limited by this
  card for bandwidth reasons: measure your own drive.

----------------------------------------------------------------
WHAT HAS BEEN VERIFIED
----------------------------------------------------------------

  On one SIGMA fp, Ver.5.02, 2026-10-01, on the test card ff9 whose
  fpSup.BIN is byte for byte this one (AutoRun.txt differs only in
  the banner), to the SD card:

    - S16: first frame fresh and correct after a cold boot, after an
      OG3.5K take, twice back to back and after an FHD take (clips
      A001_605, 609, 610, 611, 613), camera moved between takes;
      Bayer phase and data width right on every frame
    - OG3.5K: 3464x2304, crop 3456x2304 at (4,0), first frame equal
      to the second (clips 606-608; 20 earlier takes on the same
      window, 0 bad)
    - FHD unchanged (clip 612); playback header numbers drawn for
      S16, OG2K and OG3.5K (user, by eye)

  And on 2026-09-27/28 on the v0.3.0a candidates, which this build
  changes only in the geometry above and the first-frame hook:

    - the six-row menu, closed-row texts, Quick Set tiles, the
      six-label strip with the cursor on the selected row
    - S16: standby live view cropped and centred; no drops
    - OG3.5K: live view fluid and complete while recording; no drops
    - OG2K 2016x1344 and OG3K 3024x2010 clips, OG2K sustained at
      100 fps 12-bit
    - frame rates greyed per row with the SSD mounted; 119.88 greyed
      on OG2K/OG3K; the stored rate kept across rows
    - crop greyed/off on the new rows; UHD with crop ON comes back ON
    - switching rows in Quick Set updates the live view

  Offline: fpSup-Merge page checks pass alone and with Gyro,
  Gyro-Base, Shell and Fast Start 2; stage2 identical to
  fpsup-og3k-v0.2.6a's.

  Final validation on THIS EXACT FILE: see MANIFEST.txt, camera log.

----------------------------------------------------------------
WHAT IS NOT VERIFIED -- THIS IS AN ALPHA BUILD
----------------------------------------------------------------

  - 8-bit and 10-bit CinemaDNG on S16 and OG3.5K (OG2K/OG3K: as
    the fpSup-OG2K/OG3K releases).  A 10-bit OG2K take at 119.88
    fell back to stock UHD30 -- that rate is now greyed.
  - In-camera playback of S16 and OG3.5K clips: by eye only.
  - MOV with a new row selected; a still photo with a new row
    selected.
  - The S16 first-frame fix on a long series: 5 takes measured, the
    30-take series is still owed.  If a first frame ever comes out
    wrong again, keep the clip and report it.
  - Ten boot / power-off cycles on the final file: MANIFEST camera
    log.

  Known, and not fixed here:

  - Switching in Quick Set between a 3:2 row and a 16:9 row (or to
    or from S16) shows a one-frame Super35-crop flash: the card has
    to toggle the crop to make the camera rebuild the live view
    inside Quick Set.  Between OG2K, OG3K and OG3.5K there is none.
  - S16 stays at 29.97: the sensor timing cannot shrink below the
    full readout (48 fps froze the camera on a probe; a real sensor
    window for S16 is under study and is not in this build).
  - S16: the focus magnifier's 4x and 8x levels look the same (the
    background keeps the S16 crop at both).
  - OG3.5K in standby previews through the hardware binning: the
    standby picture is the whole 3:2 frame, as in OG3K.

----------------------------------------------------------------
HOW IT WORKS, IN SHORT
----------------------------------------------------------------

  The firmware describes each video mode in one row of a parameter
  table plus one timing row per sensor mode.  The card adds no rows:
  while a new menu row is selected it BORROWS an existing profile's
  row (the 1:1 video profile for S16 and OG2K, the UHD 12-bit profile
  for OG3.5K, OG3K's own) and writes the window, the ISP ratios, the
  preview and the output sizes; leaving the row puts the stock
  values back.  A hook in the format picker supplies the sensor
  timing for the current frame rate; a hook in the canvas builder
  sets the stored raster, the DNG crop and the pixel format every
  frame, and in standby the S16 crop.  The menu is the camera's own,
  with its list extended to six rows.

----------------------------------------------------------------
WITH THANKS
----------------------------------------------------------------

  Bei (ijigen) for fpSup: the loader, the OG2K / OG3K open gates
  this card grew out of, the menu runtime, and the build rules.
  Vitaly Li got open gate out of a SIGMA fp first.
