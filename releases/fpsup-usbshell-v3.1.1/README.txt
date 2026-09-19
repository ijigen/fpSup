================================================================
 fpsup-usbshell  v3.1.1
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

WHAT CHANGED SINCE v3.1.0

  The worker no longer lives in the cave. It runs where the file
  lands, asks the allocator for memory of its own and copies
  itself into it, so it neither reserves a fixed address nor
  shares one with anything else -- which is what lets this card be
  combined with a payload that wants the cave for its own code.

  The payload container is fpSup.BIN. v3.1.0 and everything before
  it named it VSHL.BIN; the two files of a card always travel
  together, so use whichever pair you downloaded and do not mix
  them.

  The AutoRun is 103 commands, down from 195: the descriptor
  patches and the worker's sixteen state words used to be spelled
  out one `mem set` at a time and are sections in the file now.

  `shl` is unchanged. Anything written against v3.1.0 works.

ENDPOINTS

  EP 0x01  OUT   host -> camera   commands
  EP 0x82  IN    camera -> host   replies
  EP 0x83  IN    camera -> host   bulk push, opened by this build

DO NOT

  - Do not send a command while the camera is recording.
  - Do not leave it on a card you are shooting with. It is a
    development tool, not something to record through.
