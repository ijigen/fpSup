================================================================
 fpsup-usbshell  v3.1.0
 SIGMA fp — the shell that answers `shl` over USB
================================================================

WHAT IT IS

  A debug channel into the running camera. Copy AutoRun.txt and
  VSHL.BIN to the root of the SD card; with the camera attached
  over USB, the host can send any of the firmware's own 77 shell
  commands and read the answer back.

  It is parasitic on the camera's own PTP gadget -- the firmware
  keeps owning the endpoints and re-creates them after a
  record-mode reconfiguration, which is why recording survives
  having the shell attached.

  **Firmware Ver.5.02 only.** RAM only: delete AutoRun.txt, pull
  the battery, and the camera is stock. Nothing is written to flash.

ENDPOINTS

  EP 0x01  OUT   host -> camera   commands
  EP 0x82  IN    camera -> host   replies
  EP 0x83  IN    camera -> host   bulk push, opened by this build

DO NOT

  - Do not send a command while the camera is recording.
  - Do not leave it on a card you are shooting with. It is a
    development tool, not something to record through.
