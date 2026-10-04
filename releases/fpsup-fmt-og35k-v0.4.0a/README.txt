================================================================
 fpSup-Formats-OG3.5K  fpsup-fmt-og35k-v0.4.0a
 SIGMA fp -- Open Gate 3.5K as its own sup
================================================================

  Firmware Ver.5.02 only.  RAM only: delete AutoRun.txt, remove the
  battery, and the camera is stock.  Nothing is written to flash.
  Test build.

WHAT IT IS

  One of the four fpSup-Formats packages:

     fpSup-Formats-S16   fpSup-Formats-OG2K
     fpSup-Formats-OG3K  fpSup-Formats-OG3.5K

  OG3.5K: the whole 3:2 sensor read 1:1 and scaled by the ISP,
  DNG 3456x2304.  23.98 .. 29.97 fps; needs an external SSD.

  Put any of the four on one card -- alone, two, three or all four --
  with or without Gyro, RAW-View and Lossless.  The Resolution menu
  shows the stock UHD and FHD plus exactly the formats on the card,
  in Settings and in Quick Set.  Frame rates, bit depths and the
  rates a format cannot record (greyed) travel with each format.

  Not with the older fpSup-OG2K / fpSup-OG3K cards (they take the same
  menu slot) nor with fpSup-Formats-All v0.3.2a (it contains all four).

HOW IT COMBINES

  Every package carries the same core (hooks, UI runtime, the tiles of
  all four formats) byte for byte; fpSup-Merge folds identical records,
  so the core is on the card once.  Each format's data sits in its own
  fixed slot.  The core's entry (0xC0730130) builds the menu at every
  load from the formats whose package left its mark this load: the
  registry lives in the loader's cave, which survives a power-switch
  restart, so a format left in RAM by an earlier card is not offered.

USE

  Compose on fpSup-Merge (tick one or more fpSup-Formats tiles) and copy
  what the zip holds to the root of the card, the FPSUPUI folder
  included.  This folder's AutoRun.txt + fpSup.BIN are the package
  alone (Bei's 756244a loader, short AutoRun).  Boot WITHOUT the USB
  cable attached.

VERIFIED

  Camera (2026-10-04): S16 + OG3.5K + Gyro + Lossless, and OG3K + Gyro
  composed on fpSup-Merge: the Resolution menu shows exactly those
  formats.  The four together leave memory byte for byte as
  fpSup-Formats-All v0.3.2a (camera-tested), except the picker loops
  that skip an empty slot.
  Host: all 15 combinations run in an emulator on the 5.02 image
  against a build made for that combination alone (menu, Quick Set
  records, tiles, row<->enum pairs, the picker at 8 rates x 3 bit
  depths, frame-rate limits), cold and after a warm restart; the
  fpSup-Merge checks pass in every combination with Gyro, RAW-View,
  Lossless and Fast Start.
  Not verified on the camera: the other combinations, a power-switch
  restart from another card (emulated only), a 30-take series.
