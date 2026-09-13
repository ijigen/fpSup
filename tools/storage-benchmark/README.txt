================================================================
 SIGMA fp -- storage write-speed test                      v1
================================================================

WHAT IT IS

  An SD card that makes the camera measure how fast it can write to
  your SD card, and optionally to an external SSD, and save the
  numbers to a text file.

WHY IT MATTERS

  CinemaDNG recording on the fp is limited by write speed long before
  it is limited by anything else.  Every frame is a whole file:

     FHD   1936 x 1090  12-bit    3.24 MB/frame    97 MB/s
     UHD   3856 x 2170   8-bit    8.45 MB/frame   253 MB/s
     UHD   3856 x 2170  12-bit   12.63 MB/frame   379 MB/s

  If the medium cannot sustain that, the camera buffers in RAM and
  then stops the take when the buffer fills.  That is not a bug and
  not a firmware limit -- it is the card.

  Card-reader benchmarks do not answer this.  They measure your
  computer's reader, not the camera's SD controller, and they report
  burst speed rather than sustained.  This measures the camera's own
  path with the camera's own driver.

----------------------------------------------------------------
IS IT SAFE
----------------------------------------------------------------

  This card runs ONLY commands that already exist in the camera's
  firmware.  You can read the whole thing -- AutoRun.txt is plain
  text and every line is a command.

  It does NOT write to memory.        (no `mem set` anywhere)
  It does NOT patch any code.
  It does NOT touch flash or firmware.
  It does NOT depend on a firmware version.

  That last point matters.  Cards that patch memory are tied to one
  exact firmware build, and running one on a different version writes
  into whatever happens to be at that address.  This card contains no
  addresses at all, so there is nothing to mismatch.

  To undo it: delete or rename AutoRun.txt.  That is the whole
  uninstall.  Nothing persists across a power cycle.

  What it DOES do:
    - creates \test.txt, up to 200 MB, on each volume it tests
    - creates \FPSPEED.TXT on the SD card (the results)
    Delete both when you are done.

  What it needs:
    - about 250 MB free on each volume you want tested
    - DO NOT press record while this card is in.  The benchmark
      borrows the same memory pool the movie recorder uses.

----------------------------------------------------------------
HOW TO RUN IT
----------------------------------------------------------------

  1. Copy AutoRun.txt to the ROOT of the SD card you want to test.
     (Back up your own AutoRun.txt first if you have one.)

  2. SD card in, SSD NOT connected.  Switch the camera on.

  3. The monitor shows progress.  The SD card test runs first and
     takes about 30 seconds.

  4. Then it shows "PLUG SSD NOW" and counts down 20 seconds.
       - If you want to test an SSD, plug it into the USB-C port now.
       - If you do not have one, just wait.  The SSD lines will
         report an error and the run finishes normally.

  5. When it shows "DONE - FPSPEED.TXT", switch off and read
     FPSPEED.TXT from the SD card.

  6. Delete AutoRun.txt, \test.txt and \FPSPEED.TXT, and put your own
     AutoRun.txt back if you had one.

  The camera is unresponsive while this runs -- that is the test, not
  a crash.  Total time is about 60-90 seconds.

----------------------------------------------------------------
HOW TO READ THE RESULTS
----------------------------------------------------------------

  FPSPEED.TXT begins with the camera identifying itself:

     model      = ...        which body
     rel_version= ...        which firmware
     git_hash   = ...

  then, for each volume, capacity and cluster/AU layout, then for
  each block size:

     test3 bufferSize = 50000000
     loop   = 0  write ok    128648[us] 388.6574[MB/sec]
     loop   = 0  read  ok    130453[us] 383.2798[MB/sec]

  MB/sec here is decimal (bytes per microsecond), the same unit as
  the frame rates in the table above, so you can compare directly.

  Ignore loop 0 of each block size -- it includes creating the file.
  Loops 1 and 2 are the real numbers.

  Larger block sizes are usually faster.  That is worth knowing: a
  camera that writes one file per frame is operating at the small
  end of that curve.

----------------------------------------------------------------
FOR REFERENCE -- what we measured
----------------------------------------------------------------

  SIGMA fp, firmware 5.02

    SD card, 128 GB UHS-II (a slow one)
       10 MB blocks    write  66   read 131
       50 MB blocks    write  94   read 218

    External SSD, 2 TB, over USB-C
       10 MB blocks    write 328   read 349
       50 MB blocks    write 390   read 390
      100 MB blocks    write 393   read 400

  Two observations from that:

    - The SSD flattens at about 390-400 MB/s in both directions.
      That is the USB 3.0 Gen1 bus, not the drive -- a different
      enclosure with the same drive gave 363.  A faster drive will
      not help; a better bridge chip might give a few percent.

    - The SD card at 94 MB/s is right at the FHD 12-bit requirement
      of 97 MB/s.  It records FHD only because the RAM buffer covers
      the 3% shortfall.  Anything larger stops within seconds.

----------------------------------------------------------------
WHAT WOULD BE USEFUL TO SEND BACK
----------------------------------------------------------------

  The whole FPSPEED.TXT, plus:
    - the exact model of the SD card
    - the exact model of the SSD AND its enclosure, if tested

  The enclosure matters as much as the drive.  We measured a 7%
  difference between two enclosures holding the same SSD, and the
  gap was 43% at the block sizes that actually correspond to one
  video frame.

================================================================
