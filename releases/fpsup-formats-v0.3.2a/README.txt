================================================================
 fpSup-Formats  fpsup-formats-v0.3.2a
 SIGMA fp -- six resolutions in one menu: Super 16 (a real sensor
 window, up to 100 fps) and 3.5K open gate next to the stock and
 OG rows
================================================================

  Firmware Ver.5.02 only.  RAM only: delete AutoRun.txt, remove the
  battery, and the camera is stock.  Nothing is written to flash.

  Only AutoRun.txt and fpSup.BIN go on the SD card, in the root.
  Boot WITHOUT the USB cable attached.

  This version replaces fpsup-formats-v0.3.1a (2026-10-01): S16 reads
  a real sensor window and records up to 100 fps, the card boots in
  seconds, and it composes with fpSup-Lossless.  History:
  CHANGELOG.txt.

WHAT IT IS

  The Resolution menu gets six rows:

     UHD   FHD   S16   OG2K   OG3K   OG3.5K

  - UHD and FHD are the camera's own, untouched (Crop Mode included).
  - S16 is a Super 16 crop: 2112x1250 photosites read 1:1, no
    binning, no scaling (12.55 x 7.43 mm, crop factor 2.87), DNG
    crop 2096x1238.  The sensor itself reads only those rows, which is
    what lets the row record at 23.98 .. 59.94 and 100 fps.  The live view shows the crop in standby and in the focus
    magnifier.
  - OG2K and OG3K are the binned 3:2 open gates of the fpSup-OG2K and
    fpSup-OG3K cards, on the same card.
  - OG3.5K reads EVERY photosite of the 3:2 area and lets the ISP
    scale it by 1.75: more detail and less aliasing than binning,
    more rolling shutter (25 ms).  Its live view is the stock UHD
    one (hardware-binned), fluid, no reframing when REC starts.

  All six rows record CinemaDNG at 8/10/12-bit and the LCD shows the
  right picture in standby and while recording.  Settings and Quick
  Set show the six choices with native UI.

  row     sensor readout                    stored     DNG crop   fps                 MB/s 12-bit
  ------  --------------------------------  ---------  ---------  ------------------  ------------------
  UHD     stock                             3856x2170  3840x2160  stock               301 @24
  FHD     stock                             1936x1090  1920x1080  stock               stock
  S16     2112x1250 sensor window, 1:1      2112x1250  2096x1238  23.98..59.94, 100   95 @24, 396 @100
  OG2K    6048x4032 binned 3x3              2016x1344  2000x1334  23.98..100          98 @24
  OG3K    6064x4024 binned 2x2              3024x2010  3008x2000  23.98..59.94        219 @24
  OG3.5K  6062x4032 every photosite, /1.75  3464x2304  3456x2304  23.98..29.97        290 @24

  Rolling shutter (from the sensor timing, not yet measured with a
  light bar): S16 7.7 ms across its 1250 rows, OG2K 8.3 ms, OG3K
  12.4 ms, OG3.5K 25 ms.  v0.3.1a's README said 25 ms for S16: that
  was the full-frame time; the skew across the crop was 7.7 ms there
  too, since rows are read in sequence.

----------------------------------------------------------------
NEW SINCE v0.3.1a  (2026-10-03)
----------------------------------------------------------------

  - S16 reads a real sensor window.  The IMX410 is programmed the way
    the firmware programs its own windowed modes (register block,
    timing crop, size, AE-grid, digital-clamp and defect rows for
    2112x1250, on a sensor mode no stock path uses).  The frame time
    drops from 25 ms to the 7.7 ms of the crop alone, which is what
    makes rates above 60 possible.  Measured on the camera: 23.98..29.97,
    48/50/59.94 and 100 fps, first frame right every time.  The
    first-frame DMA skip of v0.3.1a is no longer needed and is off.
  - S16 frame rates 48, 50, 59.94 and 100.  119.88 is NOT offered:
    the sensor needs 71..80 blanking rows in this mode and 119.88
    leaves 59 (the camera froze; a live sweep put the limit between
    118 and 119 fps).  100 fps at 12-bit is 396 MB/s: SSD, and the
    take stops when the buffer is full (see MEDIA SPEED).
  - Frame rate of the four added rows: the row's own ceiling is the
    effective maximum whatever the media or bit depth.  The stock
    firmware caps 12-bit at 59.94 on SD and when the SSD is not the
    write target; on a slow medium a fast take simply stops when the
    buffer is full.
  - Focus magnifier in S16: 4x behaves like 8x (the two looked the
    same); the S16 crop stays in the background in both.
  - Boot in a few seconds instead of ~35: AutoRun.txt is 3.4 KB.  The
    camera's script reader sleeps 1 ms per character it reads,
    comments included (spotted on the fpSup Discord), and the old
    file carried 29 KB of comments; the new one also switches that
    pacing off while it loads and restores it at the end.
  - Composes with fpSup-Lossless: the UI runtime accepts the shared
    string pool a uishare Sup installs (Bei's "menus by addition"),
    so the Resolution summary and the Quick Set tiles survive next to
    Lossless, RAW-View v0.2.3 and OG v0.2.8.
  - Loader and stage2 from ijigen/fpSup 756244a (2026-10-03).

----------------------------------------------------------------
INSTALL
----------------------------------------------------------------

  1. Confirm the camera is a SIGMA fp on firmware Ver.5.02.
  2. Power off, REMOVE THE BATTERY, and put the card in a reader.
  3. Copy AutoRun.txt and fpSup.BIN to the ROOT of the SD card.
  4. Insert the card and power on, USB cable unplugged.  Wait for
     the progress bar and the final message:  fpSup-Fmt-v0.3.2a!
  5. Recording format CinemaDNG.  Select a row from MENU ->
     recording -> resolution, or from Quick Set -> RES.  Choose the
     frame rate and the CinemaDNG quality normally.

  To remove: delete AutoRun.txt, power off, remove the battery, and
  power on.

  If the camera freezes: remove the card, take the battery out with
  the USB cable unplugged, and boot.  Switching it off and on is not
  enough after a freeze.

----------------------------------------------------------------
COMBINING  (fpSup-Merge)
----------------------------------------------------------------

  Upload fpSup.BIN on the fpSup-Merge page with "Add a .BIN" and tick
  what you want next to it: fpSup-Gyro, Gyro-Base, RAW-View
  (v0.2.3test), Lossless (v0.1.2test), the shell, Fast Start 2.  Every
  combination passes the page's checks (2026-10-03).  Not with
  fpSup-OG3K or fpSup-OG2K: this card already contains them.

  A ready-made card with Gyro v1.14.0 + RAW-View v0.2.3test +
  Lossless v0.1.2test is published next to this one
  (fpsup-formats-v0.3.2a-gyro-rawview-lossless): booted and used on
  the author's camera; Lossless RAW row in SHOOT page 2, gyro data,
  RAW-View, S16 clips mostly compressed.

  Lossless on S16 (12-bit): at 29.97 fps 126 of 127 frames came out
  lossless-JPEG at 0.234x (123 MB instead of 513 MB, 0.24x); at 100
  fps 43 of 97 (average 0.66x), which is what makes the rate
  sustainable: on the author's SSD (not the T5) an uncompressed 100 fps
  take ran up to 30 s, and with Lossless on it recorded without
  stopping.  At 48 fps on an SD card a take ran 23 s, at 30 fps
  continuously.

  One combination does not work: with fpSup-Gyro on the card, S16 at
  100 fps fails.  Bisected on the camera with four cards carrying the
  same Formats payload (alone, +Lossless, +Lossless+RAW-View,
  +Lossless+RAW-View+Gyro): only the one with Gyro fails, and the one
  without it recorded at 100 fps without stopping.  Lower rates with
  Gyro are fine.  Reported upstream.

----------------------------------------------------------------
MEDIA SPEED  (Samsung T5 over USB-C unless noted)
----------------------------------------------------------------

  The camera records cleanly until its buffer (about 325-470 MB) is
  full, then stops the take.  What decides is the drive's SUSTAINED
  write rate once its cache is full and it is warm.

     format  bits  fps    MB/s   result
     S16     12    100    396    2.8 s and 14 s takes on the T5 (uncompressed)
     S16     12    59.94  237    not yet timed
     OG3K     8    100    616    2 s
     OG3K     8    59.94  369    42 s
     OG3K     8    50     308    58 s OK
     OG3K    10    50/48  384    23-30 s
     OG3K    10    29.97  230    OK
     OG3K    12    29.97  276    OK
     OG3.5K  12    29.97  362    81 s cold, 12-17 s warm

----------------------------------------------------------------
NOT VERIFIED
----------------------------------------------------------------

  - S16 30-take series; light-bar rolling-shutter measurement (7.7 ms
    is from the sensor timing); where exactly Gyro stops keeping up
    with S16 (59.94 not tested).
