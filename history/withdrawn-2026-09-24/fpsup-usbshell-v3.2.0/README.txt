================================================================
 fpsup-usbshell  v3.2.0
 SIGMA fp — the shell that answers `shl` over USB
================================================================

WHAT IT IS

  A debug channel into the running camera. Copy AutoRun.txt and
  fpSup.BIN to the root of the SD card; with the camera attached
  over USB, the host can send any of the firmware's own 77 shell
  commands and read the answer back.

  It is parasitic on the camera's own PTP gadget -- the firmware
  keeps owning the endpoints and re-creates them after a
  record-mode reconfiguration, which is why recording survives
  having the shell attached.

  **Firmware Ver.5.02 only.** RAM only: delete AutoRun.txt, pull
  the battery, and the camera is stock. Nothing is written to flash.

WHAT CHANGED SINCE v3.1.1

  One section: stage2, the loader's second stage. Everything else
  -- the worker, the seven descriptor patches, the AutoRun's 103
  commands -- is byte for byte v3.1.1.

  The cave is handed out at boot now instead of being divided up
  by hand at build time. stage2 has always reset the bump pointer
  every boot; what changed is where it resets it TO. It was
  0xC072EC60, because the gyro logger's state words were named at
  fixed addresses below that and the arena had to start above
  them. They are fields of that payload's own blob in the pool as
  of fpGyroSup v1.13, so the arena is the whole payload window:

      0xC072E064..0xC072EFB4    3,920 bytes, one unbroken run
      before                      852 bytes, above the gyro's words

  A payload asks for what it needs with the bump pointer at
  0xC072E060 and gets an address nobody else can be holding. The
  host side asks the same word -- see fp_usb_shell/cave.py -- so a
  tool's scratch cannot land on a payload's code either.

  stage2 also stamps the microsecond clock at 0xC072F6F8 when the
  load finishes. `mem get 0xC072F6F8,,4` after a boot is power-on
  to load-complete with no host, no USB enumeration and no polling
  in the number.

  `shl` is unchanged. Anything written against v3.1.1 works, and
  the two files of a card still travel together.

ENDPOINTS

  EP 0x01  OUT   host -> camera   commands
  EP 0x82  IN    camera -> host   replies
  EP 0x83  IN    camera -> host   bulk push, opened by this build

DO NOT

  - Do not send a command while the camera is recording.
  - Do not leave it on a card you are shooting with. It is a
    development tool, not something to record through.
